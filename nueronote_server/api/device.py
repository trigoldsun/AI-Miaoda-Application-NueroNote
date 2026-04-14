#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 设备管理 API
【更新日志 2026-04-14 v1.2】

路由:
- GET  /api/v1/device/list     - 获取设备列表
- POST /api/v1/device/revoke  - 撤销设备
- POST /api/v1/device/revoke-all - 撤销所有设备
"""

from flask import Blueprint, g, jsonify, request
from functools import wraps
import time

from nueronote_server.database import get_db
from nueronote_server.services.device import get_device_service
from nueronote_server.utils.jwt import verify_token
from nueronote_server.utils.audit import write_audit, get_client_ip

device_bp = Blueprint('device', __name__, url_prefix='/api/v1/device')


def require_auth(func):
    """验证用户认证"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized'}), 401
        
        token = auth_header[7:]
        from flask import current_app
        try:
            user_id = verify_token(token, current_app.config['JWT_SECRET'])
        except Exception:
            return jsonify({'error': 'Invalid token'}), 401
        
        if not user_id:
            return jsonify({'error': 'Invalid token'}), 401
        
        g.user_id = user_id
        return func(*args, **kwargs)
    return wrapper


@device_bp.route('/list', methods=['GET'])
@require_auth
def list_devices():
    """
    获取用户的信任设备列表
    
    返回: {devices: [{id, device_name, browser, os, last_seen, expires_in_days, is_current}]}
    """
    user_id = g.user_id
    db = get_db()
    device_service = get_device_service()
    
    # 获取当前设备指纹
    current_fingerprint = request.headers.get('X-Device-Fingerprint', '')
    current_fp_hash = ''
    if current_fingerprint:
        current_fp_hash = device_service.hash_fingerprint(current_fingerprint)
    
    devices = device_service.get_user_devices(db, user_id)
    
    result = []
    now = int(time.time() * 1000)
    
    for d in devices:
        expires_days = max(0, (d.expires_at - now) // (24 * 60 * 60 * 1000))
        
        result.append({
            'id': d.id,
            'device_name': d.device_name or '未知设备',
            'browser': d.browser or '未知',
            'os': d.os or '未知',
            'device_type': d.device_type or 'desktop',
            'ip_address': d.ip_address or '',
            'last_seen': _format_ts(d.last_seen_at),
            'first_seen': _format_ts(d.first_seen_at),
            'expires_in_days': expires_days,
            'login_count': d.login_count,
            'is_current': d.fingerprint == current_fp_hash,
            'is_trusted': bool(d.is_trusted)
        })
    
    return jsonify({'devices': result})


@device_bp.route('/revoke', methods=['POST'])
@require_auth
def revoke_device():
    """
    撤销单个设备
    
    请求: {device_id: string}
    """
    body = request.get_json(force=True, silent=True) or {}
    device_id = body.get('device_id')
    
    if not device_id:
        return jsonify({'error': 'device_id required'}), 400
    
    user_id = g.user_id
    db = get_db()
    device_service = get_device_service()
    
    if device_service.revoke_device(db, user_id, device_id):
        write_audit(user_id, 'DEVICE_REVOKED', details={'device_id': device_id})
        return jsonify({'success': True, 'message': '设备已撤销'})
    
    return jsonify({'error': 'Device not found'}), 404


@device_bp.route('/revoke-all', methods=['POST'])
@require_auth
def revoke_all_devices():
    """
    撤销所有设备（退出所有设备登录）
    """
    user_id = g.user_id
    db = get_db()
    device_service = get_device_service()
    
    count = device_service.revoke_all_devices(db, user_id)
    write_audit(user_id, 'ALL_DEVICES_REVOKED', details={'count': count})
    
    return jsonify({
        'success': True,
        'message': f'已撤销 {count} 个设备',
        'revoked_count': count
    })


@device_bp.route('/current', methods=['POST'])
@require_auth
def register_current_device():
    """
    注册/信任当前设备（登录成功后自动调用）
    
    请求头: X-Device-Fingerprint
    请求体: {device_info: {name, browser, os, deviceType}}
    """
    fingerprint = request.headers.get('X-Device-Fingerprint', '')
    
    if not fingerprint:
        return jsonify({'error': 'Missing device fingerprint'}), 400
    
    body = request.get_json(force=True, silent=True) or {}
    device_info = body.get('device_info', {})
    ip = get_client_ip()
    user_agent = request.headers.get('User-Agent', '')[:500]
    
    user_id = g.user_id
    db = get_db()
    device_service = get_device_service()
    
    device = device_service.register_device(
        db, user_id, fingerprint, device_info, ip, user_agent
    )
    
    write_audit(user_id, 'DEVICE_REGISTERED', details={
        'device_id': device.id,
        'browser': device.browser,
        'os': device.os
    })
    
    return jsonify({
        'success': True,
        'device_id': device.id,
        'expires_in_days': 30,
        'message': '设备已信任，30天内免MFA'
    })


def _format_ts(ts: int) -> str:
    """格式化时间戳"""
    from datetime import datetime
    if not ts:
        return ''
    dt = datetime.fromtimestamp(ts / 1000)
    return dt.strftime('%Y-%m-%d %H:%M')
