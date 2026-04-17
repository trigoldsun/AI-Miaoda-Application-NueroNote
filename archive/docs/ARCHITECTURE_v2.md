# NueroNote 商业化架构 — SPEC v2

> 定位不变：端到端加密 + 块级编辑 + 服务器零知识
> 架构升级：商业级高可用、高安全、高弹性

---

## 一、商业化四座大山

### 1. 高并发（10万~100万并发用户）

| 问题 | 解决 |
|------|------|
| SQLite 无法并发 | PostgreSQL + 连接池（PgBouncer）|
| 服务器单点 | 无状态设计，水平扩展 |
| 数据库扛不住读 | Redis 多级缓存（热点数据）|
| 突发流量 | API Gateway 限流 + 降级 |

### 2. 高存储（PB级，用户数据量大）

| 问题 | 解决 |
|------|------|
| 数据库不适合存 blob | 对象存储（S3/R2/COS），数据库只存索引 |
| 重复内容浪费空间 | 内容寻址存储（CAS），相同内容只存一份 |
| 热点/冷数据混杂 | 分层存储：热(SSD) / 温(SAS) / 冷(OSS归档) |
| 备份成本高 | 增量备份 + 加密快照 |

### 3. 高安全（企业级合规）

| 问题 | 解决 |
|------|------|
| 密钥管理风险 | HSM/KMS 硬件加密，密钥永不泄露 |
| 内部人员攻击 | 零知识架构，服务器无解密能力 |
| 数据泄露 | 传输加密(TLS1.3) + 存储加密(AES-256) |
| 合规审计 | 完整操作审计日志（不可篡改）|
| DDoS/注入 | API Gateway + WAF |

### 4. 高移动互联网化（弱网环境）

| 问题 | 解决 |
|------|------|
| 弱网丢包/断线 | CRDT 离线优先，合并时不丢数据 |
| 同步耗流量 | 块级增量（只传差异），LZFSE 压缩 |
| 重连后大文件卡顿 | 分块上传（断点续传），后台队列 |
| App 安装包大 | 天然优势（纯 Web，PWA ~200KB）|

---

## 二、架构总览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           用户设备层                                      │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐                   │
│  │  Web (PWA)   │  │  iOS App    │  │ Android App  │                   │
│  │  ~200KB      │  │  Flutter    │  │  Flutter     │                   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘                   │
│         │                 │                 │                           │
│  ┌──────▼──────────────────────────────────────────────────────┐        │
│  │               本地加密存储 + CRDT 同步引擎                    │        │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐    │        │
│  │  │加密块  │ │操作日志│ │向量时钟│ │冲突检测│ │压缩传输│    │        │
│  │  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘    │        │
│  └──────────────────────────────────────────────────────────────┘        │
└────────────────────────────┬──────────────────────────────────────────┘
                              │ HTTPS + HTTP/2 + Multiplexing
┌─────────────────────────────▼──────────────────────────────────────────┐
│                          CDN 边缘节点                                     │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Cloudflare / AWS CloudFront / 阿里云CDN                          │  │
│  │  - 静态资源全球缓存                                                │  │
│  │  - DDoS 防护 + WAF                                                │  │
│  │  - 边缘计算（Workers/Edge Functions）                             │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────────────────┐
│                      API Gateway 层                                      │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Kong / AWS API Gateway / 阿里云 API Gateway                       │  │
│  │  - JWT 认证 + 鉴权                                                 │  │
│  │  - 限流（令牌桶/滑动窗口）                                          │  │
│  │  - 请求路由 + 负载均衡                                              │  │
│  │  - 请求/响应压缩（BR/Brotli）                                      │  │
│  │  - 请求校验 + 安全头（CSP/CORS/HSTS）                               │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  同步服务集群  │  │   搜索服务集群   │  │   文件服务集群   │
│ (无状态,水平扩展)│  │ (无状态,水平扩展)│  │ (无状态,水平扩展)│
│  Go:50051     │  │  Go:+Elasticsearch│  │  Go:+S3         │
└───────┬───────┘  └────────┬────────┘  └────────┬────────┘
        │                    │                    │
        └────────────────────┼────────────────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
        ┌──────────┐  ┌────────────┐  ┌──────────┐
        │ PostgreSQL│  │   Redis    │  │ 对象存储  │
        │ 主库+只读 │  │ 集群(3主)  │  │  S3/R2/COS│
        │ 备库      │  │ - 缓存     │  │           │
        └──────────┘  │ - 会话     │  └──────────┘
                       │ - 限流     │
                       │ - 队列     │
                       └────────────┘
```

---

## 三、核心存储设计（高并发 + 高存储）

### 3.1 三层存储架构

```
用户数据流动路径：

  [写入]
  明文块 → AES-256-GCM 加密 → 加密块
                               │
                    内容哈希 (SHA-256)  ← 内容寻址（去重）
                               │
                    ┌──────────┴──────────┐
                    ▼                     ▼
              热数据(SSD)            温数据(SAS)           冷数据(OSS归档)
              90天内活跃             90天~1年              1年以上
              全量索引               元数据索引            只读快照

  [读取]
  缓存优先(Redis LRU) → 热存储 → 温存储 → 冷存储（触发取回）
```

### 3.2 内容寻址存储（CAS）— 节省 60%+ 存储

```
同一个块（如"公司名称"）在 10000 个文档中出现：
  → 只在对象存储中存 1 份！
  → 节省 = 9999 × 平均块大小

实现：
  block_hash = SHA-256(encrypted_content)
  storage_key = "blocks/{year}/{month}/{block_hash}"
  dedup_index = Redis SET（内存中存所有活跃哈希，O(1) 查询）
```

### 3.3 PostgreSQL 表结构（高并发优化）

```sql
-- 用户账户
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  plan TEXT DEFAULT 'free',          -- free | pro | enterprise
  storage_quota BIGINT DEFAULT 536870912,  -- 512MB free
  storage_used BIGINT DEFAULT 0,
  kms_key_id TEXT,                    -- 每个用户的KEK（来自KMS）
  encrypted_vault_check BYTEA,        -- 密钥验证
  vault_version BIGINT DEFAULT 0,     -- 乐观锁版本号
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX users_email ON users(email);

-- Vault 元数据（数据量少，PostgreSQL 完全hold住）
CREATE TABLE vaults (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  latest_version BIGINT DEFAULT 1,
  total_blocks INT DEFAULT 0,
  total_docs INT DEFAULT 0,
  last_sync_at TIMESTAMPTZ,
  UNIQUE(user_id)
);

-- 文档索引（不存内容，只存元数据）
CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  vault_id UUID NOT NULL REFERENCES vaults(id) ON DELETE CASCADE,
  title_encrypted BYTEA,              -- 加密的标题（用于搜索）
  title_hash TEXT,                    -- 确定性加密哈希（可搜索）
  tags_encrypted BYTEA,
  is_daily BOOLEAN DEFAULT false,
  daily_date DATE,                    -- 每日笔记日期
  block_count INT DEFAULT 0,
  size_bytes BIGINT DEFAULT 0,        -- 加密后大小
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  is_deleted BOOLEAN DEFAULT false
);
CREATE INDEX docs_user ON documents(user_id);
CREATE INDEX docs_daily ON documents(user_id, daily_date) WHERE is_daily = true;
CREATE INDEX docs_updated ON documents(user_id, updated_at DESC);

-- 块索引（不存内容，只存引用关系 + 内容寻址哈希）
CREATE TABLE blocks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  doc_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  block_type TEXT,                    -- p | h1 | h2 | h3 | code | quote | callout | math | list
  content_cas_key TEXT,               -- 对象存储中的 key（内容寻址）
  content_hash TEXT,                  -- SHA-256(encrypted_content)，用于去重
  content_size INT,                   -- 加密后字节数
  is_deleted BOOLEAN DEFAULT false,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now(),
  version BIGINT DEFAULT 1            -- 块级别版本号
);
CREATE INDEX blocks_doc ON blocks(doc_id) WHERE NOT is_deleted;
CREATE INDEX blocks_user ON blocks(user_id);
CREATE INDEX blocks_cas ON blocks(content_hash) WHERE content_hash IS NOT NULL;

-- 操作日志（用于增量同步 + 审计 + 事件溯源）
CREATE TABLE operations (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID NOT NULL,
  doc_id UUID,
  block_id UUID,
  op_type TEXT NOT NULL,             -- CREATE | UPDATE | DELETE | SYNC
  op_data JSONB,                    -- 操作详情
  prev_version BIGINT,
  new_version BIGINT,
  device_id TEXT,                    -- 设备标识
  created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ops_user ON operations(user_id, created_at DESC);
CREATE INDEX ops_doc ON operations(doc_id, created_at DESC);
-- 分区表（按月分区，自动清理旧数据）
CREATE INDEX ops_created ON operations(created_at DESC);

-- 审计日志（不可篡改，append-only）
CREATE TABLE audit_logs (
  id BIGSERIAL PRIMARY KEY,
  user_id UUID,
  action TEXT NOT NULL,              -- LOGIN | LOGOUT | SYNC | EXPORT | UPGRADE
  ip_addr INET,
  user_agent TEXT,
  resource_type TEXT,
  resource_id TEXT,
  details JSONB,
  created_at TIMESTAMPTZ DEFAULT now()
) PARTITION BY RANGE (created_at);
-- 按月分区，保留2年
```

### 3.4 对象存储布局（S3/R2/COS）

```
nueronote-bucket/
├── blocks/
│   └── {user_id_prefix}/
│       └── {year}/
│           └── {month}/
│               └── {block_hash_0-3}/
│                   └── {block_hash_4-7}/
│                       └── {block_hash}.enc        ← 加密块内容（内容寻址）
├── attachments/
│   └── {user_id}/
│       └── {doc_id}/
│           └── {attachment_hash}.enc               ← 加密附件
├── backups/
│   └── {user_id}/
│       └── {vault_id}/
│           └── {timestamp}/
│               └── vault_snapshot.enc             ← 加密快照
└── tmp/
    └── {upload_id}/                                ← 分块上传临时文件
```

---

## 四、安全设计（企业级）

### 4.1 密钥层次结构

```
                    ┌─────────────────┐
                    │   根密钥 (HSM)   │
                    │  硬件安全模块    │
                    └────────┬────────┘
                             │ 派生
                    ┌────────▼────────┐
                    │  主密钥 (KMS)    │
                    │  per-tenant KEK │
                    └────────┬────────┘
                             │ 派生
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼────┐  ┌──────▼──────┐  ┌───▼────┐
     │ 用户数据密钥  │  │  备份密钥   │  │  搜索密钥│
     │  (DEK)      │  │  (BEK)     │  │  (SEK) │
     │ 用户独享    │  │  独立派生  │  │ 盲索引 │
     └─────────────┘  └────────────┘  └────────┘

密钥派生链（永不逆转）：
  设备首次注册：
    用户密码 → Argon2id(10万迭代) → 设备主密钥 DMK
    DMK + salt → PBKDF2 → AES-256 数据加密密钥 DEK
    DEK 永远只存在于用户设备内存中！
```

### 4.2 零知识搜索（服务器不解密也能搜）

```
传统方案的问题：
  ❌ 全解密后搜索  → 服务器可看到明文
  ❌ 只搜加密字段  → 无法实现（相同词产生相同密文=泄露信息）

NueroNote 方案：Blind Index（盲索引）+ Bloom Filter

  客户端：
  1. 内容分词（tokenize）
  2. 每个 token → SHA-256 → 取前16位 = Bloom bit
  3. 多个 token 的 bit OR = Blind Index（加密字段）
  4. Blind Index 和 加密内容 一起上传

  服务端（看不到明文）：
  - Blind Index 存 PostgreSQL（可搜索）
  - 加密内容存对象存储（无法搜索）
  - 搜索时：查询词 → 同样算法算 Blind Index → 匹配结果返回
  - 命中的 document_id 列表返回给客户端 → 客户端解密验证

安全性：
  - 服务端不知道具体词，只知道"存在某个词"
  - Bloom Filter 有假阳性率（约1%），需客户端二次验证
  - 无法枚举所有文档内容
```

### 4.3 三因素认证

```
注册/登录：
  1. 邮箱 + 密码（主密钥来源）
  2. TOTP（Google Authenticator）— 可选，Pro默认开启
  3. Passkey（WebAuthn）— 未来支持，指纹/面容登录

会话管理：
  - Access Token：JWT，15分钟有效，存内存
  - Refresh Token：7天有效，HttpOnly Cookie
  - Refresh Token 轮换：每次刷新颁发新的，旧的可信设备列表
  - 设备管理：每个设备有唯一 device_id，可远程吊销
```

### 4.4 安全审计

```
所有操作均记录，不可篡改：
  账户：注册 / 登录 / 登出 / 改密码 / 升级套餐
  数据：创建文档 / 删除文档 / 同步 / 导出
  权限：邀请协作者 / 撤销权限
  计费：升级 / 降级 / 取消

告警规则（自动触发）：
  - 1小时内5次登录失败 → 锁定账户 + 邮件通知
  - 单用户1分钟内100+同步请求 → 限流
  - 检测到异常IP访问 → 标记并通知
```

---

## 五、同步引擎（高移动互联网 + 冲突处理）

### 5.1 同步协议设计

```
核心：Operational Transformation + CRDT 融合

客户端维护：
  ┌─────────────────────────────────────────────┐
  │ 本地状态                                      │
  │  · pending_ops[]   待发送的操作队列           │
  │  · synced_version   已同步的最新版本号         │
  │  · local_clock      本地向量时钟               │
  │  · server_clock     服务端向量时钟             │
  └─────────────────────────────────────────────┘

同步流程（增量，类 git push/pull）：
  1. 客户端收集 pending_ops（本地未同步操作）
  2. 发送：last_synced_version + pending_ops[]
  3. 服务端：
     a. 按时间顺序 replay 所有 op
     b. 检测冲突（同一 block 被不同设备修改）
     c. 冲突 → 写入冲突日志，返回 conflict_list
     d. 无冲突 → 更新数据库，返回 new_version
  4. 客户端收到响应：
     a. 已确认的 op 从 pending_ops 移除
     b. 冲突 → 展示给用户（3选项：保留本地/服务端/手动合并）
     c. 拉取服务端新操作 → 本地 apply
```

### 5.2 冲突处理策略

```
冲突类型与处理：

类型1：同一块被两设备修改
  → 策略：类似 git，提示用户手动选择
  → 展示：左右对比视图 + 合并编辑器

类型2：块被设备A删除，设备B修改了它
  → 策略：保留删除（安全优先），存入"删除回收站"30天

类型3：文档被删除，但有未同步的新块
  → 策略：自动恢复文档，新块合并进去

CRDT 保证（不会丢数据）：
  · 操作是幂等的（重复apply不影响结果）
  · 操作交换律（不同设备操作顺序无关）
  · 指针引用用 Logical Timestamp，不怕网络延迟
```

### 5.3 流量优化

```
压缩策略：
  · 请求体：LZ4（速度优先）或 Brotli（压缩率优先）
  · 加密块：整体 AES-GCM 后再压缩（压不掉加密特征，但metadata可压）
  · 分块上传：大文件（>5MB）分 1MB 块，断点可续

离线队列（类 git stash）：
  1. 用户在地铁里写了几十块内容
  2. 全部存本地 operation log
  3. 联网后自动按顺序同步
  4. 冲突率：地铁场景下 < 0.1%（写不同块）

移动网络感知：
  · WiFi：全量同步 + 后台预取（用户常用文档）
  · 4G：仅关键文档同步，延迟非关键同步
  · 2G/离线：完全本地，队列等待
```

---

## 六、多租户隔离（高安全 + 成本分摊）

```
每个用户的数据严格隔离：

物理隔离（Enterprise）：
  · 独立数据库实例
  · 独立加密密钥
  · 独享计算资源

逻辑隔离（Free/Pro）：
  · PostgreSQL Row-Level Security (RLS)
  · 所有查询自动加上 user_id = current_user
  · 即使 SQL 注入也无法跨用户访问

配额管理：
  ┌──────────┬───────────┬────────────┬──────────────┐
  │ 套餐      │ 存储空间  │ 设备数      │ 同步带宽     │
  ├──────────┼───────────┼────────────┼──────────────┤
  │ Free     │ 512MB     │ 1台        │ 无限制       │
  │ Pro      │ 10GB      │ 3台        │ 无限制       │
  │ Team     │ 100GB/人  │ 无限       │ 无限        │
  │ Enterprise│ 无限     │ 无限       │ 无限        │
  └──────────┴───────────┴────────────┴──────────────┘

配额检查（原子操作，防超卖）：
  UPDATE users
  SET storage_used = storage_used + $new_size
  WHERE id = $user_id
    AND storage_used + $new_size <= storage_quota
  RETURNING id;
  -- 如果返回空，说明配额不足，拒绝写入
```

---

## 七、技术选型总结

### 服务端

| 组件 | 选型 | 原因 |
|------|------|------|
| 核心框架 | Go（golang）| 高并发，编译型快，部署简单 |
| API 协议 | gRPC + REST | gRPC 高效，REST 兼容 |
| 主数据库 | PostgreSQL 16 | JSONB 支持，RLS 安全，成熟稳定 |
| 连接池 | PgBouncer | 超高并发连接复用 |
| 缓存 | Redis Cluster | 3主模式，高可用 |
| 对象存储 | S3 / R2 / COS | 按量付费，弹性扩容 |
| 搜索引擎 | Elasticsearch | 盲索引搜索，横向扩展 |
| 消息队列 | Redis Streams | 异步任务，后台同步 |
| 密钥管理 | AWS KMS / 阿里云 KMS | HSM 硬件加密 |
| CDN | Cloudflare / 阿里云CDN | 全球加速，DDoS防护 |
| 容器编排 | Kubernetes (EKS/ACK) | 自动扩缩容，自愈 |
| 监控 | Prometheus + Grafana | 可观测性 |
| 日志 | Loki / ELK | 结构化日志 |

### 客户端

| 组件 | 选型 |
|------|------|
| Web | 原生 JS + HTML5（约200KB）|
| iOS | Flutter（约3MB）|
| Android | Flutter（约3MB）|
| 加密 | Web Crypto API / libsodium |
| 本地存储 | IndexedDB + SQLite（移动端）|
| 搜索 | FlexSearch（Web）/ SQLite FTS（移动端）|
| 同步 | CRDT（自发明的简化版）|
| 网络 | HTTP/2 + LZFSE 压缩 |

---

## 八、成本模型（100万用户）

```
服务器月成本（估算）：

基础架构：
  · Kubernetes 托管（3个区域，各3节点）：
    AWS EKS: 3 × 3 × $0.1/hr = $216/月（小型）
  · PostgreSQL RDS (db.r6g.large): $150/月
  · Redis Cluster (3 × cache.r6g.large): $135/月
  · 对象存储 S3: 假设平均 1GB/人 × 100万用户 = 1PB
    S3 成本: $0.023/GB = $23,000/月 ← 太高！
  → 优化：90%用户用 Free（512MB）= 450TB，热数据 10%
    实际 S3 成本: $450,000GB × $0.023 = $10,350/月

架构优化后（S3 冷热分层）：
  · 热存储 (50GB × 100万免费用户 = 50TB): $1,150/月
  · 温存储 (200GB × 活跃用户10万 = 20TB): $460/月
  · 冷存储 (剩余): $460/月
  · 合计: ~$2,100/月

CDN + 流量:
  · Cloudflare Pro: $20/月/域名
  · 出口流量: 1PB × $0.08/GB = $80,000/月 ← 必须优化！
  → 优化：压缩 + 增量同步，实际人均带宽 ~50MB/月
    100万用户 × 50MB = 50TB = $4,000/月

总成本：
  · 基础设施: ~$2,200/月
  · CDN + 流量: ~$4,200/月
  · 监控/日志: ~$500/月
  · 总计: ~$6,900/月

收入覆盖：
  · 如果 1% 用户付费 Pro（$5/月）= 10,000 × $5 = $50,000/月
  · 利润率: (50000 - 6900) / 50000 = 86%
```

---

## 九、项目结构（v2）

```
nueronote/
├── SPEC.md                          ← 架构规格文档
├── docs/
│   ├── ARCHITECTURE_v2.md            ← 本文档
│   └── DEPLOYMENT.md                 ← 部署指南
│
├── nueronote_client/                 ← Web 客户端
│   ├── index.html                   ← 单文件 SPA
│   ├── sw.js                        ← Service Worker
│   └── manifest.json                 ← PWA 配置
│
├── nueronote_mobile/                 ← 移动端（Flutter）
│   ├── lib/
│   │   ├── main.dart
│   │   ├── crypto/                  ← 加密模块
│   │   ├── sync/                    ← 同步引擎
│   │   ├── storage/                 ← SQLite 本地存储
│   │   └── ui/                      ← Flutter 界面
│   └── pubspec.yaml
│
├── nueronote_server/                 ← Go 后端
│   ├── cmd/
│   │   └── server/
│   │       └── main.go              ← 入口
│   ├── internal/
│   │   ├── api/
│   │   │   ├── auth.go              ← 认证 API
│   │   │   ├── sync.go             ← 同步 API
│   │   │   ├── search.go           ← 搜索 API
│   │   │   └── vault.go            ← Vault API
│   │   ├── auth/
│   │   │   ├── jwt.go              ← JWT 实现
│   │   │   └── totp.go             ← TOTP
│   │   ├── crypto/
│   │   │   └── server_encrypt.go   ← 服务端辅助加密（Blind Index）
│   │   ├── storage/
│   │   │   ├── postgres.go         ← PostgreSQL
│   │   │   ├── redis.go            ← Redis
│   │   │   └── s3.go              ← S3 对象存储
│   │   ├── sync/
│   │   │   ├── engine.go           ← 同步引擎
│   │   │   └── conflict.go        ← 冲突处理
│   │   └── audit/
│   │       └── logger.go           ← 审计日志
│   ├── migrations/                  ← PostgreSQL DDL
│   └── go.mod
│
└── infra/                           ← 基础设施即代码
    ├── terraform/
    │   ├── main.tf                 ← AWS 资源
    │   ├── postgres.tf
    │   ├── redis.tf
    │   ├── s3.tf
    │   └── ecs.tf
    └── kubernetes/
        ├── deployment.yaml
        ├── service.yaml
        └── ingress.yaml
```

---

## 十、与 v1 的关键差异

| 维度 | v1 (MVP) | v2 (商业化) |
|------|---------|------------|
| 服务端 | Flask 单机 | Go 分布式 |
| 数据库 | SQLite | PostgreSQL + PgBouncer |
| 存储 | SQLite 内 | 对象存储 + PostgreSQL |
| 同步 | 简单 delta | CRDT + Operational Transform |
| 密钥 | 客户端单层 | HSM→KMS→DEK 三层 |
| 搜索 | 客户端 | 盲索引 + Elasticsearch |
| 移动 | 无 | Flutter 跨平台 |
| 部署 | 单机 | Kubernetes 多区域 |
| 成本 | $0 | ~$7000/月（100万用户）|
