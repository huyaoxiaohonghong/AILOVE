from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import require_permissions
from app.core.config import get_settings
from app.core.exceptions import BusinessException
from app.core.security import hash_password
from app.db.mysql import get_session_factory
from app.models.user import User
from app.schemas.account import (
    AccountItem,
    AccountResetPasswordRequest,
    AccountStatusUpdate,
    AdminCreateAccountRequest,
)
from app.schemas.common import ok
from app.schemas.system import AccountRoleUpdate
from app.services import sys_config_service
from app.services.auth_service import (
    admin_create_account,
    admin_update_account_role,
    get_dev_fallback_users,
    validate_password_strength,
)
from app.services.session_service import session_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/accounts", tags=["管理端-平台用户分配与管理"])


@router.get("", summary="分页查询平台用户列表（含实时在线设备数）")
async def list_accounts(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    keyword: str | None = Query(default=None, description="邮箱 / 昵称 / 用户名"),
    role: str | None = Query(default=None, description="super_admin / admin / user"),
    register_source: str | None = Query(
        default=None, description="email_register / admin_assigned / system_bootstrap"
    ),
    is_active: bool | None = Query(default=None),
    _current_admin: dict[str, Any] = Depends(require_permissions("account:view")),
):
    settings = get_settings()
    try:
        factory = get_session_factory()
        async with factory() as session:
            stmt = select(User)
            count_stmt = select(func.count(User.id))

            if keyword:
                pattern = f"%{keyword.strip()}%"
                cond = or_(
                    User.email.like(pattern),
                    User.nickname.like(pattern),
                    User.username.like(pattern),
                )
                stmt = stmt.where(cond)
                count_stmt = count_stmt.where(cond)

            if role:
                stmt = stmt.where(User.role == role)
                count_stmt = count_stmt.where(User.role == role)

            if register_source:
                stmt = stmt.where(User.register_source == register_source)
                count_stmt = count_stmt.where(User.register_source == register_source)

            if is_active is not None:
                stmt = stmt.where(User.is_active == is_active)
                count_stmt = count_stmt.where(User.is_active == is_active)

            total = await session.scalar(count_stmt) or 0
            stmt = stmt.order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size)
            rows = (await session.execute(stmt)).scalars().all()

            items = []
            for row in rows:
                online = await session_service.count_user_sessions(row.id)
                items.append(
                    AccountItem(
                        id=row.id,
                        username=row.username,
                        email=row.email,
                        canonical_email=row.canonical_email,
                        nickname=row.nickname,
                        role=row.role,
                        register_source=row.register_source,
                        email_provider=row.email_provider,
                        email_trust_score=row.email_trust_score,
                        is_active=row.is_active,
                        online_sessions=online,
                        created_by=row.created_by,
                        last_login_at=row.last_login_at,
                        created_at=row.created_at,
                    ).model_dump(mode="json")
                )
            return ok(
                {
                    "items": items,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "db_connected": True,
                }
            )
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("List accounts fallback (MySQL unavailable): %s", exc)
        if not (settings.is_development and settings.ALLOW_DEV_FALLBACK_AUTH):
            return ok(
                {
                    "items": [],
                    "total": 0,
                    "page": page,
                    "page_size": page_size,
                    "db_connected": False,
                }
            )

        rows_mem = list(get_dev_fallback_users().values())
        if keyword:
            kw = keyword.strip().lower()
            rows_mem = [
                r
                for r in rows_mem
                if kw in r["email"].lower()
                or kw in r["nickname"].lower()
                or (r["username"] and kw in r["username"].lower())
            ]
        if role:
            rows_mem = [r for r in rows_mem if r["role"] == role]
        if register_source:
            rows_mem = [r for r in rows_mem if r["register_source"] == register_source]
        if is_active is not None:
            rows_mem = [r for r in rows_mem if r["is_active"] == is_active]

        rows_mem.sort(key=lambda r: r["id"], reverse=True)
        total = len(rows_mem)
        page_rows = rows_mem[(page - 1) * page_size : page * page_size]
        items = []
        for r in page_rows:
            online = await session_service.count_user_sessions(r["id"])
            clean = {k: v for k, v in r.items() if k != "password_hash"}
            clean["online_sessions"] = online
            items.append(AccountItem(**clean).model_dump(mode="json"))
        return ok(
            {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "db_connected": False,
            }
        )


@router.post("", summary="管理员分配创建新用户账号")
async def create_account_by_admin(
    req: AdminCreateAccountRequest,
    current_admin: dict[str, Any] = Depends(require_permissions("account:create")),
):
    creator_id = int(current_admin.get("sub", 0))
    creator_role = str(current_admin.get("role", ""))
    account = await admin_create_account(
        req, creator_admin_id=creator_id, creator_role=creator_role
    )
    return ok(account.model_dump(mode="json"), message="用户分配创建成功")


@router.patch("/{user_id}/role", summary="调整平台账号的 RBAC 角色（变更后立即下线旧会话）")
async def update_account_role(
    user_id: int,
    body: AccountRoleUpdate,
    current_admin: dict[str, Any] = Depends(require_permissions("account:manage")),
):
    operator_id = int(current_admin.get("sub", 0))
    operator_role = str(current_admin.get("role", ""))
    result = await admin_update_account_role(
        user_id,
        body.role,
        operator_id=operator_id,
        operator_role=operator_role,
    )
    return ok(result, message=f"已调整角色为「{result['role_name']}」，原设备会话已刷新")


@router.patch("/{user_id}/status", summary="启用或禁用用户账号（禁用时立即踢除所有在线终端）")
async def update_account_status(
    user_id: int,
    body: AccountStatusUpdate,
    current_admin: dict[str, Any] = Depends(require_permissions("account:manage")),
):
    if user_id == int(current_admin.get("sub", 0)) and not body.is_active:
        raise BusinessException("不能禁用当前正在登录的管理员自身账号", code=40030)

    settings = get_settings()
    try:
        factory = get_session_factory()
        async with factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                raise BusinessException(
                    "目标用户不存在", code=40401, status_code=status.HTTP_404_NOT_FOUND
                )
            if user.role == "super_admin" and not body.is_active:
                raise BusinessException("不允许禁用超级管理员账号", code=40031)
            user.is_active = body.is_active
            await session.commit()
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        if settings.is_development and settings.ALLOW_DEV_FALLBACK_AUTH:
            store = get_dev_fallback_users()
            item = store.get(user_id)
            if item is None:
                raise BusinessException(
                    "目标用户不存在", code=40401, status_code=status.HTTP_404_NOT_FOUND
                ) from exc
            item["is_active"] = body.is_active
        else:
            raise BusinessException(
                "数据库暂不可用", code=50301, status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            ) from exc

    kicked = 0
    if not body.is_active:
        kicked = await session_service.revoke_all_sessions(user_id)
    return ok(
        {"id": user_id, "is_active": body.is_active, "kicked_sessions": kicked},
        message="账号状态已更新",
    )


@router.post("/{user_id}/reset-password", summary="管理员重置用户密码（同时强制下线其全部设备）")
async def reset_account_password(
    user_id: int,
    body: AccountResetPasswordRequest,
    current_admin: dict[str, Any] = Depends(require_permissions("account:manage")),
):
    min_pwd_len = await sys_config_service.get_int("security.password_min_length", default=8)
    validate_password_strength(body.new_password, min_length=min_pwd_len)
    new_hash = hash_password(body.new_password)
    operator_role = str(current_admin.get("role", ""))
    settings = get_settings()

    try:
        factory = get_session_factory()
        async with factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                raise BusinessException(
                    "目标用户不存在", code=40401, status_code=status.HTTP_404_NOT_FOUND
                )
            if user.role == "super_admin" and operator_role != "super_admin":
                raise BusinessException("无权重置超级管理员账号密码", code=40301, status_code=403)
            user.password_hash = new_hash
            await session.commit()
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        if settings.is_development and settings.ALLOW_DEV_FALLBACK_AUTH:
            store = get_dev_fallback_users()
            item = store.get(user_id)
            if item is None:
                raise BusinessException(
                    "目标用户不存在", code=40401, status_code=status.HTTP_404_NOT_FOUND
                ) from exc
            if item["role"] == "super_admin" and operator_role != "super_admin":
                raise BusinessException(
                    "无权重置超级管理员账号密码", code=40301, status_code=403
                ) from exc
            item["password_hash"] = new_hash
        else:
            raise BusinessException(
                "数据库暂不可用", code=50301, status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            ) from exc

    kicked = await session_service.revoke_all_sessions(user_id)
    return ok(
        {"id": user_id, "reset": True, "kicked_sessions": kicked},
        message="密码重置成功，原在线设备已自动下线",
    )


@router.post("/{user_id}/kick", summary="管理员一键强制下线指定用户的全部在线设备")
async def kick_account_sessions(
    user_id: int,
    current_admin: dict[str, Any] = Depends(require_permissions("account:manage")),
):
    current_id = int(current_admin.get("sub", 0))
    if user_id == current_id:
        current_jti = str(current_admin.get("jti", ""))
        kicked = await session_service.revoke_other_sessions(user_id, keep_jti=current_jti)
        return ok({"id": user_id, "kicked_sessions": kicked}, message=f"已下线你的其他 {kicked} 台设备")

    kicked = await session_service.revoke_all_sessions(user_id)
    return ok({"id": user_id, "kicked_sessions": kicked}, message=f"已强制下线该用户的 {kicked} 台在线设备")
