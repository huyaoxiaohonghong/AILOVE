from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI


@dataclass(frozen=True)
class ModelPreset:
    id: str
    label: str
    description: str
    context_window: int
    supports_reasoning: bool = False
    supports_temperature: bool = True
    default_max_tokens: int = 4096


@dataclass(frozen=True)
class ProviderDescriptor:
    code: str
    name: str
    protocol: str
    status: str  # "active" | "planned"
    description: str
    default_base_url: str
    docs_url: str
    api_key_placeholder: str
    default_protocol: str = "openai"
    protocol_endpoints: dict[str, str] = field(default_factory=dict)
    models: tuple[ModelPreset, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "protocol": self.protocol,
            "default_protocol": self.default_protocol,
            "protocol_endpoints": dict(self.protocol_endpoints),
            "status": self.status,
            "description": self.description,
            "default_base_url": self.default_base_url,
            "docs_url": self.docs_url,
            "api_key_placeholder": self.api_key_placeholder,
            "models": [
                {
                    "id": m.id,
                    "label": m.label,
                    "description": m.description,
                    "context_window": m.context_window,
                    "supports_reasoning": m.supports_reasoning,
                    "supports_temperature": m.supports_temperature,
                    "default_max_tokens": m.default_max_tokens,
                }
                for m in self.models
            ],
        }


SUPPORTED_PROTOCOLS = frozenset({"openai", "anthropic"})


def resolve_protocol(
    base_url: str = "",
    extra_params: dict[str, Any] | None = None,
    default: str = "openai",
) -> str:
    """统一解析接口协议：显式 extra_params.protocol 优先，其次按 Base URL 推断，最后回退默认值。"""
    explicit = str((extra_params or {}).get("protocol") or "").strip().lower()
    if explicit in SUPPORTED_PROTOCOLS:
        return explicit
    if "/anthropic" in (base_url or "").lower():
        return "anthropic"
    return default


def humanize_llm_error(exc: Exception, *, model_name: str, base_url: str, latency_ms: int = 0) -> str:
    """将底层 SDK 异常转换为面向管理员/用户的友好中文提示（不泄露密钥与内部堆栈）。"""
    err_text = str(exc)
    lowered = err_text.lower()
    if "401" in err_text or "authentication" in lowered or "invalid_api_key" in lowered:
        return "鉴权失败 (401)：请检查 API Key 是否填写正确"
    if "402" in err_text or "insufficient balance" in lowered:
        return "账户余额不足 (402)：请在模型开放平台充值后重试"
    if "429" in err_text or "rate limit" in lowered:
        return "请求过于频繁 (429)：已触发模型服务限流，请稍后重试"
    if "404" in err_text:
        return f"模型或接口地址不存在 (404)：请检查模型名 {model_name} 与 Base URL"
    if "timeout" in lowered or "timed out" in lowered:
        return f"请求超时（{latency_ms}ms）：服务器访问 {base_url} 网络超时"
    if any(code in err_text for code in ("500", "502", "503", "504")):
        return "模型服务暂时不可用 (5xx)：上游服务繁忙，请稍后重试"
    return f"调用失败：{err_text[:180]}"


class BaseProviderAdapter:
    """多模型统一适配协议：后续新增 OpenAI / 通义千问 / 智谱 / Gemini 只需新增子类并注册即可。"""

    descriptor: ProviderDescriptor

    def resolve_protocol(
        self, base_url: str = "", extra_params: dict[str, Any] | None = None
    ) -> str:
        return resolve_protocol(base_url, extra_params, default=self.descriptor.default_protocol)

    def supports_reasoning_model(self, model_name: str) -> bool:
        clean = (model_name or "").strip().lower()
        for preset in self.descriptor.models:
            if preset.id.lower() == clean:
                return preset.supports_reasoning
        return clean in {"deepseek-v4-pro", "deepseek-reasoner"}

    def build_chat_model(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        temperature: float,
        top_p: float,
        max_tokens: int,
        timeout_seconds: int,
        streaming: bool = True,
        extra_params: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        raise NotImplementedError

    def extract_chunk_deltas(self, chunk: Any) -> tuple[str, str]:
        """从流式/同步响应提取 (reasoning_delta, content_delta)，同时兼容 OpenAI 与 Anthropic 协议。"""
        additional = getattr(chunk, "additional_kwargs", None) or {}
        reasoning_parts: list[str] = []
        if additional.get("reasoning_content"):
            reasoning_parts.append(str(additional["reasoning_content"]))

        raw_content = getattr(chunk, "content", "")
        content_parts: list[str] = []
        if isinstance(raw_content, str):
            content_parts.append(raw_content)
        elif isinstance(raw_content, list):
            for item in raw_content:
                if isinstance(item, str):
                    content_parts.append(item)
                elif isinstance(item, dict):
                    item_type = item.get("type")
                    if item_type == "thinking":
                        thinking_text = item.get("thinking") or item.get("text") or ""
                        if thinking_text:
                            reasoning_parts.append(str(thinking_text))
                    elif item_type == "text":
                        text_val = item.get("text") or ""
                        if text_val:
                            content_parts.append(str(text_val))
        elif raw_content:
            content_parts.append(str(raw_content))

        return "".join(reasoning_parts), "".join(content_parts)


class DeepSeekProviderAdapter(BaseProviderAdapter):
    """DeepSeek 官方适配器（双协议支持 OpenAI / Anthropic，内置 deepseek-flash 与 deepseek-v4-pro）。"""

    descriptor = ProviderDescriptor(
        code="deepseek",
        name="DeepSeek",
        protocol="OpenAI / Anthropic 双协议",
        default_protocol="openai",
        protocol_endpoints={
            "openai": "https://api.deepseek.com",
            "anthropic": "https://api.deepseek.com/anthropic",
        },
        status="active",
        description=(
            "支持 OpenAI (https://api.deepseek.com) 与 Anthropic (https://api.deepseek.com/anthropic) "
            "双协议接口，内置 deepseek-flash 与 deepseek-v4-pro。"
        ),
        default_base_url="https://api.deepseek.com",
        docs_url="https://platform.deepseek.com/api_keys",
        api_key_placeholder="sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        models=(
            ModelPreset(
                id="deepseek-flash",
                label="DeepSeek Flash (deepseek-flash)",
                description="高速轻量主力模型，低延迟高性价比，适合实时对话与日常问答。",
                context_window=131072,
                supports_reasoning=False,
                supports_temperature=True,
                default_max_tokens=4096,
            ),
            ModelPreset(
                id="deepseek-v4-pro",
                label="DeepSeek V4 Pro (deepseek-v4-pro)",
                description="旗舰级增强模型，具备深度推理、复杂规划与高质量长文本生成能力。",
                context_window=131072,
                supports_reasoning=True,
                supports_temperature=True,
                default_max_tokens=8192,
            ),
        ),
    )

    def build_chat_model(
        self,
        *,
        api_key: str,
        base_url: str,
        model_name: str,
        temperature: float,
        top_p: float,
        max_tokens: int,
        timeout_seconds: int,
        streaming: bool = True,
        extra_params: dict[str, Any] | None = None,
    ) -> BaseChatModel:
        protocol = self.resolve_protocol(base_url, extra_params)
        default_url = self.descriptor.protocol_endpoints.get(
            protocol, self.descriptor.default_base_url
        )
        clean_base_url = (base_url or default_url).strip().rstrip("/")
        is_legacy_reasoner = model_name.strip().lower() == "deepseek-reasoner"

        passthrough = {
            k: v
            for k, v in (extra_params or {}).items()
            if k not in {"protocol", "api_key", "base_url", "model"}
        }

        if protocol == "anthropic":
            anthropic_kwargs: dict[str, Any] = {
                "api_key": api_key,
                "base_url": clean_base_url,
                "model": model_name,
                "max_tokens": max_tokens,
                "timeout": timeout_seconds,
                "streaming": streaming,
            }
            if not is_legacy_reasoner:
                anthropic_kwargs["temperature"] = temperature
                if top_p < 1.0:
                    anthropic_kwargs["top_p"] = top_p
            if passthrough:
                anthropic_kwargs["model_kwargs"] = passthrough
            return ChatAnthropic(**anthropic_kwargs)

        openai_kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": clean_base_url,
            "model": model_name,
            "max_tokens": max_tokens,
            "timeout": timeout_seconds,
            "streaming": streaming,
            # 流式输出时在末尾 chunk 返回 usage，便于统计 Token 消耗
            "stream_usage": True,
        }
        if not is_legacy_reasoner:
            openai_kwargs["temperature"] = temperature
            openai_kwargs["top_p"] = top_p
        if passthrough:
            openai_kwargs["model_kwargs"] = passthrough

        return ChatOpenAI(**openai_kwargs)


# 已激活的提供商适配器注册表（后续接入新模型直接在此注册）
ACTIVE_PROVIDER_ADAPTERS: dict[str, BaseProviderAdapter] = {
    "deepseek": DeepSeekProviderAdapter(),
}

# 架构预留的后续扩展提供商清单（仅用于前端路线图展示，无需改表即可平滑接入）
PLANNED_PROVIDERS: tuple[ProviderDescriptor, ...] = (
    ProviderDescriptor(
        code="qwen",
        name="通义千问 (DashScope)",
        protocol="openai-compatible",
        status="planned",
        description="阿里云百炼兼容协议，后续零改表扩展接入。",
        default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        docs_url="https://bailian.console.aliyun.com/",
        api_key_placeholder="sk-xxxxxxxxxxxxxxxx",
        models=(),
    ),
    ProviderDescriptor(
        code="openai",
        name="OpenAI",
        protocol="openai-compatible",
        status="planned",
        description="GPT-4o / o3 系列模型，架构已兼容，后续按需开放。",
        default_base_url="https://api.openai.com/v1",
        docs_url="https://platform.openai.com/api-keys",
        api_key_placeholder="sk-proj-xxxxxxxxxxxxxxxx",
        models=(),
    ),
    ProviderDescriptor(
        code="zhipu",
        name="智谱清言 (GLM)",
        protocol="openai-compatible",
        status="planned",
        description="GLM-4 系列国产大模型，后续扩展接入。",
        default_base_url="https://open.bigmodel.cn/api/paas/v4",
        docs_url="https://open.bigmodel.cn/",
        api_key_placeholder="xxxxxxxxxxxxxxxx.xxxxxxxx",
        models=(),
    ),
    ProviderDescriptor(
        code="gemini",
        name="Google Gemini",
        protocol="google-genai",
        status="planned",
        description="Google 多模态大模型，通过独立 Adapter 扩展接入。",
        default_base_url="https://generativelanguage.googleapis.com",
        docs_url="https://aistudio.google.com/",
        api_key_placeholder="AIzaSyxxxxxxxxxxxxxxxx",
        models=(),
    ),
)


def get_provider_adapter(provider_code: str) -> BaseProviderAdapter | None:
    return ACTIVE_PROVIDER_ADAPTERS.get((provider_code or "").strip().lower())


def list_all_providers() -> list[dict[str, Any]]:
    active = [adapter.descriptor.to_dict() for adapter in ACTIVE_PROVIDER_ADAPTERS.values()]
    planned = [desc.to_dict() for desc in PLANNED_PROVIDERS]
    return active + planned
