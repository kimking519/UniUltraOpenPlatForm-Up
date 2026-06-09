"""
任务看板路由模块
Dashboard Task Board - 4-column kanban view
"""
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse
from Sills.db_task_board import get_all_tasks, get_task_counts, update_task_status, add_alert, delete_alert
from routes.auth import login_required, templates

router = APIRouter(prefix="/task_board", tags=["task-board"])
api_router = APIRouter(tags=["task-board-api"])


# Page route (redirects to dashboard with kanban view)
@router.get("", response_class=HTMLResponse)
async def task_board_page(request: Request, current_user: dict = Depends(login_required)):
    """任务看板页面 - 重定向到dashboard"""
    return RedirectResponse(url="/", status_code=303)


# API endpoints with pagination
@api_router.get("/api/task_board/list")
async def api_task_list(
    status: str = Query(None, description="Filter by status: pending/in_progress/inspection/completed"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Tasks per page"),
    current_user: dict = Depends(login_required)
):
    """获取任务列表API"""
    try:
        tasks, total = get_all_tasks(status_filter=status, page=page, page_size=page_size)
        return {
            "success": True,
            "tasks": tasks,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": total > page * page_size
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"查询失败: {str(e)}"}
        )


@api_router.get("/api/task_board/counts")
async def api_task_counts(current_user: dict = Depends(login_required)):
    """获取任务计数API（用于摘要栏）"""
    try:
        counts = get_task_counts()
        return {
            "success": True,
            "counts": counts,
            "total": sum(counts.values())
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"计数查询失败: {str(e)}"}
        )


@api_router.post("/api/task_board/update_status")
async def api_update_status(request: Request, current_user: dict = Depends(login_required)):
    """更新任务状态API"""
    try:
        data = await request.json()

        # Validate ref_type
        valid_ref_types = ['contact', 'quote', 'order', 'buy', 'alert']
        if data.get('ref_type') not in valid_ref_types:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": f"无效的 ref_type: {data.get('ref_type')}"}
            )

        # Validate status transition
        valid_statuses = ['pending', 'in_progress', 'inspection', 'completed']
        if data.get('new_status') not in valid_statuses:
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": f"无效的 new_status: {data.get('new_status')}"}
            )

        success, msg = update_task_status(data['ref_type'], data['ref_id'], data['new_status'])

        if success:
            return {"success": True, "message": msg}
        else:
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": msg}
            )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"更新失败: {str(e)}"}
        )


@api_router.post("/api/task_board/alert/add")
async def api_add_alert(request: Request, current_user: dict = Depends(login_required)):
    """添加综合预警API"""
    try:
        data = await request.json()

        if not data.get('alert_title'):
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "alert_title 必填"}
            )

        # Add created_by from current user
        data['created_by'] = current_user.get('emp_id')

        success, msg = add_alert(data)

        if success:
            return {"success": True, "message": msg}
        else:
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": msg}
            )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"添加失败: {str(e)}"}
        )


@api_router.delete("/api/task_board/alert/{alert_id}")
async def api_delete_alert(alert_id: str, current_user: dict = Depends(login_required)):
    """删除综合预警API"""
    try:
        success, msg = delete_alert(alert_id)

        if success:
            return {"success": True, "message": msg}
        else:
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": msg}
            )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"删除失败: {str(e)}"}
        )


# Need to import RedirectResponse
from fastapi.responses import RedirectResponse