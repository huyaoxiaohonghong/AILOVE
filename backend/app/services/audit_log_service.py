from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.db.mysql import get_session_factory
from app.models.audit_log import AuditLog
from app.models.login_log import LoginLog
from app.services import sys_config_service
from app.services.session_service import _mem_login_logs, parse_device_label

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "new_password",
        "current_password",
        "api_key",
        "secret",
        "token",
        "access_token",
        "captcha_token",
    }
)

# MySQL 不可用时的内存审计日志降级列表
_mem_audit_logs: list[dict[str, Any]] = []
_mem_audit_seq = 0


def sanitize_payload(data: Any, *, _depth: int = 0) -> Any:
    """递归脱敏请求摘要，确保明文密码/API Key/Token 绝不落入审计日志。"""
    if _depth > 4:
        return "..."
    if isinstance(data, dict):
        cleaned: dict[str, Any] = {}
        for idx, (k, v) in enumerate(data.items()):
            if idx >= 30:
                cleaned["..."] = "truncated"
                break
            key_str = str(k)
            if key_str.lower() in _SENSITIVE_KEYS:
                cleaned[key_str] = "***REDACTED***" if v else ""
            else:
                cleaned[key_str] = sanitize_payload(v, _depth=_depth + 1)
        return cleaned
    if isinstance(data, list):
        return [sanitize_payload(item, _depth=_depth + 1) for item in data[:12]]
    if isinstance(data, str):
        return data[:220] + ("..." if len(data) > 220 else "")
    return data


def _parse_iso_dt(raw: str | None) -> datetime | None:
    if not raw or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(UTC).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


async def record_audit_log(
    *,
    request_id: str,
    user_id: int | None,
    username: str,
    role: str,
    module: str,
    action: str,
    method: str,
    path: str,
    status_code: int,
    result: str,
    ip: str,
    user_agent: str,
    duration_ms: int,
    request_summary: str = "",
    error_message: str = "",
) -> None:
    """记录操作与安全审计事件；若关闭常规采集开关仍保留 403/5xx 安全告警。"""
    is_security_event = status_code == 403 or status_code >= 500 or result != "success"
    if not is_security_event:
        enabled = await sys_config_service.get_bool("log.audit_enabled", default=True)
        if not enabled:
            return

    device_label = parse_device_label(user_agent)
    summary_text = (request_summary or "")[:2000]
    err_text = (error_message or "")[:250]

    try:
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                AuditLog(
                    request_id=request_id[:36],
                    user_id=user_id,
                    username=(username or "anonymous")[:128],
                    role=(role or "anonymous")[:32],
                    module=(module or "system")[:32],
                    action=(action or f"{method} {path}")[:64],
                    method=method[:10],
                    path=path[:255],
                    status_code=status_code,
                    result=result[:16],
                    ip=(ip or "")[:64],
                    device_label=device_label[:128],
                    duration_ms=max(0, int(duration_ms)),
                    request_summary=summary_text,
                    error_message=err_text,
                )
            )
            await session.commit()
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("Audit log DB write skipped (fallback mem): %s", exc)
        global _mem_audit_seq
        _mem_audit_seq += 1
        _mem_audit_logs.insert(
            0,
            {
                "id": _mem_audit_seq,
                "request_id": request_id[:36],
                "user_id": user_id,
                "username": (username or "anonymous")[:128],
                "role": (role or "anonymous")[:32],
                "module": (module or "system")[:32],
                "action": (action or f"{method} {path}")[:64],
                "method": method[:10],
                "path": path[:255],
                "status_code": status_code,
                "result": result[:16],
                "ip": (ip or "")[:64],
                "device_label": device_label[:128],
                "duration_ms": max(0, int(duration_ms)),
                "request_summary": summary_text,
                "error_message": err_text,
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        del _mem_audit_logs[300:]


async def query_audit_logs(
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    module: str | None = None,
    result: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    dt_start = _parse_iso_dt(start_time)
    dt_end = _parse_iso_dt(end_time)
    try:
        factory = get_session_factory()
        async with factory() as session:
            stmt = select(AuditLog)
            count_stmt = select(func.count(AuditLog.id))

            if keyword:
                pat = f"%{keyword.strip()}%"
                cond = or_(
                    AuditLog.username.like(pat),
                    AuditLog.path.like(pat),
                    AuditLog.action.like(pat),
                    AuditLog.request_id.like(pat),
                )
                stmt = stmt.where(cond)
                count_stmt = count_stmt.where(cond)
            if module:
                stmt = stmt.where(AuditLog.module == module)
                count_stmt = count_stmt.where(AuditLog.module == module)
            if result:
                stmt = stmt.where(AuditLog.result == result)
                count_stmt = count_stmt.where(AuditLog.result == result)
            if method:
                stmt = stmt.where(AuditLog.method == method.upper())
                count_stmt = count_stmt.where(AuditLog.method == method.upper())
            if status_code is not None:
                stmt = stmt.where(AuditLog.status_code == status_code)
                count_stmt = count_stmt.where(AuditLog.status_code == status_code)
            if dt_start is not None:
                stmt = stmt.where(AuditLog.created_at >= dt_start)
                count_stmt = count_stmt.where(AuditLog.created_at >= dt_start)
            if dt_end is not None:
                stmt = stmt.where(AuditLog.created_at <= dt_end)
                count_stmt = count_stmt.where(AuditLog.created_at <= dt_end)

            total = int((await session.scalar(count_stmt)) or 0)
            stmt = (
                stmt.order_by(AuditLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            rows = (await session.execute(stmt)).scalars().all()
            items = [
                {
                    "id": r.id,
                    "request_id": r.request_id,
                    "user_id": r.user_id,
                    "username": r.username,
                    "role": r.role,
                    "module": r.module,
                    "action": r.action,
                    "method": r.method,
                    "path": r.path,
                    "status_code": r.status_code,
                    "result": r.result,
                    "ip": r.ip,
                    "device_label": r.device_label,
                    "duration_ms": r.duration_ms,
                    "request_summary": r.request_summary,
                    "error_message": r.error_message,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ]
            return {"items": items, "total": total, "page": page, "page_size": page_size}
    except (SQLAlchemyError, OSError):
        filtered = list(_mem_audit_logs)
        if keyword:
            kw = keyword.strip().lower()
            filtered = [
                x
                for x in filtered
                if kw in x["username"].lower()
                or kw in x["path"].lower()
                or kw in x["action"].lower()
                or kw in x["request_id"].lower()
            ]
        if module:
            filtered = [x for x in filtered if x["module"] == module]
        if result:
            filtered = [x for x in filtered if x["result"] == result]
        if method:
            filtered = [x for x in filtered if x["method"] == method.upper()]
        if status_code is not None:
            filtered = [x for x in filtered if x["status_code"] == status_code]
        total = len(filtered)
        return {
            "items": filtered[(page - 1) * page_size : page * page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


async def query_all_login_logs(
    *,
    page: int = 1,
    page_size: int = 20,
    keyword: str | None = None,
    status_filter: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    dt_start = _parse_iso_dt(start_time)
    dt_end = _parse_iso_dt(end_time)
    try:
        factory = get_session_factory()
        async with factory() as session:
            stmt = select(LoginLog)
            count_stmt = select(func.count(LoginLog.id))

            if keyword:
                pat = f"%{keyword.strip()}%"
                cond = or_(LoginLog.account.like(pat), LoginLog.ip.like(pat))
                stmt = stmt.where(cond)
                count_stmt = count_stmt.where(cond)
            if status_filter:
                stmt = stmt.where(LoginLog.status == status_filter)
                count_stmt = count_stmt.where(LoginLog.status == status_filter)
            if dt_start is not None:
                stmt = stmt.where(LoginLog.created_at >= dt_start)
                count_stmt = count_stmt.where(LoginLog.created_at >= dt_start)
            if dt_end is not None:
                stmt = stmt.where(LoginLog.created_at <= dt_end)
                count_stmt = count_stmt.where(LoginLog.created_at <= dt_end)

            total = int((await session.scalar(count_stmt)) or 0)
            stmt = (
                stmt.order_by(LoginLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            rows = (await session.execute(stmt)).scalars().all()
            items = [
                {
                    "id": r.id,
                    "user_id": r.user_id,
                    "account": r.account,
                    "ip": r.ip,
                    "device_label": r.device_label,
                    "status": r.status,
                    "fail_reason": r.fail_reason,
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
                for r in rows
            ]
            return {"items": items, "total": total, "page": page, "page_size": page_size}
    except (SQLAlchemyError, OSError):
        filtered = list(_mem_login_logs)
        if keyword:
            kw = keyword.strip().lower()
            filtered = [
                x for x in filtered if kw in x["account"].lower() or kw in x["ip"].lower()
            ]
        if status_filter:
            filtered = [x for x in filtered if x["status"] == status_filter]
        total = len(filtered)
        return {
            "items": filtered[(page - 1) * page_size : page * page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
        }


async def get_log_summary() -> dict[str, Any]:
    since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=24)
    try:
        factory = get_session_factory()
        async with factory() as session:
            audit_total_24h = int(
                (
                    await session.scalar(
                        select(func.count(AuditLog.id)).where(AuditLog.created_at >= since)
                    )
                )
                or 0
            )
            audit_alert_24h = int(
                (
                    await session.scalar(
                        select(func.count(AuditLog.id)).where(
                            AuditLog.created_at >= since,
                            AuditLog.result != "success",
                        )
                    )
                )
                or 0
            )
            login_success_24h = int(
                (
                    await session.scalar(
                        select(func.count(LoginLog.id)).where(
                            LoginLog.created_at >= since,
                            LoginLog.status == "success",
                        )
                    )
                )
                or 0
            )
            login_failed_24h = int(
                (
                    await session.scalar(
                        select(func.count(LoginLog.id)).where(
                            LoginLog.created_at >= since,
                            LoginLog.status == "failed",
                        )
                    )
                )
                or 0
            )
            mod_rows = (
                await session.execute(
                    select(AuditLog.module, func.count(AuditLog.id))
                    .where(AuditLog.created_at >= since)
                    .group_by(AuditLog.module)
                )
            ).all()
            return {
                "audit_total_24h": audit_total_24h,
                "audit_alert_24h": audit_alert_24h,
                "login_success_24h": login_success_24h,
                "login_failed_24h": login_failed_24h,
                "by_module": {str(m): int(c) for m, c in mod_rows},
            }
    except (SQLAlchemyError, OSError):
        by_module: dict[str, int] = {}
        alert_count = 0
        for item in _mem_audit_logs:
            m = str(item.get("module", "system"))
            by_module[m] = by_module.get(m, 0) + 1
            if item.get("result") != "success":
                alert_count += 1
        login_ok = sum(1 for item in _mem_login_logs if item.get("status") == "success")
        login_fail = sum(1 for item in _mem_login_logs if item.get("status") == "failed")
        return {
            "audit_total_24h": len(_mem_audit_logs),
            "audit_alert_24h": alert_count,
            "login_success_24h": login_ok,
            "login_failed_24h": login_fail,
            "by_module": by_module,
        }


async def cleanup_old_logs(retention_days: int | None = None, target: str = "all") -> dict[str, int]:
    days = (
        retention_days
        if retention_days is not None
        else await sys_config_service.get_int("log.retention_days", default=90)
    )
    cutoff = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
    deleted_audit = 0
    deleted_login = 0

    try:
        factory = get_session_factory()
        async with factory() as session:
            if target in {"audit", "all"}:
                res_a = await session.execute(delete(AuditLog).where(AuditLog.created_at < cutoff))
                deleted_audit = int(res_a.rowcount or 0)
            if target in {"login", "all"}:
                res_l = await session.execute(delete(LoginLog).where(LoginLog.created_at < cutoff))
                deleted_login = int(res_l.rowcount or 0)
            await session.commit()
    except (SQLAlchemyError, OSError):
        cutoff_iso = cutoff.replace(tzinfo=UTC).isoformat()
        if target in {"audit", "all"}:
            before = len(_mem_audit_logs)
            _mem_audit_logs[:] = [x for x in _mem_audit_logs if x.get("created_at", "") >= cutoff_iso]
            deleted_audit = before - len(_mem_audit_logs)
        if target in {"login", "all"}:
            before_l = len(_mem_login_logs)
            _mem_login_logs[:] = [x for x in _mem_login_logs if x.get("created_at", "") >= cutoff_iso]
            deleted_login = before_l - len(_mem_login_logs)

    return {
        "retention_days": days,
        "deleted_audit_logs": deleted_audit,
        "deleted_login_logs": deleted_login,
    }


def serialize_summary(body_bytes: bytes) -> str:
    if not body_bytes:
        return ""
    try:
        parsed = json.loads(body_bytes.decode("utf-8"))
        return json.dumps(sanitize_payload(parsed), ensure_ascii=False)
    except Exception:
        return ""
