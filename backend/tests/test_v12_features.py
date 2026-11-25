from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, HumanMessage

from app.main import app
from app.services import llm_service as llm_mod
from app.services.ai_config_service import RuntimeAIConfig
from app.services.ai_providers import get_provider_adapter
from tests.test_health_and_api import solve_slider_captcha

_SAMPLE_IMAGE_DATA_URL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/x8AAwMCAO+ip1sAAAAASUVORK5CYII="
)


async def _login_admin(client: AsyncClient) -> dict[str, str]:
    from app.core.config import get_settings

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


def _parse_sse_events(body_text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for block in body_text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


@pytest.mark.asyncio
async def test_soften_draft_sync_and_stream():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        wx_res = await client.post(
            "/api/v1/miniapp/auth/wx-login",
            json={"code": "soften_tester_001", "nickname": "小柔测"},
        )
        assert wx_res.status_code == 200
        headers = {"Authorization": f"Bearer {wx_res.json()['data']['access_token']}"}

        presets = await client.get("/api/v1/ai/soften-draft/presets", headers=headers)
        assert presets.status_code == 200
        assert len(presets.json()["data"]["intensities"]) >= 3

        sync_res = await client.post(
            "/api/v1/ai/soften-draft",
            json={
                "draft_message": "算了随便你吧，忙你的去，以后别来找我了",
                "intensity": "heated",
                "context": "约好见面临时取消",
                "incognito": True,
            },
            headers=headers,
        )
        assert sync_res.status_code == 200
        data = sync_res.json()["data"]
        assert data["incognito"] is True
        assert data["session_id"].startswith("incognito_")
        assert "先别发" in data["reply"]

        stream_res = await client.post(
            "/api/v1/ai/soften-draft/stream",
            json={
                "draft_message": "你是不是根本不在意我的感受？",
                "intensity": "mild",
                "incognito": True,
            },
            headers=headers,
        )
        assert stream_res.status_code == 200
        evts = _parse_sse_events(stream_res.text)
        assert evts[0]["event"] == "meta"
        assert evts[0]["incognito"] is True
        assert any(e["event"] == "done" for e in evts)


@pytest.mark.asyncio
async def test_reply_helper_multimodal_images_routing_and_never_persists_base64(
    monkeypatch: pytest.MonkeyPatch,
):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        wx_res = await client.post(
            "/api/v1/miniapp/auth/wx-login",
            json={"code": "vision_tester_001", "nickname": "识图小测"},
        )
        headers = {"Authorization": f"Bearer {wx_res.json()['data']['access_token']}"}

        # 1. 空文字且空图片 -> 422
        bad_empty = await client.post(
            "/api/v1/ai/reply-helper",
            json={"partner_message": "", "images": []},
            headers=headers,
        )
        assert bad_empty.status_code == 422

        # 2. 非法图片格式 -> 422
        bad_img = await client.post(
            "/api/v1/ai/reply-helper",
            json={"images": ["https://evil.example.com/a.png"]},
            headers=headers,
        )
        assert bad_img.status_code == 422

        # 3. 无 Key 演示模式下上传截图应正常响应，且对话历史绝不存入 base64
        mock_res = await client.post(
            "/api/v1/ai/reply-helper",
            json={"images": [_SAMPLE_IMAGE_DATA_URL], "scene": "ambiguous", "tone": "playful"},
            headers=headers,
        )
        assert mock_res.status_code == 200
        sid = mock_res.json()["data"]["session_id"]
        assert "1 张" in mock_res.json()["data"]["reply"]

        hist = await client.get(f"/api/v1/ai/conversations/{sid}/messages", headers=headers)
        assert hist.status_code == 200
        raw_hist = json.dumps(hist.json()["data"], ensure_ascii=False)
        assert "data:image/" not in raw_hist
        assert "iVBORw0KGgo" not in raw_hist

        # 4. 当主模型为非视觉 DeepSeek 且无视觉模型时，报错友好引导
        text_only_cfg = RuntimeAIConfig(
            id=801,
            name="DeepSeek 纯文本",
            provider="deepseek",
            model_name="deepseek-flash",
            base_url="https://api.deepseek.com",
            api_key="sk-text-only",
            api_key_masked="sk-t****ly",
            temperature=0.7,
            top_p=1.0,
            max_tokens=2048,
            timeout_seconds=30,
            max_history_messages=20,
            system_prompt="你是情感军师",
            extra_params={"protocol": "openai"},
        )
        vision_cfg = RuntimeAIConfig(
            id=802,
            name="千问视觉识图",
            provider="qwen",
            model_name="qwen-vl-plus",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            api_key="sk-qwen-vision",
            api_key_masked="sk-q****on",
            temperature=0.7,
            top_p=1.0,
            max_tokens=2048,
            timeout_seconds=30,
            max_history_messages=20,
            system_prompt="你是情感军师",
            extra_params={"protocol": "openai"},
        )

        async def fake_runtime(config_id: int | None = None) -> RuntimeAIConfig:
            return text_only_cfg

        async def fake_no_vision(config_id: int | None = None):
            return None

        monkeypatch.setattr(llm_mod, "resolve_runtime_config", fake_runtime)
        monkeypatch.setattr(llm_mod, "resolve_vision_config", fake_no_vision)
        no_vision_resp = await client.post(
            "/api/v1/ai/reply-helper",
            json={"images": [_SAMPLE_IMAGE_DATA_URL], "incognito": True},
            headers=headers,
        )
        assert no_vision_resp.status_code == 400
        assert "多模态" in no_vision_resp.json()["message"]

        # 5. 当存在视觉模型时，自动切换为视觉模型且向 LLM 传入 image_url 块
        captured_messages: list[Any] = []

        async def fake_has_vision(config_id: int | None = None) -> RuntimeAIConfig:
            return vision_cfg

        def fake_build_llm(self: Any, cfg: RuntimeAIConfig, temperature: float, *, streaming: bool):
            adapter = get_provider_adapter(cfg.provider)
            assert adapter is not None

            class _FakeVisionLLM:
                async def ainvoke(self, messages: list[Any]) -> AIMessage:
                    captured_messages.extend(messages)
                    return AIMessage(content="### 💬 3 条可直接发送的备选回复\n> 我刚看懂她是在撒娇试探啦")

            return adapter, _FakeVisionLLM()

        monkeypatch.setattr(llm_mod, "resolve_vision_config", fake_has_vision)
        monkeypatch.setattr(llm_mod.LLMService, "_build_llm", fake_build_llm)
        vision_ok = await client.post(
            "/api/v1/ai/reply-helper",
            json={"images": [_SAMPLE_IMAGE_DATA_URL], "incognito": True},
            headers=headers,
        )
        assert vision_ok.status_code == 200
        assert vision_ok.json()["data"]["model"] == "qwen-vl-plus"
        human_msg = [m for m in captured_messages if isinstance(m, HumanMessage)][-1]
        assert isinstance(human_msg.content, list)
        assert any(part.get("type") == "image_url" for part in human_msg.content)


@pytest.mark.asyncio
async def test_favorites_incognito_export_and_purge_sovereignty():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        wx_a = await client.post(
            "/api/v1/miniapp/auth/wx-login",
            json={"code": "fav_user_a", "nickname": "收藏用户A"},
        )
        wx_b = await client.post(
            "/api/v1/miniapp/auth/wx-login",
            json={"code": "fav_user_b", "nickname": "收藏用户B"},
        )
        headers_a = {"Authorization": f"Bearer {wx_a.json()['data']['access_token']}"}
        headers_b = {"Authorization": f"Bearer {wx_b.json()['data']['access_token']}"}

        # 1. 无痕对话不存入历史，支持 ephemeral_history
        inc_chat = await client.post(
            "/api/v1/ai/chat",
            json={
                "message": "秘密心事不留痕",
                "incognito": True,
                "ephemeral_history": [{"role": "user", "content": "前一句临时上下文"}],
            },
            headers=headers_a,
        )
        assert inc_chat.status_code == 200
        inc_sid = inc_chat.json()["data"]["session_id"]

        # 正常对话落库
        norm_chat = await client.post(
            "/api/v1/ai/chat",
            json={"message": "常规咨询留档"},
            headers=headers_a,
        )
        assert norm_chat.status_code == 200
        norm_sid = norm_chat.json()["data"]["session_id"]

        convs_a = await client.get("/api/v1/ai/conversations", headers=headers_a)
        sids_a = [c["session_id"] for c in convs_a.json()["data"]["items"]]
        assert inc_sid not in sids_a
        assert norm_sid in sids_a

        # 2. 收藏夹新增、去重、跨用户隔离
        f1 = await client.post(
            "/api/v1/ai/favorites",
            json={
                "content": "忙完这阵记得给自己留十分钟喘口气，我随时都在～",
                "category": "reply_helper",
                "scene_label": "暧昧升温",
            },
            headers=headers_a,
        )
        assert f1.status_code == 200
        assert f1.json()["data"]["deduplicated"] is False
        fav_id = f1.json()["data"]["item"]["id"]

        f_dup = await client.post(
            "/api/v1/ai/favorites",
            json={"content": "忙完这阵记得给自己留十分钟喘口气，我随时都在～"},
            headers=headers_a,
        )
        assert f_dup.status_code == 200
        assert f_dup.json()["data"]["deduplicated"] is True

        # B 用户不可删除 A 的收藏
        b_del = await client.delete(f"/api/v1/ai/favorites/{fav_id}", headers=headers_b)
        assert b_del.status_code == 404

        # 3. 导出 Markdown 手账（含收藏与常规会话，不含无痕对话）
        exp_json = await client.get("/api/v1/ai/my-data/export?format=json", headers=headers_a)
        assert exp_json.status_code == 200
        md = exp_json.json()["data"]["markdown"]
        assert "忙完这阵记得给自己留十分钟喘口气" in md
        assert "常规咨询留档" in md
        assert "秘密心事不留痕" not in md

        exp_file = await client.get("/api/v1/ai/my-data/export?format=markdown", headers=headers_a)
        assert exp_file.status_code == 200
        assert "text/markdown" in exp_file.headers.get("content-type", "")

        # 4. 一键彻底清空个人云端数据
        purged = await client.delete("/api/v1/ai/my-data", headers=headers_a)
        assert purged.status_code == 200
        assert purged.json()["data"]["cleared_conversations"] >= 1
        assert purged.json()["data"]["cleared_favorites"] >= 1

        left_convs = await client.get("/api/v1/ai/conversations", headers=headers_a)
        assert len(left_convs.json()["data"]["items"]) == 0
        left_favs = await client.get("/api/v1/ai/favorites", headers=headers_a)
        assert len(left_favs.json()["data"]["items"]) == 0


@pytest.mark.asyncio
async def test_invite_code_circle_access_control():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin_headers = await _login_admin(client)
        created_code_id: int | None = None
        try:
            # 1. 管理员创建仅可用 2 次的内测邀请码
            gen = await client.post(
                "/api/v1/admin/system/invite-codes",
                headers=admin_headers,
                json={"note": "单测好友圈", "max_uses": 2},
            )
            assert gen.status_code == 200
            invite_code = gen.json()["data"]["code"]
            created_code_id = gen.json()["data"]["id"]
            assert invite_code.startswith("LOVE-")

            # 开启小圈子邀请码准入
            upd = await client.put(
                "/api/v1/admin/system/configs",
                headers=admin_headers,
                json={
                    "items": {
                        "registration.invite_code_required": True,
                        "registration.slider_captcha_enabled": False,
                    }
                },
            )
            assert upd.status_code == 200
            pub = await client.get("/api/v1/system/public-config")
            assert pub.json()["data"]["invite_code_required"] is True

            # 2. 未带邀请码的邮箱注册被拒
            bad_reg = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "no_invite_user@qq.com",
                    "password": "Password123",
                    "invite_code": "",
                },
            )
            assert bad_reg.status_code == 403

            # 带有效邀请码邮箱注册成功（消耗第 1 次）
            ok_reg = await client.post(
                "/api/v1/auth/register",
                json={
                    "email": "invited_friend_01@qq.com",
                    "password": "Password123",
                    "invite_code": invite_code,
                },
            )
            assert ok_reg.status_code == 200

            # 3. 未激活邀请码的小程序新用户调用 AI 被拦截 (403)
            wx_new = await client.post(
                "/api/v1/miniapp/auth/wx-login",
                json={"code": "unverified_mini_001", "nickname": "待激活微信用户"},
            )
            assert wx_new.status_code == 200
            assert wx_new.json()["data"]["user"]["invite_verified"] is False
            wx_headers = {"Authorization": f"Bearer {wx_new.json()['data']['access_token']}"}

            blocked_chat = await client.post(
                "/api/v1/ai/chat",
                json={"message": "未激活能聊吗"},
                headers=wx_headers,
            )
            assert blocked_chat.status_code == 403

            # 在小程序验证邀请码（消耗第 2 次）后可正常调用
            act_res = await client.post(
                "/api/v1/miniapp/user/verify-invite",
                json={"invite_code": invite_code},
                headers=wx_headers,
            )
            assert act_res.status_code == 200
            assert act_res.json()["data"]["invite_verified"] is True

            # 已激活用户拉取旧 token 也应通过 DB 查验放行
            allowed_chat = await client.post(
                "/api/v1/ai/chat",
                json={"message": "激活成功啦！", "incognito": True},
                headers=wx_headers,
            )
            assert allowed_chat.status_code == 200

            # 4. 次数耗尽（2/2）后第 3 人再使用应被拒绝
            wx_third = await client.post(
                "/api/v1/miniapp/auth/wx-login",
                json={"code": "unverified_mini_002"},
            )
            third_headers = {"Authorization": f"Bearer {wx_third.json()['data']['access_token']}"}
            exhausted = await client.post(
                "/api/v1/miniapp/user/verify-invite",
                json={"invite_code": invite_code},
                headers=third_headers,
            )
            assert exhausted.status_code == 403
            assert "上限" in exhausted.json()["message"]
        finally:
            if created_code_id is not None:
                await client.delete(
                    f"/api/v1/admin/system/invite-codes/{created_code_id}",
                    headers=admin_headers,
                )
            await client.post(
                "/api/v1/admin/system/configs/reset",
                headers=admin_headers,
                json={"group_name": "registration"},
            )
