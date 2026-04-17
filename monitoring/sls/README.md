# Alibaba Cloud SLS (Log Service) Configuration for NueroNote

## Overview

This directory contains Fluent Bit configuration for shipping NueroNote application logs to Alibaba Cloud Log Service (SLS).

## Files

| File | Purpose |
|------|---------|
| `fluent-bit.conf` | Main Fluent Bit configuration |
| `parsers.conf` | Log parsing rules |
| `lua-filter.lua` | Custom Lua filters for log enrichment |

## Quick Start

### 1. Create SLS Project and Logstore

```bash
# Using Alibaba Cloud CLI
aliyun log create_project --project_name="nueronote-prod" --description="NueroNote Production Logs"

aliyun log create_logstore --project_name="nueronote-prod" --logstore_name="app-logs" --ttl=30 --shard_count=2

aliyun log create_logstore --project_name="nueronote-prod" --logstore_name="access-logs" --ttl=30 --shard_count=2

aliyun log create_logstore --project_name="nueronote-prod" --logstore_name="audit-logs" --ttl=90 --shard_count=2
```

### 2. Create IAM Role for ACK

The ACK nodes need permission to write to SLS. Create a RAM role and attach the `AliyunLogFullAccess` policy.

```bash
# Create role
aliyun ram create_role --RoleName="nueronote-ack-sls-role"

# Attach policy
aliyun ram attach_policy --PolicyType="System" --PolicyName="AliyunLogFullAccess" --RoleName="nueronote-ack-sls-role"
```

### 3. Deploy Fluent Bit as DaemonSet

```yaml
# fluent-bit.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: fluent-bit
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: fluent-bit
  template:
    metadata:
      labels:
        app: fluent-bit
    spec:
      serviceAccountName: fluent-bit-sa
      containers:
        - name: fluent-bit
          image: fluent/fluent-bit:2.1.0
          ports:
            - name: http
              containerPort: 2020
          volumeMounts:
            - name: config
              mountPath: /fluent-bit/etc/
            - name: varlog
              mountPath: /var/log/
            - name: varlibdockercontainers
              mountPath: /var/lib/docker/containers
              readOnly: true
      volumes:
        - name: config
          configMap:
            name: fluent-bit-config
        - name: varlog
          hostPath:
            path: /var/log
        - name: varlibdockercontainers
          hostPath:
            path: /var/lib/docker/containers
```

## Log Categories

| Logstore | Source | Retention | Use Case |
|----------|--------|-----------|----------|
| app-logs | stdout/stderr | 30 days | Application logs |
| access-logs | Nginx ingress | 30 days | HTTP access logs |
| audit-logs | Backend app | 90 days | Security audit |

## Log Format

### Application Logs (app-logs)

```json
{
  "time": "2026-04-17T10:30:00.000Z",
  "level": "info",
  "service": "nueronote-backend",
  "trace_id": "abc123def456",
  "message": "Note created successfully",
  "user_id": "user-uuid",
  "method": "POST",
  "path": "/api/v1/notes",
  "status": 201,
  "duration_ms": 45
}
```

### Access Logs (access-logs)

```json
{
  "time": "2026-04-17T10:30:00.000Z",
  "remote_addr": "192.168.1.100",
  "host": "api.nueronote.com",
  "method": "POST",
  "uri": "/api/v1/notes",
  "status": 201,
  "body_bytes_sent": 512,
  "request_time": 0.045,
  "user_agent": "Mozilla/5.0...",
  "xff": "10.0.0.1"
}
```

### Audit Logs (audit-logs)

```json
{
  "time": "2026-04-17T10:30:00.000Z",
  "event_type": "note.create",
  "user_id": "user-uuid",
  "resource_id": "note-uuid",
  "ip_address": "192.168.1.100",
  "user_agent": "Mozilla/5.0...",
  "result": "success",
  "metadata": {
    "title": "My Note Title",
    "size_bytes": 1024
  }
}
```

## Index Fields

Create the following index fields in SLS console:

| Field | Type | Description |
|-------|------|-------------|
| time | text | Log timestamp |
| level | text | Log level (info/warn/error) |
| service | text | Service name |
| trace_id | text | Distributed trace ID |
| user_id | text | User identifier |
| method | text | HTTP method |
| path | text | HTTP path |
| status | long | HTTP status code |
| duration_ms | long | Request duration |
| event_type | text | Audit event type |
| result | text | Operation result |

## Dashboards

Import the following dashboards in Grafana:

1. **NueroNote App Overview** - Application metrics
2. **NueroNote Access Log** - HTTP traffic analysis  
3. **NueroNote Audit** - Security events

## Troubleshooting

### Check Fluent Bit Logs

```bash
kubectl logs -n monitoring -l app=fluent-bit --tail=100
```

### Test SLS Connection

```bash
kubectl exec -n monitoring fluent-bit-xxx -- fluent-bit --version
```

### Common Issues

| Issue | Solution |
|-------|----------|
| Permission denied | Check IAM role and RAM policy |
| Log delay | Increase buffer size or shard count |
| Index not searchable | Verify index field configuration |
