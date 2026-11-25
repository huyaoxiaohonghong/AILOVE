from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import status
from sqlalchemy import delete, desc, func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import BusinessException
from app.db.mysql import get_session_factory
from app.models.favorite_reply import FavoriteReply
from app.services.llm_service import build_owner_scope

logger = logging.getLogger(__name__)

_MAX_FAVORITES_PER_USER = 200
_mem_favorites: dict[str, list[dict[str, Any]]] = {}
_mem_seq = 1


def _row_to_dict(row: FavoriteReply) -> dict[str, Any]:
    return {
        "id": row.id,
        "category": row.category,
        "scene_label": row.scene_label or "",
        "content": row.content,
        "note": row.note or "",
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


async def list_favorites(
    user_type: str,
    user_id: int,
    *,
    category: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    owner = build_owner_scope(user_type, user_id)
    clean_cat = (category or "").strip()
    try:
        factory = get_session_factory()
        async with factory() as session:
            stmt = select(FavoriteReply).where(FavoriteReply.owner_scope == owner)
            if clean_cat and clean_cat != "all":
                stmt = stmt.where(FavoriteReply.category == clean_cat)
            stmt = stmt.order_by(desc(FavoriteReply.id)).limit(max(1, min(limit, 200)))
            rows = (await session.execute(stmt)).scalars().all()
            return [_row_to_dict(r) for r in rows]
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("Favorite list fallback to mem: %s", exc)
        items = list(_mem_favorites.get(owner, []))
        if clean_cat and clean_cat != "all":
            items = [i for i in items if i["category"] == clean_cat]
        items.sort(key=lambda i: int(i["id"]), reverse=True)
        return items[:limit]


async def create_favorite(
    user_type: str,
    user_id: int,
    *,
    content: str,
    category: str = "reply_helper",
    scene_label: str = "",
    note: str = "",
) -> tuple[dict[str, Any], bool]:
    """收藏话术（若同内容已收藏则返回已有记录并标记 deduplicated=True）。"""
    global _mem_seq
    owner = build_owner_scope(user_type, user_id)
    clean_content = content.strip()[:1200]
    if not clean_content:
        raise BusinessException("收藏的话术内容不能为空", code=40066)
    clean_cat = (category or "reply_helper").strip()[:32]
    clean_scene = (scene_label or "").strip()[:64]
    clean_note = (note or "").strip()[:255]

    try:
        factory = get_session_factory()
        async with factory() as session:
            existing = (
                await session.execute(
                    select(FavoriteReply).where(
                        FavoriteReply.owner_scope == owner,
                        FavoriteReply.content == clean_content,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return _row_to_dict(existing), True

            total = (
                await session.execute(
                    select(func.count(FavoriteReply.id)).where(FavoriteReply.owner_scope == owner)
                )
            ).scalar_one()
            if int(total or 0) >= _MAX_FAVORITES_PER_USER:
                raise BusinessException(
                    f"话术收藏夹已达上限（{_MAX_FAVORITES_PER_USER} 条），请先清理旧收藏",
                    code=40067,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            row = FavoriteReply(
                owner_scope=owner,
                user_type=(user_type or "web")[:16],
                user_id=int(user_id or 0),
                category=clean_cat,
                scene_label=clean_scene,
                content=clean_content,
                note=clean_note,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _row_to_dict(row), False
    except BusinessException:
        raise
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("Favorite create fallback to mem: %s", exc)
        bucket = _mem_favorites.setdefault(owner, [])
        for item in bucket:
            if item["content"] == clean_content:
                return dict(item), True
        if len(bucket) >= _MAX_FAVORITES_PER_USER:
            raise BusinessException(
                f"话术收藏夹已达上限（{_MAX_FAVORITES_PER_USER} 条），请先清理旧收藏",
                code=40067,
                status_code=status.HTTP_400_BAD_REQUEST,
            ) from exc
        rec = {
            "id": _mem_seq,
            "category": clean_cat,
            "scene_label": clean_scene,
            "content": clean_content,
            "note": clean_note,
            "created_at": datetime.now(UTC).isoformat(),
        }
        _mem_seq += 1
        bucket.append(rec)
        return dict(rec), False


async def delete_favorite(user_type: str, user_id: int, favorite_id: int) -> bool:
    owner = build_owner_scope(user_type, user_id)
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    select(FavoriteReply).where(
                        FavoriteReply.id == favorite_id,
                        FavoriteReply.owner_scope == owner,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True
    except (SQLAlchemyError, OSError):
        bucket = _mem_favorites.get(owner, [])
        before = len(bucket)
        _mem_favorites[owner] = [i for i in bucket if int(i["id"]) != int(favorite_id)]
        return len(_mem_favorites[owner]) < before


async def delete_all_favorites(user_type: str, user_id: int) -> int:
    owner = build_owner_scope(user_type, user_id)
    try:
        factory = get_session_factory()
        async with factory() as session:
            res = await session.execute(
                delete(FavoriteReply).where(FavoriteReply.owner_scope == owner)
            )
            await session.commit()
            return int(res.rowcount or 0)
    except (SQLAlchemyError, OSError):
        removed = len(_mem_favorites.pop(owner, []))
        return removed
