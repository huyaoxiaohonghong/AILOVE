from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import status
from langchain_core.messages import HumanMessage
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret, mask_api_key
from app.core.exceptions import BusinessException
from app.db.mysql import get_session_factory
from app.db.redis import cache_delete, cache_get_json, cache_set_json
from app.models.ai_model_config import AIModelConfig
from app.schemas.ai import AIModelConfigCreate, AIModelConfigItem, AIModelConfigUpdate
from app.services.ai_providers import (
    ACTIVE_PROVIDER_ADAPTERS,
    get_provider_adapter,
    humanize_llm_error,
    resolve_protocol,
)

logger = logging.getLogger(__name__)

_ACTIVE_CACHE_KEY = "ailove:ai:active_config"

# 无 MySQL 时的本地开发/单元测试内存仓库
_mem_configs: dict[int, dict[str, Any]] = {}
_mem_seq = 1


@dataclass
class RuntimeAIConfig:
    id: int | None
    name: str
    provider: str
    model_name: str
    base_url: str
    api_key: str
    api_key_masked: str
    temperature: float
    top_p: float
    max_tokens: int
    timeout_seconds: int
    max_history_messages: int
    system_prompt: str
    extra_params: dict[str, Any]
    is_enabled: bool = True
    is_default: bool = True
    last_test_status: str = "untested"
    last_test_latency_ms: int | None = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key.strip())

    @property
    def protocol(self) -> str:
        return resolve_protocol(self.base_url, self.extra_params)


def _parse_extra(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}


def _resolve_protocol(base_url: str, extra: dict[str, Any]) -> str:
    return resolve_protocol(base_url, extra)


def _ensure_mem_seed() -> None:
    if not _mem_configs:
        settings = get_settings()
        plain_key = settings.LLM_API_KEY.strip()
        now = datetime.now(UTC).replace(tzinfo=None)
        seed_base = (
            settings.LLM_BASE_URL
            if settings.LLM_PROVIDER == "deepseek"
            else "https://api.deepseek.com"
        )
        seed_model = (
            settings.LLM_MODEL if settings.LLM_PROVIDER == "deepseek" else "deepseek-flash"
        )
        _mem_configs[1] = {
            "id": 1,
            "name": "DeepSeek 默认对话",
            "provider": "deepseek",
            "model_name": seed_model,
            "base_url": seed_base,
            "api_key_encrypted": encrypt_secret(plain_key),
            "api_key_masked": mask_api_key(plain_key),
            "temperature": settings.LLM_TEMPERATURE,
            "top_p": 1.0,
            "max_tokens": 4096,
            "timeout_seconds": settings.LLM_TIMEOUT_SECONDS,
            "max_history_messages": 20,
            "system_prompt": settings.LLM_SYSTEM_PROMPT,
            "extra_params": json.dumps({"protocol": _resolve_protocol(seed_base, {})}),
            "is_enabled": True,
            "is_default": True,
            "last_test_status": "untested",
            "last_test_latency_ms": None,
            "last_test_message": "",
            "last_tested_at": None,
            "updated_by": None,
            "updated_at": now,
        }


def _row_to_item(row: AIModelConfig) -> AIModelConfigItem:
    extra = _parse_extra(row.extra_params)
    return AIModelConfigItem(
        id=row.id,
        name=row.name,
        provider=row.provider,
        protocol=_resolve_protocol(row.base_url, extra),  # type: ignore[arg-type]
        model_name=row.model_name,
        base_url=row.base_url,
        has_api_key=bool(row.api_key_encrypted),
        api_key_masked=row.api_key_masked,
        temperature=row.temperature,
        top_p=row.top_p,
        max_tokens=row.max_tokens,
        timeout_seconds=row.timeout_seconds,
        max_history_messages=row.max_history_messages,
        system_prompt=row.system_prompt,
        extra_params=extra,
        is_enabled=row.is_enabled,
        is_default=row.is_default,
        last_test_status=row.last_test_status,
        last_test_latency_ms=row.last_test_latency_ms,
        last_test_message=row.last_test_message,
        last_tested_at=row.last_tested_at,
        updated_at=row.updated_at,
    )


def _mem_to_item(rec: dict[str, Any]) -> AIModelConfigItem:
    extra = _parse_extra(rec.get("extra_params", "{}"))
    return AIModelConfigItem(
        id=rec["id"],
        name=rec["name"],
        provider=rec["provider"],
        protocol=_resolve_protocol(rec["base_url"], extra),  # type: ignore[arg-type]
        model_name=rec["model_name"],
        base_url=rec["base_url"],
        has_api_key=bool(rec["api_key_encrypted"]),
        api_key_masked=rec["api_key_masked"],
        temperature=rec["temperature"],
        top_p=rec["top_p"],
        max_tokens=rec["max_tokens"],
        timeout_seconds=rec["timeout_seconds"],
        max_history_messages=rec["max_history_messages"],
        system_prompt=rec["system_prompt"],
        extra_params=extra,
        is_enabled=rec["is_enabled"],
        is_default=rec["is_default"],
        last_test_status=rec["last_test_status"],
        last_test_latency_ms=rec["last_test_latency_ms"],
        last_test_message=rec["last_test_message"],
        last_tested_at=rec["last_tested_at"],
        updated_at=rec["updated_at"],
    )


def _row_to_runtime(row: AIModelConfig) -> RuntimeAIConfig:
    return RuntimeAIConfig(
        id=row.id,
        name=row.name,
        provider=row.provider,
        model_name=row.model_name,
        base_url=row.base_url,
        api_key=decrypt_secret(row.api_key_encrypted),
        api_key_masked=row.api_key_masked,
        temperature=row.temperature,
        top_p=row.top_p,
        max_tokens=row.max_tokens,
        timeout_seconds=row.timeout_seconds,
        max_history_messages=row.max_history_messages,
        system_prompt=row.system_prompt,
        extra_params=_parse_extra(row.extra_params),
        is_enabled=row.is_enabled,
        is_default=row.is_default,
        last_test_status=row.last_test_status,
        last_test_latency_ms=row.last_test_latency_ms,
    )


def _mem_to_runtime(rec: dict[str, Any]) -> RuntimeAIConfig:
    return RuntimeAIConfig(
        id=rec["id"],
        name=rec["name"],
        provider=rec["provider"],
        model_name=rec["model_name"],
        base_url=rec["base_url"],
        api_key=decrypt_secret(rec["api_key_encrypted"]),
        api_key_masked=rec["api_key_masked"],
        temperature=rec["temperature"],
        top_p=rec["top_p"],
        max_tokens=rec["max_tokens"],
        timeout_seconds=rec["timeout_seconds"],
        max_history_messages=rec["max_history_messages"],
        system_prompt=rec["system_prompt"],
        extra_params=_parse_extra(rec.get("extra_params", "{}")),
        is_enabled=rec["is_enabled"],
        is_default=rec["is_default"],
        last_test_status=rec["last_test_status"],
        last_test_latency_ms=rec["last_test_latency_ms"],
    )


async def invalidate_active_cache() -> None:
    await cache_delete(_ACTIVE_CACHE_KEY)


async def ensure_default_ai_config() -> None:
    """首次启动时自动初始化一条 DeepSeek 默认配置记录，方便管理员直接在后台填入 Key。"""
    settings = get_settings()
    try:
        factory = get_session_factory()
        async with factory() as session:
            existing = (await session.execute(select(AIModelConfig).limit(1))).scalar_one_or_none()
            if existing is None:
                plain_key = settings.LLM_API_KEY.strip()
                cfg = AIModelConfig(
                    name="DeepSeek 默认对话",
                    provider="deepseek",
                    model_name="deepseek-flash",
                    base_url="https://api.deepseek.com",
                    api_key_encrypted=encrypt_secret(plain_key),
                    api_key_masked=mask_api_key(plain_key),
                    temperature=settings.LLM_TEMPERATURE,
                    top_p=1.0,
                    max_tokens=4096,
                    timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
                    max_history_messages=20,
                    system_prompt=settings.LLM_SYSTEM_PROMPT,
                    extra_params=json.dumps({"protocol": "openai"}),
                    is_enabled=True,
                    is_default=True,
                )
                session.add(cfg)
                await session.commit()
                await invalidate_active_cache()
                logger.info("Initialized default DeepSeek AI model configuration.")
    except Exception as exc:
        logger.warning("Skip default AI config bootstrap: %s", exc)


async def list_ai_configs(*, only_enabled: bool = False) -> list[AIModelConfigItem]:
    try:
        factory = get_session_factory()
        async with factory() as session:
            stmt = select(AIModelConfig)
            if only_enabled:
                stmt = stmt.where(AIModelConfig.is_enabled.is_(True))
            stmt = stmt.order_by(AIModelConfig.is_default.desc(), AIModelConfig.id.asc())
            rows = (await session.execute(stmt)).scalars().all()
            return [_row_to_item(r) for r in rows]
    except (SQLAlchemyError, OSError):
        _ensure_mem_seed()
        recs = list(_mem_configs.values())
        if only_enabled:
            recs = [r for r in recs if r["is_enabled"]]
        recs.sort(key=lambda r: (not r["is_default"], r["id"]))
        return [_mem_to_item(r) for r in recs]


async def create_ai_config(req: AIModelConfigCreate, admin_id: int) -> AIModelConfigItem:
    adapter = get_provider_adapter(req.provider)
    if adapter is None:
        supported = " / ".join(ACTIVE_PROVIDER_ADAPTERS.keys())
        raise BusinessException(
            f"暂不支持提供商「{req.provider}」，当前已开放：{supported}",
            code=40040,
        )

    plain_key = req.api_key.strip()
    enc_key = encrypt_secret(plain_key)
    masked = mask_api_key(plain_key)
    merged_extra = dict(req.extra_params or {})
    merged_extra["protocol"] = req.protocol
    extra_json = json.dumps(merged_extra, ensure_ascii=False)

    try:
        factory = get_session_factory()
        async with factory() as session:
            has_any = (await session.execute(select(AIModelConfig.id).limit(1))).scalar_one_or_none()
            should_default = req.is_default or (has_any is None)
            if should_default:
                await session.execute(update(AIModelConfig).values(is_default=False))

            row = AIModelConfig(
                name=req.name.strip(),
                provider=adapter.descriptor.code,
                model_name=req.model_name.strip(),
                base_url=req.base_url.strip().rstrip("/"),
                api_key_encrypted=enc_key,
                api_key_masked=masked,
                temperature=req.temperature,
                top_p=req.top_p,
                max_tokens=req.max_tokens,
                timeout_seconds=req.timeout_seconds,
                max_history_messages=req.max_history_messages,
                system_prompt=req.system_prompt.strip(),
                extra_params=extra_json,
                is_enabled=req.is_enabled,
                is_default=should_default,
                updated_by=admin_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            await invalidate_active_cache()
            return _row_to_item(row)
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError):
        _ensure_mem_seed()
        global _mem_seq
        _mem_seq += 1
        cid = _mem_seq
        if req.is_default:
            for rec in _mem_configs.values():
                rec["is_default"] = False
        now = datetime.now(UTC).replace(tzinfo=None)
        rec = {
            "id": cid,
            "name": req.name.strip(),
            "provider": adapter.descriptor.code,
            "model_name": req.model_name.strip(),
            "base_url": req.base_url.strip().rstrip("/"),
            "api_key_encrypted": enc_key,
            "api_key_masked": masked,
            "temperature": req.temperature,
            "top_p": req.top_p,
            "max_tokens": req.max_tokens,
            "timeout_seconds": req.timeout_seconds,
            "max_history_messages": req.max_history_messages,
            "system_prompt": req.system_prompt.strip(),
            "extra_params": extra_json,
            "is_enabled": req.is_enabled,
            "is_default": req.is_default,
            "last_test_status": "untested",
            "last_test_latency_ms": None,
            "last_test_message": "",
            "last_tested_at": None,
            "updated_by": admin_id,
            "updated_at": now,
        }
        _mem_configs[cid] = rec
        await invalidate_active_cache()
        return _mem_to_item(rec)


async def update_ai_config(
    config_id: int, req: AIModelConfigUpdate, admin_id: int
) -> AIModelConfigItem:
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(AIModelConfig, config_id)
            if row is None:
                raise BusinessException(
                    "目标 AI 模型配置不存在", code=40403, status_code=status.HTTP_404_NOT_FOUND
                )

            if req.name is not None:
                row.name = req.name.strip()
            if req.model_name is not None:
                row.model_name = req.model_name.strip()
            if req.base_url is not None:
                row.base_url = req.base_url.strip().rstrip("/")
            if req.clear_api_key:
                row.api_key_encrypted = ""
                row.api_key_masked = ""
            elif req.api_key is not None and req.api_key.strip():
                plain = req.api_key.strip()
                row.api_key_encrypted = encrypt_secret(plain)
                row.api_key_masked = mask_api_key(plain)
            if req.temperature is not None:
                row.temperature = req.temperature
            if req.top_p is not None:
                row.top_p = req.top_p
            if req.max_tokens is not None:
                row.max_tokens = req.max_tokens
            if req.timeout_seconds is not None:
                row.timeout_seconds = req.timeout_seconds
            if req.max_history_messages is not None:
                row.max_history_messages = req.max_history_messages
            if req.system_prompt is not None:
                row.system_prompt = req.system_prompt.strip()
            if req.extra_params is not None or req.protocol is not None:
                merged_extra = (
                    dict(req.extra_params)
                    if req.extra_params is not None
                    else _parse_extra(row.extra_params)
                )
                if req.protocol is not None:
                    merged_extra["protocol"] = req.protocol
                row.extra_params = json.dumps(merged_extra, ensure_ascii=False)
            if req.is_enabled is not None:
                row.is_enabled = req.is_enabled
            if req.is_default is True:
                await session.execute(update(AIModelConfig).values(is_default=False))
                row.is_default = True
                row.is_enabled = True
            row.updated_by = admin_id
            await session.commit()
            await session.refresh(row)
            await invalidate_active_cache()
            return _row_to_item(row)
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        _ensure_mem_seed()
        rec = _mem_configs.get(config_id)
        if rec is None:
            raise BusinessException(
                "目标 AI 模型配置不存在", code=40403, status_code=status.HTTP_404_NOT_FOUND
            ) from exc
        if req.name is not None:
            rec["name"] = req.name.strip()
        if req.model_name is not None:
            rec["model_name"] = req.model_name.strip()
        if req.base_url is not None:
            rec["base_url"] = req.base_url.strip().rstrip("/")
        if req.clear_api_key:
            rec["api_key_encrypted"] = ""
            rec["api_key_masked"] = ""
        elif req.api_key is not None and req.api_key.strip():
            plain = req.api_key.strip()
            rec["api_key_encrypted"] = encrypt_secret(plain)
            rec["api_key_masked"] = mask_api_key(plain)
        for fld in (
            "temperature",
            "top_p",
            "max_tokens",
            "timeout_seconds",
            "max_history_messages",
            "system_prompt",
            "is_enabled",
        ):
            val = getattr(req, fld)
            if val is not None:
                rec[fld] = val.strip() if isinstance(val, str) else val
        if req.extra_params is not None or req.protocol is not None:
            merged_extra = (
                dict(req.extra_params)
                if req.extra_params is not None
                else _parse_extra(rec.get("extra_params", "{}"))
            )
            if req.protocol is not None:
                merged_extra["protocol"] = req.protocol
            rec["extra_params"] = json.dumps(merged_extra, ensure_ascii=False)
        if req.is_default is True:
            for other in _mem_configs.values():
                other["is_default"] = False
            rec["is_default"] = True
            rec["is_enabled"] = True
        rec["updated_at"] = datetime.now(UTC).replace(tzinfo=None)
        await invalidate_active_cache()
        return _mem_to_item(rec)


async def set_default_ai_config(config_id: int, admin_id: int) -> AIModelConfigItem:
    return await update_ai_config(
        config_id, AIModelConfigUpdate(is_default=True, is_enabled=True), admin_id=admin_id
    )


async def delete_ai_config(config_id: int) -> None:
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(AIModelConfig, config_id)
            if row is None:
                raise BusinessException(
                    "目标 AI 模型配置不存在", code=40403, status_code=status.HTTP_404_NOT_FOUND
                )
            was_default = row.is_default
            await session.delete(row)
            await session.flush()
            if was_default:
                next_row = (
                    await session.execute(select(AIModelConfig).order_by(AIModelConfig.id.asc()).limit(1))
                ).scalar_one_or_none()
                if next_row is not None:
                    next_row.is_default = True
            await session.commit()
            await invalidate_active_cache()
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        _ensure_mem_seed()
        rec = _mem_configs.pop(config_id, None)
        if rec is None:
            raise BusinessException(
                "目标 AI 模型配置不存在", code=40403, status_code=status.HTTP_404_NOT_FOUND
            ) from exc
        if rec["is_default"] and _mem_configs:
            first_id = sorted(_mem_configs.keys())[0]
            _mem_configs[first_id]["is_default"] = True
        await invalidate_active_cache()


async def resolve_runtime_config(config_id: int | None = None) -> RuntimeAIConfig:
    """按 config_id 或全局默认配置加载运行时模型参数（优先 Redis 热缓存，自动回退 DB / .env）。"""
    if config_id is None:
        cached = await cache_get_json(_ACTIVE_CACHE_KEY)
        if isinstance(cached, dict) and "model_name" in cached:
            return RuntimeAIConfig(
                id=cached.get("id"),
                name=cached.get("name", "DeepSeek 默认对话"),
                provider=cached.get("provider", "deepseek"),
                model_name=cached.get("model_name", "deepseek-flash"),
                base_url=cached.get("base_url", "https://api.deepseek.com"),
                api_key=decrypt_secret(cached.get("api_key_encrypted", "")),
                api_key_masked=cached.get("api_key_masked", ""),
                temperature=float(cached.get("temperature", 0.7)),
                top_p=float(cached.get("top_p", 1.0)),
                max_tokens=int(cached.get("max_tokens", 2048)),
                timeout_seconds=int(cached.get("timeout_seconds", 60)),
                max_history_messages=int(cached.get("max_history_messages", 20)),
                system_prompt=cached.get("system_prompt", get_settings().LLM_SYSTEM_PROMPT),
                extra_params=cached.get("extra_params", {}),
                is_enabled=True,
                is_default=True,
                last_test_status=cached.get("last_test_status", "untested"),
                last_test_latency_ms=cached.get("last_test_latency_ms"),
            )

    try:
        factory = get_session_factory()
        async with factory() as session:
            if config_id is not None:
                row = await session.get(AIModelConfig, config_id)
                if row is None or not row.is_enabled:
                    raise BusinessException(
                        "指定的 AI 模型配置不存在或已禁用",
                        code=40403,
                        status_code=status.HTTP_404_NOT_FOUND,
                    )
                return _row_to_runtime(row)

            row = (
                await session.execute(
                    select(AIModelConfig)
                    .where(AIModelConfig.is_enabled.is_(True))
                    .order_by(AIModelConfig.is_default.desc(), AIModelConfig.id.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if row is not None:
                await cache_set_json(
                    _ACTIVE_CACHE_KEY,
                    {
                        "id": row.id,
                        "name": row.name,
                        "provider": row.provider,
                        "model_name": row.model_name,
                        "base_url": row.base_url,
                        "api_key_encrypted": row.api_key_encrypted,
                        "api_key_masked": row.api_key_masked,
                        "temperature": row.temperature,
                        "top_p": row.top_p,
                        "max_tokens": row.max_tokens,
                        "timeout_seconds": row.timeout_seconds,
                        "max_history_messages": row.max_history_messages,
                        "system_prompt": row.system_prompt,
                        "extra_params": _parse_extra(row.extra_params),
                        "last_test_status": row.last_test_status,
                        "last_test_latency_ms": row.last_test_latency_ms,
                    },
                    ttl_seconds=300,
                )
                return _row_to_runtime(row)
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError):
        _ensure_mem_seed()
        if config_id is not None:
            rec = _mem_configs.get(config_id)
            if rec is None or not rec["is_enabled"]:
                raise BusinessException(
                    "指定的 AI 模型配置不存在或已禁用",
                    code=40403,
                    status_code=status.HTTP_404_NOT_FOUND,
                ) from None
            return _mem_to_runtime(rec)
        enabled = [r for r in _mem_configs.values() if r["is_enabled"]]
        if enabled:
            enabled.sort(key=lambda r: (not r["is_default"], r["id"]))
            return _mem_to_runtime(enabled[0])

    # 兜底回退 .env 默认值
    settings = get_settings()
    return RuntimeAIConfig(
        id=None,
        name="DeepSeek 默认配置 (.env)",
        provider=settings.LLM_PROVIDER,
        model_name=settings.LLM_MODEL,
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY.strip(),
        api_key_masked=mask_api_key(settings.LLM_API_KEY),
        temperature=settings.LLM_TEMPERATURE,
        top_p=1.0,
        max_tokens=2048,
        timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        max_history_messages=20,
        system_prompt=settings.LLM_SYSTEM_PROMPT,
        extra_params={},
    )


async def resolve_fallback_configs(exclude_id: int | None = None) -> list[RuntimeAIConfig]:
    """获取已启用且已配置 API Key 的备用模型列表（优先选用最近探针测试通过的配置）。"""
    candidates: list[RuntimeAIConfig] = []
    try:
        factory = get_session_factory()
        async with factory() as session:
            stmt = select(AIModelConfig).where(AIModelConfig.is_enabled.is_(True))
            if exclude_id is not None:
                stmt = stmt.where(AIModelConfig.id != exclude_id)
            rows = (await session.execute(stmt)).scalars().all()
            for row in rows:
                runtime = _row_to_runtime(row)
                if runtime.is_configured and get_provider_adapter(runtime.provider) is not None:
                    candidates.append(runtime)
    except (SQLAlchemyError, OSError):
        _ensure_mem_seed()
        for rec in _mem_configs.values():
            if not rec["is_enabled"]:
                continue
            if exclude_id is not None and rec["id"] == exclude_id:
                continue
            runtime = _mem_to_runtime(rec)
            if runtime.is_configured and get_provider_adapter(runtime.provider) is not None:
                candidates.append(runtime)

    candidates.sort(
        key=lambda c: (
            c.last_test_status != "ok",
            not c.is_default,
            c.id or 0,
        )
    )
    return candidates


async def _record_test_outcome(
    config_id: int, ok_flag: bool, latency_ms: int, message: str
) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    test_status = "ok" if ok_flag else "failed"
    short_msg = (message or "")[:250]
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(AIModelConfig, config_id)
            if row is not None:
                row.last_test_status = test_status
                row.last_test_latency_ms = latency_ms
                row.last_test_message = short_msg
                row.last_tested_at = now
                await session.commit()
    except (SQLAlchemyError, OSError):
        rec = _mem_configs.get(config_id)
        if rec is not None:
            rec["last_test_status"] = test_status
            rec["last_test_latency_ms"] = latency_ms
            rec["last_test_message"] = short_msg
            rec["last_tested_at"] = now
    await invalidate_active_cache()


async def test_ai_config_connection(config_id: int) -> dict[str, Any]:
    """对指定 AI 模型配置执行真实探针测试，校验 API Key、Base URL 与模型可用性并记录延迟。"""
    cfg = await resolve_runtime_config(config_id=config_id)
    if not cfg.is_configured:
        await _record_test_outcome(config_id, False, 0, "尚未填写 API Key")
        return {
            "success": False,
            "latency_ms": 0,
            "model": cfg.model_name,
            "provider": cfg.provider,
            "reply_preview": "",
            "message": "该配置尚未填写 API Key，请先编辑填入 DeepSeek API Key 后再测试",
        }

    adapter = get_provider_adapter(cfg.provider)
    if adapter is None:
        return {
            "success": False,
            "latency_ms": 0,
            "model": cfg.model_name,
            "provider": cfg.provider,
            "reply_preview": "",
            "message": f"未找到提供商 {cfg.provider} 的适配器",
        }

    t0 = time.perf_counter()
    try:
        llm = adapter.build_chat_model(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            model_name=cfg.model_name,
            temperature=0.1,
            top_p=1.0,
            max_tokens=64,
            timeout_seconds=min(cfg.timeout_seconds, 25),
            streaming=False,
            extra_params=cfg.extra_params,
        )
        resp = await llm.ainvoke([HumanMessage(content="请仅回复：OK")])
        latency_ms = int((time.perf_counter() - t0) * 1000)
        _, text = adapter.extract_chunk_deltas(resp)
        preview = text.strip()[:80] or "OK"
        msg = f"连通成功（耗时 {latency_ms}ms，回复：{preview}）"
        await _record_test_outcome(config_id, True, latency_ms, msg)
        return {
            "success": True,
            "latency_ms": latency_ms,
            "model": cfg.model_name,
            "provider": cfg.provider,
            "protocol": cfg.protocol,
            "reply_preview": preview,
            "message": msg,
        }
    except Exception as exc:
        latency_ms = int((time.perf_counter() - t0) * 1000)
        friendly = humanize_llm_error(
            exc, model_name=cfg.model_name, base_url=cfg.base_url, latency_ms=latency_ms
        )
        await _record_test_outcome(config_id, False, latency_ms, friendly)
        return {
            "success": False,
            "latency_ms": latency_ms,
            "model": cfg.model_name,
            "provider": cfg.provider,
            "reply_preview": "",
            "message": friendly,
        }
