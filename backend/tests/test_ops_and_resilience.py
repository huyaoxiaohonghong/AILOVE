from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.core.csv_utils import render_csv_bytes, sanitize_csv_cell
from app.main import app
from app.services import alert_service
from app.services import llm_service as llm_mod
from app.services.ai_config_service import RuntimeAIConfig
from app.services.ai_providers import get_provider_adapter, is_fallback_eligible_error
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
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


def test_csv_formula_injection_and_bom():
    assert sanitize_csv_cell("=CMD|' /C calc'!A0") == "'=CMD|' /C calc'!A0"
    assert sanitize_csv_cell("+SUM(1,2)") == "'+SUM(1,2)"
    assert sanitize_csv_cell("-1+1") == "'-1+1"
    assert sanitize_csv_cell("@evil") == "'@evil"
    assert sanitize_csv_cell("正常中文") == "正常中文"

    raw = render_csv_bytes(["列名", "内容"], [["用户", "=1+1"]])
    assert raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    assert "'=1+1" in text


def test_webhook_payload_builders_for_wecom_feishu_dingtalk():
    url1, body1 = alert_service.build_webhook_request(
        provider="wecom",
        webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
        title="测试告警",
        content="内容详情",
        severity="critical",
    )
    assert url1.endswith("key=abc")
    assert body1["msgtype"] == "markdown"
    assert "测试告警" in body1["markdown"]["content"]

    url2, body2 = alert_service.build_webhook_request(
        provider="feishu",
        webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/xyz",
        webhook_secret="my-feishu-secret",
        title="飞书测试",
        content="内容",
    )
    assert url2.endswith("/xyz")
    assert body2["msg_type"] == "text"
    assert body2.get("timestamp") and body2.get("sign")

    url3, body3 = alert_service.build_webhook_request(
        provider="dingtalk",
        webhook_url="https://oapi.dingtalk.com/robot/send?access_token=tok",
        webhook_secret="SEC-ding-secret",
        title="钉钉测试",
        content="内容",
    )
    assert "timestamp=" in url3 and "sign=" in url3
    assert body3["msgtype"] == "markdown"


def test_chinese_emotion_llm_providers_and_fallback_eligibility():
    for code, sample_model in (
        ("qwen", "qwen-plus"),
        ("doubao", "doubao-1-5-pro-32k-250115"),
        ("moonshot", "moonshot-v1-32k"),
    ):
        adapter = get_provider_adapter(code)
        assert adapter is not None
        assert adapter.descriptor.status == "active"
        llm = adapter.build_chat_model(
            api_key="sk-test-key",
            base_url=adapter.descriptor.default_base_url,
            model_name=sample_model,
            temperature=0.7,
            top_p=1.0,
            max_tokens=4096,
            timeout_seconds=30,
            streaming=True,
        )
        assert isinstance(llm, ChatOpenAI)
        assert llm.model_name == sample_model

    assert is_fallback_eligible_error(Exception("Error code: 402 Insufficient Balance")) is True
    assert is_fallback_eligible_error(Exception("Error code: 429 rate limit exceeded")) is True
    assert is_fallback_eligible_error(Exception("503 Service Unavailable")) is True
    assert is_fallback_eligible_error(Exception("Request timed out")) is True
    assert is_fallback_eligible_error(Exception("Error code: 400 Invalid parameter")) is False


@pytest.mark.asyncio
async def test_csv_exports_and_multi_provider_creation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _login_admin(client)

        # 1. 创建通义千问模型配置并确认成功
        create_qwen = await client.post(
            "/api/v1/admin/ai/configs",
            headers=headers,
            json={
                "name": "通义千问 Plus 情感备选",
                "provider": "qwen",
                "protocol": "openai",
                "model_name": "qwen-plus",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "sk-qwen-test-secret-123456",
                "is_default": False,
            },
        )
        assert create_qwen.status_code == 200
        qwen_id = create_qwen.json()["data"]["id"]
        assert create_qwen.json()["data"]["provider"] == "qwen"

        # 清理测试配置
        del_qwen = await client.delete(f"/api/v1/admin/ai/configs/{qwen_id}", headers=headers)
        assert del_qwen.status_code == 200

        # 2. 导出三类 CSV（操作审计 / 登录安全 / AI 用量）
        for path, prefix in (
            ("/api/v1/admin/logs/audit/export", "ailove_audit_logs_"),
            ("/api/v1/admin/logs/login/export", "ailove_login_logs_"),
            ("/api/v1/admin/ai/analytics/export?days=7", "ailove_ai_usage_7d_"),
        ):
            resp = await client.get(path, headers=headers)
            assert resp.status_code == 200
            assert "text/csv" in resp.headers.get("content-type", "")
            assert prefix in resp.headers.get("content-disposition", "")
            assert resp.content.startswith(b"\xef\xbb\xbf")


@pytest.mark.asyncio
async def test_alert_webhook_test_endpoint_and_cooldown(monkeypatch: pytest.MonkeyPatch):
    posted: list[tuple[str, dict[str, Any]]] = []

    class FakeAsyncClient:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def post(self, url: str, json: dict[str, Any]) -> SimpleNamespace:
            posted.append((url, json))
            return SimpleNamespace(
                status_code=200,
                text='{"errcode":0,"errmsg":"ok"}',
                json=lambda: {"errcode": 0},
            )

    monkeypatch.setattr(alert_service.httpx, "AsyncClient", FakeAsyncClient)
    alert_service._mem_cooldowns.clear()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _login_admin(client)
        try:
            # 配置企微 Webhook（密钥加密保存）
            upd = await client.put(
                "/api/v1/admin/system/configs",
                headers=headers,
                json={
                    "items": {
                        "alert.webhook_enabled": True,
                        "alert.webhook_provider": "wecom",
                        "alert.webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=unit-test-key",
                        "alert.cooldown_seconds": 120,
                    }
                },
            )
            assert upd.status_code == 200

            # 管理员发起连通性测试告警
            test_resp = await client.post(
                "/api/v1/admin/system/alert/test",
                headers=headers,
                json={"message": "单元测试连通校验"},
            )
            assert test_resp.status_code == 200
            assert test_resp.json()["data"]["delivered"] is True
            assert len(posted) == 1
            assert "单元测试连通校验" in posted[0][1]["markdown"]["content"]

            # 触发登录锁定时首次推送，冷却期内第二次自动去重抑制
            first = await alert_service.notify_login_lockout(
                account="victim@qq.com", client_ip="203.0.113.5", fail_count=5, lock_minutes=15
            )
            second = await alert_service.notify_login_lockout(
                account="victim@qq.com", client_ip="203.0.113.5", fail_count=5, lock_minutes=15
            )
            assert first["delivered"] is True
            assert second["delivered"] is False
            assert second["skipped"] == "cooldown"
        finally:
            await client.post(
                "/api/v1/admin/system/configs/reset",
                headers=headers,
                json={"group_name": "alert"},
            )


@pytest.mark.asyncio
async def test_llm_auto_fallback_on_primary_402_failure(monkeypatch: pytest.MonkeyPatch):
    primary_cfg = RuntimeAIConfig(
        id=101,
        name="DeepSeek 主模型",
        provider="deepseek",
        model_name="deepseek-flash",
        base_url="https://api.deepseek.com",
        api_key="sk-primary-key",
        api_key_masked="sk-pri****-key",
        temperature=0.7,
        top_p=1.0,
        max_tokens=2048,
        timeout_seconds=30,
        max_history_messages=20,
        system_prompt="你是情感助手",
        extra_params={"protocol": "openai"},
    )
    backup_cfg = RuntimeAIConfig(
        id=102,
        name="通义千问备选",
        provider="qwen",
        model_name="qwen-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key="sk-backup-key",
        api_key_masked="sk-bac****-key",
        temperature=0.7,
        top_p=1.0,
        max_tokens=2048,
        timeout_seconds=30,
        max_history_messages=20,
        system_prompt="你是情感助手",
        extra_params={"protocol": "openai"},
    )

    alert_events: list[dict[str, Any]] = []

    async def fake_resolve_runtime(config_id: int | None = None) -> RuntimeAIConfig:
        return primary_cfg

    async def fake_resolve_fallbacks(exclude_id: int | None = None) -> list[RuntimeAIConfig]:
        return [backup_cfg]

    async def fake_notify_llm(**kwargs: Any) -> dict[str, Any]:
        alert_events.append(kwargs)
        return {"delivered": True}

    def fake_build_llm(self: Any, cfg: RuntimeAIConfig, temperature: float, *, streaming: bool):
        adapter = get_provider_adapter(cfg.provider)
        assert adapter is not None

        class _FakeLLM:
            async def ainvoke(self, _messages: Any) -> AIMessage:
                if cfg.id == primary_cfg.id:
                    raise RuntimeError("Error code: 402 Insufficient Balance")
                return AIMessage(content="我是通义千问备用模型，已为你无缝接管回复。")

        return adapter, _FakeLLM()

    monkeypatch.setattr(llm_mod, "resolve_runtime_config", fake_resolve_runtime)
    monkeypatch.setattr(llm_mod, "resolve_fallback_configs", fake_resolve_fallbacks)
    monkeypatch.setattr(alert_service, "notify_llm_alert", fake_notify_llm)
    monkeypatch.setattr(llm_mod.LLMService, "_build_llm", fake_build_llm)

    from app.schemas.ai import ChatRequest

    result = await llm_mod.llm_service.chat(
        ChatRequest(message="今天有点想TA，怎么自然发消息？"),
        user_type="web",
        user_id=999,
        username="fallback_tester",
        role="super_admin",
    )
    assert result.fallback_used is True
    assert "DeepSeek 主模型" in result.fallback_from
    assert result.provider == "qwen"
    assert result.model == "qwen-plus"
    assert "无缝接管" in result.reply
    assert len(alert_events) == 1
    assert "通义千问备选" in alert_events[0]["fallback_to"]
