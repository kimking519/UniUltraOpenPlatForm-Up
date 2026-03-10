---
name: sale-edit-needs
description: 修改需求管理表中的记录字段。当用户提到"修改需求"、"编辑询价"、"更新报价"、"改一下XX的单价"、"修改批号"、"交期改成X"、"把XX的数量改成Y"等场景时使用。
---

# Sale Edit Needs (API版本)

`sale-edit-needs` 是一个用于修改需求记录的自动化工具，通过自然语言理解将用户的修改意图转化为具体的字段更新操作。

## When to Use

在以下场景使用此 Skill：
- 客户要求修改已提交的需求信息
- 需要更新成本价、目标价等价格信息
- 修正型号、品牌等基本信息
- 更新批号、货期等交付信息

## Prerequisites

- Python 3.x 已安装
- 主应用 API 服务已启动 (`uvicorn main:app --host 0.0.0.0 --port 8000`)

## Field Mapping

| 用户描述 | 字段名 | 类型 |
|---------|--------|------|
| 型号/MPN | inquiry_mpn | Text |
| 报价型号 | quoted_mpn | Text |
| 品牌 | inquiry_brand | Text |
| 数量 | inquiry_qty | Integer |
| 成本价 | cost_price_rmb | Number |
| 目标价 | target_price_rmb | Number |
| 批号 | date_code | Text |
| 货期 | delivery_date | Text |
| 备注 | remark | Text |

## Usage Example

```bash
# 修改需求 x00028 的成本价为 10 元
python openclaw_skills/sale-edit-needs/scripts/edit_needs.py \
  --quote_id "x00028" --field "cost_price_rmb" --value "10"

# 修改批号为 "200+"
python openclaw_skills/sale-edit-needs/scripts/edit_needs.py \
  --quote_id "x00028" --field "date_code" --value "200+"
```

## API Endpoint

**单字段更新**: `POST /api/quote/update`
**请求体**: Form data with `quote_id`, `field`, `value`

## Error Handling

- **字段不存在**: 返回 "非法字段" 错误
- **数据类型错误**: 返回 "必须是数字" 错误  
- **权限不足**: 仅管理员可修改某些字段

## Notes

- 每次只能修改一个字段，需要多次调用修改多个字段
- 数字字段会自动验证并转换类型
- 文本字段会自动清理多余空格