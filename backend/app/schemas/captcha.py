from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SliderCreateRequest(BaseModel):
    scene: Literal["login", "register", "reset_password"] = Field(
        default="login", description="验证码使用场景：login / register / reset_password"
    )


class TrailPointSchema(BaseModel):
    x: float = Field(..., description="滑块水平偏移像素")
    y: float = Field(..., description="指针相对纵坐标像素")
    t: float = Field(..., ge=0, description="相对按下的毫秒时间")


class SliderVerifyRequest(BaseModel):
    captcha_id: str = Field(..., min_length=8, max_length=128, description="拼图挑战ID")
    scene: Literal["login", "register", "reset_password"] = Field(
        default="login", description="业务场景"
    )
    final_x: float = Field(..., ge=0, le=400, description="最终滑块停靠的水平像素位置")
    duration_ms: float = Field(..., ge=0, le=60000, description="滑动总耗时(毫秒)")
    trail: list[TrailPointSchema] = Field(..., max_length=2000, description="拖动轨迹采样点")
