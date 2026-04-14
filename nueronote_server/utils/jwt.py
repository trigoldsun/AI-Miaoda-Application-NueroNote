#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
JWT 工具函数
实现 HMAC-SHA256 签名的 JWT，无外部依赖。
"""

import hashlib
import hmac
import json
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Optional


def b64u_encode(data: bytes | str) -> str:
    """URL安全的Base64编码（去掉填充）"""
    if isinstance(data, str):
        data = data.encode()
    return urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_decode(data: str) -> bytes:
    """URL安全的Base64解码（补全填充）"""
    pad = (4 - len(data) % 4) % 4
    return urlsafe_b64decode(data + "=" * pad)


def sign_token(user_id: str, secret: str) -> str:
    """
    签发 JWT（HMAC-SHA256）
    
    Args:
        user_id: 用户ID
        secret: 签名密钥
        
    Returns:
        JWT token字符串
    """
    now = int(time.time())
    header = b64u_encode(json.dumps({"alg": "HS256", "typ": "JWT"}))
    payload = b64u_encode(json.dumps({
        "sub": user_id,
        "iat": now,
        "exp": now + 86400,     # 24 小时有效期
        "jti": secrets.token_hex(8),  # 唯一 ID，防重放
    }))
    sig = hmac.new(
        secret.encode(),
        f"{header}.{payload}".encode(),
        hashlib.sha256
    ).digest()
    return f"{header}.{payload}.{b64u_encode(sig)}"


def verify_token(token: str, secret: str) -> Optional[str]:
    """
    验证 JWT，返回 user_id 或 None
    
    Args:
        token: JWT token字符串
        secret: 签名密钥
        
    Returns:
        用户ID（验证成功）或 None（验证失败）
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header, payload, sig = parts

        # 验证签名
        expected_sig = hmac.new(
            secret.encode(),
            f"{header}.{payload}".encode(),
            hashlib.sha256
        ).digest()
        if not hmac.compare_digest(sig, b64u_encode(expected_sig)):
            return None

        # 验证过期
        payload_data = json.loads(b64u_decode(payload))
        exp = payload_data.get("exp", 0)
        if exp < time.time():
            return None

        return payload_data.get("sub")
    except Exception:
        return None


def decode_token(token: str) -> Optional[dict]:
    """
    解码JWT payload（不验证签名）
    仅用于调试或获取信息，不可用于认证。
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload = parts[1]
        return json.loads(b64u_decode(payload))
    except Exception:
        return None
