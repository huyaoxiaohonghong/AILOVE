from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

APIProtocol = Literal["openai", "anthropic"]
_DATA_IMAGE_URL_RE = re.compile(r"^data:image/(?:jpeg|jpg|png|webp);base64,[A-Za-z0-9+/=\s]+$", re.I)


class ChatMessageItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000, description="用户输入消息")
    session_id: str | None = Field(default=None, max_length=64, description="多轮会话ID")
    config_id: int | None = Field(default=None, description="指定使用的模型配置ID（留空使用全局默认）")
    persona_id: int | None = Field(default=None, description="指定使用的 AI 智能体模板 ID")
    system_prompt: str | None = Field(default=None, max_length=3000, description="覆盖系统提示词")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0, description="临时覆盖温度")
    timezone: str | None = Field(
        default=None, max_length=64, description="客户端时区（如 Asia/Shanghai），留空默认北京时间"
    )
    use_love_profile: bool | None = Field(
        default=None, description="是否注入个人情感档案上下文（留空则跟随档案 auto_inject 开关）"
    )
    incognito: bool = Field(
        default=False, description="无痕倾诉模式：开启后不写入云端历史会话与上下文记忆"
    )
    ephemeral_history: list[ChatMessageItem] = Field(
        default_factory=list,
        max_length=12,
        description="无痕模式下的本地临时多轮上下文",
    )


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    reasoning: str = ""
    model: str
    provider: str
    protocol: str = "openai"
    config_id: int | None = None
    config_name: str = ""
    persona_id: int | None = None
    persona_name: str = ""
    is_mock: bool = False
    incognito: bool = False
    history_length: int = 0
    token_usage: int = 0
    love_profile_injected: bool = False
    emotion_care: dict[str, Any] | None = None
    fallback_used: bool = False
    fallback_from: str = ""


class ConversationUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120, description="新的会话标题")
    is_pinned: bool | None = Field(default=None, description="是否置顶会话")
    persona_id: int | None = Field(default=None, description="绑定的智能体 ID")
    clear_persona: bool = Field(default=False, description="是否解除智能体绑定（回到默认直连）")


ConversationRenameRequest = ConversationUpdateRequest


RelationshipStage = Literal[
    "",
    "single_crush",
    "ambiguous",
    "in_love",
    "long_distance",
    "cold_war",
    "breakup_healing",
    "married",
]


class LoveProfileUpdateRequest(BaseModel):
    relationship_stage: RelationshipStage = Field(default="", description="当前情感阶段编码")
    partner_nickname: str = Field(default="", max_length=32, description="对方称呼")
    partner_traits: list[str] = Field(default_factory=list, description="对方性格/依恋特点标签")
    my_traits: list[str] = Field(default_factory=list, description="自身沟通特点标签")
    relationship_goal: str = Field(default="", max_length=160, description="当前核心情感目标")
    communication_taboos: str = Field(default="", max_length=300, description="沟通雷区与注意事项")
    background_notes: str = Field(default="", max_length=1200, description="补充情感背景摘要")
    auto_inject: bool = Field(default=True, description="是否自动注入 AI 对话上下文")


ReplyHelperScene = Literal["ambiguous", "cold_reply", "conflict", "date_invite", "polite_decline"]
ReplyHelperTone = Literal["playful", "gentle", "graceful", "sincere", "humorous"]


class ReplyHelperRequest(BaseModel):
    partner_message: str = Field(
        default="", max_length=2000, description="对方发来的原话/聊天片段（上传截图时可选）"
    )
    images: list[str] = Field(
        default_factory=list,
        max_length=3,
        description="微信聊天截图 Base64 Data URL 列表（最多 3 张，支持 jpg/png/webp）",
    )
    scene: ReplyHelperScene = Field(default="ambiguous", description="当前互动场景")
    tone: ReplyHelperTone = Field(default="playful", description="期望回复语气")
    context: str = Field(default="", max_length=800, description="可选：前文背景或事件经过")
    my_intent: str = Field(default="", max_length=400, description="可选：我真实想表达的核心意思")
    session_id: str | None = Field(default=None, max_length=64, description="归属会话 ID（留空新建）")
    config_id: int | None = Field(default=None, description="指定模型配置 ID")
    persona_id: int | None = Field(default=None, description="指定智能体 ID（留空自动匹配恋爱军师）")
    timezone: str | None = Field(default=None, max_length=64, description="客户端时区")
    use_love_profile: bool | None = Field(default=None, description="是否注入个人情感档案")
    incognito: bool = Field(default=False, description="是否启用无痕模式（不保存云端历史）")

    @model_validator(mode="after")
    def validate_text_or_images(self) -> ReplyHelperRequest:
        has_text = bool((self.partner_message or "").strip())
        clean_images: list[str] = []
        for idx, raw in enumerate(self.images):
            item = (raw or "").strip()
            if not item:
                continue
            if len(item) > 2_800_000:
                raise ValueError(f"第 {idx + 1} 张聊天截图体积过大，请压缩后再上传")
            if not _DATA_IMAGE_URL_RE.match(item):
                raise ValueError("聊天截图格式须为 JPG / PNG / WEBP 的 Base64 Data URL")
            clean_images.append(item)
        self.images = clean_images
        if not has_text and not self.images:
            raise ValueError("请粘贴对方发来的原话，或至少上传 1 张微信聊天截图")
        return self


SoftenIntensity = Literal["mild", "medium", "heated"]


class SoftenDraftRequest(BaseModel):
    draft_message: str = Field(
        ..., min_length=1, max_length=2000, description="情绪上头时打算发出去的原话草稿"
    )
    intensity: SoftenIntensity = Field(default="heated", description="当前情绪温度")
    context: str = Field(default="", max_length=800, description="可选：吵架或委屈的前因后果")
    session_id: str | None = Field(default=None, max_length=64, description="归属会话 ID")
    config_id: int | None = Field(default=None, description="指定模型配置 ID")
    persona_id: int | None = Field(default=None, description="指定智能体 ID")
    timezone: str | None = Field(default=None, max_length=64, description="客户端时区")
    use_love_profile: bool | None = Field(default=None, description="是否注入个人情感档案")
    incognito: bool = Field(default=False, description="是否启用无痕模式（不保存云端历史）")


FavoriteCategory = Literal["reply_helper", "soften", "chat", "custom"]


class FavoriteReplyCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=1200, description="收藏话术正文")
    category: FavoriteCategory = Field(default="reply_helper", description="来源分类")
    scene_label: str = Field(default="", max_length=64, description="场景或风格标签")
    note: str = Field(default="", max_length=255, description="个人备注")


class AIModelConfigCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="配置名称")
    provider: str = Field(default="deepseek", min_length=2, max_length=32, description="提供商标识")
    protocol: APIProtocol = Field(default="openai", description="API 接口协议: openai / anthropic")
    model_name: str = Field(default="deepseek-flash", min_length=1, max_length=64, description="模型名")
    base_url: str = Field(
        default="https://api.deepseek.com", min_length=8, max_length=255, description="API Base URL"
    )
    api_key: str = Field(default="", max_length=512, description="明文 API Key（落库自动加密）")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    max_tokens: int = Field(default=4096, ge=64, le=32768)
    timeout_seconds: int = Field(default=60, ge=5, le=300)
    max_history_messages: int = Field(default=20, ge=2, le=100)
    system_prompt: str = Field(
        default="你是 AILOVE 智能助手，请用清晰、温暖、专业的中文回答用户问题。",
        max_length=4000,
    )
    extra_params: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True
    is_default: bool = False


class AIModelConfigUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    protocol: APIProtocol | None = Field(default=None, description="API 接口协议: openai / anthropic")
    model_name: str | None = Field(default=None, min_length=1, max_length=64)
    base_url: str | None = Field(default=None, min_length=8, max_length=255)
    api_key: str | None = Field(
        default=None, max_length=512, description="留空或 None 表示保留原加密 Key 不变"
    )
    clear_api_key: bool = Field(default=False, description="是否清空已保存的 API Key")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=64, le=32768)
    timeout_seconds: int | None = Field(default=None, ge=5, le=300)
    max_history_messages: int | None = Field(default=None, ge=2, le=100)
    system_prompt: str | None = Field(default=None, max_length=4000)
    extra_params: dict[str, Any] | None = None
    is_enabled: bool | None = None
    is_default: bool | None = None


class AIModelConfigItem(BaseModel):
    id: int
    name: str
    provider: str
    protocol: APIProtocol = "openai"
    model_name: str
    base_url: str
    has_api_key: bool
    api_key_masked: str = ""
    temperature: float
    top_p: float
    max_tokens: int
    timeout_seconds: int
    max_history_messages: int
    system_prompt: str
    extra_params: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool
    is_default: bool
    last_test_status: str = "untested"
    last_test_latency_ms: int | None = None
    last_test_message: str = ""
    last_tested_at: datetime | None = None
    updated_at: datetime | None = None


PersonaCategory = Literal["dating", "chat_coach", "relationship", "conflict", "healing"]


class AIPersonaCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$", description="唯一编码")
    name: str = Field(..., min_length=1, max_length=64, description="智能体名称")
    avatar_emoji: str = Field(default="💘", min_length=1, max_length=16, description="Emoji 图标")
    category: PersonaCategory = Field(default="chat_coach", description="情感智能体分类")
    description: str = Field(default="", max_length=255, description="一句话简介")
    system_prompt: str = Field(..., min_length=4, max_length=6000, description="系统人设提示词")
    starter_prompts: list[str] = Field(default_factory=list, description="开场白快捷示例提示词")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0, description="覆盖采样温度")
    is_enabled: bool = True
    sort_order: int = Field(default=100, ge=0, le=9999)


class AIPersonaUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    avatar_emoji: str | None = Field(default=None, min_length=1, max_length=16)
    category: PersonaCategory | None = None
    description: str | None = Field(default=None, max_length=255)
    system_prompt: str | None = Field(default=None, min_length=4, max_length=6000)
    starter_prompts: list[str] | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    clear_temperature: bool = Field(default=False, description="是否清空覆盖温度")
    is_enabled: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=9999)
