"""
OpenClaw Bridge Layer - 为 openclaw_skills 提供统一的数据库操作接口

使用方法:
  import sys
  sys.path.insert(0, os.environ.get('UNIULTRA_PROJECT_ROOT', '.'))
  from openclaw_bridge import get_quote_list, add_quote, DB_PATH

环境变量:
  UNIULTRA_PROJECT_ROOT - 项目根目录 (默认: 自动检测)
  UNIULTRA_DB_PATH - 数据库路径 (默认: {PROJECT_ROOT}/uni_platform.db)
  UNIULTRA_OUTPUT_DIR - 输出目录 (默认: {PROJECT_ROOT}/output)
"""

import os
import sys

# ============================================================
# 路径配置 - 全部通过环境变量
# ============================================================
PROJECT_ROOT = os.environ.get('UNIULTRA_PROJECT_ROOT',
    os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get('UNIULTRA_DB_PATH',
    os.path.join(PROJECT_ROOT, 'uni_platform.db'))
OUTPUT_DIR = os.environ.get('UNIULTRA_OUTPUT_DIR',
    os.path.join(PROJECT_ROOT, 'output'))

# 添加项目路径到 sys.path (用于导入 Sills)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ============================================================
# 导入 Sills 层
# ============================================================
from Sills.base import get_db_connection, get_exchange_rates, clear_cache
from Sills.db_quote import get_quote_list, add_quote, update_quote, delete_quote
from Sills.db_offer import get_offer_list, add_offer, update_offer, delete_offer
from Sills.db_order import get_order_list, add_order, update_order, delete_order
from Sills.db_cli import get_cli_list, add_cli, update_cli, delete_cli
from Sills.db_vendor import add_vendor, update_vendor, delete_vendor
from Sills.db_buy import get_buy_list, add_buy, update_buy, delete_buy
from Sills.db_daily import get_daily_list, add_daily, update_daily
from Sills.db_emp import get_emp_list, verify_login

# ============================================================
# 扩展函数 - Skills 特有的操作
# ============================================================

def get_cli_id_by_name(cli_name):
    """根据客户名称模糊查找客户ID"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT cli_id FROM uni_cli WHERE cli_name LIKE ? LIMIT 1",
            (f"%{cli_name}%",)
        ).fetchone()
        return row['cli_id'] if row else None

def get_quote_by_id(quote_id):
    """根据ID获取询价记录详情"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM uni_quote WHERE quote_id = ?", (quote_id,)
        ).fetchone()
        return dict(row) if row else None

def get_offer_by_id(offer_id):
    """根据ID获取报价记录详情"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM uni_offer WHERE offer_id = ?", (offer_id,)
        ).fetchone()
        return dict(row) if row else None

def get_order_by_id(order_id):
    """根据ID获取订单详情（含客户信息）"""
    with get_db_connection() as conn:
        row = conn.execute("""
            SELECT o.*, c.cli_name, c.cli_name_en, c.contact_name,
                   c.address, c.email, c.phone, c.cli_full_name, c.region
            FROM uni_order o
            LEFT JOIN uni_cli c ON o.cli_id = c.cli_id
            WHERE o.order_id = ?
        """, (order_id,)).fetchone()
        return dict(row) if row else None

def get_orders_for_ci(order_ids):
    """获取订单列表（用于生成CI文档）"""
    if not order_ids:
        return []
    placeholders = ','.join(['?'] * len(order_ids))
    with get_db_connection() as conn:
        rows = conn.execute(f"""
            SELECT o.order_id, o.order_no, o.order_date, o.cli_id,
                   o.inquiry_mpn, o.inquiry_brand, o.price_rmb, o.price_kwr, o.price_usd,
                   o.offer_id, o.cost_price_rmb,
                   c.cli_name, c.cli_name_en, c.contact_name, c.address, c.email, c.phone,
                   c.cli_full_name, c.region,
                   off.quoted_qty, off.date_code, off.delivery_date, off.inquiry_qty
            FROM uni_order o
            LEFT JOIN uni_cli c ON o.cli_id = c.cli_id
            LEFT JOIN uni_offer off ON o.offer_id = off.offer_id
            WHERE o.order_id IN ({placeholders})
            ORDER BY o.order_id
        """, order_ids).fetchall()
        return [dict(r) for r in rows]

def mark_offer_transferred(offer_id):
    """标记报价已转订单"""
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE uni_offer SET is_transferred = '已转' WHERE offer_id = ?",
            (offer_id,)
        )
        conn.commit()

def mark_quote_transferred(quote_id):
    """标记询价已转报价"""
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE uni_quote SET is_transferred = '已转', status = '已报价' WHERE quote_id = ?",
            (quote_id,)
        )
        conn.commit()

# ============================================================
# 暴露统一接口
# ============================================================
__all__ = [
    # 路径常量
    'PROJECT_ROOT', 'DB_PATH', 'OUTPUT_DIR',
    # 数据库连接
    'get_db_connection', 'get_exchange_rates', 'clear_cache',
    # 询价操作
    'get_quote_list', 'add_quote', 'update_quote', 'delete_quote',
    'get_quote_by_id', 'mark_quote_transferred',
    # 报价操作
    'get_offer_list', 'add_offer', 'update_offer', 'delete_offer',
    'get_offer_by_id', 'mark_offer_transferred',
    # 订单操作
    'get_order_list', 'add_order', 'update_order', 'delete_order',
    'get_order_by_id', 'get_orders_for_ci',
    # 客户操作
    'get_cli_list', 'add_cli', 'update_cli', 'delete_cli',
    'get_cli_id_by_name',
    # 供应商操作
    'add_vendor', 'update_vendor', 'delete_vendor',
    # 采购操作
    'get_buy_list', 'add_buy', 'update_buy', 'delete_buy',
    # 汇率操作
    'get_daily_list', 'add_daily', 'update_daily',
    # 员工操作
    'get_emp_list', 'verify_login',
]