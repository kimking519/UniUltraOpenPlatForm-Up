"""
邮件数据库操作层 - 核心模块
包含：邮件列表、保存/删除、草稿箱、关联关系
"""
from typing import Optional, Dict, List, Any
from Sills.base import get_db_connection
from Sills.db_config import get_datetime_now


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
        # 2026-06-11: 新增 content 搜索 - 支持搜邮件正文（用于验证自动分类回写情况）
        query += " AND (subject LIKE ? OR from_addr LIKE ? OR to_addr LIKE ? OR content LIKE ?)"
        count_query += " AND (subject LIKE ? OR from_addr LIKE ? OR to_addr LIKE ? OR content LIKE ?)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param, search_param])
        count_params.extend([search_param, search_param, search_param, search_param])

    query += " ORDER BY received_at DESC, id DESC LIMIT ? OFFSET ?"
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
        # 2026-06-11: 新增 content 搜索
        query += " AND (subject LIKE ? OR from_addr LIKE ? OR to_addr LIKE ? OR content LIKE ?)"
        count_query += " AND (subject LIKE ? OR from_addr LIKE ? OR to_addr LIKE ? OR content LIKE ?)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param, search_param])
        count_params.extend([search_param, search_param, search_param, search_param])

    query += " ORDER BY deleted_at DESC, id DESC LIMIT ? OFFSET ?"
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

            # 检查重复并更新is_sent/is_draft
            existing_id = None
            if imap_uid and imap_folder and account_id:
                existing = conn.execute(
                    "SELECT id, is_sent, is_draft FROM uni_mail WHERE imap_uid = ? AND imap_folder = ? AND account_id = ?",
                    (imap_uid, imap_folder, account_id)
                ).fetchone()
                if existing:
                    existing_id = existing[0]
                    # 如果is_sent或is_draft不同，更新它们
                    new_is_sent = mail_data.get('is_sent', 0)
                    new_is_draft = mail_data.get('is_draft', 0)
                    if existing[1] != new_is_sent or existing[2] != new_is_draft:
                        conn.execute(
                            "UPDATE uni_mail SET is_sent = ?, is_draft = ? WHERE id = ?",
                            (new_is_sent, new_is_draft, existing_id)
                        )

            if not existing_id and message_id:
                existing = conn.execute(
                    "SELECT id, is_sent, is_draft FROM uni_mail WHERE message_id = ?",
                    (message_id,)
                ).fetchone()
                if existing:
                    existing_id = existing[0]
                    # 如果is_sent或is_draft不同，更新它们
                    new_is_sent = mail_data.get('is_sent', 0)
                    new_is_draft = mail_data.get('is_draft', 0)
                    if existing[1] != new_is_sent or existing[2] != new_is_draft:
                        conn.execute(
                            "UPDATE uni_mail SET is_sent = ?, is_draft = ? WHERE id = ?",
                            (new_is_sent, new_is_draft, existing_id)
                        )

            if existing_id:
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
    dt_now = get_datetime_now()
    with get_db_connection() as conn:
        # 软删除：设置 is_deleted = 1
        result = conn.execute(f"""
            UPDATE uni_mail SET is_deleted = 1, deleted_at = {dt_now} WHERE id = ?
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
    dt_now = get_datetime_now()
    with get_db_connection() as conn:
        placeholders = ','.join('?' * len(mail_ids))
        # 软删除：设置 is_deleted = 1
        result = conn.execute(f"UPDATE uni_mail SET is_deleted = 1, deleted_at = {dt_now} WHERE id IN ({placeholders})", mail_ids)
        conn.commit()
        return result.rowcount


def batch_permanently_delete_emails(mail_ids: list) -> int:
    """批量永久删除邮件"""
    if not mail_ids:
        return 0
    with get_db_connection() as conn:
        placeholders = ','.join('?' * len(mail_ids))
        # 先删除关联关系
        conn.execute(f"DELETE FROM uni_mail_rel WHERE mail_id IN ({placeholders})", mail_ids)
        # 再永久删除邮件
        result = conn.execute(f"DELETE FROM uni_mail WHERE id IN ({placeholders})", mail_ids)
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
        # 2026-06-11: 新增 from_addr 和 content 搜索，对齐其他列表行为
        query += " AND (subject LIKE ? OR from_addr LIKE ? OR to_addr LIKE ? OR content LIKE ?)"
        count_query += " AND (subject LIKE ? OR from_addr LIKE ? OR to_addr LIKE ? OR content LIKE ?)"
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param, search_param])
        count_params.extend([search_param, search_param, search_param, search_param])

    # 草稿按received_at排序，与前端显示的日期一致
    query += " ORDER BY received_at DESC NULLS LAST, id DESC LIMIT ? OFFSET ?"
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


# ============ 邮件关联关系 ============

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
        # 清空邮件
        result = conn.execute(
            "DELETE FROM uni_mail WHERE account_id = ?",
            (account_id,)
        )
        deleted_count = result.rowcount
        # 同时清理已同步UID记录，确保重新同步时能获取所有邮件
        uid_result = conn.execute(
            "DELETE FROM uni_mail_synced_uid WHERE account_id = ?",
            (account_id,)
        )
        uid_deleted = uid_result.rowcount if hasattr(uid_result, 'rowcount') else 0
        conn.commit()
        print(f"[DB] 清空账户 {account_id} 邮件: 删除 {deleted_count} 封邮件, 清理 {uid_deleted} 条同步记录")
        return {"deleted": deleted_count, "synced_uids_cleared": uid_deleted}