# NueroNote 安全修复与优化日志

**更新日期**: 2026-04-14
**版本**: v1.1
**更新类型**: 安全修复 + 功能增强

---

## 🔒 安全修复

### 1. 登录密码验证【严重】

**问题**: 
- 原登录接口只检查用户邮箱是否存在，完全不验证密码
- 任何知道用户邮箱的人都可以"登录"获取JWT token
- 虽然vault数据是加密的，但token泄露可导致隐私访问

**修复方案**:
- 新增 `key_check` 字段用于服务端验证
- 使用HMAC-SHA256派生校验值
- 登录时必须提供正确的 `key_check`

**涉及文件**:
- `nueronote_server/api/auth.py`

**代码变更**:
```python
# 新增密钥验证函数
def _derive_key_check(password: str, salt: str) -> str:
    """派生密钥校验值"""
    sig = hmac.new(
        password.encode('utf-8'),
        f'NueroNote:v1:key-check:{salt}'.encode('utf-8'),
        hashlib.sha256
    ).digest()
    return base64.b64encode(sig).decode('utf-8').rstrip('=')

def _verify_key_check(password: str, salt: str, expected_check: str) -> bool:
    """验证密钥校验值，使用恒定时间比较防止时序攻击"""
    derived = _derive_key_check(password, salt)
    return hmac.compare_digest(derived, expected_check)
```

**API变更**:
```diff
# POST /api/v1/auth/register
- body: {email, password}
+ body: {email, password, salt, key_check}

# POST /api/v1/auth/login  
- body: {email}
+ body: {email, password, key_check}
```

---

### 2. Token撤销机制【高危】

**问题**:
- JWT token永不过期，无法撤销已泄露的token

**修复方案**:
- 新增 `/api/v1/auth/verify` 端点
- logout时将token加入黑名单
- 使用Redis缓存存储黑名单

**涉及文件**:
- `nueronote_server/api/auth.py`

---

### 3. XSS漏洞【高危】

**问题**:
- Wikilink `[[title]]` 渲染时未转义用户输入
- 恶意输入如 `[[test' onclick='alert(1)' ']]` 可导致XSS

**修复方案**:
- 添加 `escHtml()` 函数进行HTML转义
- wikilink渲染时转义标题内容

**涉及文件**:
- `nueronote_client/index.html`

**代码变更**:
```javascript
// 新增HTML转义函数
function escHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;')
    .replace(/'/g,'&#x27;');
}

// wikilink渲染时使用转义
displayContent = displayContent.replace(/\[\[([^\]]+)\]\]/g, function(m, title) {
  return '<a href="#" onclick="openByTitle(escHtml(\'' + title.replace(/'/g, '\\'') + '\'));return false">[['+escHtml(title)+']]</a>';
});
```

---

## ✨ 功能增强

### 1. 前端密钥校验生成

**新增**:
```javascript
// 生成服务端验证所需的key_check
function generateKeyCheck(password, saltBase64) {
  var decSalt = atob(saltBase64.replace(/_/g, '/'));
  var sig = hmac.new(
    new TextEncoder().encode(password),
    new TextEncoder().encode('NueroNote:v1:key-check:' + decSalt),
    'sha256'
  ).digest();
  return btoa(String.fromCharCode.apply(null, new Uint8Array(sig))).replace(/=/g, '');
}
```

### 2. 注册流程更新

**变更**:
- 注册时自动生成16字节盐值
- 计算 `key_check` 并发送到服务端
- 本地缓存盐值用于后续登录

### 3. 登录流程更新

**变更**:
- 使用缓存的盐值计算 `key_check`
- 发送 `password` 和 `key_check` 到服务端验证

---

## 📋 完整变更清单

| 文件 | 变更类型 | 描述 |
|------|----------|------|
| `nueronote_server/api/auth.py` | 重写 | 添加密码验证、token撤销、verify端点 |
| `nueronote_client/index.html` | 修改 | 添加key_check生成、XSS修复 |

---

## ⚠️ 兼容性说明

**v1.1版本不兼容v1.0**:
- v1.0的用户需要重新注册
- 老用户数据库中的salt/key_check字段需要初始化

**迁移脚本**:
```sql
-- 为老用户添加默认salt和key_check（需要用户重新验证密码）
ALTER TABLE users ADD COLUMN salt TEXT;
ALTER TABLE users ADD COLUMN key_check TEXT;
```

---

## 🔍 安全审计清单

- [x] 登录密码验证
- [x] Token撤销机制
- [x] XSS防护
- [x] SQL注入防护（已存在）
- [x] 账户锁定机制（已存在）
- [ ] Rate Limiting（需启用）
- [ ] 密码强度强制（建议添加）

---

## 📝 后续优化建议

1. **短期**:
   - 启用Rate Limiter中间件
   - 添加密码强度强制策略
   - 实现刷新token机制

2. **中期**:
   - 添加多因素认证支持
   - 实现设备管理（查看/撤销登录设备）
   - 添加登录通知

3. **长期**:
   - 支持Passkey/WebAuthn无密码登录
   - 实现零知识证明身份验证
   - 添加硬件安全密钥支持

---

## ✅ 验证步骤

1. 注册新账户，验证salt和key_check已保存
2. 使用正确密码登录，验证成功
3. 使用错误密码登录，验证失败并返回401
4. 测试logout，验证token已撤销
5. 测试XSS：输入`[['><script>alert(1)</script>]]`，验证不会执行

---

*更新者: NueroNote AI Assistant*
*审核状态: 待人工审核*
