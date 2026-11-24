from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.network import extract_client_ip
from app.core.rate_limit import rate_limit
from app.schemas.captcha import SliderCreateRequest, SliderVerifyRequest
from app.schemas.common import ok
from app.services.captcha_service import TrailPoint, slider_captcha_engine

router = APIRouter(prefix="/captcha", tags=["风控-防机器人滑动验证"])


def _client_ip(request: Request) -> str:
    return extract_client_ip(request, default="")


@router.post(
    "/slider/create",
    summary="生成动态拼图滑动验证码",
    dependencies=[Depends(rate_limit("captcha_create", limit=60, window_seconds=60))],
)
async def create_slider_captcha(req: SliderCreateRequest, request: Request):
    challenge = await slider_captcha_engine.create_challenge(
        scene=req.scene,
        client_ip=_client_ip(request),
    )
    return ok(challenge)


@router.post(
    "/slider/verify",
    summary="校验滑动位置与行为轨迹，通过后返回一次性票据",
    dependencies=[Depends(rate_limit("captcha_verify", limit=60, window_seconds=60))],
)
async def verify_slider_captcha(req: SliderVerifyRequest, request: Request):
    trail = [TrailPoint(x=pt.x, y=pt.y, t=pt.t) for pt in req.trail]
    result = await slider_captcha_engine.verify_challenge(
        captcha_id=req.captcha_id,
        scene=req.scene,
        final_x=req.final_x,
        duration_ms=req.duration_ms,
        trail=trail,
        client_ip=_client_ip(request),
    )
    return ok(
        {
            "passed": result.passed,
            "human_score": result.human_score,
            "captcha_token": result.captcha_token,
            "reason": result.reason,
            "metrics": result.metrics,
        },
        message=result.reason,
    )
