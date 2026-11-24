from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.mysql import get_session_factory
from app.db.redis import cache_delete, cache_get_json, cache_set_json
from app.models.love_profile import UserLoveProfile

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300
_mem_profiles: dict[str, dict[str, Any]] = {}

RELATIONSHIP_STAGES: tuple[dict[str, str], ...] = (
    {"code": "single_crush", "label": "暗恋观察期", "emoji": "🌱"},
    {"code": "ambiguous", "label": "暧昧升温期", "emoji": "✨"},
    {"code": "in_love", "label": "热恋甜蜜期", "emoji": "💞"},
    {"code": "long_distance", "label": "异地相处期", "emoji": "🚄"},
    {"code": "cold_war", "label": "争吵冷战修复", "emoji": "🧊"},
    {"code": "breakup_healing", "label": "失恋疗愈期", "emoji": "🌙"},
    {"code": "married", "label": "长期稳定/伴侣", "emoji": "🏡"},
)

_STAGE_LABEL_MAP: dict[str, str] = {item["code"]: item["label"] for item in RELATIONSHIP_STAGES}

PARTNER_TRAIT_PRESETS: tuple[str, ...] = (
    "慢热型",
    "回避型依恋",
    "嘴硬心软",
    "工作忙回复慢",
    "细节控",
    "情绪敏感",
    "直球理性",
    "爱吃醋",
)

MY_TRAIT_PRESETS: tuple[str, ...] = (
    "容易内耗",
    "焦虑型依恋",
    "直球真诚",
    "不善表达",
    "容易心软",
    "注重仪式感",
)


def _owner_scope(user_type: str, user_id: int) -> str:
    return f"{(user_type or 'web')[:16]}:{int(user_id or 0)}"


def _cache_key(owner_scope: str) -> str:
    return f"ailove:love_profile:{owner_scope}"


def _clean_tags(raw: list[str] | None, *, max_count: int = 8) -> list[str]:
    if not raw:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in raw:
        tag = str(item or "").strip()[:24]
        if tag and tag not in seen:
            seen.add(tag)
            result.append(tag)
        if len(result) >= max_count:
            break
    return result


def _parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return _clean_tags([str(x) for x in parsed])
    except Exception:
        pass
    return []


def _compute_is_configured(data: dict[str, Any]) -> bool:
    return any(
        [
            bool(data.get("relationship_stage")),
            bool(data.get("partner_nickname")),
            bool(data.get("partner_traits")),
            bool(data.get("my_traits")),
            bool(data.get("relationship_goal")),
            bool(data.get("communication_taboos")),
            bool(data.get("background_notes")),
        ]
    )


def _empty_profile(owner_scope: str) -> dict[str, Any]:
    return {
        "owner_scope": owner_scope,
        "relationship_stage": "",
        "relationship_stage_label": "",
        "partner_nickname": "",
        "partner_traits": [],
        "my_traits": [],
        "relationship_goal": "",
        "communication_taboos": "",
        "background_notes": "",
        "auto_inject": True,
        "is_configured": False,
        "updated_at": None,
    }


def _serialize_model(row: UserLoveProfile) -> dict[str, Any]:
    stage = row.relationship_stage or ""
    data: dict[str, Any] = {
        "owner_scope": row.owner_scope,
        "relationship_stage": stage,
        "relationship_stage_label": _STAGE_LABEL_MAP.get(stage, ""),
        "partner_nickname": row.partner_nickname or "",
        "partner_traits": _parse_json_list(row.partner_traits_json),
        "my_traits": _parse_json_list(row.my_traits_json),
        "relationship_goal": row.relationship_goal or "",
        "communication_taboos": row.communication_taboos or "",
        "background_notes": row.background_notes or "",
        "auto_inject": bool(row.auto_inject),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    data["is_configured"] = _compute_is_configured(data)
    return data


def get_love_profile_presets() -> dict[str, Any]:
    return {
        "stages": list(RELATIONSHIP_STAGES),
        "partner_trait_presets": list(PARTNER_TRAIT_PRESETS),
        "my_trait_presets": list(MY_TRAIT_PRESETS),
    }


async def get_love_profile(user_type: str, user_id: int) -> dict[str, Any]:
    """读取当前用户的个人情感档案记忆卡（优先缓存 -> MySQL -> 内存降级）。"""
    owner = _owner_scope(user_type, user_id)
    cached = await cache_get_json(_cache_key(owner))
    if isinstance(cached, dict) and cached.get("owner_scope") == owner:
        return cached

    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    select(UserLoveProfile).where(UserLoveProfile.owner_scope == owner)
                )
            ).scalar_one_or_none()
            data = _serialize_model(row) if row is not None else _empty_profile(owner)
            await cache_set_json(_cache_key(owner), data, ttl_seconds=_CACHE_TTL_SECONDS)
            return data
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("Love profile DB read fallback to mem: %s", exc)
        rec = _mem_profiles.get(owner)
        return dict(rec) if rec else _empty_profile(owner)


async def upsert_love_profile(
    user_type: str,
    user_id: int,
    *,
    relationship_stage: str = "",
    partner_nickname: str = "",
    partner_traits: list[str] | None = None,
    my_traits: list[str] | None = None,
    relationship_goal: str = "",
    communication_taboos: str = "",
    background_notes: str = "",
    auto_inject: bool = True,
) -> dict[str, Any]:
    """保存或更新当前用户的个人情感档案记忆卡。"""
    utype = (user_type or "web")[:16]
    uid = int(user_id or 0)
    owner = _owner_scope(utype, uid)

    clean_stage = relationship_stage.strip()
    if clean_stage and clean_stage not in _STAGE_LABEL_MAP:
        clean_stage = ""
    clean_nick = partner_nickname.strip()[:32]
    clean_partner_traits = _clean_tags(partner_traits)
    clean_my_traits = _clean_tags(my_traits)
    clean_goal = relationship_goal.strip()[:160]
    clean_taboos = communication_taboos.strip()[:300]
    clean_notes = background_notes.strip()[:1200]
    clean_auto = bool(auto_inject)

    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    select(UserLoveProfile).where(UserLoveProfile.owner_scope == owner)
                )
            ).scalar_one_or_none()
            if row is None:
                row = UserLoveProfile(
                    owner_scope=owner,
                    user_type=utype,
                    user_id=uid,
                )
                session.add(row)
            row.relationship_stage = clean_stage
            row.partner_nickname = clean_nick
            row.partner_traits_json = json.dumps(clean_partner_traits, ensure_ascii=False)
            row.my_traits_json = json.dumps(clean_my_traits, ensure_ascii=False)
            row.relationship_goal = clean_goal
            row.communication_taboos = clean_taboos
            row.background_notes = clean_notes
            row.auto_inject = clean_auto
            await session.commit()
            await session.refresh(row)
            data = _serialize_model(row)
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("Love profile DB write fallback to mem: %s", exc)
        data = {
            "owner_scope": owner,
            "relationship_stage": clean_stage,
            "relationship_stage_label": _STAGE_LABEL_MAP.get(clean_stage, ""),
            "partner_nickname": clean_nick,
            "partner_traits": clean_partner_traits,
            "my_traits": clean_my_traits,
            "relationship_goal": clean_goal,
            "communication_taboos": clean_taboos,
            "background_notes": clean_notes,
            "auto_inject": clean_auto,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        data["is_configured"] = _compute_is_configured(data)
        _mem_profiles[owner] = data

    await cache_set_json(_cache_key(owner), data, ttl_seconds=_CACHE_TTL_SECONDS)
    return data


async def clear_love_profile(user_type: str, user_id: int) -> dict[str, Any]:
    """一键清空当前用户的情感档案记忆卡。"""
    owner = _owner_scope(user_type, user_id)
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    select(UserLoveProfile).where(UserLoveProfile.owner_scope == owner)
                )
            ).scalar_one_or_none()
            if row is not None:
                await session.delete(row)
                await session.commit()
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("Love profile DB delete fallback to mem: %s", exc)
    _mem_profiles.pop(owner, None)
    await cache_delete(_cache_key(owner))
    return _empty_profile(owner)


def build_love_profile_prompt(profile: dict[str, Any]) -> str:
    """将用户情感背景记忆卡格式化为简洁、可执行的系统提示词上下文。"""
    if not profile or not profile.get("is_configured"):
        return ""

    lines: list[str] = [
        "[用户个人情感背景记忆卡 — 请结合以下真实处境给出贴合个体的建议，不必让用户重复交代]"
    ]
    stage_label = profile.get("relationship_stage_label") or _STAGE_LABEL_MAP.get(
        str(profile.get("relationship_stage", "")), ""
    )
    if stage_label:
        lines.append(f"- 当前关系阶段：{stage_label}")
    if profile.get("partner_nickname"):
        lines.append(f"- 对方称呼：{profile['partner_nickname']}")
    if profile.get("partner_traits"):
        lines.append(f"- 对方性格/依恋特点：{'、'.join(profile['partner_traits'])}")
    if profile.get("my_traits"):
        lines.append(f"- 用户自身沟通特点：{'、'.join(profile['my_traits'])}")
    if profile.get("relationship_goal"):
        lines.append(f"- 当前核心情感目标：{profile['relationship_goal']}")
    if profile.get("communication_taboos"):
        lines.append(f"- 沟通雷区与注意事项：{profile['communication_taboos']}")
    if profile.get("background_notes"):
        lines.append(f"- 补充背景摘要：{profile['background_notes']}")
    return "\n".join(lines)
