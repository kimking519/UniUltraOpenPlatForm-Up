---
name: buyer-make-koquote
description: >
  根据模板生成韩文报价单 Excel。当用户提到"生成报价单"、"做견적서"、
  "出报价 Excel"、"打印韩文报价"、"给客户出见积"等场景时使用。
  即使用户没有明确说"견적서"，只要意图是生成正式的 Excel 报价文件，
  就应当触发此 Skill。
---

# Buyer Make Koquote

根据一个或多个报价编号（`offer_id`），以 Excel 模板生成正式的韩文报价单（견적서），保存到 `Trans` 目录。

---

## 前置条件

- **Python 3.x** 已安装
- **openpyxl** 已安装（`pip install openpyxl`）
- 数据库路径已配置在 `openclaw_skills/buyer-make-koquote/config/db_config_20260301194403.json` 中
- 模板文件位于 `openclaw_skills/buyer-make-koquote/template/유니콘_전자부품견적서_template.xlsx`

> ⚠️ 出于安全考虑，数据库路径等关键配置以独立文件形式存放，不硬编码在脚本中。

**WSL 环境变量动态覆盖（可选）：**

```bash
echo 'export MAKE_KOQUOTE_DB_PATH="/home/kim/workspace/UniUltraOpenPlatForm/uni_platform.db"' >> ~/.bashrc
source ~/.bashrc
```

**Windows PowerShell 环境变量（可选）：**

```powershell
[Environment]::SetEnvironmentVariable("MAKE_KOQUOTE_DB_PATH", "E:\WorkPlace\7_AI_APP\UniUltraOpenPlatFormCls\uni_platform.db", "User")
```

---

## 工作流程

### 第一步：解析用户输入

从用户的自然语言输入中提取以下参数：

| 参数 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `offer_ids` | ✅ | 报价编号，多个用逗号分隔 | "b00015,b00016" |

### 第二步：执行生成

```bash
# Windows 环境
python openclaw_skills/buyer-make-koquote/scripts/make_koquote_20260301194403.py \
  --offer_ids "b00015,b00016"

# WSL 环境
python3 openclaw_skills/buyer-make-koquote/scripts/make_koquote_20260301194403.py \
  --offer_ids "b00015,b00016"
```

### 第三步：输出结果

将脚本输出（文件保存路径）直接返回给用户。

---

## 模板结构

```
견 적 서（标题）
──────────────────────────────────────
수신: {客户公司全名}
견적번호 : 제 {编号}호     | 公급자信息
작성일자 : {年}년 {月}월 {日}일  | 地址、联系方式
──────────────────────────────────────
No. | 모델명 | 제공가능한 부품 | 메이커 | 생산일자 | 수량(EA) | 단가(KRW) | 납기 | 비고
1   | ...    | ...            | ...    | ...      | ...      | ...       | ...  | ...
──────────────────────────────────────
합    계 | (合并单元格)
견적정보 | 报价有效期、付款方式、手续费等条款
특기사항 | 快递说明、通关等信息
```

### 字段映射

| Excel 位置 | 数据库字段 | 来源表 | 说明 |
|------------|-----------|--------|------|
| C5 | `cli_full_name` | `uni_cli` | 客户公司全名 |
| 모델명 | `inquiry_mpn` | `uni_offer` | 型号 |
| 제공가능한 부품 | `quoted_mpn` | `uni_offer` | 报价型号 |
| 메이커 | `inquiry_brand` | `uni_offer` | 品牌 |
| 생산일자 | `date_code` | `uni_offer` | 批次号 |
| 수량(EA) | `quoted_qty` | `uni_offer` | 数量 |
| 단가(KRW) | `price_kwr` 或 `offer_price_rmb` | `uni_offer` | 单价 |
| 납기 | `delivery_date` | `uni_offer` | 交期 |
| 비고 | `remark` | `uni_offer` | 备注 |

### 固定行样式

数据行后自动添加三行固定内容：

| 行 | 内容 | 行高 | 样式 |
|----|------|------|------|
| 合计行 | `합    계` | 22.5 | 灰色背景, 居中 |
| 报价信息行 | `견적정보` + 条款 | 94.0 | 灰色背景, 左对齐 |
| 特别事项行 | `특기사항` + 说明 | 64.0 | 灰色背景, 左对齐, 底部实线 |

---

## 输出路径

```
{项目根目录}/Trans/{客户名}/{yyyymmdd}/유니콘_전자부품견적서_{yyyymmddhhmm}.xlsx
```

示例: `Trans/TaeJu solusion/20260301/유니콘_전자부품견적서_202603011944.xlsx`

---

## 示例

### 输入示例

```
帮我生成 b00015 的견적서
```

```
给 b00015,b00016 出报价 Excel
```

### 输出示例 — 成功

```
✅ 报价单生成成功！
   文件路径: Trans/TaeJu solusion/20260301/유니콘_전자부품견적서_202603011944.xlsx
   报价条数: 2
   客    户: TaeJu solusion
```

### 输出示例 — 失败

```
❌ 报价编号 [b99999] 不存在。
```

---

## 注意事项

- **多个报价必须属于同一客户**：脚本会校验，不同客户的报价不能生成在同一份见积中
- **模板文件**：不要修改 `template/` 下的模板文件
- **目录自动创建**：`Trans\客户名\yyyymmdd\` 如不存在会自动创建
- **见积番号**：格式 `yyyymmddhhmm`，与文件名一致

---

## 参考资源

- `scripts/make_koquote_20260301194403.py` — 核心脚本
- `config/db_config_20260301194403.json` — 数据库路径配置
- `template/유니콘_전자부품견적서_template.xlsx` — Excel 模板
- 环境变量: `MAKE_KOQUOTE_DB_PATH`（可选覆盖）
- 数据表: `uni_offer`（报价表）、`uni_quote`（需求表）、`uni_cli`（客户表）
