import sqlite3
import os
from functools import lru_cache
from datetime import datetime
import threading
import gc

# 数据库路径
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uni_platform.db")

# 线程本地存储用于连接池
_local = threading.local()

# 全局连接追踪
_active_connections = set()
_connection_lock = threading.Lock()

# 连接池配置
POOL_SIZE = 10
POOL_TIMEOUT = 5.0

# SQLite PRAGMA 优化配置
PRAGMA_OPTIMIZATIONS = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;
PRAGMA temp_store = MEMORY;
PRAGMA busy_timeout = 5000;
PRAGMA foreign_keys = ON;
"""


def get_db_path():
    return DB_PATH


def get_db_connection():
    """获取数据库连接，使用 WAL 模式和优化配置"""
    conn = sqlite3.connect(get_db_path(), timeout=POOL_TIMEOUT, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(PRAGMA_OPTIMIZATIONS)
    # 追踪连接
    with _connection_lock:
        _active_connections.add(conn)
    return conn


def get_cached_connection():
    """获取线程本地连接（用于同一请求内复用）"""
    if not hasattr(_local, 'conn') or _local.conn is None:
        _local.conn = get_db_connection()
    return _local.conn


def release_cached_connection():
    """释放线程本地连接"""
    if hasattr(_local, 'conn') and _local.conn is not None:
        _local.conn.close()
        _local.conn = None


class DbContext:
    """数据库上下文管理器，支持事务批处理"""

    def __init__(self, autocommit=True):
        self.autocommit = autocommit
        self.conn = None

    def __enter__(self):
        self.conn = get_db_connection()
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None and self.autocommit:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()


def batch_execute(conn, sql, params_list):
    """批量执行 SQL，使用 executemany 提升性能"""
    conn.executemany(sql, params_list)


@lru_cache(maxsize=100)
def get_cached_rate(currency_code):
    """缓存汇率查询结果"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT exchange_rate FROM uni_daily WHERE currency_code=? ORDER BY record_date DESC LIMIT 1",
            (currency_code,)
        ).fetchone()
        return float(row[0]) if row else (180.0 if currency_code == 2 else 7.0)


def get_exchange_rates():
    """获取最新汇率，使用缓存"""
    try:
        return get_cached_rate(2), get_cached_rate(1)
    except:
        return 180.0, 7.0


def clear_cache():
    """清除所有缓存"""
    get_cached_rate.cache_clear()


def close_all_connections():
    """关闭所有活跃的数据库连接"""
    with _connection_lock:
        connections = list(_active_connections)
        _active_connections.clear()

    for conn in connections:
        try:
            conn.close()
        except:
            pass

    # 强制垃圾回收
    gc.collect()
    print(f"[DB] 已关闭 {len(connections)} 个数据库连接")


def init_db():
    schema = """
    CREATE TABLE IF NOT EXISTS uni_daily (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        record_date TEXT NOT NULL,
        currency_code INTEGER NOT NULL,
        exchange_rate REAL NOT NULL,
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        UNIQUE(record_date, currency_code)
    );

    CREATE TABLE IF NOT EXISTS uni_emp (
        emp_id TEXT PRIMARY KEY CHECK(length(emp_id) = 3),
        department TEXT,
        position TEXT,
        emp_name TEXT NOT NULL,
        contact TEXT,
        account TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        hire_date TEXT,
        rule TEXT NOT NULL,
        remark TEXT,
        created_at DATETIME DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS uni_cli (
        cli_id TEXT PRIMARY KEY,
        cli_name TEXT NOT NULL,
        cli_full_name TEXT,
        cli_name_en TEXT,
        contact_name TEXT,
        address TEXT,
        region TEXT NOT NULL DEFAULT '韩国',
        credit_level TEXT DEFAULT 'A',
        margin_rate REAL DEFAULT 10.0,
        emp_id TEXT NOT NULL,
        website TEXT,
        payment_terms TEXT,
        email TEXT,
        phone TEXT,
        remark TEXT,
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (emp_id) REFERENCES uni_emp(emp_id) ON UPDATE CASCADE
    );

    CREATE TABLE IF NOT EXISTS uni_quote (
        quote_id TEXT PRIMARY KEY,
        quote_date TEXT,
        cli_id TEXT NOT NULL,
        inquiry_mpn TEXT NOT NULL,
        quoted_mpn TEXT,
        inquiry_brand TEXT,
        inquiry_qty INTEGER,
        target_price_rmb REAL,
        cost_price_rmb REAL,
        date_code TEXT,
        delivery_date TEXT,
        status TEXT DEFAULT '询价中',
        remark TEXT,
        is_transferred TEXT DEFAULT '未转',
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (cli_id) REFERENCES uni_cli(cli_id) ON UPDATE CASCADE
    );


    CREATE TABLE IF NOT EXISTS uni_vendor (
        vendor_id TEXT PRIMARY KEY,
        vendor_name TEXT NOT NULL,
        address TEXT,
        qq TEXT,
        wechat TEXT,
        email TEXT,
        remark TEXT,
        created_at DATETIME DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS uni_offer (
        offer_id TEXT PRIMARY KEY,
        offer_date TEXT,
        quote_id TEXT,
        inquiry_mpn TEXT,
        quoted_mpn TEXT,
        inquiry_brand TEXT,
        quoted_brand TEXT,
        inquiry_qty INTEGER,
        actual_qty INTEGER,
        quoted_qty INTEGER,
        cost_price_rmb REAL,
        offer_price_rmb REAL,
        price_kwr REAL,
        price_usd REAL,
        platform TEXT,
        vendor_id TEXT,
        date_code TEXT,
        delivery_date TEXT,
        emp_id TEXT NOT NULL,
        offer_statement TEXT,
        remark TEXT,
        is_transferred TEXT DEFAULT '未转',
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (quote_id) REFERENCES uni_quote(quote_id),
        FOREIGN KEY (vendor_id) REFERENCES uni_vendor(vendor_id),
        FOREIGN KEY (emp_id) REFERENCES uni_emp(emp_id),
        UNIQUE(quote_id)
    );

    CREATE TABLE IF NOT EXISTS uni_order (
        order_id TEXT PRIMARY KEY,
        order_no TEXT UNIQUE,
        order_date TEXT,
        cli_id TEXT NOT NULL,
        offer_id TEXT,
        inquiry_mpn TEXT,
        inquiry_brand TEXT,
        price_rmb REAL,
        price_kwr REAL,
        price_usd REAL,
        cost_price_rmb REAL,
        is_finished INTEGER DEFAULT 0 CHECK(is_finished IN (0,1)),
        is_paid INTEGER DEFAULT 0 CHECK(is_paid IN (0,1)),
        paid_amount REAL DEFAULT 0.0,
        return_status TEXT DEFAULT '正常',
        remark TEXT,
        is_transferred TEXT DEFAULT '未转',
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (cli_id) REFERENCES uni_cli(cli_id),
        FOREIGN KEY (offer_id) REFERENCES uni_offer(offer_id)
    );

    CREATE TABLE IF NOT EXISTS uni_buy (
        buy_id TEXT PRIMARY KEY,
        buy_date TEXT,
        order_id TEXT,
        vendor_id TEXT,
        buy_mpn TEXT,
        buy_brand TEXT,
        buy_price_rmb REAL,
        buy_qty INTEGER,
        sales_price_rmb REAL,
        total_amount REAL,
        is_source_confirmed INTEGER DEFAULT 0 CHECK(is_source_confirmed IN (0,1)),
        is_ordered INTEGER DEFAULT 0 CHECK(is_ordered IN (0,1)),
        is_instock INTEGER DEFAULT 0 CHECK(is_instock IN (0,1)),
        is_shipped INTEGER DEFAULT 0 CHECK(is_shipped IN (0,1)),
        remark TEXT,
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (order_id) REFERENCES uni_order(order_id),
        FOREIGN KEY (vendor_id) REFERENCES uni_vendor(vendor_id)
    );

    -- 性能优化索引
    CREATE INDEX IF NOT EXISTS idx_cli_name ON uni_cli(cli_name);
    CREATE INDEX IF NOT EXISTS idx_cli_emp ON uni_cli(emp_id);

    CREATE INDEX IF NOT EXISTS idx_quote_date ON uni_quote(quote_date);
    CREATE INDEX IF NOT EXISTS idx_quote_cli ON uni_quote(cli_id);
    CREATE INDEX IF NOT EXISTS idx_quote_transferred ON uni_quote(is_transferred);

    CREATE INDEX IF NOT EXISTS idx_offer_date ON uni_offer(offer_date);
    CREATE INDEX IF NOT EXISTS idx_offer_quote ON uni_offer(quote_id);
    CREATE INDEX IF NOT EXISTS idx_offer_vendor ON uni_offer(vendor_id);
    CREATE INDEX IF NOT EXISTS idx_offer_transferred ON uni_offer(is_transferred);

    CREATE INDEX IF NOT EXISTS idx_order_date ON uni_order(order_date);
    CREATE INDEX IF NOT EXISTS idx_order_cli ON uni_order(cli_id);
    CREATE INDEX IF NOT EXISTS idx_order_offer ON uni_order(offer_id);
    CREATE INDEX IF NOT EXISTS idx_order_transferred ON uni_order(is_transferred);

    CREATE INDEX IF NOT EXISTS idx_buy_date ON uni_buy(buy_date);
    CREATE INDEX IF NOT EXISTS idx_buy_order ON uni_buy(order_id);
    CREATE INDEX IF NOT EXISTS idx_buy_vendor ON uni_buy(vendor_id);

    CREATE INDEX IF NOT EXISTS idx_daily_date ON uni_daily(record_date);
    CREATE INDEX IF NOT EXISTS idx_daily_currency ON uni_daily(currency_code);

    CREATE INDEX IF NOT EXISTS idx_emp_account ON uni_emp(account);
    CREATE INDEX IF NOT EXISTS idx_emp_rule ON uni_emp(rule);
    """

    with get_db_connection() as conn:
        conn.executescript(schema)
        conn.execute("""
            INSERT OR IGNORE INTO uni_emp (emp_id, emp_name, account, password, rule)
            VALUES ('000', '超级管理员', 'Admin', '088426ba2d6e02949f54ef1e62a2aa73', '3')
        """)
        conn.commit()
    # 初始化后清除缓存
    clear_cache()


def get_paginated_list(table_name, page=1, page_size=10, search_kwargs=None):
    """
    Generic pagination and fuzzy search
    search_kwargs: {column_name: value}
    """
    offset = (page - 1) * page_size
    query = f"SELECT * FROM {table_name}"
    params = []

    if search_kwargs:
        conditions = []
        for col, val in search_kwargs.items():
            conditions.append(f"{col} LIKE ?")
            params.append(f"%{val}%")
        query += " WHERE " + " AND ".join(conditions)

    count_query = f"SELECT COUNT(*) FROM ({query})"
    query += f" ORDER BY created_at DESC LIMIT {page_size} OFFSET {offset}"

    with get_db_connection() as conn:
        total_count = conn.execute(count_query, params).fetchone()[0]
        items = conn.execute(query, params).fetchall()

    results = [
        {k: ("" if v is None else v) for k, v in dict(row).items()}
        for row in items
    ]

    return {
        "items": results,
        "total_count": total_count,
        "page": page,
        "page_size": page_size,
        "total_pages": (total_count + page_size - 1) // page_size
    }


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully.")