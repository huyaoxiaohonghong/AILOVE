from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.network import extract_client_ip, extract_client_ip_from_asgi
from app.core.rate_limit import rate_limit
from app.db import redis as redis_mod
from app.main import create_app


def _make_request(
    peer_host: str | None = "172.18.0.5",
    headers: dict[str, str] | None = None,
) -> Request:
    raw_headers = [
        (k.lower().encode("latin1"), v.encode("latin1"))
        for k, v in (headers or {}).items()
    ]
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "client": (peer_host, 54321) if peer_host else None,
    }
    return Request(scope)


def test_extract_client_ip_ignores_spoofed_xff_by_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRUST_X_FORWARDED_FOR", "false")
    get_settings.cache_clear()
    try:
        # 1. 可信 Docker Nginx 反代但仅带客户端伪造的 XFF -> 忽略 XFF，回退到对端 IP
        req_spoof = _make_request(
            peer_host="172.18.0.5",
            headers={"X-Forwarded-For": "8.8.8.8"},
        )
        assert extract_client_ip(req_spoof) == "172.18.0.5"

        # 2. 可信 Nginx 以 $remote_addr 覆写 X-Real-IP -> 信任 X-Real-IP 并忽略伪造 XFF
        req_nginx = _make_request(
            peer_host="172.18.0.5",
            headers={"X-Real-IP": "203.0.113.9", "X-Forwarded-For": "8.8.8.8"},
        )
        assert extract_client_ip(req_nginx) == "203.0.113.9"

        # 3. 非可信公网直连（即使同时伪造 X-Real-IP 和 XFF）-> 拒绝信任任何代理头
        req_direct = _make_request(
            peer_host="198.51.100.5",
            headers={"X-Real-IP": "1.1.1.1", "X-Forwarded-For": "2.2.2.2"},
        )
        assert extract_client_ip(req_direct) == "198.51.100.5"

        # 4. 畸形 X-Real-IP 头 -> 自动丢弃并安全回退
        req_bad = _make_request(
            peer_host="127.0.0.1",
            headers={"X-Real-IP": "not-an-ip-value"},
        )
        assert extract_client_ip(req_bad) == "127.0.0.1"
    finally:
        get_settings.cache_clear()


def test_extract_client_ip_honors_xff_when_opted_in(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRUST_X_FORWARDED_FOR", "true")
    get_settings.cache_clear()
    try:
        # 可信代理 + 显式开启 TRUST_X_FORWARDED_FOR（CDN/LB + Nginx 场景）
        req_cdn = _make_request(
            peer_host="172.18.0.5",
            headers={
                "X-Forwarded-For": "203.0.113.88, 10.0.0.5",
                "X-Real-IP": "10.0.0.5",
            },
        )
        assert extract_client_ip(req_cdn) == "203.0.113.88"

        # 即使开启 TRUST_X_FORWARDED_FOR，公网非代理直连仍不信任伪造头
        req_direct = _make_request(
            peer_host="198.51.100.5",
            headers={"X-Forwarded-For": "203.0.113.88", "X-Real-IP": "203.0.113.88"},
        )
        assert extract_client_ip(req_direct) == "198.51.100.5"
    finally:
        get_settings.cache_clear()


def test_extract_client_ip_from_asgi_policy(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRUST_X_FORWARDED_FOR", "false")
    get_settings.cache_clear()
    try:
        scope_spoof = {
            "client": ("172.18.0.5", 12345),
            "headers": [(b"x-forwarded-for", b"9.9.9.9")],
        }
        assert extract_client_ip_from_asgi(scope_spoof) == "172.18.0.5"

        scope_nginx = {
            "client": ("172.18.0.5", 12345),
            "headers": [
                (b"x-forwarded-for", b"9.9.9.9"),
                (b"x-real-ip", b"203.0.113.42"),
            ],
        }
        assert extract_client_ip_from_asgi(scope_nginx) == "203.0.113.42"

        scope_public = {
            "client": ("198.51.100.7", 12345),
            "headers": [(b"x-real-ip", b"8.8.8.8")],
        }
        assert extract_client_ip_from_asgi(scope_public) == "198.51.100.7"
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_rate_limit_blocks_rotating_spoofed_xff(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TRUST_X_FORWARDED_FOR", "false")
    get_settings.cache_clear()

    scope_name = f"test_spoof_{uuid.uuid4().hex[:8]}"
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get(
        "/ping",
        dependencies=[Depends(rate_limit(scope_name, limit=3, window_seconds=60))],
    )
    async def ping():
        return {"ok": True}

    try:
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            # 攻击者轮换伪造 X-Forwarded-For，但因为默认不信任 XFF，仍命中同一 IP 桶
            for idx in range(1, 4):
                resp = await client.get(
                    "/ping", headers={"X-Forwarded-For": f"198.51.100.{idx}"}
                )
                assert resp.status_code == 200

            blocked = await client.get(
                "/ping", headers={"X-Forwarded-For": "198.51.100.99"}
            )
            assert blocked.status_code == 429
            assert blocked.json()["code"] == 42904

            # 来自 Nginx 真实覆写的另一客户端 X-Real-IP 拥有独立限流桶
            other_user = await client.get(
                "/ping", headers={"X-Real-IP": "203.0.113.77"}
            )
            assert other_user.status_code == 200
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_openapi_and_docs_disabled_when_debug_false(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("APP_DEBUG", "false")
    get_settings.cache_clear()
    try:
        prod_app = create_app()
        assert prod_app.docs_url is None
        assert prod_app.redoc_url is None
        assert prod_app.openapi_url is None

        async with AsyncClient(
            transport=ASGITransport(app=prod_app), base_url="http://test"
        ) as client:
            assert (await client.get("/docs")).status_code == 404
            assert (await client.get("/redoc")).status_code == 404
            assert (await client.get("/openapi.json")).status_code == 404

            root_resp = await client.get("/")
            assert root_resp.status_code == 200
            assert root_resp.json()["docs"] is None
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_distributed_lock_lifecycle_and_offline_fallback(
    monkeypatch: pytest.MonkeyPatch,
):
    store: dict[str, str] = {}

    async def fake_set(key: str, value: str, *, nx: bool = False, ex: int = 30) -> bool:
        if nx and key in store:
            return False
        store[key] = value
        return True

    async def fake_eval(_script: str, _numkeys: int, key: str, token: str) -> int:
        if store.get(key) == token:
            del store[key]
            return 1
        return 0

    async def fake_exists(key: str) -> int:
        return 1 if key in store else 0

    fake_client = SimpleNamespace(set=fake_set, eval=fake_eval, exists=fake_exists)
    monkeypatch.setattr(redis_mod, "get_redis", lambda: fake_client)

    lock_key = "ailove:test:lock"
    ok1, token1 = await redis_mod.acquire_distributed_lock(lock_key, ttl_seconds=30)
    assert ok1 is True
    assert token1

    # 第二个 worker 抢锁失败，避免并发 DDL/种子初始化冲突
    ok2, token2 = await redis_mod.acquire_distributed_lock(lock_key, ttl_seconds=30)
    assert ok2 is False
    assert token2 == ""

    # 错误 token 无法释放其他 worker 的锁
    assert await redis_mod.release_distributed_lock(lock_key, "wrong-token") is False
    assert lock_key in store

    # 正确 token 原子释放锁
    assert await redis_mod.release_distributed_lock(lock_key, token1) is True
    assert await redis_mod.wait_for_lock_release(lock_key, timeout_seconds=0.5) is True

    # 释放后其他 worker 可正常抢占
    ok3, token3 = await redis_mod.acquire_distributed_lock(lock_key, ttl_seconds=30)
    assert ok3 is True
    assert token3
    await redis_mod.release_distributed_lock(lock_key, token3)

    # Redis 离线异常时优雅降级放行
    async def broken_set(*_args: Any, **_kwargs: Any) -> bool:
        raise ConnectionError("redis down")

    monkeypatch.setattr(
        redis_mod, "get_redis", lambda: SimpleNamespace(set=broken_set)
    )
    ok_fallback, token_fallback = await redis_mod.acquire_distributed_lock(lock_key)
    assert ok_fallback is True
    assert token_fallback == ""
    assert await redis_mod.release_distributed_lock(lock_key, token_fallback) is False
