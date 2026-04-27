import sqlite3
import os
import platform
from functools import lru_cache
from datetime import datetime
import threading
import gc

# 导入数据库配置
from Sills.db_config import DATABASE_TYPE, SQLITE_PATH, PG_CONFIG, is_postgresql, is_sqlite

# 数据库路径（兼容旧代码）
DB_PATH = SQLITE_PATH

# 线程本地存储用于连接池
_local = threading.local()

# 全局连接追踪
_active_connections = set()
_connection_lock = threading.Lock()

# 连接池配置
POOL_SIZE = 10
POOL_TIMEOUT = 5.0

# PostgreSQL 连接池（延迟初始化）
_pg_pool = None


def _init_pg_pool():
    """初始化 PostgreSQL 连接池"""
    global _pg_pool
    if _pg_pool is None and is_postgresql():
        try:
            import psycopg
            from psycopg_pool import ConnectionPool
            # psycopg3 使用 dbname 而不是 database
            pg_config = PG_CONFIG.copy()
            pg_config['dbname'] = pg_config.pop('database')
            _pg_pool = ConnectionPool(
                min_size=1,
                max_size=POOL_SIZE,
                kwargs=pg_config
            )
            print(f"[DB] PostgreSQL 连接池已初始化: {PG_CONFIG['host']}:{PG_CONFIG['port']}/{PG_CONFIG['database']}")
        except Exception as e:
            print(f"[DB] PostgreSQL 连接池初始化失败: {e}")
            raise
    return _pg_pool


def _is_wsl_windows_path(db_path):
    """
    检测是否在 WSL 中访问 Windows 文件系统
    WSL 通过 9P 协议访问 Windows 盘，不完全支持 SQLite WAL 的文件锁定
    """
    # 检查是否在 WSL 环境中
    if platform.system() == 'Linux':
        try:
            # 检查 /proc/version 是否包含 microsoft 或 wsl
            with open('/proc/version', 'r') as f:
                version_info = f.read().lower()
                if 'microsoft' in version_info or 'wsl' in version_info:
                    # WSL 环境，检查路径是否是 Windows 挂载点
                    abs_path = os.path.abspath(db_path)
                    if abs_path.startswith('/mnt/'):
                        return True
        except (FileNotFoundError, PermissionError):
            pass
    return False


def _is_wsl_environment():
    """检测是否在 WSL 环境中（无论路径在哪里）"""
    if platform.system() == 'Linux':
        try:
            with open('/proc/version', 'r') as f:
                version_info = f.read().lower()
                if 'microsoft' in version_info or 'wsl' in version_info:
                    return True
        except (FileNotFoundError, PermissionError):
            pass
    return False


def _get_journal_mode():
    """根据运行环境选择合适的 journal 模式"""
    # WSL 环境统一使用 DELETE 模式，避免多进程并发 I/O 错误
    if _is_wsl_environment():
        print("[DB] 检测到 WSL 环境，使用 DELETE 模式以避免 I/O 错误")
        return "DELETE"
    return "WAL"


def _get_busy_timeout():
    """根据运行环境选择合适的 busy_timeout"""
    # WSL 环境需要更长的超时时间
    if _is_wsl_environment():
        return 30000  # 30秒
    return 5000  # 5秒


# 动态生成 PRAGMA 配置
JOURNAL_MODE = _get_journal_mode()
BUSY_TIMEOUT = _get_busy_timeout()

PRAGMA_OPTIMIZATIONS = f"""
PRAGMA journal_mode = {JOURNAL_MODE};
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;
PRAGMA temp_store = MEMORY;
PRAGMA busy_timeout = {BUSY_TIMEOUT};
PRAGMA foreign_keys = ON;
"""


def get_db_path():
    return DB_PATH


def get_db_connection():
    """获取数据库连接，支持 SQLite 和 PostgreSQL"""
    if is_postgresql():
        # PostgreSQL 模式 - psycopg3
        pool = _init_pg_pool()
        # psycopg3 ConnectionPool 使用 pool.connection() 返回连接上下文管理器
        conn_ctx = pool.connection()
        conn = conn_ctx.__enter__()
        # 追踪连接
        with _connection_lock:
            _active_connections.add(conn)
        return _PgConnectionWrapper(conn, pool, conn_ctx)
    else:
        # SQLite 模式
        conn = sqlite3.connect(get_db_path(), timeout=POOL_TIMEOUT, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.executescript(PRAGMA_OPTIMIZATIONS)
        # 追踪连接
        with _connection_lock:
            _active_connections.add(conn)
        return conn


class _DictCursorWrapper:
    """游标包装器，同时支持数字索引和列名访问"""
    def __init__(self, cursor):
        self._cursor = cursor
        self._columns = None

    def _get_columns(self):
        if self._columns is None and self._cursor.description:
            # psycopg3: desc.name 属性; SQLite/psycopg2: desc[0] 索引
            self._columns = []
            for desc in self._cursor.description:
                if hasattr(desc, 'name'):
                    # psycopg3 Column 对象
                    self._columns.append(desc.name)
                else:
                    # SQLite/psycopg2 元组
                    self._columns.append(desc[0])
        return self._columns

    def _wrap_row(self, row):
        """包装单行数据，支持数字索引和列名访问"""
        if row is None:
            return None

        columns = self._get_columns()

        # 获取值列表
        if isinstance(row, dict):
            values = list(row.values())
            data = row.copy()
        elif isinstance(row, (tuple, list)):
            values = list(row)
            data = {columns[i]: row[i] for i in range(len(columns))} if columns else {}
        else:
            return row

        # 创建支持双重访问的 Row 对象
        class _Row(dict):
            def __init__(inner_self, d, vals):
                super().__init__(d)
                inner_self._values = vals

            def __getitem__(inner_self, key):
                if isinstance(key, int):
                    if 0 <= key < len(inner_self._values):
                        return inner_self._values[key]
                    raise IndexError(f"index {key} out of range")
                return super().__getitem__(key)

        return _Row(data, values)

    def fetchone(self):
        row = self._cursor.fetchone()
        return self._wrap_row(row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [self._wrap_row(r) for r in rows] if rows else []

    def fetchmany(self, size=None):
        rows = self._cursor.fetchmany(size) if size else self._cursor.fetchmany()
        return [self._wrap_row(r) for r in rows] if rows else []

    def __getattr__(self, name):
        # PostgreSQL 没有 lastrowid，需要特殊处理
        if name == 'lastrowid':
            # 尝试从最后一次 INSERT 获取 ID
            # 如果有 RETURNING id 的结果，使用它
            if hasattr(self._cursor, 'description') and self._cursor.description:
                # 如果是 RETURNING 结果，取第一行第一列
                try:
                    row = self._cursor.fetchone()
                    if row:
                        return row[0] if isinstance(row, (tuple, list)) else row.get('id', row.get(0))
                except:
                    pass
            return None
        return getattr(self._cursor, name)


class _PgConnectionWrapper:
    """PostgreSQL 连接包装器，模拟 SQLite 接口"""

    def __init__(self, conn, pool, conn_ctx=None):
        self._conn = conn
        self._pool = pool
        self._conn_ctx = conn_ctx  # psycopg3 连接上下文管理器

    def execute(self, sql, params=None):
        """执行 SQL，自动转换占位符和 SQLite 函数"""
        import re

        # 将 ? 占位符转换为 %s
        pg_sql = sql.replace('?', '%s')

        # 转换 SQLite 特有函数为 PostgreSQL 兼容
        # IFNULL -> COALESCE
        pg_sql = pg_sql.replace('IFNULL', 'COALESCE')

        # datetime('now', 'localtime') -> NOW()
        pg_sql = pg_sql.replace("datetime('now', 'localtime')", 'NOW()')
        pg_sql = pg_sql.replace('datetime("now", "localtime")', 'NOW()')

        # GROUP_CONCAT(col ORDER BY x) -> STRING_AGG(col::text, ',' ORDER BY x)
        # 匹配 GROUP_CONCAT(字段 [ORDER BY ...])
        def replace_group_concat(match):
            content = match.group(1)
            # 检查是否有 ORDER BY
            order_match = re.search(r'\s+ORDER\s+BY\s+(.+)$', content, re.IGNORECASE)
            if order_match:
                col = content[:order_match.start()].strip()
                order_by = order_match.group(1)
                return f"STRING_AGG({col}::text, ',' ORDER BY {order_by})"
            else:
                return f"STRING_AGG({content}::text, ',')"

        pg_sql = re.sub(r'GROUP_CONCAT\(([^)]+)\)', replace_group_concat, pg_sql, flags=re.IGNORECASE)

        cur = self._conn.cursor()
        if params:
            cur.execute(pg_sql, params)
        else:
            cur.execute(pg_sql)
        return _DictCursorWrapper(cur)

    def executescript(self, script):
        """执行脚本（PostgreSQL 不需要 PRAGMA）"""
        # 忽略 PRAGMA 语句
        pass

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        """归还连接到池"""
        with _connection_lock:
            _active_connections.discard(self._conn)
        if self._conn_ctx:
            # psycopg3 使用上下文管理器
            self._conn_ctx.__exit__(None, None, None)
        else:
            # psycopg2 兼容
            self._pool.putconn(self._conn)

    def cursor(self):
        return self._conn.cursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()
        return False


class ConnectionContext:
    """自动关闭连接的上下文管理器"""

    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            with _connection_lock:
                _active_connections.discard(self.conn)
            self.conn.close()
        return False  # 不抑制异常


def get_db_connection_auto_close():
    """获取自动关闭的数据库连接（用于 with 语句）"""
    return ConnectionContext(get_db_connection())


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
        # 从追踪集合中移除并关闭连接
        with _connection_lock:
            _active_connections.discard(self.conn)
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
    """获取最新汇率，使用缓存（返回KRW, USD, JPY）"""
    try:
        return get_cached_rate(2), get_cached_rate(1), get_cached_rate(3)
    except:
        return 180.0, 7.0, 20.0  # 默认值：KRW=180, USD=7, JPY=20


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
    """初始化数据库，支持 SQLite 和 PostgreSQL"""
    if is_postgresql():
        _init_db_postgresql()
    else:
        _init_db_sqlite()


def _init_db_postgresql():
    """初始化 PostgreSQL 数据库"""
    from Sills.pg_schema import PG_SCHEMA, PG_DEFAULT_ADMIN

    with get_db_connection() as conn:
        cur = conn.cursor()

        # 迁移：uni_cli 表添加营销字段
        try:
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'uni_cli' AND column_name = 'domain'
            """)
            if not cur.fetchone():
                cur.execute("""
                    ALTER TABLE uni_cli
                    ADD COLUMN domain TEXT,
                    ADD COLUMN is_contacted INTEGER DEFAULT 0,
                    ADD COLUMN has_inquiry INTEGER DEFAULT 0,
                    ADD COLUMN has_order INTEGER DEFAULT 0
                """)
                print("[DB] 迁移：uni_cli 表已添加营销字段 (domain, is_contacted, has_inquiry, has_order)")
        except Exception as e:
            conn.rollback()
            print(f"[DB] uni_cli 营销字段迁移: {e}")

        # 迁移：uni_cli 表添加 send_mail 字段
        try:
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'uni_cli' AND column_name = 'send_mail'
            """)
            if not cur.fetchone():
                cur.execute("ALTER TABLE uni_cli ADD COLUMN send_mail TEXT")
                print("[DB] 迁移：uni_cli 表已添加 send_mail 字段")
        except Exception as e:
            conn.rollback()
            print(f"[DB] uni_cli send_mail 字段迁移: {e}")

        # 迁移：uni_order_manager_rel 表从 order_id 改为 offer_id
        try:
            # 检查是否存在 order_id 列
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'uni_order_manager_rel' AND column_name = 'order_id'
            """)
            if cur.fetchone():
                # 删除旧表并重建
                cur.execute("DROP TABLE IF EXISTS uni_order_manager_rel CASCADE")
                print("[DB] 迁移：uni_order_manager_rel 表已删除，将重建为关联报价订单")
        except Exception as e:
            conn.rollback()
            print(f"[DB] 迁移检查: {e}")

        # 迁移：uni_mail 表添加新字段（邮件分类、同步优化等功能）
        mail_columns_to_add = [
            ("mail_type", "INTEGER DEFAULT 0"),
            ("original_recipient", "TEXT"),
            ("is_sent", "INTEGER DEFAULT 0"),
            ("is_read", "INTEGER DEFAULT 0"),
            ("is_deleted", "INTEGER DEFAULT 0"),
            ("deleted_at", "TIMESTAMP"),
            ("is_draft", "INTEGER DEFAULT 0"),
            ("is_blacklisted", "INTEGER DEFAULT 0"),
            ("imap_uid", "INTEGER"),
            ("imap_folder", "TEXT"),
            ("account_id", "INTEGER"),
            ("cc_addr", "TEXT"),
            ("from_name", "TEXT"),
            ("folder_id", "INTEGER"),
            ("sync_status", "TEXT DEFAULT 'completed'"),
            ("sync_error", "TEXT"),
        ]
        for col_name, col_def in mail_columns_to_add:
            try:
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'uni_mail' AND column_name = %s
                """, (col_name,))
                if not cur.fetchone():
                    cur.execute(f"ALTER TABLE uni_mail ADD COLUMN {col_name} {col_def}")
                    print(f"[DB] 迁移：uni_mail 添加 {col_name} 列")
            except Exception as e:
                conn.rollback()
                print(f"[DB] uni_mail {col_name} 列迁移: {e}")

        # 迁移：uni_offer 表添加 status 和 target_price_rmb 列（合并需求管理功能）
        offer_columns_to_add = [
            ("status", "TEXT DEFAULT '询价中'"),
            ("target_price_rmb", "DOUBLE PRECISION"),
            ("cli_id", "TEXT REFERENCES uni_cli(cli_id)"),
        ]
        for col_name, col_def in offer_columns_to_add:
            try:
                cur.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'uni_offer' AND column_name = %s
                """, (col_name,))
                if not cur.fetchone():
                    cur.execute(f"ALTER TABLE uni_offer ADD COLUMN {col_name} {col_def}")
                    print(f"[DB] 迁移：uni_offer 添加 {col_name} 列")
            except Exception as e:
                conn.rollback()
                print(f"[DB] uni_offer {col_name} 列迁移: {e}")

        # 迁移：uni_offer 表添加约束（如果列已存在但约束不存在）
        try:
            cur.execute("""
                SELECT constraint_name FROM information_schema.table_constraints
                WHERE table_name = 'uni_mail' AND constraint_type = 'CHECK'
            """)
            existing_checks = {row[0] for row in cur.fetchall()}
            checks_to_add = [
                ("chk_is_sent", "is_sent IN (0,1)"),
                ("chk_is_read", "is_read IN (0,1)"),
                ("chk_is_deleted", "is_deleted IN (0,1)"),
                ("chk_is_draft", "is_draft IN (0,1)"),
                ("chk_is_blacklisted", "is_blacklisted IN (0,1)"),
                ("chk_mail_type", "mail_type IN (0,1,2,3,4)"),
            ]
            for constraint_name, check_def in checks_to_add:
                if constraint_name not in existing_checks:
                    try:
                        cur.execute(f"ALTER TABLE uni_mail ADD CONSTRAINT {constraint_name} CHECK ({check_def})")
                        print(f"[DB] 迁移：uni_mail 添加约束 {constraint_name}")
                    except Exception:
                        pass  # 约束可能已存在或有其他问题
        except Exception as e:
            conn.rollback()
            print(f"[DB] uni_mail 约束检查: {e}")

        # 清除事务状态，确保后续操作在新事务中执行
        try:
            conn.commit()
        except:
            conn.rollback()
            conn.commit()

        # 执行 schema
        cur.execute(PG_SCHEMA)
        # 插入默认管理员
        cur.execute(PG_DEFAULT_ADMIN)
        conn.commit()
    print("[DB] PostgreSQL 数据库初始化完成")
    clear_cache()


def _init_db_sqlite():
    """初始化 SQLite 数据库"""
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
        cli_id TEXT,
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
        price_jpy REAL,                          -- 日元报价
        platform TEXT,
        vendor_id TEXT,
        date_code TEXT,
        delivery_date TEXT,
        emp_id TEXT NOT NULL,
        offer_statement TEXT,
        remark TEXT,
        status TEXT DEFAULT '询价中',
        target_price_rmb REAL,
        is_transferred TEXT DEFAULT '未转',
        manager_id TEXT,
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (vendor_id) REFERENCES uni_vendor(vendor_id),
        FOREIGN KEY (emp_id) REFERENCES uni_emp(emp_id),
        FOREIGN KEY (cli_id) REFERENCES uni_cli(cli_id),
        FOREIGN KEY (manager_id) REFERENCES uni_order_manager(manager_id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS uni_order (
        order_id TEXT PRIMARY KEY,
        order_no TEXT,
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

    -- 客户订单主表
    CREATE TABLE IF NOT EXISTS uni_order_manager (
        manager_id TEXT PRIMARY KEY,
        customer_order_no TEXT UNIQUE NOT NULL,
        order_date TEXT NOT NULL,
        cli_id TEXT NOT NULL,
        transaction_code TEXT,                     -- 交易编码（用于关联银行流水）
        total_cost_rmb REAL DEFAULT 0,
        total_price_rmb REAL DEFAULT 0,
        total_price_kwr REAL DEFAULT 0,
        total_price_usd REAL DEFAULT 0,
        profit_rmb REAL DEFAULT 0,
        model_count INTEGER DEFAULT 0,
        total_qty INTEGER DEFAULT 0,
        is_paid INTEGER DEFAULT 0 CHECK(is_paid IN (0,1)),
        is_finished INTEGER DEFAULT 0 CHECK(is_finished IN (0,1)),
        paid_amount REAL DEFAULT 0,
        shipping_fee REAL DEFAULT 0,
        tracking_no TEXT,
        query_link TEXT,
        mail_id TEXT,
        mail_notes TEXT,
        remark TEXT,
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (cli_id) REFERENCES uni_cli(cli_id) ON UPDATE CASCADE
    );

    -- 客户订单与报价订单关联表（原销售订单关联表已迁移）
    CREATE TABLE IF NOT EXISTS uni_order_manager_rel (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        manager_id TEXT NOT NULL,
        offer_id TEXT NOT NULL,
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (manager_id) REFERENCES uni_order_manager(manager_id) ON DELETE CASCADE,
        FOREIGN KEY (offer_id) REFERENCES uni_offer(offer_id) ON DELETE CASCADE,
        UNIQUE(manager_id, offer_id)
    );

    -- 客户订单附件表
    CREATE TABLE IF NOT EXISTS uni_order_attachment (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        manager_id TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_type TEXT NOT NULL,
        file_name TEXT,
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (manager_id) REFERENCES uni_order_manager(manager_id) ON DELETE CASCADE
    );

    -- 邮件系统配置表（必须在uni_mail之前创建）
    CREATE TABLE IF NOT EXISTS mail_config (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_name TEXT DEFAULT '默认账户',
        smtp_server TEXT,
        smtp_port INTEGER DEFAULT 587,
        imap_server TEXT,
        imap_port INTEGER DEFAULT 993,
        username TEXT,
        password TEXT,
        use_tls INTEGER DEFAULT 1,
        sync_batch_size INTEGER DEFAULT 100,
        sync_pause_seconds REAL DEFAULT 1.0,
        is_current INTEGER DEFAULT 0 CHECK(is_current IN (0,1)),
        created_at DATETIME DEFAULT (datetime('now', 'localtime'))
    );

    CREATE TABLE IF NOT EXISTS uni_mail (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT,
        from_addr TEXT NOT NULL,
        from_name TEXT,
        to_addr TEXT NOT NULL,
        cc_addr TEXT,
        content TEXT,
        html_content TEXT,
        received_at DATETIME,
        sent_at DATETIME,
        is_sent INTEGER DEFAULT 0,
        is_read INTEGER DEFAULT 0,
        is_deleted INTEGER DEFAULT 0,
        deleted_at DATETIME,
        message_id TEXT,
        imap_uid INTEGER,
        imap_folder TEXT,
        account_id INTEGER,
        folder_id INTEGER REFERENCES mail_folder(id) ON DELETE SET NULL,
        sync_status TEXT DEFAULT 'completed',
        sync_error TEXT,
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (account_id) REFERENCES mail_config(id) ON DELETE SET NULL
    );

    CREATE INDEX IF NOT EXISTS idx_mail_uid_folder ON uni_mail(imap_uid, imap_folder);

    CREATE TABLE IF NOT EXISTS uni_mail_rel (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mail_id INTEGER NOT NULL,
        ref_type TEXT NOT NULL,
        ref_id TEXT NOT NULL,
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (mail_id) REFERENCES uni_mail(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS mail_sync_lock (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        locked_at DATETIME,
        locked_by TEXT,
        expires_at DATETIME,
        progress_total INTEGER DEFAULT 0,
        progress_current INTEGER DEFAULT 0,
        progress_message TEXT DEFAULT '',
        sync_start_date TEXT,
        sync_end_date TEXT,
        total_emails INTEGER DEFAULT 0,
        synced_emails INTEGER DEFAULT 0
    );

    -- 全局设置表（存储同步间隔等系统配置）
    CREATE TABLE IF NOT EXISTS global_settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at DATETIME DEFAULT (datetime('now', 'localtime'))
    );

    -- 邮件文件夹表
    CREATE TABLE IF NOT EXISTS mail_folder (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        folder_name TEXT NOT NULL,
        folder_icon TEXT DEFAULT 'folder',
        sort_order INTEGER DEFAULT 0,
        account_id INTEGER,
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (account_id) REFERENCES mail_config(id) ON DELETE CASCADE
    );

    -- 邮件过滤规则表
    CREATE TABLE IF NOT EXISTS mail_filter_rule (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        folder_id INTEGER NOT NULL,
        keyword TEXT NOT NULL,
        priority INTEGER DEFAULT 0,
        is_enabled INTEGER DEFAULT 1 CHECK(is_enabled IN (0,1)),
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (folder_id) REFERENCES mail_folder(id) ON DELETE CASCADE
    );

    -- 邮件黑名单表
    CREATE TABLE IF NOT EXISTS mail_blacklist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email_addr TEXT NOT NULL UNIQUE,
        reason TEXT,
        account_id INTEGER,
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (account_id) REFERENCES mail_config(id) ON DELETE CASCADE
    );

    -- 已同步邮件UID记录表（用于区分"从未同步"和"已删除"）
    CREATE TABLE IF NOT EXISTS uni_mail_synced_uid (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        imap_uid INTEGER NOT NULL,
        imap_folder TEXT NOT NULL,
        synced_at DATETIME DEFAULT (datetime('now', 'localtime')),
        UNIQUE(account_id, imap_uid, imap_folder),
        FOREIGN KEY (account_id) REFERENCES mail_config(id) ON DELETE CASCADE
    );

    -- 文件夹同步进度表（记录每个文件夹最后同步的UID和时间）
    CREATE TABLE IF NOT EXISTS mail_folder_sync_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        folder_name TEXT NOT NULL,
        last_uid INTEGER DEFAULT 0,
        last_sync_at DATETIME,
        UNIQUE(account_id, folder_name),
        FOREIGN KEY (account_id) REFERENCES mail_config(id) ON DELETE CASCADE
    );

    -- 性能优化索引
    CREATE INDEX IF NOT EXISTS idx_cli_name ON uni_cli(cli_name);
    CREATE INDEX IF NOT EXISTS idx_cli_emp ON uni_cli(emp_id);

    CREATE INDEX IF NOT EXISTS idx_quote_date ON uni_quote(quote_date);
    CREATE INDEX IF NOT EXISTS idx_quote_cli ON uni_quote(cli_id);
    CREATE INDEX IF NOT EXISTS idx_quote_transferred ON uni_quote(is_transferred);

    CREATE INDEX IF NOT EXISTS idx_offer_date ON uni_offer(offer_date);
    CREATE INDEX IF NOT EXISTS idx_offer_vendor ON uni_offer(vendor_id);
    CREATE INDEX IF NOT EXISTS idx_offer_transferred ON uni_offer(is_transferred);
    CREATE INDEX IF NOT EXISTS idx_offer_status ON uni_offer(status);
    CREATE INDEX IF NOT EXISTS idx_offer_target_price ON uni_offer(target_price_rmb);

    CREATE INDEX IF NOT EXISTS idx_order_date ON uni_order(order_date);
    CREATE INDEX IF NOT EXISTS idx_order_cli ON uni_order(cli_id);
    CREATE INDEX IF NOT EXISTS idx_order_offer ON uni_order(offer_id);
    CREATE INDEX IF NOT EXISTS idx_order_transferred ON uni_order(is_transferred);

    CREATE INDEX IF NOT EXISTS idx_buy_date ON uni_buy(buy_date);
    CREATE INDEX IF NOT EXISTS idx_buy_order ON uni_buy(order_id);
    CREATE INDEX IF NOT EXISTS idx_buy_vendor ON uni_buy(vendor_id);

    -- 客户订单索引
    CREATE INDEX IF NOT EXISTS idx_order_manager_cli ON uni_order_manager(cli_id);
    CREATE INDEX IF NOT EXISTS idx_order_manager_date ON uni_order_manager(order_date);
    CREATE INDEX IF NOT EXISTS idx_order_manager_rel_manager ON uni_order_manager_rel(manager_id);
    CREATE INDEX IF NOT EXISTS idx_order_manager_rel_offer ON uni_order_manager_rel(offer_id);

    CREATE INDEX IF NOT EXISTS idx_daily_date ON uni_daily(record_date);
    CREATE INDEX IF NOT EXISTS idx_daily_currency ON uni_daily(currency_code);

    CREATE INDEX IF NOT EXISTS idx_emp_account ON uni_emp(account);
    CREATE INDEX IF NOT EXISTS idx_emp_rule ON uni_emp(rule);

    -- 邮件系统索引
    CREATE INDEX IF NOT EXISTS idx_mail_received ON uni_mail(received_at DESC);
    CREATE INDEX IF NOT EXISTS idx_mail_sent ON uni_mail(sent_at DESC);
    CREATE INDEX IF NOT EXISTS idx_mail_from ON uni_mail(from_addr);
    CREATE INDEX IF NOT EXISTS idx_mail_sync_status ON uni_mail(sync_status);
    CREATE INDEX IF NOT EXISTS idx_mail_account ON uni_mail(account_id);
    CREATE UNIQUE INDEX IF NOT EXISTS idx_mail_message_id ON uni_mail(message_id) WHERE message_id IS NOT NULL;
    CREATE INDEX IF NOT EXISTS idx_mail_rel_ref ON uni_mail_rel(ref_type, ref_id);

    -- 文件夹和规则索引
    CREATE INDEX IF NOT EXISTS idx_mail_folder_account ON mail_folder(account_id);
    CREATE INDEX IF NOT EXISTS idx_mail_filter_folder ON mail_filter_rule(folder_id);
    CREATE INDEX IF NOT EXISTS idx_mail_filter_priority ON mail_filter_rule(priority DESC);
    CREATE INDEX IF NOT EXISTS idx_mail_folder_id ON uni_mail(folder_id);

    -- 联系人表（营销模块）
    CREATE TABLE IF NOT EXISTS uni_contact (
        contact_id TEXT PRIMARY KEY,
        cli_id TEXT,                    -- 关联客户ID (可为空，新客户未创建时)
        email TEXT NOT NULL UNIQUE,     -- 联系人邮箱
        domain TEXT NOT NULL,           -- 邮箱域名 (自动提取)
        contact_name TEXT,              -- 联系人姓名
        country TEXT,                   -- 国家
        position TEXT,                  -- 职位
        phone TEXT,                     -- 电话
        company TEXT,                   -- 公司名称

        -- 营销状态字段
        is_bounced INTEGER DEFAULT 0 CHECK(is_bounced IN (0,1)),   -- 是否退信
        is_read INTEGER DEFAULT 0 CHECK(is_read IN (0,1)),         -- 是否已读
        is_deleted INTEGER DEFAULT 0 CHECK(is_deleted IN (0,1)),   -- 是否删除
        send_count INTEGER DEFAULT 0,   -- 发送次数
        bounce_count INTEGER DEFAULT 0, -- 退信次数
        read_count INTEGER DEFAULT 0,   -- 已读次数
        last_sent_at DATETIME,          -- 最后发送时间

        remark TEXT,
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (cli_id) REFERENCES uni_cli(cli_id) ON DELETE SET NULL
    );

    -- 联系人组表 (Email Task Manager)
    CREATE TABLE IF NOT EXISTS uni_contact_group (
        group_id TEXT PRIMARY KEY,           -- GP+时间戳格式
        group_name TEXT NOT NULL,            -- 组名称
        filter_criteria TEXT,                -- JSON筛选条件: {country, domain, is_bounced}
        contact_count INTEGER DEFAULT 0,     -- 组内联系人数
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        updated_at DATETIME DEFAULT (datetime('now', 'localtime'))
    );

    -- 发件人账号表
    CREATE TABLE IF NOT EXISTS uni_email_account (
        account_id TEXT PRIMARY KEY,         -- EA+时间戳格式
        email TEXT NOT NULL UNIQUE,          -- 发件人邮箱
        password TEXT NOT NULL,              -- AES加密后的密码
        smtp_server TEXT DEFAULT 'smtp.163.com',
        daily_limit INTEGER DEFAULT 1800,    -- 每日发送限制
        sent_today INTEGER DEFAULT 0,        -- 今日已发送数
        last_reset_date TEXT,                -- 最后重置日期 YYYY-MM-DD
        created_at DATETIME DEFAULT (datetime('now', 'localtime'))
    );

    -- 邮件任务表
    CREATE TABLE IF NOT EXISTS uni_email_task (
        task_id TEXT PRIMARY KEY,            -- ET+时间戳格式
        task_name TEXT NOT NULL,             -- 任务名称
        account_ids TEXT NOT NULL,           -- JSON数组: 发件人账号IDs（支持多账号轮换）
        group_ids TEXT NOT NULL,             -- JSON数组: 关联的组IDs
        subject TEXT NOT NULL,               -- 邮件主题
        body TEXT NOT NULL,                  -- HTML邮件内容(含签名)
        placeholders TEXT,                   -- JSON: 占位符配置
        schedule_start TEXT,                 -- 发送开始时间 HH:MM
        schedule_end TEXT,                   -- 发送结束时间 HH:MM
        send_interval INTEGER DEFAULT 2,     -- 发送间隔(秒)
        daily_limit_per_account INTEGER DEFAULT 1800, -- 单账号日发送上限
        skip_enabled INTEGER DEFAULT 1,      -- 是否启用跳过规则(默认开启)
        skip_days INTEGER DEFAULT 7,         -- 成功发送后跳过天数
        current_account_index INTEGER DEFAULT 0, -- 当前使用的账号索引
        status TEXT DEFAULT 'pending',       -- pending, running, paused, completed, cancelled, error
        total_count INTEGER DEFAULT 0,       -- 总收件人数
        sent_count INTEGER DEFAULT 0,        -- 已发送数
        failed_count INTEGER DEFAULT 0,      -- 失败数
        skipped_count INTEGER DEFAULT 0,     -- 因时间限制跳过数
        started_at DATETIME,                 -- 开始时间
        completed_at DATETIME,               -- 完成时间
        cancel_requested INTEGER DEFAULT 0,  -- 取消请求标志
        error_message TEXT,                  -- 错误信息
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        CHECK(skip_enabled IN (0,1))
    );

    -- 邮件发送日志表
    CREATE TABLE IF NOT EXISTS uni_email_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,               -- 关联任务
        contact_id TEXT NOT NULL,            -- 关联联系人
        email TEXT NOT NULL,                 -- 收件人邮箱
        company_name TEXT,                   -- 公司名(用于占位符替换记录)
        sent_at DATETIME DEFAULT (datetime('now', 'localtime')),
        status TEXT DEFAULT 'sent',          -- sent, failed
        error_message TEXT,                  -- 失败原因
        FOREIGN KEY (task_id) REFERENCES uni_email_task(task_id) ON DELETE CASCADE,
        FOREIGN KEY (contact_id) REFERENCES uni_contact(contact_id) ON DELETE CASCADE
    );

    -- 联系人索引
    CREATE INDEX IF NOT EXISTS idx_contact_cli ON uni_contact(cli_id);
    CREATE INDEX IF NOT EXISTS idx_contact_domain ON uni_contact(domain);
    CREATE INDEX IF NOT EXISTS idx_contact_email ON uni_contact(email);
    CREATE INDEX IF NOT EXISTS idx_contact_country ON uni_contact(country);
    CREATE INDEX IF NOT EXISTS idx_contact_bounced ON uni_contact(is_bounced);

    -- Email Task Manager 索引
    CREATE INDEX IF NOT EXISTS idx_task_status ON uni_email_task(status);
    CREATE INDEX IF NOT EXISTS idx_task_account ON uni_email_task(account_id);
    CREATE INDEX IF NOT EXISTS idx_log_task ON uni_email_log(task_id);
    CREATE INDEX IF NOT EXISTS idx_log_status ON uni_email_log(status);
    CREATE INDEX IF NOT EXISTS idx_log_contact ON uni_email_log(contact_id);
    CREATE INDEX IF NOT EXISTS idx_account_email ON uni_email_account(email);

    -- 待开发客户表 (Prospect)
    CREATE TABLE IF NOT EXISTS uni_prospect (
        prospect_id TEXT PRIMARY KEY,      -- PK+时间戳格式
        prospect_name TEXT NOT NULL,       -- 客户名称
        company_website TEXT,              -- 公司网站
        domain TEXT NOT NULL UNIQUE,       -- 域名（关联键）
        country TEXT,                      -- 国家
        business_type TEXT,                -- 主要业务
        business_detail TEXT,              -- 业务明细
        value_level INTEGER DEFAULT 0,     -- 价值分级(1-3, 1最高, 0未分级)
        cli_id TEXT,                       -- 转化后的客户ID（外键）
        status TEXT DEFAULT 'pending',     -- 状态：pending/converted/archived
        contact_count INTEGER DEFAULT 0,   -- 关联联系人数
        is_public_domain INTEGER DEFAULT 0, -- 是否公共邮箱域名（gmail/hotmail等）
        remark TEXT,                       -- 备注
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (cli_id) REFERENCES uni_cli(cli_id) ON DELETE SET NULL
    );

    -- Prospect 索引
    CREATE INDEX IF NOT EXISTS idx_prospect_domain ON uni_prospect(domain);
    CREATE INDEX IF NOT EXISTS idx_prospect_cli ON uni_prospect(cli_id);
    CREATE INDEX IF NOT EXISTS idx_prospect_status ON uni_prospect(status);
    CREATE INDEX IF NOT EXISTS idx_prospect_public ON uni_prospect(is_public_domain);

    -- ============ 银行流水管理表（财务管理模块） ============

    -- 银行流水主表
    CREATE TABLE IF NOT EXISTS uni_bank_transaction (
        transaction_id TEXT PRIMARY KEY,
        transaction_time TEXT NOT NULL,
        transaction_no TEXT NOT NULL,
        ledger_no TEXT,
        transaction_type TEXT NOT NULL,
        transaction_detail TEXT,
        currency TEXT DEFAULT 'CNY',
        transaction_amount REAL NOT NULL CHECK(transaction_amount > 0),
        balance REAL,
        payer_name TEXT,
        payer_bank TEXT,
        payer_account TEXT,
        payee_name TEXT,
        payee_bank TEXT,
        payee_account TEXT,
        payee_remark_name TEXT,
        remark_text TEXT,
        internal_remark TEXT,
        source_file TEXT,
        import_batch TEXT NOT NULL,
        is_matched INTEGER DEFAULT 0 CHECK(is_matched IN (0,1,2)),
        matched_amount REAL DEFAULT 0,
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        UNIQUE(transaction_no, ledger_no)
    );

    -- 银行流水索引
    CREATE INDEX IF NOT EXISTS idx_bt_time ON uni_bank_transaction(transaction_time DESC);
    CREATE INDEX IF NOT EXISTS idx_bt_no ON uni_bank_transaction(transaction_no);
    CREATE INDEX IF NOT EXISTS idx_bt_matched ON uni_bank_transaction(is_matched);
    CREATE INDEX IF NOT EXISTS idx_bt_payer ON uni_bank_transaction(payer_name);
    CREATE INDEX IF NOT EXISTS idx_bt_payee ON uni_bank_transaction(payee_name);
    CREATE INDEX IF NOT EXISTS idx_bt_batch ON uni_bank_transaction(import_batch);
    CREATE INDEX IF NOT EXISTS idx_bt_amount ON uni_bank_transaction(transaction_amount);

    -- 台账关联表（流水与订单关联）
    CREATE TABLE IF NOT EXISTS uni_bank_ledger (
        ledger_id TEXT PRIMARY KEY,
        transaction_id TEXT NOT NULL,
        manager_id TEXT NOT NULL,
        allocation_amount REAL NOT NULL CHECK(allocation_amount > 0),
        is_primary INTEGER DEFAULT 0 CHECK(is_primary IN (0,1)),
        match_type TEXT DEFAULT 'manual' CHECK(match_type IN ('manual', 'auto', 'partial')),
        remark TEXT,
        created_by TEXT,
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (transaction_id) REFERENCES uni_bank_transaction(transaction_id) ON DELETE CASCADE,
        FOREIGN KEY (manager_id) REFERENCES uni_order_manager(manager_id) ON DELETE CASCADE,
        FOREIGN KEY (created_by) REFERENCES uni_emp(emp_id) ON DELETE SET NULL,
        UNIQUE(transaction_id, manager_id)
    );

    -- 台账关联表索引
    CREATE INDEX IF NOT EXISTS idx_bl_tx ON uni_bank_ledger(transaction_id);
    CREATE INDEX IF NOT EXISTS idx_bl_manager ON uni_bank_ledger(manager_id);
    CREATE INDEX IF NOT EXISTS idx_bl_date ON uni_bank_ledger(created_at DESC);

    -- 邮件模板表 (开发信模板管理)
    CREATE TABLE IF NOT EXISTS uni_email_template (
        template_id TEXT PRIMARY KEY,         -- TPL+时间戳格式
        template_name TEXT NOT NULL,          -- 模板名称
        subject TEXT NOT NULL,                -- 邮件主题模板
        body TEXT NOT NULL,                   -- HTML邮件内容模板
        created_by TEXT NOT NULL,             -- 创建人(员工ID)
        created_at DATETIME DEFAULT (datetime('now', 'localtime')),
        FOREIGN KEY (created_by) REFERENCES uni_emp(emp_id) ON DELETE CASCADE
    );

    -- 邮件模板索引
    CREATE INDEX IF NOT EXISTS idx_template_created_by ON uni_email_template(created_by);
    CREATE INDEX IF NOT EXISTS idx_template_name ON uni_email_template(template_name);
    """

    with get_db_connection() as conn:
        # 先执行迁移：为已有数据库添加 account_id 列（必须在executescript之前）
        try:
            conn.execute("ALTER TABLE uni_mail ADD COLUMN account_id INTEGER REFERENCES mail_config(id) ON DELETE SET NULL")
            print("[DB] 迁移完成：uni_mail 添加 account_id 列")
        except sqlite3.OperationalError:
            pass  # 列已存在或表不存在，忽略

        # 迁移：添加 cc 字段
        try:
            conn.execute("ALTER TABLE uni_mail ADD COLUMN cc_addr TEXT")
            print("[DB] 迁移完成：uni_mail 添加 cc_addr 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 mail_sync_lock 添加进度字段
        try:
            conn.execute("ALTER TABLE mail_sync_lock ADD COLUMN progress_total INTEGER DEFAULT 0")
            conn.execute("ALTER TABLE mail_sync_lock ADD COLUMN progress_current INTEGER DEFAULT 0")
            conn.execute("ALTER TABLE mail_sync_lock ADD COLUMN progress_message TEXT DEFAULT ''")
            print("[DB] 迁移完成：mail_sync_lock 添加进度字段")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 mail_sync_lock 添加同步统计字段
        try:
            conn.execute("ALTER TABLE mail_sync_lock ADD COLUMN sync_start_date TEXT")
            conn.execute("ALTER TABLE mail_sync_lock ADD COLUMN sync_end_date TEXT")
            conn.execute("ALTER TABLE mail_sync_lock ADD COLUMN total_emails INTEGER DEFAULT 0")
            conn.execute("ALTER TABLE mail_sync_lock ADD COLUMN synced_emails INTEGER DEFAULT 0")
            print("[DB] 迁移完成：mail_sync_lock 添加同步统计字段")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 uni_mail 添加 is_read 字段
        try:
            conn.execute("ALTER TABLE uni_mail ADD COLUMN is_read INTEGER DEFAULT 0")
            print("[DB] 迁移完成：uni_mail 添加 is_read 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 uni_mail 添加 from_name 字段
        try:
            conn.execute("ALTER TABLE uni_mail ADD COLUMN from_name TEXT")
            print("[DB] 迁移完成：uni_mail 添加 from_name 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 uni_mail 添加 folder_id 字段
        try:
            conn.execute("ALTER TABLE uni_mail ADD COLUMN folder_id INTEGER REFERENCES mail_folder(id) ON DELETE SET NULL")
            print("[DB] 迁移完成：uni_mail 添加 folder_id 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 uni_mail 添加 is_deleted 字段（回收站功能）
        try:
            conn.execute("ALTER TABLE uni_mail ADD COLUMN is_deleted INTEGER DEFAULT 0 CHECK(is_deleted IN (0,1))")
            print("[DB] 迁移完成：uni_mail 添加 is_deleted 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 uni_mail 添加 deleted_at 字段
        try:
            conn.execute("ALTER TABLE uni_mail ADD COLUMN deleted_at DATETIME")
            print("[DB] 迁移完成：uni_mail 添加 deleted_at 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 uni_mail 添加 is_draft 字段（草稿箱功能）
        try:
            conn.execute("ALTER TABLE uni_mail ADD COLUMN is_draft INTEGER DEFAULT 0 CHECK(is_draft IN (0,1))")
            print("[DB] 迁移完成：uni_mail 添加 is_draft 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 uni_mail 添加 is_blacklisted 字段（黑名单邮件箱功能）
        try:
            conn.execute("ALTER TABLE uni_mail ADD COLUMN is_blacklisted INTEGER DEFAULT 0 CHECK(is_blacklisted IN (0,1))")
            print("[DB] 迁移完成：uni_mail 添加 is_blacklisted 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 mail_config 添加同步批次配置字段
        try:
            conn.execute("ALTER TABLE mail_config ADD COLUMN sync_batch_size INTEGER DEFAULT 100")
            print("[DB] 迁移完成：mail_config 添加 sync_batch_size 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        try:
            conn.execute("ALTER TABLE mail_config ADD COLUMN sync_pause_seconds REAL DEFAULT 1.0")
            print("[DB] 迁移完成：mail_config 添加 sync_pause_seconds 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 uni_mail 添加 IMAP UID 字段（用于增量同步优化）
        try:
            conn.execute("ALTER TABLE uni_mail ADD COLUMN imap_uid INTEGER")
            print("[DB] 迁移完成：uni_mail 添加 imap_uid 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        try:
            conn.execute("ALTER TABLE uni_mail ADD COLUMN imap_folder TEXT")
            print("[DB] 迁移完成：uni_mail 添加 imap_folder 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：添加 UID+文件夹唯一约束（防止重复同步）
        try:
            # 先删除旧索引
            conn.execute("DROP INDEX IF EXISTS idx_mail_uid_folder")
            # 创建唯一约束（SQLite用UNIQUE索引实现）
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_mail_uid_folder_account ON uni_mail(imap_uid, imap_folder, account_id) WHERE imap_uid IS NOT NULL")
            print("[DB] 迁移完成：uni_mail 添加唯一约束 (imap_uid, imap_folder, account_id)")
        except sqlite3.OperationalError as e:
            if "UNIQUE constraint" in str(e) or "already exists" in str(e):
                pass  # 约束已存在或数据有重复，忽略
            else:
                print(f"[DB] 迁移警告：{e}")

        # 迁移：uni_order_manager_rel 表从关联销售订单改为关联报价订单
        try:
            # 检查表是否存在且有 order_id 列
            old_schema = conn.execute("PRAGMA table_info(uni_order_manager_rel)").fetchall()
            has_order_id = any(col[1] == 'order_id' for col in old_schema)

            if has_order_id:
                # 备份旧数据（可选，这里直接清空因为关联关系改变）
                conn.execute("DROP TABLE IF EXISTS uni_order_manager_rel_backup")
                conn.execute("ALTER TABLE uni_order_manager_rel RENAME TO uni_order_manager_rel_backup")
                print("[DB] 迁移：uni_order_manager_rel 表已备份为 uni_order_manager_rel_backup")
                # 新表将由 executescript(schema) 创建
        except sqlite3.OperationalError as e:
            if "no such table" in str(e):
                pass  # 表不存在，将由 schema 创建
            else:
                print(f"[DB] 迁移警告 (uni_order_manager_rel): {e}")

        # 迁移：为 uni_offer 添加 status 和 target_price_rmb 列（必须在 executescript 之前，因为 schema 中有索引）
        try:
            conn.execute("ALTER TABLE uni_offer ADD COLUMN status TEXT DEFAULT '询价中'")
            print("[DB] 迁移完成：uni_offer 添加 status 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        try:
            conn.execute("ALTER TABLE uni_offer ADD COLUMN target_price_rmb REAL")
            print("[DB] 迁移完成：uni_offer 添加 target_price_rmb 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        conn.executescript(schema)

        # 迁移：为 uni_cli 添加营销相关字段
        try:
            conn.execute("ALTER TABLE uni_cli ADD COLUMN domain TEXT")
            print("[DB] 迁移完成：uni_cli 添加 domain 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        try:
            conn.execute("ALTER TABLE uni_cli ADD COLUMN is_contacted INTEGER DEFAULT 0 CHECK(is_contacted IN (0,1))")
            print("[DB] 迁移完成：uni_cli 添加 is_contacted 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        try:
            conn.execute("ALTER TABLE uni_cli ADD COLUMN has_inquiry INTEGER DEFAULT 0 CHECK(has_inquiry IN (0,1))")
            print("[DB] 迁移完成：uni_cli 添加 has_inquiry 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        try:
            conn.execute("ALTER TABLE uni_cli ADD COLUMN has_order INTEGER DEFAULT 0 CHECK(has_order IN (0,1))")
            print("[DB] 迁移完成：uni_cli 添加 has_order 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 uni_cli 添加 send_mail 列（批量发送邮件用，与 email 字段分开）
        try:
            conn.execute("ALTER TABLE uni_cli ADD COLUMN send_mail TEXT")
            print("[DB] 迁移完成：uni_cli 添加 send_mail 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 为 uni_cli 添加域名索引
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_cli_domain ON uni_cli(domain)")
            print("[DB] 迁移完成：uni_cli 添加 domain 索引")
        except sqlite3.OperationalError:
            pass

        # 迁移：为 uni_offer 添加 cli_id 列（报价可直接指定客户）
        try:
            conn.execute("ALTER TABLE uni_offer ADD COLUMN cli_id TEXT REFERENCES uni_cli(cli_id)")
            print("[DB] 迁移完成：uni_offer 添加 cli_id 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 uni_order_manager 添加 transaction_code 列（用于关联银行流水）
        try:
            conn.execute("ALTER TABLE uni_order_manager ADD COLUMN transaction_code TEXT")
            print("[DB] 迁移完成：uni_order_manager 添加 transaction_code 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 uni_email_task 添加跳过规则相关字段
        try:
            conn.execute("ALTER TABLE uni_email_task ADD COLUMN send_interval INTEGER DEFAULT 2")
            conn.execute("ALTER TABLE uni_email_task ADD COLUMN skip_enabled INTEGER DEFAULT 1")
            conn.execute("ALTER TABLE uni_email_task ADD COLUMN skip_days INTEGER DEFAULT 7")
            conn.execute("ALTER TABLE uni_email_task ADD COLUMN skipped_count INTEGER DEFAULT 0")
            print("[DB] 迁移完成：uni_email_task 添加 skip_enabled/skip_days/skipped_count 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 uni_email_task 添加多账号轮换字段
        try:
            conn.execute("ALTER TABLE uni_email_task ADD COLUMN account_ids TEXT")
            conn.execute("ALTER TABLE uni_email_task ADD COLUMN daily_limit_per_account INTEGER DEFAULT 1800")
            conn.execute("ALTER TABLE uni_email_task ADD COLUMN current_account_index INTEGER DEFAULT 0")
            # 数据迁移：将旧的account_id转为account_ids JSON数组
            conn.execute("UPDATE uni_email_task SET account_ids = json_array(account_id) WHERE account_ids IS NULL AND account_id IS NOT NULL")
            print("[DB] 迁移完成：uni_email_task 添加 account_ids/daily_limit_per_account 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        # 迁移：为 uni_email_log 添加 account_id 列（记录每条发送使用的账号）
        try:
            conn.execute("ALTER TABLE uni_email_log ADD COLUMN account_id TEXT")
            conn.execute("ALTER TABLE uni_email_log ADD COLUMN account_email TEXT")
            print("[DB] 迁移完成：uni_email_log 添加 account_id/account_email 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略

        conn.execute("""
            INSERT INTO uni_emp (emp_id, emp_name, account, password, rule)
            VALUES ('000', '超级管理员', 'Admin', '088426ba2d6e02949f54ef1e62a2aa73', '3')
            ON CONFLICT(emp_id) DO NOTHING
        """)

        conn.commit()
    # 初始化后清除缓存
    clear_cache()


def get_paginated_list(table_name, page=1, page_size=10, search_kwargs=None, where_clause=None, where_params=None):
    """
    Generic pagination and fuzzy search
    search_kwargs: {column_name: value} - fuzzy search with LIKE
    where_clause: custom WHERE clause for exact filtering
    where_params: params for where_clause
    """
    offset = (page - 1) * page_size
    query = f"SELECT * FROM {table_name}"
    params = []

    conditions = []

    if search_kwargs:
        for col, val in search_kwargs.items():
            conditions.append(f"{col} LIKE ?")
            params.append(f"%{val}%")

    if where_clause:
        conditions.append(where_clause)
        if where_params:
            params.extend(where_params)

    if conditions:
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