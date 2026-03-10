"""
sale-input-needs: 自动从销售聊天、邮件或日常笔记中提取电子元组件需求
用法:
  python auto_input.py --cli_name "客户A" --mpn "TPS54331DR" --qty 1000
  python auto_input.py --cli_name "客户A" --text "TPS54331 100 TI\nSTM32F103 500 ST"
"""

import sys
import os
import argparse

# 设置项目根目录
PROJECT_ROOT = os.environ.get('UNIULTRA_PROJECT_ROOT',
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, PROJECT_ROOT)

# 导入桥接层
from openclaw_bridge import add_quote, get_cli_id_by_name


def perform_input(cli_id, mpn, brand='', qty=0, price=0.0, remark='', date_code='3 년내', delivery_date='1~3days'):
    """通过桥接层添加询价记录"""
    data = {
        "cli_id": cli_id,
        "inquiry_mpn": mpn.upper().strip(),
        "inquiry_brand": brand,
        "inquiry_qty": qty,
        "cost_price_rmb": price,
        "remark": remark,
        "date_code": date_code,
        "delivery_date": delivery_date,
    }
    success, message = add_quote(data)
    if success:
        # 从消息中提取 quote_id
        import re
        match = re.search(r'(x\d{5})', message)
        quote_id = match.group(1) if match else "unknown"
        return True, quote_id
    return False, message


def main():
    parser = argparse.ArgumentParser(description='Auto input sales needs to UniUltra Platform')
    parser.add_argument('--cli_name', help='Client Name or ID')
    parser.add_argument('--mpn', help='MPN (e.g. TPS54331DR)')
    parser.add_argument('--qty', type=int, default=0)
    parser.add_argument('--brand', default='')
    parser.add_argument('--price', type=float, default=0.0)
    parser.add_argument('--remark', default='')
    parser.add_argument('--date_code', default='3 년내', help='批号/DC (默认：3 년내)')
    parser.add_argument('--delivery_date', default='1~3days', help='交期 (默认：1~3days)')
    parser.add_argument('--text', help='Batch text to process (format: MPN QTY BRAND REMARK)')

    args = parser.parse_args()

    # 解析客户ID
    cli_id = args.cli_name or 'C001'
    # 如果传入的是客户名称，尝试查找ID
    if cli_id and not cli_id.startswith('C'):
        found_id = get_cli_id_by_name(cli_id)
        if found_id:
            cli_id = found_id
        else:
            print(f"警告: 未找到客户 '{cli_id}'，使用原值作为ID")

    # 批量处理模式
    if args.text:
        lines = args.text.strip().split('\n')
        print(f"Processing {len(lines)} lines from text...")
        for line in lines:
            parts = line.split()
            if len(parts) >= 1:
                mpn = parts[0]
                qty = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                ok, qid = perform_input(cli_id, mpn, qty=qty)
                if ok:
                    print(f"Added: {mpn} -> {qid}")
                else:
                    print(f"Failed {mpn}: {qid}")
        return

    # 单条录入模式
    if not args.mpn:
        print("Error: --mpn is required for single entry mode.")
        return

    ok, res = perform_input(cli_id, args.mpn, args.brand, args.qty, args.price, args.remark, args.date_code, args.delivery_date)

    if ok:
        print(f"Successfully recorded demand. ID: {res}")
    else:
        print(f"Input failed: {res}")


if __name__ == "__main__":
    main()