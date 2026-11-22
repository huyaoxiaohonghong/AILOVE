from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_current_admin
from app.core.exceptions import BusinessException
from app.db.mysql import get_session_factory
from app.models.wechat_user import WechatUser
from app.schemas.common import ok
from app.schemas.user import WechatUserItem, WechatUserStatusUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/users", tags=["管理端-小程序用户"])


@router.get("", summary="分页查询小程序用户列表")
async def list_wechat_users(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=10, ge=1, le=100, description="每页数量"),
    keyword: str | None = Query(default=None, description="昵称/OpenID/手机号搜索"),
    user_status: int | None = Query(default=None, alias="status", ge=0, le=1),
    _current_admin: dict[str, Any] = Depends(get_current_admin),
):
    try:
        factory = get_session_factory()
        async with factory() as session:
            stmt = select(WechatUser)
            count_stmt = select(func.count(WechatUser.id))

            if keyword:
                like_pattern = f"%{keyword.strip()}%"
                cond = or_(
                    WechatUser.nickname.like(like_pattern),
                    WechatUser.openid.like(like_pattern),
                    WechatUser.phone.like(like_pattern),
                )
                stmt = stmt.where(cond)
                count_stmt = count_stmt.where(cond)

            if user_status is not None:
                stmt = stmt.where(WechatUser.status == user_status)
                count_stmt = count_stmt.where(WechatUser.status == user_status)

            total = await session.scalar(count_stmt) or 0
            stmt = stmt.order_by(WechatUser.id.desc()).offset((page - 1) * page_size).limit(page_size)
            rows = (await session.execute(stmt)).scalars().all()

            items = [
                WechatUserItem(
                    id=row.id,
                    openid=row.openid,
                    nickname=row.nickname,
                    avatar_url=row.avatar_url,
                    phone=row.phone,
                    status=row.status,
                    last_login_at=row.last_login_at,
                    created_at=row.created_at,
                ).model_dump(mode="json")
                for row in rows
            ]
            return ok(
                {
                    "items": items,
                    "total": total,
                    "page": page,
                    "page_size": page_size,
                    "db_connected": True,
                }
            )
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("List wechat users failed (MySQL unavailable): %s", exc)
        return ok(
            {
                "items": [],
                "total": 0,
                "page": page,
                "page_size": page_size,
                "db_connected": False,
            },
            message="MySQL 暂未连接，当前返回空列表",
        )


@router.patch("/{user_id}/status", summary="更新小程序用户启用/禁用状态")
async def update_wechat_user_status(
    user_id: int,
    body: WechatUserStatusUpdate,
    _current_admin: dict[str, Any] = Depends(get_current_admin),
):
    try:
        factory = get_session_factory()
        async with factory() as session:
            user = await session.get(WechatUser, user_id)
            if user is None:
                raise BusinessException(
                    "目标用户不存在",
                    code=40401,
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            user.status = body.status
            await session.commit()
            return ok({"id": user.id, "status": user.status}, message="状态更新成功")
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        raise BusinessException(
            "数据库暂不可用，无法更新用户状态",
            code=50301,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
