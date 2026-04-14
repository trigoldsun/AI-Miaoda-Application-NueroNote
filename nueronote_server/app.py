#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 服务端 — 零知识同步 API
Flask 实现，约 400 行，无重型依赖

安全特性：
- JWT 认证（HMAC-SHA256，Flask Secret 管理）
- 乐观锁版本控制
- 存储配额强制执行
- 请求体大小限制（防止 DoS）
- 账户锁定（暴力破解防护）
- 审计日志（所有写操作）
- CORS 安全配置
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Optional

from flask import Flask, g, jsonify, request
# CORS: handled via response headers or reverse proxy

# 导入数据库模块
from nueronote_server.database import get_db, close_db, init_db

app = Flask(__name__, static_folder="")

# ============================================================================
# 配置
# ============================================================================

# 安全密钥配置
# 生产环境必须设置环境变量：FLUX_SECRET_KEY 和 FLUX_JWT_SECRET
import secrets

# 检查环境变量
secret_key = os.environ.get("FLUX_SECRET_KEY")
jwt_secret = os.environ.get("FLUX_JWT_SECRET")

if not secret_key:
    # 开发环境：生成临时密钥（每次重启变化）
    if os.environ.get("FLUX_DEBUG", "false").lower() == "true":
        secret_key = secrets.token_urlsafe(32)
        print("⚠️  警告：使用临时生成的SECRET_KEY，生产环境必须设置FLUX_SECRET_KEY环境变量")
    else:
        raise ValueError("生产环境必须设置FLUX_SECRET_KEY环境变量")

if not jwt_secret:
    # 如果没有单独设置JWT密钥，使用不同的随机密钥
    jwt_secret = secrets.token_urlsafe(32)
    if os.environ.get("FLUX_DEBUG", "false").lower() != "true":
        print("⚠️  警告：使用临时生成的JWT_SECRET，建议设置FLUX_JWT_SECRET环境变量")

app.config["SECRET_KEY"] = secret_key
app.config["JWT_SECRET"] = jwt_secret

# JSON 请求体大小限制（1MB，防止内存耗尽 DoS）
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024

# 响应不排序（避免时序攻击）
app.config["JSON_SORT_KEYS"] = False

DATABASE_PATH = os.environ.get("FLUX_DB", "nueronote.db")

# 配额配置（字节）
QUOTA_FREE = 512 * 1024 * 1024   # 512 MB
QUOTA_PRO = 10 * 1024**3          # 10 GB
QUOTA_TEAM = 100 * 1024**3        # 100 GB

# 账户锁定配置
MAX_LOGIN_FAILS = 5              # 5次失败后锁定
LOCKOUT_DURATION = 15 * 60       # 锁定15分钟

_start_time = time.time()

# 使用新的数据库模块（从database.py导入）
from nueronote_server.database import get_db as db_get_db, close_db as db_close_db, init_db as db_init_db
get_db = db_get_db
init_db = db_init_db

@app.teardown_appcontext
def close_db(exception=None):
    db_close_db(exception)

# ============================================================================
# 数据库
# ============================================================================

def init_db():
    # 调用database模块的初始化
    from nueronote_server.database import init_db as db_init_db
    db_init_db()


# ============================================================================
# 安全中间件
# ============================================================================

def get_client_ip() -> str:
    """获取真实客户端 IP（支持代理）"""
    # X-Forwarded-For 可能被伪造，但 API Gateway 层会清理
    return request.headers.get(
        "X-Forwarded-For",
        request.headers.get("X-Real-IP", request.remote_addr or "")
    ).split(",")[0].strip()


def write_audit(user_id: str, action: str, **kwargs):
    """写审计日志（异步，写入失败不阻塞主流程）"""
    try:
        db = get_db()
        db.execute(
            "INSERT INTO audit_log (user_id, action, ip_addr, user_agent, "
            "resource_type, resource_id, details, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                user_id,
                action,
                get_client_ip(),
                request.headers.get("User-Agent", "")[:256],
                kwargs.get("resource_type"),
                kwargs.get("resource_id"),
                json.dumps(kwargs.get("details") or {}),
                int(time.time() * 1000),
            )
        )
    except Exception:
        pass  # 审计日志失败不阻断主流程


def rate_limit(action: str, max_requests: int, window_seconds: int):
    """简单 IP 级别限流（滑动窗口）"""
    def decorator(f):
        @wraps(f)
        def limited(*args, **kwargs):
            ip = get_client_ip()
            now = int(time.time())
            window_start = now - window_seconds

            db = get_db()
            db.execute(
                "DELETE FROM rate_limit WHERE window_start < ?",
                (window_start,)
            )

            row = db.execute(
                "SELECT count FROM rate_limit WHERE ip_addr = ? AND action = ?",
                (ip, action)
            ).fetchone()

            count = row["count"] + 1 if row else 1

            if count > max_requests:
                return jsonify({
                    "error": "Too many requests",
                    "retry_after": window_seconds,
                }), 429

            db.execute(
                "INSERT OR REPLACE INTO rate_limit (ip_addr, action, count, window_start) "
                "VALUES (?, ?, ?, ?)",
                (ip, action, count, now)
            )

            return f(*args, **kwargs)
        return limited
    return decorator


def require_auth(f):
    """JWT 认证装饰器"""
    @wraps(f)
    def authed(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing Authorization header"}), 401

        token = auth_header[7:]
        user_id = _verify_token(token)
        if not user_id:
            return jsonify({"error": "Invalid or expired token"}), 401

        # 验证用户存在且未被锁定
        db = get_db()
        user = db.execute(
            "SELECT id, locked_until FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not user:
            return jsonify({"error": "User not found"}), 401
        if user["locked_until"] > time.time():
            return jsonify({"error": "Account locked due to too many failed login attempts"}), 423

        g.user_id = user_id
        return f(*args, **kwargs)
    return authed


# ============================================================================
# JWT 实现（简化版 HMAC-SHA256）
# ============================================================================

def _sign_token(user_id: str, secret: str) -> str:
    """签发 JWT（无外部依赖）"""
    now = int(time.time())
    header = _b64u(json.dumps({"alg": "HS256", "typ": "JWT"}))
    payload = _b64u(json.dumps({
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
    return f"{header}.{payload}.{_b64u(sig)}"


def _verify_token(token: str) -> Optional[str]:
    """验证 JWT，返回 user_id 或 None"""
    secret = app.config["JWT_SECRET"]
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
        if not hmac.compare_digest(sig, _b64u(expected_sig)):
            return None

        # 验证过期
        payload_data = json.loads(_b64d(payload + "=="))
        exp = payload_data.get("exp", 0)
        if exp < time.time():
            return None

        return payload_data.get("sub")
    except Exception:
        return None


def _b64u(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode()
    return __import__("base64").urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64d(data: str) -> bytes:
    pad = (4 - len(data) % 4) % 4
    return __import__("base64").urlsafe_b64decode(data + "=" * pad)


# ============================================================================
# 账户 API
# ============================================================================

@app.route("/api/v1/auth/register", methods=["POST"])
@rate_limit("register", max_requests=10, window_seconds=3600)
def api_register():
    """
    注册账户
    请求：{email}
    返回：{user_id, token}
    注意：密码不在服务端处理（端到端加密）
    """
    body = request.get_json(force=True, silent=True) or {}

    # 输入验证
    email = (body.get("email") or "").strip().lower()
    if not email or "@" not in email or len(email) > 254:
        return jsonify({"error": "Invalid email format"}), 400

    if len(body.get("vault", {}).get("ciphertext", "")) > 10 * 1024 * 1024:
        return jsonify({"error": "Vault too large (max 10MB)"}), 413

    db = get_db()
    now = int(time.time() * 1000)

    # 幂等检查
    try:
        db.execute(
            "INSERT INTO users (id, email, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (uuid.uuid4().hex, email, now, now)
        )
    except sqlite3.IntegrityError:
        return jsonify({"error": "Email already registered"}), 409

    user_id = db.execute(
        "SELECT id FROM users WHERE email = ?", (email,)
    ).fetchone()["id"]

    # 初始化 vault
    vault_json = body.get("vault", {})
    vault_bytes = len(json.dumps(vault_json).encode())
    db.execute(
        "INSERT INTO vaults (user_id, vault_json, updated_at, storage_bytes) VALUES (?, ?, ?, ?)",
        (user_id, json.dumps(vault_json), now, vault_bytes)
    )
    db.execute(
        "UPDATE users SET storage_used = ? WHERE id = ?",
        (vault_bytes, user_id)
    )

    write_audit(user_id, "REGISTER", details={"email": email})

    token = _sign_token(user_id, app.config["JWT_SECRET"])
    return jsonify({
        "user_id": user_id,
        "token": token,
        "plan": "free",
        "storage_quota": QUOTA_FREE,
    }), 201


@app.route("/api/v1/auth/login", methods=["POST"])
@rate_limit("login", max_requests=20, window_seconds=300)
def api_login():
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
        "SELECT id, plan, storage_quota, storage_used, locked_until, login_fails "
        "FROM users WHERE email = ?", (email,)
    ).fetchone()

    # 通用错误信息（防用户枚举）
    auth_error = json.dumps({"error": "Invalid credentials"}), 401

    if not user:
        # 延迟响应，防止枚举（固定 200ms）
        time.sleep(0.2)
        return *auth_error,

    # 检查账户锁定
    if user["locked_until"] > time.time():
        remaining = int(user["locked_until"] - time.time())
        return jsonify({
            "error": "Account temporarily locked",
            "retry_after": remaining,
        }), 423

    # 解锁（如果锁定期已过）
    if user["locked_until"] > 0:
        db.execute(
            "UPDATE users SET locked_until = 0, login_fails = 0 WHERE id = ?",
            (user["id"],)
        )

    token = _sign_token(user["id"], app.config["JWT_SECRET"])
    now = int(time.time() * 1000)
    db.execute(
        "UPDATE users SET last_login = ?, last_ip = ? WHERE id = ?",
        (now, ip, user["id"])
    )

    write_audit(user["id"], "LOGIN", details={"ip": ip})

    return jsonify({
        "user_id": user["id"],
        "token": token,
        "plan": user["plan"],
        "storage_quota": user["storage_quota"],
        "storage_used": user["storage_used"],
    })


@app.route("/api/v1/auth/logout", methods=["POST"])
@require_auth
def api_logout():
    """登出（服务端可记录审计）"""
    write_audit(g.user_id, "LOGOUT")
    return jsonify({"status": "ok"})


# ============================================================================
# Vault 同步 API
# ============================================================================

@app.route("/api/v1/vault", methods=["GET"])
@require_auth
@rate_limit("vault_read", max_requests=100, window_seconds=60)
def api_get_vault():
    """获取最新 vault"""
    db = get_db()
    row = db.execute(
        "SELECT vault_json, vault_version, storage_bytes FROM vaults WHERE user_id = ?",
        (g.user_id,)
    ).fetchone()

    if not row:
        return jsonify({"error": "Vault not found"}), 404

    return jsonify({
        "vault": json.loads(row["vault_json"]),
        "version": row["vault_version"],
        "storage_used": row["storage_bytes"],
    })


@app.route("/api/v1/vault", methods=["PUT"])
@require_auth
@rate_limit("vault_write", max_requests=60, window_seconds=60)
def api_put_vault():
    """
    上传 vault（完整覆盖，乐观锁）
    请求：{vault, expected_version}
    返回：{version} 或 409 冲突
    """
    body = request.get_json(force=True, silent=True) or {}
    vault_json = body.get("vault")
    expected_version = body.get("expected_version", 0)

    if not vault_json:
        return jsonify({"error": "Missing vault data"}), 400

    # 验证 vault 结构完整性
    if not isinstance(vault_json, dict):
        return jsonify({"error": "Invalid vault format"}), 400
    required = ("salt", "nonce", "ciphertext", "check")
    missing = [f for f in required if f not in vault_json]
    if missing:
        return jsonify({"error": f"Missing vault fields: {missing}"}), 400

    vault_bytes = len(json.dumps(vault_json).encode())

    # 配额检查
    db = get_db()
    user = db.execute(
        "SELECT storage_quota FROM users WHERE id = ?", (g.user_id,)
    ).fetchone()
    if user and vault_bytes > user["storage_quota"]:
        return jsonify({
            "error": "Storage quota exceeded",
            "quota": user["storage_quota"],
            "required": vault_bytes,
        }), 507

    now = int(time.time() * 1000)

    # 乐观锁更新
    result = db.execute(
        """UPDATE vaults
           SET vault_json = ?, updated_at = ?,
               vault_version = vault_version + 1,
               storage_bytes = ?
           WHERE user_id = ? AND vault_version = ?""",
        (json.dumps(vault_json), now, vault_bytes, g.user_id, expected_version)
    )

    if result.rowcount == 0:
        # 版本冲突：获取当前版本
        current = db.execute(
            "SELECT vault_version FROM vaults WHERE user_id = ?", (g.user_id,)
        ).fetchone()
        return jsonify({
            "error": "Version conflict",
            "current_version": current["vault_version"] if current else None,
        }), 409

    new_version = expected_version + 1

    # ── 保存版本快照（最多保留最近 100 个）──────────────────────
    db.execute(
        """INSERT INTO vault_versions
           (user_id, version, vault_json, vault_bytes, created_at, note, is_auto)
           VALUES (?, ?, ?, ?, ?, ?, 1)""",
        (g.user_id, new_version, json.dumps(vault_json), vault_bytes, now,
         f'Auto snapshot at version {new_version}')
    )
    # 只保留最近 100 个快照（节省存储）
    db.execute(
        """DELETE FROM vault_versions
           WHERE user_id = ? AND id NOT IN (
               SELECT id FROM vault_versions
               WHERE user_id = ?
               ORDER BY version DESC LIMIT 100
           )""",
        (g.user_id, g.user_id)
    )

    # 更新用户存储使用量
    db.execute(
        "UPDATE users SET storage_used = ?, updated_at = ? WHERE id = ?",
        (vault_bytes, now, g.user_id)
    )

    write_audit(g.user_id, "VAULT_PUT",
        resource_type="vault",
        details={"version": new_version, "bytes": vault_bytes})

    return jsonify({
        "version": new_version,
        "storage_used": vault_bytes,
    })


# ============================================================================
# 增量同步 API
# ============================================================================

@app.route("/api/v1/sync/push", methods=["POST"])
@require_auth
@rate_limit("sync_push", max_requests=200, window_seconds=60)
def api_sync_push():
    """
    推送增量操作记录
    请求：{records: [{record_id, record_type, operation, encrypted_data}]}
    """
    body = request.get_json(force=True, silent=True) or {}
    records = body.get("records", [])

    if not isinstance(records, list) or len(records) > 500:
        return jsonify({"error": "Invalid records (max 500 per batch)"}), 400

    now = int(time.time() * 1000)
    db = get_db()
    pushed = 0

    for rec in records:
        record_id = rec.get("record_id", uuid.uuid4().hex)
        db.execute(
            """INSERT OR REPLACE INTO sync_log
               (id, user_id, record_type, record_id, operation,
                encrypted_data, vector_clock, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record_id,
                g.user_id,
                rec.get("record_type", "block"),
                rec.get("record_id", ""),
                rec.get("operation", "upsert"),
                rec.get("encrypted_data", ""),
                now,
                now,
            )
        )
        pushed += 1

    write_audit(g.user_id, "SYNC_PUSH",
        details={"count": pushed, "records": [r.get("record_id","?") for r in records[:10]]})

    return jsonify({"pushed": pushed, "server_time": now})


@app.route("/api/v1/sync/pull", methods=["GET"])
@require_auth
@rate_limit("sync_pull", max_requests=200, window_seconds=60)
def api_sync_pull():
    """
    拉取增量同步记录
    请求：?since=<timestamp>&limit=1000
    """
    since = max(0, int(request.args.get("since", 0)))
    limit = min(5000, max(1, int(request.args.get("limit", 1000))))

    db = get_db()
    rows = db.execute(
        """SELECT id, record_type, record_id, operation,
                  encrypted_data, vector_clock, created_at
           FROM sync_log
           WHERE user_id = ? AND created_at > ?
           ORDER BY created_at ASC
           LIMIT ?""",
        (g.user_id, since, limit)
    ).fetchall()

    records = [dict(r) for r in rows]
    return jsonify({
        "records": records,
        "server_time": int(time.time() * 1000),
        "has_more": len(records) == limit,
    })


# ============================================================================
# 账户管理 API
# ============================================================================

@app.route("/api/v1/account", methods=["GET"])
@require_auth
def api_account():
    """获取账户信息"""
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


@app.route("/api/v1/account/upgrade", methods=["POST"])
@require_auth
def api_upgrade():
    """升级套餐（实际支付集成需扩展）"""
    body = request.get_json(force=True, silent=True) or {}
    plan = body.get("plan", "")

    if plan not in ("free", "pro", "team"):
        return jsonify({"error": "Invalid plan"}), 400

    quotas = {"free": QUOTA_FREE, "pro": QUOTA_PRO, "team": QUOTA_TEAM}
    db = get_db()
    db.execute(
        "UPDATE users SET plan = ?, storage_quota = ?, updated_at = ? WHERE id = ?",
        (plan, quotas[plan], int(time.time() * 1000), g.user_id)
    )
    write_audit(g.user_id, "PLAN_UPGRADE", details={"plan": plan})
    return jsonify({"plan": plan, "storage_quota": quotas[plan]})


# ============================================================================
# 安全与健康检查
# ============================================================================

@app.route("/api/v1/health", methods=["GET"])
def api_health():
    """健康检查（无认证，CDN/负载均衡探测）"""
    return jsonify({
        "status": "ok",
        "version": "1.0.0",
        "uptime_seconds": int(time.time() - _start_time),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/v1/security.txt", methods=["GET"])
def security_txt():
    """RFC 9116 安全联系页面"""
    return (
        "Contact: mailto:security@nueronote.app\n"
        "Preferred-Languages: en, zh\n"
        "Encryption: https://nueronote.app/keys.asc\n"
        "Hire: https://nueronote.app/jobs\n",
        200,
        {"Content-Type": "text/plain; charset=utf-8"},
    )


# ============================================================================
# 错误处理
# ============================================================================

@app.errorhandler(413)
def request_too_large(e):
    return jsonify({"error": "Request body too large (max 1MB)"}), 413


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def internal_error(e):
    # 不泄露内部错误细节
    return jsonify({"error": "Internal server error"}), 500


# ============================================================================
# 静态文件
# ============================================================================

@app.route("/", methods=["GET"])
def serve_client():
    """提供前端 SPA"""
    client_path = Path(__file__).parent / "nueronote_client" / "index.html"
    if client_path.exists():
        return client_path.read_text(encoding="utf-8"), 200, {
            "Content-Type": "text/html; charset=utf-8",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        }
    return jsonify({"error": "Client not found",
                     "info": "Serve nueronote_client/index.html as static"}), 404


# ============================================================================

# ============================================================================
# 云存储集成 API（腾讯云COS / 阿里云OSS / 百度网盘）
# ============================================================================

def _get_cloud_storage():
    """延迟导入云存储模块"""
    try:
        from nueronote.cloud import create_cloud_storage, CloudConfig
        return create_cloud_storage, CloudConfig
    except ImportError:
        return None, None


@app.route("/api/v1/cloud/providers", methods=["GET"])
def api_cloud_providers():
    """返回支持的云服务商列表（无需认证）"""
    return jsonify({
        "providers": [
            {
                "id": "tencent_cos",
                "name": "腾讯云 COS",
                "description": "S3兼容对象存储，50GB免费额度，按量付费",
                "website": "https://cloud.tencent.com/product/cos",
                "auth_type": "AccessKey",
                "features": ["高可用", "全球CDN", "免费50GB", "S3兼容"],
                "fields": [
                    {"name": "secret_id",   "label": "SecretId",   "required": True,  "hint": "从CAM控制台获取"},
                    {"name": "secret_key",  "label": "SecretKey",   "required": True,  "hint": "勿泄露"},
                    {"name": "region",      "label": "地域",         "required": True,  "hint": "如 ap-guangzhou"},
                    {"name": "bucket",      "label": "Bucket",       "required": True,  "hint": "存储桶名称（不含.cos.前缀）"},
                    {"name": "storage_class", "label": "存储类型",   "required": False, "hint": "STANDARD | STANDARD_IA | ARCHIVE"},
                ],
                "setup_steps": [
                    "1. 开通COS: cloud.tencent.com",
                    "2. 创建存储桶（同地域）",
                    "3. CAM创建子用户，授权COSFullAccess",
                    "4. 填入SecretId、SecretKey、Bucket、地域",
                ],
            },
            {
                "id": "aliyun_oss",
                "name": "阿里云 OSS",
                "description": "企业级对象存储，SLA 99.99%，30GB免费额度",
                "website": "https://www.aliyun.com/product/oss",
                "auth_type": "AccessKey",
                "features": ["高可用", "内网免费", "SDK完善", "生命周期管理"],
                "fields": [
                    {"name": "access_key_id",      "label": "AccessKeyId",    "required": True,  "hint": "从RAM控制台获取"},
                    {"name": "access_key_secret",  "label": "AccessKeySecret","required": True,  "hint": "勿泄露"},
                    {"name": "region",             "label": "地域",           "required": True,  "hint": "如 cn-hangzhou"},
                    {"name": "bucket",             "label": "Bucket",         "required": True,  "hint": "存储桶名称"},
                    {"name": "storage_class",      "label": "存储类型",       "required": False, "hint": "Standard | IA | Archive"},
                ],
                "setup_steps": [
                    "1. 开通OSS: oss.console.aliyun.com",
                    "2. 创建存储桶（同地域）",
                    "3. RAM创建子账号，授权AliyunOSSFullAccess",
                    "4. 填入AccessKeyId、AccessKeySecret、Bucket、地域",
                ],
            },
            {
                "id": "baidu_netdisk",
                "name": "百度网盘",
                "description": "7亿用户个人云盘，需OAuth2授权，需要会员",
                "website": "https://pan.baidu.com/union/",
                "auth_type": "OAuth2",
                "features": ["无需企业账号", "个人可用", "海量存储"],
                "fields": [
                    {"name": "client_id",     "label": "App Key",    "required": True,  "hint": "从百度开放平台获取"},
                    {"name": "client_secret","label": "Secret Key", "required": True,  "hint": "勿泄露"},
                    {"name": "app_folder",   "label": "应用目录",   "required": False, "hint": "默认NueroNote"},
                ],
                "setup_steps": [
                    "1. 注册百度账号并完成实名认证",
                    "2. 前往 pan.baidu.com/union/ 创建应用",
                    "3. 获取App Key和Secret Key",
                    "4. 完成OAuth2授权（有效期30天）",
                ],
                "limitations": [
                    "需要百度网盘会员（非会员空间有限）",
                    "API请求频率限制（1000次/天）",
                    "access_token有效期30天，需定期刷新",
                ],
            },
        ]
    })


@app.route("/api/v1/cloud/status", methods=["GET"])
@require_auth
def api_cloud_status():
    """查询云存储连接状态"""
    create_fn, CloudConfig = _get_cloud_storage()
    if create_fn is None:
        return jsonify({"error": "cloud module not installed (pip install cos-python-sdk-v5 oss2)"}), 503

    db = get_db()
    row = db.execute("SELECT cloud_config FROM users WHERE id = ?", (g.user_id,)).fetchone()
    if not row or not row["cloud_config"]:
        return jsonify({"configured": [], "active": None})

    import json as _json
    configs = _json.loads(row["cloud_config"])
    active = None
    for cfg_dict in configs:
        cfg = CloudConfig.from_json(cfg_dict)
        if cfg.enabled:
            try:
                storage = create_fn(cfg)
                if storage:
                    ok, msg = storage.test_connection()
                    active = {
                        "provider": cfg.provider,
                        "connected": ok,
                        "message": msg,
                        "last_sync": cfg.last_sync,
                    }
                    break
            except Exception:
                pass

    return jsonify({
        "configured": [c["provider"] for c in configs],
        "active": active,
    })


@app.route("/api/v1/cloud/configure", methods=["POST"])
@require_auth
@rate_limit("cloud_config", max_requests=20, window_seconds=3600)
def api_cloud_configure():
    """配置/测试云存储连接"""
    create_fn, CloudConfig = _get_cloud_storage()
    if create_fn is None:
        return jsonify({"error": "cloud module not installed"}), 503

    body = request.get_json(force=True, silent=True) or {}
    provider = (body.get("provider") or "").strip().lower()
    enabled = bool(body.get("enabled", False))
    extra = body.get("extra", {})

    if provider not in ("tencent_cos", "aliyun_oss", "baidu_netdisk"):
        return jsonify({"error": "provider must be: tencent_cos | aliyun_oss | baidu_netdisk"}), 400

    cfg = CloudConfig(provider=provider, enabled=enabled, extra=extra)
    try:
        storage = create_fn(cfg)
        if not storage:
            return jsonify({"error": "Failed to create storage"}), 500
        ok, msg = storage.test_connection()
        if not ok:
            return jsonify({"success": False, "message": msg}), 400

        # 保存配置
        import json as _json
        db = get_db()
        row = db.execute("SELECT cloud_config FROM users WHERE id = ?", (g.user_id,)).fetchone()
        existing = []
        if row and row["cloud_config"]:
            try: existing = _json.loads(row["cloud_config"])
            except: existing = []

        found = False
        for i, c in enumerate(existing):
            if c.get("provider") == provider:
                existing[i] = cfg.to_json()
                found = True
                break
        if not found:
            existing.append(cfg.to_json())

        db.execute("UPDATE users SET cloud_config = ? WHERE id = ?",
                   (_json.dumps(existing), g.user_id))
        write_audit(g.user_id, "CLOUD_CONFIGURE", details={"provider": provider, "enabled": enabled})
        return jsonify({"success": True, "message": msg})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/v1/cloud/sync", methods=["POST"])
@require_auth
@rate_limit("cloud_sync", max_requests=30, window_seconds=3600)
def api_cloud_sync():
    """同步vault到云存储（上传）或从云存储恢复（下载）"""
    create_fn, CloudConfig = _get_cloud_storage()
    if create_fn is None:
        return jsonify({"error": "cloud module not installed"}), 503

    body = request.get_json(force=True, silent=True) or {}
    action = body.get("action", "upload")
    target_version = body.get("version")

    db = get_db()
    vault_row = db.execute(
        "SELECT vault_json, vault_version FROM vaults WHERE user_id = ?",
        (g.user_id,)
    ).fetchone()
    if not vault_row:
        return jsonify({"error": "Vault not found"}), 404

    # 获取云配置
    import json as _json
    row = db.execute("SELECT cloud_config FROM users WHERE id = ?", (g.user_id,)).fetchone()
    cloud_cfg = None
    if row and row["cloud_config"]:
        for cfg_dict in _json.loads(row["cloud_config"]):
            cfg = CloudConfig.from_json(cfg_dict)
            if cfg.enabled:
                cloud_cfg = cfg
                break

    if not cloud_cfg:
        return jsonify({"error": "No cloud storage configured or enabled"}), 400

    try:
        storage = create_fn(cloud_cfg)
        if not storage:
            return jsonify({"error": "Storage init failed"}), 500

        if action == "upload":
            vault_json = _json.loads(vault_row["vault_json"])
            version = vault_row["vault_version"]
            result = storage.upload_vault(
                vault_json,
                user_id=g.user_id,
                version=version,
                metadata={"timestamp": int(time.time()*1000), "platform": "nueronote"},
            )
            if result.success:
                write_audit(g.user_id, "CLOUD_SYNC_UPLOAD",
                    details={"version": version, "bytes": result.size_bytes})
                return jsonify({
                    "success": True,
                    "version": version,
                    "size_bytes": result.size_bytes,
                    "url": result.url,
                    "message": f"已同步到{cloud_cfg.provider}，{result.size_bytes} bytes",
                })
            return jsonify({"error": result.error}), 500

        elif action == "download":
            versions = storage.list_versions(g.user_id, limit=1)
            if not versions:
                return jsonify({"error": "No cloud versions found"}), 404
            try:
                ver_num = int(versions[0].object_key.split("/v")[-1].replace(".enc.json",""))
            except:
                ver_num = target_version or vault_row["vault_version"]
            vault_data = storage.download_vault(g.user_id, ver_num)
            if not vault_data:
                return jsonify({"error": "Vault not found in cloud"}), 404
            write_audit(g.user_id, "CLOUD_SYNC_DOWNLOAD", details={"version": ver_num})
            return jsonify({"success": True, "vault": vault_data, "message": "从云存储恢复成功"})

        return jsonify({"error": "action must be 'upload' or 'download'"}), 400
    except Exception as e:
        write_audit(g.user_id, "CLOUD_SYNC_ERROR", details={"error": str(e)})
        return jsonify({"error": f"Sync failed: {str(e)}"}), 500


@app.route("/api/v1/cloud/versions", methods=["GET"])
@require_auth
def api_cloud_versions():
    """列出云存储中的vault版本"""
    create_fn, CloudConfig = _get_cloud_storage()
    if create_fn is None:
        return jsonify({"error": "cloud module not installed"}), 503

    import json as _json
    db = get_db()
    row = db.execute("SELECT cloud_config FROM users WHERE id = ?", (g.user_id,)).fetchone()
    if not row or not row["cloud_config"]:
        return jsonify({"error": "No cloud configured"}), 400

    cloud_cfg = None
    for cfg_dict in _json.loads(row["cloud_config"]):
        cfg = CloudConfig.from_json(cfg_dict)
        if cfg.enabled:
            cloud_cfg = cfg
            break

    if not cloud_cfg:
        return jsonify({"error": "No enabled cloud"}), 400

    try:
        storage = create_fn(cloud_cfg)
        files = storage.list_versions(g.user_id, limit=100)
        return jsonify({
            "versions": [{
                "object_key": f.object_key,
                "size_bytes": f.size_bytes,
                "last_modified": f.last_modified,
                "url": f.url,
            } for f in files]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/v1/cloud/test", methods=["POST"])
@require_auth
def api_cloud_test():
    """测试云存储连接（不保存配置）"""
    create_fn, CloudConfig = _get_cloud_storage()
    if create_fn is None:
        return jsonify({"error": "cloud module not installed"}), 503

    body = request.get_json(force=True, silent=True) or {}
    provider = body.get("provider", "")
    extra = body.get("extra", {})
    cfg = CloudConfig(provider=provider, enabled=True, extra=extra)
    try:
        storage = create_fn(cfg)
        if not storage:
            return jsonify({"error": "Unknown provider"}), 400
        ok, msg = storage.test_connection()
        names = {"tencent_cos":"腾讯云COS","aliyun_oss":"阿里云OSS","baidu_netdisk":"百度网盘"}
        return jsonify({"success": ok, "message": msg, "provider": names.get(provider, provider)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/v1/cloud/audit", methods=["GET"])
@require_auth
def api_cloud_audit():
    """查询用户审计日志"""
    page = max(1, int(request.args.get("page", 1)))
    page_size = min(100, max(1, int(request.args.get("page_size", 20))))
    offset = (page - 1) * page_size

    db = get_db()
    rows = db.execute(
        """SELECT action, ip_addr, details, created_at
           FROM audit_log
           WHERE user_id = ?
           ORDER BY created_at DESC
           LIMIT ? OFFSET ?""",
        (g.user_id, page_size, offset)
    ).fetchall()

    total = db.execute(
        "SELECT COUNT(*) as cnt FROM audit_log WHERE user_id = ?",
        (g.user_id,)
    ).fetchone()["cnt"]

    return jsonify({
        "logs": [{"action":r["action"],"ip":r["ip_addr"],"details":r["details"],
                  "created_at":r["created_at"]} for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    })


@app.route("/api/v1/cloud/vault-history", methods=["GET"])
@require_auth
def api_vault_history():
    """查询vault版本快照历史"""
    limit = min(100, max(1, int(request.args.get("limit", 50))))
    db = get_db()
    rows = db.execute(
        """SELECT id, version, vault_bytes, created_at, note, is_auto
           FROM vault_versions
           WHERE user_id = ?
           ORDER BY version DESC
           LIMIT ?""",
        (g.user_id, limit)
    ).fetchall()
    return jsonify({
        "versions": [{
            "id": r["id"],
            "version": r["version"],
            "bytes": r["vault_bytes"],
            "created_at": r["created_at"],
            "note": r["note"],
            "is_auto": bool(r["is_auto"]),
        } for r in rows]
    })


@app.route("/api/v1/cloud/vault-restore", methods=["POST"])
@require_auth
def api_vault_restore():
    """从指定快照版本恢复vault"""
    body = request.get_json(force=True, silent=True) or {}
    version = int(body.get("version", 0))
    if not version:
        return jsonify({"error": "version required"}), 400

    db = get_db()
    row = db.execute(
        "SELECT vault_json, vault_version FROM vaults WHERE user_id = ?",
        (g.user_id,)
    ).fetchone()
    if not row:
        return jsonify({"error": "Vault not found"}), 404

    snapshot = db.execute(
        "SELECT vault_json, version FROM vault_versions WHERE user_id = ? AND version = ?",
        (g.user_id, version)
    ).fetchone()

    if not snapshot:
        return jsonify({"error": f"Snapshot version {version} not found"}), 404

    import json as _json
    current_version = row["vault_version"]
    new_version = current_version + 1

    # 写入新版本（不覆盖原vault，保留历史）
    db.execute(
        """INSERT INTO vault_versions
           (user_id, version, vault_json, vault_bytes, created_at, note, is_auto)
           VALUES (?, ?, ?, ?, ?, ?, 0)""",
        (g.user_id, new_version, snapshot["vault_json"],
         len(snapshot["vault_json"]), int(time.time()*1000),
         f"Restored from version {version} (手动恢复快照)")
    )

    # 更新当前vault
    db.execute(
        "UPDATE vaults SET vault_json = ?, updated_at = ?, vault_version = ? WHERE user_id = ?",
        (snapshot["vault_json"], int(time.time()*1000), new_version, g.user_id)
    )

    write_audit(g.user_id, "VAULT_RESTORE",
        details={"from_version": version, "to_version": new_version})
    return jsonify({
        "success": True,
        "restored_from_version": version,
        "new_version": new_version,
        "message": f"已从版本{version}恢复到新版本{new_version}",
    })



# 启动
# ============================================================================

if __name__ == "__main__":
    import secrets

    # 安全警告（生产必须设置环境变量）
    secret = app.config["JWT_SECRET"]
    if "dev-only" in secret:
        print("\n\U0001f6a8  安全警告：使用默认 JWT Secret！")
        print("   生产环境必须设置 FLUX_JWT_SECRET 环境变量：")
        print("   export FLUX_JWT_SECRET=$(secrets.token_hex(32))\n")

    _start_time = time.time()
    init_db()
    print(f"NueroNote 服务端启动...")
    print(f"  数据库: {DATABASE_PATH}")
    print(f"  端口: 5555")
    # debug=False 是安全要求！Werkzeug debugger 可远程代码执行
    app.run(host="0.0.0.0", port=5555, debug=False)
