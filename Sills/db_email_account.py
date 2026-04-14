"""
发件人账号管理数据库操作模块
用于邮件任务管理中的发件人账号设置
"""
import sqlite3
from datetime import datetime, date
from Sills.base import get_db_connection
from Sills.crypto_utils import encrypt_password, decrypt_password  # AES加密


def get_next_account_id():
    """获取下一个账号ID (EA+时间戳+随机数格式)"""
    import random
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    rand_suffix = random.randint(1000, 9999)
    return f"EA{timestamp}{rand_suffix}"


def get_account_list(page=1, page_size=20, search_kw=""):
    """获取发件人账号列表"""
    offset = (page - 1) * page_size
    where_clause = ""
    params = []

    if search_kw:
        where_clause = "WHERE email LIKE ?"
        params = [f"%{search_kw}%"]

    query = f"""
    SELECT account_id, email, smtp_server, daily_limit, sent_today, last_reset_date, created_at
    FROM uni_email_account
    {where_clause}
    ORDER BY created_at DESC
    LIMIT ? OFFSET ?
    """

    count_query = f"SELECT COUNT(*) FROM uni_email_account {where_clause}"

    with get_db_connection() as conn:
        total = conn.execute(count_query, params).fetchone()[0]
        items = conn.execute(query, params + [page_size, offset]).fetchall()
        results = [
            {k: ("" if v is None else v) for k, v in dict(row).items()}
            for row in items
        ]
        # 不返回password字段
        return results, total


def get_account_by_id(account_id):
    """根据ID获取账号详情(包含密码)"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM uni_email_account WHERE account_id = ?",
            (account_id,)
        ).fetchone()
        if row:
            data = {k: ("" if v is None else v) for k, v in dict(row).items()}
            # 解密密码
            if data.get('password'):
                try:
                    data['password'] = decrypt_password(data['password'])
                except:
                    pass  # 解密失败则返回原始值
            return data
        return None


def get_account_by_email(email):
    """根据邮箱获取账号"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM uni_email_account WHERE email = ?",
            (email.lower(),)
        ).fetchone()
        if row:
            data = {k: ("" if v is None else v) for k, v in dict(row).items()}
            if data.get('password'):
                try:
                    data['password'] = decrypt_password(data['password'])
                except:
                    pass
            return data
        return None


def add_account(email, password, smtp_server=None, daily_limit=1800):
    """添加发件人账号

    Args:
        email: 发件人邮箱
        password: 密码(明文,会自动AES加密)
        smtp_server: SMTP服务器,默认根据邮箱判断
        daily_limit: 每日发送限制

    Returns:
        (success, message) tuple
    """
    try:
        if not email or not email.strip():
            return False, "邮箱不能为空"
        if not password or not password.strip():
            return False, "密码不能为空"

        email = email.strip().lower()

        # 检查是否已存在
        existing = get_account_by_email(email)
        if existing:
            return False, f"邮箱 {email} 已存在"

        # 根据邮箱自动判断SMTP服务器
        if not smtp_server:
            if "163.com" in email:
                smtp_server = "smtp.163.com"
            elif "qiye.163.com" in email or "unicornsemi.com" in email:
                smtp_server = "smtphz.qiye.163.com"
            else:
                smtp_server = "smtp.163.com"  # 默认163

        account_id = get_next_account_id()

        # AES加密密码
        encrypted_password = encrypt_password(password.strip())

        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO uni_email_account (account_id, email, password, smtp_server, daily_limit, sent_today, last_reset_date)
                VALUES (?, ?, ?, ?, ?, 0, ?)
            """, (account_id, email, encrypted_password, smtp_server, daily_limit, date.today().isoformat()))
            conn.commit()

        return True, f"发件人账号 {account_id} 创建成功"
    except Exception as e:
        return False, str(e)


def update_account(account_id, password=None, smtp_server=None, daily_limit=None):
    """更新发件人账号"""
    try:
        updates = []
        params = []

        if password and password.strip():
            updates.append("password = ?")
            params.append(encrypt_password(password.strip()))

        if smtp_server:
            updates.append("smtp_server = ?")
            params.append(smtp_server)

        if daily_limit is not None:
            updates.append("daily_limit = ?")
            params.append(daily_limit)

        if not updates:
            return True, "无需更新"

        params.append(account_id)
        sql = f"UPDATE uni_email_account SET {', '.join(updates)} WHERE account_id = ?"

        with get_db_connection() as conn:
            conn.execute(sql, params)
            conn.commit()

        return True, "更新成功"
    except Exception as e:
        return False, str(e)


def delete_account(account_id):
    """删除发件人账号"""
    try:
        with get_db_connection() as conn:
            # 检查是否有正在进行的任务使用此账号
            running_task = conn.execute("""
                SELECT task_id FROM uni_email_task
                WHERE account_id = ? AND status = 'running'
            """, (account_id,)).fetchone()
            if running_task:
                return False, "此账号有正在进行的任务,无法删除"

            conn.execute("DELETE FROM uni_email_account WHERE account_id = ?", (account_id,))
            conn.commit()
        return True, "删除成功"
    except Exception as e:
        return False, str(e)


def reset_daily_count(account_id=None):
    """重置每日发送计数

    Args:
        account_id: 指定账号ID,为None则重置所有账号

    Returns:
        int 重置的账号数量
    """
    today = date.today().isoformat()

    with get_db_connection() as conn:
        if account_id:
            conn.execute("""
                UPDATE uni_email_account
                SET sent_today = 0, last_reset_date = ?
                WHERE account_id = ? AND last_reset_date != ?
            """, (today, account_id, today))
            conn.commit()
            return 1
        else:
            result = conn.execute("""
                UPDATE uni_email_account
                SET sent_today = 0, last_reset_date = ?
                WHERE last_reset_date != ?
            """, (today, today))
            conn.commit()
            return result.rowcount


def increment_sent_count(account_id):
    """增加发送计数"""
    with get_db_connection() as conn:
        conn.execute("""
            UPDATE uni_email_account
            SET sent_today = sent_today + 1
            WHERE account_id = ?
        """, (account_id,))
        conn.commit()


def can_send_today(account_id):
    """检查今日是否可以继续发送

    Returns:
        (can_send, remaining) tuple
    """
    today = date.today().isoformat()

    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT daily_limit, sent_today, last_reset_date
            FROM uni_email_account WHERE account_id = ?
        """, (account_id,)).fetchone()

        if not row:
            return False, 0

        daily_limit, sent_today, last_reset = row

        # 如果是新的一天,自动重置
        if last_reset != today:
            conn.execute("""
                UPDATE uni_email_account
                SET sent_today = 0, last_reset_date = ?
                WHERE account_id = ?
            """, (today, account_id))
            conn.commit()
            sent_today = 0

        remaining = daily_limit - sent_today
        return remaining > 0, remaining


def get_smtp_server_for_email(email):
    """根据邮箱获取SMTP服务器"""
    if "163.com" in email.lower():
        return "smtp.163.com"
    elif "qiye.163.com" in email.lower() or "unicornsemi.com" in email.lower():
        return "smtphz.qiye.163.com"
    else:
        return "smtp.163.com"