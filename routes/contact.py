"""
联系人管理路由模块
"""
import io
from openpyxl import Workbook
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse

from Sills.base import get_db_connection
from Sills.db_contact import (
    get_contact_list, get_contact_by_id, get_contact_countries,
    get_marketing_stats, add_contact, update_contact, delete_contact,
    batch_delete_contacts
)
from routes.auth import login_required, templates

router = APIRouter(prefix="/contact", tags=["contact"])


@router.get("", response_class=HTMLResponse)
async def contact_page(request: Request, current_user: dict = Depends(login_required)):
    """联系人管理页面"""
    countries = get_contact_countries()
    stats = get_marketing_stats()
    return templates.TemplateResponse("contact.html", {
        "request": request,
        "active_page": "contact",
        "current_user": current_user,
        "countries": countries,
        "stats": stats
    })


# API 端点
api_router = APIRouter(tags=["contact-api"])


@api_router.get("/api/contact/list")
async def api_contact_list(
    page: int = 1,
    page_size: int = 20,
    search: str = None,
    cli_id: str = None,
    country: str = None,
    is_bounced: int = None,
    is_read: int = None,
    has_sent: int = None,
    prospect_tag: str = None,
    no_prospect_tag: str = None,
    current_user: dict = Depends(login_required)
):
    """获取联系人列表（支持按标识 prospect_tag 筛选）"""
    filters = {}
    if cli_id:
        filters['cli_id'] = cli_id
    if country:
        filters['country'] = country
    if is_bounced is not None:
        filters['is_bounced'] = is_bounced
    if is_read is not None:
        filters['is_read'] = is_read
    if has_sent is not None:
        filters['has_sent'] = has_sent
    # 标识筛选：no_prospect_tag 优先（tag IS NULL OR tag=0）
    if no_prospect_tag in ('1', 'true', 'True', 'yes'):
        filters['no_prospect_tag'] = True
    elif prospect_tag is not None and prospect_tag != '':
        filters['prospect_tag'] = prospect_tag

    items, total = get_contact_list(
        page=page,
        page_size=page_size,
        search_kw=search or "",
        filters=filters if filters else None
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@api_router.get("/api/contact/template")
async def api_contact_template(current_user: dict = Depends(login_required)):
    """下载联系人导入模板"""
    wb = Workbook()
    ws = wb.active
    ws.title = "联系人导入模板"
    ws.append(['域名*', '邮箱*', '姓名', '职位', '备注'])
    ws.append(['example.com', 'zhangsan@example.com', '张三', '经理', '备注信息'])
    ws.append(['test.com', 'lisi@test.com', '李四', '总监', ''])

    ws.column_dimensions['A'].width = 20
    ws.column_dimensions['B'].width = 25
    ws.column_dimensions['C'].width = 15
    ws.column_dimensions['D'].width = 15
    ws.column_dimensions['E'].width = 30

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=contact_template.xlsx"}
    )


@api_router.get("/api/contact/countries")
async def api_contact_countries(current_user: dict = Depends(login_required)):
    """获取所有国家列表"""
    return {"countries": get_contact_countries()}


@api_router.get("/api/contact/stats")
async def api_contact_stats(current_user: dict = Depends(login_required)):
    """获取营销统计数据"""
    return get_marketing_stats()


@api_router.get("/api/contact/{contact_id}")
async def api_contact_get(contact_id: str, current_user: dict = Depends(login_required)):
    """获取联系人详情"""
    contact = get_contact_by_id(contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="联系人不存在")
    return contact


@api_router.post("/api/contact/add")
async def api_contact_add(request: Request, current_user: dict = Depends(login_required)):
    """添加联系人"""
    data = await request.json()
    success, message = add_contact(data)
    return {"success": success, "message": message}


@api_router.post("/api/contact/update")
async def api_contact_update(request: Request, current_user: dict = Depends(login_required)):
    """更新联系人"""
    data = await request.json()
    contact_id = data.get('contact_id')
    if not contact_id:
        return {"success": False, "message": "缺少联系人ID"}

    update_data = {k: v for k, v in data.items() if k != 'contact_id'}
    success, message = update_contact(contact_id, update_data)
    return {"success": success, "message": message}


@api_router.post("/api/contact/delete")
async def api_contact_delete(request: Request, current_user: dict = Depends(login_required)):
    """删除联系人"""
    data = await request.json()
    contact_id = data.get('contact_id')
    if not contact_id:
        return {"success": False, "message": "缺少联系人ID"}
    success, message = delete_contact(contact_id)
    return {"success": success, "message": message}


@api_router.post("/api/contact/batch_delete")
async def api_contact_batch_delete(request: Request, current_user: dict = Depends(login_required)):
    """批量删除联系人"""
    data = await request.json()
    contact_ids = data.get('contact_ids', [])
    deleted, failed, message = batch_delete_contacts(contact_ids)
    return {"success": True, "deleted": deleted, "failed": failed, "message": message}


@api_router.post("/api/contact/clear_all")
async def api_contact_clear_all(current_user: dict = Depends(login_required)):
    """清空所有联系人"""
    with get_db_connection() as conn:
        deleted = conn.execute("SELECT COUNT(*) FROM uni_contact").fetchone()[0]
        conn.execute("DELETE FROM uni_contact")
        conn.commit()
    return {"success": True, "deleted": deleted, "message": f"已清空 {deleted} 条联系人"}