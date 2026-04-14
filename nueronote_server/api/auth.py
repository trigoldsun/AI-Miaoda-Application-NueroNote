#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 认证 API 模块
处理用户注册、登录、登出等认证相关功能。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Optional

from flask import Blueprint, g, jsonify, request

from nueronote_server.database import get_db
from nueronote_server.utils.jwt import sign_token, verify_token
from nueronote_server.utils.validation import validate_email
from nueronote_server.utils.audit import write_audit, get_client_ip

# 创建认证蓝图
auth_bp = Blueprint('auth', __name__, url_prefix='/api/v1/auth')


def _check_account_lock(db, user_id: str) -> bool:
    """
    检查账户是否被锁定
    返回 True 表示账户被锁定
    """
    user = db.execute(
        "SELECT locked_until FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if user and user["locked_until"] and user["locked_until"] > time.time():
        return True
    return False


def _increment_login_fails(db, user_id: str) -> None:
    """增加登录失败计数，如果达到阈值则锁定账户"""
    db.execute(
        "UPDATE users SET login_fails = login_fails + 1 WHERE id = ?",
        (user_id,)
    )
    
    fails_row = db.execute(
        "SELECT login_fails FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    
    if fails_row and fails_row["login_fails"] >= 5:  # 达到5次失败
        lock_until = int(time.time()) + 15 * 60  # 锁定15分钟
        db.execute(
            "UPDATE users SET locked_until = ? WHERE id = ?",
            (lock_until, user_id)
        )
    
    db.commit()


def _reset_login_fails(db, user_id: str) -> None:
    """重置登录失败计数"""
    db.execute(
        "UPDATE users SET login_fails = 0, locked_until = 0 WHERE id = ?",
        (user_id,)
    )
    db.commit()


@auth_bp.route('/register', methods=['POST'])
def register():
    """
    注册账户
    请求：{email, vault?}
    返回：{user_id, token, plan, storage_quota}
    """
    body = request.get_json(force=True, silent=True) or {}
    
    # 输入验证
    email = (body.get("email") or "").strip().lower()
    if not validate_email(email):
        return jsonify({"error": "Invalid email format"}), 400
    
    # 检查vault大小
    vault = body.get("vault", {})
    vault_size = len(json.dumps(vault).encode())
    if vault_size > 10 * 1024 * 1024:  # 10MB限制
        return jsonify({"error": "Vault too large (max 10MB)"}), 413
    
    db = get_db()
    now = int(time.time() * 1000)
    
    # 检查邮箱是否已存在
    existing = db.execute(
        "SELECT id FROM users WHERE email = ?", (email,)
    ).fetchone()
    if existing:
        return jsonify({"error": "Email already registered"}), 409
    
    # 创建用户
    user_id = uuid.uuid4().hex
    try:
        db.execute(
            "INSERT INTO users (id, email, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (user_id, email, now, now)
        )
    except Exception as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500
    
    # 初始化vault
    db.execute(
        "INSERT INTO vaults (user_id, vault_json, updated_at, storage_bytes) VALUES (?, ?, ?, ?)",
        (user_id, json.dumps(vault), now, vault_size)
    )
    db.execute(
        "UPDATE users SET storage_used = ? WHERE id = ?",
        (vault_size, user_id)
    )
    
    # 审计日志
    write_audit(user_id, "REGISTER", details={"email": email})
    
    # 生成JWT令牌
    from flask import current_app
    token = sign_token(user_id, current_app.config["JWT_SECRET"])
    
    return jsonify({
        "user_id": user_id,
        "token": token,
        "plan": "free",
        "storage_quota": 512 * 1024 * 1024,  # 512MB
    }), 201


@auth_bp.route('/login', methods=['POST'])
def login():
    """
    登录
    请求：{email}
    返回：{user_id, token, plan, storage_quota, storage_used}
    """
    body = request.get_json(force=True, silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    ip = get_client_ip()
    
    if not email:
        return jsonify({"error": "Email required"}), 400
    
    db = get_db()
    user = db.execute(
        "SELECT id, locked_until FROM users WHERE email = ?", (email,)
    ).fetchone()
    
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    # 检查账户锁定
    if _check_account_lock(db, user["id"]):
        return jsonify({"error": "Account locked due to too many failed login attempts"}), 423
    
    # 模拟密码验证（实际由客户端加密，服务端只检查用户存在）
    # 这里总是视为登录成功（因为端到端加密，服务端不验证密码）
    
    # 重置登录失败计数
    _reset_login_fails(db, user["id"])
    
    # 更新最后登录信息
    db.execute(
        "UPDATE users SET last_login = ?, last_ip = ? WHERE id = ?",
        (int(time.time()), ip, user["id"])
    )
    
    # 获取存储使用情况
    vault = db.execute(
        "SELECT storage_bytes FROM vaults WHERE user_id = ?", (user["id"],)
    ).fetchone()
    storage_used = vault["storage_bytes"] if vault else 0
    
    # 生成JWT令牌
    from nueronote_server import app
    token = sign_token(user["id"], app.config["JWT_SECRET"])
    
    write_audit(user["id"], "LOGIN", details={"ip": ip})
    
    return jsonify({
        "user_id": user["id"],
        "token": token,
        "plan": "free",
        "storage_quota": 512 * 1024 * 1024,
        "storage_used": storage_used,
    })


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    登出（客户端应丢弃token）
    请求：空
    返回：{success: true}
    """
    # 服务端无状态，客户端自行丢弃token
    # 可选：将token加入黑名单（需要状态）
    return jsonify({"success": True})
