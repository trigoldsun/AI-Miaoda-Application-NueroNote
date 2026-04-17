# NueroNote — 隐私至上的轻量笔记系统

## 定位

> NueroNote = **轻量 + 隐私优先 + 块级编辑 + 简洁高效**
> 目标：面向公众的免费订阅系统，服务器端**永远不触碰用户明文数据**。

---

## 2026-04-14 新增功能

### 云存储集成
NueroNote 支持将加密笔记同步到三大国内云存储服务商：

| 云服务商 | 认证方式 | 免费额度 | 适合场景 |
|---------|---------|---------|---------|
| 腾讯云COS | AccessKey | 50GB存储 + 10GB/月流量 | 个人/企业，推荐 |
| 阿里云OSS | AccessKey | 30GB存储 | 企业首选 |
| 百度网盘 | OAuth2 | 需要会员 | 个人用户 |

**架构特点：**
- 云存储=额外备份层，不替代本地加密
- vault数据仍然端到端加密，服务商看不到内容
- 支持一键"上传到云"/"从云恢复"
- 自动保存最近100个版本快照

### 审计追踪
- 所有操作均记录审计日志（不可篡改）
- 支持查询：登录/登出/同步/升级/配置变更
- Vault版本快照历史，可随时恢复到任意版本

### API清单
```
# 云存储
GET  /api/v1/cloud/providers     # 服务商说明
GET  /api/v1/cloud/status      # 连接状态
POST /api/v1/cloud/configure    # 配置云存储
POST /api/v1/cloud/sync         # 上传/下载
GET  /api/v1/cloud/versions     # 版本列表
POST /api/v1/cloud/test         # 测试连接
GET  /api/v1/cloud/audit       # 审计日志
GET  /api/v1/cloud/vault-history  # Vault快照历史
POST /api/v1/cloud/vault-restore  # 从快照恢复
```

---

## 设计理念

### 核心理念

1. **隐私即架构**：端到端加密是默认，不是可选项
2. **简洁即力量**：只保留每天都会用到的功能
3. **本地优先**：离线完全可用，联网时才同步
4. **轻盈如风**：不用Electron，不用重型框架，数据量轻到可放在手机里

### 摒弃的功能（华而不实）

| 功能 | 原因 |
|------|------|
| 插件系统 | 大多数用户只用核心功能 |
| 复杂图谱（3D/VR） | 好看不实用，极少人用 |
| 数十种编辑器 | 一个就够了 |
| 内置数据库 | 大多数人不需要 SQL 查询 |
| 多光标协作 | 增加复杂度，用户实际用不上 |
| 主题市场 | 一套好主题就够了 |
| 内置云服务 | 用已有的云存储（S3/Dropbox/坚果云）|

---

## 技术架构

### 客户端架构

```
nueronote_client/
├── index.html              ← 单文件SPA（可离线运行）
├── app.js                  ← 前端逻辑（约1500行）
├── crypto.js               ← 端到端加密（XChaCha20-Poly1305）
├── storage.js             ← IndexedDB本地存储
├── sync.js               ← 增量同步引擎
├── search.js             ← FlexSearch轻量全文搜索
└── sw.js                ← Service Worker离线缓存
```

**技术选型**：
- 前端：原生 JS + HTML5（零框架依赖，约100KB）
- 加密：Web Crypto API（XChaCha20-Poly1305 / AES-GCM）
- 存储：IndexedDB（浏览器本地）
- 搜索：FlexSearch（约4KB）
- 离线：Service Worker

### 服务端架构

```
nueronote_server/
├── app.py                 ← Flask应用（<500行）
├── auth.py                ← JWT认证
├── sync_api.py           ← 增量同步API
├── account.py             ← 账户管理
└── requirements.txt      ← 零第三方依赖
```

**技术选型**：
- Python Flask（极简）
- SQLite（同步存储，用户数据加密隔离）
- Redis（可选，限流用）
- Cloudflare Workers（可部署到边缘节点，$0成本）

### 核心数据结构

```python
# Block（块）— 核心单元
class Block:
    id: str              # nanoid() 唯一ID
    type: str            # paragraph | heading | code | list | quote | callout | math
    content: str          # 明文内容（客户端加密存储）
    children: list[id]   # 子块ID（折叠列表）
    parent_id: str | None # 父块ID
    attrs: dict           # 样式属性（加粗/颜色等）
    created_at: int       # Unix ms
    updated_at: int       # Unix ms

# Document（文档）— 块的容器
class Document:
    id: str              # nanoid()
    title: str            # 文档标题
    root_block_id: str     # 根块ID（包含所有内容）
    tags: list[str]        # 标签
    created_at: int
    updated_at: int

# Sync Record（同步记录）— 增量同步
class SyncRecord:
    id: str               # nanoid()
    user_id: str
    block_id: str
    operation: str         # CREATE | UPDATE | DELETE
    encrypted_content: bytes # 加密后的块内容
    vector_clock: int      # 向量时钟（冲突检测）
    timestamp: int

# User
class User:
    id: str
    email: str            # 不存密码（用 Passkey 或邮箱验证码）
    encrypted_key_check: bytes  # 验证密钥是否正确
    plan: str              # free | pro
    storage_used: int       # bytes
```

---

## 核心功能

### 1. 块级编辑（SiYuan 精髓）

```
- 任意段落 = 一个块
- 每个块有唯一ID
- / 命令菜单（原生实现，不是插件）
  /h1 ~ /h6    标题
  /code         代码块
  /list         列表
  /quote        引用
  /callout      高亮提示框
  /math         LaTeX公式
  /divider      分隔线
  /date         插入日期
  /time         插入时间
  /daily        打开今日日记
```

### 2. 双向链接（Obsidian + 思源融合）

```markdown
[[文档标题]]           ← 文件级链接（Obsidian风格）
((block-id))            ← 块引用（思源风格，双向同步）

效果：
- 输入 [[ 会弹出搜索下拉框
- 链接到不存在的文档 → 自动创建（原子笔记理念）
- 被引用块底部自动显示反链
```

### 3. 端到端加密（隐私核心）

```
用户密码 → Argon2id → 256位密钥
密钥永不发送到服务器！

加密流程：
1. 用户输入密码 → Argon2id(密码, salt) → 主密钥 MK
2. MK → XChaCha20-Poly1305 → 加密每个块的内容
3. 服务器只存储：encrypted_block_data + block_id + vector_clock
4. 服务器永远不知道：用户写了什么

密钥派生：
- 盐（salt）：随机16字节，每次注册时生成
- Argon2id 参数：time=3, memory=64MB, parallelism=4
- 防暴力破解：密码错误则无法解密（可验证 encrypted_key_check）
```

### 4. 增量同步（类似git）

```
每次保存 = 生成一个 SyncRecord
同步只上传差异（delta）
服务器按 vector_clock 检测冲突

冲突处理：
- 同一块被两设备修改 → 提示用户选择保留哪个
- 不自动合并（知识工作不能自动合并）
```

### 5. 闪卡（内置，简洁版）

```markdown
在任意块上：快捷键 Ctrl+Shift+A 制作闪卡

闪卡只存两个块引用：
- 问题块（正面）
- 答案块（背面）

复习：基于遗忘曲线（SM-2简化版）
```

### 6. 每日笔记

```
快捷键 Ctrl+D → 打开/创建今日日记
标题格式：2026-04-13（日历）
模板可自定义
```

### 7. 全文搜索（FlexSearch）

```
Ctrl+Shift+F → 全局搜索
搜索范围：标题 + 内容（已解密后）
结果高亮匹配词
```

### 8. 导出/导入

```
导出：纯 Markdown.zip（无加密，用户掌控）
导入：Markdown文件 → 自动解析并加密存储
```

---

## 功能优先级

### P0（必须，上线即有）

| 功能 | 说明 |
|------|------|
| 块级编辑 | 7种块类型 |
| 双向链接 | [[]] 和 (()) |
| 端到端加密 | Argon2id + XChaCha20 |
| 本地存储 | IndexedDB |
| 增量同步 | 差量上传/下载 |
| 全文搜索 | FlexSearch |
| 每日笔记 | 模板日记 |
| 导出Markdown | 明文导出 |

### P1（重要，30天内）

| 功能 | 说明 |
|------|------|
| 闪卡 | 内置简化版 |
| 标签 | #标签系统 |
| 书签 | 收藏块 |
| 模板 | 可复用笔记模板 |
| 暗色主题 | 护眼模式 |

### P2（增强，90天内）

| 功能 | 说明 |
|------|------|
| 多设备同步 | 最多3设备（free plan） |
| 协作链接分享 | 只读分享链接 |
| 图片存储 | S3/Cloudflare R2 |
| API | 开放API（pro plan） |

---

## 免费订阅模式

### Free Plan（$0）

```
- 存储空间：500MB
- 设备数：1台
- 文档数：无限制
- 块数：无限制
- 闪卡数：500张
- 导出：Markdown
- 加密：端到端（必须）
- 同步：无（本地存储）
```

### Pro Plan（待定，$2-5/月）

```
+ 3设备同步
+ 无限存储
+ 无限闪卡
+ 分享链接（只读）
+ 图片托管
+ API访问
+ 优先支持
```

### 经济模型

```
服务器成本（100万用户）：
- Cloudflare Workers: ~$0（每天1亿请求内免费）
- R2存储: ~$0（1GB/月免费）
- D1数据库: ~$0（每天250万行写入免费）
= 服务器成本 ≈ $0

用户越多，边际成本越低 → 可持续免费模式
```

---

## 用户体验设计

### 界面简洁原则

```
1. 只有一个编辑区（类iA Writer）
2. 侧边栏可折叠（只显示搜索+文档树）
3. 不需要工具栏（快捷键搞定一切）
4. 深色/浅色一键切换
5. 手机端优先设计（80%流量来自手机）
```

### 键盘优先

```
Ctrl+N       新建文档
Ctrl+O       打开文档
Ctrl+S       保存（自动保存，但保留手动）
Ctrl+D       今日日记
Ctrl+[/]     块缩进
Ctrl+Shift+A  制作闪卡
Ctrl+Shift+F  全局搜索
Ctrl+K       插入链接
Ctrl+Shift+K  插入块引用
```

---

## 安全设计

### 隐私保证

```
1. 服务器零知识（Zero-Knowledge）
   → 服务器无法解密任何用户数据

2. 密钥推导在客户端完成
   → 服务器不存明文密钥

3. encrypted_key_check 验证
   → 验证密码正确性，但不泄露密钥

4. 所有通信走 HTTPS
   → 传输过程加密

5. 本地数据用 IndexedDB 存储
   → 关闭浏览器后数据仍在

6. 密码丢失 = 数据无法恢复
   → 明确告知用户（可以导出明文Markdown备份）
```

---

## 竞争对手对比

| 功能 | NueroNote | Obsidian | 思源 | Notion |
|------|---------|---------|------|--------|
| 端到端加密 | ✅ 默认 | ❌ | ❌ | ❌ |
| 块级引用 | ✅ | ❌ | ✅ | ❌ |
| 闪卡内置 | ✅ | ❌ | ✅ | ❌ |
| 重量（Electron） | ❌ | ❌ | ❌ | ✅重 |
| 免费本地用 | ✅离线 | ✅ | ✅ | ❌ |
| 插件生态 | ❌精简 | ✅5000+ | ❌ | ✅ |
| 多设备免费 | 待定 | ❌ | ❌ | ❌ |
| 部署成本 | ≈$0 | N/A | N/A | 贵 |

---

## 开发里程碑

| 阶段 | 内容 | 目标 |
|------|------|------|
| MVP | 块编辑 + 本地存储 + 导出 | 2周 |
| v1.0 | 端到端加密 + 同步API | 1个月 |
| v1.1 | 闪卡 + 搜索 | 6周 |
| v2.0 | 多设备 + 分享链接 | 3个月 |
