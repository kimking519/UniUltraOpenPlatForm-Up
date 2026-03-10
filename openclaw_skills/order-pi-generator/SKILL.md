---
name: order-pi-generator
description: >
  根据销售订单生成 Proforma Invoice (PI) 文件。
  当用户提到"生成PI"、"PI文件"、"发票"、"Proforma Invoice"、
  或在订单管理页面选择订单后要求生成PI时使用此skill。
---

# 订单PI生成器

根据选中的销售订单信息，自动生成 Proforma Invoice Excel 和 PDF 文件。

**版本**: 1.1.0 (2026-03-08)
**更新**: 新增商务蓝风格美化 + PDF 双输出

---

## 前置条件

- Python 3.x
- openpyxl 库 (`pip install openpyxl`)
- LibreOffice（用于 PDF 转换，可选）
- SQLite 数据库访问权限

---

## 工作流程

### 第一步：获取订单数据

从数据库查询选中订单的完整信息，包括：
- 订单基本信息（型号、品牌、价格）
- 客户信息（联系人、公司名、地址、邮箱、电话）
- 关联报价信息（数量、批号、货期）

### 第二步：数据验证

- 检查所有订单是否属于同一客户
- 验证必要字段是否完整

### 第三步：生成PI文件

基于模板填充数据，应用商务蓝风格样式：
- **表头样式**: 深海蓝背景 (#1E3A5F) + 白色文字
- **数据行样式**: 斑马纹效果（浅灰蓝/白色交替）
- **合计行样式**: 深海蓝背景 + 红色金额 (#DC2626)

### 第四步：输出

- 输出目录：`E:\1_Business\1_Auto\{客户名}\{日期yyyymmdd}`
- Excel 文件：`Proforma Invoice_{客户名}_{发票号}.xlsx`（内部编辑用）
- PDF 文件：`Proforma Invoice_{客户名}_{发票号}.pdf`（发送客户）

---

## 示例

### 输入示例
```
订单编号: d00001, d00002, d00003
```

### 输出示例
```
成功 PI生成成功！
Excel路径: E:\1_Business\1_Auto\TAEJU\20260308\Proforma Invoice_TAEJU_UNI20260308143000.xlsx
PDF路径: E:\1_Business\1_Auto\TAEJU\20260308\Proforma Invoice_TAEJU_UNI20260308143000.pdf
订单条数: 3
客户: TAEJU
Invoice No.: UNI2026030814
```

---

## 样式说明

### 配色方案（商务蓝风格）

| 元素 | 颜色代码 | 用途 |
|------|----------|------|
| 表头背景 | `#1E3A5F` | 深海蓝，专业稳重 |
| 表头文字 | `#FFFFFF` | 白色，高对比度 |
| 奇数行背景 | `#F8FAFC` | 浅灰蓝，斑马纹 |
| 偶数行背景 | `#FFFFFF` | 白色，斑马纹 |
| 合计行背景 | `#1E3A5F` | 深海蓝，突出显示 |
| 合计金额 | `#DC2626` | 红色，醒目 |

---

## 注意事项 / 边缘情况

- 订单必须属于同一客户，否则拒绝生成
- 如果订单没有关联报价单，QTY/D/C/L/T 字段为空
- 支持跨平台路径（Windows/WSL）
- 动态行数：根据订单数量自动插入或删除行
- PDF 生成需要安装 LibreOffice

---

## 配置说明

配置文件位于 `config/db_config.json`：

| 配置项 | 说明 |
|--------|------|
| db_path_windows | Windows 数据库路径 |
| db_path_wsl | WSL 数据库路径 |
| output_base_windows | Windows 输出目录 |
| output_base_wsl | WSL 输出目录 |
| libreoffice_path_windows | Windows LibreOffice 路径 |
| libreoffice_path_wsl | WSL LibreOffice 路径 |

环境变量 `ORDER_PI_DB_PATH` 可覆盖数据库路径配置。

---

## 目录结构

```
order-pi-generator/
├── SKILL.md                    # 本文档
├── config/
│   └── db_config.json          # 配置文件
├── scripts/
│   ├── make_pi.py              # PI生成脚本（主程序）
│   └── excel_to_pdf.py         # PDF转换模块
└── template/
    └── Proforma_Invoice_template.xlsx  # PI模板
```

---

## 安装 LibreOffice

### Windows
下载安装: https://www.libreoffice.org/download/

### WSL/Linux
```bash
sudo apt install libreoffice
```