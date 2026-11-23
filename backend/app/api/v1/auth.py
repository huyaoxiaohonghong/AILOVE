from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request, status

from app.api.deps import get_current_web_user
from app.core.config import get_settings
from app.core.exceptions import BusinessException
from app.core.rate_limit import rate_limit
from app.schemas.auth import (
    AccountLoginRequest,
    ChangePasswordRequest,
    EmailCheckRequest,
    EmailRegisterRequest,
    UpdateProfileRequest,
)
from app.schemas.common import ok
from app.services import sys_config_service
from app.services.auth_service import (
    change_own_password,
    get_fresh_user_profile,
    login_account,
    register_user_by_email,
    update_own_profile,
)
from app.services.email_validator import email_trust_analyzer
from app.services.session_service import list_user_login_logs, session_service

router = APIRouter(prefix="/auth", tags=["用户认证-多点会话与安全中心"])


def _extract_client_meta(request: Request) -> tuple[str, str]:
    forwarded = request.headers.get("x-forwarded-for")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "")
    ua = request.headers.get("user-agent", "")
    return ip, ua


@router.post(
    "/check-email",
    summary="实时检测邮箱是否符合正规邮箱注册风控策略",
    dependencies=[Depends(rate_limit("check_email", limit=40, window_seconds=60))],
)
async def check_email_policy(req: EmailCheckRequest):
    analysis = await email_trust_analyzer.analyze(
        req.email, check_mx=True, strict_registration=True
    )
    return ok(analysis.to_dict())


@router.post(
    "/register",
    summary="用户邮箱自助注册（需滑动验证 + 正规邮箱算法校验）",
    dependencies=[Depends(rate_limit("register", limit=20, window_seconds=60))],
)
async def register_by_email(req: EmailRegisterRequest, request: Request):
    ip, ua = _extract_client_meta(request)
    result = await register_user_by_email(req, client_ip=ip, user_agent=ua)
    return ok(result.model_dump(), message="注册成功")


@router.post("/login", summary="统一账号密码登录（支持多点登录、24小时自动过期与防爆破锁定）")
async def web_login(req: AccountLoginRequest, request: Request):
    ip, ua = _extract_client_meta(request)
    result = await login_account(
        account=req.account,
        password=req.password,
        captcha_token=req.captcha_token,
        require_admin=False,
        client_ip=ip,
        user_agent=ua,
    )
    return ok(result.model_dump(), message="登录成功")


@router.get("/me", summary="获取当前登录用户信息及当前会话有效期")
async def web_me(current_user: dict[str, Any] = Depends(get_current_web_user)):
    settings = get_settings()
    user_id = int(current_user.get("sub", 0))
    current_jti = str(current_user.get("jti", ""))
    profile = await get_fresh_user_profile(user_id, current_user)
    sessions = await session_service.list_user_sessions(user_id, current_jti=current_jti)
    current_sess = next((s for s in sessions if s["is_current"]), None)

    data = profile.model_dump()
    ttl_hours = await sys_config_service.get_int(
        "security.session_ttl_hours",
        default=max(1, settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES // 60),
    )
    max_sessions = await sys_config_service.get_int(
        "security.max_sessions_per_user", default=settings.MAX_SESSIONS_PER_USER
    )
    data["session"] = {
        "session_id": current_jti,
        "expires_at": current_sess["expires_at"] if current_sess else "",
        "remaining_seconds": current_sess["remaining_seconds"] if current_sess else 0,
        "online_count": len(sessions),
        "max_sessions": max_sessions,
        "ttl_hours": round(float(ttl_hours), 1),
    }
    return ok(data)


@router.post("/logout", summary="退出当前设备登录（不影响其他已登录设备）")
async def web_logout(current_user: dict[str, Any] = Depends(get_current_web_user)):
    user_id = int(current_user.get("sub", 0))
    jti = str(current_user.get("jti", ""))
    await session_service.revoke_session(user_id, jti)
    return ok({"logged_out": True}, message="当前设备已安全退出登录")


@router.patch("/profile", summary="修改当前用户个人资料（昵称）")
async def update_profile(
    req: UpdateProfileRequest,
    current_user: dict[str, Any] = Depends(get_current_web_user),
):
    user_id = int(current_user.get("sub", 0))
    profile = await update_own_profile(user_id, req.nickname)
    return ok(profile.model_dump(), message="个人资料更新成功")


@router.post("/change-password", summary="自助修改登录密码（可选自动下线其他在线设备）")
async def change_password(
    req: ChangePasswordRequest,
    current_user: dict[str, Any] = Depends(get_current_web_user),
):
    user_id = int(current_user.get("sub", 0))
    current_jti = str(current_user.get("jti", ""))
    result = await change_own_password(user_id, req, current_jti=current_jti)
    return ok(result, message="密码修改成功")


@router.get("/sessions", summary="查看当前账号全部多点在线设备及会话到期时间")
async def list_my_sessions(current_user: dict[str, Any] = Depends(get_current_web_user)):
    settings = get_settings()
    user_id = int(current_user.get("sub", 0))
    current_jti = str(current_user.get("jti", ""))
    sessions = await session_service.list_user_sessions(user_id, current_jti=current_jti)
    ttl_hours = await sys_config_service.get_int(
        "security.session_ttl_hours",
        default=max(1, settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES // 60),
    )
    max_sessions = await sys_config_service.get_int(
        "security.max_sessions_per_user", default=settings.MAX_SESSIONS_PER_USER
    )
    return ok(
        {
            "items": sessions,
            "online_count": len(sessions),
            "max_sessions": max_sessions,
            "ttl_hours": round(float(ttl_hours), 1),
        }
    )


@router.delete("/sessions/{session_id}", summary="远程踢除指定在线设备会话")
async def revoke_my_session(
    session_id: str,
    current_user: dict[str, Any] = Depends(get_current_web_user),
):
    user_id = int(current_user.get("sub", 0))
    revoked = await session_service.revoke_session(user_id, session_id)
    if not revoked:
        raise BusinessException(
            "目标会话不存在或已过期",
            code=40402,
            status_code=status.HTTP_404_NOT_FOUND,
        )
    return ok({"session_id": session_id, "revoked": True}, message="已将该设备踢下线")


@router.post("/sessions/revoke-others", summary="一键下线除当前终端外的全部其他设备")
async def revoke_my_other_sessions(current_user: dict[str, Any] = Depends(get_current_web_user)):
    user_id = int(current_user.get("sub", 0))
    current_jti = str(current_user.get("jti", ""))
    count = await session_service.revoke_other_sessions(user_id, keep_jti=current_jti)
    return ok({"revoked_count": count}, message=f"已成功下线其他 {count} 台设备")


@router.get("/login-logs", summary="查看当前账号近期登录安全审计日志")
async def get_my_login_logs(current_user: dict[str, Any] = Depends(get_current_web_user)):
    user_id = int(current_user.get("sub", 0))
    logs = await list_user_login_logs(user_id, limit=20)
    return ok({"items": logs})
