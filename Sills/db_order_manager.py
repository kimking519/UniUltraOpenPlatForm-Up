"""
客户订单管理数据库操作模块
uni_order_manager - 客户订单主表
uni_order_manager_rel - 客户订单与销售订单关联表
uni_order_attachment - 客户订单附件表
"""

import uuid
from datetime import datetime
from Sills.base import get_db_connection, get_exchange_rates


def generate_customer_order_no():
    """生成客户订单号 (格式: CO + 时间戳 + 4位随机)"""
    import random
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_num = random.randint(1000, 9999)
    return f"CO{timestamp}{random_num}"


def get_manager_list(page=1, page_size=10, search_kw="", cli_id="", start_date="", end_date="", is_paid="", is_finished=""):
    """分页查询客户订单列表"""
    offset = (page - 1) * page_size
    query = """
    FROM uni_order_manager m
    JOIN uni_cli c ON m.cli_id = c.cli_id
    WHERE (m.customer_order_no LIKE ? OR c.cli_name LIKE ?)
    """
    params = [f"%{search_kw}%", f"%{search_kw}%"]

    if cli_id:
        query += " AND m.cli_id = ?"
        params.append(cli_id)
    if start_date:
        query += " AND m.order_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND m.order_date <= ?"
        params.append(end_date)
    if is_paid in ('0', '1'):
        query += " AND m.is_paid = ?"
        params.append(int(is_paid))
    if is_finished in ('0', '1'):
        query += " AND m.is_finished = ?"
        params.append(int(is_finished))

    count_sql = "SELECT COUNT(*) " + query
    data_sql = """SELECT m.*, c.cli_name,
                   (SELECT COUNT(*) FROM uni_order_manager_rel WHERE manager_id = m.manager_id) as rel_count
            """ + query + " ORDER BY m.order_date DESC, m.created_at DESC LIMIT ? OFFSET ?"
    params_with_limit = params + [page_size, offset]

    with get_db_connection() as conn:
        total = conn.execute(count_sql, params).fetchone()[0]
        rows = conn.execute(data_sql, params_with_limit).fetchall()

        results = []
        for r in rows:
            item = dict(r)
            # 计算采购进度（基于报价订单转采购）
            rel_count = item.get('rel_count', 0)
            item['purchase_progress'] = f"0/{rel_count}" if rel_count > 0 else "0/0"
            item['purchase_complete'] = False
            results.append(item)

    return results, total


def get_manager_by_id(manager_id):
    """根据ID获取客户订单详情"""
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT m.*, c.cli_name, c.cli_full_name,
                   (SELECT COUNT(*) FROM uni_order_manager_rel WHERE manager_id = m.manager_id) as rel_count
            FROM uni_order_manager m
            JOIN uni_cli c ON m.cli_id = c.cli_id
            WHERE m.manager_id = ?
        """, (manager_id,)).fetchone()
        if row:
            result = dict(row)
            # 计算采购进度
            rel_count = result.get('rel_count', 0)
            result['purchase_progress'] = f"0/{rel_count}" if rel_count > 0 else "0/0"
            result['purchase_complete'] = False
            return result
        return None


def get_manager_by_order_no(customer_order_no):
    """根据客户订单号获取详情"""
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT m.*, c.cli_name
            FROM uni_order_manager m
            JOIN uni_cli c ON m.cli_id = c.cli_id
            WHERE m.customer_order_no = ?
        """, (customer_order_no,)).fetchone()
        if row:
            return dict(row)
        return None


def add_manager(data):
    """创建客户订单"""
    try:
        with get_db_connection() as conn:
            manager_id = f"OM{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"
            customer_order_no = data.get('customer_order_no') or generate_customer_order_no()

            # 检查客户订单号是否重复
            existing = conn.execute("SELECT manager_id FROM uni_order_manager WHERE customer_order_no = ?", (customer_order_no,)).fetchone()
            if existing:
                return False, f"客户订单号 {customer_order_no} 已存在"

            cli_id = data.get('cli_id')
            if not cli_id:
                return False, "缺少客户编号"

            cli = conn.execute("SELECT cli_id FROM uni_cli WHERE cli_id = ?", (cli_id,)).fetchone()
            if not cli:
                return False, f"客户编号 {cli_id} 不存在"

            order_date = data.get('order_date') or datetime.now().strftime("%Y-%m-%d")

            conn.execute("""
                INSERT INTO uni_order_manager (
                    manager_id, customer_order_no, order_date, cli_id,
                    shipping_fee, tracking_no, query_link, mail_id, mail_notes, remark
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                manager_id, customer_order_no, order_date, cli_id,
                float(data.get('shipping_fee') or 0),
                data.get('tracking_no', ''),
                data.get('query_link', ''),
                data.get('mail_id', ''),
                data.get('mail_notes', ''),
                data.get('remark', '')
            ))
            conn.commit()
            return True, {"manager_id": manager_id, "customer_order_no": customer_order_no}
    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def update_manager(manager_id, data):
    """更新客户订单基本信息"""
    try:
        allowed_fields = ['customer_order_no', 'order_date', 'cli_id', 'shipping_fee',
                         'tracking_no', 'query_link', 'mail_id', 'mail_notes', 'remark',
                         'is_paid', 'is_finished', 'paid_amount']

        set_cols = []
        params = []
        for k, v in data.items():
            if k in allowed_fields:
                if k in ['is_paid', 'is_finished']:
                    set_cols.append(f"{k} = ?")
                    params.append(int(v))
                elif k in ['shipping_fee', 'paid_amount']:
                    set_cols.append(f"{k} = ?")
                    params.append(float(v))
                else:
                    set_cols.append(f"{k} = ?")
                    params.append(v)

        if not set_cols:
            return True, "无更新内容"

        sql = f"UPDATE uni_order_manager SET {', '.join(set_cols)} WHERE manager_id = ?"
        params.append(manager_id)

        with get_db_connection() as conn:
            conn.execute(sql, params)
            conn.commit()
        return True, "更新成功"
    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def delete_manager(manager_id):
    """删除客户订单（有关联报价订单时禁止删除）"""
    try:
        with get_db_connection() as conn:
            # 检查是否有关联的报价订单
            rel_count = conn.execute("SELECT COUNT(*) FROM uni_order_manager_rel WHERE manager_id = ?", (manager_id,)).fetchone()[0]
            if rel_count > 0:
                return False, f"无法删除：该客户订单关联了 {rel_count} 条报价订单，请先移除关联"

            # 删除附件记录
            conn.execute("DELETE FROM uni_order_attachment WHERE manager_id = ?", (manager_id,))

            # 删除客户订单
            conn.execute("DELETE FROM uni_order_manager WHERE manager_id = ?", (manager_id,))
            conn.commit()
        return True, "删除成功"
    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def add_offer_to_manager(manager_id, offer_id):
    """添加报价订单到客户订单"""
    try:
        with get_db_connection() as conn:
            # 检查客户订单是否存在
            manager = conn.execute("SELECT manager_id FROM uni_order_manager WHERE manager_id = ?", (manager_id,)).fetchone()
            if not manager:
                return False, "客户订单不存在"

            # 检查报价订单是否存在
            offer = conn.execute("SELECT offer_id FROM uni_offer WHERE offer_id = ?", (offer_id,)).fetchone()
            if not offer:
                return False, "报价订单不存在"

            # 检查是否已关联
            existing = conn.execute("SELECT id FROM uni_order_manager_rel WHERE manager_id = ? AND offer_id = ?", (manager_id, offer_id)).fetchone()
            if existing:
                return False, "该报价订单已关联到此客户订单"

            # 添加关联
            conn.execute("INSERT INTO uni_order_manager_rel (manager_id, offer_id) VALUES (?, ?)", (manager_id, offer_id))
            conn.commit()

            # 重新计算汇总
            recalculate_manager_totals(manager_id)

        return True, "关联成功"
    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def remove_offer_from_manager(manager_id, offer_id):
    """从客户订单移除报价订单"""
    try:
        with get_db_connection() as conn:
            result = conn.execute("DELETE FROM uni_order_manager_rel WHERE manager_id = ? AND offer_id = ?", (manager_id, offer_id))
            if result.rowcount == 0:
                return False, "关联记录不存在"
            conn.commit()

            # 重新计算汇总
            recalculate_manager_totals(manager_id)

        return True, "移除成功"
    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def recalculate_manager_totals(manager_id):
    """重新计算客户订单的汇总字段"""
    with get_db_connection() as conn:
        # 查询所有关联的报价订单
        rows = conn.execute("""
            SELECT o.offer_price_rmb as price_rmb, o.price_kwr, o.price_usd, o.cost_price_rmb,
                   COALESCE(o.quoted_qty, 1) as qty
            FROM uni_order_manager_rel r
            JOIN uni_offer o ON r.offer_id = o.offer_id
            WHERE r.manager_id = ?
        """, (manager_id,)).fetchall()

        total_price_rmb = 0.0
        total_price_kwr = 0.0
        total_price_usd = 0.0
        total_cost_rmb = 0.0
        total_qty = 0

        for r in rows:
            qty = int(r['qty'] or 1)
            price_rmb = float(r['price_rmb'] or 0)
            price_kwr = float(r['price_kwr'] or 0)
            price_usd = float(r['price_usd'] or 0)
            cost_rmb = float(r['cost_price_rmb'] or 0)

            # 价格 × 数量 = 总价
            total_price_rmb += price_rmb * qty
            total_price_kwr += price_kwr * qty
            total_price_usd += price_usd * qty
            total_cost_rmb += cost_rmb * qty
            total_qty += qty

        model_count = len(rows)
        profit_rmb = total_price_rmb - total_cost_rmb

        # 更新客户订单
        conn.execute("""
            UPDATE uni_order_manager SET
                total_price_rmb = ?, total_price_kwr = ?, total_price_usd = ?,
                total_cost_rmb = ?, profit_rmb = ?, model_count = ?, total_qty = ?
            WHERE manager_id = ?
        """, (round(total_price_rmb, 2), round(total_price_kwr, 2), round(total_price_usd, 2),
              round(total_cost_rmb, 2), round(profit_rmb, 2), model_count, total_qty, manager_id))
        conn.commit()


def get_manager_offers(manager_id):
    """获取客户订单关联的所有报价订单"""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT o.*, c.cli_name, v.vendor_name
            FROM uni_order_manager_rel r
            JOIN uni_offer o ON r.offer_id = o.offer_id
            LEFT JOIN uni_quote q ON o.quote_id = q.quote_id
            LEFT JOIN uni_cli c ON q.cli_id = c.cli_id
            LEFT JOIN uni_vendor v ON o.vendor_id = v.vendor_id
            WHERE r.manager_id = ?
            ORDER BY o.created_at DESC
        """, (manager_id,)).fetchall()

        results = [dict(r) for r in rows]

        # 计算每条记录的利润
        for r in results:
            price = float(r.get('offer_price_rmb') or 0)
            cost = float(r.get('cost_price_rmb') or 0)
            qty = int(r.get('quoted_qty') or 1)
            r['profit'] = round((price - cost) * qty, 2)
            r['total_price'] = round(price * qty, 2)

        return results


def get_available_offers_for_manager(cli_id=None, manager_id=None):
    """获取可添加到客户订单的报价订单（未被关联的）"""
    with get_db_connection() as conn:
        query = """
            SELECT o.offer_id, o.offer_date, o.quoted_mpn, o.inquiry_mpn,
                   o.offer_price_rmb, o.quoted_qty, q.cli_id, c.cli_name
            FROM uni_offer o
            LEFT JOIN uni_quote q ON o.quote_id = q.quote_id
            LEFT JOIN uni_cli c ON q.cli_id = c.cli_id
            WHERE o.offer_id NOT IN (SELECT offer_id FROM uni_order_manager_rel)
        """
        params = []

        if cli_id:
            query += " AND q.cli_id = ?"
            params.append(cli_id)

        # 如果指定了 manager_id，可以显示该客户订单已关联的报价订单
        if manager_id:
            query = query.replace(
                "WHERE o.offer_id NOT IN (SELECT offer_id FROM uni_order_manager_rel)",
                """WHERE (o.offer_id NOT IN (SELECT offer_id FROM uni_order_manager_rel)
                   OR o.offer_id IN (SELECT offer_id FROM uni_order_manager_rel WHERE manager_id = ?))"""
            )
            params.insert(0, manager_id)

        query += " ORDER BY o.offer_date DESC LIMIT 100"

        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def batch_import_manager_from_rows(rows_data, cli_id=None):
    """批量导入客户订单（从已解析的行数据）

    Args:
        rows_data: 已解析的行数据列表（可以是CSV解析或Excel解析的结果）
        cli_id: 默认客户编号

    支持两种格式:
    - 新格式: 日期,客户名,订单号,备注
    - 旧格式: 订单号,客户编号,日期,备注
    """
    success_count = 0
    errors = []

    try:
        if not rows_data:
            return 0, ["无数据"]

        # 跳过标题行
        start_idx = 0
        if len(rows_data[0]) > 0 and ("订单号" in str(rows_data[0][0]) or "日期" in str(rows_data[0][0])):
            start_idx = 1

        with get_db_connection() as conn:
            # 构建客户名到客户编号的映射
            cli_name_to_id = {}
            cli_rows = conn.execute("SELECT cli_id, cli_name FROM uni_cli").fetchall()
            for cli_row in cli_rows:
                cli_name_to_id[cli_row['cli_name']] = cli_row['cli_id']

            for row in rows_data[start_idx:]:
                if not row or len(row) < 1:
                    continue
                try:
                    # 检测格式：如果第一个字段是日期格式，则是新格式（仅接受 YYYY-MM-DD）
                    import re
                    first_field = row[0] if len(row) > 0 else ""
                    is_new_format = bool(re.match(r'^\d{4}-\d{1,2}-\d{1,2}$', first_field))

                    if is_new_format:
                        # 新格式：日期,客户名,订单号,备注
                        order_date = row[0] if len(row) > 0 else datetime.now().strftime("%Y-%m-%d")
                        cli_name = row[1] if len(row) > 1 else ""
                        customer_order_no = row[2] if len(row) > 2 else ""
                        remark = row[3] if len(row) > 3 else ""

                        if not customer_order_no:
                            continue

                        # 通过客户名查找客户编号
                        row_cli_id = cli_name_to_id.get(cli_name)
                        if not row_cli_id:
                            errors.append(f"{customer_order_no}: 客户名 '{cli_name}' 不存在")
                            continue
                    else:
                        # 旧格式：订单号,客户编号,日期,备注
                        customer_order_no = row[0] if len(row) > 0 else ""
                        if not customer_order_no:
                            continue

                        row_cli_id = row[1] if len(row) > 1 and row[1] else cli_id
                        if not row_cli_id:
                            errors.append(f"{customer_order_no}: 缺少客户编号")
                            continue

                        cli = conn.execute("SELECT cli_id FROM uni_cli WHERE cli_id = ?", (row_cli_id,)).fetchone()
                        if not cli:
                            errors.append(f"{customer_order_no}: 客户不存在")
                            continue

                        order_date = row[2] if len(row) > 2 else datetime.now().strftime("%Y-%m-%d")
                        remark = row[3] if len(row) > 3 else ""

                    # 检查是否已存在
                    existing = conn.execute("SELECT manager_id FROM uni_order_manager WHERE customer_order_no = ?", (customer_order_no,)).fetchone()
                    if existing:
                        errors.append(f"{customer_order_no}: 已存在")
                        continue

                    manager_id = f"OM{datetime.now().strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"

                    conn.execute("""
                        INSERT INTO uni_order_manager (manager_id, customer_order_no, order_date, cli_id, remark)
                        VALUES (?, ?, ?, ?, ?)
                    """, (manager_id, customer_order_no, order_date, row_cli_id, remark))
                    success_count += 1

                except Exception as e:
                    errors.append(f"行处理失败：{str(e)}")

            if success_count > 0:
                conn.commit()

    except Exception as e:
        errors.append(f"导入失败：{str(e)}")

    return success_count, errors


def batch_import_manager(text, cli_id=None):
    """批量导入客户订单（从文本/CSV格式）

    支持两种格式:
    - 新格式: 日期,客户名,订单号,备注
    - 旧格式: 订单号,客户编号,日期,备注
    """
    import io, csv
    f = io.StringIO(text.strip())
    reader = csv.reader(f)
    rows_data = list(reader)
    return batch_import_manager_from_rows(rows_data, cli_id)


def batch_delete_managers(manager_ids):
    """批量删除客户订单（有关联销售订单或报价时禁止删除）"""
    if not manager_ids:
        return True, "无选中记录"
    try:
        with get_db_connection() as conn:
            placeholders = ','.join(['?'] * len(manager_ids))
            # 检查是否有关联的销售订单
            rel_count = conn.execute(f"SELECT COUNT(*) FROM uni_order_manager_rel WHERE manager_id IN ({placeholders})", manager_ids).fetchone()[0]
            if rel_count > 0:
                return False, f"无法删除：选中的客户订单共关联了 {rel_count} 条销售订单，请先移除关联"

            # 检查是否有关联的报价
            offer_count = conn.execute(f"SELECT COUNT(*) FROM uni_offer WHERE manager_id IN ({placeholders})", manager_ids).fetchone()[0]
            if offer_count > 0:
                return False, f"无法删除：选中的客户订单共关联了 {offer_count} 条报价，请先移除关联"

            # 删除附件
            conn.execute(f"DELETE FROM uni_order_attachment WHERE manager_id IN ({placeholders})", manager_ids)
            # 删除客户订单
            conn.execute(f"DELETE FROM uni_order_manager WHERE manager_id IN ({placeholders})", manager_ids)
            conn.commit()
        return True, f"成功删除 {len(manager_ids)} 条记录"
    except Exception as e:
        return False, str(e)


# ============ 附件管理 ============

def add_attachment(manager_id, file_path, file_type, file_name):
    """添加附件记录"""
    try:
        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO uni_order_attachment (manager_id, file_path, file_type, file_name)
                VALUES (?, ?, ?, ?)
            """, (manager_id, file_path, file_type, file_name))
            conn.commit()
        return True, "附件添加成功"
    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def get_attachments(manager_id):
    """获取客户订单的所有附件"""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT * FROM uni_order_attachment
            WHERE manager_id = ?
            ORDER BY created_at DESC
        """, (manager_id,)).fetchall()
        return [dict(r) for r in rows]


def delete_attachment(attachment_id):
    """删除附件记录"""
    try:
        with get_db_connection() as conn:
            # 获取文件路径
            row = conn.execute("SELECT file_path FROM uni_order_attachment WHERE id = ?", (attachment_id,)).fetchone()
            if not row:
                return False, "附件不存在"

            file_path = row['file_path']

            # 删除数据库记录
            conn.execute("DELETE FROM uni_order_attachment WHERE id = ?", (attachment_id,))
            conn.commit()

            # 删除文件
            import os
            if os.path.exists(file_path):
                os.remove(file_path)

        return True, "附件删除成功"
    except Exception as e:
        return False, f"删除失败：{str(e)}"


# ============ 报价转客户订单 ============

def get_manager_list_by_cli(cli_id):
    """获取指定客户的客户订单列表（用于报价转订单时选择）"""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT manager_id, customer_order_no, order_date, model_count, total_qty
            FROM uni_order_manager
            WHERE cli_id = ?
            ORDER BY order_date DESC, created_at DESC
            LIMIT 50
        """, (cli_id,)).fetchall()
        return [dict(r) for r in rows]


def batch_convert_offers_to_manager(offer_ids, manager_id):
    """
    批量将报价转入客户订单

    流程：
    1. 验证客户一致性
    2. 创建销售订单(uni_order)
    3. 建立客户订单与销售订单的关联(uni_order_manager_rel)
    4. 更新报价状态

    Args:
        offer_ids: 报价ID列表
        manager_id: 目标客户订单ID

    Returns:
        (success, message)
    """
    if not offer_ids:
        return False, "未选中报价记录"

    try:
        with get_db_connection() as conn:
            # 检查客户订单是否存在
            manager = conn.execute("""
                SELECT m.manager_id, m.cli_id, c.cli_name
                FROM uni_order_manager m
                JOIN uni_cli c ON m.cli_id = c.cli_id
                WHERE m.manager_id = ?
            """, (manager_id,)).fetchone()
            if not manager:
                return False, "客户订单不存在"

            manager_cli_id = manager['cli_id']
            manager_cli_name = manager['cli_name']

            # 获取报价信息并验证客户一致性
            placeholders = ','.join(['?'] * len(offer_ids))
            offers = conn.execute(f"""
                SELECT o.offer_id, o.quote_id, o.inquiry_mpn, o.quoted_mpn,
                       o.inquiry_brand, o.quoted_brand,
                       o.offer_price_rmb, o.price_kwr, o.price_usd, o.cost_price_rmb,
                       o.quoted_qty, o.is_transferred, o.manager_id,
                       q.cli_id, c.cli_name as offer_cli_name
                FROM uni_offer o
                LEFT JOIN uni_quote q ON o.quote_id = q.quote_id
                LEFT JOIN uni_cli c ON q.cli_id = c.cli_id
                WHERE o.offer_id IN ({placeholders})
            """, offer_ids).fetchall()

            success_count = 0
            errors = []
            order_date = datetime.now().strftime("%Y-%m-%d")

            for offer in offers:
                offer_data = dict(offer)

                # 检查是否已转入其他客户订单
                if offer_data.get('manager_id') and offer_data['manager_id'] != manager_id:
                    errors.append(f"{offer_data['offer_id']}: 已转入其他客户订单")
                    continue

                # 检查是否已存在销售订单
                existing_order = conn.execute(
                    "SELECT order_id FROM uni_order WHERE offer_id = ?",
                    (offer_data['offer_id'],)
                ).fetchone()
                if existing_order:
                    # 检查是否已关联到此客户订单
                    existing_rel = conn.execute(
                        "SELECT id FROM uni_order_manager_rel WHERE manager_id = ? AND order_id = ?",
                        (manager_id, existing_order['order_id'])
                    ).fetchone()
                    if existing_rel:
                        errors.append(f"{offer_data['offer_id']}: 已存在关联的销售订单")
                        continue
                    # 已有销售订单但未关联，建立关联
                    conn.execute("""
                        INSERT INTO uni_order_manager_rel (manager_id, order_id)
                        VALUES (?, ?)
                    """, (manager_id, existing_order['order_id']))
                    conn.execute("UPDATE uni_offer SET manager_id = ?, is_transferred = '已转' WHERE offer_id = ?",
                                (manager_id, offer_data['offer_id']))
                    success_count += 1
                    continue

                # 验证客户一致性
                offer_cli_id = offer_data.get('cli_id')
                if offer_cli_id and offer_cli_id != manager_cli_id:
                    errors.append(f"{offer_data['offer_id']}: 客户不匹配（报价客户: {offer_data.get('offer_cli_name', '未知')}，目标客户: {manager_cli_name}）")
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

                # 创建销售订单
                conn.execute("""
                    INSERT INTO uni_order (
                        order_id, order_no, order_date, cli_id, offer_id,
                        inquiry_mpn, inquiry_brand, price_rmb, price_kwr, price_usd,
                        cost_price_rmb, is_finished, is_paid, paid_amount, return_status,
                        remark, is_transferred
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    order_id, order_id, order_date, manager_cli_id, offer_data['offer_id'],
                    offer_data['quoted_mpn'] or offer_data['inquiry_mpn'],
                    offer_data['quoted_brand'] or offer_data['inquiry_brand'],
                    offer_data['offer_price_rmb'], offer_data['price_kwr'], offer_data['price_usd'],
                    offer_data['cost_price_rmb'], 0, 0, 0.0, '正常',
                    '', '未转'
                ))

                # 建立客户订单与销售订单的关联
                conn.execute("""
                    INSERT INTO uni_order_manager_rel (manager_id, order_id)
                    VALUES (?, ?)
                """, (manager_id, order_id))

                # 更新报价状态
                conn.execute("""
                    UPDATE uni_offer SET manager_id = ?, is_transferred = '已转'
                    WHERE offer_id = ?
                """, (manager_id, offer_data['offer_id']))

                success_count += 1

            if success_count > 0:
                conn.commit()

            if success_count == 0 and errors:
                return False, errors[0]

            return True, f"成功转入 {success_count} 条报价" + (f" (失败 {len(errors)} 条)" if errors else "")

    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def get_manager_orders_for_purchase(manager_id):
    """获取客户订单中可用于转采购的报价订单（排除已转采购的）"""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT o.offer_id, o.quoted_mpn as inquiry_mpn, o.quoted_brand as buy_brand, o.offer_price_rmb as price_rmb, o.price_usd,
                   o.cost_price_rmb, q.cli_id, c.cli_name,
                   o.quoted_qty, o.date_code, o.delivery_date,
                   v.vendor_id, v.vendor_name, m.customer_order_no,
                   CASE WHEN bu.buy_id IS NOT NULL THEN 1 ELSE 0 END as is_purchased
            FROM uni_order_manager_rel r
            JOIN uni_offer o ON r.offer_id = o.offer_id
            JOIN uni_order_manager m ON r.manager_id = m.manager_id
            LEFT JOIN uni_quote q ON o.quote_id = q.quote_id
            LEFT JOIN uni_cli c ON q.cli_id = c.cli_id
            LEFT JOIN uni_vendor v ON o.vendor_id = v.vendor_id
            LEFT JOIN uni_order ord ON ord.offer_id = o.offer_id
            LEFT JOIN uni_buy bu ON bu.order_id = ord.order_id
            WHERE r.manager_id = ?
            ORDER BY o.created_at DESC
        """, (manager_id,)).fetchall()
        return [dict(r) for r in rows]


def get_all_manager_orders_for_purchase(manager_ids):
    """批量获取多个客户订单的报价订单用于转采购（排除已转采购的）"""
    if not manager_ids:
        return []

    with get_db_connection() as conn:
        placeholders = ','.join(['?'] * len(manager_ids))
        rows = conn.execute(f"""
            SELECT o.offer_id, o.quoted_mpn as inquiry_mpn, o.quoted_brand as buy_brand, o.offer_price_rmb as price_rmb, o.price_usd,
                   o.cost_price_rmb, q.cli_id, c.cli_name,
                   o.quoted_qty, o.date_code, o.delivery_date,
                   v.vendor_id, v.vendor_name, r.manager_id, m.customer_order_no,
                   CASE WHEN bu.buy_id IS NOT NULL THEN 1 ELSE 0 END as is_purchased
            FROM uni_order_manager_rel r
            JOIN uni_offer o ON r.offer_id = o.offer_id
            JOIN uni_order_manager m ON r.manager_id = m.manager_id
            LEFT JOIN uni_quote q ON o.quote_id = q.quote_id
            LEFT JOIN uni_cli c ON q.cli_id = c.cli_id
            LEFT JOIN uni_vendor v ON o.vendor_id = v.vendor_id
            LEFT JOIN uni_order ord ON ord.offer_id = o.offer_id
            LEFT JOIN uni_buy bu ON bu.order_id = ord.order_id
            WHERE r.manager_id IN ({placeholders})
            ORDER BY o.created_at DESC
        """, manager_ids).fetchall()
        # 只返回未转采购的
        return [dict(r) for r in rows if not r.get('is_purchased')]