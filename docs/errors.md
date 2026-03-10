# 错误记录与修复方案

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
