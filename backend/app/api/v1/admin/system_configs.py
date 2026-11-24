from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import require_permissions
from app.schemas.common import ok
from app.schemas.system import (
    AlertWebhookTestRequest,
    SmtpTestRequest,
    SysConfigBatchUpdateRequest,
    SysConfigResetRequest,
)
from app.services import alert_service, email_service, sys_config_service

router = APIRouter(prefix="/system", tags=["管理端-动态系统配置中心"])


@router.get("/configs", summary="按分组获取系统全部动态配置")
async def get_system_configs(
    _current_admin: dict[str, Any] = Depends(require_permissions("system:config:view")),
):
    return ok(await sys_config_service.list_grouped_configs())


@router.put("/configs", summary="批量更新系统配置并经 Redis 热生效")
async def update_system_configs(
    req: SysConfigBatchUpdateRequest,
    current_admin: dict[str, Any] = Depends(require_permissions("system:config:manage")),
):
    admin_id = int(current_admin.get("sub", 0))
    data = await sys_config_service.batch_update_configs(req.items, admin_id=admin_id)
    return ok(data, message="系统配置已保存并实时生效")


@router.post("/configs/reset", summary="恢复指定分组或全部配置为系统默认值")
async def reset_system_configs(
    req: SysConfigResetRequest,
    current_admin: dict[str, Any] = Depends(require_permissions("system:config:manage")),
):
    admin_id = int(current_admin.get("sub", 0))
    data = await sys_config_service.reset_configs(req.group_name, admin_id=admin_id)
    return ok(data, message="已恢复系统默认配置并实时生效")


@router.post("/smtp/test", summary="发送 SMTP 连通性测试邮件")
async def test_smtp_delivery(
    req: SmtpTestRequest,
    _current_admin: dict[str, Any] = Depends(require_permissions("system:config:manage")),
):
    res = await email_service.send_test_email(req.to_email)
    return ok(res, message=f"测试邮件发送成功（耗时 {res['latency_ms']}ms）")


@router.post("/alert/test", summary="发送企业微信/飞书/钉钉异常告警连通性测试")
async def test_alert_webhook(
    req: AlertWebhookTestRequest,
    _current_admin: dict[str, Any] = Depends(require_permissions("system:config:manage")),
):
    res = await alert_service.send_test_alert(req.message)
    return ok(res, message=res.get("message", "测试告警发送成功"))
