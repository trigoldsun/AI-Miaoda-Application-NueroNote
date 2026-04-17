# NueroNote 安全修复日志 v1.2

**更新日期**: 2026-04-14
**版本**: v1.2
**更新类型**: 安全漏洞修复 + 依赖更新

---

## 🔒 安全修复

### P0 级别 - 严重漏洞

#### 1. JWT密钥弱默认检查【严重】

**问题**:
- 配置模块中使用弱默认密钥（如 "changeme-jwt-secret-in-production"）
- 攻击者可伪造任意用户JWT token

**修复方案**:
- 添加 `WEAK_SECRETS` 禁止密钥列表
- 添加 `_is_weak_secret()` 检查函数
- **生产环境禁止使用弱密钥和长度小于32的密钥**
- 启动时检查并拒绝使用弱密钥

**涉及文件**:
- `nueronote_server/config/__init__.py`

**代码变更**:
```python
# 禁止使用的弱密钥列表
WEAK_SECRETS = {
    "changeme", "changeme-jwt-secret", "changeme-jwt-secret-in-production",
    "secret", "secret-key", "jwt-secret", "your-secret-key",
    "password", "123456", "000000", "admin", "root"
}

def _is_weak_secret(self, key: str) -> bool:
    key_lower = key.lower()
    if key_lower in self.WEAK_SECRETS:
        return True
    if "changeme" in key_lower or len(key) < 32:
        return True
    return False

def __post_init__(self):
    is_production = os.environ.get("NN_DEBUG", "false").lower() != "true"
    # ...
    elif is_production and self._is_weak_secret(self.secret_key):
        raise ValueError(f"生产环境禁止使用弱密钥! 请设置至少32字符的NN_SECRET_KEY")
    # 同样检查 jwt_secret
```

---

#### 2. 审计日志伪造漏洞【严重】

**问题**:
- `write_audit()` 函数接受外部传入的 `user_id` 参数
- 攻击者可伪造任意用户行为审计记录

**修复方案**:
- 修改 `write_audit()` 强制从 Flask `g` 对象获取 `user_id`
- 忽略外部传入的 `user_id` 参数
- 不在Flask上下文时使用 'SYSTEM'

**涉及文件**:
- `nueronote_server/utils/audit.py`

**代码变更**:
```python
def write_audit(user_id: str = None, action: str = None, details: Dict = None,
               resource_type: str = None, resource_id: str = None) -> int:
    """
    【安全修复 v1.2】
    现在强制从Flask g对象获取user_id，不接受外部传入的值。
    """
    try:
        from flask import g
        actual_user_id = getattr(g, 'user_id', None) or 'SYSTEM'
    except RuntimeError:
        actual_user_id = 'SYSTEM'

    return log_audit(
        action=action or "UNKNOWN",
        user_id=actual_user_id,  # 忽略传入的user_id
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
    )
```

---

#### 3. 存储配额绕过漏洞【严重】

**问题**:
- 原代码只检查当前上传vault大小
- 未累计用户已使用的存储量
- 用户可超过配额限制

**修复方案**:
- 计算**总使用量 = 当前vault大小 + 已使用存储**
- 正确判断是否超出配额

**涉及文件**:
- `nueronote_server/api/vault.py`

**代码变更**:
```python
# 配额检查 【安全修复 v1.2 - 计算总使用量】
user = db.execute(
    "SELECT storage_quota, storage_used FROM users WHERE id = ?", (g.user_id,)
).fetchone()
if user:
    # 计算总使用量 = 当前vault大小 + 已使用存储
    total_usage = vault_bytes + (user["storage_used"] or 0)
    if total_usage > user["storage_quota"]:
        return jsonify({
            "error": "Storage quota exceeded",
            "quota": user["storage_quota"],
            "current_usage": user["storage_used"] or 0,
            "required": vault_bytes,
            "total_after_upload": total_usage,
        }), 507
```

---

### P1 级别 - 高优先级

#### 4. 强化 XSS 防护

**问题**:
- wikilink 渲染时 onclick handler 中的 title 未转义
- 原有修复不完整

**修复方案**:
- 在 onclick handler 中也使用 `escHtml()` 转义 title
- 使用函数式 replace 确保 title 被正确转义

**涉及文件**:
- `nueronote_client/index.html`

**代码变更**:
```javascript
// Render wikilinks 【安全修复 v1.2】HTML转义防止XSS
displayContent = displayContent.replace(/\[\[([^\]]+)\]\]/g, function(match, title) {
  return '<a href="#" onclick="openByTitle(\\'' + escHtml(title) + '\\');return false" style="color:var(--accent)">[[' + escHtml(title) + ']]</a>';
});
```

---

## 📦 依赖更新

### 新增安全依赖

**问题**:
- `requirements.txt` 仅有两个基础依赖
- 缺少关键安全库

**修复方案**:
- 添加 PyJWT (JWT认证)
- 添加 bcrypt (密码哈希)
- 添加 cryptography (加密支持)
- 添加 pydantic + email-validator (数据验证)
- 添加 redis (缓存)
- 添加 flask-limiter (速率限制)
- 添加 flask-cors (CORS支持)
- 添加 gunicorn (生产服务器)

**涉及文件**:
- `nueronote_server/requirements.txt`

**新增依赖**:
```
PyJWT>=2.8.0
bcrypt>=4.1.0
cryptography>=41.0.0
pydantic>=2.5.0
email-validator>=2.1.0
redis>=5.0.0
flask-limiter>=3.5.0
flask-cors>=4.0.0
gunicorn>=21.2.0
```

---

## 📋 修复文件清单

| 文件路径 | 修复类型 |
|----------|---------|
| `nueronote_server/config/__init__.py` | P0: JWT密钥检查 |
| `nueronote_server/utils/audit.py` | P0: 审计日志安全 |
| `nueronote_server/api/vault.py` | P0: 配额计算 |
| `nueronote_client/index.html` | P1: XSS防护 (两处) |
| `nueronote_server/requirements.txt` | P1: 安全依赖 |

---

## ⚠️ 部署注意事项

1. **必须设置环境变量**:
   - `NN_SECRET_KEY` - 至少32字符的强密钥
   - `NN_JWT_SECRET` - 至少32字符的强密钥
   - `NN_DEBUG=false` - 生产环境必须设为 false

2. **安装新依赖**:
   ```bash
   cd nueronote_server
   pip install -r requirements.txt
   ```

3. **验证密钥强度**:
   ```bash
   # 启动时会自动检查密钥强度
   python app.py
   # 如果使用弱密钥，会报错并拒绝启动
   ```

---

## 🔄 迁移指南

### 从 v1.1 升级

1. 拉取最新代码
2. 更新依赖: `pip install -r requirements.txt`
3. 检查环境变量是否设置强密钥
4. 重启服务

### 环境变量检查清单

```bash
# 必需（生产环境）
export NN_SECRET_KEY="your-strong-secret-key-at-least-32-chars"
export NN_JWT_SECRET="your-jwt-secret-key-at-least-32-chars"
export NN_DEBUG="false"

# 可选
export NN_DEBUG="true"  # 开发环境允许临时密钥
```
