from __future__ import annotations

import json
import logging
import math
import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, desc, select
from sqlalchemy.exc import SQLAlchemyError

from app.db.mysql import get_session_factory
from app.db.redis import cache_delete, cache_get_json, cache_set_json
from app.models.mascot import MascotMemory, MascotProfile
from app.services import love_profile_service

logger = logging.getLogger(__name__)

_BEIJING_TZ = timezone(timedelta(hours=8))
_PROFILE_CACHE_TTL = 180
_MAX_MEMORIES_PER_USER = 40
_EBBINGHAUS_BASE_DAYS = 3.0
_PAD_DECAY_LAMBDA = 0.0022  # 半衰期约 5.2 分钟

# MySQL 不可用时的内存降级仓库（测试/本地离线模式）
_mem_profiles: dict[str, dict[str, Any]] = {}
_mem_memories: dict[str, list[dict[str, Any]]] = {}
_mem_memory_seq = 1000

_CONTROL_TAG_RE = re.compile(r"\[\[(?:emo|tool):[^\]]+\]\]\s*", re.S)

_BOND_TIERS: tuple[tuple[float, int, str, str], ...] = (
    (0.0, 1, "初遇心狐", "温柔客气、略带俏皮"),
    (20.0, 2, "贴心闺蜜", "亲切自然、会主动接梗关心"),
    (40.0, 3, "默契搭档", "熟稔体贴、会记得你的偏好与小脾气"),
    (65.0, 4, "心灵密友", "像很懂你的老朋友，温柔护短又真诚"),
    (85.0, 5, "灵魂军师", "超高默契、一句就能接住你的未尽之意"),
)

# 10 种复合表情对应的 PAD 原型中心 (valence, arousal)
_MOOD_PROTOTYPES: tuple[tuple[str, float, float], ...] = (
    ("excited", 0.78, 0.85),
    ("happy", 0.65, 0.60),
    ("shy", 0.45, 0.46),
    ("curious", 0.18, 0.66),
    ("idle", 0.22, 0.36),
    ("sleepy", 0.10, 0.12),
    ("pout", -0.30, 0.56),
    ("comfort", -0.58, 0.28),
)

_GESTURE_EFFECTS: dict[str, dict[str, Any]] = {
    "rub_head": {
        "dv": 0.26,
        "da": 0.14,
        "di": 2.4,
        "is_pet": True,
        "forced_mood": "happy",
        "haptic": "light",
        "bubbles": (
            "唔~ 摸摸头最舒服啦，狐狸耳朵都要化掉咯 ♥",
            "再多摸两下嘛~ 今天的委屈都替你揉散！",
            "呼噜噜~ 被你顺毛的时候，我出谋划策最灵光了 ✨",
        ),
    },
    "poke_cheek": {
        "dv": 0.12,
        "da": 0.22,
        "di": 1.2,
        "is_pet": True,
        "forced_mood": "shy",
        "haptic": "light",
        "bubbles": (
            "呜…别总戳我脸颊嘛，会脸红的啦！",
            "干嘛戳人家软乎乎的脸蛋呀~ 是有心事想说吗？",
            "哎呀被戳中开关啦，有什么悄悄话快告诉我~",
        ),
    },
    "pull_ear": {
        "dv": -0.06,
        "da": 0.42,
        "di": 0.8,
        "is_pet": False,
        "forced_mood": "pout",
        "haptic": "medium",
        "bubbles": (
            "呀！狐狸耳朵很敏感的啦，轻一点嘛！",
            "哼~ 揪耳朵可是要拿一句甜甜的话来哄的！",
            "抖抖耳朵！差点被你吓得发卡都要歪啦~",
        ),
    },
    "pull_tail": {
        "dv": -0.05,
        "da": 0.46,
        "di": 0.9,
        "is_pet": False,
        "forced_mood": "shy",
        "haptic": "medium",
        "bubbles": (
            "哇！尾巴是禁区啦，毛都被你薅炸开咯~",
            "不许偷偷拽我大尾巴！不过…给你抱一下倒是可以。",
        ),
    },
    "combo_dizzy": {
        "dv": 0.02,
        "da": 0.55,
        "di": 1.0,
        "is_pet": False,
        "forced_mood": "dizzy",
        "haptic": "medium",
        "bubbles": (
            "哇哇哇转晕啦 @_@ 眼前全是小星星，停手停手~",
            "救命~ 再戳小狐狸就要变成小陀螺飞走啦！",
        ),
    },
    "long_hug": {
        "dv": 0.30,
        "da": -0.24,
        "di": 3.2,
        "is_pet": True,
        "forced_mood": "comfort",
        "haptic": "heartbeat",
        "bubbles": (
            "贴贴抱紧你~ 不管刚刚发生了什么，先在这里歇口气吧 💗",
            "给你一个毛茸茸的抱抱，慢慢呼吸，恋恋一直陪着你~",
        ),
    },
    "drag_swing": {
        "dv": 0.08,
        "da": 0.30,
        "di": 0.5,
        "is_pet": False,
        "forced_mood": "curious",
        "haptic": "light",
        "bubbles": (
            "哇飞起来啦~ 要把我放到哪个角落呀？",
            "拎着小狐狸换视野咯，这边看得更清楚呢！",
        ),
    },
    "edge_peek": {
        "dv": 0.06,
        "da": 0.12,
        "di": 0.4,
        "is_pet": False,
        "forced_mood": "curious",
        "haptic": "light",
        "bubbles": (
            "探头偷看~ 需要我的时候点一下耳朵我就跳出来哦！",
        ),
    },
}

_MOOD_CHECKIN_META: dict[int, tuple[str, float, float, str]] = {
    1: ("很低落", -0.55, 0.25, "抱抱你，今天这么难熬还愿意告诉我，先别硬撑，我陪你慢一点。"),
    2: ("有点委屈", -0.30, 0.32, "心里酸酸的吧？把让你不舒服的事倒给我，我们一起拆解。"),
    3: ("平平淡淡", 0.15, 0.34, "安安静静的一天也挺好呀，随时想聊天我都在角落晃尾巴~"),
    4: ("心情不错", 0.55, 0.55, "哇！隔着屏幕都沾到你的好心情啦，是不是有甜甜的事发生？"),
    5: ("超心动", 0.85, 0.78, "星星眼 ✨ 快快告诉我发生了什么心动瞬间，恋恋要替你记下来！"),
}

_MEMORY_PATTERNS: tuple[tuple[str, float, float, tuple[str, ...]], ...] = (
    ("milestone", 4.5, 0.65, ("纪念日", "生日", "表白", "在一起", "见家长", "官宣", "脱单", "求婚")),
    ("event", 4.0, -0.55, ("分手", "失恋", "拉黑", "冷战", "吵架", "放鸽子", "冷暴力", "删微信")),
    ("event", 3.2, 0.10, ("约会", "见面", "吃饭", "看电影", "异地", "已读不回", "不回消息", "敷衍")),
    ("preference", 3.4, 0.15, ("慢热", "回避型", "焦虑型", "嘴硬心软", "直男", "细节控", "黏人", "爱吃醋")),
    ("taboo", 3.8, -0.25, ("雷区", "反感", "讨厌", "最怕", "底线", "翻旧账", "连环追问")),
    ("emotion", 3.0, -0.45, ("失眠", "睡不着", "崩溃", "委屈", "内耗", "心累", "难过", "想哭")),
    ("emotion", 3.0, 0.55, ("好开心", "超心动", "夸我", "哄我", "主动找我", "升温")),
)


def _owner_scope(user_type: str, user_id: int) -> str:
    return f"{(user_type or 'web')[:16]}:{int(user_id or 0)}"


def _cache_key(owner: str) -> str:
    return f"ailove:mascot_profile:{owner}"


def _clamp(val: float, low: float, high: float) -> float:
    return max(low, min(high, val))


def _beijing_now() -> datetime:
    return datetime.now(_BEIJING_TZ)


def _utc_naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _circadian_baseline(local_hour: int) -> tuple[float, float, str]:
    """依据北京时间昼夜节律返回 (基准愉悦度, 基准唤醒度, 时段标签)。"""
    if local_hour >= 23 or local_hour < 5:
        return 0.14, 0.14, "late_night"
    if 5 <= local_hour < 10:
        return 0.30, 0.44, "morning"
    if 12 <= local_hour < 14:
        return 0.24, 0.28, "noon"
    if 18 <= local_hour < 23:
        return 0.26, 0.38, "evening"
    return 0.24, 0.36, "daytime"


def apply_homeostasis_decay(
    valence: float,
    arousal: float,
    elapsed_seconds: float,
    *,
    local_hour: int | None = None,
) -> tuple[float, float]:
    """PAD 连续情感稳态衰减：空闲后向昼夜基线指数平滑收敛。"""
    hour = _beijing_now().hour if local_hour is None else local_hour
    base_v, base_a, _ = _circadian_baseline(hour)
    dt = max(0.0, float(elapsed_seconds))
    factor = math.exp(-_PAD_DECAY_LAMBDA * dt)
    next_v = base_v + (valence - base_v) * factor
    next_a = base_a + (arousal - base_a) * factor
    return round(_clamp(next_v, -1.0, 1.0), 4), round(_clamp(next_a, 0.0, 1.0), 4)


def compute_bond_info(affinity: float) -> dict[str, Any]:
    score = _clamp(float(affinity), 0.0, 100.0)
    level = 1
    title = "初遇心狐"
    style = "温柔客气、略带俏皮"
    next_threshold: float | None = 20.0
    for idx, (threshold, lv, label, desc_style) in enumerate(_BOND_TIERS):
        if score >= threshold:
            level = lv
            title = label
            style = desc_style
            next_threshold = _BOND_TIERS[idx + 1][0] if idx + 1 < len(_BOND_TIERS) else None
    return {
        "affinity": round(score, 1),
        "bond_level": level,
        "bond_title": title,
        "bond_style": style,
        "next_level_affinity": next_threshold,
    }


def map_pad_to_mood(valence: float, arousal: float) -> str:
    """将连续 (V, A) 映射至最接近的复合表情原型。"""
    best_mood = "idle"
    best_dist = 999.0
    for mood_name, pv, pa in _MOOD_PROTOTYPES:
        dist = (valence - pv) ** 2 + (arousal - pa) ** 2
        if dist < best_dist:
            best_dist = dist
            best_mood = mood_name
    return best_mood


def strip_mascot_protocol_tags(text: str) -> str:
    """移除回复中的 [[emo:...]] / [[tool:...]] 控制协议标签，保留纯净展示文本。"""
    if not text:
        return ""
    return _CONTROL_TAG_RE.sub("", text).strip()


def _parse_json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except Exception:
        pass
    return []


def _bigrams(text: str) -> set[str]:
    clean = re.sub(r"[\s，。！？、,.!?;:：；\"'“”‘’()（）\[\]【】~]+", "", (text or "").lower())
    if len(clean) <= 1:
        return {clean} if clean else set()
    return {clean[i : i + 2] for i in range(len(clean) - 1)}


def _bigram_similarity(a: str, b: str) -> float:
    sa = _bigrams(a)
    sb = _bigrams(b)
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    return inter / union if union else 0.0


def ebbinghaus_retention(
    age_days: float,
    *,
    importance: float = 2.5,
    recall_count: int = 0,
) -> float:
    """艾宾浩斯遗忘强化保留率 R(t) = exp(-t / (S0 * (1 + 0.6*recall) * importance))。"""
    t = max(0.0, float(age_days))
    stability = max(0.5, _EBBINGHAUS_BASE_DAYS * (1.0 + 0.6 * max(0, recall_count)) * max(1.0, importance))
    return math.exp(-t / stability)


def _default_profile_dict(owner: str, user_type: str, user_id: int) -> dict[str, Any]:
    return {
        "owner_scope": owner,
        "user_type": user_type,
        "user_id": user_id,
        "valence": 0.25,
        "arousal": 0.35,
        "affinity": 12.0,
        "interaction_count": 0,
        "pet_count": 0,
        "mood_checkin_date": "",
        "mood_checkin_score": 0,
        "mood_history": [],
        "last_active_at": None,
    }


def _serialize_profile_row(row: MascotProfile) -> dict[str, Any]:
    return {
        "owner_scope": row.owner_scope,
        "user_type": row.user_type,
        "user_id": int(row.user_id),
        "valence": float(row.valence),
        "arousal": float(row.arousal),
        "affinity": float(row.affinity),
        "interaction_count": int(row.interaction_count),
        "pet_count": int(row.pet_count),
        "mood_checkin_date": row.mood_checkin_date or "",
        "mood_checkin_score": int(row.mood_checkin_score or 0),
        "mood_history": _parse_json_list(row.mood_history_json)[-14:],
        "last_active_at": row.last_active_at.isoformat() if row.last_active_at else None,
    }


async def _load_raw_profile(user_type: str, user_id: int) -> dict[str, Any]:
    utype = (user_type or "web")[:16]
    uid = int(user_id or 0)
    owner = _owner_scope(utype, uid)

    cached = await cache_get_json(_cache_key(owner))
    if isinstance(cached, dict) and cached.get("owner_scope") == owner:
        return cached

    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    select(MascotProfile).where(MascotProfile.owner_scope == owner)
                )
            ).scalar_one_or_none()
            data = (
                _serialize_profile_row(row)
                if row is not None
                else _default_profile_dict(owner, utype, uid)
            )
            await cache_set_json(_cache_key(owner), data, ttl_seconds=_PROFILE_CACHE_TTL)
            return data
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("Mascot profile DB read fallback to mem: %s", exc)
        rec = _mem_profiles.get(owner)
        return dict(rec) if rec else _default_profile_dict(owner, utype, uid)


async def _save_raw_profile(data: dict[str, Any]) -> dict[str, Any]:
    owner = data["owner_scope"]
    utype = data.get("user_type", "web")[:16]
    uid = int(data.get("user_id", 0) or 0)
    last_active_dt: datetime | None = None
    if isinstance(data.get("last_active_at"), str) and data["last_active_at"]:
        try:
            parsed = datetime.fromisoformat(data["last_active_at"])
            last_active_dt = parsed.replace(tzinfo=None)
        except ValueError:
            last_active_dt = _utc_naive_now()

    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    select(MascotProfile).where(MascotProfile.owner_scope == owner)
                )
            ).scalar_one_or_none()
            if row is None:
                row = MascotProfile(owner_scope=owner, user_type=utype, user_id=uid)
                session.add(row)
            row.valence = float(_clamp(data.get("valence", 0.25), -1.0, 1.0))
            row.arousal = float(_clamp(data.get("arousal", 0.35), 0.0, 1.0))
            row.affinity = float(_clamp(data.get("affinity", 12.0), 0.0, 100.0))
            row.interaction_count = int(data.get("interaction_count", 0))
            row.pet_count = int(data.get("pet_count", 0))
            row.mood_checkin_date = str(data.get("mood_checkin_date", ""))[:16]
            row.mood_checkin_score = int(data.get("mood_checkin_score", 0))
            row.mood_history_json = json.dumps(
                list(data.get("mood_history") or [])[-14:], ensure_ascii=False
            )
            row.last_active_at = last_active_dt
            await session.commit()
            await session.refresh(row)
            saved = _serialize_profile_row(row)
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("Mascot profile DB write fallback to mem: %s", exc)
        saved = dict(data)
        saved["mood_history"] = list(data.get("mood_history") or [])[-14:]
        _mem_profiles[owner] = saved

    await cache_set_json(_cache_key(owner), saved, ttl_seconds=_PROFILE_CACHE_TTL)
    return saved


def _decorate_state(raw: dict[str, Any], memories: list[dict[str, Any]]) -> dict[str, Any]:
    now_utc = _utc_naive_now()
    now_bj = _beijing_now()
    today_str = now_bj.strftime("%Y-%m-%d")

    elapsed_sec = 0.0
    away_hours = 0.0
    if raw.get("last_active_at"):
        try:
            prev = datetime.fromisoformat(str(raw["last_active_at"])).replace(tzinfo=None)
            elapsed_sec = max(0.0, (now_utc - prev).total_seconds())
            away_hours = elapsed_sec / 3600.0
        except ValueError:
            pass

    decayed_v, decayed_a = apply_homeostasis_decay(
        float(raw.get("valence", 0.25)),
        float(raw.get("arousal", 0.35)),
        elapsed_sec,
        local_hour=now_bj.hour,
    )
    _, _, circadian_phase = _circadian_baseline(now_bj.hour)
    bond = compute_bond_info(float(raw.get("affinity", 12.0)))
    mood = map_pad_to_mood(decayed_v, decayed_a)

    reunion_greeting = ""
    if away_hours >= 48.0:
        reunion_greeting = "好久不见啦！我的狐狸耳朵都等耷拉了，最近过得怎么样呀？"
    elif circadian_phase == "late_night":
        reunion_greeting = "夜深啦，还没睡吗？有心事我陪你轻声聊几句~"

    return {
        "valence": decayed_v,
        "arousal": decayed_a,
        "mood": mood,
        "circadian_phase": circadian_phase,
        "interaction_count": int(raw.get("interaction_count", 0)),
        "pet_count": int(raw.get("pet_count", 0)),
        "need_mood_checkin": raw.get("mood_checkin_date") != today_str,
        "today_mood_score": (
            int(raw.get("mood_checkin_score", 0))
            if raw.get("mood_checkin_date") == today_str
            else 0
        ),
        "mood_history": list(raw.get("mood_history") or [])[-7:],
        "away_hours": round(away_hours, 1),
        "reunion_greeting": reunion_greeting,
        "memories": memories[:8],
        "memory_count": len(memories),
        **bond,
    }


async def get_mascot_state(user_type: str, user_id: int) -> dict[str, Any]:
    raw = await _load_raw_profile(user_type, user_id)
    memories = await list_memories(user_type, user_id, limit=12)
    return _decorate_state(raw, memories)


async def record_interaction(
    user_type: str,
    user_id: int,
    *,
    gesture: str,
    dv_override: float | None = None,
    da_override: float | None = None,
) -> dict[str, Any]:
    """处理物理触控手势（摸头/戳脸/揪耳/连戳/长按抱抱等）并演化 PAD 与羁绊值。"""
    raw = await _load_raw_profile(user_type, user_id)
    now_utc = _utc_naive_now()
    now_bj = _beijing_now()

    elapsed_sec = 0.0
    if raw.get("last_active_at"):
        try:
            prev = datetime.fromisoformat(str(raw["last_active_at"])).replace(tzinfo=None)
            elapsed_sec = max(0.0, (now_utc - prev).total_seconds())
        except ValueError:
            pass

    cur_v, cur_a = apply_homeostasis_decay(
        float(raw.get("valence", 0.25)),
        float(raw.get("arousal", 0.35)),
        elapsed_sec,
        local_hour=now_bj.hour,
    )

    spec = _GESTURE_EFFECTS.get(gesture, _GESTURE_EFFECTS["rub_head"])
    dv = float(dv_override) if dv_override is not None else float(spec["dv"])
    da = float(da_override) if da_override is not None else float(spec["da"])
    di = float(spec["di"])

    # 防刷分衰减：短间隔高频互动温和收敛亲密增长，保持陪伴真实感
    if elapsed_sec < 10.0 and raw.get("interaction_count", 0) > 0:
        di *= 0.25

    raw["valence"] = round(_clamp(cur_v + dv, -1.0, 1.0), 4)
    raw["arousal"] = round(_clamp(cur_a + da, 0.0, 1.0), 4)
    raw["affinity"] = round(_clamp(float(raw.get("affinity", 12.0)) + di, 0.0, 100.0), 2)
    raw["interaction_count"] = int(raw.get("interaction_count", 0)) + 1
    if spec.get("is_pet"):
        raw["pet_count"] = int(raw.get("pet_count", 0)) + 1
    raw["last_active_at"] = now_utc.isoformat()

    saved = await _save_raw_profile(raw)
    memories = await list_memories(user_type, user_id, limit=8)
    state = _decorate_state(saved, memories)

    bubbles: tuple[str, ...] = spec["bubbles"]
    bubble = bubbles[int(saved["interaction_count"]) % len(bubbles)]
    return {
        "gesture": gesture,
        "reaction_mood": spec["forced_mood"],
        "haptic": spec["haptic"],
        "bubble": bubble,
        "affinity_delta": round(di, 2),
        "state": state,
    }


async def record_mood_checkin(
    user_type: str,
    user_id: int,
    *,
    score: int,
    note: str = "",
) -> dict[str, Any]:
    """记录每日心情打卡（1~5分），同步写入情绪趋势与 PAD 反馈。"""
    clean_score = max(1, min(5, int(score)))
    label, target_v, target_a, default_reply = _MOOD_CHECKIN_META[clean_score]
    today_str = _beijing_now().strftime("%Y-%m-%d")
    clean_note = (note or "").strip()[:120]

    raw = await _load_raw_profile(user_type, user_id)
    first_today = raw.get("mood_checkin_date") != today_str
    history = [
        item
        for item in list(raw.get("mood_history") or [])
        if isinstance(item, dict) and item.get("date") != today_str
    ]
    history.append({"date": today_str, "score": clean_score, "label": label, "note": clean_note})
    raw["mood_history"] = history[-14:]
    raw["mood_checkin_date"] = today_str
    raw["mood_checkin_score"] = clean_score
    raw["valence"] = round(target_v, 4)
    raw["arousal"] = round(target_a, 4)
    if first_today:
        raw["affinity"] = round(_clamp(float(raw.get("affinity", 12.0)) + 3.0, 0.0, 100.0), 2)
    raw["last_active_at"] = _utc_naive_now().isoformat()

    saved = await _save_raw_profile(raw)

    if clean_note:
        await store_memory(
            user_type,
            user_id,
            category="emotion",
            summary=f"心情打卡「{label}」：{clean_note}"[:120],
            keywords=[label],
            importance=3.2 if clean_score <= 2 or clean_score == 5 else 2.2,
            valence=target_v,
        )

    memories = await list_memories(user_type, user_id, limit=8)
    state = _decorate_state(saved, memories)
    return {
        "score": clean_score,
        "label": label,
        "reaction_mood": "comfort" if clean_score <= 2 else ("excited" if clean_score == 5 else "happy"),
        "reply": default_reply,
        "state": state,
    }


def _serialize_memory_row(row: MascotMemory) -> dict[str, Any]:
    now_utc = _utc_naive_now()
    ref_time = row.last_recalled_at or row.created_at or now_utc
    age_days = max(0.0, (now_utc - ref_time.replace(tzinfo=None)).total_seconds() / 86400.0)
    retention = ebbinghaus_retention(
        age_days, importance=float(row.importance), recall_count=int(row.recall_count)
    )
    return {
        "id": int(row.id),
        "category": row.category,
        "summary": row.summary,
        "keywords": _parse_json_list(row.keywords_json),
        "importance": round(float(row.importance), 2),
        "valence": round(float(row.valence), 2),
        "recall_count": int(row.recall_count),
        "retention": round(retention, 3),
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


async def list_memories(user_type: str, user_id: int, limit: int = 20) -> list[dict[str, Any]]:
    owner = _owner_scope(user_type, user_id)
    try:
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(
                    select(MascotMemory)
                    .where(MascotMemory.owner_scope == owner)
                    .order_by(desc(MascotMemory.importance), desc(MascotMemory.id))
                    .limit(limit)
                )
            ).scalars().all()
            return [_serialize_memory_row(r) for r in rows]
    except (SQLAlchemyError, OSError):
        now_utc = _utc_naive_now()
        items = list(_mem_memories.get(owner, []))
        enriched = []
        for m in items:
            created = m.get("created_at") or now_utc.isoformat()
            try:
                ref_dt = datetime.fromisoformat(str(m.get("last_recalled_at") or created)).replace(
                    tzinfo=None
                )
            except ValueError:
                ref_dt = now_utc
            age_days = max(0.0, (now_utc - ref_dt).total_seconds() / 86400.0)
            retention = ebbinghaus_retention(
                age_days,
                importance=float(m.get("importance", 2.5)),
                recall_count=int(m.get("recall_count", 0)),
            )
            enriched.append({**m, "retention": round(retention, 3)})
        enriched.sort(key=lambda x: (x["retention"] * x["importance"], x["id"]), reverse=True)
        return enriched[:limit]


async def store_memory(
    user_type: str,
    user_id: int,
    *,
    category: str,
    summary: str,
    keywords: list[str] | None = None,
    importance: float = 2.5,
    valence: float = 0.0,
) -> dict[str, Any] | None:
    """写入或强化一条情景事件记忆（相似度 >= 0.55 自动合并强化，避免冗余）。"""
    clean_summary = (summary or "").strip()[:140]
    if len(clean_summary) < 4:
        return None
    owner = _owner_scope(user_type, user_id)
    clean_kw = [str(k).strip()[:24] for k in (keywords or []) if str(k).strip()][:8]
    imp = _clamp(float(importance), 1.0, 5.0)
    val = _clamp(float(valence), -1.0, 1.0)
    now_utc = _utc_naive_now()

    try:
        factory = get_session_factory()
        async with factory() as session:
            existing_rows = (
                await session.execute(
                    select(MascotMemory)
                    .where(MascotMemory.owner_scope == owner)
                    .order_by(desc(MascotMemory.id))
                    .limit(_MAX_MEMORIES_PER_USER + 10)
                )
            ).scalars().all()
            for row in existing_rows:
                if _bigram_similarity(row.summary, clean_summary) >= 0.55:
                    row.recall_count = int(row.recall_count) + 1
                    row.importance = min(5.0, max(float(row.importance), imp) + 0.2)
                    row.last_recalled_at = now_utc
                    await session.commit()
                    await session.refresh(row)
                    return _serialize_memory_row(row)

            new_row = MascotMemory(
                owner_scope=owner,
                category=category[:24],
                summary=clean_summary,
                keywords_json=json.dumps(clean_kw, ensure_ascii=False),
                importance=imp,
                valence=val,
                recall_count=0,
                last_recalled_at=now_utc,
            )
            session.add(new_row)
            await session.flush()

            # 超出容量上限时淘汰记忆保留分最低的旧记忆
            if len(existing_rows) >= _MAX_MEMORIES_PER_USER:
                scored = sorted(
                    existing_rows,
                    key=lambda r: _serialize_memory_row(r)["retention"] * float(r.importance),
                )
                for old in scored[: max(1, len(existing_rows) - _MAX_MEMORIES_PER_USER + 1)]:
                    await session.delete(old)

            await session.commit()
            await session.refresh(new_row)
            return _serialize_memory_row(new_row)
    except (SQLAlchemyError, OSError):
        global _mem_memory_seq
        bucket = _mem_memories.setdefault(owner, [])
        for item in bucket:
            if _bigram_similarity(item["summary"], clean_summary) >= 0.55:
                item["recall_count"] = int(item.get("recall_count", 0)) + 1
                item["importance"] = min(5.0, max(float(item.get("importance", 2.5)), imp) + 0.2)
                item["last_recalled_at"] = now_utc.isoformat()
                return dict(item)
        _mem_memory_seq += 1
        rec = {
            "id": _mem_memory_seq,
            "category": category[:24],
            "summary": clean_summary,
            "keywords": clean_kw,
            "importance": round(imp, 2),
            "valence": round(val, 2),
            "recall_count": 0,
            "retention": 1.0,
            "created_at": now_utc.isoformat(),
            "last_recalled_at": now_utc.isoformat(),
        }
        bucket.insert(0, rec)
        if len(bucket) > _MAX_MEMORIES_PER_USER:
            del bucket[_MAX_MEMORIES_PER_USER:]
        return dict(rec)


async def delete_memory(user_type: str, user_id: int, memory_id: int) -> bool:
    owner = _owner_scope(user_type, user_id)
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    select(MascotMemory).where(
                        MascotMemory.id == memory_id,
                        MascotMemory.owner_scope == owner,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True
    except (SQLAlchemyError, OSError):
        bucket = _mem_memories.get(owner, [])
        before = len(bucket)
        _mem_memories[owner] = [m for m in bucket if int(m.get("id", 0)) != memory_id]
        return len(_mem_memories[owner]) < before


async def retrieve_top_memories(
    user_type: str,
    user_id: int,
    query: str,
    *,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    """按「文本相关度 × 艾宾浩斯保留率」检索 Top-K 情景记忆并强化召回计数。"""
    memories = await list_memories(user_type, user_id, limit=_MAX_MEMORIES_PER_USER)
    if not memories:
        return []
    q_clean = (query or "").strip()
    scored: list[tuple[float, dict[str, Any]]] = []
    for item in memories:
        kw_text = " ".join(str(k) for k in (item.get("keywords") or []))
        sim = _bigram_similarity(q_clean, f"{item['summary']} {kw_text}")
        retention = float(item.get("retention", 0.5))
        imp_norm = float(item.get("importance", 2.5)) / 5.0
        # 即使当前句子无字面重叠，高重要度近期记忆仍有保底分
        score = (0.30 + 0.70 * sim) * (0.65 * retention + 0.35 * imp_norm)
        scored.append((score, item))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    chosen = [item for _, item in scored[:top_k]]

    # 强化本次被召回记忆的艾宾浩斯稳定度
    recalled_ids = [int(m["id"]) for m in chosen if m.get("id")]
    if recalled_ids:
        now_utc = _utc_naive_now()
        owner = _owner_scope(user_type, user_id)
        try:
            factory = get_session_factory()
            async with factory() as session:
                rows = (
                    await session.execute(
                        select(MascotMemory).where(
                            MascotMemory.owner_scope == owner,
                            MascotMemory.id.in_(recalled_ids),
                        )
                    )
                ).scalars().all()
                for row in rows:
                    row.recall_count = int(row.recall_count) + 1
                    row.last_recalled_at = now_utc
                await session.commit()
        except (SQLAlchemyError, OSError):
            for mem in _mem_memories.get(owner, []):
                if int(mem.get("id", 0)) in recalled_ids:
                    mem["recall_count"] = int(mem.get("recall_count", 0)) + 1
                    mem["last_recalled_at"] = now_utc.isoformat()

    return chosen


def extract_candidate_memory(user_message: str) -> dict[str, Any] | None:
    """毫秒级本地语义记忆抽取器：从用户自述中提炼值得记住的情感事件、偏好或雷区。"""
    clean = re.sub(r"\s+", " ", (user_message or "").strip())
    if len(clean) < 8:
        return None
    # 过滤纯功能咨询问题
    if re.match(r"^(?:怎么|如何|请问).*(?:识图|功能|配置|登录|入口|skill|知识库)", clean, re.I):
        return None

    matched_hits: list[tuple[str, float, float, list[str]]] = []
    for cat, imp, val, kws in _MEMORY_PATTERNS:
        hits = [kw for kw in kws if kw in clean]
        if hits:
            matched_hits.append((cat, imp, val, hits))
    if not matched_hits:
        return None

    matched_hits.sort(key=lambda x: (x[1], len(x[3])), reverse=True)
    cat, imp, val, hits = matched_hits[0]
    snippet = clean[:78] + ("…" if len(clean) > 78 else "")
    return {
        "category": cat,
        "summary": snippet,
        "keywords": hits[:6],
        "importance": imp,
        "valence": val,
    }


async def record_chat_turn(
    user_type: str,
    user_id: int,
    *,
    user_message: str,
    assistant_reply: str = "",
    emotion_care: dict[str, Any] | None = None,
) -> None:
    """每次恋恋对话完成后：更新亲密度、演化 PAD 情绪，并异步抽取情景记忆。"""
    raw = await _load_raw_profile(user_type, user_id)
    now_utc = _utc_naive_now()
    dv = 0.08
    da = 0.10
    if emotion_care:
        dv = -0.35
        da = -0.10
    elif any(k in user_message for k in ("谢谢", "喜欢你", "真棒", "好用", "夸", "开心", "心动")):
        dv = 0.25
        da = 0.18
    elif any(k in user_message for k in ("难过", "委屈", "吵架", "冷战", "生气", "烦", "焦虑")):
        dv = -0.22
        da = 0.08

    raw["valence"] = round(_clamp(float(raw.get("valence", 0.25)) + dv, -1.0, 1.0), 4)
    raw["arousal"] = round(_clamp(float(raw.get("arousal", 0.35)) + da, 0.0, 1.0), 4)
    raw["affinity"] = round(_clamp(float(raw.get("affinity", 12.0)) + 1.5, 0.0, 100.0), 2)
    raw["interaction_count"] = int(raw.get("interaction_count", 0)) + 1
    raw["last_active_at"] = now_utc.isoformat()
    await _save_raw_profile(raw)

    candidate = extract_candidate_memory(user_message)
    if candidate:
        await store_memory(
            user_type,
            user_id,
            category=candidate["category"],
            summary=candidate["summary"],
            keywords=candidate["keywords"],
            importance=candidate["importance"],
            valence=candidate["valence"],
        )


async def build_mascot_system_block(
    user_type: str,
    user_id: int,
    *,
    user_message: str,
    mascot_context: str = "",
) -> tuple[str, dict[str, Any]]:
    """为恋恋对话构造动态情感大脑注入块（羁绊语气 + 艾宾浩斯记忆 + 实时动作编排/工具协议）。"""
    state = await get_mascot_state(user_type, user_id)
    recalled = await retrieve_top_memories(user_type, user_id, user_message, top_k=3)

    lines: list[str] = [
        "[恋恋 2.0 情感大脑与实时动作编排协议]",
        f"- 你与用户的当前羁绊等级：Lv.{state['bond_level']}「{state['bond_title']}」（亲密度 {state['affinity']}/100，语气风格：{state['bond_style']}）。",
        f"- 当前时段节律：{state['circadian_phase']}；当前心情坐标：愉悦={state['valence']}，活跃={state['arousal']}。",
    ]
    if state.get("today_mood_score"):
        lines.append(f"- 用户今日心情打卡：{state['today_mood_score']}/5 分。")
    if mascot_context.strip():
        lines.append(f"- 用户当前所在页面/行为语境：{mascot_context.strip()[:220]}")
    if recalled:
        lines.append("- 你记得的关于 TA 的近期重要心事（自然关怀即可，不要生硬背诵）：")
        for m in recalled:
            lines.append(f"  · [{m['category']}] {m['summary']}")

    lines.extend(
        [
            "- **【必须遵守】实时微表情控制头**：每次回复的**最开头第 1 行**必须输出且仅输出一个控制标签，随后直接写正文（不要加代码块或多余解释）：",
            "  `[[emo:<idle|happy|shy|curious|comfort|pout|excited>|act:<none|ear_twitch|tail_turbo|blush|hug|nod|sparkle>|dv:<变化-0.4~0.4>|da:<变化-0.3~0.3>]]`",
            "  例如：`[[emo:shy|act:blush|dv:0.2|da:0.15]]`",
            "- **【按需可选】客户端结构化行动卡片**：如果用户适合立刻使用某项工具，可在正文**最末尾另起一行**附带最多 1 个 `[[tool:{...}]]` JSON 指令（严格单行合法 JSON）：",
            '  1. 用户贴了对方原话问怎么回：`[[tool:{"type":"open_reply_helper","label":"一键带入帮我回消息","partner_message":"对方原话","scene":"ambiguous","tone":"playful"}]]`',
            '  2. 用户正在气头上准备发狠话：`[[tool:{"type":"open_soften_draft","label":"先去降温柔化再发","draft_message":"草稿原话","intensity":"heated"}]]`',
            '  3. 用户提到对方新特征/阶段/雷区值得记住：`[[tool:{"type":"propose_profile_update","label":"顺手记进情感档案","summary":"简述写入内容","patch":{"partner_traits":["慢热型"]}}]]`',
            '  4. 用户明显焦虑/委屈/失眠需要平复：`[[tool:{"type":"start_calm_breathing","label":"跟恋恋做30秒呼吸放松","seconds":30}]]`',
        ]
    )
    return "\n".join(lines), {
        "bond_level": state["bond_level"],
        "bond_title": state["bond_title"],
        "affinity": state["affinity"],
        "recalled_memory_count": len(recalled),
    }


def build_mock_mascot_reply(user_message: str, invoked_skills: list[dict[str, Any]] | None = None) -> str:
    """无 API Key 演示模式下的恋恋 2.0 动作编排 + 工具卡片演示回复。"""
    msg = (user_message or "").strip()
    tool_line = ""
    emo_header = "[[emo:happy|act:ear_twitch|dv:0.18|da:0.15]]"
    body = ""

    if any(k in msg for k in ("生气", "气死", "狠话", "算了", "随便你", "受够", "先别发")):
        emo_header = "[[emo:comfort|act:hug|dv:-0.15|da:-0.20]]"
        body = (
            "先停一下，把手机放远两秒，恋恋先抱抱你 💗\n"
            "1. 气头上发出去的反话最容易把对方推远，我们先留住底线又体面地表达委屈。\n"
            "2. 点下面卡片可以直接把这句话带进「先别发 · 柔化器」，我给你 3 个稳妥版本~"
        )
        tool_line = f'[[tool:{json.dumps({"type": "open_soften_draft", "label": "带入先别发降温改写", "draft_message": msg[:180], "intensity": "heated"}, ensure_ascii=False)}]]'
    elif any(k in msg for k in ("难过", "崩溃", "睡不着", "失眠", "焦虑", "抱抱", "委屈")):
        emo_header = "[[emo:comfort|act:hug|dv:-0.20|da:-0.25]]"
        body = (
            "给你递一杯温热的可可，耳朵垂下来陪着你 💗\n"
            "1. 此刻不需要急着想通全部问题，先让紧绷的肩膀松下来。\n"
            "2. 要不要跟着下面的呼吸圈，和恋恋一起做 30 秒慢呼吸呀？"
        )
        tool_line = '[[tool:{"type":"start_calm_breathing","label":"跟恋恋做30秒呼吸放松","seconds":30}]]'
    elif any(k in msg for k in ("怎么回", "回消息", "已读不回", "他说", "她说", "潜台词")):
        emo_header = "[[emo:curious|act:ear_twitch|dv:0.15|da:0.22]]"
        body = (
            "让我竖起狐狸耳朵帮你听听这句话背后的潜台词 ✨\n"
            "1. 别急着追问压力，先给对方一个轻松接话的小台阶。\n"
            "2. 点下方卡片可以一键带入「帮我回消息」（还能直接传微信截图识图哦）~"
        )
        tool_line = f'[[tool:{json.dumps({"type": "open_reply_helper", "label": "一键带入帮我回消息", "partner_message": msg[:180], "scene": "cold_reply", "tone": "playful"}, ensure_ascii=False)}]]'
    elif any(k in msg for k in ("慢热", "回避", "异地", "嘴硬", "爱吃醋")):
        emo_header = "[[emo:shy|act:sparkle|dv:0.22|da:0.18]]"
        trait = next((t for t in ("慢热型", "回避型依恋", "嘴硬心软", "爱吃醋") if t[:2] in msg), "慢热型")
        body = (
            f"记在小本本上啦！对方偏「{trait}」的话，留白感和安全感比连环追问更有效哦~\n"
            "要不要我顺手帮你把这条特征记进「情感档案」，以后聊起来更懂你们？"
        )
        tool_line = f'[[tool:{json.dumps({"type": "propose_profile_update", "label": f"将「{trait}」记入情感档案", "summary": f"添加对方特征：{trait}", "patch": {"partner_traits": [trait]}}, ensure_ascii=False)}]]'
    else:
        skill_hint = ""
        if invoked_skills:
            names = "、".join(sk["name"] for sk in invoked_skills[:2])
            skill_hint = f"\n（我刚刚还顺手翻了你的知识库「{names}」哦 📚）"
        body = (
            f"收到啦~ 恋恋正晃着尾巴认真听你说呢 ✨{skill_hint}\n"
            "当前后端模型尚未配置 API Key，我正在以演示大脑陪你体验动作编排与交互卡片；"
            "在管理端填入 DeepSeek Key 后就会立刻切换成完整聪明版恋恋哦~"
        )

    return f"{emo_header}\n{body}" + (f"\n{tool_line}" if tool_line else "")


async def apply_love_profile_patch(
    user_type: str,
    user_id: int,
    patch: dict[str, Any],
) -> dict[str, Any]:
    """将恋恋提议的轻量补丁安全合并到用户情感档案，不覆盖已有字段。"""
    current = await love_profile_service.get_love_profile(user_type, user_id)
    merged_partner_traits = list(current.get("partner_traits") or [])
    for tag in patch.get("partner_traits") or []:
        t = str(tag or "").strip()[:24]
        if t and t not in merged_partner_traits:
            merged_partner_traits.append(t)

    merged_my_traits = list(current.get("my_traits") or [])
    for tag in patch.get("my_traits") or []:
        t = str(tag or "").strip()[:24]
        if t and t not in merged_my_traits:
            merged_my_traits.append(t)

    stage = str(patch.get("relationship_stage") or "").strip() or str(
        current.get("relationship_stage") or ""
    )
    nick = str(patch.get("partner_nickname") or "").strip() or str(
        current.get("partner_nickname") or ""
    )
    goal = str(patch.get("relationship_goal") or "").strip() or str(
        current.get("relationship_goal") or ""
    )

    taboos = str(current.get("communication_taboos") or "")
    new_taboo = str(patch.get("communication_taboos") or "").strip()
    if new_taboo and new_taboo not in taboos:
        taboos = f"{taboos}；{new_taboo}".strip("；")[:300]

    notes = str(current.get("background_notes") or "")
    new_note = str(patch.get("background_notes") or "").strip()
    if new_note and new_note not in notes:
        notes = f"{notes}\n{new_note}".strip()[:1200]

    updated = await love_profile_service.upsert_love_profile(
        user_type,
        user_id,
        relationship_stage=stage,
        partner_nickname=nick,
        partner_traits=merged_partner_traits[:8],
        my_traits=merged_my_traits[:8],
        relationship_goal=goal,
        communication_taboos=taboos,
        background_notes=notes,
        auto_inject=bool(current.get("auto_inject", True)),
    )
    return updated


async def purge_mascot_data(user_type: str, user_id: int) -> None:
    """数据主权：随用户清空个人数据时一并销毁恋恋的羁绊档案与记忆。"""
    owner = _owner_scope(user_type, user_id)
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                delete(MascotMemory).where(MascotMemory.owner_scope == owner)
            )
            await session.execute(
                delete(MascotProfile).where(MascotProfile.owner_scope == owner)
            )
            await session.commit()
    except (SQLAlchemyError, OSError):
        pass
    _mem_profiles.pop(owner, None)
    _mem_memories.pop(owner, None)
    await cache_delete(_cache_key(owner))
