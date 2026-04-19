"""
邮件数据库操作层 - 账户管理模块
包含：邮件账户配置、添加、更新、删除、切换
"""
from typing import Optional, Dict, List, Any
from Sills.base import get_db_connection
from Sills.crypto_utils import encrypt_password, decrypt_password


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
    from Sills.db_config import is_postgresql

    # 检查重复账号（用户名或账户名称）
    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM mail_config WHERE username = ? OR account_name = ?",
            (config.get('username'), config.get('account_name'))
        ).fetchone()
        if existing:
            raise ValueError("该邮箱账号已存在，不能重复添加")

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

        if is_postgresql():
            # PostgreSQL 使用 RETURNING id
            row = conn.execute("""
                INSERT INTO mail_config (account_name, smtp_server, smtp_port, imap_server,
                                         imap_port, username, password, use_tls, is_current)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                RETURNING id
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
            )).fetchone()
            conn.commit()
            return row['id'] if isinstance(row, dict) else row[0]
        else:
            # SQLite 使用 lastrowid
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