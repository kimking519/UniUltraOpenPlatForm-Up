"""
order-ci-generator-kr: 根据销售订单生成 Commercial Invoice (CI) 文件
用法:
  python make_ci.py --order_ids "d00001"
  python make_ci.py --order_ids "d00001,d00002"

通过 Sills.ci_generator 模块生成 CI，无直接SQL语句。
"""

import sys
import os
import argparse

# 设置项目根目录
PROJECT_ROOT = os.environ.get('UNIULTRA_PROJECT_ROOT',
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, PROJECT_ROOT)

# 导入 CI 生成模块
from Sills.ci_generator import generate_ci_kr


def main():
    parser = argparse.ArgumentParser(description="生成 Commercial Invoice (order-ci-generator-kr)")
    parser.add_argument("--order_ids", required=True, help="订单编号，多个用逗号分隔")
    parser.add_argument("--output_dir", default=None, help="输出目录（可选）")

    args = parser.parse_args()

    order_ids = [oid.strip() for oid in args.order_ids.split(",") if oid.strip()]
    if not order_ids:
        print("错误: 请提供至少一个订单编号")
        sys.exit(1)

    # 调用核心模块生成 CI
    success, result = generate_ci_kr(order_ids, output_base=args.output_dir)

    if success:
        print(f"成功 CI生成成功！")
        print(f"Excel路径: {result.get('excel_path', '')}")
        print(f"订单条数: {result.get('count', 0)}")
        print(f"客户: {result.get('cli_name', '')}")
        print(f"Invoice No.: {result.get('invoice_no', '')}")
    else:
        print(f"错误: {result}")
        sys.exit(1)


if __name__ == "__main__":
    main()