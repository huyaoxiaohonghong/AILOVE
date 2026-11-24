from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from typing import Any

from fastapi import Request

from app.core.config import get_settings

# 仅信任来自回环/内网/Docker 网桥等可信反向代理节点的转发头，防止公网直连伪造
_TRUSTED_PROXY_NETWORKS = (
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
)


def _normalize_ip(raw: str | None) -> str:
    """校验并规范化 IP 字符串；无效内容（如畸形头或注入字符）返回空串。"""
    if not raw:
        return ""
    candidate = raw.strip()
    if not candidate or len(candidate) > 64:
        return ""
    try:
        addr = ipaddress.ip_address(candidate)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        return str(addr)
    except ValueError:
        return ""


def _is_trusted_proxy(peer_ip: str) -> bool:
    if not peer_ip:
        return False
    if peer_ip in {"testclient", "localhost"}:
        return True
    normalized = _normalize_ip(peer_ip)
    if not normalized:
        return False
    addr = ipaddress.ip_address(normalized)
    return any(addr in net for net in _TRUSTED_PROXY_NETWORKS)


def _resolve_ip(
    *,
    peer_ip: str,
    x_real_ip: str | None,
    x_forwarded_for: str | None,
    default: str,
) -> str:
    """按安全优先级解析客户端真实 IP。

    策略：
    1. 若直连对端（peer_ip）不属于内网/回环可信代理，直接拒绝信任任何代理头，返回 peer_ip；
    2. 开启 TRUST_X_FORWARDED_FOR=True（Nginx 外层另有可信 CDN/LB）时，
       优先取 X-Forwarded-For 最左有效 IP，其次 X-Real-IP；
    3. 默认 TRUST_X_FORWARDED_FOR=False（单层 Nginx 反代）时，
       忽略客户端可伪造的 X-Forwarded-For，仅信任由 Nginx 以 $remote_addr 覆写的 X-Real-IP；
    4. 最终回退到 TCP peer_ip 或调用方指定的 default。
    """
    if _is_trusted_proxy(peer_ip):
        if get_settings().TRUST_X_FORWARDED_FOR and x_forwarded_for:
            for part in x_forwarded_for.split(","):
                parsed = _normalize_ip(part)
                if parsed:
                    return parsed
        real_ip = _normalize_ip(x_real_ip)
        if real_ip:
            return real_ip

    normalized_peer = _normalize_ip(peer_ip)
    if normalized_peer:
        return normalized_peer
    return peer_ip or default


def extract_client_ip(request: Request, *, default: str = "unknown") -> str:
    """从 FastAPI Request 中安全提取客户端真实 IP（防 X-Forwarded-For 伪造）。"""
    peer_ip = request.client.host if request.client and request.client.host else ""
    return _resolve_ip(
        peer_ip=peer_ip,
        x_real_ip=request.headers.get("x-real-ip"),
        x_forwarded_for=request.headers.get("x-forwarded-for"),
        default=default,
    )


def extract_client_ip_from_asgi(scope: dict[str, Any], *, default: str = "") -> str:
    """从纯 ASGI scope 中安全提取客户端真实 IP（供 AuditMiddleware 等中间件使用）。"""
    client = scope.get("client")
    peer_ip = str(client[0]) if client and len(client) > 0 and client[0] else ""

    x_real_ip = ""
    x_forwarded_for = ""
    raw_headers: Iterable[tuple[bytes, bytes]] = scope.get("headers", ())
    for k, v in raw_headers:
        kl = k.lower()
        if kl == b"x-real-ip" and not x_real_ip:
            x_real_ip = v.decode("latin1", errors="ignore")
        elif kl == b"x-forwarded-for" and not x_forwarded_for:
            x_forwarded_for = v.decode("latin1", errors="ignore")

    return _resolve_ip(
        peer_ip=peer_ip,
        x_real_ip=x_real_ip,
        x_forwarded_for=x_forwarded_for,
        default=default,
    )
