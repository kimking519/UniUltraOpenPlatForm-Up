"""
联系人管理数据库操作模块
用于营销邮件发送和客户关系管理
"""
import sqlite3
import re
from urllib.parse import unquote
from Sills.base import get_db_connection
from Sills.db_config import get_datetime_now
from datetime import datetime


def purify_email(email):
    """
    邮箱提纯函数
    1. URL解码（处理 %20%3c 等）
    2. 正则提取纯邮箱地址
    3. 小写化、去空格
    """
    if not email:
        return ''

    # URL解码
    decoded = unquote(email)

    # 正则提取纯邮箱地址
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    match = re.search(pattern, decoded)

    if match:
        return match.group(0).lower().strip()

    # 如果没有匹配到标准邮箱格式，尝试简单处理
    email = decoded.lower().strip()
    # 去掉常见的特殊字符
    email = email.replace('<', '').replace('>', '').replace('"', '')
    email = email.strip()

    return email if '@' in email else ''


def extract_domain(email):
    """从邮箱地址提取域名"""
    if not email or '@' not in email:
        return ''
    return email.split('@')[-1].lower().strip()


def get_next_contact_id():
    """获取下一个联系人ID (CT + 微秒时间戳 + 3位计数器)
    Bug 修复(2026-06-16): 原秒级时间戳+4位随机在批量导入时产生约 5% 重复。
    """
    from Sills.base import gen_unique_id
    return gen_unique_id('CT')


def _build_contact_filter_clauses(search_kw="", filters=None):
    """构建联系人筛选 WHERE 子句与参数（公共函数）

    被 get_contact_list / get_marketing_stats 复用，保证筛选逻辑一致。

    filters: {cli_id, country, is_bounced, is_read, has_sent, prospect_tag, no_prospect_tag}

    prospect_tag 筛选约定：
    - filters['no_prospect_tag'] = True → 仅"无标识"（p.prospect_id IS NULL）
    - filters['prospect_tag'] 为字符串值（如 "0"/"1"/"2"）→ p.tag = ?

    返回: (where_sql, params)  where_sql 不含 " WHERE" 前缀，空条件时为 ""
    """
    where_clauses = []
    params = []

    if search_kw:
        where_clauses.append("(c.email LIKE ? OR c.contact_name LIKE ? OR c.company LIKE ? OR c.domain LIKE ?)")
        params.extend([f"%{search_kw}%", f"%{search_kw}%", f"%{search_kw}%", f"%{search_kw}%"])

    if filters:
        if filters.get('cli_id'):
            where_clauses.append("c.cli_id = ?")
            params.append(filters['cli_id'])
        if filters.get('country'):
            where_clauses.append("(c.country = ? OR p.country = ?)")
            params.extend([filters['country'], filters['country']])
        if filters.get('is_bounced') is not None:
            where_clauses.append("c.is_bounced = ?")
            params.append(int(filters['is_bounced']))
        # 联系人级别筛选
        if filters.get('is_read') is not None:
            where_clauses.append("c.is_read = ?")
            params.append(int(filters['is_read']))
        if filters.get('has_sent') is not None:
            if int(filters['has_sent']) == 1:
                where_clauses.append("c.send_count > 0")
            else:
                where_clauses.append("c.send_count = 0")
        # 标识（prospect.tag）筛选
        if filters.get('no_prospect_tag'):
            where_clauses.append("p.prospect_id IS NULL")
        elif filters.get('prospect_tag') is not None and filters.get('prospect_tag') != '':
            where_clauses.append("p.tag = ?")
            params.append(filters['prospect_tag'])

    where_sql = " AND ".join(where_clauses) if where_clauses else ""
    return where_sql, params


# 联系人筛选 SQL 公共模板（含 prospect/country 关联），供 list / stats / export 复用
_CONTACT_FILTER_JOIN = """
    FROM uni_contact c
    LEFT JOIN uni_cli cli ON c.cli_id = cli.cli_id
    LEFT JOIN uni_prospect p ON c.domain = p.domain AND p.status = 'pending'
"""


def get_contact_list(page=1, page_size=20, search_kw="", filters=None):
    """
    获取联系人列表
    filters: {cli_id, country, is_bounced, is_read, has_sent, prospect_tag, no_prospect_tag}
    """
    offset = (page - 1) * page_size

    where_sql, params = _build_contact_filter_clauses(search_kw, filters)
    where_clause = f" WHERE {where_sql}" if where_sql else ""

    # LEFT JOIN uni_cli（正式客户）和 uni_prospect（待开发客户）
    # 注：prospect_tag 仅在联系人关联到 pending 状态的 prospect 时有值；CLI 表暂无 tag 字段
    query = f"""
    SELECT c.*,
           cli.cli_name, cli.region as cli_region,
           p.prospect_name, p.country as prospect_country, p.prospect_id,
           p.tag as prospect_tag
    {_CONTACT_FILTER_JOIN}
    {where_clause}
    ORDER BY c.created_at DESC
    LIMIT ? OFFSET ?
    """

    count_query = f"""
    SELECT COUNT(*)
    {_CONTACT_FILTER_JOIN}
    {where_clause}
    """

    with get_db_connection() as conn:
        total = conn.execute(count_query, params).fetchone()[0]
        items = conn.execute(query, params + [page_size, offset]).fetchall()

        results = [
            {k: ("" if v is None else v) for k, v in dict(row).items()}
            for row in items
        ]
        return results, total


def get_contact_by_id(contact_id):
    """根据ID获取联系人详情"""
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT c.*, cli.cli_name, cli.region as cli_region
            FROM uni_contact c
            LEFT JOIN uni_cli cli ON c.cli_id = cli.cli_id
            WHERE c.contact_id = ?
        """, (contact_id,)).fetchone()
        if row:
            return {k: ("" if v is None else v) for k, v in dict(row).items()}
        return None


def get_contact_by_email(email):
    """根据邮箱获取联系人"""
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM uni_contact WHERE email = ?", (email,)).fetchone()
        if row:
            return {k: ("" if v is None else v) for k, v in dict(row).items()}
        return None


def add_contact(data):
    """添加联系人"""
    try:
        contact_id = data.get('contact_id') or get_next_contact_id()
        # 邮箱提纯：URL解码、提取纯邮箱
        email = purify_email(data.get('email', ''))

        if not email:
            return False, "邮箱不能为空"

        # 检查邮箱是否已存在
        with get_db_connection() as conn:
            existing = conn.execute("SELECT contact_id FROM uni_contact WHERE email = ?", (email,)).fetchone()
            if existing:
                return False, f"邮箱 {email} 已存在"

        # 自动提取域名
        domain = extract_domain(email)
        if not domain:
            return False, "邮箱格式不正确"

        # 尝试通过域名匹配客户
        cli_id = data.get('cli_id')
        company = data.get('company', '')
        if not cli_id and domain:
            with get_db_connection() as conn:
                matched_cli = conn.execute(
                    "SELECT cli_id FROM uni_cli WHERE domain = ? OR email LIKE ?",
                    (domain, f"%@{domain}")
                ).fetchone()
                if matched_cli:
                    cli_id = matched_cli[0]

                # 如果公司为空，用域名填充（保持与列表显示一致）
                if not company and domain:
                    company = domain

        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO uni_contact (
                    contact_id, cli_id, email, domain, contact_name, country,
                    position, phone, company, is_bounced, is_read, is_deleted,
                    send_count, bounce_count, read_count, remark
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                contact_id, cli_id, email, domain,
                data.get('contact_name', ''),
                data.get('country', ''),
                data.get('position', ''),
                data.get('phone', ''),
                company,  # 使用处理后的 company（可能从 prospect 填充）
                0, 0, 0,  # is_bounced, is_read, is_deleted
                0, 0, 0,  # send_count, bounce_count, read_count
                data.get('remark', '')
            ))
            conn.commit()

        # 同步客户营销状态
        if cli_id:
            from Sills.db_cli import sync_cli_marketing_status
            sync_cli_marketing_status(cli_id)

        return True, f"联系人 {contact_id} 添加成功"
    except Exception as e:
        return False, str(e)


def update_contact(contact_id, data):
    """更新联系人"""
    try:
        # 如果更新邮箱，重新提取域名
        if 'email' in data:
            data['email'] = data['email'].strip().lower()
            data['domain'] = extract_domain(data['email'])

        set_cols = []
        params = []
        for k, v in data.items():
            set_cols.append(f"{k} = ?")
            params.append(v)

        params.append(contact_id)
        sql = f"UPDATE uni_contact SET {', '.join(set_cols)} WHERE contact_id = ?"

        with get_db_connection() as conn:
            conn.execute(sql, params)
            conn.commit()
            return True, "更新成功"
    except Exception as e:
        return False, str(e)


def delete_contact(contact_id):
    """删除联系人"""
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM uni_contact WHERE contact_id = ?", (contact_id,))
            conn.commit()
            return True, "删除成功"
    except Exception as e:
        return False, str(e)


def batch_delete_contacts(contact_ids):
    """批量删除联系人"""
    if not contact_ids:
        return 0, 0, "未选择记录"

    deleted_count = 0
    failed_count = 0

    with get_db_connection() as conn:
        for contact_id in contact_ids:
            try:
                conn.execute("DELETE FROM uni_contact WHERE contact_id = ?", (contact_id,))
                deleted_count += 1
            except Exception:
                failed_count += 1
        conn.commit()

    return deleted_count, failed_count, "批量删除完成"


def batch_import_contacts(contacts_list, auto_create_cli=False):
    """
    批量导入联系人
    contacts_list: [{email, contact_name, country, position, phone, company, remark}, ...]
    auto_create_cli: 是否自动创建不存在的客户
    每条记录使用独立连接，避免 PostgreSQL 事务错误累积

    返回: (success_count, skipped_count, errors, new_clients)
      - success_count: 成功导入数
      - skipped_count: 因邮箱重复跳过的数量（与 Prospect 导入对齐）
      - errors: 真正的错误（不含重复跳过）
      - new_clients: 自动创建的客户列表
    """
    success_count = 0
    skipped_count = 0
    errors = []
    new_clients = []

    for contact in contacts_list:
        try:
            # 邮箱提纯：URL解码、提取纯邮箱
            email = purify_email(contact.get('email', ''))
            if not email:
                errors.append(f"邮箱为空或格式无效，跳过")
                continue

            # 优先使用传入的domain，否则从邮箱自动提取
            raw_domain = contact.get('domain', '').strip() if contact.get('domain') else extract_domain(email)
            # domain 规范化：转小写、去开头的 www. 前缀（避免 www.x.com 和 x.com 重复入库）
            domain = raw_domain.lower() if raw_domain else ''
            if domain.startswith('www.'):
                domain = domain[4:]
            contact_id = get_next_contact_id()

            # 每条记录使用独立连接
            with get_db_connection() as conn:
                # 检查是否已存在（按 email 唯一）
                existing = conn.execute("SELECT contact_id FROM uni_contact WHERE email = ?", (email,)).fetchone()
                if existing:
                    skipped_count += 1
                    continue

                # 尝试匹配客户
                cli_id = None
                company = contact.get('company', '')
                if domain:
                    matched_cli = conn.execute(
                        "SELECT cli_id, cli_name FROM uni_cli WHERE domain = ?",
                        (domain,)
                    ).fetchone()

                    if matched_cli:
                        cli_id = matched_cli[0]
                    elif auto_create_cli:
                        # 自动创建新客户（使用独立调用）
                        from Sills.db_cli import get_next_cli_id, add_cli
                        new_cli_id = get_next_cli_id()
                        cli_data = {
                            'cli_id': new_cli_id,
                            'cli_name': contact.get('company') or domain,
                            'domain': domain,
                            'region': contact.get('country', '未知'),
                            'emp_id': '000'
                        }
                        ok, msg = add_cli(cli_data)
                        if ok:
                            cli_id = new_cli_id
                            new_clients.append(f"{domain} -> {new_cli_id}")
                        else:
                            errors.append(f"{domain}: 创建客户失败 - {msg}")

                    # 如果公司为空，用域名填充（保持与列表显示一致）
                    if not company and domain:
                        company = domain

                conn.execute("""
                    INSERT INTO uni_contact (
                        contact_id, cli_id, email, domain, contact_name, country,
                        position, phone, company, remark
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    contact_id, cli_id, email, domain,
                    contact.get('contact_name', ''),
                    contact.get('country', ''),
                    contact.get('position', ''),
                    contact.get('phone', ''),
                    company,  # 使用处理后的 company（可能从 prospect 填充）
                    contact.get('remark', '')
                ))
                # with语句结束时自动commit
                success_count += 1

        except Exception as e:
            error_msg = str(e)
            if 'duplicate key' in error_msg.lower() or 'already exists' in error_msg.lower():
                # DB 层唯一约束兜底，也算 skipped 而非 error
                skipped_count += 1
            else:
                errors.append(f"{contact.get('email', '未知')}: {error_msg}")

    # 同步所有涉及客户的营销状态
    if success_count > 0:
        from Sills.db_cli import sync_cli_marketing_status
        sync_cli_marketing_status()

    return success_count, skipped_count, errors, new_clients


def update_contact_marketing_status(contact_id, status_type, increment=True):
    """
    更新联系人营销状态
    status_type: 'sent', 'bounced', 'read'
    """
    try:
        dt_now = get_datetime_now()
        with get_db_connection() as conn:
            if status_type == 'sent':
                if increment:
                    conn.execute(f"""
                        UPDATE uni_contact
                        SET send_count = send_count + 1, last_sent_at = {dt_now}
                        WHERE contact_id = ?
                    """, (contact_id,))
                else:
                    conn.execute(f"""
                        UPDATE uni_contact
                        SET send_count = ?, last_sent_at = {dt_now}
                        WHERE contact_id = ?
                    """, (0, contact_id))

            elif status_type == 'bounced':
                if increment:
                    conn.execute("""
                        UPDATE uni_contact
                        SET bounce_count = bounce_count + 1, is_bounced = 1
                        WHERE contact_id = ?
                    """, (contact_id,))
                else:
                    conn.execute("""
                        UPDATE uni_contact
                        SET bounce_count = 0, is_bounced = 0
                        WHERE contact_id = ?
                    """, (contact_id,))

            elif status_type == 'read':
                if increment:
                    conn.execute("""
                        UPDATE uni_contact
                        SET read_count = read_count + 1, is_read = 1
                        WHERE contact_id = ?
                    """, (contact_id,))
                else:
                    conn.execute("""
                        UPDATE uni_contact
                        SET read_count = 0, is_read = 0
                        WHERE contact_id = ?
                    """, (contact_id,))

            conn.commit()
            return True, "状态更新成功"
    except Exception as e:
        return False, str(e)


def get_contacts_for_marketing(filters=None):
    """
    获取用于营销邮件发送的联系人列表
    filters: {countries: [], is_bounced: bool, is_read: bool, has_sent: bool}
    """
    where_clauses = ["c.is_bounced = 0"]  # 排除已退信的
    params = []

    if filters:
        if filters.get('countries'):
            placeholders = ','.join(['?' for _ in filters['countries']])
            where_clauses.append(f"c.country IN ({placeholders})")
            params.extend(filters['countries'])

        if filters.get('is_bounced') is not None:
            where_clauses.append("c.is_bounced = ?")
            params.append(int(filters['is_bounced']))

        # 联系人级别筛选
        if filters.get('is_read') is not None:
            where_clauses.append("c.is_read = ?")
            params.append(int(filters['is_read']))
        if filters.get('has_sent') is not None:
            if int(filters['has_sent']) == 1:
                where_clauses.append("c.send_count > 0")
            else:
                where_clauses.append("c.send_count = 0")

    where_sql = " AND ".join(where_clauses)

    query = f"""
    SELECT c.contact_id, c.email, c.contact_name, c.domain, c.country, c.company,
           cli.cli_name, c.is_read, c.send_count
    FROM uni_contact c
    LEFT JOIN uni_cli cli ON c.cli_id = cli.cli_id
    WHERE {where_sql}
    ORDER BY c.send_count ASC, c.created_at DESC
    """

    with get_db_connection() as conn:
        items = conn.execute(query, params).fetchall()
        results = [
            {k: ("" if v is None else v) for k, v in dict(row).items()}
            for row in items
        ]
        return results


def add_marketing_email(contact_id, mail_id, subject, content, status='sent'):
    """记录营销邮件发送"""
    try:
        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO uni_marketing_email (contact_id, mail_id, subject, content, status)
                VALUES (?, ?, ?, ?, ?)
            """, (contact_id, mail_id, subject, content, status))
            conn.commit()
            return True, "记录成功"
    except Exception as e:
        return False, str(e)


def get_marketing_email_history(contact_id=None, page=1, page_size=20):
    """获取营销邮件发送历史"""
    offset = (page - 1) * page_size

    with get_db_connection() as conn:
        if contact_id:
            query = """
                SELECT m.*, c.email, c.contact_name
                FROM uni_marketing_email m
                LEFT JOIN uni_contact c ON m.contact_id = c.contact_id
                WHERE m.contact_id = ?
                ORDER BY m.sent_at DESC
                LIMIT ? OFFSET ?
            """
            items = conn.execute(query, [contact_id, page_size, offset]).fetchall()
            total = conn.execute(
                "SELECT COUNT(*) FROM uni_marketing_email WHERE contact_id = ?",
                (contact_id,)
            ).fetchone()[0]
        else:
            query = """
                SELECT m.*, c.email, c.contact_name
                FROM uni_marketing_email m
                LEFT JOIN uni_contact c ON m.contact_id = c.contact_id
                ORDER BY m.sent_at DESC
                LIMIT ? OFFSET ?
            """
            items = conn.execute(query, [page_size, offset]).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM uni_marketing_email").fetchone()[0]

        results = [
            {k: ("" if v is None else v) for k, v in dict(row).items()}
            for row in items
        ]
        return results, total


def get_contact_countries():
    """获取所有国家列表（从联系人和待开发客户表合并查询）"""
    with get_db_connection() as conn:
        # 从联系人表获取国家
        contact_rows = conn.execute("""
            SELECT DISTINCT country FROM uni_contact
            WHERE country IS NOT NULL AND country != ''
        """).fetchall()

        # 从待开发客户表获取国家
        prospect_rows = conn.execute("""
            SELECT DISTINCT country FROM uni_prospect
            WHERE country IS NOT NULL AND country != ''
        """).fetchall()

        # 合并去重
        countries = set()
        for row in contact_rows:
            countries.add(row[0])
        for row in prospect_rows:
            countries.add(row[0])

        return sorted(list(countries))


def get_marketing_stats(search_kw="", filters=None):
    """获取营销统计数据（支持按筛选条件联动统计）

    统计逻辑：
    - total_sent    = SUM(uni_contact.send_count)
    - total_bounced = mail_folder 名含"退信"的文件夹中 original_recipient 匹配联系人去重数
    - total_read    = mail_folder 名含"읽음"且不含"않음"的文件夹中 from_addr 匹配联系人去重数
    - total_unread  = mail_folder 名含"읽지 않음"的文件夹中 from_addr 匹配联系人去重数

    以 folder_id 为准，与 /mail 页面文件夹展示一致。

    search_kw/filters: 与 get_contact_list 相同的筛选条件，5 个数字按筛选范围统计。
    不传参数时等价于原全表统计（向后兼容）。
    """
    # 构建联系人筛选子句（c.xxx 字段，复用公共函数保证与列表一致）
    where_sql, params = _build_contact_filter_clauses(search_kw, filters)
    contact_from = _CONTACT_FILTER_JOIN.strip()
    contact_where = f" WHERE {where_sql}" if where_sql else ""
    and_where = f" AND {where_sql}" if where_sql else ""

    # 注：中文关键词通过 ? 参数传入，避免 SQL 字面量含中文触发 psycopg 查询解析 UnicodeDecodeError
    # （带 params 时 psycopg 解析 query 字符串会在中文字节边界出错，参数化后 SQL 无中文字面量）
    FOLDER_BOUNCE = '%退信%'
    FOLDER_READ = '%읽음%'
    FOLDER_READ_EXCLUDE = '%않음%'
    FOLDER_UNREAD = '%읽지 않음%'

    with get_db_connection() as conn:
        total_contacts = conn.execute(
            f"SELECT COUNT(*) {contact_from} {contact_where}", params
        ).fetchone()[0]
        total_sent = conn.execute(
            f"SELECT COALESCE(SUM(c.send_count), 0) {contact_from} {contact_where}", params
        ).fetchone()[0]

        # 退信：文件夹名含"退信"，用 original_recipient 匹配联系人
        # 联系人侧筛选通过 LEFT JOIN prospect/cli + and_where 应用
        total_bounced = conn.execute(f"""
            SELECT COUNT(DISTINCT c.contact_id)
            FROM uni_mail m
            JOIN mail_folder f ON m.folder_id = f.id
            JOIN uni_contact c ON m.original_recipient = c.email
            LEFT JOIN uni_prospect p ON c.domain = p.domain AND p.status = 'pending'
            LEFT JOIN uni_cli cli ON c.cli_id = cli.cli_id
            WHERE f.folder_name LIKE ?
              AND m.original_recipient IS NOT NULL
              AND m.original_recipient != ''
              {and_where}
        """, [FOLDER_BOUNCE] + params).fetchone()[0]

        # 已读：文件夹名含"읽음"且不含"않음"，用 from_addr 匹配联系人
        total_read = conn.execute(f"""
            SELECT COUNT(DISTINCT c.contact_id)
            FROM uni_mail m
            JOIN mail_folder f ON m.folder_id = f.id
            JOIN uni_contact c ON m.from_addr = c.email
            LEFT JOIN uni_prospect p ON c.domain = p.domain AND p.status = 'pending'
            LEFT JOIN uni_cli cli ON c.cli_id = cli.cli_id
            WHERE f.folder_name LIKE ?
              AND f.folder_name NOT LIKE ?
              AND m.from_addr IS NOT NULL
              AND m.from_addr != ''
              {and_where}
        """, [FOLDER_READ, FOLDER_READ_EXCLUDE] + params).fetchone()[0]

        # 未读：文件夹名含"읽지 않음"，用 from_addr 匹配联系人
        total_unread = conn.execute(f"""
            SELECT COUNT(DISTINCT c.contact_id)
            FROM uni_mail m
            JOIN mail_folder f ON m.folder_id = f.id
            JOIN uni_contact c ON m.from_addr = c.email
            LEFT JOIN uni_prospect p ON c.domain = p.domain AND p.status = 'pending'
            LEFT JOIN uni_cli cli ON c.cli_id = cli.cli_id
            WHERE f.folder_name LIKE ?
              AND m.from_addr IS NOT NULL
              AND m.from_addr != ''
              {and_where}
        """, [FOLDER_UNREAD] + params).fetchone()[0]

        bounce_rate = round(total_bounced / total_sent * 100, 2) if total_sent > 0 else 0

        return {
            'total_contacts': total_contacts,
            'total_sent': total_sent,
            'total_bounced': total_bounced,
            'total_read': total_read,
            'total_unread': total_unread,
            'bounce_rate': bounce_rate
        }


def extract_emails_from_addr(addr):
    """从地址字段提取所有邮箱地址（用于统计匹配）"""
    if not addr:
        return []

    from urllib.parse import unquote

    # URL解码
    decoded = unquote(addr)

    # 匹配邮箱格式
    pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    emails = re.findall(pattern, decoded.lower())
    return emails