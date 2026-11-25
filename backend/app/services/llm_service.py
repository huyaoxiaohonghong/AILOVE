from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from sqlalchemy import delete, desc, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import BusinessException
from app.db.mysql import get_session_factory
from app.db.redis import cache_delete, cache_get_json, cache_set_json
from app.models.ai_chat import AIConversation
from app.models.ai_chat import AIMessage as DBAIMessage
from app.schemas.ai import ChatRequest, ChatResponse, ReplyHelperRequest, SoftenDraftRequest
from app.services import (
    ai_persona_service,
    ai_usage_service,
    alert_service,
    love_profile_service,
    sys_config_service,
)
from app.services.ai_config_service import (
    RuntimeAIConfig,
    resolve_fallback_configs,
    resolve_runtime_config,
    resolve_vision_config,
)
from app.services.ai_providers import (
    BaseProviderAdapter,
    get_provider_adapter,
    humanize_llm_error,
    is_fallback_eligible_error,
)
from app.services.emotion_guard import (
    build_reply_helper_prompt,
    build_soften_draft_prompt,
    evaluate_emotion_care,
    strip_emotion_care_for_client,
)

logger = logging.getLogger(__name__)

# 当 Redis / MySQL 未启动时，使用进程内内存字典降级保存多轮上下文与会话列表（仅开发调试）
_fallback_memory: dict[str, list[dict[str, str]]] = {}
_mem_conversations: dict[str, dict[str, Any]] = {}
_SESSION_TTL_SECONDS = 86400
_WEEKDAYS_ZH = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
_BEIJING_TZ = timezone(timedelta(hours=8))
_BEIJING_ALIASES = {"", "asia/shanghai", "asia/chongqing", "asia/harbin", "prc", "utc+8", "cst"}


def build_realtime_clock_prompt(tz_name: str | None = None) -> str:
    """构建服务端实时时间上下文，让模型可准确回答当前日期/星期/时间与跨时区换算。"""
    clean_tz = (tz_name or "").strip()
    tz: Any = _BEIJING_TZ
    tz_label = "北京时间 Asia/Shanghai, UTC+8"
    if clean_tz.lower() not in _BEIJING_ALIASES:
        try:
            tz = ZoneInfo(clean_tz)
            probe = datetime.now(tz)
            raw_off = probe.strftime("%z")
            off_fmt = f"UTC{raw_off[:3]}:{raw_off[3:]}" if len(raw_off) == 5 else ""
            tz_label = f"{clean_tz} ({off_fmt})" if off_fmt else clean_tz
        except Exception:
            tz = _BEIJING_TZ
            tz_label = "北京时间 Asia/Shanghai, UTC+8"

    now = datetime.now(tz)
    weekday = _WEEKDAYS_ZH[now.weekday()]
    return (
        "[实时系统时钟上下文 — 服务端实时注入，权威可信]\n"
        f"- 当前真实日期与时间：{now.strftime('%Y年%m月%d日')} {weekday} "
        f"{now.strftime('%H:%M:%S')}（{tz_label}）\n"
        f"- 标准 ISO 时间：{now.isoformat(timespec='seconds')}\n"
        "- 回复规则：当用户询问“今天几号、今天星期几、现在几点、今年是哪一年、明天/昨天/本周日期”"
        "或任何依赖当前时间的问题时，请直接依据上述实时系统时钟给出明确准确的回答，"
        "不要说无法获取实时日期或时间（即使上文历史记录曾如此回答，也以本条最新实时时钟为准）；"
        "若用户需要其他时区时间，请基于本时间直接换算。"
    )


def build_owner_scope(user_type: str, user_id: int) -> str:
    """会话归属作用域：不同账号的会话记忆互相隔离，防止通过 session_id 越权读取/清空他人上下文。"""
    return f"{(user_type or 'anon')[:16]}:{int(user_id or 0)}"


class LLMService:
    """基于 LangChain + 可扩展 Provider Adapter 的大模型对话引擎（首期内置 DeepSeek 双协议）。"""

    def _history_key(self, owner: str, session_id: str) -> str:
        return f"ailove:chat:history:{owner}:{session_id}"

    async def get_history(self, session_id: str, owner: str) -> list[dict[str, str]]:
        key = self._history_key(owner, session_id)
        cached = await cache_get_json(key)
        if isinstance(cached, list):
            return cached
        return list(_fallback_memory.get(key, []))

    async def save_history(
        self,
        session_id: str,
        history: list[dict[str, str]],
        owner: str,
        max_messages: int = 20,
    ) -> None:
        key = self._history_key(owner, session_id)
        trimmed = history[-max(2, max_messages) :]
        stored = await cache_set_json(key, trimmed, ttl_seconds=_SESSION_TTL_SECONDS)
        if not stored:
            _fallback_memory[key] = trimmed

    async def clear_history(self, session_id: str, owner: str) -> None:
        key = self._history_key(owner, session_id)
        _fallback_memory.pop(key, None)
        await cache_delete(key)

    def _build_messages(
        self,
        system_prompt: str,
        history: list[dict[str, str]],
        user_input: str,
        tz_name: str | None = None,
        *,
        inject_clock: bool = True,
        extra_system_blocks: list[str] | None = None,
        images: list[str] | None = None,
    ) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        blocks: list[str] = []
        base_prompt = system_prompt.strip()
        if base_prompt:
            blocks.append(base_prompt)
        for extra in extra_system_blocks or []:
            clean_extra = extra.strip()
            if clean_extra:
                blocks.append(clean_extra)
        if inject_clock:
            blocks.append(build_realtime_clock_prompt(tz_name))
        full_system = "\n\n".join(blocks)
        if full_system:
            messages.append(SystemMessage(content=full_system))
        for item in history:
            role = item.get("role")
            content = item.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        if images:
            content_parts: list[dict[str, Any]] = [{"type": "text", "text": user_input}]
            for img_url in images:
                content_parts.append({"type": "image_url", "image_url": {"url": img_url}})
            messages.append(HumanMessage(content=content_parts))
        else:
            messages.append(HumanMessage(content=user_input))
        return messages

    def _build_mock_reply(self, cfg: RuntimeAIConfig, user_message: str, image_count: int = 0) -> str:
        img_note = f"（含 {image_count} 张微信聊天截图预览）" if image_count > 0 else ""
        return (
            f"【{cfg.name} · 演示回复】已收到你的消息{img_note}：「{user_message}」。\n"
            f"当前模型配置（{cfg.provider} / {cfg.model_name}）尚未填写 API Key，系统自动以演示模式响应。\n"
            "请登录管理后台 →「AI 模型配置」填入 DeepSeek API Key 并测试连通后，"
            "即可实时切换至真实大模型（无需重启服务）。"
        )

    async def _persist_turn(
        self,
        *,
        session_id: str,
        user_type: str,
        user_id: int,
        model_name: str,
        user_content: str,
        assistant_content: str,
        token_usage: int = 0,
        persona_id: int | None = None,
        persona_name: str = "",
    ) -> None:
        """将会话与问答消息持久化到 MySQL（MySQL 不可用时降级保存至内存会话仓库）。"""
        now = datetime.now(UTC).replace(tzinfo=None)
        utype = (user_type or "web")[:16]
        uid = int(user_id or 0)
        clean_pname = (persona_name or "")[:64]
        try:
            factory = get_session_factory()
            async with factory() as session:
                conv = (
                    await session.execute(
                        select(AIConversation).where(AIConversation.session_id == session_id)
                    )
                ).scalar_one_or_none()
                if conv is None:
                    conv = AIConversation(
                        session_id=session_id,
                        user_type=utype,
                        user_id=uid,
                        title=user_content.strip().replace("\n", " ")[:60] or "新对话",
                        model_name=model_name[:64],
                        persona_id=persona_id,
                        persona_name=clean_pname,
                        is_pinned=False,
                    )
                    session.add(conv)
                    await session.flush()
                elif conv.user_id != uid or conv.user_type != utype:
                    return
                else:
                    conv.model_name = model_name[:64]
                    conv.persona_id = persona_id
                    conv.persona_name = clean_pname
                    conv.updated_at = now

                session.add(
                    DBAIMessage(
                        conversation_id=conv.id,
                        role="user",
                        content=user_content,
                        token_usage=0,
                    )
                )
                session.add(
                    DBAIMessage(
                        conversation_id=conv.id,
                        role="assistant",
                        content=assistant_content,
                        token_usage=token_usage,
                    )
                )
                await session.commit()
        except (SQLAlchemyError, OSError) as exc:
            logger.debug("AI chat DB persistence fallback to mem: %s", exc)
            mem_key = f"{build_owner_scope(utype, uid)}:{session_id}"
            now_iso = datetime.now(UTC).isoformat()
            rec = _mem_conversations.get(mem_key)
            if rec is None:
                rec = {
                    "session_id": session_id,
                    "user_type": utype,
                    "user_id": uid,
                    "title": user_content.strip().replace("\n", " ")[:60] or "新对话",
                    "model_name": model_name[:64],
                    "persona_id": persona_id,
                    "persona_name": clean_pname,
                    "is_pinned": False,
                    "messages": [],
                    "created_at": now_iso,
                    "updated_at": now_iso,
                }
                _mem_conversations[mem_key] = rec
            else:
                rec["model_name"] = model_name[:64]
                rec["persona_id"] = persona_id
                rec["persona_name"] = clean_pname
                rec["updated_at"] = now_iso
            rec["messages"].append(
                {
                    "role": "user",
                    "content": user_content,
                    "token_usage": 0,
                    "created_at": now_iso,
                }
            )
            rec["messages"].append(
                {
                    "role": "assistant",
                    "content": assistant_content,
                    "token_usage": token_usage,
                    "created_at": now_iso,
                }
            )

    async def list_conversations(
        self, user_type: str, user_id: int, limit: int = 30
    ) -> list[dict[str, Any]]:
        """列出当前用户本人的 AI 历史会话（置顶优先，其次按最近活跃倒序）。"""
        utype = (user_type or "web")[:16]
        uid = int(user_id or 0)
        try:
            factory = get_session_factory()
            async with factory() as session:
                stmt = (
                    select(AIConversation)
                    .where(
                        AIConversation.user_type == utype,
                        AIConversation.user_id == uid,
                    )
                    .order_by(
                        desc(AIConversation.is_pinned),
                        desc(AIConversation.updated_at),
                        desc(AIConversation.id),
                    )
                    .limit(limit)
                )
                rows = (await session.execute(stmt)).scalars().all()
                return [
                    {
                        "session_id": r.session_id,
                        "title": r.title,
                        "model_name": r.model_name,
                        "persona_id": r.persona_id,
                        "persona_name": r.persona_name or "",
                        "is_pinned": bool(r.is_pinned),
                        "created_at": r.created_at.isoformat() if r.created_at else "",
                        "updated_at": r.updated_at.isoformat() if r.updated_at else "",
                    }
                    for r in rows
                ]
        except (SQLAlchemyError, OSError):
            items = [
                {
                    "session_id": rec["session_id"],
                    "title": rec["title"],
                    "model_name": rec["model_name"],
                    "persona_id": rec.get("persona_id"),
                    "persona_name": rec.get("persona_name", ""),
                    "is_pinned": bool(rec.get("is_pinned", False)),
                    "created_at": rec["created_at"],
                    "updated_at": rec["updated_at"],
                }
                for rec in _mem_conversations.values()
                if rec["user_type"] == utype and rec["user_id"] == uid
            ]
            items.sort(key=lambda x: (x["is_pinned"], x["updated_at"]), reverse=True)
            return items[:limit]

    async def get_conversation_messages(
        self, session_id: str, user_type: str, user_id: int
    ) -> dict[str, Any] | None:
        """获取指定会话全部消息，并自动预热 Redis 短期多轮上下文缓存。"""
        utype = (user_type or "web")[:16]
        uid = int(user_id or 0)
        owner = build_owner_scope(utype, uid)
        try:
            factory = get_session_factory()
            async with factory() as session:
                conv = (
                    await session.execute(
                        select(AIConversation).where(
                            AIConversation.session_id == session_id,
                            AIConversation.user_type == utype,
                            AIConversation.user_id == uid,
                        )
                    )
                ).scalar_one_or_none()
                if conv is None:
                    return None
                msgs = (
                    await session.execute(
                        select(DBAIMessage)
                        .where(DBAIMessage.conversation_id == conv.id)
                        .order_by(DBAIMessage.id.asc())
                    )
                ).scalars().all()
                msg_list = [
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content,
                        "token_usage": m.token_usage,
                        "created_at": m.created_at.isoformat() if m.created_at else "",
                    }
                    for m in msgs
                ]
                await self.save_history(
                    session_id,
                    [{"role": m.role, "content": m.content} for m in msgs[-20:]],
                    owner,
                )
                return {
                    "session_id": conv.session_id,
                    "title": conv.title,
                    "model_name": conv.model_name,
                    "persona_id": conv.persona_id,
                    "persona_name": conv.persona_name or "",
                    "is_pinned": bool(conv.is_pinned),
                    "messages": msg_list,
                }
        except (SQLAlchemyError, OSError):
            mem_key = f"{owner}:{session_id}"
            rec = _mem_conversations.get(mem_key)
            if rec is None:
                return None
            msgs = rec["messages"]
            await self.save_history(
                session_id,
                [{"role": m["role"], "content": m["content"]} for m in msgs[-20:]],
                owner,
            )
            return {
                "session_id": rec["session_id"],
                "title": rec["title"],
                "model_name": rec["model_name"],
                "persona_id": rec.get("persona_id"),
                "persona_name": rec.get("persona_name", ""),
                "is_pinned": bool(rec.get("is_pinned", False)),
                "messages": list(msgs),
            }

    async def update_conversation(
        self,
        session_id: str,
        user_type: str,
        user_id: int,
        *,
        title: str | None = None,
        is_pinned: bool | None = None,
        persona_id: int | None = None,
        clear_persona: bool = False,
    ) -> dict[str, Any] | None:
        """更新会话标题、置顶状态或绑定智能体。"""
        utype = (user_type or "web")[:16]
        uid = int(user_id or 0)
        clean_title = title.strip()[:120] if title is not None else None
        resolved_persona_name: str | None = None
        if clear_persona:
            persona_id = None
            resolved_persona_name = ""
        elif persona_id is not None:
            persona = await ai_persona_service.get_persona(persona_id, require_enabled=False)
            persona_id = int(persona["id"])
            resolved_persona_name = str(persona["name"])[:64]

        try:
            factory = get_session_factory()
            async with factory() as session:
                conv = (
                    await session.execute(
                        select(AIConversation).where(
                            AIConversation.session_id == session_id,
                            AIConversation.user_type == utype,
                            AIConversation.user_id == uid,
                        )
                    )
                ).scalar_one_or_none()
                if conv is None:
                    return None
                if clean_title is not None:
                    conv.title = clean_title or "新对话"
                if is_pinned is not None:
                    conv.is_pinned = bool(is_pinned)
                if clear_persona or persona_id is not None:
                    conv.persona_id = persona_id
                    conv.persona_name = resolved_persona_name or ""
                await session.commit()
                return {
                    "session_id": conv.session_id,
                    "title": conv.title,
                    "model_name": conv.model_name,
                    "persona_id": conv.persona_id,
                    "persona_name": conv.persona_name or "",
                    "is_pinned": bool(conv.is_pinned),
                }
        except (SQLAlchemyError, OSError):
            mem_key = f"{build_owner_scope(utype, uid)}:{session_id}"
            rec = _mem_conversations.get(mem_key)
            if rec is None:
                return None
            if clean_title is not None:
                rec["title"] = clean_title or "新对话"
            if is_pinned is not None:
                rec["is_pinned"] = bool(is_pinned)
            if clear_persona or persona_id is not None:
                rec["persona_id"] = persona_id
                rec["persona_name"] = resolved_persona_name or ""
            return {
                "session_id": rec["session_id"],
                "title": rec["title"],
                "model_name": rec["model_name"],
                "persona_id": rec.get("persona_id"),
                "persona_name": rec.get("persona_name", ""),
                "is_pinned": bool(rec.get("is_pinned", False)),
            }

    async def rename_conversation(
        self, session_id: str, user_type: str, user_id: int, title: str
    ) -> dict[str, Any] | None:
        return await self.update_conversation(session_id, user_type, user_id, title=title)

    async def delete_conversation(
        self, session_id: str, user_type: str, user_id: int
    ) -> bool:
        utype = (user_type or "web")[:16]
        uid = int(user_id or 0)
        owner = build_owner_scope(utype, uid)
        deleted = False
        try:
            factory = get_session_factory()
            async with factory() as session:
                conv = (
                    await session.execute(
                        select(AIConversation).where(
                            AIConversation.session_id == session_id,
                            AIConversation.user_type == utype,
                            AIConversation.user_id == uid,
                        )
                    )
                ).scalar_one_or_none()
                if conv is None:
                    return False
                await session.delete(conv)
                await session.commit()
                deleted = True
        except (SQLAlchemyError, OSError):
            mem_key = f"{owner}:{session_id}"
            deleted = _mem_conversations.pop(mem_key, None) is not None

        await self.clear_history(session_id, owner)
        return deleted

    async def purge_all_user_conversations(self, user_type: str, user_id: int) -> int:
        """彻底清空指定用户的全部历史会话记录与 Redis 上下文缓存（数据主权一键销毁）。"""
        utype = (user_type or "web")[:16]
        uid = int(user_id or 0)
        owner = build_owner_scope(utype, uid)
        convs = await self.list_conversations(utype, uid, limit=500)
        session_ids = [c["session_id"] for c in convs if c.get("session_id")]
        removed = 0
        try:
            factory = get_session_factory()
            async with factory() as session:
                res = await session.execute(
                    delete(AIConversation).where(
                        AIConversation.user_type == utype,
                        AIConversation.user_id == uid,
                    )
                )
                await session.commit()
                removed = int(res.rowcount or 0)
        except (SQLAlchemyError, OSError):
            pass

        prefix = f"{owner}:"
        for k in [key for key in _mem_conversations if key.startswith(prefix)]:
            _mem_conversations.pop(k, None)
            removed += 1

        for sid in session_ids:
            await self.clear_history(sid, owner)
        return max(removed, len(session_ids))

    async def export_user_journal_markdown(self, user_type: str, user_id: int) -> dict[str, Any]:
        """将当前用户的情感档案、收藏话术与历史对话导出为整洁可读的私密 Markdown 手账。"""
        from app.services import favorite_reply_service  # noqa: PLC0415

        utype = (user_type or "web")[:16]
        uid = int(user_id or 0)
        profile = await love_profile_service.get_love_profile(utype, uid)
        favorites = await favorite_reply_service.list_favorites(utype, uid, limit=200)
        convs = await self.list_conversations(utype, uid, limit=200)

        lines: list[str] = [
            "# AILOVE 我的私密情感手账",
            "",
            f"> 导出时间：{datetime.now(_BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')} (北京时间)",
            "",
            "---",
            "",
            "## 一、个人情感背景档案",
            "",
        ]
        if profile.get("is_configured"):
            if profile.get("relationship_stage_label"):
                lines.append(f"- **当前阶段**：{profile['relationship_stage_label']}")
            if profile.get("partner_nickname"):
                lines.append(f"- **对方称呼**：{profile['partner_nickname']}")
            if profile.get("partner_traits"):
                lines.append(f"- **对方特点**：{'、'.join(profile['partner_traits'])}")
            if profile.get("my_traits"):
                lines.append(f"- **我的特点**：{'、'.join(profile['my_traits'])}")
            if profile.get("relationship_goal"):
                lines.append(f"- **核心诉求**：{profile['relationship_goal']}")
            if profile.get("communication_taboos"):
                lines.append(f"- **沟通雷区**：{profile['communication_taboos']}")
            if profile.get("background_notes"):
                lines.append(f"- **背景补充**：{profile['background_notes']}")
        else:
            lines.append("_暂未填写个人情感背景记忆卡_")

        lines.extend(["", "---", "", f"## 二、高情商话术收藏夹（共 {len(favorites)} 条）", ""])
        if favorites:
            for idx, fav in enumerate(favorites, 1):
                tag = fav.get("scene_label") or fav.get("category") or "收藏"
                lines.append(f"{idx}. **[{tag}]** {fav['content']}")
                if fav.get("note"):
                    lines.append(f"   - 备注：{fav['note']}")
        else:
            lines.append("_暂无收藏话术_")

        lines.extend(["", "---", "", f"## 三、情感咨询历史手账（共 {len(convs)} 个会话）", ""])
        if convs:
            for conv in convs:
                detail = await self.get_conversation_messages(conv["session_id"], utype, uid)
                if not detail:
                    continue
                pin_flag = "📌 " if detail.get("is_pinned") else ""
                pname = f" · {detail['persona_name']}" if detail.get("persona_name") else ""
                lines.append(f"### {pin_flag}{detail['title']}{pname}")
                lines.append("")
                for msg in detail.get("messages", []):
                    role_label = "🗣️ **我**" if msg["role"] == "user" else "💘 **AI 导师**"
                    lines.append(f"{role_label}：")
                    lines.append("")
                    lines.append(str(msg.get("content", "")))
                    lines.append("")
                lines.append("---")
                lines.append("")
        else:
            lines.append("_暂无保存的云端历史会话（无痕模式对话不会出现在此导出中）_")

        ts_name = datetime.now(_BEIJING_TZ).strftime("%Y%m%d_%H%M")
        return {
            "filename": f"ailove_journal_{ts_name}.md",
            "markdown": "\n".join(lines),
            "stats": {
                "has_love_profile": bool(profile.get("is_configured")),
                "favorite_count": len(favorites),
                "conversation_count": len(convs),
            },
        }

    def _extract_token_breakdown(self, msg: Any) -> tuple[int, int, int]:
        usage = getattr(msg, "usage_metadata", None)
        if isinstance(usage, dict):
            prompt_tok = int(usage.get("input_tokens", 0) or 0)
            comp_tok = int(usage.get("output_tokens", 0) or 0)
            total_tok = int(usage.get("total_tokens", 0) or 0)
            return prompt_tok, comp_tok, total_tok or (prompt_tok + comp_tok)
        resp_meta = getattr(msg, "response_metadata", None)
        if isinstance(resp_meta, dict):
            tok = resp_meta.get("token_usage")
            if isinstance(tok, dict):
                prompt_tok = int(tok.get("prompt_tokens", 0) or 0)
                comp_tok = int(tok.get("completion_tokens", 0) or 0)
                total_tok = int(tok.get("total_tokens", 0) or 0)
                return prompt_tok, comp_tok, total_tok or (prompt_tok + comp_tok)
        return 0, 0, 0

    def _extract_token_usage(self, msg: Any) -> int:
        return self._extract_token_breakdown(msg)[2]

    def _build_llm(
        self, cfg: RuntimeAIConfig, temperature: float, *, streaming: bool
    ) -> tuple[BaseProviderAdapter, Any]:
        adapter = get_provider_adapter(cfg.provider)
        if adapter is None:
            raise BusinessException(
                f"暂不支持的 AI 提供商：{cfg.provider}", code=40040, status_code=400
            )
        llm = adapter.build_chat_model(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            model_name=cfg.model_name,
            temperature=temperature,
            top_p=cfg.top_p,
            max_tokens=cfg.max_tokens,
            timeout_seconds=cfg.timeout_seconds,
            streaming=streaming,
            extra_params=cfg.extra_params,
        )
        return adapter, llm

    def _wrap_llm_error(self, exc: Exception, cfg: RuntimeAIConfig, t0: float) -> BusinessException:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        logger.warning(
            "LLM invocation failed (provider=%s model=%s): %s", cfg.provider, cfg.model_name, exc
        )
        friendly = humanize_llm_error(
            exc, model_name=cfg.model_name, base_url=cfg.base_url, latency_ms=latency_ms
        )
        return BusinessException(friendly, code=50201, status_code=502)

    async def _resolve_ai_runtime_policies(
        self, message: str, req_timezone: str | None
    ) -> tuple[bool, str]:
        max_len = await sys_config_service.get_int("ai.max_message_length", default=4000)
        if len(message) > max_len:
            raise BusinessException(
                f"单条提问内容不能超过 {max_len} 字符（当前 {len(message)} 字符）",
                code=40051,
            )
        inject_clock = await sys_config_service.get_bool("ai.inject_realtime_clock", default=True)
        default_tz = await sys_config_service.get_str("ai.default_timezone", default="Asia/Shanghai")
        effective_tz = (req_timezone or "").strip() or default_tz
        return inject_clock, effective_tz

    async def _resolve_persona_and_quota(
        self,
        req: ChatRequest,
        *,
        owner: str,
        role: str,
        cfg: RuntimeAIConfig,
    ) -> tuple[int | None, str, str, float]:
        await ai_usage_service.check_daily_quota(owner, role)

        persona_id: int | None = None
        persona_name = ""
        system_prompt = cfg.system_prompt
        temperature = cfg.temperature

        if req.persona_id is not None:
            persona = await ai_persona_service.get_persona(req.persona_id, require_enabled=True)
            persona_id = int(persona["id"])
            persona_name = str(persona["name"])
            if persona.get("system_prompt"):
                system_prompt = str(persona["system_prompt"])
            if persona.get("temperature") is not None:
                temperature = float(persona["temperature"])

        if req.system_prompt:
            system_prompt = req.system_prompt
        if req.temperature is not None:
            temperature = req.temperature

        return persona_id, persona_name, system_prompt, temperature

    async def _prepare_love_and_safety_context(
        self,
        req: ChatRequest,
        *,
        user_type: str,
        user_id: int,
        extra_system_instruction: str = "",
    ) -> tuple[bool, dict[str, Any] | None, list[str]]:
        """组装用户情感档案上下文、帮我回消息格式规范与情绪安全关怀护栏。"""
        extra_blocks: list[str] = []
        love_profile_injected = False

        profile = await love_profile_service.get_love_profile(user_type, user_id)
        should_inject = bool(profile.get("is_configured")) and (
            req.use_love_profile
            if req.use_love_profile is not None
            else bool(profile.get("auto_inject", True))
        )
        if should_inject:
            profile_prompt = love_profile_service.build_love_profile_prompt(profile)
            if profile_prompt:
                extra_blocks.append(profile_prompt)
                love_profile_injected = True

        if extra_system_instruction.strip():
            extra_blocks.append(extra_system_instruction.strip())

        care = evaluate_emotion_care(req.message)
        if care and care.get("prompt_guidance"):
            extra_blocks.append(str(care["prompt_guidance"]))

        return love_profile_injected, strip_emotion_care_for_client(care), extra_blocks

    async def _resolve_vision_runtime_config(
        self, cfg: RuntimeAIConfig, config_id: int | None
    ) -> RuntimeAIConfig:
        """若请求携带聊天截图且主模型已配置 API Key，确保切换至支持多模态识图的模型。"""
        if not cfg.is_configured:
            return cfg
        adapter = get_provider_adapter(cfg.provider)
        if adapter is not None and adapter.supports_vision_model(cfg.model_name):
            return cfg
        vision_cfg = await resolve_vision_config(config_id=config_id)
        if vision_cfg is None:
            raise BusinessException(
                "当前主模型不支持识图且未找到启用中的视觉模型，请在「AI 模型配置」启用 "
                "DeepSeek Flash (deepseek-flash) 或通义千问 VL / 豆包 Vision 后重试",
                code=40055,
                status_code=400,
            )
        return vision_cfg

    async def build_reply_helper_chat_request(
        self, req: ReplyHelperRequest
    ) -> tuple[ChatRequest, str, list[str]]:
        """将「帮我回消息 2.0（含截图识图）」结构化请求转换为标准 ChatRequest + 指令 + 图片列表。"""
        user_message, extra_instruction = build_reply_helper_prompt(
            partner_message=req.partner_message,
            scene=req.scene,
            tone=req.tone,
            context=req.context,
            my_intent=req.my_intent,
            image_count=len(req.images),
        )
        persona_id = req.persona_id
        if persona_id is None:
            enabled_personas = await ai_persona_service.list_personas(enabled_only=True)
            for item in enabled_personas:
                if item.get("code") == "love_chat_coach":
                    persona_id = int(item["id"])
                    break

        chat_req = ChatRequest(
            message=user_message,
            session_id=req.session_id,
            config_id=req.config_id,
            persona_id=persona_id,
            timezone=req.timezone,
            use_love_profile=req.use_love_profile,
            incognito=req.incognito,
        )
        return chat_req, extra_instruction, list(req.images)

    async def build_soften_draft_chat_request(
        self, req: SoftenDraftRequest
    ) -> tuple[ChatRequest, str]:
        """将「先别发！情绪降温与话术柔化」请求转换为标准 ChatRequest + 格式指令。"""
        user_message, extra_instruction = build_soften_draft_prompt(
            draft_message=req.draft_message,
            context=req.context,
            intensity=req.intensity,
        )
        persona_id = req.persona_id
        if persona_id is None:
            enabled_personas = await ai_persona_service.list_personas(enabled_only=True)
            for item in enabled_personas:
                if item.get("code") in {"conflict_mediator", "love_conflict_mediator"}:
                    persona_id = int(item["id"])
                    break

        chat_req = ChatRequest(
            message=user_message,
            session_id=req.session_id,
            config_id=req.config_id,
            persona_id=persona_id,
            timezone=req.timezone,
            use_love_profile=req.use_love_profile,
            incognito=req.incognito,
        )
        return chat_req, extra_instruction

    async def chat(
        self,
        req: ChatRequest,
        *,
        user_type: str = "web",
        user_id: int = 0,
        username: str = "",
        role: str = "user",
        extra_system_instruction: str = "",
        images: list[str] | None = None,
    ) -> ChatResponse:
        inject_clock, effective_tz = await self._resolve_ai_runtime_policies(
            req.message, req.timezone
        )
        cfg = await resolve_runtime_config(config_id=req.config_id)
        if images:
            cfg = await self._resolve_vision_runtime_config(cfg, req.config_id)
        owner = build_owner_scope(user_type, user_id)
        persona_id, persona_name, system_prompt, temperature = (
            await self._resolve_persona_and_quota(req, owner=owner, role=role, cfg=cfg)
        )
        love_profile_injected, emotion_care, extra_blocks = (
            await self._prepare_love_and_safety_context(
                req,
                user_type=user_type,
                user_id=user_id,
                extra_system_instruction=extra_system_instruction,
            )
        )
        is_incognito = bool(req.incognito)
        if is_incognito:
            session_id = (req.session_id or "").strip() or f"incognito_{uuid.uuid4().hex[:12]}"
            history = [
                {"role": m.role, "content": m.content}
                for m in req.ephemeral_history[-12:]
                if m.role in {"user", "assistant"} and m.content
            ]
        else:
            session_id = req.session_id or uuid.uuid4().hex
            history = await self.get_history(session_id, owner)

        is_mock = not cfg.is_configured
        active_cfg = cfg
        fallback_used = False
        fallback_from = ""
        reasoning = ""
        prompt_tokens = 0
        completion_tokens = 0
        token_usage = 0
        t0 = time.perf_counter()

        if is_mock:
            reply = self._build_mock_reply(cfg, req.message, image_count=len(images or []))
        else:
            adapter, llm = self._build_llm(cfg, temperature, streaming=False)
            messages = self._build_messages(
                system_prompt,
                history,
                req.message,
                tz_name=effective_tz,
                inject_clock=inject_clock,
                extra_system_blocks=extra_blocks,
                images=images,
            )
            ai_msg: Any = None
            try:
                ai_msg = await llm.ainvoke(messages)
            except Exception as primary_exc:
                primary_latency = max(1, int((time.perf_counter() - t0) * 1000))
                primary_friendly = humanize_llm_error(
                    primary_exc,
                    model_name=cfg.model_name,
                    base_url=cfg.base_url,
                    latency_ms=primary_latency,
                )
                await ai_usage_service.record_usage(
                    owner_scope=owner,
                    user_type=user_type,
                    user_id=user_id,
                    username=username,
                    session_id=session_id,
                    persona_id=persona_id,
                    persona_name=persona_name,
                    provider=cfg.provider,
                    model_name=cfg.model_name,
                    latency_ms=primary_latency,
                    is_stream=False,
                    is_mock=False,
                    call_status="failed",
                )

                auto_fb = await sys_config_service.get_bool("ai.auto_fallback_enabled", default=True)
                if auto_fb and is_fallback_eligible_error(primary_exc):
                    backups = await resolve_fallback_configs(exclude_id=cfg.id)
                    if images:
                        backups = [
                            b
                            for b in backups
                            if (ad := get_provider_adapter(b.provider)) is not None
                            and ad.supports_vision_model(b.model_name)
                        ]
                    for fb_cfg in backups:
                        try:
                            fb_adapter, fb_llm = self._build_llm(
                                fb_cfg, temperature, streaming=False
                            )
                            ai_msg = await fb_llm.ainvoke(messages)
                            adapter = fb_adapter
                            active_cfg = fb_cfg
                            fallback_used = True
                            fallback_from = f"{cfg.name} ({cfg.model_name})"
                            logger.warning(
                                "AI auto-fallback succeeded: %s/%s -> %s/%s",
                                cfg.provider,
                                cfg.model_name,
                                fb_cfg.provider,
                                fb_cfg.model_name,
                            )
                            alert_service.schedule_llm_alert(
                                provider=cfg.provider,
                                model_name=cfg.model_name,
                                config_name=cfg.name,
                                error_summary=primary_friendly,
                                fallback_to=f"{fb_cfg.name} ({fb_cfg.model_name})",
                            )
                            break
                        except Exception as fb_exc:
                            logger.warning(
                                "Fallback candidate %s/%s failed: %s",
                                fb_cfg.provider,
                                fb_cfg.model_name,
                                fb_exc,
                            )

                if ai_msg is None:
                    alert_service.schedule_llm_alert(
                        provider=cfg.provider,
                        model_name=cfg.model_name,
                        config_name=cfg.name,
                        error_summary=primary_friendly,
                    )
                    raise self._wrap_llm_error(primary_exc, cfg, t0) from primary_exc

            reasoning, reply = adapter.extract_chunk_deltas(ai_msg)
            prompt_tokens, completion_tokens, token_usage = self._extract_token_breakdown(ai_msg)

        latency_ms = max(1, int((time.perf_counter() - t0) * 1000))
        if not is_incognito:
            history.append({"role": "user", "content": req.message})
            history.append({"role": "assistant", "content": reply})
            await self.save_history(
                session_id, history, owner, max_messages=active_cfg.max_history_messages
            )
            await self._persist_turn(
                session_id=session_id,
                user_type=user_type,
                user_id=user_id,
                model_name=active_cfg.model_name,
                user_content=req.message,
                assistant_content=reply,
                token_usage=token_usage,
                persona_id=persona_id,
                persona_name=persona_name,
            )
        if persona_id is not None:
            await ai_persona_service.increment_persona_usage(persona_id)
        await ai_usage_service.record_usage(
            owner_scope=owner,
            user_type=user_type,
            user_id=user_id,
            username=username,
            session_id=session_id,
            persona_id=persona_id,
            persona_name=persona_name,
            provider=active_cfg.provider,
            model_name=active_cfg.model_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=token_usage,
            latency_ms=latency_ms,
            is_stream=False,
            is_mock=is_mock,
            call_status="success",
        )

        return ChatResponse(
            session_id=session_id,
            reply=reply,
            reasoning=reasoning,
            model=active_cfg.model_name,
            provider=active_cfg.provider,
            protocol=active_cfg.protocol,
            config_id=active_cfg.id,
            config_name=active_cfg.name,
            persona_id=persona_id,
            persona_name=persona_name,
            is_mock=is_mock,
            incognito=is_incognito,
            history_length=len(history),
            token_usage=token_usage,
            love_profile_injected=love_profile_injected,
            emotion_care=emotion_care,
            fallback_used=fallback_used,
            fallback_from=fallback_from,
        )

    async def stream_chat(
        self,
        req: ChatRequest,
        *,
        user_type: str = "web",
        user_id: int = 0,
        username: str = "",
        role: str = "user",
        extra_system_instruction: str = "",
        images: list[str] | None = None,
    ) -> tuple[str, RuntimeAIConfig, dict[str, Any], AsyncGenerator[tuple[str, str], None]]:
        """流式对话生成器，逐块产出 (event_type: 'reasoning' | 'delta' | 'usage', text_chunk)。"""
        inject_clock, effective_tz = await self._resolve_ai_runtime_policies(
            req.message, req.timezone
        )
        cfg = await resolve_runtime_config(config_id=req.config_id)
        if images:
            cfg = await self._resolve_vision_runtime_config(cfg, req.config_id)
        owner = build_owner_scope(user_type, user_id)
        persona_id, persona_name, system_prompt, temperature = (
            await self._resolve_persona_and_quota(req, owner=owner, role=role, cfg=cfg)
        )
        love_profile_injected, emotion_care, extra_blocks = (
            await self._prepare_love_and_safety_context(
                req,
                user_type=user_type,
                user_id=user_id,
                extra_system_instruction=extra_system_instruction,
            )
        )
        is_incognito = bool(req.incognito)
        if is_incognito:
            session_id = (req.session_id or "").strip() or f"incognito_{uuid.uuid4().hex[:12]}"
            history = [
                {"role": m.role, "content": m.content}
                for m in req.ephemeral_history[-12:]
                if m.role in {"user", "assistant"} and m.content
            ]
        else:
            session_id = req.session_id or uuid.uuid4().hex
            history = await self.get_history(session_id, owner)

        async def _generator() -> AsyncGenerator[tuple[str, str], None]:
            collected: list[str] = []
            prompt_tokens = 0
            completion_tokens = 0
            token_usage = 0
            active_cfg = cfg
            t0 = time.perf_counter()
            if not cfg.is_configured:
                mock_text = self._build_mock_reply(cfg, req.message, image_count=len(images or []))
                chunk_size = 8
                for i in range(0, len(mock_text), chunk_size):
                    piece = mock_text[i : i + chunk_size]
                    collected.append(piece)
                    yield "delta", piece
                    await asyncio.sleep(0.025)
            else:
                adapter, llm = self._build_llm(cfg, temperature, streaming=True)
                messages = self._build_messages(
                    system_prompt,
                    history,
                    req.message,
                    tz_name=effective_tz,
                    inject_clock=inject_clock,
                    extra_system_blocks=extra_blocks,
                    images=images,
                )
                emitted_any = False
                try:
                    async for chunk in llm.astream(messages):
                        reasoning_piece, content_piece = adapter.extract_chunk_deltas(chunk)
                        if reasoning_piece:
                            emitted_any = True
                            yield "reasoning", reasoning_piece
                        if content_piece:
                            emitted_any = True
                            collected.append(content_piece)
                            yield "delta", content_piece
                        p_tok, c_tok, t_tok = self._extract_token_breakdown(chunk)
                        prompt_tokens += p_tok
                        completion_tokens += c_tok
                        token_usage += t_tok
                except Exception as primary_exc:
                    primary_latency = max(1, int((time.perf_counter() - t0) * 1000))
                    primary_friendly = humanize_llm_error(
                        primary_exc,
                        model_name=cfg.model_name,
                        base_url=cfg.base_url,
                        latency_ms=primary_latency,
                    )
                    await ai_usage_service.record_usage(
                        owner_scope=owner,
                        user_type=user_type,
                        user_id=user_id,
                        username=username,
                        session_id=session_id,
                        persona_id=persona_id,
                        persona_name=persona_name,
                        provider=cfg.provider,
                        model_name=cfg.model_name,
                        latency_ms=primary_latency,
                        is_stream=True,
                        is_mock=False,
                        call_status="failed",
                    )

                    recovered = False
                    auto_fb = await sys_config_service.get_bool(
                        "ai.auto_fallback_enabled", default=True
                    )
                    if not emitted_any and auto_fb and is_fallback_eligible_error(primary_exc):
                        backups = await resolve_fallback_configs(exclude_id=cfg.id)
                        if images:
                            backups = [
                                b
                                for b in backups
                                if (ad := get_provider_adapter(b.provider)) is not None
                                and ad.supports_vision_model(b.model_name)
                            ]
                        for fb_cfg in backups:
                            fb_emitted = False
                            prompt_tokens = 0
                            completion_tokens = 0
                            token_usage = 0
                            try:
                                fb_adapter, fb_llm = self._build_llm(
                                    fb_cfg, temperature, streaming=True
                                )
                                async for chunk in fb_llm.astream(messages):
                                    r_piece, c_piece = fb_adapter.extract_chunk_deltas(chunk)
                                    if (r_piece or c_piece) and not fb_emitted:
                                        fb_emitted = True
                                        active_cfg = fb_cfg
                                        yield (
                                            "fallback",
                                            f"{fb_cfg.name} ({fb_cfg.model_name})",
                                        )
                                        alert_service.schedule_llm_alert(
                                            provider=cfg.provider,
                                            model_name=cfg.model_name,
                                            config_name=cfg.name,
                                            error_summary=primary_friendly,
                                            fallback_to=f"{fb_cfg.name} ({fb_cfg.model_name})",
                                        )
                                    if r_piece:
                                        yield "reasoning", r_piece
                                    if c_piece:
                                        collected.append(c_piece)
                                        yield "delta", c_piece
                                    p_tok, c_tok, t_tok = self._extract_token_breakdown(chunk)
                                    prompt_tokens += p_tok
                                    completion_tokens += c_tok
                                    token_usage += t_tok
                                if fb_emitted or collected:
                                    recovered = True
                                    break
                            except Exception as fb_exc:
                                logger.warning(
                                    "Stream fallback candidate %s/%s failed: %s",
                                    fb_cfg.provider,
                                    fb_cfg.model_name,
                                    fb_exc,
                                )
                                if fb_emitted:
                                    raise self._wrap_llm_error(fb_exc, fb_cfg, t0) from fb_exc

                    if not recovered:
                        alert_service.schedule_llm_alert(
                            provider=cfg.provider,
                            model_name=cfg.model_name,
                            config_name=cfg.name,
                            error_summary=primary_friendly,
                        )
                        raise self._wrap_llm_error(primary_exc, cfg, t0) from primary_exc
                if token_usage:
                    yield "usage", str(token_usage)

            latency_ms = max(1, int((time.perf_counter() - t0) * 1000))
            full_reply = "".join(collected)
            if not is_incognito:
                history.append({"role": "user", "content": req.message})
                history.append({"role": "assistant", "content": full_reply})
                await self.save_history(
                    session_id, history, owner, max_messages=active_cfg.max_history_messages
                )
                await self._persist_turn(
                    session_id=session_id,
                    user_type=user_type,
                    user_id=user_id,
                    model_name=active_cfg.model_name,
                    user_content=req.message,
                    assistant_content=full_reply,
                    token_usage=token_usage,
                    persona_id=persona_id,
                    persona_name=persona_name,
                )
            if persona_id is not None:
                await ai_persona_service.increment_persona_usage(persona_id)
            await ai_usage_service.record_usage(
                owner_scope=owner,
                user_type=user_type,
                user_id=user_id,
                username=username,
                session_id=session_id,
                persona_id=persona_id,
                persona_name=persona_name,
                provider=active_cfg.provider,
                model_name=active_cfg.model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=token_usage,
                latency_ms=latency_ms,
                is_stream=True,
                is_mock=not active_cfg.is_configured,
                call_status="success",
            )

        meta = {
            "persona_id": persona_id,
            "persona_name": persona_name,
            "love_profile_injected": love_profile_injected,
            "emotion_care": emotion_care,
            "incognito": is_incognito,
        }
        return session_id, cfg, meta, _generator()


llm_service = LLMService()
