from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.api.deps import require_permissions
from app.schemas.ai import AIPersonaCreate, AIPersonaUpdate
from app.schemas.common import ok
from app.services.ai_persona_service import (
    create_persona,
    delete_persona,
    list_personas,
    update_persona,
)
from app.services.ai_usage_service import get_ai_analytics

router = APIRouter(prefix="/ai", tags=["管理端-智能体与分析"])


@router.get("/personas", summary="获取全部 AI 智能体模板")
async def list_admin_personas(
    category: str | None = Query(default=None, description="分类过滤"),
    keyword: str | None = Query(default=None, description="关键字过滤"),
    _current_admin: dict[str, Any] = Depends(require_permissions("ai:config:view")),
):
    items = await list_personas(enabled_only=False, category=category, keyword=keyword)
    return ok({"items": items, "total": len(items)})


@router.post("/personas", summary="新建 AI 智能体模板")
async def create_admin_persona(
    payload: AIPersonaCreate,
    _current_admin: dict[str, Any] = Depends(require_permissions("ai:config:manage")),
):
    item = await create_persona(payload)
    return ok(item, message="智能体模板创建成功")


@router.put("/personas/{persona_id}", summary="更新 AI 智能体模板")
async def update_admin_persona(
    persona_id: int,
    payload: AIPersonaUpdate,
    _current_admin: dict[str, Any] = Depends(require_permissions("ai:config:manage")),
):
    item = await update_persona(persona_id, payload)
    return ok(item, message="智能体模板已更新")


@router.delete("/personas/{persona_id}", summary="删除 AI 智能体模板")
async def delete_admin_persona(
    persona_id: int,
    _current_admin: dict[str, Any] = Depends(require_permissions("ai:config:manage")),
):
    res = await delete_persona(persona_id)
    return ok(res, message="智能体模板已删除")


@router.get("/analytics", summary="AI 用量与趋势统计分析")
async def admin_ai_analytics(
    days: int = Query(default=7, ge=1, le=30, description="统计天数(1~30)"),
    _current_admin: dict[str, Any] = Depends(require_permissions("dashboard:view")),
):
    data = await get_ai_analytics(days=days)
    return ok(data)
