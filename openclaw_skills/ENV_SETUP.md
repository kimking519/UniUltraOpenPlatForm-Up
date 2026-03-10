# 环境变量配置

使用 `openclaw_skills` 前需设置以下环境变量：

## 变量说明

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `UNIULTRA_PROJECT_ROOT` | 项目根目录 | 脚本自动检测 |
| `UNIULTRA_DB_PATH` | 数据库路径 | `{PROJECT_ROOT}/uni_platform.db` |
| `UNIULTRA_OUTPUT_DIR` | 输出目录 | `{PROJECT_ROOT}/output` |

## 设置方式

### Windows (PowerShell)
```powershell
$env:UNIULTRA_DB_PATH = "E:\WorkPlace\7_AI_APP\UniUltraOpenPlatForm\uni_platform.db"
$env:UNIULTRA_OUTPUT_DIR = "E:\1_Business\1_Auto"
```

### Windows (CMD)
```cmd
set UNIULTRA_DB_PATH=E:\WorkPlace\7_AI_APP\UniUltraOpenPlatForm\uni_platform.db
set UNIULTRA_OUTPUT_DIR=E:\1_Business\1_Auto
```

### Linux/WSL
```bash
export UNIULTRA_DB_PATH="/mnt/e/WorkPlace/7_AI_APP/UniUltraOpenPlatForm/uni_platform.db"
export UNIULTRA_OUTPUT_DIR="/mnt/e/1_Business/1_Auto"
```

## 使用桥接层

所有 skills 脚本应通过 `openclaw_bridge.py` 访问数据库：

```python
import os
import sys

# 设置项目根目录（如果环境变量未设置）
os.environ.setdefault('UNIULTRA_PROJECT_ROOT',
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 导入桥接层
sys.path.insert(0, os.environ['UNIULTRA_PROJECT_ROOT'])
from openclaw_bridge import (
    DB_PATH, OUTPUT_DIR,
    get_quote_list, add_quote,
    get_offer_list, add_offer,
    get_order_list, add_order,
    get_cli_id_by_name,
    get_orders_for_ci,
    get_exchange_rates,
)
```

## 迁移后的 Skills

以下 skills 已迁移使用桥接层：

| Skill | 功能 | 使用接口 |
|-------|------|----------|
| `sale-input-needs` | 添加询价记录 | `add_quote`, `get_cli_id_by_name` |
| `buyer-tran-order` | 报价转订单 | `get_offer_by_id`, `add_order`, `mark_offer_transferred` |
| `order-ci-generator-kr` | 生成CI文档 | `get_orders_for_ci`, `get_exchange_rates` |
| `sale-query-quote` | 查询报价 | `get_offer_list` |