"""
重新执行任务(reexecute)单元测试

隔离测试，使用临时 SQLite 数据库，不依赖真实数据库和服务器。
覆盖 Sills/db_email_task.py::reexecute_task 的状态校验与进度重置逻辑。
"""
import sqlite3
import contextlib
import pytest
from Sills import db_email_task


# 仅保留 reexecute_task / get_task_by_id 用到的字段
SCHEMA = """
CREATE TABLE IF NOT EXISTS uni_email_task (
    task_id TEXT PRIMARY KEY,
    task_name TEXT NOT NULL,
    account_ids TEXT NOT NULL,
    group_ids TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    total_count INTEGER DEFAULT 0,
    sent_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,
    started_at DATETIME,
    cancel_requested INTEGER DEFAULT 0,
    error_message TEXT
);
"""


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    """临时数据库 + patch get_db_connection / get_task_all_contacts"""
    db_path = tmp_path / "test_reexecute.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()

    @contextlib.contextmanager
    def fake_get_db_connection():
        yield conn

    monkeypatch.setattr(db_email_task, "get_db_connection", fake_get_db_connection)
    # 临时库为 SQLite，强制返回 SQLite 兼容的时间表达式（生产中按 DB 模式自动切换）
    monkeypatch.setattr(db_email_task, "get_datetime_now", lambda: "datetime('now','localtime')")
    # 避免依赖联系人/组表，直接返回虚拟联系人列表
    monkeypatch.setattr(
        db_email_task, "get_task_all_contacts",
        lambda tid: [{"contact_id": "c1", "email": "a@b.com"}],
    )
    yield conn
    conn.close()


def _insert_task(conn, task_id, status, sent=5, failed=1, skipped=2):
    conn.execute(
        """INSERT INTO uni_email_task
           (task_id, task_name, account_ids, group_ids, subject, body,
            status, total_count, sent_count, failed_count, skipped_count,
            cancel_requested, error_message)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (task_id, "T", "[]", "[]", "s", "b", status, 10, sent, failed, skipped, 0, ""),
    )
    conn.commit()


def test_reexecute_completed_resets_progress(temp_db):
    """completed 任务重新执行：状态置 running，进度计数清零"""
    _insert_task(temp_db, "ET1", "completed", sent=8, failed=2, skipped=0)
    ok, msg = db_email_task.reexecute_task("ET1")
    assert ok is True
    row = temp_db.execute(
        "SELECT status, sent_count, failed_count, skipped_count, cancel_requested "
        "FROM uni_email_task WHERE task_id='ET1'"
    ).fetchone()
    assert row["status"] == "running"
    assert row["sent_count"] == 0
    assert row["failed_count"] == 0
    assert row["skipped_count"] == 0
    assert row["cancel_requested"] == 0


def test_reexecute_error_status(temp_db):
    """error 任务允许重新执行"""
    _insert_task(temp_db, "ET2", "error", sent=3, failed=4, skipped=1)
    ok, msg = db_email_task.reexecute_task("ET2")
    assert ok is True
    assert temp_db.execute(
        "SELECT status FROM uni_email_task WHERE task_id='ET2'"
    ).fetchone()["status"] == "running"


def test_reexecute_rejects_pending(temp_db):
    """pending 任务不允许重新执行"""
    _insert_task(temp_db, "ET3", "pending")
    ok, msg = db_email_task.reexecute_task("ET3")
    assert ok is False
    assert "已完成或执行错误" in msg


def test_reexecute_rejects_running(temp_db):
    """running 任务不允许重新执行"""
    _insert_task(temp_db, "ET4", "running")
    ok, msg = db_email_task.reexecute_task("ET4")
    assert ok is False


def test_reexecute_nonexistent(temp_db):
    """不存在的任务返回失败"""
    ok, msg = db_email_task.reexecute_task("NOPE")
    assert ok is False
    assert "不存在" in msg


def test_reexecute_no_contacts(temp_db, monkeypatch):
    """无可发送联系人时返回失败，且不改动任务状态"""
    _insert_task(temp_db, "ET5", "completed")
    monkeypatch.setattr(db_email_task, "get_task_all_contacts", lambda tid: [])
    ok, msg = db_email_task.reexecute_task("ET5")
    assert ok is False
    assert "没有可发送" in msg
    # 状态应保持 completed，未被改写
    assert temp_db.execute(
        "SELECT status FROM uni_email_task WHERE task_id='ET5'"
    ).fetchone()["status"] == "completed"


# ==================== Worker 跳过逻辑测试 ====================
# 验证 EmailSenderWorker.run() 在不同模式下对 7 天跳过规则的处理：
#   - reexecute + skip 开启：7 天内已发送邮箱跳过，7 天外的重发
#   - reexecute + skip 关闭：全部重发
#   - reexecute：本任务旧日志的已发送邮箱不按"当前任务已发送"跳过（交给 7 天规则）
#   - 普通模式：本任务已发送邮箱仍按"当前任务已发送"跳过（不破坏原行为）
from Sills import email_sender as _es
from Sills import db_email_log as _elog
from Sills.email_sender import EmailSenderWorker as _Worker


class _DummySMTPServer:
    """模拟 SMTP 连接对象，仅提供 run() 用到的 noop/quit 方法"""
    def noop(self):
        pass

    def quit(self):
        pass


def _build_worker(monkeypatch, *, reexecute_mode, skip_enabled, skip_days,
                  contacts, current_task_sent=(), recently_sent=(), sent_box):
    """构造一个全部外部依赖均已 mock 的 worker，调用 .run() 即可跑发送循环。

    sent_box: 传入一个空 list，run() 后内含实际"发送"的邮箱顺序。
    """
    # 模块级函数 mock（email_sender 顶部 from-import 进来的名字）
    monkeypatch.setattr(_es, "get_task_by_id", lambda tid: {
        "sent_count": 0, "failed_count": 0, "skipped_count": 0
    })
    monkeypatch.setattr(_es, "update_task_progress", lambda *a, **k: None)
    monkeypatch.setattr(_es, "is_cancel_requested", lambda tid: False)
    monkeypatch.setattr(_es, "can_send_today", lambda *a, **k: (True, 100))
    monkeypatch.setattr(_es, "increment_sent_count", lambda *a, **k: None)
    monkeypatch.setattr(_es, "add_log", lambda *a, **k: None)
    monkeypatch.setattr(_es, "update_contact_marketing_status", lambda *a, **k: None)
    monkeypatch.setattr(_es, "save_sent_email_to_mail", lambda *a, **k: None)
    monkeypatch.setattr(_es, "complete_task", lambda *a, **k: None)
    monkeypatch.setattr(_es, "error_task", lambda *a, **k: None)
    monkeypatch.setattr(_es.time, "sleep", lambda *a, **k: None)
    # run() 内部 from-import 的函数，需 patch 源模块
    monkeypatch.setattr(_elog, "get_sent_emails_for_task", lambda tid: list(current_task_sent))
    monkeypatch.setattr(_elog, "get_recently_sent_emails", lambda days=7: set(recently_sent))

    worker = _Worker("TEST", reexecute_mode=reexecute_mode)
    worker.task = {
        "task_id": "TEST", "task_name": "T",
        "skip_enabled": skip_enabled, "skip_days": skip_days,
        "daily_limit_per_account": 1800, "send_interval": 2,
        "sent_count": 0, "failed_count": 0, "skipped_count": 0,
    }
    worker.accounts = [{"account_id": "A1", "email": "a@x.com"}]
    worker.contacts = contacts
    worker.current_account_index = 0

    monkeypatch.setattr(worker, "load_task_data", lambda: None)
    monkeypatch.setattr(worker, "connect_smtp", lambda acc=None: _DummySMTPServer())
    monkeypatch.setattr(worker, "get_current_account", lambda: worker.accounts[0])

    def _fake_send(server, email, company):
        sent_box.append(email)
        return {"success": True, "to_email": email, "subject": "s",
                "body": "b", "message_id": "m"}
    monkeypatch.setattr(worker, "send_single_email", _fake_send)
    monkeypatch.setattr(worker, "send_report_email", lambda *a, **k: None)
    return worker


def _contact(cid, email):
    return {"contact_id": cid, "email": email, "company": "C"}


def test_reexecute_skips_recently_sent(monkeypatch):
    """reexecute + skip 开启：7 天内已发送邮箱被跳过，7 天外的重发"""
    sent = []
    w = _build_worker(monkeypatch, reexecute_mode=True, skip_enabled=1, skip_days=7,
                      contacts=[_contact("c1", "recent@x.com"),
                                _contact("c2", "fresh@x.com")],
                      recently_sent={"recent@x.com"}, sent_box=sent)
    w.run()
    assert sent == ["fresh@x.com"]


def test_reexecute_skip_disabled_sends_all(monkeypatch):
    """reexecute + skip 关闭：7 天内已发送的也重发"""
    sent = []
    w = _build_worker(monkeypatch, reexecute_mode=True, skip_enabled=0, skip_days=7,
                      contacts=[_contact("c1", "recent@x.com"),
                                _contact("c2", "fresh@x.com")],
                      recently_sent={"recent@x.com"}, sent_box=sent)
    w.run()
    assert sorted(sent) == ["fresh@x.com", "recent@x.com"]


def test_reexecute_ignores_current_task_old_sent(monkeypatch):
    """reexecute：本任务旧日志里的已发送邮箱不按"当前任务已发送"跳过，
    交由 7 天规则判定。old@x.com 在旧日志但不在 7 天集合内 → 应重发。"""
    sent = []
    w = _build_worker(monkeypatch, reexecute_mode=True, skip_enabled=1, skip_days=7,
                      contacts=[_contact("c1", "old@x.com")],
                      current_task_sent=["old@x.com"], recently_sent=set(),
                      sent_box=sent)
    w.run()
    assert sent == ["old@x.com"]


def test_normal_mode_keeps_current_task_dedup(monkeypatch):
    """普通模式：本任务已发送邮箱仍按"当前任务已发送"跳过（验证未破坏普通路径）"""
    sent = []
    w = _build_worker(monkeypatch, reexecute_mode=False, skip_enabled=1, skip_days=7,
                      contacts=[_contact("c1", "old@x.com")],
                      current_task_sent=["old@x.com"], recently_sent=set(),
                      sent_box=sent)
    w.run()
    assert sent == []
