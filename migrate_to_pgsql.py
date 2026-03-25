"""
SQLite 到 PostgreSQL 数据迁移脚本
用法: python migrate_to_pgsql.py
"""
import sqlite3
import os
import sys
from datetime import datetime

# 尝试加载环境变量
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("[警告] python-dotenv 未安装，使用系统环境变量")

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("[错误] psycopg2 未安装，请运行: pip install psycopg2-binary")
    sys.exit(1)


# PostgreSQL 配置
PG_CONFIG = {
    'host': os.getenv('PG_HOST', 'localhost'),
    'port': int(os.getenv('PG_PORT', 5432)),
    'database': os.getenv('PG_DATABASE', 'uni_platform'),
    'user': os.getenv('PG_USER', 'postgres'),
    'password': os.getenv('PG_PASSWORD', '')
}

# SQLite 路径
SQLITE_PATH = os.path.join(os.path.dirname(__file__), 'uni_platform.db')


def get_sqlite_connection():
    """获取 SQLite 连接"""
    if not os.path.exists(SQLITE_PATH):
        print(f"[错误] SQLite 数据库文件不存在: {SQLITE_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_pg_connection():
    """获取 PostgreSQL 连接"""
    try:
        conn = psycopg2.connect(**PG_CONFIG, cursor_factory=RealDictCursor)
        print(f"[成功] 已连接到 PostgreSQL: {PG_CONFIG['host']}:{PG_CONFIG['port']}/{PG_CONFIG['database']}")
        return conn
    except Exception as e:
        print(f"[错误] 无法连接 PostgreSQL: {e}")
        sys.exit(1)


def get_table_list(sqlite_conn):
    """获取 SQLite 中的所有表名"""
    cursor = sqlite_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    return [row['name'] for row in cursor.fetchall()]


def get_table_schema(sqlite_conn, table_name):
    """获取表结构"""
    cursor = sqlite_conn.execute(f"PRAGMA table_info({table_name})")
    return cursor.fetchall()


def sqlite_type_to_pg(sqlite_type):
    """将 SQLite 类型转换为 PostgreSQL 类型"""
    sqlite_type = sqlite_type.upper()

    type_mapping = {
        'INTEGER': 'INTEGER',
        'INT': 'INTEGER',
        'BIGINT': 'BIGINT',
        'SMALLINT': 'SMALLINT',
        'TEXT': 'TEXT',
        'VARCHAR': 'VARCHAR(255)',
        'CHAR': 'CHAR(1)',
        'REAL': 'DOUBLE PRECISION',
        'FLOAT': 'DOUBLE PRECISION',
        'DOUBLE': 'DOUBLE PRECISION',
        'NUMERIC': 'NUMERIC',
        'DECIMAL': 'NUMERIC',
        'BOOLEAN': 'BOOLEAN',
        'BLOB': 'BYTEA',
        'DATE': 'DATE',
        'DATETIME': 'TIMESTAMP',
        'TIMESTAMP': 'TIMESTAMP',
    }

    # 处理带长度的类型，如 VARCHAR(255)
    for key in type_mapping:
        if sqlite_type.startswith(key):
            if '(' in sqlite_type:
                # 保留原始长度定义
                return sqlite_type.replace('VARCHAR', 'VARCHAR').replace('CHAR', 'CHAR')
            return type_mapping[key]

    # 默认返回 TEXT
    return 'TEXT'


def create_table_pg(pg_conn, table_name, columns):
    """在 PostgreSQL 中创建表"""
    col_defs = []
    primary_keys = []

    for col in columns:
        col_name = col['name']
        col_type = sqlite_type_to_pg(col['type'])
        not_null = 'NOT NULL' if col['notnull'] else ''

        # 转换默认值
        default = ''
        if col['dflt_value']:
            dflt = col['dflt_value']
            # SQLite datetime 转换为 PostgreSQL NOW()
            if "datetime('now', 'localtime')" in dflt or 'datetime("now", "localtime")' in dflt:
                default = 'DEFAULT NOW()'
            elif "datetime('now')" in dflt or 'datetime("now")' in dflt:
                default = 'DEFAULT NOW()'
            elif "date('now')" in dflt or 'date("now")' in dflt:
                default = 'DEFAULT CURRENT_DATE'
            elif "time('now')" in dflt or 'time("now")' in dflt:
                default = 'DEFAULT CURRENT_TIME'
            else:
                default = f'DEFAULT {dflt}'

        col_def = f'"{col_name}" {col_type}'
        if not_null:
            col_def += f' {not_null}'
        if default:
            col_def += f' {default}'

        col_defs.append(col_def)

        if col['pk']:
            primary_keys.append(col_name)

    # 添加主键约束
    if primary_keys:
        col_defs.append(f'PRIMARY KEY ({", ".join(f"""{pk}""" for pk in primary_keys)})')

    sql = f'CREATE TABLE IF NOT EXISTS "{table_name}" (\n  ' + ',\n  '.join(col_defs) + '\n)'

    with pg_conn.cursor() as cur:
        cur.execute(sql)
    pg_conn.commit()
    print(f"  [创建表] {table_name}")


def migrate_table_data(sqlite_conn, pg_conn, table_name):
    """迁移表数据"""
    # 获取 SQLite 数据
    cursor = sqlite_conn.execute(f'SELECT * FROM "{table_name}"')
    rows = cursor.fetchall()

    if not rows:
        print(f"  [跳过] {table_name} (无数据)")
        return 0

    columns = rows[0].keys()
    col_names = ', '.join(f'"{col}"' for col in columns)
    placeholders = ', '.join(['%s'] * len(columns))

    sql = f'INSERT INTO "{table_name}" ({col_names}) VALUES ({placeholders})'

    migrated = 0
    with pg_conn.cursor() as cur:
        for row in rows:
            try:
                values = [row[col] for col in columns]
                cur.execute(sql, values)
                migrated += 1
            except Exception as e:
                print(f"    [警告] 行插入失败: {e}")

    pg_conn.commit()
    print(f"  [迁移] {table_name}: {migrated} 行")
    return migrated


def create_indexes(pg_conn, sqlite_conn, table_name):
    """迁移索引"""
    cursor = sqlite_conn.execute(f"PRAGMA index_list({table_name})")
    indexes = cursor.fetchall()

    for idx in indexes:
        idx_name = idx['name']
        if idx_name.startswith('sqlite_'):
            continue

        # 获取索引列
        idx_cursor = sqlite_conn.execute(f"PRAGMA index_info({idx_name})")
        idx_cols = idx_cursor.fetchall()
        col_names = ', '.join(f'"{col["name"]}"' for col in idx_cols)

        is_unique = 'UNIQUE' if idx['unique'] else ''

        try:
            sql = f'CREATE {is_unique} INDEX IF NOT EXISTS "{idx_name}" ON "{table_name}" ({col_names})'
            with pg_conn.cursor() as cur:
                cur.execute(sql)
            pg_conn.commit()
            print(f"    [索引] {idx_name}")
        except Exception as e:
            print(f"    [索引跳过] {idx_name}: {e}")


def main():
    print("=" * 60)
    print("SQLite → PostgreSQL 数据迁移")
    print("=" * 60)
    print(f"SQLite 源: {SQLITE_PATH}")
    print(f"PostgreSQL 目标: {PG_CONFIG['host']}:{PG_CONFIG['port']}/{PG_CONFIG['database']}")
    print()

    # 检查环境变量
    if not PG_CONFIG['password']:
        print("[警告] PG_PASSWORD 环境变量未设置")
        response = input("继续吗? (y/n): ")
        if response.lower() != 'y':
            print("已取消")
            sys.exit(0)

    # 连接数据库
    print("\n[步骤 1] 连接数据库...")
    sqlite_conn = get_sqlite_connection()
    pg_conn = get_pg_connection()

    # 获取表列表
    print("\n[步骤 2] 获取表列表...")
    tables = get_table_list(sqlite_conn)
    print(f"  发现 {len(tables)} 个表: {', '.join(tables)}")

    # 迁移每个表
    print("\n[步骤 3] 创建表结构并迁移数据...")
    total_rows = 0

    for table in tables:
        print(f"\n处理表: {table}")
        columns = get_table_schema(sqlite_conn, table)

        # 创建表
        create_table_pg(pg_conn, table, columns)

        # 迁移数据
        rows = migrate_table_data(sqlite_conn, pg_conn, table)
        total_rows += rows

        # 创建索引
        create_indexes(pg_conn, sqlite_conn, table)

    # 关闭连接
    sqlite_conn.close()
    pg_conn.close()

    print("\n" + "=" * 60)
    print(f"迁移完成! 共迁移 {total_rows} 行数据")
    print("=" * 60)


if __name__ == '__main__':
    main()