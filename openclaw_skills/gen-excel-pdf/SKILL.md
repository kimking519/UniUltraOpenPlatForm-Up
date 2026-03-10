---
name: gen-excel-pdf
description: >
  Excel 转 PDF 文件。当用户提到"excel转pdf"、"xlsx转pdf"、
  "生成pdf"、"导出pdf"、"把excel转成pdf"等场景时使用。
  即使用户没有明确说"转pdf"，只要意图是将 Excel 文件转换为 PDF 格式，
  就应当触发此 Skill。
---

# Gen Excel to PDF

将 XLSX 文件转换为 PDF 格式，输出到同目录并返回全路径。

---

## 前置条件

- **Python 3.x** 已安装
- **LibreOffice** 已安装（转换引擎）
  - Windows: 下载安装 https://www.libreoffice.org/
  - WSL: `sudo apt install libreoffice`
- 配置文件路径：`openclaw_skills/gen-excel-pdf/config/config_20260301230424.json`

> ⚠️ 出于安全考虑，默认目录等配置以独立文件形式存放，不硬编码在脚本中。
> 支持通过环境变量 `EXCEL_PDF_DEFAULT_DIR` 动态覆盖。

**WSL 环境变量设置（推荐）：**

```bash
echo 'export EXCEL_PDF_DEFAULT_DIR="/home/kim/UniProject"' >> ~/.bashrc
source ~/.bashrc
```

**Windows 环境变量设置（可选）：**

```powershell
[Environment]::SetEnvironmentVariable("EXCEL_PDF_DEFAULT_DIR", "E:\WorkPlace\7_AI_APP\UniUltraOpenPlatFormCls", "User")
```

---

## 工作流程

### 第一步：解析用户输入

从用户的自然语言输入中提取以下参数：

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `input` | ✅ | XLSX 文件名（可含路径） | "report.xlsx", "/data/sales.xlsx" |
| `dir` | ❌ | 指定目录（可选，覆盖默认值） | "/home/kim/data" |

### 第二步：执行转换

调用转换脚本：

```bash
# Windows 环境
python openclaw_skills/gen-excel-pdf/scripts/excel_to_pdf_20260301230424.py --input "data.xlsx"

# WSL 环境
python3 openclaw_skills/gen-excel-pdf/scripts/excel_to_pdf_20260301230424.py --input "data.xlsx"

# 指定完整路径
python3 openclaw_skills/gen-excel-pdf/scripts/excel_to_pdf_20260301230424.py --input "/home/kim/data/report.xlsx"

# 指定目录
python3 openclaw_skills/gen-excel-pdf/scripts/excel_to_pdf_20260301230424.py --input "report.xlsx" --dir "/home/kim/custom"
```

### 第三步：输出结果

返回生成的 PDF 文件全路径。

---

## 示例

### 输入示例

```
把 data.xlsx 转成 pdf
```

```
excel转pdf report.xlsx
```

### 输出示例 — 成功

```
[OK] Excel 转 PDF 成功！
     输入文件: /home/kim/UniProject/data.xlsx
     输出文件: /home/kim/UniProject/data.pdf
     文件大小: 125 KB
```

### 输出示例 — 文件不存在

```
[FAIL] 转换失败: Excel 文件 [data.xlsx] 不存在。
```

### 输出示例 — 格式错误

```
[FAIL] 转换失败: 文件 [data.doc] 不是 Excel 格式。
```

### 输出示例 — LibreOffice 未安装

```
[FAIL] 转换失败: LibreOffice 未安装。请安装后重试。
  WSL: sudo apt install libreoffice
```

### 输出示例 — 同名文件自动重命名

```
[OK] Excel 转 PDF 成功！
     输入文件: /home/kim/UniProject/data.xlsx
     输出文件: /home/kim/UniProject/data_1.pdf
     文件大小: 125 KB
```

---

## 注意事项 / 边缘情况

- **文件不存在**：输出明确错误提示
- **非 XLSX/XLS 文件**：检查扩展名，拒绝处理
- **同名文件已存在**：自动追加序号（data_1.pdf, data_2.pdf ...）
- **LibreOffice 未安装**：输出安装指引
- **大文件处理**：超过 5MB 的文件可能需要较长时间
- **路径处理**：支持相对路径、绝对路径、Windows 路径、WSL 路径
- **环境检测**：自动检测 Windows/WSL 环境，选择对应的 LibreOffice 路径
- **超时处理**：转换超过 2 分钟自动终止

---

## 参考资源

- `scripts/excel_to_pdf_20260301230424.py` — 核心转换脚本
- `config/config_20260301230424.json` — 默认目录及 LibreOffice 路径配置
- 环境变量: `EXCEL_PDF_DEFAULT_DIR`（可选覆盖）
- LibreOffice 官网: https://www.libreoffice.org/