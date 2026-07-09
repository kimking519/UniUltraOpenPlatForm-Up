import sqlite3
import uuid
import csv
import io
from datetime import datetime
from Sills.base import get_db_connection, get_exchange_rates

def get_offer_list(page=1, page_size=10, search_kw="", start_date="", end_date="", cli_id="", is_transferred="", status=""):
    offset = (page - 1) * page_size

    base_query = """
    FROM uni_offer o
    LEFT JOIN uni_vendor v ON o.vendor_id = v.vendor_id
    LEFT JOIN uni_emp e ON o.emp_id = e.emp_id
    LEFT JOIN uni_quote q ON o.quote_id = q.quote_id
    LEFT JOIN uni_cli c ON COALESCE(o.cli_id, q.cli_id) = c.cli_id
    WHERE (o.inquiry_mpn LIKE ? OR o.offer_id LIKE ? OR v.vendor_name LIKE ? OR e.emp_name LIKE ? OR c.cli_name LIKE ?)
    """
    params = [f"%{search_kw}%", f"%{search_kw}%", f"%{search_kw}%", f"%{search_kw}%", f"%{search_kw}%"]

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
    if status:
        base_query += " AND o.status = ?"
        params.append(status)

    query = f"""
    SELECT o.*, v.vendor_name, e.emp_name, c.cli_name, COALESCE(o.cli_id, c.cli_id) as cli_id, c.margin_rate,
           o.status, o.target_price_rmb,
           (COALESCE(o.quoted_mpn, '') || ' | ' || COALESCE(o.quoted_brand, '') || ' | ' || COALESCE(CAST(o.quoted_qty AS TEXT), '') || ' pcs') as combined_info,
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
    ORDER BY o.offer_date DESC, o.created_at DESC, o.offer_id DESC
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
        krw_val, usd_val, _ = get_exchange_rates()

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
                # USD汇率表示 1 USD = X RMB，需要除法
                if not r.get('price_usd') or float(r.get('price_usd') or 0) == 0:
                    r['price_usd'] = round(offer_price / usd_val, 3) if usd_val else 0.0
            except:
                pass

        return results, total

def add_offer(data, emp_id, conn=None):
    try:
        offer_date = data.get('offer_date') or datetime.now().strftime("%Y-%m-%d")

        quote_id = data.get('quote_id')
        if quote_id and str(quote_id).strip() == "":
            quote_id = None

        vendor_id = data.get('vendor_id')
        if vendor_id and str(vendor_id).strip() == "":
            vendor_id = None

        cli_id = data.get('cli_id')
        if not cli_id or str(cli_id).strip() == "":
            cli_id = None

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

            # Handle auto-calc based on margin (只有当报价未提供时才自动计算)
            if offer_price == 0.0 and cost_price > 0:
                margin = 0.0
                if quote_id:
                    margin_row = conn.execute("SELECT margin_rate FROM uni_cli c JOIN uni_quote q ON c.cli_id = q.cli_id WHERE q.quote_id = ?", (quote_id,)).fetchone()
                    if margin_row: margin = float(margin_row[0] or 0.0)
                offer_price = cost_price * (1 + margin / 100.0)

            # 使用缓存的汇率
            krw_val, usd_val, _ = get_exchange_rates()

            if krw_val > 10: price_kwr = round(offer_price * krw_val, 1)
            else: price_kwr = round(offer_price / krw_val, 1) if krw_val else 0.0

            # USD汇率表示 1 USD = X RMB，需要除法
            price_usd = round(offer_price / usd_val, 3) if usd_val else 0.0

            inquiry_mpn = data.get('inquiry_mpn', '')
            quoted_mpn = data.get('quoted_mpn', '')
            if not quoted_mpn: quoted_mpn = inquiry_mpn

            inquiry_brand = data.get('inquiry_brand', '')
            quoted_brand = data.get('quoted_brand', '')
            if not quoted_brand: quoted_brand = inquiry_brand
            
            sql = """
            INSERT INTO uni_offer (
                offer_id, offer_date, quote_id, cli_id, inquiry_mpn, quoted_mpn, inquiry_brand, quoted_brand,
                inquiry_qty, actual_qty, quoted_qty, cost_price_rmb, offer_price_rmb,
                price_kwr, price_usd, platform,
                vendor_id, date_code, delivery_date, emp_id, offer_statement, remark, status, target_price_rmb, is_transferred
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                offer_id, offer_date, quote_id, cli_id,
                inquiry_mpn, quoted_mpn,
                inquiry_brand, quoted_brand,
                inquiry_qty, actual_qty, quoted_qty,
                cost_price, offer_price,
                price_kwr, price_usd,
                data.get('platform', ''),
                vendor_id, data.get('date_code', ''),
                data.get('delivery_date', ''), emp_id,
                data.get('offer_statement', ''), data.get('remark', ''),
                data.get('status', '询价中'), data.get('target_price_rmb', None),
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

        # 获取推荐汇率
        krw_val, usd_val, jpy_val = get_exchange_rates()

        # 如果更新了 offer_price_rmb，只有外币价格为空或0时才计算
        if 'offer_price_rmb' in data:
            offer_price = float(data.get('offer_price_rmb') or 0)

            # 先查询当前报价的外币价格
            with get_db_connection() as conn:
                current = conn.execute(
                    "SELECT price_kwr, price_usd, price_jpy FROM uni_offer WHERE offer_id = ?",
                    (offer_id,)
                ).fetchone()

            if current:
                current_kwr = float(current['price_kwr'] or 0)
                current_usd = float(current['price_usd'] or 0)
                current_jpy = float(current['price_jpy'] or 0)

                # 只有外币价格为空或0时才计算
                if current_kwr == 0:
                    data['price_kwr'] = round(offer_price * krw_val, 1) if krw_val else 0.0
                if current_usd == 0:
                    data['price_usd'] = round(offer_price / usd_val, 3) if usd_val else 0.0
                if current_jpy == 0:
                    data['price_jpy'] = round(offer_price * jpy_val, 2) if jpy_val else 0.0

        # 如果更新了 price_kwr，反向计算 RMB
        if 'price_kwr' in data and 'offer_price_rmb' not in data:
            price_kwr = float(data.get('price_kwr') or 0)
            # RMB = KWR ÷ KRW汇率
            data['offer_price_rmb'] = round(price_kwr / krw_val, 4) if krw_val else 0.0
            # 同时更新 USD 和 JPY
            data['price_usd'] = round(data['offer_price_rmb'] / usd_val, 3) if usd_val else 0.0
            data['price_jpy'] = round(data['offer_price_rmb'] * jpy_val, 2) if jpy_val else 0.0

        # 如果更新了 price_usd，反向计算 RMB
        if 'price_usd' in data and 'offer_price_rmb' not in data:
            price_usd = float(data.get('price_usd') or 0)
            # RMB = USD × USD汇率
            data['offer_price_rmb'] = round(price_usd * usd_val, 4) if usd_val else 0.0
            # 同时更新 KWR 和 JPY
            data['price_kwr'] = round(data['offer_price_rmb'] * krw_val, 1) if krw_val else 0.0
            data['price_jpy'] = round(data['offer_price_rmb'] * jpy_val, 2) if jpy_val else 0.0

        # 如果更新了 price_jpy，反向计算 RMB
        if 'price_jpy' in data and 'offer_price_rmb' not in data:
            price_jpy = float(data.get('price_jpy') or 0)
            # RMB = JPY ÷ JPY汇率
            data['offer_price_rmb'] = round(price_jpy / jpy_val, 4) if jpy_val else 0.0
            # 同时更新 KWR 和 USD
            data['price_kwr'] = round(data['offer_price_rmb'] * krw_val, 1) if krw_val else 0.0
            data['price_usd'] = round(data['offer_price_rmb'] / usd_val, 3) if usd_val else 0.0

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
            conn.commit()
            return True, "更新成功"
    except Exception as e:
        return False, str(e)

def delete_offer(offer_id):
    """删除报价记录，如果被订单引用则拒绝删除"""
    try:
        with get_db_connection() as conn:
            # 检查是否被订单引用
            order_ref = conn.execute(
                "SELECT order_id FROM uni_order WHERE offer_id = ? LIMIT 1",
                (offer_id,)
            ).fetchone()
            if order_ref:
                return False, f"删除失败：报价已被订单 {order_ref['order_id']} 引用，请先删除关联订单。"

            conn.execute("DELETE FROM uni_offer WHERE offer_id = ?", (offer_id,))
            conn.commit()
            return True, "删除成功"
    except Exception as e:
        if "FOREIGN KEY constraint failed" in str(e):
            return False, "删除失败：报价已被后续流程引用，无法直接删除。"
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


def duplicate_offer(offer_id, emp_id):
    """复制/重插一条报价记录

    Args:
        offer_id: 原报价ID
        emp_id: 当前员工ID

    Returns:
        (success, message): 成功时返回新报价ID
    """
    try:
        with get_db_connection() as conn:
            # 获取原报价数据
            row = conn.execute("""
                SELECT offer_date, quote_id, cli_id, inquiry_mpn, quoted_mpn, inquiry_brand, quoted_brand,
                       inquiry_qty, actual_qty, quoted_qty, cost_price_rmb, offer_price_rmb,
                       price_kwr, price_usd, price_jpy, platform, vendor_id, date_code, delivery_date,
                       offer_statement, remark, status, target_price_rmb, is_transferred
                FROM uni_offer WHERE offer_id = ?
            """, (offer_id,)).fetchone()

            if not row:
                return False, "报价不存在"

            data = dict(row)

            # 生成新的报价ID
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
            new_offer_id = f"b{new_num:05d}"

            # 使用今天的日期
            new_offer_date = datetime.now().strftime("%Y-%m-%d")

            # 插入新报价（状态改为询价中，已转改为未转）
            conn.execute("""
                INSERT INTO uni_offer (
                    offer_id, offer_date, quote_id, cli_id, inquiry_mpn, quoted_mpn, inquiry_brand, quoted_brand,
                    inquiry_qty, actual_qty, quoted_qty, cost_price_rmb, offer_price_rmb,
                    price_kwr, price_usd, price_jpy, platform, vendor_id, date_code, delivery_date,
                    emp_id, offer_statement, remark, status, target_price_rmb, is_transferred
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                new_offer_id, new_offer_date,
                data.get('quote_id'), data.get('cli_id'),
                data.get('inquiry_mpn'), data.get('quoted_mpn'),
                data.get('inquiry_brand'), data.get('quoted_brand'),
                data.get('inquiry_qty'), data.get('actual_qty'), data.get('quoted_qty'),
                data.get('cost_price_rmb'), data.get('offer_price_rmb'),
                data.get('price_kwr'), data.get('price_usd'), data.get('price_jpy'),
                data.get('platform'), data.get('vendor_id'),
                data.get('date_code'), data.get('delivery_date'),
                emp_id, data.get('offer_statement'), data.get('remark'),
                '询价中',  # 状态改为询价中
                data.get('target_price_rmb'),
                '未转'    # 已转改为未转
            ))
            conn.commit()

            return True, new_offer_id
    except Exception as e:
        return False, str(e)


def batch_duplicate_offers(offer_ids, emp_id):
    """批量复制报价记录

    Args:
        offer_ids: 报价ID列表
        emp_id: 当前员工ID

    Returns:
        (success_count, failed_count, new_ids): 成功数、失败数、新报价ID列表
    """
    success_count = 0
    failed_count = 0
    new_ids = []

    for offer_id in offer_ids:
        ok, result = duplicate_offer(offer_id, emp_id)
        if ok:
            success_count += 1
            new_ids.append(result)
        else:
            failed_count += 1

    return success_count, failed_count, new_ids

def batch_import_offer_text(text, emp_id):
    import io, csv, re
    from datetime import datetime

    # 智能分隔符策略 (2026-06-19)：
    # - 行内含英文逗号 → 走 csv.reader（保留双引号字段保护、空字段位置）
    # - 行内不含英文逗号 → 走正则切分，支持中文逗号/中英文分号/Tab/竖线/≥2个空格
    # 与前端 offer.html 智能带入框（≥2空格分隔规则）保持一致体验
    SEP_RE = re.compile(r'[，;；\t|]+|\s{2,}')
    rows = []
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ',' in line:
            # 走 csv.reader（保留原行为）
            csv_reader = csv.reader(io.StringIO(line))
            for parsed in csv_reader:
                rows.append(parsed)
        else:
            # 走正则切分，过滤空段
            parts = [p for p in SEP_RE.split(line) if p.strip()]
            rows.append(parts)
    success_count = 0
    errors = []

    if not rows: return 0, []

    # Heuristic to skip header: if the first column of the first row contains '日期' or '型号' or 'MPN'
    start_idx = 0
    first_row = rows[0]
    if len(first_row) > 0 and ('日期' in first_row[0] or '型号' in first_row[0] or 'MPN' in first_row[0].upper()):
        start_idx = 1

    # 新模板列索引：
    # 0: 日期, 1: 询价型号, 2: 报价型号, 3: 询价品牌, 4: 报价品牌,
    # 5: 询价数量, 6: 报价数量, 7: 目标价, 8: 成本价, 9: 报价,
    # 10: 客户名称, 11: 批号, 12: 交期, 13: 备注, 14: 状态

    for i, parts in enumerate(rows[start_idx:], start=start_idx + 1):
        if not parts or len(parts) < 1: continue

        try:
            # 从日期自动生成需求编号（使用 db_quote 的生成函数）
            offer_date = parts[0] if len(parts) > 0 and parts[0].strip() else datetime.now().strftime('%Y-%m-%d')
            quote_id = None  # 报价记录不一定需要关联需求编号

            # 验证状态值
            status_val = parts[14] if len(parts) > 14 and parts[14].strip() else "询价中"
            valid_status = ['询价中', '已报价', '缺货']
            if status_val not in valid_status:
                status_val = "询价中"

            data = {
                "quote_id": quote_id,
                "offer_date": offer_date,
                "inquiry_mpn": parts[1] if len(parts) > 1 else "",
                "quoted_mpn": parts[2] if len(parts) > 2 else "",
                "inquiry_brand": parts[3] if len(parts) > 3 else "",
                "quoted_brand": parts[4] if len(parts) > 4 else "",
                "inquiry_qty": 0,
                "quoted_qty": 0,
                "target_price_rmb": 0.0,
                "cost_price_rmb": 0.0,
                "offer_price_rmb": 0.0,
                "cli_id": None,  # 通过客户名称匹配
                "date_code": parts[11] if len(parts) > 11 else "",
                "delivery_date": parts[12] if len(parts) > 12 else "",
                "remark": parts[13] if len(parts) > 13 else "",
                "status": status_val
            }

            # Numeric values logic
            try: data["inquiry_qty"] = int(parts[5]) if len(parts) > 5 and parts[5] else 0
            except: pass

            try: data["quoted_qty"] = int(parts[6]) if len(parts) > 6 and parts[6] else data["inquiry_qty"]
            except: data["quoted_qty"] = data["inquiry_qty"]

            try: data["target_price_rmb"] = float(parts[7]) if len(parts) > 7 and parts[7] else 0.0
            except: pass

            try: data["cost_price_rmb"] = float(parts[8]) if len(parts) > 8 and parts[8] else 0.0
            except: pass

            try: data["offer_price_rmb"] = float(parts[9]) if len(parts) > 9 and parts[9] else 0.0
            except: pass

            # 通过客户名称自动匹配客户编号
            cli_name = parts[10] if len(parts) > 10 and parts[10].strip() else ""
            if cli_name:
                with get_db_connection() as conn:
                    cli_row = conn.execute(
                        "SELECT cli_id FROM uni_cli WHERE cli_name = ?", (cli_name,)
                    ).fetchone()
                    if cli_row:
                        data["cli_id"] = cli_row['cli_id']
                    # 如果找不到匹配，cli_id 保持为 None，不影响导入

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

def get_offer_combined_info(offer_ids):
    """获取报价记录的组合信息列表（用于复制组合功能）"""
    if not offer_ids: return []
    try:
        with get_db_connection() as conn:
            placeholders = ','.join(['?'] * len(offer_ids))
            rows = conn.execute(f"""
                SELECT offer_id, quoted_mpn, quoted_qty,
                       COALESCE(quoted_mpn, '') || ' | ' || COALESCE(quoted_brand, '') || ' | ' || COALESCE(CAST(quoted_qty AS TEXT), '') || ' pcs' as combined_info
                FROM uni_offer WHERE offer_id IN ({placeholders})
            """, offer_ids).fetchall()
            return [row['combined_info'] for row in rows]
    except Exception as e:
        return []


def _parse_update_cost_line(line):
    """解析单行更新报价文本，返回 (mpn, cost_price, date_code, delivery_date, fields_to_update, error)

    字段顺序：型号 成本价 批号 交期
    分隔规则与 batch_import_offer_text 一致（逗号/分号/Tab/竖线/≥2空格）
    不足4个时按顺序解析，缺的字段不更新。
    """
    import re
    SEP_RE = re.compile(r'[，;；\t|]+|\s{2,}')

    if ',' in line:
        # 走 csv.reader 保留逗号语义
        import csv, io
        parsed = next(csv.reader(io.StringIO(line)))
        parts = [p.strip() for p in parsed]
    else:
        parts = [p.strip() for p in SEP_RE.split(line) if p.strip()]
        # 兜底：强分隔符切不出多段时，回退到任意空格切分
        # （与前端 splitOfferLine 行为一致，兼容用户单空格输入）
        if len(parts) < 2:
            parts = [p.strip() for p in line.split() if p.strip()]

    if not parts:
        return None, None, None, None, [], "空行"

    mpn = parts[0]
    if not mpn:
        return None, None, None, None, [], "缺少型号"

    cost_price = None
    date_code = None
    delivery_date = None
    fields = []

    # 第2字段：成本价
    if len(parts) > 1 and parts[1]:
        try:
            cost_price = float(parts[1])
            fields.append('cost_price_rmb')
        except ValueError:
            return mpn, None, None, None, [], f"成本价格式错误: {parts[1]}"

    # 第3字段：批号
    if len(parts) > 2 and parts[2]:
        date_code = parts[2]
        fields.append('date_code')

    # 第4字段：交期
    if len(parts) > 3 and parts[3]:
        delivery_date = parts[3]
        fields.append('delivery_date')

    if not fields:
        return mpn, None, None, None, [], "无可更新字段（仅型号）"

    return mpn, cost_price, date_code, delivery_date, fields, None


def preview_update_today_cost(text):
    """预览更新当天录入报价的成本价/批号/交期。

    匹配规则：当天录入(created_at 是今天) 且 inquiry_mpn 或 quoted_mpn 匹配，
    多条时只取最新一条(created_at 倒序)。历史数据不动。
    返回 (preview_list, error_lines)

    注：当天判断放在 Python 层（复用 is_today 逻辑），避免 SQLite/PostgreSQL
    日期函数差异及 SQL 翻译器(? -> %s)与 LIKE '%' 冲突。
    """
    if not text or not text.strip():
        return [], []

    today_str = datetime.now().strftime('%Y-%m-%d')
    preview_list = []
    error_lines = []

    def _is_today(created_at):
        """created_at 是否为当天（兼容字符串与 datetime）"""
        if created_at is None:
            return False
        if isinstance(created_at, datetime):
            return created_at.strftime('%Y-%m-%d') == today_str
        s = str(created_at)
        date_str = s.split(' ')[0] if ' ' in s else s.split('T')[0]
        return date_str == today_str

    with get_db_connection() as conn:
        for idx, raw_line in enumerate(text.strip().splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue

            mpn, cost_price, date_code, delivery_date, fields, err = _parse_update_cost_line(line)
            if err:
                error_lines.append(f"第 {idx} 行: {err}")
                continue

            # 按型号查出候选（按 created_at 倒序），Python 层过滤当天，取最新一条
            rows = conn.execute("""
                SELECT offer_id, inquiry_mpn, quoted_mpn, cost_price_rmb, date_code, delivery_date, created_at
                FROM uni_offer
                WHERE LOWER(TRIM(inquiry_mpn)) = LOWER(TRIM(?))
                   OR LOWER(TRIM(quoted_mpn)) = LOWER(TRIM(?))
                ORDER BY created_at DESC
            """, (mpn, mpn)).fetchall()

            row = None
            for r in rows:
                if _is_today(r['created_at']):
                    row = r
                    break

            if not row:
                error_lines.append(f"第 {idx} 行 ({mpn}): 未匹配到当天录入记录")
                continue

            new_values = {}
            if 'cost_price_rmb' in fields:
                new_values['cost_price_rmb'] = cost_price
            if 'date_code' in fields:
                new_values['date_code'] = date_code
            if 'delivery_date' in fields:
                new_values['delivery_date'] = delivery_date

            preview_list.append({
                'offer_id': row['offer_id'],
                'mpn': mpn,
                'old_cost_price': row['cost_price_rmb'],
                'new_cost_price': new_values.get('cost_price_rmb'),
                'update_cost_price': 'cost_price_rmb' in fields,
                'old_date_code': row['date_code'],
                'new_date_code': new_values.get('date_code'),
                'update_date_code': 'date_code' in fields,
                'old_delivery_date': row['delivery_date'],
                'new_delivery_date': new_values.get('delivery_date'),
                'update_delivery_date': 'delivery_date' in fields,
            })

    return preview_list, error_lines


def execute_update_today_cost(preview_list):
    """根据预览确认列表执行更新。返回 (success_count, errors)

    安全：不信任前端回传的 offer_id。执行前重新查询该记录 created_at 并用 Python
    判定当天录入，仅当天记录才执行 UPDATE，防止 IDOR 改历史数据。
    """
    if not preview_list:
        return 0, ["无数据"]

    today_str = datetime.now().strftime('%Y-%m-%d')

    def _is_today(created_at):
        if created_at is None:
            return False
        if isinstance(created_at, datetime):
            return created_at.strftime('%Y-%m-%d') == today_str
        s = str(created_at)
        date_str = s.split(' ')[0] if ' ' in s else s.split('T')[0]
        return date_str == today_str

    success_count = 0
    errors = []
    with get_db_connection() as conn:
        for item in preview_list:
            offer_id = item.get('offer_id')
            if not offer_id:
                errors.append(f"{item.get('mpn','?')}: 缺少 offer_id")
                continue

            # 安全校验：重新查询该记录，确认仍为当天录入（防 IDOR/篡改 offer_id）
            chk = conn.execute(
                "SELECT created_at FROM uni_offer WHERE offer_id = ?",
                (offer_id,),
            ).fetchone()
            if not chk:
                errors.append(f"{item.get('mpn','?')}: 记录不存在")
                continue
            if not _is_today(chk['created_at']):
                errors.append(f"{item.get('mpn','?')}: 非当天录入记录，已跳过（历史数据不动）")
                continue

            set_parts = []
            params = []
            if item.get('update_cost_price'):
                set_parts.append("cost_price_rmb = ?")
                params.append(item.get('new_cost_price'))
            if item.get('update_date_code'):
                set_parts.append("date_code = ?")
                params.append(item.get('new_date_code'))
            if item.get('update_delivery_date'):
                set_parts.append("delivery_date = ?")
                params.append(item.get('new_delivery_date'))

            if not set_parts:
                errors.append(f"{item.get('mpn','?')}: 无可更新字段")
                continue

            params.append(offer_id)
            sql = f"""
                UPDATE uni_offer
                SET {', '.join(set_parts)}
                WHERE offer_id = ?
            """
            cur = conn.execute(sql, params)
            if cur.rowcount > 0:
                success_count += 1
            else:
                errors.append(f"{item.get('mpn','?')}: 更新失败（可能记录已变）")
        conn.commit()
    return success_count, errors
