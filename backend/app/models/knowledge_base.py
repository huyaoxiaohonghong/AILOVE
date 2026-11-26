from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

LONG_TEXT = Text().with_variant(LONGTEXT, "mysql")


class KBWikiBase(Base, TimestampMixin):
    """LLM Wiki 知识库主表（三层结构：raw/ + wiki/ + SCHEMA.md/index.md/log.md）。"""

    __tablename__ = "kb_wiki_bases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, comment="知识库唯一标识 slug"
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="知识库名称")
    description: Mapped[str] = mapped_column(
        String(500), default="", nullable=False, comment="知识库简介与适用领域"
    )
    category: Mapped[str] = mapped_column(
        String(32), default="general", index=True, nullable=False, comment="知识库分类"
    )
    owner_scope: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False, comment="所属账号作用域（如 web:1 / wx:2）"
    )
    visibility: Mapped[str] = mapped_column(
        String(16), default="private", index=True, nullable=False, comment="可见性：private / public"
    )
    schema_md: Mapped[str] = mapped_column(
        LONG_TEXT, default="", nullable=False, comment="LLM Wiki SCHEMA.md 编译与维护约定"
    )
    index_md: Mapped[str] = mapped_column(
        LONG_TEXT, default="", nullable=False, comment="LLM Wiki index.md 词条全览目录"
    )
    log_md: Mapped[str] = mapped_column(
        LONG_TEXT, default="", nullable=False, comment="LLM Wiki log.md 追加式操作流水账"
    )
    source_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="raw/ 原始资料数"
    )
    page_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="wiki/ 词条页数"
    )
    last_lint_score: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="最近一次 Lint 健康评分 (0-100)"
    )
    last_lint_json: Mapped[str] = mapped_column(
        Text, default="", nullable=False, comment="最近一次 Lint 结果 JSON"
    )
    last_compiled_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="最近一次 Wiki 编译时间"
    )


class KBRawSource(Base, TimestampMixin):
    """LLM Wiki 第一层（不可变 raw/ 原始资料文件）。"""

    __tablename__ = "kb_raw_sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("kb_wiki_bases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="所属知识库 ID",
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False, comment="原始文件名")
    rel_path: Mapped[str] = mapped_column(
        String(255), default="", nullable=False, comment="相对 raw/ 的路径"
    )
    mime_type: Mapped[str] = mapped_column(
        String(100), default="text/plain", nullable=False, comment="MIME 类型或扩展类型"
    )
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="原文件字节数")
    content_sha256: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False, comment="正文 SHA-256 去重摘要"
    )
    raw_text: Mapped[str] = mapped_column(
        LONG_TEXT, default="", nullable=False, comment="提取后的纯文本/Markdown 正文"
    )
    ingest_status: Mapped[str] = mapped_column(
        String(16), default="pending", index=True, nullable=False, comment="pending / ingested / failed"
    )
    ingest_error: Mapped[str] = mapped_column(
        String(500), default="", nullable=False, comment="入库编译失败原因"
    )
    ingested_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="编译入库时间"
    )


class KBWikiPage(Base, TimestampMixin):
    """LLM Wiki 第二层（LLM 编译与互链维护的 wiki/ Markdown 词条）。"""

    __tablename__ = "kb_wiki_pages"
    __table_args__ = (UniqueConstraint("kb_id", "page_path", name="uq_kb_wiki_page_path"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("kb_wiki_bases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
        comment="所属知识库 ID",
    )
    page_path: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="词条虚拟路径（如 wiki/concepts/attachment.md）"
    )
    slug: Mapped[str] = mapped_column(String(128), index=True, nullable=False, comment="词条 slug")
    title: Mapped[str] = mapped_column(String(200), nullable=False, comment="词条标题")
    page_type: Mapped[str] = mapped_column(
        String(24),
        default="concept",
        index=True,
        nullable=False,
        comment="summary / concept / entity / insight / overview",
    )
    summary: Mapped[str] = mapped_column(String(500), default="", nullable=False, comment="一句话摘要")
    content_md: Mapped[str] = mapped_column(
        LONG_TEXT, default="", nullable=False, comment="Markdown 词条正文（含 [[wikilinks]]）"
    )
    links_json: Mapped[str] = mapped_column(
        Text, default="[]", nullable=False, comment="出链 [[wikilinks]] JSON 列表"
    )
    source_ids_json: Mapped[str] = mapped_column(
        Text, default="[]", nullable=False, comment="关联原始资料 ID JSON 列表"
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="词条版本号")


class KBSkill(Base, TimestampMixin):
    """封装为可调用 Skill 技能包的知识库发布配置（含 SKILL.md 与触发词）。"""

    __tablename__ = "kb_skills"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kb_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("kb_wiki_bases.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        comment="绑定的知识库 ID（一对一发布）",
    )
    slug: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False, comment="Skill 唯一触发 slug"
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="Skill 显示名称")
    description: Mapped[str] = mapped_column(
        String(500), default="", nullable=False, comment="触发描述与适用场景说明"
    )
    triggers_json: Mapped[str] = mapped_column(
        Text, default="[]", nullable=False, comment="自动触发关键词 JSON 列表"
    )
    skill_md: Mapped[str] = mapped_column(
        LONG_TEXT, default="", nullable=False, comment="完整 SKILL.md 技能指令文本"
    )
    version: Mapped[str] = mapped_column(String(32), default="1.0.0", nullable=False, comment="版本号")
    owner_scope: Mapped[str] = mapped_column(
        String(64), index=True, nullable=False, comment="所属账号作用域"
    )
    visibility: Mapped[str] = mapped_column(
        String(16), default="private", index=True, nullable=False, comment="可见性：private / public"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, index=True, nullable=False, comment="是否允许在对话中调用"
    )
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="累计调用次数")
