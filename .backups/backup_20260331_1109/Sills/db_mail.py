"""
邮件数据库操作层
SmartMail Integration - Database Operations
"""
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from Sills.base import get_db_connection
from Sills.crypto_utils import encrypt_password, decrypt_password


def _clean_text(text):
    """
    清理文本中的 NUL 字符（PostgreSQL 不支持字符串中的 NUL 字符）
    """
    if text is None:
        return None
    if isinstance(text, str):
        return text.replace('\x00', '')
    return text


def get_mail_list(page: int = 1, limit: int = 20, is_sent: int = 0,
                  search: str = None, account_id: int = None) -> Dict[str, Any]:
    """
    获取邮件列表（分页）

    Args:
        page: 页码
        limit: 每页数量
        is_sent: 0=收件箱, 1=已发送
        search: 搜索关键词（主题/发件人/收件人）
        account_id: 账户ID（用户隔离）

    Returns:
        分页结果字典
    """
    offset = (page - 1) * limit
    params = [is_sent]
    count_params = [is_sent]

    # 列表视图只查询必要字段，避免加载大字段（content, html_content）
    select_fields = "id, subject, from_addr, from_name, to_addr, received_at, sent_at, is_sent, is_read, message_id, account_id, folder_id"

    query = f"SELECT {select_fields} FROM uni_mail WHERE is_sent = ? AND is_deleted = 0"
    count_query = "SELECT COUNT(*) FROM uni_mail WHERE is_sent = ? AND is_deleted = 0"

    # 收件箱只显示未分类的邮件（folder_id IS NULL）且非草稿
    if is_sent == 0:
        query += " AND folder_id IS NULL AND is_draft = 0"
        count_query += " AND folder_id IS NULL AND is_draft = 0"

    # 用户隔离：按账户ID过滤
    if account_id is not None:
        query += " AND account_id = ?"
        count_query += " AND account_id = ?"
        params.append(account_id)
        count_params.append(account_id)
    else:
        # 没有指定账户ID时返回空结果
        return {
            "items": [],
            "total_count": 0,
            "page": page,
            "page_size": limit,
            "total_pages": 0
        }

    if search:
        query += " AND (subject LIKE ? OR from_addr LIKE ? OR to_addr LIKE ?)"
        count_query += " AND (subject LIKE ? OR from_addr LIKE ? OR to_addr LIKE ?)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param])
        count_params.extend([search_param, search_param, search_param])

    query += " ORDER BY received_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db_connection() as conn:
        total_count = conn.execute(count_query, count_params).fetchone()[0]
        rows = conn.execute(query, params).fetchall()

    items = []
    for row in rows:
        item = dict(row)
        # 列表视图不需要内容预览（大字段已排除）
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


def get_mail_by_id(mail_id: int) -> Optional[Dict[str, Any]]:
    """获取单封邮件详情"""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM uni_mail WHERE id = ?", (mail_id,)).fetchone()
        if row:
            return dict(row)
    return None


def get_trash_list(page: int = 1, limit: int = 20, search: str = None, account_id: int = None) -> Dict[str, Any]:
    """
    获取回收站邮件列表（分页）
    """
    offset = (page - 1) * limit
    params = []
    count_params = []

    # 列表视图只查询必要字段，避免加载大字段
    select_fields = "id, subject, from_addr, from_name, to_addr, received_at, sent_at, is_sent, is_read, message_id, account_id, folder_id, deleted_at"

    query = f"SELECT {select_fields} FROM uni_mail WHERE is_deleted = 1"
    count_query = "SELECT COUNT(*) FROM uni_mail WHERE is_deleted = 1"

    # 回收站不按账户过滤，显示所有已删除邮件

    if search:
        query += " AND (subject LIKE ? OR from_addr LIKE ? OR to_addr LIKE ?)"
        count_query += " AND (subject LIKE ? OR from_addr LIKE ? OR to_addr LIKE ?)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param])
        count_params.extend([search_param, search_param, search_param])

    query += " ORDER BY deleted_at DESC LIMIT ? OFFSET ?"
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


def save_email(mail_data: Dict[str, Any]) -> int:
    """
    保存邮件到数据库（防止重复插入）

    Args:
        mail_data: 邮件数据字典

    Returns:
        新邮件的ID，如果已存在返回已有ID
    """
    # 将空字符串的message_id转为None，避免唯一约束冲突
    message_id = mail_data.get('message_id')
    if message_id == '':
        message_id = None

    with get_db_connection() as conn:
        imap_uid = mail_data.get('imap_uid')
        imap_folder = mail_data.get('imap_folder')
        account_id = mail_data.get('account_id')

        # 检查1：通过imap_uid + imap_folder + account_id
        if imap_uid and imap_folder and account_id:
            existing = conn.execute(
                "SELECT id, is_sent, is_draft FROM uni_mail WHERE imap_uid = ? AND imap_folder = ? AND account_id = ?",
                (imap_uid, imap_folder, account_id)
            ).fetchone()
            if existing:
                # 如果is_sent或is_draft不同，更新它们
                new_is_sent = mail_data.get('is_sent', 0)
                new_is_draft = mail_data.get('is_draft', 0)
                if existing[1] != new_is_sent or existing[2] != new_is_draft:
                    conn.execute(
                        "UPDATE uni_mail SET is_sent = ?, is_draft = ? WHERE id = ?",
                        (new_is_sent, new_is_draft, existing[0])
                    )
                    conn.commit()
                return existing[0]

        # 检查2：通过message_id（同一封邮件可能在不同文件夹有相同message_id）
        if message_id:
            existing = conn.execute(
                "SELECT id, is_sent, is_draft FROM uni_mail WHERE message_id = ?",
                (message_id,)
            ).fetchone()
            if existing:
                # 如果is_sent或is_draft不同，更新它们
                new_is_sent = mail_data.get('is_sent', 0)
                new_is_draft = mail_data.get('is_draft', 0)
                if existing[1] != new_is_sent or existing[2] != new_is_draft:
                    conn.execute(
                        "UPDATE uni_mail SET is_sent = ?, is_draft = ? WHERE id = ?",
                        (new_is_sent, new_is_draft, existing[0])
                    )
                    conn.commit()
                return existing[0]

        cursor = conn.execute("""
            INSERT INTO uni_mail (subject, from_addr, from_name, to_addr, cc_addr, content, html_content,
                                  received_at, sent_at, is_sent, is_draft, message_id, sync_status, account_id,
                                  imap_uid, imap_folder, folder_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            _clean_text(mail_data.get('subject')),
            _clean_text(mail_data.get('from_addr')),
            _clean_text(mail_data.get('from_name')),
            _clean_text(mail_data.get('to_addr')),
            _clean_text(mail_data.get('cc_addr')),
            _clean_text(mail_data.get('content')),
            _clean_text(mail_data.get('html_content')),
            _clean_text(mail_data.get('received_at')),
            _clean_text(mail_data.get('sent_at')),
            mail_data.get('is_sent', 0),
            mail_data.get('is_draft', 0),
            _clean_text(message_id),
            _clean_text(mail_data.get('sync_status', 'completed')),
            mail_data.get('account_id'),
            _clean_text(mail_data.get('imap_uid')),
            _clean_text(mail_data.get('imap_folder')),
            mail_data.get('folder_id')
        ))
        conn.commit()
        return cursor.lastrowid


def batch_save_emails(emails_data: list) -> int:
    """
    批量保存邮件到数据库（一次事务，更高效）

    Args:
        emails_data: 邮件数据字典列表

    Returns:
        成功保存的邮件数量
    """
    if not emails_data:
        return 0

    saved_count = 0
    with get_db_connection() as conn:
        for mail_data in emails_data:
            # 将空字符串的message_id转为None
            message_id = mail_data.get('message_id')
            if message_id == '':
                message_id = None

            imap_uid = mail_data.get('imap_uid')
            imap_folder = mail_data.get('imap_folder')
            account_id = mail_data.get('account_id')

            # 检查重复
            skip = False
            if imap_uid and imap_folder and account_id:
                existing = conn.execute(
                    "SELECT id FROM uni_mail WHERE imap_uid = ? AND imap_folder = ? AND account_id = ?",
                    (imap_uid, imap_folder, account_id)
                ).fetchone()
                if existing:
                    skip = True

            if not skip and message_id:
                existing = conn.execute(
                    "SELECT id FROM uni_mail WHERE message_id = ?",
                    (message_id,)
                ).fetchone()
                if existing:
                    skip = True

            if skip:
                continue

            conn.execute("""
                INSERT INTO uni_mail (subject, from_addr, from_name, to_addr, cc_addr, content, html_content,
                                      received_at, sent_at, is_sent, is_draft, message_id, sync_status, account_id,
                                      imap_uid, imap_folder, folder_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                _clean_text(mail_data.get('subject')),
                _clean_text(mail_data.get('from_addr')),
                _clean_text(mail_data.get('from_name')),
                _clean_text(mail_data.get('to_addr')),
                _clean_text(mail_data.get('cc_addr')),
                _clean_text(mail_data.get('content')),
                _clean_text(mail_data.get('html_content')),
                _clean_text(mail_data.get('received_at')),
                _clean_text(mail_data.get('sent_at')),
                mail_data.get('is_sent', 0),
                mail_data.get('is_draft', 0),
                _clean_text(message_id),
                _clean_text(mail_data.get('sync_status', 'completed')),
                mail_data.get('account_id'),
                _clean_text(mail_data.get('imap_uid')),
                _clean_text(mail_data.get('imap_folder')),
                mail_data.get('folder_id')
            ))
            saved_count += 1

        # 一次性提交所有邮件
        conn.commit()

    return saved_count


def delete_email(mail_id: int) -> bool:
    """删除邮件（移入回收站）"""
    with get_db_connection() as conn:
        # 软删除：设置 is_deleted = 1
        result = conn.execute("""
            UPDATE uni_mail SET is_deleted = 1, deleted_at = datetime('now', 'localtime') WHERE id = ?
        """, (mail_id,))
        conn.commit()
        return result.rowcount > 0


def restore_email(mail_id: int) -> bool:
    """恢复邮件（从回收站）"""
    with get_db_connection() as conn:
        result = conn.execute("""
            UPDATE uni_mail SET is_deleted = 0, deleted_at = NULL WHERE id = ?
        """, (mail_id,))
        conn.commit()
        return result.rowcount > 0


def permanently_delete_email(mail_id: int) -> bool:
    """永久删除邮件"""
    with get_db_connection() as conn:
        # 先删除关联关系
        conn.execute("DELETE FROM uni_mail_rel WHERE mail_id = ?", (mail_id,))
        result = conn.execute("DELETE FROM uni_mail WHERE id = ?", (mail_id,))
        conn.commit()
        return result.rowcount > 0


def empty_trash() -> int:
    """清空回收站"""
    with get_db_connection() as conn:
        # 先删除关联关系
        conn.execute("DELETE FROM uni_mail_rel WHERE mail_id IN (SELECT id FROM uni_mail WHERE is_deleted = 1)")
        result = conn.execute("DELETE FROM uni_mail WHERE is_deleted = 1")
        conn.commit()
        return result.rowcount


def get_trash_count() -> int:
    """获取回收站邮件数量"""
    with get_db_connection() as conn:
        row = conn.execute("SELECT COUNT(*) FROM uni_mail WHERE is_deleted = 1").fetchone()
        return row[0] if row else 0


def batch_delete_emails(mail_ids: list) -> int:
    """批量删除邮件（移入回收站）"""
    if not mail_ids:
        return 0
    with get_db_connection() as conn:
        placeholders = ','.join('?' * len(mail_ids))
        # 软删除：设置 is_deleted = 1
        result = conn.execute(f"UPDATE uni_mail SET is_deleted = 1, deleted_at = datetime('now', 'localtime') WHERE id IN ({placeholders})", mail_ids)
        conn.commit()
        return result.rowcount


def batch_restore_emails(mail_ids: list) -> int:
    """批量恢复邮件（从回收站）"""
    if not mail_ids:
        return 0
    with get_db_connection() as conn:
        placeholders = ','.join('?' * len(mail_ids))
        result = conn.execute(f"UPDATE uni_mail SET is_deleted = 0, deleted_at = NULL WHERE id IN ({placeholders})", mail_ids)
        conn.commit()
        return result.rowcount


def mark_email_read(mail_id: int) -> bool:
    """标记邮件为已读"""
    with get_db_connection() as conn:
        conn.execute("UPDATE uni_mail SET is_read = 1 WHERE id = ?", (mail_id,))
        conn.commit()
        return True


# ============ 草稿箱功能 ============

def save_draft(mail_data: Dict[str, Any]) -> int:
    """
    保存草稿

    Args:
        mail_data: 草稿数据字典，包含 to_addr, cc_addr, subject, content, html_content 等

    Returns:
        新草稿的ID
    """
    from Sills.base import get_db_connection

    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO uni_mail (subject, from_addr, to_addr, cc_addr, content, html_content,
                                  is_sent, is_draft, sync_status, account_id)
            VALUES (?, ?, ?, ?, ?, ?, 0, 1, 'draft', ?)
        """, (
            mail_data.get('subject'),
            mail_data.get('from_addr', ''),
            mail_data.get('to_addr'),
            mail_data.get('cc_addr'),
            mail_data.get('content'),
            mail_data.get('html_content'),
            mail_data.get('account_id')
        ))
        conn.commit()
        return cursor.lastrowid


def get_draft_list(page: int = 1, limit: int = 20, search: str = None, account_id: int = None) -> Dict[str, Any]:
    """
    获取草稿列表（分页）
    """
    offset = (page - 1) * limit
    params = []
    count_params = []

    # 列表视图只查询必要字段，避免加载大字段
    select_fields = "id, subject, from_addr, from_name, to_addr, received_at, sent_at, is_sent, is_read, message_id, account_id, folder_id, created_at"

    query = f"SELECT {select_fields} FROM uni_mail WHERE is_draft = 1 AND is_deleted = 0"
    count_query = "SELECT COUNT(*) FROM uni_mail WHERE is_draft = 1 AND is_deleted = 0"

    if account_id is not None:
        query += " AND account_id = ?"
        count_query += " AND account_id = ?"
        params.append(account_id)
        count_params.append(account_id)

    if search:
        query += " AND (subject LIKE ? OR to_addr LIKE ?)"
        count_query += " AND (subject LIKE ? OR to_addr LIKE ?)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param])
        count_params.extend([search_param, search_param])

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
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


def get_draft_by_id(draft_id: int) -> Optional[Dict[str, Any]]:
    """获取单个草稿详情"""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM uni_mail WHERE id = ? AND is_draft = 1", (draft_id,)).fetchone()
        if row:
            return dict(row)
    return None


def update_draft(draft_id: int, mail_data: Dict[str, Any]) -> bool:
    """更新草稿"""
    with get_db_connection() as conn:
        result = conn.execute("""
            UPDATE uni_mail SET
                subject = ?,
                to_addr = ?,
                cc_addr = ?,
                content = ?,
                html_content = ?
            WHERE id = ? AND is_draft = 1
        """, (
            mail_data.get('subject'),
            mail_data.get('to_addr'),
            mail_data.get('cc_addr'),
            mail_data.get('content'),
            mail_data.get('html_content'),
            draft_id
        ))
        conn.commit()
        return result.rowcount > 0


def delete_draft(draft_id: int) -> bool:
    """删除草稿"""
    with get_db_connection() as conn:
        result = conn.execute("DELETE FROM uni_mail WHERE id = ? AND is_draft = 1", (draft_id,))
        conn.commit()
        return result.rowcount > 0


def get_draft_count(account_id: int = None) -> int:
    """获取草稿数量"""
    with get_db_connection() as conn:
        if account_id is not None:
            row = conn.execute(
                "SELECT COUNT(*) FROM uni_mail WHERE is_draft = 1 AND is_deleted = 0 AND account_id = ?",
                (account_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM uni_mail WHERE is_draft = 1 AND is_deleted = 0"
            ).fetchone()
        return row[0] if row else 0


# ============ 黑名单功能 ============

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
        query += " AND (subject LIKE ? OR from_addr LIKE ?)"
        count_query += " AND (subject LIKE ? OR from_addr LIKE ?)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param])
        count_params.extend([search_param, search_param])

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
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


def create_mail_relation(mail_id: int, ref_type: str, ref_id: str) -> int:
    """
    创建邮件与ERP实体的关联关系

    Args:
        mail_id: 邮件ID
        ref_type: 关联类型 ('cli' 或 'order')
        ref_id: 关联的实体ID

    Returns:
        关联记录ID
    """
    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO uni_mail_rel (mail_id, ref_type, ref_id)
            VALUES (?, ?, ?)
        """, (mail_id, ref_type, ref_id))
        conn.commit()
        return cursor.lastrowid


def get_mail_relations(mail_id: int) -> List[Dict[str, Any]]:
    """获取邮件的所有关联关系"""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT r.*, c.cli_name, o.order_no
            FROM uni_mail_rel r
            LEFT JOIN uni_cli c ON r.ref_type = 'cli' AND r.ref_id = c.cli_id
            LEFT JOIN uni_order o ON r.ref_type = 'order' AND r.ref_id = o.order_id
            WHERE r.mail_id = ?
        """, (mail_id,)).fetchall()
        return [dict(row) for row in rows]


def remove_mail_relation(relation_id: int) -> bool:
    """删除邮件关联关系"""
    with get_db_connection() as conn:
        result = conn.execute("DELETE FROM uni_mail_rel WHERE id = ?", (relation_id,))
        conn.commit()
        return result.rowcount > 0


def remove_mail_relations_by_ref(ref_type: str, ref_id: str) -> int:
    """
    删除指定实体的所有邮件关联关系

    Args:
        ref_type: 实体类型 ('cli' 或 'order')
        ref_id: 实体ID

    Returns:
        删除的记录数
    """
    with get_db_connection() as conn:
        result = conn.execute(
            "DELETE FROM uni_mail_rel WHERE ref_type = ? AND ref_id = ?",
            (ref_type, ref_id)
        )
        conn.commit()
        return result.rowcount


def get_mail_config() -> Optional[Dict[str, Any]]:
    """获取当前邮件账户配置（解密密码）"""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM mail_config WHERE is_current = 1").fetchone()
        if row:
            config = dict(row)
            # 解密密码
            if config.get('password'):
                try:
                    config['password'] = decrypt_password(config['password'])
                except Exception:
                    pass  # 如果解密失败，可能未加密
            return config
    return None


def get_all_mail_accounts() -> List[Dict[str, Any]]:
    """获取所有邮件账户列表（不含密码）"""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT id, account_name, smtp_server, smtp_port,
                   imap_server, imap_port, username, use_tls,
                   is_current
            FROM mail_config
            ORDER BY is_current DESC, id DESC
        """).fetchall()
        return [dict(row) for row in rows]


def get_mail_account_by_id(account_id: int) -> Optional[Dict[str, Any]]:
    """获取指定邮件账户（解密密码）"""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM mail_config WHERE id = ?", (account_id,)).fetchone()
        if row:
            config = dict(row)
            if config.get('password'):
                try:
                    config['password'] = decrypt_password(config['password'])
                except Exception:
                    pass
            return config
    return None


def add_mail_account(config: Dict[str, Any]) -> int:
    """添加新邮件账户"""
    password = config.get('password', '')
    if password:
        try:
            password = encrypt_password(password)
        except Exception:
            pass

    with get_db_connection() as conn:
        # 如果是第一个账户，自动设为当前账户
        count = conn.execute("SELECT COUNT(*) FROM mail_config").fetchone()[0]
        is_current = 1 if count == 0 else 0

        cursor = conn.execute("""
            INSERT INTO mail_config (account_name, smtp_server, smtp_port, imap_server,
                                     imap_port, username, password, use_tls, is_current)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            config.get('account_name', '新账户'),
            config.get('smtp_server'),
            config.get('smtp_port', 587),
            config.get('imap_server'),
            config.get('imap_port', 993),
            config.get('username'),
            password,
            config.get('use_tls', 1),
            is_current
        ))
        conn.commit()
        return cursor.lastrowid


def update_mail_account(account_id: int, config: Dict[str, Any]) -> bool:
    """更新邮件账户配置（加密密码）"""
    password = config.get('password', '')
    if password:
        try:
            password = encrypt_password(password)
        except Exception:
            pass

    with get_db_connection() as conn:
        # 构建动态更新
        update_fields = []
        params = []

        field_mapping = {
            'account_name': config.get('account_name'),
            'smtp_server': config.get('smtp_server'),
            'smtp_port': config.get('smtp_port'),
            'imap_server': config.get('imap_server'),
            'imap_port': config.get('imap_port'),
            'username': config.get('username'),
            'use_tls': config.get('use_tls'),
            'sync_batch_size': config.get('sync_batch_size'),
            'sync_pause_seconds': config.get('sync_pause_seconds'),
        }

        for field, value in field_mapping.items():
            if value is not None:
                update_fields.append(f"{field} = ?")
                params.append(value)

        # 密码单独处理（只有提供了才更新）
        if config.get('password'):
            update_fields.append("password = ?")
            params.append(password)

        if not update_fields:
            return False

        params.append(account_id)
        sql = f"UPDATE mail_config SET {', '.join(update_fields)} WHERE id = ?"

        conn.execute(sql, params)
        conn.commit()
        return True


def switch_current_account(account_id: int) -> bool:
    """切换当前邮件账户"""
    with get_db_connection() as conn:
        # 先取消所有账户的当前状态
        conn.execute("UPDATE mail_config SET is_current = 0")
        # 设置指定账户为当前账户
        result = conn.execute("UPDATE mail_config SET is_current = 1 WHERE id = ?", (account_id,))
        conn.commit()
        return result.rowcount > 0


def delete_mail_account(account_id: int) -> Dict[str, Any]:
    """删除邮件账户"""
    with get_db_connection() as conn:
        # 检查是否是当前账户
        row = conn.execute("SELECT is_current FROM mail_config WHERE id = ?", (account_id,)).fetchone()
        if not row:
            return {"success": False, "message": "账户不存在"}

        was_current = row[0] == 1

        # 删除账户
        conn.execute("DELETE FROM mail_config WHERE id = ?", (account_id,))

        # 如果删除的是当前账户，自动选择下一个账户
        if was_current:
            next_row = conn.execute("SELECT id FROM mail_config ORDER BY created_at DESC LIMIT 1").fetchone()
            if next_row:
                conn.execute("UPDATE mail_config SET is_current = 1 WHERE id = ?", (next_row[0],))

        conn.commit()
        return {"success": True, "message": "删除成功"}


def update_mail_sync_status(mail_id: int, status: str, error: str = None) -> bool:
    """
    更新邮件同步状态

    Args:
        mail_id: 邮件ID
        status: 状态 ('pending', 'completed', 'failed')
        error: 错误信息（可选）

    Returns:
        是否更新成功
    """
    with get_db_connection() as conn:
        conn.execute("""
            UPDATE uni_mail SET sync_status = ?, sync_error = ? WHERE id = ?
        """, (status, error, mail_id))
        conn.commit()
        return True


def acquire_sync_lock(lock_id: str) -> bool:
    """
    获取同步锁

    Args:
        lock_id: 锁标识符（进程/线程ID）

    Returns:
        True=获取成功，False=已被锁定
    """
    now = datetime.now()
    expires_at = now + timedelta(minutes=5)

    with get_db_connection() as conn:
        # 检查是否存在过期锁
        row = conn.execute("SELECT * FROM mail_sync_lock WHERE id = 1").fetchone()
        if row:
            lock = dict(row)
            if lock.get('expires_at'):
                # PostgreSQL 返回 datetime 对象，SQLite 返回字符串
                expires = lock['expires_at']
                if isinstance(expires, str):
                    expires = datetime.fromisoformat(expires)
                if expires > now:
                    return False  # 锁仍然有效

        # 获取或更新锁（包含进度字段）
        conn.execute("""
            INSERT INTO mail_sync_lock (id, locked_at, locked_by, expires_at, progress_total, progress_current, progress_message)
            VALUES (1, ?, ?, ?, 0, 0, '初始化中...')
            ON CONFLICT(id) DO UPDATE SET
                locked_at = excluded.locked_at,
                locked_by = excluded.locked_by,
                expires_at = excluded.expires_at,
                progress_total = 0,
                progress_current = 0,
                progress_message = '初始化中...'
        """, (now.isoformat(), lock_id, expires_at.isoformat()))
        conn.commit()
        return True


def update_sync_progress(current: int, total: int, message: str = "",
                          sync_start_date: str = None, sync_end_date: str = None,
                          total_emails: int = None, synced_emails: int = None) -> bool:
    """
    更新同步进度

    Args:
        current: 当前进度
        total: 总数
        message: 进度消息
        sync_start_date: 同步开始日期
        sync_end_date: 同步结束日期
        total_emails: 总邮件数
        synced_emails: 已同步邮件数

    Returns:
        是否更新成功
    """
    with get_db_connection() as conn:
        # 构建动态更新语句
        updates = ["progress_current = ?", "progress_total = ?", "progress_message = ?"]
        params = [current, total, message]

        if sync_start_date is not None:
            updates.append("sync_start_date = ?")
            params.append(sync_start_date)
        if sync_end_date is not None:
            updates.append("sync_end_date = ?")
            params.append(sync_end_date)
        if total_emails is not None:
            updates.append("total_emails = ?")
            params.append(total_emails)
        if synced_emails is not None:
            updates.append("synced_emails = ?")
            params.append(synced_emails)

        sql = f"UPDATE mail_sync_lock SET {', '.join(updates)} WHERE id = 1"
        conn.execute(sql, params)
        conn.commit()
        return True


def get_sync_progress() -> Dict[str, Any]:
    """
    获取同步进度

    Returns:
        {syncing: bool, current: int, total: int, message: str,
         sync_start_date: str, sync_end_date: str, total_emails: int, synced_emails: int, percent: int}
    """
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM mail_sync_lock WHERE id = 1").fetchone()
        if row:
            lock = dict(row)
            if lock.get('expires_at'):
                # PostgreSQL 返回 datetime 对象，SQLite 返回字符串
                expires = lock['expires_at']
                if isinstance(expires, str):
                    expires = datetime.fromisoformat(expires)
                if expires > datetime.now():
                    total_emails = lock.get('total_emails', 0) or 0
                    synced_emails = lock.get('synced_emails', 0) or 0
                    percent = int((synced_emails / total_emails) * 100) if total_emails > 0 else 0
                    return {
                        "syncing": True,
                        "current": lock.get('progress_current', 0) or 0,
                        "total": lock.get('progress_total', 0) or 0,
                        "message": lock.get('progress_message', '') or '',
                        "status": "syncing",
                        "sync_start_date": lock.get('sync_start_date', '') or '',
                        "sync_end_date": lock.get('sync_end_date', '') or '',
                        "total_emails": total_emails,
                        "synced_emails": synced_emails,
                        "percent": percent
                    }
    return {
        "syncing": False,
        "current": 0,
        "total": 0,
        "message": "",
        "status": "idle",
        "sync_start_date": "",
        "sync_end_date": "",
        "total_emails": 0,
        "synced_emails": 0,
        "percent": 0
    }


def release_sync_lock() -> bool:
    """释放同步锁"""
    with get_db_connection() as conn:
        conn.execute("DELETE FROM mail_sync_lock WHERE id = 1")
        conn.commit()
        return True


def is_sync_locked() -> bool:
    """检查同步锁是否有效"""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM mail_sync_lock WHERE id = 1").fetchone()
        if row:
            lock = dict(row)
            if lock.get('expires_at'):
                # PostgreSQL 返回 datetime 对象，SQLite 返回字符串
                expires = lock['expires_at']
                if isinstance(expires, str):
                    expires = datetime.fromisoformat(expires)
                return expires > datetime.now()
    return False


def recover_orphaned_syncs() -> int:
    """
    恢复孤立的同步记录（标记超过5分钟的pending为failed）

    Returns:
        恢复的记录数
    """
    cutoff = datetime.now() - timedelta(minutes=5)

    with get_db_connection() as conn:
        result = conn.execute("""
            UPDATE uni_mail
            SET sync_status = 'failed', sync_error = 'Sync timeout - orphaned task'
            WHERE sync_status = 'pending'
            AND created_at < ?
        """, (cutoff.isoformat(),))
        conn.commit()
        return result.rowcount


def get_unread_count() -> int:
    """获取未读邮件数量（收件箱）"""
    with get_db_connection() as conn:
        # 暂时返回收件箱总数，后续可添加 is_read 字段
        row = conn.execute(
            "SELECT COUNT(*) FROM uni_mail WHERE is_sent = 0"
        ).fetchone()
        return row[0] if row else 0


def get_sync_interval() -> int:
    """获取同步间隔（分钟）"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT value FROM global_settings WHERE key = 'sync_interval'"
        ).fetchone()
        if row:
            return int(row[0])
    return 30  # 默认30分钟


def set_sync_interval(minutes: int) -> bool:
    """设置同步间隔（分钟）"""
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO global_settings (key, value, updated_at)
            VALUES ('sync_interval', ?, datetime('now', 'localtime'))
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
        """, (str(minutes),))
        conn.commit()
        return True


def get_sync_days() -> int:
    """获取同步时间范围（天）"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT value FROM global_settings WHERE key = 'sync_days'"
        ).fetchone()
        if row:
            return int(row[0])
    return 90  # 默认90天


def set_sync_days(days: int) -> bool:
    """设置同步时间范围（天）"""
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO global_settings (key, value, updated_at)
            VALUES ('sync_days', ?, datetime('now', 'localtime'))
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
        """, (str(days),))
        conn.commit()
        return True


def get_undo_send_seconds() -> int:
    """获取发送撤销时间（秒）"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT value FROM global_settings WHERE key = 'undo_send_seconds'"
        ).fetchone()
        if row:
            return int(row[0])
    return 5  # 默认5秒


def set_undo_send_seconds(seconds: int) -> bool:
    """设置发送撤销时间（秒）"""
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO global_settings (key, value, updated_at)
            VALUES ('undo_send_seconds', ?, datetime('now', 'localtime'))
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
        """, (str(seconds),))
        conn.commit()
        return True


def get_folder_last_uid(account_id: int, folder_name: str) -> int:
    """
    获取文件夹最后同步的UID

    Args:
        account_id: 账户ID
        folder_name: 文件夹名称

    Returns:
        最后同步的UID，如果没有记录返回0
    """
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT last_uid FROM mail_folder_sync_progress WHERE account_id = ? AND folder_name = ?",
            (account_id, folder_name)
        ).fetchone()
        return row[0] if row else 0


def update_folder_last_uid(account_id: int, folder_name: str, last_uid: int) -> bool:
    """
    更新文件夹最后同步的UID

    Args:
        account_id: 账户ID
        folder_name: 文件夹名称
        last_uid: 最后同步的UID

    Returns:
        是否成功
    """
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO mail_folder_sync_progress (account_id, folder_name, last_uid, last_sync_at)
            VALUES (?, ?, ?, datetime('now', 'localtime'))
            ON CONFLICT(account_id, folder_name) DO UPDATE SET
                last_uid = excluded.last_uid,
                last_sync_at = excluded.last_sync_at
        """, (account_id, folder_name, last_uid))
        conn.commit()
        return True


def get_all_folder_last_uids(account_id: int) -> dict:
    """
    获取所有文件夹的最后同步UID

    Args:
        account_id: 账户ID

    Returns:
        {folder_name: last_uid} 字典
    """
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT folder_name, last_uid FROM mail_folder_sync_progress WHERE account_id = ?",
            (account_id,)
        ).fetchall()
        return {row[0]: row[1] for row in rows}


def get_signature() -> str:
    """获取邮件签名"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT value FROM global_settings WHERE key = 'email_signature'"
        ).fetchone()
        if row:
            return row[0] or ''
    return ''


def set_signature(signature: str) -> bool:
    """设置邮件签名"""
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO global_settings (key, value, updated_at)
            VALUES ('email_signature', ?, datetime('now', 'localtime'))
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
        """, (signature,))
        conn.commit()
        return True


def get_sync_date_range() -> tuple:
    """
    获取自定义同步日期范围

    Returns:
        (start_date, end_date) 或 (None, None)
    """
    with get_db_connection() as conn:
        start_row = conn.execute(
            "SELECT value FROM global_settings WHERE key = 'sync_start_date'"
        ).fetchone()
        end_row = conn.execute(
            "SELECT value FROM global_settings WHERE key = 'sync_end_date'"
        ).fetchone()
        if start_row and end_row:
            return (start_row[0], end_row[0])
    return (None, None)


def set_sync_date_range(start_date: str, end_date: str) -> bool:
    """
    设置自定义同步日期范围

    Args:
        start_date: 起始日期 (YYYY-MM-DD)
        end_date: 结束日期 (YYYY-MM-DD)
    """
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO global_settings (key, value, updated_at)
            VALUES ('sync_start_date', ?, datetime('now', 'localtime'))
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
        """, (start_date,))
        conn.execute("""
            INSERT INTO global_settings (key, value, updated_at)
            VALUES ('sync_end_date', ?, datetime('now', 'localtime'))
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
        """, (end_date,))
        conn.commit()
        return True


def clear_sync_date_range() -> bool:
    """清除自定义同步日期范围"""
    with get_db_connection() as conn:
        conn.execute("DELETE FROM global_settings WHERE key IN ('sync_start_date', 'sync_end_date')")
        conn.commit()
        return True


# ==================== 邮件文件夹管理 ====================

def get_folders(account_id: int = None) -> List[Dict[str, Any]]:
    """获取文件夹列表"""
    with get_db_connection() as conn:
        if account_id is not None:
            rows = conn.execute(
                "SELECT * FROM mail_folder WHERE account_id = ? OR account_id IS NULL ORDER BY sort_order, id",
                (account_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM mail_folder ORDER BY sort_order, id"
            ).fetchall()
        return [dict(row) for row in rows]


def get_folder_by_id(folder_id: int) -> Optional[Dict[str, Any]]:
    """获取单个文件夹"""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM mail_folder WHERE id = ?", (folder_id,)).fetchone()
        if row:
            return dict(row)
    return None


def get_or_create_sent_folder(account_id: int = None) -> int:
    """
    获取或创建已发送文件夹

    Args:
        account_id: 账户ID

    Returns:
        已发送文件夹ID
    """
    with get_db_connection() as conn:
        # 查找是否已存在已发送文件夹
        if account_id is not None:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '已发送' AND (account_id = ? OR account_id IS NULL)",
                (account_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '已发送'"
            ).fetchone()

        if row:
            return row[0]

        # 创建已发送文件夹
        cursor = conn.execute(
            "INSERT INTO mail_folder (folder_name, folder_icon, sort_order, account_id) VALUES (?, ?, ?, ?)",
            ('已发送', '📤', 10, account_id)
        )
        conn.commit()
        print(f"[DB] 创建已发送文件夹，ID: {cursor.lastrowid}")
        return cursor.lastrowid


def get_or_create_draft_folder(account_id: int = None) -> int:
    """
    获取或创建草稿箱文件夹

    Args:
        account_id: 账户ID

    Returns:
        草稿箱文件夹ID
    """
    with get_db_connection() as conn:
        # 查找是否已存在草稿箱文件夹
        if account_id is not None:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '草稿箱' AND (account_id = ? OR account_id IS NULL)",
                (account_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '草稿箱'"
            ).fetchone()

        if row:
            return row[0]

        # 创建草稿箱文件夹
        cursor = conn.execute(
            "INSERT INTO mail_folder (folder_name, folder_icon, sort_order, account_id) VALUES (?, ?, ?, ?)",
            ('草稿箱', '📝', 20, account_id)
        )
        conn.commit()
        print(f"[DB] 创建草稿箱文件夹，ID: {cursor.lastrowid}")
        return cursor.lastrowid


def get_or_create_spam_folder(account_id: int = None) -> int:
    """
    获取或创建垃圾邮件文件夹

    Args:
        account_id: 账户ID

    Returns:
        垃圾邮件文件夹ID
    """
    with get_db_connection() as conn:
        # 查找是否已存在垃圾邮件文件夹
        if account_id is not None:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '垃圾邮件' AND (account_id = ? OR account_id IS NULL)",
                (account_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '垃圾邮件'"
            ).fetchone()

        if row:
            return row[0]

        # 创建垃圾邮件文件夹
        cursor = conn.execute(
            "INSERT INTO mail_folder (folder_name, folder_icon, sort_order, account_id) VALUES (?, ?, ?, ?)",
            ('垃圾邮件', '🗑️', 100, account_id)
        )
        conn.commit()
        print(f"[DB] 创建垃圾邮件文件夹，ID: {cursor.lastrowid}")
        return cursor.lastrowid


def get_or_create_system_folder(account_id: int = None) -> int:
    """
    获取或创建系统邮件文件夹

    Args:
        account_id: 账户ID

    Returns:
        系统邮件文件夹ID
    """
    with get_db_connection() as conn:
        # 查找是否已存在系统邮件文件夹
        if account_id is not None:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '系统邮件' AND (account_id = ? OR account_id IS NULL)",
                (account_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '系统邮件'"
            ).fetchone()

        if row:
            return row[0]

        # 创建系统邮件文件夹
        cursor = conn.execute(
            "INSERT INTO mail_folder (folder_name, folder_icon, sort_order, account_id) VALUES (?, ?, ?, ?)",
            ('系统邮件', '🔔', 90, account_id)
        )
        conn.commit()
        print(f"[DB] 创建系统邮件文件夹，ID: {cursor.lastrowid}")
        return cursor.lastrowid


def get_or_create_blacklist_folder(account_id: int = None) -> int:
    """
    获取或创建黑名单文件夹

    Args:
        account_id: 账户ID

    Returns:
        黑名单文件夹ID
    """
    with get_db_connection() as conn:
        # 查找是否已存在黑名单文件夹
        if account_id is not None:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '黑名单' AND (account_id = ? OR account_id IS NULL)",
                (account_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT id FROM mail_folder WHERE folder_name = '黑名单'"
            ).fetchone()

        if row:
            return row[0]

        # 创建黑名单文件夹
        cursor = conn.execute(
            "INSERT INTO mail_folder (folder_name, folder_icon, sort_order, account_id) VALUES (?, ?, ?, ?)",
            ('黑名单', '🚫', 110, account_id)
        )
        conn.commit()
        print(f"[DB] 创建黑名单文件夹，ID: {cursor.lastrowid}")
        return cursor.lastrowid


def add_folder(folder_data: Dict[str, Any]) -> int:
    """添加文件夹"""
    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO mail_folder (folder_name, folder_icon, sort_order, account_id)
            VALUES (?, ?, ?, ?)
        """, (
            folder_data.get('folder_name'),
            folder_data.get('folder_icon', 'folder'),
            folder_data.get('sort_order', 0),
            folder_data.get('account_id')
        ))
        conn.commit()
        return cursor.lastrowid


def update_folder(folder_id: int, folder_data: Dict[str, Any]) -> bool:
    """更新文件夹"""
    with get_db_connection() as conn:
        result = conn.execute("""
            UPDATE mail_folder SET folder_name = ?, folder_icon = ?, sort_order = ?
            WHERE id = ?
        """, (
            folder_data.get('folder_name'),
            folder_data.get('folder_icon', 'folder'),
            folder_data.get('sort_order', 0),
            folder_id
        ))
        conn.commit()
        return result.rowcount > 0


def delete_folder(folder_id: int) -> bool:
    """删除文件夹（关联邮件移回收件箱）"""
    with get_db_connection() as conn:
        # 将该文件夹的邮件移回收件箱（folder_id = NULL）
        conn.execute("UPDATE uni_mail SET folder_id = NULL WHERE folder_id = ?", (folder_id,))
        # 删除文件夹（规则会级联删除）
        result = conn.execute("DELETE FROM mail_folder WHERE id = ?", (folder_id,))
        conn.commit()
        return result.rowcount > 0


def get_mail_count_by_folder(folder_id: int, account_id: int = None) -> int:
    """获取文件夹中的邮件数量"""
    with get_db_connection() as conn:
        if account_id is not None:
            row = conn.execute(
                "SELECT COUNT(*) FROM uni_mail WHERE folder_id = ? AND account_id = ? AND is_sent = 0",
                (folder_id, account_id)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM uni_mail WHERE folder_id = ? AND is_sent = 0",
                (folder_id,)
            ).fetchone()
        return row[0] if row else 0


# ==================== 邮件过滤规则管理 ====================

def get_filter_rules(folder_id: int = None) -> List[Dict[str, Any]]:
    """获取过滤规则列表"""
    with get_db_connection() as conn:
        if folder_id:
            rows = conn.execute(
                "SELECT r.*, f.folder_name FROM mail_filter_rule r " +
                "LEFT JOIN mail_folder f ON r.folder_id = f.id " +
                "WHERE r.folder_id = ? ORDER BY r.priority DESC, r.id",
                (folder_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT r.*, f.folder_name FROM mail_filter_rule r " +
                "LEFT JOIN mail_folder f ON r.folder_id = f.id " +
                "ORDER BY r.priority DESC, r.id"
            ).fetchall()
        return [dict(row) for row in rows]


def add_filter_rule(rule_data: Dict[str, Any]) -> int:
    """添加过滤规则"""
    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO mail_filter_rule (folder_id, keyword, priority, is_enabled)
            VALUES (?, ?, ?, ?)
        """, (
            rule_data.get('folder_id'),
            rule_data.get('keyword'),
            rule_data.get('priority', 0),
            rule_data.get('is_enabled', 1)
        ))
        conn.commit()
        return cursor.lastrowid


def update_filter_rule(rule_id: int, rule_data: Dict[str, Any]) -> bool:
    """更新过滤规则"""
    with get_db_connection() as conn:
        result = conn.execute("""
            UPDATE mail_filter_rule SET keyword = ?, priority = ?, is_enabled = ?
            WHERE id = ?
        """, (
            rule_data.get('keyword'),
            rule_data.get('priority', 0),
            rule_data.get('is_enabled', 1),
            rule_id
        ))
        conn.commit()
        return result.rowcount > 0


def delete_filter_rule(rule_id: int) -> bool:
    """删除过滤规则"""
    with get_db_connection() as conn:
        result = conn.execute("DELETE FROM mail_filter_rule WHERE id = ?", (rule_id,))
        conn.commit()
        return result.rowcount > 0


# ==================== 自动分类功能 ====================

def auto_classify_emails(account_id: int = None) -> Dict[str, int]:
    """
    自动分类邮件（根据规则匹配标题）
    支持多关键词，用逗号分隔，如：报价,invoice,quote

    Returns:
        {classified_count: 已分类邮件数, rule_count: 使用规则数}
    """
    # 获取所有启用的规则，按优先级降序
    with get_db_connection() as conn:
        rules = conn.execute("""
            SELECT r.*, f.folder_name
            FROM mail_filter_rule r
            JOIN mail_folder f ON r.folder_id = f.id
            WHERE r.is_enabled = 1
            ORDER BY r.priority DESC, r.id
        """).fetchall()

        if not rules:
            return {"classified_count": 0, "rule_count": 0}

        # 获取未分类的收件箱邮件
        if account_id is not None:
            emails = conn.execute("""
                SELECT id, subject FROM uni_mail
                WHERE is_sent = 0 AND folder_id IS NULL AND account_id = ?
            """, (account_id,)).fetchall()
        else:
            emails = conn.execute("""
                SELECT id, subject FROM uni_mail
                WHERE is_sent = 0 AND folder_id IS NULL
            """).fetchall()

        classified_count = 0

        for email in emails:
            email_id = email['id']
            subject = email['subject'] or ''

            # 按优先级顺序匹配规则
            for rule in rules:
                keyword_str = rule['keyword'] or ''
                # 支持多关键词，用逗号分隔
                keywords = [k.strip().lower() for k in keyword_str.split(',') if k.strip()]
                if any(kw in subject.lower() for kw in keywords):
                    # 匹配成功，更新邮件的文件夹
                    conn.execute(
                        "UPDATE uni_mail SET folder_id = ? WHERE id = ?",
                        (rule['folder_id'], email_id)
                    )
                    classified_count += 1
                    break  # 只匹配第一个符合条件的规则

        conn.commit()

    return {"classified_count": classified_count, "rule_count": len(rules)}


def get_mails_by_folder(folder_id: int, page: int = 1, limit: int = 20,
                        search: str = None, account_id: int = None) -> Dict[str, Any]:
    """获取指定文件夹的邮件列表"""
    offset = (page - 1) * limit
    params = [folder_id]
    count_params = [folder_id]

    # 列表视图只查询必要字段，避免加载大字段
    select_fields = "id, subject, from_addr, from_name, to_addr, received_at, sent_at, is_sent, is_read, message_id, account_id, folder_id, created_at"

    query = f"SELECT {select_fields} FROM uni_mail WHERE folder_id = ? AND is_sent = 0"
    count_query = "SELECT COUNT(*) FROM uni_mail WHERE folder_id = ? AND is_sent = 0"

    if account_id is not None:
        query += " AND account_id = ?"
        count_query += " AND account_id = ?"
        params.append(account_id)
        count_params.append(account_id)

    if search:
        query += " AND (subject LIKE ? OR from_addr LIKE ?)"
        count_query += " AND (subject LIKE ? OR from_addr LIKE ?)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param])
        count_params.extend([search_param, search_param])

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
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

def get_latest_mail_time(account_id: int = None, is_sent: int = 0) -> Optional[str]:
    """
    获取最新邮件的时间（用于增量同步）

    Args:
        account_id: 账户ID
        is_sent: 0=收件箱, 1=已发送

    Returns:
        ISO格式的时间字符串，或None
    """
    with get_db_connection() as conn:
        if account_id is not None:
            row = conn.execute("""
                SELECT MAX(received_at) as latest_time FROM uni_mail
                WHERE is_sent = ? AND account_id = ?
            """, (is_sent, account_id)).fetchone()
        else:
            row = conn.execute("""
                SELECT MAX(received_at) as latest_time FROM uni_mail
                WHERE is_sent = ?
            """, (is_sent,)).fetchone()

        if row and row["latest_time"]:
            return row["latest_time"]
    return None


def get_local_uids(folder: str, account_id: int) -> set:
    """
    获取本地已存储的邮件UID集合（用于增量同步优化）

    Args:
        folder: 邮箱文件夹名称（如 'INBOX'）
        account_id: 账户ID

    Returns:
        UID集合
    """
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT imap_uid FROM uni_mail WHERE imap_folder = ? AND account_id = ? AND imap_uid IS NOT NULL",
            (folder, account_id)
        ).fetchall()
        return {row[0] for row in rows if row[0] is not None}


def get_local_message_ids(account_id: int) -> set:
    """
    获取本地已存储的邮件Message-ID集合（备用方案）

    Args:
        account_id: 账户ID

    Returns:
        Message-ID集合
    """
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT message_id FROM uni_mail WHERE account_id = ? AND message_id IS NOT NULL",
            (account_id,)
        ).fetchall()
        return {row[0] for row in rows if row[0] is not None}


def cleanup_duplicate_emails(account_id: int = None) -> dict:
    """
    清理重复邮件，保留最早的一条

    Args:
        account_id: 指定账户ID，为None时清理所有账户

    Returns:
        {"deleted": 删除数量, "kept": 保留数量}
    """
    with get_db_connection() as conn:
        # 查找重复邮件（相同imap_uid + imap_folder + account_id）
        if account_id:
            duplicates = conn.execute("""
                SELECT imap_uid, imap_folder, account_id, COUNT(*) as cnt,
                       GROUP_CONCAT(id ORDER BY id) as ids
                FROM uni_mail
                WHERE imap_uid IS NOT NULL AND account_id = ?
                GROUP BY imap_uid, imap_folder, account_id
                HAVING COUNT(*) > 1
            """, (account_id,)).fetchall()
        else:
            duplicates = conn.execute("""
                SELECT imap_uid, imap_folder, account_id, COUNT(*) as cnt,
                       GROUP_CONCAT(id ORDER BY id) as ids
                FROM uni_mail
                WHERE imap_uid IS NOT NULL
                GROUP BY imap_uid, imap_folder, account_id
                HAVING COUNT(*) > 1
            """).fetchall()

        deleted_count = 0
        kept_count = 0

        for row in duplicates:
            ids = row['ids'].split(',')
            # 保留第一个（最早插入的），删除其余的
            keep_id = ids[0]
            delete_ids = ids[1:]

            if delete_ids:
                placeholders = ','.join('?' * len(delete_ids))
                conn.execute(f"DELETE FROM uni_mail WHERE id IN ({placeholders})", delete_ids)
                deleted_count += len(delete_ids)
                kept_count += 1

        conn.commit()
        return {"deleted": deleted_count, "kept": kept_count}


def clear_account_emails(account_id: int) -> dict:
    """
    清空指定账户的所有本地邮件

    Args:
        account_id: 账户ID

    Returns:
        {"deleted": 删除数量}
    """
    with get_db_connection() as conn:
        result = conn.execute(
            "DELETE FROM uni_mail WHERE account_id = ?",
            (account_id,)
        )
        conn.commit()
        return {"deleted": result.rowcount}


# ==================== 已同步UID记录 ====================

def record_synced_uid(account_id: int, imap_uid: int, imap_folder: str) -> bool:
    """
    记录已同步的邮件UID

    Args:
        account_id: 账户ID
        imap_uid: 邮件UID
        imap_folder: 文件夹名称

    Returns:
        是否成功
    """
    with get_db_connection() as conn:
        try:
            conn.execute("""
                INSERT INTO uni_mail_synced_uid (account_id, imap_uid, imap_folder)
                VALUES (?, ?, ?)
                ON CONFLICT(account_id, imap_uid, imap_folder) DO NOTHING
            """, (account_id, imap_uid, imap_folder))
            conn.commit()
            return True
        except Exception as e:
            print(f"Record synced UID error: {e}")
            return False


def batch_record_synced_uids(account_id: int, uid_folder_pairs: list) -> bool:
    """
    批量记录已同步的邮件UID

    Args:
        account_id: 账户ID
        uid_folder_pairs: [(uid, folder), ...] 列表

    Returns:
        是否成功
    """
    if not uid_folder_pairs:
        return True

    with get_db_connection() as conn:
        try:
            for uid, folder in uid_folder_pairs:
                conn.execute("""
                    INSERT INTO uni_mail_synced_uid (account_id, imap_uid, imap_folder)
                    VALUES (?, ?, ?)
                    ON CONFLICT(account_id, imap_uid, imap_folder) DO NOTHING
                """, (account_id, uid, folder))
            conn.commit()
            return True
        except Exception as e:
            print(f"Batch record synced UIDs error: {e}")
            return False


def get_synced_uids(account_id: int, folder: str = None) -> set:
    """
    获取已同步的UID集合

    Args:
        account_id: 账户ID
        folder: 文件夹名称，None表示所有文件夹

    Returns:
        已同步的UID集合（返回(uid, folder)元组集合或仅uid集合）
    """
    with get_db_connection() as conn:
        if folder:
            rows = conn.execute(
                "SELECT imap_uid FROM uni_mail_synced_uid WHERE account_id = ? AND imap_folder = ?",
                (account_id, folder)
            ).fetchall()
            return {row[0] for row in rows}
        else:
            rows = conn.execute(
                "SELECT imap_uid, imap_folder FROM uni_mail_synced_uid WHERE account_id = ?",
                (account_id,)
            ).fetchall()
            return {(row[0], row[1]) for row in rows}


def is_uid_synced(account_id: int, imap_uid: int, imap_folder: str) -> bool:
    """
    检查UID是否已同步过

    Args:
        account_id: 账户ID
        imap_uid: 邮件UID
        imap_folder: 文件夹名称

    Returns:
        是否已同步过
    """
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT 1 FROM uni_mail_synced_uid
            WHERE account_id = ? AND imap_uid = ? AND imap_folder = ?
        """, (account_id, imap_uid, imap_folder)).fetchone()
        return row is not None


def get_sync_deleted_setting() -> bool:
    """
    获取"同步已删除邮件"开关设置

    Returns:
        True表示开启（同步已删除邮件），False表示关闭
    """
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT value FROM global_settings WHERE key = 'sync_deleted_emails'"
        ).fetchone()
        # 默认开启（True）
        if row is None:
            return True
        return row[0].lower() in ('true', '1', 'yes')


def set_sync_deleted_setting(enabled: bool) -> bool:
    """
    设置"同步已删除邮件"开关

    Args:
        enabled: True表示开启，False表示关闭

    Returns:
        是否成功
    """
    with get_db_connection() as conn:
        try:
            conn.execute("""
                INSERT OR REPLACE INTO global_settings (key, value, updated_at)
                VALUES ('sync_deleted_emails', ?, datetime('now', 'localtime'))
            """, (str(enabled).lower(),))
            conn.commit()
            return True
        except Exception as e:
            print(f"Set sync deleted setting error: {e}")
            return False

