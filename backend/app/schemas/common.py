from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一接口响应结构。"""

    code: int = 0
    message: str = "ok"
    data: T | None = None


class PageData(BaseModel, Generic[T]):
    """统一分页响应结构。"""

    items: list[T]
    total: int
    page: int
    page_size: int


def ok(data: T | None = None, message: str = "ok") -> dict:
    return {"code": 0, "message": message, "data": data}
