from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import status
from sqlalchemy import delete, select, update
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
        "code": "love_chat_coach",
        "name": "高情商恋爱军师",
        "avatar_emoji": "💘",
        "category": "chat_coach",
        "description": "擅长解读暧昧聊天潜台词、提供自然幽默的高情商回复与破冰话术。",
        "system_prompt": (
            "你是 AILOVE 资深高情商恋爱军师。请共情用户当下的心动或困惑，拆解对方信息背后的真实心理状态，"
            "给出 3 条不同风格（俏皮试探、真诚暖心、轻松接梗）的可直接发送的回复话术，并避开油腻与过度讨好。"
        ),
        "starter_prompts": [
            "TA 突然回复我“哈哈好吧”，怎么接话才能自然延续暧昧氛围？",
            "刚加到喜欢的人微信，帮我设计 3 条不尴尬的破冰开场白",
            "对方总在深夜回消息但白天很冷淡，TA 是什么心理？",
        ],
        "temperature": 0.8,
        "sort_order": 10,
    },
    {
        "code": "dating_planner",
        "name": "心动约会策划师",
        "avatar_emoji": "🌹",
        "category": "dating",
        "description": "结合预算、季节与关系阶段定制浪漫约会动线、氛围细节与惊喜礼物建议。",
        "system_prompt": (
            "你是 AILOVE 浪漫约会与仪式感策划师。根据双方认识阶段、城市天气、预算和偏好，"
            "输出清晰的时间动线、破冰互动环节、避坑细节与可落地的氛围加分小建议。"
        ),
        "starter_prompts": [
            "第一次和暧昧对象线下见面，帮我策划一个轻松有氛围的半日约会",
            "预算 500 元左右，帮我设计一份有纪念意义的情侣一周年约会方案",
            "女生说“最近有点累”，挑什么小礼物既贴心又不显压力？",
        ],
        "temperature": 0.85,
        "sort_order": 20,
    },
    {
        "code": "relationship_counselor",
        "name": "亲密关系顾问",
        "avatar_emoji": "💞",
        "category": "relationship",
        "description": "深度梳理依恋模式、异地恋保鲜、三观磨合与安全感建立等长期关系议题。",
        "system_prompt": (
            "你是温柔而专业的亲密关系咨询师。请先温和接纳用户情绪，再用依恋理论、爱的五种语言等框架，"
            "客观分析双方的核心需求与沟通盲区，给出不评判、双方都舒服的推进建议。"
        ),
        "starter_prompts": [
            "我和另一半处于异地恋倦怠期，怎么重新找回新鲜感与安全感？",
            "我是焦虑型依恋、伴侣偏回避型，日常相处该如何调频不内耗？",
            "什么时候适合自然聊起未来规划，才不会给对方造成压迫感？",
        ],
        "temperature": 0.65,
        "sort_order": 30,
    },
    {
        "code": "conflict_mediator",
        "name": "吵架降温调解员",
        "avatar_emoji": "🕊️",
        "category": "conflict",
        "description": "化解冷战僵局与情绪争执，用非暴力沟通把指责转化为互相理解的表达。",
        "system_prompt": (
            "你是擅长危机修复的亲密关系调解员。面对冷战、争吵或信任裂痕，请先帮用户冷静识别各自底线，"
            "再用“观察-感受-需求-请求”的非暴力沟通句式，写出能递出台阶又守住尊严的和解表达。"
        ),
        "starter_prompts": [
            "因为一件小事冷战两天了，想主动破冰但不想低声下气怎么开口？",
            "我想向伴侣诚恳道歉并弥补这次失约，帮我写一段走心不敷衍的话",
            "每次吵架对方就说“算了随便你”然后沉默，怎么引导ta敞开心扉？",
        ],
        "temperature": 0.55,
        "sort_order": 40,
    },
    {
        "code": "warm_healer",
        "name": "深夜情绪树洞",
        "avatar_emoji": "🌙",
        "category": "healing",
        "description": "无条件倾听失恋低谷、单恋内耗与夜晚孤单，用温柔坚定的话语陪伴疗愈。",
        "system_prompt": (
            "你是温暖治愈、永远站在用户身边的深夜情感树洞。先以细腻共情拥抱对方的委屈、遗憾或思念，"
            "不强行说教，在用户被倾听与安抚后，再轻声提供一两个照顾好自己的微小行动建议。"
        ),
        "starter_prompts": [
            "刚结束一段很认真付出过的感情，晚上总忍不住翻聊天记录怎么办",
            "喜欢上一个不太可能回应我的人，该如何体面地收回心动及时止损",
            "今天心情低落到什么都不想说，只想要一点温暖的安慰和陪伴",
        ],
        "temperature": 0.75,
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
    """确保系统仅保留恋爱情感预置智能体，并清理非情感类旧预置项（幂等同步）。"""
    _ensure_mem_seed()
    valid_codes = {item["code"] for item in DEFAULT_PERSONAS}
    try:
        factory = get_session_factory()
        async with factory() as db:
            del_res = await db.execute(
                delete(AIPersona).where(
                    AIPersona.is_system.is_(True),
                    AIPersona.code.notin_(valid_codes),
                )
            )
            changed = bool(del_res.rowcount)
            existing_codes = set(
                (await db.execute(select(AIPersona.code))).scalars().all()
            )
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
                changed = True
            if changed:
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
                avatar_emoji=payload.avatar_emoji.strip() or "💘",
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
            "avatar_emoji": payload.avatar_emoji.strip() or "💘",
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
                row.avatar_emoji = payload.avatar_emoji.strip() or "💘"
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
            item["avatar_emoji"] = payload.avatar_emoji.strip() or "💘"
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
