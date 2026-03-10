---
name: sale-input-needs
description: 自动从销售聊天、邮件或日常笔记中提取电子元组件需求（MPN、数量、价格、客户），并快速录入 UniUltra 平台的"需求管理"表。适用于快速处理非结构化询价信息。
---

# Sale Input Needs

`sale-input-needs` 是一个专为销售团队设计的自动化工具，它能通过自然语言处理能力将口头或文字的需求描述快速转化为系统内的询价记录。

## When to Use

在以下场景使用此 Skill：
- 从微信聊天记录中快速抓取客户发来的询价单
- 将邮件中的零件列表快速导入系统，而无需逐条手动录入
- 在与客户通话后，通过简短的文字总结快速归档需求
- 处理包含多个型号和不同客户的复杂询价信息

## 环境配置

使用前需设置环境变量（可选，有默认值）：

```bash
# Windows (PowerShell)
$env:UNIULTRA_DB_PATH = "E:\WorkPlace\7_AI_APP\UniUltraOpenPlatForm\uni_platform.db"

# Linux/WSL
export UNIULTRA_DB_PATH="/mnt/e/WorkPlace/7_AI_APP/UniUltraOpenPlatForm/uni_platform.db"
```

详见 `openclaw_skills/ENV_SETUP.md`。

## Quick Start

### 1. 识别需求数据

从用户输入中提取以下结构化信息：
- **cli_id/cli_name**: 客户 ID 或名称（如 C001 或 "三星"）
- **mpn**: 型号（必须为大写，如 TPS54331DR）
- **qty**: 需求数量
- **brand**: 指定品牌（可选）
- **price**: 客户目标价（可选）
- **remark**: 备注信息

### 2. 执行自动化录入

通过桥接层访问数据库，无直接 SQL：

```bash
python scripts/auto_input.py --cli_name "三星" --mpn "STM32F103" --qty 1000
```

## Batch Processing

如果有多个型号，可以使用 `--text` 参数：

```bash
python scripts/auto_input.py --cli_name "客户A" --text "TPS54331 100 TI
STM32F103 500 ST"
```

## 工作流程

```
1. 接收输入 → 销售粘贴聊天记录或描述
2. 数据建模 → 提取 (mpn, qty, price, cli_name)
3. 校验数据 → 转换型号为全大写，查找客户ID
4. 运行脚本 → 通过桥接层调用 add_quote()
5. 结果反馈 → 返回已生成的需求编号
```

## 使用的桥接层接口

| 接口 | 用途 |
|------|------|
| `get_cli_id_by_name()` | 根据客户名称查找ID |
| `add_quote()` | 添加询价记录 |

## 注意事项

- **型号纠错**：电子行业型号对字母非常敏感，录入前请务必去除多余的空格并转换为大写。
- **缺失客户**：如果用户未指定客户名，请先询问。
- **批量处理**：如果聊天记录包含多个型号，使用 `--text` 模式。

## 目录结构

```
sale-input-needs/
├── SKILL.md                    # 本文档
├── scripts/
│   └── auto_input.py           # 自动录入脚本
└── examples/
    └── extract_chat.md         # 示例文档
```