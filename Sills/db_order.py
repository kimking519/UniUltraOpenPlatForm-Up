import sqlite3
import uuid
from datetime import datetime
from Sills.base import get_db_connection, get_exchange_rates

def generate_order_no():
    """生成格式为 d + 5位递增数字的订单编号"""
    with get_db_connection() as conn:
        last_order = conn.execute("SELECT order_no FROM uni_order WHERE order_no LIKE 'd%' ORDER BY order_no DESC LIMIT 1").fetchone()
        if last_order:
            try:
                last_num = int(last_order['order_no'][1:])  # 去掉前缀d，获取数字部分
                new_num = last_num + 1
            except:
                new_num = 1
        else:
            new_num = 1
        return f"d{new_num:05d}"  # 格式化为5位数，例如 d00001

def get_order_list(page=1, page_size=10, search_kw="", cli_id="", start_date="", end_date="", is_finished="", is_transferred=""):
    offset = (page - 1) * page_size
    query = """
    FROM uni_order o
    JOIN uni_cli c ON o.cli_id = c.cli_id
    LEFT JOIN uni_offer off ON o.offer_id = off.offer_id
    LEFT JOIN uni_vendor v ON off.vendor_id = v.vendor_id
    LEFT JOIN uni_quote q ON off.quote_id = q.quote_id
    WHERE (o.inquiry_mpn LIKE ? OR o.order_id LIKE ? OR c.cli_name LIKE ?)
    """
    params = [f"%{search_kw}%", f"%{search_kw}%", f"%{search_kw}%"]

    if cli_id:
        query += " AND o.cli_id = ?"
        params.append(cli_id)
    if start_date:
        query += " AND o.order_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND o.order_date <= ?"
        params.append(end_date)
    if is_finished in ('0', '1'):
        query += " AND o.is_finished = ?"
        params.append(int(is_finished))
    if is_transferred:
        query += " AND o.is_transferred = ?"
        params.append(is_transferred)

    count_sql = "SELECT COUNT(*) " + query
    data_sql = """SELECT o.*, c.cli_name, c.margin_rate,
        off.quoted_mpn, off.offer_price_rmb, off.cost_price_rmb AS source_cost,
        off.inquiry_qty, off.quoted_qty, off.date_code, off.delivery_date,
        v.vendor_name
        """ + query + " ORDER BY o.order_date DESC, o.created_at DESC LIMIT ? OFFSET ?"
    params_with_limit = params + [page_size, offset]

    with get_db_connection() as conn:
        total = conn.execute(count_sql, params).fetchone()[0]
        rows = conn.execute(data_sql, params_with_limit).fetchall()

        results = [dict(r) for r in rows]
        krw_val, usd_val = get_exchange_rates()

        for r in results:
            price = r.get('price_rmb')
            if price is None or str(price).strip() == "":
                price = r.get('offer_price_rmb') or 0.0
            price = float(price)
            r['price_rmb'] = price

            cost = float(r.get('cost_price_rmb') or 0.0)
            qty = int(r.get('quoted_qty') or 0)
            r['profit'] = round(price - cost, 3)
            r['total_profit'] = int(round(r['profit'] * qty, 0))

            # 只在数据库中没有值时才计算汇率，不覆盖已保存的值
            try:
                if not r.get('price_kwr') or float(r.get('price_kwr') or 0) == 0:
                    if krw_val > 10: r['price_kwr'] = round(price * krw_val, 1)
                    else: r['price_kwr'] = round(price / krw_val, 1) if krw_val else 0.0
                if not r.get('price_usd') or float(r.get('price_usd') or 0) == 0:
                    if usd_val > 10: r['price_usd'] = round(price * usd_val, 2)
                    else: r['price_usd'] = round(price / usd_val, 2) if usd_val else 0.0
            except:
                pass

    return results, total

def add_order(data, conn=None):
    try:
        order_id = data.get('order_id')

        must_close = False
        if conn is None:
            conn = get_db_connection()
            must_close = True

        try:
            if not order_id:
                # 生成递增的5位数销售订单编号
                last_order = conn.execute("SELECT order_id FROM uni_order WHERE order_id LIKE 'd%' ORDER BY order_id DESC LIMIT 1").fetchone()
                if last_order:
                    try:
                        last_num = int(last_order['order_id'][1:])  # 去掉前缀d，获取数字部分
                        new_num = last_num + 1
                    except:
                        new_num = 1
                else:
                    new_num = 1
                order_id = f"d{new_num:05d}"  # 格式化为5位数，例如 d00001

            existing = conn.execute("SELECT order_id FROM uni_order WHERE order_id = ?", (order_id,)).fetchone()
            if existing:
                return False, f"订单编号 {order_id} 已存在"

            cli_id = data.get('cli_id')
            if not cli_id or str(cli_id).strip() == "":
                return False, "缺少客户编号"

            cli = conn.execute("SELECT cli_name FROM uni_cli WHERE cli_id = ?", (cli_id,)).fetchone()
            if not cli:
                return False, f"客户编号 {cli_id} 在数据库中不存在"
            cli_name = cli['cli_name']

            offer_id = data.get('offer_id')
            if offer_id and str(offer_id).strip() == "":
                offer_id = None

            if offer_id:
                off = conn.execute("SELECT offer_id FROM uni_offer WHERE offer_id = ?", (offer_id,)).fetchone()
                if not off:
                    return False, f"关联报价单 {offer_id} 不存在"

            order_date = data.get('order_date') or datetime.now().strftime("%Y-%m-%d")
            paid_amount = float(data.get('paid_amount') or 0.0)
            order_no = data.get('order_no') or order_id  # order_no 使用与 order_id 相同的值

            sql = """
            INSERT INTO uni_order (
                order_id, order_no, order_date, cli_id, offer_id, inquiry_mpn, inquiry_brand,
                price_rmb, price_kwr, price_usd, cost_price_rmb, is_finished, is_paid, paid_amount, return_status, remark, is_transferred
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                order_id, order_no, order_date, cli_id, offer_id,
                data.get('inquiry_mpn'), data.get('inquiry_brand'),
                data.get('price_rmb'), data.get('price_kwr'), data.get('price_usd'),
                data.get('cost_price_rmb'),
                int(data.get('is_finished', 0)),
                int(data.get('is_paid', 0)),
                paid_amount,
                data.get('return_status', '正常'),
                data.get('remark', ''),
                '未转'
            )
            conn.execute(sql, params)
            if must_close:
                conn.commit()
            return True, f"销售订单 {order_id} 创建成功"
        finally:
            if must_close:
                conn.close()
    except Exception as e:
        return False, f"数据库错误：{str(e)}"

def batch_import_order(text, cli_id):
    """批量导入订单，优化：单事务 + executemany"""
    import io, csv
    f = io.StringIO(text.strip())
    reader = csv.reader(f)
    success_count = 0
    errors = []

    try:
        rows = list(reader)
        if not rows: return 0, []
        start_idx = 0
        if len(rows[0]) > 0 and ("报价编号" in rows[0][0] or "型号" in str(rows[0])):
            start_idx = 1

        with get_db_connection() as conn:
            cli = conn.execute("SELECT cli_name FROM uni_cli WHERE cli_id = ?", (cli_id,)).fetchone()
            if not cli:
                return 0, [f"客户编号 {cli_id} 不存在"]
            cli_name = cli['cli_name']

            insert_data = []
            for row in rows[start_idx:]:
                if not row or len(row) < 1: continue
                try:
                    offer_id = row[0] if len(row) > 0 and str(row[0]).strip() != "" else None
                    if offer_id and not str(offer_id).startswith('O'):
                        offer_id = None

                    inquiry_mpn = row[4] if len(row) > 4 and row[4] else (row[3] if len(row) > 3 else "")
                    inquiry_brand = row[6] if len(row) > 6 and row[6] else (row[5] if len(row) > 5 else "")
                    remark = row[17] if len(row) > 17 else ""

                    if not offer_id and not inquiry_mpn:
                        continue

                    # 生成递增的5位数销售订单编号
                    last_order = conn.execute("SELECT order_id FROM uni_order WHERE order_id LIKE 'd%' ORDER BY order_id DESC LIMIT 1").fetchone()
                    if last_order:
                        try:
                            last_num = int(last_order['order_id'][1:])
                            new_num = last_num + 1
                        except:
                            new_num = 1
                    else:
                        new_num = 1
                    order_id = f"d{new_num:05d}"
                    order_no = order_id  # order_no 使用与 order_id 相同的值
                    order_date = datetime.now().strftime("%Y-%m-%d")

                    insert_data.append((
                        order_id, order_no, order_date, cli_id, offer_id,
                        inquiry_mpn, inquiry_brand, 0, 0, 0, 0, 0, 0, 0.0, '正常', remark, '未转'
                    ))
                except Exception as e:
                    errors.append(f"行解析失败：{str(e)}")

            if insert_data:
                sql = """
                INSERT INTO uni_order (
                    order_id, order_no, order_date, cli_id, offer_id, inquiry_mpn, inquiry_brand,
                    price_rmb, price_kwr, price_usd, cost_price_rmb, is_finished, is_paid, paid_amount, return_status, remark, is_transferred
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                conn.executemany(sql, insert_data)
                conn.commit()
                success_count = len(insert_data)

    except Exception as e:
        errors.append(f"导入失败：{str(e)}")

    return success_count, errors

def batch_convert_from_offer(offer_ids, cli_id=None):
    """批量从报价转订单，优化：单事务"""
    if not offer_ids: return False, "未选中记录"
    try:
        success_count = 0
        errors = []
        with get_db_connection() as conn:
            placeholders = ','.join(['?'] * len(offer_ids))
            rows = conn.execute(f"SELECT * FROM uni_offer WHERE offer_id IN ({placeholders})", offer_ids).fetchall()

            for row in rows:
                offer_data = dict(row)
                existing = conn.execute("SELECT order_id FROM uni_order WHERE offer_id = ?", (offer_data['offer_id'],)).fetchone()
                if existing:
                    errors.append(f"{offer_data['offer_id']}: 已存在销售订单")
                    continue

                final_cli_id = cli_id
                if not final_cli_id:
                    quote_info = conn.execute("SELECT cli_id FROM uni_quote WHERE quote_id = ?", (offer_data['quote_id'],)).fetchone()
                    if quote_info:
                        final_cli_id = quote_info['cli_id']

                if not final_cli_id:
                    errors.append(f"{offer_data['offer_id']}: 无法确定客户 ID")
                    continue

                # 生成递增的5位数销售订单编号
                last_order = conn.execute("SELECT order_id FROM uni_order WHERE order_id LIKE 'd%' ORDER BY order_id DESC LIMIT 1").fetchone()
                if last_order:
                    try:
                        last_num = int(last_order['order_id'][1:])
                        new_num = last_num + 1
                    except:
                        new_num = 1
                else:
                    new_num = 1
                order_id = f"d{new_num:05d}"
                order_no = order_id  # order_no 使用与 order_id 相同的值

                sql = """
                INSERT INTO uni_order (
                    order_id, order_no, order_date, cli_id, offer_id, inquiry_mpn, inquiry_brand,
                    price_rmb, price_kwr, price_usd, cost_price_rmb, is_finished, is_paid, paid_amount, return_status, remark, is_transferred
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                params = (
                    order_id, order_no, datetime.now().strftime("%Y-%m-%d"), final_cli_id, offer_data['offer_id'],
                    offer_data['quoted_mpn'] or offer_data['inquiry_mpn'],
                    offer_data['quoted_brand'] or offer_data['inquiry_brand'],
                    offer_data['offer_price_rmb'], offer_data['price_kwr'], offer_data['price_usd'],
                    offer_data['cost_price_rmb'], 0, 0, 0.0, '正常', offer_data.get('remark', ''), '未转'
                )
                conn.execute(sql, params)
                conn.execute("UPDATE uni_offer SET is_transferred = '已转' WHERE offer_id = ?", (offer_data['offer_id'],))
                success_count += 1

            if success_count > 0:
                conn.commit()

        if success_count == 0 and errors:
            return False, errors[0]
        return True, f"成功转换 {success_count} 条记录" + (f" (失败 {len(errors)} 条)" if errors else "")
    except Exception as e:
        return False, str(e)

def batch_delete_order(order_ids):
    if not order_ids: return True, "无选中记录"
    try:
        with get_db_connection() as conn:
            placeholders = ','.join(['?'] * len(order_ids))
            conn.execute(f"DELETE FROM uni_order WHERE order_id IN ({placeholders})", order_ids)
            conn.commit()
            return True, "批量删除成功"
    except Exception as e:
        if "FOREIGN KEY constraint failed" in str(e):
            return False, "删除失败：部分记录已被 [采购记录]引用，无法直接删除。"
        return False, str(e)

def update_order_status(order_id, field, value):
    try:
        if field not in ['is_finished', 'is_paid', 'return_status']:
            return False, "非法字段"

        sql = f"UPDATE uni_order SET {field} = ? WHERE order_id = ?"
        with get_db_connection() as conn:
            conn.execute(sql, (int(value), order_id))
            conn.commit()
            return True, "状态更新成功"
    except Exception as e:
        return False, str(e)

def update_order(order_id, data):
    try:
        set_cols = []
        params = []
        for k, v in data.items():
            set_cols.append(f"{k} = ?")
            params.append(v)
        if not set_cols: return True, "No changes"

        sql = f"UPDATE uni_order SET {', '.join(set_cols)} WHERE order_id = ?"
        params.append(order_id)

        with get_db_connection() as conn:
            conn.execute(sql, params)
            conn.commit()
            return True, "更新成功"
    except Exception as e:
        return False, str(e)

def delete_order(order_id):
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM uni_order WHERE order_id = ?", (order_id,))
            conn.commit()
            return True, "删除成功"
    except Exception as e:
        if "FOREIGN KEY constraint failed" in str(e):
            return False, "删除失败：记录已被 [采购记录]引用，无法直接删除。"
        return False, str(e)
