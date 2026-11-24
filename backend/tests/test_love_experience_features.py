from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import app
from app.services.emotion_guard import build_reply_helper_prompt, evaluate_emotion_care
from app.services.love_profile_service import build_love_profile_prompt
from tests.test_health_and_api import solve_slider_captcha


async def _login_admin(client: AsyncClient) -> str:
    settings = get_settings()
    cap_token = await solve_slider_captcha(client, "login")
    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "account": settings.DEFAULT_ADMIN_USERNAME,
            "password": settings.DEFAULT_ADMIN_PASSWORD,
            "captcha_token": cap_token,
        },
    )
    assert resp.status_code == 200
    return resp.json()["data"]["access_token"]


@pytest.mark.asyncio
async def test_conversation_persona_binding_and_pinning_order():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _login_admin(client)
        headers = {"Authorization": f"Bearer {token}"}

        personas_resp = await client.get("/api/v1/ai/personas", headers=headers)
        assert personas_resp.status_code == 200
        personas = personas_resp.json()["data"]["items"]
        assert len(personas) >= 2
        p1, p2 = personas[0], personas[1]

        # 开启会话 A（绑定智能体 p1）与会话 B（绑定智能体 p2）
        chat_a = await client.post(
            "/api/v1/ai/chat",
            headers=headers,
            json={"message": "会话A测试：暧昧期怎么自然推进？", "persona_id": p1["id"]},
        )
        assert chat_a.status_code == 200
        sid_a = chat_a.json()["data"]["session_id"]

        chat_b = await client.post(
            "/api/v1/ai/chat",
            headers=headers,
            json={"message": "会话B测试：周末第一次约会怎么安排？", "persona_id": p2["id"]},
        )
        assert chat_b.status_code == 200
        sid_b = chat_b.json()["data"]["session_id"]

        # 置顶会话 A 后，列表首位应为 A 且保留智能体快照
        pin_resp = await client.patch(
            f"/api/v1/ai/conversations/{sid_a}",
            headers=headers,
            json={"is_pinned": True, "title": "置顶情感咨询"},
        )
        assert pin_resp.status_code == 200
        pin_data = pin_resp.json()["data"]
        assert pin_data["is_pinned"] is True
        assert pin_data["title"] == "置顶情感咨询"
        assert pin_data["persona_id"] == p1["id"]

        list_resp = await client.get("/api/v1/ai/conversations", headers=headers)
        assert list_resp.status_code == 200
        items = list_resp.json()["data"]["items"]
        pos_a = next(i for i, it in enumerate(items) if it["session_id"] == sid_a)
        pos_b = next(i for i, it in enumerate(items) if it["session_id"] == sid_b)
        assert pos_a < pos_b
        assert items[pos_a]["is_pinned"] is True
        assert items[pos_a]["persona_id"] == p1["id"]
        assert items[pos_a]["persona_name"] == p1["name"]

        # 加载历史详情自动携带绑定的智能体，供前端无缝还原
        detail_resp = await client.get(
            f"/api/v1/ai/conversations/{sid_a}/messages", headers=headers
        )
        assert detail_resp.status_code == 200
        detail = detail_resp.json()["data"]
        assert detail["persona_id"] == p1["id"]
        assert detail["persona_name"] == p1["name"]
        assert detail["is_pinned"] is True

        # 支持解除会话智能体绑定并取消置顶
        unbind_resp = await client.patch(
            f"/api/v1/ai/conversations/{sid_a}",
            headers=headers,
            json={"clear_persona": True, "is_pinned": False},
        )
        assert unbind_resp.status_code == 200
        unbind_data = unbind_resp.json()["data"]
        assert unbind_data["persona_id"] is None
        assert unbind_data["persona_name"] == ""
        assert unbind_data["is_pinned"] is False


@pytest.mark.asyncio
async def test_love_profile_crud_isolation_and_context_injection():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_token = await _login_admin(client)
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 初始状态未配置，且返回 7 阶段与预设标签
        init_resp = await client.get("/api/v1/ai/love-profile", headers=admin_headers)
        assert init_resp.status_code == 200
        init_data = init_resp.json()["data"]
        assert len(init_data["presets"]["stages"]) == 7
        assert len(init_data["presets"]["partner_trait_presets"]) >= 5

        # 保存个人情感背景记忆卡
        put_resp = await client.put(
            "/api/v1/ai/love-profile",
            headers=admin_headers,
            json={
                "relationship_stage": "ambiguous",
                "partner_nickname": "小林",
                "partner_traits": ["慢热型", "嘴硬心软", "慢热型"],
                "my_traits": ["容易内耗", "直球真诚"],
                "relationship_goal": "推进关系确认",
                "communication_taboos": "忌连环追问和翻旧账",
                "background_notes": "认识两个月，每天都会互道晚安",
                "auto_inject": True,
            },
        )
        assert put_resp.status_code == 200
        saved = put_resp.json()["data"]["profile"]
        assert saved["is_configured"] is True
        assert saved["relationship_stage_label"] == "暧昧升温期"
        assert saved["partner_traits"] == ["慢热型", "嘴硬心软"]

        prompt_block = build_love_profile_prompt(saved)
        assert "暧昧升温期" in prompt_block
        assert "小林" in prompt_block
        assert "推进关系确认" in prompt_block
        assert "忌连环追问" in prompt_block

        # 对话时默认自动注入，传 use_love_profile=False 时跳过注入
        chat_injected = await client.post(
            "/api/v1/ai/chat",
            headers=admin_headers,
            json={"message": "今晚想约TA看电影怎么开口？"},
        )
        assert chat_injected.status_code == 200
        assert chat_injected.json()["data"]["love_profile_injected"] is True

        chat_skip = await client.post(
            "/api/v1/ai/chat",
            headers=admin_headers,
            json={"message": "随便聊聊天气", "use_love_profile": False},
        )
        assert chat_skip.status_code == 200
        assert chat_skip.json()["data"]["love_profile_injected"] is False

        # 注册另一独立账号验证隐私严格隔离
        cap_reg = await solve_slider_captcha(client, "register")
        reg = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "loveprofile.iso@qq.com",
                "password": "Password123",
                "nickname": "IsoUser",
                "captcha_token": cap_reg,
            },
        )
        assert reg.status_code == 200
        other_token = reg.json()["data"]["access_token"]
        other_profile_resp = await client.get(
            "/api/v1/ai/love-profile",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert other_profile_resp.status_code == 200
        assert other_profile_resp.json()["data"]["profile"]["is_configured"] is False

        # 一键清空管理员情感档案
        del_resp = await client.delete("/api/v1/ai/love-profile", headers=admin_headers)
        assert del_resp.status_code == 200
        assert del_resp.json()["data"]["profile"]["is_configured"] is False


@pytest.mark.asyncio
async def test_reply_helper_and_emotion_care_guardrail():
    # 1. 纯本地护栏评估与 Prompt 构造校验
    assert evaluate_emotion_care("周末一起去吃火锅吧") is None
    distress = evaluate_emotion_care("刚分手好崩溃，整夜睡不着")
    assert distress is not None and distress["level"] == "distress"
    crisis = evaluate_emotion_care("太痛苦了，我真的不想活了")
    assert crisis is not None and crisis["level"] == "crisis"
    assert any("400-161-9995" in h["phone"] for h in crisis["hotlines"])

    user_msg, sys_inst = build_reply_helper_prompt(
        partner_message="最近有点忙，改天再聊",
        scene="cold_reply",
        tone="graceful",
        my_intent="体面收尾且不显得卑微",
    )
    assert "对方冷淡" in user_msg and "体面台阶" in user_msg
    assert "潜台词与情绪拆解" in sys_inst and "3 条可直接发送" in sys_inst

    # 2. 端到端 API 验证：预设、帮我回消息自动绑定恋爱军师、同步与流式护栏回传
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _login_admin(client)
        headers = {"Authorization": f"Bearer {token}"}

        presets = await client.get("/api/v1/ai/reply-helper/presets", headers=headers)
        assert presets.status_code == 200
        assert len(presets.json()["data"]["scenes"]) == 5
        assert len(presets.json()["data"]["tones"]) == 5

        helper_resp = await client.post(
            "/api/v1/ai/reply-helper",
            headers=headers,
            json={
                "partner_message": "最近项目太忙了，改天有空再约你",
                "scene": "cold_reply",
                "tone": "graceful",
                "my_intent": "给对方台阶同时保留好感",
            },
        )
        assert helper_resp.status_code == 200
        hdata = helper_resp.json()["data"]
        assert hdata["persona_id"] is not None
        assert hdata["persona_name"] == "高情商恋爱军师"
        assert hdata["emotion_care"] is None

        # 同步对话触发低谷护栏（且绝不泄漏内部 prompt_guidance）
        distress_resp = await client.post(
            "/api/v1/ai/chat",
            headers=headers,
            json={"message": "被分手了好崩溃，哭了一晚上"},
        )
        assert distress_resp.status_code == 200
        ec_distress = distress_resp.json()["data"]["emotion_care"]
        assert ec_distress is not None
        assert ec_distress["level"] == "distress"
        assert "prompt_guidance" not in ec_distress

        # SSE 流式对话触发危机护栏，meta 事件应立即携带援助热线卡片
        stream_resp = await client.post(
            "/api/v1/ai/chat/stream",
            headers=headers,
            json={"message": "太绝望了，我现在真的不想活了"},
        )
        assert stream_resp.status_code == 200
        meta_event = None
        for line in stream_resp.text.splitlines():
            if line.startswith("data: "):
                evt = json.loads(line[6:])
                if evt.get("event") == "meta":
                    meta_event = evt
                    break
        assert meta_event is not None
        assert meta_event["emotion_care"]["level"] == "crisis"
        assert len(meta_event["emotion_care"]["hotlines"]) >= 2
