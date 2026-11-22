from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_current_admin
from app.schemas.auth import AdminLoginRequest
from app.schemas.common import ok
from app.services.auth_service import get_fresh_user_profile, login_account
from app.services.session_service import session_service

router = APIRouter(prefix="/auth", tags=["管理端-认证"])


@router.post("/login", summary="管理员登录（需滑动验证）")
async def admin_login(req: AdminLoginRequest, request: Request):
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "")
    ua = request.headers.get("user-agent", "")
    result = await login_account(
        account=req.username,
        password=req.password,
        captcha_token=req.captcha_token,
        require_admin=True,
        client_ip=ip,
        user_agent=ua,
    )
    return ok(result.model_dump())


@router.get("/me", summary="获取当前管理员信息")
async def admin_me(current_admin: dict[str, Any] = Depends(get_current_admin)):
    user_id = int(current_admin.get("sub", 0))
    profile = await get_fresh_user_profile(user_id, current_admin)
    return ok(profile.model_dump())


@router.post("/logout", summary="管理员退出当前设备登录")
async def admin_logout(current_admin: dict[str, Any] = Depends(get_current_admin)):
    user_id = int(current_admin.get("sub", 0))
    jti = str(current_admin.get("jti", ""))
    await session_service.revoke_session(user_id, jti)
    return ok({"logged_out": True}, message="已退出登录")
