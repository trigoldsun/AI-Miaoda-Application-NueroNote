# Changelog

All notable changes to the NueroNote operations infrastructure are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [2.0.0] - 2026-04-17

### Added

#### Architecture Documentation
- **ARCHITECTURE.md** - Comprehensive system architecture documentation in English
  - System overview and tech stack
  - Component specifications
  - Deployment architecture
  - CI/CD pipeline details
  - Security architecture summary
  - Monitoring and observability
  - Disaster recovery plan

#### Kubernetes Infrastructure
- **kubernetes/base/backend.yaml** - Backend Flask application deployment
- **kubernetes/base/frontend.yaml** - Frontend static HTML deployment
- **kubernetes/base/services.yaml** - Backend and frontend services
- **kubernetes/base/hpa.yaml** - Horizontal Pod Autoscaler configurations
- **kubernetes/base/ingress.yaml** - Alibaba Cloud SLB ingress configuration
- **kubernetes/base/networkpolicy.yaml** - Network policies for pod isolation
- **kubernetes/base/quota.yaml** - ResourceQuota and LimitRange
- **kubernetes/base/config.yaml** - ConfigMap and Secret templates
- **kubernetes/base/rbac.yaml** - ServiceAccount, Role, and RoleBinding
- **kubernetes/base/namespace.yaml** - Namespace definitions (dev/staging/prod)
- **kubernetes/base/kustomization.yaml** - Kustomize base configuration

#### Kubernetes Overlays
- **kubernetes/overlays/dev/** - Development environment (1 replica, debug logs)
- **kubernetes/overlays/staging/** - Staging environment (2 replicas, info logs)
- **kubernetes/overlays/prod/** - Production environment (5 backend, 3 frontend replicas)

#### CI/CD Pipeline
- **github/workflows/ci.yml** - Continuous Integration pipeline
  - Backend: flake8, Bandit, pytest
  - Frontend: static analysis
  - Docker build (Alibaba Cloud ACR)
  - Trivy security scanning
- **github/workflows/deploy.yml** - Continuous Deployment pipeline
  - Multi-environment deployment (dev/staging/prod)
  - ArgoCD sync integration
  - Rollback capability
  - Slack notifications

#### Monitoring Stack
- **monitoring/prometheus/prometheus.yaml** - Prometheus configuration
  - 7 scrape jobs (Kubernetes, backend, frontend, ingress)
  - 15+ alert rules (API errors, latency, pod health, HPA, DB/Redis)
- **monitoring/alertmanager/alertmanager.yaml** - Alert routing
  - PagerDuty for critical
  - DingTalk for team routing
  - Email for warnings
- **monitoring/grafana/nueronote-dashboard.json** - Grafana dashboard
  - Overview panel (Error Rate, P99 Latency, QPS, CPU)
  - API Metrics panel (Request Rate by Status, Latency Distribution)
  - Pod Status panel (Running pods, HPA replicas, Memory usage)

#### Logging Infrastructure
- **monitoring/sls/README.md** - Alibaba Cloud SLS deployment guide
- **monitoring/sls/fluent-bit.conf** - Fluent Bit configuration
  - Kubernetes log collection
  - Nginx access log parsing
  - Alibaba Cloud SLS output
- **monitoring/sls/parsers.conf** - Log parsing rules
  - Docker JSON parser
  - Nginx access log parser
  - JSON log parser
- **monitoring/sls/lua-filter.lua** - Lua filter for log enrichment
  - Trace ID generation
  - Kubernetes metadata injection
  - Log severity mapping

#### GitOps
- **argocd/nueronote-apps.yaml** - ArgoCD Application definitions
  - NueroNote project
  - Backend/Frontend applications
  - Automated sync policies

#### Scripts
- **scripts/deploy.sh** - Deployment helper script
  - Support for dev/staging/prod
  - apply/delete/status/logs/restart commands

#### Documentation
- **NueroNote-Security-Architecture.md** - Security hardening guide (updated to English)
- **NueroNote-DevOps-Automation.md** - DevOps automation guide (updated to English)
- **NueroNote-Multi-Region-Architecture.md** - Multi-region disaster recovery (updated to English)

### Changed

#### Tech Stack Correction
- **Backend**: Changed from Go to Python Flask (matching actual codebase)
- **Frontend**: Changed from React/Next.js to Vanilla HTML/JS (matching actual codebase)
- **Registry**: Changed from Docker Hub to Alibaba Cloud ACR

#### K8s Resource Restructuring
- Split monolithic `namespace.yaml` (493 lines) into 11 separate resource files
- Each resource type now has its own file for better maintainability
- Proper kustomize resource management

### Removed

- Legacy Kubernetes configuration (if any)
- Obsolete Docker configurations

## [1.0.0] - 2026-04-14

### Added
- Initial NueroNote project structure
- Basic Flask server implementation
- Vanilla HTML/JS frontend
- Security hardening (P0/P1 fixes)
- Cloud sync architecture design

---

## Migration Guide

### Upgrading from 1.x to 2.0

1. **Update kubectl context**
   ```bash
   kubectl config use-context <cluster-name>
   ```

2. **Deploy new infrastructure**
   ```bash
   kubectl apply -k kubernetes/overlays/prod
   ```

3. **Update GitHub Secrets**
   - Replace Docker Hub credentials with Alibaba Cloud ACR
   - Add ArgoCD credentials
   - Add Slack webhook URL

4. **Import Grafana Dashboard**
   - Navigate to Grafana → Dashboards → Import
   - Upload `monitoring/grafana/nueronote-dashboard.json`

5. **Configure ArgoCD**
   ```bash
   kubectl apply -f argocd/nueronote-apps.yaml
   ```
