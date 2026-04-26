"""
银行台账关联数据库操作模块
uni_bank_ledger - 流水与订单关联表
"""

import uuid
from datetime import datetime
from Sills.base import get_db_connection
from Sills.db_bank_transaction import update_matched_status


def generate_ledger_id():
    """生成台账ID (格式: LED-YYYYMMDDHHMMSS-XXXXXXXX)
    使用8位随机字符，避免批量创建时ID碰撞
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_num = uuid.uuid4().hex[:8].upper()  # 8位随机，约4亿种组合
    return f"LED-{timestamp}-{random_num}"


def get_ledger_by_transaction(transaction_id):
    """查询流水关联的所有订单"""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT l.*, m.customer_order_no, c.cli_name,
                   bt.transaction_amount, bt.transaction_time, bt.payer_name
            FROM uni_bank_ledger l
            JOIN uni_order_manager m ON l.manager_id = m.manager_id
            JOIN uni_cli c ON m.cli_id = c.cli_id
            JOIN uni_bank_transaction bt ON l.transaction_id = bt.transaction_id
            WHERE l.transaction_id = ?
            ORDER BY l.is_primary DESC, l.created_at ASC
        """, (transaction_id,)).fetchall()
        return [dict(r) for r in rows]


def get_ledger_by_manager(manager_id):
    """查询订单关联的所有流水"""
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT l.*, bt.transaction_no, bt.transaction_time, bt.transaction_type,
                   bt.transaction_amount, bt.currency, bt.payer_name, bt.payee_name,
                   bt.remark_text, bt.is_matched as tx_matched
            FROM uni_bank_ledger l
            JOIN uni_bank_transaction bt ON l.transaction_id = bt.transaction_id
            WHERE l.manager_id = ?
            ORDER BY l.is_primary DESC, l.created_at ASC
        """, (manager_id,)).fetchall()

        results = [dict(r) for r in rows]

        # 计算订单总收款
        total_received = sum(float(r.get('allocation_amount') or 0) for r in results)

        return results, total_received


def validate_allocation_amount(transaction_id, new_allocation):
    """验证分配金额是否有效

    Returns:
        (is_valid, remaining_amount)
    """
    with get_db_connection() as conn:
        tx = conn.execute(
            "SELECT transaction_amount FROM uni_bank_transaction WHERE transaction_id = ?",
            (transaction_id,)
        ).fetchone()
        if not tx:
            return False, 0

        total_amount = float(tx['transaction_amount'])

        # 查询已分配总额
        allocated = conn.execute(
            "SELECT COALESCE(SUM(allocation_amount), 0) FROM uni_bank_ledger WHERE transaction_id = ?",
            (transaction_id,)
        ).fetchone()[0]
        allocated = float(allocated)

        remaining = total_amount - allocated
        # 增加容差0.01处理浮点精度误差
        return new_allocation <= remaining + 0.01, remaining


def create_ledger(transaction_id, manager_id, allocation_amount,
                  is_primary=None, match_type='manual', created_by=None, remark=''):
    """创建流水与订单的关联

    Args:
        transaction_id: 流水ID
        manager_id: 订单ID
        allocation_amount: 分配金额
        is_primary: 是否主要匹配（None时自动判断）
        match_type: 匹配类型 (manual/auto/partial)
        created_by: 创建人（员工ID）
        remark: 备注

    Returns:
        (success, message/ledger_id)
    """
    try:
        with get_db_connection() as conn:
            # 检查流水是否存在
            tx = conn.execute(
                "SELECT transaction_id, transaction_amount, is_matched FROM uni_bank_transaction WHERE transaction_id = ?",
                (transaction_id,)
            ).fetchone()
            if not tx:
                return False, "流水不存在"

            # 检查订单是否存在
            manager = conn.execute(
                "SELECT manager_id FROM uni_order_manager WHERE manager_id = ?",
                (manager_id,)
            ).fetchone()
            if not manager:
                return False, "订单不存在"

            # 检查是否已存在关联
            existing = conn.execute(
                "SELECT ledger_id FROM uni_bank_ledger WHERE transaction_id = ? AND manager_id = ?",
                (transaction_id, manager_id)
            ).fetchone()
            if existing:
                return False, "该流水与订单已存在关联"

            # 验证分配金额
            allocation = float(allocation_amount)
            if allocation <= 0:
                return False, "分配金额必须大于0"

            is_valid, remaining = validate_allocation_amount(transaction_id, allocation)
            if not is_valid:
                return False, f"分配金额超出剩余可分配金额（剩余：{remaining:.2f}）"

            # 自动设置is_primary
            if is_primary is None:
                # 检查该订单是否有已存在的is_primary=1记录
                primary_count = conn.execute(
                    "SELECT COUNT(*) FROM uni_bank_ledger WHERE manager_id = ? AND is_primary = 1",
                    (manager_id,)
                ).fetchone()[0]
                is_primary = 0 if primary_count > 0 else 1

            ledger_id = generate_ledger_id()

            conn.execute("""
                INSERT INTO uni_bank_ledger (
                    ledger_id, transaction_id, manager_id, allocation_amount,
                    is_primary, match_type, created_by, remark
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ledger_id, transaction_id, manager_id, allocation,
                is_primary, match_type, created_by, remark
            ))
            conn.commit()

            # 更新流水匹配状态
            update_matched_status(transaction_id)

            # 更新订单收款金额缓存（可选）
            update_manager_paid_amount(manager_id)

        return True, {"ledger_id": ledger_id, "is_primary": is_primary}
    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def delete_ledger(ledger_id):
    """删除关联"""
    try:
        with get_db_connection() as conn:
            # 获取关联信息
            ledger = conn.execute(
                "SELECT ledger_id, transaction_id, manager_id, is_primary FROM uni_bank_ledger WHERE ledger_id = ?",
                (ledger_id,)
            ).fetchone()
            if not ledger:
                return False, "关联不存在"

            transaction_id = ledger['transaction_id']
            manager_id = ledger['manager_id']
            was_primary = ledger['is_primary']

            # 删除关联
            conn.execute(
                "DELETE FROM uni_bank_ledger WHERE ledger_id = ?",
                (ledger_id,)
            )
            conn.commit()

            # 如果删除的是is_primary=1的记录，自动设置下一条为primary
            if was_primary == 1:
                next_ledger = conn.execute(
                    "SELECT ledger_id FROM uni_bank_ledger WHERE manager_id = ? ORDER BY created_at ASC LIMIT 1",
                    (manager_id,)
                ).fetchone()
                if next_ledger:
                    conn.execute(
                        "UPDATE uni_bank_ledger SET is_primary = 1 WHERE ledger_id = ?",
                        (next_ledger['ledger_id'],)
                    )
                    conn.commit()

            # 更新流水匹配状态
            update_matched_status(transaction_id)

            # 更新订单收款金额
            update_manager_paid_amount(manager_id)

        return True, "关联已删除"
    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def update_ledger(ledger_id, allocation_amount=None, remark=None):
    """更新关联信息"""
    try:
        with get_db_connection() as conn:
            ledger = conn.execute(
                "SELECT ledger_id, transaction_id FROM uni_bank_ledger WHERE ledger_id = ?",
                (ledger_id,)
            ).fetchone()
            if not ledger:
                return False, "关联不存在"

            transaction_id = ledger['transaction_id']

            if allocation_amount is not None:
                allocation = float(allocation_amount)
                if allocation <= 0:
                    return False, "分配金额必须大于0"

                # 计算其他分配总额
                other_allocated = conn.execute(
                    "SELECT COALESCE(SUM(allocation_amount), 0) FROM uni_bank_ledger WHERE transaction_id = ? AND ledger_id != ?",
                    (transaction_id, ledger_id)
                ).fetchone()[0]
                other_allocated = float(other_allocated)

                tx = conn.execute(
                    "SELECT transaction_amount FROM uni_bank_transaction WHERE transaction_id = ?",
                    (transaction_id,)
                ).fetchone()
                total = float(tx['transaction_amount'])

                if allocation + other_allocated > total:
                    remaining = total - other_allocated
                    return False, f"分配金额超出剩余可分配金额（剩余：{remaining:.2f}）"

                conn.execute(
                    "UPDATE uni_bank_ledger SET allocation_amount = ? WHERE ledger_id = ?",
                    (allocation, ledger_id)
                )

            if remark is not None:
                conn.execute(
                    "UPDATE uni_bank_ledger SET remark = ? WHERE ledger_id = ?",
                    (remark, ledger_id)
                )

            conn.commit()

            # 更新流水匹配状态
            update_matched_status(transaction_id)

            # 更新订单收款金额（需要查询manager_id）
            ledger_info = conn.execute(
                "SELECT manager_id FROM uni_bank_ledger WHERE ledger_id = ?",
                (ledger_id,)
            ).fetchone()
            if ledger_info:
                update_manager_paid_amount(ledger_info['manager_id'])

        return True, "更新成功"
    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def set_primary_ledger(manager_id, ledger_id):
    """设置主要匹配记录"""
    try:
        with get_db_connection() as conn:
            # 检查关联是否属于该订单
            ledger = conn.execute(
                "SELECT ledger_id FROM uni_bank_ledger WHERE ledger_id = ? AND manager_id = ?",
                (ledger_id, manager_id,)
            ).fetchone()
            if not ledger:
                return False, "关联不存在或不属于该订单"

            # 清除该订单其他记录的is_primary
            conn.execute(
                "UPDATE uni_bank_ledger SET is_primary = 0 WHERE manager_id = ?",
                (manager_id,)
            )

            # 设置当前记录为primary
            conn.execute(
                "UPDATE uni_bank_ledger SET is_primary = 1 WHERE ledger_id = ?",
                (ledger_id,)
            )
            conn.commit()

        return True, "已设为主要匹配"
    except Exception as e:
        return False, f"数据库错误：{str(e)}"


def update_manager_paid_amount(manager_id):
    """更新订单收款金额缓存"""
    with get_db_connection() as conn:
        total = conn.execute(
            "SELECT COALESCE(SUM(allocation_amount), 0) FROM uni_bank_ledger WHERE manager_id = ?",
            (manager_id,)
        ).fetchone()[0]
        total = float(total)

        conn.execute(
            "UPDATE uni_order_manager SET paid_amount = ? WHERE manager_id = ?",
            (total, manager_id)
        )
        conn.commit()


def get_ledger_summary(manager_id):
    """获取订单收款摘要"""
    ledgers, total_received = get_ledger_by_manager(manager_id)

    with get_db_connection() as conn:
        # 获取订单总金额
        manager = conn.execute(
            "SELECT total_price_rmb, customer_order_no FROM uni_order_manager WHERE manager_id = ?",
            (manager_id,)
        ).fetchone()
        if manager:
            total_price = float(manager['total_price_rmb'] or 0)
            order_no = manager['customer_order_no']
        else:
            total_price = 0
            order_no = ''

    return {
        'ledgers': ledgers,
        'total_received': total_received,
        'total_price': total_price,
        'order_no': order_no,
        'payment_progress': f"{total_received:.2f}/{total_price:.2f}",
        'is_paid': total_received >= total_price if total_price > 0 else False
    }


def auto_match_by_payer_name(transaction_id=None, threshold=0.8):
    """自动匹配：根据付款方名称匹配客户

    Args:
        transaction_id: 指定流水ID（None则匹配所有未匹配流水）
        threshold: 名称相似度阈值

    Returns:
        (matched_count, errors)
    """
    matched_count = 0
    errors = []

    from Sills.db_bank_transaction import get_unmatched_transactions

    if transaction_id:
        # 匹配指定流水
        transactions = [get_transaction_by_id(transaction_id)]
        if not transactions[0]:
            return 0, ["流水不存在"]
    else:
        # 匹配所有未匹配流水
        transactions = get_unmatched_transactions(limit=100)

    with get_db_connection() as conn:
        for tx in transactions:
            payer_name = tx.get('payer_name', '')
            if not payer_name:
                continue

            # 查找名称相似的客户订单
            # 简单匹配：付款方名称包含客户名或客户名包含付款方名称
            rows = conn.execute("""
                SELECT m.manager_id, m.customer_order_no, c.cli_name, m.total_price_rmb, m.paid_amount
                FROM uni_order_manager m
                JOIN uni_cli c ON m.cli_id = c.cli_id
                WHERE c.cli_name LIKE ? OR ? LIKE '%' || c.cli_name || '%'
                ORDER BY m.order_date DESC
                LIMIT 5
            """, (f"%{payer_name}%", payer_name)).fetchall()

            if not rows:
                continue

            # 取第一个匹配的订单（金额相近优先）
            best_match = None
            tx_amount = float(tx['transaction_amount'])

            for row in rows:
                total_price = float(row['total_price_rmb'] or 0)
                paid_amount = float(row['paid_amount'] or 0)
                remaining = total_price - paid_amount

                # 金额匹配度判断
                if abs(tx_amount - remaining) < tx_amount * 0.1:  # 误差10%以内
                    best_match = dict(row)
                    break

            if not best_match:
                best_match = dict(rows[0])

            # 创建关联
            success, result = create_ledger(
                transaction_id=tx['transaction_id'],
                manager_id=best_match['manager_id'],
                allocation_amount=tx_amount,
                is_primary=0,  # 自动匹配不设为primary
                match_type='auto'
            )

            if success:
                matched_count += 1
            else:
                errors.append(f"{tx['transaction_id']}: {result}")

    return matched_count, errors


def get_transaction_by_id(transaction_id):
    """获取流水详情（内部引用）"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM uni_bank_transaction WHERE transaction_id = ?",
            (transaction_id,)
        ).fetchone()
        if row:
            return dict(row)
        return None