from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import status
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.exceptions import BusinessException
from app.db.mysql import get_session_factory
from app.models.invite_code import InviteCode

logger = logging.getLogger(__name__)

# 去掉易混淆字符 (0/O, 1/I/L)，方便微信口头或文字转发
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
_mem_invites: dict[int, dict[str, Any]] = {}
_mem_seq = 1


def _normalize_code(raw: str) -> str:
    return (raw or "").strip().upper()


def _generate_code() -> str:
    suffix = "".join(secrets.choice(_ALPHABET) for _ in range(6))
    return f"LOVE-{suffix}"


def _row_to_dict(row: InviteCode) -> dict[str, Any]:
    now = datetime.now(UTC).replace(tzinfo=None)
    expired = bool(row.expires_at and row.expires_at <= now)
    exhausted = bool(row.max_uses > 0 and row.used_count >= row.max_uses)
    return {
        "id": row.id,
        "code": row.code,
        "note": row.note or "",
        "max_uses": int(row.max_uses),
        "used_count": int(row.used_count),
        "is_active": bool(row.is_active),
        "is_available": bool(row.is_active) and not expired and not exhausted,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def _mem_to_dict(rec: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC).replace(tzinfo=None)
    exp = rec.get("expires_at")
    expired = bool(exp and exp <= now)
    exhausted = bool(rec["max_uses"] > 0 and rec["used_count"] >= rec["max_uses"])
    return {
        "id": rec["id"],
        "code": rec["code"],
        "note": rec.get("note", ""),
        "max_uses": int(rec["max_uses"]),
        "used_count": int(rec["used_count"]),
        "is_active": bool(rec["is_active"]),
        "is_available": bool(rec["is_active"]) and not expired and not exhausted,
        "expires_at": exp.isoformat() if exp else None,
        "created_at": rec["created_at"].isoformat() if rec.get("created_at") else "",
    }


def _validate_record_availability(
    *, is_active: bool, max_uses: int, used_count: int, expires_at: datetime | None
) -> None:
    if not is_active:
        raise BusinessException(
            "该邀请码已被停用",
            code=40308,
            status_code=status.HTTP_403_FORBIDDEN,
        )
    now = datetime.now(UTC).replace(tzinfo=None)
    if expires_at is not None and expires_at <= now:
        raise BusinessException(
            "该邀请码已过期",
            code=40308,
            status_code=status.HTTP_403_FORBIDDEN,
        )
    if max_uses > 0 and used_count >= max_uses:
        raise BusinessException(
            "该邀请码使用次数已达上限",
            code=40308,
            status_code=status.HTTP_403_FORBIDDEN,
        )


async def list_invite_codes(limit: int = 100) -> list[dict[str, Any]]:
    try:
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(
                    select(InviteCode).order_by(desc(InviteCode.id)).limit(max(1, min(limit, 200)))
                )
            ).scalars().all()
            return [_row_to_dict(r) for r in rows]
    except (SQLAlchemyError, OSError):
        items = list(_mem_invites.values())
        items.sort(key=lambda r: int(r["id"]), reverse=True)
        return [_mem_to_dict(r) for r in items[:limit]]


async def create_invite_code(
    *,
    note: str = "",
    max_uses: int = 1,
    expires_days: int | None = None,
    custom_code: str = "",
    admin_id: int | None = None,
) -> dict[str, Any]:
    global _mem_seq
    code = _normalize_code(custom_code) or _generate_code()
    if len(code) < 4 or len(code) > 32:
        raise BusinessException("邀请码长度需为 4~32 位字符", code=40068)
    clean_note = (note or "").strip()[:128]
    now = datetime.now(UTC).replace(tzinfo=None)
    expires_at = (now + timedelta(days=expires_days)) if expires_days else None

    try:
        factory = get_session_factory()
        async with factory() as session:
            row = InviteCode(
                code=code,
                note=clean_note,
                max_uses=int(max_uses),
                used_count=0,
                is_active=True,
                expires_at=expires_at,
                created_by=admin_id,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _row_to_dict(row)
    except IntegrityError as exc:
        raise BusinessException(f"邀请码「{code}」已存在，请换一个或留空自动生成", code=40906) from exc
    except (SQLAlchemyError, OSError):
        for rec in _mem_invites.values():
            if rec["code"] == code:
                raise BusinessException(
                    f"邀请码「{code}」已存在，请换一个或留空自动生成", code=40906
                ) from None
        rec = {
            "id": _mem_seq,
            "code": code,
            "note": clean_note,
            "max_uses": int(max_uses),
            "used_count": 0,
            "is_active": True,
            "expires_at": expires_at,
            "created_by": admin_id,
            "created_at": now,
        }
        _mem_invites[_mem_seq] = rec
        _mem_seq += 1
        return _mem_to_dict(rec)


async def toggle_invite_code(code_id: int, is_active: bool) -> dict[str, Any]:
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(InviteCode, code_id)
            if row is None:
                raise BusinessException(
                    "目标邀请码不存在", code=40408, status_code=status.HTTP_404_NOT_FOUND
                )
            row.is_active = bool(is_active)
            await session.commit()
            await session.refresh(row)
            return _row_to_dict(row)
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        rec = _mem_invites.get(code_id)
        if rec is None:
            raise BusinessException(
                "目标邀请码不存在", code=40408, status_code=status.HTTP_404_NOT_FOUND
            ) from exc
        rec["is_active"] = bool(is_active)
        return _mem_to_dict(rec)


async def delete_invite_code(code_id: int) -> bool:
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(InviteCode, code_id)
            if row is None:
                raise BusinessException(
                    "目标邀请码不存在", code=40408, status_code=status.HTTP_404_NOT_FOUND
                )
            await session.delete(row)
            await session.commit()
            return True
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        if code_id not in _mem_invites:
            raise BusinessException(
                "目标邀请码不存在", code=40408, status_code=status.HTTP_404_NOT_FOUND
            ) from exc
        _mem_invites.pop(code_id, None)
        return True


async def verify_invite_code_only(raw_code: str) -> dict[str, Any]:
    """仅预检邀请码是否可用（不扣减次数，适合多步校验先行判定）。"""
    code = _normalize_code(raw_code)
    if not code:
        raise BusinessException(
            "当前为小圈子内测模式，请输入有效邀请码",
            code=40308,
            status_code=status.HTTP_403_FORBIDDEN,
        )
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(select(InviteCode).where(InviteCode.code == code))
            ).scalar_one_or_none()
            if row is None:
                raise BusinessException(
                    "邀请码无效，请向创建者索取最新邀请码",
                    code=40308,
                    status_code=status.HTTP_403_FORBIDDEN,
                )
            _validate_record_availability(
                is_active=row.is_active,
                max_uses=row.max_uses,
                used_count=row.used_count,
                expires_at=row.expires_at,
            )
            return _row_to_dict(row)
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        for rec in _mem_invites.values():
            if rec["code"] == code:
                _validate_record_availability(
                    is_active=rec["is_active"],
                    max_uses=rec["max_uses"],
                    used_count=rec["used_count"],
                    expires_at=rec["expires_at"],
                )
                return _mem_to_dict(rec)
        raise BusinessException(
            "邀请码无效，请向创建者索取最新邀请码",
            code=40308,
            status_code=status.HTTP_403_FORBIDDEN,
        ) from exc


async def verify_and_consume_invite_code(raw_code: str) -> dict[str, Any]:
    """校验并核销 1 次邀请码。"""
    code = _normalize_code(raw_code)
    if not code:
        raise BusinessException(
            "当前为小圈子内测模式，请输入有效邀请码",
            code=40308,
            status_code=status.HTTP_403_FORBIDDEN,
        )
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(select(InviteCode).where(InviteCode.code == code))
            ).scalar_one_or_none()
            if row is None:
                raise BusinessException(
                    "邀请码无效，请向创建者索取最新邀请码",
                    code=40308,
                    status_code=status.HTTP_403_FORBIDDEN,
                )
            _validate_record_availability(
                is_active=row.is_active,
                max_uses=row.max_uses,
                used_count=row.used_count,
                expires_at=row.expires_at,
            )
            row.used_count = int(row.used_count) + 1
            await session.commit()
            await session.refresh(row)
            return _row_to_dict(row)
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        for rec in _mem_invites.values():
            if rec["code"] == code:
                _validate_record_availability(
                    is_active=rec["is_active"],
                    max_uses=rec["max_uses"],
                    used_count=rec["used_count"],
                    expires_at=rec["expires_at"],
                )
                rec["used_count"] = int(rec["used_count"]) + 1
                return _mem_to_dict(rec)
        raise BusinessException(
            "邀请码无效，请向创建者索取最新邀请码",
            code=40308,
            status_code=status.HTTP_403_FORBIDDEN,
        ) from exc
