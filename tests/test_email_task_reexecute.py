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
