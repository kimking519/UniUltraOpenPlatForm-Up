"""
联系人组管理数据库操作模块
用于邮件任务管理中的联系人分组
支持动态组(筛选条件)和静态组(手动邮件列表)
"""
import sqlite3
import json
import re
from datetime import datetime
from Sills.base import get_db_connection
from Sills.db_contact import get_contact_by_email


def get_next_group_id():
    """获取下一个联系人组ID (GP+时间戳+随机数格式)"""
    import random
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    rand_suffix = random.randint(1000, 9999)
    return f"GP{timestamp}{rand_suffix}"


def get_group_list(page=1, page_size=20, search_kw=""):
    """获取联系人组列表"""
    offset = (page - 1) * page_size
    where_clause = ""
    params = []

    if search_kw:
        where_clause = "WHERE group_name LIKE ?"
        params = [f"%{search_kw}%"]

    query = f"""
    SELECT * FROM uni_contact_group
    {where_clause}
    ORDER BY created_at DESC
    LIMIT ? OFFSET ?
    """

    count_query = f"SELECT COUNT(*) FROM uni_contact_group {where_clause}"

    with get_db_connection() as conn:
        total = conn.execute(count_query, params).fetchone()[0]
        items = conn.execute(query, params + [page_size, offset]).fetchall()
        results = [
            {k: ("" if v is None else v) for k, v in dict(row).items()}
            for row in items
        ]
        return results, total


def get_group_by_id(group_id):
    """根据ID获取联系人组详情"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM uni_contact_group WHERE group_id = ?",
            (group_id,)
        ).fetchone()
        if row:
            return {k: ("" if v is None else v) for k, v in dict(row).items()}
        return None


def add_group(group_name, filter_criteria=None, manual_emails=None):
    """添加联系人组

    Args:
        group_name: 组名称
        filter_criteria: dict 筛选条件 {country, domain, is_bounced, has_cli}
        manual_emails: list 手动添加的邮件 [{"email": "x@x.com", "company": "公司名"}, ...]

    Returns:
        (success, message) tuple
    """
    try:
        if not group_name or not group_name.strip():
            return False, "组名称不能为空"

        group_id = get_next_group_id()
        criteria_json = json.dumps(filter_criteria) if filter_criteria else ""

        # 处理手动邮件
        manual_emails_json = ""
        manual_count = 0
        if manual_emails:
            # 验证并去重
            unique_emails = {}
            for item in manual_emails:
                email = item.get('email', '').strip().lower()
                if email and '@' in email:
                    unique_emails[email] = {
                        'email': email,
                        'company': item.get('company', ''),
                        'contact_name': item.get('contact_name', '')
                    }
            manual_emails_json = json.dumps(list(unique_emails.values()))
            manual_count = len(unique_emails)

        # 计算筛选条件匹配的联系人数量
        filter_count = count_contacts_by_criteria(filter_criteria)

        # 总数 = 筛选条件数 + 手动邮件数（可能有重叠，后续获取时会去重）
        total_count = filter_count + manual_count

        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO uni_contact_group (group_id, group_name, filter_criteria, manual_emails, contact_count)
                VALUES (?, ?, ?, ?, ?)
            """, (group_id, group_name.strip(), criteria_json, manual_emails_json, total_count))
            conn.commit()

        return True, f"联系人组 {group_id} 创建成功，筛选 {filter_count} 个联系人 + 手动添加 {manual_count} 个邮件"
    except Exception as e:
        return False, str(e)


def update_group(group_id, group_name=None, filter_criteria=None, manual_emails=None):
    """更新联系人组（支持筛选条件和手动邮件）"""
    try:
        updates = []
        params = []

        if group_name:
            updates.append("group_name = ?")
            params.append(group_name.strip())

        if filter_criteria is not None:
            updates.append("filter_criteria = ?")
            params.append(json.dumps(filter_criteria) if filter_criteria else "")

        if manual_emails is not None:
            # 验证并去重
            unique_emails = {}
            for item in manual_emails:
                email = item.get('email', '').strip().lower()
                if email and '@' in email:
                    unique_emails[email] = {
                        'email': email,
                        'company': item.get('company', ''),
                        'contact_name': item.get('contact_name', '')
                    }
            updates.append("manual_emails = ?")
            params.append(json.dumps(list(unique_emails.values())) if unique_emails else "")

        if not updates:
            return True, "无需更新"

        # 重新计算总数
        group = get_group_by_id(group_id)
        if group:
            filter_count = count_contacts_by_criteria(filter_criteria) if filter_criteria else 0
            manual_count = len(unique_emails) if manual_emails else 0
            updates.append("contact_count = ?")
            params.append(filter_count + manual_count)

        updates.append("updated_at = NOW()")
        params.append(group_id)

        sql = f"UPDATE uni_contact_group SET {', '.join(updates)} WHERE group_id = ?"

        with get_db_connection() as conn:
            conn.execute(sql, params)
            conn.commit()

        return True, "更新成功"
    except Exception as e:
        return False, str(e)


def delete_group(group_id):
    """删除联系人组"""
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM uni_contact_group WHERE group_id = ?", (group_id,))
            conn.commit()
        return True, "删除成功"
    except Exception as e:
        return False, str(e)


def count_contacts_by_criteria(criteria):
    """根据筛选条件统计联系人数量

    Args:
        criteria: dict {country, countries, domain, cli_id, send_status, read_status, bounce_status, send_count, last_sent_days, has_cli}

    Returns:
        int 符合条件的联系人数
    """
    if not criteria:
        with get_db_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM uni_contact WHERE email IS NOT NULL AND email != ''").fetchone()[0]

    where_clauses = ["email IS NOT NULL AND email != ''"]
    params = []

    # 特定客户筛选（优先级最高）
    if criteria.get('cli_id'):
        where_clauses.append("cli_id = ?")
        params.append(criteria['cli_id'])

    # 是否关联客户（勾选）
    if criteria.get('has_cli'):
        where_clauses.append("cli_id IS NOT NULL AND cli_id != ''")

    # 国家筛选（支持单选和多选）
    # 国家筛选需要通过 uni_prospect 表关联，因为 uni_contact.country 都是空的
    country_filter = None
    if criteria.get('countries'):
        countries_list = criteria['countries']
        if isinstance(countries_list, list) and len(countries_list) > 0:
            country_filter = countries_list
    elif criteria.get('country'):
        country_filter = [criteria['country']]

    if country_filter:
        # 先从 uni_prospect 查找该国家对应的 domain
        with get_db_connection() as conn:
            placeholders = ','.join(['?' for _ in country_filter])
            domains = conn.execute(
                f"SELECT DISTINCT domain FROM uni_prospect WHERE country IN ({placeholders}) AND domain IS NOT NULL AND domain != ''",
                country_filter
            ).fetchall()
            domain_list = [d[0] for d in domains if d[0]]

        if domain_list:
            # 再从 uni_contact 查找匹配这些 domain 的联系人
            placeholders = ','.join(['?' for _ in domain_list])
            where_clauses.append(f"domain IN ({placeholders})")
            params.extend(domain_list)
        else:
            # 该国家没有对应的 domain，返回 0
            return 0

    if criteria.get('domain'):
        where_clauses.append("domain LIKE ?")
        params.append(f"%{criteria['domain']}%")

    # 发送状态
    if criteria.get('send_status') is not None:
        if criteria['send_status'] == 0:
            where_clauses.append("send_count = 0")
        else:
            where_clauses.append("send_count > 0")

    # 已读状态
    if criteria.get('read_status') is not None:
        where_clauses.append("is_read = ?")
        params.append(criteria['read_status'])

    # 退信状态
    if criteria.get('bounce_status') is not None:
        where_clauses.append("is_bounced = ?")
        params.append(criteria['bounce_status'])

    # 发送次数范围
    send_count_range = criteria.get('send_count')
    if send_count_range:
        if send_count_range == '0':
            where_clauses.append("send_count = 0")
        elif send_count_range == '1-3':
            where_clauses.append("send_count BETWEEN 1 AND 3")
        elif send_count_range == '4+':
            where_clauses.append("send_count >= 4")

    # 最后联系时间（X天内未联系）
    last_sent_days = criteria.get('last_sent_days')
    if last_sent_days:
        where_clauses.append(
            "(last_sent_at IS NULL OR datetime(last_sent_at) < datetime('now', 'localtime', '-{} days'))".format(last_sent_days)
        )

    where_sql = "WHERE " + " AND ".join(where_clauses)

    with get_db_connection() as conn:
        return conn.execute(f"SELECT COUNT(*) FROM uni_contact {where_sql}", params).fetchone()[0]


def get_group_contacts(group_id, page=1, page_size=100):
    """获取联系人组内的联系人列表

    Args:
        group_id: 组ID
        page: 页码
        page_size: 每页数量

    Returns:
        (contacts_list, total) tuple
    """
    group = get_group_by_id(group_id)
    if not group:
        return [], 0

    criteria = json.loads(group.get('filter_criteria', '{}') or '{}')

    offset = (page - 1) * page_size
    where_clauses = ["c.email IS NOT NULL AND c.email != ''"]
    params = []

    # 特定客户筛选（优先级最高）
    if criteria.get('cli_id'):
        where_clauses.append("c.cli_id = ?")
        params.append(criteria['cli_id'])

    # 是否关联客户（勾选）
    if criteria.get('has_cli'):
        where_clauses.append("c.cli_id IS NOT NULL AND c.cli_id != ''")

    # 国家筛选（支持单选和多选）
    # 国家筛选需要通过 uni_prospect 表关联，因为 uni_contact.country 都是空的
    country_filter = None
    if criteria.get('countries'):
        countries_list = criteria['countries']
        if isinstance(countries_list, list) and len(countries_list) > 0:
            country_filter = countries_list
    elif criteria.get('country'):
        country_filter = [criteria['country']]

    if country_filter:
        # 先从 uni_prospect 查找该国家对应的 domain
        with get_db_connection() as conn:
            placeholders = ','.join(['?' for _ in country_filter])
            domains = conn.execute(
                f"SELECT DISTINCT domain FROM uni_prospect WHERE country IN ({placeholders}) AND domain IS NOT NULL AND domain != ''",
                country_filter
            ).fetchall()
            domain_list = [d[0] for d in domains if d[0]]

        if domain_list:
            # 再从 uni_contact 查找匹配这些 domain 的联系人
            placeholders = ','.join(['?' for _ in domain_list])
            where_clauses.append(f"c.domain IN ({placeholders})")
            params.extend(domain_list)
        else:
            # 该国家没有对应的 domain，返回空结果
            return [], 0

    if criteria.get('domain'):
        where_clauses.append("c.domain LIKE ?")
        params.append(f"%{criteria['domain']}%")

    # 发送状态
    if criteria.get('send_status') is not None:
        if criteria['send_status'] == 0:
            where_clauses.append("c.send_count = 0")
        else:
            where_clauses.append("c.send_count > 0")

    # 已读状态
    if criteria.get('read_status') is not None:
        where_clauses.append("c.is_read = ?")
        params.append(criteria['read_status'])

    # 退信状态
    if criteria.get('bounce_status') is not None:
        where_clauses.append("c.is_bounced = ?")
        params.append(criteria['bounce_status'])

    # 发送次数范围
    send_count_range = criteria.get('send_count')
    if send_count_range:
        if send_count_range == '0':
            where_clauses.append("c.send_count = 0")
        elif send_count_range == '1-3':
            where_clauses.append("c.send_count BETWEEN 1 AND 3")
        elif send_count_range == '4+':
            where_clauses.append("c.send_count >= 4")

    # 最后联系时间
    last_sent_days = criteria.get('last_sent_days')
    if last_sent_days:
        where_clauses.append(
            "(c.last_sent_at IS NULL OR datetime(c.last_sent_at) < datetime('now', 'localtime', '-{} days'))".format(last_sent_days)
        )

    where_sql = "WHERE " + " AND ".join(where_clauses)

    query = f"""
    SELECT c.contact_id, c.cli_id, c.email, c.domain, c.contact_name,
           CASE WHEN c.country IS NOT NULL AND c.country != '' THEN c.country ELSE p.country END as country,
           c.position, c.phone,
           CASE WHEN c.company IS NOT NULL AND c.company != '' THEN c.company
                WHEN p.prospect_name IS NOT NULL AND p.prospect_name != '' THEN p.prospect_name
                ELSE ''
           END as company,
           c.is_bounced, c.is_read,
           c.send_count, c.bounce_count, c.read_count, c.last_sent_at, c.remark,
           p.prospect_name
    FROM uni_contact c
    LEFT JOIN uni_prospect p ON c.domain = p.domain
    {where_sql}
    ORDER BY c.email
    LIMIT ? OFFSET ?
    """

    count_query = f"SELECT COUNT(*) FROM uni_contact c {where_sql}"

    with get_db_connection() as conn:
        total = conn.execute(count_query, params).fetchone()[0]
        items = conn.execute(query, params + [page_size, offset]).fetchall()
        results = [
            {k: ("" if v is None else v) for k, v in dict(row).items()}
            for row in items
        ]
        return results, total


def get_all_groups_contacts(group_ids):
    """获取多个组的合并联系人列表(去重)

    Args:
        group_ids: list 组ID列表

    Returns:
        list 合并去重后的联系人列表
    """
    all_contacts = {}

    for group_id in group_ids:
        # 先获取总数，然后获取全部联系人
        contacts, total = get_group_contacts(group_id, page_size=10000)
        # 如果总数超过10000，继续获取剩余的
        if total > 10000:
            contacts, _ = get_group_contacts(group_id, page_size=total)
        for c in contacts:
            # 以email为key去重
            email = c.get('email', '').lower()
            if email and email not in all_contacts:
                all_contacts[email] = c

    return list(all_contacts.values())


# ==================== 静态邮件组功能 ====================

def add_static_group(group_name, email_list, description=""):
    """添加静态邮件组（手动邮件列表）

    Args:
        group_name: 组名称
        email_list: list 邮件列表 [{"email": "x@x.com", "company": "公司名", "contact_name": "姓名"}, ...]
        description: 组描述

    Returns:
        (success, message) tuple
    """
    try:
        if not group_name or not group_name.strip():
            return False, "组名称不能为空"
        if not email_list or len(email_list) == 0:
            return False, "邮件列表不能为空"

        # 验证邮件格式并去重
        unique_emails = {}
        for item in email_list:
            email = item.get('email', '').strip().lower()
            if email and '@' in email:
                unique_emails[email] = {
                    'email': email,
                    'company': item.get('company', ''),
                    'contact_name': item.get('contact_name', '')
                }

        if not unique_emails:
            return False, "没有有效的邮箱地址"

        group_id = get_next_group_id()
        email_list_json = json.dumps(list(unique_emails.values()))

        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO uni_contact_group (group_id, group_name, description, group_type, email_list, contact_count)
                VALUES (?, ?, ?, 'static', ?, ?)
            """, (group_id, group_name.strip(), description, email_list_json, len(unique_emails)))
            conn.commit()

        return True, f"静态邮件组 {group_id} 创建成功，包含 {len(unique_emails)} 个邮箱"
    except Exception as e:
        return False, str(e)


def update_static_group(group_id, group_name=None, email_list=None, description=None):
    """更新静态邮件组"""
    try:
        updates = []
        params = []

        if group_name:
            updates.append("group_name = ?")
            params.append(group_name.strip())

        if description is not None:
            updates.append("description = ?")
            params.append(description)

        if email_list is not None:
            # 验证并去重
            unique_emails = {}
            for item in email_list:
                email = item.get('email', '').strip().lower()
                if email and '@' in email:
                    unique_emails[email] = {
                        'email': email,
                        'company': item.get('company', ''),
                        'contact_name': item.get('contact_name', '')
                    }
            updates.append("email_list = ?")
            params.append(json.dumps(list(unique_emails.values())))
            updates.append("contact_count = ?")
            params.append(len(unique_emails))

        if not updates:
            return True, "无需更新"

        updates.append("updated_at = NOW()")
        params.append(group_id)

        sql = f"UPDATE uni_contact_group SET {', '.join(updates)} WHERE group_id = ? AND group_type = 'static'"

        with get_db_connection() as conn:
            result = conn.execute(sql, params)
            conn.commit()
            if result.rowcount == 0:
                return False, "静态邮件组不存在"

        return True, "更新成功"
    except Exception as e:
        return False, str(e)


def get_static_group_contacts(group_id):
    """获取静态邮件组的联系人列表

    Returns:
        list 联系人列表（包含email, company, contact_name字段）
    """
    group = get_group_by_id(group_id)
    if not group or group.get('group_type') != 'static':
        return []

    email_list = json.loads(group.get('email_list', '[]') or '[]')

    # 尝试从uni_contact获取更多信息
    results = []
    for item in email_list:
        email = item.get('email', '')
        contact = get_contact_by_email(email)
        if contact:
            # 合并contact表的信息
            results.append({
                'contact_id': contact.get('contact_id', ''),
                'email': email,
                'company': item.get('company') or contact.get('company', ''),
                'contact_name': item.get('contact_name') or contact.get('contact_name', ''),
                'country': contact.get('country', ''),
                'domain': contact.get('domain', ''),
                'position': contact.get('position', ''),
                'phone': contact.get('phone', ''),
                'is_bounced': contact.get('is_bounced', 0),
                'send_count': contact.get('send_count', 0)
            })
        else:
            # 仅使用提供的信息
            results.append({
                'contact_id': '',
                'email': email,
                'company': item.get('company', ''),
                'contact_name': item.get('contact_name', ''),
                'country': '',
                'domain': '',
                'position': '',
                'phone': '',
                'is_bounced': 0,
                'send_count': 0
            })

    return results


def get_group_contacts_all_types(group_id, page=1, page_size=100):
    """获取联系人组内的联系人列表（支持动态组+静态组+客户组+手动邮件合并）

    Args:
        group_id: 组ID
        page: 页码
        page_size: 每页数量

    Returns:
        (contacts_list, total) tuple
    """
    group = get_group_by_id(group_id)
    if not group:
        return [], 0

    group_type = group.get('group_type', 'dynamic')

    if group_type == 'static':
        # 静态组：从email_list获取
        contacts = get_static_group_contacts(group_id)
        return contacts, len(contacts)
    elif group_type == 'cli_group':
        # 客户组：从uni_cli获取
        criteria = json.loads(group.get('filter_criteria', '{}') or '{}')
        contacts, total = get_cli_group_contacts(criteria, page=page, page_size=page_size)
        return contacts, total
    else:
        # 动态组：筛选条件 + 手动邮件合并
        # 1. 从筛选条件获取联系人（使用传入的page_size）
        filter_contacts, filter_total = get_group_contacts(group_id, page_size=page_size)

        # 如果总数超过page_size，继续获取剩余的联系人
        if filter_total > page_size:
            all_filter_contacts = filter_contacts[:]
            current_page = 2
            while len(all_filter_contacts) < filter_total:
                more_contacts, _ = get_group_contacts(group_id, page=current_page, page_size=page_size)
                if not more_contacts:
                    break
                all_filter_contacts.extend(more_contacts)
                current_page += 1
            filter_contacts = all_filter_contacts

        # 2. 从手动邮件列表获取
        manual_emails = json.loads(group.get('manual_emails', '[]') or '[]')
        manual_contacts = []
        for item in manual_emails:
            email = item.get('email', '').strip().lower()
            if email:
                # 尝试从contact表获取更多信息
                contact = get_contact_by_email(email)
                if contact:
                    manual_contacts.append({
                        'contact_id': contact.get('contact_id', ''),
                        'email': email,
                        'company': item.get('company') or contact.get('company', ''),
                        'contact_name': item.get('contact_name') or contact.get('contact_name', ''),
                        'country': contact.get('country', ''),
                        'domain': contact.get('domain', ''),
                        'position': contact.get('position', ''),
                        'phone': contact.get('phone', ''),
                        'is_bounced': contact.get('is_bounced', 0),
                        'send_count': contact.get('send_count', 0),
                        'source': 'manual'  # 标记来源为手动添加
                    })
                else:
                    manual_contacts.append({
                        'contact_id': '',
                        'email': email,
                        'company': item.get('company', ''),
                        'contact_name': item.get('contact_name', ''),
                        'country': '',
                        'domain': '',
                        'position': '',
                        'phone': '',
                        'is_bounced': 0,
                        'send_count': 0,
                        'source': 'manual'
                    })

        # 3. 合并去重
        all_contacts = {}
        for c in filter_contacts:
            email = c.get('email', '').lower()
            if email:
                c['source'] = 'filter'
                all_contacts[email] = c

        for c in manual_contacts:
            email = c.get('email', '').lower()
            if email and email not in all_contacts:
                all_contacts[email] = c

        total = len(all_contacts)
        contacts_list = list(all_contacts.values())

        # 分页处理
        offset = (page - 1) * page_size
        paginated = contacts_list[offset:offset + page_size]

        return paginated, total


def add_manual_emails_to_group(group_id, emails):
    """向联系人组添加手动邮件

    Args:
        group_id: 组ID
        emails: list 要添加的邮件 [{"email": "x@x.com", "company": "公司名"}, ...]

    Returns:
        (success, message) tuple
    """
    try:
        group = get_group_by_id(group_id)
        if not group:
            return False, "联系人组不存在"

        # 获取现有手动邮件
        existing_manual = json.loads(group.get('manual_emails', '[]') or '[]')
        existing_emails = {item.get('email', '').lower() for item in existing_manual}

        # 添加新邮件（去重）
        added_count = 0
        for item in emails:
            email = item.get('email', '').strip().lower()
            if email and '@' in email and email not in existing_emails:
                existing_manual.append({
                    'email': email,
                    'company': item.get('company', ''),
                    'contact_name': item.get('contact_name', '')
                })
                existing_emails.add(email)
                added_count += 1

        if added_count == 0:
            return False, "没有新增邮件（可能都已存在或格式无效）"

        # 更新数据库
        manual_emails_json = json.dumps(existing_manual)

        with get_db_connection() as conn:
            conn.execute("""
                UPDATE uni_contact_group
                SET manual_emails = ?, updated_at = NOW()
                WHERE group_id = ?
            """, (manual_emails_json, group_id))
            conn.commit()

        return True, f"成功添加 {added_count} 个邮件"
    except Exception as e:
        return False, str(e)


def remove_manual_email_from_group(group_id, email):
    """从联系人组移除手动邮件

    Args:
        group_id: 组ID
        email: 要移除的邮箱地址

    Returns:
        (success, message) tuple
    """
    try:
        group = get_group_by_id(group_id)
        if not group:
            return False, "联系人组不存在"

        existing_manual = json.loads(group.get('manual_emails', '[]') or '[]')
        email_lower = email.strip().lower()

        # 过滤掉要移除的邮件
        new_manual = [item for item in existing_manual if item.get('email', '').lower() != email_lower]

        if len(new_manual) == len(existing_manual):
            return False, "该邮件不在手动邮件列表中"

        with get_db_connection() as conn:
            conn.execute("""
                UPDATE uni_contact_group
                SET manual_emails = ?, updated_at = NOW()
                WHERE group_id = ?
            """, (json.dumps(new_manual), group_id))
            conn.commit()

        return True, "邮件已移除"
    except Exception as e:
        return False, str(e)


def get_group_manual_emails(group_id):
    """获取联系人组的手动邮件列表

    Returns:
        list 手动邮件列表 [{"email", "company", "contact_name"}, ...]
    """
    group = get_group_by_id(group_id)
    if not group:
        return []

    return json.loads(group.get('manual_emails', '[]') or '[]')


# ==================== 客户组功能（从uni_cli获取） ====================

def get_cli_regions():
    """获取uni_cli中所有的region列表"""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT DISTINCT region FROM uni_cli
            WHERE region IS NOT NULL AND region != ''
            ORDER BY region
        """).fetchall()
        return [r[0] for r in rows if r[0]]


def get_cli_credit_levels():
    """获取uni_cli中所有的credit_level列表"""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT DISTINCT credit_level FROM uni_cli
            WHERE credit_level IS NOT NULL AND credit_level != ''
            ORDER BY credit_level
        """).fetchall()
        return [r[0] for r in rows if r[0]]


def count_cli_group_contacts(criteria):
    """根据筛选条件统计客户组联系人数量

    Args:
        criteria: dict {credit_levels: [], regions: [], cli_name: ""}

    Returns:
        int 邮箱数量（分割后的）
    """
    where_clauses = ["email IS NOT NULL AND email != ''"]
    params = []

    # 信用等级筛选（多选）
    credit_levels = criteria.get('credit_levels', [])
    if credit_levels and len(credit_levels) > 0:
        placeholders = ','.join(['?' for _ in credit_levels])
        where_clauses.append(f"credit_level IN ({placeholders})")
        params.extend(credit_levels)

    # 区域筛选（多选）
    regions = criteria.get('regions', [])
    if regions and len(regions) > 0:
        placeholders = ','.join(['?' for _ in regions])
        where_clauses.append(f"region IN ({placeholders})")
        params.extend(regions)

    # 客户名称搜索
    cli_name = criteria.get('cli_name', '')
    if cli_name:
        where_clauses.append("cli_name LIKE ?")
        params.append(f"%{cli_name}%")

    where_sql = "WHERE " + " AND ".join(where_clauses)

    with get_db_connection() as conn:
        # 获取所有email并分割统计
        rows = conn.execute(f"SELECT email FROM uni_cli {where_sql}", params).fetchall()
        total_emails = 0
        for r in rows:
            email_str = r[0] or ''
            # 分割逗号（中英文）、回车分隔的邮箱
            emails = [e.strip().lower() for e in re.split(r'[，,\n\r]+', email_str) if e.strip() and '@' in e.strip()]
            total_emails += len(emails)
        return total_emails


def get_cli_group_contacts(criteria, page=1, page_size=100):
    """获取客户组的联系人列表

    Args:
        criteria: dict {credit_levels: [], regions: [], cli_name: ""}
        page: 页码
        page_size: 每页数量

    Returns:
        (contacts_list, total) tuple
    """
    where_clauses = ["email IS NOT NULL AND email != ''"]
    params = []

    # 信用等级筛选（多选）
    credit_levels = criteria.get('credit_levels', [])
    if credit_levels and len(credit_levels) > 0:
        placeholders = ','.join(['?' for _ in credit_levels])
        where_clauses.append(f"credit_level IN ({placeholders})")
        params.extend(credit_levels)

    # 区域筛选（多选）
    regions = criteria.get('regions', [])
    if regions and len(regions) > 0:
        placeholders = ','.join(['?' for _ in regions])
        where_clauses.append(f"region IN ({placeholders})")
        params.extend(regions)

    # 客户名称搜索
    cli_name = criteria.get('cli_name', '')
    if cli_name:
        where_clauses.append("cli_name LIKE ?")
        params.append(f"%{cli_name}%")

    where_sql = "WHERE " + " AND ".join(where_clauses)

    with get_db_connection() as conn:
        # 获取所有符合条件的客户
        rows = conn.execute(f"""
            SELECT cli_id, cli_name, cli_name_en, contact_name, email, region, credit_level, address, phone
            FROM uni_cli {where_sql}
            ORDER BY cli_name
        """, params).fetchall()

        # 分割邮箱并构建联系人列表
        all_contacts = []
        for r in rows:
            cli = dict(r)
            email_str = cli.get('email', '') or ''
            # 分割逗号（中英文）、回车分隔的邮箱
            emails = [e.strip().lower() for e in re.split(r'[，,\n\r]+', email_str) if e.strip() and '@' in e.strip()]

            for email in emails:
                all_contacts.append({
                    'contact_id': '',  # 客户组没有contact_id
                    'cli_id': cli.get('cli_id', ''),
                    'email': email,
                    'company': cli.get('cli_name', ''),
                    'contact_name': cli.get('contact_name', ''),
                    'country': cli.get('region', ''),
                    'region': cli.get('region', ''),
                    'credit_level': cli.get('credit_level', ''),
                    'phone': cli.get('phone', ''),
                    'address': cli.get('address', ''),
                    'is_bounced': 0,
                    'send_count': 0,
                    'source': 'cli_group'
                })

        total = len(all_contacts)
        offset = (page - 1) * page_size
        paginated = all_contacts[offset:offset + page_size]

        return paginated, total


def add_cli_group(group_name, criteria, description=""):
    """添加客户组

    Args:
        group_name: 组名称
        criteria: dict {credit_levels: [], regions: [], cli_name: ""}
        description: 组描述

    Returns:
        (success, message) tuple
    """
    try:
        if not group_name or not group_name.strip():
            return False, "组名称不能为空"

        group_id = get_next_group_id()
        criteria_json = json.dumps(criteria) if criteria else ""

        # 计算联系人数量
        contact_count = count_cli_group_contacts(criteria)

        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO uni_contact_group (group_id, group_name, description, group_type, filter_criteria, contact_count)
                VALUES (?, ?, ?, 'cli_group', ?, ?)
            """, (group_id, group_name.strip(), description, criteria_json, contact_count))
            conn.commit()

        return True, f"客户组 {group_id} 创建成功，包含 {contact_count} 个邮箱"
    except Exception as e:
        return False, str(e)


def update_cli_group(group_id, group_name=None, criteria=None, description=None):
    """更新客户组"""
    try:
        updates = []
        params = []

        if group_name:
            updates.append("group_name = ?")
            params.append(group_name.strip())

        if description is not None:
            updates.append("description = ?")
            params.append(description)

        if criteria is not None:
            updates.append("filter_criteria = ?")
            params.append(json.dumps(criteria) if criteria else "")
            # 重新计算数量
            contact_count = count_cli_group_contacts(criteria)
            updates.append("contact_count = ?")
            params.append(contact_count)

        if not updates:
            return True, "无需更新"

        updates.append("updated_at = NOW()")
        params.append(group_id)

        sql = f"UPDATE uni_contact_group SET {', '.join(updates)} WHERE group_id = ? AND group_type = 'cli_group'"

        with get_db_connection() as conn:
            result = conn.execute(sql, params)
            conn.commit()
            if result.rowcount == 0:
                return False, "客户组不存在"

        return True, "更新成功"
    except Exception as e:
        return False, str(e)


def get_all_groups_contacts_all_types(group_ids):
    """获取多个组的合并联系人列表(去重，支持动态和静态组)

    Args:
        group_ids: list 组ID列表

    Returns:
        list 合并去重后的联系人列表
    """
    all_contacts = {}

    for group_id in group_ids:
        # 先获取总数，然后获取全部联系人
        contacts, total = get_group_contacts_all_types(group_id, page_size=10000)
        # 如果总数超过10000，继续获取剩余的
        if total > 10000:
            contacts, _ = get_group_contacts_all_types(group_id, page_size=total)
        for c in contacts:
            email = c.get('email', '').lower()
            if email and email not in all_contacts:
                all_contacts[email] = c

    return list(all_contacts.values())