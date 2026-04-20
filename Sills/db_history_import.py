"""
历史客户订单Excel导入模块
用于将历史订单数据从Excel批量导入到系统
"""

import pandas as pd
import os
import tempfile
from datetime import datetime
from Sills.base import get_db_connection, get_exchange_rates
from Sills.db_cli import get_next_cli_id


def parse_excel(file_path):
    """
    解析Excel文件，返回DataFrame
    期望的列名：日期, 客户订单号, 客户名称, 询价型号, 报价型号, 询价品牌, 报价品牌,
              询价数量, 报价数量, 目标价(RMB), 成本价(RMB), 报价(RMB), 批号, 交期, 备注, 状态
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


def import_history_orders(file_path, emp_id):
    """
    主导入函数
    返回: (success_count, skip_count, fail_count, errors[])
    """
    success_count = 0
    skip_count = 0
    fail_count = 0
    errors = []

    try:
        # 解析Excel
        df = parse_excel(file_path)

        if df.empty:
            return 0, 0, 0, ["Excel文件为空"]

        # 检查必要列
        required_cols = ['客户订单号', '客户名称', '询价型号', '报价数量', '报价(RMB)']
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            return 0, 0, 0, [f"缺少必要列: {', '.join(missing_cols)}"]

        # 按客户订单号分组
        grouped = df.groupby('客户订单号')

        with get_db_connection() as conn:
            for order_no, group in grouped:
                try:
                    # 开启事务
                    order_date = None
                    cli_id = None

                    # 获取第一条记录的客户信息和日期
                    first_row = group.iloc[0]
                    cli_name = first_row.get('客户名称', '')

                    # 查找或创建客户
                    cli_id, err = find_or_create_customer(cli_name, conn)
                    if err:
                        errors.append(f"订单 {order_no}: {err}")
                        fail_count += len(group)
                        continue

                    # 获取订单日期（日期列）
                    order_date_raw = first_row.get('日期', '')
                    if pd.notna(order_date_raw) and str(order_date_raw).strip():
                        try:
                            # 尝试解析日期
                            if isinstance(order_date_raw, str):
                                order_date = datetime.strptime(order_date_raw.strip(), '%Y-%m-%d').strftime('%Y-%m-%d')
                            else:
                                order_date = pd.to_datetime(order_date_raw).strftime('%Y-%m-%d')
                        except:
                            order_date = datetime.now().strftime('%Y-%m-%d')
                    else:
                        order_date = datetime.now().strftime('%Y-%m-%d')

                    # 检查订单是否已存在
                    existing_order = conn.execute(
                        "SELECT manager_id FROM uni_order_manager WHERE customer_order_no = ?",
                        (str(order_no),)
                    ).fetchone()

                    if existing_order:
                        manager_id = existing_order['manager_id']
                    else:
                        # 创建客户订单
                        manager_id = f"OM{datetime.now().strftime('%Y%m%d%H%M%S')}{os.urandom(2).hex().upper()}"
                        conn.execute("""
                            INSERT INTO uni_order_manager (manager_id, customer_order_no, order_date, cli_id)
                            VALUES (?, ?, ?, ?)
                        """, (manager_id, str(order_no), order_date, cli_id))

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

                            # 检查重复（使用报价型号）
                            if check_duplicate(manager_id, quoted_mpn, conn):
                                errors.append(f"订单 {order_no} 型号 {quoted_mpn}: 已存在，跳过")
                                skip_count += 1
                                continue

                            # 准备报价数据
                            inquiry_brand = str(row.get('询价品牌', '')).strip()
                            quoted_brand = str(row.get('报价品牌', '')).strip()
                            if not quoted_brand:
                                quoted_brand = inquiry_brand

                            inquiry_qty = int(row.get('询价数量', 0) or 0)
                            quoted_qty = int(row.get('报价数量', 1) or 1)

                            target_price = float(row.get('目标价(RMB)', 0) or 0)
                            cost_price = float(row.get('成本价(RMB)', 0) or 0)
                            offer_price = float(row.get('报价(RMB)', 0) or 0)

                            date_code = str(row.get('批号', '')).strip()
                            delivery_date = str(row.get('交期', '')).strip()
                            remark = str(row.get('备注', '')).strip()
                            status = str(row.get('状态', '询价中') or '询价中').strip()

                            # 计算汇率价格
                            krw_val, usd_val = get_exchange_rates()
                            if krw_val > 10:
                                price_kwr = round(offer_price * krw_val, 1)
                            else:
                                price_kwr = round(offer_price / krw_val, 1) if krw_val else 0.0
                            price_usd = round(offer_price * usd_val, 2) if usd_val else 0.0

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

                            # 插入报价记录 (quote_id 为 None，因为是历史数据)
                            conn.execute("""
                                INSERT INTO uni_offer (
                                    offer_id, offer_date, quote_id, inquiry_mpn, quoted_mpn,
                                    inquiry_brand, quoted_brand, inquiry_qty, quoted_qty,
                                    target_price_rmb, cost_price_rmb, offer_price_rmb, price_kwr, price_usd,
                                    date_code, delivery_date, emp_id, remark, status, is_transferred
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                offer_id, datetime.now().strftime('%Y-%m-%d'), None,
                                inquiry_mpn, quoted_mpn, inquiry_brand, quoted_brand,
                                inquiry_qty, quoted_qty,
                                target_price, cost_price, offer_price, price_kwr, price_usd,
                                date_code, delivery_date, emp_id, remark, status, '未转'
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

                except Exception as e:
                    errors.append(f"订单 {order_no}: {str(e)}")
                    fail_count += len(group)
                    conn.rollback()

        return success_count, skip_count, fail_count, errors

    except Exception as e:
        return 0, 0, 0, [f"导入过程出错: {str(e)}"]