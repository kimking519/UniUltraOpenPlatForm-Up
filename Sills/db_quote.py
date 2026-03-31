import sqlite3
import uuid
from datetime import datetime
from Sills.base import get_db_connection

def generate_quote_id():
    """生成递增的5位数需求编号，格式：x00001"""
    with get_db_connection() as conn:
        last_quote = conn.execute("SELECT quote_id FROM uni_quote WHERE quote_id LIKE 'x%' ORDER BY quote_id DESC LIMIT 1").fetchone()
        if last_quote:
            try:
                last_num = int(last_quote['quote_id'][1:])  # 去掉前缀x，获取数字部分
                new_num = last_num + 1
            except:
                new_num = 1
        else:
            new_num = 1
        return f"x{new_num:05d}"  # 格式化为5位数，例如 x00001

def get_default_date_code():
    """获取默认批号：3年内"""
    from datetime import timedelta
    today = datetime.now()
    future = today + timedelta(days=365*3)
    return f"{future.strftime('%y')}{future.strftime('%W')}+"  # 格式如 "2912+"

def get_default_delivery():
    """获取默认交期：1~3days"""
    return "1~3days"

def get_quote_list(page=1, page_size=10, search_kw="", start_date="", end_date="", cli_id="", status="", is_transferred=""):
    offset = (page - 1) * page_size
    
    base_query = """
    FROM uni_quote q
    LEFT JOIN uni_cli c ON q.cli_id = c.cli_id
    WHERE (q.inquiry_mpn LIKE ? OR q.quote_id LIKE ? OR c.cli_name LIKE ?)
    """
    params = [f"%{search_kw}%", f"%{search_kw}%", f"%{search_kw}%"]
    
    if start_date:
        base_query += " AND q.quote_date >= ?"
        params.append(start_date)
    if end_date:
        base_query += " AND q.quote_date <= ?"
        params.append(end_date)
    if cli_id:
        base_query += " AND q.cli_id = ?"
        params.append(cli_id)
    if status:
        base_query += " AND q.status = ?"
        params.append(status)
    if is_transferred:
        base_query += " AND q.is_transferred = ?"
        params.append(is_transferred)
        
    query = f"""
    SELECT q.*, c.cli_name,
           (COALESCE(q.quoted_mpn, '') || ' | ' ||
            COALESCE(q.inquiry_brand, '') || ' | ' ||
            COALESCE(CAST(q.inquiry_qty AS TEXT), '') || ' pcs') as combined_info
    {base_query}
    ORDER BY q.created_at DESC
    LIMIT ? OFFSET ?
    """
    
    count_query = f"SELECT COUNT(*) {base_query}"
    
    with get_db_connection() as conn:
        total = conn.execute(count_query, params).fetchone()[0]
        items = conn.execute(query, params + [page_size, offset]).fetchall()
        
        results = [
            {k: ("" if v is None else v) for k, v in dict(row).items()}
            for row in items
        ]
        return results, total

def add_quote(data):
    try:
        quote_id = generate_quote_id()
        quote_date = datetime.now().strftime("%Y-%m-%d")
        # 报价型号默认等于询价型号，报价数量默认等于需求数量
        inquiry_mpn = data.get('inquiry_mpn', '')
        inquiry_qty = data.get('inquiry_qty', 0)
        # 默认值：批号3年内，交期1~3days
        default_date_code = get_default_date_code()
        default_delivery = get_default_delivery()

        sql = """
        INSERT INTO uni_quote (quote_id, quote_date, cli_id, inquiry_mpn, quoted_mpn, inquiry_brand, inquiry_qty, actual_qty, target_price_rmb, cost_price_rmb, date_code, delivery_date, status, remark, is_transferred)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '未转')
        """
        params = (
            quote_id,
            quote_date,
            data.get('cli_id'),
            inquiry_mpn,
            data.get('quoted_mpn') or inquiry_mpn,  # 报价型号默认等于询价型号
            data.get('inquiry_brand', ''),
            inquiry_qty,
            data.get('actual_qty') or inquiry_qty,  # 报价数量默认等于需求数量
            data.get('target_price_rmb', 0.0),
            data.get('cost_price_rmb', 0.0),
            data.get('date_code') or default_date_code,  # 默认批号3年内
            data.get('delivery_date') or default_delivery,  # 默认交期1~3days
            data.get('status', '询价中'),
            data.get('remark', '')
        )
        with get_db_connection() as conn:
            conn.execute(sql, params)
            conn.commit()
            return True, f"需求 {quote_id} 创建成功"
    except Exception as e:
        return False, str(e)

def batch_import_quote_text(text):
    lines = text.strip().split('\n')
    success_count = 0
    errors = []

    # 跳过标题行（如果第一行包含"日期"或"客户名"等关键字）
    if lines and ('日期' in lines[0] or '客户名' in lines[0] or '客户编号' in lines[0]):
        lines = lines[1:]

    # 构建客户名到客户编号的映射
    cli_name_to_id = {}
    with get_db_connection() as conn:
        rows = conn.execute("SELECT cli_id, cli_name FROM uni_cli").fetchall()
        for row in rows:
            cli_name_to_id[row['cli_name']] = row['cli_id']

    for line in lines:
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 1: continue

        try:
            # 新格式：日期,客户名,询价型号,报价型号,询价品牌,询价数量,目标价,成本价,批号,交期,状态,备注
            # 旧格式：客户编号,询价型号,报价型号,询价品牌,询价数量,目标价,成本价,批号,交期,状态,备注
            # 检测格式：如果第一个字段是日期格式，则是新格式

            first_field = parts[0]
            is_new_format = False

            # 检测是否为日期格式 (YYYY-MM-DD 或 YYYY/MM/DD)
            import re
            if re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}$', first_field):
                is_new_format = True

            if is_new_format:
                # 新格式：日期,客户名,询价型号,...
                cli_field = parts[1] if len(parts) > 1 else ""
                # 尝试通过客户名查找客户编号
                cli_id = cli_name_to_id.get(cli_field, cli_field)  # 如果找不到，假设输入的是客户编号

                data = {
                    "quote_date": parts[0] if len(parts) > 0 else "",
                    "cli_id": cli_id,
                    "inquiry_mpn": parts[2] if len(parts) > 2 else "",
                    "quoted_mpn": parts[3] if len(parts) > 3 else "",
                    "inquiry_brand": parts[4] if len(parts) > 4 else "",
                    "inquiry_qty": int(parts[5]) if len(parts) > 5 and parts[5] else 0,
                    "target_price_rmb": float(parts[6]) if len(parts) > 6 and parts[6] else 0.0,
                    "cost_price_rmb": float(parts[7]) if len(parts) > 7 and parts[7] else 0.0,
                    "date_code": parts[8] if len(parts) > 8 else "",
                    "delivery_date": parts[9] if len(parts) > 9 else "",
                    "status": parts[10] if len(parts) > 10 else "询价中",
                    "remark": parts[11] if len(parts) > 11 else ""
                }
            else:
                # 旧格式：客户编号,询价型号,...
                data = {
                    "cli_id": parts[0],
                    "inquiry_mpn": parts[1] if len(parts) > 1 else "",
                    "quoted_mpn": parts[2] if len(parts) > 2 else "",
                    "inquiry_brand": parts[3] if len(parts) > 3 else "",
                    "inquiry_qty": int(parts[4]) if len(parts) > 4 and parts[4] else 0,
                    "target_price_rmb": float(parts[5]) if len(parts) > 5 and parts[5] else 0.0,
                    "cost_price_rmb": float(parts[6]) if len(parts) > 6 and parts[6] else 0.0,
                    "date_code": parts[7] if len(parts) > 7 else "",
                    "delivery_date": parts[8] if len(parts) > 8 else "",
                    "status": parts[9] if len(parts) > 9 else "询价中",
                    "remark": parts[10] if len(parts) > 10 else ""
                }

            if not data["cli_id"] or not data["inquiry_mpn"]:
                errors.append(f"{line}: 缺少必填的客户或型号")
                continue

            ok, msg = add_quote(data)
            if ok: success_count += 1
            else: errors.append(f"{data['inquiry_mpn']}: {msg}")
        except Exception as e:
            errors.append(f"{line}: 数据格式解析失败 ({str(e)})")

    return success_count, errors

def update_quote(quote_id, data):
    try:
        set_cols = []
        params = []
        for k, v in data.items():
            set_cols.append(f"{k} = ?")
            params.append(v)
        if not set_cols: return True, "No changes"
        
        sql = f"UPDATE uni_quote SET {', '.join(set_cols)} WHERE quote_id = ?"
        params.append(quote_id)
        
        with get_db_connection() as conn:
            conn.execute(sql, params)
            conn.commit()
            return True, "更新成功"
    except Exception as e:
        return False, str(e)

def delete_quote(quote_id):
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM uni_quote WHERE quote_id = ?", (quote_id,))
            conn.commit()
            return True, "删除成功"
    except Exception as e:
        return False, str(e)

def batch_delete_quote(quote_ids):
    if not quote_ids: return True, "无选中记录"
    try:
        with get_db_connection() as conn:
            placeholders = ','.join(['?'] * len(quote_ids))
            conn.execute(f"DELETE FROM uni_quote WHERE quote_id IN ({placeholders})", quote_ids)
            conn.commit()
            return True, "批量删除成功"
    except Exception as e:
        if "FOREIGN KEY constraint failed" in str(e):
            return False, "删除失败：部分记录已被[报价订单]引用，请先删除对应的报价。"
        return False, str(e)

def batch_copy_quote(quote_ids):
    try:
        if not quote_ids: return True, "未选择数据"
        with get_db_connection() as conn:
            success_count = 0
            for q_id in quote_ids:
                row = conn.execute("SELECT * FROM uni_quote WHERE quote_id=?", (q_id,)).fetchone()
                if row:
                    new_id = generate_quote_id()
                    d = dict(row)
                    sql = """
                    INSERT INTO uni_quote (quote_id, quote_date, cli_id, inquiry_mpn, quoted_mpn, inquiry_brand, inquiry_qty, actual_qty, target_price_rmb, cost_price_rmb, date_code, delivery_date, status, remark, is_transferred)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """
                    params = (
                        new_id,
                        datetime.now().strftime("%Y-%m-%d"),
                        d.get('cli_id'),
                        d.get('inquiry_mpn'),
                        d.get('quoted_mpn'),
                        d.get('inquiry_brand'),
                        d.get('inquiry_qty'),
                        d.get('actual_qty'),  # 报价数量也要复制
                        d.get('target_price_rmb'),
                        d.get('cost_price_rmb'),
                        d.get('date_code'),
                        d.get('delivery_date'),
                        d.get('status'),
                        d.get('remark'),
                        '未转'  # 复制的记录重置为未转
                    )
                    conn.execute(sql, params)
                    success_count += 1
            conn.commit()
            return True, f"成功复制 {success_count} 条记录"
    except Exception as e:
        return False, str(e)

def batch_add_quotes(items):
    """批量添加询价记录，供 skill 调用

    参数:
        items: list of dict, 每个dict包含:
            - cli_id: 客户ID (必填)
            - inquiry_mpn: 询价型号 (必填)
            - inquiry_brand: 品牌 (可选)
            - inquiry_qty: 需求数量 (可选, 默认0)
            - target_price_rmb: 目标价 (可选)
            - cost_price_rmb: 成本价 (可选)
            - date_code: 批号 (可选, 默认3年内)
            - delivery_date: 交期 (可选, 默认1~3days)
            - remark: 备注 (可选)

    返回:
        (success_count, errors, created_ids)
    """
    success_count = 0
    errors = []
    created_ids = []

    for item in items:
        try:
            # 必填字段检查
            if not item.get('cli_id'):
                errors.append(f"缺少客户ID")
                continue
            if not item.get('inquiry_mpn'):
                errors.append(f"缺少询价型号")
                continue

            ok, msg = add_quote(item)
            if ok:
                success_count += 1
                # 获取新创建的ID (从msg中提取)
                if '需求' in msg and '创建成功' in msg:
                    created_ids.append(msg.split('需求 ')[1].split(' ')[0])
            else:
                errors.append(f"{item.get('inquiry_mpn', 'unknown')}: {msg}")
        except Exception as e:
            errors.append(f"{item.get('inquiry_mpn', 'unknown')}: {str(e)}")

    return success_count, errors, created_ids
