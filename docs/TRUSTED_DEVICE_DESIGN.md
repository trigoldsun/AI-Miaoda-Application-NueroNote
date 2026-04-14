# NueroNote 信任设备 / Browser Cookie 功能设计

**版本**: v1.2
**更新日期**: 2026-04-14
**功能**: 30天内已验证浏览器免MFA

---

## 一、功能概述

### 1.1 核心概念

```
信任设备 (Trusted Device)
├── 定义：用户已验证通过的浏览器
├── 有效期：30天
├── 用途：30天内再次登录，跳过MFA
└── 可管理：用户可查看/撤销信任设备
```

### 1.2 登录流程（新版）

```
输入邮箱/密码 + key_check
        ↓
    密码验证通过
        ↓
    ┌─────┴─────┐
    │ 启用MFA?  │
    └─────┬─────┘
       是 │ 否
        ↓   ↓
  ┌──────┴──────┐
  │ 信任设备?   │  ← 新增判断
  └──────┬──────┘
    是  │  否
    ↓   ↓
跳过MFA  需要MFA验证
  ↓
  → JWT Token
```

---

## 二、数据库设计

### 2.1 新增表

```sql
-- 信任设备表
CREATE TABLE IF NOT EXISTS trusted_devices (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- 设备指纹信息
    fingerprint     TEXT NOT NULL,           -- 浏览器指纹Hash
    device_name     TEXT,                     -- 设备名称（如"Chrome on Windows"）
    browser         TEXT,                     -- 浏览器名称
    os              TEXT,                     -- 操作系统
    device_type     TEXT,                     -- 'desktop', 'mobile', 'tablet'
    
    -- 设备元数据
    ip_address     TEXT,                     -- 注册时的IP地址
    user_agent      TEXT,                     -- 完整的User-Agent
    
    -- 信任状态
    is_trusted      BOOLEAN DEFAULT TRUE,    -- 是否信任
    first_seen_at   INTEGER NOT NULL,        -- 首次出现时间
    last_seen_at    INTEGER NOT NULL,        -- 最后使用时间
    login_count     INTEGER DEFAULT 1,       -- 登录次数
    
    -- 过期时间
    expires_at      INTEGER NOT NULL,        -- 过期时间戳（首次登录+30天）
    
    UNIQUE(user_id, fingerprint)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_trusted_device_user ON trusted_devices(user_id);
CREATE INDEX IF NOT EXISTS idx_trusted_device_fingerprint ON trusted_devices(fingerprint);
CREATE INDEX IF NOT EXISTS idx_trusted_device_expires ON trusted_devices(expires_at);
```

### 2.2 Users表扩展

```sql
-- 可选：是否启用"信任设备免MFA"功能
ALTER TABLE users ADD COLUMN trust_devices BOOLEAN DEFAULT TRUE;
```

---

## 三、浏览器指纹生成

### 3.1 前端指纹生成

```javascript
// 生成浏览器唯一指纹
async function generateDeviceFingerprint() {
  const components = [];
  
  // 1. Canvas指纹
  try {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    ctx.textBaseline = 'top';
    ctx.font = "14px 'Arial'";
    ctx.fillStyle = '#f60';
    ctx.fillRect(125, 1, 62, 20);
    ctx.fillStyle = '#069';
    ctx.fillText('NueroNote fingerprint', 2, 15);
    ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
    ctx.fillText('NueroNote fingerprint', 4, 17);
    components.push(canvas.toDataURL().slice(-50));
  } catch (e) {
    components.push('canvas-error');
  }
  
  // 2. WebGL指纹
  try {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
    if (gl) {
      const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
      if (debugInfo) {
        components.push(gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL));
        components.push(gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL));
      }
    }
  } catch (e) {
    components.push('webgl-error');
  }
  
  // 3. 屏幕信息
  components.push(`${screen.width}x${screen.height}x${screen.colorDepth}`);
  components.push(navigator.hardwareConcurrency || 'unknown');  // CPU核心数
  
  // 4. 时区
  components.push(Intl.DateTimeFormat().resolvedOptions().timeZone);
  
  // 5. 语言
  components.push(navigator.language);
  components.push(navigator.languages ? navigator.languages.join(',') : '');
  
  // 6. 平台
  components.push(navigator.platform);
  
  // 7. 是否支持Touch
  components.push(navigator.maxTouchPoints > 0 ? 'touch' : 'no-touch');
  
  // 8. 浏览器插件（简化的navigator.plugins）
  if (navigator.plugins) {
    components.push(navigator.plugins.length);
  }
  
  // 9. Cookie启用
  components.push(navigator.cookieEnabled ? 'cookie' : 'no-cookie');
  
  // 10. Do Not Track
  components.push(navigator.doNotTrack || 'unknown');
  
  // 组合并生成Hash
  const raw = components.join('|');
  const hash = await sha256(raw);
  
  return {
    fingerprint: hash,
    deviceInfo: {
      browser: getBrowserName(),
      os: getOSName(),
      deviceType: getDeviceType(),
      screen: `${screen.width}x${screen.height}`
    }
  };
}

// 简化的浏览器检测
function getBrowserName() {
  const ua = navigator.userAgent;
  if (ua.indexOf('Firefox') > -1) return 'Firefox';
  if (ua.indexOf('Chrome') > -1 && ua.indexOf('Edg') === -1) return 'Chrome';
  if (ua.indexOf('Safari') > -1 && ua.indexOf('Chrome') === -1) return 'Safari';
  if (ua.indexOf('Edg') > -1) return 'Edge';
  if (ua.indexOf('Opera') > -1 || ua.indexOf('OPR') > -1) return 'Opera';
  return 'Unknown';
}

// 简化的操作系统检测
function getOSName() {
  const ua = navigator.userAgent;
  if (ua.indexOf('Win') > -1) return 'Windows';
  if (ua.indexOf('Mac') > -1) return 'macOS';
  if (ua.indexOf('Linux') > -1) return 'Linux';
  if (ua.indexOf('Android') > -1) return 'Android';
  if (ua.indexOf('iOS') > -1 || ua.indexOf('iPhone') > -1 || ua.indexOf('iPad') > -1) return 'iOS';
  return 'Unknown';
}

// 设备类型检测
function getDeviceType() {
  if (/Mobi|Android|iPhone|iPad|Tablet/i.test(navigator.userAgent)) {
    return navigator.maxTouchPoints > 1 ? 'tablet' : 'mobile';
  }
  return 'desktop';
}

// SHA256 Hash
async function sha256(str) {
  const encoder = new TextEncoder();
  const data = encoder.encode(str);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}
```

---

## 四、后端实现

### 4.1 设备管理服务

```python
# nueronote_server/services/device.py

import hashlib
import secrets
import time
from typing import Optional, List, Dict
from dataclasses import dataclass


@dataclass
class TrustedDevice:
    """信任设备"""
    id: str
    user_id: str
    fingerprint: str
    device_name: str
    browser: str
    os: str
    device_type: str
    ip_address: str
    first_seen_at: int
    last_seen_at: int
    expires_at: int
    login_count: int
    is_trusted: bool


class DeviceService:
    """设备信任服务"""
    
    TRUST_DAYS = 30  # 信任有效期
    TRUST_SECONDS = TRUST_DAYS * 24 * 60 * 60
    
    def __init__(self):
        self.cache = None  # 可选Redis缓存
    
    def generate_device_id(self) -> str:
        """生成设备ID"""
        return secrets.token_hex(16)
    
    def hash_fingerprint(self, fingerprint: str) -> str:
        """哈希指纹（保护隐私）"""
        return hashlib.sha256(fingerprint.encode()).hexdigest()[:32]
    
    def check_trusted_device(
        self, 
        db, 
        user_id: str, 
        fingerprint: str
    ) -> Optional[TrustedDevice]:
        """
        检查设备是否受信任
        
        Returns:
            TrustedDevice if trusted and not expired, None otherwise
        """
        fp_hash = self.hash_fingerprint(fingerprint)
        now = int(time.time() * 1000)
        
        row = db.execute("""
            SELECT * FROM trusted_devices 
            WHERE user_id = ? AND fingerprint = ? AND is_trusted = 1
        """, (user_id, fp_hash)).fetchone()
        
        if not row:
            return None
        
        # 检查是否过期
        if row['expires_at'] < now:
            # 标记为不信任
            db.execute(
                "UPDATE trusted_devices SET is_trusted = 0 WHERE id = ?",
                (row['id'],)
            )
            return None
        
        return TrustedDevice(**dict(row))
    
    def register_device(
        self,
        db,
        user_id: str,
        fingerprint: str,
        device_info: dict,
        ip_address: str,
        user_agent: str
    ) -> TrustedDevice:
        """
        注册/更新信任设备
        
        如果设备已存在，更新last_seen_at和login_count
        如果是新设备，创建新记录
        """
        fp_hash = self.hash_fingerprint(fingerprint)
        now = int(time.time() * 1000)
        expires_at = now + self.TRUST_SECONDS * 1000
        
        # 检查是否已存在
        existing = db.execute("""
            SELECT id FROM trusted_devices 
            WHERE user_id = ? AND fingerprint = ?
        """, (user_id, fp_hash)).fetchone()
        
        if existing:
            # 更新现有设备
            device_id = existing['id']
            db.execute("""
                UPDATE trusted_devices 
                SET last_seen_at = ?, 
                    login_count = login_count + 1,
                    ip_address = ?,
                    expires_at = ?
                WHERE id = ?
            """, (now, ip_address, expires_at, device_id))
        else:
            # 创建新设备
            device_id = self.generate_device_id()
            db.execute("""
                INSERT INTO trusted_devices 
                (id, user_id, fingerprint, device_name, browser, os, device_type,
                 ip_address, user_agent, first_seen_at, last_seen_at, expires_at, 
                 login_count, is_trusted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                device_id, user_id, fp_hash,
                device_info.get('name', 'Unknown Device'),
                device_info.get('browser', 'Unknown'),
                device_info.get('os', 'Unknown'),
                device_info.get('deviceType', 'desktop'),
                ip_address, user_agent,
                now, now, expires_at,
                1
            ))
        
        # 返回设备信息
        row = db.execute(
            "SELECT * FROM trusted_devices WHERE id = ?", (device_id,)
        ).fetchone()
        
        return TrustedDevice(**dict(row))
    
    def revoke_device(self, db, user_id: str, device_id: str) -> bool:
        """撤销信任设备"""
        result = db.execute("""
            UPDATE trusted_devices 
            SET is_trusted = 0
            WHERE id = ? AND user_id = ?
        """, (device_id, user_id))
        
        return result.rowcount > 0
    
    def revoke_all_devices(self, db, user_id: str) -> int:
        """撤销所有信任设备"""
        result = db.execute("""
            UPDATE trusted_devices 
            SET is_trusted = 0
            WHERE user_id = ? AND is_trusted = 1
        """, (user_id,))
        
        return result.rowcount
    
    def get_user_devices(self, db, user_id: str) -> List[TrustedDevice]:
        """获取用户的所有设备"""
        rows = db.execute("""
            SELECT * FROM trusted_devices 
            WHERE user_id = ?
            ORDER BY last_seen_at DESC
        """, (user_id,)).fetchall()
        
        return [TrustedDevice(**dict(row)) for row in rows]
    
    def cleanup_expired(self, db) -> int:
        """清理过期设备（可定时任务）"""
        now = int(time.time() * 1000)
        result = db.execute("""
            DELETE FROM trusted_devices 
            WHERE expires_at < ?
        """, (now,))
        
        return result.rowcount
```

### 4.2 设备管理API

```python
# nueronote_server/api/device.py

from flask import Blueprint, g, jsonify, request
from functools import wraps

from nueronote_server.database import get_db
from nueronote_server.services.device import DeviceService
from nueronote_server.utils.jwt import verify_token
from nueronote_server.utils.audit import write_audit

device_bp = Blueprint('device', __name__, url_prefix='/api/v1/device')
device_service = DeviceService()


def require_auth_device(func):
    """验证用户认证"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Unauthorized'}), 401
        
        token = auth_header[7:]
        from flask import current_app
        user_id = verify_token(token, current_app.config['JWT_SECRET'])
        
        if not user_id:
            return jsonify({'error': 'Invalid token'}), 401
        
        g.user_id = user_id
        return func(*args, **kwargs)
    return wrapper


@device_bp.route('/list', methods=['GET'])
@require_auth_device
def list_devices():
    """
    获取用户的信任设备列表
    
    返回：{devices: [{id, device_name, browser, os, last_seen, expires_at, is_current}]}
    """
    user_id = g.user_id
    db = get_db()
    
    # 获取当前设备的fingerprint（从请求头）
    current_fingerprint = request.headers.get('X-Device-Fingerprint', '')
    current_fp_hash = device_service.hash_fingerprint(current_fingerprint) if current_fingerprint else ''
    
    devices = device_service.get_user_devices(db, user_id)
    
    result = []
    now = int(time.time() * 1000)
    
    for d in devices:
        result.append({
            'id': d.id,
            'device_name': d.device_name,
            'browser': d.browser,
            'os': d.os,
            'device_type': d.device_type,
            'last_seen': _format_timestamp(d.last_seen_at),
            'first_seen': _format_timestamp(d.first_seen_at),
            'expires_in_days': max(0, (d.expires_at - now) // (24*60*60*1000)),
            'login_count': d.login_count,
            'is_current': d.fingerprint == current_fp_hash,
            'is_trusted': d.is_trusted
        })
    
    return jsonify({'devices': result})


@device_bp.route('/revoke', methods=['POST'])
@require_auth_device
def revoke_device():
    """
    撤销单个设备
    
    请求：{device_id: string}
    """
    body = request.get_json(force=True, silent=True) or {}
    device_id = body.get('device_id')
    
    if not device_id:
        return jsonify({'error': 'device_id required'}), 400
    
    user_id = g.user_id
    db = get_db()
    
    if device_service.revoke_device(db, user_id, device_id):
        write_audit(user_id, 'DEVICE_REVOKED', details={'device_id': device_id})
        return jsonify({'success': True})
    
    return jsonify({'error': 'Device not found'}), 404


@device_bp.route('/revoke-all', methods=['POST'])
@require_auth_device
def revoke_all_devices():
    """
    撤销所有设备（退出所有设备）
    """
    user_id = g.user_id
    db = get_db()
    
    count = device_service.revoke_all_devices(db, user_id)
    write_audit(user_id, 'ALL_DEVICES_REVOKED', details={'count': count})
    
    return jsonify({
        'success': True,
        'revoked_count': count
    })


@device_bp.route('/current', methods=['POST'])
@require_auth_device
def register_current_device():
    """
    注册/信任当前设备（登录时自动调用）
    
    请求头：X-Device-Fingerprint
    请求体：{device_info: {name, browser, os, deviceType}}
    """
    fingerprint = request.headers.get('X-Device-Fingerprint', '')
    
    if not fingerprint:
        return jsonify({'error': 'Missing device fingerprint'}), 400
    
    body = request.get_json(force=True, silent=True) or {}
    device_info = body.get('device_info', {})
    ip_address = _get_client_ip()
    user_agent = request.headers.get('User-Agent', '')
    
    user_id = g.user_id
    db = get_db()
    
    device = device_service.register_device(
        db, user_id, fingerprint, device_info, ip_address, user_agent
    )
    
    write_audit(user_id, 'DEVICE_REGISTERED', details={
        'device_id': device.id,
        'browser': device.browser,
        'os': device.os
    })
    
    return jsonify({
        'success': True,
        'device_id': device.id,
        'expires_in_days': 30
    })


def _format_timestamp(ts: int) -> str:
    """格式化时间戳"""
    from datetime import datetime
    dt = datetime.fromtimestamp(ts / 1000)
    return dt.strftime('%Y-%m-%d %H:%M')


def _get_client_ip() -> str:
    """获取客户端IP"""
    from flask import request
    return request.headers.get('X-Forwarded-For', 
           request.headers.get('X-Real-IP', 
           request.remote_addr or '')).split(',')[0].strip()
```

---

## 五、登录流程变更

### 5.1 修改后的登录API

```python
@auth_bp.route('/login', methods=['POST'])
def login():
    """
    登录（含MFA + 信任设备）
    
    请求：{
        email, 
        password, 
        key_check,
        device_fingerprint?,      # 浏览器指纹
        device_info?: {name, browser, os, deviceType}
    }
    """
    body = request.get_json(force=True, silent=True) or {}
    email = body.get('email', '').strip().lower()
    password = body.get('password', '')
    key_check = body.get('key_check', '')
    device_fingerprint = body.get('device_fingerprint')
    device_info = body.get('device_info', {})
    ip = get_client_ip()
    
    # 1. 基础验证
    if not email:
        return jsonify({'error': 'Email required'}), 400
    
    if not password or not key_check:
        return jsonify({'error': 'Credentials required'}), 400
    
    db = get_db()
    
    # 2. 获取用户
    user = db.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()
    
    if not user:
        return jsonify({'error': 'Invalid credentials'}), 401
    
    # 3. 检查账户锁定
    if _check_account_lock(db, user['id']):
        return jsonify({'error': 'Account locked'}), 423
    
    # 4. 验证密码
    if not _verify_key_check(password, user['salt'], user['key_check']):
        _increment_login_fails(db, user['id'])
        write_audit(user['id'], 'LOGIN_FAILED', details={'ip': ip, 'reason': 'invalid_password'})
        return jsonify({'error': 'Invalid credentials'}), 401
    
    # 5. 重置登录失败
    _reset_login_fails(db, user['id'])
    
    # 6. 检查是否启用MFA
    mfa_settings = db.execute(
        "SELECT mfa_enabled FROM mfa_settings WHERE user_id = ? AND mfa_enabled = 1",
        (user['id'],)
    ).fetchone()
    
    needs_mfa = mfa_settings is not None
    
    # 7. 如果需要MFA，检查是否是信任设备
    skip_mfa = False
    device_id = None
    
    if needs_mfa and device_fingerprint:
        trusted = device_service.check_trusted_device(
            db, user['id'], device_fingerprint
        )
        if trusted:
            skip_mfa = True
            device_id = trusted.id
    
    # 8. 处理登录结果
    if needs_mfa and not skip_mfa:
        # 需要MFA验证
        return _create_mfa_session(user, ip, device_info)
    
    # 9. 直接登录成功
    token = sign_token(user['id'], current_app.config['JWT_SECRET'])
    
    # 10. 如果有设备指纹，注册/更新设备
    if device_fingerprint:
        device_service.register_device(
            db, user['id'], device_fingerprint, device_info, ip,
            request.headers.get('User-Agent', '')
        )
    
    # 11. 更新最后登录
    db.execute(
        "UPDATE users SET last_login = ?, last_ip = ? WHERE id = ?",
        (int(time.time()), ip, user['id'])
    )
    
    write_audit(user['id'], 'LOGIN_SUCCESS', details={
        'ip': ip,
        'mfa_skipped': skip_mfa,
        'device_id': device_id
    })
    
    return jsonify({
        'success': True,
        'token': token,
        'user_id': user['id'],
        'mfa_skipped': skip_mfa,  # 告诉前端是否跳过了MFA
        'device_id': device_id
    })
```

### 5.2 MFA会话扩展

```python
# MFA会话中添加设备信息
MFA_SESSIONS[mfa_token] = {
    'user_id': user_id,
    'mfa_type': mfa_type,
    'expires_at': expires_at,
    'device_fingerprint': device_fingerprint,  # 新增
    'device_info': device_info               # 新增
}

# MFA验证成功后，注册设备
@auth_bp.route('/mfa-verify', methods=['POST'])
def mfa_verify():
    # ... 验证逻辑 ...
    
    if session.get('device_fingerprint'):
        # 注册设备
        device_service.register_device(
            db, user_id, 
            session['device_fingerprint'],
            session.get('device_info', {}),
            ip,
            request.headers.get('User-Agent', '')
        )
```

---

## 六、前端实现

### 6.1 自动发送设备指纹

```javascript
// 在登录请求时自动附加设备指纹
async function doLogin() {
  var email = $('#auth-email').value.trim();
  var password = $('#auth-password').value;
  if (!email || !password) { toast('请填写邮箱和密码'); return; }
  
  renderLoading('正在登录...');
  
  try {
    // 获取设备指纹
    const fp = await generateDeviceFingerprint();
    
    // 生成key_check
    var salt = localStorage.getItem('flux_salt');
    if (!salt) {
      salt = 'c2FsdDEyYnl0ZXMh';
    }
    var keyCheck = generateKeyCheck(password, salt);
    
    var resp = await fetch(API + '/auth/login', {
      method:'POST',
      headers:{
        'Content-Type':'application/json',
        'X-Device-Fingerprint': fp.fingerprint  // 添加指纹
      },
      body: JSON.stringify({
        email: email, 
        password: password, 
        key_check: keyCheck,
        device_fingerprint: fp.fingerprint,
        device_info: fp.deviceInfo
      })
    });
    
    var data = await resp.json();
    
    if (!resp.ok) {
      renderAuth();
      toast(data.error || '登录失败');
      return;
    }
    
    // 处理MFA
    if (data.mfa_required && !data.mfa_skipped) {
      renderAuth();
      showMFADialog(data.mfa_token, data.mfa_type);
      return;
    }
    
    // 登录成功
    token = data.token;
    userId = data.user_id;
    passwordCache = password;
    localStorage.setItem('flux_token', token);
    localStorage.setItem('flux_uid', userId);
    localStorage.setItem('flux_salt', salt);
    localStorage.setItem('flux_device_id', data.device_id);  // 保存设备ID
    
    // 显示是否跳过MFA
    if (data.mfa_skipped) {
      toast('登录成功 (已信任设备)');
    }
    
    // 加载Vault
    await loadVault();
    showApp();
    
  } catch(err) {
    renderAuth();
    toast('网络错误');
  }
}
```

### 6.2 设备管理页面

```javascript
// 信任设备管理
async function showDeviceManagement() {
  const resp = await fetch(API + '/device/list', {
    headers: {'Authorization': 'Bearer ' + token}
  });
  
  if (!resp.ok) {
    toast('获取设备列表失败');
    return;
  }
  
  const data = await resp.json();
  
  const modal = document.createElement('div');
  modal.className = 'modal';
  modal.innerHTML = `
    <div class="modal-content" style="max-width: 500px;">
      <h2>信任设备管理</h2>
      <p style="color: #666; font-size: 0.9em;">
        30天内已验证的设备再次登录时无需MFA验证码
      </p>
      
      <div class="device-list">
        ${data.devices.map(d => `
          <div class="device-item ${d.is_current ? 'current' : ''}">
            <div class="device-icon">
              ${d.device_type === 'mobile' ? '📱' : d.device_type === 'tablet' ? '📲' : '💻'}
            </div>
            <div class="device-info">
              <div class="device-name">
                ${d.device_name || 'Unknown Device'}
                ${d.is_current ? '<span class="badge">当前</span>' : ''}
              </div>
              <div class="device-meta">
                ${d.browser} · ${d.os}
              </div>
              <div class="device-meta">
                上次使用: ${d.last_seen} · 剩余 ${d.expires_in_days} 天
              </div>
            </div>
            ${!d.is_current ? `
              <button class="btn-revoke" onclick="revokeDevice('${d.id}')">
                撤销
              </button>
            ` : ''}
          </div>
        `).join('')}
      </div>
      
      <div style="margin-top: 1em; display: flex; gap: 0.5em;">
        <button onclick="revokeAllDevices()" style="flex: 1;">
          退出所有设备
        </button>
        <button onclick="closeModal()" style="flex: 1;">
          关闭
        </button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
}

async function revokeDevice(deviceId) {
  if (!confirm('确定要撤销此设备的信任状态吗？')) return;
  
  try {
    const resp = await fetch(API + '/device/revoke', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token
      },
      body: JSON.stringify({device_id: deviceId})
    });
    
    if (resp.ok) {
      toast('设备已撤销');
      showDeviceManagement();  // 刷新列表
    } else {
      toast('撤销失败');
    }
  } catch (e) {
    toast('网络错误');
  }
}

async function revokeAllDevices() {
  if (!confirm('确定要撤销所有设备的信任状态吗？\n您需要重新验证每个设备。')) return;
  
  try {
    const resp = await fetch(API + '/device/revoke-all', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token
      }
    });
    
    if (resp.ok) {
      const data = await resp.json();
      toast(`已撤销 ${data.revoked_count} 个设备`);
      showDeviceManagement();  // 刷新列表
    } else {
      toast('撤销失败');
    }
  } catch (e) {
    toast('网络错误');
  }
}
```

---

## 七、安全考虑

### 7.1 指纹隐私
- ✅ 服务端只存储指纹的Hash，不存储原始指纹
- ✅ 无法从Hash反向还原设备信息

### 7.2 设备伪造防护
- ⚠️ 指纹可被高端用户伪造（但这需要有意图）
- ⚠️ 可结合IP、User-Agent等辅助判断
- ✅ 建议：敏感操作仍需MFA

### 7.3 过期清理
- 建议添加定时任务清理过期设备
- 过期设备自动失效

---

## 八、API汇总

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/device/list` | GET | 获取信任设备列表 |
| `/api/v1/device/revoke` | POST | 撤销单个设备 |
| `/api/v1/device/revoke-all` | POST | 撤销所有设备 |
| `/api/v1/device/current` | POST | 注册当前设备 |

---

## 九、UI样式建议

```css
.device-list {
  max-height: 400px;
  overflow-y: auto;
}

.device-item {
  display: flex;
  align-items: center;
  padding: 1em;
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 0.5em;
}

.device-item.current {
  border-color: var(--accent);
  background: rgba(37, 99, 235, 0.05);
}

.device-icon {
  font-size: 2em;
  margin-right: 1em;
}

.device-info {
  flex: 1;
}

.device-name {
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 0.5em;
}

.badge {
  background: var(--accent);
  color: white;
  font-size: 0.7em;
  padding: 2px 6px;
  border-radius: 4px;
}

.device-meta {
  font-size: 0.85em;
  color: var(--muted);
}

.btn-revoke {
  background: #fee2e2;
  color: #dc2626;
  padding: 0.5em 1em;
  border-radius: 4px;
  border: none;
}
```

---

## 十、与MFA的完整流程

```
登录流程（完整版）：

1. 输入凭证 (email, password, key_check)
           ↓
2. 验证密码
           ↓
3. 检查MFA启用状态
      ↓        ↓
   未启用      已启用
     ↓           ↓
4. 检查信任设备      ← 新增步骤
      ↓        ↓
   是信任设备   否
     ↓        ↓
5. 生成JWT    发送MFA验证码
     ↓           ↓
6. 返回Token   输入验证码
                    ↓
               验证通过
                    ↓
            注册/更新设备
                    ↓
              生成JWT
                    ↓
              返回Token
```

---

*文档版本: 1.0*
*更新日期: 2026-04-14*
