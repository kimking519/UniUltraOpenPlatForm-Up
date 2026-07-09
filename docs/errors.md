# 错误记录与修复方案

## 2026-06-20: 联系人导出国家为空（国家相关 bug 第 2 次）⚠️ 重复 bug

### 问题描述
联系人管理 → 导出 Excel，"国家"列大部分为空，但联系人列表页能正常显示国家。

### 根本原因
**SQL `COALESCE` 与前端 JS `||` 对空字符串处理不一致**：
- `uni_contact.country` 字段存的是**空字符串 `''`**（不是 NULL）
- 导出 SQL：`COALESCE(c.country, p.country)` —— COALESCE 只在 NULL 时回退，空字符串 `''` 不回退 → 返回 `''`
- 列表前端 JS：`item.country || item.prospect_country` —— JS `||` 把空字符串当 falsy → 正确回退到 prospect_country

### 修复方案
导出改用复用 `get_contact_list` 取数据，国家在 **Python 层用 `r.get('country') or r.get('prospect_country') or ''`**（与前端 `||` 语义完全一致），不再用 SQL COALESCE。

### ⚠️ 重复 bug 警示（CLAUDE.md：出现 2 次以上的 bug 要记录）
| 时间 | 现象 | 根因 |
|---|---|---|
| 2026-06-19 (`84a056d`) | 导出 Excel 没有国家列 | 原 SQL 只查 uni_contact 没 JOIN prospect |
| **2026-06-20 (本次)** | 导出国家大部分为空 | JOIN 用了 COALESCE，空字符串不回退；且多余 `AND p.status='pending'` 排除了已转化 prospect |

**教训**：导出/列表同一字段必须用**完全相同的取值逻辑**，跨语言（SQL vs Python vs JS）的空值语义差异是高发 bug 源。后续涉及"列表/导出一致性"应直接复用同一数据获取函数，禁止各自写 SQL。

---

## 2026-02-28: Session 筛选条件导致"全部状态"不生效

### 问题描述
在需求管理页面中，选择"全部状态"时，数据没有变化，仍然显示之前选择的状态（如"询价中"）的数据。

### 现象
- 选择"询价中" → 正常显示询价中的数据 ✓
- 选择"缺货" → 正常显示缺货数据 ✓
- 选择"已报价" → 正常显示已报价数据 ✓
- 选择"全部状态" → **数据不变，仍显示之前的状态** ✗

### 根本原因

**问题代码模式：**
```python
@app.get("/quote")
async def quote_page(..., status: str = ""):
    session = request.session
    if not search and not status and not ...:  # ← 问题在这里
        # 从 session 读取旧值
        status = session.get("quote_status", "")
    else:
        # 保存到 session
        session["quote_status"] = status
```

**问题分析：**
1. 前端选择"全部状态"时，`status=""`（空字符串）
2. 后端条件 `if not status` 判断为空字符串为 True
3. 但其他参数也为空时，整个条件为 True
4. 从 session 读取了**之前保存的 status 值**（如"询价中"）
5. 导致实际查询的还是"询价中"的数据

### 正确修复方案

**使用 `request.query_params` 检查 URL 中是否有参数：**

```python
@app.get("/quote")
async def quote_page(request: Request, ..., status: str = "", ...):
    session = request.session

    # 检查 URL 中是否有筛选参数（包括空值）
    has_params = any(k in request.query_params for k in [
        'search', 'start_date', 'end_date', 'cli_id', 'status', 'is_transferred'
    ])

    if not has_params:
        # 首次访问：从 session 读取
        status = session.get("quote_status", "")
    else:
        # 有参数（包括空值）：保存到 session
        session["quote_status"] = status

    # 使用 status 进行查询
    results, total = get_quote_list(..., status=status, ...)
```

### 关键知识点

1. **空字符串 vs 不存在**：
   - `status=""`（空字符串）是有意义的参数，表示"全部"
   - `status` 不在 URL 中表示没有该参数

2. **检查参数是否存在**：
   ```python
   # 错误方式
   if not status:  # 空字符串也会被认为是"无参数"

   # 正确方式
   if 'status' not in request.query_params:  # 只检查是否存在
   ```

3. **Session 使用原则**：
   - 只有当 URL 中**完全没有参数**时，才从 session 读取
   - 一旦有参数（包括空值），就以 URL 参数为准，并更新 session

### 前端配合

始终传递参数（即使是空值）：
```javascript
// 正确方式
let url = `/quote?status=${encodeURIComponent(status)}&is_transferred=${encodeURIComponent(is_transferred)}`;

// 错误方式（不要这样做）
if (status) url += `&status=${status}`;  // 空值时不传递
```

### 类似场景

此问题适用于所有带筛选条件 + Session 持久化的场景：
- 订单管理筛选
- 客户管理筛选
- 供应商管理筛选
- 任何使用 `?key=value` 进行筛选的页面

### 检查清单

下次做类似修改时，请检查：
- [ ] 空值参数是否被正确传递到后端
- [ ] 后端是否区分"空值"和"无参数"
- [ ] Session 是否只在首次访问时读取
- [ ] 前端是否始终传递所有筛选参数

---

## 2026-02-28: 报价管理"全部"状态前端选中逻辑错误

### 问题描述
在报价管理页面中，选择"全部"状态时，下拉框仍然显示"未转"被选中，数据也显示"未转"的数据。

### 现象
- 选择"未转" → 正常显示未转数据，下拉框选中"未转" ✓
- 选择"已转" → 正常显示已转数据，下拉框选中"已转" ✓
- 选择"全部" → **下拉框仍选中"未转"，数据显示"未转"** ✗

### 根本原因

**问题代码模式（templates/offer.html）：**
```html
<option value="">全部</option>
<option value="未转" {% if is_transferred=='未转' or is_transferred=='' %}selected{% endif %}>未转</option>
<option value="已转" {% if is_transferred=='已转' %}selected{% endif %}>已转</option>
```

**问题分析：**
1. 当用户选择"全部"时，`is_transferred=""`（空字符串）
2. 模板条件 `is_transferred=='未转' or is_transferred==''` 判断为空字符串为 True
3. 导致"未转"选项被加上 `selected` 属性
4. 虽然后端查询逻辑正确，但前端显示状态错误，用户体验混乱

### 正确修复方案

**每个选项只对应一个明确的值：**

```html
<option value="" {% if is_transferred=='' %}selected{% endif %}>全部</option>
<option value="未转" {% if is_transferred=='未转' %}selected{% endif %}>未转</option>
<option value="已转" {% if is_transferred=='已转' %}selected{% endif %}>已转</option>
```

### 关键知识点

1. **互斥条件**：
   - 每个选项的 `selected` 条件应该是**互斥的**
   - 不要使用 `or` 连接多个条件，除非确实需要多选

2. **空值处理**：
   - `value=""` 表示"全部"或"无筛选"
   - 空值也是有意义的值，需要单独处理

3. **前后端一致性**：
   - 后端：空字符串 → 查询全部（不添加 WHERE 条件）
   - 前端：空字符串 → 选中"全部"选项

### 完整的 Session + 筛选逻辑

**后端（main.py）：**
```python
@app.get("/offer", response_class=HTMLResponse)
async def offer_page(request: Request, ..., is_transferred: str = ""):
    session = request.session

    # 检查 URL 中是否有筛选参数（包括空值）
    has_params = any(k in request.query_params for k in [
        'search', 'start_date', 'end_date', 'cli_id', 'is_transferred'
    ])

    if not has_params:
        # 首次访问：从 session 读取默认值
        is_transferred = session.get("offer_is_transferred", "未转")
    else:
        # 有参数（包括空值）：保存到 session
        session["offer_is_transferred"] = is_transferred

    # 查询时使用 URL 传递的值（空字符串表示全部）
    results, total = get_offer_list(..., is_transferred=is_transferred)

    return templates.TemplateResponse("offer.html", {
        "is_transferred": is_transferred,
        ...
    })
```

**前端模板：**
```html
<!-- 下拉框：每个选项独立判断 -->
<select id="is_transferred">
    <option value="" {% if is_transferred=='' %}selected{% endif %}>全部</option>
    <option value="未转" {% if is_transferred=='未转' %}selected{% endif %}>未转</option>
    <option value="已转" {% if is_transferred=='已转' %}selected{% endif %}>已转</option>
</select>

<!-- JavaScript：始终传递参数 -->
<script>
function applyFilters() {
    const is_transferred = document.getElementById('is_transferred').value;
    let url = `/offer?page=1&is_transferred=${encodeURIComponent(is_transferred)}`;
    // 其他参数...
    window.location.href = url;
}
</script>
```

### 检查清单

修改带筛选条件的页面时，请检查：
- [ ] 后端是否使用 `request.query_params` 区分"空值"和"无参数"
- [ ] Session 是否只在首次访问（无参数）时读取
- [ ] 前端每个选项的 `selected` 条件是否互斥
- [ ] 空值选项（如"全部"）是否有独立的 `value=""` 和判断条件
- [ ] JavaScript 是否始终传递所有参数（包括空值）
- [ ] 分页链接是否包含所有筛选参数

---

## 2026-03-10: 文档生成系列 Bug（出现2次以上）

### Bug 1: 报价单生成 Excel 报错 - `no such column: o.offer_no`

#### 问题描述
在报价订单中生成 Excel 报价时报错：`生成失败: 生成异常: no such column: o.offer_no`

#### 根本原因
`document_generator.py` 中的 SQL 查询引用了不存在的列 `offer_no`：
```sql
SELECT o.offer_id, o.offer_no, o.offer_date, ...
FROM uni_offer o
```

但实际上 `uni_offer` 表并没有 `offer_no` 列。表结构如下：
- `offer_id` (主键)
- `offer_date`
- `quote_id`
- `inquiry_mpn` / `quoted_mpn`
- ...

#### 修复方案
移除 SQL 查询中不存在的 `offer_no` 列：
```python
# document_generator.py - get_offers_for_document()
rows = conn.execute(f"""
    SELECT o.offer_id, o.offer_date, o.cli_id,
           o.quoted_mpn, o.quoted_brand, o.offer_price_rmb, o.price_usd as offer_price_usd,
           ...
    FROM uni_offer o
    ...
""")
```

---

### Bug 2: PI 生成报错 - `'MergedCell' object attribute 'value' is read-only`

#### 问题描述
在销售订单中生成 PI 报错：`生成失败: 生成异常: 'MergedCell' object attribute 'value' is read-only`

#### 根本原因
PI 模板（`templates/pi/ProformaInvoice_template.xlsx`）中的 Total 行预设了合并单元格。
当代码尝试向合并单元格的非主单元格写入值时，会触发 `MergedCell` 只读错误。

```python
# 问题代码
ws.cell(actual_total_row, 1).value = "Total Amount:"  # 如果该单元格是合并单元格的一部分
```

#### 修复方案
在写入数据前，先取消该行可能存在的合并单元格：
```python
# 先取消可能存在的合并单元格
merged_ranges_to_remove = []
for merged_range in ws.merged_cells.ranges:
    if merged_range.min_row == actual_total_row:
        merged_ranges_to_remove.append(merged_range)
for mr in merged_ranges_to_remove:
    ws.unmerge_cells(str(mr))

# 然后写入数据
ws.cell(actual_total_row, 1).value = "Total Amount:"
ws.cell(actual_total_row, 8).value = f"=SUM(H{first_data_row}:H{last_data_row})"

# 最后重新合并
ws.merge_cells(f"A{actual_total_row}:G{actual_total_row}")
```

#### 关键知识点
1. **MergedCell 只读**：合并单元格中只有左上角的主单元格可以写入，其他单元格是只读的
2. **正确处理流程**：先取消合并 → 写入数据 → 重新合并
3. **遍历合并区域**：使用 `ws.merged_cells.ranges` 获取所有合并区域

---

### Bug 3: 文档输出路径错误

#### 问题描述
销售订单中生成 PI 和 CI 的路径应该是 `E:\1_Business\1_Auto\{客户名}\yyyymmdd`，
但代码中默认输出到项目目录下的 `Trans` 文件夹。

#### 根本原因
多个文档生成函数中的默认输出路径不一致：
- `document_generator.py`: 默认使用 `os.path.join(project_root, "Trans")`
- `ci_generator.py`: 同样使用 `Trans` 目录

#### 修复方案
1. 定义统一的默认输出路径常量：
```python
# document_generator.py
DEFAULT_OUTPUT_BASE = r"E:\1_Business\1_Auto"

def _get_output_base():
    """获取输出基础目录"""
    output_base = os.environ.get('UNIULTRA_OUTPUT_DIR')
    if output_base:
        return output_base
    return DEFAULT_OUTPUT_BASE
```

2. 在所有文档生成函数中使用统一的路径逻辑：
```python
if not output_base:
    output_base = _get_output_base()
```

3. 同时修复 `ci_generator.py` 中的 `generate_ci_kr()` 函数。

#### 影响范围
- `document_generator.py`: `generate_ci_us()`, `generate_pi()`, `generate_koquote()`
- `ci_generator.py`: `generate_ci_kr()`

---

### Bug 4: 文档输出路径在 WSL2 下不兼容

#### 问题描述
在 WSL2 环境下运行时，文档生成失败，因为路径使用 Windows 格式 `E:\1_Business\1_Auto`，而 WSL2 需要 `/mnt/e/1_Business/1_Auto`。

#### 根本原因
路径硬编码为 Windows 格式：
```python
DEFAULT_OUTPUT_BASE = r"E:\1_Business\1_Auto"
```

#### 修复方案
使用 `platform.system()` 动态检测操作系统：
```python
import platform

def _get_default_output_base():
    """获取默认输出目录 - 兼容 Windows 和 WSL2"""
    if platform.system() == "Windows":
        return r"E:\1_Business\1_Auto"
    else:
        # WSL2 或其他 Linux 系统
        return "/mnt/e/1_Business/1_Auto"
```

#### 影响范围
- `document_generator.py`
- `ci_generator.py`

---

### 检查清单

修改文档生成相关代码时，请检查：
- [ ] SQL 查询中的列名是否与表结构一致
- [ ] 处理 Excel 模板时是否考虑了合并单元格
- [ ] 输出路径是否使用 `_get_output_base()` 函数（兼容 Windows 和 WSL2）
- [ ] 环境变量 `UNIULTRA_OUTPUT_DIR` 是否正确使用

---

## 2026-03-19: 报价导出精度丢失问题

### Bug 1: CSV导出报价和成本价只保留2位小数

#### 问题描述
通过CSV导出按钮，导出来的报价(RMB)和成本价只显示2位小数，丢失了精度。

#### 根本原因
`main.py:1184-1185` 使用格式化字符串强制截取为2位小数：
```python
f"{cost_price_rmb:.2f}",
f"{offer_price_rmb:.2f}",
```

#### 修复方案
直接输出原始数值，不进行格式化截取：
```python
cost_price_rmb,
offer_price_rmb,
```

---

### Bug 2: Excel报价单KWR价格只保留1位小数

#### 问题描述
通过生成Excel报价单按钮，导出来的报价(KWR)只显示1位小数，丢失了精度。

#### 根本原因
`document_generator.py:1424` 使用 `round()` 强制截取为1位小数：
```python
price_kwr = round(float(price_rmb) * exchange_rate_krw, 1)
```

#### 修复方案
保留完整精度，不进行round截取：
```python
price_kwr = float(price_rmb) * exchange_rate_krw
```

---

### 检查清单

修改导出/文档生成相关代码时，请检查：
- [ ] 数值输出是否保留了原始精度
- [ ] 避免使用 `.Nf` 格式化字符串截取小数
- [ ] 避免使用 `round()` 函数截取小数位数
- [ ] 确认业务需求是否真的需要截取精度

---

### Bug 3: 待开发客户批量导入 95 条数据丢失（prospect_id 主键冲突）

**发生日期**: 2026-06-16

#### 问题描述
用户通过"联系人管理-待开发客户"页面批量导入 2093 条 Excel 数据，导入后页面只显示 1998 条，**95 条数据被静默丢弃，无任何提示**。

#### 根本原因
`Sills/db_prospect.py::get_next_prospect_id()` 用 **秒级时间戳 + 4位随机数** 生成 ID：

```python
timestamp = datetime.now().strftime('%Y%m%d%H%M%S')   # 秒级
rand_suffix = random.randint(1000, 9999)              # 9000 个值
return f"PK{timestamp}{rand_suffix}"
```

**冲突链路**：
1. 2093 条插入仅耗时 2.65 秒 → 同一秒内并发 700+ 条
2. 同一秒内 4 位随机只有 9000 个空间 → **必然碰撞**（实测 2093 次调用产生 206 个重复 ID）
3. 第二条 INSERT 抛 `duplicate key value violates unique constraint "uni_prospect_pkey"`
4. `import_prospects` except 分支识别到 `duplicate key` 关键词 → 归为 `skipped_count` 而非 `errors`
5. 后端返回 `{success:True, imported:1998, skipped:95}`
6. 前端 `importFile` 当时 toast 已显示但用户没注意到

#### 修复方案
1. **`Sills/base.py`**: 新增公共函数 `gen_unique_id(prefix)` ——
   微秒级时间戳(20 位) + 进程内自增计数器(3 位) + 线程锁。实测 5000 次调用零重复。
2. **统一替换以下 6 个 ID 生成器**为调用 `gen_unique_id`：
   - `get_next_prospect_id` (PK)
   - `get_next_contact_id` (CT)
   - `get_next_group_id` (GP)
   - `get_next_task_id` (ET)
   - `get_next_template_id` (TPL)
   - `get_next_account_id` (EA)
3. **前端 `templates/contact.html`**: ProspectManager.importFile/importText
   - 加全屏 loading 遮罩（`showLoadingMask`/`hideLoadingMask`）
   - 完成后弹出 alert 显示 imported/skipped/errors 明细
   - skipped/errors > 0 时 toast 改用 warning 颜色而非 success

#### 影响功能模块
- 待开发客户批量导入（核心修复）
- 联系人批量导入（同类风险，预防性修复）
- 邮件任务、模板、账号 ID 生成（一致性优化）

#### 检查清单
- [x] ID 生成函数在批量场景下产生唯一值（5000 次零重复）
- [x] 7 个修改的 Python 模块 import 通过
- [x] HTML JS 括号匹配（{ 345/345, ( 807/807）
- [x] 端到端回归: 100 条批量导入零跳过零错误
- [x] 用户操作流程: 重新上传 Excel 即可补齐 95 条

---

## 2026-06-21: 联系人标识筛选两个 Bug

### Bug 1: 切换标识下拉，列表数据不变
**现象**: 联系人页"标识"下拉切到 100/1/无标识，下方列表 total 始终 12864 不变，统计数字也不联动。
**根因**: `main.py::api_contact_list`（`/api/contact/list`）路由函数签名漏了 `prospect_tag`/`no_prospect_tag` 参数。前端发 `?prospect_tag=100`，FastAPI 对未声明的 query 参数静默丢弃 → 后端用空 filters 查全量。
**排查关键**: 直接调 `get_contact_list(filters={'prospect_tag':'100'})` 返回 484 条（db 层正确），浏览器抓包响应却 12864 → 断点在 HTTP 路由层，不在 db 层。
**修复**: `api_contact_list` 补 `prospect_tag`/`no_prospect_tag` 2 个可选参数 + filters 赋值，抄已验证的 `api_contact_stats` 同款写法。
**教训**: 同一批功能（stats/export/list 三端点都要支持 prospect_tag），改了 stats 和 export 却漏了 list。**多端点同步加参数时，必须逐个核对端点清单，不能只改"看到的那几个"。**

### Bug 2: "无标识"筛选包含 tag=0 的联系人
**现象**: 选"无标识"，结果里混入了标识为 0 的联系人；"无标识"和"0"两个选项数据完全重合（均 11037 条）。
**根因**: `db_contact.py::_build_contact_filter_clauses` 的 `no_prospect_tag` 条件为 `(p.prospect_id IS NULL OR p.tag IS NULL OR p.tag = 0)`，把 tag=0 也算入"无标识"。而 tag=0 是 prospect 建表默认值，是一个具体的标识值，不该归入"无标识"。
**修复**: 条件改为只 `p.prospect_id IS NULL`。语义对齐：无标识=未关联任何 prospect；0=关联了 tag=0 的 prospect。
**教训**: "默认值"≠"空值"。tag 默认 0，但 0 是合法标识值。**筛选条件里把默认值当"无"处理，会与"值为默认值"的真实数据混淆。** 设计筛选语义时必须明确区分"未关联"和"关联了默认值"。

### 死代码发现（未处理，记录在案）
`routes/contact.py` 整个文件未被 `main.py` import/注册，是死代码。其 `api_contact_list` 参数齐全但从不生效。后续若清理，需确认无其他入口引用。

---

### 测试踩坑（2026-07-03）

**现象**: 为 `reexecute_task` 写 SQLite 临时库单元测试时，`reexecute_task` 在 completed/error 任务上返回失败，错误信息 `no such function: NOW`。
**根因**: `Sills/db_config.py::get_datetime_now()` 按 DB 模式返回——PG 模式返回 `'NOW()'`，SQLite 模式返回 `"datetime('now','localtime')"`。测试环境变量命中了 PG 模式，但临时库是原生 sqlite3，不认识 `NOW()`。`reexecute_task` / `start_task` / `complete_task` 都用 `started_at = {dt_now}` 这个模式，生产中按模式自动切换是对的，**不是代码 bug**。
**处理**: 测试 fixture 里 `monkeypatch.setattr(db_email_task, "get_datetime_now", lambda: "datetime('now','localtime')")` 强制 SQLite 变体。
**教训**: 写隔离单测时，凡是被测函数依赖了「按运行环境切换输出」的工具函数（如 get_datetime_now、get_db_connection），必须在 fixture 里一并 patch 到与测试库匹配的变体，否则会误报代码 bug。

---

## 2026-07-03: 重新执行任务绕过 7 天跳过规则

### 问题描述
开发信任务设置"7 天内不重发"跳过规则后，点击「重新执行」按钮，7 天内已发送的邮箱仍被重发，跳过规则未生效。

### 根本原因
`Sills/email_sender.py` 在引入重新执行功能（commit `2de9e7a`）时，在两处对 `reexecute_mode` 做了特殊处理，与跳过规则的产品预期冲突：

1. **第 374 行**（加载 7 天已发送集合）：
   ```python
   if skip_enabled == 1 and not self.retry_mode and not self.reexecute_mode:
       recently_sent_set = get_recently_sent_emails(skip_days)
   ```
   重新执行时条件不成立 → `recently_sent_set` 为空集 → 第 480 行的 7 天跳过判断永远不命中 → 全部重发。

2. **第 470 行**（当前任务已发送去重，连带 bug）：`reexecute_task` 重置计数但**不清理旧日志**，`sent_email_set`（第 365 行）仍含上次运行的全部已发送邮箱；而该判断**未**对 reexecute 做绕过 → 重新执行 `completed` 任务时所有联系人被按"当前任务已发送"跳过、0 封发出，7 天规则根本没机会生效。

### 修复方案
- 第 374 行：去掉 `and not self.reexecute_mode`，重新执行时也加载 7 天已发送集合并跳过。
- 第 470 行：加 `not self.reexecute_mode` 守卫，重新执行时绕过"当前任务已发送"去重，统一交由 7 天规则判定。
- 效果：重新执行 = 重发全部联系人，但 7 天内已发送（任意任务）的跳过并计入 `skipped_count`；`skip_enabled=0` 时不跳过。

### 教训
- "重新执行"语义是"重发全部联系人"，但不等于"无视一切跳过规则"。**跳过规则（7 天内不重发）是防骚扰的硬性约束，应在所有发送路径生效**，除非用户显式关闭（skip_enabled=0）。
- 新增模式（reexecute_mode）时，必须同步审视所有与该模式相关的既有判断（374 行跳过、470 行去重），不能只改一处。
- 该 bug 是上一个需求（重新执行功能）引入的回归。当时单测只覆盖了 `reexecute_task` 的 DB 重置逻辑，**未覆盖 worker 发送循环的跳过行为**，导致漏网。已补 4 个 worker 跳过逻辑单测（reexecute 7 天内跳过 / skip 关闭全发 / reexecute 绕过当前任务去重 / 普通模式去重不破坏）。

---

### 高频 Bug 模式记录（出现 2 次以上）

#### 模式 A: 静默吞错（出现 2 次）
- Bug 1（联系人导出 500）和 Bug 3 都因为后端把异常归到不显眼的字段，前端没显示
- **预防原则**: 后端任何 errors 字段，前端必须显示出来；toast 只用 success 表示真正全部成功

## 2026-07-09: 更新报价-当天判断跨库SQL不兼容

### 问题描述
新增"更新报价"功能，最初用 `date(created_at) = date('now','localtime')` 判断当天，PostgreSQL 下报 `UndefinedFunction: function date(unknown, unknown) does not exist`。

### 根本原因
**项目同时支持 SQLite 和 PostgreSQL，但 `base.py` 的 SQL 翻译器只翻译 `datetime()`、`IFNULL`、`GROUP_CONCAT` 等部分函数，不翻译 `date()` 函数**。`date()` 是 SQLite 专有语法，PG 不支持。

后续尝试也踩坑：
1. `created_at LIKE ? || '%'` → SQL 翻译器把 `?` 换成 `%s` 后，psycopg 把 `'%'` 误识别为占位符 → `only '%s', '%b', '%t' are allowed as placeholders`
2. `SUBSTR(created_at, 1, 10) = ?` → PG 的 `SUBSTR` 不能直接作用于 `timestamp` 类型 → `function substr(timestamp without time zone, integer, integer) does not exist`

### 最终修复方案
**当天判断完全放到 Python 层**：SQL 只按型号查候选（`ORDER BY created_at DESC`），用 Python 的 `isinstance(created_at, datetime)` + `strftime` 比较日期（参考 `db_task_board.is_today`）。彻底规避 SQL 日期函数方言与 SQL 翻译器占位符冲突。

### 经验（跨库兼容规则）
- ❌ 禁用：`date()`、`SUBSTR(timestamp,...)`、`LIKE ? || '%'`（带 `%` 的拼接）
- ✅ 推荐：日期类过滤尽量在 Python 层做；SQL 里只做等值/范围比较
- ✅ 跨库安全：`LOWER(TRIM(col))`、`COALESCE`、`ORDER BY`、`LIMIT`、普通 `=` 比较
- 测试里改 created_at 也不要用 `datetime('now','-1 day')`，改用 Python 算昨天 ISO 字符串直接赋值

### ⚠️ 重复 bug 警示（CLAUDE.md：出现 2 次以上的 bug 要记录）
| 时间 | 现象 | 根因 |
|---|---|---|
| 2026-06 多次 | 各类跨库 SQL 不兼容 | 写了 SQLite 专有语法，PG 不认 |
| **2026-07-09 (本次)** | date()/SUBSTR(timestamp)/LIKE拼接 三连失败 | 同属"SQL 日期函数方言"问题族 |

**教训**：跨库项目写 SQL 日期逻辑前，先确认该函数在翻译器覆盖范围内（base.py 翻译表），不在范围内的日期/字符串函数一律移到 Python 层处理。

## 2026-07-09: 更新报价-安全审查修复(XSS+IDOR)

### 安全审查发现 2 个问题

#### 1. XSS (templates/offer.html) - MEDIUM
**问题**：`showUpdateCostModal` 用模板字符串把 `item.mpn`/批号/交期等直接 innerHTML 插入，型号含 `<script>` 等会被执行。
**修复**：新增 `esc(v)` HTML 转义函数（`& < > " '`），所有动态文本插值经 `esc()` 包裹。
**影响**：仅本次新增的更新报价预览弹窗，既有代码不动。

#### 2. IDOR (Sills/db_offer.py) - MEDIUM
**问题**：`execute_update_today_cost` 直接信任前端回传 `preview_list` 里的 `offer_id`，不校验是否当天记录。攻击者可篡改 offer_id 指向任意历史报价，绕过"只更新当天"核心约束，改历史成本价。
**修复**：执行 UPDATE 前重新 `SELECT created_at FROM uni_offer WHERE offer_id=?`，用 Python 判定当天（`_is_today`），非当天直接拒绝并计入 errors，不执行 UPDATE。
**验证**：新增 `test_update_cost_idor_history_rejected` 用例，伪造 offer_id 指向昨天记录，断言 updated_count=0 且库值不变。

### 经验
- 任何"按前端传 ID 执行写操作"的接口，必须服务端重新校验该 ID 满足业务约束（如"当天""本人""特定状态"），不能假设前端传来的就是 preview 当时的合法值。
- 模板字符串 innerHTML 拼接动态数据，一律先转义；尤其型号/批号这类用户可输入字段。
