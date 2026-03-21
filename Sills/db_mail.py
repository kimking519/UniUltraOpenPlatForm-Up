"""
邮件数据库操作层
SmartMail Integration - Database Operations
"""
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from Sills.base import get_db_connection
from Sills.crypto_utils import encrypt_password, decrypt_password


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

    query = "SELECT * FROM uni_mail WHERE is_sent = ? AND is_deleted = 0"
    count_query = "SELECT COUNT(*) FROM uni_mail WHERE is_sent = ? AND is_deleted = 0"

    # 收件箱只显示未分类的邮件（folder_id IS NULL）
    if is_sent == 0:
        query += " AND folder_id IS NULL"
        count_query += " AND folder_id IS NULL"

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

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    with get_db_connection() as conn:
        total_count = conn.execute(count_query, count_params).fetchone()[0]
        rows = conn.execute(query, params).fetchall()

    items = []
    for row in rows:
        item = dict(row)
        # 截断内容预览，清理HTML标签
        content = item.get('content', '') or ''
        # 移除HTML标签
        import re
        content_clean = re.sub(r'<[^>]+>', '', content)
        content_clean = re.sub(r'\s+', ' ', content_clean).strip()
        item['content_preview'] = content_clean[:100]
        item['body_truncated'] = len(content_clean) > 100
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

    query = "SELECT * FROM uni_mail WHERE is_deleted = 1"
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
        import re
        content = item.get('content', '') or ''
        content_clean = re.sub(r'<[^>]+>', '', content)
        content_clean = re.sub(r'\s+', ' ', content_clean).strip()
        item['content_preview'] = content_clean[:100]
        item['body_truncated'] = len(content_clean) > 100
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
    保存邮件到数据库

    Args:
        mail_data: 邮件数据字典

    Returns:
        新邮件的ID
    """
    # 将空字符串的message_id转为None，避免唯一约束冲突
    message_id = mail_data.get('message_id')
    if message_id == '':
        message_id = None

    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO uni_mail (subject, from_addr, from_name, to_addr, cc_addr, content, html_content,
                                  received_at, sent_at, is_sent, message_id, sync_status, account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mail_data.get('subject'),
            mail_data.get('from_addr'),
            mail_data.get('from_name'),
            mail_data.get('to_addr'),
            mail_data.get('cc_addr'),
            mail_data.get('content'),
            mail_data.get('html_content'),
            mail_data.get('received_at'),
            mail_data.get('sent_at'),
            mail_data.get('is_sent', 0),
            message_id,
            mail_data.get('sync_status', 'completed'),
            mail_data.get('account_id')
        ))
        conn.commit()
        return cursor.lastrowid


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
    """批量删除邮件"""
    if not mail_ids:
        return 0
    with get_db_connection() as conn:
        # 删除关联关系
        placeholders = ','.join('?' * len(mail_ids))
        conn.execute(f"DELETE FROM uni_mail_rel WHERE mail_id IN ({placeholders})", mail_ids)
        # 删除邮件
        result = conn.execute(f"DELETE FROM uni_mail WHERE id IN ({placeholders})", mail_ids)
        conn.commit()
        return result.rowcount


def mark_email_read(mail_id: int) -> bool:
    """标记邮件为已读"""
    with get_db_connection() as conn:
        conn.execute("UPDATE uni_mail SET is_read = 1 WHERE id = ?", (mail_id,))
        conn.commit()
        return True


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
                expires = datetime.fromisoformat(lock['expires_at'])
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


def update_sync_progress(current: int, total: int, message: str = "") -> bool:
    """
    更新同步进度

    Args:
        current: 当前进度
        total: 总数
        message: 进度消息

    Returns:
        是否更新成功
    """
    with get_db_connection() as conn:
        conn.execute("""
            UPDATE mail_sync_lock
            SET progress_current = ?, progress_total = ?, progress_message = ?
            WHERE id = 1
        """, (current, total, message))
        conn.commit()
        return True


def get_sync_progress() -> Dict[str, Any]:
    """
    获取同步进度

    Returns:
        {syncing: bool, current: int, total: int, message: str}
    """
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM mail_sync_lock WHERE id = 1").fetchone()
        if row:
            lock = dict(row)
            if lock.get('expires_at'):
                expires = datetime.fromisoformat(lock['expires_at'])
                if expires > datetime.now():
                    return {
                        "syncing": True,
                        "current": lock.get('progress_current', 0) or 0,
                        "total": lock.get('progress_total', 0) or 0,
                        "message": lock.get('progress_message', '') or '',
                        "status": "syncing"
                    }
    return {"syncing": False, "current": 0, "total": 0, "message": "", "status": "idle"}


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
                expires = datetime.fromisoformat(lock['expires_at'])
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

    query = "SELECT * FROM uni_mail WHERE folder_id = ? AND is_sent = 0"
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
        content = item.get('content', '') or ''
        import re
        content_clean = re.sub(r'<[^>]+>', '', content)
        content_clean = re.sub(r'\s+', ' ', content_clean).strip()
        item['content_preview'] = content_clean[:100]
        item['body_truncated'] = len(content_clean) > 100
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

