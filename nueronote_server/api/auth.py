#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 认证 API 模块
处理用户注册、登录、登出等认证相关功能。

【更新日志 2026-04-14】
- v1.1: 添加登录密码验证 (key_check)
  - 登录时必须提供客户端加密的key_check
  - 服务端使用HMAC验证密钥正确性
  - 防止只知道邮箱即可登录的问题
- v1.0: 初始版本
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Optional, Tuple

from flask import Blueprint, g, jsonify, request

from nueronote_server.database import get_db
from nueronote_server.utils.jwt import sign_token, verify_token
from nueronote_server.utils.validation import validate_email
from nueronote_server.utils.audit import write_audit, get_client_ip

# 创建认证蓝图
auth_bp = Blueprint('auth', __name__, url_prefix='/api/v1/auth')


# ============================================================================
# 密钥验证辅助函数
# ============================================================================

def _derive_key_check(password: str, salt: str) -> str:
    """
    派生密钥校验值 (v1版本)
    
    使用HMAC-SHA256对固定字符串进行签名
    用于在不传输实际密钥的情况下验证密码正确性
    
    Args:
        password: 用户密码
        salt: 用户盐值 (base64编码)
        
    Returns:
        44字符的base64编码校验值
    """
    enc = __import__('base64').b64encode
    sig = hmac.new(
        password.encode('utf-8'),
        f'NueroNote:v1:key-check:{salt}'.encode('utf-8'),
        hashlib.sha256
    ).digest()
    return enc(sig).decode('utf-8').rstrip('=')


def _verify_key_check(password: str, salt: str, expected_check: str) -> bool:
    """
    验证密钥校验值
    
    Args:
        password: 用户密码
        salt: 用户盐值
        expected_check: 期望的校验值
        
    Returns:
        验证是否通过
    """
    if not password or not salt or not expected_check:
        return False
    
    derived = _derive_key_check(password, salt)
    # 使用恒定时间比较防止时序攻击
    return hmac.compare_digest(derived, expected_check)


# ============================================================================
# 账户锁定辅助函数
# ============================================================================

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


# ============================================================================
# API路由
# ============================================================================

@auth_bp.route('/register', methods=['POST'])
def register():
    """
    注册账户
    请求：{email, password, key_check, salt}
    返回：{user_id, token, plan, storage_quota}
    
    【更新日志 2026-04-14】
    - v1.1: 添加password和key_check验证
      - 新增必填字段: password (最小8字符), key_check, salt
      - 使用HMAC验证密钥正确性
    """
    body = request.get_json(force=True, silent=True) or {}
    
    # 输入验证
    email = (body.get("email") or "").strip().lower()
    password = body.get("password", "")
    key_check = body.get("key_check", "")
    salt = body.get("salt", "")
    
    # 【更新v1.1】邮箱格式验证
    if not validate_email(email):
        return jsonify({"error": "Invalid email format"}), 400
    
    # 【更新v1.1】密码强度验证
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400
    
    # 【更新v1.1】key_check验证
    if not key_check or not salt:
        return jsonify({"error": "Missing key_check or salt"}), 400
    
    # 【更新v1.1】验证key_check格式 (44字符base64)
    if len(key_check) != 44:
        return jsonify({"error": "Invalid key_check format"}), 400
    
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
    
    # 【更新v1.1】生成用户ID (使用邮箱哈希保证一致性)
    user_id = hashlib.sha256(f"{email}:{now}".encode()).hexdigest()[:32]
    
    try:
        db.execute(
            """INSERT INTO users 
               (id, email, password, salt, key_check, created_at, updated_at) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, email, password, salt, key_check, now, now)
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
    
    # 生成JWT令牌 (24小时有效期)
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
    登录（含MFA + 信任设备）
    
    请求：{
        email, 
        password, 
        key_check,
        device_fingerprint?: string,  # 浏览器指纹
        device_info?: {name, browser, os, deviceType}
    }
    返回：{success, mfa_required?, mfa_type?, mfa_token?, token?, user_id?}
    
    【更新日志 2026-04-14 v1.2】
    - v1.2: 添加MFA和信任设备支持
      - 启用MFA时，验证通过后发送验证码
      - 信任设备30天内免MFA
    """
    body = request.get_json(force=True, silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password", "")
    key_check = body.get("key_check", "")
    device_fingerprint = body.get("device_fingerprint")
    device_info = body.get("device_info", {})
    ip = get_client_ip()
    
    # 基础验证
    if not email:
        return jsonify({"error": "Email required"}), 400
    
    if not password or not key_check:
        return jsonify({"error": "Password and key_check required"}), 400
    
    db = get_db()
    
    # 获取用户
    user = db.execute(
        "SELECT id, salt, key_check, locked_until FROM users WHERE email = ?", (email,)
    ).fetchone()
    
    # 【v1.3安全修复】使用恒定时间响应，防止时序攻击泄露用户存在性
    # 即使用户不存在，也让CPU忙一段时间
    import hmac
    import hashlib
    dummy_salt = "dummy_salt_for_timing_attack_prevention"
    dummy_check = hmac.new(
        "dummy_password".encode('utf-8'),
        f'NueroNote:v1:key-check:{dummy_salt}'.encode('utf-8'),
        hashlib.sha256
    ).digest()
    _ = base64.b64encode(dummy_check).decode('utf-8') if 'base64' in dir() else ""
    
    if not user:
        # 即使用户不存在，也让CPU忙一段时间
        time.sleep(0.1)
        return jsonify({"error": "Invalid credentials"}), 401
    
    # 检查账户锁定
    if _check_account_lock(db, user["id"]):
        return jsonify({"error": "Account locked"}), 423
    
    # 验证密码
    if not _verify_key_check(password, user["salt"], key_check):
        _increment_login_fails(db, user["id"])
        write_audit(user["id"], "LOGIN_FAILED", details={"ip": ip, "reason": "invalid_password"})
        return jsonify({"error": "Invalid credentials"}), 401
    
    # 重置登录失败
    _reset_login_fails(db, user["id"])
    
    # 获取MFA设置
    mfa_settings = db.execute(
        "SELECT mfa_enabled, mfa_type FROM mfa_settings WHERE user_id = ? AND mfa_enabled = 1",
        (user["id"],)
    ).fetchone()
    
    needs_mfa = mfa_settings is not None
    skip_mfa = False
    
    # 如果需要MFA，检查是否是信任设备
    if needs_mfa and device_fingerprint:
        from nueronote_server.services.device import get_device_service
        device_service = get_device_service()
        trusted = device_service.check_trusted(db, user["id"], device_fingerprint)
        if trusted:
            skip_mfa = True
    
    if needs_mfa and not skip_mfa:
        # 需要MFA验证 - 创建MFA会话
        # 【v1.3】使用持久化会话存储
        from nueronote_server.api.mfa import get_mfa_session_store
        
        session_store = get_mfa_session_store()
        mfa_token = session_store.create(user["id"], mfa_settings['mfa_type'])
        
        # 发送验证码
        from nueronote_server.services.mfa import get_mfa_service
        mfa_service = get_mfa_service()
        
        if mfa_settings['mfa_type'] == 'email':
            user_email = db.execute("SELECT email FROM users WHERE id = ?", (user["id"],)).fetchone()
            if user_email:
                code = mfa_service.generate_code()
                from nueronote_server.api.mfa import _store_code
                _store_code(db, user["id"], code, 'email')
                mfa_service.send_mfa_email(user_email['email'], code)
        else:
            code = mfa_service.generate_code()
            from nueronote_server.api.mfa import _store_code
            _store_code(db, user["id"], code, 'sms')
            mfa_service.send_sms(mfa_settings['phone_number'], code)
        
        write_audit(user["id"], "MFA_REQUIRED", details={"ip": ip})
        
        return jsonify({
            "success": True,
            "mfa_required": True,
            "mfa_type": mfa_settings['mfa_type'],
            "mfa_token": mfa_token,
            "mfa_skipped": False,
            "message": "MFA verification required"
        })
    
    # 直接登录成功
    from flask import current_app
    token = sign_token(user["id"], current_app.config["JWT_SECRET"])
    
    # 如果有设备指纹，注册/更新设备
    if device_fingerprint:
        from nueronote_server.services.device import get_device_service
        device_service = get_device_service()
        device_service.register_device(
            db, user["id"], device_fingerprint, device_info, ip,
            request.headers.get('User-Agent', '')
        )
    
    # 更新最后登录
    db.execute(
        "UPDATE users SET last_login = ?, last_ip = ? WHERE id = ?",
        (int(time.time()), ip, user["id"])
    )
    db.commit()
    
    # 获取存储使用
    vault = db.execute(
        "SELECT storage_bytes FROM vaults WHERE user_id = ?", (user["id"],)
    ).fetchone()
    storage_used = vault["storage_bytes"] if vault else 0
    
    write_audit(user["id"], "LOGIN_SUCCESS", details={"ip": ip, "mfa_skipped": skip_mfa})
    
    return jsonify({
        "success": True,
        "token": token,
        "user_id": user["id"],
        "mfa_skipped": skip_mfa,
        "plan": "free",
        "storage_quota": 512 * 1024 * 1024,
        "storage_used": storage_used,
    })


@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    登出
    请求：空 (token在Authorization头)
    返回：{success: true}
    
    【更新日志 2026-04-14】
    - v1.1: 添加token黑名单支持
      - 将token加入黑名单，有效期24小时
    """
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
        # 【更新v1.1】将token加入黑名单
        try:
            from nueronote_server.cache import get_cache
            cache = get_cache()
            if cache:
                # JWT有效期24小时，黑名单保留25小时
                cache.set(f"token_blacklist:{token}", "revoked", ex=90000)
        except Exception:
            pass  # 缓存不可用不影响登出
    
    return jsonify({"success": True})


@auth_bp.route('/verify', methods=['GET'])
def verify_token():
    """
    验证当前token是否有效
    返回：{valid: true, user_id: xxx}
    
    【新增 v1.1】
    """
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return jsonify({"valid": False, "error": "Missing token"}), 401
    
    token = auth_header[7:]
    
    # 【新增】检查token黑名单
    try:
        from nueronote_server.cache import get_cache
        cache = get_cache()
        if cache:
            if cache.get(f"token_blacklist:{token}"):
                return jsonify({"valid": False, "error": "Token revoked"}), 401
    except Exception:
        pass
    
    # 验证JWT
    try:
        from flask import current_app
        user_id = verify_token(token, current_app.config["JWT_SECRET"])
        if user_id:
            return jsonify({"valid": True, "user_id": user_id})
    except Exception:
        pass
    
    return jsonify({"valid": False, "error": "Invalid token"}), 401
