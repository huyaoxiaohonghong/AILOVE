from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessageChunk, SystemMessage
from langchain_openai import ChatOpenAI

from app.core.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret, mask_api_key
from app.main import app
from app.services.ai_providers import get_provider_adapter
from app.services.llm_service import llm_service
from tests.test_health_and_api import solve_slider_captcha


def test_secret_encryption_and_masking():
    plain = "sk-deepseek-test-9876543210abcdef"
    cipher = encrypt_secret(plain)
    assert cipher and cipher != plain
    assert decrypt_secret(cipher) == plain
    assert mask_api_key(plain) == "sk-dee****cdef"


def test_deepseek_dual_protocol_adapter_and_chunk_extraction():
    adapter = get_provider_adapter("deepseek")
    assert adapter is not None
    assert adapter.descriptor.default_base_url == "https://api.deepseek.com"
    assert adapter.descriptor.protocol_endpoints == {
        "openai": "https://api.deepseek.com",
        "anthropic": "https://api.deepseek.com/anthropic",
    }

    # OpenAI 协议构建 ChatOpenAI
    openai_llm = adapter.build_chat_model(
        api_key="sk-test-openai",
        base_url="https://api.deepseek.com",
        model_name="deepseek-flash",
        temperature=0.7,
        top_p=1.0,
        max_tokens=4096,
        timeout_seconds=30,
        streaming=True,
        extra_params={"protocol": "openai"},
    )
    assert isinstance(openai_llm, ChatOpenAI)
    assert openai_llm.model_name == "deepseek-flash"

    # Anthropic 协议构建 ChatAnthropic
    anthropic_llm = adapter.build_chat_model(
        api_key="sk-test-anthropic",
        base_url="https://api.deepseek.com/anthropic",
        model_name="deepseek-v4-pro",
        temperature=0.6,
        top_p=1.0,
        max_tokens=8192,
        timeout_seconds=60,
        streaming=True,
        extra_params={"protocol": "anthropic"},
    )
    assert isinstance(anthropic_llm, ChatAnthropic)
    assert anthropic_llm.model == "deepseek-v4-pro"
    assert anthropic_llm.anthropic_api_url == "https://api.deepseek.com/anthropic"

    # OpenAI reasoning_content + text 提取
    openai_chunk = AIMessageChunk(
        content="最终答复",
        additional_kwargs={"reasoning_content": "先分析条件"},
    )
    assert adapter.extract_chunk_deltas(openai_chunk) == ("先分析条件", "最终答复")

    # Anthropic thinking + text block 提取
    anthropic_chunk = AIMessageChunk(
        content=[
            {"type": "thinking", "thinking": "逐步推理"},
            {"type": "text", "text": "结论如下"},
        ]
    )
    assert adapter.extract_chunk_deltas(anthropic_chunk) == ("逐步推理", "结论如下")


def test_realtime_clock_injected_into_system_message():
    msgs = llm_service._build_messages("你是 AILOVE 助手。", [], "今天几号？", tz_name="Asia/Shanghai")
    assert isinstance(msgs[0], SystemMessage)
    expected_date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y年%m月%d日")
    assert expected_date in str(msgs[0].content)
    assert "北京时间 Asia/Shanghai, UTC+8" in str(msgs[0].content)
    assert "你是 AILOVE 助手。" in str(msgs[0].content)


@pytest.mark.asyncio
async def test_ai_config_crud_and_deepseek_provider_policy():
    settings = get_settings()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. 管理员登录
        cap = await solve_slider_captcha(client, "login")
        login = await client.post(
            "/api/v1/auth/login",
            json={
                "account": settings.DEFAULT_ADMIN_USERNAME,
                "password": settings.DEFAULT_ADMIN_PASSWORD,
                "captcha_token": cap,
            },
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}

        # 2. 获取提供商目录：DeepSeek 为 active，支持双协议与 deepseek-flash / deepseek-v4-pro
        prov_resp = await client.get("/api/v1/admin/ai/providers", headers=headers)
        assert prov_resp.status_code == 200
        providers = prov_resp.json()["data"]["items"]
        deepseek = next(p for p in providers if p["code"] == "deepseek")
        assert deepseek["status"] == "active"
        assert deepseek["default_base_url"] == "https://api.deepseek.com"
        assert deepseek["protocol_endpoints"]["openai"] == "https://api.deepseek.com"
        assert deepseek["protocol_endpoints"]["anthropic"] == "https://api.deepseek.com/anthropic"
        model_ids = [m["id"] for m in deepseek["models"]]
        assert "deepseek-flash" in model_ids
        assert "deepseek-v4-pro" in model_ids

        # 3. 尚未开放的提供商创建应被明确拦截
        unsupported = await client.post(
            "/api/v1/admin/ai/configs",
            json={
                "name": "未开放模型测试",
                "provider": "openai",
                "model_name": "gpt-4o",
                "base_url": "https://api.openai.com/v1",
            },
            headers=headers,
        )
        assert unsupported.status_code == 400

        # 4. 创建 DeepSeek V4 Pro（Anthropic 协议）配置：API Key 自动加密并脱敏返回
        create_resp = await client.post(
            "/api/v1/admin/ai/configs",
            json={
                "name": "DeepSeek V4 Pro (Anthropic)",
                "provider": "deepseek",
                "protocol": "anthropic",
                "model_name": "deepseek-v4-pro",
                "base_url": "https://api.deepseek.com/anthropic",
                "api_key": "sk-test-deepseek-secret-998877",
                "max_tokens": 8192,
                "is_default": False,
            },
            headers=headers,
        )
        assert create_resp.status_code == 200
        created = create_resp.json()["data"]
        assert created["protocol"] == "anthropic"
        assert created["base_url"] == "https://api.deepseek.com/anthropic"
        assert created["has_api_key"] is True
        assert created["api_key_masked"] == "sk-tes****8877"
        assert "sk-test-deepseek-secret-998877" not in str(created)
        cid = created["id"]

        # 5. 编辑配置且留空 api_key -> 保留原有加密 Key，同时支持切换回 OpenAI 协议
        edit_resp = await client.put(
            f"/api/v1/admin/ai/configs/{cid}",
            json={
                "name": "DeepSeek V4 Pro 旗舰",
                "protocol": "openai",
                "base_url": "https://api.deepseek.com",
                "api_key": "",
            },
            headers=headers,
        )
        assert edit_resp.status_code == 200
        edited = edit_resp.json()["data"]
        assert edited["name"] == "DeepSeek V4 Pro 旗舰"
        assert edited["protocol"] == "openai"
        assert edited["base_url"] == "https://api.deepseek.com"
        assert edited["has_api_key"] is True
        assert edited["api_key_masked"] == "sk-tes****8877"

        # 6. 设为默认模型 + 检查 /api/v1/ai/models 列表
        def_resp = await client.post(
            f"/api/v1/admin/ai/configs/{cid}/set-default", headers=headers
        )
        assert def_resp.status_code == 200
        assert def_resp.json()["data"]["is_default"] is True

        models_resp = await client.get("/api/v1/ai/models", headers=headers)
        assert models_resp.status_code == 200
        m_items = models_resp.json()["data"]["items"]
        target = next(m for m in m_items if m["id"] == cid)
        assert target["is_default"] is True
        assert target["protocol"] == "openai"
        assert target["supports_reasoning"] is True
        assert "api_key" not in target

        # 7. 清空 API Key 后测试连通性应返回友好错误提示
        await client.put(
            f"/api/v1/admin/ai/configs/{cid}",
            json={"clear_api_key": True},
            headers=headers,
        )
        test_resp = await client.post(
            f"/api/v1/admin/ai/configs/{cid}/test", headers=headers
        )
        assert test_resp.status_code == 200
        assert test_resp.json()["data"]["success"] is False
        assert "API Key" in test_resp.json()["data"]["message"]

        # 8. 删除配置
        del_resp = await client.delete(
            f"/api/v1/admin/ai/configs/{cid}", headers=headers
        )
        assert del_resp.status_code == 200


def test_humanize_llm_error_messages():
    from app.services.ai_providers import humanize_llm_error

    kw = {"model_name": "deepseek-flash", "base_url": "https://api.deepseek.com"}
    assert "401" in humanize_llm_error(Exception("Error code: 401 - Authentication Fails"), **kw)
    assert "402" in humanize_llm_error(Exception("Error code: 402 Insufficient Balance"), **kw)
    assert "429" in humanize_llm_error(Exception("Error code: 429 rate limit"), **kw)
    assert "超时" in humanize_llm_error(Exception("Request timed out"), latency_ms=25000, **kw)


@pytest.mark.asyncio
async def test_chat_session_history_is_isolated_per_owner():
    from app.services.llm_service import build_owner_scope

    owner_a = build_owner_scope("user", 101)
    owner_b = build_owner_scope("user", 202)
    sid = "isolation-test-session"
    await llm_service.save_history(sid, [{"role": "user", "content": "私密内容"}], owner_a)

    assert (await llm_service.get_history(sid, owner_a))[0]["content"] == "私密内容"
    # 其他账号即使拿到相同 session_id 也无法读取或清空
    assert await llm_service.get_history(sid, owner_b) == []
    await llm_service.clear_history(sid, owner_b)
    assert len(await llm_service.get_history(sid, owner_a)) == 1

    await llm_service.clear_history(sid, owner_a)
    assert await llm_service.get_history(sid, owner_a) == []
