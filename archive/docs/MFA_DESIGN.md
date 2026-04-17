# NueroNote MFA（多因素认证）设计方案

**版本**: v1.2
**更新日期**: 2026-04-14
**方案**: 邮件验证码 + 短信验证码（可选）

---

## 一、方案概述

### 1.1 支持的MFA方式

| 方式 | 状态 | 成本 | 说明 |
|------|------|------|------|
| **邮件验证码** | ✅ 首选 | 0元 | 发送到注册邮箱 |
| **短信验证码** | ⚠️ 可选 | ~0.05元/条 | 需要短信服务商 |

### 1.2 核心设计

```
登录流程（启用MFA后）：

1. 输入邮箱/密码 + key_check
   ↓ 验证成功
2. 发送MFA验证码（邮件/短信）
   ↓
3. 输入验证码
   ↓ 验证成功
4. 获得JWT Token

→ 攻击者即使破解密码，仍无法登录（需要验证码）
```

---

## 二、数据库设计

### 2.1 新增表

```sql
-- MFA设置表
CREATE TABLE IF NOT EXISTS mfa_settings (
    user_id         TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    mfa_enabled     BOOLEAN DEFAULT FALSE,           -- 是否启用MFA
    mfa_type        TEXT DEFAULT 'email',            -- 'email' 或 'sms'
    phone_number    TEXT,                             -- 短信用
    backup_codes    TEXT,                             -- 备用码（JSON数组）
    created_at      INTEGER NOT NULL,
    updated_at      INTEGER NOT NULL
);

-- MFA验证码表（临时）
CREATE TABLE IF NOT EXISTS mfa_codes (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code            TEXT NOT NULL,                    -- 6位验证码
    code_hash       TEXT NOT NULL,                    -- 哈希存储（安全）
    mfa_type        TEXT NOT NULL,                    -- 'email' 或 'sms'
    attempts        INTEGER DEFAULT 0,                -- 尝试次数
    expires_at      INTEGER NOT NULL,                 -- 过期时间戳
    created_at      INTEGER NOT NULL,
    used_at         INTEGER                           -- 使用时间（null=未使用）
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_mfa_codes_user ON mfa_codes(user_id);
CREATE INDEX IF NOT EXISTS idx_mfa_codes_expires ON mfa_codes(expires_at);
```

### 2.2 Users表扩展

```sql
-- 添加手机号字段（可选）
ALTER TABLE users ADD COLUMN phone_number TEXT;
ALTER TABLE users ADD COLUMN phone_verified BOOLEAN DEFAULT FALSE;
```

---

## 三、API设计

### 3.1 MFA管理API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/mfa/setup` | POST | 初始化MFA设置 |
| `/api/v1/mfa/verify-setup` | POST | 验证MFA设置 |
| `/api/v1/mfa/status` | GET | 获取MFA状态 |
| `/api/v1/mfa/send-code` | POST | 发送验证码 |
| `/api/v1/mfa/disable` | POST | 禁用MFA |

### 3.2 登录流程API变更

```
POST /api/v1/auth/login
  请求: {email, password, key_check}
  返回: {
    success: true,
    mfa_required: true,    ← 新增字段
    mfa_type: 'email',     ← 'email' 或 'sms'
    mfa_token: 'temp_xxx'   ← 临时token，用于MFA验证
  }

POST /api/v1/auth/mfa-verify
  请求: {mfa_token, code}
  返回: {token, user_id}   ← 正式JWT
```

---

## 四、后端实现

### 4.1 MFA服务模块

```python
# nueronote_server/services/mfa.py

import hashlib
import hmac
import secrets
import time
from typing import Optional, Tuple

class MFAService:
    """MFA服务"""
    
    # 验证码配置
    CODE_LENGTH = 6
    CODE_EXPIRY_MINUTES = 5
    MAX_ATTEMPTS = 3
    MAX_BACKUP_CODES = 10
    
    def __init__(self):
        self.cache = None  # 可选：使用Redis缓存验证码
    
    def generate_code(self) -> str:
        """生成6位随机验证码"""
        return ''.join([str(secrets.randbelow(10)) for _ in range(self.CODE_LENGTH)])
    
    def hash_code(self, code: str, salt: str = '') -> str:
        """哈希验证码（防止明文存储）"""
        return hashlib.sha256(
            f"{code}:{salt}:{time.time() // 300}".encode()
        ).hexdigest()[:32]
    
    def verify_code(self, code: str, hashed: str) -> bool:
        """验证验证码（恒定时间）"""
        # 尝试验证最近3个时间窗口
        current_window = time.time() // 300
        for window_offset in range(3):
            window = current_window - window_offset
            expected = hashlib.sha256(
                f"{code}:::{window}".encode()
            ).hexdigest()[:32]
            if hmac.compare_digest(hashed, expected):
                return True
        return False
    
    def send_email_code(self, email: str, code: str) -> bool:
        """发送邮件验证码"""
        # TODO: 集成邮件服务
        # 可选: SendGrid, Amazon SES, 自建SMTP
        print(f"[MFA Email] To: {email}, Code: {code}")  # DEBUG
        return True
    
    def send_sms_code(self, phone: str, code: str) -> bool:
        """发送短信验证码"""
        # TODO: 集成短信服务
        # 可选: 阿里云, 腾讯云, 短信宝
        print(f"[MFA SMS] To: {phone}, Code: {code}")  # DEBUG
        return True
    
    def generate_backup_codes(self) -> list:
        """生成备用码（一次性）"""
        codes = []
        for _ in range(self.MAX_BACKUP_CODES):
            code = secrets.token_hex(4).upper()  # 8位
            codes.append(code)
        return codes
    
    def create_mfa_session(self, user_id: str, mfa_type: str) -> Tuple[str, str]:
        """
        创建MFA会话
        
        Returns: (session_token, code)
        """
        code = self.generate_code()
        session_token = secrets.token_urlsafe(32)
        
        # 存储会话（可使用Redis或数据库）
        # 这里简化处理，直接存储到mfa_codes表
        
        return session_token, code
    
    def verify_mfa_session(self, session_token: str, code: str) -> Optional[str]:
        """
        验证MFA会话
        
        Returns: user_id if valid, None otherwise
        """
        # TODO: 实现验证逻辑
        pass
```

### 4.2 MFA路由

```python
# nueronote_server/api/mfa.py

from flask import Blueprint, g, jsonify, request
from functools import wraps
import hashlib
import secrets
import time

from nueronote_server.database import get_db
from nueronote_server.utils.jwt import sign_token, verify_token
from nueronote_server.utils.audit import write_audit
from nueronote_server.services.mfa import MFAService

mfa_bp = Blueprint('mfa', __name__, url_prefix='/api/v1/mfa')
mfa_service = MFAService()

# MFA会话存储（生产环境应使用Redis）
MFA_SESSIONS = {}


def require_mfa_session(func):
    """验证MFA会话"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Missing session token'}), 401
        
        session_token = auth_header[7:]
        if session_token not in MFA_SESSIONS:
            return jsonify({'error': 'Invalid or expired session'}), 401
        
        session = MFA_SESSIONS[session_token]
        if session['expires_at'] < time.time():
            del MFA_SESSIONS[session_token]
            return jsonify({'error': 'Session expired'}), 401
        
        g.mfa_session = session
        return func(*args, **kwargs)
    return wrapper


@mfa_bp.route('/setup', methods=['POST'])
@require_auth
def setup_mfa():
    """
    初始化MFA设置
    
    请求: {type: 'email' | 'sms', phone_number?: string}
    返回: {success, backup_codes[]}
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
        return jsonify({'error': 'No email associated with account'}), 400
    
    if mfa_type == 'sms':
        phone = body.get('phone_number')
        if not phone:
            return jsonify({'error': 'Phone number required'}), 400
        # TODO: 验证手机号格式
    
    # 生成备用码
    backup_codes = mfa_service.generate_backup_codes()
    backup_codes_hash = [mfa_service.hash_code(code) for code in backup_codes]
    
    # 保存MFA设置
    try:
        db.execute("""
            INSERT OR REPLACE INTO mfa_settings 
            (user_id, mfa_enabled, mfa_type, phone_number, backup_codes, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (user_id, True, mfa_type, body.get('phone_number'), 
              json.dumps(backup_codes_hash), now, now))
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    # 发送测试验证码
    if mfa_type == 'email':
        code = mfa_service.generate_code()
        mfa_service.send_email_code(user['email'], code)
        # 存储验证码
        _store_code(user_id, code, 'email')
    else:
        code = mfa_service.generate_code()
        mfa_service.send_sms_code(body.get('phone_number'), code)
        _store_code(user_id, code, 'sms')
    
    write_audit(user_id, 'MFA_ENABLED', details={'type': mfa_type})
    
    return jsonify({
        'success': True,
        'message': 'MFA enabled. Please verify with the code sent.',
        'backup_codes': backup_codes,  # 明文显示一次，之后不保存
        'warning': 'Save backup codes securely. They can only be used once.'
    })


@mfa_bp.route('/verify-setup', methods=['POST'])
@require_auth
def verify_mfa_setup():
    """
    验证MFA设置（首次验证）
    
    请求: {code}
    """
    body = request.get_json(force=True, silent=True) or {}
    code = body.get('code', '').strip()
    
    if len(code) != 6:
        return jsonify({'error': 'Invalid code format'}), 400
    
    user_id = g.user_id
    
    # 验证验证码
    if not _verify_and_consume_code(user_id, code):
        return jsonify({'error': 'Invalid or expired code'}), 401
    
    write_audit(user_id, 'MFA_VERIFIED', details={'type': 'setup'})
    
    return jsonify({
        'success': True,
        'message': 'MFA setup verified successfully'
    })


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


@mfa_bp.route('/send-code', methods=['POST'])
@require_auth
def send_mfa_code():
    """
    发送MFA验证码（用于登录时）
    
    请求: 无（从MFA会话获取用户信息）
    """
    session = g.mfa_session
    user_id = session['user_id']
    mfa_type = session.get('mfa_type', 'email')
    
    db = get_db()
    mfa_settings = db.execute(
        "SELECT * FROM mfa_settings WHERE user_id = ? AND mfa_enabled = 1",
        (user_id,)
    ).fetchone()
    
    if not mfa_settings:
        return jsonify({'error': 'MFA not enabled'}), 400
    
    # 获取用户联系方式
    if mfa_settings['mfa_type'] == 'email':
        user = db.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
        contact = user['email'] if user else None
    else:
        contact = mfa_settings['phone_number']
    
    if not contact:
        return jsonify({'error': 'No contact info'}), 400
    
    # 生成并发送验证码
    code = mfa_service.generate_code()
    if mfa_settings['mfa_type'] == 'email':
        mfa_service.send_email_code(contact, code)
    else:
        mfa_service.send_sms_code(contact, code)
    
    # 存储验证码
    _store_code(user_id, code, mfa_settings['mfa_type'])
    
    return jsonify({
        'success': True,
        'message': f'Code sent to {mfa_settings["mfa_type"]}',
        'expires_in': 300  # 5分钟
    })


@mfa_bp.route('/verify', methods=['POST'])
@require_mfa_session
def verify_mfa():
    """
    验证MFA验证码（登录流程）
    
    请求: {code}
    返回: {token, user_id}
    """
    body = request.get_json(force=True, silent=True) or {}
    code = body.get('code', '').strip()
    
    if len(code) != 6:
        return jsonify({'error': 'Invalid code format'}), 400
    
    session = g.mfa_session
    user_id = session['user_id']
    
    # 验证验证码
    if not _verify_and_consume_code(user_id, code):
        return jsonify({'error': 'Invalid or expired code'}), 401
    
    # 生成正式JWT
    token = sign_token(user_id, current_app.config['JWT_SECRET'])
    
    # 清理MFA会话
    del MFA_SESSIONS[request.headers.get('Authorization', '')[7:]]
    
    write_audit(user_id, 'MFA_LOGIN_SUCCESS')
    
    return jsonify({
        'success': True,
        'token': token,
        'user_id': user_id
    })


@mfa_bp.route('/disable', methods=['POST'])
@require_auth
def disable_mfa():
    """
    禁用MFA（需要验证）
    
    请求: {password, key_check, code}
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
        return jsonify({'error': 'Invalid password'}), 401
    
    # 验证MFA码
    if not _verify_and_consume_code(user_id, code):
        return jsonify({'error': 'Invalid MFA code'}), 401
    
    # 禁用MFA
    db.execute("DELETE FROM mfa_settings WHERE user_id = ?", (user_id,))
    
    write_audit(user_id, 'MFA_DISABLED')
    
    return jsonify({'success': True, 'message': 'MFA disabled'})


@mfa_bp.route('/backup-code', methods=['POST'])
@require_auth
def use_backup_code():
    """
    使用备用码登录
    
    请求: {backup_code}
    """
    body = request.get_json(force=True, silent=True) or {}
    backup_code = body.get('backup_code', '').strip().upper()
    
    session = g.mfa_session
    user_id = session['user_id']
    mfa_type = session.get('mfa_type', 'email')
    
    db = get_db()
    settings = db.execute(
        "SELECT backup_codes FROM mfa_settings WHERE user_id = ?", (user_id,)
    ).fetchone()
    
    if not settings or not settings['backup_codes']:
        return jsonify({'error': 'No backup codes available'}), 400
    
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
    
    # 生成JWT
    token = sign_token(user_id, current_app.config['JWT_SECRET'])
    
    write_audit(user_id, 'MFA_BACKUP_SUCCESS', details={'codes_remaining': len(backup_codes)})
    
    return jsonify({
        'success': True,
        'token': token,
        'user_id': user_id,
        'codes_remaining': len(backup_codes)
    })


# ============================================================================
# 辅助函数
# ============================================================================

def _store_code(user_id: str, code: str, mfa_type: str):
    """存储验证码"""
    db = get_db()
    now = int(time.time() * 1000)
    expires_at = now + 5 * 60 * 1000  # 5分钟后过期
    
    code_hash = mfa_service.hash_code(code)
    
    # 删除该用户的所有旧验证码
    db.execute("DELETE FROM mfa_codes WHERE user_id = ?", (user_id,))
    
    # 存储新验证码
    db.execute("""
        INSERT INTO mfa_codes 
        (id, user_id, code, code_hash, mfa_type, expires_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (secrets.token_hex(16), user_id, code, code_hash, mfa_type, expires_at, now))


def _verify_and_consume_code(user_id: str, code: str) -> bool:
    """验证并消费验证码（一次性）"""
    db = get_db()
    now = int(time.time() * 1000)
    
    row = db.execute("""
        SELECT * FROM mfa_codes 
        WHERE user_id = ? AND expires_at > ? AND used_at IS NULL
        ORDER BY created_at DESC LIMIT 1
    """, (user_id, now)).fetchone()
    
    if not row:
        return False
    
    # 验证验证码
    code_hash = mfa_service.hash_code(code)
    if not hmac.compare_digest(code_hash, row['code_hash']):
        # 增加尝试次数
        db.execute(
            "UPDATE mfa_codes SET attempts = attempts + 1 WHERE id = ?",
            (row['id'],)
        )
        return False
    
    # 标记为已使用
    db.execute(
        "UPDATE mfa_codes SET used_at = ? WHERE id = ?",
        (now, row['id'])
    )
    
    return True
```

---

## 五、登录流程变更

### 5.1 修改后的登录流程

```python
@auth_bp.route('/login', methods=['POST'])
def login():
    """登录（含MFA）"""
    # ... 现有验证逻辑 ...
    
    # 验证密码
    if not _verify_key_check(password, user['salt'], user['key_check']):
        _increment_login_fails(db, user_id)
        return jsonify({'error': 'Invalid credentials'}), 401
    
    # 检查是否启用MFA
    db = get_db()
    mfa_settings = db.execute(
        "SELECT mfa_enabled, mfa_type FROM mfa_settings WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    
    if mfa_settings and mfa_settings['mfa_enabled']:
        # 需要MFA验证
        mfa_token = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + 300  # 5分钟
        
        # 存储MFA会话
        MFA_SESSIONS[mfa_token] = {
            'user_id': user_id,
            'mfa_type': mfa_settings['mfa_type'],
            'expires_at': expires_at
        }
        
        # 发送验证码
        if mfa_settings['mfa_type'] == 'email':
            _send_mfa_email(user['email'])
        else:
            _send_mfa_sms(mfa_settings['phone_number'])
        
        return jsonify({
            'success': True,
            'mfa_required': True,
            'mfa_type': mfa_settings['mfa_type'],
            'mfa_token': mfa_token,
            'message': 'MFA verification required'
        })
    
    # 无MFA，直接返回token
    token = sign_token(user_id, current_app.config['JWT_SECRET'])
    return jsonify({
        'success': True,
        'token': token,
        'user_id': user_id
    })


@auth_bp.route('/mfa-verify', methods=['POST'])
def mfa_verify():
    """MFA验证"""
    body = request.get_json(force=True, silent=True) or {}
    mfa_token = body.get('mfa_token', '')
    code = body.get('code', '').strip()
    
    if mfa_token not in MFA_SESSIONS:
        return jsonify({'error': 'Invalid session'}), 401
    
    session = MFA_SESSIONS[mfa_token]
    if session['expires_at'] < time.time():
        del MFA_SESSIONS[mfa_token]
        return jsonify({'error': 'Session expired'}), 401
    
    user_id = session['user_id']
    
    # 验证验证码
    if not _verify_and_consume_code(user_id, code):
        return jsonify({'error': 'Invalid code'}), 401
    
    # 生成正式token
    token = sign_token(user_id, current_app.config['JWT_SECRET'])
    
    # 清理会话
    del MFA_SESSIONS[mfa_token]
    
    write_audit(user_id, 'LOGIN_MFA_SUCCESS')
    
    return jsonify({
        'success': True,
        'token': token,
        'user_id': user_id
    })
```

---

## 六、前端实现

### 6.1 MFA登录UI

```javascript
// MFA登录弹窗
function showMFADialog(mfaToken, mfaType) {
  const modal = document.createElement('div');
  modal.id = 'mfa-modal';
  modal.innerHTML = `
    <div class="modal-content">
      <h2>输入验证码</h2>
      <p>验证码已发送到您的${mfaType === 'email' ? '邮箱' : '手机'}</p>
      
      <div class="code-input-group">
        <input type="text" id="mfa-code" maxlength="6" 
               placeholder="6位验证码" autocomplete="one-time-code">
      </div>
      
      <button onclick="verifyMFA('${mfaToken}')" class="primary">验证</button>
      
      <div class="mfa-footer">
        <a href="#" onclick="resendCode('${mfaToken}');return false">重新发送</a>
        <span class="divider">|</span>
        <a href="#" onclick="showBackupCodeDialog('${mfaToken}');return false">使用备用码</a>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
}

async function verifyMFA(mfaToken) {
  const code = $('#mfa-code').value.trim();
  
  if (code.length !== 6) {
    toast('请输入6位验证码');
    return;
  }
  
  try {
    const resp = await fetch(API + '/auth/mfa-verify', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mfa_token: mfaToken, code: code})
    });
    
    const data = await resp.json();
    
    if (data.success) {
      // 登录成功
      token = data.token;
      userId = data.user_id;
      localStorage.setItem('flux_token', token);
      localStorage.setItem('flux_uid', userId);
      
      $('#mfa-modal').remove();
      showApp();
      toast('登录成功');
    } else {
      toast(data.error || '验证失败');
    }
  } catch (e) {
    toast('网络错误');
  }
}

async function resendCode(mfaToken) {
  try {
    const resp = await fetch(API + '/mfa/send-code', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + mfaToken
      }
    });
    
    const data = await resp.json();
    if (data.success) {
      toast('验证码已重新发送');
    } else {
      toast(data.error || '发送失败');
    }
  } catch (e) {
    toast('网络错误');
  }
}

// 备用码登录
async function verifyBackupCode(mfaToken) {
  const code = $('#backup-code').value.trim().toUpperCase();
  
  if (code.length !== 8) {
    toast('请输入8位备用码');
    return;
  }
  
  try {
    const resp = await fetch(API + '/mfa/backup-code', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + mfaToken
      },
      body: JSON.stringify({backup_code: code})
    });
    
    const data = await resp.json();
    
    if (data.success) {
      token = data.token;
      userId = data.user_id;
      localStorage.setItem('flux_token', token);
      localStorage.setItem('flux_uid', userId);
      
      $('#mfa-modal').remove();
      showApp();
      toast(`登录成功，剩余 ${data.codes_remaining} 个备用码`);
    } else {
      toast(data.error || '验证失败');
    }
  } catch (e) {
    toast('网络错误');
  }
}
```

### 6.2 MFA设置页面

```javascript
// 在设置页面添加MFA选项
async function showMFASettings() {
  const resp = await fetch(API + '/mfa/status', {
    headers: {'Authorization': 'Bearer ' + token}
  });
  const data = await resp.json();
  
  if (data.enabled) {
    showDisableMFAOption(data.type);
  } else {
    showEnableMFAOption();
  }
}

async function enableMFA(type) {
  const body = {type: type};
  
  if (type === 'sms') {
    const phone = prompt('请输入手机号:');
    if (!phone) return;
    body.phone_number = phone;
  }
  
  try {
    const resp = await fetch(API + '/mfa/setup', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token
      },
      body: JSON.stringify(body)
    });
    
    const data = await resp.json();
    
    if (data.success) {
      // 显示备用码
      alert(`MFA已启用！\n\n备用码（请妥善保管）：\n${data.backup_codes.join('\n')}\n\n${data.warning}`);
      
      // 弹出验证界面
      showMFAVerifyDialog(data.backup_codes);
    } else {
      toast(data.error || '启用失败');
    }
  } catch (e) {
    toast('网络错误');
  }
}
```

---

## 七、邮件服务集成

### 7.1 邮件发送（简单实现）

```python
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_email(to_email: str, subject: str, body: str):
    """发送邮件（简单SMTP实现）"""
    smtp_server = os.environ.get('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = os.environ.get('SMTP_USER')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    
    if not smtp_user or not smtp_password:
        print(f"[Email] DEBUG: To={to_email}, Subject={subject}")
        return True
    
    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = to_email
    msg['Subject'] = subject
    
    msg.attach(MIMEText(body, 'html'))
    
    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
    
    return True


def send_mfa_email(email: str, code: str):
    """发送MFA验证码邮件"""
    subject = "【NueroNote】您的登录验证码"
    html_body = f"""
    <html>
    <body>
    <h2>您好，</h2>
    <p>您正在进行 NueroNote 登录验证，您的验证码是：</p>
    <h1 style="font-size: 32px; letter-spacing: 8px; color: #2563eb;">{code}</h1>
    <p>验证码有效期为 <strong>5 分钟</strong>，请勿告诉他人。</p>
    <p>如果您没有进行登录操作，请忽略此邮件。</p>
    <hr>
    <p style="color: #666; font-size: 12px;">
    NueroNote - 端到端加密笔记<br>
    此邮件由系统自动发送，请勿回复。
    </p>
    </body>
    </html>
    """
    return send_email(email, subject, html_body)
```

### 7.2 推荐邮件服务

| 服务 | 免费额度 | 说明 |
|------|----------|------|
| **SendGrid** | 100/天 | 稳定，推荐 |
| **Amazon SES** | 62,000/月 | 成本最低 |
| **Mailgun** | 5,000/月 | API友好 |
| **自建SMTP** | 无限 | 使用企业邮箱 |

---

## 八、安全考虑

### 8.1 验证码安全
- ❌ 不存储明文验证码
- ✅ 存储SHA256哈希
- ✅ 验证码5分钟过期
- ✅ 最多3次尝试
- ✅ 尝试错误后需重新获取

### 8.2 暴力破解防护
- 验证码6位 = 100万种组合
- 3次尝试限制 = 暴力破解概率极低
- 账户锁定机制（已有）

### 8.3 备用码安全
- 生成10个8位备用码
- 每个码只能使用一次
- SHA256哈希存储

---

## 九、用户体验优化

### 9.1 验证码自动填充
```html
<input type="text" inputmode="numeric" 
       autocomplete="one-time-code" 
       pattern="[0-9]*" maxlength="6">
```

### 9.2 倒计时重发
```javascript
let countdown = 60;
const timer = setInterval(() => {
  countdown--;
  $('#resend-btn').textContent = `重新发送 (${countdown}s)`;
  if (countdown <= 0) {
    clearInterval(timer);
    $('#resend-btn').textContent = '重新发送';
  }
}, 1000);
```

---

## 十、实现计划

| 阶段 | 功能 | 工作量 | 优先级 |
|------|------|--------|--------|
| **1** | 数据库表设计 | 0.5天 | P0 |
| **2** | MFA API实现 | 1天 | P0 |
| **3** | 邮件发送集成 | 0.5天 | P0 |
| **4** | 前端MFA UI | 1天 | P0 |
| **5** | 短信发送（可选） | 1天 | P1 |

---

*文档版本: 1.0*
*更新日期: 2026-04-14*
