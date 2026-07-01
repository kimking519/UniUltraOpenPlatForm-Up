# 开发信任务管理 - 任务名单编辑功能 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在开发信任务列表的 pending/paused/error 状态任务上添加"编辑名单"按钮，点击弹窗展示所有联系人（客户名+邮箱），支持搜索过滤，支持删除/恢复联系人。

**Architecture:** 在 `uni_email_task` 表新增 `excluded_contacts` TEXT 字段（JSON数组存储被排除的邮箱），修改 `get_task_contacts()` 过滤排除项，新增3个REST API，前端新增编辑弹窗。

**Tech Stack:** FastAPI + SQLite + Jinja2 + vanilla JavaScript

## Global Constraints

- 不修改现有表结构（仅新增字段，通过迁移脚本）
- 排除仅影响当前任务，不影响联系人组或其他任务
- 编辑按钮仅在 pending/paused/error 状态显示
- 遵循现有代码风格：中文注释、内联样式、原生JS

---

### Task 1: 数据库迁移 - 添加 excluded_contacts 字段

**Files:**
- Modify: `Sills/base.py:1514` (在最后一个迁移块之后添加)

**Interfaces:**
- Produces: `uni_email_task.excluded_contacts TEXT` 字段，存储JSON数组如 `["email1@x.com","email2@x.com"]`

- [ ] **Step 1: 添加迁移代码**

在 `Sills/base.py` 的 `init_db()` 函数中，找到最后一个 `uni_email_task` 相关的迁移块（约1514行之后），添加：

```python
        # 迁移：为 uni_email_task 添加 excluded_contacts 字段（任务级别排除联系人）
        try:
            conn.execute("ALTER TABLE uni_email_task ADD COLUMN excluded_contacts TEXT DEFAULT ''")
            print("[DB] 迁移完成：uni_email_task 添加 excluded_contacts 列")
        except sqlite3.OperationalError:
            pass  # 列已存在，忽略
```

- [ ] **Step 2: 验证迁移**

运行 `python Sills/base.py` 确保迁移成功执行（应看到迁移日志），且再次运行不会报错。

- [ ] **Step 3: 提交**

```bash
git add Sills/base.py
git commit -m "feat: uni_email_task 新增 excluded_contacts 字段 (20260701XXXX)"
```

---

### Task 2: 后端 - 新增任务联系人排除/恢复函数

**Files:**
- Modify: `Sills/db_email_task.py:396-417` (修改 `get_task_contacts`，并在其后新增函数)

**Interfaces:**
- Consumes: `uni_email_task.excluded_contacts` (JSON array of emails)
- Produces:
  - `get_task_contacts_with_excluded(task_id, search="")` → `(contacts_list, excluded_count, total)` — 获取带排除标记的联系人列表，支持搜索
  - `exclude_task_contact(task_id, email)` → `(success, message)`
  - `restore_task_contact(task_id, email)` → `(success, message)`

- [ ] **Step 1: 修改 `get_task_contacts` 函数，增加排除过滤**

找到 `get_task_contacts` 函数（约396行），在获取 sent_emails 之后、过滤之前，增加 excluded_contacts 的解析和过滤：

```python
def get_task_contacts(task_id):
    """获取任务的联系人列表（排除已发送成功的邮箱 + 手动排除的邮箱）

    Returns:
        list 未发送联系人列表 [{"contact_id", "email", "company", ...}, ...]
    """
    task = get_task_by_id(task_id)
    if not task:
        return []

    group_ids = json.loads(task.get('group_ids', '[]') or '[]')
    all_contacts = get_all_groups_contacts_all_types(group_ids)

    # 获取本任务已发送成功的邮箱列表
    from Sills.db_email_log import get_sent_emails_for_task
    sent_emails = get_sent_emails_for_task(task_id)
    sent_email_set = set(e.lower() for e in sent_emails)

    # 获取本任务手动排除的邮箱列表
    excluded_json = task.get('excluded_contacts', '') or ''
    excluded_emails = set()
    if excluded_json:
        try:
            excluded_emails = set(e.lower() for e in json.loads(excluded_json))
        except:
            pass

    # 过滤掉已发送成功 + 手动排除的联系人
    unsent_contacts = [
        c for c in all_contacts
        if c.get('email', '').lower() not in sent_email_set
        and c.get('email', '').lower() not in excluded_emails
    ]

    return unsent_contacts
```

- [ ] **Step 2: 新增 `get_task_contacts_with_excluded` 函数**

在 `get_task_contacts` 之后新增：

```python
def get_task_contacts_with_excluded(task_id, search=""):
    """获取任务的全部联系人列表（带排除标记，用于编辑弹窗）

    Args:
        task_id: 任务ID
        search: 搜索关键词（匹配客户名或邮箱）

    Returns:
        (contacts_list, excluded_count, total) tuple
        contacts_list 中每个联系人包含 is_excluded 字段
    """
    task = get_task_by_id(task_id)
    if not task:
        return [], 0, 0

    group_ids = json.loads(task.get('group_ids', '[]') or '[]')
    all_contacts = get_all_groups_contacts_all_types(group_ids)

    # 获取手动排除的邮箱
    excluded_json = task.get('excluded_contacts', '') or ''
    excluded_set = set()
    if excluded_json:
        try:
            excluded_set = set(e.lower() for e in json.loads(excluded_json))
        except:
            pass

    # 构建联系人列表（带排除标记）
    results = []
    for c in all_contacts:
        email = c.get('email', '').lower()
        if not email:
            continue
        # 搜索过滤
        if search:
            kw = search.lower()
            name = (c.get('name', '') or c.get('contact_name', '') or '').lower()
            company = (c.get('company', '') or c.get('company_name', '') or '').lower()
            if kw not in email and kw not in name and kw not in company:
                continue
        results.append({
            'contact_id': c.get('contact_id', ''),
            'email': c.get('email', ''),
            'name': c.get('name', '') or c.get('contact_name', '') or '',
            'company': c.get('company', '') or c.get('company_name', '') or '',
            'is_excluded': email in excluded_set
        })

    # 去重（按email）
    seen = set()
    deduped = []
    for c in results:
        email_lower = c['email'].lower()
        if email_lower not in seen:
            seen.add(email_lower)
            deduped.append(c)

    excluded_count = sum(1 for c in deduped if c['is_excluded'])

    return deduped, excluded_count, len(deduped)
```

- [ ] **Step 3: 新增 `exclude_task_contact` 函数**

```python
def exclude_task_contact(task_id, email):
    """从任务中排除某个联系人邮箱

    Args:
        task_id: 任务ID
        email: 要排除的邮箱地址

    Returns:
        (success, message) tuple
    """
    try:
        task = get_task_by_id(task_id)
        if not task:
            return False, "任务不存在"

        # 只允许在 pending/paused/error 状态编辑
        if task.get('status') not in ('pending', 'paused', 'error'):
            return False, "当前任务状态不允许编辑名单"

        email_lower = email.strip().lower()
        if not email_lower:
            return False, "邮箱地址不能为空"

        # 获取现有排除列表
        excluded_json = task.get('excluded_contacts', '') or ''
        excluded_list = []
        if excluded_json:
            try:
                excluded_list = json.loads(excluded_json)
            except:
                excluded_list = []

        if email_lower in [e.lower() for e in excluded_list]:
            return False, "该邮箱已在排除列表中"

        excluded_list.append(email.strip())
        new_excluded_json = json.dumps(excluded_list)

        # 同步更新 total_count（减少1，但不能低于已处理数）
        task_total = task.get('total_count', 0) or 0
        sent = task.get('sent_count', 0) or 0
        skipped = task.get('skipped_count', 0) or 0
        new_total = max(task_total - 1, sent + skipped)

        with get_db_connection() as conn:
            conn.execute(
                "UPDATE uni_email_task SET excluded_contacts = ?, total_count = ? WHERE task_id = ?",
                (new_excluded_json, new_total, task_id)
            )
            conn.commit()

        return True, "邮箱已从名单中移除"
    except Exception as e:
        return False, str(e)
```

- [ ] **Step 4: 新增 `restore_task_contact` 函数**

```python
def restore_task_contact(task_id, email):
    """恢复任务中被排除的联系人邮箱

    Args:
        task_id: 任务ID
        email: 要恢复的邮箱地址

    Returns:
        (success, message) tuple
    """
    try:
        task = get_task_by_id(task_id)
        if not task:
            return False, "任务不存在"

        # 只允许在 pending/paused/error 状态编辑
        if task.get('status') not in ('pending', 'paused', 'error'):
            return False, "当前任务状态不允许编辑名单"

        email_lower = email.strip().lower()
        if not email_lower:
            return False, "邮箱地址不能为空"

        # 获取现有排除列表
        excluded_json = task.get('excluded_contacts', '') or ''
        excluded_list = []
        if excluded_json:
            try:
                excluded_list = json.loads(excluded_json)
            except:
                excluded_list = []

        # 查找并移除
        found = False
        new_list = []
        for e in excluded_list:
            if e.lower() == email_lower:
                found = True
            else:
                new_list.append(e)

        if not found:
            return False, "该邮箱不在排除列表中"

        new_excluded_json = json.dumps(new_list) if new_list else ""

        # 同步更新 total_count（增加1）
        task_total = task.get('total_count', 0) or 0
        new_total = task_total + 1

        with get_db_connection() as conn:
            conn.execute(
                "UPDATE uni_email_task SET excluded_contacts = ?, total_count = ? WHERE task_id = ?",
                (new_excluded_json, new_total, task_id)
            )
            conn.commit()

        return True, "邮箱已恢复到名单中"
    except Exception as e:
        return False, str(e)
```

- [ ] **Step 5: 验证后端函数**

在Python交互环境中手动测试（或写一个简单脚本）：
```python
from Sills.db_email_task import get_task_contacts_with_excluded, exclude_task_contact, restore_task_contact
# 找一个 pending 状态的任务测试
contacts, excluded_count, total = get_task_contacts_with_excluded('ET...', '')
print(f"总数: {total}, 已排除: {excluded_count}")
```

- [ ] **Step 6: 提交**

```bash
git add Sills/db_email_task.py
git commit -m "feat: 任务联系人排除/恢复/查询函数 (20260701XXXX)"
```

---

### Task 3: 后端 - 新增 API 端点

**Files:**
- Modify: `main.py` (在开发信管理模块区域约6770行附近添加)

**Interfaces:**
- Consumes: `get_task_contacts_with_excluded`, `exclude_task_contact`, `restore_task_contact` from `db_email_task`
- Produces:
  - `GET /api/task/{task_id}/contacts?search=` → JSON
  - `POST /api/task/{task_id}/contacts/exclude` body: `{email: "..."}` → JSON
  - `POST /api/task/{task_id}/contacts/restore` body: `{email: "..."}` → JSON

- [ ] **Step 1: 在 main.py 的 import 区域添加新函数引用**

找到 `from Sills.db_email_task import (` 区域（约6237行），添加 `get_task_contacts_with_excluded, exclude_task_contact, restore_task_contact`：

```python
from Sills.db_email_task import (
    get_task_list, get_task_by_id, get_active_task, has_running_task,
    create_task, start_task, update_task_progress, cancel_task,
    complete_task, get_task_progress, get_task_contacts,
    delete_task, delete_tasks_batch,
    get_task_contacts_with_excluded, exclude_task_contact, restore_task_contact
)
```

- [ ] **Step 2: 添加 API 端点（在 export 端点之前约6770行）**

```python
@app.get("/api/task/{task_id}/contacts")
async def api_task_contacts(
    task_id: str,
    search: str = "",
    current_user: dict = Depends(login_required)
):
    """获取任务联系人列表（用于编辑名单弹窗）"""
    contacts, excluded_count, total = get_task_contacts_with_excluded(task_id, search)
    return {
        "success": True,
        "contacts": contacts,
        "excluded_count": excluded_count,
        "total": total
    }


@app.post("/api/task/{task_id}/contacts/exclude")
async def api_task_exclude_contact(
    task_id: str,
    request: Request,
    current_user: dict = Depends(login_required)
):
    """从任务名单中排除联系人"""
    data = await request.json()
    email = data.get('email', '')
    if not email:
        return {"success": False, "message": "邮箱地址不能为空"}

    success, message = exclude_task_contact(task_id, email)
    return {"success": success, "message": message}


@app.post("/api/task/{task_id}/contacts/restore")
async def api_task_restore_contact(
    task_id: str,
    request: Request,
    current_user: dict = Depends(login_required)
):
    """恢复任务名单中被排除的联系人"""
    data = await request.json()
    email = data.get('email', '')
    if not email:
        return {"success": False, "message": "邮箱地址不能为空"}

    success, message = restore_task_contact(task_id, email)
    return {"success": success, "message": message}
```

- [ ] **Step 3: 验证 API**

启动服务后测试：
```bash
curl "http://localhost:8000/api/task/ET.../contacts?search="
curl -X POST "http://localhost:8000/api/task/ET.../contacts/exclude" -H "Content-Type: application/json" -d '{"email":"test@x.com"}'
```

- [ ] **Step 4: 提交**

```bash
git add main.py
git commit -m "feat: 任务名单编辑 API 端点 (20260701XXXX)"
```

---

### Task 4: 前端 - 编辑按钮和弹窗

**Files:**
- Modify: `templates/email_task.html` (多处修改)

**Interfaces:**
- Consumes: `GET /api/task/{task_id}/contacts?search=`, `POST /api/task/{task_id}/contacts/exclude`, `POST /api/task/{task_id}/contacts/restore`
- Produces: 编辑按钮 + 弹窗 UI

- [ ] **Step 1: 在任务列表操作栏添加"编辑名单"按钮**

找到 `loadTaskHistory()` 函数中构建 `actionButtons` 的代码（约880-893行），在 pending/paused/error 状态的操作按钮中添加编辑按钮：

将第881-893行的 actionButtons 构建逻辑修改为：

```javascript
// 根据状态显示不同操作按钮
let actionButtons = '';
let editBtn = `<button class="btn btn-sm" onclick="showEditTaskContactsModal('${t.task_id}', '${t.task_name.replace(/'/g, "\\'")}')">编辑名单</button>`;
if (t.status === 'pending') {
    actionButtons = `${editBtn} <button class="btn btn-primary btn-sm" onclick="startTask('${t.task_id}')">开始执行</button> <button class="btn btn-sm" onclick="exportTaskContacts('${t.task_id}')">导出</button> <button class="btn btn-sm" onclick="deleteTask('${t.task_id}')">删除</button>`;
} else if (t.status === 'running') {
    actionButtons = `<button class="btn btn-sm" onclick="stopTask('${t.task_id}')">停止执行</button> <button class="btn btn-sm" onclick="exportTaskContacts('${t.task_id}')">导出</button>`;
} else if (t.status === 'retrying') {
    actionButtons = `<button class="btn btn-sm" onclick="stopTask('${t.task_id}')">停止执行</button> <button class="btn btn-sm" onclick="exportTaskContacts('${t.task_id}')">导出</button>`;
} else if (t.status === 'paused') {
    actionButtons = `${editBtn} <button class="btn btn-primary btn-sm" onclick="startTask('${t.task_id}')">继续执行</button> <button class="btn btn-sm" onclick="exportTaskContacts('${t.task_id}')">导出</button> <button class="btn btn-sm" onclick="deleteTask('${t.task_id}')">删除</button>`;
} else if (t.status === 'error') {
    actionButtons = `${editBtn} <button class="btn btn-primary btn-sm" onclick="startTask('${t.task_id}')">重新执行</button> <button class="btn btn-sm" onclick="retryFailedEmails('${t.task_id}')">重试失败</button> <button class="btn btn-sm" onclick="exportTaskContacts('${t.task_id}')">导出</button> <button class="btn btn-sm" onclick="deleteTask('${t.task_id}')">删除</button>`;
} else if (t.status === 'completed') {
    actionButtons = `<button class="btn btn-sm" onclick="retryFailedEmails('${t.task_id}')">重试失败</button> <button class="btn btn-sm" onclick="exportTaskContacts('${t.task_id}')">导出</button> <button class="btn btn-sm" onclick="deleteTask('${t.task_id}')">删除</button>`;
}
```

- [ ] **Step 2: 添加编辑名单弹窗 HTML**

找到现有的 `editGroupModal` 弹窗结束位置（约450行附近，即 `closeAddEmailsModal` 弹窗之前），插入新的弹窗 HTML：

```html
<!-- 编辑任务名单弹窗 -->
<div id="editTaskContactsModal" style="display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 1000; align-items: center; justify-content: center;">
    <div style="background: var(--card-bg); padding: 20px; border-radius: var(--radius); width: 600px; max-height: 85vh; display: flex; flex-direction: column;">
        <h3 style="margin: 0 0 10px 0;">编辑任务名单 - <span id="editTaskContactsName"></span></h3>
        <input type="hidden" id="editTaskContactsId">
        <div style="display: flex; gap: 8px; margin-bottom: 12px;">
            <input type="text" id="editTaskContactsSearch" placeholder="搜索客户名或邮箱..." oninput="loadEditTaskContacts()" style="flex: 1; padding: 0.4rem; border: 1px solid var(--border); border-radius: var(--radius); background: var(--bg-main); color: var(--text-main);">
        </div>
        <div id="editTaskContactsStats" style="font-size: 12px; color: var(--text-muted); margin-bottom: 8px;"></div>
        <div id="editTaskContactsList" style="flex: 1; overflow-y: auto; max-height: 50vh;">
            <!-- 联系人列表动态加载 -->
        </div>
        <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 15px; padding-top: 10px; border-top: 1px solid var(--border);">
            <button class="btn" onclick="closeEditTaskContactsModal()">关闭</button>
        </div>
    </div>
</div>
```

- [ ] **Step 3: 添加编辑名单相关的 JavaScript 函数**

在 `email_task.html` 的 `<script>` 区域末尾（约 `</script>` 之前）添加以下函数：

```javascript
    // ==================== 编辑任务名单 ====================

    // 显示编辑任务名单弹窗
    function showEditTaskContactsModal(taskId, taskName) {
        document.getElementById('editTaskContactsId').value = taskId;
        document.getElementById('editTaskContactsName').textContent = taskName;
        document.getElementById('editTaskContactsSearch').value = '';
        document.getElementById('editTaskContactsModal').style.display = 'flex';
        loadEditTaskContacts();
    }

    // 关闭编辑任务名单弹窗
    function closeEditTaskContactsModal() {
        document.getElementById('editTaskContactsModal').style.display = 'none';
    }

    // 加载任务联系人列表
    async function loadEditTaskContacts() {
        const taskId = document.getElementById('editTaskContactsId').value;
        const search = document.getElementById('editTaskContactsSearch').value;
        try {
            const res = await fetch(`/api/task/${taskId}/contacts?search=${encodeURIComponent(search)}`);
            const data = await res.json();
            if (!data.success) {
                alert('加载失败: ' + (data.message || '未知错误'));
                return;
            }

            // 统计信息
            document.getElementById('editTaskContactsStats').innerHTML =
                `共 ${data.total} 人，已排除 ${data.excluded_count} 人`;

            // 联系人列表
            const listEl = document.getElementById('editTaskContactsList');
            listEl.innerHTML = '';
            if (data.contacts.length === 0) {
                listEl.innerHTML = '<div style="text-align: center; padding: 30px; color: var(--text-muted);">暂无联系人</div>';
                return;
            }

            data.contacts.forEach(c => {
                const displayName = c.name || c.company || '-';
                const rowStyle = c.is_excluded
                    ? 'text-decoration: line-through; opacity: 0.6;'
                    : '';
                const actionBtn = c.is_excluded
                    ? `<button class="btn btn-sm" style="background: #22C55E; color: white;" onclick="restoreTaskContact('${taskId}', '${c.email.replace(/'/g, "\\'")}')">恢复</button>`
                    : `<button class="btn btn-sm" style="color: #DC2626;" onclick="excludeTaskContact('${taskId}', '${c.email.replace(/'/g, "\\'")}')">删除</button>`;

                listEl.innerHTML += `
                    <div style="display: flex; align-items: center; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border); ${rowStyle}">
                        <div style="flex: 1; min-width: 0;">
                            <span style="font-size: 13px; color: var(--text-main);">${displayName}</span>
                            <span style="font-size: 12px; color: var(--text-muted); margin-left: 8px;">${c.email}</span>
                        </div>
                        <div style="flex-shrink: 0; margin-left: 12px;">
                            ${actionBtn}
                        </div>
                    </div>`;
            });
        } catch (e) {
            console.error('加载任务联系人失败:', e);
            alert('加载失败');
        }
    }

    // 排除联系人
    async function excludeTaskContact(taskId, email) {
        if (!confirm(`确定从名单中移除 ${email} 吗？`)) return;
        try {
            const res = await fetch(`/api/task/${taskId}/contacts/exclude`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: email })
            });
            const data = await res.json();
            if (data.success) {
                loadEditTaskContacts();
            } else {
                alert('操作失败: ' + data.message);
            }
        } catch (e) {
            console.error('排除联系人失败:', e);
            alert('操作失败');
        }
    }

    // 恢复联系人
    async function restoreTaskContact(taskId, email) {
        if (!confirm(`确定将 ${email} 恢复到名单中吗？`)) return;
        try {
            const res = await fetch(`/api/task/${taskId}/contacts/restore`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: email })
            });
            const data = await res.json();
            if (data.success) {
                loadEditTaskContacts();
            } else {
                alert('操作失败: ' + data.message);
            }
        } catch (e) {
            console.error('恢复联系人失败:', e);
            alert('操作失败');
        }
    }
```

- [ ] **Step 4: 提交**

```bash
git add templates/email_task.html
git commit -m "feat: 任务名单编辑弹窗和按钮 (20260701XXXX)"
```

---

### Task 5: 回归验证

**Files:**
- 无新建文件

- [ ] **Step 1: 启动服务验证**

```bash
python main.py
```

- [ ] **Step 2: 手动测试场景**

1. 打开开发信任务页面，确认 pending/paused/error 状态任务显示"编辑名单"按钮
2. 确认 running/retrying/completed 状态任务不显示该按钮
3. 点击"编辑名单"，弹窗展示所有联系人（客户名+邮箱）
4. 搜索框输入关键词，列表实时过滤
5. 点击"删除"排除某个联系人，该联系人变为删除线样式
6. 点击"恢复"将排除的联系人加回
7. 关闭弹窗后重新打开，排除状态保留
8. 确认排除的联系人在任务执行时不会被发送

- [ ] **Step 3: 提交（如有修复）**

```bash
git add -A
git commit -m "fix: 任务名单编辑回归修复 (20260701XXXX)"
```
