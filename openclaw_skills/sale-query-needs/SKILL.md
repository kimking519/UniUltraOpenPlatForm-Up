---
name: sale-query-needs
description: >
  查询客户的询价需求记录。当用户提到"查询询价"、"查看需求"、"XX客户今天有哪些询价"、
  "帮我看看XX的需求"、"查一下XX的询价记录"等场景时使用。
  即使用户没有明确说"查询"，只要意图是了解某个客户的询价情况，就应当触发此 Skill。
---

# Sale Query Needs

`sale-query-needs` 是一个销售查询工具，用于快速查看指定客户在某天的所有询价需求记录。

## 前置条件

- Python 3.x
- 数据库配置文件 `config/db_config.json` 已正确设置
- 如果在 WSL 下运行，需通过 `/mnt/` 挂载点访问 Windows 目录

## 环境配置

### 数据库路径配置

配置文件位于 `config/db_config.json`:

```json
{
  "db_path_windows": "E:\\WorkPlace\\7_AI_APP\\UniUltraOpenPlatFormCls\\uni_platform.db",
  "db_path_wsl": "/home/kim/workspace/UniUltraOpenPlatForm/uni_platform.db"
}
```

### 环境变量（可选）

可以通过环境变量覆盖配置文件：

```bash
# Windows
set SALE_QUERY_NEEDS_DB_PATH=E:\WorkPlace\7_AI_APP\UniUltraOpenPlatFormCls\uni_platform.db

# WSL/Linux
export SALE_QUERY_NEEDS_DB_PATH=/home/kim/workspace/UniUltraOpenPlatForm/uni_platform.db
```

---

## 工作流程

### 第一步：解析用户输入

从用户的自然语言中提取以下参数：

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `cli_name` | ✅ | 客户名称（支持模糊匹配） | "XX科技"、"Unicorn" |
| `date` | ❌ | 查询日期，默认"今天" | "今天"、"昨天"、"2026-03-01" |

**日期格式支持**：
- `今天` / `今日` / `today` - 当天
- `昨天` / `昨日` / `yesterday` - 前一天
- `YYYY-MM-DD` - 指定日期（如 2026-03-01）

### 第二步：执行查询

使用脚本查询数据库：

```bash
# 查询某客户今天的询价
python openclaw_skills/sale-query-needs/scripts/query_needs.py --cli_name "客户名"

# 查询某客户昨天的询价
python openclaw_skills/sale-query-needs/scripts/query_needs.py --cli_name "客户名" --date "昨天"

# 查询某客户指定日期的询价
python openclaw_skills/sale-query-needs/scripts/query_needs.py --cli_name "客户名" --date "2026-03-01"
```

### 第三步：输出结果

返回格式化的询价记录列表，适合聊天窗口展示：

```
┌─ 客户: XX科技 | 日期: 2026-03-01 ─────────────
│ x00001... | TPS54331DR | TI | 1000 pcs | ¥3.50
│   → TPS54331DR | TI | 1000 pcs | 2024+ | 现货 | 未转 | 无
│ x00002... | STM32F103 | ST | 500 pcs | ¥8.00
│   → STM32F103 | ST | 500 pcs | 2025+ | 2周 | 未转 | 紧急
└─ 共 2 条记录 ──────────────────────────────
```

**输出字段说明**：
| 字段 | 说明 |
|------|------|
| 需求编号 | `quote_id`（截取前12位） |
| 型号 | `inquiry_mpn` 或 `quoted_mpn` |
| 品牌 | `inquiry_brand` |
| 数量 | `inquiry_qty` pcs |
| 目标价 | `target_price_rmb`（RMB） |
| combined_info | 报价型号 \| 品牌 \| 数量 \| 批号 \| 交期 \| 转单状态 \| 备注 |

---

## 示例

### 输入示例

```
# 简洁版
查一下XX科技今天的询价

# 详细版
帮我看看Unicorn昨天有哪些询价记录

# 指定日期
查询客户"ABC电子"在2026-03-01的需求
```

### 输出示例 — 成功

```
┌─ 客户: Unicorn | 日期: 2026-03-01 ─────────────
│ x00001... | TPS54331DR | TI | 1000 pcs | ¥3.50
│   → TPS54331DR | TI | 1000 pcs | 2024+ | 现货 | 未转 | 无
│ x00002... | STM32F103 | ST | 500 pcs | ¥8.00
│   → STM32F103 | ST | 500 pcs | 2025+ | 2周 | 未转 | 紧急
└─ 共 2 条记录 ──────────────────────────────
```

### 输出示例 — 无记录

```
[INFO] 客户 "XX科技" 在 2026-03-01 暂无询价记录
```

### 输出示例 — 失败

```
[FAIL] 数据库文件不存在: /path/to/uni_platform.db
```

---

## 注意事项

- **模糊匹配**：客户名支持模糊匹配，输入部分名称即可查询
- **大小写敏感**：客户名查询区分大小写（取决于数据库排序规则）
- **日期默认值**：如未指定日期，默认查询当天
- **空结果处理**：如查询结果为空，返回友好提示而非错误
- **多客户匹配**：如客户名匹配多个客户，会返回所有匹配客户的询价记录

---

## 参考资源

- 核心脚本: `openclaw_skills/sale-query-needs/scripts/query_needs.py`
- 配置文件: `openclaw_skills/sale-query-needs/config/db_config.json`
- 数据表: `uni_quote` (询价需求表), `uni_cli` (客户表)
- 关联 Skill: `sale-input-needs` (询价需求录入)