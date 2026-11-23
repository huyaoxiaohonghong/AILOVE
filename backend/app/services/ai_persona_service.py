from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import status
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import BusinessException
from app.db.mysql import get_session_factory
from app.db.redis import cache_delete, cache_get_json, cache_set_json
from app.models.ai_persona import AIPersona
from app.schemas.ai import AIPersonaCreate, AIPersonaUpdate

logger = logging.getLogger(__name__)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_PERSONAS_CACHE_KEY = "ailove:ai:personas:all"

DEFAULT_PERSONAS: list[dict[str, Any]] = [
    {
        "code": "assistant_general",
        "name": "全能暖心助手",
        "avatar_emoji": "🤖",
        "category": "general",
        "description": "日常问答、信息梳理与方案建议的通用搭档，表达自然有条理。",
        "system_prompt": (
            "你是 AILOVE 全能助手，请用清晰、温暖、专业且结论先行的中文回答问题。"
            "复杂回答优先分点阐述，必要时给出可执行清单。"
        ),
        "starter_prompts": [
            "帮我把本周的工作事项按优先级排个序",
            "给我 3 个提高日常沟通效率的实用技巧",
            "把下面这段杂乱的想法整理成清晰的会议纪要",
        ],
        "temperature": 0.7,
        "sort_order": 10,
    },
    {
        "code": "copywriter_pro",
        "name": "爆款文案大师",
        "avatar_emoji": "✍️",
        "category": "writing",
        "description": "精通公众号、小红书、产品发布与活动宣传文案润色及多风格改写。",
        "system_prompt": (
            "你是一位资深品牌内容总监与爆款文案专家。请紧扣目标受众痛点与情绪价值，"
            "输出抓眼球的标题与结构化正文，并提供 2~3 个不同语气的备选方案。"
        ),
        "starter_prompts": [
            "为一个 AI 智能工作台写 5 个吸引人的发布会标题",
            "把这段生硬的产品介绍改写成亲切的小红书种草风格",
            "策划一份简洁有感染力的会员周报开场白",
        ],
        "temperature": 0.85,
        "sort_order": 20,
    },
    {
        "code": "architect_coder",
        "name": "全栈架构导师",
        "avatar_emoji": "💻",
        "category": "coding",
        "description": "专注 Python/FastAPI、Vue/TS、SQL 优化与系统架构设计排错。",
        "system_prompt": (
            "你是一位严谨的资深全栈架构师。回答技术问题时先给结论与根因分析，"
            "再附带干净、可运行、带关键注释的示例代码与边界条件提醒。"
        ),
        "starter_prompts": [
            "分析一段 FastAPI 异步接口并发场景下的连接池瓶颈",
            "帮我优化这条慢 SQL 查询并说明索引设计原因",
            "用 TypeScript 写一个防抖与错误重试合一的请求封装",
        ],
        "temperature": 0.3,
        "sort_order": 30,
    },
    {
        "code": "translator_bilingual",
        "name": "中英双语译官",
        "avatar_emoji": "🌐",
        "category": "translate",
        "description": "兼顾信达雅、技术文档术语与商务邮件的地道中英互译专家。",
        "system_prompt": (
            "你是一位精通中英文的专业同声传译与技术本地化专家。"
            "自动识别输入语种并译为目标语言：保证术语准确、语气地道，"
            "并在译文后附 1~2 条关键表达解释。"
        ),
        "starter_prompts": [
            "将这封英文客户沟通邮件润色为得体专业的商务表达",
            "把这段中文技术方案准确翻译成英文 PRD 文档",
            "解释“graceful degradation”在系统架构语境下的最佳译法",
        ],
        "temperature": 0.3,
        "sort_order": 40,
    },
    {
        "code": "data_analyst",
        "name": "结构化分析顾问",
        "avatar_emoji": "📊",
        "category": "analysis",
        "description": "擅长将业务问题拆解为指标维度、根因假设与可视化分析建议。",
        "system_prompt": (
            "你是一位资深商业数据分析师。善于使用 MECE 原则与漏斗思维拆解问题，"
            "输出请包含核心指标定义、对比维度、可能原因及下一步验证动作，常用 Markdown 表格。"
        ),
        "starter_prompts": [
            "帮我设计一套 AI 助手产品的核心留存与活跃度评估指标",
            "留存率连续两周下滑 8%，请给出排查维度拆解框架",
            "用 Markdown 表格对比三种用户配额限流策略的优缺点",
        ],
        "temperature": 0.5,
        "sort_order": 50,
    },
]

_mem_personas: dict[int, dict[str, Any]] = {}
_mem_seq = 1


def _now_shanghai_naive() -> datetime:
    return datetime.now(_SHANGHAI_TZ).replace(tzinfo=None)


def _clean_starters(starters: list[str] | None) -> list[str]:
    if not starters:
        return []
    cleaned: list[str] = []
    for item in starters:
        text = str(item).strip()
        if text and text not in cleaned:
            cleaned.append(text[:200])
        if len(cleaned) >= 6:
            break
    return cleaned


def _parse_starters(raw: str) -> list[str]:
    try:
        parsed = json.loads(raw or "[]")
        if isinstance(parsed, list):
            return [str(x) for x in parsed if str(x).strip()]
    except ValueError:
        pass
    return []


def _serialize_persona(row: AIPersona) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "code": row.code,
        "name": row.name,
        "avatar_emoji": row.avatar_emoji,
        "category": row.category,
        "description": row.description,
        "system_prompt": row.system_prompt,
        "starter_prompts": _parse_starters(row.starter_prompts_json),
        "temperature": row.temperature,
        "is_system": bool(row.is_system),
        "is_enabled": bool(row.is_enabled),
        "sort_order": int(row.sort_order),
        "usage_count": int(row.usage_count),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _ensure_mem_seed() -> None:
    global _mem_seq
    if _mem_personas:
        return
    now_iso = _now_shanghai_naive().isoformat()
    for item in DEFAULT_PERSONAS:
        pid = _mem_seq
        _mem_seq += 1
        _mem_personas[pid] = {
            "id": pid,
            "code": item["code"],
            "name": item["name"],
            "avatar_emoji": item["avatar_emoji"],
            "category": item["category"],
            "description": item["description"],
            "system_prompt": item["system_prompt"],
            "starter_prompts": list(item["starter_prompts"]),
            "temperature": item["temperature"],
            "is_system": True,
            "is_enabled": True,
            "sort_order": item["sort_order"],
            "usage_count": 0,
            "created_at": now_iso,
            "updated_at": now_iso,
        }


async def ensure_default_personas() -> None:
    """确保系统内置智能体模板存在（幂等写入）。"""
    _ensure_mem_seed()
    try:
        factory = get_session_factory()
        async with factory() as db:
            existing_codes = set(
                (await db.execute(select(AIPersona.code))).scalars().all()
            )
            inserted = False
            for item in DEFAULT_PERSONAS:
                if item["code"] in existing_codes:
                    continue
                db.add(
                    AIPersona(
                        code=item["code"],
                        name=item["name"],
                        avatar_emoji=item["avatar_emoji"],
                        category=item["category"],
                        description=item["description"],
                        system_prompt=item["system_prompt"],
                        starter_prompts_json=json.dumps(
                            item["starter_prompts"], ensure_ascii=False
                        ),
                        temperature=item["temperature"],
                        is_system=True,
                        is_enabled=True,
                        sort_order=item["sort_order"],
                        usage_count=0,
                    )
                )
                inserted = True
            if inserted:
                await db.commit()
                await cache_delete(_PERSONAS_CACHE_KEY)
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("ensure_default_personas fallback to memory: %s", exc)


async def _load_all_personas() -> list[dict[str, Any]]:
    cached = await cache_get_json(_PERSONAS_CACHE_KEY)
    if isinstance(cached, list) and cached:
        return cached

    try:
        factory = get_session_factory()
        async with factory() as db:
            rows = (
                await db.execute(
                    select(AIPersona).order_by(AIPersona.sort_order.asc(), AIPersona.id.asc())
                )
            ).scalars().all()
            if not rows:
                await ensure_default_personas()
                rows = (
                    await db.execute(
                        select(AIPersona).order_by(AIPersona.sort_order.asc(), AIPersona.id.asc())
                    )
                ).scalars().all()
            items = [_serialize_persona(r) for r in rows]
            await cache_set_json(_PERSONAS_CACHE_KEY, items, ttl_seconds=300)
            return items
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("_load_all_personas fallback to memory: %s", exc)
        _ensure_mem_seed()
        return sorted(
            [dict(v) for v in _mem_personas.values()],
            key=lambda x: (int(x["sort_order"]), int(x["id"])),
        )


async def list_personas(
    *,
    enabled_only: bool = False,
    category: str | None = None,
    keyword: str | None = None,
) -> list[dict[str, Any]]:
    items = await _load_all_personas()
    cat = (category or "").strip().lower()
    kw = (keyword or "").strip().lower()
    result: list[dict[str, Any]] = []
    for item in items:
        if enabled_only and not item["is_enabled"]:
            continue
        if cat and cat != "all" and item["category"].lower() != cat:
            continue
        if kw:
            haystack = f"{item['code']} {item['name']} {item['description']}".lower()
            if kw not in haystack:
                continue
        result.append(item)
    return result


async def get_persona(persona_id: int, *, require_enabled: bool = False) -> dict[str, Any]:
    items = await _load_all_personas()
    target = next((item for item in items if int(item["id"]) == int(persona_id)), None)
    if not target:
        raise BusinessException(
            "指定的 AI 智能体不存在",
            code=40404,
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if require_enabled and not target["is_enabled"]:
        raise BusinessException(
            "该 AI 智能体已停用，请切换其他智能体",
            code=40010,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return target


async def create_persona(payload: AIPersonaCreate) -> dict[str, Any]:
    global _mem_seq
    code = payload.code.strip()
    starters = _clean_starters(payload.starter_prompts)
    try:
        factory = get_session_factory()
        async with factory() as db:
            dup = (
                await db.execute(select(AIPersona.id).where(AIPersona.code == code))
            ).scalar_one_or_none()
            if dup is not None:
                raise BusinessException(
                    f"智能体编码 {code} 已存在",
                    code=40009,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            row = AIPersona(
                code=code,
                name=payload.name.strip(),
                avatar_emoji=payload.avatar_emoji.strip() or "🤖",
                category=payload.category,
                description=payload.description.strip(),
                system_prompt=payload.system_prompt.strip(),
                starter_prompts_json=json.dumps(starters, ensure_ascii=False),
                temperature=payload.temperature,
                is_system=False,
                is_enabled=payload.is_enabled,
                sort_order=payload.sort_order,
                usage_count=0,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            await cache_delete(_PERSONAS_CACHE_KEY)
            return _serialize_persona(row)
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("create_persona fallback to memory: %s", exc)
        _ensure_mem_seed()
        if any(p["code"] == code for p in _mem_personas.values()):
            raise BusinessException(
                f"智能体编码 {code} 已存在",
                code=40009,
                status_code=status.HTTP_400_BAD_REQUEST,
            ) from exc
        pid = _mem_seq
        _mem_seq += 1
        now_iso = _now_shanghai_naive().isoformat()
        item = {
            "id": pid,
            "code": code,
            "name": payload.name.strip(),
            "avatar_emoji": payload.avatar_emoji.strip() or "🤖",
            "category": payload.category,
            "description": payload.description.strip(),
            "system_prompt": payload.system_prompt.strip(),
            "starter_prompts": starters,
            "temperature": payload.temperature,
            "is_system": False,
            "is_enabled": payload.is_enabled,
            "sort_order": payload.sort_order,
            "usage_count": 0,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        _mem_personas[pid] = item
        await cache_delete(_PERSONAS_CACHE_KEY)
        return dict(item)


async def update_persona(persona_id: int, payload: AIPersonaUpdate) -> dict[str, Any]:
    try:
        factory = get_session_factory()
        async with factory() as db:
            row = await db.get(AIPersona, persona_id)
            if not row:
                raise BusinessException(
                    "指定的 AI 智能体不存在",
                    code=40404,
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            if payload.name is not None:
                row.name = payload.name.strip()
            if payload.avatar_emoji is not None:
                row.avatar_emoji = payload.avatar_emoji.strip() or "🤖"
            if payload.category is not None:
                row.category = payload.category
            if payload.description is not None:
                row.description = payload.description.strip()
            if payload.system_prompt is not None:
                row.system_prompt = payload.system_prompt.strip()
            if payload.starter_prompts is not None:
                row.starter_prompts_json = json.dumps(
                    _clean_starters(payload.starter_prompts), ensure_ascii=False
                )
            if payload.clear_temperature:
                row.temperature = None
            elif payload.temperature is not None:
                row.temperature = payload.temperature
            if payload.is_enabled is not None:
                row.is_enabled = payload.is_enabled
            if payload.sort_order is not None:
                row.sort_order = payload.sort_order

            await db.commit()
            await db.refresh(row)
            await cache_delete(_PERSONAS_CACHE_KEY)
            return _serialize_persona(row)
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("update_persona fallback to memory: %s", exc)
        _ensure_mem_seed()
        item = _mem_personas.get(persona_id)
        if not item:
            raise BusinessException(
                "指定的 AI 智能体不存在",
                code=40404,
                status_code=status.HTTP_404_NOT_FOUND,
            ) from exc
        if payload.name is not None:
            item["name"] = payload.name.strip()
        if payload.avatar_emoji is not None:
            item["avatar_emoji"] = payload.avatar_emoji.strip() or "🤖"
        if payload.category is not None:
            item["category"] = payload.category
        if payload.description is not None:
            item["description"] = payload.description.strip()
        if payload.system_prompt is not None:
            item["system_prompt"] = payload.system_prompt.strip()
        if payload.starter_prompts is not None:
            item["starter_prompts"] = _clean_starters(payload.starter_prompts)
        if payload.clear_temperature:
            item["temperature"] = None
        elif payload.temperature is not None:
            item["temperature"] = payload.temperature
        if payload.is_enabled is not None:
            item["is_enabled"] = payload.is_enabled
        if payload.sort_order is not None:
            item["sort_order"] = payload.sort_order
        item["updated_at"] = _now_shanghai_naive().isoformat()
        await cache_delete(_PERSONAS_CACHE_KEY)
        return dict(item)


async def delete_persona(persona_id: int) -> dict[str, Any]:
    try:
        factory = get_session_factory()
        async with factory() as db:
            row = await db.get(AIPersona, persona_id)
            if not row:
                raise BusinessException(
                    "指定的 AI 智能体不存在",
                    code=40404,
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            if row.is_system:
                raise BusinessException(
                    "系统预置智能体不可删除，如不需要可将其设为停用",
                    code=40301,
                    status_code=status.HTTP_403_FORBIDDEN,
                )
            name = row.name
            await db.delete(row)
            await db.commit()
            await cache_delete(_PERSONAS_CACHE_KEY)
            return {"deleted_id": persona_id, "name": name}
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("delete_persona fallback to memory: %s", exc)
        _ensure_mem_seed()
        item = _mem_personas.get(persona_id)
        if not item:
            raise BusinessException(
                "指定的 AI 智能体不存在",
                code=40404,
                status_code=status.HTTP_404_NOT_FOUND,
            ) from exc
        if item["is_system"]:
            raise BusinessException(
                "系统预置智能体不可删除，如不需要可将其设为停用",
                code=40301,
                status_code=status.HTTP_403_FORBIDDEN,
            ) from exc
        name = item["name"]
        _mem_personas.pop(persona_id, None)
        await cache_delete(_PERSONAS_CACHE_KEY)
        return {"deleted_id": persona_id, "name": name}


async def increment_persona_usage(persona_id: int) -> None:
    """累加智能体使用次数（非关键计数，失败静默降级）。"""
    try:
        factory = get_session_factory()
        async with factory() as db:
            await db.execute(
                update(AIPersona)
                .where(AIPersona.id == persona_id)
                .values(usage_count=AIPersona.usage_count + 1)
            )
            await db.commit()
            await cache_delete(_PERSONAS_CACHE_KEY)
            return
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("increment_persona_usage fallback to memory: %s", exc)
        _ensure_mem_seed()
        if persona_id in _mem_personas:
            _mem_personas[persona_id]["usage_count"] = (
                int(_mem_personas[persona_id].get("usage_count", 0)) + 1
            )
            await cache_delete(_PERSONAS_CACHE_KEY)
