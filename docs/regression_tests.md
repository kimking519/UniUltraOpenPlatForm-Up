# 回归测试用例表

用于确保系统功能稳定性和回归测试。

---

## 测试环境配置

- **测试数据库**: `uni_platform_test.db` (独立测试库)
- **测试框架**: pytest + pytest-cov
- **执行命令**: `pytest tests/ -v --cov=Sills`

---

## 测试用例清单

### 1. 用户认证模块 (AUTH)

| 用例 ID | 测试项 | 测试步骤 | 预期结果 | 状态 |
|---------|--------|----------|----------|------|
| AUTH-TC001 | 正常登录 | 使用正确的账号密码登录 | 登录成功，返回用户信息 | ⬜ |
| AUTH-TC002 | 错误密码 | 使用错误密码登录 | 登录失败，提示"密码错误" | ⬜ |
| AUTH-TC003 | 账号不存在 | 使用不存在的账号登录 | 登录失败，提示"账号不存在" | ⬜ |
| AUTH-TC004 | 禁用账号登录 | 使用 rule=4 的账号登录 | 登录失败，提示"此账号被限制登录" | ⬜ |
| AUTH-TC005 | 修改密码 | 修改当前用户密码 | 密码修改成功，新密码可登录 | ⬜ |
| AUTH-TC006 | 默认管理员 | 使用 Admin/uni519 登录 | 登录成功，拥有管理员权限 | ⬜ |

---

### 2. 员工管理模块 (EMP)

| 用例 ID | 测试项 | 测试步骤 | 预期结果 | 状态 |
|---------|--------|----------|----------|------|
| EMP-TC001 | 获取员工列表 | 调用 get_emp_list() | 返回员工列表和总数 | ⬜ |
| EMP-TC002 | 员工分页 | 设置 page=2, page_size=10 | 返回第 11-20 条记录 | ⬜ |
| EMP-TC003 | 员工搜索 | 搜索姓名包含"张"的员工 | 返回匹配的员工 | ⬜ |
| EMP-TC004 | 添加员工 | 调用 add_employee() 添加新员工 | 添加成功，emp_id 自增 | ⬜ |
| EMP-TC005 | 员工编号唯一 | 添加相同 emp_id 的员工 | 添加失败，提示已存在 | ⬜ |
| EMP-TC006 | 批量导入员工 | 调用 batch_import_text() 导入 CSV | 成功导入，返回成功数 | ⬜ |
| EMP-TC007 | 更新员工 | 调用 update_employee() 更新信息 | 更新成功 | ⬜ |
| EMP-TC008 | 删除员工 | 调用 delete_employee() 删除员工 | 删除成功 | ⬜ |

---

### 3. 客户管理模块 (CLI)

| 用例 ID | 测试项 | 测试步骤 | 预期结果 | 状态 |
|---------|--------|----------|----------|------|
| CLI-TC001 | 获取客户列表 | 调用 get_cli_list() | 返回客户列表和总数 | ⬜ |
| CLI-TC002 | 客户搜索 | 搜索客户名称或地区 | 返回匹配的客户 | ⬜ |
| CLI-TC003 | 添加客户 | 调用 add_cli() 添加新客户 | 添加成功，cli_id 自动生成 (C001) | ⬜ |
| CLI-TC004 | 客户编号唯一 | 添加相同 cli_id 的客户 | 添加失败 | ⬜ |
| CLI-TC005 | 默认利润率 | 添加客户未指定 margin_rate | 默认为 10.0 | ⬜ |
| CLI-TC006 | 批量导入客户 | 调用 batch_import_cli_text() | 成功导入，返回成功数 | ⬜ |
| CLI-TC007 | 更新客户 | 调用 update_cli() 更新信息 | 更新成功 | ⬜ |
| CLI-TC008 | 删除客户 | 调用 delete_cli() 删除客户 | 删除成功 | ⬜ |
| CLI-TC009 | 删除有订单的客户 | 删除已有关联订单的客户 | 删除失败 (外键约束) | ⬜ |

---

### 4. 供应商管理模块 (VEN)

| 用例 ID | 测试项 | 测试步骤 | 预期结果 | 状态 |
|---------|--------|----------|----------|------|
| VEN-TC001 | 获取供应商列表 | 调用 get_paginated_list('uni_vendor') | 返回供应商列表 | ⬜ |
| VEN-TC002 | 添加供应商 | 调用 add_vendor() | 添加成功，vendor_id 自动生成 (V001) | ⬜ |
| VEN-TC003 | 批量导入供应商 | 调用 batch_import_vendor_text() | 成功导入 | ⬜ |
| VEN-TC004 | 更新供应商 | 调用 update_vendor() | 更新成功 | ⬜ |
| VEN-TC005 | 删除供应商 | 调用 delete_vendor() | 删除成功 | ⬜ |

---

### 5. 询价管理模块 (QUO)

| 用例 ID | 测试项 | 测试步骤 | 预期结果 | 状态 |
|---------|--------|----------|----------|------|
| QUO-TC001 | 获取询价列表 | 调用 get_quote_list() | 返回询价列表和总数 | ⬜ |
| QUO-TC002 | 询价多条件筛选 | 按日期、客户、状态筛选 | 返回筛选后的结果 | ⬜ |
| QUO-TC003 | 添加询价 | 调用 add_quote() | 添加成功，quote_id 自动生成 | ⬜ |
| QUO-TC004 | 批量导入询价 | 调用 batch_import_quote_text() | 成功导入 | ⬜ |
| QUO-TC005 | 更新询价 | 调用 update_quote() | 更新成功 | ⬜ |
| QUO-TC006 | 删除询价 | 调用 delete_quote() | 删除成功 | ⬜ |
| QUO-TC007 | 批量删除询价 | 调用 batch_delete_quote() | 批量删除成功 | ⬜ |
| QUO-TC008 | 批量复制询价 | 调用 batch_copy_quote() | 成功复制，生成新 quote_id | ⬜ |
| QUO-TC009 | 询价转报价 | 调用 batch_convert_from_quote() | 生成报价单，询价标记为已转 | ⬜ |

---

### 6. 报价管理模块 (OFF)

| 用例 ID | 测试项 | 测试步骤 | 预期结果 | 状态 |
|---------|--------|----------|----------|------|
| OFF-TC001 | 获取报价列表 | 调用 get_offer_list() | 返回报价列表和总数 | ⬜ |
| OFF-TC002 | 报价多条件筛选 | 按日期、客户、供应商筛选 | 返回筛选后的结果 | ⬜ |
| OFF-TC003 | 添加报价 | 调用 add_offer() | 添加成功，offer_id 自动生成 | ⬜ |
| OFF-TC004 | 报价自动利润率 | 添加报价时自动计算 offer_price | 按客户 margin_rate 计算 | ⬜ |
| OFF-TC005 | 报价汇率换算 | 添加报价后检查 price_kwr/price_usd | 按最新汇率换算 | ⬜ |
| OFF-TC006 | 批量导入报价 | 调用 batch_import_offer_text() | 成功导入 | ⬜ |
| OFF-TC007 | 更新报价 | 调用 update_offer() | 更新成功 | ⬜ |
| OFF-TC008 | 删除报价 | 调用 delete_offer() | 删除成功 | ⬜ |
| OFF-TC009 | 批量删除报价 | 调用 batch_delete_offer() | 批量删除成功 | ⬜ |
| OFF-TC010 | 报价转订单 | 调用 batch_convert_from_offer() | 生成订单，报价标记为已转 | ⬜ |
| OFF-TC011 | 重复转换检查 | 对已转换的询价再次转换 | 转换失败，提示已存在 | ⬜ |
| OFF-TC012 | 更新报价-解析匹配当天 | 输入"型号 成本价 批号 交期"调 preview_update_cost | 匹配当天录入同型号最新一条，预览含旧值/新值 | ✅ |
| OFF-TC013 | 更新报价-字段不足解析 | 仅输入"型号 成本价" | 只更新成本价，批号/交期不变 | ✅ |
| OFF-TC014 | 更新报价-执行落库 | 预览确认后调 execute_update_cost | 库中 cost_price_rmb/date_code/delivery_date 更新，offer_price 不联动 | ✅ |
| OFF-TC015 | 更新报价-历史数据不动 | 把记录 created_at 改为昨天再 preview | 匹配不到当天记录，进 errors，库值不变 | ✅ |
| OFF-TC016 | 更新报价-非法成本价跳过 | 成本价填非数字(abc) | 该行报"成本价格式错误"跳过，不更新 | ✅ |

---

### 7. 销售订单模块 (ORD)

| 用例 ID | 测试项 | 测试步骤 | 预期结果 | 状态 |
|---------|--------|----------|----------|------|
| ORD-TC001 | 获取订单列表 | 调用 get_order_list() | 返回订单列表和总数 | ⬜ |
| ORD-TC002 | 订单多条件筛选 | 按日期、客户、完成状态筛选 | 返回筛选后的结果 | ⬜ |
| ORD-TC003 | 添加订单 | 调用 add_order() | 添加成功，order_no 自动生成 | ⬜ |
| ORD-TC004 | 订单编号唯一 | 添加相同 order_id 的订单 | 添加失败 | ⬜ |
| ORD-TC005 | 订单利润计算 | 检查返回的 profit/total_profit | 计算正确 | ⬜ |
| ORD-TC006 | 批量导入订单 | 调用 batch_import_order() | 成功导入 | ⬜ |
| ORD-TC007 | 更新订单状态 | 调用 update_order_status() | 状态更新成功 | ⬜ |
| ORD-TC008 | 更新订单信息 | 调用 update_order() | 更新成功 | ⬜ |
| ORD-TC009 | 删除订单 | 调用 delete_order() | 删除成功 | ⬜ |
| ORD-TC010 | 删除有采购的订单 | 删除已被采购引用的订单 | 删除失败 (外键约束) | ⬜ |
| ORD-TC011 | 批量删除订单 | 调用 batch_delete_order() | 批量删除成功 | ⬜ |
| ORD-TC012 | 订单转采购 | 调用 batch_convert_from_order() | 生成采购单，订单标记为已转 | ⬜ |

---

### 8. 采购管理模块 (BUY)

| 用例 ID | 测试项 | 测试步骤 | 预期结果 | 状态 |
|---------|--------|----------|----------|------|
| BUY-TC001 | 获取采购列表 | 调用 get_buy_list() | 返回采购列表和总数 | ⬜ |
| BUY-TC002 | 采购多条件筛选 | 按日期、订单、发货状态筛选 | 返回筛选后的结果 | ⬜ |
| BUY-TC003 | 添加采购 | 调用 add_buy() | 添加成功，buy_id 自动生成 | ⬜ |
| BUY-TC004 | 批量导入采购 | 调用 batch_import_buy() | 成功导入 | ⬜ |
| BUY-TC005 | 更新采购节点 | 调用 update_buy_node() 更新 4 节点状态 | 节点更新成功 | ⬜ |
| BUY-TC006 | 更新采购信息 | 调用 update_buy() | 更新成功，自动计算 total_amount | ⬜ |
| BUY-TC007 | 删除采购 | 调用 delete_buy() | 删除成功 | ⬜ |
| BUY-TC008 | 批量删除采购 | 调用 batch_delete_buy() | 批量删除成功 | ⬜ |

---

### 9. 汇率管理模块 (EXR)

| 用例 ID | 测试项 | 测试步骤 | 预期结果 | 状态 |
|---------|--------|----------|----------|------|
| EXR-TC001 | 获取汇率列表 | 调用 get_daily_list() | 返回汇率列表 | ⬜ |
| EXR-TC002 | 添加汇率 | 调用 add_daily() | 添加成功 | ⬜ |
| EXR-TC003 | 重复日期币种 | 添加相同 date+currency 的记录 | 添加失败 (唯一约束) | ⬜ |
| EXR-TC004 | 更新汇率 | 调用 update_daily() | 更新成功 | ⬜ |
| EXR-TC005 | 获取最新汇率 | 查询最新 USD/KRW 汇率 | 返回最新记录 | ⬜ |

---

### 10. 数据库基础模块 (BASE)

| 用例 ID | 测试项 | 测试步骤 | 预期结果 | 状态 |
|---------|--------|----------|----------|------|
| BASE-TC001 | 数据库初始化 | 调用 init_db() | 所有表创建成功 | ⬜ |
| BASE-TC002 | 双环境隔离 | prod/dev 环境使用不同数据库 | 数据隔离正确 | ⬜ |
| BASE-TC003 | 分页查询 | 调用 get_paginated_list() | 返回正确的分页数据 | ⬜ |
| BASE-TC004 | 外键约束开启 | 检查 PRAGMA foreign_keys | ON | ⬜ |

---

## 集成测试用例

| 用例 ID | 测试项 | 测试步骤 | 预期结果 | 状态 |
|---------|--------|----------|----------|------|
| INT-TC001 | 完整业务流程 | 客户→询价→报价→订单→采购 | 全流程数据关联正确 | ⬜ |
| INT-TC002 | 利润计算链路 | 报价成本→订单售价→采购成本 | 利润计算正确 | ⬜ |
| INT-TC003 | 汇率换算链路 | 汇率→报价 KRW/USD→订单 KRW/USD | 换算正确 | ⬜ |
| INT-TC004 | 状态流转 | 询价→报价→订单→采购状态变更 | 状态标记正确传递 | ⬜ |

---

## 测试数据 fixtures

```python
# tests/conftest.py
import pytest
from Sills.base import get_db_connection, init_db

@pytest.fixture(scope="session")
def test_db():
    """初始化测试数据库"""
    init_db()
    yield
    # 清理测试数据

@pytest.fixture
def sample_emp():
    """示例员工数据"""
    return {
        "emp_name": "测试员工",
        "account": "test001",
        "password": "123456",
        "rule": "2"
    }

@pytest.fixture
def sample_cli():
    """示例客户数据"""
    return {
        "cli_name": "测试公司",
        "region": "韩国",
        "margin_rate": 15.0
    }
```

---

## 覆盖率要求

| 模块 | 目标覆盖率 |
|------|----------|
| Sills/base.py | 90% |
| Sills/db_emp.py | 90% |
| Sills/db_cli.py | 90% |
| Sills/db_vendor.py | 90% |
| Sills/db_quote.py | 85% |
| Sills/db_offer.py | 85% |
| Sills/db_order.py | 85% |
| Sills/db_buy.py | 85% |
| Sills/db_daily.py | 90% |

---

## 执行测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定模块测试
pytest tests/test_emp.py -v
pytest tests/test_quote.py -v

# 生成覆盖率报告
pytest tests/ --cov=Sills --cov-report=html

# 运行并生成 JUnit XML 报告
pytest tests/ --junitxml=test-results.xml
```

---

*最后更新：2026-02-28*

---

## 测试用例: ID 生成器批量唯一性

**新增日期**: 2026-06-16
**触发 Bug**: errors.md Bug 3

### TC-ID-001: 6 个 ID 生成器在 5000 次连续调用中零重复
**模块**: `Sills/base.py::gen_unique_id` 及调用方
**步骤**:
```python
from Sills.db_prospect import get_next_prospect_id
from Sills.db_contact import get_next_contact_id
from Sills.db_contact_group import get_next_group_id
from Sills.db_email_task import get_next_task_id
from Sills.db_email_template import get_next_template_id
from Sills.db_email_account import get_next_account_id

for f in [get_next_prospect_id, get_next_contact_id, get_next_group_id,
          get_next_task_id, get_next_template_id, get_next_account_id]:
    ids = [f() for _ in range(5000)]
    assert len(set(ids)) == 5000, f'{f.__name__} 出现重复'
```
**预期**: 6 个函数各自 5000 次调用全部唯一。

### TC-ID-002: 待开发客户批量导入 100 条零丢失
**模块**: `Sills/db_prospect.py::import_prospects`
**步骤**:
```python
fake = [{'prospect_name':f'T{i}','domain':f'test-id-fix-{i}.example'} for i in range(100)]
imported, skipped, errors = import_prospects(fake)
assert imported == 100 and skipped == 0 and len(errors) == 0
# 清理: DELETE FROM uni_prospect WHERE remark='AUTO_TEST_TEMP'
```
**预期**: 100 全部导入，0 跳过，0 错误。

### TC-ID-003: 联系人 ID 长度与格式
**预期**:
- prospect_id: `PK` + 20位时间戳 + 3位计数器 = 25 字符
- contact_id: `CT` + 同上 = 25 字符
- group_id: `GP` = 25 字符
- task_id: `ET` = 25 字符
- template_id: `TPL` + 同上 = 26 字符
- account_id: `EA` = 25 字符

---

## 开发信任务管理模块 (Email Task)

### TC-ETASK-001: 任意时间创建任务（已移除时间段限制）
**模块**: `templates/email_task.html` + `main.py::api_task_create`
**步骤**:
1. 打开"开发信任务管理"页面
2. 检查表单：UI 上**不再有**「发送时间段」输入框
3. 填写任务名 / 账号 / 联系人组 / 主题 / 内容，点击创建
**预期**: 创建成功，POST body 不包含 schedule_start/end 字段。

### TC-ETASK-002: 任意时间启动任务（不再阻拦）
**模块**: `templates/email_task.html::startTask`
**步骤**:
1. 调整系统时间到 23:00 或 03:00（原时间段 09:00-18:00 之外）
2. 点击任务列表上的"开始执行"
**预期**: 不再弹出"不在发送时间段"alert，进入"确定开始执行该任务"确认。

### TC-ETASK-003: 老任务（含 schedule_start/end）自动放行
**模块**: `Sills/email_sender.py::is_in_schedule_time`
**步骤**:
1. 取一条历史任务（数据库中 schedule_start='09:00', schedule_end='18:00'）
2. 在非时间段（如 22:00）启动该任务
**预期**: 任务正常发送，不被时间段卡住（`is_in_schedule_time` 永远 return True）。

### TC-ETASK-004: 后端 API 接收时强制 NULL
**模块**: `main.py::api_task_create`
**步骤**:
```python
# 即使前端传了 schedule_start/end，后端也强制写 None
POST /api/task/create {"task_name": "...", "schedule_start": "09:00", ...}
```
**预期**: 数据库 `uni_email_task` 中 schedule_start/end 字段为 NULL。

### TC-ETASK-005: 任务列表按钮组合（已移除改账号/查看日志/重试失败）
**模块**: `templates/email_task.html::loadTaskHistory`
**步骤**: 创建多个任务覆盖 5 种状态（pending/running/paused/error/completed），逐一观察操作列。
**预期**:
| 状态 | 应有按钮 | 不应有按钮 |
|---|---|---|
| pending | 开始执行/导出/删除 | 改账号 |
| running | 停止执行/导出 | — |
| retrying | 停止执行/导出 | — |
| paused | 继续执行/导出/删除 | 改账号 |
| error | 重新执行/导出/删除 | 改账号、重试失败 |
| completed | 重新执行/导出/删除 | 改账号、查看日志、重试失败 |

### TC-ETASK-006: viewTaskLogs 占位函数已删除
**模块**: `templates/email_task.html`
**步骤**: 浏览器 Console 执行 `typeof viewTaskLogs`
**预期**: 返回 `'undefined'`（函数已删）。

### TC-ETASK-007: 有任务运行时仍可创建新任务
**模块**: `Sills/db_email_task.py::create_task`
**步骤**:
1. 创建任务 A 并启动（status='running'）
2. 在任务 A 运行期间，创建任务 B
**预期**: 任务 B 创建成功，不再返回 `"已有任务正在进行,无法创建新任务"` 错误。

### TC-ETASK-008: 旧版 mail.html 创建拦截已移除
**模块**: `templates/mail.html`
**步骤**: 旧版页面在有任务运行时尝试创建新任务
**预期**: 不再弹出 `"已有任务正在进行，请等待完成或取消后再创建新任务"` alert，直接进入 `/api/task/create`。

### TC-ETASK-009: 重新执行任务（重发全部联系人）
**模块**: `main.py::api_task_reexecute` + `Sills/db_email_task.py::reexecute_task` + `Sills/email_sender.py::EmailSenderWorker(reexecute_mode=True)`
**步骤**:
1. 准备一个 `completed` 或 `error` 状态的任务（含若干联系人，部分已发送成功）
2. 任务列表点击「重新执行」按钮，确认弹窗后提交
3. 观察 `/api/task/reexecute` 返回、任务状态、进度计数、Worker 日志
**预期**:
- 接口返回 `success=true`，message 提示将发送 N 个联系人（N=全部联系人，含已发送成功的）
- 任务 `status` 变为 `running`，`sent_count/failed_count/skipped_count` 均清零
- Worker 以 `[重新执行]` 模式运行，重发全部联系人（不排除已发送成功的邮箱）
- 跳过规则（N天内已发送）在重新执行模式下**同样生效**：7 天内已发送（任意任务）的邮箱被跳过并计入 `skipped_count`；`skip_enabled=0` 时不跳过
- 历史发送日志（`uni_email_log`）保留不删
- `pending`/`running`/`paused`/`retrying` 状态任务点重新执行应被拒绝（返回 `success=false`）
- 任务列表 `error`/`completed` 行显示「重新执行」按钮，不再显示「重试失败」按钮

### TC-ETASK-010: 重新执行遵守 7 天跳过规则（Bug 回归）
**模块**: `Sills/email_sender.py::EmailSenderWorker.run()` 跳过逻辑（第 374/470/480 行）
**步骤**:
1. 准备 `completed` 任务 A，其联系人含邮箱 `e1@x.com`（3 天前已发送成功，日志在 `uni_email_log`）
2. 重新执行任务 A
3. 另准备联系人 `e2@x.com`（10 天前发送或从未发送）
**预期**:
- `e1@x.com` 在 7 天窗口内 → 被跳过，不计入 sent，计入 `skipped_count`，Worker 日志打印 `跳过(最近7天已发送)`
- `e2@x.com` 不在 7 天窗口内 → 正常重发
- `skip_enabled=0` 时 `e1@x.com` 也被重发（跳过规则关闭）
- 重新执行模式下不按"当前任务已发送"跳过（即旧日志里的 `e1@x.com` 不会被第 470 行误跳过，而是统一走 7 天规则）
- 单元测试 `tests/test_email_task_reexecute.py` 中 `test_reexecute_skips_recently_sent` / `test_reexecute_skip_disabled_sends_all` / `test_reexecute_ignores_current_task_old_sent` / `test_normal_mode_keeps_current_task_dedup` 4 用例全过

---

## 报价模块 (OFF) 新增

### TC-OFF-013: 批量导入支持 ≥2 空格作为分隔符
**模块**: `Sills/db_offer.py::batch_import_offer_text`
**步骤**:
```
输入文本：
STM32F103  ST  100  Samsung
LM358  TI  50  LG
```
**预期**: 成功导入 2 条，每条 4 列正确切分（≥2 空格命中正则分支）。

### TC-OFF-014: 批量导入保留单空格型号（如 BAT 54C）
**模块**: `Sills/db_offer.py::batch_import_offer_text`
**步骤**: 输入 `BAT 54C  TI  500`（型号内部 1 空格、字段间 2 空格）
**预期**: `inquiry_mpn='BAT 54C'`，3 列。

### TC-OFF-015: 批量导入兼容老 CSV 格式（含逗号）
**模块**: `Sills/db_offer.py::batch_import_offer_text`
**步骤**: 输入老模板（含双引号字段、空字段）：`2026-06-19,"含,逗号,的备注",STM32,,ST,,100,...`
**预期**: 行为与原 csv.reader 完全等价 —— 双引号字段保留、空字段索引保留。

### TC-OFF-016: 多分隔符混合
**模块**: `Sills/db_offer.py::batch_import_offer_text`
**步骤**: 输入 `STM32\tST|100；Samsung，备注`
**预期**: 5 列正确切分（Tab / | / ； / ，）。

---

## 联系人模块 (CTM) 增强 (2026-06-20)

### TC-CTM-011: 导出按筛选条件
**模块**: `main.py::api_contact_export` + `templates/contact.html::exportContacts`
**步骤**:
1. 列表页选 country=韩国 → 点导出
2. 对比全量导出条数
**预期**: 导出文件只含韩国联系人，条数 ≤ 全量；不传参数时全量导出（向后兼容）。

### TC-CTM-012: 5 个统计数字随筛选联动
**模块**: `main.py::api_contact_stats` + `templates/contact.html::loadStats`
**步骤**:
1. 列表页选筛选条件（如 prospect_tag=0）
2. 观察"联系人总数/已发送/已读/未读/退信"5 个数字
**预期**: 数字随筛选条件实时变化（防抖 200ms），筛选无匹配时归零。

### TC-CTM-013: 标识筛选下拉
**模块**: `templates/contact.html::filterTag + loadProspectTagFilter`
**步骤**:
1. 打开联系人列表页
2. 查看"标识"下拉选项
**预期**: 含"全部标识"/"无标识" + 所有 prospect.tag distinct 值（来自 `/api/contact/prospect_tags`）。

### TC-CTM-014: 导出 Excel 含标识列
**模块**: `main.py::api_contact_export`
**步骤**: 导出 Excel，查看列结构
**预期**: 11 列，末列为"标识"（prospect.tag，无 prospect 关联时为空）。

### TC-CTM-015: 导出国家与列表一致（Bug A 回归）
**模块**: `main.py::api_contact_export`
**步骤**:
1. 取一条列表页显示有国家（来自 prospect 回退）的联系人
2. 导出 Excel 查同一条记录
**预期**: 导出的国家值与列表页显示一致（Python `c.country or prospect_country` 回退，空字符串视为 falsy）。

### TC-CTM-016: psycopg 中文 LIKE 参数化（回归）
**模块**: `Sills/db_contact.py::get_marketing_stats`
**步骤**: 在 PostgreSQL 环境下，带任意 filter 调 `get_marketing_stats(filters={...})`
**预期**: 不再触发 `UnicodeDecodeError`（中文关键词已参数化为 `?`）。

### TC-CTM-017: 标识筛选列表数据联动（Bug 1 回归）
**模块**: `main.py::api_contact_list` + `templates/contact.html::filterTag`
**步骤**:
1. 打开联系人列表页，"标识"下拉依次切到 全部/100/1/0/无标识
2. 每次记录列表 total 和统计栏 5 个数字
**预期**: total 随选项变化（全部=12864, 100=484, 1=1343, 0=11037, 无标识=0）；统计数字同步联动；`0+1+100 = 总数` 互斥可累加。

### TC-CTM-018: "无标识"与"0"语义分离（Bug 2 回归）
**模块**: `Sills/db_contact.py::_build_contact_filter_clauses`
**步骤**:
1. 选"无标识" → 列表应为未关联任何 prospect 的联系人
2. 选"0" → 列表为关联了 tag=0 prospect 的联系人
3. 两者数据不重叠
**预期**: "无标识"条件 = `p.prospect_id IS NULL`；"0"条件 = `p.tag = 0`；当前数据下"无标识"=0 条（所有联系人均已关联 prospect）。

---

## 默认原始汇率设置 (2026-07-14 新增)

### TC-DR-001: 默认汇率读写与缓存清除生效
**模块**: `Sills/base.py::get_default_rate/get_all_default_rates/set_default_rates`
**步骤**:
1. 调 `get_all_default_rates()` 读初始值（USD=7.0,KRW=180.0,JPY=20.0,EUR=7.8）
2. 调 `set_default_rates({'1':7.33,'4':7.6})`
3. 调 `get_default_rate(1)`、`get_default_rate(4)`
**预期**: 保存返回 True；保存后 USD=7.33、EUR=7.6（`clear_cache` 已执行，新值立即生效）；测试后还原回初值。

### TC-DR-002: settings 页面卡片渲染
**模块**: `main.py::settings_page` + `templates/settings.html`
**步骤**: 管理员登录后 GET `/settings`
**预期**: 页面含"默认原始汇率设置"卡片；4 个输入框顺序为 韩元(data-code=2)→日元(3)→美元(1)→欧元(4)，与总控制台实时汇率卡片顺序一致；各输入框 value 与 default_rates 对应。

### TC-DR-003: 保存接口正常保存
**模块**: `main.py::api_save_default_rates` (POST `/api/settings/default-rates`)
**步骤**: 管理员 POST `{"rates":{"1":7.33,"2":180.0,"3":20.0,"4":7.8}}`
**预期**: 返回 `{"success":true,"message":"默认原始汇率保存成功",...}`；`get_default_rate(1)` 立即返回 7.33。

### TC-DR-004: 非法值拦截
**模块**: `main.py::api_save_default_rates`
**步骤**: 管理员 POST `{"rates":{"1":"abc"}}`
**预期**: 返回 `{"success":false,"message":"币种 1 的汇率值非法: abc"}`，文件不被修改。

### TC-DR-005: 空参数拦截
**模块**: `main.py::api_save_default_rates`
**步骤**: 管理员 POST `{}`
**预期**: 返回 `{"success":false,"message":"缺少 rates 参数或为空"}`。

### TC-DR-006: 非管理员拦截
**模块**: `main.py::api_save_default_rates` + `settings_page`
**步骤**: rule=2 用户访问
**预期**: GET `/settings` 返回 303 重定向；POST `/api/settings/default-rates` 返回 `{"success":false,"message":"仅管理员可修改默认汇率"}`。

### TC-DR-007: 未登录拦截
**模块**: `main.py::api_save_default_rates`
**步骤**: 不带 cookie POST `/api/settings/default-rates`
**预期**: 返回 401 `{"success":false,"message":"登录已过期，请重新登录"}`。

---

*最后更新：2026-07-14*
