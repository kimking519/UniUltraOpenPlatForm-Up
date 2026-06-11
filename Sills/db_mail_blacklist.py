"""
邮件数据库操作层 - 黑名单管理模块
包含：黑名单CRUD、邮件黑名单标记、自动分类
"""
from typing import Dict, List, Any
from Sills.base import get_db_connection
from Sills.db_mail_folder import get_or_create_blacklist_folder


def add_to_blacklist(email_addr: str, reason: str = None, account_id: int = None) -> bool:
    """
    添加邮箱到黑名单

    Args:
        email_addr: 邮箱地址
        reason: 拉黑原因
        account_id: 账户ID

    Returns:
        是否成功
    """
    with get_db_connection() as conn:
        try:
            conn.execute("""
                INSERT INTO mail_blacklist (email_addr, reason, account_id)
                VALUES (?, ?, ?)
                ON CONFLICT(email_addr) DO NOTHING
            """, (email_addr, reason, account_id))
            conn.commit()
            return True
        except:
            return False


def remove_from_blacklist(blacklist_id: int) -> bool:
    """从黑名单移除"""
    with get_db_connection() as conn:
        result = conn.execute("DELETE FROM mail_blacklist WHERE id = ?", (blacklist_id,))
        conn.commit()
        return result.rowcount > 0


def get_blacklist_list(account_id: int = None) -> list:
    """获取黑名单列表"""
    with get_db_connection() as conn:
        if account_id is not None:
            rows = conn.execute(
                "SELECT * FROM mail_blacklist WHERE account_id = ? OR account_id IS NULL ORDER BY created_at DESC",
                (account_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mail_blacklist ORDER BY created_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]


def is_in_blacklist(email_addr: str, account_id: int = None) -> bool:
    """检查邮箱是否在黑名单中"""
    with get_db_connection() as conn:
        if account_id is not None:
            row = conn.execute(
                "SELECT COUNT(*) FROM mail_blacklist WHERE email_addr = ? AND (account_id = ? OR account_id IS NULL)",
                (email_addr, account_id)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM mail_blacklist WHERE email_addr = ?",
                (email_addr,)
            ).fetchone()
        return row[0] > 0 if row else False


def get_blacklisted_list(page: int = 1, limit: int = 20, search: str = None, account_id: int = None) -> Dict[str, Any]:
    """获取黑名单邮件列表（分页）"""
    offset = (page - 1) * limit
    params = []
    count_params = []

    # 列表视图只查询必要字段，避免加载大字段
    select_fields = "id, subject, from_addr, from_name, to_addr, received_at, sent_at, is_sent, is_read, message_id, account_id, folder_id, created_at"

    query = f"SELECT {select_fields} FROM uni_mail WHERE is_blacklisted = 1 AND is_deleted = 0"
    count_query = "SELECT COUNT(*) FROM uni_mail WHERE is_blacklisted = 1 AND is_deleted = 0"

    if account_id is not None:
        query += " AND account_id = ?"
        count_query += " AND account_id = ?"
        params.append(account_id)
        count_params.append(account_id)

    if search:
        # 2026-06-11: 新增 to_addr 和 content 搜索，对齐其他列表行为
        query += " AND (subject LIKE ? OR from_addr LIKE ? OR to_addr LIKE ? OR content LIKE ?)"
        count_query += " AND (subject LIKE ? OR from_addr LIKE ? OR to_addr LIKE ? OR content LIKE ?)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param, search_param])
        count_params.extend([search_param, search_param, search_param, search_param])

    query += " ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db_connection() as conn:
        total_count = conn.execute(count_query, count_params).fetchone()[0]
        rows = conn.execute(query, params).fetchall()

    items = []
    for row in rows:
        item = dict(row)
        item['content_preview'] = ''
        item['body_truncated'] = False
        items.append(item)

    return {
        "items": items,
        "total_count": total_count,
        "page": page,
        "page_size": limit,
        "total_pages": (total_count + limit - 1) // limit if total_count > 0 else 0
    }


def get_blacklisted_count(account_id: int = None) -> int:
    """获取黑名单邮件数量"""
    with get_db_connection() as conn:
        if account_id is not None:
            row = conn.execute(
                "SELECT COUNT(*) FROM uni_mail WHERE is_blacklisted = 1 AND is_deleted = 0 AND account_id = ?",
                (account_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM uni_mail WHERE is_blacklisted = 1 AND is_deleted = 0"
            ).fetchone()
        return row[0] if row else 0


def mark_email_as_blacklisted(mail_id: int) -> bool:
    """将邮件标记为黑名单邮件"""
    with get_db_connection() as conn:
        result = conn.execute(
            "UPDATE uni_mail SET is_blacklisted = 1 WHERE id = ?",
            (mail_id,)
        )
        conn.commit()
        return result.rowcount > 0


def unmark_email_as_blacklisted(mail_id: int) -> bool:
    """取消邮件的黑名单标记"""
    with get_db_connection() as conn:
        result = conn.execute(
            "UPDATE uni_mail SET is_blacklisted = 0 WHERE id = ?",
            (mail_id,)
        )
        conn.commit()
        return result.rowcount > 0


def auto_classify_blacklist(account_id: int = None) -> int:
    """
    自动将黑名单邮箱的邮件标记为黑名单邮件，并移动到黑名单文件夹
    返回：被标记的邮件数量
    """
    # 先获取或创建黑名单文件夹
    blacklist_folder_id = get_or_create_blacklist_folder(account_id)

    with get_db_connection() as conn:
        # 获取黑名单邮箱列表
        if account_id is not None:
            blacklist_rows = conn.execute(
                "SELECT email_addr FROM mail_blacklist WHERE account_id = ? OR account_id IS NULL",
                (account_id,)
            ).fetchall()
        else:
            blacklist_rows = conn.execute(
                "SELECT email_addr FROM mail_blacklist"
            ).fetchall()

        if not blacklist_rows:
            return 0

        blacklist_emails = [row[0] for row in blacklist_rows]
        count = 0

        for email in blacklist_emails:
            # 更新所有来自该邮箱的邮件：设置黑名单标记并移动到黑名单文件夹
            result = conn.execute("""
                UPDATE uni_mail SET is_blacklisted = 1, folder_id = ?
                WHERE from_addr LIKE ? AND is_blacklisted = 0 AND is_deleted = 0
            """, (blacklist_folder_id, f"%{email}%"))
            count += result.rowcount

        conn.commit()
        return count


def get_unread_count(account_id: int = None) -> int:
    """获取未读邮件数量"""
    with get_db_connection() as conn:
        if account_id is not None:
            row = conn.execute(
                "SELECT COUNT(*) FROM uni_mail WHERE is_sent = 0 AND is_read = 0 AND account_id = ?",
                (account_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM uni_mail WHERE is_sent = 0 AND is_read = 0"
            ).fetchone()
        return row[0] if row else 0