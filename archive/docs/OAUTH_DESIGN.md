# NueroNote 社交登录设计方案

**版本**: v1.2
**更新日期**: 2026-04-14

---

## 一、方案概述

### 支持平台

| 平台 | 状态 | 备注 |
|------|------|------|
| **Apple登录** | ✅ 推荐首选 | 个人开发者可用 |
| **微信登录** | ⚠️ 待定 | 需要企业资质 |
| **支付宝登录** | ⚠️ 待定 | 需要企业资质 |

### 核心设计原则

1. **社交登录 = 身份认证** - 只负责验证"你是谁"
2. **Vault密钥独立管理** - 即使微信账号被盗，Vault仍安全
3. **账户关联机制** - 同一用户可用多种方式登录

---

## 二、账户模型设计

### 2.1 用户表结构变更

```sql
-- 扩展users表
ALTER TABLE users ADD COLUMN oauth_provider TEXT;      -- 'apple', 'wechat', 'alipay'
ALTER TABLE users ADD COLUMN oauth_id TEXT;           -- 第三方用户ID
ALTER TABLE users ADD COLUMN oauth_email TEXT;         -- 第三方邮箱（可能为空）
ALTER TABLE users ADD COLUMN email_verified BOOLEAN;  -- 邮箱是否验证

-- 账户关联表（支持多平台绑定）
CREATE TABLE IF NOT EXISTS oauth_accounts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    provider TEXT NOT NULL,        -- 'apple', 'wechat', 'alipay'
    provider_user_id TEXT NOT NULL, -- 第三方平台用户ID
    provider_email TEXT,             -- 第三方平台邮箱
    email_verified BOOLEAN DEFAULT FALSE,
    created_at INTEGER NOT NULL,
    UNIQUE(provider, provider_user_id)
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_oauth_provider ON oauth_accounts(provider, provider_user_id);
CREATE INDEX IF NOT EXISTS idx_oauth_user ON oauth_accounts(user_id);
```

### 2.2 密钥管理策略

**方案A：首次登录时设置（推荐）**
```
用户流程：
1. Apple登录成功
2. 判断是否为首次登录
   - 首次：引导用户设置Vault密码
   - 非首次：使用已保存的密钥
```

**方案B：社交账号作为主密钥来源**
```
用户流程：
1. Apple登录成功
2. 服务端生成并托管密钥（需要额外加密）
⚠️ 注意：这会削弱端到端加密的安全性
```

**方案C：密钥托管（折中）**
```
用户流程：
1. Apple登录成功
2. 如果是首次，引导用户设置恢复邮箱+密码
3. 密钥由密码派生，服务端只存储加密后的Vault
```

**我们选择方案A**，保持端到端加密的完整性。

---

## 三、Apple登录实现

### 3.1 前置要求

1. **Apple开发者账号**
   - 个人：https://developer.apple.com
   - 年费：$99/年

2. **配置Sign in with Apple**
   - 在Certificates, Identifiers & Profiles中创建App ID
   - 启用Sign in with Apple capability
   - 创建Services ID
   - 配置Return URLs

3. **获取Client ID和Team ID**
   - Team ID: 开发团队唯一标识
   - Client ID: Services ID

### 3.2 前端实现

```javascript
// Apple登录按钮
async function signInWithApple() {
  // 1. 引导用户使用Apple登录
  const appleIdProvider = new AppleID.auth.AppleID.auth.AuthorizeRequest;

  try {
    // 2. 请求Apple登录
    const response = await AppleID.auth.signIn({
      clientId: 'com.yourapp.nueronote',
      scope: AppleID.auth.Scope.EMAIL,
      redirectURI: 'https://your-api.com/api/v1/auth/oauth/apple/callback',
      state: generateRandomState()
    });

    // 3. 获取identityToken
    const idToken = response.authorization.id_token;
    const authorizationCode = response.authorization.code;

    // 4. 发送到后端验证
    const resp = await fetch(API + '/auth/oauth/apple', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id_token: idToken,
        authorization_code: authorizationCode
      })
    });

    const data = await resp.json();

    if (data.success) {
      // 5. 判断是否需要设置密码
      if (data.need_setup) {
        showPasswordSetupModal();
      } else {
        // 正常登录
        token = data.token;
        userId = data.user_id;
        localStorage.setItem('flux_token', token);
        localStorage.setItem('flux_uid', userId);
        showApp();
      }
    }

  } catch (error) {
    console.error('Apple login failed:', error);
    toast('登录失败，请重试');
  }
}
```

### 3.3 后端实现

#### 路由：`/api/v1/auth/oauth/apple`

```python
@auth_bp.route('/oauth/apple', methods=['POST'])
def oauth_apple():
  """
  Apple登录/注册
  
  请求：{id_token, authorization_code}
  返回：{success, token?, user_id?, need_setup?}
  """
  body = request.get_json(force=True, silent=True) or {}
  id_token = body.get('id_token')
  authorization_code = body.get('authorization_code')
  
  if not id_token:
    return jsonify({'error': 'Missing id_token'}), 400
  
  # 1. 验证Apple id_token
  try:
    apple_user = verify_apple_id_token(id_token)
  except Exception as e:
    return jsonify({'error': f'Invalid token: {str(e)}'}), 401
  
  # 2. 查找或创建用户
  db = get_db()
  
  # 检查是否已存在关联账户
  existing_account = db.execute(
    "SELECT user_id FROM oauth_accounts WHERE provider = 'apple' AND provider_user_id = ?",
    (apple_user['sub'],)
  ).fetchone()
  
  if existing_account:
    # 已有关联账户，直接登录
    user_id = existing_account['user_id']
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    
    # 检查是否需要设置Vault密码
    need_setup = not user['salt'] or not user['key_check']
    
    token = sign_token(user_id, current_app.config['JWT_SECRET'])
    write_audit(user_id, 'OAUTH_LOGIN', details={'provider': 'apple'})
    
    return jsonify({
      'success': True,
      'token': token,
      'user_id': user_id,
      'need_setup': need_setup
    })
  
  # 3. 新用户：创建账户
  # 生成用户ID
  new_user_id = secrets.token_hex(16)
  now = int(time.time() * 1000)
  
  try:
    # 创建主用户记录
    db.execute(
      """INSERT INTO users 
         (id, email, created_at, updated_at, oauth_provider, email_verified) 
         VALUES (?, ?, ?, ?, ?, ?)""",
      (new_user_id, apple_user.get('email', ''), now, now, 'apple', 
       apple_user.get('email_verified', False))
    )
    
    # 创建OAuth关联记录
    db.execute(
      """INSERT INTO oauth_accounts 
         (id, user_id, provider, provider_user_id, provider_email, email_verified, created_at) 
         VALUES (?, ?, ?, ?, ?, ?, ?)""",
      (secrets.token_hex(16), new_user_id, 'apple', apple_user['sub'],
       apple_user.get('email'), apple_user.get('email_verified', False), now)
    )
    
    # 创建空Vault
    db.execute(
      "INSERT INTO vaults (user_id, vault_json, updated_at, storage_bytes) VALUES (?, ?, ?, ?)",
      (new_user_id, '{}', now, 0)
    )
    
  except Exception as e:
    return jsonify({'error': f'Failed to create account: {str(e)}'}), 500
  
  # 4. 生成token（首次需要设置密码）
  token = sign_token(new_user_id, current_app.config['JWT_SECRET'])
  write_audit(new_user_id, 'OAUTH_REGISTER', details={'provider': 'apple'})
  
  return jsonify({
    'success': True,
    'token': token,
    'user_id': new_user_id,
    'need_setup': True,  # 首次需要设置Vault密码
    'email': apple_user.get('email'),  # 可能为空
    'email_verified': apple_user.get('email_verified', False)
  }), 201


def verify_apple_id_token(id_token: str) -> dict:
  """
  验证Apple ID Token
  
  Apple ID Token包含以下Claims:
  - iss: Apple验证服务器
  - aud: 客户端ID
  - exp: 过期时间
  - iat: 签发时间
  - sub: 用户唯一标识
  - c_hash: 代码验证
  - email: 用户邮箱（首次可能为空）
  - email_verified: 邮箱是否验证
  """
  import jwt
  
  # Apple's公开密钥
  APPLE_KEYS_URL = 'https://appleid.apple.com/auth/keys'
  
  # 获取Apple公钥（可缓存）
  # 实际实现应缓存密钥，每24小时刷新
  apple_keys = get_apple_public_keys()  # 需要实现
  
  # 解码header获取kid
  header = jwt.get_unverified_header(id_token)
  kid = header.get('kid')
  
  # 找到对应密钥
  key = find_apple_key_by_kid(kid, apple_keys)
  if not key:
    raise ValueError('Invalid key ID')
  
  # 验证token
  try:
    payload = jwt.decode(
      id_token,
      key,
      algorithms=['RS256'],
      audience='com.yourapp.nueronote',  # 你的Client ID
      issuer='https://appleid.apple.com'
    )
    
    return {
      'sub': payload['sub'],  # Apple用户ID
      'email': payload.get('email'),
      'email_verified': payload.get('email_verified', 'false') == 'true'
    }
    
  except jwt.ExpiredSignatureError:
    raise ValueError('Token expired')
  except jwt.InvalidTokenError as e:
    raise ValueError(f'Invalid token: {str(e)}')
```

---

## 四、密码设置流程

### 4.1 首次登录引导

```python
@auth_bp.route('/setup-vault', methods=['POST'])
def setup_vault_password():
  """
  为OAuth用户设置Vault密码
  
  请求：{password, key_check, salt}
  """
  auth_header = request.headers.get('Authorization', '')
  if not auth_header.startswith('Bearer '):
    return jsonify({'error': 'Unauthorized'}), 401
  
  token = auth_header[7:]
  user_id = verify_token(token, current_app.config['JWT_SECRET'])
  if not user_id:
    return jsonify({'error': 'Invalid token'}), 401
  
  body = request.get_json(force=True, silent=True) or {}
  password = body.get('password', '')
  key_check = body.get('key_check', '')
  salt = body.get('salt', '')
  
  if len(password) < 8:
    return jsonify({'error': 'Password must be at least 8 characters'}), 400
  
  if not key_check or not salt:
    return jsonify({'error': 'Missing key_check or salt'}), 400
  
  # 更新用户记录
  db = get_db()
  db.execute(
    "UPDATE users SET password=?, salt=?, key_check=?, updated_at=? WHERE id=?",
    (password, salt, key_check, int(time.time()*1000), user_id)
  )
  
  write_audit(user_id, 'VAULT_PASSWORD_SET', details={'method': 'oauth_setup'})
  
  return jsonify({'success': True})
```

### 4.2 前端密码设置UI

```javascript
function showPasswordSetupModal() {
  // 显示密码设置对话框
  const modal = document.createElement('div');
  modal.className = 'modal';
  modal.innerHTML = `
    <div class="modal-content">
      <h2>设置Vault密码</h2>
      <p>为了保护您的笔记安全，请设置加密密码。</p>
      <p style="font-size:0.9em;color:#666">
        注意：此密码用于加密您的笔记，服务端无法解密。
        请务必牢记，忘记后将无法恢复。
      </p>
      
      <label>
        <span>设置密码</span>
        <input type="password" id="setup-password" placeholder="至少8位">
      </label>
      
      <label>
        <span>确认密码</span>
        <input type="password" id="setup-password-confirm" placeholder="再次输入密码">
      </label>
      
      <button onclick="submitVaultPassword()">确认设置</button>
    </div>
  `;
  document.body.appendChild(modal);
}

async function submitVaultPassword() {
  const password = $('#setup-password').value;
  const confirm = $('#setup-password-confirm').value;
  
  if (password !== confirm) {
    toast('两次输入的密码不一致');
    return;
  }
  
  if (password.length < 8) {
    toast('密码至少8位');
    return;
  }
  
  // 生成salt和key_check
  const saltBytes = crypto.getRandomValues(new Uint8Array(16));
  const salt = btoa(String.fromCharCode.apply(null, saltBytes)).replace(/[+/=]/g, '_');
  const keyCheck = generateKeyCheck(password, salt);
  
  try {
    const resp = await fetch(API + '/auth/setup-vault', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token
      },
      body: JSON.stringify({
        password: password,
        salt: salt,
        key_check: keyCheck
      })
    });
    
    if (resp.ok) {
      // 初始化Vault
      const vault = createVault(password);
      vaultCreate(vault, {salt, check: keyCheck, nonce: btoa('init'), ciphertext: btoa('')});
      
      // 保存vault
      const sealed = await vaultSeal(vault);
      await fetch(API + '/vault', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': 'Bearer ' + token
        },
        body: JSON.stringify({vault: vault._vault, expected_version: 0})
      });
      
      passwordCache = password;
      localStorage.setItem('flux_salt', salt);
      
      // 关闭弹窗
      document.querySelector('.modal').remove();
      
      toast('密码设置成功');
    } else {
      const data = await resp.json();
      toast(data.error || '设置失败');
    }
  } catch (e) {
    toast('网络错误');
  }
}
```

---

## 五、账户关联（后续功能）

### 5.1 多平台绑定

用户可以将多个社交账号绑定到同一个Vault：

```python
@auth_bp.route('/oauth/link', methods=['POST'])
@require_auth
def link_oauth_account():
  """
  关联第三方账户到当前用户
  """
  # 用户需已设置Vault密码
  # 验证后，添加新的OAuth关联
  pass

@auth_bp.route('/oauth/unlink', methods=['POST'])
@require_auth
def unlink_oauth_account():
  """
  解除第三方账户关联
  """
  # 至少保留一种登录方式
  pass
```

---

## 六、安全考虑

### 6.1 Token验证
- Apple ID Token必须验证签名
- 检查audience是否匹配
- 检查exp是否过期

### 6.2 邮箱处理
- Apple可能在第二次登录时不返回邮箱（隐私保护）
- 需要处理邮箱为空的情况
- 建议用户绑定备用邮箱

### 6.3 账户安全
- 同一设备多次登录失败应触发验证码
- 异地登录应发送通知

---

## 七、微信/支付宝（企业功能）

### 7.1 申请条件
- 微信开放平台：需要企业营业执照
- 支付宝开放平台：需要企业资质

### 7.2 申请流程
1. 注册微信/支付宝开放平台账号
2. 完成企业认证
3. 创建应用，获取AppID和AppSecret
4. 配置授权回调域
5. 实现OAuth2.0流程

### 7.3 架构兼容
微信/支付宝实现架构与Apple登录类似：
- 验证平台Token
- 查找/创建关联账户
- 生成JWT

---

## 八、后续规划

| 阶段 | 功能 | 优先级 |
|------|------|--------|
| **v1.2** | Apple登录 | P0 |
| **v1.3** | 账户关联（多平台绑定） | P1 |
| **v1.4** | 微信登录（企业） | P2 |
| **v1.5** | 支付宝登录（企业） | P2 |

---

## 九、技术储备

### 需要的技术栈
- `PyJWT`: Python JWT处理
- `cryptography`: RSA密钥处理
- 前端Apple登录SDK

### 参考资料
- [Sign in with Apple](https://developer.apple.com/documentation/sign_in_with_apple)
- [Apple ID API Reference](https://developer.apple.com/documentation/sign_in_with_apple/generate_and_validate_tokens)

---

*文档版本: 1.0*
*更新日期: 2026-04-14*
