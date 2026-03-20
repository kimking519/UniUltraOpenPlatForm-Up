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

    query = "SELECT * FROM uni_mail WHERE is_sent = ?"
    count_query = "SELECT COUNT(*) FROM uni_mail WHERE is_sent = ?"

    # 用户隔离：按账户ID过滤（兼容旧数据：account_id IS NULL）
    if account_id is not None:
        query += " AND (account_id = ? OR account_id IS NULL)"
        count_query += " AND (account_id = ? OR account_id IS NULL)"
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
        # 截断内容预览
        content = item.get('content', '') or ''
        item['content_preview'] = content[:500]
        item['body_truncated'] = len(content) > 500
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


def save_email(mail_data: Dict[str, Any]) -> int:
    """
    保存邮件到数据库

    Args:
        mail_data: 邮件数据字典

    Returns:
        新邮件的ID
    """
    with get_db_connection() as conn:
        cursor = conn.execute("""
            INSERT INTO uni_mail (subject, from_addr, to_addr, cc_addr, content, html_content,
                                  received_at, sent_at, is_sent, message_id, sync_status, account_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            mail_data.get('subject'),
            mail_data.get('from_addr'),
            mail_data.get('to_addr'),
            mail_data.get('cc_addr'),
            mail_data.get('content'),
            mail_data.get('html_content'),
            mail_data.get('received_at'),
            mail_data.get('sent_at'),
            mail_data.get('is_sent', 0),
            mail_data.get('message_id'),
            mail_data.get('sync_status', 'completed'),
            mail_data.get('account_id')
        ))
        conn.commit()
        return cursor.lastrowid


def delete_email(mail_id: int) -> bool:
    """删除邮件"""
    with get_db_connection() as conn:
        # 先删除关联关系
        conn.execute("DELETE FROM uni_mail_rel WHERE mail_id = ?", (mail_id,))
        result = conn.execute("DELETE FROM uni_mail WHERE id = ?", (mail_id,))
        conn.commit()
        return result.rowcount > 0


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

        # 获取或更新锁
        conn.execute("""
            INSERT INTO mail_sync_lock (id, locked_at, locked_by, expires_at)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                locked_at = excluded.locked_at,
                locked_by = excluded.locked_by,
                expires_at = excluded.expires_at
        """, (now.isoformat(), lock_id, expires_at.isoformat()))
        conn.commit()
        return True


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