from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

APIProtocol = Literal["openai", "anthropic"]


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
    history_length: int = 0
    token_usage: int = 0


class ChatMessageItem(BaseModel):
    role: str
    content: str


class ConversationRenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120, description="新的会话标题")


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
