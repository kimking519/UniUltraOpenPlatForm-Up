#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sale-edit-needs 编辑脚本
修改需求管理表 (uni_quote) 中的记录字段

用法:
    # 编辑模式
    python edit_needs.py --quote_id "x00001" --date_code "2526+" --delivery_date "2026-04-15"

    # 报价总览模式
    python edit_needs.py --overview --cli_name "客户名"
    python edit_needs.py --overview --quote_id "x00001"

通过 openclaw_bridge 接口操作数据库，无直接SQL语句。
"""

import argparse
import os
import sys

# 设置项目根目录
PROJECT_ROOT = os.environ.get('UNIULTRA_PROJECT_ROOT',
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, PROJECT_ROOT)

# 导入桥接层
from openclaw_bridge import get_db_connection, get_quote_by_id, update_quote, get_cli_id_by_name


def show_overview_by_client(cli_name):
    """
    查询客户报价总览
    """
    cli_id = get_cli_id_by_name(cli_name)
    if not cli_id:
        return []

    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT q.quote_id, q.inquiry_mpn, q.inquiry_brand, q.inquiry_qty,
                   q.date_code, q.delivery_date, q.status, c.cli_name
            FROM uni_quote q
            LEFT JOIN uni_cli c ON q.cli_id = c.cli_id
            WHERE c.cli_id = ?
            ORDER BY q.created_at DESC
        """, (cli_id,)).fetchall()
        return [dict(row) for row in rows]


def show_overview_by_quote_id(quote_id):
    """
    查询指定需求编号的详情
    """
    record = get_quote_by_id(quote_id)
    if record:
        # 获取客户名称
        with get_db_connection() as conn:
            cli_row = conn.execute(
                "SELECT cli_name FROM uni_cli WHERE cli_id = ?",
                (record.get('cli_id'),)
            ).fetchone()
            if cli_row:
                record['cli_name'] = cli_row['cli_name']
    return record


def format_overview_output(cli_name, records):
    """
    格式化报价总览输出
    """
    if not records:
        return f'[INFO] 客户 "{cli_name}" 暂无报价记录'

    lines = []
    lines.append(f"┌─ 客户: {records[0]['cli_name']} | 报价总览 ─────────────")

    for r in records:
        quote_id = (
            r["quote_id"][:12] + "..." if len(r["quote_id"]) > 12 else r["quote_id"]
        )
        mpn = r["inquiry_mpn"] or "-"
        brand = r["inquiry_brand"] or "-"
        qty = r["inquiry_qty"] or 0
        dc = r["date_code"] or "N/A"
        delivery = r["delivery_date"] or "N/A"

        lines.append(
            f"│ {quote_id} | {mpn} | {brand} | {qty} pcs | DC: {dc} | 货期: {delivery}"
        )

    lines.append(f"└─ 共 {len(records)} 条记录 ──────────────────────────────")

    return "\n".join(lines)


def format_detail_output(record):
    """
    格式化单条记录详情输出
    """
    if not record:
        return "[INFO] 未找到该需求记录"

    lines = []
    lines.append(f"┌─ 需求详情: {record['quote_id']} ─────────────")
    lines.append(f"│ 客户: {record.get('cli_name', 'N/A')}")
    lines.append(f"│ 型号: {record.get('inquiry_mpn') or 'N/A'}")
    lines.append(f"│ 品牌: {record.get('inquiry_brand') or 'N/A'}")
    lines.append(f"│ 数量: {record.get('inquiry_qty') or 0} pcs")
    lines.append(f"│ 目标价: RMB {record.get('target_price_rmb') or 0:.2f}")
    lines.append(f"│ 成本价: RMB {record.get('cost_price_rmb') or 0:.2f}")
    lines.append(f"│ 批号(DC): {record.get('date_code') or 'N/A'}")
    lines.append(f"│ 货期: {record.get('delivery_date') or 'N/A'}")
    lines.append(f"│ 状态: {record.get('status') or 'N/A'}")
    lines.append(f"│ 备注: {record.get('remark') or '无'}")
    lines.append(f"└─ 记录查询完成 ──────────────────────────────")

    return "\n".join(lines)


def format_update_output(quote_id, updates):
    """
    格式化更新结果输出
    """
    lines = []
    lines.append(f"[OK] 需求 {quote_id} 更新成功！")
    lines.append(f"     已修改字段:")

    field_names = {
        "target_price_rmb": "目标价",
        "cost_price_rmb": "成本价",
        "date_code": "批号(DC)",
        "delivery_date": "货期",
        "inquiry_qty": "数量",
        "quoted_mpn": "报价型号",
        "quoted_brand": "报价品牌",
        "remark": "备注",
        "status": "状态",
    }

    for field, value in updates.items():
        name = field_names.get(field, field)
        lines.append(f"       - {name}: {value}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="编辑需求管理表记录",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 报价总览（按客户）
    python edit_needs.py --overview --cli_name "XX科技"

    # 报价总览（按需求编号）
    python edit_needs.py --overview --quote_id "x00001"

    # 修改单个字段
    python edit_needs.py --quote_id "x00001" --date_code "2526+"

    # 修改多个字段
    python edit_needs.py --quote_id "x00001" --date_code "2526+" --delivery_date "现货" --inquiry_qty 500
        """,
    )

    # 模式选择
    parser.add_argument("--overview", "-o", action="store_true", help="报价总览模式")

    # 查询参数
    parser.add_argument(
        "--cli_name", "-c", help="客户名称（用于报价总览，支持模糊匹配）"
    )

    # 编辑参数
    parser.add_argument("--quote_id", "-q", help="需求编号（编辑模式必须）")

    parser.add_argument("--target_price_rmb", type=float, help="目标价/单价（人民币）")

    parser.add_argument("--cost_price_rmb", type=float, help="成本价（人民币）")

    parser.add_argument("--date_code", help="批号/DC")

    parser.add_argument("--delivery_date", help="交期/货期")

    parser.add_argument("--inquiry_qty", type=int, help="可提供数量")

    parser.add_argument("--quoted_mpn", help="报价型号（注意：只修改报价型号，不修改询价型号）")

    parser.add_argument("--quoted_brand", help="报价品牌（注意：只修改报价品牌，不修改询价品牌）")

    parser.add_argument("--remark", help="备注")

    parser.add_argument("--status", help="状态（如：询价中/已报价）")

    args = parser.parse_args()

    # 报价总览模式
    if args.overview:
        if args.quote_id:
            # 按需求编号查询详情
            record = show_overview_by_quote_id(args.quote_id)
            print(format_detail_output(record))
        elif args.cli_name:
            # 按客户查询总览
            records = show_overview_by_client(args.cli_name)
            print(format_overview_output(args.cli_name, records))
        else:
            print("[FAIL] 报价总览模式需要 --cli_name 或 --quote_id 参数")
            sys.exit(1)
        return

    # 编辑模式
    if not args.quote_id:
        print("[FAIL] 编辑模式需要 --quote_id 参数")
        sys.exit(1)

    # 收集需要更新的字段
    updates = {}
    if args.target_price_rmb is not None:
        updates["target_price_rmb"] = args.target_price_rmb
    if args.cost_price_rmb is not None:
        updates["cost_price_rmb"] = args.cost_price_rmb
    if args.date_code is not None:
        updates["date_code"] = args.date_code
    if args.delivery_date is not None:
        updates["delivery_date"] = args.delivery_date
    if args.inquiry_qty is not None:
        updates["inquiry_qty"] = args.inquiry_qty
    if args.quoted_mpn is not None:
        updates["quoted_mpn"] = args.quoted_mpn
    if args.quoted_brand is not None:
        updates["quoted_brand"] = args.quoted_brand
    if args.remark is not None:
        updates["remark"] = args.remark
    if args.status is not None:
        updates["status"] = args.status

    if not updates:
        print("[FAIL] 未指定需要修改的字段，请至少提供一个更新参数")
        sys.exit(1)

    # 验证需求编号是否存在
    record = get_quote_by_id(args.quote_id)
    if not record:
        print(f"[FAIL] 需求编号 {args.quote_id} 不存在")
        sys.exit(1)

    # 执行更新 - 使用 openclaw_bridge 的 update_quote
    success, message = update_quote(args.quote_id, updates)

    if success:
        print(format_update_output(args.quote_id, updates))
    else:
        print(f"[FAIL] {message}")
        sys.exit(1)


if __name__ == "__main__":
    main()