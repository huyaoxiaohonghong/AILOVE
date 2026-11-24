from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from tests.test_health_and_api import solve_slider_captcha


async def _login_admin(client: AsyncClient) -> dict[str, str]:
    settings = get_settings()
    cap = await solve_slider_captcha(client, "login")
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "account": settings.DEFAULT_ADMIN_USERNAME,
            "password": settings.DEFAULT_ADMIN_PASSWORD,
            "captcha_token": cap,
        },
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["user"]["role"] == "super_admin"
    assert "*" in data["user"]["permissions"]
    return {"Authorization": f"Bearer {data['access_token']}"}


@pytest.mark.asyncio
async def test_dynamic_system_config_and_hot_policies():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_headers = await _login_admin(client)

        # 1. 公共配置默认状态
        pub_resp = await client.get("/api/v1/system/public-config")
        assert pub_resp.status_code == 200
        assert pub_resp.json()["data"]["registration_enabled"] is True
        assert pub_resp.json()["data"]["slider_captcha_enabled"] is True

        # 2. 获取分组配置清单
        cfg_resp = await client.get("/api/v1/admin/system/configs", headers=admin_headers)
        assert cfg_resp.status_code == 200
        groups = cfg_resp.json()["data"]["groups"]
        assert len(groups) == 7

        try:
            # 3. 动态关闭自助注册 + 提高密码最小长度为 10
            upd = await client.put(
                "/api/v1/admin/system/configs",
                json={
                    "items": {
                        "registration.enabled": False,
                        "security.password_min_length": 10,
                    }
                },
                headers=admin_headers,
            )
            assert upd.status_code == 200

            pub_after = await client.get("/api/v1/system/public-config")
            assert pub_after.json()["data"]["registration_enabled"] is False

            # 自助注册立即返回 403
            cap_reg = await solve_slider_captcha(client, "register")
            blocked_reg = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "closed_reg@qq.com",
                    "password": "Password1234",
                    "captcha_token": cap_reg,
                },
            )
            assert blocked_reg.status_code == 403

            # 管理员分配账号受动态密码最小长度 10 约束
            short_assign = await client.post(
                "/api/v1/admin/accounts",
                json={
                    "email": "shortpwd@163.com",
                    "password": "Pass1234",
                    "nickname": "短密码测试",
                    "role": "user",
                },
                headers=admin_headers,
            )
            assert short_assign.status_code == 400
            assert "10" in short_assign.json()["message"]
        finally:
            # 恢复全部默认系统配置，保证后续测试环境干净
            reset_resp = await client.post(
                "/api/v1/admin/system/configs/reset",
                json={"group_name": None},
                headers=admin_headers,
            )
            assert reset_resp.status_code == 200


@pytest.mark.asyncio
async def test_rbac_custom_role_enforcement_and_audit_logs():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_headers = await _login_admin(client)

        # 1. 查询权限树与内置角色
        perm_resp = await client.get("/api/v1/admin/rbac/permissions", headers=admin_headers)
        assert perm_resp.status_code == 200
        assert len(perm_resp.json()["data"]["groups"]) >= 6

        roles_resp = await client.get("/api/v1/admin/rbac/roles", headers=admin_headers)
        assert roles_resp.status_code == 200
        role_codes = {r["code"] for r in roles_resp.json()["data"]["items"]}
        assert {"super_admin", "admin", "operator", "user"}.issubset(role_codes)

        # 2. 创建自定义只读角色 viewer_ro
        create_role = await client.post(
            "/api/v1/admin/rbac/roles",
            json={
                "code": "viewer_ro",
                "name": "只读巡检员",
                "description": "仅可查看控制台、账号列表与审计日志",
                "permissions": ["dashboard:view", "account:view", "log:audit:view"],
                "is_admin_portal": True,
                "is_enabled": True,
                "sort_order": 50,
            },
            headers=admin_headers,
        )
        assert create_role.status_code == 200
        role_id = create_role.json()["data"]["id"]

        # 3. 创建绑定该自定义角色的测试成员
        secret_pwd = "ViewerPass987"
        create_acc = await client.post(
            "/api/v1/admin/accounts",
            json={
                "email": "viewer_ro_member@qq.com",
                "password": secret_pwd,
                "nickname": "巡检员测试",
                "role": "viewer_ro",
            },
            headers=admin_headers,
        )
        assert create_acc.status_code == 200
        uid = create_acc.json()["data"]["id"]

        # 4. 使用巡检员账号登录 -> 拥有被授予权限，缺少的写权限返回 403
        cap_v = await solve_slider_captcha(client, "login")
        v_login = await client.post(
            "/api/v1/auth/login",
            json={
                "account": "viewer_ro_member@qq.com",
                "password": secret_pwd,
                "captcha_token": cap_v,
            },
        )
        assert v_login.status_code == 200
        v_data = v_login.json()["data"]
        assert v_data["user"]["is_admin_portal"] is True
        assert "account:view" in v_data["user"]["permissions"]
        v_headers = {"Authorization": f"Bearer {v_data['access_token']}"}

        # 已授权只读接口放行
        assert (
            await client.get("/api/v1/admin/dashboard/overview", headers=v_headers)
        ).status_code == 200
        assert (
            await client.get("/api/v1/admin/accounts", headers=v_headers)
        ).status_code == 200

        # 未授权管理写接口精确返回 403，且响应携带 X-Request-ID
        denied_resp = await client.put(
            "/api/v1/admin/system/configs",
            json={"items": {"site.name": "HACKED"}},
            headers=v_headers,
        )
        assert denied_resp.status_code == 403
        assert "X-Request-ID" in denied_resp.headers
        assert "system:config:manage" in denied_resp.json()["message"]

        # 5. 角色仍被账号绑定时不可删除 -> 调整账号角色后原会话失效，角色方可删除
        blocked_del = await client.delete(
            f"/api/v1/admin/rbac/roles/{role_id}", headers=admin_headers
        )
        assert blocked_del.status_code == 400

        reassign = await client.patch(
            f"/api/v1/admin/accounts/{uid}/role",
            json={"role": "user"},
            headers=admin_headers,
        )
        assert reassign.status_code == 200

        # 角色变更后旧 Token 已被强制刷新下线
        assert (
            await client.get("/api/v1/auth/me", headers=v_headers)
        ).status_code == 401

        del_role = await client.delete(
            f"/api/v1/admin/rbac/roles/{role_id}", headers=admin_headers
        )
        assert del_role.status_code == 200

        # 6. 验证操作审计日志采集、敏感字段脱敏、越权拦截记录、汇总与清理
        audit_resp = await client.get(
            "/api/v1/admin/logs/audit",
            params={"page": 1, "page_size": 50},
            headers=admin_headers,
        )
        assert audit_resp.status_code == 200
        audit_items = audit_resp.json()["data"]["items"]
        assert len(audit_items) >= 4
        assert any(item["result"] == "denied" and item["status_code"] == 403 for item in audit_items)
        # 密码绝不以明文出现在任何审计摘要中
        joined = str(audit_items)
        assert secret_pwd not in joined
        assert "***REDACTED***" in joined

        summary_resp = await client.get("/api/v1/admin/logs/summary", headers=admin_headers)
        assert summary_resp.status_code == 200
        assert summary_resp.json()["data"]["audit_alert_24h"] >= 1

        login_logs_resp = await client.get("/api/v1/admin/logs/login", headers=admin_headers)
        assert login_logs_resp.status_code == 200
        assert len(login_logs_resp.json()["data"]["items"]) >= 1

        cleanup_resp = await client.post(
            "/api/v1/admin/logs/cleanup",
            json={"retention_days": 365, "target": "all"},
            headers=admin_headers,
        )
        assert cleanup_resp.status_code == 200
