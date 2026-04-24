"""
银行流水管理数据库操作模块
uni_bank_transaction - 银行流水主表
"""

import uuid
from datetime import datetime
from Sills.base import get_db_connection


def generate_transaction_id():
    """生成流水ID (格式: BT-YYYYMMDDHHMMSS-XXXX)"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_num = uuid.uuid4().hex[:4].upper()
    return f"BT-{timestamp}-{random_num}"


def generate_batch_id():
    """生成导入批次ID (格式: BATCH-YYYYMMDDHHMM-XXX)"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M")
    random_num = uuid.uuid4().hex[:3].upper()
    return f"BATCH-{timestamp}-{random_num}"


def get_transaction_list(page=1, page_size=20, start_date="", end_date="",
                         transaction_type="", is_matched="", payer_name="",
                         min_amount="", max_amount="", import_batch=""):
    """分页查询银行流水列表"""
    offset = (page - 1) * page_size
    query = "FROM uni_bank_transaction WHERE 1=1"
    params = []

    if start_date:
        query += " AND transaction_time >= ?"
        params.append(start_date)
    if end_date:
        query += " AND transaction_time <= ?"
        params.append(end_date)
    if transaction_type:
        query += " AND transaction_type = ?"
        params.append(transaction_type)
    if is_matched in ('0', '1', '2'):
        query += " AND is_matched = ?"
        params.append(int(is_matched))
    if payer_name:
        query += " AND payer_name LIKE ?"
        params.append(f"%{payer_name}%")
    if min_amount:
        query += " AND transaction_amount >= ?"
        params.append(float(min_amount))
    if max_amount:
        query += " AND transaction_amount <= ?"
        params.append(float(max_amount))
    if import_batch:
        query += " AND import_batch = ?"
        params.append(import_batch)

    count_sql = "SELECT COUNT(*) " + query
    data_sql = "SELECT * " + query + " ORDER BY transaction_time DESC LIMIT ? OFFSET ?"
    params_with_limit = params + [page_size, offset]

    with get_db_connection() as conn:
        total = conn.execute(count_sql, params).fetchone()[0]
        rows = conn.execute(data_sql, params_with_limit).fetchall()
        results = [dict(r) for r in rows]

    return results, total


def get_transaction_by_id(transaction_id):
    """根据ID获取流水详情"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM uni_bank_transaction WHERE transaction_id = ?",
            (transaction_id,)
        ).fetchone()
        if row:
            return dict(row)
        return None


def get_transaction_by_bank_no(transaction_no, ledger_no=None):
    """根据银行流水号查询（用于去重检查）"""
    with get_db_connection() as conn:
        if ledger_no:
            row = conn.execute(
                "SELECT transaction_id FROM uni_bank_transaction WHERE transaction_no = ? AND ledger_no = ?",
                (transaction_no, ledger_no)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT transaction_id FROM uni_bank_transaction WHERE transaction_no = ?",
                (transaction_no,)
            ).fetchone()
        if row:
            return dict(row)
        return None


def add_transaction(data):
    """添加单条银行流水"""
    try:
        with get_db_connection() as conn:
            transaction_id = generate_transaction_id()

            # 处理交易时间格式
            transaction_time = data.get('transaction_time')
            if isinstance(transaction_time, str) and transaction_time:
                # 尝试解析不同格式的时间
                try:
                    # 格式: YYYY/MM/DD HH:MM:SS 或 YYYY-MM-DD HH:MM:SS
                    if '/' in transaction_time:
                        dt = datetime.strptime(transaction_time, "%Y/%m/%d %H:%M:%S")
                    elif '-' in transaction_time and ':' in transaction_time:
                        dt = datetime.strptime(transaction_time, "%Y-%m-%d %H:%M:%S")
                    else:
                        dt = datetime.strptime(transaction_time, "%Y-%m-%d")
                    transaction_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    transaction_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            conn.execute("""
                INSERT INTO uni_bank_transaction (
                    transaction_id, transaction_time, transaction_no, ledger_no,
                    transaction_type, transaction_detail, currency, transaction_amount,
                    balance, payer_name, payer_bank, payer_account,
                    payee_name, payee_bank, payee_account, payee_remark_name,
                    remark_text, internal_remark, source_file, import_batch,
                    is_matched, matched_amount
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                transaction_id,
                transaction_time,
                data.get('transaction_no', ''),
                data.get('ledger_no', ''),
                data.get('transaction_type', '收入'),
                data.get('transaction_detail', ''),
                data.get('currency', 'CNY'),
                float(data.get('transaction_amount') or 0),
                float(data.get('balance') or 0) if data.get('balance') else None,
                data.get('payer_name', ''),
                data.get('payer_bank', ''),
                data.get('payer_account', ''),
                data.get('payee_name', ''),
                data.get('payee_bank', ''),
                data.get('payee_account', ''),
                data.get('payee_remark_name', ''),
                data.get('remark_text', ''),
                data.get('internal_remark', ''),
                data.get('source_file', ''),
                data.get('import_batch', generate_batch_id()),
                0,
                0.0
            ))
            conn.commit()
        return True, {"transaction_id": transaction_id}
    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def batch_import_transactions(rows_data, source_file="", batch_id=None):
    """批量导入银行流水（从已解析的Excel行数据）

    Args:
        rows_data: 已解析的行数据列表
        source_file: 来源文件名
        batch_id: 批次ID（可选，默认自动生成）

    Returns:
        (success_count, errors, batch_id)
    """
    success_count = 0
    errors = []

    if not batch_id:
        batch_id = generate_batch_id()

    if not rows_data:
        return 0, ["无数据"], batch_id

    try:
        with get_db_connection() as conn:
            for idx, row in enumerate(rows_data, start=1):
                try:
                    # 去重检查
                    transaction_no = row.get('transaction_no', '')
                    ledger_no = row.get('ledger_no', '')

                    if transaction_no or ledger_no:
                        existing = get_transaction_by_bank_no(transaction_no, ledger_no)
                        if existing:
                            continue  # 跳过重复流水

                    transaction_id = generate_transaction_id()

                    # 处理交易时间
                    transaction_time = row.get('transaction_time')
                    if isinstance(transaction_time, str) and transaction_time:
                        try:
                            if '/' in transaction_time:
                                dt = datetime.strptime(transaction_time, "%Y/%m/%d %H:%M:%S")
                            elif '-' in transaction_time and ':' in transaction_time:
                                dt = datetime.strptime(transaction_time, "%Y-%m-%d %H:%M:%S")
                            else:
                                dt = datetime.strptime(transaction_time, "%Y-%m-%d")
                            transaction_time = dt.strftime("%Y-%m-%d %H:%M:%S")
                        except:
                            transaction_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        transaction_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    # 处理金额（确保为正数）
                    amount = float(row.get('transaction_amount') or 0)
                    if amount < 0:
                        amount = abs(amount)  # 转为正数

                    conn.execute("""
                        INSERT INTO uni_bank_transaction (
                            transaction_id, transaction_time, transaction_no, ledger_no,
                            transaction_type, transaction_detail, currency, transaction_amount,
                            balance, payer_name, payer_bank, payer_account,
                            payee_name, payee_bank, payee_account, payee_remark_name,
                            remark_text, internal_remark, source_file, import_batch,
                            is_matched, matched_amount
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        transaction_id,
                        transaction_time,
                        transaction_no,
                        ledger_no,
                        row.get('transaction_type', '收入'),
                        row.get('transaction_detail', ''),
                        row.get('currency', 'CNY'),
                        amount,
                        float(row.get('balance') or 0) if row.get('balance') else None,
                        row.get('payer_name', ''),
                        row.get('payer_bank', ''),
                        row.get('payer_account', ''),
                        row.get('payee_name', ''),
                        row.get('payee_bank', ''),
                        row.get('payee_account', ''),
                        row.get('payee_remark_name', ''),
                        row.get('remark_text', ''),
                        '',
                        source_file,
                        batch_id,
                        0,
                        0.0
                    ))
                    success_count += 1

                except Exception as e:
                    errors.append(f"第{idx}行导入失败：{str(e)}")

            if success_count > 0:
                conn.commit()

    except Exception as e:
        errors.append(f"批量导入失败：{str(e)}")

    return success_count, errors, batch_id


def update_transaction(transaction_id, data):
    """更新流水信息（仅允许更新备注等非关键字段）"""
    try:
        allowed_fields = ['internal_remark']
        set_cols = []
        params = []

        for k, v in data.items():
            if k in allowed_fields:
                set_cols.append(f"{k} = ?")
                params.append(v)

        if not set_cols:
            return True, "无更新内容"

        params.append(transaction_id)

        with get_db_connection() as conn:
            conn.execute(
                f"UPDATE uni_bank_transaction SET {', '.join(set_cols)} WHERE transaction_id = ?",
                params
            )
            conn.commit()
        return True, "更新成功"
    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def delete_transaction(transaction_id):
    """删除单条流水（需检查是否已匹配）"""
    try:
        with get_db_connection() as conn:
            # 检查是否已匹配
            tx = conn.execute(
                "SELECT is_matched FROM uni_bank_transaction WHERE transaction_id = ?",
                (transaction_id,)
            ).fetchone()
            if not tx:
                return False, "流水不存在"
            if tx['is_matched'] in (1, 2):
                return False, "该流水已关联订单，请先解除关联"

            conn.execute(
                "DELETE FROM uni_bank_transaction WHERE transaction_id = ?",
                (transaction_id,)
            )
            conn.commit()
        return True, "删除成功"
    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def batch_delete_by_batch(import_batch):
    """按批次删除流水"""
    try:
        with get_db_connection() as conn:
            # 检查该批次是否有已匹配的流水
            matched_count = conn.execute(
                "SELECT COUNT(*) FROM uni_bank_transaction WHERE import_batch = ? AND is_matched IN (1, 2)",
                (import_batch,)
            ).fetchone()[0]
            if matched_count > 0:
                return False, f"该批次有 {matched_count} 条已匹配流水，请先解除关联"

            result = conn.execute(
                "DELETE FROM uni_bank_transaction WHERE import_batch = ?",
                (import_batch,)
            )
            deleted_count = result.rowcount if hasattr(result, 'rowcount') else 0
            conn.commit()
        return True, f"已删除 {deleted_count} 条流水"
    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def batch_delete_selected(transaction_ids):
    """批量删除勾选的流水（仅允许删除未匹配的流水）"""
    try:
        if not transaction_ids:
            return False, "未选择任何流水"

        with get_db_connection() as conn:
            # 检查是否有已匹配的流水
            matched_ids = []
            for tx_id in transaction_ids:
                tx = conn.execute(
                    "SELECT is_matched FROM uni_bank_transaction WHERE transaction_id = ?",
                    (tx_id,)
                ).fetchone()
                if tx and tx['is_matched'] in (1, 2):
                    matched_ids.append(tx_id)

            if matched_ids:
                return False, f"有 {len(matched_ids)} 条已匹配流水无法删除，请先解除关联"

            # 执行删除
            placeholders = ','.join(['?' for _ in transaction_ids])
            result = conn.execute(
                f"DELETE FROM uni_bank_transaction WHERE transaction_id IN ({placeholders}) AND is_matched = 0",
                transaction_ids
            )
            deleted_count = result.rowcount if hasattr(result, 'rowcount') else len(transaction_ids)
            conn.commit()

        return True, f"已删除 {deleted_count} 条流水"
    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def update_matched_status(transaction_id):
    """更新流水的匹配状态（关联/解除关联后调用）"""
    with get_db_connection() as conn:
        # 获取流水总金额
        tx = conn.execute(
            "SELECT transaction_amount FROM uni_bank_transaction WHERE transaction_id = ?",
            (transaction_id,)
        ).fetchone()
        if not tx:
            return

        total = float(tx['transaction_amount'])

        # 计算已匹配金额
        matched = conn.execute(
            "SELECT COALESCE(SUM(allocation_amount), 0) FROM uni_bank_ledger WHERE transaction_id = ?",
            (transaction_id,)
        ).fetchone()[0]
        matched = float(matched)

        # 计算匹配状态
        if matched == 0:
            status = 0  # 未匹配
        elif matched >= total:
            status = 1  # 完全匹配
        else:
            status = 2  # 部分匹配

        conn.execute(
            "UPDATE uni_bank_transaction SET is_matched = ?, matched_amount = ? WHERE transaction_id = ?",
            (status, matched, transaction_id)
        )
        conn.commit()


def get_batch_list():
    """获取所有导入批次列表"""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT import_batch, source_file, COUNT(*) as count,
                   MIN(transaction_time) as min_time,
                   MAX(transaction_time) as max_time,
                   SUM(CASE WHEN is_matched = 0 THEN 1 ELSE 0 END) as unmatched_count,
                   created_at
            FROM uni_bank_transaction
            GROUP BY import_batch, source_file
            ORDER BY created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_unmatched_transactions(limit=100):
    """获取未匹配的流水（用于自动匹配）"""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT transaction_id, transaction_time, transaction_amount,
                   payer_name, payee_name, remark_text, transaction_no
            FROM uni_bank_transaction
            WHERE is_matched = 0
            ORDER BY transaction_time DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]