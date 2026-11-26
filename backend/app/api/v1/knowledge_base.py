from __future__ import annotations

import hashlib
import json
import posixpath
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from app.api.deps import get_current_token_payload
from app.core.exceptions import BusinessException
from app.core.rate_limit import rate_limit
from app.schemas.common import ok
from app.schemas.knowledge_base import (
    KBBaseCreate,
    KBBaseUpdate,
    KBCompileRequest,
    KBInsightCreateRequest,
    KBPageUpdateRequest,
    KBSkillPublishRequest,
    KBSkillTestQueryRequest,
    KBSkillUpdateRequest,
)
from app.services import kb_wiki_service
from app.services.kb_file_parser import BundleFileEntry, extract_text_from_file, sanitize_rel_path
from app.services.llm_service import build_owner_scope

router = APIRouter(prefix="/kb", tags=["LLM Wiki 知识库与 Skill"])


def _resolve_actor(current_user: dict[str, Any]) -> tuple[str, str]:
    user_type = str(current_user.get("type", "web"))
    raw_sub = str(current_user.get("sub", "0")).strip()
    if raw_sub.isdigit():
        uid = int(raw_sub)
    else:
        seed = raw_sub or str(current_user.get("openid", "")).strip()
        if seed:
            hashed = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12], 16)
            uid = 1_000_000 + (hashed % 1_000_000_000)
        else:
            uid = 0
    role = str(current_user.get("role") or "user")
    return build_owner_scope(user_type, uid), role


@router.get("/bases", summary="获取当前用户可见的知识库列表")
async def list_kb_bases(current_user: dict[str, Any] = Depends(get_current_token_payload)):
    owner_scope, role = _resolve_actor(current_user)
    items = await kb_wiki_service.list_kbs(owner_scope=owner_scope, role=role)
    return ok({"items": items})


@router.post("/bases", summary="创建 LLM Wiki 知识库")
async def create_kb_base(
    req: KBBaseCreate,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, _ = _resolve_actor(current_user)
    kb = await kb_wiki_service.create_kb(
        name=req.name,
        slug=req.slug,
        description=req.description,
        category=req.category,
        visibility=req.visibility,
        schema_md=req.schema_md,
        owner_scope=owner_scope,
    )
    return ok(kb, message="LLM Wiki 知识库已创建")


@router.get("/bases/{kb_id}", summary="获取知识库详情（raw/ 源文件、wiki/ 词条、SCHEMA/index/log 与 Skill）")
async def get_kb_base_detail(
    kb_id: int,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    detail = await kb_wiki_service.get_kb_detail(kb_id, owner_scope=owner_scope, role=role)
    return ok(detail)


@router.patch("/bases/{kb_id}", summary="更新知识库基础信息或 SCHEMA.md")
async def update_kb_base(
    kb_id: int,
    req: KBBaseUpdate,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    updated = await kb_wiki_service.update_kb(
        kb_id,
        req.model_dump(exclude_none=True),
        owner_scope=owner_scope,
        role=role,
    )
    return ok(updated, message="知识库信息已更新")


@router.delete("/bases/{kb_id}", summary="删除知识库及其所有 Wiki 词条与 Skill")
async def delete_kb_base(
    kb_id: int,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    deleted = await kb_wiki_service.delete_kb(kb_id, owner_scope=owner_scope, role=role)
    if not deleted:
        raise BusinessException("知识库不存在", code=40410, status_code=404)
    return ok({"deleted_id": kb_id}, message="知识库已删除")


@router.post("/bases/{kb_id}/sources", summary="上传本地文件到知识库 raw/ 层")
async def upload_kb_sources(
    kb_id: int,
    files: list[UploadFile] = File(...),
    rel_paths_json: str = Form(default="[]"),
    auto_compile: bool = Form(default=False),
    use_llm: bool = Form(default=True),
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    try:
        rel_paths = json.loads(rel_paths_json or "[]")
        if not isinstance(rel_paths, list):
            rel_paths = []
    except json.JSONDecodeError:
        rel_paths = []

    entries: list[BundleFileEntry] = []
    for idx, up in enumerate(files):
        raw_bytes = await up.read()
        raw_name = up.filename or f"document_{idx + 1}.txt"
        rel_raw = str(rel_paths[idx]) if idx < len(rel_paths) and rel_paths[idx] else raw_name
        clean_rel = sanitize_rel_path(rel_raw)
        basename = posixpath.basename(clean_rel)
        text, mime = extract_text_from_file(basename, raw_bytes)
        entries.append(
            BundleFileEntry(
                rel_path=clean_rel,
                filename=basename,
                raw_bytes=raw_bytes,
                text=text,
                sha256=hashlib.sha256(raw_bytes).hexdigest(),
                mime_type=mime,
            )
        )

    res = await kb_wiki_service.upload_sources(
        kb_id,
        entries,
        owner_scope=owner_scope,
        role=role,
        auto_compile=auto_compile,
        use_llm=use_llm,
    )
    return ok(res, message=f"成功上传 {res['uploaded']} 份原始文件")


@router.delete("/bases/{kb_id}/sources/{source_id}", summary="删除 raw/ 原始文件记录")
async def delete_kb_source(
    kb_id: int,
    source_id: int,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    deleted = await kb_wiki_service.delete_source(
        kb_id, source_id, owner_scope=owner_scope, role=role
    )
    if not deleted:
        raise BusinessException("源文件不存在", code=40413, status_code=404)
    return ok({"deleted_id": source_id}, message="原始文件已移除")


@router.post(
    "/bases/{kb_id}/compile",
    summary="LLM Wiki Ingest：将 raw/ 原始文件编译为互链 Markdown 知识词条",
    dependencies=[Depends(rate_limit("kb_compile", limit=20, window_seconds=60, by_user=True))],
)
async def compile_kb_wiki(
    kb_id: int,
    req: KBCompileRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    res = await kb_wiki_service.compile_sources_into_wiki(
        kb_id,
        owner_scope=owner_scope,
        role=role,
        source_ids=req.source_ids or None,
        use_llm=req.use_llm,
        config_id=req.config_id,
        recompile_all=req.recompile_all,
    )
    return ok(
        res,
        message=f"已完成编译：{res['compiled_sources']} 份资料 -> 生成 {res['generated_pages']} 篇 Wiki 词条",
    )


@router.get("/bases/{kb_id}/pages/{page_id}", summary="读取单篇 Wiki 词条正文与关联链接")
async def get_kb_wiki_page(
    kb_id: int,
    page_id: int,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    page = await kb_wiki_service.get_wiki_page(kb_id, page_id, owner_scope=owner_scope, role=role)
    return ok(page)


@router.put("/bases/{kb_id}/pages/{page_id}", summary="在线修订 Wiki 词条内容并同步更新 index.md")
async def update_kb_wiki_page(
    kb_id: int,
    page_id: int,
    req: KBPageUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    page = await kb_wiki_service.update_wiki_page(
        kb_id,
        page_id,
        req.model_dump(exclude_none=True),
        owner_scope=owner_scope,
        role=role,
    )
    return ok(page, message="Wiki 词条已保存并刷新索引")


@router.delete("/bases/{kb_id}/pages/{page_id}", summary="删除单篇 Wiki 词条")
async def delete_kb_wiki_page(
    kb_id: int,
    page_id: int,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    deleted = await kb_wiki_service.delete_wiki_page(kb_id, page_id, owner_scope=owner_scope, role=role)
    if not deleted:
        raise BusinessException("Wiki 词条不存在", code=40411, status_code=404)
    return ok({"deleted_id": page_id}, message="词条已删除")


@router.post("/bases/{kb_id}/lint", summary="LLM Wiki Lint：检查孤立词条、死链与未编译文件")
async def lint_kb_wiki(
    kb_id: int,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    report = await kb_wiki_service.lint_wiki(kb_id, owner_scope=owner_scope, role=role)
    return ok(report, message=f"Wiki 体检完成，综合健康度 {report['score']} 分")


@router.post("/bases/{kb_id}/insights", summary="将高价值问答结论回流沉淀至 wiki/insights/")
async def file_kb_insight(
    kb_id: int,
    req: KBInsightCreateRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    res = await kb_wiki_service.file_insight_to_wiki(
        kb_id,
        title=req.title,
        content=req.content,
        source_question=req.source_question,
        owner_scope=owner_scope,
        role=role,
    )
    return ok(res, message="已将该洞察沉淀进 Wiki 知识库")


@router.post("/bases/{kb_id}/skill/publish", summary="将知识库打包生成 SKILL.md 并发布为可调用 Skill")
async def publish_kb_skill(
    kb_id: int,
    req: KBSkillPublishRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    skill = await kb_wiki_service.publish_skill(
        kb_id,
        owner_scope=owner_scope,
        role=role,
        name=req.name,
        slug=req.slug,
        description=req.description,
        triggers=req.triggers,
        skill_md=req.skill_md,
        version=req.version,
        visibility=req.visibility,
        is_enabled=req.is_enabled,
    )
    return ok(skill, message=f"Skill「{skill['name']}」已发布并激活")


@router.patch("/skills/{skill_id}", summary="更新已发布的知识库 Skill 配置或启停状态")
async def update_kb_skill(
    skill_id: int,
    req: KBSkillUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    skill = await kb_wiki_service.update_skill(
        skill_id,
        req.model_dump(exclude_none=True),
        owner_scope=owner_scope,
        role=role,
    )
    return ok(skill, message="Skill 配置已更新")


@router.get("/bases/{kb_id}/export-skill", summary="导出完整 LLM Wiki + SKILL.md 便携压缩包 (.zip)")
async def export_kb_skill_zip(
    kb_id: int,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    filename, zip_bytes = await kb_wiki_service.export_skill_zip(
        kb_id, owner_scope=owner_scope, role=role
    )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.post(
    "/import-bundle",
    summary="整包上传本地文件 + SKILL.md（支持 .zip 整包或本地文件夹多文件），自动建库编译并激活调用",
)
async def import_kb_skill_bundle(
    bundle_zip: UploadFile | None = File(default=None),
    files: list[UploadFile] = File(default=[]),
    rel_paths_json: str = Form(default="[]"),
    name: str = Form(default=""),
    visibility: str = Form(default="private"),
    auto_compile: bool = Form(default=True),
    use_llm: bool = Form(default=True),
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    zip_bytes: bytes | None = None
    file_entries: list[tuple[str, bytes]] = []

    if bundle_zip is not None and bundle_zip.filename:
        zip_bytes = await bundle_zip.read()
    elif files:
        try:
            rel_paths = json.loads(rel_paths_json or "[]")
            if not isinstance(rel_paths, list):
                rel_paths = []
        except json.JSONDecodeError:
            rel_paths = []
        for idx, up in enumerate(files):
            raw_bytes = await up.read()
            fallback_name = up.filename or f"file_{idx + 1}.txt"
            rel = str(rel_paths[idx]) if idx < len(rel_paths) and rel_paths[idx] else fallback_name
            file_entries.append((rel, raw_bytes))
    else:
        raise BusinessException("请上传 .zip 整包或选择包含文件与 SKILL.md 的本地目录", code=40070)

    res = await kb_wiki_service.import_skill_bundle(
        owner_scope=owner_scope,
        role=role,
        zip_bytes=zip_bytes,
        file_entries=file_entries or None,
        override_name=name,
        override_visibility=visibility,
        auto_compile=auto_compile,
        use_llm=use_llm,
    )
    return ok(
        res,
        message=f"整包导入成功！Skill「{res['skill']['name']}」(/skill:{res['skill']['slug']}) 已立即可用",
    )


@router.get("/skills", summary="获取当前用户可在对话中调用的全部已激活 Skill 列表")
async def list_callable_kb_skills(current_user: dict[str, Any] = Depends(get_current_token_payload)):
    owner_scope, role = _resolve_actor(current_user)
    items = await kb_wiki_service.list_callable_skills(owner_scope=owner_scope, role=role)
    return ok({"items": items})


@router.post("/skills/{skill_id}/test-query", summary="在线测试 Skill 对 LLM Wiki 词条的检索命中与引用结果")
async def test_kb_skill_query(
    skill_id: int,
    req: KBSkillTestQueryRequest,
    current_user: dict[str, Any] = Depends(get_current_token_payload),
):
    owner_scope, role = _resolve_actor(current_user)
    res = await kb_wiki_service.test_skill_query(
        skill_id,
        query=req.query,
        top_k=req.top_k,
        owner_scope=owner_scope,
        role=role,
    )
    return ok(res)
