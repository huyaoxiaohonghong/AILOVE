from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

KBVisibility = Literal["private", "public"]
KBPageType = Literal["summary", "concept", "entity", "insight", "overview"]


class KBBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="知识库名称")
    slug: str = Field(default="", max_length=64, description="可选唯一 slug（留空自动生成）")
    description: str = Field(default="", max_length=500, description="知识库简介与适用场景")
    category: str = Field(default="general", max_length=32, description="分类标签")
    visibility: KBVisibility = Field(default="private", description="private 仅本人 / public 全平台可调用")
    schema_md: str = Field(default="", max_length=40000, description="可选自定义 SCHEMA.md")


class KBBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    category: str | None = Field(default=None, max_length=32)
    visibility: KBVisibility | None = Field(default=None)
    schema_md: str | None = Field(default=None, max_length=40000)


class KBCompileRequest(BaseModel):
    source_ids: list[int] = Field(
        default_factory=list, description="指定待编译的资料 ID（留空编译全部待处理）"
    )
    use_llm: bool = Field(
        default=True, description="是否优先调用已配置大模型深度编排（未配置时自动结构化编译）"
    )
    config_id: int | None = Field(default=None, description="可选指定模型配置 ID")
    recompile_all: bool = Field(default=False, description="是否对已入库资料全部重新编译")


class KBPageUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    page_type: KBPageType | None = Field(default=None)
    summary: str | None = Field(default=None, max_length=500)
    content_md: str | None = Field(default=None, max_length=100000)


class KBInsightCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200, description="洞察词条标题")
    content: str = Field(..., min_length=1, max_length=50000, description="洞察 Markdown 正文")
    source_question: str = Field(default="", max_length=1000, description="关联的用户提问")


class KBSkillPublishRequest(BaseModel):
    name: str = Field(default="", max_length=100, description="Skill 显示名称（留空继承知识库名称）")
    slug: str = Field(default="", max_length=64, description="触发 slug（支持 /skill:slug 调用）")
    description: str = Field(default="", max_length=500, description="何时调用此 Skill 的触发描述")
    triggers: list[str] = Field(default_factory=list, max_length=30, description="自动触发关键词列表")
    skill_md: str = Field(
        default="", max_length=60000, description="自定义完整 SKILL.md（留空自动生成标准模板）"
    )
    version: str = Field(default="1.0.0", max_length=32)
    visibility: KBVisibility | None = Field(default=None, description="可见性（留空跟随知识库）")
    is_enabled: bool = Field(default=True, description="是否启用调用")


class KBSkillUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    triggers: list[str] | None = Field(default=None, max_length=30)
    skill_md: str | None = Field(default=None, max_length=60000)
    version: str | None = Field(default=None, max_length=32)
    visibility: KBVisibility | None = Field(default=None)
    is_enabled: bool | None = Field(default=None)


class KBSkillTestQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="测试检索问题")
    top_k: int = Field(default=4, ge=1, le=8, description="返回最相关的 Wiki 词条数量")
