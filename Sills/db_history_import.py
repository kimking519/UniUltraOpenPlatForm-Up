"""
历史客户订单Excel导入模块
用于将历史订单数据从Excel批量导入到系统
支持字段：日期, 交易编码, 客户订单号, 客户名称, 询价型号, 报价型号, 询价品牌, 报价品牌,
          询价数量, 报价数量, 目标价(RMB), 成本价(RMB), 报价(RMB), 报价(KRW), 报价(USD), 报价(JPY), 批号, 交期, 备注
"""

import pandas as pd
import os
import tempfile
from datetime import datetime
from Sills.base import get_db_connection
from Sills.db_cli import get_next_cli_id


def parse_excel(file_path):
    """
    解析Excel文件，返回DataFrame
    新字段列表：日期, 交易编码, 客户订单号, 客户名称, 询价型号, 报价型号, 询价品牌, 报价品牌,
              询价数量, 报价数量, 目标价(RMB), 成本价(RMB), 报价(RMB), 报价(KRW), 报价(USD), 报价(JPY), 批号, 交期, 备注
    """
    try:
        df = pd.read_excel(file_path)
        # 清理列名，去除空格
        df.columns = [str(col).strip() for col in df.columns]
        return df
    except Exception as e:
        raise Exception(f"Excel解析失败: {str(e)}")


def find_or_create_customer(cli_name, conn):
    """
    按名称查找客户，不存在则创建
    返回 cli_id
    """
    if not cli_name or str(cli_name).strip() == "":
        return None, "客户名称为空"

    cli_name = str(cli_name).strip()

    # 查找现有客户（忽略大小写和空格）
    existing = conn.execute("""
        SELECT cli_id FROM uni_cli
        WHERE REPLACE(LOWER(cli_name), ' ', '') = REPLACE(LOWER(?), ' ', '')
    """, (cli_name,)).fetchone()

    if existing:
        return existing['cli_id'], None

    # 创建新客户
    cli_id = get_next_cli_id()
    conn.execute("""
        INSERT INTO uni_cli (cli_id, cli_name, cli_full_name)
        VALUES (?, ?, ?)
    """, (cli_id, cli_name, cli_name))

    return cli_id, None


def check_duplicate(manager_id, mpn, conn):
    """
    检查是否重复（同一订单+型号）
    """
    if not manager_id or not mpn:
        return False

    existing = conn.execute("""
        SELECT r.id FROM uni_order_manager_rel r
        JOIN uni_offer o ON r.offer_id = o.offer_id
        WHERE r.manager_id = ? AND (o.inquiry_mpn = ? OR o.quoted_mpn = ?)
    """, (manager_id, mpn, mpn)).fetchone()

    return existing is not None


def find_bank_transaction_by_code(transaction_code, conn):
    """
    根据交易编码查找银行流水
    返回 transaction_id 或 None
    """
    if not transaction_code or str(transaction_code).strip() == "":
        return None

    transaction_code = str(transaction_code).strip()

    # 通过 transaction_no 或 ledger_no 查找
    row = conn.execute("""
        SELECT transaction_id FROM uni_bank_transaction
        WHERE transaction_no = ? OR ledger_no = ?
        LIMIT 1
    """, (transaction_code, transaction_code)).fetchone()

    if row:
        return row['transaction_id']
    return None


def import_history_orders(file_path, emp_id):
    """
    主导入函数
    返回: (success_count, skip_count, fail_count, errors[])
    """
    print(f"[导入] 开始导入: {file_path}")
    success_count = 0
    skip_count = 0
    fail_count = 0
    errors = []
    linked_transactions = []  # 记录已关联的交易

    try:
        # 解析Excel
        print("[导入] 解析Excel...")
        df = parse_excel(file_path)
        print(f"[导入] 解析完成，行数: {len(df)}, 列名: {list(df.columns)}")

        if df.empty:
            return 0, 0, 0, ["Excel文件为空"]

        # 检查必要列
        required = ['客户订单号', '客户名称', '询价型号', '报价数量']

        if not all(col in df.columns for col in required):
            missing = [col for col in required if col not in df.columns]
            return 0, 0, 0, [f"模板格式不匹配，缺少字段: {', '.join(missing)}"]

        # 分组字段和客户名字段
        group_col = '客户订单号'
        cli_name_col = '客户名称'

        # 按分组字段分组
        grouped = df.groupby(group_col)

        with get_db_connection() as conn:
            for order_no, group in grouped:
                try:
                    cli_id = None
                    transaction_code = None  # 交易编码（用于关联银行流水）

                    # 获取第一条记录的客户信息和交易编码
                    first_row = group.iloc[0]
                    cli_name = first_row.get(cli_name_col, '')
                    transaction_code = str(first_row.get('交易编码', '') or '').strip()

                    # 解析订单日期
                    order_date_raw = first_row.get('日期', '') if '日期' in df.columns else ''
                    if pd.notna(order_date_raw) and str(order_date_raw).strip():
                        try:
                            if isinstance(order_date_raw, str):
                                order_date = datetime.strptime(order_date_raw.strip(), '%Y-%m-%d').strftime('%Y-%m-%d')
                            else:
                                order_date = pd.to_datetime(order_date_raw).strftime('%Y-%m-%d')
                        except:
                            order_date = datetime.now().strftime('%Y-%m-%d')
                    else:
                        order_date = datetime.now().strftime('%Y-%m-%d')

                    # 查找或创建客户
                    cli_id, err = find_or_create_customer(cli_name, conn)
                    if err:
                        errors.append(f"订单 {order_no}: {err}")
                        fail_count += len(group)
                        continue

                    # 检查订单是否已存在
                    existing_order = conn.execute(
                        "SELECT manager_id FROM uni_order_manager WHERE customer_order_no = ?",
                        (str(order_no),)
                    ).fetchone()

                    if existing_order:
                        manager_id = existing_order['manager_id']
                        # 更新交易编码（如果原订单没有且当前有）
                        if transaction_code:
                            conn.execute(
                                "UPDATE uni_order_manager SET transaction_code = ? WHERE manager_id = ? AND transaction_code IS NULL",
                                (transaction_code, manager_id)
                            )
                    else:
                        # 创建客户订单（保存交易编码）
                        manager_id = f"OM{datetime.now().strftime('%Y%m%d%H%M%S')}{os.urandom(2).hex().upper()}"
                        conn.execute("""
                            INSERT INTO uni_order_manager (manager_id, customer_order_no, order_date, cli_id, transaction_code)
                            VALUES (?, ?, ?, ?, ?)
                        """, (manager_id, str(order_no), order_date, cli_id, transaction_code if transaction_code else None))

                    # 遍历每行报价数据
                    for idx, row in group.iterrows():
                        try:
                            # 询价型号为空则跳过
                            inquiry_mpn = str(row.get('询价型号', '')).strip()
                            if not inquiry_mpn:
                                errors.append(f"订单 {order_no} 第{idx+1}行: 询价型号为空")
                                skip_count += 1
                                continue

                            # 报价型号默认使用询价型号
                            quoted_mpn = str(row.get('报价型号', '')).strip()
                            if not quoted_mpn:
                                quoted_mpn = inquiry_mpn

                            # 准备报价数据
                            inquiry_brand = str(row.get('询价品牌', '') or '').strip()
                            quoted_brand = str(row.get('报价品牌', '') or '').strip()
                            if not quoted_brand:
                                quoted_brand = inquiry_brand

                            # 安全数值转换
                            def safe_int(val, default=0):
                                try:
                                    v = row.get(val)
                                    if v is None or (isinstance(v, float) and pd.isna(v)):
                                        return default
                                    return int(float(v) if v else default)
                                except:
                                    return default

                            def safe_float(val, default=0.0):
                                try:
                                    v = row.get(val)
                                    if v is None or (isinstance(v, float) and pd.isna(v)):
                                        return default
                                    return float(v) if v else default
                                except:
                                    return default

                            inquiry_qty = safe_int('询价数量', 0)
                            quoted_qty = safe_int('报价数量', 1)

                            target_price = safe_float('目标价(RMB)', 0.0)
                            cost_price = safe_float('成本价(RMB)', 0.0)
                            offer_price = safe_float('报价(RMB)', 0.0)
                            offer_price_krw = safe_float('报价(KRW)', 0.0)
                            offer_price_usd = safe_float('报价(USD)', 0.0)
                            offer_price_jpy = safe_float('报价(JPY)', 0.0)

                            date_code = str(row.get('批号', '') or '').strip()
                            delivery_date = str(row.get('交期', '') or '').strip()
                            remark = str(row.get('备注', '') or '').strip()

                            # 生成报价ID
                            last_offer = conn.execute(
                                "SELECT offer_id FROM uni_offer WHERE offer_id LIKE 'b%' ORDER BY offer_id DESC LIMIT 1"
                            ).fetchone()
                            if last_offer:
                                try:
                                    last_num = int(last_offer['offer_id'][1:])
                                    new_num = last_num + 1
                                except:
                                    new_num = 1
                            else:
                                new_num = 1
                            offer_id = f"b{new_num:05d}"

                            # 插入报价记录 (quote_id 为 None，因为是历史数据，但需要设置 cli_id)
                            conn.execute("""
                                INSERT INTO uni_offer (
                                    offer_id, offer_date, quote_id, cli_id, inquiry_mpn, quoted_mpn,
                                    inquiry_brand, quoted_brand, inquiry_qty, quoted_qty,
                                    target_price_rmb, cost_price_rmb, offer_price_rmb, price_kwr, price_usd, price_jpy,
                                    date_code, delivery_date, emp_id, remark, status, is_transferred
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                offer_id, datetime.now().strftime('%Y-%m-%d'), None, cli_id,
                                inquiry_mpn, quoted_mpn, inquiry_brand, quoted_brand,
                                inquiry_qty, quoted_qty,
                                target_price, cost_price, offer_price, offer_price_krw, offer_price_usd, offer_price_jpy,
                                date_code, delivery_date, emp_id, remark, '询价中', '未转'
                            ))

                            # 建立关联
                            conn.execute("""
                                INSERT INTO uni_order_manager_rel (manager_id, offer_id)
                                VALUES (?, ?)
                            """, (manager_id, offer_id))

                            success_count += 1

                        except Exception as e:
                            errors.append(f"订单 {order_no} 型号 {quoted_mpn}: {str(e)}")
                            fail_count += 1

                    # 提交当前订单的事务
                    conn.commit()

                    # 更新订单汇总
                    from Sills.db_order_manager import recalculate_manager_totals
                    recalculate_manager_totals(manager_id)

                    # 自动关联银行流水（如果有交易编码）
                    if transaction_code:
                        try:
                            transaction_id = find_bank_transaction_by_code(transaction_code, conn)
                            if transaction_id:
                                # 获取订单总金额用于关联
                                manager = conn.execute(
                                    "SELECT total_price_rmb FROM uni_order_manager WHERE manager_id = ?",
                                    (manager_id,)
                                ).fetchone()
                                if manager and manager['total_price_rmb']:
                                    allocation_amount = float(manager['total_price_rmb'])

                                    # 检查是否已存在关联
                                    existing_link = conn.execute(
                                        "SELECT ledger_id FROM uni_bank_ledger WHERE transaction_id = ? AND manager_id = ?",
                                        (transaction_id, manager_id)
                                    ).fetchone()

                                    if not existing_link:
                                        # 创建关联
                                        from Sills.db_bank_ledger import create_ledger
                                        success, result = create_ledger(
                                            transaction_id=transaction_id,
                                            manager_id=manager_id,
                                            allocation_amount=allocation_amount,
                                            is_primary=1,
                                            match_type='manual',
                                            created_by=emp_id,
                                            remark=f'历史订单导入自动关联，交易编码: {transaction_code}'
                                        )
                                        if success:
                                            linked_transactions.append({
                                                'order_no': order_no,
                                                'transaction_code': transaction_code
                                            })
                                        else:
                                            errors.append(f"订单 {order_no} 关联流水失败: {result}")
                        except Exception as e:
                            errors.append(f"订单 {order_no} 关联流水时出错: {str(e)}")

                except Exception as e:
                    errors.append(f"订单 {order_no}: {str(e)}")
                    fail_count += len(group)
                    conn.rollback()

        # 返回结果
        result_msg = f"成功导入 {success_count} 条报价"
        if linked_transactions:
            result_msg += f"，自动关联 {len(linked_transactions)} 条银行流水"

        return success_count, skip_count, fail_count, errors

    except Exception as e:
        return 0, 0, 0, [f"导入过程出错: {str(e)}"]