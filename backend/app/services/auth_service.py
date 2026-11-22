from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import status
from sqlalchemy import or_, select
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
    UserProfile,
    WxLoginRequest,
    WxLoginResponse,
)
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


def validate_password_strength(password: str) -> None:
    """密码强度校验：至少 8 位，同时包含字母和数字。"""
    if len(password) < 8:
        raise BusinessException("密码长度至少为 8 位", code=40021)
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


async def _issue_web_token(
    profile: UserProfile,
    *,
    client_ip: str = "",
    user_agent: str = "",
) -> AuthTokenResponse:
    """签发 24 小时有效期 JWT 并在 Redis 注册多点设备会话。"""
    is_admin = profile.role in {"super_admin", "admin"}
    access_token, expires_in, jti = create_access_token(
        subject=str(profile.id),
        user_type="admin" if is_admin else "user",
        extra={
            "username": profile.username or "",
            "email": profile.email,
            "nickname": profile.nickname,
            "role": profile.role,
            "register_source": profile.register_source,
            "email_provider": profile.email_provider,
            "email_trust_score": profile.email_trust_score,
            "auth_mode": profile.auth_mode,
        },
    )
    sess = await session_service.create_session(
        user_id=profile.id,
        jti=jti,
        role=profile.role,
        ip=client_ip,
        user_agent=user_agent,
        ttl_seconds=expires_in,
    )
    return AuthTokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        session_id=jti,
        expires_at=str(sess.get("expires_at", "")),
        user=profile,
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


async def register_user_by_email(
    req: EmailRegisterRequest,
    *,
    client_ip: str = "",
    user_agent: str = "",
) -> AuthTokenResponse:
    """用户邮箱自助注册：强制校验一次性滑动验证票据 + 六层正规邮箱识别算法 + 归一化防重。"""
    settings = get_settings()

    await _consume_captcha_or_raise(req.captcha_token, scene="register")

    analysis = await email_trust_analyzer.analyze(
        req.email, check_mx=True, strict_registration=True
    )
    if not analysis.allowed:
        raise BusinessException(
            analysis.summary,
            code=40020,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    validate_password_strength(req.password)

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

    # 2. 滑动验证一次性票据校验
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
            raise BusinessException(
                f"密码连续错误达到上限，账号已锁定 {settings.LOGIN_LOCK_MINUTES} 分钟",
                code=42901,
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        raise BusinessException(
            f"账号或密码错误（还剩 {remain} 次尝试机会）",
            code=40101,
            status_code=status.HTTP_401_UNAUTHORIZED,
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
            if require_admin and user.role not in {"super_admin", "admin"}:
                raise BusinessException(
                    "该账号无管理员权限",
                    code=40300,
                    status_code=status.HTTP_403_FORBIDDEN,
                )

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
        if require_admin and matched["role"] not in {"super_admin", "admin"}:
            raise BusinessException(
                "该账号无管理员权限",
                code=40300,
                status_code=status.HTTP_403_FORBIDDEN,
            ) from exc

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
    """优先从数据库加载最新个人资料（确保跨设备修改昵称后实时同步）。"""
    try:
        factory = get_session_factory()
        async with factory() as session:
            user = await session.get(User, user_id)
            if user is not None:
                return _to_user_profile(user, auth_mode="mysql")
    except (SQLAlchemyError, OSError):
        mem = get_dev_fallback_users().get(user_id)
        if mem is not None:
            return UserProfile(
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

    return UserProfile(
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
            return _to_user_profile(user, auth_mode="mysql")
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
            return UserProfile(
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
        raise BusinessException(
            "数据库暂不可用", code=50301, status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        ) from exc


async def change_own_password(
    user_id: int,
    req: ChangePasswordRequest,
    current_jti: str,
) -> dict[str, Any]:
    """用户自助修改密码，并可选择自动下线其他在线设备。"""
    validate_password_strength(req.new_password)
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


async def admin_create_account(
    req: AdminCreateAccountRequest,
    creator_admin_id: int,
) -> AccountItem:
    """管理员后台直接分配创建用户账号（支持默认正规邮箱校验或显式允许内部邮箱）。"""
    settings = get_settings()
    validate_password_strength(req.password)

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
