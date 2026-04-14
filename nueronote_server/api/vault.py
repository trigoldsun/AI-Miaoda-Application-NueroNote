#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote Vault API 模块
处理Vault存储、版本管理和存储配额。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Optional, Dict, Any

from flask import Blueprint, g, jsonify, request

from nueronote_server.database import get_db
from nueronote_server.utils.jwt import verify_token

from nueronote_server.utils.audit import write_audit

# 创建Vault蓝图
vault_bp = Blueprint('vault', __name__, url_prefix='/api/v1/vault')


def require_auth_vault(func):
    """Vault专用的认证装饰器"""
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


@vault_bp.route('/', methods=['GET'])
@require_auth_vault
def get_vault():
    """
    获取最新 vault
    返回：{vault, version, storage_used}
    """
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


@vault_bp.route('/', methods=['PUT'])
@require_auth_vault
def put_vault():
    """
    上传 vault（完整覆盖，乐观锁）
    请求：{vault, expected_version}
    返回：{version, storage_used} 或 409 冲突
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

    # 保存版本快照（最多保留最近 100 个）
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


@vault_bp.route('/versions', methods=['GET'])
@require_auth_vault
def get_vault_versions():
    """
    获取Vault版本历史
    查询参数：limit (默认10，最大100), offset (默认0)
    返回：{versions: [{version, created_at, vault_bytes, note, is_auto}]}
    """
    limit = min(int(request.args.get('limit', 10)), 100)
    offset = max(int(request.args.get('offset', 0)), 0)
    
    db = get_db()
    rows = db.execute(
        """SELECT version, created_at, vault_bytes, note, is_auto
           FROM vault_versions
           WHERE user_id = ?
           ORDER BY version DESC
           LIMIT ? OFFSET ?""",
        (g.user_id, limit, offset)
    ).fetchall()
    
    versions = []
    for row in rows:
        versions.append({
            "version": row["version"],
            "created_at": row["created_at"],
            "vault_bytes": row["vault_bytes"],
            "note": row["note"],
            "is_auto": bool(row["is_auto"])
        })
    
    return jsonify({"versions": versions})


@vault_bp.route('/restore/<int:version>', methods=['POST'])
@require_auth_vault
def restore_vault_version(version: int):
    """
    恢复指定版本的Vault
    返回：{success: true, version: new_version}
    """
    db = get_db()
    
    # 获取指定版本的vault数据
    row = db.execute(
        """SELECT vault_json, vault_bytes
           FROM vault_versions
           WHERE user_id = ? AND version = ?""",
        (g.user_id, version)
    ).fetchone()
    
    if not row:
        return jsonify({"error": f"Version {version} not found"}), 404
    
    vault_json = json.loads(row["vault_json"])
    vault_bytes = row["vault_bytes"]
    
    now = int(time.time() * 1000)
    
    # 获取当前版本
    current_row = db.execute(
        "SELECT vault_version FROM vaults WHERE user_id = ?", (g.user_id,)
    ).fetchone()
    current_version = current_row["vault_version"] if current_row else 0
    
    # 更新vault到指定版本
    db.execute(
        """UPDATE vaults
           SET vault_json = ?, updated_at = ?,
               vault_version = vault_version + 1,
               storage_bytes = ?
           WHERE user_id = ?""",
        (json.dumps(vault_json), now, vault_bytes, g.user_id)
    )
    
    new_version = current_version + 1
    
    # 创建手动恢复的快照
    db.execute(
        """INSERT INTO vault_versions
           (user_id, version, vault_json, vault_bytes, created_at, note, is_auto)
           VALUES (?, ?, ?, ?, ?, ?, 0)""",
        (g.user_id, new_version, json.dumps(vault_json), vault_bytes, now,
         f'Manual restore from version {version}')
    )
    
    # 更新用户存储使用量
    db.execute(
        "UPDATE users SET storage_used = ?, updated_at = ? WHERE id = ?",
        (vault_bytes, now, g.user_id)
    )
    
    write_audit(g.user_id, "VAULT_RESTORE",
        resource_type="vault",
        details={"from_version": version, "to_version": new_version})
    
    return jsonify({
        "success": True,
        "version": new_version,
        "restored_from": version
    })