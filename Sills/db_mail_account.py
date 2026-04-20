"""
邮件数据库操作层 - 账户管理模块
包含：邮件账户配置、添加、更新、删除、切换
使用 uni_email_account 表（迁移自 mail_config）
"""
from typing import Optional, Dict, List, Any
from datetime import datetime
from Sills.base import get_db_connection
from Sills.crypto_utils import encrypt_password, decrypt_password


def get_next_account_id():
    """获取下一个邮件账号ID (EA+时间戳格式)"""
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    return f"EA{timestamp}"


def get_mail_config() -> Optional[Dict[str, Any]]:
    """获取当前邮件账户配置（解密密码）"""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM uni_email_account WHERE is_current = 1").fetchone()
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
            SELECT account_id, account_name, smtp_server, smtp_port,
                   imap_server, imap_port, email, username, use_tls,
                   is_current, is_primary, daily_limit
            FROM uni_email_account
            ORDER BY is_current DESC, created_at DESC
        """).fetchall()
        return [dict(row) for row in rows]


def get_mail_account_by_id(account_id: str) -> Optional[Dict[str, Any]]:
    """获取指定邮件账户（解密密码）"""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM uni_email_account WHERE account_id = ?", (account_id,)).fetchone()
        if row:
            config = dict(row)
            if config.get('password'):
                try:
                    config['password'] = decrypt_password(config['password'])
                except Exception:
                    pass
            return config
    return None


def add_mail_account(config: Dict[str, Any]) -> str:
    """添加新邮件账户，返回 account_id"""
    # 检查重复账号（邮箱或账户名称）
    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT account_id FROM uni_email_account WHERE email = ? OR account_name = ?",
            (config.get('email'), config.get('account_name'))
        ).fetchone()
        if existing:
            raise ValueError("该邮箱账号已存在，不能重复添加")

    password = config.get('password', '')
    if password:
        try:
            password = encrypt_password(password)
        except Exception:
            pass

    account_id = get_next_account_id()

    with get_db_connection() as conn:
        # 如果是第一个账户，自动设为当前账户
        count = conn.execute("SELECT COUNT(*) FROM uni_email_account").fetchone()[0]
        is_current = 1 if count == 0 else 0

        conn.execute("""
            INSERT INTO uni_email_account (
                account_id, account_name, email, username, password,
                smtp_server, smtp_port, imap_server, imap_port,
                use_tls, is_current, is_primary, daily_limit
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1800)
        """, (
            account_id,
            config.get('account_name', '新账户'),
            config.get('email'),
            config.get('username') or config.get('email'),
            password,
            config.get('smtp_server'),
            config.get('smtp_port', 465),
            config.get('imap_server'),
            config.get('imap_port', 993),
            config.get('use_tls', 1),
            is_current,
            is_current,
        ))
        conn.commit()
        return account_id


def update_mail_account(account_id: str, config: Dict[str, Any]) -> bool:
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
            'email': config.get('email'),
            'username': config.get('username'),
            'smtp_server': config.get('smtp_server'),
            'smtp_port': config.get('smtp_port'),
            'imap_server': config.get('imap_server'),
            'imap_port': config.get('imap_port'),
            'use_tls': config.get('use_tls'),
            'sync_batch_size': config.get('sync_batch_size'),
            'sync_pause_seconds': config.get('sync_pause_seconds'),
            'daily_limit': config.get('daily_limit'),
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

        update_fields.append("updated_at = NOW()")
        params.append(account_id)
        sql = f"UPDATE uni_email_account SET {', '.join(update_fields)} WHERE account_id = ?"

        conn.execute(sql, params)
        conn.commit()
        return True


def switch_current_account(account_id: str) -> bool:
    """切换当前邮件账户"""
    with get_db_connection() as conn:
        # 先取消所有账户的当前状态
        conn.execute("UPDATE uni_email_account SET is_current = 0")
        # 设置指定账户为当前账户
        result = conn.execute("UPDATE uni_email_account SET is_current = 1 WHERE account_id = ?", (account_id,))
        conn.commit()
        return result.rowcount > 0


def delete_mail_account(account_id: str) -> Dict[str, Any]:
    """删除邮件账户"""
    with get_db_connection() as conn:
        # 检查是否是当前账户
        row = conn.execute("SELECT is_current FROM uni_email_account WHERE account_id = ?", (account_id,)).fetchone()
        if not row:
            return {"success": False, "message": "账户不存在"}

        was_current = row.get('is_current') == 1

        # 删除账户
        conn.execute("DELETE FROM uni_email_account WHERE account_id = ?", (account_id,))

        # 如果删除的是当前账户，自动选择下一个账户
        if was_current:
            next_row = conn.execute("SELECT account_id FROM uni_email_account ORDER BY created_at DESC LIMIT 1").fetchone()
            if next_row:
                conn.execute("UPDATE uni_email_account SET is_current = 1 WHERE account_id = ?", (next_row.get('account_id'),))

        conn.commit()
        return {"success": True, "message": "删除成功"}