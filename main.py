from fastapi import FastAPI, Request, Form, Depends, HTTPException, Response, Cookie, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import asyncio
import threading
from Sills.base import init_db, get_db_connection, get_exchange_rates
from Sills.db_daily import get_daily_list, add_daily, update_daily
from Sills.db_emp import get_emp_list, add_employee, batch_import_text, verify_login, change_password, update_employee, delete_employee
from Sills.db_vendor import add_vendor, batch_import_vendor_text, update_vendor, delete_vendor
from Sills.db_cli import get_cli_list, add_cli, batch_import_cli_text, update_cli, delete_cli
from Sills.db_quote import get_quote_list, add_quote, batch_import_quote_text, delete_quote, update_quote, batch_delete_quote, batch_copy_quote, batch_add_quotes
from Sills.db_offer import get_offer_list, add_offer, batch_import_offer_text, update_offer, delete_offer, batch_delete_offer, batch_convert_from_quote
from Sills.db_order import get_order_list, add_order, update_order_status, update_order, delete_order, batch_import_order, batch_delete_order, batch_convert_from_offer, get_order_by_id
from Sills.db_buy import get_buy_list, add_buy, update_buy_node, update_buy, delete_buy, batch_import_buy, batch_delete_buy, batch_convert_from_order
from Sills.db_mail import (
    get_mail_list, get_mail_by_id, save_email, delete_email,
    create_mail_relation, get_mail_relations, remove_mail_relation,
    get_mail_config, is_sync_locked, get_sync_progress,
    # 多账户管理
    get_all_mail_accounts, get_mail_account_by_id, add_mail_account,
    update_mail_account, switch_current_account, delete_mail_account,
    # 同步间隔设置
    get_sync_interval, set_sync_interval,
    # 文件夹管理
    get_folders, get_folder_by_id, add_folder, update_folder, delete_folder,
    get_mail_count_by_folder, get_mails_by_folder,
    # 过滤规则管理
    get_filter_rules, add_filter_rule, update_filter_rule, delete_filter_rule,
    # 自动分类
    auto_classify_emails
)
from Sills.mail_service import sync_inbox, sync_inbox_async, send_email_now
from Sills.ai_service import intent_recognizer, smart_replier

from typing import Optional
import uvicorn
import shutil
import os
import platform
import io
import json
import base64
import urllib.request
import urllib.error
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import openpyxl

app = FastAPI()

# 内部服务API密钥（用于skill调用绕过认证）
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "dev-local-key")

# 开发模式：跳过认证校验（生产环境设为False）
SKIP_AUTH = os.environ.get("SKIP_AUTH", "true").lower() == "true"

# Add session middleware
app.add_middleware(SessionMiddleware, secret_key="uni_platform_secret_key_2026")

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.on_event("startup")
async def startup_event():
    init_db()
    # 启动自动备份定时任务
    start_auto_backup()

def get_backup_root():
    """获取备份根目录"""
    is_windows = platform.system() == "Windows"
    return r"E:\WorkPlace\1_AIemployee\备份目录" if is_windows else "/home/kim/workspace/DbBackup"

def get_server_env():
    """检测服务器环境（包括WSL）"""
    system = platform.system()

    if system == "Linux":
        # 检测是否是WSL
        try:
            with open("/proc/version", "r") as f:
                version = f.read().lower()
                if "microsoft" in version or "wsl" in version:
                    return "WSL"
        except:
            pass
        return "Linux"
    elif system == "Windows":
        return "Windows"
    elif system == "Darwin":
        return "macOS"
    else:
        return system

def do_backup():
    """执行备份操作（内部函数，无权限检查）"""
    backup_root = get_backup_root()
    date_str = datetime.now().strftime("%Y%m%d%H")  # 精确到小时
    backup_dir = os.path.join(backup_root, f"backup_{date_str}")

    # 确保备份根目录存在
    if not os.path.exists(backup_root):
        os.makedirs(backup_root, exist_ok=True)

    # If exists, delete and recreate
    if os.path.exists(backup_dir):
        shutil.rmtree(backup_dir)
    os.makedirs(backup_dir, exist_ok=True)

    # Copy all .db files from project root
    project_root = os.path.dirname(os.path.abspath(__file__))
    db_files = [f for f in os.listdir(project_root) if f.endswith(".db")]

    for db_file in db_files:
        src = os.path.join(project_root, db_file)
        dst = os.path.join(backup_dir, db_file)
        shutil.copy2(src, dst)

    # Copy static directory
    static_src = os.path.join(project_root, "static")
    if os.path.exists(static_src):
        static_dst = os.path.join(backup_dir, "static")
        shutil.copytree(static_src, static_dst, dirs_exist_ok=True)

    return len(db_files), backup_dir

def cleanup_old_backups(backup_root, days=3):
    """清理超过指定天数的备份目录"""
    if not os.path.exists(backup_root):
        return 0

    deleted_count = 0
    cutoff_time = datetime.now().timestamp() - (days * 24 * 60 * 60)

    for item in os.listdir(backup_root):
        if item.startswith("backup_"):
            item_path = os.path.join(backup_root, item)
            if os.path.isdir(item_path):
                try:
                    # 获取目录修改时间
                    mtime = os.path.getmtime(item_path)
                    if mtime < cutoff_time:
                        shutil.rmtree(item_path)
                        deleted_count += 1
                        print(f"[备份清理] 已删除过期备份: {item}")
                except Exception as e:
                    print(f"[备份清理] 删除 {item} 失败: {str(e)}")

    return deleted_count

def auto_backup_task():
    """自动备份定时任务"""
    while True:
        try:
            count, backup_dir = do_backup()
            print(f"[自动备份] 成功备份 {count} 个数据库文件到 {backup_dir}")

            # 清理超过3天的备份
            backup_root = get_backup_root()
            deleted = cleanup_old_backups(backup_root, days=3)
            if deleted > 0:
                print(f"[自动备份] 已清理 {deleted} 个过期备份")
        except Exception as e:
            print(f"[自动备份] 失败: {str(e)}")
        # 每30分钟执行一次
        threading.Event().wait(1800)

def start_auto_backup():
    """启动自动备份线程"""
    backup_thread = threading.Thread(target=auto_backup_task, daemon=True)
    backup_thread.start()
    print("[系统] 自动备份服务已启动，每30分钟执行一次")
    # 注意：自动备份线程会立即执行第一次备份，不需要在这里重复执行

async def get_current_user(request: Request, emp_id: str = Cookie(None), rule: str = Cookie(None), account: str = Cookie(None)):
    # 0. 开发模式：跳过认证
    if SKIP_AUTH:
        return {"emp_id": "000", "rule": "3", "account": "Dev-Mode"}

    # 1. 检查内部服务API密钥（优先）- 用于skill调用
    internal_key = request.headers.get("X-Internal-API-Key")
    if internal_key == INTERNAL_API_KEY:
        return {"emp_id": "000", "rule": "3", "account": "Internal-Service"}

    # 2. 正常Cookie认证流程
    if not emp_id or not rule:
        return None
    return {"emp_id": emp_id, "rule": rule, "account": account}

async def login_required(current_user: dict = Depends(get_current_user)):
    if not current_user:
        raise HTTPException(status_code=303, headers={"Location": "/login"})
    return current_user

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, current_user: dict = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
        
    with get_db_connection() as conn:
        cli_count = conn.execute("SELECT COUNT(*) FROM uni_cli").fetchone()[0]
        emp_count = conn.execute("SELECT COUNT(*) FROM uni_emp").fetchone()[0]
        order_sum = conn.execute("SELECT IFNULL(SUM(paid_amount), 0) FROM uni_order").fetchone()[0]
        
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "active_page": "dashboard",
        "current_user": current_user,
        "stats": {
            "cli_count": cli_count,
            "emp_count": emp_count,
            "order_sum": order_sum
        }
    })

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = "", account: str = ""):
    return templates.TemplateResponse("login.html", {"request": request, "error": error, "account": account})

@app.post("/login")
async def login(response: Response, account: str = Form(...), password: str = Form(...)):
    if account == "Admin" and password == "uni519":
        # System init backdoor, just in case
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(key="emp_id", value="000")
        response.set_cookie(key="account", value="Admin")
        response.set_cookie(key="rule", value="3")
        return response

    ok, user, msg = verify_login(account, password)
    if not ok:
        # Redirect back to login with error message and retained account
        return RedirectResponse(url=f"/login?error={msg}&account={account}", status_code=303)
    
    # Check if first time login (password is default 12345)
    from Sills.db_emp import hash_password
    if user['password'] == hash_password('12345'):
        response = RedirectResponse(url="/change_password", status_code=303)
        response.set_cookie(key="emp_id", value=user['emp_id'])
        response.set_cookie(key="account", value=user['account'])
        response.set_cookie(key="rule", value=user['rule'])
        return response

    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="emp_id", value=str(user['emp_id']))
    response.set_cookie(key="account", value=str(user['account']))
    response.set_cookie(key="rule", value=str(user['rule']))
    return response

@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("emp_id")
    response.delete_cookie("rule")
    response.delete_cookie("account")
    return response

@app.get("/change_password", response_class=HTMLResponse)
async def change_pwd_page(request: Request, current_user: dict = Depends(get_current_user), error: str = ""):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse("change_pwd.html", {"request": request, "current_user": current_user, "error": error})

@app.post("/change_password")
async def change_pwd_post(new_password: str = Form(...), confirm_password: str = Form(...), current_user: dict = Depends(get_current_user)):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)
    
    if new_password == '12345':
        return RedirectResponse(url="/change_password?error=新密码不能为12345", status_code=303)
    if new_password != confirm_password:
        return RedirectResponse(url="/change_password?error=两次输入的密码不一致", status_code=303)
        
    change_password(current_user['emp_id'], new_password)
    return RedirectResponse(url="/", status_code=303)

# Placeholder routes for modules 1-8
@app.get("/daily", response_class=HTMLResponse)
async def daily_page(request: Request, page: int = 1, current_user: dict = Depends(login_required)):
    items, total = get_daily_list(page=page)
    return templates.TemplateResponse("daily.html", {
        "request": request, 
        "active_page": "daily",
        "current_user": current_user,
        "items": items,
        "total": total,
        "page": page
    })

@app.post("/daily/add")
async def daily_add(currency_code: int = Form(...), exchange_rate: float = Form(...), current_user: dict = Depends(login_required)):
    from datetime import datetime
    record_date = datetime.now().strftime('%Y-%m-%d')
    success, msg = add_daily(record_date, currency_code, exchange_rate)
    return RedirectResponse(url="/daily", status_code=303)

@app.post("/api/daily/update")
async def daily_update_api(id: int = Form(...), exchange_rate: float = Form(...), current_user: dict = Depends(login_required)):
    success, msg = update_daily(id, exchange_rate)
    return {"success": success, "message": msg}

@app.get("/emp", response_class=HTMLResponse)
async def emp_page(request: Request, page: int = 1, search: str = "", current_user: dict = Depends(login_required)):
    items, total = get_emp_list(page=page, search=search)
    return templates.TemplateResponse("emp.html", {
        "request": request, 
        "active_page": "emp",
        "current_user": current_user,
        "items": items,
        "total": total,
        "page": page,
        "search": search
    })

@app.post("/emp/add")
async def emp_add(
    emp_name: str = Form(...), department: str = Form(""), position: str = Form(""),
    contact: str = Form(""), account: str = Form(...), hire_date: str = Form(...),
    rule: str = Form("1"), remark: str = Form(""),
    current_user: dict = Depends(login_required)
):
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/emp", status_code=303)
        
    data = {
        "emp_name": emp_name, "department": department, "position": position,
        "contact": contact, "account": account, "password": "12345",
        "hire_date": hire_date,
        "rule": rule, "remark": remark
    }
    success, msg = add_employee(data)
    return RedirectResponse(url="/emp", status_code=303)

@app.post("/emp/import")
async def emp_import(import_text: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/emp", status_code=303)
    success_count, errors = batch_import_text(import_text)
    return RedirectResponse(url=f"/emp?import_success={success_count}&errors={len(errors)}", status_code=303)

@app.post("/emp/import/csv")
async def emp_import_csv(csv_file: UploadFile = File(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/emp", status_code=303)
    content = await csv_file.read()
    try:
        text = content.decode('utf-8-sig').strip()
    except UnicodeDecodeError:
        text = content.decode('gbk', errors='replace').strip()
        
    if '\n' in text:
        text = text.split('\n', 1)[1] # skip header
    success_count, errors = batch_import_text(text)
    return RedirectResponse(url=f"/emp?import_success={success_count}&errors={len(errors)}", status_code=303)

@app.post("/api/emp/update")
async def emp_update_api(emp_id: str = Form(...), field: str = Form(...), value: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return {"success": False, "message": "无权限"}
    # Only allow certain fields
    allowed_fields = ['emp_name', 'account', 'password', 'department', 'position', 'rule', 'contact', 'hire_date', 'remark']
    if field not in allowed_fields:
        return {"success": False, "message": "非法字段"}
    
    success, msg = update_employee(emp_id, {field: value})
    return {"success": success, "message": msg}

@app.post("/api/emp/delete")
async def emp_delete_api(emp_id: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return {"success": False, "message": "无权限"}
    success, msg = delete_employee(emp_id)
    return {"success": success, "message": msg}

from Sills.base import get_paginated_list

@app.get("/vendor", response_class=HTMLResponse)
async def vendor_page(request: Request, page: int = 1, search: str = "", current_user: dict = Depends(login_required)):
    search_kwargs = {"vendor_name": search} if search else None
    result = get_paginated_list("uni_vendor", page=page, search_kwargs=search_kwargs)
    return templates.TemplateResponse("vendor.html", {
        "request": request, "active_page": "vendor", "current_user": current_user,
        "items": result["items"], "total_pages": result["total_pages"], 
        "page": page, "search": search, "active_page": "vendor"
    })

@app.post("/vendor/add")
async def vendor_add(
    vendor_name: str = Form(...), address: str = Form(""), qq: str = Form(""),
    wechat: str = Form(""), email: str = Form(""), remark: str = Form(""),
    current_user: dict = Depends(login_required)
):
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/vendor", status_code=303)
    data = {
        "vendor_name": vendor_name, "address": address, "qq": qq,
        "wechat": wechat, "email": email, "remark": remark
    }
    add_vendor(data)
    return RedirectResponse(url="/vendor", status_code=303)

@app.post("/vendor/import")
async def vendor_import(import_text: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/vendor", status_code=303)
    success_count, errors = batch_import_vendor_text(import_text)
    return RedirectResponse(url=f"/vendor?import_success={success_count}&errors={len(errors)}", status_code=303)

@app.post("/vendor/import/csv")
async def vendor_import_csv(csv_file: UploadFile = File(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/vendor", status_code=303)
    content = await csv_file.read()
    try:
        text = content.decode('utf-8-sig').strip()
    except UnicodeDecodeError:
        text = content.decode('gbk', errors='replace').strip()
        
    if '\n' in text:
        text = text.split('\n', 1)[1] # skip header
    success_count, errors = batch_import_vendor_text(text)
    return RedirectResponse(url=f"/vendor?import_success={success_count}&errors={len(errors)}", status_code=303)

@app.post("/api/vendor/update")
async def vendor_update_api(vendor_id: str = Form(...), field: str = Form(...), value: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return {"success": False, "message": "无权限"}
    allowed_fields = ['vendor_name', 'address', 'qq', 'wechat', 'email', 'remark']
    if field not in allowed_fields:
        return {"success": False, "message": "非法字段"}
    success, msg = update_vendor(vendor_id, {field: value})
    return {"success": success, "message": msg}

@app.post("/api/vendor/delete")
async def vendor_delete_api(vendor_id: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return {"success": False, "message": "无权限"}
    success, msg = delete_vendor(vendor_id)
    return {"success": success, "message": msg}

@app.get("/cli", response_class=HTMLResponse)
async def cli_page(request: Request, page: int = 1, search: str = "", current_user: dict = Depends(login_required)):
    search_kwargs = {"cli_name": search} if search else None
    result = get_paginated_list("uni_cli", page=page, search_kwargs=search_kwargs)
    
    # Needs employees for dropdown
    employees, _ = get_emp_list(page=1, page_size=1000)
    
    return templates.TemplateResponse("cli.html", {
        "request": request, "active_page": "cli", "current_user": current_user,
        "items": result["items"], "total_pages": result["total_pages"], 
        "page": page, "search": search, "employees": employees
    })

@app.post("/cli/add")
async def cli_add(
    cli_name: str = Form(...), cli_full_name: str = Form(""), cli_name_en: str = Form(""),
    contact_name: str = Form(""), address: str = Form(""),
    region: str = Form("韩国"), credit_level: str = Form("A"),
    margin_rate: float = Form(10.0), emp_id: str = Form(...), website: str = Form(""),
    payment_terms: str = Form(""), email: str = Form(""), phone: str = Form(""),
    remark: str = Form(""), current_user: dict = Depends(login_required)
):
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/cli", status_code=303)
    data = {
        "cli_name": cli_name, "cli_full_name": cli_full_name, "cli_name_en": cli_name_en,
        "contact_name": contact_name, "address": address,
        "region": region, "credit_level": credit_level,
        "margin_rate": margin_rate, "emp_id": emp_id, "website": website,
        "payment_terms": payment_terms, "email": email, "phone": phone, "remark": remark
    }
    add_cli(data)
    return RedirectResponse(url="/cli", status_code=303)

@app.post("/cli/import")
async def cli_import(import_text: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/cli", status_code=303)
    success_count, errors = batch_import_cli_text(import_text)
    return RedirectResponse(url=f"/cli?import_success={success_count}&errors={len(errors)}", status_code=303)

@app.post("/cli/import/csv")
async def cli_import_csv(csv_file: UploadFile = File(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/cli", status_code=303)
    content = await csv_file.read()
    try:
        text = content.decode('utf-8-sig').strip()
    except UnicodeDecodeError:
        text = content.decode('gbk', errors='replace').strip()
        
    if '\n' in text:
        text = text.split('\n', 1)[1] # skip header
    success_count, errors = batch_import_cli_text(text)
    return RedirectResponse(url=f"/cli?import_success={success_count}&errors={len(errors)}", status_code=303)

@app.post("/api/order/update")
async def order_update_api(order_id: str = Form(...), field: str = Form(...), value: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return {"success": False, "message": "无修改权限"}

    allowed_fields = ['order_no', 'order_date', 'inquiry_mpn', 'inquiry_brand', 'price_rmb', 'price_kwr', 'price_usd', 'cost_price_rmb', 'paid_amount', 'return_status', 'remark', 'is_transferred']
    if field not in allowed_fields:
        return {"success": False, "message": f"非法字段: {field}"}

    if field in ['price_rmb', 'price_kwr', 'price_usd', 'cost_price_rmb', 'paid_amount']:
        try:
            val = float(value)

            # 当修改price_rmb时，自动计算price_kwr和price_usd
            if field == 'price_rmb':
                from Sills.base import get_exchange_rates
                krw_rate, usd_rate = get_exchange_rates()

                # 汇率含义: 1 RMB = X 外币
                # price_kwr = price_rmb * krw_rate (韩元)
                # price_usd = price_rmb * usd_rate (美元)
                price_kwr = round(val * krw_rate, 1) if krw_rate else 0
                price_usd = round(val * usd_rate, 3) if usd_rate else 0

                # 同时更新三个价格字段
                success, msg = update_order(order_id, {
                    'price_rmb': val,
                    'price_kwr': price_kwr,
                    'price_usd': price_usd
                })

                # 获取成本价计算利润
                order_info = get_order_by_id(order_id)
                cost_price = float(order_info.get('cost_price_rmb') or 0) if order_info else 0
                profit = round(val - cost_price, 3)

                return {"success": success, "message": msg, "price_kwr": price_kwr, "price_usd": price_usd, "profit": profit}

            # 当修改cost_price_rmb时，计算利润
            if field == 'cost_price_rmb':
                success, msg = update_order(order_id, {field: val})

                # 获取销售价计算利润
                order_info = get_order_by_id(order_id)
                price_rmb = float(order_info.get('price_rmb') or 0) if order_info else 0
                profit = round(price_rmb - val, 3)

                return {"success": success, "message": msg, "profit": profit}

            success, msg = update_order(order_id, {field: val})
            return {"success": success, "message": msg}
        except:
            return {"success": False, "message": "必须是数字"}

    success, msg = update_order(order_id, {field: value})
    return {"success": success, "message": msg}

@app.post("/api/order/update_status")
async def order_update_status_api(order_id: str = Form(...), field: str = Form(...), value: str = Form(...), current_user: dict = Depends(login_required)):
    from Sills.db_order import update_order_status
    success, msg = update_order_status(order_id, field, value)
    return {"success": success, "message": msg}

@app.post("/api/cli/update")
async def cli_update_api(cli_id: str = Form(...), field: str = Form(...), value: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return {"success": False, "message": "无权限"}
    allowed_fields = ['cli_name', 'cli_full_name', 'cli_name_en', 'contact_name', 'address', 'region', 'credit_level', 'margin_rate', 'emp_id', 'website', 'payment_terms', 'email', 'phone', 'remark']
    if field not in allowed_fields:
        return {"success": False, "message": "非法字段"}
    
    if field == 'margin_rate':
        try: 
            val = float(value)
            success, msg = update_cli(cli_id, {field: val})
            return {"success": success, "message": msg}
        except: 
            return {"success": False, "message": "利润率必须是数字"}
        
    success, msg = update_cli(cli_id, {field: value})
    return {"success": success, "message": msg}

@app.post("/api/cli/delete")
async def cli_delete_api(cli_id: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] != '3':
        return {"success": False, "message": "仅管理员可删除"}
    success, msg = delete_cli(cli_id)
    return {"success": success, "message": msg}

@app.post("/api/cli/batch_delete")
async def cli_batch_delete_api(request: Request, current_user: dict = Depends(login_required)):
    """批量删除客户"""
    if current_user['rule'] != '3':
        return {"success": False, "message": "仅管理员可删除"}

    from Sills.db_cli import batch_delete_cli
    data = await request.json()
    cli_ids = data.get('ids', [])

    if not cli_ids:
        return {"success": False, "message": "未选择记录"}

    deleted_count, failed_count, msg = batch_delete_cli(cli_ids)
    return {
        "success": True,
        "deleted_count": deleted_count,
        "failed_count": failed_count,
        "message": msg
    }

@app.get("/api/cli/list")
async def cli_list_api(current_user: dict = Depends(get_current_user)):
    """获取客户列表API（用于邮件关联选择器）"""
    if not current_user:
        return {"success": False, "message": "未登录", "items": []}
    items, total = get_cli_list(page=1, page_size=1000)
    return {"success": True, "items": items, "total": total}

@app.get("/api/order/list")
async def order_list_api(current_user: dict = Depends(get_current_user)):
    """获取订单列表API（用于邮件关联选择器）"""
    if not current_user:
        return {"success": False, "message": "未登录", "items": []}
    items, total = get_order_list(page=1, page_size=1000)
    return {"success": True, "items": items, "total": total}

# ---------------- Quote Module ----------------
@app.get("/quote", response_class=HTMLResponse)
async def quote_page(request: Request, current_user: dict = Depends(login_required), page: int = 1, page_size: int = 20, search: str = "", start_date: str = "", end_date: str = "", cli_id: str = "", status: str = "", is_transferred: str = ""):
    # 从 session 获取筛选条件
    session = request.session
    # 检查 URL 中是否有筛选参数（包括空值）
    has_params = any(k in request.query_params for k in ['search', 'start_date', 'end_date', 'cli_id', 'status', 'is_transferred'])

    if not has_params:
        # 首次访问或无参数，从 session 读取
        search = session.get("quote_search", "")
        start_date = session.get("quote_start_date", "")
        end_date = session.get("quote_end_date", "")
        cli_id = session.get("quote_cli_id", "")
        status = session.get("quote_status", "")
        is_transferred = session.get("quote_is_transferred", "")
    else:
        # 有参数时（包括空值），保存到 session
        session["quote_search"] = search
        session["quote_start_date"] = start_date
        session["quote_end_date"] = end_date
        session["quote_cli_id"] = cli_id
        session["quote_status"] = status
        session["quote_is_transferred"] = is_transferred

    results, total = get_quote_list(page=page, page_size=page_size, search_kw=search, start_date=start_date, end_date=end_date, cli_id=cli_id, status=status, is_transferred=is_transferred)
    total_pages = (total + page_size - 1) // page_size
    cli_list, _ = get_cli_list(page=1, page_size=1000)
    return templates.TemplateResponse("quote.html", {
        "request": request,
        "active_page": "quote",
        "current_user": current_user,
        "items": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "search": search,
        "start_date": start_date,
        "end_date": end_date,
        "cli_id": cli_id,
        "status": status,
        "is_transferred": is_transferred,
        "cli_list": cli_list
    })

@app.post("/quote/add")
async def quote_add(request: Request, current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/quote", status_code=303)
    form = await request.form()
    data = dict(form)
    ok, msg = add_quote(data)
    import urllib.parse
    msg_param = urllib.parse.quote(msg)
    success = 1 if ok else 0
    return RedirectResponse(url=f"/quote?msg={msg_param}&success={success}", status_code=303)

@app.post("/quote/import")
async def quote_import_text(batch_text: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/quote", status_code=303)
    success_count, errors = batch_import_quote_text(batch_text)
    err_msg = ""
    if errors:
        import urllib.parse
        err_msg = "&msg=" + urllib.parse.quote(errors[0])
    return RedirectResponse(url=f"/quote?import_success={success_count}&errors={len(errors)}{err_msg}", status_code=303)

@app.post("/quote/import/csv")
async def quote_import_csv(csv_file: UploadFile = File(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/quote", status_code=303)
    content = await csv_file.read()
    try:
        text = content.decode('utf-8-sig').strip()
    except UnicodeDecodeError:
        text = content.decode('gbk', errors='replace').strip()
        
    # Pass full text to sill
    success_count, errors = batch_import_quote_text(text)
    err_msg = ""
    if errors:
        import urllib.parse
        err_msg = "&msg=" + urllib.parse.quote(errors[0])
    return RedirectResponse(url=f"/quote?import_success={success_count}&errors={len(errors)}{err_msg}", status_code=303)

@app.post("/api/quote/update")
async def quote_update_api(quote_id: str = Form(...), field: str = Form(...), value: str = Form(default=""), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return {"success": False, "message": "无修改权限"}
        
    allowed_fields = ['cli_id', 'inquiry_mpn', 'quoted_mpn', 'inquiry_brand', 'inquiry_qty', 'actual_qty', 'target_price_rmb', 'cost_price_rmb', 'date_code', 'delivery_date', 'status', 'is_transferred', 'remark']
    if field not in allowed_fields:
        return {"success": False, "message": f"非法字段: {field}"}

    if field in ['inquiry_qty', 'actual_qty', 'target_price_rmb', 'cost_price_rmb']:
        try:
            val = float(value) if 'price' in field else int(value)
            success, msg = update_quote(quote_id, {field: val})
            return {"success": success, "message": msg}
        except:
            return {"success": False, "message": "必须是数字"}
            
    success, msg = update_quote(quote_id, {field: value})
    return {"success": success, "message": msg}

@app.post("/api/quote/delete")
async def quote_delete_api(quote_id: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] != '3':
        return {"success": False, "message": "仅管理员可删除"}
    success, msg = delete_quote(quote_id)
    return {"success": success, "message": msg}

@app.post("/api/quote/batch_delete")
async def quote_batch_delete_api(request: Request, current_user: dict = Depends(login_required)):
    if current_user['rule'] != '3':
        return {"success": False, "message": "仅管理员可删除"}
    data = await request.json()
    ids = data.get("ids", [])
    success, msg = batch_delete_quote(ids)
    return {"success": success, "message": msg}

@app.post("/api/quote/batch_copy")
async def quote_batch_copy_api(request: Request, current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return {"success": False, "message": "无权限复制需求"}
    data = await request.json()
    ids = data.get("ids", [])
    success, msg = batch_copy_quote(ids)
    return {"success": success, "message": msg}

@app.post("/api/quote/batch_add")
async def quote_batch_add_api(request: Request):
    """批量添加询价记录 - 供 skill 调用，使用内部 API Key 认证"""
    # 检查内部 API Key
    internal_key = request.headers.get("X-Internal-API-Key")
    if internal_key != INTERNAL_API_KEY:
        return {"success": False, "message": "无权限访问"}

    try:
        data = await request.json()
        items = data.get("items", [])

        if not items:
            return {"success": False, "message": "缺少 items 参数"}

        success_count, errors, created_ids = batch_add_quotes(items)

        return {
            "success": True,
            "message": f"成功添加 {success_count} 条记录",
            "success_count": success_count,
            "error_count": len(errors),
            "errors": errors,
            "created_ids": created_ids
        }
    except Exception as e:
        return {"success": False, "message": f"批量添加失败: {str(e)}"}

@app.get("/api/quote/info")
async def get_quote_info_api(id: str, current_user: dict = Depends(login_required)):
    from Sills.base import get_db_connection
    with get_db_connection() as conn:
        row = conn.execute("SELECT q.*, c.cli_name FROM uni_quote q LEFT JOIN uni_cli c ON q.cli_id = c.cli_id WHERE q.quote_id = ?", (id,)).fetchone()
        if row:
            return {"success": True, "data": dict(row)}
        return {"success": False, "message": "未找到"}

@app.post("/api/quote/export_offer_csv")
async def quote_export_offer_csv(request: Request, current_user: dict = Depends(login_required)):
    data = await request.json()
    ids = data.get("ids", [])
    if not ids:
        return {"success": False, "message": "未选择任何记录进行导出"}

    from Sills.base import get_db_connection
    placeholders = ','.join(['?'] * len(ids))
    with get_db_connection() as conn:
        quotes = conn.execute(f"""
            SELECT q.*, c.cli_name
            FROM uni_quote q
            LEFT JOIN uni_cli c ON q.cli_id = c.cli_id
            WHERE q.quote_id IN ({placeholders})
        """, ids).fetchall()

    import io, csv
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    # 字段顺序与页面显示一致
    writer.writerow(['需求日期','需求编号','客户名称','询价型号','报价型号','询价品牌','需求数量','目标价','成本价','批号','交期','状态','已转','备注'])

    for q in quotes:
        q_dict = dict(q)
        writer.writerow([
            q_dict.get('quote_date', ''),
            q_dict.get('quote_id', ''),
            q_dict.get('cli_name', ''),
            q_dict.get('inquiry_mpn', ''),
            q_dict.get('quoted_mpn', ''),
            q_dict.get('inquiry_brand', ''),
            q_dict.get('inquiry_qty', 0),
            q_dict.get('target_price_rmb', 0.0),
            q_dict.get('cost_price_rmb', 0.0),
            q_dict.get('date_code', ''),
            q_dict.get('delivery_date', ''),
            q_dict.get('status', ''),
            q_dict.get('is_transferred', ''),
            q_dict.get('remark', '')
        ])

    return {"success": True, "csv_content": output.getvalue()}

# ---------------- Offer Module ----------------
@app.get("/offer", response_class=HTMLResponse)
async def offer_page(request: Request, current_user: dict = Depends(login_required), page: int = 1, page_size: int = 20, search: str = "", start_date: str = "", end_date: str = "", cli_id: str = "", is_transferred: str = ""):
    # 从 session 获取筛选条件
    session = request.session
    # 检查 URL 中是否有筛选参数（包括空值）
    has_params = any(k in request.query_params for k in ['search', 'start_date', 'end_date', 'cli_id', 'is_transferred'])

    if not has_params:
        # 首次访问或无参数，从 session 读取
        search = session.get("offer_search", "")
        start_date = session.get("offer_start_date", "")
        end_date = session.get("offer_end_date", "")
        cli_id = session.get("offer_cli_id", "")
        is_transferred = session.get("offer_is_transferred", "未转")
        page_size = session.get("offer_page_size", 20)
    else:
        # 有参数（包括空值），保存到 session
        session["offer_search"] = search
        session["offer_start_date"] = start_date
        session["offer_end_date"] = end_date
        session["offer_cli_id"] = cli_id
        session["offer_is_transferred"] = is_transferred
        session["offer_page_size"] = page_size

    # is_transferred 空字符串表示"全部"，直接传递给查询层处理
    # 首次访问时 session 默认为"未转"，用户选择"全部"后 session 保存空字符串
    query_is_transferred = is_transferred
    results, total = get_offer_list(page=page, page_size=page_size, search_kw=search, start_date=start_date, end_date=end_date, cli_id=cli_id, is_transferred=query_is_transferred)
    total_pages = (total + page_size - 1) // page_size
    from Sills.base import get_paginated_list
    vendor_data = get_paginated_list('uni_vendor', page=1, page_size=1000)
    vendor_list = vendor_data['items']
    cli_data = get_paginated_list('uni_cli', page=1, page_size=1000)
    cli_list = cli_data['items']
    return templates.TemplateResponse("offer.html", {
        "request": request,
        "active_page": "offer",
        "current_user": current_user,
        "items": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "search": search,
        "start_date": start_date,
        "end_date": end_date,
        "cli_id": cli_id,
        "is_transferred": is_transferred,
        "vendor_list": vendor_list,
        "cli_list": cli_list
    })

@app.post("/offer/add")
async def offer_add_route(request: Request, current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/offer", status_code=303)
    form = await request.form()
    data = dict(form)
    data['emp_id'] = current_user['emp_id']
    
    # 自动报价逻辑：如果报价为 0 且指定了需求，则联动客户利润率
    if (not data.get('offer_price_rmb') or float(data.get('offer_price_rmb')) == 0) and data.get('quote_id'):
        from Sills.base import get_db_connection
        with get_db_connection() as conn:
            clip = conn.execute("""
                SELECT c.margin_rate, q.cost_price_rmb 
                FROM uni_quote q 
                JOIN uni_cli c ON q.cli_id = c.cli_id 
                WHERE q.quote_id = ?
            """, (data['quote_id'],)).fetchone()
            if clip and clip['cost_price_rmb']:
                margin = float(clip['margin_rate'] or 10.0)
                cost = float(clip['cost_price_rmb'])
                data['offer_price_rmb'] = round(cost * (1 + margin / 100.0), 4)
                if not data.get('cost_price_rmb') or float(data.get('cost_price_rmb')) == 0:
                    data['cost_price_rmb'] = cost

    ok, msg = add_offer(data)
    import urllib.parse
    msg_param = urllib.parse.quote(msg)
    success = 1 if ok else 0
    return RedirectResponse(url=f"/offer?msg={msg_param}&success={success}", status_code=303)

@app.post("/offer/import")
async def offer_import_text(batch_text: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/offer", status_code=303)
    success_count, errors = batch_import_offer_text(batch_text, current_user['emp_id'])
    err_msg = ""
    if errors:
        import urllib.parse
        err_msg = "&msg=" + urllib.parse.quote(errors[0])
    return RedirectResponse(url=f"/offer?import_success={success_count}&errors={len(errors)}{err_msg}", status_code=303)

@app.post("/offer/import/csv")
async def offer_import_csv(csv_file: UploadFile = File(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/offer", status_code=303)
    content = await csv_file.read()
    try:
        text = content.decode('utf-8-sig').strip()
    except UnicodeDecodeError:
        text = content.decode('gbk', errors='replace').strip()
        
    # Pass full text to sill
    success_count, errors = batch_import_offer_text(text, current_user['emp_id'])
    err_msg = ""
    if errors:
        import urllib.parse
        err_msg = "&msg=" + urllib.parse.quote(errors[0])
    return RedirectResponse(url=f"/offer?import_success={success_count}&errors={len(errors)}{err_msg}", status_code=303)

@app.get("/api/exchange/rates")
async def get_exchange_rates_api(current_user: dict = Depends(login_required)):
    """获取最新汇率（KRW 和 USD）"""
    from Sills.base import get_exchange_rates
    krw, usd = get_exchange_rates()
    return {"success": True, "krw": krw, "usd": usd}

@app.get("/api/server/env")
async def get_server_env_api():
    """获取服务器环境信息"""
    return {"success": True, "env": get_server_env()}

@app.post("/api/offer/update")
async def offer_update_api(offer_id: str = Form(...), field: str = Form(...), value: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return {"success": False, "message": "无修改权限"}
        
    allowed_fields = ['quote_id', 'inquiry_mpn', 'quoted_mpn', 'inquiry_brand', 'quoted_brand',
                      'inquiry_qty', 'actual_qty', 'quoted_qty', 'cost_price_rmb', 'offer_price_rmb',
                      'price_kwr', 'price_usd', 'vendor_id', 'date_code', 'delivery_date', 'offer_statement', 'is_transferred', 'remark']
    if field not in allowed_fields:
        return {"success": False, "message": f"非法字段: {field}"}
        
    if field in ['inquiry_qty', 'actual_qty', 'quoted_qty', 'cost_price_rmb', 'offer_price_rmb', 'price_kwr', 'price_usd']:
        try:
            val = float(value) if 'price' in field else int(value)
            success, msg = update_offer(offer_id, {field: val})
            return {"success": success, "message": msg}
        except:
            return {"success": False, "message": "必须是数字"}
            
    success, msg = update_offer(offer_id, {field: value})
    return {"success": success, "message": msg}

@app.post("/api/offer/delete")
async def offer_delete_api(offer_id: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] != '3':
        return {"success": False, "message": "仅管理员可删除"}
    success, msg = delete_offer(offer_id)
    return {"success": success, "message": msg}

@app.post("/api/offer/batch_delete")
async def offer_batch_delete_api(request: Request, current_user: dict = Depends(login_required)):
    if current_user['rule'] != '3':
        return {"success": False, "message": "仅管理员可删除"}
    data = await request.json()
    ids = data.get("ids", [])
    success, msg = batch_delete_offer(ids)
    return {"success": success, "message": msg}

@app.post("/api/offer/batch_price_increase")
async def offer_batch_price_increase_api(request: Request, current_user: dict = Depends(login_required)):
    """按比例加价：新报价RMB = 成本价 × (1 + 比例%)，同时更新KWR和USD"""
    if current_user['rule'] != '3' and current_user['rule'] != '0':
        return {"success": False, "message": "无权限执行此操作"}

    data = await request.json()
    ids = data.get("ids", [])
    ratio = data.get("ratio", 15)  # 默认15%

    if not ids:
        return {"success": False, "message": "未选择任何记录"}

    from Sills.base import get_db_connection

    updated_count = 0
    with get_db_connection() as conn:
        # 获取最新汇率
        try:
            krw_row = conn.execute("SELECT exchange_rate FROM uni_daily WHERE currency_code=2 ORDER BY record_date DESC LIMIT 1").fetchone()
            usd_row = conn.execute("SELECT exchange_rate FROM uni_daily WHERE currency_code=1 ORDER BY record_date DESC LIMIT 1").fetchone()
            krw_rate = float(krw_row[0]) if krw_row else 180.0
            usd_rate = float(usd_row[0]) if usd_row else 7.0
        except:
            krw_rate = 180.0
            usd_rate = 7.0

        # 批量更新：新报价RMB = 成本价 × (1 + ratio/100)
        for offer_id in ids:
            # 获取当前记录的成本价
            row = conn.execute("SELECT cost_price_rmb FROM uni_offer WHERE offer_id=?", (offer_id,)).fetchone()
            if row and row[0]:
                cost_price = float(row[0])
                new_offer_rmb = cost_price * (1 + ratio / 100)
                new_price_kwr = round(new_offer_rmb * krw_rate, 1)  # KWR保留1位小数
                new_price_usd = round(new_offer_rmb * usd_rate, 3)  # USD保留3位小数

                conn.execute("""
                    UPDATE uni_offer
                    SET offer_price_rmb=?, price_kwr=?, price_usd=?
                    WHERE offer_id=?
                """, (new_offer_rmb, new_price_kwr, new_price_usd, offer_id))
                updated_count += 1

        conn.commit()

    return {"success": True, "updated_count": updated_count, "message": f"成功更新 {updated_count} 条报价"}

@app.post("/api/offer/batch_send_email")
async def offer_batch_send_email_api(request: Request, current_user: dict = Depends(login_required)):
    data = await request.json()
    ids = data.get("ids", [])
    if not ids:
        return {"success": False, "message": "未选择任何记录"}

    # 1. Fetch Data
    from Sills.base import get_db_connection
    placeholders = ','.join(['?'] * len(ids))
    with get_db_connection() as conn:
        # Get KRW rate for calculation
        try:
            rate_row = conn.execute("SELECT exchange_rate FROM uni_daily WHERE currency_code=2 ORDER BY record_date DESC LIMIT 1").fetchone()
            krw_rate = float(rate_row[0]) if rate_row else 180.0
        except: krw_rate = 180.0

        query = f"""
            SELECT o.*, v.vendor_name, c.cli_name
            FROM uni_offer o
            LEFT JOIN uni_vendor v ON o.vendor_id = v.vendor_id
            LEFT JOIN uni_quote q ON o.quote_id = q.quote_id
            LEFT JOIN uni_cli c ON q.cli_id = c.cli_id
            WHERE o.offer_id IN ({placeholders})
        """
        rows = conn.execute(query, ids).fetchall()
    
    if not rows:
        return {"success": False, "message": "记录不存在"}

    # 2. Generate Excel and Body
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Batch Offers"
    # Headers exactly as requested: Model, Brand, QTY(pcs), Price(KWR), DC, L/T, Remark
    headers = ['Model', 'Brand', 'QTY(pcs)', 'Price(KWR)', 'DC', 'L/T', 'Remark']
    ws.append(headers)
    
    email_body_sections = []
    
    for row_data in rows:
        r = dict(row_data)
        # Handle KRW price if missing
        pkwr = r.get('price_kwr')
        if not pkwr:
            try: pkwr = round(float(r['offer_price_rmb'] or 0) * krw_rate, 1)
            except: pkwr = 0.0
            
        # Format for Excel
        ws.append([
            r['quoted_mpn'] or r['inquiry_mpn'], r['quoted_brand'] or r['inquiry_brand'],
            r['quoted_qty'], pkwr, r['date_code'], r['delivery_date'], r['remark']
        ])
        
        # Format for Email Body (Template requested)
        email_body_sections.append(f"""================
Model：{r['quoted_mpn'] or r['inquiry_mpn']}
Brand：{r['quoted_brand'] or r['inquiry_brand']}
Amount(pcs)：{r['quoted_qty']}
Price(KRW)：{pkwr}
DC:{r['date_code']}
LeadTime：{r['delivery_date']}
Remark: {r['remark']}
================ """ )

    full_body_for_email = "您好，这是批量导出的报价信息，请查收附件：\n\n" + "\n\n".join(email_body_sections)
    full_body_for_clipboard = "\n\n".join(email_body_sections)
    
    excel_file = io.BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)
    
    # 3. MIME
    message = MIMEMultipart()
    message['To'] = 'joy@unicornsemi.com'
    message['Subject'] = f"批量报价汇总 - {len(rows)}条记录"
    message.attach(MIMEText(full_body_for_email, 'plain'))
    
    part = MIMEBase('application', 'vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    part.set_payload(excel_file.read())
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', f'attachment; filename="batch_offers_{datetime.now().strftime("%Y%m%d%H%M%S")}.xlsx"')
    message.attach(part)
    
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
    
    # 4. Gmail Skill (Maton Gateway)
    maton_key = "AIzaSyCgZbWmrE266eSmCynikDsoddpt_ERCbvs"
    try:
        url = 'https://gateway.maton.ai/google-mail/gmail/v1/users/me/messages/send'
        payload = json.dumps({'raw': raw_message}).encode('utf-8')
        
        req = urllib.request.Request(
            url,
            data=payload,
            method='POST'
        )
        req.add_header('Authorization', f'Bearer {maton_key}')
        req.add_header('Content-Type', 'application/json')
        
        opener = urllib.request.build_opener()
        try:
            with opener.open(req, timeout=30) as response:
                resp_body = response.read().decode('utf-8')
                # Prepare base64 for frontend download
                excel_b64 = base64.b64encode(excel_file.getvalue()).decode('utf-8')
                return {
                    "success": True, 
                    "message": f"成功发送 {len(rows)} 条报价到 joy@unicornsemi.com",
                    "clipboard": full_body_for_clipboard,
                    "excel_b64": excel_b64,
                    "filename": f"batch_offers_{datetime.now().strftime('%Y%m%d%H%M%S')}.xlsx"
                }
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8')
            return {"success": False, "message": f"邮件发送失败 (HTTP {e.code}): {err_body}"}
    except Exception as e:
        return {"success": False, "message": f"邮件发送失败: {str(e)}"}

@app.post("/api/offer/export_csv")
async def offer_export_csv(request: Request, current_user: dict = Depends(login_required)):
    data = await request.json()
    ids = data.get("ids", [])
    if not ids:
        return {"success": False, "message": "未选择任何记录进行导出"}

    from Sills.base import get_db_connection, get_exchange_rates
    placeholders = ','.join(['?'] * len(ids))
    with get_db_connection() as conn:
        query = f"""
            SELECT o.*, v.vendor_name, e.emp_name, c.cli_name
            FROM uni_offer o
            LEFT JOIN uni_vendor v ON o.vendor_id = v.vendor_id
            LEFT JOIN uni_emp e ON o.emp_id = e.emp_id
            LEFT JOIN uni_quote q ON o.quote_id = q.quote_id
            LEFT JOIN uni_cli c ON q.cli_id = c.cli_id
            WHERE o.offer_id IN ({placeholders})
        """
        rows = conn.execute(query, ids).fetchall()

    # 获取汇率
    krw_rate, usd_rate = get_exchange_rates()

    # CSV 头部 - 与页面展示一致
    headers = ['日期', '报价编号', '客户名称', '需求编号', '询价型号', '报价型号', '需求品牌', '报价品牌',
               '需求数量(pcs)', '报价数量(pcs)', '成本价', '报价(RMB)', '报价(KWR)', '报价(USD)',
               '利润', '总利润', '供应商', '批号(DC)', '交期(LT)', '负责人', '已转', '备注']

    csv_lines = [','.join(headers)]

    for row_data in rows:
        r = dict(row_data)

        # 计算价格
        offer_price_rmb = float(r.get('offer_price_rmb') or 0)
        cost_price_rmb = float(r.get('cost_price_rmb') or 0)
        quoted_qty = int(r.get('quoted_qty') or 0)

        # KWR 价格
        pkwr = r.get('price_kwr')
        if not pkwr or float(pkwr) == 0:
            if krw_rate > 10:
                pkwr = round(offer_price_rmb * krw_rate, 1)
            else:
                pkwr = round(offer_price_rmb / krw_rate, 1) if krw_rate else 0

        # USD 价格 (USD汇率表示 1 RMB = ? USD，直接乘)
        pusd = r.get('price_usd')
        if not pusd or float(pusd) == 0:
            pusd = round(offer_price_rmb * usd_rate, 2) if usd_rate else 0

        # 利润计算
        profit = round(offer_price_rmb - cost_price_rmb, 3)
        total_profit = int(round(profit * quoted_qty, 0))

        # 构建CSV行
        line = [
            r.get('offer_date', ''),
            r.get('offer_id', ''),
            r.get('cli_name', ''),
            r.get('quote_id', ''),
            r.get('inquiry_mpn', ''),
            r.get('quoted_mpn', ''),
            r.get('inquiry_brand', ''),
            r.get('quoted_brand', ''),
            r.get('inquiry_qty', 0),
            r.get('quoted_qty', 0),
            cost_price_rmb,
            offer_price_rmb,
            pkwr,
            pusd,
            profit,
            total_profit,
            r.get('vendor_name', ''),
            r.get('date_code', ''),
            r.get('delivery_date', ''),
            r.get('emp_name', ''),
            r.get('is_transferred', '未转'),
            (r.get('remark') or '').replace('\n', ' ').replace(',', '，')
        ]
        csv_lines.append(','.join([str(v) for v in line]))

    csv_content = '\n'.join(csv_lines)

    # 生成剪贴板内容（报价模板格式）
    clipboard_sections = []
    for row_data in rows:
        r = dict(row_data)
        offer_price_rmb = float(r.get('offer_price_rmb') or 0)
        quoted_qty = int(r.get('quoted_qty') or 0)

        # KWR 价格
        pkwr = r.get('price_kwr')
        if not pkwr or float(pkwr) == 0:
            if krw_rate > 10:
                pkwr = round(offer_price_rmb * krw_rate, 1)
            else:
                pkwr = round(offer_price_rmb / krw_rate, 1) if krw_rate else 0

        clipboard_sections.append(f"""================
Model：{r.get('quoted_mpn') or r.get('inquiry_mpn')}
Brand：{r.get('quoted_brand') or r.get('inquiry_brand')}
Amount(pcs)：{r.get('quoted_qty')}
Price(KRW)：{pkwr}
DC：{r.get('date_code')}
LeadTime：{r.get('delivery_date')}
Remark: {r.get('remark')}
================ """)

    clipboard_content = "\n\n".join(clipboard_sections)

    return {
        "success": True,
        "csv_content": csv_content,
        "clipboard": clipboard_content,
        "filename": f"报价卡片_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
    }

@app.post("/api/offer/generate_koquote")
async def offer_generate_koquote(request: Request, current_user: dict = Depends(login_required)):
    """生成韩文Excel报价单"""
    from Sills.document_generator import generate_koquote

    data = await request.json()
    offer_ids = data.get("offer_ids", [])
    if not offer_ids:
        return {"success": False, "message": "未选择任何报价记录"}

    try:
        success, result = generate_koquote(offer_ids)

        if success:
            return {
                "success": True,
                "file_path": result.get("excel_path", ""),
                "count": result.get("count", 0),
                "cli_name": result.get("cli_name", "")
            }
        else:
            return {"success": False, "message": f"生成失败: {result}"}
    except Exception as e:
        return {"success": False, "message": f"生成异常: {str(e)}"}
    except subprocess.TimeoutExpired:
        return {"success": False, "message": "生成超时，请稍后重试"}
    except Exception as e:
        return {"success": False, "message": f"生成异常: {str(e)}"}

@app.get("/order", response_class=HTMLResponse)
async def order_page(request: Request, current_user: dict = Depends(login_required), page: int = 1, page_size: int = 20, search: str = "", cli_id: str = "", start_date: str = "", end_date: str = "", is_finished: str = "", is_transferred: str = ""):
    # 日期默认不选择，保持为空
    # is_finished 为空表示"全部状态"，不做强制设置
    results, total = get_order_list(page=page, page_size=page_size, search_kw=search, cli_id=cli_id, start_date=start_date, end_date=end_date, is_finished=is_finished, is_transferred=is_transferred)
    total_pages = (total + page_size - 1) // page_size
    from Sills.db_cli import get_cli_list
    from Sills.base import get_paginated_list
    cli_list, _ = get_cli_list(page=1, page_size=1000)
    vendor_data = get_paginated_list('uni_vendor', page=1, page_size=1000)
    vendor_list = vendor_data['items']
    return templates.TemplateResponse("order.html", {
        "request": request, "active_page": "order", "current_user": current_user,
        "items": results, "total": total, "page": page, "page_size": page_size,
        "total_pages": total_pages, "search": search, "cli_id": cli_id,
        "start_date": start_date, "end_date": end_date, "cli_list": cli_list,
        "vendor_list": vendor_list,
        "is_finished": is_finished,
        "is_transferred": request.query_params.get("is_transferred", "")
    })

@app.post("/order/add")
async def order_add_route(
    cli_id: str = Form(...), offer_id: str = Form(None), 
    order_id: str = Form(None), order_date: str = Form(None),
    inquiry_mpn: str = Form(None), inquiry_brand: str = Form(None),
    is_finished: int = Form(0), is_paid: int = Form(0), 
    paid_amount: float = Form(0.0), remark: str = Form(""),
    current_user: dict = Depends(login_required)
):
    data = {
        "cli_id": cli_id, "offer_id": offer_id, "order_id": order_id, "order_date": order_date,
        "inquiry_mpn": inquiry_mpn, "inquiry_brand": inquiry_brand,
        "is_finished": is_finished, "is_paid": is_paid, 
        "paid_amount": paid_amount, "remark": remark
    }
    ok, msg = add_order(data)
    import urllib.parse
    return RedirectResponse(url=f"/order?msg={urllib.parse.quote(msg)}&success={1 if ok else 0}", status_code=303)

@app.post("/order/import")
async def order_import_text(batch_text: str = Form(None), csv_file: UploadFile = File(None), cli_id: str = Form(...), current_user: dict = Depends(login_required)):
    if batch_text:
        text = batch_text
    elif csv_file:
        content = await csv_file.read()
        try:
            text = content.decode('utf-8-sig').strip()
        except UnicodeDecodeError:
            text = content.decode('gbk', errors='replace').strip()
    else:
        return RedirectResponse(url="/order?msg=未提供导入内容&success=0", status_code=303)
        
    success_count, errors = batch_import_order(text, cli_id)
    import urllib.parse
    err_msg = ""
    if errors: err_msg = "&msg=" + urllib.parse.quote(errors[0])
    return RedirectResponse(url=f"/order?import_success={success_count}&errors={len(errors)}{err_msg}", status_code=303)

@app.post("/api/order/update_status")
async def api_order_update_status(order_id: str = Form(...), field: str = Form(...), value: int = Form(...), current_user: dict = Depends(login_required)):
    ok, msg = update_order_status(order_id, field, value)
    return {"success": ok, "message": msg}

@app.post("/api/order/update")
async def api_order_update(order_id: str = Form(...), field: str = Form(...), value: str = Form(...), current_user: dict = Depends(login_required)):
    if field in ['paid_amount']:
        try: value = float(value)
        except: return {"success": False, "message": "必须是数字"}
    
    allowed_fields = ['order_no', 'order_date', 'cli_id', 'offer_id', 'inquiry_mpn', 'inquiry_brand', 'price_rmb', 'price_kwr', 'price_usd', 'cost_price_rmb', 'is_finished', 'is_paid', 'paid_amount', 'return_status', 'remark', 'is_transferred']
    if field not in allowed_fields:
        return {"success": False, "message": f"非法字段: {field}"}

    ok, msg = update_order(order_id, {field: value})
    return {"success": ok, "message": msg}

@app.post("/api/order/delete")
async def api_order_delete(order_id: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] != '3': return {"success": False, "message": "无权限"}
    ok, msg = delete_order(order_id)
    return {"success": ok, "message": msg}

@app.post("/api/order/batch_delete")
async def api_order_batch_delete(request: Request, current_user: dict = Depends(login_required)):
    if current_user['rule'] != '3': return {"success": False, "message": "仅管理员可删除"}
    data = await request.json()
    ids = data.get("ids", [])
    ok, msg = batch_delete_order(ids)
    return {"success": ok, "message": msg}

@app.post("/api/order/export_csv")
async def order_export_csv(request: Request, current_user: dict = Depends(login_required)):
    data = await request.json()
    ids = data.get("ids", [])
    if not ids: return {"success": False, "message": "未选择记录"}
    placeholders = ','.join(['?'] * len(ids))
    with get_db_connection() as conn:
        orders = conn.execute(f"""
            SELECT ord.*, c.cli_name,
                   off.inquiry_qty, off.quoted_qty, off.date_code, off.delivery_date,
                   v.vendor_name
            FROM uni_order ord
            LEFT JOIN uni_cli c ON ord.cli_id = c.cli_id
            LEFT JOIN uni_offer off ON ord.offer_id = off.offer_id
            LEFT JOIN uni_vendor v ON off.vendor_id = v.vendor_id
            WHERE ord.order_id IN ({placeholders})
        """, ids).fetchall()

    krw_rate, usd_rate = get_exchange_rates()

    import io, csv
    output = io.StringIO(); output.write('\ufeff')
    writer = csv.writer(output)
    # 与页面显示字段一致
    writer.writerow(['订单日期','订单编号','客户','报价编号','报价型号','品牌','报价(RMB)','报价(KWR)','报价(USD)','成本(RMB)','利润','需求数量(pcs)','报价数量(pcs)','供应商','批号(DC)','货期','退货状态','完结','付款','已付金额','已转','备注'])

    for r in orders:
        d = dict(r)
        price_rmb = float(d.get('price_rmb') or 0)
        cost_rmb = float(d.get('cost_price_rmb') or 0)
        qty = int(d.get('quoted_qty') or 0)
        profit = round(price_rmb - cost_rmb, 3)

        # KWR/USD 计算
        price_kwr = d.get('price_kwr')
        price_usd = d.get('price_usd')
        if not price_kwr:
            if krw_rate > 10: price_kwr = round(price_rmb * krw_rate, 1)
            else: price_kwr = round(price_rmb / krw_rate, 1) if krw_rate else 0
        if not price_usd:
            price_usd = round(price_rmb * usd_rate, 2) if usd_rate else 0

        writer.writerow([
            d.get('order_date', ''),
            d.get('order_no') or d.get('order_id', ''),
            d.get('cli_name', ''),
            d.get('offer_id') or '',
            d.get('inquiry_mpn') or '',
            d.get('inquiry_brand') or '',
            f"{price_rmb:.2f}",
            price_kwr,
            price_usd,
            f"{cost_rmb:.2f}",
            profit,
            d.get('inquiry_qty') or '',
            d.get('quoted_qty') or '',
            d.get('vendor_name') or '',
            d.get('date_code') or '',
            d.get('delivery_date') or '',
            d.get('return_status', '正常'),
            '已完结' if d.get('is_finished') == 1 else '未完结',
            '已付款' if d.get('is_paid') == 1 else '未付款',
            d.get('paid_amount', 0),
            d.get('is_transferred', '未转'),
            d.get('remark') or ''
        ])
    return {"success": True, "csv_content": output.getvalue()}

@app.get("/buy", response_class=HTMLResponse)
async def buy_page(request: Request, current_user: dict = Depends(login_required), page: int = 1, page_size: int = 20, search: str = "", order_id: str = "", start_date: str = "", end_date: str = "", cli_id: str = "", is_shipped: str = ""):
    # 日期默认不选择，保持为空
    # is_shipped 为空表示"全部状态"，不做强制设置
    results, total = get_buy_list(page=page, page_size=page_size, search_kw=search, order_id=order_id, start_date=start_date, end_date=end_date, cli_id=cli_id, is_shipped=is_shipped)
    total_pages = (total + page_size - 1) // page_size
    with get_db_connection() as conn:
        vendors = conn.execute("SELECT vendor_id, vendor_name, address FROM uni_vendor").fetchall()
        orders = conn.execute("SELECT order_id, order_no FROM uni_order").fetchall()
        clis = conn.execute("SELECT cli_id, cli_name FROM uni_cli").fetchall()
        vendor_addresses = {str(v['vendor_id']): (v['address'] or "") for v in vendors}
    return templates.TemplateResponse("buy.html", {
        "request": request, "active_page": "buy", "current_user": current_user,
        "items": results, "total": total, "page": page, "page_size": page_size,
        "total_pages": total_pages, "search": search, "order_id": order_id,
        "start_date": start_date, "end_date": end_date, "cli_id": cli_id,
        "vendor_list": vendors, "order_list": orders, "cli_list": clis,
        "is_shipped": is_shipped, "vendor_addresses": vendor_addresses
    })

@app.post("/buy/import")
async def buy_import_text(batch_text: str = Form(None), csv_file: UploadFile = File(None), current_user: dict = Depends(login_required)):
    if batch_text:
        text = batch_text
    elif csv_file:
        content = await csv_file.read()
        try:
            text = content.decode('utf-8-sig').strip()
        except UnicodeDecodeError:
            text = content.decode('gbk', errors='replace').strip()
    else:
        return RedirectResponse(url="/buy?import_success=0&errors=1&msg=未提供导入内容", status_code=303)
        
    success_count, errors = batch_import_buy(text)
    import urllib.parse
    err_msg = ""
    if errors: err_msg = "&msg=" + urllib.parse.quote(errors[0])
    return RedirectResponse(url=f"/buy?import_success={success_count}&errors={len(errors)}{err_msg}", status_code=303)

@app.post("/buy/add")
async def buy_add_route(
    order_id: str = Form(...), vendor_id: str = Form(...),
    buy_mpn: str = Form(...), buy_brand: str = Form(""),
    buy_price_rmb: float = Form(...), buy_qty: int = Form(...),
    sales_price_rmb: float = Form(0.0), remark: str = Form(""),
    current_user: dict = Depends(login_required)
):
    data = {
        "order_id": order_id, "vendor_id": vendor_id,
        "buy_mpn": buy_mpn, "buy_brand": buy_brand,
        "buy_price_rmb": buy_price_rmb, "buy_qty": buy_qty,
        "sales_price_rmb": sales_price_rmb, "remark": remark
    }
    ok, msg = add_buy(data)
    import urllib.parse
    msg_param = urllib.parse.quote(msg)
    success = 1 if ok else 0
    return RedirectResponse(url=f"/buy?msg={msg_param}&success={success}", status_code=303)

@app.post("/api/buy/update_node")
async def api_buy_update_node(buy_id: str = Form(...), field: str = Form(...), value: int = Form(...), current_user: dict = Depends(login_required)):
    from Sills.db_buy import update_buy_node
    ok, msg = update_buy_node(buy_id, field, value)
    return {"success": ok, "message": msg}

@app.post("/api/buy/update")
async def api_buy_update(buy_id: str = Form(...), field: str = Form(...), value: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] not in ['3', '0']:
        return {"success": False, "message": "无权限"}
    allowed_fields = ['order_id', 'vendor_id', 'buy_mpn', 'buy_brand', 'buy_price_rmb', 'buy_qty', 'sales_price_rmb', 'remark', 'price_kwr', 'price_usd']
    if field not in allowed_fields:
        return {"success": False, "message": f"非法字段: {field}"}
    from Sills.db_buy import update_buy
    success, msg = update_buy(buy_id, {field: value})
    return {"success": success, "message": msg}

@app.post("/api/buy/delete")
async def api_buy_delete(buy_id: str = Form(...), current_user: dict = Depends(login_required)):
    if current_user['rule'] != '3': return {"success": False, "message": "仅管理员可删除"}
    from Sills.db_buy import delete_buy
    ok, msg = delete_buy(buy_id)
    return {"success": ok, "message": msg}

@app.post("/api/buy/batch_delete")
async def api_buy_batch_delete(request: Request, current_user: dict = Depends(login_required)):
    if current_user['rule'] != '3': return {"success": False, "message": "仅管理员可删除"}
    data = await request.json()
    ids = data.get("ids", [])
    ok, msg = batch_delete_buy(ids)
    return {"success": ok, "message": msg}

@app.post("/api/buy/export_csv")
async def buy_export_csv(request: Request, current_user: dict = Depends(login_required)):
    data = await request.json()
    ids = data.get("ids", [])
    if not ids: return {"success": False, "message": "未选择记录"}
    placeholders = ','.join(['?'] * len(ids))
    with get_db_connection() as conn:
        buys = conn.execute(f"""
            SELECT b.*, v.vendor_name, v.address as vendor_address, ord.order_no,
                   c.cli_id, c.cli_name, off.date_code, off.delivery_date
            FROM uni_buy b
            LEFT JOIN uni_vendor v ON b.vendor_id = v.vendor_id
            LEFT JOIN uni_order ord ON b.order_id = ord.order_id
            LEFT JOIN uni_cli c ON ord.cli_id = c.cli_id
            LEFT JOIN uni_offer off ON ord.offer_id = off.offer_id
            WHERE b.buy_id IN ({placeholders})
        """, ids).fetchall()

    krw_rate, usd_rate = get_exchange_rates()

    import io, csv
    output = io.StringIO(); output.write('\ufeff')
    writer = csv.writer(output)
    # 与页面显示字段一致
    writer.writerow(['日期','采购编号','对应销售单','客户ID','客户名称','供应商','供应商地址','型号','品牌','批号(DC)','货期','采购单价(RMB)','销售报价(RMB)','采购单价(KWR)','采购单价(USD)','数量','总额(RMB)','货源确认','下单确认','入库确认','发货确认','备注'])

    for r in buys:
        d = dict(r)
        buy_price = float(d.get('buy_price_rmb') or 0)

        # KWR/USD 计算
        price_kwr = d.get('price_kwr')
        price_usd = d.get('price_usd')
        if not price_kwr or float(price_kwr or 0) == 0:
            if krw_rate > 10: price_kwr = round(buy_price * krw_rate, 1)
            else: price_kwr = round(buy_price / krw_rate, 1) if krw_rate else 0
        if not price_usd or float(price_usd or 0) == 0:
            price_usd = round(buy_price * usd_rate, 2) if usd_rate else 0

        writer.writerow([
            d.get('buy_date', ''),
            d.get('buy_id', ''),
            d.get('order_no') or '',
            d.get('cli_id') or '',
            d.get('cli_name') or '',
            d.get('vendor_name') or '',
            d.get('vendor_address') or '',
            d.get('buy_mpn') or '',
            d.get('buy_brand') or '',
            d.get('date_code') or '',
            d.get('delivery_date') or '',
            f"{buy_price:.2f}",
            f"{float(d.get('sales_price_rmb') or 0):.2f}",
            price_kwr,
            price_usd,
            d.get('buy_qty') or 0,
            d.get('total_amount') or 0,
            '是' if d.get('is_source_confirmed') == 1 else '否',
            '是' if d.get('is_ordered') == 1 else '否',
            '是' if d.get('is_instock') == 1 else '否',
            '是' if d.get('is_shipped') == 1 else '否',
            d.get('remark') or ''
        ])
    return {"success": True, "csv_content": output.getvalue()}
# --- New Workflow API endpoints ---

@app.post("/api/quote/batch_to_offer")
async def api_quote_batch_to_offer(data: dict, current_user: dict = Depends(login_required)):
    ids = data.get('ids', [])
    if not ids: return {"success": False, "message": "未选中记录"}
    try:
        ok, msg = batch_convert_from_quote(ids, current_user['emp_id'])
        return {"success": ok, "message": msg}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/offer/batch_to_order")
async def api_offer_batch_to_order(data: dict, current_user: dict = Depends(login_required)):
    ids = data.get('ids', [])
    cli_id = data.get('cli_id')
    if not ids: return {"success": False, "message": "未选中记录"}
    try:
        ok, msg = batch_convert_from_offer(ids, cli_id)
        return {"success": ok, "message": msg}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/order/batch_to_buy")
async def api_order_batch_to_buy(data: dict, current_user: dict = Depends(login_required)):
    ids = data.get('ids', [])
    if not ids: return {"success": False, "message": "未选中记录"}
    try:
        ok, msg = batch_convert_from_order(ids)
        return {"success": ok, "message": msg}
    except Exception as e:
        return {"success": False, "message": str(e)}

@app.post("/api/order/generate_pi")
async def api_order_generate_pi(request: Request, current_user: dict = Depends(login_required)):
    """生成PI文件"""
    from Sills.document_generator import generate_pi

    data = await request.json()
    order_ids = data.get("order_ids", [])
    if not order_ids:
        return {"success": False, "message": "未选择任何订单"}

    try:
        success, result = generate_pi(order_ids)

        if success:
            return {
                "success": True,
                "excel_path": result.get("excel_path", ""),
                "pdf_path": result.get("pdf_path", ""),
                "count": result.get("count", 0),
                "cli_name": result.get("cli_name", ""),
                "invoice_no": result.get("invoice_no", "")
            }
        else:
            return {"success": False, "message": f"生成失败: {result}"}
    except Exception as e:
        return {"success": False, "message": f"生成异常: {str(e)}"}


@app.post("/api/order/generate_pi_us")
async def api_order_generate_pi_us(request: Request, current_user: dict = Depends(login_required)):
    """生成PI-US文件（美元版）"""
    from Sills.document_generator import generate_pi_us

    data = await request.json()
    order_ids = data.get("order_ids", [])
    if not order_ids:
        return {"success": False, "message": "未选择任何订单"}

    try:
        success, result = generate_pi_us(order_ids)

        if success:
            return {
                "success": True,
                "excel_path": result.get("excel_path", ""),
                "count": result.get("count", 0),
                "cli_name": result.get("cli_name", ""),
                "invoice_no": result.get("invoice_no", "")
            }
        else:
            return {"success": False, "message": f"生成失败: {result}"}
    except Exception as e:
        return {"success": False, "message": f"生成异常: {str(e)}"}


@app.post("/api/order/generate_ci_kr")
async def api_order_generate_ci_kr(request: Request, current_user: dict = Depends(login_required)):
    """生成CI-KR文件"""
    from Sills.ci_generator import generate_ci_kr

    data = await request.json()
    order_ids = data.get("order_ids", [])
    if not order_ids:
        return {"success": False, "message": "未选择任何订单"}

    try:
        success, result = generate_ci_kr(order_ids)

        if success:
            return {
                "success": True,
                "excel_path": result.get("excel_path", ""),
                "pdf_path": result.get("pdf_path", ""),
                "count": result.get("count", 0),
                "cli_name": result.get("cli_name", ""),
                "invoice_no": result.get("invoice_no", "")
            }
        else:
            return {"success": False, "message": f"生成失败: {result}"}
    except Exception as e:
        return {"success": False, "message": f"生成异常: {str(e)}"}


@app.post("/api/order/generate_ci_us")
async def api_order_generate_ci_us(request: Request, current_user: dict = Depends(login_required)):
    """生成CI-US文件（美元版）"""
    from Sills.document_generator import generate_ci_us

    data = await request.json()
    order_ids = data.get("order_ids", [])
    if not order_ids:
        return {"success": False, "message": "未选择任何订单"}

    try:
        success, result = generate_ci_us(order_ids)

        if success:
            return {
                "success": True,
                "excel_path": result.get("excel_path", ""),
                "pdf_path": result.get("pdf_path", ""),
                "count": result.get("count", 0),
                "cli_name": result.get("cli_name", ""),
                "invoice_no": result.get("invoice_no", "")
            }
        else:
            return {"success": False, "message": f"生成失败: {result}"}
    except Exception as e:
        return {"success": False, "message": f"生成异常: {str(e)}"}

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, current_user: dict = Depends(login_required)):
    if current_user['rule'] != '3':
        return RedirectResponse(url="/", status_code=303)

    # Get backup path info - 根据系统选择路径
    is_windows = platform.system() == "Windows"
    backup_root = r"E:\WorkPlace\1_AIemployee\备份目录" if is_windows else "/home/kim/workspace/DbBackup"

    return templates.TemplateResponse("settings.html", {
        "request": request,
        "active_page": "settings",
        "current_user": current_user,
        "backup_path": backup_root
    })

@app.post("/api/backup")
async def api_backup(current_user: dict = Depends(login_required)):
    if current_user['rule'] != '3':
        return {"success": False, "message": "仅管理员可执行备份"}

    try:
        count, backup_dir = do_backup()
        return {"success": True, "message": f"备份成功！已备份 {count} 个数据库文件和 static 目录到 {backup_dir}"}
    except Exception as e:
        return {"success": False, "message": f"备份失败: {str(e)}"}

@app.get("/api/backup/list")
async def api_backup_list(current_user: dict = Depends(login_required)):
    """获取备份目录列表"""
    if current_user['rule'] != '3':
        return {"success": False, "message": "仅管理员可执行"}

    try:
        backup_root = get_backup_root()
        if not os.path.exists(backup_root):
            return {"success": True, "backups": []}

        backups = []
        for item in os.listdir(backup_root):
            try:
                item_path = os.path.join(backup_root, item)
                if os.path.isdir(item_path) and item.startswith("backup_"):
                    # 获取目录修改时间
                    mtime = os.path.getmtime(item_path)
                    mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                    # 获取目录大小
                    total_size = 0
                    for f in os.listdir(item_path):
                        fpath = os.path.join(item_path, f)
                        if os.path.isfile(fpath):
                            total_size += os.path.getsize(fpath)
                    backups.append({
                        "name": item,
                        "path": item_path,
                        "mtime": mtime_str,
                        "size": f"{total_size / 1024:.1f} KB"
                    })
            except Exception as e:
                print(f"处理备份目录 {item} 时出错: {str(e)}")
                continue

        # 按修改时间降序排序
        backups.sort(key=lambda x: x['mtime'], reverse=True)
        return {"success": True, "backups": backups}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "message": f"获取备份列表失败: {str(e)}"}

@app.post("/api/backup/restore")
async def api_backup_restore(backup_path: str = Form(...), current_user: dict = Depends(login_required)):
    """从备份目录恢复数据库"""
    if current_user['rule'] != '3':
        return {"success": False, "message": "仅管理员可执行恢复"}

    try:
        if not os.path.exists(backup_path):
            return {"success": False, "message": f"备份目录不存在: {backup_path}"}

        project_root = os.path.dirname(os.path.abspath(__file__))
        restored_count = 0

        # 关闭所有数据库连接
        from Sills.base import clear_cache, close_all_connections
        close_all_connections()
        clear_cache()

        # 恢复所有 .db 文件
        for db_file in os.listdir(backup_path):
            if db_file.endswith(".db"):
                src = os.path.join(backup_path, db_file)
                dst = os.path.join(project_root, db_file)
                # 删除目标文件（包括 WAL 和 SHM 文件）
                if os.path.exists(dst):
                    os.remove(dst)
                wal_file = dst + "-wal"
                shm_file = dst + "-shm"
                if os.path.exists(wal_file):
                    os.remove(wal_file)
                if os.path.exists(shm_file):
                    os.remove(shm_file)
                # 复制备份文件
                shutil.copy2(src, dst)
                restored_count += 1

        if restored_count == 0:
            return {"success": False, "message": "备份目录中没有找到数据库文件"}

        # 再次清除缓存
        clear_cache()

        return {"success": True, "message": f"恢复成功！已恢复 {restored_count} 个数据库文件（请刷新页面）"}
    except Exception as e:
        return {"success": False, "message": f"恢复失败: {str(e)}"}


@app.post("/api/backup/delete")
async def api_backup_delete(backup_path: str = Form(...), current_user: dict = Depends(login_required)):
    """删除备份目录"""
    if current_user['rule'] != '3':
        return {"success": False, "message": "仅管理员可执行删除"}

    try:
        # 安全检查：确保路径在备份目录内
        backup_root = get_backup_root()
        if not os.path.exists(backup_path):
            return {"success": False, "message": "备份目录不存在"}

        # 确保是备份目录
        if not backup_path.startswith(backup_root):
            return {"success": False, "message": "非法路径"}

        if not os.path.basename(backup_path).startswith("backup_"):
            return {"success": False, "message": "不是有效的备份目录"}

        # 删除目录
        shutil.rmtree(backup_path)
        return {"success": True, "message": f"已删除备份: {os.path.basename(backup_path)}"}
    except Exception as e:
        return {"success": False, "message": f"删除失败: {str(e)}"}


# ==================== SmartMail 邮件模块路由 ====================

@app.get("/mail", response_class=HTMLResponse)
async def mail_page(request: Request, current_user: dict = Depends(login_required)):
    """邮件中心页面"""
    from Sills.db_mail import get_mail_config
    mail_config = get_mail_config()
    current_email = mail_config.get('username', '') if mail_config else ''
    return templates.TemplateResponse("mail.html", {
        "request": request,
        "active_page": "mail",
        "current_user": current_user,
        "current_email": current_email
    })


@app.get("/api/mail/list")
async def api_mail_list(
    folder: str = "inbox",
    page: int = 1,
    page_size: int = 20,
    search: str = None,
    current_user: dict = Depends(login_required)
):
    """获取邮件列表（用户隔离）"""
    # 限制每页数量在1-100之间
    page_size = max(1, min(100, page_size))
    is_sent = 1 if folder == "sent" else 0
    # 获取当前邮件账户ID
    config = get_mail_config()
    account_id = config.get('id') if config else None
    result = get_mail_list(page=page, limit=page_size, is_sent=is_sent, search=search, account_id=account_id)
    return result


@app.post("/api/mail/send")
async def api_mail_send(
    request: Request,
    current_user: dict = Depends(login_required)
):
    """发送邮件"""
    from Sills.db_mail import get_signature

    data = await request.json()
    to = data.get('to', '')
    subject = data.get('subject', '')
    body = data.get('body', '')
    html_body = data.get('html_body', '')
    cc = data.get('cc', '')

    if not to or not subject:
        return {"success": False, "message": "收件人和主题不能为空"}

    # 追加签名（签名现在是HTML格式）
    signature = get_signature()
    if signature:
        # 纯文本body：从HTML中提取纯文本（简单处理）
        import re
        plain_signature = re.sub(r'<[^>]+>', '', signature).replace('&nbsp;', ' ')
        body = body + "\n\n" + plain_signature if body else plain_signature
        # HTML body：直接追加HTML签名（空字符串也会进入else分支）
        if html_body and html_body.strip():
            html_body = html_body + "<br><br>" + signature
        else:
            html_body = signature

    result = send_email_now(to=to, subject=subject, body=body, html_body=html_body, cc=cc)

    if result["success"]:
        return {"success": True, "message": "邮件发送成功", "message_id": result.get("message_id")}
    else:
        return {"success": False, "message": f"发送失败: {result.get('error', '未知错误')}"}


@app.post("/api/mail/send-with-attachments")
async def api_mail_send_with_attachments(
    request: Request,
    current_user: dict = Depends(login_required)
):
    """发送带附件的邮件"""
    from fastapi import UploadFile, File, Form
    from Sills.db_mail import get_signature
    import tempfile
    import os

    form = await request.form()
    to = form.get('to', '')
    subject = form.get('subject', '')
    body = form.get('body', '')
    html_body = form.get('html_body', '')
    cc = form.get('cc', '')

    if not to or not subject:
        return {"success": False, "message": "收件人和主题不能为空"}

    # 追加签名（签名现在是HTML格式）
    signature = get_signature()
    if signature:
        # 纯文本body：从HTML中提取纯文本（简单处理）
        import re
        plain_signature = re.sub(r'<[^>]+>', '', signature).replace('&nbsp;', ' ')
        body = body + "\n\n" + plain_signature if body else plain_signature
        # HTML body：直接追加HTML签名（空字符串也会进入else分支）
        if html_body and html_body.strip():
            html_body = html_body + "<br><br>" + signature
        else:
            html_body = signature

    # 获取所有附件（使用getlist获取多个同名字段）
    attachments = []
    attachment_files = form.getlist('attachments')
    for value in attachment_files:
        if hasattr(value, 'filename') and value.filename:
            # 保存到临时文件
            content = await value.read()
            if content:
                temp_dir = tempfile.gettempdir()
                temp_path = os.path.join(temp_dir, value.filename)
                with open(temp_path, 'wb') as f:
                    f.write(content)
                attachments.append({
                    'path': temp_path,
                    'filename': value.filename,
                    'content_type': value.content_type or 'application/octet-stream'
                })

    from Sills.mail_service import send_email_with_attachments
    result = send_email_with_attachments(
        to=to, subject=subject, body=body,
        html_body=html_body, cc=cc, attachments=attachments
    )

    # 清理临时文件
    for att in attachments:
        try:
            os.remove(att['path'])
        except:
            pass

    if result["success"]:
        return {"success": True, "message": "邮件发送成功", "message_id": result.get("message_id")}
    else:
        return {"success": False, "message": f"发送失败: {result.get('error', '未知错误')}"}


@app.post("/api/mail/sync")
async def api_mail_sync(current_user: dict = Depends(login_required)):
    """同步邮件（后台异步）"""
    if is_sync_locked():
        return {"success": False, "message": "同步任务正在进行中，请稍后"}

    result = sync_inbox_async()
    return {"success": True, "message": "同步任务已启动"}


@app.post("/api/mail/sync-new")
async def api_mail_sync_new(current_user: dict = Depends(login_required)):
    """增量同步：只获取新邮件"""
    from Sills.mail_service import sync_new_emails_async
    if is_sync_locked():
        return {"success": False, "message": "同步任务正在进行中，请稍后"}

    result = sync_new_emails_async()
    return {"success": True, "message": "增量同步任务已启动"}


@app.get("/api/mail/sync/status")
async def api_mail_sync_status(current_user: dict = Depends(login_required)):
    """获取同步状态和进度"""
    progress = get_sync_progress()
    return {
        "success": True,
        **progress
    }


@app.get("/api/mail/config")
async def api_mail_config_get(current_user: dict = Depends(login_required)):
    """获取邮件配置"""
    config = get_mail_config()
    if config:
        # 隐藏密码
        config["password"] = "******" if config.get("password") else ""
    return {
        "success": True,
        "config": config
    }


@app.post("/api/mail/config")
async def api_mail_config_update(
    request: Request,
    current_user: dict = Depends(login_required)
):
    """更新邮件配置（含连接验证）"""
    from pydantic import BaseModel
    from Sills.mail_service import IMAPClient

    class MailConfigRequest(BaseModel):
        imap_server: str = ""
        imap_port: int = 993
        smtp_server: str = ""
        smtp_port: int = 587
        username: str = ""
        password: str = ""
        use_tls: int = 1
        sync_interval: int = 5

    try:
        data = await request.json()
        config_data = MailConfigRequest(**data)
    except Exception as e:
        return {"success": False, "message": f"请求数据格式错误: {str(e)}"}

    # 验证必填字段
    if not config_data.imap_server or not config_data.smtp_server or not config_data.username:
        return {"success": False, "message": "服务器地址和用户名不能为空"}

    # 验证IMAP连接（如果提供了密码）
    if config_data.password and config_data.password != "******":
        test_config = {
            'imap_server': config_data.imap_server,
            'imap_port': config_data.imap_port,
            'username': config_data.username,
            'password': config_data.password,
            'use_tls': config_data.use_tls
        }
        try:
            imap_client = IMAPClient(test_config)
            imap_client.connect()
            imap_client.disconnect()
        except Exception as e:
            return {"success": False, "message": f"IMAP连接验证失败: {str(e)}"}

    config = {
        "imap_server": config_data.imap_server,
        "imap_port": config_data.imap_port,
        "smtp_server": config_data.smtp_server,
        "smtp_port": config_data.smtp_port,
        "username": config_data.username,
        "use_tls": config_data.use_tls,
        "sync_interval": config_data.sync_interval
    }

    # 只有提供了新密码才更新
    if config_data.password and config_data.password != "******":
        config["password"] = config_data.password

    try:
        result = update_mail_config(config)
        if result:
            return {"success": True, "message": "设置保存成功"}
        else:
            return {"success": False, "message": "保存失败"}
    except ValueError as e:
        # 加密密钥未配置
        return {"success": False, "message": f"系统配置错误: {str(e)}"}
    except Exception as e:
        return {"success": False, "message": f"保存失败: {str(e)}"}


@app.get("/api/mail/accounts")
async def api_mail_accounts_list(current_user: dict = Depends(login_required)):
    """获取所有邮件账户列表"""
    accounts = get_all_mail_accounts()
    return {
        "success": True,
        "accounts": accounts
    }


@app.get("/api/mail/account/current")
async def api_mail_account_current(current_user: dict = Depends(login_required)):
    """获取当前邮件账户配置"""
    config = get_mail_config()
    if config:
        # 隐藏密码
        config['password'] = '******' if config.get('password') else ''
    return {
        "success": True,
        "config": config
    }


@app.get("/api/mail/account/{account_id}")
async def api_mail_account_get(account_id: int, current_user: dict = Depends(login_required)):
    """获取指定邮件账户配置"""
    config = get_mail_account_by_id(account_id)
    if not config:
        return {"success": False, "message": "账户不存在"}

    # 隐藏密码
    config['password'] = '******' if config.get('password') else ''
    return {
        "success": True,
        "config": config
    }


@app.get("/api/mail/sync-interval")
async def api_mail_sync_interval_get(current_user: dict = Depends(login_required)):
    """获取同步间隔设置"""
    interval = get_sync_interval()
    return {
        "success": True,
        "interval": interval
    }


@app.post("/api/mail/sync-interval")
async def api_mail_sync_interval_set(
    request: Request,
    current_user: dict = Depends(login_required)
):
    """设置同步间隔"""
    try:
        data = await request.json()
        interval = data.get('interval', 30)
        if not isinstance(interval, int) or interval < 1:
            return {"success": False, "message": "同步间隔必须为正整数"}

        set_sync_interval(interval)
        return {"success": True, "message": f"同步间隔已设置为 {interval} 分钟"}
    except Exception as e:
        return {"success": False, "message": f"设置失败: {str(e)}"}


@app.get("/api/mail/sync-days")
async def api_mail_sync_days_get(current_user: dict = Depends(login_required)):
    """获取同步时间范围设置"""
    from Sills.db_mail import get_sync_days
    days = get_sync_days()
    return {
        "success": True,
        "days": days
    }


@app.post("/api/mail/sync-days")
async def api_mail_sync_days_set(
    request: Request,
    current_user: dict = Depends(login_required)
):
    """设置同步时间范围"""
    from Sills.db_mail import set_sync_days
    try:
        data = await request.json()
        days = data.get('days', 90)
        if not isinstance(days, int) or days < 1 or days > 365:
            return {"success": False, "message": "同步时间范围必须在1-365天之间"}

        set_sync_days(days)
        return {"success": True, "message": f"同步时间范围已设置为 {days} 天"}
    except Exception as e:
        return {"success": False, "message": f"设置失败: {str(e)}"}


@app.get("/api/mail/undo-send-seconds")
async def api_mail_undo_send_seconds_get(current_user: dict = Depends(login_required)):
    """获取发送撤销时间设置"""
    from Sills.db_mail import get_undo_send_seconds
    seconds = get_undo_send_seconds()
    return {
        "success": True,
        "seconds": seconds
    }


@app.post("/api/mail/undo-send-seconds")
async def api_mail_undo_send_seconds_set(
    request: Request,
    current_user: dict = Depends(login_required)
):
    """设置发送撤销时间"""
    from Sills.db_mail import set_undo_send_seconds
    try:
        data = await request.json()
        seconds = data.get('seconds', 5)
        if not isinstance(seconds, int) or seconds < 0 or seconds > 30:
            return {"success": False, "message": "撤销时间必须在0-30秒之间"}

        set_undo_send_seconds(seconds)
        return {"success": True, "message": f"撤销时间已设置为 {seconds} 秒"}
    except Exception as e:
        return {"success": False, "message": f"设置失败: {str(e)}"}


@app.get("/api/mail/signature")
async def api_mail_signature_get(current_user: dict = Depends(login_required)):
    """获取邮件签名"""
    from Sills.db_mail import get_signature
    signature = get_signature()
    return {
        "success": True,
        "signature": signature
    }


@app.post("/api/mail/signature")
async def api_mail_signature_set(
    request: Request,
    current_user: dict = Depends(login_required)
):
    """设置邮件签名"""
    from Sills.db_mail import set_signature
    try:
        data = await request.json()
        signature = data.get('signature', '')
        set_signature(signature)
        return {"success": True, "message": "签名设置成功"}
    except Exception as e:
        return {"success": False, "message": f"设置失败: {str(e)}"}


@app.post("/api/mail/account/add")
async def api_mail_account_add(
    request: Request,
    current_user: dict = Depends(login_required)
):
    """添加新邮件账户（含连接验证）"""
    from Sills.mail_service import IMAPClient

    try:
        data = await request.json()

        # 验证必填字段
        if not data.get('imap_server') or not data.get('smtp_server') or not data.get('username'):
            return {"success": False, "message": "服务器地址和用户名不能为空"}

        # 验证IMAP连接（如果提供了密码）
        if data.get('password') and data['password'] != "******":
            test_config = {
                'imap_server': data.get('imap_server'),
                'imap_port': data.get('imap_port', 993),
                'username': data.get('username'),
                'password': data['password'],
                'use_tls': data.get('use_tls', 1)
            }
            try:
                imap_client = IMAPClient(test_config)
                imap_client.connect()
                imap_client.disconnect()
            except Exception as e:
                return {"success": False, "message": f"IMAP连接验证失败: {str(e)}"}

        account_id = add_mail_account(data)
        return {
            "success": True,
            "message": "账户添加成功",
            "account_id": account_id
        }

    except ValueError as e:
        return {"success": False, "message": f"系统配置错误: {str(e)}"}
    except Exception as e:
        return {"success": False, "message": f"添加失败: {str(e)}"}


@app.post("/api/mail/account/update")
async def api_mail_account_update(
    request: Request,
    current_user: dict = Depends(login_required)
):
    """更新邮件账户（含连接验证）"""
    from Sills.mail_service import IMAPClient

    try:
        data = await request.json()
        account_id = data.get('id')

        if not account_id:
            return {"success": False, "message": "账户ID不能为空"}

        # 验证必填字段
        if not data.get('imap_server') or not data.get('smtp_server') or not data.get('username'):
            return {"success": False, "message": "服务器地址和用户名不能为空"}

        # 验证IMAP连接（如果提供了新密码）
        if data.get('password') and data['password'] != "******":
            test_config = {
                'imap_server': data.get('imap_server'),
                'imap_port': data.get('imap_port', 993),
                'username': data.get('username'),
                'password': data['password'],
                'use_tls': data.get('use_tls', 1)
            }
            try:
                imap_client = IMAPClient(test_config)
                imap_client.connect()
                imap_client.disconnect()
            except Exception as e:
                return {"success": False, "message": f"IMAP连接验证失败: {str(e)}"}

        result = update_mail_account(account_id, data)
        if result:
            return {"success": True, "message": "账户更新成功"}
        else:
            return {"success": False, "message": "更新失败"}

    except ValueError as e:
        return {"success": False, "message": f"系统配置错误: {str(e)}"}
    except Exception as e:
        return {"success": False, "message": f"更新失败: {str(e)}"}


@app.post("/api/mail/account/switch")
async def api_mail_account_switch(
    request: Request,
    current_user: dict = Depends(login_required)
):
    """切换当前邮件账户"""
    try:
        data = await request.json()
        account_id = data.get('account_id')

        if not account_id:
            return {"success": False, "message": "账户ID不能为空"}

        result = switch_current_account(account_id)
        if result:
            return {"success": True, "message": "已切换到新账户"}
        else:
            return {"success": False, "message": "切换失败，账户不存在"}

    except Exception as e:
        return {"success": False, "message": f"切换失败: {str(e)}"}


@app.delete("/api/mail/account/{account_id}")
async def api_mail_account_delete(
    account_id: int,
    current_user: dict = Depends(login_required)
):
    """删除邮件账户"""
    try:
        result = delete_mail_account(account_id)
        if result.get('success'):
            return {"success": True, "message": result.get('message', '删除成功')}
        else:
            return {"success": False, "message": result.get('message', '删除失败')}
    except Exception as e:
        return {"success": False, "message": f"删除失败: {str(e)}"}


# ==================== 邮件文件夹 API (必须在 /api/mail/{mail_id} 之前) ====================

@app.get("/api/mail/folders")
async def api_get_folders(current_user: dict = Depends(login_required)):
    """获取文件夹列表"""
    account = get_mail_config()
    account_id = account.get('id') if account else None
    folders = get_folders(account_id)
    # 为每个文件夹添加邮件数量
    for folder in folders:
        folder['mail_count'] = get_mail_count_by_folder(folder['id'], account_id)
    return {"success": True, "folders": folders}


@app.post("/api/mail/folder/add")
async def api_add_folder(request: Request, current_user: dict = Depends(login_required)):
    """添加文件夹"""
    data = await request.json()
    folder_name = data.get('folder_name', '').strip()
    if not folder_name:
        return {"success": False, "message": "文件夹名称不能为空"}

    account = get_mail_config()
    account_id = account.get('id') if account else None

    folder_id = add_folder({
        'folder_name': folder_name,
        'folder_icon': data.get('folder_icon', 'folder'),
        'sort_order': data.get('sort_order', 0),
        'account_id': account_id
    })
    return {"success": True, "folder_id": folder_id}


@app.post("/api/mail/folder/update")
async def api_update_folder(request: Request, current_user: dict = Depends(login_required)):
    """更新文件夹"""
    data = await request.json()
    folder_id = data.get('folder_id')
    if not folder_id:
        return {"success": False, "message": "缺少文件夹ID"}

    success = update_folder(folder_id, {
        'folder_name': data.get('folder_name'),
        'folder_icon': data.get('folder_icon'),
        'sort_order': data.get('sort_order', 0)
    })
    return {"success": success}


@app.post("/api/mail/folder/delete")
async def api_delete_folder(request: Request, current_user: dict = Depends(login_required)):
    """删除文件夹"""
    data = await request.json()
    folder_id = data.get('folder_id')
    if not folder_id:
        return {"success": False, "message": "缺少文件夹ID"}

    success = delete_folder(folder_id)
    return {"success": success}


# ==================== 邮件过滤规则 API ====================

@app.get("/api/mail/filter-rules")
async def api_get_filter_rules(folder_id: int = None, current_user: dict = Depends(login_required)):
    """获取过滤规则列表"""
    rules = get_filter_rules(folder_id)
    return {"success": True, "rules": rules}


@app.post("/api/mail/filter-rule/add")
async def api_add_filter_rule(request: Request, current_user: dict = Depends(login_required)):
    """添加过滤规则"""
    data = await request.json()
    folder_id = data.get('folder_id')
    keyword = data.get('keyword', '').strip()

    if not folder_id or not keyword:
        return {"success": False, "message": "文件夹和关键词不能为空"}

    rule_id = add_filter_rule({
        'folder_id': folder_id,
        'keyword': keyword,
        'priority': data.get('priority', 0),
        'is_enabled': data.get('is_enabled', 1)
    })
    return {"success": True, "rule_id": rule_id}


@app.post("/api/mail/filter-rule/update")
async def api_update_filter_rule(request: Request, current_user: dict = Depends(login_required)):
    """更新过滤规则"""
    data = await request.json()
    rule_id = data.get('rule_id')
    if not rule_id:
        return {"success": False, "message": "缺少规则ID"}

    success = update_filter_rule(rule_id, {
        'keyword': data.get('keyword'),
        'priority': data.get('priority', 0),
        'is_enabled': data.get('is_enabled', 1)
    })
    return {"success": success}


@app.post("/api/mail/filter-rule/delete")
async def api_delete_filter_rule(request: Request, current_user: dict = Depends(login_required)):
    """删除过滤规则"""
    data = await request.json()
    rule_id = data.get('rule_id')
    if not rule_id:
        return {"success": False, "message": "缺少规则ID"}

    success = delete_filter_rule(rule_id)
    return {"success": success}


# ==================== 自动分类 API ====================

@app.post("/api/mail/auto-classify")
async def api_auto_classify(current_user: dict = Depends(login_required)):
    """自动分类邮件"""
    account = get_mail_config()
    account_id = account.get('id') if account else None

    result = auto_classify_emails(account_id)
    return {
        "success": True,
        "classified_count": result['classified_count'],
        "rule_count": result['rule_count']
    }


@app.get("/api/mail/folder/{folder_id}")
async def api_get_mails_by_folder(
    folder_id: int,
    page: int = 1,
    page_size: int = 20,
    search: str = None,
    current_user: dict = Depends(login_required)
):
    """获取指定文件夹的邮件列表"""
    account = get_mail_config()
    account_id = account.get('id') if account else None

    result = get_mails_by_folder(folder_id, page, page_size, search, account_id)
    return result


@app.get("/api/mail/{mail_id}")
async def api_mail_detail(mail_id: int, current_user: dict = Depends(login_required)):
    """获取邮件详情"""
    email = get_mail_by_id(mail_id)
    if not email:
        raise HTTPException(status_code=404, detail="邮件不存在")

    # 获取关联信息
    relations = get_mail_relations(mail_id)

    return {
        "success": True,
        "email": email,
        "relations": relations
    }


@app.post("/api/mail/{mail_id}/relate")
async def api_mail_relate(
    mail_id: int,
    entity_type: str = Form(...),
    entity_id: str = Form(...),
    current_user: dict = Depends(login_required)
):
    """关联邮件到客户或订单"""
    if entity_type not in ["client", "order"]:
        return {"success": False, "message": "无效的实体类型"}

    result = create_mail_relation(mail_id, entity_type, entity_id)
    return result


@app.delete("/api/mail/{mail_id}/relate/{relation_id}")
async def api_mail_unrelate(
    mail_id: int,
    relation_id: int,
    current_user: dict = Depends(login_required)
):
    """移除邮件关联"""
    result = remove_mail_relation(relation_id)
    return result


@app.delete("/api/mail/{mail_id}")
async def api_mail_delete(mail_id: int, current_user: dict = Depends(login_required)):
    """删除邮件"""
    result = delete_email(mail_id)
    return result


@app.post("/api/mail/batch-delete")
async def api_mail_batch_delete(request: Request, current_user: dict = Depends(login_required)):
    """批量删除邮件"""
    from Sills.db_mail import batch_delete_emails
    data = await request.json()
    mail_ids = data.get('ids', [])
    if not mail_ids:
        return {"success": False, "message": "未选择邮件"}
    deleted = batch_delete_emails(mail_ids)
    return {"success": True, "deleted": deleted}


@app.post("/api/mail/{mail_id}/read")
async def api_mail_mark_read(mail_id: int, current_user: dict = Depends(login_required)):
    """标记邮件为已读"""
    from Sills.db_mail import mark_email_read
    mark_email_read(mail_id)
    return {"success": True}


@app.get("/api/mail/{mail_id}/analyze")
async def api_mail_analyze(mail_id: int, current_user: dict = Depends(login_required)):
    """AI 分析邮件"""
    email = get_mail_by_id(mail_id)
    if not email:
        raise HTTPException(status_code=404, detail="邮件不存在")

    content = email.get("content", "") or email.get("html_content", "")
    subject = email.get("subject", "")

    result = intent_recognizer.analyze(content, subject)
    return {
        "success": True,
        "analysis": result
    }


@app.get("/api/mail/{mail_id}/suggest-reply")
async def api_mail_suggest_reply(mail_id: int, current_user: dict = Depends(login_required)):
    """AI 建议回复"""
    email = get_mail_by_id(mail_id)
    if not email:
        raise HTTPException(status_code=404, detail="邮件不存在")

    content = email.get("content", "") or email.get("html_content", "")
    sender = email.get("from_addr", "")

    # 解析发件人名称
    sender_name = ""
    if sender:
        from email.utils import parseaddr
        sender_name, _ = parseaddr(sender)

    reply = smart_replier.generate_reply(content, {"client_name": sender_name})
    return {
        "success": True,
        "suggested_reply": reply
    }

# ==================== SmartMail 路由结束 ====================

if __name__ == "__main__":
    # 根据环境选择端口: Windows=8001, WSL=8000
    env = get_server_env()
    port = 8001 if env == "Windows" else 8000
    uvicorn.run("main:app", host="127.0.0.1", port=port, reload=True)
