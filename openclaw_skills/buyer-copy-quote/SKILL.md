---
name: buyer-copy-quote
description: >
  打印发给客户的报价单。当用户提到"打印报价"、"复制报价"、"报价单"、
  "发给客户的报价"、"帮我出一份报价"、"生成报价单"、"报价格式"等场景时使用。
  即使用户没有明确说"打印报价"，只要意图是生成客户可见的报价文本，
  就应当触发此 Skill。
---

# Buyer Copy Quote

查询指定客户的报价记录（`uni_offer`），按固定格式输出可直接发给客户的报价单文本。

---

## 前置条件

- **Python 3.x** 已安装
- 数据库路径已配置在 `openclaw_skills/buyer-copy-quote/config/db_config_20260301185153.json` 中
- 如在 WSL 下运行，确保数据库通过 `/mnt/` 挂载点可访问

> ⚠️ 出于安全考虑，数据库路径等关键配置以独立文件形式存放，不硬编码在脚本中。
> 配置文件位置：`openclaw_skills/buyer-copy-quote/config/db_config_20260301185153.json`

**WSL 环境变量动态覆盖（可选）：**

```bash
echo 'export COPY_QUOTE_DB_PATH="/home/kim/workspace/UniUltraOpenPlatForm/uni_platform.db"' >> ~/.bashrc
source ~/.bashrc
```

**Windows PowerShell 环境变量（可选）：**

```powershell
[Environment]::SetEnvironmentVariable("COPY_QUOTE_DB_PATH", "E:\WorkPlace\7_AI_APP\UniUltraOpenPlatFormCls\uni_platform.db", "User")
```

---

## 工作流程

### 第一步：解析用户输入

从用户的自然语言输入中提取以下参数：

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `cli_name` | ✅ | 客户名称（支持模糊匹配） | "三星"、"SK海力士" |
| `offer_ids` | ❌ | 报价编号，多个用逗号分隔 | "b00015,b00016" |
| `date` | ❌ | 查询日期，默认当天 | "2026-03-01" |
| `days` | ❌ | 最近N天 | 7 |
| `start_date` / `end_date` | ❌ | 日期范围 | "2026-02-01" ~ "2026-02-28" |

### 第二步：执行查询并格式化

调用脚本生成报价单：

```bash
# Windows 环境
python openclaw_skills/buyer-copy-quote/scripts/copy_quote_20260301185153.py \
  --cli_name "三星" --date "2026-03-01"

# WSL 环境
python3 openclaw_skills/buyer-copy-quote/scripts/copy_quote_20260301185153.py \
  --cli_name "三星" --date "2026-03-01"

# 指定报价编号
python3 openclaw_skills/buyer-copy-quote/scripts/copy_quote_20260301185153.py \
  --cli_name "三星" --offer_ids "b00015,b00016"

# 最近7天
python3 openclaw_skills/buyer-copy-quote/scripts/copy_quote_20260301185153.py \
  --cli_name "三星" --days 7
```

### 第三步：输出结果

将脚本输出的格式化报价单文本直接返回给用户，用户可直接复制发给客户。

---

## 示例

### 输入示例

```
帮我打印三星今天的报价单
```

```
出一份 SK海力士 b00015 的报价
```

### 输出示例

```
================
Model：TPS54331DR
Brand：TI
Amount：1000pcs
Price(KRW)：₩693
DC：2526+
LeadTime：现货
Remark：—
================
Model：STM32F103C8T6
Brand：ST
Amount：500pcs
Price(KRW)：₩1440
DC：2024+
LeadTime：2周
Remark：客户催单
================
```

### 无记录时的输出

```
📭 客户 [三星电子] 在 2026-03-01 暂无报价记录。
```

---

## 注意事项 / 边缘情况

- **客户名不存在**：提示 `⚠️ 未找到匹配的客户`
- **多个匹配客户**：列出所有匹配项并依次输出
- **结果为空**：提示"暂无报价记录"
- **Price(KRW) 为 0**：如 `price_kwr` 为 0，显示 `₩0`
- **字段为空**：空字段显示 `—`

---

## 参考资源

- `scripts/copy_quote_20260301185153.py` — 核心脚本
- `config/db_config_20260301185153.json` — 数据库路径配置
- 环境变量: `COPY_QUOTE_DB_PATH`（可选覆盖）
- 关联 Skill: `buyer-query-quote` — 查询报价总览（内部格式，非客户格式）
- 数据表: `uni_offer`（报价表）、`uni_quote`（需求表）、`uni_cli`（客户表）
