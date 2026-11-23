from __future__ import annotations

from collections.abc import Callable
from typing import Any

import jwt
from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import BusinessException
from app.core.permissions import has_permission
from app.core.security import decode_access_token
from app.services.rbac_service import get_role_meta
from app.services.session_service import session_service

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_token_payload(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    """解析并校验 Bearer Token；对网站/管理端会话实时校验 Redis 多点会话状态（过期与撤销即时生效）。"""
    if credentials is None or not credentials.credentials:
        raise BusinessException(
            "未登录或登录凭证缺失",
            code=40100,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError as exc:
        raise BusinessException(
            "登录凭证已自动过期，请重新登录",
            code=40104,
            status_code=status.HTTP_401_UNAUTHORIZED,
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise BusinessException(
            "无效的登录凭证",
            code=40105,
            status_code=status.HTTP_401_UNAUTHORIZED,
        ) from exc

    # 对网站端/管理端用户实时校验 Redis 会话是否仍然活跃（支持单端退出、多点踢下线与到期过期）
    if payload.get("type") in {"admin", "user"}:
        jti = str(payload.get("jti", ""))
        session_info = await session_service.validate_and_touch_session(jti)
        if session_info is None:
            raise BusinessException(
                "当前会话已过期或已在其他终端下线，请重新登录",
                code=40106,
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        payload["_session"] = session_info

    return payload


async def get_current_web_user(
    payload: dict[str, Any] = Depends(get_current_token_payload),
) -> dict[str, Any]:
    """校验当前请求为已登录网站端用户（包含普通注册用户、管理员分配用户与管理角色）。"""
    if payload.get("type") not in {"admin", "user"}:
        raise BusinessException(
            "无权访问网站端接口",
            code=40300,
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return payload


async def get_current_admin(
    payload: dict[str, Any] = Depends(get_current_token_payload),
) -> dict[str, Any]:
    """校验当前请求拥有可进入管理中台的角色权限（兼容 super_admin / admin / operator / 自定义管理角色）。"""
    if payload.get("type") not in {"admin", "user"}:
        raise BusinessException(
            "仅管理端角色有权访问该接口",
            code=40300,
            status_code=status.HTTP_403_FORBIDDEN,
        )
    role_code = str(payload.get("role") or "")
    role_meta = await get_role_meta(role_code)
    if not role_meta.get("is_enabled") or not role_meta.get("is_admin_portal"):
        raise BusinessException(
            "仅管理端角色有权访问该接口",
            code=40300,
            status_code=status.HTTP_403_FORBIDDEN,
        )
    payload["_role_meta"] = role_meta
    return payload


def require_permissions(*required_perms: str) -> Callable[..., Any]:
    """细粒度 RBAC 权限依赖工厂：实时查询角色最新授权并校验全部所需权限点。"""

    async def _permission_guard(
        payload: dict[str, Any] = Depends(get_current_web_user),
    ) -> dict[str, Any]:
        role_code = str(payload.get("role") or "")
        role_meta = await get_role_meta(role_code)
        if not role_meta.get("is_enabled"):
            raise BusinessException(
                f"当前角色「{role_code}」已被禁用，请联系超级管理员",
                code=40301,
                status_code=status.HTTP_403_FORBIDDEN,
            )
        granted = list(role_meta.get("permissions") or [])
        missing = [perm for perm in required_perms if not has_permission(granted, perm)]
        if missing:
            raise BusinessException(
                f"权限不足，缺少操作权限：{', '.join(missing)}",
                code=40301,
                status_code=status.HTTP_403_FORBIDDEN,
            )
        payload["_role_meta"] = role_meta
        return payload

    return _permission_guard


async def get_current_miniapp_user(
    payload: dict[str, Any] = Depends(get_current_token_payload),
) -> dict[str, Any]:
    """校验当前请求为小程序用户身份。"""
    if payload.get("type") != "miniapp":
        raise BusinessException(
            "无权访问小程序接口",
            code=40303,
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return payload
