from __future__ import annotations

import asyncio
import html
import json
import logging
import secrets
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any, Literal

from fastapi import status

from app.core.exceptions import BusinessException
from app.db.redis import get_redis
from app.services import sys_config_service

logger = logging.getLogger(__name__)

EmailCodeScene = Literal["register", "reset_password"]

_CODE_TTL_DEFAULT_SECONDS = 600
_RESEND_COOLDOWN_SECONDS = 60
_MAX_VERIFY_ATTEMPTS = 5

# Redis 不可用时的内存降级仓库
_mem_email_codes: dict[str, tuple[dict[str, Any], float]] = {}
_mem_email_cooldowns: dict[str, float] = {}


@dataclass(frozen=True)
class SmtpRuntimeConfig:
    enabled: bool
    host: str
    port: int
    security: str
    username: str
    password: str
    from_email: str
    from_name: str
    code_expire_minutes: int
    site_name: str

    @property
    def sender_email(self) -> str:
        return (self.from_email or self.username).strip()

    @property
    def is_configured(self) -> bool:
        if self.security == "none":
            return bool(self.host.strip() and self.sender_email)
        return bool(self.host.strip() and self.username.strip() and self.password.strip())


async def get_smtp_runtime_config() -> SmtpRuntimeConfig:
    enabled = await sys_config_service.get_bool("email.smtp_enabled", default=False)
    host = await sys_config_service.get_str("email.smtp_host", default="")
    port = await sys_config_service.get_int("email.smtp_port", default=465)
    security = (await sys_config_service.get_str("email.smtp_security", default="ssl")).lower()
    if security not in {"ssl", "starttls", "none"}:
        security = "ssl"
    username = await sys_config_service.get_str("email.smtp_username", default="")
    password = await sys_config_service.get_secret("email.smtp_password", default="")
    from_email = await sys_config_service.get_str("email.from_email", default="")
    from_name = await sys_config_service.get_str("email.from_name", default="AILOVE 安全中心")
    code_expire_minutes = await sys_config_service.get_int("email.code_expire_minutes", default=10)
    site_name = await sys_config_service.get_str("site.name", default="AILOVE")

    return SmtpRuntimeConfig(
        enabled=enabled,
        host=host.strip(),
        port=max(1, min(65535, port)),
        security=security,
        username=username.strip(),
        password=password,
        from_email=from_email.strip(),
        from_name=from_name.strip() or "AILOVE 安全中心",
        code_expire_minutes=max(3, min(30, code_expire_minutes)),
        site_name=site_name.strip() or "AILOVE",
    )


def _send_smtp_sync(cfg: SmtpRuntimeConfig, msg: EmailMessage) -> None:
    """同步执行 SMTP 邮件投递（由 asyncio.to_thread 调度）。"""
    timeout = 12
    try:
        if cfg.security == "ssl":
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=timeout, context=ctx) as server:
                server.login(cfg.username, cfg.password)
                server.send_message(msg)
        elif cfg.security == "starttls":
            ctx = ssl.create_default_context()
            with smtplib.SMTP(cfg.host, cfg.port, timeout=timeout) as server:
                server.ehlo()
                server.starttls(context=ctx)
                server.ehlo()
                server.login(cfg.username, cfg.password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(cfg.host, cfg.port, timeout=timeout) as server:
                if cfg.username and cfg.password:
                    server.login(cfg.username, cfg.password)
                server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise BusinessException(
            "SMTP 身份认证失败，请核对发件账号与授权码/密码是否正确",
            code=50211,
            status_code=status.HTTP_502_BAD_GATEWAY,
        ) from exc
    except (smtplib.SMTPException, OSError, TimeoutError, ssl.SSLError) as exc:
        raise BusinessException(
            f"SMTP 邮件发送失败：{exc}",
            code=50210,
            status_code=status.HTTP_502_BAD_GATEWAY,
        ) from exc


def _build_code_email_html(
    *,
    site_name: str,
    scene_title: str,
    code: str,
    expire_minutes: int,
) -> str:
    safe_site = html.escape(site_name)
    safe_scene = html.escape(scene_title)
    safe_code = html.escape(code)
    body_style = (
        "margin:0;padding:24px;background:#F7F4F1;color:#1A161D;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC',sans-serif;"
    )
    card_style = (
        "max-width:520px;margin:0 auto;background:#FFFFFF;"
        "border:1px solid #EAE2D8;border-radius:16px;padding:32px 28px;"
    )
    box_style = (
        "background:#FFF6F7;border:1px dashed #F4B3C0;border-radius:12px;"
        "padding:18px;text-align:center;margin-bottom:22px;"
    )
    code_style = (
        "font-family:ui-monospace,SFMono-Regular,Menlo,monospace;"
        "font-size:32px;font-weight:700;letter-spacing:8px;color:#C83553;"
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<body style="{body_style}">
  <div style="{card_style}">
    <div style="font-size:13px;font-weight:600;color:#C83553;letter-spacing:0.04em;margin-bottom:8px;">
      {safe_site} 安全中心
    </div>
    <h1 style="margin:0 0 12px;font-size:20px;font-weight:700;color:#1A161D;">{safe_scene}</h1>
    <p style="margin:0 0 22px;font-size:14px;line-height:1.65;color:#524B57;">
      您好，您正在进行「{safe_scene}」安全操作。请在页面中输入以下 6 位一次性验证码：
    </p>
    <div style="{box_style}">
      <span style="{code_style}">
        {safe_code}
      </span>
    </div>
    <p style="margin:0 0 8px;font-size:13px;line-height:1.6;color:#6E6574;">
      • 该验证码 <strong>{expire_minutes} 分钟内</strong>有效，验证成功或连续输错 5 次后将立即失效。
    </p>
    <p style="margin:0;font-size:12.5px;line-height:1.6;color:#9B92A1;">
      如非本人操作，请直接忽略本邮件并检查账号安全设置。系统自动发出，请勿直接回复。
    </p>
  </div>
</body>
</html>"""


async def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
    *,
    allow_disabled: bool = False,
) -> tuple[SmtpRuntimeConfig, int]:
    cfg = await get_smtp_runtime_config()
    if not allow_disabled and not cfg.enabled:
        raise BusinessException(
            "管理员尚未启用 SMTP 邮件服务，暂无法发送邮箱验证码",
            code=50310,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if not cfg.is_configured:
        raise BusinessException(
            "SMTP 服务器地址、发件账号或授权码尚未配置完整",
            code=40080,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((cfg.from_name, cfg.sender_email))
    msg["To"] = to_email
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    t0 = time.perf_counter()
    await asyncio.to_thread(_send_smtp_sync, cfg, msg)
    latency_ms = max(1, int((time.perf_counter() - t0) * 1000))
    return cfg, latency_ms


async def send_test_email(to_email: str) -> dict[str, Any]:
    target = (to_email or "").strip()
    if "@" not in target or "." not in target.split("@", 1)[-1]:
        raise BusinessException("请输入有效的收件邮箱地址", code=40020)

    cfg = await get_smtp_runtime_config()
    html_body = _build_code_email_html(
        site_name=cfg.site_name,
        scene_title="SMTP 邮件通道连通性测试",
        code="888666",
        expire_minutes=cfg.code_expire_minutes,
    )
    text_body = f"【{cfg.site_name}】这是一封 SMTP 连通性测试邮件，代表您的发信通道配置成功。"
    used_cfg, latency_ms = await send_email(
        to_email=target,
        subject=f"【{cfg.site_name}】SMTP 邮件配置测试成功",
        html_body=html_body,
        text_body=text_body,
        allow_disabled=True,
    )
    return {
        "sent": True,
        "to_email": target,
        "host": used_cfg.host,
        "port": used_cfg.port,
        "security": used_cfg.security,
        "latency_ms": latency_ms,
    }


def _code_key(scene: EmailCodeScene, canonical_email: str) -> str:
    return f"ailove:email_code:{scene}:{canonical_email.lower()}"


def _cooldown_key(scene: EmailCodeScene, canonical_email: str) -> str:
    return f"ailove:email_cd:{scene}:{canonical_email.lower()}"


def _prune_mem() -> None:
    now = time.time()
    for k in [key for key, (_, exp) in _mem_email_codes.items() if exp <= now]:
        _mem_email_codes.pop(k, None)
    for k in [key for key, exp in _mem_email_cooldowns.items() if exp <= now]:
        _mem_email_cooldowns.pop(k, None)


async def _get_cooldown_remaining(cd_key: str) -> int:
    try:
        redis = get_redis()
        ttl = await redis.ttl(cd_key)
        return max(0, int(ttl)) if ttl and int(ttl) > 0 else 0
    except Exception:
        _prune_mem()
        exp = _mem_email_cooldowns.get(cd_key)
        if exp and exp > time.time():
            return max(1, int(exp - time.time()))
        return 0


async def _set_code_and_cooldown(
    code_key: str,
    cd_key: str,
    payload: dict[str, Any],
    code_ttl_seconds: int,
) -> None:
    try:
        redis = get_redis()
        pipe = redis.pipeline()
        pipe.set(code_key, json.dumps(payload), ex=code_ttl_seconds)
        pipe.set(cd_key, "1", ex=_RESEND_COOLDOWN_SECONDS)
        await pipe.execute()
        return
    except Exception:
        _prune_mem()
        now = time.time()
        _mem_email_codes[code_key] = (payload, now + code_ttl_seconds)
        _mem_email_cooldowns[cd_key] = now + _RESEND_COOLDOWN_SECONDS


async def _get_code_record(code_key: str) -> tuple[dict[str, Any] | None, int]:
    try:
        redis = get_redis()
        raw = await redis.get(code_key)
        if not raw:
            return None, 0
        ttl = int(await redis.ttl(code_key))
        if ttl == -2:
            return None, 0
        return json.loads(raw), (max(1, ttl) if ttl > 0 else _CODE_TTL_DEFAULT_SECONDS)
    except Exception:
        _prune_mem()
        rec = _mem_email_codes.get(code_key)
        if not rec:
            return None, 0
        payload, exp = rec
        if exp <= time.time():
            _mem_email_codes.pop(code_key, None)
            return None, 0
        return dict(payload), max(1, int(exp - time.time()))


async def _update_code_record(code_key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
    try:
        redis = get_redis()
        await redis.set(code_key, json.dumps(payload), ex=max(1, ttl_seconds))
        return
    except Exception:
        _mem_email_codes[code_key] = (payload, time.time() + max(1, ttl_seconds))


async def _delete_code_record(code_key: str) -> None:
    try:
        redis = get_redis()
        await redis.delete(code_key)
        return
    except Exception:
        _mem_email_codes.pop(code_key, None)


async def issue_and_send_code(
    *,
    to_email: str,
    canonical_email: str,
    scene: EmailCodeScene,
) -> dict[str, Any]:
    """生成并发送 6 位一次性邮箱验证码（含 60 秒冷却防刷）。"""
    c_key = _code_key(scene, canonical_email)
    cd_key = _cooldown_key(scene, canonical_email)

    remaining = await _get_cooldown_remaining(cd_key)
    if remaining > 0:
        raise BusinessException(
            f"验证码发送过于频繁，请 {remaining} 秒后再试",
            code=42905,
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    cfg = await get_smtp_runtime_config()
    if not cfg.enabled:
        raise BusinessException(
            "管理员尚未启用 SMTP 邮件服务，暂无法发送邮箱验证码",
            code=50310,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if not cfg.is_configured:
        raise BusinessException(
            "SMTP 服务器地址、发件账号或授权码尚未配置完整",
            code=40080,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    code = f"{secrets.randbelow(1_000_000):06d}"
    scene_title = "邮箱自助注册验证" if scene == "register" else "重置登录密码验证"
    subject = f"【{cfg.site_name}】{scene_title}验证码：{code}"
    html_body = _build_code_email_html(
        site_name=cfg.site_name,
        scene_title=scene_title,
        code=code,
        expire_minutes=cfg.code_expire_minutes,
    )
    text_body = (
        f"【{cfg.site_name}】您正在进行{scene_title}，验证码：{code}，"
        f"{cfg.code_expire_minutes} 分钟内有效，请勿泄露给他人。"
    )

    await send_email(
        to_email=to_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        allow_disabled=False,
    )
    await _set_code_and_cooldown(
        c_key,
        cd_key,
        {"code": code, "attempts": 0, "max_attempts": _MAX_VERIFY_ATTEMPTS},
        code_ttl_seconds=cfg.code_expire_minutes * 60,
    )
    return {
        "sent": True,
        "email": to_email,
        "scene": scene,
        "expire_minutes": cfg.code_expire_minutes,
        "cooldown_seconds": _RESEND_COOLDOWN_SECONDS,
    }


async def verify_and_consume_code(
    *,
    canonical_email: str,
    scene: EmailCodeScene,
    submitted_code: str,
) -> None:
    """校验并一次性消费 6 位邮箱验证码（最多连续试错 5 次）。"""
    clean_code = (submitted_code or "").strip()
    if not clean_code:
        raise BusinessException("请输入 6 位邮箱验证码", code=40028)

    c_key = _code_key(scene, canonical_email)
    record, remaining_ttl = await _get_code_record(c_key)
    if not record or not record.get("code"):
        raise BusinessException("邮箱验证码不存在或已过期，请重新获取", code=40028)

    expected = str(record["code"])
    if not secrets.compare_digest(clean_code, expected):
        attempts = int(record.get("attempts", 0)) + 1
        max_attempts = int(record.get("max_attempts", _MAX_VERIFY_ATTEMPTS))
        if attempts >= max_attempts:
            await _delete_code_record(c_key)
            raise BusinessException(
                "邮箱验证码错误次数过多，已失效，请重新获取", code=40029
            )
        record["attempts"] = attempts
        await _update_code_record(c_key, record, remaining_ttl)
        raise BusinessException(
            f"邮箱验证码错误，还可尝试 {max_attempts - attempts} 次",
            code=40029,
        )

    await _delete_code_record(c_key)
