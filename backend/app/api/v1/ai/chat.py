from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.api.deps import get_current_token_payload
from app.core.exceptions import BusinessException
from app.core.rate_limit import rate_limit
from app.schemas.ai import ChatRequest, ConversationRenameRequest
from app.schemas.common import ok
from app.services.ai_config_service import list_ai_configs
from app.services.ai_persona_service import list_personas
from app.services.ai_providers import get_provider_adapter
from app.services.ai_usage_service import get_user_quota_status
from app.services.llm_service import build_owner_scope, llm_service

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


@router.patch("/conversations/{session_id}", summary="重命名 AI 历史会话标题")
async def rename_conversation(
    session_id: str,
    req: ConversationRenameRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    user_type, user_id = _resolve_identity(current_user)
    updated = await llm_service.rename_conversation(session_id, user_type, user_id, req.title)
    if updated is None:
        raise BusinessException("目标会话不存在或无权访问", code=40405, status_code=404)
    return ok(updated, message="会话标题已更新")


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


def _resolve_identity(current_user: dict[str, Any]) -> tuple[str, int]:
    user_type = str(current_user.get("type", "web"))
    raw_sub = str(current_user.get("sub", "0"))
    user_id = int(raw_sub) if raw_sub.isdigit() else 0
    return user_type, user_id


def _resolve_user_meta(current_user: dict[str, Any]) -> tuple[str, str]:
    username = str(
        current_user.get("username") or current_user.get("email") or current_user.get("sub") or ""
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
    user_type, user_id = _resolve_identity(current_user)
    username, role = _resolve_user_meta(current_user)
    result = await llm_service.chat(
        req, user_type=user_type, user_id=user_id, username=username, role=role
    )
    return ok(result.model_dump())


@router.post(
    "/chat/stream",
    summary="LangChain SSE 流式多轮对话（支持 OpenAI/Anthropic 双协议与深度思考流）",
    dependencies=[Depends(rate_limit("ai_chat", limit=30, window_seconds=60, by_user=True))],
)
async def ai_chat_stream(
    req: ChatRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    user_type, user_id = _resolve_identity(current_user)
    username, role = _resolve_user_meta(current_user)
    session_id, cfg, persona_meta, event_gen = await llm_service.stream_chat(
        req, user_type=user_type, user_id=user_id, username=username, role=role
    )

    async def event_generator():
        yield _sse(
            {
                "event": "meta",
                "session_id": session_id,
                "model": cfg.model_name,
                "provider": cfg.provider,
                "protocol": cfg.protocol,
                "config_name": cfg.name,
                "persona_id": persona_meta.get("persona_id"),
                "persona_name": persona_meta.get("persona_name") or "",
                "is_mock": not cfg.is_configured,
            }
        )
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
