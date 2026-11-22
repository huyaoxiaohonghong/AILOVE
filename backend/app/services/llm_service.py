from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import BusinessException
from app.db.mysql import get_session_factory
from app.db.redis import cache_delete, cache_get_json, cache_set_json
from app.models.ai_chat import AIConversation
from app.models.ai_chat import AIMessage as DBAIMessage
from app.schemas.ai import ChatRequest, ChatResponse
from app.services.ai_config_service import RuntimeAIConfig, resolve_runtime_config
from app.services.ai_providers import (
    BaseProviderAdapter,
    get_provider_adapter,
    humanize_llm_error,
)

logger = logging.getLogger(__name__)

# 当 Redis 未启动时，使用进程内内存字典降级保存多轮上下文（仅开发调试）
_fallback_memory: dict[str, list[dict[str, str]]] = {}
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
    ) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        clock_prompt = build_realtime_clock_prompt(tz_name)
        base_prompt = system_prompt.strip()
        full_system = f"{base_prompt}\n\n{clock_prompt}" if base_prompt else clock_prompt
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
        """将会话与问答消息异步持久化到 MySQL（MySQL 不可用时静默跳过不影响对话）。"""
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
                        user_type=user_type[:16],
                        user_id=user_id,
                        title=user_content.strip()[:60] or "新对话",
                        model_name=model_name[:64],
                    )
                    session.add(conv)
                    await session.flush()
                else:
                    conv.model_name = model_name[:64]

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
            logger.debug("Skip AI chat DB persistence: %s", exc)

    def _extract_token_usage(self, msg: Any) -> int:
        usage = getattr(msg, "usage_metadata", None)
        if isinstance(usage, dict):
            return int(usage.get("total_tokens", 0) or 0)
        resp_meta = getattr(msg, "response_metadata", None)
        if isinstance(resp_meta, dict):
            tok = resp_meta.get("token_usage")
            if isinstance(tok, dict):
                return int(tok.get("total_tokens", 0) or 0)
        return 0

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

    async def chat(
        self,
        req: ChatRequest,
        *,
        user_type: str = "web",
        user_id: int = 0,
    ) -> ChatResponse:
        cfg = await resolve_runtime_config(config_id=req.config_id)
        owner = build_owner_scope(user_type, user_id)
        session_id = req.session_id or uuid.uuid4().hex
        history = await self.get_history(session_id, owner)
        system_prompt = req.system_prompt or cfg.system_prompt
        temperature = req.temperature if req.temperature is not None else cfg.temperature

        is_mock = not cfg.is_configured
        reasoning = ""
        token_usage = 0

        if is_mock:
            reply = self._build_mock_reply(cfg, req.message)
        else:
            adapter, llm = self._build_llm(cfg, temperature, streaming=False)
            messages = self._build_messages(
                system_prompt, history, req.message, tz_name=req.timezone
            )
            t0 = time.perf_counter()
            try:
                ai_msg = await llm.ainvoke(messages)
            except Exception as exc:
                raise self._wrap_llm_error(exc, cfg, t0) from exc
            reasoning, reply = adapter.extract_chunk_deltas(ai_msg)
            token_usage = self._extract_token_usage(ai_msg)

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

        return ChatResponse(
            session_id=session_id,
            reply=reply,
            reasoning=reasoning,
            model=cfg.model_name,
            provider=cfg.provider,
            protocol=cfg.protocol,
            config_id=cfg.id,
            config_name=cfg.name,
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
    ) -> tuple[str, RuntimeAIConfig, AsyncGenerator[tuple[str, str], None]]:
        """流式对话生成器，逐块产出 (event_type: 'reasoning' | 'delta' | 'usage', text_chunk)。"""
        cfg = await resolve_runtime_config(config_id=req.config_id)
        owner = build_owner_scope(user_type, user_id)
        session_id = req.session_id or uuid.uuid4().hex
        history = await self.get_history(session_id, owner)
        system_prompt = req.system_prompt or cfg.system_prompt
        temperature = req.temperature if req.temperature is not None else cfg.temperature

        async def _generator() -> AsyncGenerator[tuple[str, str], None]:
            collected: list[str] = []
            token_usage = 0
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
                    system_prompt, history, req.message, tz_name=req.timezone
                )
                t0 = time.perf_counter()
                try:
                    async for chunk in llm.astream(messages):
                        reasoning_piece, content_piece = adapter.extract_chunk_deltas(chunk)
                        if reasoning_piece:
                            yield "reasoning", reasoning_piece
                        if content_piece:
                            collected.append(content_piece)
                            yield "delta", content_piece
                        # LangChain 约定各 chunk 的 usage_metadata 可累加（OpenAI 末块 / Anthropic 首末块）
                        token_usage += self._extract_token_usage(chunk)
                except Exception as exc:
                    raise self._wrap_llm_error(exc, cfg, t0) from exc
                if token_usage:
                    yield "usage", str(token_usage)

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

        return session_id, cfg, _generator()


llm_service = LLMService()
