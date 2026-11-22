from __future__ import annotations

import math
import random

import pytest

from app.services.captcha_service import (
    SliderCaptchaEngine,
    TrailPoint,
    evaluate_human_trajectory,
)
from app.services.email_validator import EmailTrustAnalyzer


def make_human_trail(target_x: float, seed: int = 42) -> tuple[list[TrailPoint], float]:
    """生成符合费茨定律（S 曲线加速-减速 + 纵向微抖动 + 非均匀采样 + 末端微调）的人类轨迹。"""
    rng = random.Random(seed)
    steps = 46
    t = 0.0
    y = 0.0
    trail: list[TrailPoint] = [TrailPoint(x=0.0, y=0.0, t=0.0)]
    for i in range(1, steps + 1):
        u = i / steps
        # 平滑 Sigmoid / cubic ease-in-out + 末端轻微过冲回拉
        s = 3 * u * u - 2 * u * u * u
        overshoot = 2.8 * math.sin((u - 0.78) * math.pi / 0.22) if u > 0.78 else 0.0
        x = target_x * s + overshoot + rng.uniform(-0.4, 0.4)
        y += rng.uniform(-0.9, 0.9)
        # 末端放慢采样间隔模拟精细对准
        dt = rng.uniform(10.0, 22.0) if u < 0.78 else rng.uniform(18.0, 42.0)
        t += dt
        trail.append(TrailPoint(x=round(x, 2), y=round(y, 2), t=round(t, 2)))
    trail[-1] = TrailPoint(x=round(target_x, 2), y=round(y, 2), t=round(t + 38.0, 2))
    return trail, trail[-1].t


@pytest.mark.asyncio
async def test_email_analyzer_allows_mainstream_and_canonicalizes():
    analyzer = EmailTrustAnalyzer()

    qq = await analyzer.analyze("123456789@qq.com", check_mx=False)
    assert qq.allowed is True
    assert qq.provider == "QQ邮箱"
    assert qq.trust_score >= 90

    netease = await analyzer.analyze("zhangsan_2026@163.com", check_mx=False)
    assert netease.allowed is True
    assert netease.provider == "网易163邮箱"

    gmail1 = await analyzer.analyze("Alice.Smith@gmail.com", check_mx=False)
    gmail2 = await analyzer.analyze("alicesmith@googlemail.com", check_mx=False)
    assert gmail1.allowed is True
    assert gmail2.allowed is True
    assert gmail1.canonical_email == gmail2.canonical_email == "alicesmith@gmail.com"


@pytest.mark.asyncio
async def test_email_analyzer_blocks_domain_disposable_typo_and_bot_emails(monkeypatch):
    analyzer = EmailTrustAnalyzer()

    # 1. 普通自定义域名邮箱
    custom = await analyzer.analyze("ceo@my-private-company.com", check_mx=False)
    assert custom.allowed is False
    assert custom.category == "custom_domain_mail"

    # 2. 企业邮自定义域名邮箱（Mock DNS MX 指纹）
    async def mock_mx_tencent(_domain: str):
        return ["mxbiz1.qq.com", "mxbiz2.qq.com"], True

    monkeypatch.setattr(analyzer, "lookup_mx_hosts", mock_mx_tencent)
    exmail = await analyzer.analyze("hr@startup-corp.cn", check_mx=True)
    assert exmail.allowed is False
    assert exmail.category == "enterprise_domain_mail"
    assert "腾讯企业域名邮箱" in exmail.provider

    # 3. 一次性临时邮箱
    disposable = await analyzer.analyze("bot99@mailinator.com", check_mx=False)
    assert disposable.allowed is False
    assert disposable.category == "disposable"

    # 4. 仿冒主流域名（编辑距离 = 1）
    typo = await analyzer.analyze("user@gmal.com", check_mx=False)
    assert typo.allowed is False
    assert typo.category == "typosquatting"
    assert "gmail.com" in typo.summary

    # 5. 子域名伪造
    sub = await analyzer.analyze("user@mail.qq.com", check_mx=False)
    assert sub.allowed is False
    assert sub.category == "subdomain_spoofing"

    # 6. '+' 别名绕过
    plus_alias = await analyzer.analyze("alice+bot1@gmail.com", check_mx=False)
    assert plus_alias.allowed is False
    assert plus_alias.category == "plus_alias_blocked"

    # 7. Punycode / 非 ASCII 同形字
    idn = await analyzer.analyze("user@xn--gmal-9qa.com", check_mx=False)
    assert idn.allowed is False
    assert idn.category == "homograph_attack"

    # 8. 无效 QQ 号段
    bad_qq = await analyzer.analyze("0001234@qq.com", check_mx=False)
    assert bad_qq.allowed is False
    assert bad_qq.category == "invalid_qq_number"

    # 9. 高信息熵机器随机批量前缀
    bot_local = await analyzer.analyze("a7k2m9p4x1z8q3r6v5w0@gmail.com", check_mx=False)
    assert bot_local.allowed is False
    assert bot_local.category == "suspicious_local_part"


def test_slider_trajectory_accepts_human_and_rejects_bots():
    target_x = 186.0

    # 1. 真实人类 S 曲线轨迹 -> 通过
    human_trail, dur = make_human_trail(target_x)
    ok_human, score_human, _, _ = evaluate_human_trajectory(target_x, dur, human_trail)
    assert ok_human is True
    assert score_human >= 70

    # 2. 匀速直线脚本 (y=0, dt=15ms) -> 拦截
    linear_trail = [
        TrailPoint(x=target_x * i / 30, y=0.0, t=float(i * 15)) for i in range(31)
    ]
    ok_bot, score_bot, _, _ = evaluate_human_trajectory(target_x, 450.0, linear_trail)
    assert ok_bot is False
    assert score_bot < 40

    # 3. 瞬移跳变脚本 -> 拦截
    jump_trail = [TrailPoint(x=0.0, y=0.0, t=0.0)]
    jump_trail.extend(TrailPoint(x=float(i), y=0.5, t=float(i * 20)) for i in range(1, 10))
    jump_trail.append(TrailPoint(x=target_x, y=0.5, t=280.0))
    ok_jump, _, _, _ = evaluate_human_trajectory(target_x, 280.0, jump_trail)
    assert ok_jump is False

    # 4. 超高速脚本 (< 200ms) -> 拦截
    fast_trail = [TrailPoint(x=target_x * i / 15, y=float(i % 2), t=float(i * 8)) for i in range(16)]
    ok_fast, _, _, _ = evaluate_human_trajectory(target_x, 120.0, fast_trail)
    assert ok_fast is False


@pytest.mark.asyncio
async def test_slider_engine_challenge_and_single_use_token():
    engine = SliderCaptchaEngine()
    challenge = await engine.create_challenge(scene="register", client_ip="127.0.0.1")
    assert challenge["bg_image"].startswith("data:image/png;base64,")
    assert challenge["piece_image"].startswith("data:image/png;base64,")
    assert "target_x" not in challenge  # 严禁向前端泄露目标坐标

    stored = await engine._get_challenge(challenge["captcha_id"])
    assert stored is not None
    target_x = float(stored["target_x"])

    # 位置错误应失败
    bad_trail, bad_dur = make_human_trail(target_x - 30.0)
    res_bad = await engine.verify_challenge(
        captcha_id=challenge["captcha_id"],
        scene="register",
        final_x=target_x - 30.0,
        duration_ms=bad_dur,
        trail=bad_trail,
    )
    assert res_bad.passed is False
    assert res_bad.captcha_token is None

    # 人类轨迹 + 对齐缺口 -> 通过并签发一次性票据
    good_trail, good_dur = make_human_trail(target_x + 1.5)
    res_ok = await engine.verify_challenge(
        captcha_id=challenge["captcha_id"],
        scene="register",
        final_x=target_x + 1.5,
        duration_ms=good_dur,
        trail=good_trail,
    )
    assert res_ok.passed is True
    assert res_ok.captcha_token is not None

    # 场景不匹配无法消费
    wrong_scene = await engine.consume_verified_token(res_ok.captcha_token, scene="login")
    assert wrong_scene is None

    # 重放攻击校验：已被消费的票据再次校验必须失败
    # 重新生成一次以测试正常消费 + 二次重放
    c2 = await engine.create_challenge(scene="login")
    s2 = await engine._get_challenge(c2["captcha_id"])
    t2, d2 = make_human_trail(float(s2["target_x"]))
    v2 = await engine.verify_challenge(c2["captcha_id"], "login", float(s2["target_x"]), d2, t2)
    assert v2.passed and v2.captcha_token
    first_use = await engine.consume_verified_token(v2.captcha_token, scene="login")
    second_use = await engine.consume_verified_token(v2.captcha_token, scene="login")
    assert first_use is not None
    assert second_use is None
