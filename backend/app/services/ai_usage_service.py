from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import status
from sqlalchemy import case, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import BusinessException
from app.db.mysql import get_session_factory
from app.db.redis import get_redis
from app.models.ai_usage_log import AIUsageLog
from app.services.rbac_service import get_role_meta
from app.services.sys_config_service import get_int

logger = logging.getLogger(__name__)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_ADMIN_EXEMPT_ROLES = {"super_admin", "admin", "operator", "auditor"}

# 无 MySQL 时的本地开发/单元测试内存流水（仅保留最近 5000 条）
_mem_usage_logs: list[dict[str, Any]] = []


def _now_shanghai() -> datetime:
    return datetime.now(_SHANGHAI_TZ).replace(tzinfo=None)


def _today_parts() -> tuple[str, str, datetime]:
    now = _now_shanghai()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now.strftime("%Y-%m-%d"), now.strftime("%Y%m%d"), day_start


def _quota_keys(owner_scope: str, yyyymmdd: str) -> tuple[str, str]:
    return (
        f"ailove:ai:quota:req:{owner_scope}:{yyyymmdd}",
        f"ailove:ai:quota:tok:{owner_scope}:{yyyymmdd}",
    )


async def _is_role_exempt(role_code: str) -> bool:
    code = (role_code or "").strip()
    if code in _ADMIN_EXEMPT_ROLES:
        return True
    meta = await get_role_meta(code) if code else None
    return bool(meta and meta.get("is_admin_portal"))


async def get_today_usage(owner_scope: str) -> tuple[int, int]:
    """查询用户今日已成功的 AI 调用次数与 Token 消耗。"""
    _, yyyymmdd, day_start = _today_parts()
    req_key, tok_key = _quota_keys(owner_scope, yyyymmdd)

    try:
        redis = get_redis()
        req_raw, tok_raw = await redis.mget(req_key, tok_key)
        if req_raw is not None and tok_raw is not None:
            return max(0, int(req_raw)), max(0, int(tok_raw))
    except Exception as exc:
        logger.debug("Redis read quota skipped: %s", exc)

    req_used = 0
    tok_used = 0
    try:
        factory = get_session_factory()
        async with factory() as db:
            stmt = select(
                func.count(AIUsageLog.id),
                func.coalesce(func.sum(AIUsageLog.total_tokens), 0),
            ).where(
                AIUsageLog.owner_scope == owner_scope,
                AIUsageLog.status == "success",
                AIUsageLog.created_at >= day_start,
            )
            row = (await db.execute(stmt)).one()
            req_used = int(row[0] or 0)
            tok_used = int(row[1] or 0)
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("get_today_usage fallback to memory: %s", exc)
        for item in _mem_usage_logs:
            if (
                item["owner_scope"] == owner_scope
                and item["status"] == "success"
                and item["created_at"] >= day_start
            ):
                req_used += 1
                tok_used += int(item["total_tokens"])

    try:
        redis = get_redis()
        pipe = redis.pipeline()
        pipe.set(req_key, str(req_used), ex=172800)
        pipe.set(tok_key, str(tok_used), ex=172800)
        await pipe.execute()
    except Exception:
        pass

    return req_used, tok_used


async def get_user_quota_status(owner_scope: str, role_code: str = "user") -> dict[str, Any]:
    """返回当前用户今日 AI 配额及剩余可用情况。"""
    today_str, _, _ = _today_parts()
    is_exempt = await _is_role_exempt(role_code)
    req_limit = await get_int("ai.daily_user_request_limit", 100)
    tok_limit = await get_int("ai.daily_user_token_limit", 100000)
    req_used, tok_used = await get_today_usage(owner_scope)

    return {
        "owner_scope": owner_scope,
        "role": role_code or "user",
        "is_exempt": is_exempt,
        "date": today_str,
        "requests_used": req_used,
        "requests_limit": req_limit,
        "requests_remaining": (
            None if (is_exempt or req_limit <= 0) else max(0, req_limit - req_used)
        ),
        "tokens_used": tok_used,
        "tokens_limit": tok_limit,
        "tokens_remaining": (
            None if (is_exempt or tok_limit <= 0) else max(0, tok_limit - tok_used)
        ),
    }


async def check_daily_quota(owner_scope: str, role_code: str = "user") -> dict[str, Any]:
    """在发起 AI 对话前校验用户当日配额（管理端角色豁免）。"""
    status_data = await get_user_quota_status(owner_scope, role_code)
    if status_data["is_exempt"]:
        return status_data

    req_limit = status_data["requests_limit"]
    req_used = status_data["requests_used"]
    if req_limit > 0 and req_used >= req_limit:
        raise BusinessException(
            f"今日 AI 对话次数已达上限（{req_limit} 次/日），请明日再试或联系管理员调整配额",
            code=42902,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    tok_limit = status_data["tokens_limit"]
    tok_used = status_data["tokens_used"]
    if tok_limit > 0 and tok_used >= tok_limit:
        raise BusinessException(
            f"今日 AI Token 消耗已达上限（{tok_limit} / 日），请明日再试或联系管理员调整配额",
            code=42903,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    return status_data


async def record_usage(
    *,
    owner_scope: str,
    user_type: str,
    user_id: int,
    username: str,
    session_id: str,
    persona_id: int | None,
    persona_name: str,
    provider: str,
    model_name: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    latency_ms: int = 0,
    is_stream: bool = False,
    is_mock: bool = False,
    call_status: str = "success",
) -> None:
    """异步落库一条 AI 调用流水并同步刷新当日 Redis 配额计数器。"""
    norm_total = total_tokens if total_tokens > 0 else max(0, prompt_tokens + completion_tokens)
    now = _now_shanghai()

    try:
        factory = get_session_factory()
        async with factory() as db:
            db.add(
                AIUsageLog(
                    owner_scope=owner_scope,
                    user_type=user_type,
                    user_id=user_id,
                    username=(username or "")[:64],
                    session_id=session_id[:128],
                    persona_id=persona_id,
                    persona_name=(persona_name or "")[:64],
                    provider=(provider or "deepseek")[:32],
                    model_name=(model_name or "")[:64],
                    prompt_tokens=max(0, int(prompt_tokens)),
                    completion_tokens=max(0, int(completion_tokens)),
                    total_tokens=max(0, int(norm_total)),
                    latency_ms=max(0, int(latency_ms)),
                    is_stream=is_stream,
                    is_mock=is_mock,
                    status=call_status[:16],
                    created_at=now,
                )
            )
            await db.commit()
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("record_usage fallback to memory: %s", exc)
        _mem_usage_logs.append(
            {
                "owner_scope": owner_scope,
                "user_type": user_type,
                "user_id": user_id,
                "username": (username or "")[:64],
                "session_id": session_id[:128],
                "persona_id": persona_id,
                "persona_name": (persona_name or "")[:64],
                "provider": (provider or "deepseek")[:32],
                "model_name": (model_name or "")[:64],
                "prompt_tokens": max(0, int(prompt_tokens)),
                "completion_tokens": max(0, int(completion_tokens)),
                "total_tokens": max(0, int(norm_total)),
                "latency_ms": max(0, int(latency_ms)),
                "is_stream": is_stream,
                "is_mock": is_mock,
                "status": call_status[:16],
                "created_at": now,
            }
        )
        if len(_mem_usage_logs) > 5000:
            del _mem_usage_logs[: len(_mem_usage_logs) - 5000]

    if call_status == "success":
        _, yyyymmdd, _ = _today_parts()
        req_key, tok_key = _quota_keys(owner_scope, yyyymmdd)
        try:
            redis = get_redis()
            if await redis.exists(req_key, tok_key) == 2:
                pipe = redis.pipeline()
                pipe.incrby(req_key, 1)
                pipe.expire(req_key, 172800)
                pipe.incrby(tok_key, max(0, int(norm_total)))
                pipe.expire(tok_key, 172800)
                await pipe.execute()
            else:
                await redis.delete(req_key, tok_key)
        except Exception:
            pass


def _build_date_axis(days: int) -> tuple[list[str], datetime, str]:
    today_str, _, day_start = _today_parts()
    start_dt = day_start - timedelta(days=days - 1)
    dates = [(start_dt + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
    return dates, start_dt, today_str


def _format_analytics_result(
    days: int,
    dates: list[str],
    today_str: str,
    *,
    total_requests: int,
    success_requests: int,
    failed_requests: int,
    total_tokens: int,
    avg_latency_ms: int,
    active_users: int,
    trend_map: dict[str, dict[str, int]],
    by_model: list[dict[str, Any]],
    top_users: list[dict[str, Any]],
    top_personas: list[dict[str, Any]],
) -> dict[str, Any]:
    daily_trend: list[dict[str, Any]] = []
    for d in dates:
        bucket = trend_map.get(d, {"requests": 0, "tokens": 0, "latency_sum": 0, "latency_cnt": 0})
        cnt = bucket["latency_cnt"]
        avg_lat = round(bucket["latency_sum"] / cnt) if cnt > 0 else 0
        daily_trend.append(
            {
                "date": d,
                "label": f"{d[5:7]}/{d[8:10]}",
                "requests": bucket["requests"],
                "tokens": bucket["tokens"],
                "avg_latency_ms": avg_lat,
            }
        )

    today_bucket = trend_map.get(today_str, {"requests": 0, "tokens": 0})
    return {
        "days": days,
        "summary": {
            "total_requests": total_requests,
            "success_requests": success_requests,
            "failed_requests": failed_requests,
            "today_requests": today_bucket["requests"],
            "total_tokens": total_tokens,
            "today_tokens": today_bucket["tokens"],
            "avg_latency_ms": avg_latency_ms,
            "active_users": active_users,
        },
        "daily_trend": daily_trend,
        "by_model": by_model,
        "top_users": top_users,
        "top_personas": top_personas,
    }


def _aggregate_analytics_mem(
    days: int, dates: list[str], start_dt: datetime, today_str: str
) -> dict[str, Any]:
    rows = [item for item in _mem_usage_logs if item["created_at"] >= start_dt]
    total_requests = len(rows)
    success_requests = sum(1 for r in rows if r["status"] == "success")
    failed_requests = total_requests - success_requests
    total_tokens = sum(int(r["total_tokens"]) for r in rows)
    latencies = [int(r["latency_ms"]) for r in rows if int(r["latency_ms"]) > 0]
    avg_latency_ms = round(sum(latencies) / len(latencies)) if latencies else 0
    active_users = len({r["owner_scope"] for r in rows})

    trend_map: dict[str, dict[str, int]] = defaultdict(
        lambda: {"requests": 0, "tokens": 0, "latency_sum": 0, "latency_cnt": 0}
    )
    model_map: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: {"requests": 0, "tokens": 0})
    user_map: dict[str, dict[str, Any]] = {}
    persona_map: dict[tuple[int | None, str], dict[str, int]] = defaultdict(
        lambda: {"requests": 0, "tokens": 0}
    )

    for r in rows:
        d = r["created_at"].strftime("%Y-%m-%d")
        trend_map[d]["requests"] += 1
        trend_map[d]["tokens"] += int(r["total_tokens"])
        if int(r["latency_ms"]) > 0:
            trend_map[d]["latency_sum"] += int(r["latency_ms"])
            trend_map[d]["latency_cnt"] += 1

        mk = (r["model_name"] or "unknown", r["provider"] or "deepseek")
        model_map[mk]["requests"] += 1
        model_map[mk]["tokens"] += int(r["total_tokens"])

        scope = r["owner_scope"]
        if scope not in user_map:
            user_map[scope] = {
                "owner_scope": scope,
                "username": r["username"] or scope,
                "requests": 0,
                "tokens": 0,
            }
        elif r["username"]:
            user_map[scope]["username"] = r["username"]
        user_map[scope]["requests"] += 1
        user_map[scope]["tokens"] += int(r["total_tokens"])

        pk = (r["persona_id"], r["persona_name"] or "自由对话")
        persona_map[pk]["requests"] += 1
        persona_map[pk]["tokens"] += int(r["total_tokens"])

    denom = max(1, total_requests)
    by_model = sorted(
        [
            {
                "model_name": k[0],
                "provider": k[1],
                "requests": v["requests"],
                "tokens": v["tokens"],
                "share_percent": round(v["requests"] * 100.0 / denom, 1),
            }
            for k, v in model_map.items()
        ],
        key=lambda x: x["requests"],
        reverse=True,
    )
    top_users = sorted(user_map.values(), key=lambda x: (x["requests"], x["tokens"]), reverse=True)[:5]
    top_personas = sorted(
        [
            {
                "persona_id": k[0],
                "persona_name": k[1],
                "requests": v["requests"],
                "tokens": v["tokens"],
            }
            for k, v in persona_map.items()
        ],
        key=lambda x: x["requests"],
        reverse=True,
    )[:5]

    return _format_analytics_result(
        days,
        dates,
        today_str,
        total_requests=total_requests,
        success_requests=success_requests,
        failed_requests=failed_requests,
        total_tokens=total_tokens,
        avg_latency_ms=avg_latency_ms,
        active_users=active_users,
        trend_map=trend_map,
        by_model=by_model,
        top_users=top_users,
        top_personas=top_personas,
    )


async def get_ai_analytics(days: int = 7) -> dict[str, Any]:
    """统计最近 N 天 AI 调用趋势、模型分布与活跃排行。"""
    safe_days = max(1, min(30, int(days)))
    dates, start_dt, today_str = _build_date_axis(safe_days)

    try:
        factory = get_session_factory()
        async with factory() as db:
            summary_row = (
                await db.execute(
                    select(
                        func.count(AIUsageLog.id),
                        func.coalesce(
                            func.sum(case((AIUsageLog.status == "success", 1), else_=0)), 0
                        ),
                        func.coalesce(func.sum(AIUsageLog.total_tokens), 0),
                        func.coalesce(
                            func.avg(case((AIUsageLog.latency_ms > 0, AIUsageLog.latency_ms), else_=None)),
                            0,
                        ),
                        func.count(func.distinct(AIUsageLog.owner_scope)),
                    ).where(AIUsageLog.created_at >= start_dt)
                )
            ).one()
            total_requests = int(summary_row[0] or 0)
            success_requests = int(summary_row[1] or 0)
            failed_requests = max(0, total_requests - success_requests)
            total_tokens = int(summary_row[2] or 0)
            avg_latency_ms = round(float(summary_row[3] or 0))
            active_users = int(summary_row[4] or 0)

            day_expr = func.date_format(AIUsageLog.created_at, "%Y-%m-%d")
            trend_rows = (
                await db.execute(
                    select(
                        day_expr.label("day"),
                        func.count(AIUsageLog.id),
                        func.coalesce(func.sum(AIUsageLog.total_tokens), 0),
                        func.coalesce(
                            func.sum(case((AIUsageLog.latency_ms > 0, AIUsageLog.latency_ms), else_=0)),
                            0,
                        ),
                        func.coalesce(
                            func.sum(case((AIUsageLog.latency_ms > 0, 1), else_=0)),
                            0,
                        ),
                    )
                    .where(AIUsageLog.created_at >= start_dt)
                    .group_by(day_expr)
                )
            ).all()
            trend_map: dict[str, dict[str, int]] = {}
            for row in trend_rows:
                trend_map[str(row[0])] = {
                    "requests": int(row[1] or 0),
                    "tokens": int(row[2] or 0),
                    "latency_sum": int(row[3] or 0),
                    "latency_cnt": int(row[4] or 0),
                }

            model_rows = (
                await db.execute(
                    select(
                        AIUsageLog.model_name,
                        AIUsageLog.provider,
                        func.count(AIUsageLog.id).label("cnt"),
                        func.coalesce(func.sum(AIUsageLog.total_tokens), 0),
                    )
                    .where(AIUsageLog.created_at >= start_dt)
                    .group_by(AIUsageLog.model_name, AIUsageLog.provider)
                    .order_by(func.count(AIUsageLog.id).desc())
                )
            ).all()
            denom = max(1, total_requests)
            by_model = [
                {
                    "model_name": row[0] or "unknown",
                    "provider": row[1] or "deepseek",
                    "requests": int(row[2] or 0),
                    "tokens": int(row[3] or 0),
                    "share_percent": round(int(row[2] or 0) * 100.0 / denom, 1),
                }
                for row in model_rows
            ]

            user_rows = (
                await db.execute(
                    select(
                        AIUsageLog.owner_scope,
                        func.max(AIUsageLog.username),
                        func.count(AIUsageLog.id).label("cnt"),
                        func.coalesce(func.sum(AIUsageLog.total_tokens), 0),
                    )
                    .where(AIUsageLog.created_at >= start_dt)
                    .group_by(AIUsageLog.owner_scope)
                    .order_by(func.count(AIUsageLog.id).desc())
                    .limit(5)
                )
            ).all()
            top_users = [
                {
                    "owner_scope": row[0],
                    "username": row[1] or row[0],
                    "requests": int(row[2] or 0),
                    "tokens": int(row[3] or 0),
                }
                for row in user_rows
            ]

            persona_rows = (
                await db.execute(
                    select(
                        AIUsageLog.persona_id,
                        func.max(AIUsageLog.persona_name),
                        func.count(AIUsageLog.id).label("cnt"),
                        func.coalesce(func.sum(AIUsageLog.total_tokens), 0),
                    )
                    .where(AIUsageLog.created_at >= start_dt)
                    .group_by(AIUsageLog.persona_id)
                    .order_by(func.count(AIUsageLog.id).desc())
                    .limit(5)
                )
            ).all()
            top_personas = [
                {
                    "persona_id": int(row[0]) if row[0] is not None else None,
                    "persona_name": row[1] or "自由对话",
                    "requests": int(row[2] or 0),
                    "tokens": int(row[3] or 0),
                }
                for row in persona_rows
            ]

            return _format_analytics_result(
                safe_days,
                dates,
                today_str,
                total_requests=total_requests,
                success_requests=success_requests,
                failed_requests=failed_requests,
                total_tokens=total_tokens,
                avg_latency_ms=avg_latency_ms,
                active_users=active_users,
                trend_map=trend_map,
                by_model=by_model,
                top_users=top_users,
                top_personas=top_personas,
            )
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("get_ai_analytics fallback to memory: %s", exc)
        return _aggregate_analytics_mem(safe_days, dates, start_dt, today_str)


async def export_usage_logs_rows(
    *,
    days: int = 7,
    status_filter: str | None = None,
    model_name: str | None = None,
    limit: int = 2000,
) -> tuple[list[str], list[list[Any]]]:
    """按天数与筛选条件导出 AI 调用明细与 Token 用量 CSV 数据（上限 5000 条）。"""
    safe_days = max(1, min(int(days), 30))
    cap = max(1, min(int(limit), 5000))
    _, start_dt, _ = _build_date_axis(safe_days)

    headers = [
        "调用时间",
        "用户名",
        "作用域",
        "来源端",
        "智能体",
        "模型提供商",
        "模型名称",
        "输入Token",
        "输出Token",
        "总Token",
        "耗时(ms)",
        "流式",
        "演示模式",
        "状态",
        "会话ID",
    ]
    rows: list[list[Any]] = []
    try:
        factory = get_session_factory()
        async with factory() as db:
            stmt = select(AIUsageLog).where(AIUsageLog.created_at >= start_dt)
            if status_filter:
                stmt = stmt.where(AIUsageLog.status == status_filter)
            if model_name:
                stmt = stmt.where(AIUsageLog.model_name == model_name)
            stmt = stmt.order_by(AIUsageLog.id.desc()).limit(cap)
            records = (await db.execute(stmt)).scalars().all()
            for r in records:
                rows.append(
                    [
                        r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
                        r.username or r.owner_scope,
                        r.owner_scope,
                        r.user_type,
                        r.persona_name or "自由对话",
                        r.provider,
                        r.model_name,
                        r.prompt_tokens,
                        r.completion_tokens,
                        r.total_tokens,
                        r.latency_ms,
                        "是" if r.is_stream else "否",
                        "是" if r.is_mock else "否",
                        r.status,
                        r.session_id,
                    ]
                )
            return headers, rows
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("export_usage_logs_rows fallback to memory: %s", exc)
        filtered = [
            it
            for it in reversed(_mem_usage_logs)
            if it["created_at"] >= start_dt
            and (not status_filter or it["status"] == status_filter)
            and (not model_name or it["model_name"] == model_name)
        ]
        for it in filtered[:cap]:
            ts = it["created_at"]
            rows.append(
                [
                    ts.strftime("%Y-%m-%d %H:%M:%S") if isinstance(ts, datetime) else str(ts),
                    it.get("username") or it.get("owner_scope", ""),
                    it.get("owner_scope", ""),
                    it.get("user_type", ""),
                    it.get("persona_name") or "自由对话",
                    it.get("provider", ""),
                    it.get("model_name", ""),
                    it.get("prompt_tokens", 0),
                    it.get("completion_tokens", 0),
                    it.get("total_tokens", 0),
                    it.get("latency_ms", 0),
                    "是" if it.get("is_stream") else "否",
                    "是" if it.get("is_mock") else "否",
                    it.get("status", ""),
                    it.get("session_id", ""),
                ]
            )
        return headers, rows
