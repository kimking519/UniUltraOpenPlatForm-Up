# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

UniUltraOpenPlatForm is a FastAPI-based ERP system for electronic component trading businesses. It manages the complete sales workflow: inquiries (询价) → quotations (报价) → orders (订单) → purchases (采购).

## Commands

1.把所有我输入的prompt保存到一个文件

2.维护一个功能列表文件

3.维护一个表结构文件

4.维护一个单元测试表，用于回归测试



不要修改表，凡是要修改表一定要先告诉我，不能私自执行

你先发不要写代码，你先分析一下，这个变动可能影响到的功能模块，
出现的bug和错误都记录下来，出现了2次以上的bug要记录下来，每次提交前都要回归测试一下

commit的时候添加时间戳精确到分钟

重要！！！ 为了做到需求理解的对称，按提的要求修改bug或者添加功能或者优化之前，先不要写代码，先将你的理解和计划和原因分析跟我沟通，只有我明确告诉你可以的时候才可以开始修改。

出于安全考虑关键key要以单独的文件配置形式来做
----------------------------------------------
为openclaw开发的skills 统一放到openclaw_skills 这目录，skills.md文件的格式参照 Skills_guideline.md
1.这个文件夹要保留sill的同时和工程要解耦，也就是做到可有可无
2.不出现硬编码，操作数据库都通过数据操作层进行修改，不出现sql语句
3.在SKILL.MD可以出现当前的下级相对路径，但是不能出现绝对路径，项目路径要求通过环境变量获取
总之要做到，openclaw_skills要实现的功能通过调用项目里的封装方法，但是项目不依赖openclaw_skills 中的任何skill

架构参考agent-skill-openlaw-arch.md
----------------------------------------------


### Run the Application
```bash
# Development
python main.py

# Or with uvicorn
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Database Management
```bash
# Initialize/reset database
python Sills/base.py
```

### Install Dependencies
```bash
pip install -r requirements.txt
```

## Architecture

### Technology Stack
- **Backend**: FastAPI (single-file `main.py`)
- **Database**: SQLite3 with WAL mode, connection pooling, LRU cache
- **Frontend**: Jinja2 templates + vanilla JavaScript
- **Document Generation**: openpyxl for Excel/CI/PI generation

### Database Layer (`Sills/`)
The `Sills/` directory contains database operation modules, one per entity:
- `base.py` - Database connection, schema, pagination utilities
- `db_emp.py` - Employee management
- `db_cli.py` - Client management
- `db_vendor.py` - Vendor management
- `db_quote.py` - Inquiry/需求 management
- `db_offer.py` - Quotation management
- `db_order.py` - Sales order management
- `db_buy.py` - Purchase management
- `db_daily.py` - Exchange rate management

### Business Entity Flow
```
uni_emp (员工)
    └── uni_cli (客户)
            ├── uni_quote (询价/需求)
            │       └── uni_offer (报价)
            │               └── uni_order (订单)
            │                       └── uni_buy (采购)
```

### ID Generation Patterns
- Employee: `001`, `002` (3-digit)
- Client: `C001`, `C002`
- Vendor: `V001`, `V002`
- Quote: `Q` + timestamp + 4-digit random
- Offer: `O` + timestamp + 4-digit random
- Order: `SO` + timestamp + 4-digit random, with `order_no` format `UNI-客户名-YYYYMMDDHH`
- Purchase: `PU` + timestamp + 4-digit random

### OpenClaw Skills (`openclaw_skills/`)
Automation scripts for document generation and data processing:
- `sale-input-needs/` - Auto-extract inquiry data from chat/email
- `order-ci-generator-kr/` - Generate Commercial Invoice (Korea)
- `order-ci-generator-us/` - Generate Commercial Invoice (US)
- `order-pi-generator/` - Generate Proforma Invoice
- `buyer-make-koquote/` - Generate Korean quotation documents

## Database Schema Key Points

- SQLite WAL mode enabled for concurrent access
- All tables have `created_at` with `datetime('now', 'localtime')`
- Foreign keys with `ON UPDATE CASCADE`
- 19 indexes for query optimization (see `base.py`)
- Exchange rates: currency_code 1=USD, 2=KRW

## Web Routes

### Pages (HTML)
- `/` - Dashboard
- `/login` - Login page
- `/emp`, `/cli`, `/vendor` - Entity management
- `/quote`, `/offer`, `/order`, `/buy` - Sales workflow
- `/daily` - Exchange rate management
- `/settings` - System settings

### API Endpoints
All CRUD operations follow the pattern: `/api/{entity}/{action}`
- Actions: `list`, `add`, `update`, `delete`, `batch_import`, `batch_delete`

## Code Conventions

- Chinese comments and documentation are used throughout
- MD5 password hashing (see `db_emp.py`)
- Permission levels: 1=read-only, 2=edit, 3=admin, 4=disabled
- Default admin account: `Admin` / `uni519`

## Document Output Paths

Generated documents (CI, PI, quotes) are saved to:
- Default: `E:\1_Business\1_Auto\{客户名}\{日期yyyymmdd}\`
- Templates located in `openclaw_skills/*/template/`