from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.exceptions import BusinessException
from app.core.permissions import ALL_PERMISSION_CODES
from app.db.mysql import get_session_factory
from app.db.redis import cache_delete, cache_get_json, cache_set_json
from app.models.rbac import SysRole
from app.models.user import User
from app.schemas.system import RoleCreateRequest, RoleUpdateRequest

logger = logging.getLogger(__name__)

_RBAC_CACHE_KEY = "ailove:rbac:roles"
_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,31}$")

_DEFAULT_ROLES: tuple[dict[str, Any], ...] = (
    {
        "code": "super_admin",
        "name": "超级管理员",
        "description": "拥有平台全部管理权限、系统动态配置、审计日志管理与 RBAC 角色授权最高权限。",
        "permissions": ["*"],
        "is_system": True,
        "is_admin_portal": True,
        "is_enabled": True,
        "sort_order": 1,
    },
    {
        "code": "admin",
        "name": "系统管理员",
        "description": "负责账号分配与风控、AI 模型配置与系统参数管理（不含 RBAC 授权变更与日志清理）。",
        "permissions": [
            "dashboard:view",
            "account:view",
            "account:create",
            "account:manage",
            "miniapp_user:view",
            "miniapp_user:manage",
            "ai:chat",
            "ai:config:view",
            "ai:config:manage",
            "kb:view",
            "kb:manage",
            "system:config:view",
            "system:config:manage",
            "log:audit:view",
            "rbac:role:view",
        ],
        "is_system": True,
        "is_admin_portal": True,
        "is_enabled": True,
        "sort_order": 2,
    },
    {
        "code": "operator",
        "name": "运营审计员",
        "description": "面向日常运营与安全巡检：可查看概览、账号、审计日志、AI 配置并管理小程序用户。",
        "permissions": [
            "dashboard:view",
            "account:view",
            "miniapp_user:view",
            "miniapp_user:manage",
            "ai:chat",
            "ai:config:view",
            "kb:view",
            "log:audit:view",
        ],
        "is_system": True,
        "is_admin_portal": True,
        "is_enabled": True,
        "sort_order": 3,
    },
    {
        "code": "user",
        "name": "普通注册用户",
        "description": "标准注册成员，可使用 AI 对话工作台与个人安全中心，不可进入后台管理页面。",
        "permissions": ["ai:chat"],
        "is_system": True,
        "is_admin_portal": False,
        "is_enabled": True,
        "sort_order": 10,
    },
)

# MySQL 不可用时的本地开发/单元测试内存降级仓库
_mem_roles: dict[int, dict[str, Any]] = {}
_mem_role_seq = 10


def _parse_perms(raw: str | list[str]) -> list[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw]
    try:
        parsed = json.loads(raw or "[]")
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    except ValueError:
        return []


def _ensure_mem_seed() -> None:
    if not _mem_roles:
        now = datetime.now(UTC).replace(tzinfo=None)
        for idx, item in enumerate(_DEFAULT_ROLES, start=1):
            _mem_roles[idx] = {
                "id": idx,
                "code": item["code"],
                "name": item["name"],
                "description": item["description"],
                "permissions": list(item["permissions"]),
                "is_system": item["is_system"],
                "is_admin_portal": item["is_admin_portal"],
                "is_enabled": item["is_enabled"],
                "sort_order": item["sort_order"],
                "created_at": now,
                "updated_at": now,
            }


def _validate_permissions(perms: list[str], *, allow_wildcard: bool = False) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for p in perms:
        code = str(p or "").strip()
        if not code:
            continue
        if code == "*":
            if not allow_wildcard:
                raise BusinessException("普通或自定义角色不可授予通配符权限 `*`", code=40061)
        elif code not in ALL_PERMISSION_CODES:
            raise BusinessException(f"存在无效的权限码：{code}", code=40062)
        if code not in seen:
            seen.add(code)
            cleaned.append(code)
    return cleaned


def _row_to_dict(row: SysRole, user_count: int = 0) -> dict[str, Any]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "description": row.description,
        "permissions": _parse_perms(row.permissions),
        "is_system": row.is_system,
        "is_admin_portal": row.is_admin_portal,
        "is_enabled": row.is_enabled,
        "sort_order": row.sort_order,
        "user_count": user_count,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _mem_to_dict(rec: dict[str, Any], user_count: int = 0) -> dict[str, Any]:
    return {
        "id": rec["id"],
        "code": rec["code"],
        "name": rec["name"],
        "description": rec["description"],
        "permissions": list(rec["permissions"]),
        "is_system": rec["is_system"],
        "is_admin_portal": rec["is_admin_portal"],
        "is_enabled": rec["is_enabled"],
        "sort_order": rec["sort_order"],
        "user_count": user_count,
        "updated_at": rec["updated_at"].isoformat() if rec.get("updated_at") else None,
    }


def _mem_role_counts() -> dict[str, int]:
    from app.services.auth_service import _dev_fallback_users, _ensure_dev_fallback_seed

    _ensure_dev_fallback_seed()
    counts: dict[str, int] = {}
    for u in _dev_fallback_users.values():
        r = str(u.get("role") or "")
        counts[r] = counts.get(r, 0) + 1
    return counts


async def invalidate_rbac_cache() -> None:
    await cache_delete(_RBAC_CACHE_KEY)


async def ensure_default_roles() -> None:
    """启动时幂等初始化内置 RBAC 角色。"""
    try:
        factory = get_session_factory()
        async with factory() as session:
            existing_codes = set((await session.execute(select(SysRole.code))).scalars().all())
            added = 0
            for item in _DEFAULT_ROLES:
                if item["code"] not in existing_codes:
                    session.add(
                        SysRole(
                            code=item["code"],
                            name=item["name"],
                            description=item["description"],
                            permissions=json.dumps(item["permissions"], ensure_ascii=False),
                            is_system=item["is_system"],
                            is_admin_portal=item["is_admin_portal"],
                            is_enabled=item["is_enabled"],
                            sort_order=item["sort_order"],
                        )
                    )
                    added += 1
            if added:
                await session.commit()
                await invalidate_rbac_cache()
                logger.info("Initialized %d default RBAC roles.", added)
    except IntegrityError:
        logger.info("Default RBAC roles already initialized by another worker.")
    except Exception as exc:
        logger.warning("Skip RBAC default role bootstrap: %s", exc)


async def _load_role_map() -> dict[str, dict[str, Any]]:
    cached = await cache_get_json(_RBAC_CACHE_KEY)
    if isinstance(cached, dict) and "super_admin" in cached:
        return cached

    try:
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(
                    select(SysRole).order_by(SysRole.sort_order.asc(), SysRole.id.asc())
                )
            ).scalars().all()
            if rows:
                role_map = {
                    r.code: {
                        "id": r.id,
                        "code": r.code,
                        "name": r.name,
                        "permissions": _parse_perms(r.permissions),
                        "is_system": r.is_system,
                        "is_admin_portal": r.is_admin_portal,
                        "is_enabled": r.is_enabled,
                    }
                    for r in rows
                }
                await cache_set_json(_RBAC_CACHE_KEY, role_map, ttl_seconds=300)
                return role_map
    except (SQLAlchemyError, OSError):
        pass

    _ensure_mem_seed()
    return {
        rec["code"]: {
            "id": rec["id"],
            "code": rec["code"],
            "name": rec["name"],
            "permissions": list(rec["permissions"]),
            "is_system": rec["is_system"],
            "is_admin_portal": rec["is_admin_portal"],
            "is_enabled": rec["is_enabled"],
        }
        for rec in _mem_roles.values()
    }


async def get_role_meta(role_code: str) -> dict[str, Any]:
    """实时获取指定角色编码的权限元数据（经 Redis 热缓存）。"""
    clean = (role_code or "").strip()
    role_map = await _load_role_map()
    if clean in role_map:
        return role_map[clean]
    return {
        "id": None,
        "code": clean,
        "name": clean or "未知角色",
        "permissions": [],
        "is_system": False,
        "is_admin_portal": False,
        "is_enabled": False,
    }


async def list_roles(*, only_enabled: bool = False) -> list[dict[str, Any]]:
    try:
        factory = get_session_factory()
        async with factory() as session:
            stmt = select(SysRole)
            if only_enabled:
                stmt = stmt.where(SysRole.is_enabled.is_(True))
            stmt = stmt.order_by(SysRole.sort_order.asc(), SysRole.id.asc())
            rows = (await session.execute(stmt)).scalars().all()

            count_rows = (
                await session.execute(select(User.role, func.count(User.id)).group_by(User.role))
            ).all()
            counts = {str(r): int(c) for r, c in count_rows}
            return [_row_to_dict(r, user_count=counts.get(r.code, 0)) for r in rows]
    except (SQLAlchemyError, OSError):
        _ensure_mem_seed()
        counts = _mem_role_counts()
        recs = list(_mem_roles.values())
        if only_enabled:
            recs = [r for r in recs if r["is_enabled"]]
        recs.sort(key=lambda r: (r["sort_order"], r["id"]))
        return [_mem_to_dict(r, user_count=counts.get(r["code"], 0)) for r in recs]


async def create_role(req: RoleCreateRequest) -> dict[str, Any]:
    code = req.code.strip().lower()
    if not _CODE_PATTERN.match(code):
        raise BusinessException("角色编码格式不合法，须为小写字母开头的 2~32 位字符", code=40060)
    perms = _validate_permissions(req.permissions, allow_wildcard=False)

    try:
        factory = get_session_factory()
        async with factory() as session:
            exists = (
                await session.execute(select(SysRole).where(SysRole.code == code))
            ).scalar_one_or_none()
            if exists is not None:
                raise BusinessException(
                    f"角色编码「{code}」已存在", code=40902, status_code=status.HTTP_409_CONFLICT
                )
            row = SysRole(
                code=code,
                name=req.name.strip(),
                description=req.description.strip(),
                permissions=json.dumps(perms, ensure_ascii=False),
                is_system=False,
                is_admin_portal=req.is_admin_portal,
                is_enabled=req.is_enabled,
                sort_order=req.sort_order,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            await invalidate_rbac_cache()
            return _row_to_dict(row, user_count=0)
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError):
        _ensure_mem_seed()
        if any(r["code"] == code for r in _mem_roles.values()):
            raise BusinessException(
                f"角色编码「{code}」已存在", code=40902, status_code=status.HTTP_409_CONFLICT
            ) from None
        global _mem_role_seq
        _mem_role_seq += 1
        rid = _mem_role_seq
        now = datetime.now(UTC).replace(tzinfo=None)
        rec = {
            "id": rid,
            "code": code,
            "name": req.name.strip(),
            "description": req.description.strip(),
            "permissions": perms,
            "is_system": False,
            "is_admin_portal": req.is_admin_portal,
            "is_enabled": req.is_enabled,
            "sort_order": req.sort_order,
            "created_at": now,
            "updated_at": now,
        }
        _mem_roles[rid] = rec
        await invalidate_rbac_cache()
        return _mem_to_dict(rec, user_count=0)


async def update_role(role_id: int, req: RoleUpdateRequest) -> dict[str, Any]:
    def _apply_rules(
        *,
        code: str,
        current_perms: list[str],
        current_portal: bool,
        current_enabled: bool,
    ) -> tuple[list[str], bool, bool]:
        is_super = code == "super_admin"
        is_protected_base = code in {"super_admin", "user"}

        next_perms = current_perms
        if req.permissions is not None:
            next_perms = _validate_permissions(req.permissions, allow_wildcard=is_super)
            if is_super and "*" not in next_perms:
                raise BusinessException("超级管理员必须保留 `*` 最高权限通配符", code=40063)

        next_portal = current_portal if req.is_admin_portal is None else req.is_admin_portal
        if is_super and not next_portal:
            raise BusinessException("超级管理员不可关闭管理后台入口权限", code=40064)

        next_enabled = current_enabled if req.is_enabled is None else req.is_enabled
        if is_protected_base and not next_enabled:
            raise BusinessException(f"系统基础角色「{code}」不允许被禁用", code=40065)

        return next_perms, next_portal, next_enabled

    try:
        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(SysRole, role_id)
            if row is None:
                raise BusinessException(
                    "目标角色不存在", code=40404, status_code=status.HTTP_404_NOT_FOUND
                )

            next_perms, next_portal, next_enabled = _apply_rules(
                code=row.code,
                current_perms=_parse_perms(row.permissions),
                current_portal=row.is_admin_portal,
                current_enabled=row.is_enabled,
            )
            if req.name is not None:
                row.name = req.name.strip()
            if req.description is not None:
                row.description = req.description.strip()
            row.permissions = json.dumps(next_perms, ensure_ascii=False)
            row.is_admin_portal = next_portal
            row.is_enabled = next_enabled
            if req.sort_order is not None:
                row.sort_order = req.sort_order

            await session.commit()
            await session.refresh(row)
            count = (
                await session.scalar(select(func.count(User.id)).where(User.role == row.code))
                or 0
            )
            await invalidate_rbac_cache()
            return _row_to_dict(row, user_count=int(count))
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        _ensure_mem_seed()
        rec = _mem_roles.get(role_id)
        if rec is None:
            raise BusinessException(
                "目标角色不存在", code=40404, status_code=status.HTTP_404_NOT_FOUND
            ) from exc

        next_perms, next_portal, next_enabled = _apply_rules(
            code=rec["code"],
            current_perms=rec["permissions"],
            current_portal=rec["is_admin_portal"],
            current_enabled=rec["is_enabled"],
        )
        if req.name is not None:
            rec["name"] = req.name.strip()
        if req.description is not None:
            rec["description"] = req.description.strip()
        rec["permissions"] = next_perms
        rec["is_admin_portal"] = next_portal
        rec["is_enabled"] = next_enabled
        if req.sort_order is not None:
            rec["sort_order"] = req.sort_order
        rec["updated_at"] = datetime.now(UTC).replace(tzinfo=None)
        await invalidate_rbac_cache()
        counts = _mem_role_counts()
        return _mem_to_dict(rec, user_count=counts.get(rec["code"], 0))


async def delete_role(role_id: int) -> None:
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = await session.get(SysRole, role_id)
            if row is None:
                raise BusinessException(
                    "目标角色不存在", code=40404, status_code=status.HTTP_404_NOT_FOUND
                )
            if row.is_system:
                raise BusinessException("系统内置角色受到保护，不可删除", code=40066)
            bound_count = (
                await session.scalar(select(func.count(User.id)).where(User.role == row.code))
                or 0
            )
            if bound_count > 0:
                raise BusinessException(
                    f"仍有 {bound_count} 个账号绑定该角色，请先调整其角色后再删除", code=40067
                )
            await session.delete(row)
            await session.commit()
            await invalidate_rbac_cache()
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        _ensure_mem_seed()
        rec = _mem_roles.get(role_id)
        if rec is None:
            raise BusinessException(
                "目标角色不存在", code=40404, status_code=status.HTTP_404_NOT_FOUND
            ) from exc
        if rec["is_system"]:
            raise BusinessException("系统内置角色受到保护，不可删除", code=40066) from exc
        counts = _mem_role_counts()
        bound_count = counts.get(rec["code"], 0)
        if bound_count > 0:
            raise BusinessException(
                f"仍有 {bound_count} 个账号绑定该角色，请先调整其角色后再删除", code=40067
            ) from exc
        _mem_roles.pop(role_id, None)
        await invalidate_rbac_cache()
