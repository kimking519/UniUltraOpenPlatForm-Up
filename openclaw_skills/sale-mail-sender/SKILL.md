---
name: sale-mail-sender
description: >
  发送邮件。当用户提到"发邮件"、"发送邮件"、"把这个发给XX"、
  "邮件发一下"、"发报价邮件"、"发给客户"等场景时使用。
  即使用户没有明确说"发送邮件"，只要意图是发送电子邮件，就应触发此 Skill。
---

# Sale Mail Sender

`sale-mail-sender` 是一个邮件发送工具，允许用户在 OpenClaw 聊天窗口中通过自然语言指令一键发送邮件。

## 前置条件

- Python 3.x
- SMTP 服务器配置（`config/mail_config.json`）
- 环境变量已设置（账号密码、默认收件人）

## 安全配置

> [!CAUTION]
> 账号密码、默认收件人等敏感信息**必须**配置在环境变量中，绝不可写入代码或配置文件！

### 环境变量设置

| 环境变量名 | 说明 | 示例 |
|-----------|------|------|
| `MAIL_SENDER_EMAIL` | 发件人邮箱 | `your_email@example.com` |
| `MAIL_SENDER_PASSWORD` | SMTP 授权码/应用专用密码 | `your_app_key` |
| `MAIL_DEFAULT_TO` | 默认收件人（多人用逗号分隔） | `joy@unicornsemi.com` |

**WSL 环境变量设置命令：**

```bash
# 写入 ~/.bashrc 永久生效
echo 'export MAIL_SENDER_EMAIL="your_email@example.com"' >> ~/.bashrc
echo 'export MAIL_SENDER_PASSWORD="your_app_key"' >> ~/.bashrc
echo 'export MAIL_DEFAULT_TO="joy@unicornsemi.com"' >> ~/.bashrc

# 立即生效
source ~/.bashrc

# 验证
echo $MAIL_SENDER_EMAIL
```

> [!IMPORTANT]
> - 建议使用 SMTP **授权码/应用专用密码**，而非登录密码
> - 如使用 zsh，请将 `~/.bashrc` 替换为 `~/.zshrc`

### SMTP 服务器配置

配置文件位于 `config/mail_config.json`（不包含敏感信息）：

```json
{
  "smtp_host": "smtp.example.com",
  "smtp_port": 465,
  "smtp_ssl": true,
  "sender_name": "Unicorn"
}
```

---

## 工作流程

### 第一步：解析用户输入

从用户的自然语言中提取以下参数：

| 参数 | 必填 | 默认值 | 说明 | 示例 |
|------|------|--------|------|------|
| `--to` / `-t` | ❌ | 环境变量 `MAIL_DEFAULT_TO` | 收件人（多人用逗号分隔） | "a@x.com,b@x.com" |
| `--cc` / `-c` | ❌ | 空 | 抄送人（多人用逗号分隔） | "c@x.com" |
| `--subject` / `-s` | ❌ | `Unicorn_YYYYMMDD_HHmmss` | 邮件标题 | "报价汇总" |
| `--body` / `-b` | ❌ | 空 | 邮件正文（支持纯文本或 HTML） | "请查收附件" |
| `--attachment` / `-a` | ❌ | 无 | 附件路径（多个用逗号分隔） | "file.xlsx" |

### 第二步：发送邮件

```bash
# 最简发送（使用默认值）
python openclaw_skills/sale-mail-sender/scripts/send_mail.py

# 指定收件人和主题
python openclaw_skills/sale-mail-sender/scripts/send_mail.py \
  --to "xxx@example.com" --subject "报价汇总"

# 带正文
python openclaw_skills/sale-mail-sender/scripts/send_mail.py \
  --to "xxx@example.com" --body "这是邮件正文内容"

# 带附件
python openclaw_skills/sale-mail-sender/scripts/send_mail.py \
  --to "xxx@example.com" --attachment "path/to/file.xlsx"

# 完整示例
python openclaw_skills/sale-mail-sender/scripts/send_mail.py \
  --to "a@x.com,b@x.com" \
  --cc "c@x.com" \
  --subject "报价汇总" \
  --body "请查收附件" \
  --attachment "file1.xlsx,file2.pdf"
```

### 第三步：反馈结果

- ✅ 成功：`[OK] 邮件发送成功！收件人: xxx@xxx.com, 主题: Unicorn_20260301_132805`
- ❌ 失败：`[FAIL] 邮件发送失败: [具体错误原因]`

---

## 示例

### 输入示例

```
# 最简发送
发一封邮件

# 指定收件人
发邮件给 joy@unicornsemi.com

# 带主题和正文
给 xxx@xxx.com 发一封邮件，主题是报价汇总，正文是请查收附件

# 带附件
把这个 Excel 文件发送给 xxx@xxx.com，主题是报价单

# 完整指令
发邮件给 a@x.com，抄送 b@x.com，主题是报价，正文是请查收，附件是 /path/to/file.xlsx
```

### 输出示例 — 成功

```
[INFO] 准备发送邮件...
       收件人: xxx@example.com
       主题: 报价汇总
       附件: 1 个文件
[OK] 邮件发送成功！收件人: xxx@example.com, 主题: 报价汇总
```

### 输出示例 — 失败（环境变量未设置）

```
[FAIL] 环境变量未设置，请先配置：
       export MAIL_SENDER_EMAIL='your_email@example.com'
       export MAIL_SENDER_PASSWORD='your_app_key'
```

### 输出示例 — 失败（SMTP 认证失败）

```
[FAIL] SMTP 认证失败：请检查邮箱和授权码是否正确
```

---

## 注意事项

- **敏感信息隔离**：账号密码、默认收件人必须配置在环境变量中
- **授权码**：建议使用 SMTP 授权码/应用专用密码，而非登录密码
- **默认标题**：如未指定主题，自动生成 `Unicorn_YYYYMMDD_HHmmss` 格式
- **附件验证**：发送前会检查附件文件是否存在，不存在则提示
- **发送确认**：发送前会显示收件人、主题等信息供确认
- **多人收件**：收件人、抄送人支持多人，用逗号分隔
- **路径转换**：自动处理 Windows/WSL 路径格式

---

## 参考资源

- 核心脚本: `openclaw_skills/sale-mail-sender/scripts/send_mail.py`
- 配置文件: `openclaw_skills/sale-mail-sender/config/mail_config.json`
- 环境变量: `MAIL_SENDER_EMAIL`, `MAIL_SENDER_PASSWORD`, `MAIL_DEFAULT_TO`