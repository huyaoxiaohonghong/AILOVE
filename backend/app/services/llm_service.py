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
from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import BusinessException
from app.db.mysql import get_session_factory
from app.db.redis import cache_delete, cache_get_json, cache_set_json
from app.models.ai_chat import AIConversation
from app.models.ai_chat import AIMessage as DBAIMessage
from app.schemas.ai import ChatRequest, ChatResponse
from app.services import ai_persona_service, ai_usage_service, sys_config_service
from app.services.ai_config_service import RuntimeAIConfig, resolve_runtime_config
from app.services.ai_providers import (
    BaseProviderAdapter,
    get_provider_adapter,
    humanize_llm_error,
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
    ) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        base_prompt = system_prompt.strip()
        if inject_clock:
            clock_prompt = build_realtime_clock_prompt(tz_name)
            full_system = f"{base_prompt}\n\n{clock_prompt}" if base_prompt else clock_prompt
        else:
            full_system = base_prompt
        if full_system:
            messages.append(SystemMessage(content=full_system))
        for item in history:
            role = item.get("role")
            content = item.get("content", "")
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                messages.append(AIMessage(content=content))
        messages.append(HumanMessage(content=user_input))
        return messages

    def _build_mock_reply(self, cfg: RuntimeAIConfig, user_message: str) -> str:
        return (
            f"【{cfg.name} · 演示回复】已收到你的消息：「{user_message}」。\n"
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
    ) -> None:
        """将会话与问答消息持久化到 MySQL（MySQL 不可用时降级保存至内存会话仓库）。"""
        now = datetime.now(UTC).replace(tzinfo=None)
        utype = (user_type or "web")[:16]
        uid = int(user_id or 0)
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
                        title=user_content.strip()[:60] or "新对话",
                        model_name=model_name[:64],
                    )
                    session.add(conv)
                    await session.flush()
                elif conv.user_id != uid or conv.user_type != utype:
                    return
                else:
                    conv.model_name = model_name[:64]
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
                    "title": user_content.strip()[:60] or "新对话",
                    "model_name": model_name[:64],
                    "messages": [],
                    "created_at": now_iso,
                    "updated_at": now_iso,
                }
                _mem_conversations[mem_key] = rec
            else:
                rec["model_name"] = model_name[:64]
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
        """列出当前用户本人的 AI 历史会话（按最近活跃倒序）。"""
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
                    .order_by(desc(AIConversation.updated_at), desc(AIConversation.id))
                    .limit(limit)
                )
                rows = (await session.execute(stmt)).scalars().all()
                return [
                    {
                        "session_id": r.session_id,
                        "title": r.title,
                        "model_name": r.model_name,
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
                    "created_at": rec["created_at"],
                    "updated_at": rec["updated_at"],
                }
                for rec in _mem_conversations.values()
                if rec["user_type"] == utype and rec["user_id"] == uid
            ]
            items.sort(key=lambda x: x["updated_at"], reverse=True)
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
                "messages": list(msgs),
            }

    async def rename_conversation(
        self, session_id: str, user_type: str, user_id: int, title: str
    ) -> dict[str, Any] | None:
        utype = (user_type or "web")[:16]
        uid = int(user_id or 0)
        clean_title = title.strip()[:120] or "新对话"
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
                conv.title = clean_title
                await session.commit()
                return {
                    "session_id": conv.session_id,
                    "title": conv.title,
                    "model_name": conv.model_name,
                }
        except (SQLAlchemyError, OSError):
            mem_key = f"{build_owner_scope(utype, uid)}:{session_id}"
            rec = _mem_conversations.get(mem_key)
            if rec is None:
                return None
            rec["title"] = clean_title
            rec["updated_at"] = datetime.now(UTC).isoformat()
            return {
                "session_id": rec["session_id"],
                "title": rec["title"],
                "model_name": rec["model_name"],
            }

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

    async def chat(
        self,
        req: ChatRequest,
        *,
        user_type: str = "web",
        user_id: int = 0,
        username: str = "",
        role: str = "user",
    ) -> ChatResponse:
        inject_clock, effective_tz = await self._resolve_ai_runtime_policies(
            req.message, req.timezone
        )
        cfg = await resolve_runtime_config(config_id=req.config_id)
        owner = build_owner_scope(user_type, user_id)
        persona_id, persona_name, system_prompt, temperature = (
            await self._resolve_persona_and_quota(req, owner=owner, role=role, cfg=cfg)
        )
        session_id = req.session_id or uuid.uuid4().hex
        history = await self.get_history(session_id, owner)

        is_mock = not cfg.is_configured
        reasoning = ""
        prompt_tokens = 0
        completion_tokens = 0
        token_usage = 0
        t0 = time.perf_counter()

        if is_mock:
            reply = self._build_mock_reply(cfg, req.message)
        else:
            adapter, llm = self._build_llm(cfg, temperature, streaming=False)
            messages = self._build_messages(
                system_prompt,
                history,
                req.message,
                tz_name=effective_tz,
                inject_clock=inject_clock,
            )
            try:
                ai_msg = await llm.ainvoke(messages)
            except Exception as exc:
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
                    latency_ms=max(1, int((time.perf_counter() - t0) * 1000)),
                    is_stream=False,
                    is_mock=False,
                    call_status="failed",
                )
                raise self._wrap_llm_error(exc, cfg, t0) from exc
            reasoning, reply = adapter.extract_chunk_deltas(ai_msg)
            prompt_tokens, completion_tokens, token_usage = self._extract_token_breakdown(ai_msg)

        latency_ms = max(1, int((time.perf_counter() - t0) * 1000))
        history.append({"role": "user", "content": req.message})
        history.append({"role": "assistant", "content": reply})
        await self.save_history(session_id, history, owner, max_messages=cfg.max_history_messages)
        await self._persist_turn(
            session_id=session_id,
            user_type=user_type,
            user_id=user_id,
            model_name=cfg.model_name,
            user_content=req.message,
            assistant_content=reply,
            token_usage=token_usage,
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
            provider=cfg.provider,
            model_name=cfg.model_name,
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
            model=cfg.model_name,
            provider=cfg.provider,
            protocol=cfg.protocol,
            config_id=cfg.id,
            config_name=cfg.name,
            persona_id=persona_id,
            persona_name=persona_name,
            is_mock=is_mock,
            history_length=len(history),
            token_usage=token_usage,
        )

    async def stream_chat(
        self,
        req: ChatRequest,
        *,
        user_type: str = "web",
        user_id: int = 0,
        username: str = "",
        role: str = "user",
    ) -> tuple[str, RuntimeAIConfig, dict[str, Any], AsyncGenerator[tuple[str, str], None]]:
        """流式对话生成器，逐块产出 (event_type: 'reasoning' | 'delta' | 'usage', text_chunk)。"""
        inject_clock, effective_tz = await self._resolve_ai_runtime_policies(
            req.message, req.timezone
        )
        cfg = await resolve_runtime_config(config_id=req.config_id)
        owner = build_owner_scope(user_type, user_id)
        persona_id, persona_name, system_prompt, temperature = (
            await self._resolve_persona_and_quota(req, owner=owner, role=role, cfg=cfg)
        )
        session_id = req.session_id or uuid.uuid4().hex
        history = await self.get_history(session_id, owner)

        async def _generator() -> AsyncGenerator[tuple[str, str], None]:
            collected: list[str] = []
            prompt_tokens = 0
            completion_tokens = 0
            token_usage = 0
            t0 = time.perf_counter()
            if not cfg.is_configured:
                mock_text = self._build_mock_reply(cfg, req.message)
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
                )
                try:
                    async for chunk in llm.astream(messages):
                        reasoning_piece, content_piece = adapter.extract_chunk_deltas(chunk)
                        if reasoning_piece:
                            yield "reasoning", reasoning_piece
                        if content_piece:
                            collected.append(content_piece)
                            yield "delta", content_piece
                        p_tok, c_tok, t_tok = self._extract_token_breakdown(chunk)
                        prompt_tokens += p_tok
                        completion_tokens += c_tok
                        token_usage += t_tok
                except Exception as exc:
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
                        latency_ms=max(1, int((time.perf_counter() - t0) * 1000)),
                        is_stream=True,
                        is_mock=False,
                        call_status="failed",
                    )
                    raise self._wrap_llm_error(exc, cfg, t0) from exc
                if token_usage:
                    yield "usage", str(token_usage)

            latency_ms = max(1, int((time.perf_counter() - t0) * 1000))
            full_reply = "".join(collected)
            history.append({"role": "user", "content": req.message})
            history.append({"role": "assistant", "content": full_reply})
            await self.save_history(
                session_id, history, owner, max_messages=cfg.max_history_messages
            )
            await self._persist_turn(
                session_id=session_id,
                user_type=user_type,
                user_id=user_id,
                model_name=cfg.model_name,
                user_content=req.message,
                assistant_content=full_reply,
                token_usage=token_usage,
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
                provider=cfg.provider,
                model_name=cfg.model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=token_usage,
                latency_ms=latency_ms,
                is_stream=True,
                is_mock=not cfg.is_configured,
                call_status="success",
            )

        return session_id, cfg, {"persona_id": persona_id, "persona_name": persona_name}, _generator()


llm_service = LLMService()
