from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.deps import get_current_token_payload
from app.api.v1.ai.chat import _resolve_identity
from app.core.exceptions import BusinessException
from app.schemas.common import ok
from app.services import mascot_service

router = APIRouter(prefix="/mascot", tags=["看板娘恋恋 2.0"])

GestureType = Literal[
    "rub_head",
    "poke_cheek",
    "pull_ear",
    "pull_tail",
    "combo_dizzy",
    "long_hug",
    "drag_swing",
    "edge_peek",
]


class MascotInteractRequest(BaseModel):
    gesture: GestureType = Field(..., description="触控手势标识")
    dv: float | None = Field(default=None, ge=-0.6, le=0.6, description="可选愉悦度微调")
    da: float | None = Field(default=None, ge=-0.6, le=0.6, description="可选唤醒度微调")


class MoodCheckinRequest(BaseModel):
    score: int = Field(..., ge=1, le=5, description="今日心情分 1~5")
    note: str = Field(default="", max_length=120, description="可选一句话心情记录")


class ProfilePatchRequest(BaseModel):
    relationship_stage: str = Field(default="", max_length=32)
    partner_nickname: str = Field(default="", max_length=32)
    partner_traits: list[str] = Field(default_factory=list, max_length=6)
    my_traits: list[str] = Field(default_factory=list, max_length=6)
    relationship_goal: str = Field(default="", max_length=160)
    communication_taboos: str = Field(default="", max_length=300)
    background_notes: str = Field(default="", max_length=400)


@router.get("/state", summary="获取恋恋实时情感状态（PAD 衰减 + 羁绊等级 + 记忆摘要 + 久别问候）")
async def get_state(current_user: dict[str, Any] = Depends(get_current_token_payload)):
    user_type, user_id = _resolve_identity(current_user)
    state = await mascot_service.get_mascot_state(user_type, user_id)
    return ok(state)


@router.post("/interact", summary="上报对恋恋的触控互动手势并更新 PAD 与亲密度")
async def interact(
    req: MascotInteractRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    user_type, user_id = _resolve_identity(current_user)
    res = await mascot_service.record_interaction(
        user_type,
        user_id,
        gesture=req.gesture,
        dv_override=req.dv,
        da_override=req.da,
    )
    return ok(res)


@router.post("/mood-checkin", summary="记录今日心情打卡并触发恋恋专属反馈")
async def mood_checkin(
    req: MoodCheckinRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    user_type, user_id = _resolve_identity(current_user)
    res = await mascot_service.record_mood_checkin(
        user_type,
        user_id,
        score=req.score,
        note=req.note,
    )
    return ok(res)


@router.post("/profile-patch", summary="一键采纳恋恋提议的情感档案补丁")
async def apply_profile_patch(
    req: ProfilePatchRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    user_type, user_id = _resolve_identity(current_user)
    updated = await mascot_service.apply_love_profile_patch(
        user_type, user_id, req.model_dump()
    )
    return ok({"profile": updated}, message="恋恋已帮你记进情感档案啦")


@router.get("/memories", summary="查看恋恋记住的近期情景事件记忆")
async def list_memories(current_user: dict[str, Any] = Depends(get_current_token_payload)):
    user_type, user_id = _resolve_identity(current_user)
    items = await mascot_service.list_memories(user_type, user_id, limit=30)
    return ok({"items": items, "total": len(items)})


@router.delete("/memories/{memory_id}", summary="让恋恋忘掉某条情景记忆")
async def forget_memory(
    memory_id: int,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    user_type, user_id = _resolve_identity(current_user)
    deleted = await mascot_service.delete_memory(user_type, user_id, memory_id)
    if not deleted:
        raise BusinessException("目标记忆不存在或已清除", code=40412, status_code=404)
    return ok({"deleted_id": memory_id}, message="恋恋已经帮你忘掉这条记忆啦")
