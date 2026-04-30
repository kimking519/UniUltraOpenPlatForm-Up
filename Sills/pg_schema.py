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
    original_rate DOUBLE PRECISION,
    rate_ratio DOUBLE PRECISION DEFAULT 0.03,
    last_refresh_time TEXT,
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
    price_jpy DOUBLE PRECISION,                  -- 日元报价
    platform TEXT,
    vendor_id TEXT,
    date_code TEXT,
    delivery_date TEXT,
    emp_id TEXT,
    offer_statement TEXT,
    remark TEXT,
    status TEXT DEFAULT '询价中',
    target_price_rmb DOUBLE PRECISION,
    is_transferred TEXT DEFAULT '未转',
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (vendor_id) REFERENCES uni_vendor(vendor_id),
    FOREIGN KEY (emp_id) REFERENCES uni_emp(emp_id)
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

-- 客户订单主表
CREATE TABLE IF NOT EXISTS uni_order_manager (
    manager_id TEXT PRIMARY KEY,
    customer_order_no TEXT UNIQUE NOT NULL,
    order_date TEXT NOT NULL,
    cli_id TEXT NOT NULL,
    transaction_code TEXT,                     -- 交易编码（用于关联银行流水）
    total_cost_rmb DOUBLE PRECISION DEFAULT 0,
    total_price_rmb DOUBLE PRECISION DEFAULT 0,
    total_price_kwr DOUBLE PRECISION DEFAULT 0,
    total_price_usd DOUBLE PRECISION DEFAULT 0,
    total_price_jpy DOUBLE PRECISION DEFAULT 0,
    profit_rmb DOUBLE PRECISION DEFAULT 0,
    model_count INTEGER DEFAULT 0,
    total_qty INTEGER DEFAULT 0,
    is_paid INTEGER DEFAULT 0,
    is_finished INTEGER DEFAULT 0,
    paid_amount DOUBLE PRECISION DEFAULT 0,
    shipping_fee DOUBLE PRECISION DEFAULT 0,
    tracking_no TEXT,
    query_link TEXT,
    mail_id TEXT,
    mail_notes TEXT,
    remark TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (cli_id) REFERENCES uni_cli(cli_id) ON UPDATE CASCADE,
    CONSTRAINT chk_om_is_paid CHECK (is_paid IN (0,1)),
    CONSTRAINT chk_om_is_finished CHECK (is_finished IN (0,1))
);

-- 客户订单与报价订单关联表
CREATE TABLE IF NOT EXISTS uni_order_manager_rel (
    id SERIAL PRIMARY KEY,
    manager_id TEXT NOT NULL,
    offer_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (manager_id) REFERENCES uni_order_manager(manager_id) ON DELETE CASCADE,
    FOREIGN KEY (offer_id) REFERENCES uni_offer(offer_id) ON DELETE CASCADE,
    UNIQUE(manager_id, offer_id)
);

-- 客户订单附件表
CREATE TABLE IF NOT EXISTS uni_order_attachment (
    id SERIAL PRIMARY KEY,
    manager_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_name TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (manager_id) REFERENCES uni_order_manager(manager_id) ON DELETE CASCADE
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
    mail_type INTEGER DEFAULT 0,
    original_recipient TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (account_id) REFERENCES mail_config(id) ON DELETE SET NULL,
    FOREIGN KEY (folder_id) REFERENCES mail_folder(id) ON DELETE SET NULL,
    CONSTRAINT chk_is_sent CHECK (is_sent IN (0,1)),
    CONSTRAINT chk_is_read CHECK (is_read IN (0,1)),
    CONSTRAINT chk_is_deleted CHECK (is_deleted IN (0,1)),
    CONSTRAINT chk_is_draft CHECK (is_draft IN (0,1)),
    CONSTRAINT chk_is_blacklisted CHECK (is_blacklisted IN (0,1)),
    CONSTRAINT chk_mail_type CHECK (mail_type IN (0,1,2,3,4))
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

-- 文件夹同步进度表（记录每个文件夹最后同步的UID和时间）
CREATE TABLE IF NOT EXISTS mail_folder_sync_progress (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL,
    folder_name TEXT NOT NULL,
    last_uid INTEGER DEFAULT 0,
    last_sync_at TIMESTAMP,
    UNIQUE(account_id, folder_name),
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

-- 客户订单索引
CREATE INDEX IF NOT EXISTS idx_order_manager_cli ON uni_order_manager(cli_id);
CREATE INDEX IF NOT EXISTS idx_order_manager_date ON uni_order_manager(order_date);
CREATE INDEX IF NOT EXISTS idx_order_manager_rel_manager ON uni_order_manager_rel(manager_id);
CREATE INDEX IF NOT EXISTS idx_order_manager_rel_offer ON uni_order_manager_rel(offer_id);

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
CREATE INDEX IF NOT EXISTS idx_mail_type ON uni_mail(mail_type);

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
    company TEXT,                   -- 公司名
    prospect_name TEXT,             -- 关联的Prospect名称（同步填充）
    is_bounced INTEGER DEFAULT 0,   -- 是否退信
    is_read INTEGER DEFAULT 0,      -- 是否已读
    is_deleted INTEGER DEFAULT 0,   -- 是否删除
    send_count INTEGER DEFAULT 0,   -- 发送次数
    bounce_count INTEGER DEFAULT 0, -- 退信次数
    read_count INTEGER DEFAULT 0,   -- 已读次数
    last_sent_at TIMESTAMP,         -- 最后发送时间
    remark TEXT,                    -- 备注
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (cli_id) REFERENCES uni_cli(cli_id) ON DELETE SET NULL,
    CONSTRAINT chk_contact_bounced CHECK (is_bounced IN (0,1)),
    CONSTRAINT chk_contact_read CHECK (is_read IN (0,1)),
    CONSTRAINT chk_contact_deleted CHECK (is_deleted IN (0,1))
);

-- 营销邮件记录表
CREATE TABLE IF NOT EXISTS uni_marketing_email (
    id SERIAL PRIMARY KEY,
    contact_id TEXT NOT NULL,
    mail_id INTEGER,
    subject TEXT,
    content TEXT,
    sent_at TIMESTAMP DEFAULT NOW(),
    status TEXT DEFAULT 'sent',     -- sent, delivered, bounced, read
    bounced_reason TEXT,            -- 退信原因
    FOREIGN KEY (contact_id) REFERENCES uni_contact(contact_id) ON DELETE CASCADE,
    FOREIGN KEY (mail_id) REFERENCES uni_mail(id) ON DELETE SET NULL
);

-- 联系人索引
CREATE INDEX IF NOT EXISTS idx_contact_cli ON uni_contact(cli_id);
CREATE INDEX IF NOT EXISTS idx_contact_domain ON uni_contact(domain);
CREATE INDEX IF NOT EXISTS idx_contact_email ON uni_contact(email);
CREATE INDEX IF NOT EXISTS idx_contact_country ON uni_contact(country);
CREATE INDEX IF NOT EXISTS idx_contact_bounced ON uni_contact(is_bounced);

-- 营销邮件索引
CREATE INDEX IF NOT EXISTS idx_marketing_contact ON uni_marketing_email(contact_id);
CREATE INDEX IF NOT EXISTS idx_marketing_sent ON uni_marketing_email(sent_at DESC);
CREATE INDEX IF NOT EXISTS idx_marketing_status ON uni_marketing_email(status);

-- 部分索引（PostgreSQL 语法）
CREATE UNIQUE INDEX IF NOT EXISTS idx_mail_message_id ON uni_mail(message_id) WHERE message_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_mail_uid_folder_account ON uni_mail(imap_uid, imap_folder, account_id) WHERE imap_uid IS NOT NULL;

-- 待开发客户表 (Prospect)
CREATE TABLE IF NOT EXISTS uni_prospect (
    prospect_id TEXT PRIMARY KEY,
    prospect_name TEXT NOT NULL,
    company_website TEXT,
    domain TEXT NOT NULL UNIQUE,
    country TEXT,
    business_type TEXT,                     -- 主要业务
    business_detail TEXT,                   -- 业务明细
    value_level INTEGER DEFAULT 0,          -- 价值分级(1-3, 1最高, 0未分级)
    cli_id TEXT,
    status TEXT DEFAULT 'pending',
    contact_count INTEGER DEFAULT 0,
    is_public_domain INTEGER DEFAULT 0,
    remark TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (cli_id) REFERENCES uni_cli(cli_id) ON DELETE SET NULL,
    CONSTRAINT chk_prospect_public CHECK (is_public_domain IN (0,1)),
    CONSTRAINT chk_prospect_value CHECK (value_level IN (0,1,2,3))
);

-- Prospect 索引
CREATE INDEX IF NOT EXISTS idx_prospect_domain ON uni_prospect(domain);
CREATE INDEX IF NOT EXISTS idx_prospect_cli ON uni_prospect(cli_id);
CREATE INDEX IF NOT EXISTS idx_prospect_status ON uni_prospect(status);
CREATE INDEX IF NOT EXISTS idx_prospect_public ON uni_prospect(is_public_domain);

-- 联系人组表
CREATE TABLE IF NOT EXISTS uni_contact_group (
    group_id TEXT PRIMARY KEY,
    group_name TEXT NOT NULL,
    description TEXT,
    group_type TEXT DEFAULT 'dynamic',     -- dynamic(筛选条件组) / static(手动邮件列表组)
    filter_criteria TEXT,                  -- dynamic组: 筛选条件JSON
    email_list TEXT,                       -- static组: 邮件JSON列表 [{"email": "x@x.com", "company": "公司名"}, ...]
    manual_emails TEXT,                    -- 手动添加的邮件JSON列表（可与筛选条件合并）
    contact_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP
);

-- 联系人-组关联表
CREATE TABLE IF NOT EXISTS uni_contact_group_rel (
    id SERIAL PRIMARY KEY,
    group_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (group_id) REFERENCES uni_contact_group(group_id) ON DELETE CASCADE,
    FOREIGN KEY (contact_id) REFERENCES uni_contact(contact_id) ON DELETE CASCADE,
    UNIQUE(group_id, contact_id)
);

-- 发件人账号表 (Email Task Manager)
CREATE TABLE IF NOT EXISTS uni_email_account (
    account_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,           -- AES加密存储
    smtp_server TEXT DEFAULT 'smtp.163.com',
    daily_limit INTEGER DEFAULT 1800,
    sent_today INTEGER DEFAULT 0,
    last_reset_date TEXT,
    is_primary INTEGER DEFAULT 0,     -- 是否为主账号(joy@unicornsemi.com)，用于代理发送
    created_at TIMESTAMP DEFAULT NOW()
);

-- 邮件任务表 (Email Task Manager)
CREATE TABLE IF NOT EXISTS uni_email_task (
    task_id TEXT PRIMARY KEY,
    task_name TEXT NOT NULL,
    account_ids TEXT NOT NULL,         -- JSON数组: 发件人账号IDs（支持多账号轮换）
    group_ids TEXT NOT NULL,          -- JSON数组: 关联的组IDs
    subject TEXT NOT NULL,
    body TEXT NOT NULL,               -- HTML邮件内容(含签名)
    placeholders TEXT,
    schedule_start TEXT,
    schedule_end TEXT,
    send_interval INTEGER DEFAULT 2,  -- 发送间隔(秒)
    daily_limit_per_account INTEGER DEFAULT 1800, -- 单账号日发送上限
    skip_enabled INTEGER DEFAULT 1,   -- 是否启用跳过规则(默认开启)
    skip_days INTEGER DEFAULT 7,      -- 成功发送后跳过天数
    current_account_index INTEGER DEFAULT 0, -- 当前使用的账号索引
    status TEXT DEFAULT 'pending',    -- pending, running, paused, completed, cancelled, error
    total_count INTEGER DEFAULT 0,
    sent_count INTEGER DEFAULT 0,
    failed_count INTEGER DEFAULT 0,
    skipped_count INTEGER DEFAULT 0,  -- 因时间限制跳过数量
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    cancel_requested INTEGER DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT chk_cancel_requested CHECK (cancel_requested IN (0,1)),
    CONSTRAINT chk_skip_enabled CHECK (skip_enabled IN (0,1))
);

-- 邮件发送日志表
CREATE TABLE IF NOT EXISTS uni_email_log (
    log_id SERIAL PRIMARY KEY,
    task_id TEXT NOT NULL,
    contact_id TEXT NOT NULL,
    email TEXT NOT NULL,
    company_name TEXT,
    sent_at TIMESTAMP DEFAULT NOW(),
    status TEXT DEFAULT 'sent',
    error_message TEXT,
    FOREIGN KEY (task_id) REFERENCES uni_email_task(task_id) ON DELETE CASCADE,
    FOREIGN KEY (contact_id) REFERENCES uni_contact(contact_id) ON DELETE CASCADE
);

-- Email Task Manager 索引
CREATE INDEX IF NOT EXISTS idx_task_status ON uni_email_task(status);
CREATE INDEX IF NOT EXISTS idx_task_account ON uni_email_task(account_id);
CREATE INDEX IF NOT EXISTS idx_log_task ON uni_email_log(task_id);
CREATE INDEX IF NOT EXISTS idx_log_status ON uni_email_log(status);
CREATE INDEX IF NOT EXISTS idx_log_contact ON uni_email_log(contact_id);
CREATE INDEX IF NOT EXISTS idx_account_email ON uni_email_account(email);
CREATE INDEX IF NOT EXISTS idx_group_name ON uni_contact_group(group_name);
CREATE INDEX IF NOT EXISTS idx_group_rel_group ON uni_contact_group_rel(group_id);
CREATE INDEX IF NOT EXISTS idx_group_rel_contact ON uni_contact_group_rel(contact_id);

-- 表结构升级（新增字段）
ALTER TABLE uni_contact_group ADD COLUMN IF NOT EXISTS group_type TEXT DEFAULT 'dynamic';
ALTER TABLE uni_contact_group ADD COLUMN IF NOT EXISTS email_list TEXT;
ALTER TABLE uni_contact_group ADD COLUMN IF NOT EXISTS manual_emails TEXT;

-- 客户订单表添加总价(JPY)字段
ALTER TABLE uni_order_manager ADD COLUMN IF NOT EXISTS total_price_jpy DOUBLE PRECISION DEFAULT 0;

-- 邮件任务表添加跳过规则字段
ALTER TABLE uni_email_task ADD COLUMN IF NOT EXISTS skip_enabled INTEGER DEFAULT 1;
ALTER TABLE uni_email_task ADD COLUMN IF NOT EXISTS skip_days INTEGER DEFAULT 7;
ALTER TABLE uni_email_task ADD COLUMN IF NOT EXISTS skipped_count INTEGER DEFAULT 0;

-- 邮件任务表添加多账号轮换字段
ALTER TABLE uni_email_task ADD COLUMN IF NOT EXISTS account_ids TEXT;
ALTER TABLE uni_email_task ADD COLUMN IF NOT EXISTS daily_limit_per_account INTEGER DEFAULT 1800;
ALTER TABLE uni_email_task ADD COLUMN IF NOT EXISTS current_account_index INTEGER DEFAULT 0;

-- 数据迁移：将旧的account_id转为account_ids JSON数组
UPDATE uni_email_task SET account_ids = json_build_array(account_id) WHERE account_ids IS NULL AND account_id IS NOT NULL;

-- ============ 银行流水管理表（财务管理模块） ============

-- 银行流水主表
CREATE TABLE IF NOT EXISTS uni_bank_transaction (
    transaction_id TEXT PRIMARY KEY,              -- 格式: BT-YYYYMMDDHHMMSS-XXXX
    transaction_time TIMESTAMP NOT NULL,         -- 银行交易时间
    transaction_no TEXT NOT NULL,                 -- 银行流水号（去重依据1）
    ledger_no TEXT,                               -- 记账流水号（去重依据2）
    transaction_type TEXT NOT NULL,               -- 交易类型：收入/支出/转账等
    transaction_detail TEXT,                      -- 交易详情描述
    currency TEXT DEFAULT 'CNY',                  -- 货币类型
    transaction_amount DOUBLE PRECISION NOT NULL, -- 交易金额（正数）
    balance DOUBLE PRECISION,                     -- 交易后余额
    payer_name TEXT,                              -- 付款方名称
    payer_bank TEXT,                              -- 付款方银行
    payer_account TEXT,                           -- 付款方账号
    payee_name TEXT,                              -- 收款方名称
    payee_bank TEXT,                              -- 收款方银行
    payee_account TEXT,                           -- 收款方账号
    payee_remark_name TEXT,                       -- 收款方备注名
    remark_text TEXT,                             -- 流水备注信息
    internal_remark TEXT,                         -- 内部备注（人工添加）
    source_file TEXT,                             -- 来源文件名
    import_batch TEXT NOT NULL,                   -- 导入批次号（格式: BATCH-YYYYMMDDHHMM-XXX）
    is_matched INTEGER DEFAULT 0,                 -- 匹配状态：0=未匹配，1=完全匹配，2=部分匹配
    matched_amount DOUBLE PRECISION DEFAULT 0,    -- 已匹配金额累计
    created_at TIMESTAMP DEFAULT NOW(),

    CONSTRAINT chk_bt_is_matched CHECK (is_matched IN (0, 1, 2)),
    CONSTRAINT chk_bt_amount_positive CHECK (transaction_amount > 0),
    CONSTRAINT uq_bt_transaction_dedup UNIQUE(transaction_no, ledger_no)  -- 去重约束
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
    ledger_id TEXT PRIMARY KEY,                   -- 格式: LED-YYYYMMDDHHMMSS-XXXX
    transaction_id TEXT NOT NULL,                 -- 关联流水ID
    manager_id TEXT NOT NULL,                     -- 关联客户订单ID
    allocation_amount DOUBLE PRECISION NOT NULL,  -- 分配金额
    is_primary INTEGER DEFAULT 0,                 -- 是否主要匹配：0=否，1=是
    match_type TEXT DEFAULT 'manual',             -- 匹配类型：manual/auto/partial
    remark TEXT,                                  -- 备注
    created_by TEXT,                              -- 创建人（员工ID）
    created_at TIMESTAMP DEFAULT NOW(),

    FOREIGN KEY (transaction_id) REFERENCES uni_bank_transaction(transaction_id) ON DELETE CASCADE,
    FOREIGN KEY (manager_id) REFERENCES uni_order_manager(manager_id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES uni_emp(emp_id) ON DELETE SET NULL,

    CONSTRAINT chk_bl_allocation_positive CHECK (allocation_amount > 0),
    CONSTRAINT chk_bl_is_primary CHECK (is_primary IN (0, 1)),
    CONSTRAINT chk_bl_match_type CHECK (match_type IN ('manual', 'auto', 'partial')),
    CONSTRAINT uq_bl_ledger_unique UNIQUE(transaction_id, manager_id)  -- 防止重复关联
);

-- 台账关联表索引
CREATE INDEX IF NOT EXISTS idx_bl_tx ON uni_bank_ledger(transaction_id);
CREATE INDEX IF NOT EXISTS idx_bl_manager ON uni_bank_ledger(manager_id);
CREATE INDEX IF NOT EXISTS idx_bl_primary ON uni_bank_ledger(is_primary) WHERE is_primary = 1;
CREATE INDEX IF NOT EXISTS idx_bl_date ON uni_bank_ledger(created_at DESC);

-- 邮件模板表 (开发信模板管理)
CREATE TABLE IF NOT EXISTS uni_email_template (
    template_id TEXT PRIMARY KEY,         -- TPL+时间戳格式
    template_name TEXT NOT NULL,          -- 模板名称
    subject TEXT NOT NULL,                -- 邮件主题模板
    body TEXT NOT NULL,                   -- HTML邮件内容模板
    created_by TEXT NOT NULL,             -- 创建人(员工ID)
    created_at TIMESTAMP DEFAULT NOW(),
    FOREIGN KEY (created_by) REFERENCES uni_emp(emp_id) ON DELETE CASCADE
);

-- 邮件模板索引
CREATE INDEX IF NOT EXISTS idx_template_created_by ON uni_email_template(created_by);
CREATE INDEX IF NOT EXISTS idx_template_name ON uni_email_template(template_name);
"""

# 默认管理员插入语句
PG_DEFAULT_ADMIN = """
INSERT INTO uni_emp (emp_id, emp_name, account, password, rule)
VALUES ('000', '超级管理员', 'Admin', '088426ba2d6e02949f54ef1e62a2aa73', '3')
ON CONFLICT (emp_id) DO NOTHING;
"""