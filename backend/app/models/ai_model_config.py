from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AIModelConfig(Base, TimestampMixin):
    """AI 模型与提供商配置表（支持多提供商扩展，当前默认内置 DeepSeek）。"""

    __tablename__ = "ai_model_configs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, comment="配置展示名称")
    provider: Mapped[str] = mapped_column(
        String(32), index=True, default="deepseek", nullable=False, comment="提供商标识: deepseek 等"
    )
    model_name: Mapped[str] = mapped_column(
        String(64), default="deepseek-flash", nullable=False, comment="模型标识"
    )
    base_url: Mapped[str] = mapped_column(
        String(255),
        default="https://api.deepseek.com",
        nullable=False,
        comment="API 接口地址",
    )
    api_key_encrypted: Mapped[str] = mapped_column(
        Text, default="", nullable=False, comment="Fernet 加密存储的 API Key"
    )
    api_key_masked: Mapped[str] = mapped_column(
        String(64), default="", nullable=False, comment="脱敏展示的 API Key"
    )
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False, comment="采样温度")
    top_p: Mapped[float] = mapped_column(Float, default=1.0, nullable=False, comment="核采样 Top-P")
    max_tokens: Mapped[int] = mapped_column(
        Integer, default=4096, nullable=False, comment="单次最大输出 Token"
    )
    timeout_seconds: Mapped[int] = mapped_column(
        Integer, default=60, nullable=False, comment="请求超时秒数"
    )
    max_history_messages: Mapped[int] = mapped_column(
        Integer, default=20, nullable=False, comment="多轮上下文保留消息条数"
    )
    system_prompt: Mapped[str] = mapped_column(
        Text,
        default="你是 AILOVE 智能助手，请用清晰、温暖、专业的中文回答用户问题。",
        nullable=False,
        comment="默认系统人设提示词",
    )
    extra_params: Mapped[str] = mapped_column(
        Text, default="{}", nullable=False, comment="预留扩展参数 JSON（支持未来多模型专属参数）"
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, comment="是否启用")
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否为全局默认生效模型"
    )
    last_test_status: Mapped[str] = mapped_column(
        String(16), default="untested", nullable=False, comment="untested / ok / failed"
    )
    last_test_latency_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="最近一次连通测试延迟(ms)"
    )
    last_test_message: Mapped[str] = mapped_column(
        String(255), default="", nullable=False, comment="最近一次连通测试结果描述"
    )
    last_tested_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="最近测试时间"
    )
    updated_by: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="最后修改的管理员ID"
    )
