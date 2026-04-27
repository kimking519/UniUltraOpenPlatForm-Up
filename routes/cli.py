"""
客户管理路由模块
"""
from fastapi import APIRouter, Request, Form, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
import io
from datetime import datetime

from Sills.base import get_paginated_list
from Sills.db_emp import get_emp_list
from Sills.db_cli import get_cli_list, add_cli, batch_import_cli_text, update_cli, delete_cli, batch_delete_cli, export_cli_to_excel
from Sills.db_order import get_order_list
from routes.auth import login_required, get_current_user, templates

router = APIRouter(prefix="/cli", tags=["cli"])


@router.get("", response_class=HTMLResponse)
async def cli_page(request: Request, page: int = 1, page_size: int = 20, search: str = "", current_user: dict = Depends(login_required)):
    """客户列表页面"""
    page_size = min(max(1, page_size), 100)
    search_kwargs = {"cli_name": search} if search else None
    result = get_paginated_list("uni_cli", page=page, page_size=page_size, search_kwargs=search_kwargs)
    employees, _ = get_emp_list(page=1, page_size=1000)

    return templates.TemplateResponse("cli.html", {
        "request": request,
        "active_page": "cli",
        "current_user": current_user,
        "items": result["items"],
        "total_pages": result["total_pages"],
        "total_count": result["total_count"],
        "page": page,
        "page_size": page_size,
        "search": search,
        "employees": employees
    })


@router.post("/add")
async def cli_add(
    cli_name: str = Form(...), cli_full_name: str = Form(""), cli_name_en: str = Form(""),
    contact_name: str = Form(""), address: str = Form(""),
    region: str = Form("韩国"), credit_level: str = Form("A"),
    margin_rate: float = Form(10.0), emp_id: str = Form(...), website: str = Form(""),
    payment_terms: str = Form(""), email: str = Form(""), phone: str = Form(""),
    remark: str = Form(""), current_user: dict = Depends(login_required)
):
    """添加客户"""
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


@router.post("/import")
async def cli_import(import_text: str = Form(...), current_user: dict = Depends(login_required)):
    """批量导入客户（文本）"""
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/cli", status_code=303)
    success_count, errors = batch_import_cli_text(import_text)
    return RedirectResponse(url=f"/cli?import_success={success_count}&errors={len(errors)}", status_code=303)


@router.post("/import/csv")
async def cli_import_csv(csv_file: UploadFile = File(...), current_user: dict = Depends(login_required)):
    """批量导入客户（CSV）"""
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/cli", status_code=303)
    content = await csv_file.read()
    try:
        text = content.decode('utf-8-sig').strip()
    except UnicodeDecodeError:
        text = content.decode('gbk', errors='replace').strip()

    if '\n' in text:
        text = text.split('\n', 1)[1]
    success_count, errors = batch_import_cli_text(text)
    return RedirectResponse(url=f"/cli?import_success={success_count}&errors={len(errors)}", status_code=303)


# API 端点
api_router = APIRouter(tags=["cli-api"])


@api_router.post("/api/cli/update")
async def cli_update_api(cli_id: str = Form(...), field: str = Form(...), value: str = Form(...), current_user: dict = Depends(login_required)):
    """更新客户API"""
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


@api_router.post("/api/cli/delete")
async def cli_delete_api(cli_id: str = Form(...), current_user: dict = Depends(login_required)):
    """删除客户API"""
    if current_user['rule'] != '3':
        return {"success": False, "message": "仅管理员可删除"}
    success, msg = delete_cli(cli_id)
    return {"success": success, "message": msg}


@api_router.post("/api/cli/batch_delete")
async def cli_batch_delete_api(request: Request, current_user: dict = Depends(login_required)):
    """批量删除客户"""
    if current_user['rule'] != '3':
        return {"success": False, "message": "仅管理员可删除"}

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


@api_router.get("/api/cli/export")
async def cli_export_api(current_user: dict = Depends(login_required)):
    """导出客户数据到Excel"""
    from urllib.parse import quote

    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    filename = f"cli_export_{timestamp}.xlsx"

    # 使用内存流
    output = io.BytesIO()
    success, result = export_cli_to_excel(output)

    if not success:
        return {"success": False, "message": result}

    output.seek(0)
    encoded_filename = quote(filename)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}"}
    )


@api_router.get("/api/cli/list")
async def cli_list_api(current_user: dict = Depends(get_current_user)):
    """获取客户列表API（用于邮件关联选择器）"""
    if not current_user:
        return {"success": False, "message": "未登录", "items": []}
    items, total = get_cli_list(page=1, page_size=1000)
    return {"success": True, "items": items, "total": total}


@api_router.get("/api/order/list")
async def order_list_api(current_user: dict = Depends(get_current_user)):
    """获取订单列表API（用于邮件关联选择器）"""
    if not current_user:
        return {"success": False, "message": "未登录", "items": []}
    items, total = get_order_list(page=1, page_size=1000)
    return {"success": True, "items": items, "total": total}