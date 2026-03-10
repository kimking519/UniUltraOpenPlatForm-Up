---
name: gen-csv-excel
description: >
  CSV 转 Excel 文件。当用户提到"csv转excel"、"转换csv"、
  "生成xlsx"、"csv导出excel"、"把csv转成xlsx"等场景时使用。
  即使用户没有明确说"转excel"，只要意图是将 CSV 文件转换为 Excel 格式，
  就应当触发此 Skill。
---

# Gen CSV to Excel

将 CSV 文件转换为 XLSX 格式，输出到同目录并返回全路径。

---

## 前置条件

- **Python 3.x** 已安装
- **openpyxl** 库已安装（`pip install openpyxl`）
- 配置文件路径：`openclaw_skills/gen-csv-excel/config/config_20260301223101.json`

> ⚠️ 出于安全考虑，默认目录等配置以独立文件形式存放，不硬编码在脚本中。
> 支持通过环境变量 `CSV_EXCEL_DEFAULT_DIR` 动态覆盖。

**WSL 环境变量设置（推荐）：**

```bash
echo 'export CSV_EXCEL_DEFAULT_DIR="/home/kim/UniProject"' >> ~/.bashrc
source ~/.bashrc
```

**Windows 环境变量设置（可选）：**

```powershell
[Environment]::SetEnvironmentVariable("CSV_EXCEL_DEFAULT_DIR", "E:\WorkPlace\7_AI_APP\UniUltraOpenPlatFormCls", "User")
```

---

## 工作流程

### 第一步：解析用户输入

从用户的自然语言输入中提取以下参数：

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `input` | ✅ | CSV 文件名（可含路径） | "report.csv", "/data/sales.csv" |
| `dir` | ❌ | 指定目录（可选，覆盖默认值） | "/home/kim/data" |

### 第二步：执行转换

调用转换脚本：

```bash
# Windows 环境
python openclaw_skills/gen-csv-excel/scripts/csv_to_excel_20260301223101.py --input "data.csv"

# WSL 环境
python3 openclaw_skills/gen-csv-excel/scripts/csv_to_excel_20260301223101.py --input "data.csv"

# 指定完整路径
python3 openclaw_skills/gen-csv-excel/scripts/csv_to_excel_20260301223101.py --input "/home/kim/data/report.csv"

# 指定目录
python3 openclaw_skills/gen-csv-excel/scripts/csv_to_excel_20260301223101.py --input "report.csv" --dir "/home/kim/custom"
```

### 第三步：输出结果

返回生成的 XLSX 文件全路径。

---

## 示例

### 输入示例

```
把 data.csv 转成 excel
```

```
csv转excel report.csv
```

### 输出示例 — 成功

```
[OK] CSV 转 Excel 成功！
     输入文件: /home/kim/UniProject/data.csv
     输出文件: /home/kim/UniProject/data.xlsx
     行    数: 150 行
     列    数: 5 列
```

### 输出示例 — 文件不存在

```
[FAIL] 转换失败: CSV 文件 [data.csv] 不存在。
```

### 输出示例 — 格式错误

```
[FAIL] 转换失败: 文件 [data.csv] 不是 CSV 格式。
```

### 输出示例 — 同名文件自动重命名

```
[OK] CSV 转 Excel 成功！
     输入文件: /home/kim/UniProject/data.csv
     输出文件: /home/kim/UniProject/data_1.xlsx
     行    数: 150 行
     列    数: 5 列
```

---

## 注意事项 / 边缘情况

- **文件不存在**：输出明确错误提示
- **非 CSV 文件**：检查扩展名，拒绝处理
- **同名文件已存在**：自动追加序号（data_1.xlsx, data_2.xlsx ...）
- **中文编码**：自动检测 UTF-8 / GBK 编码
- **大文件处理**：超过 10MB 的文件可能需要较长时间
- **路径处理**：支持相对路径、绝对路径、Windows 路径、WSL 路径
- **环境检测**：自动检测 Windows/WSL 环境，选择对应的默认目录

---

## 参考资源

- `scripts/csv_to_excel_20260301223101.py` — 核心转换脚本
- `config/config_20260301223101.json` — 默认目录配置
- 环境变量: `CSV_EXCEL_DEFAULT_DIR`（可选覆盖）