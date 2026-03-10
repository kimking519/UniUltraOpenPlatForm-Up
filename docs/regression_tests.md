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
