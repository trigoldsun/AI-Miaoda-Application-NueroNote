# NueroNote Architecture Documentation

**Version:** 2.0.0  
**Date:** 2026-04-17  
**Author:** Hermes Agent  
**Status:** Commercial-Ready

---

## 1. System Overview

### 1.1 Product Description

NueroNote is a zero-knowledge, privacy-first note synchronization application designed for commercial deployment. It enables users to securely store, sync, and manage notes across devices with end-to-end encryption.

### 1.2 Tech Stack

| Layer | Technology | Rationale |
|-------|------------|-----------|
| **Backend** | Python Flask | Lightweight, ~400 LOC, minimal dependencies |
| **Frontend** | Vanilla HTML/JS (Static) | No build step, CDN-friendly, fast loading |
| **Database** | PostgreSQL | Mature, reliable, JSONB support for flexible schemas |
| **Cache** | Redis | Best performance, mature ecosystem |
| **Object Storage** | S3/OSS | Pay-per-use, elastic scaling |
| **Container Registry** | Alibaba Cloud ACR | `registry.cn-shanghai.aliyuncs.com/nueronote` |
| **Orchestration** | Alibaba Cloud ACK | Managed Kubernetes, high availability |
| **GitOps** | ArgoCD | GitOps synchronization |
| **CI/CD** | GitHub Actions | GitOps pipeline automation |

### 1.3 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Client Layer                                   │
│  ┌─────────────────────┐    ┌─────────────────────┐                         │
│  │   Web Client        │    │   Mobile Client     │                         │
│  │   (Static HTML/JS)  │    │   (Future)          │                         │
│  └──────────┬──────────┘    └──────────┬──────────┘                         │
│             │                          │                                     │
│             └────────────┬─────────────┘                                     │
│                          │ HTTPS (TLS 1.3)                                   │
├──────────────────────────┼──────────────────────────────────────────────────┤
│                          ▼                                                   │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    Alibaba Cloud SLB / CDN                           │    │
│  │              api.nueronote.com  |  app.nueronote.com                 │    │
│  └────────────────────────────────┬────────────────────────────────────┘    │
│                                   │                                          │
├───────────────────────────────────┼──────────────────────────────────────────┤
│                                   ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                    Kubernetes Cluster (ACK)                          │    │
│  │                                                                       │    │
│  │   ┌─────────────────┐      ┌─────────────────┐                       │    │
│  │   │  Flask Backend  │      │  Nginx Frontend │                       │    │
│  │   │  (Backend Pod)  │◀────▶│  (Frontend Pod) │                       │    │
│  │   │  Port: 8080     │      │  Port: 80       │                       │    │
│  │   └────────┬────────┘      └────────┬────────┘                       │    │
│  │            │                        │                                │    │
│  │            └──────────┬─────────────┘                                │    │
│  │                     │                                                  │    │
│  │            ┌────────▼────────┐                                        │    │
│  │            │   Redis Cache   │                                        │    │
│  │            │   nueronote-    │                                        │    │
│  │            │   cache.internal│                                        │    │
│  │            └────────┬────────┘                                        │    │
│  │                     │                                                  │    │
│  │            ┌────────▼────────┐                                        │    │
│  │            │  PostgreSQL     │                                        │    │
│  │            │  nueronote-    │                                        │    │
│  │            │  db.internal    │                                        │    │
│  │            └─────────────────┘                                        │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                    Monitoring & Observability                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ Prometheus  │  │  Grafana    │  │ ArgoCD      │  │ Alibaba     │         │
│  │ (Metrics)   │  │ (Dashboards)│  │ (GitOps)   │  │ SLS/ARMS   │         │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘         │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Component Specifications

### 2.1 Backend (Python Flask)

| Property | Value |
|----------|-------|
| Language | Python 3.11 |
| Framework | Flask |
| Port | 8080 |
| Health Check | `GET /health` |
| Metrics | `GET /metrics` (Prometheus format) |
| Replicas (Prod) | 2-10 (HPA) |
| Memory Limit | 512Mi |
| CPU Limit | 500m |

**Security Features:**
- JWT Authentication (HMAC-SHA256)
- Optimistic Lock Version Control
- Storage Quota Enforcement
- Request Body Size Limit (DoS prevention)
- Account Lockout (Brute Force Protection)
- Audit Logging (All Write Operations)
- CORS Security Configuration

### 2.2 Frontend (Static HTML/JS)

| Property | Value |
|----------|-------|
| Type | Vanilla HTML/JS (No build step) |
| Port | 80 (nginx:alpine) |
| Replicas (Prod) | 2-5 (HPA) |
| Memory Limit | 128Mi |
| CPU Limit | 200m |

### 2.3 Database Layer

| Property | Value |
|----------|-------|
| Engine | PostgreSQL 15 |
| Host | nueronote-db.internal |
| Port | 5432 |
| Extensions | UUID, JSONB, Vector |

### 2.4 Cache Layer

| Property | Value |
|----------|-------|
| Engine | Redis 7 |
| Host | nueronote-cache.internal |
| Port | 6379 |

---

## 3. Deployment Architecture

### 3.1 Kubernetes Resources

| Resource | Namespace | Count |
|----------|-----------|-------|
| Namespace | nueronote, nueronote-dev, nueronote-staging, nueronote-prod | 4 |
| Deployment | nueronote-backend, nueronote-frontend | Per namespace |
| Service | nueronote-backend, nueronote-frontend | Per namespace |
| HPA | nueronote-backend-hpa, nueronote-frontend-hpa | Per namespace |
| Ingress | nueronote-ingress | Per namespace |
| NetworkPolicy | nueronote-network-policy | Per namespace |
| ResourceQuota | nueronote-quota | Per namespace |
| LimitRange | nueronote-limit | Per namespace |

### 3.2 Container Registry

| Image | Registry | Tag Strategy |
|-------|----------|--------------|
| Backend | `registry.cn-shanghai.aliyuncs.com/nueronote/backend` | `sha-{commit}`, `latest` |
| Frontend | `registry.cn-shanghai.aliyuncs.com/nueronote/frontend` | `sha-{commit}`, `latest` |

### 3.3 Environment Overlays

| Environment | Replicas (Backend) | Replicas (Frontend) | Log Level |
|-------------|-------------------|---------------------|-----------|
| dev | 1 | 1 | debug |
| staging | 2 | 2 | info |
| prod | 5 | 3 | warn |

---

## 4. CI/CD Pipeline

### 4.1 GitHub Actions Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `CI Pipeline` | Push/PR to main, staging, develop | Lint, Test, Build, Security Scan |
| `CD Deployment` | CI success or manual dispatch | Deploy to dev/staging/prod |

### 4.2 CI Pipeline Stages

```
Code Commit → Git Push → CI Pipeline
                              │
         ┌────────────────────┼────────────────────┐
         │                    │                    │
         ▼                    ▼                    ▼
   lint-backend         lint-frontend        security-scan
         │                    │                    │
         ▼                    │                    │
   test-backend                │                    │
         │                    │                    │
         ▼                    ▼                    ▼
   build-backend          build-frontend         Trivy
         │                    │               (SARIF)
         └────────────────────┴───────────────┘
                               │
                               ▼
                    Push to ACR (Alibaba Cloud)
                               │
                               ▼
                        ArgoCD Sync
                               │
                               ▼
                     Kubernetes Deployment
```

### 4.3 Required GitHub Secrets

| Secret | Description |
|--------|-------------|
| `ACR_USERNAME` | Alibaba Cloud ACR username |
| `ACR_PASSWORD` | Alibaba Cloud ACR password |
| `ACK_KUBECONFIG_DEV` | ACK kubeconfig for dev cluster |
| `ACK_KUBECONFIG_STAGING` | ACK kubeconfig for staging cluster |
| `ACK_KUBECONFIG_PROD` | ACK kubeconfig for prod cluster |
| `ARGOCD_SERVER` | ArgoCD server URL |
| `ARGOCD_TOKEN` | ArgoCD API token |
| `SLACK_WEBHOOK_URL` | Slack notifications webhook |

---

## 5. Security Architecture

### 5.1 Transport Security

- **TLS 1.3** enforced on all endpoints
- **HSTS** header with 2-year max-age
- Certificate management via Let's Encrypt / ACME

### 5.2 Authentication

- **JWT** with HMAC-SHA256
- Dual Token mechanism:
  - Access Token: 15min expiry
  - Refresh Token: 7-day expiry
- Token rotation on refresh

### 5.3 API Security

| Protection | Mechanism |
|------------|-----------|
| Rate Limiting | 100 requests/minute per user |
| Body Size Limit | 10MB max request body |
| CORS | Strict origin validation |
| Brute Force | Account lockout after 5 failed attempts |
| Audit | All write operations logged |

---

## 6. Monitoring & Observability

### 6.1 Metrics Stack

| Component | Purpose | Port |
|-----------|---------|------|
| Prometheus | Metrics collection | 9090 |
| Grafana | Dashboards & visualization | 3000 |
| AlertManager | Alert routing & deduplication | 9093 |
| SLS/ARMS | Alibaba Cloud native observability | - |

### 6.2 Key Metrics

| Metric | Description | Alert Threshold |
|--------|-------------|-----------------|
| API Error Rate | 5xx responses / total | > 1% for 5min |
| API Latency P99 | Backend response time | > 500ms for 5min |
| Pod Restarts | Container restart rate | > 0.01/min |
| CPU Usage | Node CPU utilization | > 85% for 10min |
| Memory Usage | Node memory utilization | > 90% for 10min |
| DB Connections | PostgreSQL connection pool | > 80% capacity |

### 6.3 Alert Routing

| Severity | Team | Channel |
|----------|------|---------|
| Critical (P0) | Ops | PagerDuty + DingTalk |
| High (P1) | Backend | DingTalk |
| Medium (P2) | Frontend | DingTalk |
| Low (P3) | All | Email |

---

## 7. Disaster Recovery

### 7.1 Backup Strategy

| Data | Frequency | Retention | Storage |
|------|-----------|-----------|---------|
| Database | Daily + WAL | 30 days | OSS |
| Redis RDB | Hourly | 7 days | OSS |
| File Storage | Real-time sync | - | S3/OSS Cross-Region |

### 7.2 RTO/RPO Targets

| Tier | RTO | RPO |
|------|-----|-----|
| High Availability | < 30s | < 1s |
| Disaster Recovery | < 5min | < 5min |
| Backup Restore | < 1hour | < 24hour |

---

## 8. Future Roadmap

| Phase | Feature | Target |
|-------|---------|--------|
| v1.4 | MFA Enhancement (TOTP) | 2026-Q2 |
| v2.0 | Mobile Client (React Native) | 2026-Q3 |
| v2.1 | Cross-Region Multi-Active | 2026-Q4 |
| v2.5 | AI Features (Search, Tagging) | 2027-Q1 |

---

## 9. Repository Structure

```
nueronote-ops/
├── github/
│   └── workflows/
│       ├── ci.yml              # CI pipeline
│       └── deploy.yml          # CD pipeline
├── kubernetes/
│   ├── base/
│   │   └── namespace.yaml      # Base K8s resources
│   └── overlays/
│       ├── dev/                # Dev environment
│       ├── staging/            # Staging environment
│       └── prod/               # Production environment
├── argocd/
│   └── nueronote-apps.yaml     # ArgoCD Application definitions
├── monitoring/
│   ├── prometheus/
│   │   └── prometheus.yaml     # Prometheus config + alert rules
│   └── alertmanager/
│       └── alertmanager.yaml   # Alert routing config
└── scripts/
    └── deploy.sh               # Deployment helper script
```

---

## 10. Appendix

### A. Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `FLASK_ENV` | Flask environment | `production` |
| `FLASK_SECRET_KEY` | Flask secret for sessions | *(secret)* |
| `JWT_SECRET` | JWT signing secret | *(secret)* |
| `DATABASE_URL` | PostgreSQL connection | `postgresql://user:pass@host:5432/db` |
| `REDIS_URL` | Redis connection | `redis://host:6379/0` |
| `CORS_ORIGINS` | Allowed CORS origins | `https://app.nueronote.com` |

### B. API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/metrics` | Prometheus metrics |
| POST | `/api/v1/auth/login` | User login |
| POST | `/api/v1/auth/refresh` | Refresh token |
| GET | `/api/v1/notes` | List notes |
| POST | `/api/v1/notes` | Create note |
| PUT | `/api/v1/notes/{id}` | Update note |
| DELETE | `/api/v1/notes/{id}` | Delete note |

### C. Related Documentation

- [NueroNote Security Architecture](./NueroNote-Security-Architecture.md) - Detailed security hardening guide
- [NueroNote Multi-Region Architecture](./NueroNote-Multi-Region-Architecture.md) - Cross-region disaster recovery
- [NueroNote DevOps Automation](./NueroNote-DevOps-Automation.md) - GitOps and CI/CD details
