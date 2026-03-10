"""
buyer-make-koquote: 根据报价生成韩文报价单 (견적서)
用法:
  python make_koquote.py --offer_ids "b00001"
  python make_koquote.py --offer_ids "b00001,b00002"

通过 Sills.document_generator 模块生成韩文报价单，无直接SQL语句。
"""

import sys
import os
import argparse

# 设置项目根目录
PROJECT_ROOT = os.environ.get('UNIULTRA_PROJECT_ROOT',
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, PROJECT_ROOT)

# 导入文档生成模块
from Sills.document_generator import generate_koquote


def main():
    parser = argparse.ArgumentParser(description="生成韩文报价单 (buyer-make-koquote)")
    parser.add_argument("--offer_ids", required=True, help="报价编号，多个用逗号分隔")
    parser.add_argument("--output_dir", default=None, help="输出目录（可选）")

    args = parser.parse_args()

    offer_ids = [oid.strip() for oid in args.offer_ids.split(",") if oid.strip()]
    if not offer_ids:
        print("错误: 请提供至少一个报价编号")
        sys.exit(1)

    # 调用核心模块生成韩文报价单
    success, result = generate_koquote(offer_ids, output_base=args.output_dir)

    if success:
        print(f"成功 报价单生成成功！")
        print(f"文件路径: {result.get('excel_path', '')}")
        print(f"报价条数: {result.get('count', 0)}")
        print(f"客户: {result.get('cli_name', '')}")
    else:
        print(f"错误: {result}")
        sys.exit(1)


if __name__ == "__main__":
    main()