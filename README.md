# NueroNote

> 端到端加密笔记同步系统 (E2E Encrypted Note Sync)

## 特性

- 🔐 **端到端加密** - 所有数据在客户端加密，服务端无法访问内容
- ☁️ **多云存储** - 支持阿里云OSS、腾讯云COS、百度网盘
- 🔄 **实时同步** - WebSocket支持毫秒级同步
- 📱 **离线支持** - IndexedDB本地存储，离线后自动同步
- 📱 **PWA** - 支持渐进式Web应用，原生体验
- 📊 **监控告警** - Prometheus指标，健康检查
- 🐳 **容器化** - Docker和Kubernetes支持

## 快速开始

```bash
# 克隆
git clone https://github.com/YOUR_USERNAME/nueronote.git
cd nueronote

# 安装依赖
cd nueronote_server
pip install -r requirements.txt

# 配置环境变量
cp ../.env.example .env
# 编辑.env设置密钥

# 运行
python3 app_modern.py
```

## 项目结构

```
nuero-note/
├── nueronote/              # 客户端加密库
├── nueronote_client/       # 前端静态文件
├── nueronote_server/       # 服务端
│   ├── api/               # API蓝图
│   ├── services/           # 业务服务
│   ├── middleware/         # 中间件
│   ├── db/                # 数据库适配器
│   └── utils/             # 工具函数
├── docs/                  # 文档
└── tests/                # 测试
```

## 部署

详见 [部署指南](docs/DEPLOYMENT.md)

```bash
# Docker部署
docker-compose up -d

# Kubernetes
helm install nueronote ./charts/nueronote
```

## API

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/v1/auth/register` | POST | 注册 |
| `/api/v1/auth/login` | POST | 登录 |
| `/api/v1/vault` | GET/PUT | Vault操作 |
| `/api/v1/sync/push` | POST | 推送同步 |
| `/api/v1/sync/pull` | GET | 拉取同步 |
| `/api/v1/cloud/providers` | GET | 云服务商列表 |

## 安全

- XChaCha20-Poly1305 加密
- Argon2id 密钥派生
- Zero-Knowledge 架构
- JWT令牌认证

## 许可证

MIT License
