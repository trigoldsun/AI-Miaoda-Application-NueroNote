# NueroNote Python 架构 — 实际实现

> 基于Python的端到端加密笔记系统
> 实际实现架构（与文档v2保持一致但使用Python技术栈）

---

## 一、技术选型（Python栈）

### 服务端
| 组件 | 选型 | 原因 |
|------|------|------|
| Web框架 | Flask 3.0+ | 轻量级，快速开发，社区成熟 |
| 数据库 | SQLite 3.37+（开发）/ PostgreSQL 16（生产） | SQLite简化开发，PostgreSQL生产就绪 |
| 数据库ORM | SQLAlchemy 2.0（可选） | 类型安全，连接池，迁移支持 |
| 配置管理 | Pydantic Settings | 类型安全，环境变量验证 |
| 加密库 | cryptography / PyNaCl | 行业标准，安全可靠 |
| 异步任务 | Celery + Redis（可选） | 后台任务处理 |
| API文档 | OpenAPI 3.0 + Swagger UI | 自动生成API文档 |
| 容器化 | Docker + Docker Compose | 一致部署环境 |

### 客户端
| 组件 | 选型 |
|------|------|
| Web前端 | Vanilla JS + Web Crypto API | 无框架依赖，体积小 |
| 移动端 | Flutter（未来） | 跨平台，性能好 |
| 加密 | Web Crypto API / libsodium.js | 浏览器原生加密 |

### 云存储（优先阿里云）
| 服务商 | 优先级 | 原因 |
|--------|--------|------|
| 阿里云盘 | 1 | API完善，OAuth2，个人免费额度 |
| 百度网盘 | 2 | 已有适配器，OAuth2 |
| 阿里云OSS | 3 | 对象存储，适合生产环境 |

---

## 二、架构总览（Python实现）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           客户端层                                         │
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
                              │ HTTPS + HTTP/2
┌─────────────────────────────▼──────────────────────────────────────────┐
│                        Python Flask 服务端                               │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │  Flask App (Gunicorn/Uvicorn workers)                            │  │
│  │  - JWT 认证 + 鉴权                                                │  │
│  │  - 请求验证 + 输入清洗                                            │  │
│  │  - 业务逻辑处理                                                   │  │
│  │  - 审计日志记录                                                   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌───────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   SQLite/     │  │      Redis      │  │    对象存储      │
│   PostgreSQL  │  │  (缓存/队列)     │  │  (阿里云OSS)     │
│   主数据库     │  │                 │  │                 │
└───────────────┘  └─────────────────┘  └─────────────────┘
```

---

## 三、模块结构（重构后）

```
nueronote_server/
├── __init__.py
├── app.py                      # Flask应用工厂
├── config/                     # 配置管理
│   ├── __init__.py
│   ├── settings.py            # 主配置
│   └── validators.py          # 配置验证
├── database/                   # 数据库层
│   ├── __init__.py
│   ├── connection.py          # 数据库连接池
│   ├── models.py              # SQLAlchemy模型
│   ├── repositories.py        # 数据访问对象
│   └── migrations/            # 数据库迁移
├── api/                       # API层
│   ├── __init__.py
│   ├── auth.py               # 认证API
│   ├── vault.py              # Vault操作API
│   ├── sync.py               # 同步API
│   ├── cloud.py              # 云存储API
│   └── middleware.py         # API中间件
├── services/                  # 业务逻辑层
│   ├── __init__.py
│   ├── auth_service.py       # 认证服务
│   ├── vault_service.py      # Vault服务
│   ├── sync_service.py       # 同步服务
│   ├── cloud_service.py      # 云存储服务
│   └── encryption_service.py # 加密服务
├── models/                    # 领域模型
│   ├── __init__.py
│   ├── user.py               # 用户模型
│   ├── vault.py              # Vault模型
│   ├── document.py           # 文档模型
│   └── cloud_config.py       # 云配置模型
├── utils/                     # 工具函数
│   ├── __init__.py
│   ├── crypto.py             # 加密工具
│   ├── validation.py         # 输入验证
│   ├── logging.py            # 日志配置
│   └── error_handling.py     # 错误处理
├── cloud/                     # 云存储适配器
│   ├── __init__.py
│   ├── base.py               # 抽象基类
│   ├── aliyunpan.py          # 阿里云盘
│   ├── baidu_netdisk.py      # 百度网盘
│   └── aliyun_oss.py         # 阿里云OSS
└── tests/                     # 测试
    ├── unit/
    ├── integration/
    └── fixtures/
```

---

## 四、核心设计原则

### 4.1 分层架构
- **API层**：仅处理HTTP请求/响应，输入验证，错误格式化
- **服务层**：业务逻辑，事务管理，权限检查
- **数据层**：数据库访问，缓存，对象存储
- **领域层**：业务实体，值对象，领域逻辑

### 4.2 安全设计
- **端到端加密**：客户端加密，服务端只存储密文
- **密钥管理**：主密钥源自用户密码（Argon2id派生）
- **零知识架构**：服务端无法解密用户数据
- **输入验证**：所有输入必须验证和清洗
- **SQL注入防护**：100%参数化查询
- **JWT认证**：短期访问令牌 + 长期刷新令牌

### 4.3 错误处理
- **结构化错误响应**：统一错误格式
- **异常分类**：业务异常 vs 系统异常
- **错误日志**：记录上下文便于调试
- **用户友好消息**：不泄露系统细节

### 4.4 配置管理
- **环境变量优先**：12-factor应用原则
- **类型安全**：Pydantic验证配置类型
- **多环境支持**：开发、测试、生产
- **密钥管理**：环境变量或密钥管理服务

---

## 五、数据库设计（SQLite/PostgreSQL兼容）

### 5.1 核心表结构
```sql
-- 用户表
CREATE TABLE users (
    id UUID PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    plan VARCHAR(20) DEFAULT 'free',
    storage_quota BIGINT DEFAULT 536870912,
    storage_used BIGINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Vault表（加密存储）
CREATE TABLE vaults (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1,
    encrypted_data TEXT NOT NULL,  -- 加密的vault JSON
    signature TEXT NOT NULL,       -- 数据签名
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, version)
);

-- 操作日志（增量同步）
CREATE TABLE operations (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    operation_type VARCHAR(50) NOT NULL,
    encrypted_payload TEXT NOT NULL,
    vector_clock BIGINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 审计日志
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID,
    action VARCHAR(100) NOT NULL,
    ip_address INET,
    user_agent TEXT,
    details JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 5.2 索引优化
```sql
-- 用户相关索引
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_created ON users(created_at DESC);

-- Vault相关索引
CREATE INDEX idx_vaults_user ON vaults(user_id);
CREATE INDEX idx_vaults_version ON vaults(version DESC);

-- 操作日志索引
CREATE INDEX idx_ops_user ON operations(user_id);
CREATE INDEX idx_ops_clock ON operations(user_id, vector_clock DESC);

-- 审计日志索引（分区友好）
CREATE INDEX idx_audit_user ON audit_logs(user_id);
CREATE INDEX idx_audit_time ON audit_logs(created_at DESC);
```

---

## 六、API设计

### 6.1 RESTful API规范
```
# 认证
POST   /api/v1/auth/register     # 注册
POST   /api/v1/auth/login        # 登录
POST   /api/v1/auth/refresh      # 刷新令牌
POST   /api/v1/auth/logout       # 登出

# Vault操作
GET    /api/v1/vault             # 获取当前vault
PUT    /api/v1/vault             # 更新vault
GET    /api/v1/vault/versions    # 获取历史版本
GET    /api/v1/vault/{version}   # 获取特定版本

# 同步
GET    /api/v1/sync/operations   # 获取未同步操作
POST   /api/v1/sync/operations   # 提交操作
PUT    /api/v1/sync/ack          # 确认同步

# 云存储
GET    /api/v1/cloud/config      # 获取云配置
PUT    /api/v1/cloud/config      # 更新云配置
POST   /api/v1/cloud/sync        # 触发云同步
GET    /api/v1/cloud/status      # 获取云同步状态
```

### 6.2 请求/响应格式
```json
// 成功响应
{
  "success": true,
  "data": { /* 业务数据 */ },
  "meta": {
    "version": "1.0",
    "timestamp": "2026-04-14T08:00:00Z"
  }
}

// 错误响应
{
  "success": false,
  "error": {
    "code": "INVALID_TOKEN",
    "message": "访问令牌无效",
    "details": { /* 可选详细信息 */ }
  },
  "meta": {
    "version": "1.0",
    "timestamp": "2026-04-14T08:00:00Z"
  }
}
```

---

## 七、部署架构

### 7.1 开发环境
```
# Docker Compose
version: '3.8'
services:
  nueronote:
    build: .
    ports:
      - "5000:5000"
    environment:
      - FLUX_ENV=development
      - FLUX_DB=postgresql://postgres:password@db/nueronote
    depends_on:
      - db
      - redis
  
  db:
    image: postgres:16
    environment:
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=nueronote
  
  redis:
    image: redis:7-alpine
```

### 7.2 生产环境（阿里云）
```
阿里云服务：
  - ECS (Elastic Compute Service): Flask应用
  - RDS (Relational Database Service): PostgreSQL
  - Redis: 阿里云Redis
  - OSS (Object Storage Service): 文件存储
  - SLB (Server Load Balancer): 负载均衡
  - WAF (Web Application Firewall): 安全防护
```

### 7.3 监控与日志
- **应用日志**：结构化JSON日志，ELK收集
- **性能监控**：Prometheus + Grafana
- **错误追踪**：Sentry
- **健康检查**：/health端点，负载均衡器探测

---

## 八、迁移计划（从当前代码）

### 第一阶段（已完成）
- [x] 修复硬编码安全问题
- [x] 创建配置管理模块
- [x] 创建输入验证模块
- [x] 创建测试框架
- [x] 创建数据库抽象层

### 第二阶段（进行中）
- [ ] 拆分app.py为模块化结构
- [ ] 引入SQLAlchemy ORM
- [ ] 实现统一错误处理
- [ ] 添加结构化日志
- [ ] 完善API文档

### 第三阶段（待进行）
- [ ] 实现CRDT同步引擎
- [ ] 添加后台任务队列
- [ ] 集成阿里云OSS
- [ ] 实现多租户隔离
- [ ] 性能优化和压力测试

---

## 九、质量保证

### 代码质量
- **代码规范**：black格式化，isort排序，flake8检查
- **类型提示**：100%类型注解，mypy检查
- **测试覆盖**：单元测试 > 80%，集成测试关键路径
- **安全扫描**：bandit安全扫描，依赖漏洞检查

### 部署质量
- **CI/CD**：GitHub Actions自动化测试和部署
- **容器安全**：非root用户，最小化镜像
- **秘密管理**：环境变量或密钥管理服务
- **备份策略**：数据库自动备份，加密快照

---

## 十、总结

当前NueroNote实现已经具备核心功能，但架构和代码质量需要优化。本架构文档提供了基于Python的实际实现方案，重点解决：

1. **架构清晰**：分层设计，模块分离
2. **安全加固**：输入验证，SQL注入防护，密钥管理
3. **代码质量**：类型安全，测试覆盖，错误处理
4. **生产就绪**：配置管理，日志监控，部署方案

通过逐步实施本架构，NueroNote将从原型阶段升级为生产就绪的应用，同时保持Python的技术栈优势。

**最后更新**：2026-04-14
