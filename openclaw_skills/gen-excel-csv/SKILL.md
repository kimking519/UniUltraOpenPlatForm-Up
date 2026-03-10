---
name: gen-excel-csv
description: >
  Excel 转 CSV 文件。当用户提到"excel转csv"、"xlsx转csv"、
  "生成csv"、"导出csv"、"把excel转成csv"等场景时使用。
  即使用户没有明确说"转csv"，只要意图是将 Excel 文件转换为 CSV 格式，
  就应当触发此 Skill。
---

# Gen Excel to CSV

将 XLSX 文件转换为 CSV 格式，输出到同目录并返回全路径。

---

## 前置条件

- **Python 3.x** 已安装
- **openpyxl** 库已安装（`pip install openpyxl`）
- 配置文件路径：`openclaw_skills/gen-excel-csv/config/config_20260302000755.json`

> ⚠️ 出于安全考虑，默认目录等配置以独立文件形式存放，不硬编码在脚本中。
> 支持通过环境变量 `EXCEL_CSV_DEFAULT_DIR` 动态覆盖。

**WSL 环境变量设置（推荐）：**

```bash
echo 'export EXCEL_CSV_DEFAULT_DIR="/home/kim/UniProject"' >> ~/.bashrc
source ~/.bashrc
```

**Windows 环境变量设置（可选）：**

```powershell
[Environment]::SetEnvironmentVariable("EXCEL_CSV_DEFAULT_DIR", "E:\WorkPlace\7_AI_APP\UniUltraOpenPlatFormCls", "User")
```

---

## 工作流程

### 第一步：解析用户输入

从用户的自然语言输入中提取以下参数：

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `input` | ✅ | XLSX 文件名（可含路径） | "report.xlsx", "/data/sales.xlsx" |
| `dir` | ❌ | 指定目录（可选，覆盖默认值） | "/home/kim/data" |
| `sheet` | ❌ | 指定 Sheet 名称（可选，默认第一个 Sheet） | "Sheet2" |
| `encoding` | ❌ | 输出编码（可选，默认 utf-8） | "utf-8-sig", "gbk" |

### 第二步：执行转换

调用转换脚本：

```bash
# Windows 环境
python openclaw_skills/gen-excel-csv/scripts/excel_to_csv_20260302000755.py --input "data.xlsx"

# WSL 环境
python3 openclaw_skills/gen-excel-csv/scripts/excel_to_csv_20260302000755.py --input "data.xlsx"

# 指定完整路径
python3 openclaw_skills/gen-excel-csv/scripts/excel_to_csv_20260302000755.py --input "/home/kim/data/report.xlsx"

# 指定 Sheet
python3 openclaw_skills/gen-excel-csv/scripts/excel_to_csv_20260302000755.py --input "data.xlsx" --sheet "Sheet2"

# 指定编码（Excel 兼容）
python openclaw_skills/gen-excel-csv/scripts/excel_to_csv_20260302000755.py --input "data.xlsx" --encoding "utf-8-sig"
```

### 第三步：输出结果

返回生成的 CSV 文件全路径。

---

## 示例

### 输入示例

```
把 data.xlsx 转成 csv
```

```
excel转csv report.xlsx
```

### 输出示例 — 成功

```
[OK] Excel 转 CSV 成功！
     输入文件: /home/kim/UniProject/data.xlsx
     输出文件: /home/kim/UniProject/data.csv
     Sheet   : Sheet1
     行    数: 150 行
     列    数: 5 列
     编    码: utf-8
```

### 输出示例 — 文件不存在

```
[FAIL] 转换失败: Excel 文件 [data.xlsx] 不存在。
```

### 输出示例 — 格式错误

```
[FAIL] 转换失败: 文件 [data.doc] 不是 Excel 格式。
```

### 输出示例 — Sheet 不存在

```
[FAIL] 转换失败: Sheet [Sheet3] 不存在。可用 Sheet: Sheet1, Sheet2
```

### 输出示例 — 同名文件自动重命名

```
[OK] Excel 转 CSV 成功！
     输入文件: /home/kim/UniProject/data.xlsx
     输出文件: /home/kim/UniProject/data_1.csv
     Sheet   : Sheet1
     行    数: 150 行
     列    数: 5 列
     编    码: utf-8
```

---

## 注意事项 / 边缘情况

- **文件不存在**：输出明确错误提示
- **非 XLSX/XLS 文件**：检查扩展名，拒绝处理
- **同名文件已存在**：自动追加序号（data_1.csv, data_2.csv ...）
- **多 Sheet 处理**：默认转换第一个 Sheet，可通过 --sheet 指定
- **编码问题**：默认 utf-8，如需 Excel 兼容可用 --encoding utf-8-sig
- **空单元格**：转换为空字符串
- **路径处理**：支持相对路径、绝对路径、Windows 路径、WSL 路径
- **环境检测**：自动检测 Windows/WSL 环境，选择对应的默认目录

---

## 参考资源

- `scripts/excel_to_csv_20260302000755.py` — 核心转换脚本
- `config/config_20260302000755.json` — 默认目录及编码配置
- 环境变量: `EXCEL_CSV_DEFAULT_DIR`（可选覆盖）