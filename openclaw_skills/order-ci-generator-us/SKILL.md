---
name: order-ci-generator-us
description: >
  根据销售订单生成 Commercial Invoice (CI) 美元版文件。
  当用户提到"生成CI-US"、"CI美元版"、"商业发票美元版"、"Commercial Invoice USD"、
  或在订单管理页面选择订单后要求生成美元CI时使用此skill。
  此skill专用于美国市场，输出美元计价的CI文件。
---

# 订单CI生成器 (美元版)

根据选中的销售订单信息，自动生成 Commercial Invoice Excel 文件（美元版）。

---

## 前置条件

- Python 3.x
- openpyxl 库 (`pip install openpyxl`)
- SQLite 数据库访问权限

---

## 工作流程

### 第一步：获取订单数据

从数据库查询选中订单的完整信息，包括：
- 订单基本信息（型号、品牌、价格）
- 客户信息（联系人、公司英文名、地址、邮箱、电话、国家）
- 关联报价信息（数量）

### 第二步：数据验证

- 检查所有订单是否属于同一客户
- 验证必要字段是否完整

### 第三步：生成CI文件

基于模板填充数据：
- 头部信息：Invoice No.、日期
- 客户信息：公司英文名、联系人、国家、电话、地址
- 数据行：动态插入，包含型号、描述、HS Code、数量、单价(美元)、总价
- 固定值：DESCRIPTION OF GOODS = "集成电路/IC"，HS Code = "8542399000"
- 合计行：自动计算总数量和总金额

### 第四步：输出

- 输出目录：`E:\1_Business\1_Auto\{客户名}\{日期yyyymmdd}`
- 文件名：`COMMERCIAL INVOICE_{客户名}_UNI{yyyymmddhhmmss}.xlsx`

---

## 与CI-KR的区别

| 项目 | CI-KR (韩元版) | CI-US (美元版) |
|------|---------------|---------------|
| F12 表头 | Unit Price(KRW) 单价 | Unit Price(USD) 单价 |
| G12 表头 | Total (KRW) 总价 | Total (USD) 总价 |
| 单价来源 | price_kwr (或计算) | price_usd |
| 数字格式 | 整数 (#,##0) | 两位小数 (#,##0.00) |

---

## 示例

### 输入示例
```
订单编号: d00001, d00002, d00003
```

### 输出示例
```
文件路径: E:\1_Business\1_Auto\DELL\20260307\COMMERCIAL INVOICE_DELL_UNI20260307103000.xlsx
订单条数: 3
客户: DELL
Invoice No.: UNI2026030710
```

---

## 注意事项 / 边缘情况

- 订单必须属于同一客户，否则拒绝生成
- 如果订单没有关联报价单，QTY字段使用需求数量(inquiry_qty)
- 支持跨平台路径（Windows/WSL）
- 动态行数：根据订单数量自动插入或删除行
- 价格使用美元(USD)，从订单的price_usd字段获取

---

## 配置说明

配置文件位于 `config/db_config.json`：

| 配置项 | 说明 |
|--------|------|
| db_path_windows | Windows 数据库路径 |
| db_path_wsl | WSL 数据库路径 |
| output_base_windows | Windows 输出目录 |
| output_base_wsl | WSL 输出目录 |

环境变量 `SALE_CI_DB_PATH` 可覆盖数据库路径配置。

---

## 目录结构

```
order-ci-generator-us/
├── SKILL.md                       # 本文档
├── config/
│   └── db_config.json             # 配置文件
├── scripts/
│   └── make_ci_us.py              # CI生成脚本
└── template/
    ├── CI_template_header_US.xlsx # CI表头模板 (行1-15)
    ├── CI_template_footer_US.xlsx # CI底部模板 (Total+印章)
    └── CI_template_US.xlsx        # (旧模板，保留备用)
```

---

## 模板说明

采用**切分模板模式**，将CI模板分为两部分：

| 模板文件 | 内容 | 说明 |
|----------|------|------|
| CI_template_header_US.xlsx | 表头 + 数据行模板 | 行1-15，包含Invoice信息、客户信息、表头、3行数据模板 |
| CI_template_footer_US.xlsx | Total + 印章 | 3行，包含Total Qty、Total Amount、SHIPPER'S SIGNATURE和印章图片 |

**优势**：
- 印章图片位置固定在Footer模板中，不受动态插入数据行影响
- 图片尺寸保持一致，不会因行数变化而变形