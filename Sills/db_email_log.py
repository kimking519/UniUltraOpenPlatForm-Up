"""
邮件发送日志数据库操作模块
用于记录和查询邮件发送状态
"""
import sqlite3
from datetime import datetime
from Sills.base import get_db_connection


def add_log(task_id, contact_id, email, company_name="", status="sent", error_message=None):
    """添加发送日志

    Args:
        task_id: 任务ID
        contact_id: 联系人ID
        email: 收件人邮箱
        company_name: 公司名称
        status: 发送状态 (sent/failed)
        error_message: 错误信息(失败时)

    Returns:
        log_id
    """
    with get_db_connection() as conn:
        result = conn.execute("""
            INSERT INTO uni_email_log (task_id, contact_id, email, company_name, status, error_message)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (task_id, contact_id, email, company_name, status, error_message or ""))
        conn.commit()
        return result.lastrowid


def get_task_logs(task_id, page=1, page_size=50):
    """获取任务的发送日志"""
    offset = (page - 1) * page_size

    query = """
    SELECT log_id, task_id, contact_id, email, company_name, sent_at, status, error_message
    FROM uni_email_log
    WHERE task_id = ?
    ORDER BY sent_at DESC
    LIMIT ? OFFSET ?
    """

    count_query = "SELECT COUNT(*) FROM uni_email_log WHERE task_id = ?"

    with get_db_connection() as conn:
        total = conn.execute(count_query, (task_id,)).fetchone()[0]
        items = conn.execute(query, (task_id, page_size, offset)).fetchall()
        results = [
            {k: ("" if v is None else v) for k, v in dict(row).items()}
            for row in items
        ]
        return results, total


def get_failed_logs(task_id):
    """获取任务的失败日志"""
    with get_db_connection() as conn:
        items = conn.execute("""
            SELECT log_id, contact_id, email, company_name, sent_at, error_message
            FROM uni_email_log
            WHERE task_id = ? AND status = 'failed'
            ORDER BY sent_at DESC
        """, (task_id,)).fetchall()
        results = [
            {k: ("" if v is None else v) for k, v in dict(row).items()}
            for row in items
        ]
        return results


def get_sent_count(task_id):
    """获取任务已发送数量"""
    with get_db_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM uni_email_log WHERE task_id = ? AND status = 'sent'",
            (task_id,)
        ).fetchone()[0]
        return count


def get_failed_count(task_id):
    """获取任务失败数量"""
    with get_db_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM uni_email_log WHERE task_id = ? AND status = 'failed'",
            (task_id,)
        ).fetchone()[0]
        return count


def get_task_stats(task_id):
    """获取任务统计"""
    with get_db_connection() as conn:
        sent = conn.execute(
            "SELECT COUNT(*) FROM uni_email_log WHERE task_id = ? AND status = 'sent'",
            (task_id,)
        ).fetchone()[0]
        failed = conn.execute(
            "SELECT COUNT(*) FROM uni_email_log WHERE task_id = ? AND status = 'failed'",
            (task_id,)
        ).fetchone()[0]
        return {
            'sent': sent,
            'failed': failed,
            'total': sent + failed
        }


def delete_task_logs(task_id):
    """删除任务的所有日志"""
    with get_db_connection() as conn:
        conn.execute("DELETE FROM uni_email_log WHERE task_id = ?", (task_id,))
        conn.commit()


def get_recent_logs(limit=100):
    """获取最近的发送日志"""
    with get_db_connection() as conn:
        items = conn.execute("""
            SELECT l.*, t.task_name, t.subject
            FROM uni_email_log l
            LEFT JOIN uni_email_task t ON l.task_id = t.task_id
            ORDER BY l.sent_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        results = [
            {k: ("" if v is None else v) for k, v in dict(row).items()}
            for row in items
        ]
        return results