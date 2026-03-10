---
name: buyer-tran-order
description: >
  报价转入订单。当用户提到"转订单"、"报价转订单"、"下单"、
  "把这个报价转成订单"、"创建订单"、"转入订单"等场景时使用。
---

# Buyer Tran Order

根据报价编号（`offer_id`）将报价记录（`uni_offer`）转入订单表（`uni_order`）。转入后源报价记录标记为"已转"。

## 环境配置

使用前需设置环境变量（可选，有默认值）：

```bash
# Windows (PowerShell)
$env:UNIULTRA_DB_PATH = "E:\WorkPlace\7_AI_APP\UniUltraOpenPlatForm\uni_platform.db"

# Linux/WSL
export UNIULTRA_DB_PATH="/mnt/e/WorkPlace/7_AI_APP/UniUltraOpenPlatForm/uni_platform.db"
```

详见 `openclaw_skills/ENV_SETUP.md`。

---

## 工作流程

### 第一步：解析用户输入

从用户的自然语言输入中提取以下参数：

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `offer_id` | ✅ | 报价编号 | "b00015" |

### 第二步：执行转入

通过桥接层访问数据库，无直接 SQL：

```bash
python scripts/tran_order.py --offer_id "b00015"
```

### 第三步：输出结果

将脚本输出直接返回给用户。

**转入规则：**
- 新 `order_id` / `order_no` = `d` + 5位递增数字（如 `d00001`）
- `order_date` = 当天
- `cli_id` 通过 `uni_offer.quote_id` → `uni_quote.cli_id` 自动关联
- `inquiry_mpn` = `offer.quoted_mpn`（优先）或 `offer.inquiry_mpn`
- `price_rmb` = `offer.offer_price_rmb`
- 源报价记录 `is_transferred` → "已转"

---

## 示例

### 输入示例

```
帮我把 b00015 转成订单
```

```
报价 b00015 下单
```

### 输出示例 — 成功

```
✅ 转入订单成功！
   报价编号: b00015
   订单编号: d00008
   客    户: 三星电子
   型    号: TPS54331DR
   报价(RMB): ¥3.85
```

### 输出示例 — 已转过

```
❌ 转入失败: 报价 b00015 已存在销售订单，不可重复转入。
```

---

## 使用的桥接层接口

| 接口 | 用途 |
|------|------|
| `get_offer_by_id()` | 查询报价详情 |
| `get_quote_by_id()` | 查询关联询价 |
| `add_order()` | 创建订单 |
| `mark_offer_transferred()` | 标记已转 |

---

## 注意事项

- **已转记录**：同一 `offer_id` 不可重复转入订单
- **编号不存在**：输出明确错误提示
- **客户 ID 无法确定**：当 `uni_offer.quote_id` 为空或关联不到客户时，返回错误提示

---

## 目录结构

```
buyer-tran-order/
├── SKILL.md                    # 本文档
└── scripts/
    └── tran_order.py           # 转入脚本
```