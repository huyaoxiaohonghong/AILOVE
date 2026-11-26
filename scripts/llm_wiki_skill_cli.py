#!/usr/bin/env python3
"""
AILOVE LLM Wiki + Skill 本地打包与云端整包上传 CLI 工具

用法示例：
  1. 将本地文件目录打包为标准 LLM Wiki + SKILL.md 整包：
     python3 scripts/llm_wiki_skill_cli.py build ./my_docs --name "恋爱沟通宝典" --triggers "沟通,约会,暧昧" --out ./love-skill.zip

  2. 将打包好的 zip（或直接把本地文件目录）上传到云平台并自动激活为可调用 Skill：
     python3 scripts/llm_wiki_skill_cli.py upload ./love-skill.zip --server http://127.0.0.1:8000 --token "$AILOVE_TOKEN" --visibility private
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import posixpath
import re
import sys
import urllib.error
import urllib.request
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

SUPPORTED_EXTS = {".md", ".markdown", ".txt", ".csv", ".json", ".html", ".htm"}


def _slugify(text: str, fallback: str = "skill") -> str:
    clean = text.strip().lower()
    ascii_part = re.sub(r"[^a-z0-9_-]+", "-", clean).strip("-_")
    digest = hashlib.sha1(clean.encode("utf-8")).hexdigest()[:6] if clean else "000000"
    if len(ascii_part) >= 3:
        if any(ord(ch) > 127 for ch in clean):
            return f"{ascii_part[:36]}-{digest}"
        return ascii_part[:48]
    return f"{fallback}-{digest}"


def _extract_summary(text: str, max_len: int = 140) -> str:
    flat = re.sub(r"\s+", " ", re.sub(r"[#>*`\[\]]", "", text or "")).strip()
    return flat[:max_len] + ("…" if len(flat) > max_len else "")


def build_bundle_bytes(
    source_dir: Path,
    *,
    name: str,
    slug: str = "",
    description: str = "",
    triggers: list[str] | None = None,
) -> tuple[bytes, dict]:
    if not source_dir.is_dir():
        raise FileNotFoundError(f"源目录不存在：{source_dir}")

    kb_slug = slug.strip() or _slugify(name, fallback="kb")
    trig_list = [t.strip() for t in (triggers or []) if t.strip()]
    existing_skill_md = ""
    existing_schema_md = ""

    raw_files: list[tuple[str, str]] = []
    for root, dirs, files in os.walk(source_dir):
        dirs[:] = [d for d in sorted(dirs) if d not in {".git", "__pycache__", "node_modules", "wiki"}]
        for fname in sorted(files):
            if fname.startswith("."):
                continue
            fpath = Path(root) / fname
            rel = fpath.relative_to(source_dir).as_posix()
            lower = rel.lower()
            if lower == "skill.md":
                existing_skill_md = fpath.read_text(encoding="utf-8", errors="replace")
                continue
            if lower in {"schema.md", "agents.md", "claude.md"}:
                existing_schema_md = fpath.read_text(encoding="utf-8", errors="replace")
                continue
            if fpath.suffix.lower() in SUPPORTED_EXTS:
                raw_files.append((rel, fpath.read_text(encoding="utf-8", errors="replace")))

    if not raw_files:
        raise RuntimeError(f"目录 {source_dir} 下未找到支持的文件 ({', '.join(sorted(SUPPORTED_EXTS))})")

    wiki_pages: list[tuple[str, str, str, str]] = []
    for rel, text in raw_files:
        base_title = posixpath.splitext(posixpath.basename(rel))[0]
        m1 = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = m1.group(1).strip()[:120] if m1 else base_title
        pslug = _slugify(title, fallback="doc")
        summary = _extract_summary(text, 140)
        wiki_content = (
            f"# {title}\n\n"
            f"> 原始来源：`raw/{rel}`\n\n"
            f"## 摘要\n{summary}\n\n"
            f"## 原文要点\n{text[:4000]}\n"
        )
        wiki_pages.append((f"wiki/summaries/{pslug}.md", title, summary, wiki_content))

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    schema_md = existing_schema_md or (
        f"# {name} · LLM Wiki Schema\n\n"
        f"> {description or '本地打包生成并同步至 AILOVE 云平台的知识库'}\n\n"
        "- `raw/`：不可变原始文件\n"
        "- `wiki/`：结构化互链词条\n"
        "- `index.md` / `log.md`：全库索引与时间线操作日志\n"
    )
    index_lines = [f"# {name} · 知识索引 (index.md)", "", f"> 生成时间：{now_str}", "", "## 原始资料精要 (Summaries)"]
    for wpath, title, summary, _ in wiki_pages:
        index_lines.append(f"- [[{title}]] (`{wpath}`) — {summary}")
    index_md = "\n".join(index_lines) + "\n"
    log_md = f"# LLM Wiki Operation Log\n\n## [{now_str}] cli-build | 打包 {len(raw_files)} 份本地资料与 {len(wiki_pages)} 篇 Wiki 词条\n"

    if existing_skill_md:
        skill_md = existing_skill_md
    else:
        trig_yaml = json.dumps(trig_list, ensure_ascii=False)
        skill_md = (
            f"---\n"
            f"name: {name}\n"
            f"slug: {kb_slug}\n"
            f"description: {description or f'调用「{name}」知识库内容回答相关问题'}\n"
            f"version: 1.0.0\n"
            f"kb_slug: {kb_slug}\n"
            f"triggers: {trig_yaml}\n"
            f"---\n\n"
            f"# {name} · 知识库 Skill\n\n"
            f"当用户提问涉及以下主题时，先检索 `index.md` 与对应 `wiki/` 词条，再用 `[词条标题]` 标明引用出处。\n\n"
            f"## 词条速览\n"
            + "\n".join(f"- [[{t}]]：{s}" for _, t, s, _ in wiki_pages[:20])
            + "\n"
        )

    manifest = {
        "format": "ailove-llm-wiki-skill/v1",
        "built_at": now_str,
        "kb": {"slug": kb_slug, "name": name, "description": description},
        "skill": {"slug": kb_slug, "name": name, "version": "1.0.0", "triggers": trig_list},
        "counts": {"raw_sources": len(raw_files), "wiki_pages": len(wiki_pages)},
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", skill_md)
        zf.writestr("SCHEMA.md", schema_md)
        zf.writestr("index.md", index_md)
        zf.writestr("log.md", log_md)
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for rel, text in raw_files:
            zf.writestr(f"raw/{rel}", text)
        for wpath, _, _, content in wiki_pages:
            zf.writestr(wpath, content)

    return buf.getvalue(), manifest


def _post_multipart_zip(server: str, token: str, zip_bytes: bytes, zip_name: str, fields: dict[str, str]) -> dict:
    boundary = f"----AILOVEBoundary{uuid.uuid4().hex}"
    body = io.BytesIO()

    for k, v in fields.items():
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8"))

    body.write(f"--{boundary}\r\n".encode())
    body.write(f'Content-Disposition: form-data; name="bundle_zip"; filename="{zip_name}"\r\n'.encode("utf-8"))
    body.write(b"Content-Type: application/zip\r\n\r\n")
    body.write(zip_bytes)
    body.write(f"\r\n--{boundary}--\r\n".encode())

    url = server.rstrip("/") + "/api/v1/kb/import-bundle"
    req = urllib.request.Request(
        url,
        data=body.getvalue(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="AILOVE LLM Wiki + Skill 本地打包上传工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="将本地目录打包为 LLM Wiki + SKILL.md 整包 (.zip)")
    p_build.add_argument("source_dir", type=Path, help="本地文件目录")
    p_build.add_argument("--name", required=True, help="知识库与 Skill 名称")
    p_build.add_argument("--slug", default="", help="可选唯一触发 slug")
    p_build.add_argument("--description", default="", help="知识库简介")
    p_build.add_argument("--triggers", default="", help="逗号分隔的触发关键词")
    p_build.add_argument("--out", type=Path, default=None, help="输出 zip 路径")

    p_up = sub.add_parser("upload", help="上传 .zip 整包或本地目录至云端知识库并激活 Skill")
    p_up.add_argument("target", type=Path, help=".zip 文件路径或本地目录")
    p_up.add_argument("--server", required=True, help="云平台服务地址（如 http://localhost:8000）")
    p_up.add_argument("--token", required=True, help="登录后的 JWT Access Token")
    p_up.add_argument("--name", default="", help="可选覆盖知识库/Skill 名称")
    p_up.add_argument("--visibility", choices=["private", "public"], default="private")
    p_up.add_argument("--auto-compile", action="store_true", default=True)

    args = parser.parse_args()
    if args.cmd == "build":
        trigs = [t.strip() for t in args.triggers.split(",") if t.strip()]
        zip_bytes, manifest = build_bundle_bytes(
            args.source_dir,
            name=args.name,
            slug=args.slug,
            description=args.description,
            triggers=trigs,
        )
        out_path = args.out or Path(f"{manifest['skill']['slug']}-skill.zip")
        out_path.write_bytes(zip_bytes)
        print(
            json.dumps(
                {
                    "out": str(out_path),
                    "size_bytes": len(zip_bytes),
                    "skill_slug": manifest["skill"]["slug"],
                    "counts": manifest["counts"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.cmd == "upload":
        target: Path = args.target
        if target.is_dir():
            kb_name = args.name.strip() or target.name
            zip_bytes, manifest = build_bundle_bytes(target, name=kb_name)
            zip_name = f"{manifest['skill']['slug']}-skill.zip"
        elif target.is_file():
            zip_bytes = target.read_bytes()
            zip_name = target.name
        else:
            print(f"目标不存在：{target}", file=sys.stderr)
            return 1

        res = _post_multipart_zip(
            args.server,
            args.token,
            zip_bytes,
            zip_name,
            fields={
                "name": args.name,
                "visibility": args.visibility,
                "auto_compile": "true" if args.auto_compile else "false",
                "use_llm": "true",
            },
        )
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
