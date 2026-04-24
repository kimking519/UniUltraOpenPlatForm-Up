"""
待开发客户 (Prospect) 数据库操作模块
用于潜在客户管理和转化
"""
import sqlite3
from datetime import datetime
from Sills.base import get_db_connection


# 公共邮箱域名列表
PUBLIC_DOMAINS = [
    'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'live.com',
    'aol.com', 'mail.com', 'protonmail.com', 'icloud.com', 'qq.com',
    '163.com', '126.com', 'sina.com', 'foxmail.com', 'yandex.com',
    'googlemail.com', 'msn.com', 'mail.ru', 'inbox.com', 'gmx.com'
]


def is_public_domain(domain):
    """检查是否是公共邮箱域名"""
    if not domain:
        return False
    return domain.lower() in PUBLIC_DOMAINS


def get_next_prospect_id():
    """获取下一个Prospect ID (PK+时间戳+随机数格式)"""
    import random
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    rand_suffix = random.randint(1000, 9999)
    return f"PK{timestamp}{rand_suffix}"


def count_contacts_by_domain(domain):
    """统计相同域名的联系人数量（支持www前缀模糊匹配）"""
    if not domain:
        return 0
    domain = domain.lower().strip()
    # 移除www前缀进行匹配
    clean_domain = domain.replace('www.', '') if domain.startswith('www.') else domain
    with get_db_connection() as conn:
        # 匹配domain字段或从email提取的域名
        count = conn.execute(
            """SELECT COUNT(*) FROM uni_contact
               WHERE LOWER(domain) = ? OR LOWER(domain) = ?""",
            (domain, clean_domain)
        ).fetchone()[0]
        return count


def get_prospect_list(page=1, page_size=20, search_kw="", filters=None):
    """
    获取Prospect列表
    filters: {country, status, has_contacts}
    """
    offset = (page - 1) * page_size
    where_clauses = []
    params = []

    if search_kw:
        where_clauses.append("(p.prospect_name LIKE ? OR p.company_website LIKE ? OR p.domain LIKE ?)")
        params.extend([f"%{search_kw}%", f"%{search_kw}%", f"%{search_kw}%"])

    if filters:
        if filters.get('country'):
            where_clauses.append("p.country = ?")
            params.append(filters['country'])
        if filters.get('status'):
            where_clauses.append("p.status = ?")
            params.append(filters['status'])
        if filters.get('is_public') is not None:
            where_clauses.append("p.is_public_domain = ?")
            params.append(int(filters['is_public']))

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    query = f"""
    SELECT p.*, cli.cli_name
    FROM uni_prospect p
    LEFT JOIN uni_cli cli ON p.cli_id = cli.cli_id
    {where_sql}
    ORDER BY p.created_at DESC
    LIMIT ? OFFSET ?
    """

    count_query = f"""
    SELECT COUNT(*)
    FROM uni_prospect p
    {where_sql}
    """

    with get_db_connection() as conn:
        total = conn.execute(count_query, params).fetchone()[0]
        items = conn.execute(query, params + [page_size, offset]).fetchall()
        results = [
            {k: ("" if v is None else v) for k, v in dict(row).items()}
            for row in items
        ]
        return results, total


def get_prospect_by_id(prospect_id):
    """根据ID获取Prospect详情"""
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT p.*, cli.cli_name
            FROM uni_prospect p
            LEFT JOIN uni_cli cli ON p.cli_id = cli.cli_id
            WHERE p.prospect_id = ?
        """, (prospect_id,)).fetchone()
        if row:
            return {k: ("" if v is None else v) for k, v in dict(row).items()}
        return None


def get_prospect_by_domain(domain):
    """根据域名获取Prospect"""
    if not domain:
        return None
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM uni_prospect WHERE domain = ?",
            (domain.lower(),)
        ).fetchone()
        if row:
            return {k: ("" if v is None else v) for k, v in dict(row).items()}
        return None


def add_prospect(data):
    """添加Prospect"""
    try:
        prospect_id = data.get('prospect_id') or get_next_prospect_id()
        prospect_name = data.get('prospect_name', '').strip()
        domain = data.get('domain', '').strip().lower()

        if not prospect_name:
            return False, "客户名称不能为空"
        if not domain:
            return False, "域名不能为空"

        # 检查域名是否已存在
        with get_db_connection() as conn:
            existing = conn.execute(
                "SELECT prospect_id FROM uni_prospect WHERE domain = ?",
                (domain,)
            ).fetchone()
            if existing:
                return False, f"域名 {domain} 已存在"

        # 判断是否公共域名
        is_public = 1 if is_public_domain(domain) else 0

        # 统计关联联系人
        contact_count = count_contacts_by_domain(domain)

        # 价值分级处理(0-3, 默认0未分级)
        value_level = data.get('value_level', 0)
        try:
            value_level = int(value_level) if value_level else 0
            if value_level < 0 or value_level > 3:
                value_level = 0
        except:
            value_level = 0

        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO uni_prospect (
                    prospect_id, prospect_name, company_website, domain,
                    country, business_type, business_detail, value_level,
                    status, contact_count, is_public_domain, remark
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                prospect_id, prospect_name,
                data.get('company_website', ''),
                domain,
                data.get('country', ''),
                data.get('business_type', ''),
                data.get('business_detail', ''),
                value_level,
                'pending',
                contact_count,
                is_public,
                data.get('remark', '')
            ))
            conn.commit()

        return True, f"Prospect {prospect_id} 添加成功"
    except Exception as e:
        return False, str(e)


def update_prospect(prospect_id, data):
    """更新Prospect"""
    try:
        set_cols = []
        params = []
        for k, v in data.items():
            if k != 'prospect_id':
                set_cols.append(f"{k} = ?")
                params.append(v)
        params.append(prospect_id)
        sql = f"UPDATE uni_prospect SET {', '.join(set_cols)} WHERE prospect_id = ?"
        with get_db_connection() as conn:
            conn.execute(sql, params)
            conn.commit()
            return True, "更新成功"
    except Exception as e:
        return False, str(e)


def delete_prospect(prospect_id):
    """删除Prospect"""
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM uni_prospect WHERE prospect_id = ?", (prospect_id,))
            conn.commit()
        return True, "删除成功"
    except Exception as e:
        return False, str(e)


def batch_delete_prospects(prospect_ids):
    """批量删除Prospect"""
    if not prospect_ids:
        return False, "未选择任何记录"
    try:
        with get_db_connection() as conn:
            for prospect_id in prospect_ids:
                conn.execute("DELETE FROM uni_prospect WHERE prospect_id = ?", (prospect_id,))
            conn.commit()
        return True, f"成功删除 {len(prospect_ids)} 条记录"
    except Exception as e:
        import traceback
        traceback.print_exc()
        return False, str(e) if str(e) else "删除时发生未知错误"


def import_prospects(data_list):
    """
    批量导入Prospect
    data_list: [{prospect_name, company_website, domain, country, remark}, ...]
    使用批量操作优化性能，单条失败不影响整体
    """
    success_count = 0
    skipped_count = 0
    errors = []

    # 使用独立连接处理每条记录，避免事务错误累积
    for data in data_list:
        try:
            prospect_name = data.get('prospect_name', '').strip()
            domain = data.get('domain', '').strip().lower()

            if not prospect_name or not domain:
                skipped_count += 1
                continue

            # 每条记录使用独立连接（PostgreSQL特性）
            with get_db_connection() as conn:
                # 检查是否已存在
                existing = conn.execute(
                    "SELECT prospect_id FROM uni_prospect WHERE domain = ?",
                    (domain,)
                ).fetchone()
                if existing:
                    skipped_count += 1
                    continue

                prospect_id = get_next_prospect_id()
                is_public = 1 if is_public_domain(domain) else 0

                # 价值分级处理
                value_level = data.get('value_level', 0)
                try:
                    value_level = int(value_level) if value_level else 0
                    if value_level < 0 or value_level > 3:
                        value_level = 0
                except:
                    value_level = 0

                conn.execute("""
                    INSERT INTO uni_prospect (
                        prospect_id, prospect_name, company_website, domain,
                        country, business_type, business_detail, value_level,
                        status, contact_count, is_public_domain, remark
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    prospect_id, prospect_name,
                    data.get('company_website', ''),
                    domain,
                    data.get('country', ''),
                    data.get('business_type', ''),
                    data.get('business_detail', ''),
                    value_level,
                    'pending',
                    0,
                    is_public,
                    data.get('remark', '')
                ))
                # with语句结束时自动commit
                success_count += 1

        except Exception as e:
            error_msg = str(e)
            if 'duplicate key' in error_msg.lower() or 'already exists' in error_msg.lower():
                skipped_count += 1
            else:
                errors.append(f"{data.get('domain', '未知')}: {error_msg}")

    return success_count, skipped_count, errors


def convert_prospect_to_cli(prospect_id):
    """
    将Prospect转化为CLI客户
    1. 创建CLI记录
    2. 更新Prospect的cli_id和status
    """
    try:
        prospect = get_prospect_by_id(prospect_id)
        if not prospect:
            return False, "Prospect不存在"

        if prospect.get('status') == 'converted':
            return False, "Prospect已转化"

        # 创建CLI
        from Sills.db_cli import get_next_cli_id, add_cli

        cli_id = get_next_cli_id()
        cli_data = {
            'cli_id': cli_id,
            'cli_name': prospect['prospect_name'],
            'domain': prospect['domain'],
            'region': prospect.get('country', '未知'),
            'emp_id': '000',  # 默认员工
            'website': prospect.get('company_website', '')
        }

        ok, msg = add_cli(cli_data)
        if not ok:
            return False, f"创建CLI失败: {msg}"

        # 更新Prospect
        with get_db_connection() as conn:
            conn.execute("""
                UPDATE uni_prospect
                SET cli_id = ?, status = 'converted'
                WHERE prospect_id = ?
            """, (cli_id, prospect_id))
            conn.commit()

        # 更新关联联系人的cli_id（支持www前缀模糊匹配）
        if prospect['domain']:
            domain = prospect['domain'].lower().strip()
            clean_domain = domain.replace('www.', '') if domain.startswith('www.') else domain
            conn.execute("""
                UPDATE uni_contact
                SET cli_id = ?
                WHERE (LOWER(domain) = ? OR LOWER(domain) = ?) AND (cli_id IS NULL OR cli_id = '')
            """, (cli_id, domain, clean_domain))
            conn.commit()

        return True, f"转化成功，CLI ID: {cli_id}"
    except Exception as e:
        return False, str(e)


def get_prospect_stats():
    """获取Prospect统计数据"""
    with get_db_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM uni_prospect").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM uni_prospect WHERE status = 'pending'"
        ).fetchone()[0]
        converted = conn.execute(
            "SELECT COUNT(*) FROM uni_prospect WHERE status = 'converted'"
        ).fetchone()[0]
        public_count = conn.execute(
            "SELECT COUNT(*) FROM uni_prospect WHERE is_public_domain = 1"
        ).fetchone()[0]

        return {
            'total': total,
            'pending': pending,
            'converted': converted,
            'public_domain': public_count
        }


def get_prospect_countries():
    """获取所有Prospect国家列表"""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT DISTINCT country FROM uni_prospect
            WHERE country IS NOT NULL AND country != ''
            ORDER BY country
        """).fetchall()
        return [row[0] for row in rows]


def refresh_all_contact_counts():
    """刷新所有Prospect的关联联系人数量"""
    with get_db_connection() as conn:
        prospects = conn.execute(
            "SELECT prospect_id, domain FROM uni_prospect"
        ).fetchall()
        updated_count = 0
        for prospect in prospects:
            prospect_id = prospect[0]
            domain = prospect[1]
            if domain:
                domain = domain.lower().strip()
                clean_domain = domain.replace('www.', '') if domain.startswith('www.') else domain
                count = conn.execute(
                    """SELECT COUNT(*) FROM uni_contact
                       WHERE LOWER(domain) = ? OR LOWER(domain) = ?""",
                    (domain, clean_domain)
                ).fetchone()[0]
            else:
                count = 0
            conn.execute(
                "UPDATE uni_prospect SET contact_count = ? WHERE prospect_id = ?",
                (count, prospect_id)
            )
            updated_count += 1
        conn.commit()
        return updated_count