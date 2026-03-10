#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sale-query-needs 查询脚本
查询指定客户在指定日期或日期范围的询价需求记录

用法:
    python query_needs.py --cli_name "客户名" [--date "2026-03-01"]
    python query_needs.py --cli_name "客户名" --start_date "2026-03-01" --end_date "2026-03-07"
    python query_needs.py --cli_name "客户名" --days 7

通过 openclaw_bridge 接口操作数据库，无直接SQL语句。
"""

import argparse
import os
import sys
from datetime import datetime, timedelta

# 设置项目根目录
PROJECT_ROOT = os.environ.get('UNIULTRA_PROJECT_ROOT',
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, PROJECT_ROOT)

# 导入桥接层
from openclaw_bridge import get_db_connection, get_cli_id_by_name


def parse_date(date_str):
    """
    解析日期字符串，支持多种格式
    - "今天" / "今日" -> 今天
    - "昨天" / "昨日" -> 昨天
    - "YYYY-MM-DD" -> 指定日期
    """
    today = datetime.now().strftime("%Y-%m-%d")

    if not date_str or date_str in ["今天", "今日", "today"]:
        return today

    if date_str in ["昨天", "昨日", "yesterday"]:
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        return yesterday

    # 尝试解析 YYYY-MM-DD 格式
    try:
        parsed = datetime.strptime(date_str, "%Y-%m-%d")
        return parsed.strftime("%Y-%m-%d")
    except ValueError:
        print(f"[FAIL] 日期格式错误: {date_str}，请使用 YYYY-MM-DD 格式或 '今天'/'昨天'")
        sys.exit(1)


def parse_date_range(start_str, end_str, days):
    """
    解析日期范围
    - start_date + end_date: 指定范围
    - days: 最近N天
    返回: (start_date, end_date)
    """
    today = datetime.now()
    today_str = today.strftime("%Y-%m-%d")

    # 方式1: 指定天数（如最近7天）
    if days > 0:
        start = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        end = today_str
        return start, end

    # 方式2: 指定日期范围
    if start_str and end_str:
        return start_str, end_str

    # 方式3: 只有start_date，无end_date -> 当天
    if start_str:
        return start_str, start_str

    # 默认: 今天
    return today_str, today_str


def query_needs(cli_name, query_date=None, start_date=None, end_date=None):
    """
    查询指定客户在指定日期或日期范围的询价需求记录
    返回: (success, records/error_message)
    """
    try:
        cli_id = get_cli_id_by_name(cli_name)
        if not cli_id:
            return True, []  # 客户不存在，返回空列表

        with get_db_connection() as conn:
            # 判断是否为日期范围查询
            is_range = start_date is not None and end_date is not None

            if is_range:
                # 日期范围查询
                query = """
                SELECT
                    q.quote_id,
                    q.quote_date,
                    q.inquiry_mpn,
                    q.quoted_mpn,
                    q.inquiry_brand,
                    q.inquiry_qty,
                    q.target_price_rmb,
                    q.cost_price_rmb,
                    q.date_code,
                    q.delivery_date,
                    q.status,
                    q.is_transferred,
                    q.remark,
                    c.cli_name,
                    (COALESCE(q.quoted_mpn, '') || ' | ' ||
                     COALESCE(q.inquiry_brand, '') || ' | ' ||
                     COALESCE(CAST(q.inquiry_qty AS TEXT), '') || ' pcs | ' ||
                     COALESCE(q.date_code, '') || ' | ' ||
                     COALESCE(q.delivery_date, '') || ' | ' ||
                     COALESCE(q.is_transferred, '未转') || ' | ' ||
                     COALESCE(q.remark, '')) as combined_info
                FROM uni_quote q
                LEFT JOIN uni_cli c ON q.cli_id = c.cli_id
                WHERE q.cli_id = ?
                  AND q.quote_date >= ?
                  AND q.quote_date <= ?
                ORDER BY q.quote_date DESC, q.created_at DESC
                """
                rows = conn.execute(query, (cli_id, start_date, end_date)).fetchall()
            else:
                # 单日期查询
                query = """
                SELECT
                    q.quote_id,
                    q.quote_date,
                    q.inquiry_mpn,
                    q.quoted_mpn,
                    q.inquiry_brand,
                    q.inquiry_qty,
                    q.target_price_rmb,
                    q.cost_price_rmb,
                    q.date_code,
                    q.delivery_date,
                    q.status,
                    q.is_transferred,
                    q.remark,
                    c.cli_name,
                    (COALESCE(q.quoted_mpn, '') || ' | ' ||
                     COALESCE(q.inquiry_brand, '') || ' | ' ||
                     COALESCE(CAST(q.inquiry_qty AS TEXT), '') || ' pcs | ' ||
                     COALESCE(q.date_code, '') || ' | ' ||
                     COALESCE(q.delivery_date, '') || ' | ' ||
                     COALESCE(q.is_transferred, '未转') || ' | ' ||
                     COALESCE(q.remark, '')) as combined_info
                FROM uni_quote q
                LEFT JOIN uni_cli c ON q.cli_id = c.cli_id
                WHERE q.cli_id = ?
                  AND q.quote_date = ?
                ORDER BY q.created_at DESC
                """
                rows = conn.execute(query, (cli_id, query_date)).fetchall()

            records = [dict(row) for row in rows]
            return True, records

    except Exception as e:
        return False, f"查询异常: {str(e)}"


def format_output(cli_name, query_date, records, is_range=False, start_date=None, end_date=None):
    """
    格式化输出结果，适合聊天窗口展示
    """
    # 确定日期显示
    if is_range:
        date_display = f"{start_date} ~ {end_date}"
    else:
        date_display = query_date

    if not records:
        return f'[INFO] 客户 "{cli_name}" 在 {date_display} 暂无询价记录'

    # 按日期分组统计
    date_counts = {}
    for r in records:
        dt = r.get('quote_date', '未知')
        date_counts[dt] = date_counts.get(dt, 0) + 1

    # 构建输出
    lines = []
    lines.append(f"┌─ 客户: {records[0]['cli_name']} | 日期: {date_display} ─────────────")

    # 如果是范围查询，显示日期汇总
    if is_range and len(date_counts) > 1:
        date_summary = " | ".join([f"{dt}({cnt})" for dt, cnt in sorted(date_counts.items(), reverse=True)])
        lines.append(f"│ 日期分布: {date_summary}")
        lines.append(f"│")

    for r in records:
        # 主行: 编号 | 型号 | 品牌 | 数量 | 目标价
        quote_id = r['quote_id'][:12] + "..." if len(r['quote_id']) > 12 else r['quote_id']
        mpn = r['inquiry_mpn'] or r['quoted_mpn'] or "-"
        brand = r['inquiry_brand'] or "-"
        qty = r['inquiry_qty'] or 0
        price = f"RMB {r['target_price_rmb']:.2f}" if r['target_price_rmb'] else "未报价"

        lines.append(f"│ {quote_id} | {mpn} | {brand} | {qty} pcs | {price}")

        # 副行: combined_info
        combined = r['combined_info'] or "-"
        lines.append(f"│   → {combined}")

    lines.append(f"└─ 共 {len(records)} 条记录 ──────────────────────────────")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="查询客户询价需求记录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 查询某客户今天的询价
    python query_needs.py --cli_name "XX科技"

    # 查询某客户昨天的询价
    python query_needs.py --cli_name "XX科技" --date "昨天"

    # 查询某客户指定日期的询价
    python query_needs.py --cli_name "XX科技" --date "2026-03-01"

    # 查询某客户最近7天的询价
    python query_needs.py --cli_name "XX科技" --days 7

    # 查询某客户日期范围的询价
    python query_needs.py --cli_name "XX科技" --start_date "2026-03-01" --end_date "2026-03-07"
        """
    )

    parser.add_argument(
        "--cli_name", "-c",
        required=True,
        help="客户名称（支持模糊匹配）"
    )

    # 单日期查询（旧接口）
    parser.add_argument(
        "--date", "-d",
        default=None,
        help="查询日期，支持: '今天'/'昨天'/YYYY-MM-DD"
    )

    # 日期范围查询（新功能）
    parser.add_argument(
        "--start_date", "-s",
        default=None,
        help="日期范围起始: YYYY-MM-DD"
    )

    parser.add_argument(
        "--end_date", "-e",
        default=None,
        help="日期范围结束: YYYY-MM-DD"
    )

    parser.add_argument(
        "--days", "-D",
        type=int,
        default=0,
        help="查询最近N天（如 7 代表最近7天）"
    )

    args = parser.parse_args()

    # 判断查询模式
    has_start = args.start_date is not None
    has_end = args.end_date is not None
    has_days = args.days > 0

    if has_days:
        # 模式1: 最近N天
        start_date, end_date = parse_date_range(None, None, args.days)
        query_date = None
        is_range = True
    elif has_start or has_end:
        # 模式2: 日期范围
        start_date = args.start_date if args.start_date else args.date
        end_date = args.end_date if args.end_date else parse_date(args.date) if args.date else start_date
        start_date, end_date = parse_date_range(start_date, end_date, 0)
        query_date = None
        is_range = True
    elif args.date:
        # 模式3: 单日期（旧兼容）
        query_date = parse_date(args.date)
        start_date = None
        end_date = None
        is_range = False
    else:
        # 默认: 今天
        query_date = parse_date("今天")
        start_date = None
        end_date = None
        is_range = False

    # 执行查询
    success, result = query_needs(args.cli_name, query_date, start_date, end_date)

    if success:
        if is_range:
            output = format_output(args.cli_name, None, result, is_range=True, start_date=start_date, end_date=end_date)
        else:
            output = format_output(args.cli_name, query_date, result)
        print(output)
    else:
        print(f"[FAIL] {result}")
        sys.exit(1)


if __name__ == "__main__":
    main()