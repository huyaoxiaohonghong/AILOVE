from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from app.services.captcha_service import slider_captcha_engine
from tests.test_email_and_captcha_algorithms import make_human_trail


async def solve_slider_captcha(client: AsyncClient, scene: str) -> str:
    create_resp = await client.post("/api/v1/captcha/slider/create", json={"scene": scene})
    assert create_resp.status_code == 200
    cid = create_resp.json()["data"]["captcha_id"]

    stored = await slider_captcha_engine._get_challenge(cid)
    assert stored is not None
    target_x = float(stored["target_x"])
    trail, duration = make_human_trail(target_x)

    verify_resp = await client.post(
        "/api/v1/captcha/slider/verify",
        json={
            "captcha_id": cid,
            "scene": scene,
            "final_x": target_x,
            "duration_ms": duration,
            "trail": [{"x": p.x, "y": p.y, "t": p.t} for p in trail],
        },
    )
    assert verify_resp.status_code == 200
    vdata = verify_resp.json()["data"]
    assert vdata["passed"] is True
    return vdata["captcha_token"]


@pytest.mark.asyncio
async def test_root_and_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        root_resp = await client.get("/")
        assert root_resp.status_code == 200
        assert "health" in root_resp.json()

        health_resp = await client.get("/api/v1/health")
        assert health_resp.status_code == 200
        body = health_resp.json()
        assert body["code"] == 0
        assert "mysql" in body["data"]["services"]
        assert "redis" in body["data"]["services"]
        assert "langchain" in body["data"]["services"]


@pytest.mark.asyncio
async def test_email_register_login_and_admin_assignment():
    settings = get_settings()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. 实时邮箱策略接口：域名邮箱拒绝，正规邮箱通过
        chk_bad = await client.post(
            "/api/v1/auth/check-email", json={"email": "hello@my-custom-biz.xyz"}
        )
        assert chk_bad.status_code == 200
        assert chk_bad.json()["data"]["allowed"] is False

        chk_ok = await client.post("/api/v1/auth/check-email", json={"email": "alice2026@qq.com"})
        assert chk_ok.status_code == 200
        assert chk_ok.json()["data"]["allowed"] is True

        # 2. 无有效滑动票据注册 -> 拦截
        no_cap = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "alice.demo@gmail.com",
                "password": "Password123",
                "nickname": "Alice",
                "captcha_token": "fake-invalid-token-123456",
            },
        )
        assert no_cap.status_code == 400

        # 3. 域名邮箱即使滑块通过也不允许注册
        cap_reg_bad = await solve_slider_captcha(client, "register")
        bad_reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "owner@private-domain.top",
                "password": "Password123",
                "nickname": "Owner",
                "captcha_token": cap_reg_bad,
            },
        )
        assert bad_reg.status_code == 400

        # 4. 正规邮箱 + 滑动验证 -> 注册成功
        cap_reg_ok = await solve_slider_captcha(client, "register")
        reg_resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "alice.demo@gmail.com",
                "password": "Password123",
                "nickname": "Alice",
                "captcha_token": cap_reg_ok,
            },
        )
        assert reg_resp.status_code == 200
        reg_user = reg_resp.json()["data"]["user"]
        assert reg_user["role"] == "user"
        assert reg_user["register_source"] == "email_register"

        # 5. 同邮箱去点别名重复注册（alicedemo@gmail.com）-> 防绕过拦截 (409)
        cap_reg_dup = await solve_slider_captcha(client, "register")
        dup_resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "alicedemo@gmail.com",
                "password": "Password123",
                "nickname": "Alice2",
                "captcha_token": cap_reg_dup,
            },
        )
        assert dup_resp.status_code == 409

        # 6. 新注册用户邮箱登录 + 获取 /auth/me
        cap_user_login = await solve_slider_captcha(client, "login")
        user_login = await client.post(
            "/api/v1/auth/login",
            json={
                "account": "alice.demo@gmail.com",
                "password": "Password123",
                "captcha_token": cap_user_login,
            },
        )
        assert user_login.status_code == 200
        user_token = user_login.json()["data"]["access_token"]
        me_user = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert me_user.status_code == 200
        assert me_user.json()["data"]["email"] == "alice.demo@gmail.com"

        # 普通用户无权访问管理员账号分配接口
        forbidden = await client.get(
            "/api/v1/admin/accounts", headers={"Authorization": f"Bearer {user_token}"}
        )
        assert forbidden.status_code == 403

        # 7. 管理员登录 + 分配创建新用户 + 仪表盘 + AI 对话/流式
        cap_admin = await solve_slider_captcha(client, "login")
        admin_login = await client.post(
            "/api/v1/auth/login",
            json={
                "account": settings.DEFAULT_ADMIN_USERNAME,
                "password": settings.DEFAULT_ADMIN_PASSWORD,
                "captcha_token": cap_admin,
            },
        )
        assert admin_login.status_code == 200
        admin_token = admin_login.json()["data"]["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        assign_resp = await client.post(
            "/api/v1/admin/accounts",
            json={
                "email": "assigned_member@163.com",
                "password": "MemberPass123",
                "nickname": "管理员分配成员",
                "role": "user",
            },
            headers=admin_headers,
        )
        assert assign_resp.status_code == 200
        assigned = assign_resp.json()["data"]
        assert assigned["register_source"] == "admin_assigned"

        # 管理员分配的账号可以正常滑动验证登录
        cap_assigned = await solve_slider_captcha(client, "login")
        assigned_login = await client.post(
            "/api/v1/auth/login",
            json={
                "account": "assigned_member@163.com",
                "password": "MemberPass123",
                "captcha_token": cap_assigned,
            },
        )
        assert assigned_login.status_code == 200

        # 管理员禁用该账号后禁止登录
        disable_resp = await client.patch(
            f"/api/v1/admin/accounts/{assigned['id']}/status",
            json={"is_active": False},
            headers=admin_headers,
        )
        assert disable_resp.status_code == 200

        cap_disabled = await solve_slider_captcha(client, "login")
        blocked_login = await client.post(
            "/api/v1/auth/login",
            json={
                "account": "assigned_member@163.com",
                "password": "MemberPass123",
                "captcha_token": cap_disabled,
            },
        )
        assert blocked_login.status_code == 403

        # 仪表盘与 AI 接口正常
        ov_resp = await client.get("/api/v1/admin/dashboard/overview", headers=admin_headers)
        assert ov_resp.status_code == 200
        chat_resp = await client.post(
            "/api/v1/ai/chat",
            json={"message": "你好，测试认证后对话"},
            headers=admin_headers,
        )
        assert chat_resp.status_code == 200
        stream_resp = await client.post(
            "/api/v1/ai/chat/stream",
            json={"message": "流式输出测试", "session_id": chat_resp.json()["data"]["session_id"]},
            headers=admin_headers,
        )
        assert stream_resp.status_code == 200
        assert '"event": "done"' in stream_resp.text


@pytest.mark.asyncio
async def test_miniapp_wx_login_and_profile():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/miniapp/auth/wx-login",
            json={"code": "mock_wx_code_12345", "nickname": "测试用户"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        token = data["access_token"]
        assert token
        assert data["user"]["openid"].startswith("dev_openid_")

        headers = {"Authorization": f"Bearer {token}"}
        profile_resp = await client.get("/api/v1/miniapp/user/profile", headers=headers)
        assert profile_resp.status_code == 200
        assert profile_resp.json()["data"]["nickname"] == "测试用户"

        # 更新小程序昵称并验证最新资料返回
        patch_resp = await client.patch(
            "/api/v1/miniapp/user/profile",
            json={"nickname": "心动小宇"},
            headers=headers,
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["data"]["nickname"] == "心动小宇"
        fresh_resp = await client.get("/api/v1/miniapp/user/profile", headers=headers)
        assert fresh_resp.json()["data"]["nickname"] == "心动小宇"

        # 验证小程序 JWT 可顺畅调用 5 大恋爱智能体、配额、情感档案与帮我回消息全链路
        personas_resp = await client.get("/api/v1/ai/personas", headers=headers)
        assert personas_resp.status_code == 200
        assert len(personas_resp.json()["data"]["items"]) >= 5

        quota_resp = await client.get("/api/v1/ai/quota", headers=headers)
        assert quota_resp.status_code == 200

        lp_save = await client.put(
            "/api/v1/ai/love-profile",
            json={"relationship_stage": "ambiguous", "partner_nickname": "小晴"},
            headers=headers,
        )
        assert lp_save.status_code == 200
        assert lp_save.json()["data"]["profile"]["is_configured"] is True

        helper_resp = await client.post(
            "/api/v1/ai/reply-helper",
            json={"partner_message": "今晚加班好累呀", "scene": "ambiguous", "tone": "gentle"},
            headers=headers,
        )
        assert helper_resp.status_code == 200
        assert helper_resp.json()["data"]["love_profile_injected"] is True

        conv_resp = await client.get("/api/v1/ai/conversations", headers=headers)
        assert conv_resp.status_code == 200
        assert len(conv_resp.json()["data"]["items"]) >= 1

        # 校验头像地址非法协议被拒绝
        bad_avatar = await client.patch(
            "/api/v1/miniapp/user/profile",
            json={"avatar_url": "javascript:alert(1)"},
            headers=headers,
        )
        assert bad_avatar.status_code == 400

        # 校验小程序用户审计元信息优先提取微信昵称而非纯数字 sub
        from app.api.v1.ai.chat import _resolve_user_meta

        uname, urole = _resolve_user_meta({"type": "miniapp", "sub": "42", "nickname": "小星恋恋"})
        assert uname == "小星恋恋"
        assert urole == "user"
