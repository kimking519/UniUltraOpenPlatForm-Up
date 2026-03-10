# 数据库表结构文档

数据库：SQLite3
双环境支持：`uni_platform.db` (生产), `uni_platform_dev.db` (开发)

---

## 表概览

| 表名 | 描述 | 主要功能 |
|------|------|----------|
| uni_daily | 汇率表 | 记录每日 KRW/USD 汇率 |
| uni_emp | 员工表 | 系统用户、权限管理 |
| uni_cli | 客户表 | 客户信息管理 |
| uni_quote | 询价表 | 客户询价记录 |
| uni_vendor | 供应商表 | 供应商信息管理 |
| uni_offer | 报价表 | 给客户的报价记录 |
| uni_order | 订单表 | 销售订单记录 |
| uni_buy | 采购表 | 采购记录跟踪 |

---

## 详细表结构

### 1. uni_daily (汇率表)

记录每日外汇汇率，用于多币种价格换算。

| 字段 | 类型 | 约束 | 描述 |
|------|------|------|------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | 自增 ID |
| record_date | TEXT | NOT NULL | 记录日期 (YYYY-MM-DD) |
| currency_code | INTEGER | NOT NULL | 币种代码 (1=USD, 2=KRW) |
| exchange_rate | REAL | NOT NULL | 汇率 |
| created_at | DATETIME | DEFAULT now | 创建时间 |

**唯一约束**: (record_date, currency_code)

**示例数据**:
```sql
INSERT INTO uni_daily (record_date, currency_code, exchange_rate)
VALUES ('2026-02-28', 1, 7.25),  -- USD: 1 CNY = 7.25 KRW? No, 1 USD = 7.25 CNY
       ('2026-02-28', 2, 180.5); -- KRW: 1 CNY = 180.5 KRW
```

---

### 2. uni_emp (员工表)

系统用户账户和权限管理。

| 字段 | 类型 | 约束 | 描述 |
|------|------|------|------|
| emp_id | TEXT | PRIMARY KEY | 员工编号 (3 位数字，如 001) |
| department | TEXT | - | 部门 |
| position | TEXT | - | 职位 |
| emp_name | TEXT | NOT NULL | 员工姓名 |
| contact | TEXT | - | 联系方式 |
| account | TEXT | UNIQUE NOT NULL | 登录账号 |
| password | TEXT | NOT NULL | 密码 (MD5 加密) |
| hire_date | TEXT | - | 入职日期 |
| rule | TEXT | NOT NULL | 权限级别 (1:读，2:编辑，3:管理员，4:禁用) |
| remark | TEXT | - | 备注 |
| created_at | DATETIME | DEFAULT now | 创建时间 |

**默认管理员**:
```sql
INSERT INTO uni_emp (emp_id, emp_name, account, password, rule)
VALUES ('000', '超级管理员', 'Admin', '088426ba2d6e02949f54ef1e62a2aa73', '3');
-- 密码：uni519 的 MD5
```

---

### 3. uni_cli (客户表)

客户信息管理。

| 字段 | 类型 | 约束 | 描述 |
|------|------|------|------|
| cli_id | TEXT | PRIMARY KEY | 客户编号 (C001 格式) |
| cli_name | TEXT | NOT NULL | 客户名称 |
| cli_full_name | TEXT | - | 公司全名 |
| cli_name_en | TEXT | - | 公司英文名 |
| contact_name | TEXT | - | 公司联系人 |
| address | TEXT | - | 公司地址 |
| region | TEXT | NOT NULL DEFAULT '韩国' | 地区 |
| credit_level | TEXT | DEFAULT 'A' | 信用等级 (A/B/C) |
| margin_rate | REAL | DEFAULT 10.0 | 利润率 (%) |
| emp_id | TEXT | NOT NULL | 负责员工编号 (外键) |
| website | TEXT | - | 网站 |
| payment_terms | TEXT | - | 付款条件 |
| email | TEXT | - | 邮箱 |
| phone | TEXT | - | 电话 |
| remark | TEXT | - | 备注 |
| created_at | DATETIME | DEFAULT now | 创建时间 |

**外键**: emp_id → uni_emp(emp_id) ON UPDATE CASCADE

---

### 4. uni_quote (询价表)

客户询价/需求记录。

| 字段 | 类型 | 约束 | 描述 |
|------|------|------|------|
| quote_id | TEXT | PRIMARY KEY | 询价编号 (Q+ 时间戳 +4 位随机) |
| quote_date | TEXT | - | 询价日期 |
| cli_id | TEXT | NOT NULL | 客户编号 (外键) |
| inquiry_mpn | TEXT | NOT NULL | 询型号 |
| quoted_mpn | TEXT | - | 报型号 (替代型号) |
| inquiry_brand | TEXT | - | 询品牌 |
| inquiry_qty | INTEGER | - | 询数量 |
| target_price_rmb | REAL | - | 目标价 (RMB) |
| cost_price_rmb | REAL | - | 成本价 (RMB) |
| date_code | TEXT | - | 批次号 |
| delivery_date | TEXT | - | 交期 |
| status | TEXT | DEFAULT '询价中' | 状态 |
| remark | TEXT | - | 备注 |
| is_transferred | TEXT | DEFAULT '未转' | 是否已转报价 |
| created_at | DATETIME | DEFAULT now | 创建时间 |

**外键**: cli_id → uni_cli(cli_id) ON UPDATE CASCADE

---

### 5. uni_vendor (供应商表)

供应商信息管理。

| 字段 | 类型 | 约束 | 描述 |
|------|------|------|------|
| vendor_id | TEXT | PRIMARY KEY | 供应商编号 (V001 格式) |
| vendor_name | TEXT | NOT NULL | 供应商名称 |
| address | TEXT | - | 地址 |
| qq | TEXT | - | QQ |
| wechat | TEXT | - | 微信 |
| email | TEXT | - | 邮箱 |
| remark | TEXT | - | 备注 |
| created_at | DATETIME | DEFAULT now | 创建时间 |

---

### 6. uni_offer (报价表)

给客户的正式报价记录。

| 字段 | 类型 | 约束 | 描述 |
|------|------|------|------|
| offer_id | TEXT | PRIMARY KEY | 报价编号 (O+ 时间戳 +4 位随机) |
| offer_date | TEXT | - | 报价日期 |
| quote_id | TEXT | UNIQUE | 关联询价 ID (外键) |
| inquiry_mpn | TEXT | - | 询型号 |
| quoted_mpn | TEXT | - | 报型号 |
| inquiry_brand | TEXT | - | 询品牌 |
| quoted_brand | TEXT | - | 报品牌 |
| inquiry_qty | INTEGER | - | 询数量 |
| actual_qty | INTEGER | - | 实报数量 |
| quoted_qty | INTEGER | - | 报价数量 |
| cost_price_rmb | REAL | - | 成本价 (RMB) |
| offer_price_rmb | REAL | - | 报价 (RMB) |
| price_kwr | REAL | - | 报价 (KRW) |
| price_usd | REAL | - | 报价 (USD) |
| platform | TEXT | - | 货源平台 |
| vendor_id | TEXT | - | 供应商 ID (外键) |
| date_code | TEXT | - | 批次号 |
| delivery_date | TEXT | - | 交期 |
| emp_id | TEXT | NOT NULL | 业务员 ID (外键) |
| offer_statement | TEXT | - | 报价条款 |
| remark | TEXT | - | 备注 |
| is_transferred | TEXT | DEFAULT '未转' | 是否已转订单 |
| created_at | DATETIME | DEFAULT now | 创建时间 |

**外键**:
- quote_id → uni_quote(quote_id)
- vendor_id → uni_vendor(vendor_id)
- emp_id → uni_emp(emp_id)

---

### 7. uni_order (订单表)

销售订单记录。

| 字段 | 类型 | 约束 | 描述 |
|------|------|------|------|
| order_id | TEXT | PRIMARY KEY | 订单编号 (SO+ 时间戳 +4 位随机) |
| order_no | TEXT | UNIQUE | 订单号 (UNI-客户名 -YYYYMMDDHH 格式) |
| order_date | TEXT | - | 订单日期 |
| cli_id | TEXT | NOT NULL | 客户编号 (外键) |
| offer_id | TEXT | - | 关联报价 ID (外键) |
| inquiry_mpn | TEXT | - | 型号 |
| inquiry_brand | TEXT | - | 品牌 |
| price_rmb | REAL | - | 单价 (RMB) |
| price_kwr | REAL | - | 单价 (KRW) |
| price_usd | REAL | - | 单价 (USD) |
| cost_price_rmb | REAL | - | 成本价 (RMB) |
| is_finished | INTEGER | DEFAULT 0 | 是否完成 (0/1) |
| is_paid | INTEGER | DEFAULT 0 | 是否付款 (0/1) |
| paid_amount | REAL | DEFAULT 0.0 | 已付金额 |
| return_status | TEXT | DEFAULT '正常' | 退货状态 |
| remark | TEXT | - | 备注 |
| is_transferred | TEXT | DEFAULT '未转' | 是否已转采购 |
| created_at | DATETIME | DEFAULT now | 创建时间 |

**外键**:
- cli_id → uni_cli(cli_id)
- offer_id → uni_offer(offer_id)

---

### 8. uni_buy (采购表)

采购记录和物流跟踪。

| 字段 | 类型 | 约束 | 描述 |
|------|------|------|------|
| buy_id | TEXT | PRIMARY KEY | 采购编号 (PU+ 时间戳 +4 位随机) |
| buy_date | TEXT | - | 采购日期 |
| order_id | TEXT | - | 关联订单 ID (外键) |
| vendor_id | TEXT | - | 供应商 ID (外键) |
| buy_mpn | TEXT | - | 采购型号 |
| buy_brand | TEXT | - | 采购品牌 |
| buy_price_rmb | REAL | - | 采购单价 (RMB) |
| buy_qty | INTEGER | - | 采购数量 |
| sales_price_rmb | REAL | - | 销售单价 (RMB) |
| total_amount | REAL | - | 总金额 |
| is_source_confirmed | INTEGER | DEFAULT 0 | 货源已确认 |
| is_ordered | INTEGER | DEFAULT 0 | 已下单 |
| is_instock | INTEGER | DEFAULT 0 | 已入库 |
| is_shipped | INTEGER | DEFAULT 0 | 已发货 |
| remark | TEXT | - | 备注 |
| created_at | DATETIME | DEFAULT now | 创建时间 |

**外键**:
- order_id → uni_order(order_id)
- vendor_id → uni_vendor(vendor_id)

---

## ER 关系图

```
┌─────────────┐
│  uni_emp    │
│  (员工表)   │
└──────┬──────┘
       │
       ├──────────────────┐
       │                  │
       ▼                  ▼
┌─────────────┐    ┌─────────────┐
│  uni_cli    │    │  uni_vendor │
│  (客户表)   │    │  (供应商表) │
└──────┬──────┘    └──────┬──────┘
       │                  │
       ▼                  │
┌─────────────┐           │
│ uni_quote   │           │
│  (询价表)   │           │
└──────┬──────┘           │
       │                  │
       ▼                  │
┌─────────────┐           │
│  uni_offer  │◄──────────┤
│  (报价表)   │           │
└──────┬──────┘           │
       │                  │
       ▼                  │
┌─────────────┐           │
│  uni_order  │           │
│  (订单表)   │           │
└──────┬──────┘           │
       │                  │
       └──────────────────┘
                  │
                  ▼
           ┌─────────────┐
           │   uni_buy   │
           │  (采购表)   │
           └─────────────┘
```

---

## 索引建议

当前未显式创建索引，建议为以下字段添加索引以提升查询性能：

```sql
-- 高频查询字段
CREATE INDEX IF NOT EXISTS idx_cli_name ON uni_cli(cli_name);
CREATE INDEX IF NOT EXISTS idx_quote_date ON uni_quote(quote_date);
CREATE INDEX IF NOT EXISTS idx_offer_date ON uni_offer(offer_date);
CREATE INDEX IF NOT EXISTS idx_order_date ON uni_order(order_date);
CREATE INDEX IF NOT EXISTS idx_buy_date ON uni_buy(buy_date);

-- 外键字段
CREATE INDEX IF NOT EXISTS idx_quote_cli ON uni_quote(cli_id);
CREATE INDEX IF NOT EXISTS idx_offer_quote ON uni_offer(quote_id);
CREATE INDEX IF NOT EXISTS idx_order_cli ON uni_order(cli_id);
CREATE INDEX IF NOT EXISTS idx_buy_order ON uni_buy(order_id);
```

---

*最后更新：2026-02-28*
