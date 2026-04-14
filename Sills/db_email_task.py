"""
邮件任务管理数据库操作模块
用于邮件任务创建、进度追踪、取消等功能
"""
import sqlite3
import json
from datetime import datetime
from Sills.base import get_db_connection
from Sills.db_contact_group import get_all_groups_contacts
from Sills.db_config import get_datetime_now


def get_next_task_id():
    """获取下一个任务ID (ET+时间戳+随机数格式)"""
    import random
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    rand_suffix = random.randint(1000, 9999)
    return f"ET{timestamp}{rand_suffix}"


def get_task_list(page=1, page_size=20, status_filter="", search_kw=""):
    """获取邮件任务列表"""
    offset = (page - 1) * page_size
    where_clauses = []
    params = []

    if status_filter:
        where_clauses.append("status = ?")
        params.append(status_filter)

    if search_kw:
        where_clauses.append("task_name LIKE ?")
        params.append(f"%{search_kw}%")

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    query = f"""
    SELECT t.*, a.email as account_email
    FROM uni_email_task t
    LEFT JOIN uni_email_account a ON t.account_id = a.account_id
    {where_sql}
    ORDER BY t.created_at DESC
    LIMIT ? OFFSET ?
    """

    count_query = f"SELECT COUNT(*) FROM uni_email_task {where_sql}"

    with get_db_connection() as conn:
        total = conn.execute(count_query, params).fetchone()[0]
        items = conn.execute(query, params + [page_size, offset]).fetchall()
        results = [
            {k: ("" if v is None else v) for k, v in dict(row).items()}
            for row in items
        ]
        return results, total


def get_task_by_id(task_id):
    """根据ID获取任务详情"""
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT t.*, a.email as account_email, a.smtp_server
            FROM uni_email_task t
            LEFT JOIN uni_email_account a ON t.account_id = a.account_id
            WHERE t.task_id = ?
        """, (task_id,)).fetchone()
        if row:
            return {k: ("" if v is None else v) for k, v in dict(row).items()}
        return None


def get_active_task():
    """获取当前活跃任务(单任务约束)"""
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT t.*, a.email as account_email, a.smtp_server, a.password
            FROM uni_email_task t
            LEFT JOIN uni_email_account a ON t.account_id = a.account_id
            WHERE t.status = 'running'
        """).fetchone()
        if row:
            return {k: ("" if v is None else v) for k, v in dict(row).items()}
        return None


def has_running_task():
    """检查是否有正在进行的任务"""
    with get_db_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM uni_email_task WHERE status = 'running'"
        ).fetchone()[0]
        return count > 0


def create_task(task_name, account_id, group_ids, subject, body,
                placeholders=None, schedule_start=None, schedule_end=None):
    """创建邮件任务

    Args:
        task_name: 任务名称
        account_id: 发件人账号ID
        group_ids: list 组ID列表
        subject: 邮件主题
        body: HTML邮件内容
        placeholders: dict 占位符配置
        schedule_start: 发送开始时间 HH:MM
        schedule_end: 发送结束时间 HH:MM

    Returns:
        (success, message_or_task_id) tuple
    """
    try:
        # 检查是否有正在进行的任务
        if has_running_task():
            return False, "已有任务正在进行,无法创建新任务"

        if not task_name or not task_name.strip():
            return False, "任务名称不能为空"
        if not account_id:
            return False, "请选择发件人账号"
        if not group_ids:
            return False, "请选择至少一个联系人组"
        if not subject or not subject.strip():
            return False, "邮件主题不能为空"
        if not body or not body.strip():
            return False, "邮件内容不能为空"

        # 合并组联系人并去重
        contacts = get_all_groups_contacts(group_ids)
        if not contacts:
            return False, "所选组中没有联系人"

        task_id = get_next_task_id()
        group_ids_json = json.dumps(group_ids)
        placeholders_json = json.dumps(placeholders) if placeholders else ""

        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO uni_email_task (
                    task_id, task_name, account_id, group_ids,
                    subject, body, placeholders,
                    schedule_start, schedule_end,
                    status, total_count, sent_count, failed_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, 0, 0)
            """, (
                task_id, task_name.strip(), account_id, group_ids_json,
                subject.strip(), body.strip(), placeholders_json,
                schedule_start, schedule_end,
                len(contacts)
            ))
            conn.commit()

        return True, task_id
    except Exception as e:
        return False, str(e)


def start_task(task_id):
    """启动任务(状态改为running)"""
    try:
        dt_now = get_datetime_now()
        with get_db_connection() as conn:
            conn.execute(f"""
                UPDATE uni_email_task
                SET status = 'running', started_at = {dt_now}
                WHERE task_id = ? AND status = 'pending'
            """, (task_id,))
            conn.commit()
            return True, "任务已启动"
    except Exception as e:
        return False, str(e)


def update_task_progress(task_id, sent_count=None, failed_count=None):
    """更新任务进度"""
    try:
        updates = []
        params = []

        if sent_count is not None:
            updates.append("sent_count = ?")
            params.append(sent_count)

        if failed_count is not None:
            updates.append("failed_count = ?")
            params.append(failed_count)

        if not updates:
            return True

        params.append(task_id)
        sql = f"UPDATE uni_email_task SET {', '.join(updates)} WHERE task_id = ?"

        with get_db_connection() as conn:
            conn.execute(sql, params)
            conn.commit()

        return True
    except Exception as e:
        return False, str(e)


def cancel_task(task_id):
    """请求取消任务"""
    try:
        with get_db_connection() as conn:
            conn.execute("""
                UPDATE uni_email_task
                SET cancel_requested = 1
                WHERE task_id = ? AND status = 'running'
            """, (task_id,))
            conn.commit()
            return True, "取消请求已发送"
    except Exception as e:
        return False, str(e)


def complete_task(task_id, failed_count=0):
    """完成任务"""
    try:
        dt_now = get_datetime_now()
        with get_db_connection() as conn:
            conn.execute(f"""
                UPDATE uni_email_task
                SET status = 'completed',
                    completed_at = {dt_now},
                    failed_count = ?
                WHERE task_id = ?
            """, (failed_count, task_id))
            conn.commit()
            return True, "任务已完成"
    except Exception as e:
        return False, str(e)


def error_task(task_id, error_message):
    """标记任务出错"""
    try:
        with get_db_connection() as conn:
            conn.execute("""
                UPDATE uni_email_task
                SET status = 'error', error_message = ?
                WHERE task_id = ?
            """, (error_message, task_id))
            conn.commit()
            return True, "任务已标记为错误"
    except Exception as e:
        return False, str(e)


def get_task_progress(task_id):
    """获取任务进度信息"""
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT task_id, task_name, status, total_count, sent_count, failed_count,
                   started_at, schedule_start, schedule_end, cancel_requested
            FROM uni_email_task
            WHERE task_id = ?
        """, (task_id,)).fetchone()
        if row:
            return {k: ("" if v is None else v) for k, v in dict(row).items()}
        return None


def is_cancel_requested(task_id):
    """检查是否请求取消"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT cancel_requested FROM uni_email_task WHERE task_id = ?",
            (task_id,)
        ).fetchone()
        return row and row[0] == 1


def get_task_contacts(task_id):
    """获取任务的联系人列表"""
    task = get_task_by_id(task_id)
    if not task:
        return []

    group_ids = json.loads(task.get('group_ids', '[]') or '[]')
    return get_all_groups_contacts(group_ids)