"""
sale-query-quote: 查询报价记录
用法:
  python query_quote_bridge.py --search "TPS54331"
  python query_quote_bridge.py --cli_id "C001"

通过桥接层访问数据库，无直接SQL语句。
"""

import sys
import os
import argparse

# 设置项目根目录
PROJECT_ROOT = os.environ.get('UNIULTRA_PROJECT_ROOT',
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, PROJECT_ROOT)

# 导入桥接层
from openclaw_bridge import get_offer_list


def format_offer_row(row):
    """格式化报价记录输出"""
    lines = [
        f"报价编号: {row.get('offer_id', '')}",
        f"  型号: {row.get('inquiry_mpn', '')} / {row.get('quoted_mpn', '')}",
        f"  品牌: {row.get('inquiry_brand', '')} / {row.get('quoted_brand', '')}",
        f"  数量: {row.get('quoted_qty', 0)}",
        f"  报价(RMB): ¥{float(row.get('offer_price_rmb', 0) or 0):.2f}",
        f"  成本(RMB): ¥{float(row.get('cost_price_rmb', 0) or 0):.2f}",
        f"  客户: {row.get('cli_name', '')}",
        f"  状态: {row.get('is_transferred', '未转')}",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="查询报价记录 (sale-query-quote) - 使用桥接层")
    parser.add_argument("--search", default="", help="搜索关键词（型号/报价编号/供应商）")
    parser.add_argument("--cli_id", default="", help="客户ID筛选")
    parser.add_argument("--start_date", default="", help="开始日期")
    parser.add_argument("--end_date", default="", help="结束日期")
    parser.add_argument("--is_transferred", default="", help="转换状态筛选")
    parser.add_argument("--page", type=int, default=1, help="页码")
    parser.add_argument("--page_size", type=int, default=20, help="每页数量")

    args = parser.parse_args()

    # 调用桥接层查询
    items, total = get_offer_list(
        page=args.page,
        page_size=args.page_size,
        search_kw=args.search,
        start_date=args.start_date,
        end_date=args.end_date,
        cli_id=args.cli_id,
        is_transferred=args.is_transferred,
    )

    if not items:
        print("未找到匹配的报价记录")
        return

    print(f"找到 {total} 条报价记录 (第 {args.page} 页)\n")
    print("=" * 60)

    for item in items:
        print(format_offer_row(item))
        print("-" * 60)


if __name__ == "__main__":
    main()