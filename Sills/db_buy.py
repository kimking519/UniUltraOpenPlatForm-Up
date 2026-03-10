import sqlite3
import uuid
from datetime import datetime
from Sills.base import get_db_connection, get_exchange_rates

def get_buy_list(page=1, page_size=10, search_kw="", order_id="", start_date="", end_date="", cli_id="", is_shipped=""):
    offset = (page - 1) * page_size
    
    base_query = """
    FROM uni_buy b
    LEFT JOIN uni_order ord ON b.order_id = ord.order_id
    LEFT JOIN uni_vendor v ON b.vendor_id = v.vendor_id
    LEFT JOIN uni_cli c ON ord.cli_id = c.cli_id
    LEFT JOIN uni_offer off ON ord.offer_id = off.offer_id
    WHERE (b.buy_id LIKE ? OR b.buy_mpn LIKE ? OR v.vendor_name LIKE ?)
    """
    params = [f"%{search_kw}%", f"%{search_kw}%", f"%{search_kw}%"]
    
    if order_id:
        base_query += " AND b.order_id = ?"
        params.append(order_id)
    if start_date:
        base_query += " AND b.buy_date >= ?"
        params.append(start_date)
    if end_date:
        base_query += " AND b.buy_date <= ?"
        params.append(end_date)
    if cli_id:
        base_query += " AND ord.cli_id = ?"
        params.append(cli_id)
    if is_shipped in ('0', '1'):
        base_query += " AND b.is_shipped = ?"
        params.append(int(is_shipped))
        
    query = f"""
    SELECT b.*, ord.order_no, v.vendor_name, v.address as vendor_address, c.cli_id, c.cli_name, c.margin_rate, off.offer_price_rmb,
           off.inquiry_qty, off.date_code, off.delivery_date
    {base_query}
    ORDER BY b.created_at DESC
    LIMIT ? OFFSET ?
    """
    
    count_query = f"SELECT COUNT(*) {base_query}"
    
    with get_db_connection() as conn:
        total = conn.execute(count_query, params).fetchone()[0]
        items = conn.execute(query, params + [page_size, offset]).fetchall()

        results = []
        for row in items:
            d = dict(row)
            results.append({k: ("" if v is None else v) for k, v in d.items()})

        # 使用缓存的汇率
        krw_val, usd_val = get_exchange_rates()

        for r in results:
            # 采购单价(RMB)作为计算基础
            buy_price = float(r.get('buy_price_rmb') or 0)

            # 采购单价(KWR) - 只在数据库没有值时才计算
            if not r.get('price_kwr') or float(r.get('price_kwr') or 0) == 0:
                try:
                    if krw_val > 10: r['price_kwr'] = round(buy_price * krw_val, 1)
                    else: r['price_kwr'] = round(buy_price / krw_val, 1) if krw_val else 0.0
                except:
                    r['price_kwr'] = 0.0

            # 采购单价(USD) - 只在数据库没有值时才计算
            if not r.get('price_usd') or float(r.get('price_usd') or 0) == 0:
                try:
                    if usd_val > 10: r['price_usd'] = round(buy_price * usd_val, 2)
                    else: r['price_usd'] = round(buy_price / usd_val, 2) if usd_val else 0.0
                except:
                    r['price_usd'] = 0.0

        return results, total

def add_buy(data, conn=None):
    try:
        buy_id = data.get('buy_id')

        # Validation Logic
        must_close = False
        if conn is None:
            conn = get_db_connection()
            must_close = True

        try:
            if not buy_id:
                # 生成递增的5位数采购编号
                last_buy = conn.execute("SELECT buy_id FROM uni_buy WHERE buy_id LIKE 'c%' ORDER BY buy_id DESC LIMIT 1").fetchone()
                if last_buy:
                    try:
                        last_num = int(last_buy['buy_id'][1:])  # 去掉前缀c，获取数字部分
                        new_num = last_num + 1
                    except:
                        new_num = 1
                else:
                    new_num = 1
                buy_id = f"c{new_num:05d}"  # 格式化为5位数，例如 c00001

            # Check uniqueness
            existing = conn.execute("SELECT buy_id FROM uni_buy WHERE buy_id = ?", (buy_id,)).fetchone()
            if existing:
                return False, f"采购单编号 {buy_id} 已存在"

            order_id = data.get('order_id')
            if order_id and str(order_id).strip() == "":
                order_id = None
            
            # Check Order
            if order_id:
                ord_row = conn.execute("SELECT order_id FROM uni_order WHERE order_id = ?", (order_id,)).fetchone()
                if not ord_row:
                    return False, f"关联销售订单 {order_id} 不存在"

            vendor_id = data.get('vendor_id')
            if vendor_id and str(vendor_id).strip() == "":
                vendor_id = None
            
            # Check Vendor
            if vendor_id:
                v_row = conn.execute("SELECT vendor_id FROM uni_vendor WHERE vendor_id = ?", (vendor_id,)).fetchone()
                if not v_row:
                    return False, f"供应商编号 {vendor_id} 不存在"

            buy_date = data.get('buy_date') or datetime.now().strftime("%Y-%m-%d")
            
            price = 0.0
            try: price = float(data.get('buy_price_rmb') or 0.0)
            except: pass

            qty = 0
            try: qty = int(data.get('buy_qty') or 0)
            except: pass

            sales_price = 0.0
            try: sales_price = float(data.get('sales_price_rmb') or 0.0)
            except: pass

            total_amount = round(price * qty, 2)
            
            sql = """
            INSERT INTO uni_buy (
                buy_id, buy_date, order_id, vendor_id, buy_mpn, buy_brand, buy_price_rmb, buy_qty,
                sales_price_rmb, total_amount, is_source_confirmed, is_ordered, is_instock, is_shipped, remark
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                buy_id, buy_date, order_id, vendor_id,
                data.get('buy_mpn', ''), data.get('buy_brand', ''),
                price, qty, sales_price, total_amount,
                int(data.get('is_source_confirmed', 0)),
                int(data.get('is_ordered', 0)),
                int(data.get('is_instock', 0)),
                int(data.get('is_shipped', 0)),
                data.get('remark', '')
            )
            conn.execute(sql, params)
            if must_close:
                conn.commit()
            return True, f"采购单 {buy_id} 创建成功"
        finally:
            if must_close:
                conn.close()
    except Exception as e:
        return False, f"数据库错误: {str(e)}"

def batch_import_buy(text):
    import io, csv
    f = io.StringIO(text.strip())
    reader = csv.reader(f)
    success_count = 0
    errors = []
    
    try:
        rows = list(reader)
        if not rows: return 0, []
        
        # Heuristic skip header
        start_idx = 0
        if len(rows[0]) > 0 and ("订单" in rows[0][0] or "型号" in str(rows[0])):
            start_idx = 1

        with get_db_connection() as conn:
            for row in rows[start_idx:]:
                if not row or len(row) < 1: continue
                try:
                    data = {
                        "order_id": row[0],
                        "buy_mpn": row[4] if len(row) > 4 else "",
                        "buy_brand": row[5] if len(row) > 5 else "",
                        "remark": row[9] if len(row) > 9 else "",
                        "buy_price_rmb": 0.0,
                        "buy_qty": 0,
                        "vendor_id": None
                    }
                    if not data["order_id"]: continue
                        
                    ok, msg = add_buy(data, conn=conn)
                    if ok: success_count += 1
                    else: errors.append(msg)
                except Exception as e:
                    errors.append(f"行解析失败: {str(e)}")
            
            if success_count > 0:
                conn.commit()
    except Exception as e:
        errors.append(f"导入失败: {str(e)}")
            
    return success_count, errors

def batch_convert_from_order(order_ids):
    if not order_ids: return False, "未选中记录"
    try:
        success_count = 0
        errors = []
        with get_db_connection() as conn:
            placeholders = ','.join(['?'] * len(order_ids))
            rows = conn.execute(f"SELECT * FROM uni_order WHERE order_id IN ({placeholders})", order_ids).fetchall()
            
            for row in rows:
                order_data = dict(row)
                existing = conn.execute("SELECT buy_id FROM uni_buy WHERE order_id = ?", (order_data['order_id'],)).fetchone()
                if existing:
                    errors.append(f"{order_data['order_id']}: 已存在采购记录")
                    continue
                
                offer_info = conn.execute("SELECT * FROM uni_offer WHERE offer_id = ?", (order_data['offer_id'],)).fetchone()
                
                data = {
                    "order_id": order_data['order_id'],
                    "buy_mpn": order_data['inquiry_mpn'],
                    "buy_brand": order_data['inquiry_brand'],
                    "buy_qty": 0,
                    "buy_price_rmb": 0.0,
                    "sales_price_rmb": 0.0,
                    "remark": order_data['remark']
                }
                
                if offer_info:
                    data['vendor_id'] = offer_info['vendor_id']
                    data['buy_qty'] = offer_info['quoted_qty']
                    data['sales_price_rmb'] = offer_info['offer_price_rmb']
                    data['buy_price_rmb'] = offer_info['cost_price_rmb']

                ok, msg = add_buy(data, conn=conn)
                if ok: 
                    success_count += 1
                    # Update source order status
                    conn.execute("UPDATE uni_order SET is_transferred = '已转' WHERE order_id = ?", (order_data['order_id'],))
                else: 
                    errors.append(msg)
            
            if success_count > 0:
                conn.commit()
                
        if success_count == 0 and errors:
            return False, errors[0]
        return True, f"成功转换 {success_count} 条记录" + (f" (失败 {len(errors)} 条)" if errors else "")
    except Exception as e:
        return False, str(e)

def batch_delete_buy(buy_ids):
    if not buy_ids: return True, "无选中记录"
    try:
        with get_db_connection() as conn:
            placeholders = ','.join(['?'] * len(buy_ids))
            conn.execute(f"DELETE FROM uni_buy WHERE buy_id IN ({placeholders})", buy_ids)
            conn.commit()
            return True, "批量删除成功"
    except Exception as e:
        return False, str(e)

def update_buy_node(buy_id, field, value):
    try:
        nodes = ['is_source_confirmed', 'is_ordered', 'is_instock', 'is_shipped']
        if field not in nodes:
            return False, "非法节点字段"
        
        sql = f"UPDATE uni_buy SET {field} = ? WHERE buy_id = ?"
        with get_db_connection() as conn:
            conn.execute(sql, (int(value), buy_id))
            conn.commit()
            return True, "节点更新成功"
    except Exception as e:
        return False, str(e)

def update_buy(buy_id, data):
    try:
        # Data normalization for FKs and types
        if 'vendor_id' in data and not str(data['vendor_id']).strip():
            data['vendor_id'] = None
        if 'order_id' in data and not str(data['order_id']).strip():
            data['order_id'] = None

        if 'buy_price_rmb' in data or 'buy_qty' in data:
            with get_db_connection() as conn:
                current = conn.execute("SELECT buy_price_rmb, buy_qty FROM uni_buy WHERE buy_id = ?", (buy_id,)).fetchone()
                if current:
                    price = float(data.get('buy_price_rmb', current['buy_price_rmb'] or 0))
                    qty = int(data.get('buy_qty', current['buy_qty'] or 0))
                    data['total_amount'] = round(price * qty, 2)

        set_cols = []
        params = []
        for k, v in data.items():
            set_cols.append(f"{k} = ?")
            params.append(v)
        
        if not set_cols: return True, "无修改内容"
        
        sql = f"UPDATE uni_buy SET {', '.join(set_cols)} WHERE buy_id = ?"
        params.append(buy_id)
        
        with get_db_connection() as conn:
            res = conn.execute(sql, params)
            conn.commit()
            if res.rowcount == 0:
                return False, f"未找到记录 {buy_id} 或数据无变化"
            return True, "更新成功"
    except Exception as e:
        return False, str(e)

def delete_buy(buy_id):
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM uni_buy WHERE buy_id = ?", (buy_id,))
            conn.commit()
            return True, "删除成功"
    except Exception as e:
        return False, str(e)
