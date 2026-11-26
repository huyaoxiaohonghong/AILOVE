from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import mascot_service


def _login_user(client: TestClient, code: str = "mascot_v2_test_code") -> dict[str, str]:
    res = client.post("/api/v1/miniapp/auth/wx-login", json={"code": code, "nickname": "恋恋测试"})
    assert res.status_code == 200
    token = res.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_pad_decay_and_ebbinghaus_retention():
    # PAD homeostasis decays smoothly toward circadian baseline
    v_late, a_late = mascot_service.apply_homeostasis_decay(0.9, 0.95, 600.0, local_hour=1)
    assert v_late < 0.9
    assert a_late < 0.95
    assert mascot_service.map_pad_to_mood(0.10, 0.12) == "sleepy"
    assert mascot_service.map_pad_to_mood(0.80, 0.85) == "excited"
    assert mascot_service.map_pad_to_mood(-0.60, 0.25) == "comfort"

    # Ebbinghaus retention: higher recall_count & importance retain more memory over time
    r_fresh = mascot_service.ebbinghaus_retention(0.5, importance=3.0, recall_count=0)
    r_old_weak = mascot_service.ebbinghaus_retention(10.0, importance=1.5, recall_count=0)
    r_old_recalled = mascot_service.ebbinghaus_retention(10.0, importance=3.5, recall_count=4)
    assert r_fresh > r_old_weak
    assert r_old_recalled > r_old_weak


def test_strip_protocol_tags():
    raw = (
        '[[emo:shy|act:blush|dv:0.2|da:0.1]]\n'
        "你好呀，恋恋来帮你看看~\n"
        '[[tool:{"type":"start_calm_breathing","label":"做30秒呼吸","seconds":30}]]'
    )
    cleaned = mascot_service.strip_mascot_protocol_tags(raw)
    assert cleaned == "你好呀，恋恋来帮你看看~"
    assert "[[" not in cleaned


def test_mascot_state_interact_checkin_memory_and_patch():
    with TestClient(app) as client:
        headers = _login_user(client, "mascot_v2_flow_01")

        # 1. Fetch initial state
        r_state = client.get("/api/v1/mascot/state", headers=headers)
        assert r_state.status_code == 200
        st = r_state.json()["data"]
        assert st["bond_level"] >= 1
        assert st["need_mood_checkin"] is True

        # 2. Physical gesture interaction (rub_head & combo_dizzy)
        r_rub = client.post("/api/v1/mascot/interact", json={"gesture": "rub_head"}, headers=headers)
        assert r_rub.status_code == 200
        rub_data = r_rub.json()["data"]
        assert rub_data["reaction_mood"] == "happy"
        assert rub_data["haptic"] == "light"
        assert rub_data["state"]["pet_count"] >= 1
        assert rub_data["state"]["affinity"] > st["affinity"]

        r_dizzy = client.post(
            "/api/v1/mascot/interact", json={"gesture": "combo_dizzy"}, headers=headers
        )
        assert r_dizzy.status_code == 200
        assert r_dizzy.json()["data"]["reaction_mood"] == "dizzy"

        # 3. Daily mood check-in with note -> persists memory
        r_ci = client.post(
            "/api/v1/mascot/mood-checkin",
            json={"score": 2, "note": "今天和对方冷战了一下午有点委屈"},
            headers=headers,
        )
        assert r_ci.status_code == 200
        ci_data = r_ci.json()["data"]
        assert ci_data["reaction_mood"] == "comfort"
        assert ci_data["state"]["need_mood_checkin"] is False
        assert ci_data["state"]["today_mood_score"] == 2

        # 4. Mascot chat mode returns inline [[emo:...]] + [[tool:...]] and stores memory
        r_chat = client.post(
            "/api/v1/ai/chat",
            json={
                "message": "他特别慢热，今天又已读不回我，好生气想发狠话算了",
                "mascot_mode": True,
                "mascot_context": "用户停留在首页",
            },
            headers=headers,
        )
        assert r_chat.status_code == 200
        reply = r_chat.json()["data"]["reply"]
        assert "[[emo:" in reply
        assert "[[tool:" in reply

        # 5. Inspect & delete remembered episodic memory
        r_mems = client.get("/api/v1/mascot/memories", headers=headers)
        assert r_mems.status_code == 200
        mem_items = r_mems.json()["data"]["items"]
        assert len(mem_items) >= 1
        del_id = mem_items[0]["id"]
        r_del = client.delete(f"/api/v1/mascot/memories/{del_id}", headers=headers)
        assert r_del.status_code == 200

        # 6. One-click profile patch merges safely into love_profile
        r_patch = client.post(
            "/api/v1/mascot/profile-patch",
            json={"partner_traits": ["慢热型", "嘴硬心软"], "relationship_stage": "ambiguous"},
            headers=headers,
        )
        assert r_patch.status_code == 200
        prof = r_patch.json()["data"]["profile"]
        assert "慢热型" in prof["partner_traits"]
        assert prof["relationship_stage"] == "ambiguous"
