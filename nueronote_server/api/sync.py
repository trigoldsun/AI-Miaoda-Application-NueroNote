#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 同步 API 模块
处理增量同步操作记录。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import List, Dict, Any

from flask import Blueprint, g, jsonify, request

from nueronote_server.database import get_db
from nueronote_server.utils.jwt import verify_token
from nueronote_server.utils.audit import write_audit

# 创建同步蓝图
sync_bp = Blueprint('sync', __name__, url_prefix='/api/v1/sync')


def require_auth_sync(func):
    """Sync专用的认证装饰器"""
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


@sync_bp.route('/push', methods=['POST'])
@require_auth_sync
def sync_push():
    """
    推送增量操作记录
    请求：{records: [{record_id, record_type, operation, encrypted_data}]}
    返回：{pushed: count, server_time: timestamp}
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


@sync_bp.route('/pull', methods=['GET'])
@require_auth_sync
def sync_pull():
    """
    拉取增量同步记录
    请求：?since=<timestamp>&limit=1000
    返回：{records: [...], server_time: timestamp, has_more: boolean}
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


@sync_bp.route('/status', methods=['GET'])
@require_auth_sync
def sync_status():
    """
    获取同步状态
    返回：{last_sync: timestamp, record_count: int, pending_changes: int}
    """
    db = get_db()
    
    # 获取最后同步时间
    vault_row = db.execute(
        "SELECT last_synced_at FROM vaults WHERE user_id = ?", (g.user_id,)
    ).fetchone()
    last_sync = vault_row["last_synced_at"] if vault_row else 0
    
    # 获取同步记录总数
    count_row = db.execute(
        "SELECT COUNT(*) as count FROM sync_log WHERE user_id = ?", (g.user_id,)
    ).fetchone()
    record_count = count_row["count"] if count_row else 0
    
    # 获取最近24小时内未同步的记录数
    since_time = int(time.time() * 1000) - 24 * 60 * 60 * 1000  # 24小时前
    pending_row = db.execute(
        """SELECT COUNT(*) as count FROM sync_log 
           WHERE user_id = ? AND created_at > ?""",
        (g.user_id, since_time)
    ).fetchone()
    pending_changes = pending_row["count"] if pending_row else 0
    
    return jsonify({
        "last_sync": last_sync,
        "record_count": record_count,
        "pending_changes": pending_changes,
        "server_time": int(time.time() * 1000)
    })