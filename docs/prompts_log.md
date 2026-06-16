# Prompts 日志

记录所有用户输入的 prompt 和系统响应历史。

---

## 2026-02-28

### Prompt #1
**时间**: 2026-02-28
**内容**: 提交到这个 github 仓库 https://github.com/kimking519/UniUltraOpenPlatForm-Cld.git

**响应**:
- 初始化 git 仓库
- 配置远程仓库
- 添加所有项目文件并创建初始提交
- 推送到 GitHub main 分支

---

### Prompt #2
**时间**: 2026-02-28
**内容**:
1. 把所有我输入的 prompt 保存到一个文件
2. 维护一个功能列表文件
3. 维护一个表结构文件
4. 维护一个单元测试表，用于回归测试

**响应**:
- 创建 `docs/prompts_log.md` - 记录用户 prompt 历史
- 创建 `docs/features.md` - 项目功能列表
- 创建 `docs/database_schema.md` - 数据库表结构文档
- 创建 `docs/regression_tests.md` - 回归测试用例

---

## 格式说明

每条记录包含：
- 时间戳
- Prompt 内容
- 系统响应摘要

---

## 2026-06-16 12:13 - 待开发客户批量导入数据丢失修复

**Prompt 序列**:
1. `http://127.0.0.1:8001/contact 联系人管理-待开发客户中 这个页面批量导入2093条，结果只显示1998总数，修复一下`
2. `1. 诊断为主：  导入后并没有提示`
3. `可以 ，开始`（提供文件路径 `C:\Users\96272\Downloads\待开发客户_20260616_120218.xlsx`）
4. `继续`
5. `1A 2是 3是 4a`（确认修复方案选择）

**响应摘要**:
- 诊断定位根因：`get_next_prospect_id` 秒级时间戳+4位随机在 2093/2.65s 高并发下产生 PK 冲突，95 条被 duplicate key 静默 skip
- 修复 `Sills/base.py`: 新增 `gen_unique_id(prefix)` 公用函数（微秒+计数器）
- 修复 6 个 ID 生成器: prospect/contact/group/task/template/email_account
- 修复前端 `templates/contact.html`: 加 loading 遮罩 + 错误明细 alert
- 端到端回归测试通过（100/100/0/0）
