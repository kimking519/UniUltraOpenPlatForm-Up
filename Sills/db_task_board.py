"""
任务看板数据库操作模块
实时扫描业务表生成任务卡片
"""
import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager
from Sills.base import get_db_connection


def is_today(created_at, today_str=None) -> bool:
    """检查 created_at 是否是当天"""
    if created_at is None:
        return False
    if today_str is None:
        today_str = datetime.now().strftime('%Y-%m-%d')

    # 处理 datetime 对象
    if isinstance(created_at, datetime):
        return created_at.strftime('%Y-%m-%d') == today_str

    # 处理字符串格式 'YYYY-MM-DD HH:MM:SS' 或 'YYYY-MM-DDTHH:MM:SS'
    date_str = str(created_at).split(' ')[0] if ' ' in str(created_at) else str(created_at).split('T')[0]
    return date_str == today_str


# ========== 规则配置函数 ==========

# 规则值合理范围定义
RULE_RANGES = {
    'task_rule_quote_timeout_hours': (1, 168),      # 1小时到7天
    'task_rule_quote_flow_timeout_hours': (1, 168), # 1小时到7天
    'task_rule_mail_contact_days': (1, 90),         # 1天到3个月
    'task_rule_quote_days': (1, 365)                # 1天到1年
}


def get_task_rule(key: str, default: int) -> int:
    """从 global_settings 读取规则配置，返回整数阈值

    如果配置不存在，自动写入默认值并返回
    """
    with get_db_connection() as conn:
        result = conn.execute(
            "SELECT value FROM global_settings WHERE key = ?", (key,)
        ).fetchone()
        if result and result[0]:
            try:
                return int(result[0])
            except ValueError:
                pass
        # 返回默认值并写入（初始化）- 使用 PostgreSQL ON CONFLICT DO NOTHING
        conn.execute(
            "INSERT INTO global_settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO NOTHING",
            (key, str(default))
        )
        conn.commit()
        return default


def set_task_rule(key: str, value: int) -> bool:
    """更新规则配置（带范围验证）

    Raises:
        ValueError: 规则值超出合理范围
    """
    min_val, max_val = RULE_RANGES.get(key, (1, 365))
    if not (min_val <= value <= max_val):
        raise ValueError(f"规则值必须在 {min_val}-{max_val} 范围内")

    with get_db_connection() as conn:
        # 使用 PostgreSQL ON CONFLICT DO UPDATE 替代 INSERT OR REPLACE
        conn.execute(
            "INSERT INTO global_settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, str(value))
        )
        conn.commit()
    return True


def get_all_task_rules() -> dict:
    """获取所有任务规则配置"""
    return {
        'quote_timeout_hours': get_task_rule('task_rule_quote_timeout_hours', 48),
        'quote_flow_timeout_hours': get_task_rule('task_rule_quote_flow_timeout_hours', 24),
        'mail_contact_days': get_task_rule('task_rule_mail_contact_days', 7),
        'quote_days': get_task_rule('task_rule_quote_days', 30)
    }


def scan_crm_tasks(status_filter=None, limit=20, offset=0) -> list[dict]:
    """A类: CRM营销任务 - 实时扫描 uni_contact"""
    with get_db_connection() as conn:
        # 使用可配置的天数阈值
        contact_days = get_task_rule('task_rule_mail_contact_days', 7)
        days_ago = (datetime.now() - timedelta(days=contact_days)).strftime('%Y-%m-%d %H:%M:%S')

        query = """
            SELECT
                c.contact_id as task_id,
                c.email,
                c.contact_name,
                c.company,
                c.send_count,
                c.last_sent_at,
                'contact' as ref_type,
                c.contact_id as ref_id,
                CASE
                    WHEN c.send_count = 0 THEN 'pending'
                    WHEN c.last_sent_at IS NULL THEN 'pending'
                    WHEN c.last_sent_at < ? THEN 'pending'
                    ELSE 'completed'
                END as status,
                'CRM' as task_type,
                '新名单/周期预警' as title
            FROM uni_contact c
            WHERE c.is_bounced = 0 AND c.is_deleted = 0
              AND (c.send_count = 0 OR c.last_sent_at IS NULL OR c.last_sent_at < ?)
            ORDER BY c.created_at DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, (days_ago, days_ago, limit, offset)).fetchall()
        return [dict(row) for row in rows]


def scan_quote_tasks(status_filter=None, limit=20, offset=0) -> list[dict]:
    """B类: 报价/询价任务 - 实时扫描 uni_quote"""
    with get_db_connection() as conn:
        # 使用可配置的小时阈值
        quote_timeout_hours = get_task_rule('task_rule_quote_timeout_hours', 48)
        flow_timeout_hours = get_task_rule('task_rule_quote_flow_timeout_hours', 24)
        # 报价管理天数范围（只显示最近N天的报价）
        quote_days = get_task_rule('task_rule_quote_days', 30)

        quote_timeout = (datetime.now() - timedelta(hours=quote_timeout_hours)).strftime('%Y-%m-%d %H:%M:%S')
        flow_timeout = (datetime.now() - timedelta(hours=flow_timeout_hours)).strftime('%Y-%m-%d %H:%M:%S')
        quote_days_ago = (datetime.now() - timedelta(days=quote_days)).strftime('%Y-%m-%d %H:%M:%S')

        # 实际状态值: '询价中', '已报价', '缺货' (来自 templates/quote.html)
        # '缺货' 不生成看板任务
        # 新增: 状态流转超时检查（已报价但超过N小时未转单）
        # 新增: 报价管理天数范围过滤（只显示N天内的报价）
        query = """
            SELECT
                q.quote_id as task_id,
                q.inquiry_mpn,
                q.cli_id,
                cli.cli_name as customer_name,
                q.status as original_status,
                q.is_transferred,
                q.created_at,
                'quote' as ref_type,
                q.quote_id as ref_id,
                CASE
                    WHEN q.status = '询价中' AND q.is_transferred = '未转' THEN 'pending'
                    WHEN q.status = '询价中' AND q.created_at < ? THEN 'pending'
                    WHEN q.status = '已报价' AND q.is_transferred = '未转' AND q.created_at < ? THEN 'pending'
                    WHEN q.status = '已报价' THEN 'inspection'
                    WHEN q.is_transferred = '已转' THEN 'completed'
                    ELSE 'pending'
                END as status,
                '报价' as task_type,
                q.inquiry_mpn as title
            FROM uni_quote q
            LEFT JOIN uni_cli cli ON q.cli_id = cli.cli_id
            WHERE q.status != '缺货'
              AND q.created_at >= ?
              AND (q.status = '询价中'
                   OR q.status = '已报价'
                   OR (q.is_transferred = '未转' AND q.created_at < ?))
            ORDER BY q.created_at DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, (quote_timeout, flow_timeout, quote_days_ago, quote_timeout, limit, offset)).fetchall()
        return [dict(row) for row in rows]


def scan_order_tasks(status_filter=None, limit=20, offset=0) -> list[dict]:
    """C类: 销售订单任务 - 实时扫描 uni_order + uni_buy"""
    with get_db_connection() as conn:

        # 待采购: 有订单但无采购单
        pending_purchase_query = """
            SELECT
                o.order_id as task_id,
                o.cli_id,
                cli.cli_name as customer_name,
                o.is_finished,
                o.is_paid,
                'order' as ref_type,
                o.order_id as ref_id,
                'pending' as status,
                '采购' as task_type,
                '待采购' as title
            FROM uni_order o
            LEFT JOIN uni_cli cli ON o.cli_id = cli.cli_id
            LEFT JOIN uni_buy b ON o.order_id = b.order_id
            WHERE b.order_id IS NULL AND o.is_finished = 0
            ORDER BY o.created_at DESC
            LIMIT ? OFFSET ?
        """

        # 回款管理: 已发货未付款
        pending_payment_query = """
            SELECT
                o.order_id as task_id,
                o.cli_id,
                cli.cli_name as customer_name,
                o.is_paid,
                'order' as ref_type,
                o.order_id as ref_id,
                'in_progress' as status,
                '回款' as task_type,
                '待收款' as title
            FROM uni_order o
            LEFT JOIN uni_cli cli ON o.cli_id = cli.cli_id
            LEFT JOIN uni_buy b ON o.order_id = b.order_id
            WHERE b.is_shipped = 1 AND o.is_paid = 0
            ORDER BY o.created_at DESC
            LIMIT ? OFFSET ?
        """

        pending_purchase = [dict(row) for row in conn.execute(pending_purchase_query, (limit, offset)).fetchall()]
        pending_payment = [dict(row) for row in conn.execute(pending_payment_query, (limit, offset)).fetchall()]

        return pending_purchase + pending_payment


def scan_alert_tasks(status_filter=None, limit=20, offset=0) -> list[dict]:
    """D类: 综合预警 - 查询 uni_task_alert 表"""
    with get_db_connection() as conn:

        where_clause = "WHERE status = ?" if status_filter else ""
        params = [status_filter, limit, offset] if status_filter else [limit, offset]

        query = f"""
            SELECT
                alert_id as task_id,
                alert_type,
                alert_title,
                alert_content,
                ref_type,
                ref_id,
                status,
                priority,
                'alert' as task_type,
                alert_title as title
            FROM uni_task_alert
            {where_clause}
            ORDER BY priority DESC, created_at DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]


def get_all_tasks(status_filter=None, page=1, page_size=20) -> tuple[list, int]:
    """获取所有任务（简化分页：不使用聚合分页，每列独立加载）

    设计决策：由于任务来自多个异构数据源，聚合分页会产生语义问题。
    采用简化方案：返回指定状态列的任务，按优先级排序，前端可按列分别请求。
    """
    limit = page_size
    offset = (page - 1) * page_size

    tasks = []

    # 按状态过滤加载对应源的任务
    if status_filter == 'pending' or status_filter is None:
        tasks.extend(scan_crm_tasks('pending', limit, offset))
        tasks.extend(scan_quote_tasks('pending', limit, offset))
        tasks.extend(scan_order_tasks('pending', limit, offset))
        tasks.extend(scan_alert_tasks('pending', limit, offset))

    if status_filter == 'in_progress' or status_filter is None:
        tasks.extend(scan_quote_tasks('in_progress', limit, offset))
        tasks.extend(scan_order_tasks('in_progress', limit, offset))
        tasks.extend(scan_alert_tasks('in_progress', limit, offset))

    if status_filter == 'inspection' or status_filter is None:
        tasks.extend(scan_quote_tasks('inspection', limit, offset))
        tasks.extend(scan_order_tasks('inspection', limit, offset))
        tasks.extend(scan_alert_tasks('inspection', limit, offset))

    if status_filter == 'completed' or status_filter is None:
        tasks.extend(scan_alert_tasks('completed', limit, offset))

    # 如果指定状态过滤，只返回该状态的任务
    if status_filter:
        tasks = [t for t in tasks if t.get('status') == status_filter]

    # 已完成任务只保留当天的（一天之外的从看板移除）
    today_str = datetime.now().strftime('%Y-%m-%d')
    tasks = [t for t in tasks if t.get('status') != 'completed' or is_today(t.get('created_at'), today_str)]

    # 按优先级/时间排序（兼容 datetime 对象和字符串）
    def sort_key(x):
        priority = x.get('priority', 1)
        created_at = x.get('created_at')
        # 处理 datetime 对象、字符串、None 等不同类型
        if created_at is None:
            return (priority, '')
        if isinstance(created_at, datetime):
            return (priority, created_at.isoformat())
        return (priority, str(created_at) if created_at else '')

    tasks.sort(key=sort_key, reverse=True)

    total = len(tasks)
    return tasks[:page_size], total


def get_task_counts() -> dict:
    """获取各状态的任务计数（用于摘要栏显示）

    单独查询每个源的计数，确保摘要栏显示准确数字。
    使用可配置阈值计算任务数量。
    """
    counts = {'pending': 0, 'in_progress': 0, 'inspection': 0, 'completed': 0}

    # 获取可配置阈值
    contact_days = get_task_rule('task_rule_mail_contact_days', 7)
    quote_days = get_task_rule('task_rule_quote_days', 30)
    days_ago = (datetime.now() - timedelta(days=contact_days)).strftime('%Y-%m-%d %H:%M:%S')
    quote_days_ago = (datetime.now() - timedelta(days=quote_days)).strftime('%Y-%m-%d %H:%M:%S')

    with get_db_connection() as conn:

        # CRM计数 - 使用可配置天数阈值
        result = conn.execute("""
            SELECT COUNT(*) FROM uni_contact
            WHERE is_bounced = 0 AND is_deleted = 0
              AND (send_count = 0 OR last_sent_at IS NULL OR last_sent_at < ?)
        """, (days_ago,)).fetchone()
        counts['pending'] += result[0]

        # 报价计数 - 使用报价管理天数范围
        result = conn.execute("""
            SELECT COUNT(*) FROM uni_quote
            WHERE status != '缺货' AND status = '询价中' AND is_transferred = '未转' AND created_at >= ?
        """, (quote_days_ago,)).fetchone()
        counts['pending'] += result[0]

        result = conn.execute("""
            SELECT COUNT(*) FROM uni_quote WHERE status = '已报价' AND created_at >= ?
        """, (quote_days_ago,)).fetchone()
        counts['inspection'] += result[0]

        result = conn.execute("""
            SELECT COUNT(*) FROM uni_quote WHERE is_transferred = '已转'
        """).fetchone()
        counts['completed'] += result[0]

        # 订单计数
        result = conn.execute("""
            SELECT COUNT(*) FROM uni_order o
            LEFT JOIN uni_buy b ON o.order_id = b.order_id
            WHERE b.order_id IS NULL AND o.is_finished = 0
        """).fetchone()
        counts['pending'] += result[0]

        # 回款任务（已发货未付款）
        result = conn.execute("""
            SELECT COUNT(*) FROM uni_order o
            LEFT JOIN uni_buy b ON o.order_id = b.order_id
            WHERE b.is_shipped = 1 AND o.is_paid = 0
        """).fetchone()
        counts['in_progress'] += result[0]

        result = conn.execute("""
            SELECT COUNT(*) FROM uni_order WHERE is_finished = 1
        """).fetchone()
        counts['completed'] += result[0]

        # 预警计数
        rows = conn.execute("""
            SELECT status, COUNT(*) FROM uni_task_alert GROUP BY status
        """).fetchall()
        for row in rows:
            if row[0] in counts:
                counts[row[0]] += row[1]

    return counts


def update_task_status(ref_type: str, ref_id: str, new_status: str) -> tuple[bool, str]:
    """更新任务状态（直接修改业务表）"""
    try:
        with get_db_connection() as conn:

            if ref_type == 'quote':
                # uni_quote: 映射到原有status字段
                status_map = {
                    'pending': '待处理',
                    'in_progress': '询价中',
                    'inspection': '已报价',
                    'completed': '已完成'
                }
                conn.execute(
                    "UPDATE uni_quote SET status = ? WHERE quote_id = ?",
                    (status_map.get(new_status, new_status), ref_id)
                )

            elif ref_type == 'order':
                # uni_order: 映射到 is_finished 字段
                finished_map = {
                    'pending': 0,
                    'in_progress': 0,
                    'inspection': 0,
                    'completed': 1
                }
                conn.execute(
                    "UPDATE uni_order SET is_finished = ? WHERE order_id = ?",
                    (finished_map.get(new_status, 0), ref_id)
                )

            elif ref_type == 'alert':
                # uni_task_alert: 直接更新status字段
                conn.execute(
                    "UPDATE uni_task_alert SET status = ?, updated_at = datetime('now', 'localtime') WHERE alert_id = ?",
                    (new_status, ref_id)
                )

            conn.commit()
            return True, f"状态已更新为 {new_status}"

    except Exception as e:
        return False, str(e)


def add_alert(data: dict) -> tuple[bool, str]:
    """添加综合预警"""
    try:
        alert_id = f"AL-{datetime.now().strftime('%Y%m%d%H%M%S')}-{str(hash(data['alert_title']) % 10000).zfill(4)}"

        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO uni_task_alert (alert_id, alert_type, ref_type, ref_id,
                                          alert_title, alert_content, status, priority, created_by)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
            """, (
                alert_id,
                data.get('alert_type', '重要备注'),
                data.get('ref_type'),
                data.get('ref_id'),
                data['alert_title'],
                data.get('alert_content'),
                data.get('priority', 1),
                data.get('created_by')
            ))
            conn.commit()
            return True, f"提醒已添加: {alert_id}"
    except Exception as e:
        return False, str(e)


def delete_alert(alert_id: str) -> tuple[bool, str]:
    """删除综合预警"""
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM uni_task_alert WHERE alert_id = ?", (alert_id,))
            conn.commit()
            return True, "提醒已删除"
    except Exception as e:
        return False, str(e)