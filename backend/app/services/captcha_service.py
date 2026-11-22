from __future__ import annotations

import base64
import io
import math
import random
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageDraw, ImageFilter

from app.db.redis import cache_delete, cache_get_del_json, cache_get_json, cache_set_json

CANVAS_WIDTH = 320
CANVAS_HEIGHT = 160
PIECE_SIZE = 56
POSITION_TOLERANCE_PX = 7.0
CHALLENGE_TTL_SECONDS = 120
PASS_TOKEN_TTL_SECONDS = 180
MAX_CHALLENGE_ATTEMPTS = 3

# Redis 离线时的内存降级存储（仅本地无 Redis 调试/单元测试使用）
_fallback_challenges: dict[str, tuple[float, dict[str, Any]]] = {}
_fallback_tokens: dict[str, tuple[float, dict[str, Any]]] = {}


@dataclass
class TrailPoint:
    x: float
    y: float
    t: float  # 相对按下的毫秒时间戳


@dataclass
class CaptchaVerifyResult:
    passed: bool
    human_score: int
    captcha_token: str | None = None
    reason: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


def _prune_fallback(store: dict[str, tuple[float, dict[str, Any]]]) -> None:
    now = time.time()
    expired = [k for k, (exp, _) in store.items() if exp <= now]
    for k in expired:
        store.pop(k, None)


def _build_jigsaw_mask(size: int = PIECE_SIZE) -> Image.Image:
    """构建带右侧凸耳、顶部凸耳与左侧凹槽的 56x56 抗锯齿拼图 Alpha 蒙版。"""
    scale = 2
    s = size * scale
    mask = Image.new("L", (s, s), 0)
    draw = ImageDraw.Draw(mask)

    # 主体方框: [6..46, 12..52] (40x40)
    x0, y0, x1, y1 = 6 * scale, 12 * scale, 46 * scale, 52 * scale
    draw.rounded_rectangle((x0, y0, x1, y1), radius=4 * scale, fill=255)

    # 顶部凸起圆耳
    r_out = 7 * scale
    cx_top, cy_top = 26 * scale, 12 * scale
    draw.ellipse((cx_top - r_out, cy_top - r_out, cx_top + r_out, cy_top + r_out), fill=255)

    # 右侧凸起圆耳
    cx_right, cy_right = 46 * scale, 32 * scale
    draw.ellipse(
        (cx_right - r_out, cy_right - r_out, cx_right + r_out, cy_right + r_out), fill=255
    )

    # 左侧向内凹槽
    r_in = 6 * scale
    cx_left, cy_left = 6 * scale, 32 * scale
    draw.ellipse((cx_left - r_in, cy_left - r_in, cx_left + r_in, cy_left + r_in), fill=0)

    return mask.resize((size, size), Image.Resampling.LANCZOS)


def _generate_procedural_background(rng: random.Random) -> Image.Image:
    """生成动态高纹理渐变 + 几何曲线背景图，防止模板匹配攻击。"""
    palettes = [
        ((38, 56, 128), (118, 75, 162), (242, 168, 134)),
        ((15, 76, 117), (50, 130, 184), (187, 225, 250)),
        ((24, 90, 157), (67, 206, 162), (253, 226, 147)),
        ((72, 49, 132), (179, 84, 166), (244, 194, 159)),
        ((30, 60, 114), (42, 82, 152), (116, 235, 213)),
        ((60, 42, 108), (105, 86, 229), (249, 168, 212)),
    ]
    c1, c2, c3 = rng.choice(palettes)

    # 先在小画布生成平滑双线性渐变再放大，速度极快
    small = Image.new("RGB", (64, 32))
    px = small.load()
    for y in range(32):
        ty = y / 31.0
        for x in range(64):
            tx = x / 63.0
            r = int(c1[0] * (1 - tx) * (1 - ty) + c2[0] * tx + c3[0] * ty * 0.55)
            g = int(c1[1] * (1 - tx) * (1 - ty) + c2[1] * tx + c3[1] * ty * 0.55)
            b = int(c1[2] * (1 - tx) * (1 - ty) + c2[2] * tx + c3[2] * ty * 0.55)
            px[x, y] = (min(255, r), min(255, g), min(255, b))

    img = small.resize((CANVAS_WIDTH, CANVAS_HEIGHT), Image.Resampling.BICUBIC).convert("RGBA")
    overlay = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # 随机柔和几何装饰（提升拼图纹理辨识度，同时干扰简单边缘提取脚本）
    for _ in range(14):
        cx = rng.randint(-20, CANVAS_WIDTH + 20)
        cy = rng.randint(-20, CANVAS_HEIGHT + 20)
        rad = rng.randint(14, 54)
        col = (
            rng.randint(140, 255),
            rng.randint(140, 255),
            rng.randint(160, 255),
            rng.randint(35, 95),
        )
        draw.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), fill=col)

    for _ in range(6):
        pts = [
            (rng.randint(0, CANVAS_WIDTH), rng.randint(0, CANVAS_HEIGHT))
            for _ in range(3)
        ]
        col = (
            rng.randint(180, 255),
            rng.randint(180, 255),
            rng.randint(180, 255),
            rng.randint(30, 75),
        )
        draw.polygon(pts, fill=col)

    # 细波浪线条增加纹理复杂度
    for _ in range(4):
        base_y = rng.randint(20, CANVAS_HEIGHT - 20)
        amp = rng.uniform(6, 18)
        freq = rng.uniform(0.025, 0.06)
        phase = rng.uniform(0, math.tau)
        line_pts = [
            (x, base_y + amp * math.sin(x * freq + phase))
            for x in range(0, CANVAS_WIDTH + 1, 8)
        ]
        draw.line(line_pts, fill=(255, 255, 255, rng.randint(55, 110)), width=2)

    combined = Image.alpha_composite(img, overlay)
    return combined


def _render_puzzle_images(target_x: int, target_y: int) -> tuple[str, str]:
    """渲染背景图（含主缺口 + 弱干扰诱饵缺口）与带高光描边的透明拼图滑块 PNG。"""
    rng = random.SystemRandom()
    bg = _generate_procedural_background(rng)
    mask = _build_jigsaw_mask(PIECE_SIZE)

    # 1. 裁剪滑块并加柔和白边高光
    crop = bg.crop((target_x, target_y, target_x + PIECE_SIZE, target_y + PIECE_SIZE))
    piece = Image.new("RGBA", (PIECE_SIZE, PIECE_SIZE), (0, 0, 0, 0))
    piece.paste(crop, (0, 0), mask)

    # 边缘轮廓高光（利用膨胀与原蒙版差分）
    edge = mask.filter(ImageFilter.FIND_EDGES)
    border_layer = Image.new("RGBA", (PIECE_SIZE, PIECE_SIZE), (255, 255, 255, 230))
    piece.paste(border_layer, (0, 0), edge)

    # 2. 在背景图上绘制一个弱干扰诱饵缺口（对抗简单亮度阈值脚本）
    decoy_candidates = [
        x for x in range(60, CANVAS_WIDTH - PIECE_SIZE - 10, 12) if abs(x - target_x) >= 68
    ]
    if decoy_candidates:
        decoy_x = rng.choice(decoy_candidates)
        decoy_fill = Image.new("RGBA", (PIECE_SIZE, PIECE_SIZE), (20, 24, 48, 68))
        bg.paste(decoy_fill, (decoy_x, target_y), mask)

    # 3. 在真实目标位置绘制深色凹陷缺口与淡描边
    hole_fill = Image.new("RGBA", (PIECE_SIZE, PIECE_SIZE), (12, 16, 36, 165))
    bg.paste(hole_fill, (target_x, target_y), mask)
    hole_rim = Image.new("RGBA", (PIECE_SIZE, PIECE_SIZE), (255, 255, 255, 150))
    bg.paste(hole_rim, (target_x, target_y), edge)

    bg_buf = io.BytesIO()
    bg.convert("RGB").save(bg_buf, format="PNG", optimize=True)
    bg_b64 = "data:image/png;base64," + base64.b64encode(bg_buf.getvalue()).decode("ascii")

    piece_buf = io.BytesIO()
    piece.save(piece_buf, format="PNG", optimize=True)
    piece_b64 = "data:image/png;base64," + base64.b64encode(piece_buf.getvalue()).decode("ascii")
    return bg_b64, piece_b64


def evaluate_human_trajectory(
    final_x: float,
    duration_ms: float,
    trail: list[TrailPoint],
) -> tuple[bool, int, str, dict[str, Any]]:
    """
    7 维行为生物特征反机器人滑动轨迹评分算法：
    F1. 轨迹点密度与瞬移跳变检测 (Teleportation)
    F2. 操作耗时合理性 (Duration Plausibility)
    F3. 水平速度变异系数 (Velocity Coefficient of Variation)
    F4. 费茨定律末端减速曲线 (Fitts's Law Deceleration)
    F5. 纵向微抖动特征 (Vertical Y-Axis Micro-Tremor)
    F6. 采样时间间隔抖动 (Delta-T Timing Jitter)
    F7. 非线性 S 曲线拟合残差 (Linearity Deviation RMSE)
    """
    n = len(trail)
    metrics: dict[str, Any] = {
        "point_count": n,
        "duration_ms": round(duration_ms, 1),
    }

    # --- 硬拦截：明显自动化脚本/伪造数据包 ---
    if n < 10:
        return False, 5, "滑动轨迹采样点过少，疑似脚本操作，请重新拖动", metrics

    if duration_ms < 200:
        return False, 5, "滑动速度超出人类正常范围，请自然拖动滑块", metrics

    if duration_ms > 20000:
        return False, 15, "滑动耗时过长，请重新验证", metrics

    xs = [p.x for p in trail]
    ys = [p.y for p in trail]
    ts = [p.t for p in trail]

    if abs(xs[0]) > 20:
        return False, 10, "轨迹起点异常，请重新拖动", metrics

    if abs(xs[-1] - final_x) > 10:
        return False, 10, "轨迹终点与提交位置不一致，请重新验证", metrics

    # 检测单步瞬移跳变（例如直接 jump 到目标位置）
    dxs = [xs[i] - xs[i - 1] for i in range(1, n)]
    dts = [max(0.5, ts[i] - ts[i - 1]) for i in range(1, n)]
    max_step = max((abs(dx) for dx in dxs), default=0.0)
    total_dist = max(abs(final_x), 1.0)
    metrics["max_step_ratio"] = round(max_step / total_dist, 3)

    if max_step > max(0.55 * total_dist, 75.0):
        return False, 10, "检测到异常瞬间跳变轨迹，疑似自动化脚本", metrics

    # --- 连续特征提取 ---
    # 1. 瞬时水平速度 (px/ms)
    speeds = [abs(dx) / dt for dx, dt in zip(dxs, dts, strict=False)]
    mean_v = sum(speeds) / len(speeds) if speeds else 0.0
    var_v = sum((v - mean_v) ** 2 for v in speeds) / len(speeds) if speeds else 0.0
    std_v = math.sqrt(var_v)
    cv_v = (std_v / mean_v) if mean_v > 1e-6 else 0.0
    metrics["velocity_cv"] = round(cv_v, 3)

    # 2. Fitts's Law 末端减速比：比较中段速度与末尾 25% 速度
    mid_start, mid_end = max(1, int(len(speeds) * 0.2)), max(2, int(len(speeds) * 0.65))
    tail_start = max(1, int(len(speeds) * 0.75))
    mid_speeds = speeds[mid_start:mid_end] or speeds
    tail_speeds = speeds[tail_start:] or speeds
    mid_v = sum(mid_speeds) / len(mid_speeds)
    tail_v = sum(tail_speeds) / len(tail_speeds)
    decel_ratio = (tail_v / mid_v) if mid_v > 1e-6 else 1.0
    metrics["tail_decel_ratio"] = round(decel_ratio, 3)

    # 3. 纵向 Y 轴微抖动特征
    mean_y = sum(ys) / n
    y_std = math.sqrt(sum((y - mean_y) ** 2 for y in ys) / n)
    unique_y = len({round(y, 1) for y in ys})
    metrics["y_std"] = round(y_std, 3)
    metrics["unique_y"] = unique_y

    # 4. 采样时间间隔抖动 (ms)
    mean_dt = sum(dts) / len(dts)
    dt_std = math.sqrt(sum((dt - mean_dt) ** 2 for dt in dts) / len(dts))
    metrics["dt_std_ms"] = round(dt_std, 3)

    # 5. 直线拟合归一化残差（人类加速-减速呈 S 曲线，匀速线性脚本 RMSE 接近 0）
    t0, t_end = ts[0], ts[-1]
    t_span = max(t_end - t0, 1.0)
    sq_errs = []
    for x_val, t_val in zip(xs, ts, strict=False):
        linear_x = xs[0] + (xs[-1] - xs[0]) * ((t_val - t0) / t_span)
        sq_errs.append((x_val - linear_x) ** 2)
    rmse_norm = math.sqrt(sum(sq_errs) / n) / total_dist
    metrics["linearity_rmse"] = round(rmse_norm, 4)

    # 6. 末端是否存在微调回拉或短暂停顿对准
    has_overshoot_correction = any(dx < -0.5 for dx in dxs[tail_start:])
    has_tail_dwell = (ts[-1] - ts[-2] >= 25.0) or (tail_v < 0.08)
    metrics["micro_alignment"] = bool(has_overshoot_correction or has_tail_dwell)

    # --- 三重经典脚本特征同时命中直接硬拦截 ---
    if cv_v < 0.16 and y_std < 0.05 and rmse_norm < 0.02:
        return False, 8, "检测到匀速直线自动化脚本轨迹，验证拦截", metrics

    # --- 加权人机评分模型 (初始 100 分，按异常特征扣分) ---
    score = 100
    penalties: list[str] = []

    if duration_ms < 280:
        score -= 25
        penalties.append("耗时偏快")
    elif duration_ms > 10000:
        score -= 12
        penalties.append("耗时偏长")

    if cv_v < 0.18:
        score -= 35
        penalties.append("速度过于恒定")
    elif cv_v < 0.28:
        score -= 15
        penalties.append("速度变化偏小")

    if decel_ratio > 1.15:
        score -= 20
        penalties.append("缺少末端减速对准特征")

    if n >= 15 and y_std < 0.01:
        score -= 25
        penalties.append("纵向零抖动")
    elif unique_y <= 1:
        score -= 18
        penalties.append("纵向轨迹单一")

    if dt_std < 0.45:
        score -= 22
        penalties.append("时间采样过于均匀")

    if rmse_norm < 0.018:
        score -= 25
        penalties.append("轨迹过于呈严格直线")
    elif rmse_norm < 0.03:
        score -= 10
        penalties.append("轨迹线性度偏高")

    if has_overshoot_correction or has_tail_dwell:
        score += 6

    score = max(0, min(100, score))
    metrics["penalties"] = penalties

    if score >= 60:
        return True, score, "滑动验证通过", metrics

    reason = f"行为轨迹异常（评分 {score}），疑似机器操作，请自然拖动滑块重试"
    return False, score, reason, metrics


class SliderCaptchaEngine:
    """动态拼图生成 + 7 维轨迹反机器人校验 + 一次性票据签发服务。"""

    def _challenge_key(self, captcha_id: str) -> str:
        return f"ailove:captcha:challenge:{captcha_id}"

    def _pass_token_key(self, token: str) -> str:
        return f"ailove:captcha:pass:{token}"

    async def _save_challenge(self, captcha_id: str, payload: dict[str, Any]) -> None:
        stored = await cache_set_json(
            self._challenge_key(captcha_id),
            payload,
            ttl_seconds=CHALLENGE_TTL_SECONDS,
        )
        if not stored:
            _prune_fallback(_fallback_challenges)
            _fallback_challenges[captcha_id] = (time.time() + CHALLENGE_TTL_SECONDS, payload)

    async def _get_challenge(self, captcha_id: str) -> dict[str, Any] | None:
        data = await cache_get_json(self._challenge_key(captcha_id))
        if isinstance(data, dict):
            return data
        _prune_fallback(_fallback_challenges)
        item = _fallback_challenges.get(captcha_id)
        return item[1] if item else None

    async def _delete_challenge(self, captcha_id: str) -> None:
        _fallback_challenges.pop(captcha_id, None)
        await cache_delete(self._challenge_key(captcha_id))

    async def _save_pass_token(self, token: str, payload: dict[str, Any]) -> None:
        stored = await cache_set_json(
            self._pass_token_key(token),
            payload,
            ttl_seconds=PASS_TOKEN_TTL_SECONDS,
        )
        if not stored:
            _prune_fallback(_fallback_tokens)
            _fallback_tokens[token] = (time.time() + PASS_TOKEN_TTL_SECONDS, payload)

    async def consume_verified_token(self, captcha_token: str, scene: str) -> dict[str, Any] | None:
        """原子消费一次性滑动验证票据，校验场景匹配且防止重放攻击。"""
        if not captcha_token:
            return None

        data = await cache_get_del_json(self._pass_token_key(captcha_token))
        if data is None:
            _prune_fallback(_fallback_tokens)
            item = _fallback_tokens.pop(captcha_token, None)
            data = item[1] if item else None

        if not isinstance(data, dict):
            return None
        if data.get("scene") != scene:
            return None
        return data

    async def create_challenge(self, scene: str, client_ip: str = "") -> dict[str, Any]:
        """生成动态拼图挑战，目标 X 坐标仅保存在服务端 Redis 中。"""
        captcha_id = secrets.token_urlsafe(24)
        target_x = secrets.randbelow(156) + 100  # [100, 255]
        target_y = secrets.randbelow(68) + 22  # [22, 89]

        bg_image, piece_image = _render_puzzle_images(target_x, target_y)

        challenge = {
            "target_x": target_x,
            "target_y": target_y,
            "scene": scene,
            "ip": client_ip,
            "created_at": time.time(),
            "attempts": 0,
        }
        await self._save_challenge(captcha_id, challenge)

        return {
            "captcha_id": captcha_id,
            "scene": scene,
            "bg_image": bg_image,
            "piece_image": piece_image,
            "piece_y": target_y,
            "canvas_width": CANVAS_WIDTH,
            "canvas_height": CANVAS_HEIGHT,
            "piece_size": PIECE_SIZE,
            "expires_in": CHALLENGE_TTL_SECONDS,
        }

    async def verify_challenge(
        self,
        captcha_id: str,
        scene: str,
        final_x: float,
        duration_ms: float,
        trail: list[TrailPoint],
        client_ip: str = "",
    ) -> CaptchaVerifyResult:
        """校验拼图对齐精度 + 7 维行为轨迹算法，通过后签发一次性 captcha_token。"""
        challenge = await self._get_challenge(captcha_id)
        if challenge is None:
            return CaptchaVerifyResult(
                passed=False,
                human_score=0,
                reason="滑动验证码已过期或不存在，请刷新重试",
            )

        if challenge.get("scene") != scene:
            return CaptchaVerifyResult(
                passed=False,
                human_score=0,
                reason="验证码业务场景不匹配，请刷新重试",
            )

        attempts = int(challenge.get("attempts", 0))
        if attempts >= MAX_CHALLENGE_ATTEMPTS:
            await self._delete_challenge(captcha_id)
            return CaptchaVerifyResult(
                passed=False,
                human_score=0,
                reason="失败次数过多，请刷新新的拼图验证码",
            )

        target_x = float(challenge["target_x"])
        offset_err = abs(final_x - target_x)

        if offset_err > POSITION_TOLERANCE_PX:
            challenge["attempts"] = attempts + 1
            if challenge["attempts"] >= MAX_CHALLENGE_ATTEMPTS:
                await self._delete_challenge(captcha_id)
            else:
                await self._save_challenge(captcha_id, challenge)
            return CaptchaVerifyResult(
                passed=False,
                human_score=0,
                reason="拼图未对齐，请拖动滑块对齐缺口",
                metrics={"position_ok": False, "attempts": challenge["attempts"]},
            )

        human_ok, score, reason, metrics = evaluate_human_trajectory(
            final_x=final_x,
            duration_ms=duration_ms,
            trail=trail,
        )
        metrics["position_ok"] = True

        if not human_ok:
            challenge["attempts"] = attempts + 1
            if challenge["attempts"] >= MAX_CHALLENGE_ATTEMPTS:
                await self._delete_challenge(captcha_id)
            else:
                await self._save_challenge(captcha_id, challenge)
            return CaptchaVerifyResult(
                passed=False,
                human_score=score,
                reason=reason,
                metrics=metrics,
            )

        # 验证通过：立即销毁拼图挑战并签发一次性验证票据
        await self._delete_challenge(captcha_id)
        pass_token = secrets.token_urlsafe(32)
        await self._save_pass_token(
            pass_token,
            {
                "scene": scene,
                "ip": client_ip,
                "human_score": score,
                "verified_at": time.time(),
            },
        )
        return CaptchaVerifyResult(
            passed=True,
            human_score=score,
            captcha_token=pass_token,
            reason="人机校验通过",
            metrics=metrics,
        )


slider_captcha_engine = SliderCaptchaEngine()
