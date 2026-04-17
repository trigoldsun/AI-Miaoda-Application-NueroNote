# NueroNote 部署指南

## 目录
1. [快速开始](#快速开始)
2. [Docker部署](#docker部署)
3. [Kubernetes部署](#kubernetes部署)
4. [生产环境配置](#生产环境配置)
5. [数据库迁移](#数据库迁移)
6. [监控和运维](#监控和运维)
7. [备份和恢复](#备份和恢复)

---

## 快速开始

### 环境要求
- Python 3.11+
- PostgreSQL 16 (生产环境)
- Redis 7 (可选，用于缓存)
- Nginx (可选，反向代理)

### 开发环境
```bash
# 克隆代码
git clone https://github.com/your-repo/nueronote.git
cd nueronote

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r nueronote_server/requirements.txt

# 设置环境变量
cp .env.example .env
# 编辑.env设置密钥

# 初始化数据库
python3 nueronote_server/migrate.py upgrade

# 运行开发服务器
python3 nueronote_server/app_modern.py
```

---

## Docker部署

### 单容器部署
```bash
# 构建镜像
docker build -t nueronote:latest .

# 运行容器
docker run -d \
  --name nueronote \
  -p 5000:5000 \
  -e NN_SECRET_KEY=your-secret-key \
  -e NN_JWT_SECRET=your-jwt-secret \
  -e DATABASE_URL=postgresql://user:pass@host:5432/nueronote \
  -v nueronote_data:/data \
  nueronote:latest
```

### Docker Compose 部署（推荐）
```bash
# 启动所有服务
docker-compose up -d

# 查看服务状态
docker-compose ps

# 查看日志
docker-compose logs -f app
```

---

## Kubernetes部署

### Helm部署
```bash
# 添加Helm仓库
helm repo add nueronote https://charts.nueronote.app
helm repo update

# 安装
helm install nueronote nueronote/nueronote \
  --set secretKey=your-secret-key \
  --set jwtSecret=your-jwt-secret \
  --set database.url=postgresql://postgres:password@postgres-svc:5432/nueronote
```

### 手动部署
```bash
# 应用配置
kubectl apply -f k8s/

# 检查状态
kubectl get pods -l app=nueronote
```

---

## 生产环境配置

### 环境变量
```bash
# 必需
NN_SECRET_KEY=<32字符随机字符串>
NN_JWT_SECRET=<32字符随机字符串>
DATABASE_URL=postgresql://user:pass@host:5432/nueronote

# 数据库
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=40

# Redis (可选)
REDIS_ENABLED=true
REDIS_URL=redis://redis:6379/0

# 存储
STORAGE_TYPE=local  # 或 oss, s3, gcs
STORAGE_PATH=/data/storage

# 安全
CORS_ORIGINS=https://app.nueronote.com
RATE_LIMIT_ENABLED=true

# 监控
PROMETHEUS_ENABLED=true
```

### Nginx配置
```nginx
upstream nueronote {
    server localhost:5000;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name app.nueronote.com;

    ssl_certificate /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;

    # Gzip压缩
    gzip on;
    gzip_types application/json text/plain text/css;
    gzip_min_length 1000;

    # 安全头
    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-Content-Type-Options "nosniff";
    add_header X-XSS-Protection "1; mode=block";

    location / {
        proxy_pass http://nueronote;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Connection "";

        # 超时设置
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # WebSocket支持
    location /socket.io {
        proxy_pass http://nueronote;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## 数据库迁移

### 开发环境
```bash
# 创建迁移
python3 nueronote_server/migrate.py create "add_new_table"

# 升级
python3 nueronote_server/migrate.py upgrade

# 回滚
python3 nueronote_server/migrate.py downgrade

# 查看状态
python3 nueronote_server/migrate.py status
```

### 生产环境
```bash
# 1. 备份数据库
pg_dump -h localhost -U postgres nueronote > backup.sql

# 2. 运行迁移（滚动更新期间自动处理）
kubectl exec -it nueronote-deployment-xxx -- python3 migrate.py upgrade

# 3. 验证
python3 nueronote_server/migrate.py status
```

---

## 监控和运维

### Prometheus指标
```bash
# 获取指标
curl http://localhost:5000/metrics

# 关键指标
- nueronote_http_requests_total
- nueronote_http_request_duration_seconds
- nueronote_active_users
- nueronote_sync_operations_total
```

### Grafana仪表板
```yaml
# 导入仪表板JSON
apiVersion: 1
providers:
  - name: 'NueroNote'
    folder: 'Applications'
    type: file
    options:
      path: /var/lib/grafana/dashboards
```

### 健康检查
```bash
# 应用健康
curl http://localhost:5000/health

# 完整健康检查（含依赖）
curl http://localhost:5000/health/detailed
```

---

## 备份和恢复

### 自动备份
```bash
#!/bin/bash
# backup.sh

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR=/backups

# 数据库备份
pg_dump -h $DB_HOST -U $DB_USER nueronote | gzip > $BACKUP_DIR/db_$DATE.sql.gz

# 保留策略（保留7天）
find $BACKUP_DIR -name "*.sql.gz" -mtime +7 -delete

# 上传到对象存储
aws s3 cp $BACKUP_DIR/db_$DATE.sql.gz s3://bucket/backups/
```

### 恢复
```bash
# 停止服务
docker-compose down

# 恢复数据库
gunzip < backup.sql.gz | psql -h localhost -U postgres nueronote

# 启动服务
docker-compose up -d
```

---

## 故障排查

### 常见问题

**1. 数据库连接失败**
```bash
# 检查连接
psql -h $DB_HOST -U $DB_USER -d nueronote

# 查看日志
docker-compose logs db
```

**2. 内存不足**
```bash
# 查看资源使用
docker stats

# 调整连接池
DB_POOL_SIZE=10
```

**3. 性能问题**
```bash
# 启用慢查询日志
SET log_min_duration_statement = 1000;

# 分析慢查询
EXPLAIN ANALYZE SELECT * FROM users WHERE id = 'xxx';
```

---

## 联系支持

- 文档: https://docs.nueronote.app
- 问题反馈: https://github.com/your-repo/nueronote/issues
- 邮件: support@nueronote.app
