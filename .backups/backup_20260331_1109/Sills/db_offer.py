import sqlite3
import uuid
import csv
import io
from datetime import datetime
from Sills.base import get_db_connection, get_exchange_rates

def get_offer_list(page=1, page_size=10, search_kw="", start_date="", end_date="", cli_id="", is_transferred=""):
    offset = (page - 1) * page_size

    base_query = """
    FROM uni_offer o
    LEFT JOIN uni_vendor v ON o.vendor_id = v.vendor_id
    LEFT JOIN uni_emp e ON o.emp_id = e.emp_id
    LEFT JOIN uni_quote q ON o.quote_id = q.quote_id
    LEFT JOIN uni_cli c ON q.cli_id = c.cli_id
    WHERE (o.inquiry_mpn LIKE ? OR o.offer_id LIKE ? OR v.vendor_name LIKE ? OR e.emp_name LIKE ?)
    """
    params = [f"%{search_kw}%", f"%{search_kw}%", f"%{search_kw}%", f"%{search_kw}%"]

    if start_date:
        base_query += " AND o.offer_date >= ?"
        params.append(start_date)
    if end_date:
        base_query += " AND o.offer_date <= ?"
        params.append(end_date)
    if cli_id:
        base_query += " AND q.cli_id = ?"
        params.append(cli_id)
    if is_transferred:
        base_query += " AND o.is_transferred = ?"
        params.append(is_transferred)

    query = f"""
    SELECT o.*, v.vendor_name, e.emp_name, c.cli_name, c.margin_rate,
           ('Model: ' || COALESCE(o.quoted_mpn, '') || ' | ' ||
            'Brand: ' || COALESCE(o.quoted_brand, '') || ' | ' ||
            'Amount(pcs): ' || COALESCE(CAST(o.inquiry_qty AS TEXT), '') || ' | ' ||
            'Price: ' || COALESCE(CAST(o.offer_price_rmb AS TEXT), '') || ' | ' ||
            'DC: ' || COALESCE(o.date_code, '') || ' | ' ||
            'LeadTime: ' || COALESCE(o.delivery_date, '') || ' | ' ||
            'Transferred: ' || COALESCE(o.is_transferred, '未转') || ' | ' ||
            'Remark: ' || COALESCE(o.remark, '')) as combined_offer_info,
            ROUND(CAST(o.offer_price_rmb - o.cost_price_rmb AS numeric), 3) as profit,
            CAST(ROUND(CAST((o.offer_price_rmb - o.cost_price_rmb) * o.quoted_qty AS numeric), 0) AS INTEGER) as total_profit
    {base_query}
    ORDER BY o.created_at DESC
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
            remark = r.get('remark') or ""
            r['remark'] = remark.replace(' | ', '\n').replace('|', '\n')

            # 报价(RMB)保留4位小数
            try:
                offer_price = float(r.get('offer_price_rmb') or 0.0)
                r['offer_price_rmb'] = round(offer_price, 4)
            except:
                r['offer_price_rmb'] = 0.0

            # 只在数据库中没有值时才计算汇率，不覆盖已保存的值（和销售订单逻辑一致）
            offer_price = float(r.get('offer_price_rmb') or 0.0)
            try:
                if not r.get('price_kwr') or float(r.get('price_kwr') or 0) == 0:
                    if krw_val > 10: r['price_kwr'] = round(offer_price * krw_val, 1)
                    else: r['price_kwr'] = round(offer_price / krw_val, 1) if krw_val else 0.0
                # USD汇率表示 1 RMB = ? USD，直接乘
                if not r.get('price_usd') or float(r.get('price_usd') or 0) == 0:
                    r['price_usd'] = round(offer_price * usd_val, 3) if usd_val else 0.0
            except:
                pass

        return results, total

def add_offer(data, emp_id, conn=None):
    try:
        offer_date = datetime.now().strftime("%Y-%m-%d")

        quote_id = data.get('quote_id')
        if quote_id and str(quote_id).strip() == "":
            quote_id = None

        vendor_id = data.get('vendor_id')
        if vendor_id and str(vendor_id).strip() == "":
            vendor_id = None

        # Validation Logic
        must_close = False
        if conn is None:
            conn = get_db_connection()
            must_close = True

        try:
            # 生成递增的5位数报价编号
            last_offer = conn.execute("SELECT offer_id FROM uni_offer WHERE offer_id LIKE 'b%' ORDER BY offer_id DESC LIMIT 1").fetchone()
            if last_offer:
                try:
                    last_num = int(last_offer['offer_id'][1:])  # 去掉前缀b，获取数字部分
                    new_num = last_num + 1
                except:
                    new_num = 1
            else:
                new_num = 1
            offer_id = f"b{new_num:05d}"  # 格式化为5位数，例如 b00001

            # 1. Emp Check
            emp = conn.execute("SELECT emp_id FROM uni_emp WHERE emp_id = ?", (emp_id,)).fetchone()
            if not emp:
                return False, f"员工编号 {emp_id} 不存在"

            # 2. Quote Check
            if quote_id:
                q_row = conn.execute("SELECT quote_id FROM uni_quote WHERE quote_id = ?", (quote_id,)).fetchone()
                if not q_row:
                    return False, f"需求编号 {quote_id} 不存在"
                
                # Uniqueness check
                existing = conn.execute("SELECT offer_id FROM uni_offer WHERE quote_id = ?", (quote_id,)).fetchone()
                if existing:
                    return False, f"该需求 {quote_id} 已转换过报价 ({existing['offer_id']})"

            # 3. Vendor Check
            if vendor_id:
                v_row = conn.execute("SELECT vendor_id FROM uni_vendor WHERE vendor_id = ?", (vendor_id,)).fetchone()
                if not v_row:
                    return False, f"供应商编号 {vendor_id} 不存在"

            # Numerical normalization
            inquiry_qty = 0
            try: inquiry_qty = int(data.get('inquiry_qty') or 0)
            except: pass

            actual_qty = data.get('actual_qty')
            if not actual_qty or str(actual_qty).strip() == "" or str(actual_qty) == "0":
                actual_qty = inquiry_qty
            else:
                try: actual_qty = int(actual_qty)
                except: actual_qty = inquiry_qty

            # quoted_qty: 优先使用 quoted_qty，如果没有则使用 actual_qty（从需求管理转报价时）
            quoted_qty = data.get('quoted_qty')
            if not quoted_qty or str(quoted_qty).strip() == "" or str(quoted_qty) == "0":
                # 从需求管理转报价时，actual_qty 就是报价数量
                if actual_qty and str(actual_qty) != "0":
                    quoted_qty = actual_qty
                else:
                    quoted_qty = inquiry_qty
            else:
                try: quoted_qty = int(quoted_qty)
                except: quoted_qty = inquiry_qty

            cost_price = 0.0
            try: cost_price = float(data.get('cost_price_rmb') or 0.0)
            except: pass

            offer_price = 0.0
            try: offer_price = float(data.get('offer_price_rmb') or 0.0)
            except: pass

            # Handle auto-calc based on margin
            margin = 0.0
            if quote_id:
                margin_row = conn.execute("SELECT margin_rate FROM uni_cli c JOIN uni_quote q ON c.cli_id = q.cli_id WHERE q.quote_id = ?", (quote_id,)).fetchone()
                if margin_row: margin = float(margin_row[0] or 0.0)

            if cost_price > 0:
                offer_price = cost_price * (1 + margin / 100.0)

            # 使用缓存的汇率
            krw_val, usd_val = get_exchange_rates()

            if krw_val > 10: price_kwr = round(offer_price * krw_val, 1)
            else: price_kwr = round(offer_price / krw_val, 1) if krw_val else 0.0

            # USD汇率表示 1 RMB = ? USD，直接乘
            price_usd = round(offer_price * usd_val, 2) if usd_val else 0.0

            inquiry_mpn = data.get('inquiry_mpn', '')
            quoted_mpn = data.get('quoted_mpn', '')
            if not quoted_mpn: quoted_mpn = inquiry_mpn

            inquiry_brand = data.get('inquiry_brand', '')
            quoted_brand = data.get('quoted_brand', '')
            if not quoted_brand: quoted_brand = inquiry_brand
            
            sql = """
            INSERT INTO uni_offer (
                offer_id, offer_date, quote_id, inquiry_mpn, quoted_mpn, inquiry_brand, quoted_brand,
                inquiry_qty, actual_qty, quoted_qty, cost_price_rmb, offer_price_rmb, 
                price_kwr, price_usd, platform,
                vendor_id, date_code, delivery_date, emp_id, offer_statement, remark, is_transferred
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                offer_id, offer_date, quote_id,
                inquiry_mpn, quoted_mpn,
                inquiry_brand, quoted_brand,
                inquiry_qty, actual_qty, quoted_qty,
                cost_price, offer_price,
                price_kwr, price_usd,
                data.get('platform', ''),
                vendor_id, data.get('date_code', ''),
                data.get('delivery_date', ''), emp_id,
                data.get('offer_statement', ''), data.get('remark', ''),
                data.get('is_transferred', '未转')
            )
            conn.execute(sql, params)
            if must_close:
                conn.commit()
            return True, f"报价单 {offer_id} 创建成功"
        finally:
            if must_close:
                conn.close()
    except Exception as e:
        return False, f"数据库错误: {str(e)}"

def update_offer(offer_id, data):
    try:
        if 'emp_id' in data:
            del data['emp_id'] # Prevent changing owner post-creation

        # 检查是否更新了价格字段，需要同步更新关联订单
        price_fields = ['offer_price_rmb', 'price_kwr', 'price_usd']
        need_sync_order = any(field in data for field in price_fields)

        # 如果更新了 offer_price_rmb，需要计算 KWR 和 USD
        if 'offer_price_rmb' in data:
            krw_val, usd_val = get_exchange_rates()
            offer_price = float(data.get('offer_price_rmb') or 0)

            # 计算 KWR
            if krw_val > 10:
                data['price_kwr'] = round(offer_price * krw_val, 1)
            else:
                data['price_kwr'] = round(offer_price / krw_val, 1) if krw_val else 0.0

            # 计算 USD (USD汇率表示 1 RMB = ? USD，直接乘)
            data['price_usd'] = round(offer_price * usd_val, 2) if usd_val else 0.0

        set_cols = []
        params = []
        for k, v in data.items():
            set_cols.append(f"{k} = ?")
            params.append(v)
        if not set_cols: return True, "No changes"

        sql = f"UPDATE uni_offer SET {', '.join(set_cols)} WHERE offer_id = ?"
        params.append(offer_id)

        with get_db_connection() as conn:
            conn.execute(sql, params)

            # 同步更新关联订单的价格字段
            if need_sync_order:
                price_rmb = data.get('offer_price_rmb')
                price_kwr = data.get('price_kwr')
                price_usd = data.get('price_usd')

                update_parts = []
                update_params = []
                if price_rmb is not None:
                    update_parts.append("price_rmb = ?")
                    update_params.append(price_rmb)
                if price_kwr is not None:
                    update_parts.append("price_kwr = ?")
                    update_params.append(price_kwr)
                if price_usd is not None:
                    update_parts.append("price_usd = ?")
                    update_params.append(price_usd)

                if update_parts:
                    update_params.append(offer_id)
                    order_sql = f"UPDATE uni_order SET {', '.join(update_parts)} WHERE offer_id = ?"
                    conn.execute(order_sql, update_params)

            conn.commit()
            return True, "更新成功"
    except Exception as e:
        return False, str(e)

def delete_offer(offer_id):
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM uni_offer WHERE offer_id = ?", (offer_id,))
            conn.commit()
            return True, "删除成功"
    except Exception as e:
        return False, str(e)

def batch_delete_offer(offer_ids):
    if not offer_ids: return True, "无选中记录"
    try:
        with get_db_connection() as conn:
            placeholders = ','.join(['?'] * len(offer_ids))
            conn.execute(f"DELETE FROM uni_offer WHERE offer_id IN ({placeholders})", offer_ids)
            conn.commit()
            return True, "批量删除成功"
    except Exception as e:
        if "FOREIGN KEY constraint failed" in str(e):
            return False, "删除失败：部分记录已被后续流程（如销售订单/采购记录）引用，无法直接删除。"
        return False, str(e)

def batch_import_offer_text(text, emp_id):
    import io, csv
    f = io.StringIO(text.strip())
    reader = csv.reader(f)
    rows = list(reader)
    success_count = 0
    errors = []
    
    if not rows: return 0, []

    # Heuristic to skip header: if the first column of the first row contains '编号' or 'MPN'
    start_idx = 0
    first_row = rows[0]
    if len(first_row) > 0 and ('编号' in first_row[0] or '型号' in first_row[0] or 'MPN' in first_row[0].upper()):
        start_idx = 1

    for i, parts in enumerate(rows[start_idx:], start=start_idx + 1):
        if not parts or len(parts) < 1: continue

        try:
            data = {
                "quote_id": parts[0] if len(parts) > 0 and parts[0].strip() else None,
                "inquiry_mpn": parts[1] if len(parts) > 1 else "",
                "quoted_mpn": parts[2] if len(parts) > 2 else "",
                "inquiry_brand": parts[3] if len(parts) > 3 else "",
                "quoted_brand": parts[4] if len(parts) > 4 else "",
                "inquiry_qty": 0,
                "actual_qty": 0,
                "quoted_qty": 0,
                "cost_price_rmb": 0.0,
                "offer_price_rmb": 0.0,
                "vendor_id": parts[10] if len(parts) > 10 and parts[10].strip() else None,
                "date_code": parts[11] if len(parts) > 11 else "",
                "delivery_date": parts[12] if len(parts) > 12 else "",
                "offer_statement": parts[13] if len(parts) > 13 else "",
                "remark": parts[14] if len(parts) > 14 else ""
            }
            
            # Numeric values logic
            try: data["inquiry_qty"] = int(parts[5]) if len(parts) > 5 and parts[5] else 0
            except: pass
            
            try: data["actual_qty"] = int(parts[6]) if len(parts) > 6 and parts[6] else data["inquiry_qty"]
            except: data["actual_qty"] = data["inquiry_qty"]
            
            try: data["quoted_qty"] = int(parts[7]) if len(parts) > 7 and parts[7] else data["inquiry_qty"]
            except: data["quoted_qty"] = data["inquiry_qty"]
            
            try: data["cost_price_rmb"] = float(parts[8]) if len(parts) > 8 and parts[8] else 0.0
            except: pass
            
            try: data["offer_price_rmb"] = float(parts[9]) if len(parts) > 9 and parts[9] else 0.0
            except: pass

            if not data["inquiry_mpn"] and not data["quoted_mpn"]:
                errors.append(f"第 {i} 行: 缺少型号信息")
                continue
                
            ok, msg = add_offer(data, emp_id)
            if ok: success_count += 1
            else: errors.append(f"第 {i} 行 ({data.get('inquiry_mpn') or data.get('quoted_mpn')}): {msg}")
        except Exception as e:
            errors.append(f"第 {i} 行: 数据格式解析失败 ({str(e)})")
            
    return success_count, errors

def batch_convert_from_quote(quote_ids, emp_id):
    if not quote_ids: return False, "未选中记录"
    try:
        success_count = 0
        errors = []
        with get_db_connection() as conn:
            # Get data from uni_quote
            placeholders = ','.join(['?'] * len(quote_ids))
            rows = conn.execute(f"SELECT * FROM uni_quote WHERE quote_id IN ({placeholders})", quote_ids).fetchall()
            
            for row in rows:
                data = dict(row)
                # Pass connection to add_offer to stay in same transaction
                ok, msg = add_offer(data, emp_id, conn=conn)
                if ok:
                    success_count += 1
                    # Update source quote status and transferred flag
                    conn.execute("UPDATE uni_quote SET is_transferred = '已转', status = '已报价' WHERE quote_id = ?", (data['quote_id'],))
            if success_count > 0:
                conn.commit()

        if success_count == 0 and errors:
            return False, errors[0]
        return True, f"成功转换 {success_count} 条记录" + (f" (失败 {len(errors)} 条)" if errors else "")
    except Exception as e:
        return False, str(e)
