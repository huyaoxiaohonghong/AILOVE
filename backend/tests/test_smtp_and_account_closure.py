from __future__ import annotations

import re

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.services import email_service
from tests.test_health_and_api import solve_slider_captcha
from tests.test_system_rbac_logs import _login_admin


def _extract_6digit_code(msg) -> str:
    plain_part = msg.get_body(preferencelist=("plain",))
    body = plain_part.get_content() if plain_part else str(msg)
    match = re.search(r"(\d{6})", body)
    assert match is not None, f"未在邮件正文找到 6 位验证码: {body}"
    return match.group(1)


async def test_smtp_config_encryption_audit_redaction_and_test_email(monkeypatch):
    sent_records: list[tuple[email_service.SmtpRuntimeConfig, object]] = []

    def fake_send_sync(cfg, msg):
        sent_records.append((cfg, msg))

    monkeypatch.setattr(email_service, "_send_smtp_sync", fake_send_sync)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_headers = await _login_admin(client)
        try:
            save_res = await client.put(
                "/api/v1/admin/system/configs",
                json={
                    "items": {
                        "email.smtp_enabled": True,
                        "email.smtp_host": "smtp.qq.com",
                        "email.smtp_port": 465,
                        "email.smtp_security": "ssl",
                        "email.smtp_username": "noreply_test@qq.com",
                        "email.smtp_password": "MySmtpSecretAuthCode99",
                        "email.from_name": "AILOVE Test Mailer",
                    }
                },
                headers=admin_headers,
            )
            assert save_res.status_code == 200
            groups = save_res.json()["data"]["groups"]
            email_group = next(g for g in groups if g["group"] == "email")
            pwd_item = next(
                item for item in email_group["items"] if item["config_key"] == "email.smtp_password"
            )
            assert pwd_item["is_secret"] is True
            assert pwd_item["has_secret"] is True
            assert pwd_item["value"] == ""
            assert "****" in pwd_item["masked_value"]
            assert "MySmtpSecretAuthCode99" not in pwd_item["masked_value"]

            # 保存同组其他项且不填密码时，原加密授权码必须保留
            keep_res = await client.put(
                "/api/v1/admin/system/configs",
                json={"items": {"email.from_name": "AILOVE 安全邮件", "email.smtp_password": ""}},
                headers=admin_headers,
            )
            assert keep_res.status_code == 200
            email_group2 = next(g for g in keep_res.json()["data"]["groups"] if g["group"] == "email")
            pwd_item2 = next(
                item for item in email_group2["items"] if item["config_key"] == "email.smtp_password"
            )
            assert pwd_item2["has_secret"] is True
            assert pwd_item2["masked_value"] == pwd_item["masked_value"]

            # 审计日志中不得泄露明文 SMTP 密码
            audit_res = await client.get(
                "/api/v1/admin/logs/audit?module=system&page_size=20",
                headers=admin_headers,
            )
            assert audit_res.status_code == 200
            audit_items = audit_res.json()["data"]["items"]
            raw_summaries = " ".join(str(row.get("request_summary", "")) for row in audit_items)
            assert "MySmtpSecretAuthCode99" not in raw_summaries
            assert "***REDACTED***" in raw_summaries

            # SMTP 连通性测试接口应使用解密后的密码投递
            test_res = await client.post(
                "/api/v1/admin/system/smtp/test",
                json={"to_email": "verify_smtp@qq.com"},
                headers=admin_headers,
            )
            assert test_res.status_code == 200
            assert test_res.json()["data"]["sent"] is True
            assert len(sent_records) == 1
            used_cfg, used_msg = sent_records[0]
            assert used_cfg.host == "smtp.qq.com"
            assert used_cfg.password == "MySmtpSecretAuthCode99"
            assert used_msg["To"] == "verify_smtp@qq.com"
        finally:
            await client.post(
                "/api/v1/admin/system/configs/reset",
                json={"group_name": "email"},
                headers=admin_headers,
            )


async def test_email_verified_registration_and_password_reset_closure(monkeypatch):
    sent_messages = []

    def fake_send_sync(_cfg, msg):
        sent_messages.append(msg)

    monkeypatch.setattr(email_service, "_send_smtp_sync", fake_send_sync)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        admin_headers = await _login_admin(client)
        try:
            await client.put(
                "/api/v1/admin/system/configs",
                json={
                    "items": {
                        "email.smtp_enabled": True,
                        "email.smtp_host": "smtp.qq.com",
                        "email.smtp_port": 465,
                        "email.smtp_security": "ssl",
                        "email.smtp_username": "auth_bot@qq.com",
                        "email.smtp_password": "SmtpBotAuthKey123",
                        "registration.email_verify_required": True,
                    }
                },
                headers=admin_headers,
            )

            pub = await client.get("/api/v1/system/public-config")
            assert pub.status_code == 200
            assert pub.json()["data"]["email_verify_required"] is True
            assert pub.json()["data"]["email_service_enabled"] is True

            target_email = "closure_u1@qq.com"

            # 1. 开启邮箱验证码后，直接提交注册必须被拒
            no_code_reg = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": target_email,
                    "password": "InitPass123",
                    "nickname": "闭环测试",
                    "captcha_token": "",
                },
            )
            assert no_code_reg.status_code == 400
            assert no_code_reg.json()["code"] == 40028

            # 2. 发送注册邮箱验证码（带滑块票据）
            reg_captcha = await solve_slider_captcha(client, "register")
            send_reg = await client.post(
                "/api/v1/auth/email-code/send",
                json={
                    "email": target_email,
                    "scene": "register",
                    "captcha_token": reg_captcha,
                },
            )
            assert send_reg.status_code == 200
            assert send_reg.json()["data"]["sent"] is True
            assert len(sent_messages) == 1
            reg_code = _extract_6digit_code(sent_messages[-1])

            # 3. 60 秒冷却防刷拦截
            reg_captcha_2 = await solve_slider_captcha(client, "register")
            cd_res = await client.post(
                "/api/v1/auth/email-code/send",
                json={
                    "email": target_email,
                    "scene": "register",
                    "captcha_token": reg_captcha_2,
                },
            )
            assert cd_res.status_code == 429
            assert cd_res.json()["code"] == 42905

            # 4. 错误验证码提示剩余尝试次数
            bad_reg = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": target_email,
                    "password": "InitPass123",
                    "nickname": "闭环测试",
                    "captcha_token": "",
                    "email_code": "999999" if reg_code != "999999" else "000000",
                },
            )
            assert bad_reg.status_code == 400
            assert bad_reg.json()["code"] == 40029

            # 5. 正确验证码完成注册，获取旧设备会话 Token
            ok_reg = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": target_email,
                    "password": "InitPass123",
                    "nickname": "闭环测试",
                    "captcha_token": "",
                    "email_code": reg_code,
                },
            )
            assert ok_reg.status_code == 200
            old_token = ok_reg.json()["data"]["access_token"]
            old_headers = {"Authorization": f"Bearer {old_token}"}
            assert (await client.get("/api/v1/auth/me", headers=old_headers)).status_code == 200

            # 6. 忘记密码流程：发送 reset_password 场景验证码
            reset_captcha = await solve_slider_captcha(client, "reset_password")
            send_reset = await client.post(
                "/api/v1/auth/email-code/send",
                json={
                    "email": target_email,
                    "scene": "reset_password",
                    "captcha_token": reset_captcha,
                },
            )
            assert send_reset.status_code == 200
            reset_code = _extract_6digit_code(sent_messages[-1])

            # 7. 提交重置密码 -> 旧会话立即失效，旧密码无法登录，新密码可登录
            reset_ok = await client.post(
                "/api/v1/auth/reset-password",
                json={
                    "email": target_email,
                    "email_code": reset_code,
                    "new_password": "NewResetPass456",
                },
            )
            assert reset_ok.status_code == 200
            assert reset_ok.json()["data"]["reset"] is True
            assert reset_ok.json()["data"]["revoked_sessions"] >= 1

            assert (await client.get("/api/v1/auth/me", headers=old_headers)).status_code == 401

            login_cap_1 = await solve_slider_captcha(client, "login")
            old_pwd_login = await client.post(
                "/api/v1/auth/login",
                json={
                    "account": target_email,
                    "password": "InitPass123",
                    "captcha_token": login_cap_1,
                },
            )
            assert old_pwd_login.status_code == 401

            login_cap_2 = await solve_slider_captcha(client, "login")
            new_pwd_login = await client.post(
                "/api/v1/auth/login",
                json={
                    "account": target_email,
                    "password": "NewResetPass456",
                    "captcha_token": login_cap_2,
                },
            )
            assert new_pwd_login.status_code == 200

            # 验证码一次性消费：重复提交应被拒绝
            replay_reset = await client.post(
                "/api/v1/auth/reset-password",
                json={
                    "email": target_email,
                    "email_code": reset_code,
                    "new_password": "AnotherPass789",
                },
            )
            assert replay_reset.status_code == 400
            assert replay_reset.json()["code"] == 40028
        finally:
            await client.post(
                "/api/v1/admin/system/configs/reset",
                json={"group_name": "email"},
                headers=admin_headers,
            )
            await client.post(
                "/api/v1/admin/system/configs/reset",
                json={"group_name": "registration"},
                headers=admin_headers,
            )
