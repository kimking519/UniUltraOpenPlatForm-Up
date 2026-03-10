---
name: order-ci-generator-kr
description: >
  根据销售订单生成 Commercial Invoice (CI) 韩国版文件。
  当用户提到"生成CI"、"CI文件"、"商业发票"、"Commercial Invoice"、
  或在订单管理页面选择订单后要求生成CI时使用此skill。
---

# 订单CI生成器 (韩国版)

根据选中的销售订单信息，自动生成 Commercial Invoice Excel 文件。

## 环境配置

使用前需设置环境变量（可选，有默认值）：

```bash
# Windows (PowerShell)
$env:UNIULTRA_DB_PATH = "E:\WorkPlace\7_AI_APP\UniUltraOpenPlatForm\uni_platform.db"
$env:UNIULTRA_OUTPUT_DIR = "E:\1_Business\1_Auto"

# Linux/WSL
export UNIULTRA_DB_PATH="/mnt/e/WorkPlace/7_AI_APP/UniUltraOpenPlatForm/uni_platform.db"
export UNIULTRA_OUTPUT_DIR="/mnt/e/1_Business/1_Auto"
```

详见 `openclaw_skills/ENV_SETUP.md`。

---

## 工作流程

### 第一步：获取订单数据

通过桥接层查询选中订单的完整信息，包括：
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
- 数据行：动态插入，包含型号、描述、HS Code、数量、单价(韩元)、总价
- 固定值：DESCRIPTION OF GOODS = "集成电路/IC"，HS Code = "8542399000"
- 合计行：自动计算总数量和总金额

### 第四步：执行脚本

```bash
python scripts/make_ci.py --order_ids "d00001,d00002"
```

---

## 示例

### 输入示例
```
订单编号: d00001, d00002, d00003
```

### 输出示例
```
成功 CI生成成功！
Excel路径: E:\1_Business\1_Auto\TAEJU\20260307\COMMERCIAL INVOICE_TAEJU_UNI20260307103000.xlsx
订单条数: 3
客户: TAEJU
Invoice No.: UNI2026030710
```

---

## 使用的桥接层接口

| 接口 | 用途 |
|------|------|
| `get_orders_for_ci()` | 获取订单列表（含客户信息） |
| `get_exchange_rates()` | 获取汇率 |

---

## 注意事项

- 订单必须属于同一客户，否则拒绝生成
- 如果订单没有关联报价单，QTY字段使用需求数量(inquiry_qty)
- 动态行数：根据订单数量自动插入或删除行
- 价格使用韩元(KRW)，从订单的price_kwr字段获取

---

## 目录结构

```
order-ci-generator-kr/
├── SKILL.md                    # 本文档
├── scripts/
│   ├── make_ci.py              # CI生成脚本
│   ├── excel_to_pdf.py         # PDF转换
│   └── create_ci_template.py   # 模板创建工具
└── template/
    ├── CI_template_header.xlsx # CI表头模板
    ├── CI_template_footer.xlsx # CI底部模板 (Total+印章)
    └── CI_template.xlsx        # 完整模板
```

---

## 模板说明

采用**切分模板模式**，将CI模板分为两部分：

| 模板文件 | 内容 |
|----------|------|
| CI_template_header.xlsx | 表头 + 数据行模板 |
| CI_template_footer.xlsx | Total + 印章 |