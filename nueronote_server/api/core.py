#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 核心 API 模块
处理健康检查、安全信息、静态文件等通用路由。
"""

import time
from datetime import datetime, timezone
from pathlib import Path
from flask import Blueprint, jsonify

# 创建核心蓝图
core_bp = Blueprint('core', __name__)

# 应用启动时间（用于计算运行时间）
_start_time = time.time()


@core_bp.route('/api/v1/health', methods=['GET'])
def api_health():
    """
    健康检查（无认证，CDN/负载均衡探测）
    返回：{status, version, uptime_seconds, timestamp}
    """
    return jsonify({
        "status": "ok",
        "version": "1.0.0",
        "uptime_seconds": int(time.time() - _start_time),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@core_bp.route('/api/v1/security.txt', methods=['GET'])
def security_txt():
    """
    RFC 9116 安全联系页面
    返回：纯文本安全联系信息
    """
    return (
        "Contact: mailto:security@nueronote.app\n"
        "Preferred-Languages: en, zh\n"
        "Encryption: https://nueronote.app/keys.asc\n"
        "Hire: https://nueronote.app/jobs\n",
        200,
        {"Content-Type": "text/plain; charset=utf-8"},
    )


@core_bp.route('/', methods=['GET'])
def serve_client():
    """
    提供前端 SPA
    返回：HTML前端或404错误
    """
    # 尝试从nueronote_client目录提供前端
    client_path = Path(__file__).parent.parent / "nueronote_client" / "index.html"
    if client_path.exists():
        return client_path.read_text(encoding="utf-8"), 200, {
            "Content-Type": "text/html; charset=utf-8",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        }
    
    # 如果前端文件不存在，返回API信息
    return jsonify({
        "name": "NueroNote API",
        "version": "1.0.0",
        "description": "Zero-knowledge note syncing service",
        "endpoints": {
            "health": "/api/v1/health",
            "auth": "/api/v1/auth/*",
            "vault": "/api/v1/vault/*",
            "sync": "/api/v1/sync/*",
            "account": "/api/v1/account/*",
            "cloud": "/api/v1/cloud/*"
        },
        "docs": "https://docs.nueronote.app"
    }), 200


@core_bp.route('/api/v1', methods=['GET'])
def api_info():
    """
    API信息页面
    返回：API版本和端点信息
    """
    return jsonify({
        "api": "NueroNote v1",
        "version": "1.0.0",
        "description": "Zero-knowledge end-to-end encrypted note sync API",
        "authentication": "Bearer token in Authorization header",
        "security": "All user data is encrypted client-side",
        "endpoints": {
            "auth": {
                "register": "POST /api/v1/auth/register",
                "login": "POST /api/v1/auth/login",
                "logout": "POST /api/v1/auth/logout"
            },
            "vault": {
                "get": "GET /api/v1/vault",
                "update": "PUT /api/v1/vault",
                "versions": "GET /api/v1/vault/versions",
                "restore": "POST /api/v1/vault/restore/<version>"
            },
            "sync": {
                "push": "POST /api/v1/sync/push",
                "pull": "GET /api/v1/sync/pull",
                "status": "GET /api/v1/sync/status"
            },
            "account": {
                "info": "GET /api/v1/account",
                "upgrade": "POST /api/v1/account/upgrade",
                "usage": "GET /api/v1/account/usage",
                "settings": "GET /api/v1/account/settings"
            },
            "cloud": {
                "providers": "GET /api/v1/cloud/providers",
                "status": "GET /api/v1/cloud/status",
                "configure": "POST /api/v1/cloud/configure",
                "sync": "POST /api/v1/cloud/sync",
                "test": "POST /api/v1/cloud/test"
            },
            "core": {
                "health": "GET /api/v1/health",
                "security": "GET /api/v1/security.txt",
                "api_info": "GET /api/v1"
            }
        },
        "encryption": {
            "algorithm": "XChaCha20-Poly1305",
            "key_derivation": "Argon2id + HKDF",
            "zero_knowledge": "Server cannot decrypt user data"
        },
        "links": {
            "documentation": "https://docs.nueronote.app",
            "github": "https://github.com/nueronote/nueronote",
            "security": "/api/v1/security.txt"
        }
    })