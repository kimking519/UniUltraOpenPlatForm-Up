"""
数据库配置模块
支持 SQLite 和 PostgreSQL 双模式
通过环境变量 DATABASE_TYPE 切换
"""
import os

# 尝试加载环境变量
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 数据库类型: 'sqlite' 或 'postgresql'
DATABASE_TYPE = os.getenv('DATABASE_TYPE', 'sqlite').lower()

# SQLite 配置
SQLITE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uni_platform.db")

# PostgreSQL 配置
PG_CONFIG = {
    'host': os.getenv('PG_HOST', 'localhost'),
    'port': int(os.getenv('PG_PORT', 5432)),
    'database': os.getenv('PG_DATABASE', 'uni_platform'),
    'user': os.getenv('PG_USER', 'postgres'),
    'password': os.getenv('PG_PASSWORD', '')
}


def get_db_type():
    """获取当前数据库类型"""
    return DATABASE_TYPE


def get_sqlite_path():
    """获取 SQLite 数据库路径"""
    return SQLITE_PATH


def get_pg_config():
    """获取 PostgreSQL 配置"""
    return PG_CONFIG.copy()


def is_postgresql():
    """检查是否使用 PostgreSQL"""
    return DATABASE_TYPE == 'postgresql'


def is_sqlite():
    """检查是否使用 SQLite"""
    return DATABASE_TYPE == 'sqlite'


# 打印当前配置
if __name__ == '__main__':
    print(f"数据库类型: {DATABASE_TYPE}")
    if is_postgresql():
        print(f"PostgreSQL: {PG_CONFIG['host']}:{PG_CONFIG['port']}/{PG_CONFIG['database']}")
    else:
        print(f"SQLite: {SQLITE_PATH}")