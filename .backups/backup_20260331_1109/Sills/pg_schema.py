"""
PostgreSQL 数据库 Schema
与 SQLite 版本对应，但使用 PostgreSQL 语法
"""

# PostgreSQL 表结构定义
# 注意：
# - INTEGER PRIMARY KEY AUTOINCREMENT → SERIAL PRIMARY KEY
# - datetime('now', 'localtime') → NOW()
# - CHECK 约束语法略有不同
# - 部分索引语法不同

PG_SCHEMA = """
-- 汇率表
CREATE TABLE IF NOT EXISTS uni_daily (
    id SERIAL PRIMARY KEY,
    record_date TEXT NOT NULL,
    currency_code INTEGER NOT NULL,
    exchange_rate DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(record_date, currency_code)
);

-- 员工表
CREATE TABLE IF NOT EXISTS uni_emp (
    emp_id TEXT PRIMARY KEY,
    department TEXT,
    position TEXT,
    emp_name TEXT NOT NULL,
    contact TEXT,
    account TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    hire_date TEXT,
    rule TEXT NOT NULL,
    remark TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT chk_emp_id_length CHECK (LENGTH(emp_id) = 3)
);

-- 客户表
CREATE TABLE IF NOT EXISTS uni_cli (
    cli_id TEXT PRIMARY KEY,
    cli_name TEXT NOT NULL,
    cli_full_name TEXT,
    cli_name_en TEXT,
    contact_name TEXT,
    address TEXT,
    region TEXT NOT NULL DEFAULT '韩国',
    credit_level TEXT DEFAULT 'A',
    margin_rate DOUBLE PRECISION DEFAULT 10.0,
    emp_id TEXT,
    website TEXT,
    payment_terms TEXT,
    email TEXT,
    phone TEXT,
    remark TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (emp_id) REFERENCES uni_emp(emp_id) ON UPDATE CASCADE
);

-- 需求/询价表
CREATE TABLE IF NOT EXISTS uni_quote (
    quote_id TEXT PRIMARY KEY,
    quote_date TEXT,
    cli_id TEXT NOT NULL,
    inquiry_mpn TEXT NOT NULL,
    quoted_mpn TEXT,
    inquiry_brand TEXT,
    quoted_brand TEXT,
    inquiry_qty INTEGER,
    actual_qty INTEGER,
    target_price_rmb DOUBLE PRECISION,
    cost_price_rmb DOUBLE PRECISION,
    offer_price_rmb DOUBLE PRECISION,
    platform TEXT,
    date_code TEXT,
    delivery_date TEXT,
    status TEXT DEFAULT '询价中',
    remark TEXT,
    is_transferred TEXT DEFAULT '未转',
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (cli_id) REFERENCES uni_cli(cli_id) ON UPDATE CASCADE
);

-- 供应商表
CREATE TABLE IF NOT EXISTS uni_vendor (
    vendor_id TEXT PRIMARY KEY,
    vendor_name TEXT NOT NULL,
    address TEXT,
    qq TEXT,
    wechat TEXT,
    email TEXT,
    remark TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 报价表
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
    cost_price_rmb DOUBLE PRECISION,
    offer_price_rmb DOUBLE PRECISION,
    price_kwr DOUBLE PRECISION,
    price_usd DOUBLE PRECISION,
    platform TEXT,
    vendor_id TEXT,
    date_code TEXT,
    delivery_date TEXT,
    emp_id TEXT,
    offer_statement TEXT,
    remark TEXT,
    is_transferred TEXT DEFAULT '未转',
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (quote_id) REFERENCES uni_quote(quote_id),
    FOREIGN KEY (vendor_id) REFERENCES uni_vendor(vendor_id),
    FOREIGN KEY (emp_id) REFERENCES uni_emp(emp_id),
    UNIQUE(quote_id)
);

-- 销售订单表
CREATE TABLE IF NOT EXISTS uni_order (
    order_id TEXT PRIMARY KEY,
    order_no TEXT,
    order_date TEXT,
    cli_id TEXT NOT NULL,
    offer_id TEXT,
    inquiry_mpn TEXT,
    inquiry_brand TEXT,
    price_rmb DOUBLE PRECISION,
    price_kwr DOUBLE PRECISION,
    price_usd DOUBLE PRECISION,
    cost_price_rmb DOUBLE PRECISION,
    is_finished INTEGER DEFAULT 0,
    is_paid INTEGER DEFAULT 0,
    paid_amount DOUBLE PRECISION DEFAULT 0.0,
    return_status TEXT DEFAULT '正常',
    remark TEXT,
    is_transferred TEXT DEFAULT '未转',
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (cli_id) REFERENCES uni_cli(cli_id),
    FOREIGN KEY (offer_id) REFERENCES uni_offer(offer_id),
    CONSTRAINT chk_is_finished CHECK (is_finished IN (0,1)),
    CONSTRAINT chk_is_paid CHECK (is_paid IN (0,1))
);

-- 采购表
CREATE TABLE IF NOT EXISTS uni_buy (
    buy_id TEXT PRIMARY KEY,
    buy_date TEXT,
    order_id TEXT,
    vendor_id TEXT,
    buy_mpn TEXT,
    buy_brand TEXT,
    buy_price_rmb DOUBLE PRECISION,
    buy_qty INTEGER,
    sales_price_rmb DOUBLE PRECISION,
    total_amount DOUBLE PRECISION,
    is_source_confirmed INTEGER DEFAULT 0,
    is_ordered INTEGER DEFAULT 0,
    is_instock INTEGER DEFAULT 0,
    is_shipped INTEGER DEFAULT 0,
    remark TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (order_id) REFERENCES uni_order(order_id),
    FOREIGN KEY (vendor_id) REFERENCES uni_vendor(vendor_id),
    CONSTRAINT chk_is_source_confirmed CHECK (is_source_confirmed IN (0,1)),
    CONSTRAINT chk_is_ordered CHECK (is_ordered IN (0,1)),
    CONSTRAINT chk_is_instock CHECK (is_instock IN (0,1)),
    CONSTRAINT chk_is_shipped CHECK (is_shipped IN (0,1))
);

-- 邮件配置表
CREATE TABLE IF NOT EXISTS mail_config (
    id SERIAL PRIMARY KEY,
    account_name TEXT DEFAULT '默认账户',
    smtp_server TEXT,
    smtp_port INTEGER DEFAULT 587,
    imap_server TEXT,
    imap_port INTEGER DEFAULT 993,
    username TEXT,
    password TEXT,
    use_tls INTEGER DEFAULT 1,
    sync_batch_size INTEGER DEFAULT 100,
    sync_pause_seconds DOUBLE PRECISION DEFAULT 1.0,
    is_current INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT chk_is_current CHECK (is_current IN (0,1))
);

-- 邮件文件夹表（需要在 uni_mail 之前创建）
CREATE TABLE IF NOT EXISTS mail_folder (
    id SERIAL PRIMARY KEY,
    folder_name TEXT NOT NULL,
    folder_icon TEXT DEFAULT 'folder',
    sort_order INTEGER DEFAULT 0,
    account_id INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (account_id) REFERENCES mail_config(id) ON DELETE CASCADE
);

-- 邮件表
CREATE TABLE IF NOT EXISTS uni_mail (
    id SERIAL PRIMARY KEY,
    subject TEXT,
    from_addr TEXT NOT NULL,
    from_name TEXT,
    to_addr TEXT NOT NULL,
    cc_addr TEXT,
    content TEXT,
    html_content TEXT,
    received_at TIMESTAMP,
    sent_at TIMESTAMP,
    is_sent INTEGER DEFAULT 0,
    is_read INTEGER DEFAULT 0,
    is_deleted INTEGER DEFAULT 0,
    deleted_at TIMESTAMP,
    message_id TEXT,
    imap_uid INTEGER,
    imap_folder TEXT,
    account_id INTEGER,
    folder_id INTEGER,
    sync_status TEXT DEFAULT 'completed',
    sync_error TEXT,
    is_draft INTEGER DEFAULT 0,
    is_blacklisted INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (account_id) REFERENCES mail_config(id) ON DELETE SET NULL,
    FOREIGN KEY (folder_id) REFERENCES mail_folder(id) ON DELETE SET NULL,
    CONSTRAINT chk_is_sent CHECK (is_sent IN (0,1)),
    CONSTRAINT chk_is_read CHECK (is_read IN (0,1)),
    CONSTRAINT chk_is_deleted CHECK (is_deleted IN (0,1)),
    CONSTRAINT chk_is_draft CHECK (is_draft IN (0,1)),
    CONSTRAINT chk_is_blacklisted CHECK (is_blacklisted IN (0,1))
);

-- 邮件关联表
CREATE TABLE IF NOT EXISTS uni_mail_rel (
    id SERIAL PRIMARY KEY,
    mail_id INTEGER NOT NULL,
    ref_type TEXT NOT NULL,
    ref_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (mail_id) REFERENCES uni_mail(id) ON DELETE CASCADE
);

-- 邮件同步锁表
CREATE TABLE IF NOT EXISTS mail_sync_lock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    locked_at TIMESTAMP,
    locked_by TEXT,
    expires_at TIMESTAMP,
    progress_total INTEGER DEFAULT 0,
    progress_current INTEGER DEFAULT 0,
    progress_message TEXT DEFAULT '',
    sync_start_date TEXT,
    sync_end_date TEXT,
    total_emails INTEGER DEFAULT 0,
    synced_emails INTEGER DEFAULT 0
);

-- 全局设置表
CREATE TABLE IF NOT EXISTS global_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 邮件过滤规则表
CREATE TABLE IF NOT EXISTS mail_filter_rule (
    id SERIAL PRIMARY KEY,
    folder_id INTEGER NOT NULL,
    keyword TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    is_enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (folder_id) REFERENCES mail_folder(id) ON DELETE CASCADE,
    CONSTRAINT chk_is_enabled CHECK (is_enabled IN (0,1))
);

-- 邮件黑名单表
CREATE TABLE IF NOT EXISTS mail_blacklist (
    id SERIAL PRIMARY KEY,
    email_addr TEXT NOT NULL UNIQUE,
    reason TEXT,
    account_id INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (account_id) REFERENCES mail_config(id) ON DELETE CASCADE
);

-- 已同步邮件UID记录表
CREATE TABLE IF NOT EXISTS uni_mail_synced_uid (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL,
    imap_uid INTEGER NOT NULL,
    imap_folder TEXT NOT NULL,
    synced_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(account_id, imap_uid, imap_folder),
    FOREIGN KEY (account_id) REFERENCES mail_config(id) ON DELETE CASCADE
);

-- 索引
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
CREATE INDEX IF NOT EXISTS idx_mail_received ON uni_mail(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_mail_sent ON uni_mail(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_mail_from ON uni_mail(from_addr);
CREATE INDEX IF NOT EXISTS idx_mail_sync_status ON uni_mail(sync_status);
CREATE INDEX IF NOT EXISTS idx_mail_account ON uni_mail(account_id);
CREATE INDEX IF NOT EXISTS idx_mail_rel_ref ON uni_mail_rel(ref_type, ref_id);
CREATE INDEX IF NOT EXISTS idx_mail_folder_account ON mail_folder(account_id);
CREATE INDEX IF NOT EXISTS idx_mail_filter_folder ON mail_filter_rule(folder_id);
CREATE INDEX IF NOT EXISTS idx_mail_filter_priority ON mail_filter_rule(priority DESC);
CREATE INDEX IF NOT EXISTS idx_mail_folder_id ON uni_mail(folder_id);

-- 部分索引（PostgreSQL 语法）
CREATE UNIQUE INDEX IF NOT EXISTS idx_mail_message_id ON uni_mail(message_id) WHERE message_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_mail_uid_folder_account ON uni_mail(imap_uid, imap_folder, account_id) WHERE imap_uid IS NOT NULL;
"""

# 默认管理员插入语句
PG_DEFAULT_ADMIN = """
INSERT INTO uni_emp (emp_id, emp_name, account, password, rule)
VALUES ('000', '超级管理员', 'Admin', '088426ba2d6e02949f54ef1e62a2aa73', '3')
ON CONFLICT (emp_id) DO NOTHING;
"""