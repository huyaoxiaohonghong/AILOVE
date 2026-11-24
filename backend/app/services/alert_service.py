from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from datetime import datetime
from typing import Any
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import httpx

from app.core.exceptions import BusinessException
from app.db.redis import get_redis
from app.services import sys_config_service

logger = logging.getLogger(__name__)

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_SUPPORTED_PROVIDERS = frozenset({"wecom", "feishu", "dingtalk", "generic"})
_mem_cooldowns: dict[str, float] = {}


def _now_str() -> str:
    return datetime.now(_SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _sign_feishu(timestamp: str, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode()
    digest = hmac.new(string_to_sign, digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _sign_dingtalk(timestamp_ms: str, secret: str) -> str:
    string_to_sign = f"{timestamp_ms}\n{secret}".encode()
    digest = hmac.new(secret.encode(), string_to_sign, digestmod=hashlib.sha256).digest()
    return quote_plus(base64.b64encode(digest).decode("utf-8"))


def build_webhook_request(
    *,
    provider: str,
    webhook_url: str,
    webhook_secret: str = "",
    title: str,
    content: str,
    severity: str = "warning",
    event_type: str = "system_alert",
    metadata: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """按企业微信 / 飞书 / 钉钉 / 通用协议构造目标 URL 与 JSON 请求体。"""
    clean_provider = (provider or "wecom").strip().lower()
    if clean_provider not in _SUPPORTED_PROVIDERS:
        clean_provider = "generic"

    clean_url = webhook_url.strip()
    clean_secret = webhook_secret.strip()
    ts_str = _now_str()
    sev_tag = {"critical": "🚨 严重告警", "warning": "⚠️ 安全/运维告警", "info": "ℹ️ 运维通知"}.get(
        severity, "⚠️ 告警通知"
    )
    md_body = f"### {sev_tag} · {title}\n{content}\n\n> 时间：{ts_str} | 系统：AILOVE 中台"

    if clean_provider == "wecom":
        return clean_url, {
            "msgtype": "markdown",
            "markdown": {"content": md_body},
        }

    if clean_provider == "feishu":
        payload: dict[str, Any] = {
            "msg_type": "text",
            "content": {"text": f"[{sev_tag}] {title}\n{content}\n时间：{ts_str}"},
        }
        if clean_secret:
            ts_sec = str(int(time.time()))
            payload["timestamp"] = ts_sec
            payload["sign"] = _sign_feishu(ts_sec, clean_secret)
        return clean_url, payload

    if clean_provider == "dingtalk":
        target_url = clean_url
        if clean_secret:
            ts_ms = str(int(time.time() * 1000))
            sign = _sign_dingtalk(ts_ms, clean_secret)
            sep = "&" if "?" in target_url else "?"
            target_url = f"{target_url}{sep}timestamp={ts_ms}&sign={sign}"
        return target_url, {
            "msgtype": "markdown",
            "markdown": {"title": f"{sev_tag} {title}", "text": md_body},
        }

    return clean_url, {
        "event": event_type,
        "severity": severity,
        "title": title,
        "content": content,
        "metadata": metadata or {},
        "timestamp": ts_str,
    }


async def _acquire_cooldown(dedup_key: str, cooldown_seconds: int) -> bool:
    """冷却去重：同类型告警在冷却期内仅推送一次，防止故障风暴刷屏群机器人。"""
    if not dedup_key or cooldown_seconds <= 0:
        return True
    rkey = f"ailove:alert:cd:{dedup_key}"
    try:
        client = get_redis()
        acquired = await client.set(rkey, "1", nx=True, ex=cooldown_seconds)
        return bool(acquired)
    except Exception:
        now = time.time()
        expired = [k for k, exp in _mem_cooldowns.items() if exp <= now]
        for k in expired:
            _mem_cooldowns.pop(k, None)
        if _mem_cooldowns.get(rkey, 0.0) > now:
            return False
        _mem_cooldowns[rkey] = now + cooldown_seconds
        return True


def _validate_webhook_url(url: str) -> str:
    clean = (url or "").strip()
    if not clean or not (clean.startswith("https://") or clean.startswith("http://")):
        raise BusinessException(
            "请先在「告警通知 Webhook」中填写有效的 http(s):// 机器人地址并保存",
            code=40061,
        )
    return clean


async def send_alert(
    *,
    event_type: str,
    title: str,
    content: str,
    severity: str = "warning",
    dedup_key: str = "",
    metadata: dict[str, Any] | None = None,
    bypass_cooldown: bool = False,
    raise_on_error: bool = False,
) -> dict[str, Any]:
    """发送运维/安全告警到已配置的企微/飞书/钉钉 Webhook。"""
    enabled = await sys_config_service.get_bool("alert.webhook_enabled", default=False)
    if not enabled and not raise_on_error:
        return {"delivered": False, "skipped": "disabled"}

    provider = (
        await sys_config_service.get_str("alert.webhook_provider", default="wecom")
    ).strip().lower()
    webhook_url = await sys_config_service.get_secret("alert.webhook_url", default="")
    webhook_secret = await sys_config_service.get_secret("alert.webhook_secret", default="")

    if not webhook_url.strip():
        if raise_on_error:
            _validate_webhook_url(webhook_url)
        return {"delivered": False, "skipped": "empty_url"}

    if raise_on_error:
        _validate_webhook_url(webhook_url)

    if not bypass_cooldown and dedup_key:
        cooldown = await sys_config_service.get_int("alert.cooldown_seconds", default=300)
        if not await _acquire_cooldown(dedup_key, cooldown):
            return {"delivered": False, "skipped": "cooldown"}

    target_url, payload = build_webhook_request(
        provider=provider,
        webhook_url=webhook_url,
        webhook_secret=webhook_secret,
        title=title,
        content=content,
        severity=severity,
        event_type=event_type,
        metadata=metadata,
    )

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(target_url, json=payload)
        latency_ms = max(1, int((time.perf_counter() - t0) * 1000))
        if resp.status_code >= 400:
            err_msg = f"Webhook 返回 HTTP {resp.status_code}：{resp.text[:160]}"
            if raise_on_error:
                raise BusinessException(err_msg, code=50202, status_code=502)
            logger.warning("Alert webhook failed (%s): %s", provider, err_msg)
            return {"delivered": False, "provider": provider, "status_code": resp.status_code}

        # 校验企微/飞书/钉钉 JSON 业务码（errcode / code 非 0 视为发送失败）
        try:
            body = resp.json()
            if isinstance(body, dict):
                biz_err = body.get("errcode")
                if biz_err is None:
                    biz_err = body.get("code")
                if biz_err not in (None, 0, "0"):
                    err_detail = body.get("errmsg") or body.get("msg") or str(body)[:120]
                    err_msg = f"机器人通道返回错误码 {biz_err}：{err_detail}"
                    if raise_on_error:
                        raise BusinessException(err_msg, code=50202, status_code=502)
                    logger.warning("Alert webhook rejected (%s): %s", provider, err_msg)
                    return {"delivered": False, "provider": provider, "message": err_msg}
        except ValueError:
            pass

        return {
            "delivered": True,
            "provider": provider,
            "status_code": resp.status_code,
            "latency_ms": latency_ms,
            "message": f"告警通知已通过 {provider} 成功送达（耗时 {latency_ms}ms）",
        }
    except BusinessException:
        raise
    except Exception as exc:
        latency_ms = max(1, int((time.perf_counter() - t0) * 1000))
        if raise_on_error:
            raise BusinessException(
                f"Webhook 连接失败（{latency_ms}ms）：{type(exc).__name__}",
                code=50202,
                status_code=502,
            ) from exc
        logger.warning("Alert webhook dispatch error (%s): %s", provider, exc)
        return {"delivered": False, "provider": provider, "error": type(exc).__name__}


async def notify_login_lockout(
    *,
    account: str,
    client_ip: str,
    fail_count: int,
    lock_minutes: int,
) -> dict[str, Any]:
    """账号触发登录防爆破连续失败锁定时异步推送告警。"""
    if not await sys_config_service.get_bool("alert.on_login_lockout", default=True):
        return {"delivered": False, "skipped": "event_disabled"}
    content = (
        f"- 触发账号：`{account}`\n"
        f"- 来源 IP：`{client_ip or 'unknown'}`\n"
        f"- 连续失败次数：{fail_count} 次\n"
        f"- 处置动作：已自动临时锁定 **{lock_minutes} 分钟**"
    )
    return await send_alert(
        event_type="login_lockout",
        title="账号触发防爆破锁定",
        content=content,
        severity="warning",
        dedup_key=f"lockout:{account.lower()}",
        metadata={
            "account": account,
            "ip": client_ip,
            "fail_count": fail_count,
            "lock_minutes": lock_minutes,
        },
    )


async def notify_llm_alert(
    *,
    provider: str,
    model_name: str,
    config_name: str,
    error_summary: str,
    fallback_to: str = "",
    severity: str = "critical",
) -> dict[str, Any]:
    """大模型发生余额不足 (402) / 限流 / 5xx 故障或触发自动切换时推送运维告警。"""
    if not await sys_config_service.get_bool("alert.on_llm_error", default=True):
        return {"delivered": False, "skipped": "event_disabled"}
    title = "AI 模型故障已自动降级切换" if fallback_to else "AI 模型调用异常告警"
    lines = [
        f"- 故障配置：{config_name}（`{provider}` / `{model_name}`）",
        f"- 异常摘要：{error_summary}",
    ]
    if fallback_to:
        lines.append(f"- 容灾动作：已自动无缝切换至备用模型 **{fallback_to}**")
    else:
        lines.append("- 容灾状态：未找到可用备用模型，请求已返回错误提示")

    return await send_alert(
        event_type="llm_fallback" if fallback_to else "llm_error",
        title=title,
        content="\n".join(lines),
        severity="warning" if fallback_to else severity,
        dedup_key=f"llm:{provider}:{model_name}:{'fb' if fallback_to else 'err'}",
        metadata={
            "provider": provider,
            "model_name": model_name,
            "config_name": config_name,
            "fallback_to": fallback_to,
        },
    )


async def send_test_alert(custom_message: str = "") -> dict[str, Any]:
    """管理员手工触发测试告警（绕过冷却窗口与总开关，直接校验机器人地址连通性）。"""
    note = custom_message.strip() or "这是一条来自 AILOVE 运营与容灾中心的连通性测试消息。"
    return await send_alert(
        event_type="webhook_test",
        title="告警通道连通性测试",
        content=f"- 测试内容：{note}\n- 状态：如果群机器人收到此消息，说明异常告警通道配置正常！",
        severity="info",
        bypass_cooldown=True,
        raise_on_error=True,
    )
