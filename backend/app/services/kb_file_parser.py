from __future__ import annotations

import hashlib
import io
import json
import posixpath
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any
from xml.etree import ElementTree

import yaml
from pypdf import PdfReader

from app.core.exceptions import BusinessException

MAX_SINGLE_FILE_BYTES = 10 * 1024 * 1024
MAX_BUNDLE_ZIP_BYTES = 20 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 30 * 1024 * 1024
MAX_BUNDLE_FILES = 120
MAX_EXTRACTED_CHARS = 120_000

ALLOWED_RAW_EXTENSIONS = {
    ".md",
    ".markdown",
    ".txt",
    ".csv",
    ".json",
    ".html",
    ".htm",
    ".docx",
    ".pdf",
}

_WIKILINK_RE = re.compile(r"\[\[([^\]|#\n]+)(?:#[^\]|\n]+)?(?:\|[^\]\n]+)?\]\]")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_SLUG_ASCII_RE = re.compile(r"[^a-z0-9_-]+")
_SKIP_PARTS = {"__MACOSX", ".git", ".svn", "node_modules"}


@dataclass
class BundleFileEntry:
    rel_path: str
    filename: str
    raw_bytes: bytes
    text: str
    sha256: str
    mime_type: str


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        if t in {"script", "style", "noscript"}:
            self._skip_depth += 1
        elif t in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1
        elif t in {"p", "h1", "h2", "h3", "h4", "li"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self._chunks.append(data)

    def get_text(self) -> str:
        joined = "".join(self._chunks)
        lines = [line.strip() for line in joined.splitlines()]
        return "\n".join(line for line in lines if line)


def sanitize_rel_path(raw_path: str) -> str:
    """规范化并严格校验相对路径，拦截 ../、绝对路径与系统隐藏目录。"""
    candidate = (raw_path or "").replace("\\", "/").strip()
    if not candidate:
        raise BusinessException("文件路径不能为空", code=40070)
    if candidate.startswith("/") or re.match(r"^[A-Za-z]:", candidate):
        raise BusinessException(f"非法绝对路径：{raw_path}", code=40071)
    if "\x00" in candidate:
        raise BusinessException("文件路径包含非法空字符", code=40071)

    parts = [p for p in candidate.split("/") if p not in {"", "."}]
    if not parts or any(p == ".." for p in parts):
        raise BusinessException(f"检测到路径穿越风险：{raw_path}", code=40071)

    normalized = posixpath.normpath("/".join(parts))
    if normalized.startswith("../") or normalized == "..":
        raise BusinessException(f"检测到路径穿越风险：{raw_path}", code=40071)
    return normalized


def should_skip_bundle_path(rel_path: str) -> bool:
    parts = rel_path.split("/")
    base = parts[-1]
    if base in {".DS_Store", "Thumbs.db"} or base.startswith("._"):
        return True
    return any(part in _SKIP_PARTS for part in parts)


def slugify_text(text: str, *, fallback: str = "item", max_len: int = 56) -> str:
    """生成稳定、URL/路径安全的 ASCII slug（中文标题自动附带短哈希避免碰撞）。"""
    clean = (text or "").strip().lower()
    ascii_part = _SLUG_ASCII_RE.sub("-", clean).strip("-_")
    digest = hashlib.sha1(clean.encode("utf-8")).hexdigest()[:6] if clean else "000000"
    if len(ascii_part) >= 3:
        base = ascii_part[: max(8, max_len - 7)]
        # 若原始文本包含非 ASCII 字符（如中文），附加短哈希避免两个不同中文词条撞 slug
        if any(ord(ch) > 127 for ch in clean):
            return f"{base}-{digest}"[:max_len]
        return base[:max_len]
    return f"{fallback}-{digest}"[:max_len]


def extract_wikilinks(md_text: str) -> list[str]:
    """按出现顺序去重提取 Markdown 中的 [[wikilinks]] 目标词条名。"""
    seen: set[str] = set()
    out: list[str] = []
    for match in _WIKILINK_RE.finditer(md_text or ""):
        target = match.group(1).strip()
        if target and target not in seen:
            seen.add(target)
            out.append(target)
    return out


def parse_skill_md_frontmatter(md_text: str) -> tuple[dict[str, Any], str]:
    """解析 SKILL.md 顶部的 YAML Frontmatter 元数据与正文。"""
    text = (md_text or "").lstrip("\ufeff")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    yaml_raw, body = match.group(1), match.group(2)
    try:
        loaded = yaml.safe_load(yaml_raw) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(loaded, dict):
        return {}, text
    triggers_raw = loaded.get("triggers")
    if isinstance(triggers_raw, str):
        triggers = [t.strip() for t in re.split(r"[,，\s]+", triggers_raw) if t.strip()]
    elif isinstance(triggers_raw, list):
        triggers = [str(t).strip() for t in triggers_raw if str(t).strip()]
    else:
        triggers = []
    loaded["triggers"] = triggers[:30]
    return loaded, body.strip()


def decode_text_bytes(raw_bytes: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin-1"):
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def extract_text_from_file(filename: str, raw_bytes: bytes) -> tuple[str, str]:
    """根据扩展名提取文件正文文本，返回 (extracted_text, mime_label)。"""
    if len(raw_bytes) > MAX_SINGLE_FILE_BYTES:
        raise BusinessException(
            f"文件「{filename}」超过单文件大小上限（{MAX_SINGLE_FILE_BYTES // (1024 * 1024)} MB）",
            code=40072,
        )
    ext = posixpath.splitext(filename.lower())[1]
    if ext not in ALLOWED_RAW_EXTENSIONS:
        supported = ", ".join(sorted(ALLOWED_RAW_EXTENSIONS))
        raise BusinessException(f"暂不支持的文件类型「{ext or '未知'}」，支持：{supported}", code=40073)

    if ext == ".pdf":
        try:
            reader = PdfReader(io.BytesIO(raw_bytes))
            if reader.is_encrypted:
                raise BusinessException(f"PDF 文件「{filename}」已加密，请解密后再上传", code=40074)
            pages = [(page.extract_text() or "").strip() for page in reader.pages]
            text = "\n\n".join(p for p in pages if p)
        except BusinessException:
            raise
        except Exception as exc:
            raise BusinessException(f"PDF 解析失败（{filename}）：{exc}", code=40074) from exc
        if not text.strip():
            raise BusinessException(
                f"PDF「{filename}」未提取到可选中文本（可能是纯扫描图片 PDF）", code=40074
            )
        return text[:MAX_EXTRACTED_CHARS], "application/pdf"

    if ext == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                xml_bytes = zf.read("word/document.xml")
            root = ElementTree.fromstring(xml_bytes)
            paragraphs: list[str] = []
            for p_node in root.iter():
                if p_node.tag.endswith("}p"):
                    runs = [
                        t_node.text
                        for t_node in p_node.iter()
                        if t_node.tag.endswith("}t") and t_node.text
                    ]
                    line = "".join(runs).strip()
                    if line:
                        paragraphs.append(line)
            text = "\n\n".join(paragraphs)
        except Exception as exc:
            raise BusinessException(f"DOCX 解析失败（{filename}）：{exc}", code=40074) from exc
        if not text.strip():
            raise BusinessException(f"DOCX「{filename}」正文为空", code=40074)
        docx_mime = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        return text[:MAX_EXTRACTED_CHARS], docx_mime

    if ext in {".html", ".htm"}:
        parser = _HtmlTextExtractor()
        parser.feed(decode_text_bytes(raw_bytes))
        parser.close()
        text = parser.get_text()
        return text[:MAX_EXTRACTED_CHARS], "text/html"

    if ext == ".json":
        decoded = decode_text_bytes(raw_bytes)
        try:
            parsed = json.loads(decoded)
            text = json.dumps(parsed, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            text = decoded
        return text[:MAX_EXTRACTED_CHARS], "application/json"

    decoded = decode_text_bytes(raw_bytes)
    mime = "text/markdown" if ext in {".md", ".markdown"} else ("text/csv" if ext == ".csv" else "text/plain")
    return decoded[:MAX_EXTRACTED_CHARS], mime


def parse_bundle_zip(zip_bytes: bytes) -> dict[str, Any]:
    """安全解压知识库+Skill整包 zip，自动分类 SKILL.md / SCHEMA.md / index.md / log.md / wiki/ / raw/。"""
    if len(zip_bytes) > MAX_BUNDLE_ZIP_BYTES:
        raise BusinessException(
            f"整包压缩文件不能超过 {MAX_BUNDLE_ZIP_BYTES // (1024 * 1024)} MB", code=40072
        )
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile as exc:
        raise BusinessException("无效的 ZIP 压缩包格式", code=40073) from exc

    entries: list[tuple[str, bytes]] = []
    total_uncompressed = 0
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = sanitize_rel_path(info.filename)
            if should_skip_bundle_path(rel):
                continue
            total_uncompressed += int(info.file_size or 0)
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise BusinessException("压缩包解压总大小超出 30 MB 限制", code=40072)
            if len(entries) >= MAX_BUNDLE_FILES:
                raise BusinessException(f"单次导入文件数不能超过 {MAX_BUNDLE_FILES} 个", code=40072)
            entries.append((rel, zf.read(info.filename)))

    return classify_bundle_files(entries)


def _strip_common_root(paths: list[str]) -> list[str]:
    """当压缩包内所有文件都被包在单一顶层目录内（如 my-kb/SKILL.md）时，自动剥离顶层目录名。"""
    if not paths:
        return paths
    first_segments = {p.split("/")[0] for p in paths if "/" in p}
    has_root_file = any("/" not in p for p in paths)
    if not has_root_file and len(first_segments) == 1:
        top = next(iter(first_segments))
        if top not in {"raw", "wiki", "schema"}:
            prefix = f"{top}/"
            return [p[len(prefix) :] if p.startswith(prefix) else p for p in paths]
    return paths


def classify_bundle_files(entries: list[tuple[str, bytes]]) -> dict[str, Any]:
    """把上传的文件集合拆分为 LLM Wiki + Skill 标准层级结构。"""
    if not entries:
        raise BusinessException("未检测到任何有效文件", code=40070)

    clean_paths = [
        sanitize_rel_path(p)
        for p, _ in entries
        if not should_skip_bundle_path(sanitize_rel_path(p))
    ]
    raw_pairs = [
        (sanitize_rel_path(p), data)
        for p, data in entries
        if not should_skip_bundle_path(sanitize_rel_path(p))
    ]
    if not raw_pairs:
        raise BusinessException("压缩包或目录中没有可导入的文件", code=40070)

    stripped_paths = _strip_common_root(clean_paths)
    result: dict[str, Any] = {
        "skill_md": "",
        "schema_md": "",
        "index_md": "",
        "log_md": "",
        "manifest": {},
        "wiki_files": [],
        "raw_files": [],
    }

    for (_, data), rel in zip(raw_pairs, stripped_paths, strict=True):
        lower = rel.lower()
        basename = posixpath.basename(rel)
        ext = posixpath.splitext(lower)[1]

        if lower == "skill.md":
            result["skill_md"] = decode_text_bytes(data).strip()
            continue
        if lower in {"schema.md", "schema/schema.md", "agents.md", "claude.md"}:
            result["schema_md"] = decode_text_bytes(data).strip()
            continue
        if lower in {"index.md", "wiki/index.md"}:
            result["index_md"] = decode_text_bytes(data).strip()
            continue
        if lower in {"log.md", "wiki/log.md"}:
            result["log_md"] = decode_text_bytes(data).strip()
            continue
        if lower == "manifest.json":
            try:
                loaded = json.loads(decode_text_bytes(data))
                if isinstance(loaded, dict):
                    result["manifest"] = loaded
            except json.JSONDecodeError:
                pass
            continue

        if lower.startswith("wiki/") and ext in {".md", ".markdown"}:
            text = decode_text_bytes(data)
            result["wiki_files"].append(
                {
                    "page_path": rel,
                    "filename": basename,
                    "text": text[:MAX_EXTRACTED_CHARS],
                }
            )
            continue

        if ext not in ALLOWED_RAW_EXTENSIONS:
            # 忽略隐藏辅助配置或不支持的二进制附件，避免整包中断
            continue

        text, mime = extract_text_from_file(basename, data)
        raw_rel = rel[4:] if lower.startswith("raw/") else rel
        result["raw_files"].append(
            BundleFileEntry(
                rel_path=raw_rel,
                filename=basename,
                raw_bytes=data,
                text=text,
                sha256=hashlib.sha256(data).hexdigest(),
                mime_type=mime,
            )
        )

    return result
