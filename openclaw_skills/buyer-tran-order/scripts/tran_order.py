"""
buyer-tran-order: 报价转入订单
用法:
  python tran_order_bridge.py --offer_id "b00015"

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
from openclaw_bridge import (
    DB_PATH,
    get_offer_by_id,
    add_order,
    mark_offer_transferred,
    get_quote_by_id,
    get_cli_list,
)


def transfer_offer_to_order(offer_id):
    """
    将单条报价记录转入订单表。
    返回 (成功与否, 消息, order_id)
    """
    # 1. 查询报价记录
    offer_data = get_offer_by_id(offer_id)
    if not offer_data:
        return False, f"报价编号 [{offer_id}] 不存在。", None

    # 2. 获取客户 ID
    cli_id = None
    quote_id = offer_data.get("quote_id")
    if quote_id:
        quote_info = get_quote_by_id(quote_id)
        if quote_info:
            cli_id = quote_info.get("cli_id")

    if not cli_id:
        return False, f"报价 {offer_id} 无法确定客户 ID（关联的 quote_id 为空或不存在）。", None

    # 3. 获取客户名称（用于输出）
    cli_name = "未知"
    cli_list, _ = get_cli_list(search_kw=cli_id)
    if cli_list:
        cli_name = cli_list[0].get("cli_name", "未知")

    # 4. 准备订单数据
    inquiry_mpn = offer_data.get("quoted_mpn") or offer_data.get("inquiry_mpn", "")
    inquiry_brand = offer_data.get("quoted_brand") or offer_data.get("inquiry_brand", "")

    order_data = {
        "cli_id": cli_id,
        "offer_id": offer_id,
        "inquiry_mpn": inquiry_mpn,
        "inquiry_brand": inquiry_brand,
        "price_rmb": offer_data.get("offer_price_rmb", 0) or 0,
        "price_kwr": offer_data.get("price_kwr", 0) or 0,
        "price_usd": offer_data.get("price_usd", 0) or 0,
        "cost_price_rmb": offer_data.get("cost_price_rmb", 0) or 0,
        "remark": offer_data.get("remark", ""),
    }

    # 5. 创建订单
    success, message = add_order(order_data)
    if not success:
        return False, f"创建订单失败: {message}", None

    # 从消息中提取 order_id
    import re
    match = re.search(r'(d\d{5})', message)
    order_id = match.group(1) if match else "unknown"

    # 6. 标记报价已转
    mark_offer_transferred(offer_id)

    # 7. 格式化输出
    price_rmb = offer_data.get("offer_price_rmb", 0) or 0
    lines = [
        "✅ 转入订单成功！",
        f"   报价编号: {offer_id}",
        f"   订单编号: {order_id}",
        f"   客    户: {cli_name}",
        f"   型    号: {inquiry_mpn}",
        f"   报价(RMB): ¥{float(price_rmb):.2f}",
    ]
    return True, "\n".join(lines), order_id


def main():
    parser = argparse.ArgumentParser(
        description="报价转入订单 (buyer-tran-order) - 使用桥接层"
    )
    parser.add_argument("--offer_id", required=True,
                        help="报价编号（必填）")

    args = parser.parse_args()

    try:
        ok, msg, order_id = transfer_offer_to_order(args.offer_id)
        print(msg)
        if not ok:
            sys.exit(1)

    except Exception as e:
        print(f"❌ 操作异常: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()