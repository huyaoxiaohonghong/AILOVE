from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.test_health_and_api import solve_slider_captcha
from tests.test_system_rbac_logs import _login_admin


async def test_ai_personas_crud_builtin_protection_and_chat_usage():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_headers = await _login_admin(client)

        list_res = await client.get("/api/v1/admin/ai/personas", headers=admin_headers)
        assert list_res.status_code == 200
        items = list_res.json()["data"]["items"]
        codes = {item["code"] for item in items}
        assert {
            "assistant_general",
            "copywriter_pro",
            "architect_coder",
            "translator_bilingual",
            "data_analyst",
        }.issubset(codes)

        builtin = next(item for item in items if item["is_system"])
        del_builtin = await client.delete(
            f"/api/v1/admin/ai/personas/{builtin['id']}",
            headers=admin_headers,
        )
        assert del_builtin.status_code == 403
        assert del_builtin.json()["code"] == 40301

        create_res = await client.post(
            "/api/v1/admin/ai/personas",
            json={
                "code": "custom_qa_bot",
                "name": "测试问答助手",
                "avatar_emoji": "🎯",
                "category": "general",
                "description": "自动化测试专用智能体",
                "system_prompt": "你是一位严谨的 QA 专家，请分点输出测试用例。",
                "starter_prompts": ["测试问题A", "测试问题B"],
                "temperature": 0.4,
                "is_enabled": True,
                "sort_order": 99,
            },
            headers=admin_headers,
        )
        assert create_res.status_code == 200
        created = create_res.json()["data"]
        pid = created["id"]
        assert created["is_system"] is False
        assert created["starter_prompts"] == ["测试问题A", "测试问题B"]

        pub_res = await client.get("/api/v1/ai/personas", headers=admin_headers)
        assert pub_res.status_code == 200
        assert any(p["code"] == "custom_qa_bot" for p in pub_res.json()["data"]["items"])

        disable_res = await client.put(
            f"/api/v1/admin/ai/personas/{pid}",
            json={"is_enabled": False},
            headers=admin_headers,
        )
        assert disable_res.status_code == 200
        assert disable_res.json()["data"]["is_enabled"] is False

        chat_disabled = await client.post(
            "/api/v1/ai/chat",
            json={"message": "使用停用智能体", "persona_id": pid},
            headers=admin_headers,
        )
        assert chat_disabled.status_code == 400

        enable_res = await client.put(
            f"/api/v1/admin/ai/personas/{pid}",
            json={"is_enabled": True, "name": "测试问答助手V2"},
            headers=admin_headers,
        )
        assert enable_res.status_code == 200

        chat_ok = await client.post(
            "/api/v1/ai/chat",
            json={"message": "帮我列一条冒烟测试用例", "persona_id": pid},
            headers=admin_headers,
        )
        assert chat_ok.status_code == 200
        chat_data = chat_ok.json()["data"]
        assert chat_data["persona_id"] == pid
        assert chat_data["persona_name"] == "测试问答助手V2"

        after_list = await client.get("/api/v1/admin/ai/personas", headers=admin_headers)
        refreshed = next(item for item in after_list.json()["data"]["items"] if item["id"] == pid)
        assert refreshed["usage_count"] >= 1

        del_custom = await client.delete(
            f"/api/v1/admin/ai/personas/{pid}",
            headers=admin_headers,
        )
        assert del_custom.status_code == 200
        assert del_custom.json()["data"]["deleted_id"] == pid


async def test_ai_daily_quota_enforcement_admin_exemption_and_analytics():
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_headers = await _login_admin(client)

        try:
            cfg_res = await client.put(
                "/api/v1/admin/system/configs",
                json={"items": {"ai.daily_user_request_limit": "2"}},
                headers=admin_headers,
            )
            assert cfg_res.status_code == 200

            create_acc = await client.post(
                "/api/v1/admin/accounts",
                json={
                    "email": "quota_u1@qq.com",
                    "password": "QuotaPass123",
                    "nickname": "配额测试员",
                    "username": "quota_u1",
                    "role": "user",
                },
                headers=admin_headers,
            )
            assert create_acc.status_code == 200

            captcha = await solve_slider_captcha(client, "login")
            login_res = await client.post(
                "/api/v1/auth/login",
                json={
                    "account": "quota_u1@qq.com",
                    "password": "QuotaPass123",
                    "captcha_token": captcha,
                },
            )
            assert login_res.status_code == 200
            user_token = login_res.json()["data"]["access_token"]
            user_headers = {"Authorization": f"Bearer {user_token}"}

            q0 = await client.get("/api/v1/ai/quota", headers=user_headers)
            assert q0.status_code == 200
            q0_data = q0.json()["data"]
            assert q0_data["is_exempt"] is False
            assert q0_data["requests_limit"] == 2
            assert q0_data["requests_remaining"] == 2

            c1 = await client.post(
                "/api/v1/ai/chat",
                json={"message": "普通用户配额测试 1"},
                headers=user_headers,
            )
            assert c1.status_code == 200

            c2 = await client.post(
                "/api/v1/ai/chat",
                json={"message": "普通用户配额测试 2"},
                headers=user_headers,
            )
            assert c2.status_code == 200

            q2 = await client.get("/api/v1/ai/quota", headers=user_headers)
            assert q2.status_code == 200
            assert q2.json()["data"]["requests_used"] == 2
            assert q2.json()["data"]["requests_remaining"] == 0

            c3 = await client.post(
                "/api/v1/ai/chat",
                json={"message": "超出当日配额请求"},
                headers=user_headers,
            )
            assert c3.status_code == 429
            assert c3.json()["code"] == 42902

            s3 = await client.post(
                "/api/v1/ai/chat/stream",
                json={"message": "流式超额拦截测试"},
                headers=user_headers,
            )
            assert s3.status_code == 429
            assert s3.json()["code"] == 42902

            forbidden_analytics = await client.get("/api/v1/admin/ai/analytics", headers=user_headers)
            assert forbidden_analytics.status_code == 403

            admin_quota = await client.get("/api/v1/ai/quota", headers=admin_headers)
            assert admin_quota.status_code == 200
            assert admin_quota.json()["data"]["is_exempt"] is True
            assert admin_quota.json()["data"]["requests_remaining"] is None

            for idx in range(3):
                ac = await client.post(
                    "/api/v1/ai/chat",
                    json={"message": f"管理员豁免配额调用 {idx + 1}"},
                    headers=admin_headers,
                )
                assert ac.status_code == 200

            analytics_res = await client.get("/api/v1/admin/ai/analytics?days=7", headers=admin_headers)
            assert analytics_res.status_code == 200
            analytics = analytics_res.json()["data"]
            assert len(analytics["daily_trend"]) == 7
            assert analytics["summary"]["total_requests"] >= 5
            assert analytics["summary"]["today_requests"] >= 5
            assert len(analytics["by_model"]) >= 1
            assert len(analytics["top_users"]) >= 1
        finally:
            await client.post(
                "/api/v1/admin/system/configs/reset",
                json={"group_name": "ai"},
                headers=admin_headers,
            )
