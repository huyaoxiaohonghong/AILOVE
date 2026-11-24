from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import require_permissions
from app.schemas.ai import AIModelConfigCreate, AIModelConfigUpdate
from app.schemas.common import ok
from app.services.ai_config_service import (
    create_ai_config,
    delete_ai_config,
    list_ai_configs,
    set_default_ai_config,
    test_ai_config_connection,
    update_ai_config,
)
from app.services.ai_providers import list_all_providers

router = APIRouter(prefix="/ai", tags=["管理端-AI模型与提供商配置"])


@router.get("/providers", summary="获取支持的 AI 模型提供商注册表（DeepSeek / 通义千问 / 豆包 / Moonshot）")
async def get_ai_providers(
    _current_admin: dict[str, Any] = Depends(require_permissions("ai:config:view")),
):
    return ok({"items": list_all_providers()})


@router.get("/configs", summary="获取所有 AI 模型配置列表（API Key 已脱敏）")
async def get_ai_configs(
    _current_admin: dict[str, Any] = Depends(require_permissions("ai:config:view")),
):
    items = await list_ai_configs(only_enabled=False)
    return ok({"items": [item.model_dump(mode="json") for item in items]})


@router.post("/configs", summary="新增 AI 模型配置（API Key 自动加密入库）")
async def create_config(
    req: AIModelConfigCreate,
    current_admin: dict[str, Any] = Depends(require_permissions("ai:config:manage")),
):
    admin_id = int(current_admin.get("sub", 0))
    created = await create_ai_config(req, admin_id=admin_id)
    return ok(created.model_dump(mode="json"), message="AI 模型配置创建成功")


@router.put("/configs/{config_id}", summary="编辑 AI 模型配置（留空 API Key 保持原值）")
async def edit_config(
    config_id: int,
    req: AIModelConfigUpdate,
    current_admin: dict[str, Any] = Depends(require_permissions("ai:config:manage")),
):
    admin_id = int(current_admin.get("sub", 0))
    updated = await update_ai_config(config_id, req, admin_id=admin_id)
    return ok(updated.model_dump(mode="json"), message="AI 模型配置已保存并热生效")


@router.post("/configs/{config_id}/set-default", summary="设为全局默认生效模型")
async def mark_default_config(
    config_id: int,
    current_admin: dict[str, Any] = Depends(require_permissions("ai:config:manage")),
):
    admin_id = int(current_admin.get("sub", 0))
    updated = await set_default_ai_config(config_id, admin_id=admin_id)
    return ok(updated.model_dump(mode="json"), message=f"已将「{updated.name}」设为默认模型")


@router.post("/configs/{config_id}/test", summary="一键真实连通性探针测试")
async def test_config(
    config_id: int,
    _current_admin: dict[str, Any] = Depends(require_permissions("ai:config:manage")),
):
    result = await test_ai_config_connection(config_id)
    return ok(result, message=result["message"])


@router.delete("/configs/{config_id}", summary="删除指定 AI 模型配置")
async def remove_config(
    config_id: int,
    _current_admin: dict[str, Any] = Depends(require_permissions("ai:config:manage")),
):
    await delete_ai_config(config_id)
    return ok({"id": config_id, "deleted": True}, message="模型配置已删除")
