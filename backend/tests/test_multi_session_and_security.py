from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from app.services.session_service import _mem_sessions, session_service
from tests.test_health_and_api import solve_slider_captcha


@pytest.mark.asyncio
async def test_multi_device_login_24h_ttl_and_session_management():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. 注册一个测试账号（设备 A: macOS Chrome）
        cap_reg = await solve_slider_captcha(client, "register")
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "multisess_user@163.com",
                "password": "Password123",
                "nickname": "多端测试用户",
                "captcha_token": cap_reg,
            },
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
                )
            },
        )
        assert reg.status_code == 200
        d_reg = reg.json()["data"]
        assert d_reg["expires_in"] == 86400  # 精确 24 小时自动过期
        token_a = d_reg["access_token"]
        sid_a = d_reg["session_id"]

        # 2. 同一账号从设备 B（iPhone Safari）和设备 C（Windows Edge）多点登录
        cap_b = await solve_slider_captcha(client, "login")
        login_b = await client.post(
            "/api/v1/auth/login",
            json={
                "account": "multisess_user@163.com",
                "password": "Password123",
                "captcha_token": cap_b,
            },
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1"
                )
            },
        )
        assert login_b.status_code == 200
        token_b = login_b.json()["data"]["access_token"]
        sid_b = login_b.json()["data"]["session_id"]

        cap_c = await solve_slider_captcha(client, "login")
        login_c = await client.post(
            "/api/v1/auth/login",
            json={
                "account": "multisess_user@163.com",
                "password": "Password123",
                "captcha_token": cap_c,
            },
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
                )
            },
        )
        assert login_c.status_code == 200
        token_c = login_c.json()["data"]["access_token"]

        # 3. 验证三端同时有效，且 /auth/sessions 正确展示 3 台设备及解析出的终端标签
        for tok in (token_a, token_b, token_c):
            me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
            assert me.status_code == 200
            assert me.json()["data"]["session"]["online_count"] == 3
            assert me.json()["data"]["session"]["ttl_hours"] == 24.0

        sess_resp = await client.get(
            "/api/v1/auth/sessions", headers={"Authorization": f"Bearer {token_a}"}
        )
        assert sess_resp.status_code == 200
        items = sess_resp.json()["data"]["items"]
        assert len(items) == 3
        labels = {item["device_label"] for item in items}
        assert "macOS · Chrome" in labels
        assert "iPhone · Safari" in labels
        assert "Windows · Edge" in labels

        # 4. 设备 C 主动退出登录 -> 仅设备 C 失效，设备 A / B 不受影响
        out_c = await client.post(
            "/api/v1/auth/logout", headers={"Authorization": f"Bearer {token_c}"}
        )
        assert out_c.status_code == 200

        me_c_after = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token_c}"}
        )
        assert me_c_after.status_code == 401

        me_a_still = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a}"}
        )
        assert me_a_still.status_code == 200

        # 5. 设备 A 远程踢除设备 B -> 设备 B 立即失效
        kick_b = await client.delete(
            f"/api/v1/auth/sessions/{sid_b}",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert kick_b.status_code == 200
        me_b_after = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token_b}"}
        )
        assert me_b_after.status_code == 401

        # 6. 修改个人昵称 + 自助修改密码（含下线其他端）
        upd = await client.patch(
            "/api/v1/auth/profile",
            json={"nickname": "已改名用户"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert upd.status_code == 200
        assert upd.json()["data"]["nickname"] == "已改名用户"

        # 再登录一台设备 D，随后在设备 A 修改密码并开启下线其他端
        cap_d = await solve_slider_captcha(client, "login")
        login_d = await client.post(
            "/api/v1/auth/login",
            json={
                "account": "multisess_user@163.com",
                "password": "Password123",
                "captcha_token": cap_d,
            },
        )
        token_d = login_d.json()["data"]["access_token"]

        chg = await client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "Password123",
                "new_password": "NewPassword456",
                "logout_other_devices": True,
            },
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert chg.status_code == 200
        assert chg.json()["data"]["revoked_other_devices"] == 1

        # 设备 D 已被下线，设备 A 保持在线
        assert (
            await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_d}"})
        ).status_code == 401
        assert (
            await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a}"})
        ).status_code == 200

        # 7. 模拟 24 小时到期自动过期 -> 会话自动失效返回 401
        if sid_a in _mem_sessions:
            _, rec = _mem_sessions[sid_a]
            rec["expires_at_ts"] = 1.0
            _mem_sessions[sid_a] = (1.0, rec)
        else:
            await session_service.revoke_session(d_reg["user"]["id"], sid_a)

        expired_me = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token_a}"}
        )
        assert expired_me.status_code == 401

        # 8. 用新密码重新登录并查看登录安全审计日志
        cap_new = await solve_slider_captcha(client, "login")
        relogin = await client.post(
            "/api/v1/auth/login",
            json={
                "account": "multisess_user@163.com",
                "password": "NewPassword456",
                "captcha_token": cap_new,
            },
        )
        assert relogin.status_code == 200
        tok_new = relogin.json()["data"]["access_token"]

        logs_resp = await client.get(
            "/api/v1/auth/login-logs", headers={"Authorization": f"Bearer {tok_new}"}
        )
        assert logs_resp.status_code == 200
        assert len(logs_resp.json()["data"]["items"]) >= 3


@pytest.mark.asyncio
async def test_bruteforce_lockout_and_admin_kick():
    settings = get_settings()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. 注册一个测试账号，连续输错密码触发防爆破锁定
        cap_r = await solve_slider_captcha(client, "register")
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "lock_test@qq.com",
                "password": "CorrectPass123",
                "captcha_token": cap_r,
            },
        )
        assert reg.status_code == 200
        uid = reg.json()["data"]["user"]["id"]
        user_tok = reg.json()["data"]["access_token"]

        for i in range(settings.LOGIN_MAX_FAIL_ATTEMPTS):
            cap = await solve_slider_captcha(client, "login")
            bad = await client.post(
                "/api/v1/auth/login",
                json={
                    "account": "lock_test@qq.com",
                    "password": "WrongPassword999",
                    "captcha_token": cap,
                },
            )
            if i < settings.LOGIN_MAX_FAIL_ATTEMPTS - 1:
                assert bad.status_code == 401
            else:
                assert bad.status_code == 429

        # 锁定后即使输对密码也会被 429 拦截
        cap_after = await solve_slider_captcha(client, "login")
        locked_resp = await client.post(
            "/api/v1/auth/login",
            json={
                "account": "lock_test@qq.com",
                "password": "CorrectPass123",
                "captcha_token": cap_after,
            },
        )
        assert locked_resp.status_code == 429

        # 2. 管理员一键强制下线该用户的全部在线设备
        cap_admin = await solve_slider_captcha(client, "login")
        admin_login = await client.post(
            "/api/v1/auth/login",
            json={
                "account": settings.DEFAULT_ADMIN_USERNAME,
                "password": settings.DEFAULT_ADMIN_PASSWORD,
                "captcha_token": cap_admin,
            },
        )
        admin_tok = admin_login.json()["data"]["access_token"]
        kick = await client.post(
            f"/api/v1/admin/accounts/{uid}/kick",
            headers={"Authorization": f"Bearer {admin_tok}"},
        )
        assert kick.status_code == 200
        assert kick.json()["data"]["kicked_sessions"] >= 1

        # 被强制下线的用户原 token 立即 401
        assert (
            await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {user_tok}"})
        ).status_code == 401
