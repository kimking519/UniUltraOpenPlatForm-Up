"""
报价管理路由模块
"""
import urllib.parse
from fastapi import APIRouter, Request, Form, Depends, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse

from Sills.base import get_paginated_list, get_db_connection, get_exchange_rates
from Sills.db_offer import get_offer_list, add_offer, batch_import_offer_text, update_offer, delete_offer, batch_delete_offer
from routes.auth import login_required, templates

router = APIRouter(prefix="/offer", tags=["offer"])


@router.get("", response_class=HTMLResponse)
async def offer_page(
    request: Request, current_user: dict = Depends(login_required),
    page: int = 1, page_size: int = 20, search: str = "",
    start_date: str = "", end_date: str = "", cli_id: str = "",
    is_transferred: str = ""
):
    """报价列表页面"""
    session = request.session
    has_params = any(k in request.query_params for k in ['search', 'start_date', 'end_date', 'cli_id', 'is_transferred'])

    if not has_params:
        search = session.get("offer_search", "")
        start_date = session.get("offer_start_date", "")
        end_date = session.get("offer_end_date", "")
        cli_id = session.get("offer_cli_id", "")
        is_transferred = session.get("offer_is_transferred", "未转")
        page_size = session.get("offer_page_size", 20)
    else:
        session["offer_search"] = search
        session["offer_start_date"] = start_date
        session["offer_end_date"] = end_date
        session["offer_cli_id"] = cli_id
        session["offer_is_transferred"] = is_transferred
        session["offer_page_size"] = page_size

    query_is_transferred = is_transferred
    results, total = get_offer_list(
        page=page, page_size=page_size, search_kw=search,
        start_date=start_date, end_date=end_date,
        cli_id=cli_id, is_transferred=query_is_transferred
    )
    total_pages = (total + page_size - 1) // page_size
    vendor_data = get_paginated_list('uni_vendor', page=1, page_size=1000)
    vendor_list = vendor_data['items']
    cli_data = get_paginated_list('uni_cli', page=1, page_size=1000)
    cli_list = sorted(cli_data['items'], key=lambda x: x.get('cli_name', ''))

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


@router.post("/add")
async def offer_add_route(request: Request, current_user: dict = Depends(login_required)):
    """添加报价"""
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/offer", status_code=303)
    form = await request.form()
    data = dict(form)
    emp_id = current_user['emp_id']

    # 自动报价逻辑
    if (not data.get('offer_price_rmb') or float(data.get('offer_price_rmb') or 0) == 0) and data.get('quote_id'):
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
                if not data.get('cost_price_rmb') or float(data.get('cost_price_rmb') or 0) == 0:
                    data['cost_price_rmb'] = cost

    ok, msg = add_offer(data, emp_id)
    msg_param = urllib.parse.quote(msg)
    success = 1 if ok else 0
    return RedirectResponse(url=f"/offer?msg={msg_param}&success={success}", status_code=303)


@router.post("/import")
async def offer_import_text(batch_text: str = Form(...), current_user: dict = Depends(login_required)):
    """批量导入报价（文本）"""
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/offer", status_code=303)
    success_count, errors = batch_import_offer_text(batch_text, current_user['emp_id'])
    err_msg = ""
    if errors:
        err_msg = "&msg=" + urllib.parse.quote(errors[0])
    return RedirectResponse(url=f"/offer?import_success={success_count}&errors={len(errors)}{err_msg}", status_code=303)


@router.post("/import/csv")
async def offer_import_csv(csv_file: UploadFile = File(...), current_user: dict = Depends(login_required)):
    """批量导入报价（CSV）"""
    if current_user['rule'] not in ['3', '0']:
        return RedirectResponse(url="/offer", status_code=303)
    content = await csv_file.read()
    try:
        text = content.decode('utf-8-sig').strip()
    except UnicodeDecodeError:
        text = content.decode('gbk', errors='replace').strip()

    success_count, errors = batch_import_offer_text(text, current_user['emp_id'])
    err_msg = ""
    if errors:
        err_msg = "&msg=" + urllib.parse.quote(errors[0])
    return RedirectResponse(url=f"/offer?import_success={success_count}&errors={len(errors)}{err_msg}", status_code=303)


# API 端点
api_router = APIRouter(tags=["offer-api"])


@api_router.get("/api/exchange/rates")
async def get_exchange_rates_api(current_user: dict = Depends(login_required)):
    """获取最新汇率"""
    krw, usd, _ = get_exchange_rates()
    return {"success": True, "krw": krw, "usd": usd}


@api_router.post("/api/offer/update")
async def offer_update_api(offer_id: str = Form(...), field: str = Form(...), value: str = Form(default=""), current_user: dict = Depends(login_required)):
    """更新报价API"""
    if current_user['rule'] not in ['3', '0']:
        return {"success": False, "message": "无修改权限"}
    allowed_fields = ['cli_id', 'quoted_mpn', 'quoted_brand', 'quoted_qty', 'offer_price_rmb', 'offer_price_kwr', 'offer_price_usd', 'cost_price_rmb', 'date_code', 'delivery_date', 'remark', 'is_transferred', 'vendor_id']
    if field not in allowed_fields:
        return {"success": False, "message": f"非法字段: {field}"}

    if field in ['quoted_qty', 'offer_price_rmb', 'offer_price_kwr', 'offer_price_usd', 'cost_price_rmb']:
        try:
            val = float(value)
            success, msg = update_offer(offer_id, {field: val})
            return {"success": success, "message": msg}
        except:
            return {"success": False, "message": "必须是数字"}

    success, msg = update_offer(offer_id, {field: value})
    return {"success": success, "message": msg}


@api_router.post("/api/offer/delete")
async def offer_delete_api(offer_id: str = Form(...), current_user: dict = Depends(login_required)):
    """删除报价API"""
    if current_user['rule'] != '3':
        return {"success": False, "message": "仅管理员可删除"}
    success, msg = delete_offer(offer_id)
    return {"success": success, "message": msg}


@api_router.post("/api/offer/batch_delete")
async def offer_batch_delete_api(request: Request, current_user: dict = Depends(login_required)):
    """批量删除报价"""
    if current_user['rule'] != '3':
        return {"success": False, "message": "仅管理员可删除"}
    data = await request.json()
    ids = data.get("ids", [])
    success, msg = batch_delete_offer(ids)
    return {"success": success, "message": msg}