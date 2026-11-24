from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from app.core.network import extract_client_ip_from_asgi
from app.core.security import decode_access_token
from app.services.audit_log_service import record_audit_log, serialize_summary

logger = logging.getLogger(__name__)

_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_MAX_SNIFF_BYTES = 16384

# (method, exact_or_prefix, is_prefix) -> (module, action_label)
_ACTION_RULES: tuple[tuple[str, str, bool, str, str], ...] = (
    ("POST", "/api/v1/auth/email-code/send", False, "auth", "发送邮箱验证码"),
    ("POST", "/api/v1/auth/reset-password", False, "auth", "邮箱验证码重置密码"),
    ("POST", "/api/v1/auth/register", False, "auth", "邮箱自助注册"),
    ("POST", "/api/v1/auth/login", False, "auth", "账号登录"),
    ("POST", "/api/v1/auth/logout", False, "auth", "退出当前设备"),
    ("PATCH", "/api/v1/auth/profile", False, "auth", "修改个人资料"),
    ("POST", "/api/v1/auth/change-password", False, "auth", "自助修改密码"),
    ("POST", "/api/v1/auth/sessions/revoke-others", False, "session", "下线其他在线设备"),
    ("DELETE", "/api/v1/auth/sessions/", True, "session", "踢除指定在线设备"),
    ("POST", "/api/v1/admin/accounts", False, "account", "管理员分配创建用户"),
    ("PATCH", "/api/v1/admin/accounts/", True, "account", "变更账号状态或角色"),
    ("POST", "/api/v1/admin/accounts/", True, "account", "账号重置密码/踢下线"),
    ("PATCH", "/api/v1/admin/users/", True, "miniapp_user", "变更小程序用户状态"),
    ("PATCH", "/api/v1/miniapp/user/profile", False, "miniapp_user", "小程序用户更新个人资料"),
    ("POST", "/api/v1/admin/ai/configs", False, "ai", "新增 AI 模型配置"),
    ("PUT", "/api/v1/admin/ai/configs/", True, "ai", "更新 AI 模型配置"),
    ("DELETE", "/api/v1/admin/ai/configs/", True, "ai", "删除 AI 模型配置"),
    ("POST", "/api/v1/admin/ai/configs/", True, "ai", "切换默认模型/测试连通"),
    ("POST", "/api/v1/admin/ai/personas", False, "ai", "新增 AI 智能体模板"),
    ("PUT", "/api/v1/admin/ai/personas/", True, "ai", "更新 AI 智能体模板"),
    ("DELETE", "/api/v1/admin/ai/personas/", True, "ai", "删除 AI 智能体模板"),
    ("POST", "/api/v1/ai/chat", False, "ai", "AI 同步对话"),
    ("POST", "/api/v1/ai/chat/stream", False, "ai", "AI 流式对话"),
    ("POST", "/api/v1/ai/reply-helper", False, "ai", "帮我回消息拆解"),
    ("POST", "/api/v1/ai/reply-helper/stream", False, "ai", "帮我回消息流式拆解"),
    ("PUT", "/api/v1/ai/love-profile", False, "ai", "更新个人情感档案"),
    ("DELETE", "/api/v1/ai/love-profile", False, "ai", "清空个人情感档案"),
    ("PATCH", "/api/v1/ai/conversations/", True, "ai", "更新会话标题/置顶/人设"),
    ("DELETE", "/api/v1/ai/conversations/", True, "ai", "删除 AI 历史会话"),
    ("DELETE", "/api/v1/ai/sessions/", True, "ai", "清空 AI 会话记忆"),
    ("PUT", "/api/v1/admin/system/configs", False, "system", "更新系统动态配置"),
    ("POST", "/api/v1/admin/system/configs/reset", False, "system", "重置系统默认配置"),
    ("POST", "/api/v1/admin/system/smtp/test", False, "system", "测试 SMTP 邮件连通性"),
    ("POST", "/api/v1/admin/system/alert/test", False, "system", "测试异常告警 Webhook"),
    ("POST", "/api/v1/admin/rbac/roles", False, "rbac", "创建自定义角色"),
    ("PUT", "/api/v1/admin/rbac/roles/", True, "rbac", "修改角色与权限配置"),
    ("DELETE", "/api/v1/admin/rbac/roles/", True, "rbac", "删除自定义角色"),
    ("POST", "/api/v1/admin/logs/cleanup", False, "log", "清理过期审计日志"),
)


def _infer_module_and_action(method: str, path: str) -> tuple[str, str]:
    for r_method, pattern, is_prefix, module, action in _ACTION_RULES:
        if r_method != method:
            continue
        if (is_prefix and path.startswith(pattern)) or (not is_prefix and path == pattern):
            return module, action

    if "/admin/rbac" in path:
        return "rbac", f"{method} {path}"
    if "/admin/system" in path:
        return "system", f"{method} {path}"
    if "/admin/logs" in path:
        return "log", f"{method} {path}"
    if "/admin/accounts" in path:
        return "account", f"{method} {path}"
    if "/admin/users" in path:
        return "miniapp_user", f"{method} {path}"
    if "/ai/" in path:
        return "ai", f"{method} {path}"
    if "/auth/" in path:
        return "auth", f"{method} {path}"
    return "system", f"{method} {path}"


def _extract_operator(scope: dict[str, Any]) -> tuple[int | None, str, str, str, str]:
    ip = extract_client_ip_from_asgi(scope, default="")
    ua = ""
    auth_header = ""
    for k, v in scope.get("headers", ()):
        kl = k.lower()
        if kl == b"user-agent":
            ua = v.decode("utf-8", errors="ignore")
        elif kl == b"authorization":
            auth_header = v.decode("latin1")

    user_id: int | None = None
    username = "anonymous"
    role = "anonymous"
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        try:
            payload = decode_access_token(token)
            raw_sub = str(payload.get("sub", ""))
            user_id = int(raw_sub) if raw_sub.isdigit() else None
            username = (
                str(payload.get("email") or payload.get("username") or raw_sub or "user")
            )
            role = str(payload.get("role") or payload.get("type") or "user")
        except Exception:
            pass
    return user_id, username, role, ip, ua


class AuditMiddleware:
    """纯 ASGI 审计日志中间件：零缓冲透传 SSE 流式响应，异步记录写操作及 403/5xx 安全事件。"""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        method: str = scope.get("method", "GET").upper()

        # SSE 流式对话与高频滑块请求不做请求体嗅探，确保 0 延迟与流式零缓冲
        is_api = path.startswith("/api/v1/")
        skip_sniff = (
            not is_api
            or method not in _WRITE_METHODS
            or path.startswith("/api/v1/ai/chat/stream")
            or path.startswith("/api/v1/captcha/")
        )

        request_id = uuid.uuid4().hex[:16]
        t0 = time.perf_counter()

        captured_req = bytearray()
        if skip_sniff:
            wrapped_receive = receive
        else:
            async def wrapped_receive() -> dict[str, Any]:
                message = await receive()
                if message.get("type") == "http.request" and len(captured_req) < _MAX_SNIFF_BYTES:
                    chunk = message.get("body", b"")
                    remain = _MAX_SNIFF_BYTES - len(captured_req)
                    if chunk and remain > 0:
                        captured_req.extend(chunk[:remain])
                return message

        status_code = 500
        err_snippet = ""
        is_sse_response = False

        async def wrapped_send(message: dict[str, Any]) -> None:
            nonlocal status_code, err_snippet, is_sse_response
            msg_type = message.get("type")
            if msg_type == "http.response.start":
                status_code = int(message.get("status", 200))
                raw_headers = list(message.get("headers", []))
                raw_headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": raw_headers}
                for hk, hv in raw_headers:
                    if hk.lower() == b"content-type" and b"text/event-stream" in hv.lower():
                        is_sse_response = True
            elif msg_type == "http.response.body" and not is_sse_response and status_code >= 400:
                if not err_snippet:
                    body_part = message.get("body", b"")
                    if body_part:
                        try:
                            parsed = json.loads(body_part.decode("utf-8"))
                            if isinstance(parsed, dict) and parsed.get("message"):
                                err_snippet = str(parsed["message"])[:250]
                        except Exception:
                            pass
            await send(message)

        try:
            await self.app(scope, wrapped_receive, wrapped_send)
        finally:
            should_audit = is_api and (
                (method in _WRITE_METHODS and not path.startswith("/api/v1/captcha/"))
                or status_code == 403
                or status_code >= 500
            )
            if should_audit:
                duration_ms = int((time.perf_counter() - t0) * 1000)
                user_id, username, role, ip, ua = _extract_operator(scope)
                module, action = _infer_module_and_action(method, path)
                if status_code == 403:
                    result = "denied"
                elif status_code >= 400:
                    result = "error"
                else:
                    result = "success"

                summary = serialize_summary(bytes(captured_req))
                try:
                    await record_audit_log(
                        request_id=request_id,
                        user_id=user_id,
                        username=username,
                        role=role,
                        module=module,
                        action=action,
                        method=method,
                        path=path,
                        status_code=status_code,
                        result=result,
                        ip=ip,
                        user_agent=ua,
                        duration_ms=duration_ms,
                        request_summary=summary,
                        error_message=err_snippet,
                    )
                except Exception as exc:
                    # 审计写入失败绝不影响主业务响应
                    logger.debug("Audit middleware write skipped: %s", exc)
