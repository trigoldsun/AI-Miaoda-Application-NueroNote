#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote MFA API
【更新日志 2026-04-14 v1.3】

修复:
- P0: MFA会话持久化 (Redis/数据库存储)
- P0: MFA尝试次数限制 (防暴力破解)
- P0: MFA过期会话自动清理

路由:
- POST /api/v1/mfa/setup       - 启用MFA
- POST /api/v1/mfa/send-code   - 发送验证码
- POST /api/v1/mfa/verify       - 验证MFA码
- POST /api/v1/mfa/disable      - 禁用MFA
- POST /api/v1/mfa/backup-code  - 使用备用码
- GET  /api/v1/mfa/status       - 获取MFA状态
"""

from flask import Blueprint, g, jsonify, request, current_app
from functools import wraps
import json
import time
import secrets
import logging

from nueronote_server.database import get_db
from nueronote_server.services.mfa import get_mfa_service
from nueronote_server.services.device import get_device_service
from nueronote_server.utils.jwt import verify_token, sign_token
from nueronote_server.utils.audit import write_audit, get_client_ip

mfa_bp = Blueprint('mfa', __name__, url_prefix='/api/v1/mfa')
logger = logging.getLogger(__name__)

# ============================================================================
# MFA会话存储 (v1.3 - 持久化存储)
# ============================================================================

class MFASessionStore:
    """
    MFA会话存储 - 支持Redis和数据库两种后端
    
    【安全修复 v1.3】
    - 使用数据库持久化存储，重启不丢失
    - 自动过期清理机制
    - 尝试次数限制
    """
    
    # 尝试次数限制
    MAX_VERIFY_ATTEMPTS = 5
    # 会话有效期（秒）
    SESSION_TTL = 300  # 5分钟
    # 冷却时间（秒）- 超过尝试次数后
    COOLDOWN_TTL = 300  # 5分钟
    
    def __init__(self):
        self._use_db = True
        self._init_store()
    
    def _init_store(self):
        """初始化存储后端"""
        try:
            from nueronote_server.cache import get_cache
            cache = get_cache()
            if cache:
                self._cache = cache
                self._use_db = False
                logger.info("MFA会话存储: Redis后端")
                return
        except Exception:
            pass
        
        logger.info("MFA会话存储: 数据库后端")
        self._use_db = True
        self._ensure_table()
    
    def _ensure_table(self):
        """确保MFA会话表存在"""
        db = get_db()
        db.execute("""
            CREATE TABLE IF NOT EXISTS mfa_sessions (
                session_token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                mfa_type TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                attempts INTEGER DEFAULT 0,
                locked_until INTEGER DEFAULT 0,
                created_at INTEGER NOT NULL
            )
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_mfa_user ON mfa_sessions(user_id)
        """)
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_mfa_expires ON mfa_sessions(expires_at)
        """)
        db.commit()
    
    def create(self, user_id: str, mfa_type: str) -> str:
        """
        创建MFA会话
        
        Returns:
            session_token
        """
        session_token = secrets.token_urlsafe(32)
        now = int(time.time())
        expires_at = now + self.SESSION_TTL
        
        if self._use_db:
            db = get_db()
            # 清理旧会话
            db.execute("DELETE FROM mfa_sessions WHERE user_id = ?", (user_id,))
            db.execute("""
                INSERT INTO mfa_sessions 
                (session_token, user_id, mfa_type, expires_at, attempts, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
            """, (session_token, user_id, mfa_type, expires_at, now))
            db.commit()
        else:
            # 清理旧会话
            self._cleanup_user_sessions(user_id)
            self._cache.set(f"mfa_session:{session_token}", 
                json.dumps({'user_id': user_id, 'mfa_type': mfa_type, 'attempts': 0}),
                ex=self.SESSION_TTL)
        
        return session_token
    
    def get(self, session_token: str) -> dict:
        """获取会话"""
        self._cleanup_expired()
        
        if self._use_db:
            db = get_db()
            row = db.execute("""
                SELECT * FROM mfa_sessions WHERE session_token = ?
            """, (session_token,)).fetchone()
            
            if not row:
                return None
            
            return {
                'user_id': row['user_id'],
                'mfa_type': row['mfa_type'],
                'expires_at': row['expires_at'],
                'attempts': row['attempts'],
                'locked_until': row['locked_until']
            }
        else:
            data = self._cache.get(f"mfa_session:{session_token}")
            if data:
                return json.loads(data)
            return None
    
    def delete(self, session_token: str):
        """删除会话"""
        if self._use_db:
            db = get_db()
            db.execute("DELETE FROM mfa_sessions WHERE session_token = ?", (session_token,))
            db.commit()
        else:
            self._cache.delete(f"mfa_session:{session_token}")
    
    def increment_attempts(self, session_token: str) -> int:
        """增加尝试次数，返回当前次数"""
        now = int(time.time())
        
        if self._use_db:
            db = get_db()
            db.execute("""
                UPDATE mfa_sessions 
                SET attempts = attempts + 1 
                WHERE session_token = ?
            """, (session_token,))
            db.commit()
            
            row = db.execute("""
                SELECT attempts, locked_until FROM mfa_sessions WHERE session_token = ?
            """, (session_token,)).fetchone()
            
            attempts = row['attempts'] if row else 0
            locked_until = row['locked_until'] if row else 0
            
            # 检查是否需要锁定
            if attempts >= self.MAX_VERIFY_ATTEMPTS and locked_until < now:
                db.execute("""
                    UPDATE mfa_sessions 
                    SET locked_until = ? 
                    WHERE session_token = ?
                """, (now + self.COOLDOWN_TTL, session_token))
                db.commit()
                logger.warning(f"MFA会话 {session_token[:8]}... 因多次失败被锁定{self.COOLDOWN_TTL}秒")
            
            return attempts
        else:
            key = f"mfa_session:{session_token}"
            data = self._cache.get(key)
            if data:
                session = json.loads(data)
                session['attempts'] = session.get('attempts', 0) + 1
                attempts = session['attempts']
                
                # 计算剩余TTL
                ttl = self._cache.client.ttl(key)
                if ttl < 0:
                    ttl = self.SESSION_TTL
                
                if attempts >= self.MAX_VERIFY_ATTEMPTS:
                    session['locked_until'] = now + self.COOLDOWN_TTL
                    # 锁定时缩短TTL
                    ttl = min(ttl, self.COOLDOWN_TTL)
                
                self._cache.set(key, json.dumps(session), ex=ttl)
                return attempts
            return 0
    
    def is_locked(self, session_token: str) -> tuple:
        """
        检查是否被锁定
        Returns:
            (is_locked: bool, reason: str)
        """
        now = int(time.time())
        
        if self._use_db:
            db = get_db()
            row = db.execute("""
                SELECT locked_until, expires_at FROM mfa_sessions WHERE session_token = ?
            """, (session_token,)).fetchone()
            
            if not row:
                return True, "会话不存在"
            
            if row['expires_at'] < now:
                return True, "会话已过期"
            
            if row['locked_until'] > now:
                remaining = row['locked_until'] - now
                return True, f"因多次验证失败，请{remaining}秒后重试"
            
            return False, ""
        else:
            key = f"mfa_session:{session_token}"
            data = self._cache.get(key)
            if not data:
                return True, "会话不存在"
            
            session = json.loads(data)
            expires_at = session.get('expires_at', 0)
            locked_until = session.get('locked_until', 0)
            
            if expires_at < now:
                return True, "会话已过期"
            
            if locked_until > now:
                remaining = locked_until - now
                return True, f"因多次验证失败，请{remaining}秒后重试"
            
            return False, ""
    
    def _cleanup_expired(self):
        """清理过期会话"""
        if self._use_db:
            try:
                db = get_db()
                now = int(time.time())
                db.execute("DELETE FROM mfa_sessions WHERE expires_at < ? OR locked_until < ?", (now, now))
                db.commit()
            except Exception as e:
                logger.error(f"清理MFA会话失败: {e}")
    
    def _cleanup_user_sessions(self, user_id: str):
        """清理用户的旧会话"""
        if not self._use_db:
            pattern = "mfa_session:*"
            try:
                keys = self._cache.client.keys(pattern)
                for key in keys:
                    data = self._cache.get(key)
                    if data:
                        session = json.loads(data)
                        if session.get('user_id') == user_id:
                            self._cache.delete(key)
            except Exception:
                pass


# 全局MFA会话存储实例
_mfa_session_store: MFASessionStore = None


def get_mfa_session_store() -> MFASessionStore:
    """获取MFA会话存储实例"""
    global _mfa_session_store
    if _mfa_session_store is None:
        _mfa_session_store = MFASessionStore()
    return _mfa_session_store


# 保持向后兼容的别名
def _get_mfa_sessions():
    """获取会话存储（兼容旧接口）"""
    return get_mfa_session_store()


def require_auth(func):
    """验证用户认证"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized'}), 401
        
        token = auth_header[7:]
        try:
            user_id = verify_token(token, current_app.config['JWT_SECRET'])
        except Exception:
            return jsonify({'error': 'Invalid token'}), 401
        
        if not user_id:
            return jsonify({'error': 'Invalid token'}), 401
        
        g.user_id = user_id
        return func(*args, **kwargs)
    return wrapper


def require_mfa_session(func):
    """验证MFA会话"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing session token'}), 401
        
        session_token = auth_header[7:]
        store = get_mfa_session_store()
        session = store.get(session_token)
        
        if not session:
            return jsonify({'error': 'Invalid or expired session'}), 401
        
        # 【v1.3】检查会话是否被锁定
        is_locked, reason = store.is_locked(session_token)
        if is_locked:
            return jsonify({'error': reason}), 429
        
        g.mfa_session = session
        g.mfa_token = session_token
        return func(*args, **kwargs)
    return wrapper


@mfa_bp.route('/status', methods=['GET'])
@require_auth
def get_mfa_status():
    """获取MFA状态"""
    user_id = g.user_id
    db = get_db()
    
    row = db.execute(
        "SELECT mfa_enabled, mfa_type FROM mfa_settings WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    
    if not row or not row['mfa_enabled']:
        return jsonify({'enabled': False})
    
    return jsonify({
        'enabled': True,
        'type': row['mfa_type']
    })


@mfa_bp.route('/setup', methods=['POST'])
@require_auth
def setup_mfa():
    """
    启用MFA
    
    请求: {type: 'email' | 'sms', phone_number?: string}
    返回: {success, backup_codes[], message}
    """
    body = request.get_json(force=True, silent=True) or {}
    mfa_type = body.get('type', 'email')
    
    if mfa_type not in ('email', 'sms'):
        return jsonify({'error': 'Invalid MFA type'}), 400
    
    user_id = g.user_id
    db = get_db()
    now = int(time.time() * 1000)
    
    # 获取用户邮箱
    user = db.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
    if not user or not user['email']:
        return jsonify({'error': 'No email associated'}), 400
    
    phone = None
    if mfa_type == 'sms':
        phone = body.get('phone_number')
        if not phone:
            return jsonify({'error': 'Phone number required'}), 400
    
    # 生成备用码
    mfa_service = get_mfa_service()
    codes_plain, codes_hash = mfa_service.generate_backup_codes()
    
    # 保存MFA设置
    db.execute("""
        INSERT OR REPLACE INTO mfa_settings 
        (user_id, mfa_enabled, mfa_type, phone_number, backup_codes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, 1, mfa_type, phone, json.dumps(codes_hash), now, now))
    db.commit()
    
    # 发送测试验证码
    if mfa_type == 'email':
        code = mfa_service.generate_code()
        _store_code(db, user_id, code, 'email')
        mfa_service.send_mfa_email(user['email'], code)
        contact = user['email']
    else:
        code = mfa_service.generate_code()
        _store_code(db, user_id, code, 'sms')
        mfa_service.send_sms(phone, code)
        contact = phone
    
    write_audit(user_id, 'MFA_ENABLED', details={'type': mfa_type})
    
    return jsonify({
        'success': True,
        'message': f'MFA已启用，验证码已发送到 {mfa_type}',
        'backup_codes': codes_plain,
        'warning': '请妥善保管备用码，每个只能用一次'
    })


@mfa_bp.route('/send-code', methods=['POST'])
@require_auth
def send_mfa_code():
    """
    发送MFA验证码（登录时调用）
    """
    user_id = g.user_id
    db = get_db()
    
    # 获取MFA设置
    settings = db.execute(
        "SELECT * FROM mfa_settings WHERE user_id = ? AND mfa_enabled = 1",
        (user_id,)
    ).fetchone()
    
    if not settings:
        return jsonify({'error': 'MFA not enabled'}), 400
    
    # 获取联系方式
    if settings['mfa_type'] == 'email':
        user = db.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
        contact = user['email'] if user else None
    else:
        contact = settings['phone_number']
    
    if not contact:
        return jsonify({'error': 'No contact info'}), 400
    
    # 生成并发送验证码
    mfa_service = get_mfa_service()
    code = mfa_service.generate_code()
    _store_code(db, user_id, code, settings['mfa_type'])
    
    if settings['mfa_type'] == 'email':
        mfa_service.send_mfa_email(contact, code)
    else:
        mfa_service.send_sms(contact, code)
    
    return jsonify({
        'success': True,
        'message': f'验证码已发送到{mfa_service.get_mfa_type_name(settings["mfa_type"])}',
        'expires_in': 300  # 5分钟
    })


@mfa_bp.route('/verify', methods=['POST'])
@require_mfa_session
def verify_mfa():
    """
    验证MFA码（登录流程）
    
    请求: {code: string, device_fingerprint?: string, device_info?: object}
    返回: {success, token, user_id, mfa_skipped}
    """
    body = request.get_json(force=True, silent=True) or {}
    code = body.get('code', '').strip()
    
    if len(code) != 6:
        return jsonify({'error': 'Invalid code format'}), 400
    
    session = g.mfa_session
    mfa_token = g.mfa_token
    user_id = session['user_id']
    db = get_db()
    
    # 验证验证码
    # 【v1.3】增加尝试次数
    store = get_mfa_session_store()
    attempts = store.increment_attempts(mfa_token)
    
    if attempts >= store.MAX_VERIFY_ATTEMPTS:
        is_locked, reason = store.is_locked(mfa_token)
        if is_locked:
            write_audit(user_id, 'MFA_VERIFY_FAILED', details={'reason': 'locked', 'attempts': attempts})
            return jsonify({'error': reason}), 429
    
    if not _verify_and_consume_code(db, user_id, code):
        write_audit(user_id, 'MFA_VERIFY_FAILED', details={'attempts': attempts})
        return jsonify({'error': 'Invalid or expired code'}), 401
    
    # 生成JWT
    token = sign_token(user_id, current_app.config['JWT_SECRET'])
    
    # 注册/更新设备（如果提供了指纹）
    device_fingerprint = body.get('device_fingerprint')
    if device_fingerprint:
        device_service = get_device_service()
        device_info = body.get('device_info', {})
        ip = get_client_ip()
        user_agent = request.headers.get('User-Agent', '')[:500]
        device_service.register_device(db, user_id, device_fingerprint, device_info, ip, user_agent)
    
    # 清理MFA会话
    store.delete(mfa_token)
    
    write_audit(user_id, 'MFA_VERIFY_SUCCESS', details={'mfa_type': session.get('mfa_type')})
    
    return jsonify({
        'success': True,
        'token': token,
        'user_id': user_id
    })


@mfa_bp.route('/disable', methods=['POST'])
@require_auth
def disable_mfa():
    """
    禁用MFA（需要验证密码）
    
    请求: {password: string, key_check: string, code: string}
    """
    body = request.get_json(force=True, silent=True) or {}
    password = body.get('password', '')
    key_check = body.get('key_check', '')
    code = body.get('code', '').strip()
    
    user_id = g.user_id
    db = get_db()
    
    # 验证密码
    user = db.execute(
        "SELECT salt, key_check FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    
    if not _verify_key_check(password, user['salt'], user['key_check']):
        write_audit(user_id, 'MFA_DISABLE_FAILED', details={'reason': 'invalid_password'})
        return jsonify({'error': 'Invalid password'}), 401
    
    # 验证MFA码
    if not _verify_and_consume_code(db, user_id, code):
        write_audit(user_id, 'MFA_DISABLE_FAILED', details={'reason': 'invalid_code'})
        return jsonify({'error': 'Invalid MFA code'}), 401
    
    # 禁用MFA
    db.execute("DELETE FROM mfa_settings WHERE user_id = ?", (user_id,))
    db.commit()
    
    # 撤销所有设备
    device_service = get_device_service()
    device_service.revoke_all_devices(db, user_id)
    
    write_audit(user_id, 'MFA_DISABLED')
    
    return jsonify({'success': True, 'message': 'MFA已禁用'})


@mfa_bp.route('/backup-code', methods=['POST'])
@require_mfa_session
def use_backup_code():
    """
    使用备用码登录
    
    请求: {backup_code: string}
    """
    body = request.get_json(force=True, silent=True) or {}
    backup_code = body.get('backup_code', '').strip().upper()
    
    if len(backup_code) != 8:
        return jsonify({'error': 'Invalid backup code format'}), 400
    
    session = g.mfa_session
    mfa_token = g.mfa_token
    user_id = session['user_id']
    db = get_db()
    
    # 获取备用码
    settings = db.execute(
        "SELECT backup_codes FROM mfa_settings WHERE user_id = ?", (user_id,)
    ).fetchone()
    
    if not settings or not settings['backup_codes']:
        return jsonify({'error': 'No backup codes'}), 400
    
    mfa_service = get_mfa_service()
    backup_codes = json.loads(settings['backup_codes'])
    
    # 验证备用码
    found_idx = None
    for i, hashed in enumerate(backup_codes):
        if mfa_service.hash_code(backup_code) == hashed:
            found_idx = i
            break
    
    if found_idx is None:
        write_audit(user_id, 'MFA_BACKUP_FAILED')
        return jsonify({'error': 'Invalid backup code'}), 401
    
    # 删除已使用的备用码
    del backup_codes[found_idx]
    db.execute(
        "UPDATE mfa_settings SET backup_codes = ? WHERE user_id = ?",
        (json.dumps(backup_codes), user_id)
    )
    db.commit()
    
    # 生成JWT
    token = sign_token(user_id, current_app.config['JWT_SECRET'])
    
    # 注册设备
    device_fingerprint = body.get('device_fingerprint')
    if device_fingerprint:
        device_service = get_device_service()
        device_info = body.get('device_info', {})
        ip = get_client_ip()
        user_agent = request.headers.get('User-Agent', '')[:500]
        device_service.register_device(db, user_id, device_fingerprint, device_info, ip, user_agent)
    
    # 清理MFA会话
    store = get_mfa_session_store()
    store.delete(mfa_token)
    
    write_audit(user_id, 'MFA_BACKUP_SUCCESS', details={'codes_remaining': len(backup_codes)})
    
    return jsonify({
        'success': True,
        'token': token,
        'user_id': user_id,
        'codes_remaining': len(backup_codes),
        'message': f'备用码验证成功，剩余 {len(backup_codes)} 个备用码'
    })


# ============================================================================
# 辅助函数
# ============================================================================

def _store_code(db, user_id: str, code: str, mfa_type: str):
    """存储验证码"""
    mfa_service = get_mfa_service()
    now = int(time.time())
    expires_at = now + 5 * 60  # 5分钟
    
    code_hash = mfa_service.hash_code(code)
    
    # 删除旧验证码
    db.execute("DELETE FROM mfa_codes WHERE user_id = ?", (user_id,))
    
    # 存储新验证码
    db.execute("""
        INSERT INTO mfa_codes 
        (id, user_id, code_hash, mfa_type, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (secrets.token_hex(16), user_id, code_hash, mfa_type, expires_at, now))
    db.commit()


def _verify_and_consume_code(db, user_id: str, code: str) -> bool:
    """验证并消费验证码"""
    mfa_service = get_mfa_service()
    now = int(time.time())
    
    row = db.execute("""
        SELECT * FROM mfa_codes 
        WHERE user_id = ? AND expires_at > ? AND used_at IS NULL
        ORDER BY created_at DESC LIMIT 1
    """, (user_id, now)).fetchone()
    
    if not row:
        return False
    
    # 验证
    if not mfa_service.verify_code(code, row['code_hash']):
        # 增加尝试次数
        db.execute(
            "UPDATE mfa_codes SET attempts = attempts + 1 WHERE id = ?",
            (row['id'],)
        )
        db.commit()
        return False
    
    # 标记为已使用
    db.execute(
        "UPDATE mfa_codes SET used_at = ? WHERE id = ?",
        (now, row['id'])
    )
    db.commit()
    
    return True


def _verify_key_check(password: str, salt: str, expected_check: str) -> bool:
    """验证密钥校验值"""
    import hmac
    import hashlib
    
    if not password or not salt or not expected_check:
        return False
    
    # 派生key_check
    sig = hmac.new(
        password.encode('utf-8'),
        f'NueroNote:v1:key-check:{salt}'.encode('utf-8'),
        hashlib.sha256
    ).digest()
    import base64
    derived = base64.b64encode(sig).decode('utf-8').rstrip('=')
    
    return hmac.compare_digest(derived, expected_check)
