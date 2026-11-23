from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_permissions
from app.schemas.common import ok
from app.schemas.system import AuditLogCleanupRequest
from app.services import audit_log_service

router = APIRouter(prefix="/logs", tags=["管理端-操作审计与安全日志中心"])


@router.get("/summary", summary="获取近 24 小时审计与登录安全汇总")
async def get_logs_summary(
    _current_admin: dict[str, Any] = Depends(require_permissions("log:audit:view")),
):
    return ok(await audit_log_service.get_log_summary())


@router.get("/audit", summary="分页检索系统操作与越权审计日志")
async def list_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: str | None = Query(default=None, description="操作人 / 路径 / 动作 / RequestID"),
    module: str | None = Query(default=None, description="auth / account / ai / system / rbac / log"),
    result: str | None = Query(default=None, description="success / denied / error"),
    method: str | None = Query(default=None),
    status_code: int | None = Query(default=None),
    start_time: str | None = Query(default=None, description="ISO 起始时间"),
    end_time: str | None = Query(default=None, description="ISO 截止时间"),
    _current_admin: dict[str, Any] = Depends(require_permissions("log:audit:view")),
):
    data = await audit_log_service.query_audit_logs(
        page=page,
        page_size=page_size,
        keyword=keyword,
        module=module,
        result=result,
        method=method,
        status_code=status_code,
        start_time=start_time,
        end_time=end_time,
    )
    return ok(data)


@router.get("/login", summary="全站用户登录与风控失败审计日志分页查询")
async def list_all_login_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: str | None = Query(default=None, description="登录账号或客户端 IP"),
    status_filter: str | None = Query(default=None, alias="status", description="success / failed"),
    start_time: str | None = Query(default=None),
    end_time: str | None = Query(default=None),
    _current_admin: dict[str, Any] = Depends(require_permissions("log:audit:view")),
):
    data = await audit_log_service.query_all_login_logs(
        page=page,
        page_size=page_size,
        keyword=keyword,
        status_filter=status_filter,
        start_time=start_time,
        end_time=end_time,
    )
    return ok(data)


@router.post("/cleanup", summary="按保留天数清理历史审计日志与登录日志")
async def cleanup_logs(
    req: AuditLogCleanupRequest,
    _current_admin: dict[str, Any] = Depends(require_permissions("log:audit:manage")),
):
    res = await audit_log_service.cleanup_old_logs(
        retention_days=req.retention_days, target=req.target
    )
    return ok(res, message="过期日志清理完成")
