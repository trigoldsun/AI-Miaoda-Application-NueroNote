#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 云存储 API 模块
处理云存储配置、同步和备份。
"""

from __future__ import annotations

import json
import time
from typing import List, Dict, Any, Optional, Tuple

from flask import Blueprint, g, jsonify, request

from nueronote_server.database import get_db
from nueronote_server.utils.jwt import verify_token
from nueronote_server.utils.audit import write_audit

# 创建云存储蓝图
cloud_bp = Blueprint('cloud', __name__, url_prefix='/api/v1/cloud')


def require_auth_cloud(func):
    """Cloud专用的认证装饰器"""
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


@cloud_bp.route('/providers', methods=['GET'])
def cloud_providers():
    """
    返回支持的云服务商列表（无需认证）
    返回：{providers: [...]}
    """
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


@cloud_bp.route('/status', methods=['GET'])
@require_auth_cloud
def cloud_status():
    """
    查询云存储连接状态
    返回：{configured: [...], active: {...} or null}
    """
    db = get_db()
    row = db.execute("SELECT cloud_config FROM users WHERE id = ?", (g.user_id,)).fetchone()
    if not row or not row["cloud_config"]:
        return jsonify({"configured": [], "active": None})
    
    configs = json.loads(row["cloud_config"])
    configured = []
    active = None
    
    for cfg_dict in configs:
        configured.append({
            "provider": cfg_dict.get("provider", "unknown"),
            "enabled": cfg_dict.get("enabled", False),
            "configured_at": cfg_dict.get("configured_at", 0)
        })
        if cfg_dict.get("enabled", False):
            active = cfg_dict.get("provider", "unknown")
    
    return jsonify({
        "configured": configured,
        "active": active
    })


@cloud_bp.route('/configure', methods=['POST'])
@require_auth_cloud
def cloud_configure():
    """
    配置云存储
    请求：{provider: "tencent_cos"|"aliyun_oss"|"baidu_netdisk", config: {...}}
    返回：{success: true, message: "配置已保存"}
    """
    body = request.get_json(force=True, silent=True) or {}
    provider = body.get("provider")
    config = body.get("config", {})
    
    if not provider or not config:
        return jsonify({"error": "Missing provider or config"}), 400
    
    # 验证provider是否支持
    supported_providers = ["tencent_cos", "aliyun_oss", "baidu_netdisk"]
    if provider not in supported_providers:
        return jsonify({"error": f"Unsupported provider. Supported: {supported_providers}"}), 400
    
    db = get_db()
    row = db.execute("SELECT cloud_config FROM users WHERE id = ?", (g.user_id,)).fetchone()
    
    configs = []
    if row and row["cloud_config"]:
        configs = json.loads(row["cloud_config"])
    
    # 更新或添加配置
    updated = False
    for i, cfg in enumerate(configs):
        if cfg.get("provider") == provider:
            configs[i] = {
                "provider": provider,
                **config,
                "enabled": cfg.get("enabled", False),
                "configured_at": int(time.time() * 1000),
                "updated_at": int(time.time() * 1000)
            }
            updated = True
            break
    
    if not updated:
        configs.append({
            "provider": provider,
            **config,
            "enabled": False,
            "configured_at": int(time.time() * 1000),
            "updated_at": int(time.time() * 1000)
        })
    
    db.execute(
        "UPDATE users SET cloud_config = ? WHERE id = ?",
        (json.dumps(configs), g.user_id)
    )
    
    write_audit(g.user_id, "CLOUD_CONFIGURE", 
                resource_type="cloud",
                details={"provider": provider, "action": "configure"})
    
    return jsonify({
        "success": True,
        "message": f"{provider}配置已保存",
        "provider": provider
    })


@cloud_bp.route('/sync', methods=['POST'])
@require_auth_cloud
def cloud_sync():
    """
    手动触发云同步
    请求：{direction: "upload"|"download"|"both"}
    返回：{success: true, task_id: "...", message: "同步任务已创建"}
    """
    body = request.get_json(force=True, silent=True) or {}
    direction = body.get("direction", "both")
    
    if direction not in ["upload", "download", "both"]:
        return jsonify({"error": "Invalid direction. Use 'upload', 'download', or 'both'"}), 400
    
    # 这里应该创建异步任务
    task_id = f"sync_{int(time.time())}_{hash(g.user_id) % 10000:04d}"
    
    write_audit(g.user_id, "CLOUD_SYNC",
                resource_type="cloud",
                details={"direction": direction, "task_id": task_id})
    
    return jsonify({
        "success": True,
        "task_id": task_id,
        "message": f"云同步任务已创建（{direction}）",
        "direction": direction
    })


@cloud_bp.route('/test', methods=['POST'])
@require_auth_cloud
def cloud_test():
    """
    测试云存储连接
    请求：{provider: "...", config: {...}}
    返回：{success: true|false, message: "...", latency_ms: 123}
    """
    body = request.get_json(force=True, silent=True) or {}
    provider = body.get("provider")
    config = body.get("config", {})
    
    if not provider:
        # 使用已保存的配置
        db = get_db()
        row = db.execute("SELECT cloud_config FROM users WHERE id = ?", (g.user_id,)).fetchone()
        if not row or not row["cloud_config"]:
            return jsonify({"error": "No cloud configuration found"}), 400
        
        configs = json.loads(row["cloud_config"])
        active_config = None
        for cfg in configs:
            if cfg.get("enabled", False):
                active_config = cfg
                break
        
        if not active_config:
            return jsonify({"error": "No active cloud configuration"}), 400
        
        provider = active_config.get("provider")
        config = active_config
    
    # 模拟连接测试（实际实现应调用对应的云存储适配器）
    start_time = time.time()
    
    # 这里应该实际测试连接
    # 暂时返回成功
    success = True
    latency_ms = int((time.time() - start_time) * 1000)
    
    if success:
        message = f"连接到{provider}成功，延迟{latency_ms}ms"
    else:
        message = f"连接到{provider}失败，请检查配置"
    
    return jsonify({
        "success": success,
        "message": message,
        "provider": provider,
        "latency_ms": latency_ms
    })