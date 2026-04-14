#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 账户管理 API 模块
处理用户账户信息、套餐升级、安全设置等。
"""

from __future__ import annotations

import time
from typing import Dict, Any, Optional

from flask import Blueprint, g, jsonify, request

from nueronote_server.database import get_db
from nueronote_server.utils.jwt import verify_token
from nueronote_server.utils.audit import write_audit

# 创建账户管理蓝图
account_bp = Blueprint('account', __name__, url_prefix='/api/v1/account')


def require_auth_account(func):
    """Account专用的认证装饰器"""
    from functools import wraps
    
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({"error": "Missing or invalid authorization header"}), 401
        
        token = auth_header[7:]
        from flask import current_app
        payload = verify_token(token, current_app.config["JWT_SECRET"])
        
        if not payload:
            return jsonify({"error": "Invalid or expired token"}), 401
        
        g.user_id = payload  # verify_token returns user_id string
        if not g.user_id:
            return jsonify({"error": "Invalid token payload"}), 401
        
        # 检查用户是否存在
        db = get_db()
        user = db.execute(
            "SELECT id FROM users WHERE id = ?", (g.user_id,)
        ).fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 404
        
        return func(*args, **kwargs)
    
    return wrapper


@account_bp.route('/', methods=['GET'])
@require_auth_account
def get_account():
    """
    获取账户信息
    返回：{user_id, email, plan, storage_quota, storage_used, created_at, last_login}
    """
    db = get_db()
    user = db.execute(
        "SELECT id, email, plan, storage_quota, storage_used, "
        "created_at, last_login FROM users WHERE id = ?",
        (g.user_id,)
    ).fetchone()
    
    if not user:
        return jsonify({"error": "Not found"}), 404
    
    return jsonify({
        "user_id": user["id"],
        "email": user["email"],
        "plan": user["plan"],
        "storage_quota": user["storage_quota"],
        "storage_used": user["storage_used"],
        "created_at": user["created_at"],
        "last_login": user["last_login"],
    })


@account_bp.route('/upgrade', methods=['POST'])
@require_auth_account
def upgrade_account():
    """
    升级套餐（实际支付集成需扩展）
    请求：{plan: "free"|"pro"|"team"}
    返回：{plan: "...", storage_quota: ...}
    """
    body = request.get_json(force=True, silent=True) or {}
    plan = body.get("plan", "")
    
    if plan not in ("free", "pro", "team"):
        return jsonify({"error": "Invalid plan"}), 400
    
    # 配额配置（字节）
    QUOTA_FREE = 512 * 1024 * 1024   # 512 MB
    QUOTA_PRO = 10 * 1024**3         # 10 GB
    QUOTA_TEAM = 100 * 1024**3       # 100 GB
    
    quotas = {"free": QUOTA_FREE, "pro": QUOTA_PRO, "team": QUOTA_TEAM}
    
    db = get_db()
    db.execute(
        "UPDATE users SET plan = ?, storage_quota = ?, updated_at = ? WHERE id = ?",
        (plan, quotas[plan], int(time.time() * 1000), g.user_id)
    )
    
    write_audit(g.user_id, "PLAN_UPGRADE", 
                resource_type="account",
                details={"plan": plan, "quota": quotas[plan]})
    
    return jsonify({
        "plan": plan,
        "storage_quota": quotas[plan],
        "success": True
    })


@account_bp.route('/usage', methods=['GET'])
@require_auth_account
def get_usage():
    """
    获取存储使用详情
    返回：{storage_used, storage_quota, usage_percent, vault_count, sync_count, audit_count}
    """
    db = get_db()
    
    # 获取用户基本存储信息
    user_row = db.execute(
        "SELECT storage_used, storage_quota FROM users WHERE id = ?",
        (g.user_id,)
    ).fetchone()
    
    if not user_row:
        return jsonify({"error": "User not found"}), 404
    
    storage_used = user_row["storage_used"] or 0
    storage_quota = user_row["storage_quota"] or QUOTA_FREE
    
    # 获取统计信息
    vault_row = db.execute(
        "SELECT COUNT(*) as count FROM vault_versions WHERE user_id = ?",
        (g.user_id,)
    ).fetchone()
    vault_count = vault_row["count"] if vault_row else 0
    
    sync_row = db.execute(
        "SELECT COUNT(*) as count FROM sync_log WHERE user_id = ?",
        (g.user_id,)
    ).fetchone()
    sync_count = sync_row["count"] if sync_row else 0
    
    audit_row = db.execute(
        "SELECT COUNT(*) as count FROM audit_log WHERE user_id = ?",
        (g.user_id,)
    ).fetchone()
    audit_count = audit_row["count"] if audit_row else 0
    
    usage_percent = (storage_used / storage_quota * 100) if storage_quota > 0 else 0
    
    return jsonify({
        "storage_used": storage_used,
        "storage_quota": storage_quota,
        "usage_percent": round(usage_percent, 2),
        "vault_count": vault_count,
        "sync_count": sync_count,
        "audit_count": audit_count,
        "last_updated": int(time.time() * 1000)
    })


@account_bp.route('/settings', methods=['GET'])
@require_auth_account
def get_settings():
    """
    获取账户设置
    返回：{email, plan, created_at, last_login, login_fails, locked_until, last_ip}
    """
    db = get_db()
    user = db.execute(
        """SELECT email, plan, created_at, last_login, 
                  login_fails, locked_until, last_ip 
           FROM users WHERE id = ?""",
        (g.user_id,)
    ).fetchone()
    
    if not user:
        return jsonify({"error": "User not found"}), 404
    
    is_locked = user["locked_until"] and user["locked_until"] > time.time()
    
    return jsonify({
        "email": user["email"],
        "plan": user["plan"],
        "created_at": user["created_at"],
        "last_login": user["last_login"],
        "login_fails": user["login_fails"],
        "is_locked": is_locked,
        "locked_until": user["locked_until"],
        "last_ip": user["last_ip"],
        "security_status": "secure" if user["login_fails"] < 3 else "warning"
    })


@account_bp.route('/reset-password', methods=['POST'])
@require_auth_account
def reset_password():
    """
    重置密码（客户端端到端加密，服务端只记录操作）
    请求：{old_password_hash?, new_password_hash?}
    返回：{success: true, message: "密码已重置"}
    """
    # 在零知识架构中，密码验证在客户端完成
    # 服务端只记录密码重置操作
    
    write_audit(g.user_id, "PASSWORD_RESET",
                resource_type="account",
                details={"action": "reset_password"})
    
    return jsonify({
        "success": True,
        "message": "密码重置请求已记录。实际密码更改由客户端端到端加密处理。",
        "timestamp": int(time.time() * 1000)
    })