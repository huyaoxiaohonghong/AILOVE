from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.rate_limit import RateLimiter
from app.main import app
from tests.test_health_and_api import solve_slider_captcha
from tests.test_system_rbac_logs import _login_admin


@pytest.mark.asyncio
async def test_rate_limiter_counting_and_key_isolation():
    limiter = RateLimiter()
    for idx in range(3):
        allowed, rem, retry = await limiter.check("unit_test_ip_a", limit=3, window_seconds=60)
        assert allowed is True
        assert rem == 2 - idx
        assert retry == 0

    blocked, rem, retry = await limiter.check("unit_test_ip_a", limit=3, window_seconds=60)
    assert blocked is False
    assert rem == 0
    assert retry >= 1

    # 其他键互不干扰
    other_ok, _, _ = await limiter.check("unit_test_ip_b", limit=3, window_seconds=60)
    assert other_ok is True


@pytest.mark.asyncio
async def test_public_config_reflects_dynamic_password_min_length():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_headers = await _login_admin(client)
        pub_initial = await client.get("/api/v1/system/public-config")
        assert pub_initial.status_code == 200
        assert pub_initial.json()["data"]["password_min_length"] == 8

        try:
            upd = await client.put(
                "/api/v1/admin/system/configs",
                json={"items": {"security.password_min_length": 12}},
                headers=admin_headers,
            )
            assert upd.status_code == 200

            pub_updated = await client.get("/api/v1/system/public-config")
            assert pub_updated.status_code == 200
            assert pub_updated.json()["data"]["password_min_length"] == 12
        finally:
            await client.post(
                "/api/v1/admin/system/configs/reset",
                json={"group_name": "security"},
                headers=admin_headers,
            )


@pytest.mark.asyncio
async def test_ai_persistent_conversations_lifecycle_and_isolation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. 注册两个独立用户 A 与 B
        cap_a = await solve_slider_captcha(client, "register")
        reg_a = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "conv_user_a@qq.com",
                "password": "Password123",
                "nickname": "会话用户A",
                "captcha_token": cap_a,
            },
        )
        assert reg_a.status_code == 200
        headers_a = {"Authorization": f"Bearer {reg_a.json()['data']['access_token']}"}

        cap_b = await solve_slider_captcha(client, "register")
        reg_b = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "conv_user_b@163.com",
                "password": "Password123",
                "nickname": "会话用户B",
                "captcha_token": cap_b,
            },
        )
        assert reg_b.status_code == 200
        headers_b = {"Authorization": f"Bearer {reg_b.json()['data']['access_token']}"}

        # 2. 用户 A 发起两轮同步对话
        turn1 = await client.post(
            "/api/v1/ai/chat",
            json={"message": "请帮我制定一个周末学习计划"},
            headers=headers_a,
        )
        assert turn1.status_code == 200
        sid = turn1.json()["data"]["session_id"]

        turn2 = await client.post(
            "/api/v1/ai/chat",
            json={"message": "再补充每天运动半小时", "session_id": sid},
            headers=headers_a,
        )
        assert turn2.status_code == 200

        # 3. 用户 A 查询会话列表与消息详情
        list_a = await client.get("/api/v1/ai/conversations", headers=headers_a)
        assert list_a.status_code == 200
        items_a = list_a.json()["data"]["items"]
        assert any(c["session_id"] == sid for c in items_a)

        detail_a = await client.get(
            f"/api/v1/ai/conversations/{sid}/messages", headers=headers_a
        )
        assert detail_a.status_code == 200
        msgs = detail_a.json()["data"]["messages"]
        assert len(msgs) >= 4
        assert msgs[0]["role"] == "user"
        assert "周末学习计划" in msgs[0]["content"]

        # 4. 跨用户 B 无法读取、重命名或删除用户 A 的会话（返回 404）
        assert (
            await client.get(f"/api/v1/ai/conversations/{sid}/messages", headers=headers_b)
        ).status_code == 404
        assert (
            await client.patch(
                f"/api/v1/ai/conversations/{sid}",
                json={"title": "越权改名"},
                headers=headers_b,
            )
        ).status_code == 404
        assert (
            await client.delete(f"/api/v1/ai/conversations/{sid}", headers=headers_b)
        ).status_code == 404

        # 5. 用户 A 重命名并删除自己的会话
        ren = await client.patch(
            f"/api/v1/ai/conversations/{sid}",
            json={"title": "周末学习与健身清单"},
            headers=headers_a,
        )
        assert ren.status_code == 200
        assert ren.json()["data"]["title"] == "周末学习与健身清单"

        dl = await client.delete(f"/api/v1/ai/conversations/{sid}", headers=headers_a)
        assert dl.status_code == 200
        assert (
            await client.get(f"/api/v1/ai/conversations/{sid}/messages", headers=headers_a)
        ).status_code == 404
