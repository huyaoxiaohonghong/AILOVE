from __future__ import annotations

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _get_fernet() -> Fernet:
    """基于应用密钥派生 32 字节 Fernet 对称加密密钥，用于安全落库大模型 API Key。"""
    return _build_fernet(get_settings().JWT_SECRET_KEY)


@lru_cache(maxsize=4)
def _build_fernet(secret_key: str) -> Fernet:
    """按密钥缓存 Fernet 实例，避免每次加解密重复做 SHA-256 派生与对象构造。"""
    digest = hashlib.sha256(b"ailove-ai-key-v1:" + secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(plain_text: str) -> str:
    clean = (plain_text or "").strip()
    if not clean:
        return ""
    return _get_fernet().encrypt(clean.encode("utf-8")).decode("ascii")


def decrypt_secret(cipher_text: str) -> str:
    clean = (cipher_text or "").strip()
    if not clean:
        return ""
    try:
        return _get_fernet().decrypt(clean.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        # 兼容尚未加密的旧值或异常密文，避免崩溃
        return ""


def mask_api_key(plain_key: str) -> str:
    """将 API Key 脱敏展示，例如 sk-1234****abcd。"""
    key = (plain_key or "").strip()
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:6]}****{key[-4:]}"
