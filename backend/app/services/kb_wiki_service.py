from __future__ import annotations

import hashlib
import io
import json
import logging
import posixpath
import re
import zipfile
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import yaml
from fastapi import status
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import delete, desc, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import BusinessException
from app.core.permissions import has_permission
from app.db.mysql import get_session_factory
from app.models.knowledge_base import KBRawSource, KBSkill, KBWikiBase, KBWikiPage
from app.services.ai_config_service import resolve_runtime_config
from app.services.ai_providers import get_provider_adapter
from app.services.kb_file_parser import (
    BundleFileEntry,
    classify_bundle_files,
    extract_wikilinks,
    parse_bundle_zip,
    parse_skill_md_frontmatter,
    slugify_text,
)
from app.services.rbac_service import get_role_meta

logger = logging.getLogger(__name__)
_BEIJING_TZ = timezone(timedelta(hours=8))

# 内存降级存储（无 MySQL 的单测或离线开发环境下保持全功能一致）
_mem_kbs: dict[int, dict[str, Any]] = {}
_mem_sources: dict[int, dict[str, Any]] = {}
_mem_pages: dict[int, dict[str, Any]] = {}
_mem_skills: dict[int, dict[str, Any]] = {}
_mem_seq = {"kb": 1, "source": 1, "page": 1, "skill": 1}

_STOPWORDS = frozenset(
    {
        "怎么",
        "什么",
        "如何",
        "为什么",
        "可以",
        "请问",
        "一下",
        "关于",
        "我们",
        "你们",
        "这个",
        "那个",
        "一个",
        "没有",
        "需要",
        "进行",
        "如果",
        "以及",
        "但是",
        "因为",
        "所以",
        "知识库",
        "skill",
        "wiki",
        "the",
        "and",
        "for",
        "with",
        "that",
        "this",
        "what",
        "how",
    }
)
_SKILL_CMD_RE = re.compile(r"/skill:([a-zA-Z0-9_-]{2,64})")


def _now_utc_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _now_bj_str() -> str:
    return datetime.now(_BEIJING_TZ).strftime("%Y-%m-%d %H:%M")


def _safe_json_loads(raw: str, default: Any) -> Any:
    try:
        parsed = json.loads(raw or "")
        return parsed if parsed is not None else default
    except (json.JSONDecodeError, TypeError):
        return default


def _kb_row_to_dict(row: KBWikiBase) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "slug": row.slug,
        "name": row.name,
        "description": row.description or "",
        "category": row.category or "general",
        "owner_scope": row.owner_scope,
        "visibility": row.visibility or "private",
        "schema_md": row.schema_md or "",
        "index_md": row.index_md or "",
        "log_md": row.log_md or "",
        "source_count": int(row.source_count or 0),
        "page_count": int(row.page_count or 0),
        "last_lint_score": row.last_lint_score,
        "last_lint_report": _safe_json_loads(row.last_lint_json, None),
        "last_compiled_at": row.last_compiled_at.isoformat() if row.last_compiled_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _source_row_to_dict(row: KBRawSource, *, include_text: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": int(row.id),
        "kb_id": int(row.kb_id),
        "filename": row.filename,
        "rel_path": row.rel_path or row.filename,
        "mime_type": row.mime_type or "text/plain",
        "file_size": int(row.file_size or 0),
        "content_sha256": row.content_sha256,
        "char_count": len(row.raw_text or ""),
        "ingest_status": row.ingest_status or "pending",
        "ingest_error": row.ingest_error or "",
        "ingested_at": row.ingested_at.isoformat() if row.ingested_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
    if include_text:
        data["raw_text"] = row.raw_text or ""
    return data


def _page_row_to_dict(row: KBWikiPage, *, include_content: bool = True) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": int(row.id),
        "kb_id": int(row.kb_id),
        "page_path": row.page_path,
        "slug": row.slug,
        "title": row.title,
        "page_type": row.page_type or "concept",
        "summary": row.summary or "",
        "links": _safe_json_loads(row.links_json, []),
        "source_ids": _safe_json_loads(row.source_ids_json, []),
        "version": int(row.version or 1),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if include_content:
        data["content_md"] = row.content_md or ""
    return data


def _skill_row_to_dict(row: KBSkill, *, kb_name: str = "") -> dict[str, Any]:
    return {
        "id": int(row.id),
        "kb_id": int(row.kb_id),
        "kb_name": kb_name,
        "slug": row.slug,
        "name": row.name,
        "description": row.description or "",
        "triggers": _safe_json_loads(row.triggers_json, []),
        "skill_md": row.skill_md or "",
        "version": row.version or "1.0.0",
        "owner_scope": row.owner_scope,
        "visibility": row.visibility or "private",
        "is_enabled": bool(row.is_enabled),
        "usage_count": int(row.usage_count or 0),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def build_default_schema_md(name: str, description: str = "") -> str:
    return (
        f"# {name} · LLM Wiki Schema\n\n"
        f"> 领域说明：{description or '基于 LLM Wiki 架构增量编排的个人与团队知识库'}\n\n"
        "## 1. 三层目录约定\n"
        "- `raw/`：不可变原始资料层（Markdown / PDF / DOCX / TXT 等），AI 仅读取与引用，绝不改写。\n"
        "- `wiki/`：LLM 编译维护的互链知识层，按 `summaries/`、`concepts/`、`entities/`、`insights/` 组织。\n"
        "- `index.md`：全库知识地图与每页一句话摘要（检索时优先浏览此目录）。\n"
        "- `log.md`：只增不删的时间线操作日志（ingest / query-insight / lint / publish-skill）。\n\n"
        "## 2. 编译与引用规范\n"
        "- 每个词条使用 `[[词条标题]]` 或 `[[slug]]` 建立双向概念互链。\n"
        "- 回答用户问题时，优先沿 `index.md` → 命中词条 → 1 跳 `[[wikilinks]]` 收集证据，"
        "并用 `[词条标题]` 标注来源。\n"
        "- 若知识库未覆盖某个细节，如实说明缺失范围，严禁编造。\n"
    )


def build_index_md(kb_name: str, pages: list[dict[str, Any]]) -> str:
    sections: dict[str, tuple[str, list[dict[str, Any]]]] = {
        "overview": ("总览导航 (Overview)", []),
        "summary": ("原始资料精要 (Summaries)", []),
        "concept": ("核心概念与方法 (Concepts)", []),
        "entity": ("人物与实体档案 (Entities)", []),
        "insight": ("问答沉淀洞察 (Insights)", []),
    }
    for p in pages:
        ptype = str(p.get("page_type") or "concept")
        if ptype not in sections:
            ptype = "concept"
        sections[ptype][1].append(p)

    lines = [
        f"# {kb_name} · 知识索引 (index.md)",
        "",
        f"> 更新时间：{_now_bj_str()} (北京时间) · 共 {len(pages)} 篇 Wiki 词条",
        "",
    ]
    for _, (label, items) in sections.items():
        if not items:
            continue
        lines.append(f"## {label}")
        for item in sorted(items, key=lambda x: str(x.get("title") or "")):
            summary = str(item.get("summary") or "").strip() or "暂无摘要"
            lines.append(f"- [[{item['title']}]] (`{item['page_path']}`) — {summary}")
        lines.append("")
    if len(pages) == 0:
        lines.append("- （暂无词条，请先上传 `raw/` 原始资料并点击编译入库）")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _append_log(current_log: str, op: str, detail: str) -> str:
    header = ""
    if not current_log.strip():
        header = "# LLM Wiki Operation Log\n\n"
    entry = f"## [{_now_bj_str()}] {op} | {detail}\n"
    return (header + (current_log.rstrip() + "\n" if current_log.strip() else "") + entry)


def build_default_skill_md(
    *,
    name: str,
    slug: str,
    description: str,
    kb_slug: str,
    triggers: list[str],
    version: str,
    index_md: str,
    pages: list[dict[str, Any]],
) -> str:
    fm = yaml.safe_dump(
        {
            "name": name,
            "slug": slug,
            "description": description or f"调用「{name}」LLM Wiki 知识库精准回答相关问题",
            "version": version,
            "kb_slug": kb_slug,
            "triggers": triggers,
        },
        allow_unicode=True,
        sort_keys=False,
    ).strip()

    preview_lines = [f"- [[{p['title']}]]：{p.get('summary') or ''}" for p in pages[:18]]
    catalog_block = (
        "\n".join(preview_lines)
        if preview_lines
        else "- （当前词条为空，调用时将回退检索 raw/ 原始资料）"
    )
    trigger_text = (
        "、".join(triggers)
        if triggers
        else f"（未设自动触发词，可通过对话选择或 /skill:{slug} 显式调用）"
    )
    index_excerpt = "\n".join((index_md or "").splitlines()[:24])

    return (
        f"---\n{fm}\n---\n\n"
        f"# {name} · 知识库 Skill\n\n"
        f"> 适用场景：{description or '围绕本知识库沉淀的方法论、案例与资料进行有据可查的问答与推理'}\n\n"
        f"## 触发条件\n"
        f"- 显式指令：`/skill:{slug}` 或在对话工具栏勾选本 Skill\n"
        f"- 自动触发关键词：{trigger_text}\n\n"
        f"## LLM Wiki 检索与回答协议\n"
        f"1. 优先依据本 Skill 附带的 `wiki/` 互链词条与 `[[wikilinks]]` 关联上下文组织答案。\n"
        f"2. 结论中涉及知识库明确观点、步骤或数据时，使用 `[词条标题]` 标注出处，方便用户追溯原文。\n"
        f"3. 若当前知识库未提及用户追问的某个细节，诚实指出知识库边界，切勿臆测。\n"
        f"4. 对话中沉淀出高质量总结时，可提示用户一键「沉淀回 Wiki」持续复利。\n\n"
        f"## 核心词条地图 ({len(pages)} 篇)\n"
        f"{catalog_block}\n\n"
        f"## index.md 概览\n"
        f"```markdown\n{index_excerpt}\n```\n"
    )


def _tokenize_query(text: str) -> list[str]:
    clean = (text or "").lower().strip()
    if not clean:
        return []
    tokens: list[str] = []
    seen: set[str] = set()

    def _add(tok: str) -> None:
        t = tok.strip()
        if len(t) >= 2 and t not in _STOPWORDS and t not in seen:
            seen.add(t)
            tokens.append(t)

    for en in re.findall(r"[a-z0-9_+-]{2,}", clean):
        _add(en)

    for run in re.findall(r"[\u4e00-\u9fff]+", clean):
        if len(run) <= 6:
            _add(run)
        for n in (2, 3, 4):
            if len(run) >= n:
                for i in range(len(run) - n + 1):
                    _add(run[i : i + n])
        if len(tokens) > 40:
            break
    return tokens[:45]


# ---------------------------------------------------------------------------
# Repository Layer (MySQL with seamless in-memory fallback)
# ---------------------------------------------------------------------------


async def _repo_next_unique_slug(model_cls: Any, desired: str) -> str:
    base = slugify_text(desired, fallback="kb", max_len=52)
    existing_slugs: set[str] = set()
    try:
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(select(model_cls.slug).where(model_cls.slug.like(f"{base}%")))
            ).scalars().all()
            existing_slugs = {str(r) for r in rows}
    except (SQLAlchemyError, OSError):
        pool = _mem_skills if model_cls is KBSkill else _mem_kbs
        existing_slugs = {str(item["slug"]) for item in pool.values()}

    if base not in existing_slugs:
        return base
    for idx in range(2, 100):
        candidate = f"{base[:46]}-{idx}"
        if candidate not in existing_slugs:
            return candidate
    return f"{base[:44]}-{hashlib.sha1(str(datetime.now(UTC).timestamp()).encode()).hexdigest()[:6]}"


async def _repo_list_kbs() -> list[dict[str, Any]]:
    try:
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(select(KBWikiBase).order_by(desc(KBWikiBase.id)))
            ).scalars().all()
            return [_kb_row_to_dict(r) for r in rows]
    except (SQLAlchemyError, OSError) as exc:
        logger.debug("KB list fallback to mem: %s", exc)
        return sorted((dict(v) for v in _mem_kbs.values()), key=lambda x: x["id"], reverse=True)


async def _repo_get_kb(kb_id: int) -> dict[str, Any] | None:
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(select(KBWikiBase).where(KBWikiBase.id == kb_id))
            ).scalar_one_or_none()
            return _kb_row_to_dict(row) if row else None
    except (SQLAlchemyError, OSError):
        item = _mem_kbs.get(int(kb_id))
        return dict(item) if item else None


async def _repo_create_kb(fields: dict[str, Any]) -> dict[str, Any]:
    now = _now_utc_naive()
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = KBWikiBase(
                slug=fields["slug"],
                name=fields["name"],
                description=fields.get("description", ""),
                category=fields.get("category", "general"),
                owner_scope=fields["owner_scope"],
                visibility=fields.get("visibility", "private"),
                schema_md=fields.get("schema_md", ""),
                index_md=fields.get("index_md", ""),
                log_md=fields.get("log_md", ""),
                source_count=0,
                page_count=0,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _kb_row_to_dict(row)
    except (SQLAlchemyError, OSError):
        kid = _mem_seq["kb"]
        _mem_seq["kb"] += 1
        rec = {
            "id": kid,
            "slug": fields["slug"],
            "name": fields["name"],
            "description": fields.get("description", ""),
            "category": fields.get("category", "general"),
            "owner_scope": fields["owner_scope"],
            "visibility": fields.get("visibility", "private"),
            "schema_md": fields.get("schema_md", ""),
            "index_md": fields.get("index_md", ""),
            "log_md": fields.get("log_md", ""),
            "source_count": 0,
            "page_count": 0,
            "last_lint_score": None,
            "last_lint_report": None,
            "last_compiled_at": None,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        _mem_kbs[kid] = rec
        return dict(rec)


async def _repo_update_kb(kb_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
    now = _now_utc_naive()
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(select(KBWikiBase).where(KBWikiBase.id == kb_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            for k, v in patch.items():
                if k == "last_lint_report":
                    row.last_lint_json = json.dumps(v, ensure_ascii=False) if v is not None else ""
                elif hasattr(row, k):
                    setattr(row, k, v)
            row.updated_at = now
            await session.commit()
            await session.refresh(row)
            return _kb_row_to_dict(row)
    except (SQLAlchemyError, OSError):
        rec = _mem_kbs.get(int(kb_id))
        if rec is None:
            return None
        for k, v in patch.items():
            if k == "last_compiled_at" and isinstance(v, datetime):
                rec[k] = v.isoformat()
            else:
                rec[k] = v
        rec["updated_at"] = now.isoformat()
        return dict(rec)


async def _repo_delete_kb(kb_id: int) -> bool:
    try:
        factory = get_session_factory()
        async with factory() as session:
            res = await session.execute(delete(KBWikiBase).where(KBWikiBase.id == kb_id))
            await session.commit()
            return int(res.rowcount or 0) > 0
    except (SQLAlchemyError, OSError):
        removed = _mem_kbs.pop(int(kb_id), None) is not None
        if removed:
            for sid in [k for k, v in _mem_sources.items() if v["kb_id"] == kb_id]:
                _mem_sources.pop(sid, None)
            for pid in [k for k, v in _mem_pages.items() if v["kb_id"] == kb_id]:
                _mem_pages.pop(pid, None)
            for skid in [k for k, v in _mem_skills.items() if v["kb_id"] == kb_id]:
                _mem_skills.pop(skid, None)
        return removed


async def _repo_list_sources(kb_id: int, *, include_text: bool = True) -> list[dict[str, Any]]:
    try:
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(
                    select(KBRawSource).where(KBRawSource.kb_id == kb_id).order_by(KBRawSource.id)
                )
            ).scalars().all()
            return [_source_row_to_dict(r, include_text=include_text) for r in rows]
    except (SQLAlchemyError, OSError):
        items = [dict(v) for v in _mem_sources.values() if v["kb_id"] == kb_id]
        items.sort(key=lambda x: x["id"])
        if not include_text:
            for item in items:
                item.pop("raw_text", None)
        return items


async def _repo_upsert_source(
    kb_id: int, entry: BundleFileEntry, *, status_val: str = "pending"
) -> tuple[dict[str, Any], bool]:
    """按 content_sha256 去重写入 raw/ 资料，返回 (source_dict, deduplicated)。"""
    now = _now_utc_naive()
    try:
        factory = get_session_factory()
        async with factory() as session:
            existing = (
                await session.execute(
                    select(KBRawSource).where(
                        KBRawSource.kb_id == kb_id,
                        KBRawSource.content_sha256 == entry.sha256,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return _source_row_to_dict(existing), True
            row = KBRawSource(
                kb_id=kb_id,
                filename=entry.filename[:255],
                rel_path=(entry.rel_path or entry.filename)[:255],
                mime_type=entry.mime_type[:100],
                file_size=len(entry.raw_bytes),
                content_sha256=entry.sha256,
                raw_text=entry.text,
                ingest_status=status_val,
                ingested_at=now if status_val == "ingested" else None,
            )
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return _source_row_to_dict(row), False
    except (SQLAlchemyError, OSError):
        for v in _mem_sources.values():
            if v["kb_id"] == kb_id and v["content_sha256"] == entry.sha256:
                return dict(v), True
        sid = _mem_seq["source"]
        _mem_seq["source"] += 1
        rec = {
            "id": sid,
            "kb_id": kb_id,
            "filename": entry.filename[:255],
            "rel_path": (entry.rel_path or entry.filename)[:255],
            "mime_type": entry.mime_type[:100],
            "file_size": len(entry.raw_bytes),
            "content_sha256": entry.sha256,
            "char_count": len(entry.text),
            "raw_text": entry.text,
            "ingest_status": status_val,
            "ingest_error": "",
            "ingested_at": now.isoformat() if status_val == "ingested" else None,
            "created_at": now.isoformat(),
        }
        _mem_sources[sid] = rec
        return dict(rec), False


async def _repo_update_source_status(source_id: int, ingest_status: str, ingest_error: str = "") -> None:
    now = _now_utc_naive()
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                update(KBRawSource)
                .where(KBRawSource.id == source_id)
                .values(
                    ingest_status=ingest_status,
                    ingest_error=ingest_error[:500],
                    ingested_at=now if ingest_status == "ingested" else None,
                )
            )
            await session.commit()
    except (SQLAlchemyError, OSError):
        rec = _mem_sources.get(int(source_id))
        if rec is not None:
            rec["ingest_status"] = ingest_status
            rec["ingest_error"] = ingest_error[:500]
            rec["ingested_at"] = now.isoformat() if ingest_status == "ingested" else None


async def _repo_delete_source(kb_id: int, source_id: int) -> bool:
    try:
        factory = get_session_factory()
        async with factory() as session:
            res = await session.execute(
                delete(KBRawSource).where(KBRawSource.kb_id == kb_id, KBRawSource.id == source_id)
            )
            await session.commit()
            return int(res.rowcount or 0) > 0
    except (SQLAlchemyError, OSError):
        rec = _mem_sources.get(int(source_id))
        if rec and rec["kb_id"] == kb_id:
            _mem_sources.pop(int(source_id), None)
            return True
        return False


async def _repo_list_pages(kb_id: int, *, include_content: bool = True) -> list[dict[str, Any]]:
    try:
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(
                    select(KBWikiPage).where(KBWikiPage.kb_id == kb_id).order_by(KBWikiPage.id)
                )
            ).scalars().all()
            return [_page_row_to_dict(r, include_content=include_content) for r in rows]
    except (SQLAlchemyError, OSError):
        items = [dict(v) for v in _mem_pages.values() if v["kb_id"] == kb_id]
        items.sort(key=lambda x: x["id"])
        if not include_content:
            for item in items:
                item.pop("content_md", None)
        return items


async def _repo_get_page(kb_id: int, page_id: int) -> dict[str, Any] | None:
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    select(KBWikiPage).where(KBWikiPage.kb_id == kb_id, KBWikiPage.id == page_id)
                )
            ).scalar_one_or_none()
            return _page_row_to_dict(row) if row else None
    except (SQLAlchemyError, OSError):
        rec = _mem_pages.get(int(page_id))
        return dict(rec) if rec and rec["kb_id"] == kb_id else None


async def _repo_upsert_page(
    kb_id: int,
    *,
    page_path: str,
    slug: str,
    title: str,
    page_type: str,
    summary: str,
    content_md: str,
    source_ids: list[int],
) -> dict[str, Any]:
    now = _now_utc_naive()
    links = extract_wikilinks(content_md)
    try:
        factory = get_session_factory()
        async with factory() as session:
            existing = (
                await session.execute(
                    select(KBWikiPage).where(
                        KBWikiPage.kb_id == kb_id,
                        KBWikiPage.page_path == page_path,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                row = KBWikiPage(
                    kb_id=kb_id,
                    page_path=page_path[:255],
                    slug=slug[:128],
                    title=title[:200],
                    page_type=page_type[:24],
                    summary=summary[:500],
                    content_md=content_md,
                    links_json=json.dumps(links, ensure_ascii=False),
                    source_ids_json=json.dumps(source_ids),
                    version=1,
                )
                session.add(row)
                await session.commit()
                await session.refresh(row)
                return _page_row_to_dict(row)

            merged_sids = sorted(set(_safe_json_loads(existing.source_ids_json, [])) | set(source_ids))
            existing.slug = slug[:128]
            existing.title = title[:200]
            existing.page_type = page_type[:24]
            existing.summary = summary[:500]
            existing.content_md = content_md
            existing.links_json = json.dumps(links, ensure_ascii=False)
            existing.source_ids_json = json.dumps(merged_sids)
            existing.version = int(existing.version or 1) + 1
            existing.updated_at = now
            await session.commit()
            await session.refresh(existing)
            return _page_row_to_dict(existing)
    except (SQLAlchemyError, OSError):
        for rec in _mem_pages.values():
            if rec["kb_id"] == kb_id and rec["page_path"] == page_path:
                rec["slug"] = slug[:128]
                rec["title"] = title[:200]
                rec["page_type"] = page_type[:24]
                rec["summary"] = summary[:500]
                rec["content_md"] = content_md
                rec["links"] = links
                rec["source_ids"] = sorted(set(rec.get("source_ids") or []) | set(source_ids))
                rec["version"] = int(rec.get("version") or 1) + 1
                rec["updated_at"] = now.isoformat()
                return dict(rec)
        pid = _mem_seq["page"]
        _mem_seq["page"] += 1
        rec = {
            "id": pid,
            "kb_id": kb_id,
            "page_path": page_path[:255],
            "slug": slug[:128],
            "title": title[:200],
            "page_type": page_type[:24],
            "summary": summary[:500],
            "content_md": content_md,
            "links": links,
            "source_ids": source_ids,
            "version": 1,
            "updated_at": now.isoformat(),
        }
        _mem_pages[pid] = rec
        return dict(rec)


async def _repo_delete_page(kb_id: int, page_id: int) -> bool:
    try:
        factory = get_session_factory()
        async with factory() as session:
            res = await session.execute(
                delete(KBWikiPage).where(KBWikiPage.kb_id == kb_id, KBWikiPage.id == page_id)
            )
            await session.commit()
            return int(res.rowcount or 0) > 0
    except (SQLAlchemyError, OSError):
        rec = _mem_pages.get(int(page_id))
        if rec and rec["kb_id"] == kb_id:
            _mem_pages.pop(int(page_id), None)
            return True
        return False


async def _repo_get_skill_by_kb(kb_id: int) -> dict[str, Any] | None:
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(select(KBSkill).where(KBSkill.kb_id == kb_id))
            ).scalar_one_or_none()
            return _skill_row_to_dict(row) if row else None
    except (SQLAlchemyError, OSError):
        for sk in _mem_skills.values():
            if sk["kb_id"] == kb_id:
                return dict(sk)
        return None


async def _repo_get_skill(skill_id: int) -> dict[str, Any] | None:
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(select(KBSkill).where(KBSkill.id == skill_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            kb = (
                await session.execute(select(KBWikiBase.name).where(KBWikiBase.id == row.kb_id))
            ).scalar_one_or_none()
            return _skill_row_to_dict(row, kb_name=str(kb or ""))
    except (SQLAlchemyError, OSError):
        sk = _mem_skills.get(int(skill_id))
        if not sk:
            return None
        out = dict(sk)
        kb = _mem_kbs.get(int(sk["kb_id"]))
        out["kb_name"] = kb["name"] if kb else ""
        return out


async def _repo_list_skills() -> list[dict[str, Any]]:
    try:
        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(select(KBSkill).order_by(desc(KBSkill.usage_count), desc(KBSkill.id)))
            ).scalars().all()
            kb_rows = (await session.execute(select(KBWikiBase.id, KBWikiBase.name))).all()
            kb_names = {int(r[0]): str(r[1]) for r in kb_rows}
            return [_skill_row_to_dict(r, kb_name=kb_names.get(int(r.kb_id), "")) for r in rows]
    except (SQLAlchemyError, OSError):
        out: list[dict[str, Any]] = []
        for sk in _mem_skills.values():
            rec = dict(sk)
            kb = _mem_kbs.get(int(sk["kb_id"]))
            rec["kb_name"] = kb["name"] if kb else ""
            out.append(rec)
        out.sort(key=lambda x: (-int(x.get("usage_count") or 0), -int(x["id"])))
        return out


async def _repo_upsert_skill(kb_id: int, fields: dict[str, Any]) -> dict[str, Any]:
    now = _now_utc_naive()
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(select(KBSkill).where(KBSkill.kb_id == kb_id))
            ).scalar_one_or_none()
            if row is None:
                row = KBSkill(
                    kb_id=kb_id,
                    slug=fields["slug"],
                    name=fields["name"],
                    description=fields.get("description", ""),
                    triggers_json=json.dumps(fields.get("triggers") or [], ensure_ascii=False),
                    skill_md=fields["skill_md"],
                    version=fields.get("version", "1.0.0"),
                    owner_scope=fields["owner_scope"],
                    visibility=fields.get("visibility", "private"),
                    is_enabled=bool(fields.get("is_enabled", True)),
                    usage_count=0,
                )
                session.add(row)
            else:
                row.name = fields.get("name", row.name)
                row.description = fields.get("description", row.description)
                row.triggers_json = json.dumps(fields.get("triggers") or [], ensure_ascii=False)
                row.skill_md = fields.get("skill_md", row.skill_md)
                row.version = fields.get("version", row.version)
                row.visibility = fields.get("visibility", row.visibility)
                row.is_enabled = bool(fields.get("is_enabled", row.is_enabled))
                row.updated_at = now
            await session.commit()
            await session.refresh(row)
            return _skill_row_to_dict(row)
    except (SQLAlchemyError, OSError):
        for sk in _mem_skills.values():
            if sk["kb_id"] == kb_id:
                sk.update(
                    {
                        "name": fields.get("name", sk["name"]),
                        "description": fields.get("description", sk["description"]),
                        "triggers": list(fields.get("triggers") or []),
                        "skill_md": fields.get("skill_md", sk["skill_md"]),
                        "version": fields.get("version", sk["version"]),
                        "visibility": fields.get("visibility", sk["visibility"]),
                        "is_enabled": bool(fields.get("is_enabled", sk["is_enabled"])),
                        "updated_at": now.isoformat(),
                    }
                )
                return dict(sk)
        sid = _mem_seq["skill"]
        _mem_seq["skill"] += 1
        rec = {
            "id": sid,
            "kb_id": kb_id,
            "slug": fields["slug"],
            "name": fields["name"],
            "description": fields.get("description", ""),
            "triggers": list(fields.get("triggers") or []),
            "skill_md": fields["skill_md"],
            "version": fields.get("version", "1.0.0"),
            "owner_scope": fields["owner_scope"],
            "visibility": fields.get("visibility", "private"),
            "is_enabled": bool(fields.get("is_enabled", True)),
            "usage_count": 0,
            "updated_at": now.isoformat(),
        }
        _mem_skills[sid] = rec
        return dict(rec)


async def _repo_update_skill(skill_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
    now = _now_utc_naive()
    try:
        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(select(KBSkill).where(KBSkill.id == skill_id))
            ).scalar_one_or_none()
            if row is None:
                return None
            for k, v in patch.items():
                if k == "triggers":
                    row.triggers_json = json.dumps(v or [], ensure_ascii=False)
                elif hasattr(row, k):
                    setattr(row, k, v)
            row.updated_at = now
            await session.commit()
            await session.refresh(row)
            return _skill_row_to_dict(row)
    except (SQLAlchemyError, OSError):
        sk = _mem_skills.get(int(skill_id))
        if sk is None:
            return None
        sk.update(patch)
        sk["updated_at"] = now.isoformat()
        return dict(sk)


async def _repo_inc_skill_usage(skill_id: int) -> None:
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                update(KBSkill)
                .where(KBSkill.id == skill_id)
                .values(usage_count=KBSkill.usage_count + 1)
            )
            await session.commit()
    except (SQLAlchemyError, OSError):
        sk = _mem_skills.get(int(skill_id))
        if sk is not None:
            sk["usage_count"] = int(sk.get("usage_count") or 0) + 1


# ---------------------------------------------------------------------------
# Access Control Helpers
# ---------------------------------------------------------------------------


async def _role_permissions(role: str) -> list[str]:
    if not role:
        return []
    try:
        meta = await get_role_meta(role)
        return list(meta.get("permissions") or [])
    except Exception:
        return []


async def _can_manage_kb(kb: dict[str, Any], owner_scope: str, role: str) -> bool:
    if kb["owner_scope"] == owner_scope:
        return True
    perms = await _role_permissions(role)
    return has_permission(perms, "kb:manage")


async def _can_read_kb(kb: dict[str, Any], owner_scope: str, role: str) -> bool:
    if kb.get("visibility") == "public":
        return True
    if kb["owner_scope"] == owner_scope:
        return True
    perms = await _role_permissions(role)
    return has_permission(perms, "kb:view") or has_permission(perms, "kb:manage")


async def _require_kb(kb_id: int, *, owner_scope: str, role: str, write: bool = False) -> dict[str, Any]:
    kb = await _repo_get_kb(kb_id)
    if kb is None:
        raise BusinessException("目标知识库不存在", code=40410, status_code=404)
    allowed = (
        await _can_manage_kb(kb, owner_scope, role)
        if write
        else await _can_read_kb(kb, owner_scope, role)
    )
    if not allowed:
        raise BusinessException(
            "无权操作或访问该私有知识库",
            code=40310,
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return kb


# ---------------------------------------------------------------------------
# LLM Wiki Ingest Compilation Engine (LLM + Deterministic Fallback)
# ---------------------------------------------------------------------------


def _split_markdown_sections(raw_text: str, filename: str) -> tuple[str, list[tuple[str, str]]]:
    """解析 Markdown/纯文本章节结构，返回 (doc_title, [(heading, body), ...])。"""
    lines = (raw_text or "").splitlines()
    doc_title = posixpath.splitext(filename)[0]
    sections: list[tuple[str, list[str]]] = []
    cur_heading = ""
    cur_body: list[str] = []

    for line in lines:
        m1 = re.match(r"^#\s+(.+)$", line)
        m2 = re.match(r"^#{2,3}\s+(.+)$", line)
        if m1 and doc_title == posixpath.splitext(filename)[0]:
            doc_title = m1.group(1).strip()[:120]
            continue
        if m2:
            if cur_body:
                sections.append((cur_heading or f"{doc_title} 概要", cur_body))
            cur_heading = m2.group(1).strip()[:120]
            cur_body = []
        else:
            cur_body.append(line)
    if cur_body:
        sections.append((cur_heading or doc_title, cur_body))

    normalized = [(h, "\n".join(b).strip()) for h, b in sections if "\n".join(b).strip()]
    if not normalized and raw_text.strip():
        normalized = [(doc_title, raw_text.strip())]
    return doc_title, normalized


def _extract_summary_line(text: str, max_len: int = 160) -> str:
    flat = re.sub(r"\s+", " ", re.sub(r"[#>*`\[\]]", "", text or "")).strip()
    return flat[:max_len] + ("…" if len(flat) > max_len else "")


def _deterministic_ingest_source(
    source: dict[str, Any],
    existing_titles: list[str],
) -> list[dict[str, Any]]:
    """无 LLM 密钥或纯离线环境下的结构化 LLM Wiki 编译器（生成 summary + concepts + 互链）。"""
    raw_text = str(source.get("raw_text") or "").strip()
    filename = str(source.get("filename") or "untitled.md")
    doc_title, sections = _split_markdown_sections(raw_text, filename)
    src_slug = slugify_text(doc_title, fallback="source")

    concept_drafts: list[dict[str, Any]] = []
    # 最多拆分 5 个核心概念节，避免单篇长文档产生过多碎片页
    for idx, (sec_title, sec_body) in enumerate(sections[:5]):
        if len(sections) == 1 and sec_title == doc_title:
            break
        if len(sec_body) < 35:
            continue
        c_slug = slugify_text(sec_title, fallback=f"concept-{idx + 1}")
        concept_drafts.append(
            {
                "page_path": f"wiki/concepts/{c_slug}.md",
                "slug": c_slug,
                "title": sec_title,
                "page_type": "concept",
                "summary": _extract_summary_line(sec_body, 140),
                "raw_body": sec_body[:6000],
            }
        )

    concept_titles = [c["title"] for c in concept_drafts]
    # 互相注入 [[wikilinks]] 关联
    summary_links = [f"- [[{t}]]" for t in concept_titles]
    for prev_t in existing_titles[:5]:
        if prev_t != doc_title and prev_t not in concept_titles and prev_t in raw_text:
            summary_links.append(f"- [[{prev_t}]]")

    summary_excerpt = raw_text[:3600]
    summary_content_parts = [
        f"# {doc_title}",
        "",
        f"> 原始来源：`raw/{source.get('rel_path') or filename}`",
        "",
        "## 核心摘要",
        _extract_summary_line(raw_text, 280),
        "",
    ]
    if summary_links:
        summary_content_parts.extend(["## 关联知识词条", *summary_links, ""])
    summary_content_parts.extend(["## 原文要点摘录", summary_excerpt, ""])

    results: list[dict[str, Any]] = [
        {
            "page_path": f"wiki/summaries/{src_slug}.md",
            "slug": src_slug,
            "title": doc_title,
            "page_type": "summary",
            "summary": _extract_summary_line(raw_text, 150),
            "content_md": "\n".join(summary_content_parts),
        }
    ]

    for c in concept_drafts:
        siblings = [t for t in concept_titles if t != c["title"]][:4]
        cross_lines = [f"- 来源总览：[[{doc_title}]]"]
        for sib in siblings:
            cross_lines.append(f"- 相关概念：[[{sib}]]")
        c_md = (
            f"# {c['title']}\n\n"
            f"> 提炼自：[[{doc_title}]] (`raw/{source.get('rel_path') or filename}`)\n\n"
            f"## 词条正文\n{c['raw_body']}\n\n"
            f"## 知识图谱关联\n" + "\n".join(cross_lines) + "\n"
        )
        results.append(
            {
                "page_path": c["page_path"],
                "slug": c["slug"],
                "title": c["title"],
                "page_type": "concept",
                "summary": c["summary"],
                "content_md": c_md,
            }
        )

    return results


async def _try_llm_ingest_source(
    kb: dict[str, Any],
    source: dict[str, Any],
    index_md: str,
    config_id: int | None = None,
) -> list[dict[str, Any]] | None:
    """尝试调用已配置真实大模型按照 SCHEMA.md 编译源文档；失败时返回 None 回退确定性编译。"""
    cfg = await resolve_runtime_config(config_id=config_id)
    if not cfg.is_configured:
        return None
    adapter = get_provider_adapter(cfg.provider)
    if adapter is None:
        return None

    try:
        llm = adapter.build_chat_model(
            api_key=cfg.api_key,
            base_url=cfg.base_url,
            model_name=cfg.model_name,
            temperature=0.3,
            top_p=cfg.top_p,
            max_tokens=min(cfg.max_tokens, 4096),
            timeout_seconds=min(cfg.timeout_seconds, 60),
            streaming=False,
            extra_params=cfg.extra_params,
        )
        sys_msg = SystemMessage(
            content=(
                "你是 LLM Wiki 知识工程师。请严格遵循知识库 SCHEMA.md，"
                "将用户提供的原始资料编译为结构化 Markdown Wiki 词条。\n"
                "必须输出合法 JSON 对象（不要输出多余解释或 markdown 代码块外文本），结构如下：\n"
                '{"pages":[{"page_type":"summary|concept|entity","title":"词条标题",'
                '"summary":"一句话摘要(<120字)","content_md":"完整Markdown正文，用[[词条标题]]互链"}]}\n'
                "要求：\n"
                "1. 至少包含 1 篇 summary 页概述全文，并提炼 1~4 篇核心 concept/entity 页。\n"
                "2. 正文保留关键数据、步骤、案例，并在词条间互链 [[词条标题]]。\n"
            )
        )
        human_msg = HumanMessage(
            content=(
                f"【知识库 SCHEMA.md】\n{(kb.get('schema_md') or '')[:1500]}\n\n"
                f"【当前 index.md】\n{index_md[:1800]}\n\n"
                f"【待编译原始文件：{source.get('rel_path') or source.get('filename')}】\n"
                f"{str(source.get('raw_text') or '')[:14000]}"
            )
        )
        ai_msg = await llm.ainvoke([sys_msg, human_msg])
        _, text = adapter.extract_chunk_deltas(ai_msg)
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        parsed = json.loads(cleaned)
        raw_pages = parsed.get("pages") if isinstance(parsed, dict) else None
        if not isinstance(raw_pages, list) or not raw_pages:
            return None

        dir_map = {"summary": "summaries", "concept": "concepts", "entity": "entities", "insight": "insights"}
        compiled: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_pages[:6]):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()[:200]
            content_md = str(item.get("content_md") or "").strip()
            if not title or not content_md:
                continue
            ptype = str(item.get("page_type") or "concept").strip().lower()
            if ptype not in dir_map:
                ptype = "concept"
            slug = slugify_text(title, fallback=f"page-{idx + 1}")
            compiled.append(
                {
                    "page_path": f"wiki/{dir_map[ptype]}/{slug}.md",
                    "slug": slug,
                    "title": title,
                    "page_type": ptype,
                    "summary": str(item.get("summary") or _extract_summary_line(content_md, 140))[:500],
                    "content_md": content_md,
                }
            )
        return compiled or None
    except Exception as exc:
        logger.warning("LLM Wiki compile fell back to deterministic parser: %s", exc)
        return None


async def _refresh_kb_index_and_overview(
    kb: dict[str, Any], *, log_op: str = "", log_detail: str = ""
) -> dict[str, Any]:
    """确保 overview 页互链健康，重算 index.md、source_count/page_count，并同步 Skill 目录。"""
    kb_id = int(kb["id"])
    sources = await _repo_list_sources(kb_id, include_text=False)
    pages = await _repo_list_pages(kb_id, include_content=False)

    non_overview = [p for p in pages if p["page_path"] != "wiki/overview.md"]
    if non_overview:
        overview_lines = [
            f"# {kb['name']} · 知识全景总览",
            "",
            f"> {kb.get('description') or '全库主题导览与核心概念入口'}",
            "",
            "## 核心词条网络",
        ]
        for p in non_overview[:40]:
            overview_lines.append(f"- [[{p['title']}]] — {p.get('summary') or ''}")
        overview_lines.append("")
        await _repo_upsert_page(
            kb_id,
            page_path="wiki/overview.md",
            slug="overview",
            title=f"{kb['name']} 总览",
            page_type="overview",
            summary=f"{kb['name']} 全部知识词条导航入口（共 {len(non_overview)} 篇）",
            content_md="\n".join(overview_lines),
            source_ids=[],
        )
        pages = await _repo_list_pages(kb_id, include_content=False)

    new_index_md = build_index_md(kb["name"], pages)
    next_log = kb.get("log_md") or ""
    if log_op and log_detail:
        next_log = _append_log(next_log, log_op, log_detail)

    updated_kb = await _repo_update_kb(
        kb_id,
        {
            "index_md": new_index_md,
            "log_md": next_log,
            "source_count": len(sources),
            "page_count": len(pages),
        },
    )
    assert updated_kb is not None

    # 若已发布 Skill，顺便刷新其目录概览段（保留用户自定义头部正文逻辑简化为重建当包含默认标记时）
    skill = await _repo_get_skill_by_kb(kb_id)
    if skill and "## 核心词条地图" in (skill.get("skill_md") or ""):
        refreshed_skill_md = build_default_skill_md(
            name=skill["name"],
            slug=skill["slug"],
            description=skill["description"],
            kb_slug=updated_kb["slug"],
            triggers=skill.get("triggers") or [],
            version=skill.get("version") or "1.0.0",
            index_md=new_index_md,
            pages=pages,
        )
        await _repo_update_skill(int(skill["id"]), {"skill_md": refreshed_skill_md})

    return updated_kb


# ---------------------------------------------------------------------------
# Public Service APIs
# ---------------------------------------------------------------------------


async def list_kbs(*, owner_scope: str, role: str) -> list[dict[str, Any]]:
    all_kbs = await _repo_list_kbs()
    visible: list[dict[str, Any]] = []
    skills = await _repo_list_skills()
    skill_by_kb = {int(s["kb_id"]): s for s in skills}
    for kb in all_kbs:
        if await _can_read_kb(kb, owner_scope, role):
            item = dict(kb)
            item["is_owner"] = kb["owner_scope"] == owner_scope
            item["skill"] = skill_by_kb.get(int(kb["id"]))
            visible.append(item)
    return visible


async def create_kb(
    *,
    name: str,
    slug: str = "",
    description: str = "",
    category: str = "general",
    visibility: str = "private",
    schema_md: str = "",
    owner_scope: str,
) -> dict[str, Any]:
    clean_name = name.strip()[:100]
    if not clean_name:
        raise BusinessException("知识库名称不能为空", code=40075)
    resolved_slug = await _repo_next_unique_slug(KBWikiBase, slug.strip() or clean_name)
    resolved_schema = schema_md.strip() or build_default_schema_md(clean_name, description)
    initial_index = build_index_md(clean_name, [])
    initial_log = _append_log("", "create", f"初始化知识库「{clean_name}」 (slug={resolved_slug})")
    return await _repo_create_kb(
        {
            "slug": resolved_slug,
            "name": clean_name,
            "description": description.strip()[:500],
            "category": (category or "general").strip()[:32],
            "owner_scope": owner_scope,
            "visibility": "public" if visibility == "public" else "private",
            "schema_md": resolved_schema,
            "index_md": initial_index,
            "log_md": initial_log,
        }
    )


async def get_kb_detail(kb_id: int, *, owner_scope: str, role: str) -> dict[str, Any]:
    kb = await _require_kb(kb_id, owner_scope=owner_scope, role=role, write=False)
    sources = await _repo_list_sources(kb_id, include_text=False)
    pages = await _repo_list_pages(kb_id, include_content=False)
    skill = await _repo_get_skill_by_kb(kb_id)
    can_manage = await _can_manage_kb(kb, owner_scope, role)
    return {
        "kb": kb,
        "can_manage": can_manage,
        "sources": sources,
        "pages": pages,
        "skill": skill,
    }


async def update_kb(kb_id: int, patch: dict[str, Any], *, owner_scope: str, role: str) -> dict[str, Any]:
    await _require_kb(kb_id, owner_scope=owner_scope, role=role, write=True)
    clean_patch = {k: v for k, v in patch.items() if v is not None}
    updated = await _repo_update_kb(kb_id, clean_patch)
    assert updated is not None
    if "visibility" in clean_patch:
        skill = await _repo_get_skill_by_kb(kb_id)
        if skill:
            await _repo_update_skill(int(skill["id"]), {"visibility": updated["visibility"]})
    return updated


async def delete_kb(kb_id: int, *, owner_scope: str, role: str) -> bool:
    await _require_kb(kb_id, owner_scope=owner_scope, role=role, write=True)
    return await _repo_delete_kb(kb_id)


async def upload_sources(
    kb_id: int,
    entries: list[BundleFileEntry],
    *,
    owner_scope: str,
    role: str,
    auto_compile: bool = False,
    use_llm: bool = True,
) -> dict[str, Any]:
    kb = await _require_kb(kb_id, owner_scope=owner_scope, role=role, write=True)
    if not entries:
        raise BusinessException("请至少选择一个有效文档文件", code=40070)

    created_ids: list[int] = []
    dedup_count = 0
    saved_items: list[dict[str, Any]] = []
    for entry in entries:
        src, deduplicated = await _repo_upsert_source(kb_id, entry, status_val="pending")
        saved_items.append(src)
        if deduplicated:
            dedup_count += 1
        else:
            created_ids.append(int(src["id"]))

    kb = await _refresh_kb_index_and_overview(
        kb,
        log_op="upload-raw" if created_ids else "",
        log_detail=f"新增 {len(created_ids)} 个原始文件（去重 {dedup_count} 个）" if created_ids else "",
    )

    compile_result = None
    if auto_compile and created_ids:
        compile_result = await compile_sources_into_wiki(
            kb_id,
            owner_scope=owner_scope,
            role=role,
            source_ids=created_ids,
            use_llm=use_llm,
        )

    return {
        "uploaded": len(created_ids),
        "deduplicated": dedup_count,
        "sources": saved_items,
        "compile_result": compile_result,
    }


async def delete_source(kb_id: int, source_id: int, *, owner_scope: str, role: str) -> bool:
    kb = await _require_kb(kb_id, owner_scope=owner_scope, role=role, write=True)
    deleted = await _repo_delete_source(kb_id, source_id)
    if deleted:
        await _refresh_kb_index_and_overview(kb, log_op="delete-raw", log_detail=f"移除原始文件 #{source_id}")
    return deleted


async def compile_sources_into_wiki(
    kb_id: int,
    *,
    owner_scope: str,
    role: str,
    source_ids: list[int] | None = None,
    use_llm: bool = True,
    config_id: int | None = None,
    recompile_all: bool = False,
) -> dict[str, Any]:
    kb = await _require_kb(kb_id, owner_scope=owner_scope, role=role, write=True)
    sources = await _repo_list_sources(kb_id, include_text=True)
    if source_ids:
        wanted = set(source_ids)
        targets = [s for s in sources if int(s["id"]) in wanted]
    elif recompile_all:
        targets = list(sources)
    else:
        targets = [s for s in sources if s.get("ingest_status") != "ingested"]

    if not targets:
        raise BusinessException("没有需要编译入库的 raw/ 文件（可勾选全量重编）", code=40076)

    existing_pages = await _repo_list_pages(kb_id, include_content=False)
    existing_titles = [p["title"] for p in existing_pages]
    running_index = kb.get("index_md") or ""
    compiled_pages: list[dict[str, Any]] = []
    mode_used = "deterministic"

    for src in targets:
        try:
            drafts: list[dict[str, Any]] | None = None
            if use_llm:
                drafts = await _try_llm_ingest_source(kb, src, running_index, config_id=config_id)
                if drafts:
                    mode_used = "llm"
            if not drafts:
                drafts = _deterministic_ingest_source(src, existing_titles)

            for d in drafts:
                saved_page = await _repo_upsert_page(
                    kb_id,
                    page_path=d["page_path"],
                    slug=d["slug"],
                    title=d["title"],
                    page_type=d["page_type"],
                    summary=d["summary"],
                    content_md=d["content_md"],
                    source_ids=[int(src["id"])],
                )
                compiled_pages.append(saved_page)
                if saved_page["title"] not in existing_titles:
                    existing_titles.append(saved_page["title"])

            await _repo_update_source_status(int(src["id"]), "ingested", "")
        except Exception as exc:
            await _repo_update_source_status(int(src["id"]), "failed", str(exc)[:300])
            raise

    updated_kb = await _refresh_kb_index_and_overview(
        kb,
        log_op="ingest",
        log_detail=(
            f"编译 {len(targets)} 份 raw/ 资料 ({mode_used}) -> "
            f"更新 {len(compiled_pages)} 篇 Wiki 词条"
        ),
    )
    updated_kb = await _repo_update_kb(kb_id, {"last_compiled_at": _now_utc_naive()})
    assert updated_kb is not None
    return {
        "compiled_sources": len(targets),
        "generated_pages": len(compiled_pages),
        "compile_mode": mode_used,
        "kb": updated_kb,
    }


async def get_wiki_page(kb_id: int, page_id: int, *, owner_scope: str, role: str) -> dict[str, Any]:
    await _require_kb(kb_id, owner_scope=owner_scope, role=role, write=False)
    page = await _repo_get_page(kb_id, page_id)
    if page is None:
        raise BusinessException("Wiki 词条不存在", code=40411, status_code=404)
    return page


async def update_wiki_page(
    kb_id: int,
    page_id: int,
    patch: dict[str, Any],
    *,
    owner_scope: str,
    role: str,
) -> dict[str, Any]:
    kb = await _require_kb(kb_id, owner_scope=owner_scope, role=role, write=True)
    cur = await _repo_get_page(kb_id, page_id)
    if cur is None:
        raise BusinessException("Wiki 词条不存在", code=40411, status_code=404)

    next_title = (patch.get("title") or cur["title"]).strip()[:200]
    next_type = (patch.get("page_type") or cur["page_type"]).strip()[:24]
    next_summary = patch["summary"].strip()[:500] if patch.get("summary") is not None else cur["summary"]
    next_md = patch["content_md"] if patch.get("content_md") is not None else cur["content_md"]

    updated = await _repo_upsert_page(
        kb_id,
        page_path=cur["page_path"],
        slug=cur["slug"],
        title=next_title,
        page_type=next_type,
        summary=next_summary,
        content_md=next_md,
        source_ids=cur.get("source_ids") or [],
    )
    await _refresh_kb_index_and_overview(
        kb,
        log_op="edit-wiki",
        log_detail=f"人工修订词条 [[{next_title}]] ({cur['page_path']})",
    )
    return updated


async def delete_wiki_page(kb_id: int, page_id: int, *, owner_scope: str, role: str) -> bool:
    kb = await _require_kb(kb_id, owner_scope=owner_scope, role=role, write=True)
    cur = await _repo_get_page(kb_id, page_id)
    if cur is None:
        return False
    ok_del = await _repo_delete_page(kb_id, page_id)
    if ok_del:
        await _refresh_kb_index_and_overview(
            kb,
            log_op="delete-wiki",
            log_detail=f"删除词条 [[{cur['title']}]] ({cur['page_path']})",
        )
    return ok_del


async def file_insight_to_wiki(
    kb_id: int,
    *,
    title: str,
    content: str,
    source_question: str = "",
    owner_scope: str,
    role: str,
) -> dict[str, Any]:
    """将对话问答产生的高价值结论直接回流写入 wiki/insights/，实现越用越聪明。"""
    kb = await _require_kb(kb_id, owner_scope=owner_scope, role=role, write=True)
    clean_title = title.strip()[:200]
    slug = slugify_text(clean_title, fallback="insight")
    pages = await _repo_list_pages(kb_id, include_content=False)

    related = [f"[[{p['title']}]]" for p in pages if p["title"] in content][:5]
    parts = [f"# {clean_title}", ""]
    if source_question.strip():
        parts.extend([f"> 触发问题：{source_question.strip()}", ""])
    parts.extend([content.strip(), ""])
    if related:
        parts.extend(["## 关联词条", ", ".join(related), ""])

    page = await _repo_upsert_page(
        kb_id,
        page_path=f"wiki/insights/{slug}.md",
        slug=slug,
        title=clean_title,
        page_type="insight",
        summary=_extract_summary_line(content, 150),
        content_md="\n".join(parts),
        source_ids=[],
    )
    updated_kb = await _refresh_kb_index_and_overview(
        kb,
        log_op="query-insight",
        log_detail=f"沉淀问答洞察 [[{clean_title}]] -> {page['page_path']}",
    )
    return {"page": page, "kb": updated_kb}


async def lint_wiki(kb_id: int, *, owner_scope: str, role: str) -> dict[str, Any]:
    """巡检 LLM Wiki 图谱健康度：死链、孤立词条、空摘要、未编译源文件。"""
    kb = await _require_kb(kb_id, owner_scope=owner_scope, role=role, write=True)
    pages = await _repo_list_pages(kb_id, include_content=True)
    sources = await _repo_list_sources(kb_id, include_text=False)

    title_or_slug_map: dict[str, int] = {}
    inbound_count: dict[int, int] = {int(p["id"]): 0 for p in pages}
    for p in pages:
        title_or_slug_map[str(p["title"]).strip().lower()] = int(p["id"])
        title_or_slug_map[str(p["slug"]).strip().lower()] = int(p["id"])

    dangling_links: list[dict[str, str]] = []
    short_pages: list[str] = []
    no_summary_pages: list[str] = []

    for p in pages:
        links = p.get("links") or extract_wikilinks(p.get("content_md") or "")
        for target in links:
            tid = title_or_slug_map.get(target.strip().lower())
            if tid is None:
                dangling_links.append({"from": p["title"], "missing_target": target})
            elif tid != int(p["id"]):
                inbound_count[tid] = inbound_count.get(tid, 0) + 1

        if p["page_type"] != "overview" and len((p.get("content_md") or "").strip()) < 60:
            short_pages.append(p["title"])
        if not (p.get("summary") or "").strip():
            no_summary_pages.append(p["title"])

    orphan_pages = [
        p["title"]
        for p in pages
        if p["page_type"] != "overview" and inbound_count.get(int(p["id"]), 0) == 0 and len(pages) > 1
    ]
    pending_sources = [s["filename"] for s in sources if s.get("ingest_status") != "ingested"]

    penalty = (
        len(dangling_links) * 8
        + len(orphan_pages) * 5
        + len(pending_sources) * 10
        + len(short_pages) * 5
        + len(no_summary_pages) * 4
    )
    if not pages:
        score = 35 if sources else 60
    else:
        score = max(15, min(100, 100 - penalty))

    report = {
        "score": score,
        "total_pages": len(pages),
        "total_sources": len(sources),
        "orphan_pages": orphan_pages,
        "dangling_links": dangling_links,
        "pending_sources": pending_sources,
        "short_pages": short_pages,
        "no_summary_pages": no_summary_pages,
        "checked_at": _now_bj_str(),
    }
    next_log = _append_log(
        kb.get("log_md") or "",
        "lint",
        (
            f"Wiki 体检得分 {score}/100"
            f"（孤立 {len(orphan_pages)} / 死链 {len(dangling_links)} / 待编译 {len(pending_sources)}）"
        ),
    )
    await _repo_update_kb(
        kb_id,
        {
            "last_lint_score": score,
            "last_lint_report": report,
            "log_md": next_log,
        },
    )
    return report


async def publish_skill(
    kb_id: int,
    *,
    owner_scope: str,
    role: str,
    name: str = "",
    slug: str = "",
    description: str = "",
    triggers: list[str] | None = None,
    skill_md: str = "",
    version: str = "1.0.0",
    visibility: str | None = None,
    is_enabled: bool = True,
) -> dict[str, Any]:
    kb = await _require_kb(kb_id, owner_scope=owner_scope, role=role, write=True)
    pages = await _repo_list_pages(kb_id, include_content=False)
    existing = await _repo_get_skill_by_kb(kb_id)

    skill_name = (name or (existing["name"] if existing else "") or kb["name"]).strip()[:100]
    raw_desc = description or (existing["description"] if existing else "") or kb.get("description") or ""
    skill_desc = raw_desc.strip()[:500]
    if existing and not slug.strip():
        skill_slug = existing["slug"]
    else:
        skill_slug = await _repo_next_unique_slug(KBSkill, slug.strip() or kb["slug"] or skill_name)

    if triggers is not None and len(triggers) > 0:
        clean_triggers = [t.strip() for t in triggers if t.strip()][:30]
    elif existing and existing.get("triggers"):
        clean_triggers = existing["triggers"]
    else:
        # 自动从知识库名称与前 6 篇词条标题提取默认触发词
        auto_trigs = [skill_name]
        for p in pages[:6]:
            if p["page_type"] != "overview" and len(p["title"]) <= 20:
                auto_trigs.append(p["title"])
        clean_triggers = list(dict.fromkeys(auto_trigs))[:12]

    final_md = skill_md.strip()
    if not final_md:
        final_md = build_default_skill_md(
            name=skill_name,
            slug=skill_slug,
            description=skill_desc,
            kb_slug=kb["slug"],
            triggers=clean_triggers,
            version=version or "1.0.0",
            index_md=kb.get("index_md") or "",
            pages=pages,
        )

    final_vis = visibility if visibility in {"private", "public"} else kb["visibility"]
    saved = await _repo_upsert_skill(
        kb_id,
        {
            "slug": skill_slug,
            "name": skill_name,
            "description": skill_desc,
            "triggers": clean_triggers,
            "skill_md": final_md,
            "version": (version or "1.0.0")[:32],
            "owner_scope": kb["owner_scope"],
            "visibility": final_vis,
            "is_enabled": is_enabled,
        },
    )
    saved["kb_name"] = kb["name"]

    next_log = _append_log(
        kb.get("log_md") or "",
        "publish-skill",
        f"发布/更新 Skill「{skill_name}」(/skill:{skill_slug}, v{saved['version']})",
    )
    await _repo_update_kb(kb_id, {"log_md": next_log})
    return saved


async def update_skill(
    skill_id: int,
    patch: dict[str, Any],
    *,
    owner_scope: str,
    role: str,
) -> dict[str, Any]:
    skill = await _repo_get_skill(skill_id)
    if skill is None:
        raise BusinessException("Skill 不存在", code=40412, status_code=404)
    await _require_kb(int(skill["kb_id"]), owner_scope=owner_scope, role=role, write=True)
    clean_patch = {k: v for k, v in patch.items() if v is not None}
    updated = await _repo_update_skill(skill_id, clean_patch)
    assert updated is not None
    updated["kb_name"] = skill.get("kb_name", "")
    return updated


async def export_skill_zip(kb_id: int, *, owner_scope: str, role: str) -> tuple[str, bytes]:
    """将整个知识库（SKILL.md + SCHEMA.md + index.md + log.md + wiki/ + raw/ + manifest.json）打包为 .zip。"""
    kb = await _require_kb(kb_id, owner_scope=owner_scope, role=role, write=False)
    pages = await _repo_list_pages(kb_id, include_content=True)
    sources = await _repo_list_sources(kb_id, include_text=True)
    skill = await _repo_get_skill_by_kb(kb_id)

    skill_slug = skill["slug"] if skill else kb["slug"]
    skill_md = (
        skill["skill_md"]
        if skill and skill.get("skill_md")
        else build_default_skill_md(
            name=kb["name"],
            slug=skill_slug,
            description=kb.get("description") or "",
            kb_slug=kb["slug"],
            triggers=[],
            version="1.0.0",
            index_md=kb.get("index_md") or "",
            pages=pages,
        )
    )
    manifest = {
        "format": "ailove-llm-wiki-skill/v1",
        "exported_at": _now_bj_str(),
        "kb": {
            "slug": kb["slug"],
            "name": kb["name"],
            "description": kb.get("description") or "",
            "category": kb.get("category") or "general",
            "visibility": kb.get("visibility") or "private",
        },
        "skill": {
            "slug": skill_slug,
            "name": skill["name"] if skill else kb["name"],
            "version": skill["version"] if skill else "1.0.0",
            "triggers": skill.get("triggers", []) if skill else [],
        },
        "counts": {
            "raw_sources": len(sources),
            "wiki_pages": len(pages),
        },
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", skill_md)
        schema_content = kb.get("schema_md") or build_default_schema_md(
            kb["name"], kb.get("description", "")
        )
        zf.writestr("SCHEMA.md", schema_content)
        zf.writestr("index.md", kb.get("index_md") or build_index_md(kb["name"], pages))
        zf.writestr("log.md", kb.get("log_md") or "")
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

        for p in pages:
            path = p["page_path"].lstrip("/")
            if not path.startswith("wiki/"):
                path = f"wiki/{path}"
            zf.writestr(path, p.get("content_md") or "")

        used_raw_paths: set[str] = set()
        for s in sources:
            rel = (s.get("rel_path") or s["filename"]).lstrip("/")
            # 二进制上传时已提取纯文本正文，按可读扩展名保存避免扩展名与文本正文不匹配
            base_no_ext, ext = posixpath.splitext(rel)
            if ext.lower() in {".pdf", ".docx"}:
                rel = f"{base_no_ext}.extracted.md"
            raw_arc = f"raw/{rel}"
            if raw_arc in used_raw_paths:
                raw_arc = f"raw/{s['id']}_{posixpath.basename(rel)}"
            used_raw_paths.add(raw_arc)
            zf.writestr(raw_arc, s.get("raw_text") or "")

    return f"{skill_slug}-skill.zip", buf.getvalue()


async def import_skill_bundle(
    *,
    owner_scope: str,
    role: str,
    zip_bytes: bytes | None = None,
    file_entries: list[tuple[str, bytes]] | None = None,
    override_name: str = "",
    override_visibility: str = "private",
    auto_compile: bool = True,
    use_llm: bool = True,
) -> dict[str, Any]:
    """整包导入本地文件 + SKILL.md（支持 .zip 整包或目录多文件），自动建库编译并激活 Skill。"""
    if zip_bytes:
        parsed = parse_bundle_zip(zip_bytes)
    elif file_entries:
        parsed = classify_bundle_files(file_entries)
    else:
        raise BusinessException("请提供 .zip 整包或本地目录文件列表", code=40070)

    skill_md_raw = str(parsed.get("skill_md") or "").strip()
    fm, _ = parse_skill_md_frontmatter(skill_md_raw)
    manifest = parsed.get("manifest") or {}
    manifest_kb = manifest.get("kb") if isinstance(manifest.get("kb"), dict) else {}
    manifest_skill = manifest.get("skill") if isinstance(manifest.get("skill"), dict) else {}

    kb_name = (
        override_name.strip()
        or str(fm.get("name") or manifest_kb.get("name") or manifest_skill.get("name") or "").strip()
        or f"导入知识库 {_now_bj_str()}"
    )[:100]
    kb_desc = str(fm.get("description") or manifest_kb.get("description") or "").strip()[:500]
    desired_slug = str(fm.get("kb_slug") or fm.get("slug") or manifest_kb.get("slug") or kb_name)
    category = str(manifest_kb.get("category") or "general")[:32]
    vis = "public" if override_visibility == "public" else "private"

    kb = await create_kb(
        name=kb_name,
        slug=desired_slug,
        description=kb_desc,
        category=category,
        visibility=vis,
        schema_md=str(parsed.get("schema_md") or ""),
        owner_scope=owner_scope,
    )
    kb_id = int(kb["id"])

    raw_files: list[BundleFileEntry] = parsed.get("raw_files") or []
    wiki_files: list[dict[str, Any]] = parsed.get("wiki_files") or []
    has_prebuilt_wiki = len(wiki_files) > 0

    for rf in raw_files:
        await _repo_upsert_source(
            kb_id,
            rf,
            status_val="ingested" if has_prebuilt_wiki else "pending",
        )

    for wf in wiki_files:
        wpath = str(wf["page_path"])
        wtext = str(wf["text"])
        lower_path = wpath.lower()
        if "summaries/" in lower_path:
            ptype = "summary"
        elif "entities/" in lower_path:
            ptype = "entity"
        elif "insights/" in lower_path:
            ptype = "insight"
        elif lower_path.endswith("overview.md"):
            ptype = "overview"
        else:
            ptype = "concept"

        heading_match = re.search(r"^#\s+(.+)$", wtext, re.MULTILINE)
        fallback_title = posixpath.splitext(wf["filename"])[0]
        wtitle = heading_match.group(1).strip()[:200] if heading_match else fallback_title
        wslug = slugify_text(posixpath.splitext(wf["filename"])[0], fallback="page")
        await _repo_upsert_page(
            kb_id,
            page_path=wpath,
            slug=wslug,
            title=wtitle,
            page_type=ptype,
            summary=_extract_summary_line(wtext, 150),
            content_md=wtext,
            source_ids=[],
        )

    compile_res = None
    if not has_prebuilt_wiki and raw_files and auto_compile:
        compile_res = await compile_sources_into_wiki(
            kb_id,
            owner_scope=owner_scope,
            role=role,
            use_llm=use_llm,
        )
    else:
        existing_log = str(parsed.get("log_md") or kb.get("log_md") or "")
        await _repo_update_kb(kb_id, {"log_md": existing_log})
        kb = await _require_kb(kb_id, owner_scope=owner_scope, role=role, write=False)
        await _refresh_kb_index_and_overview(
            kb,
            log_op="import-bundle",
            log_detail=f"整包导入 {len(raw_files)} 份 raw/ 与 {len(wiki_files)} 篇 wiki/ 词条",
        )

    raw_trigs = (
        fm.get("triggers")
        if isinstance(fm.get("triggers"), list)
        else (manifest_skill.get("triggers") or [])
    )
    triggers = raw_trigs
    skill = await publish_skill(
        kb_id,
        owner_scope=owner_scope,
        role=role,
        name=str(fm.get("name") or manifest_skill.get("name") or kb_name),
        slug=str(fm.get("slug") or manifest_skill.get("slug") or ""),
        description=kb_desc,
        triggers=[str(t) for t in triggers],
        skill_md=skill_md_raw,
        version=str(fm.get("version") or manifest_skill.get("version") or "1.0.0"),
        visibility=vis,
        is_enabled=True,
    )
    final_detail = await get_kb_detail(kb_id, owner_scope=owner_scope, role=role)
    return {
        "kb": final_detail["kb"],
        "skill": skill,
        "imported_raw": len(raw_files),
        "imported_wiki": len(final_detail["pages"]),
        "compile_result": compile_res,
    }


# ---------------------------------------------------------------------------
# Skill Discovery & Grounded LLM Wiki Execution (for Chat / Mascot / MiniProgram)
# ---------------------------------------------------------------------------


async def list_callable_skills(*, owner_scope: str, role: str) -> list[dict[str, Any]]:
    all_skills = await _repo_list_skills()
    perms = await _role_permissions(role)
    can_admin_view = has_permission(perms, "kb:view") or has_permission(perms, "kb:manage")
    out: list[dict[str, Any]] = []
    for sk in all_skills:
        if not sk.get("is_enabled", True):
            continue
        if sk.get("visibility") == "public" or sk["owner_scope"] == owner_scope or can_admin_view:
            kb = await _repo_get_kb(int(sk["kb_id"]))
            item = dict(sk)
            item["kb_name"] = kb["name"] if kb else sk["name"]
            item["page_count"] = int(kb.get("page_count") or 0) if kb else 0
            item["source_count"] = int(kb.get("source_count") or 0) if kb else 0
            item["is_owner"] = sk["owner_scope"] == owner_scope
            out.append(item)
    return out


def _score_skill_match(skill: dict[str, Any], query: str, index_md: str) -> float:
    q_lower = query.lower()
    score = 0.0
    if skill["slug"].lower() in q_lower:
        score += 10.0
    if skill["name"].lower() in q_lower:
        score += 10.0
    for trig in skill.get("triggers") or []:
        t_clean = str(trig).strip().lower()
        if t_clean and t_clean in q_lower:
            score += 8.0

    q_tokens = _tokenize_query(query)
    trig_str = " ".join(skill.get("triggers") or [])
    haystack = f"{skill.get('description', '')} {trig_str} {index_md[:2500]}".lower()
    for tok in q_tokens:
        if tok in haystack:
            score += 2.5
    return score


def _retrieve_wiki_evidence(
    pages: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    query: str,
    *,
    top_k: int = 4,
) -> list[dict[str, Any]]:
    """沿 LLM Wiki 页面评分 + 1 跳 [[wikilinks]] 图谱扩展收集引用证据。"""
    q_tokens = _tokenize_query(query)
    q_lower = query.lower()

    scored: list[tuple[float, dict[str, Any]]] = []
    page_by_key: dict[str, dict[str, Any]] = {}
    for p in pages:
        page_by_key[str(p["title"]).strip().lower()] = p
        page_by_key[str(p["slug"]).strip().lower()] = p

        score = 0.0
        title_l = str(p.get("title") or "").lower()
        slug_l = str(p.get("slug") or "").lower()
        summary_l = str(p.get("summary") or "").lower()
        content_l = str(p.get("content_md") or "").lower()

        if title_l and title_l in q_lower:
            score += 12.0
        for tok in q_tokens:
            if tok in title_l:
                score += 4.0
            if tok in slug_l:
                score += 3.0
            if tok in summary_l:
                score += 2.5
            if tok in content_l:
                score += 1.0
        if p.get("page_type") == "insight" and score > 0:
            score += 1.5
        scored.append((score, p))

    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    picked: list[tuple[float, dict[str, Any], str]] = []
    picked_ids: set[int] = set()

    for sc, p in scored[:top_k]:
        if sc > 0 or len(picked) == 0:
            picked.append((round(sc, 1), p, "direct"))
            picked_ids.add(int(p["id"]))

    # 若页面全部未直接匹配但处于显式调用模式，补充 overview + 前几篇保证上下文有效
    if not picked and pages:
        for p in pages[:top_k]:
            picked.append((0.0, p, "overview"))
            picked_ids.add(int(p["id"]))

    # 1-hop [[wikilinks]] 扩展最多 2 篇关联页面
    hop_added = 0
    for _, base_p, _ in list(picked):
        if hop_added >= 2:
            break
        links = base_p.get("links") or extract_wikilinks(base_p.get("content_md") or "")
        for target in links:
            neighbor = page_by_key.get(target.strip().lower())
            if neighbor and int(neighbor["id"]) not in picked_ids:
                picked.append((0.5, neighbor, "wikilink"))
                picked_ids.add(int(neighbor["id"]))
                hop_added += 1
                if hop_added >= 2:
                    break

    evidence: list[dict[str, Any]] = []
    for sc, p, via in picked:
        evidence.append(
            {
                "page_id": int(p["id"]),
                "page_path": p["page_path"],
                "title": p["title"],
                "page_type": p["page_type"],
                "summary": p.get("summary") or "",
                "score": sc,
                "via": via,
                "content_md": str(p.get("content_md") or "")[:1400],
                "excerpt": _extract_summary_line(p.get("content_md") or p.get("summary") or "", 180),
            }
        )

    # 若 Wiki 尚未编译（0 页），平滑回退到 raw/ 原始材料
    if not evidence and sources:
        for s in sources[:2]:
            txt = str(s.get("raw_text") or "")
            evidence.append(
                {
                    "page_id": 0,
                    "page_path": f"raw/{s.get('rel_path') or s['filename']}",
                    "title": s["filename"],
                    "page_type": "raw_fallback",
                    "summary": _extract_summary_line(txt, 140),
                    "score": 1.0,
                    "via": "raw_fallback",
                    "content_md": txt[:1500],
                    "excerpt": _extract_summary_line(txt, 180),
                }
            )
    return evidence


async def test_skill_query(
    skill_id: int,
    *,
    query: str,
    top_k: int = 4,
    owner_scope: str,
    role: str,
) -> dict[str, Any]:
    skill = await _repo_get_skill(skill_id)
    if skill is None:
        raise BusinessException("Skill 不存在", code=40412, status_code=404)
    kb = await _require_kb(int(skill["kb_id"]), owner_scope=owner_scope, role=role, write=False)
    pages = await _repo_list_pages(int(kb["id"]), include_content=True)
    sources = await _repo_list_sources(int(kb["id"]), include_text=True)
    evidence = _retrieve_wiki_evidence(pages, sources, query, top_k=top_k)
    return {
        "skill": skill,
        "kb_name": kb["name"],
        "query": query,
        "citations": evidence,
    }


async def resolve_and_execute_skills(
    user_message: str,
    *,
    owner_scope: str,
    role: str,
    skill_ids: list[int] | None = None,
    auto_match_skills: bool = True,
) -> tuple[list[str], list[dict[str, Any]]]:
    """在 AI 对话/流式回复前自动或显式调用已挂载的知识库 Skill，组装 Grounded Wiki 上下文与引用溯源。"""
    callable_skills = await list_callable_skills(owner_scope=owner_scope, role=role)
    if not callable_skills:
        return [], []

    skill_by_id = {int(s["id"]): s for s in callable_skills}
    skill_by_slug = {str(s["slug"]).lower(): s for s in callable_skills}

    chosen: list[tuple[dict[str, Any], str]] = []
    seen_ids: set[int] = set()

    # 1. 显式传入 skill_ids
    for sid in (skill_ids or [])[:3]:
        sk = skill_by_id.get(int(sid))
        if sk and int(sk["id"]) not in seen_ids:
            chosen.append((sk, "manual"))
            seen_ids.add(int(sk["id"]))

    # 2. 解析 /skill:<slug> 命令
    for match in _SKILL_CMD_RE.finditer(user_message or ""):
        slug_key = match.group(1).lower()
        sk = skill_by_slug.get(slug_key)
        if sk and int(sk["id"]) not in seen_ids:
            chosen.append((sk, "command"))
            seen_ids.add(int(sk["id"]))
            if len(chosen) >= 3:
                break

    # 3. 无显式指定时按触发词与 index.md 相关性自动路由
    if not chosen and auto_match_skills:
        scored_skills: list[tuple[float, dict[str, Any]]] = []
        for sk in callable_skills:
            kb = await _repo_get_kb(int(sk["kb_id"]))
            sc = _score_skill_match(sk, user_message, kb.get("index_md", "") if kb else "")
            if sc >= 6.0:
                scored_skills.append((sc, sk))
        scored_skills.sort(key=lambda pair: (-pair[0], -int(pair[1]["id"])))
        for _, sk in scored_skills[:2]:
            chosen.append((sk, "auto_trigger"))

    if not chosen:
        return [], []

    blocks: list[str] = []
    invoked_meta: list[dict[str, Any]] = []

    for sk, reason in chosen[:3]:
        kb_id = int(sk["kb_id"])
        kb = await _repo_get_kb(kb_id)
        if kb is None:
            continue
        pages = await _repo_list_pages(kb_id, include_content=True)
        sources = await _repo_list_sources(kb_id, include_text=True)
        evidence = _retrieve_wiki_evidence(pages, sources, user_message, top_k=4)

        _, skill_body = parse_skill_md_frontmatter(sk.get("skill_md") or "")
        skill_inst = (skill_body or sk.get("skill_md") or "")[:900]
        index_preview = (kb.get("index_md") or "")[:650]

        evidence_parts: list[str] = []
        budget = 3200
        for ev in evidence:
            snippet = f"### [词条] {ev['title']} ({ev['page_path']})\n{ev['content_md']}\n"
            if len(snippet) > budget and evidence_parts:
                break
            evidence_parts.append(snippet[:budget])
            budget -= len(snippet[:budget])
            if budget <= 180:
                break

        block = (
            f"【已调用知识库 Skill：{sk['name']} (/skill:{sk['slug']})】\n"
            f"技能指令摘要：\n{skill_inst}\n\n"
            f"知识目录概览 (index.md)：\n{index_preview}\n\n"
            f"命中 Wiki 词条上下文：\n{''.join(evidence_parts)}\n"
            "引用规则：回答优先依据上述命中 Wiki 词条内容，并在相关结论后使用 [词条标题] 标明出处；"
            "若词条未涵盖具体细节，请诚实说明。"
        )
        blocks.append(block)
        await _repo_inc_skill_usage(int(sk["id"]))

        invoked_meta.append(
            {
                "id": int(sk["id"]),
                "slug": sk["slug"],
                "name": sk["name"],
                "kb_id": kb_id,
                "kb_name": kb["name"],
                "match_reason": reason,
                "citations": [
                    {
                        "page_id": ev["page_id"],
                        "page_path": ev["page_path"],
                        "title": ev["title"],
                        "page_type": ev["page_type"],
                        "score": ev["score"],
                        "via": ev["via"],
                        "excerpt": ev["excerpt"],
                    }
                    for ev in evidence
                ],
            }
        )

    return blocks, invoked_meta
