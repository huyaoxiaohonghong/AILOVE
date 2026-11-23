from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.core.config import get_settings
from app.core.exceptions import BusinessException
from app.core.security import create_access_token, hash_password, verify_password
from app.db.mysql import get_session_factory
from app.models.admin_user import AdminUser
from app.models.user import User
from app.models.wechat_user import WechatUser
from app.schemas.account import AccountItem, AdminCreateAccountRequest
from app.schemas.auth import (
    AuthTokenResponse,
    ChangePasswordRequest,
    EmailRegisterRequest,
    MiniappUserProfile,
    ResetPasswordRequest,
    SendEmailCodeRequest,
    UserProfile,
    WxLoginRequest,
    WxLoginResponse,
)
from app.services import email_service, rbac_service, sys_config_service
from app.services.captcha_service import slider_captcha_engine
from app.services.email_validator import email_trust_analyzer
from app.services.session_service import (
    login_rate_limiter,
    record_login_log,
    session_service,
)

logger = logging.getLogger(__name__)

# 本地开发环境且未启动 MySQL 时的内存降级用户仓库（仅开发/无库单元测试使用）
_dev_fallback_users: dict[int, dict[str, Any]] = {}
_dev_fallback_seq = 100


def _ensure_dev_fallback_seed() -> None:
    if 1 not in _dev_fallback_users:
        settings = get_settings()
        _dev_fallback_users[1] = {
            "id": 1,
            "username": settings.DEFAULT_ADMIN_USERNAME,
            "email": "admin@ailove.local",
            "canonical_email": "admin@ailove.local",
            "password_hash": hash_password(settings.DEFAULT_ADMIN_PASSWORD),
            "nickname": "系统管理员 (开发调试模式)",
            "role": "super_admin",
            "register_source": "system_bootstrap",
            "email_provider": "系统内置账号",
            "email_trust_score": 100,
            "is_active": True,
            "created_by": None,
            "last_login_at": None,
            "created_at": datetime.now(UTC).replace(tzinfo=None),
        }


def validate_password_strength(password: str, *, min_length: int = 8) -> None:
    """密码强度校验：满足动态配置的最小长度，且同时包含字母和数字。"""
    min_len = max(6, int(min_length))
    if len(password) < min_len:
        raise BusinessException(f"密码长度至少为 {min_len} 位", code=40021)
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise BusinessException("密码必须同时包含字母和数字", code=40022)


def _to_user_profile(user: User, auth_mode: str = "mysql") -> UserProfile:
    return UserProfile(
        id=user.id,
        username=user.username,
        email=user.email,
        nickname=user.nickname or user.email.split("@", 1)[0],
        role=user.role,
        register_source=user.register_source,
        email_provider=user.email_provider,
        email_trust_score=user.email_trust_score,
        auth_mode=auth_mode,
    )


async def _enrich_profile_rbac(profile: UserProfile) -> UserProfile:
    """为 UserProfile 注入实时 RBAC 角色名称、管理入口标识与权限点列表。"""
    meta = await rbac_service.get_role_meta(profile.role)
    return profile.model_copy(
        update={
            "role_name": str(meta.get("name") or profile.role),
            "is_admin_portal": bool(meta.get("is_admin_portal")),
            "permissions": list(meta.get("permissions") or []),
        }
    )


async def _issue_web_token(
    profile: UserProfile,
    *,
    client_ip: str = "",
    user_agent: str = "",
) -> AuthTokenResponse:
    """签发动态有效期的 JWT 并在 Redis 注册多点设备会话。"""
    settings = get_settings()
    enriched = await _enrich_profile_rbac(profile)
    ttl_hours = await sys_config_service.get_int(
        "security.session_ttl_hours",
        default=max(1, settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES // 60),
    )
    expire_minutes = max(1, ttl_hours) * 60
    access_token, expires_in, jti = create_access_token(
        subject=str(enriched.id),
        user_type="admin" if enriched.is_admin_portal else "user",
        expires_minutes=expire_minutes,
        extra={
            "username": enriched.username or "",
            "email": enriched.email,
            "nickname": enriched.nickname,
            "role": enriched.role,
            "register_source": enriched.register_source,
            "email_provider": enriched.email_provider,
            "email_trust_score": enriched.email_trust_score,
            "auth_mode": enriched.auth_mode,
        },
    )
    sess = await session_service.create_session(
        user_id=enriched.id,
        jti=jti,
        role=enriched.role,
        ip=client_ip,
        user_agent=user_agent,
        ttl_seconds=expires_in,
    )
    return AuthTokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        session_id=jti,
        expires_at=str(sess.get("expires_at", "")),
        user=enriched,
    )


async def _consume_captcha_or_raise(captcha_token: str, scene: str) -> dict[str, Any]:
    verified = await slider_captcha_engine.consume_verified_token(captcha_token, scene=scene)
    if verified is None:
        raise BusinessException(
            "滑动验证未通过或已失效，请重新完成拼图滑块验证",
            code=40010,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return verified


async def ensure_default_admin() -> None:
    """若 MySQL 可用且尚未初始化默认管理员，则自动创建（同步写入 users 与 admin_users）。"""
    settings = get_settings()
    pwd_hash = hash_password(settings.DEFAULT_ADMIN_PASSWORD)
    try:
        factory = get_session_factory()
        async with factory() as session:
            existing_user = (
                await session.execute(
                    select(User).where(User.username == settings.DEFAULT_ADMIN_USERNAME)
                )
            ).scalar_one_or_none()
            if existing_user is None:
                session.add(
                    User(
                        username=settings.DEFAULT_ADMIN_USERNAME,
                        email="admin@ailove.local",
                        canonical_email="admin@ailove.local",
                        password_hash=pwd_hash,
                        nickname="系统管理员",
                        role="super_admin",
                        register_source="system_bootstrap",
                        email_provider="系统内置账号",
                        email_trust_score=100,
                        is_active=True,
                    )
                )

            existing_legacy = (
                await session.execute(
                    select(AdminUser).where(AdminUser.username == settings.DEFAULT_ADMIN_USERNAME)
                )
            ).scalar_one_or_none()
            if existing_legacy is None:
                session.add(
                    AdminUser(
                        username=settings.DEFAULT_ADMIN_USERNAME,
                        password_hash=pwd_hash,
                        nickname="系统管理员",
                        role="super_admin",
                        is_active=True,
                    )
                )

            await session.commit()
            logger.info("Default admin bootstrap verified: %s", settings.DEFAULT_ADMIN_USERNAME)
    except IntegrityError:
        logger.info("Default admin account already initialized by another worker.")
    except Exception as exc:
        logger.warning("Skip default admin bootstrap (MySQL unavailable or not migrated): %s", exc)


async def _find_user_by_email(email: str, canonical_email: str) -> dict[str, Any] | None:
    """按邮箱/归一化邮箱查找平台用户基础信息（兼容 MySQL 与开发降级内存库）。"""
    settings = get_settings()
    try:
        factory = get_session_factory()
        async with factory() as session:
            user = (
                await session.execute(
                    select(User).where(
                        or_(
                            User.email == email,
                            User.canonical_email == canonical_email,
                        )
                    )
                )
            ).scalar_one_or_none()
            if user is None:
                return None
            return {
                "id": int(user.id),
                "email": user.email,
                "username": user.username,
                "is_active": bool(user.is_active),
            }
    except (SQLAlchemyError, OSError):
        if settings.is_development and settings.ALLOW_DEV_FALLBACK_AUTH:
            _ensure_dev_fallback_seed()
            for item in _dev_fallback_users.values():
                if item["email"] == email or item["canonical_email"] == canonical_email:
                    return {
                        "id": int(item["id"]),
                        "email": item["email"],
                        "username": item.get("username"),
                        "is_active": bool(item.get("is_active", True)),
                    }
            return None
        raise


async def send_auth_email_code(req: SendEmailCodeRequest) -> dict[str, Any]:
    """发送注册验证或重置密码用的 6 位一次性邮箱验证码。"""
    if req.scene == "register":
        if await sys_config_service.get_bool("site.maintenance_mode", default=False):
            raise BusinessException(
                "系统当前正在维护中，暂不开放新用户注册",
                code=50305,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not await sys_config_service.get_bool("registration.enabled", default=True):
            raise BusinessException(
                "管理员已关闭邮箱自助注册，请联系管理员分配账号",
                code=40305,
                status_code=status.HTTP_403_FORBIDDEN,
            )
        if not await sys_config_service.get_bool("registration.email_verify_required", default=False):
            raise BusinessException(
                "当前未开启注册邮箱验证码校验，可直接提交注册",
                code=40027,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    if await sys_config_service.get_bool("registration.slider_captcha_enabled", default=True):
        await _consume_captcha_or_raise(req.captcha_token, scene=req.scene)

    if req.scene == "register":
        strict_email = await sys_config_service.get_bool(
            "registration.strict_email_policy", default=True
        )
        analysis = await email_trust_analyzer.analyze(
            req.email, check_mx=True, strict_registration=strict_email
        )
        if not analysis.allowed:
            raise BusinessException(analysis.summary, code=40020)

        existing = await _find_user_by_email(analysis.email, analysis.canonical_email)
        if existing is not None:
            raise BusinessException(
                "该邮箱已注册（含同邮箱别名），请直接登录或找回密码",
                code=40901,
                status_code=status.HTTP_409_CONFLICT,
            )
        return await email_service.issue_and_send_code(
            to_email=analysis.email,
            canonical_email=analysis.canonical_email,
            scene="register",
        )

    analysis = await email_trust_analyzer.analyze(
        req.email, check_mx=False, strict_registration=False
    )
    if analysis.category in {"invalid_syntax", "homograph_attack"}:
        raise BusinessException(analysis.summary, code=40020)

    user_rec = await _find_user_by_email(analysis.email, analysis.canonical_email)
    if user_rec is None:
        raise BusinessException(
            "该邮箱尚未注册账号，请确认后重试",
            code=40401,
            status_code=status.HTTP_404_NOT_FOUND,
        )
    if not user_rec["is_active"]:
        raise BusinessException(
            "该账号已被禁用，请联系管理员处理",
            code=40302,
            status_code=status.HTTP_403_FORBIDDEN,
        )
    if str(user_rec["email"]).lower().endswith(".local"):
        raise BusinessException(
            "系统内置演示邮箱不支持邮件找回密码，请联系管理员重置",
            code=40020,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return await email_service.issue_and_send_code(
        to_email=user_rec["email"],
        canonical_email=analysis.canonical_email,
        scene="reset_password",
    )


async def register_user_by_email(
    req: EmailRegisterRequest,
    *,
    client_ip: str = "",
    user_agent: str = "",
) -> AuthTokenResponse:
    """用户邮箱自助注册：结合系统动态策略校验滑动验证 / 邮箱验证码 + 正规邮箱算法 + 归一化防重。"""
    settings = get_settings()

    if await sys_config_service.get_bool("site.maintenance_mode", default=False):
        raise BusinessException(
            "系统当前正在维护中，暂不开放新用户注册",
            code=50305,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if not await sys_config_service.get_bool("registration.enabled", default=True):
        raise BusinessException(
            "管理员已关闭邮箱自助注册，请联系管理员分配账号",
            code=40305,
            status_code=status.HTTP_403_FORBIDDEN,
        )

    email_verify_required = await sys_config_service.get_bool(
        "registration.email_verify_required", default=False
    )
    if not email_verify_required:
        if await sys_config_service.get_bool("registration.slider_captcha_enabled", default=True):
            await _consume_captcha_or_raise(req.captcha_token, scene="register")

    strict_email = await sys_config_service.get_bool(
        "registration.strict_email_policy", default=True
    )
    analysis = await email_trust_analyzer.analyze(
        req.email, check_mx=True, strict_registration=strict_email
    )
    if not analysis.allowed:
        raise BusinessException(
            analysis.summary,
            code=40020,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    min_pwd_len = await sys_config_service.get_int("security.password_min_length", default=8)
    validate_password_strength(req.password, min_length=min_pwd_len)

    nickname = (req.nickname or "").strip() or analysis.email.split("@", 1)[0][:32]
    pwd_hash = hash_password(req.password)
    now = datetime.now(UTC).replace(tzinfo=None)

    try:
        factory = get_session_factory()
        async with factory() as session:
            existing = (
                await session.execute(
                    select(User).where(
                        or_(
                            User.email == analysis.email,
                            User.canonical_email == analysis.canonical_email,
                        )
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise BusinessException(
                    "该邮箱已注册（含同邮箱别名），请直接登录",
                    code=40901,
                    status_code=status.HTTP_409_CONFLICT,
                )

            if email_verify_required:
                await email_service.verify_and_consume_code(
                    canonical_email=analysis.canonical_email,
                    scene="register",
                    submitted_code=req.email_code,
                )

            user = User(
                username=None,
                email=analysis.email,
                canonical_email=analysis.canonical_email,
                password_hash=pwd_hash,
                nickname=nickname,
                role="user",
                register_source="email_register",
                email_provider=analysis.provider,
                email_trust_score=analysis.trust_score,
                is_active=True,
                last_login_at=now,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            profile = _to_user_profile(user, auth_mode="mysql")
            await record_login_log(
                user_id=user.id,
                account=user.email,
                ip=client_ip,
                user_agent=user_agent,
                status="success",
            )
            return await _issue_web_token(
                profile, client_ip=client_ip, user_agent=user_agent
            )
    except BusinessException:
        raise
    except IntegrityError as exc:
        raise BusinessException(
            "该邮箱已被注册，请直接登录",
            code=40901,
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("MySQL register failed: %s", exc)
        if not (settings.is_development and settings.ALLOW_DEV_FALLBACK_AUTH):
            raise BusinessException(
                "数据库服务暂不可用，请联系管理员",
                code=50301,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc

        _ensure_dev_fallback_seed()
        for item in _dev_fallback_users.values():
            if (
                item["email"] == analysis.email
                or item["canonical_email"] == analysis.canonical_email
            ):
                raise BusinessException(
                    "该邮箱已注册（含同邮箱别名），请直接登录",
                    code=40901,
                    status_code=status.HTTP_409_CONFLICT,
                ) from exc

        if email_verify_required:
            await email_service.verify_and_consume_code(
                canonical_email=analysis.canonical_email,
                scene="register",
                submitted_code=req.email_code,
            )

        global _dev_fallback_seq
        _dev_fallback_seq += 1
        uid = _dev_fallback_seq
        _dev_fallback_users[uid] = {
            "id": uid,
            "username": None,
            "email": analysis.email,
            "canonical_email": analysis.canonical_email,
            "password_hash": pwd_hash,
            "nickname": nickname,
            "role": "user",
            "register_source": "email_register",
            "email_provider": analysis.provider,
            "email_trust_score": analysis.trust_score,
            "is_active": True,
            "created_by": None,
            "last_login_at": now,
            "created_at": now,
        }
        profile = UserProfile(
            id=uid,
            username=None,
            email=analysis.email,
            nickname=nickname,
            role="user",
            register_source="email_register",
            email_provider=analysis.provider,
            email_trust_score=analysis.trust_score,
            auth_mode="dev-fallback",
        )
        await record_login_log(
            user_id=uid,
            account=analysis.email,
            ip=client_ip,
            user_agent=user_agent,
            status="success",
        )
        return await _issue_web_token(profile, client_ip=client_ip, user_agent=user_agent)


async def login_account(
    account: str,
    password: str,
    captcha_token: str,
    *,
    require_admin: bool = False,
    client_ip: str = "",
    user_agent: str = "",
) -> AuthTokenResponse:
    """统一账号登录：防爆破锁定 + 滑动验证 + 24小时多点会话 + 登录安全审计。"""
    settings = get_settings()
    acct = account.strip()
    acct_lower = acct.lower()

    # 1. 登录防爆破锁定检查
    locked, retry_secs = await login_rate_limiter.check_locked(acct_lower)
    if locked:
        mins = max(1, (retry_secs + 59) // 60)
        raise BusinessException(
            f"密码连续输错次数过多，账号已临时锁定，请约 {mins} 分钟后再试",
            code=42901,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    # 2. 滑动验证一次性票据校验（受系统配置动态控制）
    if await sys_config_service.get_bool("registration.slider_captcha_enabled", default=True):
        await _consume_captcha_or_raise(captcha_token, scene="login")

    canonical_lookup = acct_lower
    if "@" in acct_lower:
        local, domain = acct_lower.split("@", 1)
        if domain in {"gmail.com", "googlemail.com"}:
            canonical_lookup = f"{local.replace('.', '')}@gmail.com"

    async def _handle_wrong_password(target_uid: int | None) -> None:
        _, just_locked, remain = await login_rate_limiter.record_failure(acct_lower)
        reason = "触发防爆破锁定" if just_locked else "账号或密码错误"
        await record_login_log(
            user_id=target_uid,
            account=acct,
            ip=client_ip,
            user_agent=user_agent,
            status="failed",
            fail_reason=reason,
        )
        if just_locked:
            lock_mins = await sys_config_service.get_int(
                "security.login_lock_minutes", default=settings.LOGIN_LOCK_MINUTES
            )
            raise BusinessException(
                f"密码连续错误达到上限，账号已锁定 {lock_mins} 分钟",
                code=42901,
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        raise BusinessException(
            f"账号或密码错误（还剩 {remain} 次尝试机会）",
            code=40101,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    async def _validate_role_access(role_code: str, target_uid: int) -> None:
        role_meta = await rbac_service.get_role_meta(role_code)
        if not role_meta.get("is_enabled"):
            await record_login_log(
                user_id=target_uid,
                account=acct,
                ip=client_ip,
                user_agent=user_agent,
                status="failed",
                fail_reason=f"所属角色 {role_code} 已禁用",
            )
            raise BusinessException(
                "所属账号角色已被禁用，请联系管理员",
                code=40301,
                status_code=status.HTTP_403_FORBIDDEN,
            )
        if require_admin and not role_meta.get("is_admin_portal"):
            raise BusinessException(
                "该账号无管理后台访问权限",
                code=40300,
                status_code=status.HTTP_403_FORBIDDEN,
            )
        if await sys_config_service.get_bool("site.maintenance_mode", default=False):
            if not role_meta.get("is_admin_portal"):
                raise BusinessException(
                    "系统正在维护中，暂仅限管理角色登录",
                    code=50305,
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                )

    try:
        factory = get_session_factory()
        async with factory() as session:
            user = (
                await session.execute(
                    select(User).where(
                        or_(
                            User.username == acct,
                            User.email == acct_lower,
                            User.canonical_email == canonical_lookup,
                        )
                    )
                )
            ).scalar_one_or_none()
            if user is None or not verify_password(password, user.password_hash):
                await _handle_wrong_password(user.id if user else None)
                raise AssertionError("unreachable")

            if not user.is_active:
                await record_login_log(
                    user_id=user.id,
                    account=acct,
                    ip=client_ip,
                    user_agent=user_agent,
                    status="failed",
                    fail_reason="账号已被管理员禁用",
                )
                raise BusinessException(
                    "该账号已被管理员禁用，请联系管理员",
                    code=40301,
                    status_code=status.HTTP_403_FORBIDDEN,
                )
            await _validate_role_access(user.role, user.id)

            await login_rate_limiter.clear_failures(acct_lower)
            user.last_login_at = datetime.now(UTC).replace(tzinfo=None)
            await session.commit()
            await record_login_log(
                user_id=user.id,
                account=acct,
                ip=client_ip,
                user_agent=user_agent,
                status="success",
            )
            return await _issue_web_token(
                _to_user_profile(user, auth_mode="mysql"),
                client_ip=client_ip,
                user_agent=user_agent,
            )
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("MySQL login query failed: %s", exc)
        if not (settings.is_development and settings.ALLOW_DEV_FALLBACK_AUTH):
            raise BusinessException(
                "数据库服务暂不可用，请联系管理员",
                code=50301,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc

        _ensure_dev_fallback_seed()
        matched: dict[str, Any] | None = None
        for item in _dev_fallback_users.values():
            if (
                item["username"] == acct
                or item["email"] == acct_lower
                or item["canonical_email"] == canonical_lookup
            ):
                matched = item
                break

        if matched is None or not verify_password(password, matched["password_hash"]):
            await _handle_wrong_password(matched["id"] if matched else None)
            raise AssertionError("unreachable") from exc
        if not matched["is_active"]:
            await record_login_log(
                user_id=matched["id"],
                account=acct,
                ip=client_ip,
                user_agent=user_agent,
                status="failed",
                fail_reason="账号已被管理员禁用",
            )
            raise BusinessException(
                "该账号已被管理员禁用",
                code=40301,
                status_code=status.HTTP_403_FORBIDDEN,
            ) from exc
        await _validate_role_access(matched["role"], matched["id"])

        await login_rate_limiter.clear_failures(acct_lower)
        matched["last_login_at"] = datetime.now(UTC).replace(tzinfo=None)
        profile = UserProfile(
            id=matched["id"],
            username=matched["username"],
            email=matched["email"],
            nickname=matched["nickname"],
            role=matched["role"],
            register_source=matched["register_source"],
            email_provider=matched["email_provider"],
            email_trust_score=matched["email_trust_score"],
            auth_mode="dev-fallback",
        )
        await record_login_log(
            user_id=matched["id"],
            account=acct,
            ip=client_ip,
            user_agent=user_agent,
            status="success",
        )
        return await _issue_web_token(profile, client_ip=client_ip, user_agent=user_agent)


async def get_fresh_user_profile(
    user_id: int, fallback_payload: dict[str, Any]
) -> UserProfile:
    """优先从数据库加载最新个人资料（确保跨设备修改昵称或变更角色后实时同步权限）。"""
    try:
        factory = get_session_factory()
        async with factory() as session:
            user = await session.get(User, user_id)
            if user is not None:
                return await _enrich_profile_rbac(_to_user_profile(user, auth_mode="mysql"))
    except (SQLAlchemyError, OSError):
        mem = get_dev_fallback_users().get(user_id)
        if mem is not None:
            return await _enrich_profile_rbac(
                UserProfile(
                    id=mem["id"],
                    username=mem["username"],
                    email=mem["email"],
                    nickname=mem["nickname"],
                    role=mem["role"],
                    register_source=mem["register_source"],
                    email_provider=mem["email_provider"],
                    email_trust_score=mem["email_trust_score"],
                    auth_mode="dev-fallback",
                )
            )

    return await _enrich_profile_rbac(
        UserProfile(
            id=user_id,
            username=str(fallback_payload.get("username", "")) or None,
            email=str(fallback_payload.get("email", "")),
            nickname=str(fallback_payload.get("nickname", "")),
            role=str(fallback_payload.get("role", "user")),
            register_source=str(fallback_payload.get("register_source", "email_register")),
            email_provider=str(fallback_payload.get("email_provider", "")),
            email_trust_score=int(fallback_payload.get("email_trust_score", 100)),
            auth_mode=str(fallback_payload.get("auth_mode", "mysql")),
        )
    )


async def update_own_profile(user_id: int, nickname: str) -> UserProfile:
    """用户修改自己的昵称。"""
    clean_nick = nickname.strip()
    if not clean_nick:
        raise BusinessException("昵称不能为空", code=40024)
    settings = get_settings()

    try:
        factory = get_session_factory()
        async with factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                raise BusinessException(
                    "用户不存在", code=40401, status_code=status.HTTP_404_NOT_FOUND
                )
            user.nickname = clean_nick
            await session.commit()
            return await _enrich_profile_rbac(_to_user_profile(user, auth_mode="mysql"))
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        if settings.is_development and settings.ALLOW_DEV_FALLBACK_AUTH:
            mem = get_dev_fallback_users().get(user_id)
            if mem is None:
                raise BusinessException(
                    "用户不存在", code=40401, status_code=status.HTTP_404_NOT_FOUND
                ) from exc
            mem["nickname"] = clean_nick
            return await _enrich_profile_rbac(
                UserProfile(
                    id=mem["id"],
                    username=mem["username"],
                    email=mem["email"],
                    nickname=mem["nickname"],
                    role=mem["role"],
                    register_source=mem["register_source"],
                    email_provider=mem["email_provider"],
                    email_trust_score=mem["email_trust_score"],
                    auth_mode="dev-fallback",
                )
            )
        raise BusinessException(
            "数据库暂不可用", code=50301, status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        ) from exc


async def change_own_password(
    user_id: int,
    req: ChangePasswordRequest,
    current_jti: str,
) -> dict[str, Any]:
    """用户自助修改密码，并可选择自动下线其他在线设备。"""
    min_pwd_len = await sys_config_service.get_int("security.password_min_length", default=8)
    validate_password_strength(req.new_password, min_length=min_pwd_len)
    if req.current_password == req.new_password:
        raise BusinessException("新密码不能与当前密码相同", code=40025)

    settings = get_settings()
    new_hash = hash_password(req.new_password)

    try:
        factory = get_session_factory()
        async with factory() as session:
            user = await session.get(User, user_id)
            if user is None:
                raise BusinessException(
                    "用户不存在", code=40401, status_code=status.HTTP_404_NOT_FOUND
                )
            if not verify_password(req.current_password, user.password_hash):
                raise BusinessException("当前原密码输入错误", code=40026)
            user.password_hash = new_hash
            await session.commit()
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        if settings.is_development and settings.ALLOW_DEV_FALLBACK_AUTH:
            mem = get_dev_fallback_users().get(user_id)
            if mem is None:
                raise BusinessException(
                    "用户不存在", code=40401, status_code=status.HTTP_404_NOT_FOUND
                ) from exc
            if not verify_password(req.current_password, mem["password_hash"]):
                raise BusinessException("当前原密码输入错误", code=40026) from exc
            mem["password_hash"] = new_hash
        else:
            raise BusinessException(
                "数据库暂不可用", code=50301, status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            ) from exc

    revoked_others = 0
    if req.logout_other_devices:
        revoked_others = await session_service.revoke_other_sessions(
            user_id=user_id, keep_jti=current_jti
        )
    return {"changed": True, "revoked_other_devices": revoked_others}


async def reset_password_by_email(
    req: ResetPasswordRequest,
    *,
    client_ip: str = "",
    user_agent: str = "",
) -> dict[str, Any]:
    """通过邮箱一次性验证码重置登录密码，并自动下线全部旧会话与解除锁定。"""
    analysis = await email_trust_analyzer.analyze(
        req.email, check_mx=False, strict_registration=False
    )
    if analysis.category in {"invalid_syntax", "homograph_attack"}:
        raise BusinessException(analysis.summary, code=40020)

    min_pwd_len = await sys_config_service.get_int("security.password_min_length", default=8)
    validate_password_strength(req.new_password, min_length=min_pwd_len)

    settings = get_settings()
    new_hash = hash_password(req.new_password)
    target_user_id = 0
    target_email = analysis.email
    target_username: str | None = None

    try:
        factory = get_session_factory()
        async with factory() as session:
            user = (
                await session.execute(
                    select(User).where(
                        or_(
                            User.email == analysis.email,
                            User.canonical_email == analysis.canonical_email,
                        )
                    )
                )
            ).scalar_one_or_none()
            if user is None:
                raise BusinessException(
                    "该邮箱尚未注册账号",
                    code=40401,
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            if not user.is_active:
                raise BusinessException(
                    "该账号已被禁用，请联系管理员处理",
                    code=40302,
                    status_code=status.HTTP_403_FORBIDDEN,
                )

            await email_service.verify_and_consume_code(
                canonical_email=analysis.canonical_email,
                scene="reset_password",
                submitted_code=req.email_code,
            )
            user.password_hash = new_hash
            await session.commit()
            target_user_id = int(user.id)
            target_email = user.email
            target_username = user.username
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        if settings.is_development and settings.ALLOW_DEV_FALLBACK_AUTH:
            _ensure_dev_fallback_seed()
            matched = next(
                (
                    item
                    for item in _dev_fallback_users.values()
                    if item["email"] == analysis.email
                    or item["canonical_email"] == analysis.canonical_email
                ),
                None,
            )
            if matched is None:
                raise BusinessException(
                    "该邮箱尚未注册账号",
                    code=40401,
                    status_code=status.HTTP_404_NOT_FOUND,
                ) from exc
            if not matched.get("is_active", True):
                raise BusinessException(
                    "该账号已被禁用，请联系管理员处理",
                    code=40302,
                    status_code=status.HTTP_403_FORBIDDEN,
                ) from exc

            await email_service.verify_and_consume_code(
                canonical_email=analysis.canonical_email,
                scene="reset_password",
                submitted_code=req.email_code,
            )
            matched["password_hash"] = new_hash
            target_user_id = int(matched["id"])
            target_email = matched["email"]
            target_username = matched.get("username")
        else:
            raise BusinessException(
                "数据库暂不可用",
                code=50301,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc

    revoked_count = await session_service.revoke_all_sessions(target_user_id)
    await login_rate_limiter.clear_failures(target_email.lower())
    if target_username:
        await login_rate_limiter.clear_failures(target_username.lower())
    await record_login_log(
        user_id=target_user_id,
        account=target_email,
        ip=client_ip,
        user_agent=user_agent,
        status="success",
        fail_reason="email_password_reset",
    )
    return {
        "reset": True,
        "email": target_email,
        "revoked_sessions": revoked_count,
    }


async def admin_create_account(
    req: AdminCreateAccountRequest,
    creator_admin_id: int,
    creator_role: str = "super_admin",
) -> AccountItem:
    """管理员后台直接分配创建用户账号（支持默认正规邮箱校验或显式允许内部邮箱，并校验目标 RBAC 角色）。"""
    settings = get_settings()
    target_role = req.role.strip()
    role_meta = await rbac_service.get_role_meta(target_role)
    if not role_meta.get("id") and target_role not in {"super_admin", "admin", "operator", "user"}:
        raise BusinessException(f"目标角色「{target_role}」不存在", code=40068)
    if not role_meta.get("is_enabled"):
        raise BusinessException(f"目标角色「{target_role}」不存在或已禁用", code=40068)
    if target_role == "super_admin" and creator_role != "super_admin":
        raise BusinessException("仅超级管理员可分配创建超级管理员账号", code=40301, status_code=403)

    min_pwd_len = await sys_config_service.get_int("security.password_min_length", default=8)
    validate_password_strength(req.password, min_length=min_pwd_len)

    analysis = await email_trust_analyzer.analyze(
        req.email,
        check_mx=True,
        strict_registration=not req.allow_non_mainstream_email,
    )
    if analysis.category in {"invalid_syntax", "homograph_attack"}:
        raise BusinessException(analysis.summary, code=40020)
    if not req.allow_non_mainstream_email and not analysis.allowed:
        raise BusinessException(
            f"{analysis.summary}（如需为内部成员分配域名邮箱，请勾选「允许分配非常规/域名邮箱」）",
            code=40020,
        )

    username = (req.username or "").strip() or None
    if username and not re.match(r"^[A-Za-z0-9_.-]{3,32}$", username):
        raise BusinessException("用户名须为 3~32 位字母、数字、点、下划线或连字符", code=40023)

    pwd_hash = hash_password(req.password)
    now = datetime.now(UTC).replace(tzinfo=None)

    try:
        factory = get_session_factory()
        async with factory() as session:
            conds = [
                User.email == analysis.email,
                User.canonical_email == analysis.canonical_email,
            ]
            if username:
                conds.append(User.username == username)
            existing = (await session.execute(select(User).where(or_(*conds)))).scalar_one_or_none()
            if existing is not None:
                raise BusinessException(
                    "邮箱或用户名已存在，请更换后重试",
                    code=40901,
                    status_code=status.HTTP_409_CONFLICT,
                )

            user = User(
                username=username,
                email=analysis.email,
                canonical_email=analysis.canonical_email,
                password_hash=pwd_hash,
                nickname=req.nickname.strip(),
                role=req.role,
                register_source="admin_assigned",
                email_provider=analysis.provider,
                email_trust_score=analysis.trust_score,
                is_active=True,
                created_by=creator_admin_id,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return AccountItem(
                id=user.id,
                username=user.username,
                email=user.email,
                canonical_email=user.canonical_email,
                nickname=user.nickname,
                role=user.role,
                register_source=user.register_source,
                email_provider=user.email_provider,
                email_trust_score=user.email_trust_score,
                is_active=user.is_active,
                online_sessions=0,
                created_by=user.created_by,
                last_login_at=user.last_login_at,
                created_at=user.created_at,
            )
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("MySQL admin_create_account failed: %s", exc)
        if not (settings.is_development and settings.ALLOW_DEV_FALLBACK_AUTH):
            raise BusinessException(
                "数据库暂不可用，无法分配用户",
                code=50301,
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ) from exc

        _ensure_dev_fallback_seed()
        for item in _dev_fallback_users.values():
            if (
                item["email"] == analysis.email
                or item["canonical_email"] == analysis.canonical_email
                or (username and item["username"] == username)
            ):
                raise BusinessException(
                    "邮箱或用户名已存在",
                    code=40901,
                    status_code=status.HTTP_409_CONFLICT,
                ) from exc

        global _dev_fallback_seq
        _dev_fallback_seq += 1
        uid = _dev_fallback_seq
        record = {
            "id": uid,
            "username": username,
            "email": analysis.email,
            "canonical_email": analysis.canonical_email,
            "password_hash": pwd_hash,
            "nickname": req.nickname.strip(),
            "role": req.role,
            "register_source": "admin_assigned",
            "email_provider": analysis.provider,
            "email_trust_score": analysis.trust_score,
            "is_active": True,
            "online_sessions": 0,
            "created_by": creator_admin_id,
            "last_login_at": None,
            "created_at": now,
        }
        _dev_fallback_users[uid] = record
        return AccountItem(**{k: v for k, v in record.items() if k != "password_hash"})


def get_dev_fallback_users() -> dict[int, dict[str, Any]]:
    _ensure_dev_fallback_seed()
    return _dev_fallback_users


async def admin_update_account_role(
    user_id: int,
    role_code: str,
    *,
    operator_id: int,
    operator_role: str,
) -> dict[str, Any]:
    """变更指定账号的 RBAC 角色，并强制下线其全部旧会话以使新权限立即生效。"""
    clean_role = role_code.strip()
    if user_id == operator_id:
        raise BusinessException("不能修改当前登录管理员自身的角色", code=40069)

    role_meta = await rbac_service.get_role_meta(clean_role)
    if not role_meta.get("is_enabled"):
        raise BusinessException(f"目标角色「{clean_role}」不存在或已禁用", code=40068)
    if clean_role == "super_admin" and operator_role != "super_admin":
        raise BusinessException("仅超级管理员有权授予超级管理员角色", code=40301, status_code=403)

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
                raise BusinessException(
                    "无权降级或修改超级管理员账号角色", code=40301, status_code=403
                )
            if user.role == "super_admin" and clean_role != "super_admin":
                sup_cnt = (
                    await session.scalar(
                        select(func.count(User.id)).where(
                            User.role == "super_admin", User.is_active.is_(True)
                        )
                    )
                    or 0
                )
                if sup_cnt <= 1:
                    raise BusinessException("至少须保留一位活跃超级管理员，不可降级", code=40070)

            user.role = clean_role
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
                    "无权降级或修改超级管理员账号角色", code=40301, status_code=403
                ) from exc
            if item["role"] == "super_admin" and clean_role != "super_admin":
                sup_cnt = sum(
                    1
                    for u in store.values()
                    if u.get("role") == "super_admin" and u.get("is_active")
                )
                if sup_cnt <= 1:
                    raise BusinessException(
                        "至少须保留一位活跃超级管理员，不可降级", code=40070
                    ) from exc
            item["role"] = clean_role
        else:
            raise BusinessException(
                "数据库暂不可用", code=50301, status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            ) from exc

    kicked = await session_service.revoke_all_sessions(user_id)
    return {
        "id": user_id,
        "role": clean_role,
        "role_name": role_meta.get("name", clean_role),
        "kicked_sessions": kicked,
    }


async def _exchange_wx_code(code: str) -> tuple[str, str | None, bool]:
    """调用微信 jscode2session 换取 openid/unionid；未配置 AppSecret 时在开发环境生成模拟 openid。"""
    settings = get_settings()
    if settings.is_wechat_configured:
        url = "https://api.weixin.qq.com/sns/jscode2session"
        params = {
            "appid": settings.WECHAT_APP_ID,
            "secret": settings.WECHAT_APP_SECRET,
            "js_code": code,
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()

        if payload.get("errcode", 0) != 0:
            raise BusinessException(
                f"微信登录凭证校验失败: {payload.get('errmsg', 'unknown error')}",
                code=40102,
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        openid = payload.get("openid")
        if not openid:
            raise BusinessException(
                "未获取到微信 OpenID",
                code=40103,
                status_code=status.HTTP_401_UNAUTHORIZED,
            )
        return openid, payload.get("unionid"), False

    if not settings.is_development:
        raise BusinessException(
            "服务端尚未配置微信小程序 AppID/AppSecret",
            code=50002,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]
    return f"dev_openid_{digest}", None, True


async def login_wechat_user(req: WxLoginRequest) -> WxLoginResponse:
    """微信小程序登录，支持真实微信凭证交换及本地开发模拟登录。"""
    openid, unionid, is_mock_wx = await _exchange_wx_code(req.code)
    now = datetime.now(UTC).replace(tzinfo=None)
    nickname = req.nickname or f"微信用户_{openid[-4:]}"
    avatar_url = req.avatar_url or ""

    user_profile = MiniappUserProfile(
        id=0,
        openid=openid,
        nickname=nickname,
        avatar_url=avatar_url,
        status=1,
    )

    try:
        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(select(WechatUser).where(WechatUser.openid == openid))
            user = result.scalar_one_or_none()
            if user is None:
                user = WechatUser(
                    openid=openid,
                    unionid=unionid,
                    nickname=nickname,
                    avatar_url=avatar_url,
                    status=1,
                    last_login_at=now,
                )
                session.add(user)
                await session.flush()
            else:
                if user.status == 0:
                    raise BusinessException(
                        "当前微信账号已被禁用",
                        code=40302,
                        status_code=status.HTTP_403_FORBIDDEN,
                    )
                if req.nickname:
                    user.nickname = req.nickname
                if req.avatar_url:
                    user.avatar_url = req.avatar_url
                if unionid and not user.unionid:
                    user.unionid = unionid
                user.last_login_at = now

            await session.commit()
            user_profile = MiniappUserProfile(
                id=user.id,
                openid=user.openid,
                nickname=user.nickname,
                avatar_url=user.avatar_url,
                phone=user.phone,
                status=user.status,
            )
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("WeChat login DB persistence skipped (MySQL unavailable): %s", exc)

    token, expires_in, _ = create_access_token(
        subject=str(user_profile.id or openid),
        user_type="miniapp",
        extra={
            "openid": user_profile.openid,
            "nickname": user_profile.nickname,
            "avatar_url": user_profile.avatar_url,
        },
    )
    return WxLoginResponse(
        access_token=token,
        expires_in=expires_in,
        user=user_profile,
        is_mock_wx=is_mock_wx,
    )
