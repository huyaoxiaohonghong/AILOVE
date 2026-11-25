from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_current_token_payload
from app.core.exceptions import BusinessException
from app.core.rate_limit import rate_limit
from app.db.mysql import get_session_factory
from app.models.wechat_user import WechatUser
from app.schemas.ai import (
    ChatRequest,
    ConversationUpdateRequest,
    FavoriteReplyCreate,
    LoveProfileUpdateRequest,
    ReplyHelperRequest,
    SoftenDraftRequest,
)
from app.schemas.common import ok
from app.services import favorite_reply_service, sys_config_service
from app.services.ai_config_service import list_ai_configs, resolve_vision_config
from app.services.ai_persona_service import list_personas
from app.services.ai_providers import get_provider_adapter
from app.services.ai_usage_service import get_user_quota_status
from app.services.emotion_guard import get_reply_helper_presets, get_soften_draft_presets
from app.services.llm_service import build_owner_scope, llm_service
from app.services.love_profile_service import (
    clear_love_profile,
    get_love_profile,
    get_love_profile_presets,
    upsert_love_profile,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["AI-LangChain 对话"])


@router.get("/conversations", summary="获取当前用户的 AI 历史会话列表")
async def list_conversations(current_user: dict[str, Any] = Depends(get_current_token_payload)):
    user_type, user_id = _resolve_identity(current_user)
    items = await llm_service.list_conversations(user_type, user_id, limit=30)
    return ok({"items": items})


@router.get("/conversations/{session_id}/messages", summary="加载指定历史会话完整消息并预热上下文")
async def get_conversation_messages(
    session_id: str,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    user_type, user_id = _resolve_identity(current_user)
    conv = await llm_service.get_conversation_messages(session_id, user_type, user_id)
    if conv is None:
        raise BusinessException("目标会话不存在或无权访问", code=40405, status_code=404)
    return ok(conv)


@router.patch("/conversations/{session_id}", summary="更新 AI 历史会话（重命名 / 置顶 / 绑定智能体）")
async def update_conversation(
    session_id: str,
    req: ConversationUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    if (
        req.title is None
        and req.is_pinned is None
        and req.persona_id is None
        and not req.clear_persona
    ):
        raise BusinessException("请至少提供一项待更新的会话属性", code=40052, status_code=400)
    user_type, user_id = _resolve_identity(current_user)
    updated = await llm_service.update_conversation(
        session_id,
        user_type,
        user_id,
        title=req.title,
        is_pinned=req.is_pinned,
        persona_id=req.persona_id,
        clear_persona=req.clear_persona,
    )
    if updated is None:
        raise BusinessException("目标会话不存在或无权访问", code=40405, status_code=404)
    return ok(updated, message="会话信息已更新")


@router.delete("/conversations/{session_id}", summary="删除 AI 历史会话及上下文记忆")
async def delete_conversation(
    session_id: str,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    user_type, user_id = _resolve_identity(current_user)
    deleted = await llm_service.delete_conversation(session_id, user_type, user_id)
    if not deleted:
        raise BusinessException("目标会话不存在或无权访问", code=40405, status_code=404)
    return ok({"session_id": session_id, "deleted": True}, message="会话已删除")


@router.get("/models", summary="获取当前已启用的可选 AI 模型列表")
async def get_available_models(_user: dict[str, Any] = Depends(get_current_token_payload)):
    configs = await list_ai_configs(only_enabled=True)
    items = []
    for c in configs:
        adapter = get_provider_adapter(c.provider)
        supports_reasoning = (
            adapter.supports_reasoning_model(c.model_name)
            if adapter is not None
            else c.model_name in {"deepseek-v4-pro", "deepseek-reasoner"}
        )
        supports_vision = (
            adapter.supports_vision_model(c.model_name) if adapter is not None else False
        )
        items.append(
            {
                "id": c.id,
                "name": c.name,
                "provider": c.provider,
                "protocol": c.protocol,
                "model_name": c.model_name,
                "is_default": c.is_default,
                "has_api_key": c.has_api_key,
                "supports_reasoning": supports_reasoning,
                "supports_vision": supports_vision,
                "last_test_status": c.last_test_status,
            }
        )
    return ok({"items": items})


@router.get("/personas", summary="获取当前已启用的 AI 智能体广场列表")
async def get_public_ai_personas(
    category: str | None = Query(default=None, description="分类过滤"),
    _user: dict[str, Any] = Depends(get_current_token_payload),
):
    items = await list_personas(enabled_only=True, category=category)
    return ok({"items": items, "total": len(items)})


@router.get("/quota", summary="查询当前用户今日 AI 调用配额")
async def get_my_ai_quota(current_user: dict[str, Any] = Depends(get_current_token_payload)):
    user_type, user_id = _resolve_identity(current_user)
    _, role = _resolve_user_meta(current_user)
    quota = await get_user_quota_status(build_owner_scope(user_type, user_id), role)
    return ok(quota)


@router.get("/love-profile", summary="获取当前用户的恋爱情感背景记忆卡与预设选项")
async def get_my_love_profile(current_user: dict[str, Any] = Depends(get_current_token_payload)):
    user_type, user_id = _resolve_identity(current_user)
    profile = await get_love_profile(user_type, user_id)
    return ok({"profile": profile, "presets": get_love_profile_presets()})


@router.put("/love-profile", summary="保存或更新当前用户的恋爱情感背景记忆卡")
async def save_my_love_profile(
    req: LoveProfileUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    user_type, user_id = _resolve_identity(current_user)
    profile = await upsert_love_profile(
        user_type,
        user_id,
        relationship_stage=req.relationship_stage,
        partner_nickname=req.partner_nickname,
        partner_traits=req.partner_traits,
        my_traits=req.my_traits,
        relationship_goal=req.relationship_goal,
        communication_taboos=req.communication_taboos,
        background_notes=req.background_notes,
        auto_inject=req.auto_inject,
    )
    return ok({"profile": profile}, message="个人情感档案已保存")


@router.delete("/love-profile", summary="清空当前用户的恋爱情感背景记忆卡")
async def delete_my_love_profile(current_user: dict[str, Any] = Depends(get_current_token_payload)):
    user_type, user_id = _resolve_identity(current_user)
    profile = await clear_love_profile(user_type, user_id)
    return ok({"profile": profile}, message="个人情感档案已清空")


@router.get("/reply-helper/presets", summary="获取「帮我回消息 2.0」场景与语气预设")
async def get_reply_helper_options(_user: dict[str, Any] = Depends(get_current_token_payload)):
    presets = get_reply_helper_presets()
    vision_cfg = await resolve_vision_config()
    presets["has_vision_model"] = vision_cfg is not None
    presets["vision_model_label"] = (
        f"{vision_cfg.name} ({vision_cfg.model_name})" if vision_cfg is not None else ""
    )
    return ok(presets)


@router.get("/soften-draft/presets", summary="获取「先别发！」情绪降温与话术柔化预设")
async def get_soften_draft_options(_user: dict[str, Any] = Depends(get_current_token_payload)):
    return ok(get_soften_draft_presets())


@router.get("/favorites", summary="获取当前用户的高情商话术收藏夹")
async def list_my_favorites(
    category: str | None = Query(default=None, description="分类过滤"),
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    user_type, user_id = _resolve_identity(current_user)
    items = await favorite_reply_service.list_favorites(user_type, user_id, category=category)
    return ok({"items": items, "total": len(items)})


@router.post("/favorites", summary="收藏一条高情商话术")
async def save_my_favorite(
    req: FavoriteReplyCreate,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    user_type, user_id = _resolve_identity(current_user)
    item, deduplicated = await favorite_reply_service.create_favorite(
        user_type,
        user_id,
        content=req.content,
        category=req.category,
        scene_label=req.scene_label,
        note=req.note,
    )
    msg = "已在你的话术收藏夹中" if deduplicated else "已收藏到「高情商话术库」"
    return ok({"item": item, "deduplicated": deduplicated}, message=msg)


@router.delete("/favorites/{favorite_id}", summary="删除一条已收藏的话术")
async def delete_my_favorite(
    favorite_id: int,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    user_type, user_id = _resolve_identity(current_user)
    deleted = await favorite_reply_service.delete_favorite(user_type, user_id, favorite_id)
    if not deleted:
        raise BusinessException("目标收藏话术不存在或无权删除", code=40407, status_code=404)
    return ok({"deleted_id": favorite_id}, message="已移出话术收藏夹")


@router.get("/my-data/export", summary="导出当前用户的私密情感手账（Markdown）")
async def export_my_love_journal(
    format: str = Query(default="markdown", description="markdown=下载.md文件 / json=返回正文与统计"),
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    user_type, user_id = _resolve_identity(current_user)
    bundle = await llm_service.export_user_journal_markdown(user_type, user_id)
    if format == "json":
        return ok(bundle)
    return Response(
        content=bundle["markdown"].encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{bundle["filename"]}"',
            "Cache-Control": "no-store",
        },
    )


@router.delete("/my-data", summary="一键彻底清除当前用户的全部云端情感档案、对话与收藏")
async def purge_my_ai_data(
    include_love_profile: bool = Query(default=True, description="同时清空情感档案记忆卡"),
    include_favorites: bool = Query(default=True, description="同时清空高情商话术收藏夹"),
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    user_type, user_id = _resolve_identity(current_user)
    cleared_convs = await llm_service.purge_all_user_conversations(user_type, user_id)
    cleared_favs = 0
    if include_favorites:
        cleared_favs = await favorite_reply_service.delete_all_favorites(user_type, user_id)
    if include_love_profile:
        await clear_love_profile(user_type, user_id)
    return ok(
        {
            "cleared_conversations": cleared_convs,
            "cleared_favorites": cleared_favs,
            "cleared_love_profile": include_love_profile,
        },
        message="你的全部云端私密情感数据已彻底销毁",
    )


async def _ensure_miniapp_invite_access(current_user: dict[str, Any]) -> None:
    """当系统开启小圈子邀请码准入时，拦截未通过邀请码激活的微信小程序用户调用 AI。"""
    if str(current_user.get("type", "web")) != "miniapp":
        return
    if not await sys_config_service.get_bool("registration.invite_code_required", default=False):
        return
    openid = str(current_user.get("openid", ""))
    if openid:
        try:
            factory = get_session_factory()
            async with factory() as session:
                user = (
                    await session.execute(select(WechatUser).where(WechatUser.openid == openid))
                ).scalar_one_or_none()
                if user is not None:
                    if user.invite_verified:
                        return
                    raise BusinessException(
                        "当前为小圈子内测模式，请先前往「首页」或「我的」输入邀请码激活",
                        code=40308,
                        status_code=status.HTTP_403_FORBIDDEN,
                    )
        except BusinessException:
            raise
        except (SQLAlchemyError, OSError):
            from app.api.v1.miniapp.user import _mem_miniapp_profiles  # noqa: PLC0415

            mem_prof = _mem_miniapp_profiles.get(openid)
            if mem_prof and mem_prof.get("invite_verified"):
                return

    if current_user.get("invite_verified"):
        return
    raise BusinessException(
        "当前为小圈子内测模式，请先前往「首页」或「我的」输入邀请码激活",
        code=40308,
        status_code=status.HTTP_403_FORBIDDEN,
    )


def _resolve_identity(current_user: dict[str, Any]) -> tuple[str, int]:
    user_type = str(current_user.get("type", "web"))
    raw_sub = str(current_user.get("sub", "0")).strip()
    if raw_sub.isdigit():
        return user_type, int(raw_sub)
    seed = raw_sub or str(current_user.get("openid", "")).strip()
    if seed:
        hashed = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12], 16)
        return user_type, 1_000_000 + (hashed % 1_000_000_000)
    return user_type, 0


def _resolve_user_meta(current_user: dict[str, Any]) -> tuple[str, str]:
    username = str(
        current_user.get("username")
        or current_user.get("email")
        or current_user.get("nickname")
        or current_user.get("sub")
        or ""
    )
    user_type = str(current_user.get("type", "web"))
    role = str(current_user.get("role") or ("user" if user_type == "miniapp" else "user"))
    return username, role


def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post(
    "/chat",
    summary="LangChain 同步多轮对话",
    dependencies=[Depends(rate_limit("ai_chat", limit=30, window_seconds=60, by_user=True))],
)
async def ai_chat(
    req: ChatRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    await _ensure_miniapp_invite_access(current_user)
    user_type, user_id = _resolve_identity(current_user)
    username, role = _resolve_user_meta(current_user)
    result = await llm_service.chat(
        req, user_type=user_type, user_id=user_id, username=username, role=role
    )
    return ok(result.model_dump())


def _build_sse_response(
    session_id: str,
    cfg: Any,
    meta: dict[str, Any],
    event_gen: Any,
    *,
    user_message_preview: str | None = None,
) -> StreamingResponse:
    async def event_generator():
        meta_payload: dict[str, Any] = {
            "event": "meta",
            "session_id": session_id,
            "model": cfg.model_name,
            "provider": cfg.provider,
            "protocol": cfg.protocol,
            "config_name": cfg.name,
            "persona_id": meta.get("persona_id"),
            "persona_name": meta.get("persona_name") or "",
            "is_mock": not cfg.is_configured,
            "incognito": bool(meta.get("incognito", False)),
            "love_profile_injected": bool(meta.get("love_profile_injected", False)),
            "emotion_care": meta.get("emotion_care"),
        }
        if user_message_preview is not None:
            meta_payload["prompt_preview"] = user_message_preview
        yield _sse(meta_payload)
        try:
            async for event_type, chunk in event_gen:
                yield _sse({"event": event_type, "content": chunk})
            yield _sse({"event": "done", "session_id": session_id})
        except BusinessException as exc:
            yield _sse({"event": "error", "message": exc.message})
        except Exception:
            logger.exception("Unexpected SSE stream failure (session=%s)", session_id)
            yield _sse({"event": "error", "message": "流式生成发生内部错误，请稍后重试"})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/chat/stream",
    summary="LangChain SSE 流式多轮对话（支持 OpenAI/Anthropic 双协议与深度思考流）",
    dependencies=[Depends(rate_limit("ai_chat", limit=30, window_seconds=60, by_user=True))],
)
async def ai_chat_stream(
    req: ChatRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    await _ensure_miniapp_invite_access(current_user)
    user_type, user_id = _resolve_identity(current_user)
    username, role = _resolve_user_meta(current_user)
    session_id, cfg, persona_meta, event_gen = await llm_service.stream_chat(
        req, user_type=user_type, user_id=user_id, username=username, role=role
    )
    return _build_sse_response(session_id, cfg, persona_meta, event_gen)


@router.post(
    "/reply-helper",
    summary="「帮我回消息 2.0 / 聊天截图识图拆解」结构化同步生成",
    dependencies=[Depends(rate_limit("ai_chat", limit=30, window_seconds=60, by_user=True))],
)
async def ai_reply_helper(
    req: ReplyHelperRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    await _ensure_miniapp_invite_access(current_user)
    user_type, user_id = _resolve_identity(current_user)
    username, role = _resolve_user_meta(current_user)
    chat_req, extra_instruction, images = await llm_service.build_reply_helper_chat_request(req)
    result = await llm_service.chat(
        chat_req,
        user_type=user_type,
        user_id=user_id,
        username=username,
        role=role,
        extra_system_instruction=extra_instruction,
        images=images,
    )
    return ok(result.model_dump())


@router.post(
    "/reply-helper/stream",
    summary="「帮我回消息 2.0 / 聊天截图识图拆解」SSE 流式生成",
    dependencies=[Depends(rate_limit("ai_chat", limit=30, window_seconds=60, by_user=True))],
)
async def ai_reply_helper_stream(
    req: ReplyHelperRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    await _ensure_miniapp_invite_access(current_user)
    user_type, user_id = _resolve_identity(current_user)
    username, role = _resolve_user_meta(current_user)
    chat_req, extra_instruction, images = await llm_service.build_reply_helper_chat_request(req)
    session_id, cfg, persona_meta, event_gen = await llm_service.stream_chat(
        chat_req,
        user_type=user_type,
        user_id=user_id,
        username=username,
        role=role,
        extra_system_instruction=extra_instruction,
        images=images,
    )
    return _build_sse_response(
        session_id,
        cfg,
        persona_meta,
        event_gen,
        user_message_preview=chat_req.message,
    )


@router.post(
    "/soften-draft",
    summary="「先别发！情绪降温与话术柔化器」结构化同步生成",
    dependencies=[Depends(rate_limit("ai_chat", limit=30, window_seconds=60, by_user=True))],
)
async def ai_soften_draft(
    req: SoftenDraftRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    await _ensure_miniapp_invite_access(current_user)
    user_type, user_id = _resolve_identity(current_user)
    username, role = _resolve_user_meta(current_user)
    chat_req, extra_instruction = await llm_service.build_soften_draft_chat_request(req)
    result = await llm_service.chat(
        chat_req,
        user_type=user_type,
        user_id=user_id,
        username=username,
        role=role,
        extra_system_instruction=extra_instruction,
    )
    return ok(result.model_dump())


@router.post(
    "/soften-draft/stream",
    summary="「先别发！情绪降温与话术柔化器」SSE 流式生成",
    dependencies=[Depends(rate_limit("ai_chat", limit=30, window_seconds=60, by_user=True))],
)
async def ai_soften_draft_stream(
    req: SoftenDraftRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    await _ensure_miniapp_invite_access(current_user)
    user_type, user_id = _resolve_identity(current_user)
    username, role = _resolve_user_meta(current_user)
    chat_req, extra_instruction = await llm_service.build_soften_draft_chat_request(req)
    session_id, cfg, persona_meta, event_gen = await llm_service.stream_chat(
        chat_req,
        user_type=user_type,
        user_id=user_id,
        username=username,
        role=role,
        extra_system_instruction=extra_instruction,
    )
    return _build_sse_response(
        session_id,
        cfg,
        persona_meta,
        event_gen,
        user_message_preview=chat_req.message,
    )


@router.get("/sessions/{session_id}/history", summary="获取会话上下文历史（仅限本人会话）")
async def get_session_history(
    session_id: str,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner = build_owner_scope(*_resolve_identity(current_user))
    history = await llm_service.get_history(session_id, owner)
    return ok({"session_id": session_id, "messages": history})


@router.delete("/sessions/{session_id}", summary="清空指定会话记忆（仅限本人会话）")
async def clear_session_history(
    session_id: str,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner = build_owner_scope(*_resolve_identity(current_user))
    await llm_service.clear_history(session_id, owner)
    return ok({"session_id": session_id, "cleared": True})
