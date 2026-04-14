#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 监控和告警模块
提供Prometheus指标、健康检查、告警规则等功能。

依赖: pip install prometheus-client
"""

import time
from dataclasses import dataclass
from typing import Dict, Optional, Callable
from functools import wraps

try:
    from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


# ==================== 指标定义 ====================

@dataclass
class Metrics:
    """Prometheus指标"""
    
    # 请求指标
    http_requests_total: 'Counter' = None
    http_request_duration_seconds: 'Histogram' = None
    http_requests_in_progress: 'Gauge' = None
    
    # 数据库指标
    db_connections_active: 'Gauge' = None
    db_queries_total: 'Counter' = None
    db_query_duration_seconds: 'Histogram' = None
    
    # 同步指标
    sync_operations_total: 'Counter' = None
    sync_conflicts_total: 'Counter' = None
    sync_latency_seconds: 'Histogram' = None
    
    # 用户指标
    active_users: 'Gauge' = None
    user_registrations_total: 'Counter' = None
    user_logins_total: 'Counter' = None
    
    # 存储指标
    storage_used_bytes: 'Gauge' = None
    storage_available_bytes: 'Gauge' = None
    
    # 错误指标
    errors_total: 'Counter' = None
    

class MonitoringService:
    """监控服务"""
    
    def __init__(self):
        self._enabled = PROMETHEUS_AVAILABLE
        self._metrics: Optional[Metrics] = None
        self._request_count = 0
        self._start_time = time.time()
        
        if self._enabled:
            self._init_metrics()
    
    def _init_metrics(self):
        """初始化指标"""
        m = Metrics()
        
        # HTTP请求
        m.http_requests_total = Counter(
            'http_requests_total',
            'Total HTTP requests',
            ['method', 'endpoint', 'status']
        )
        m.http_request_duration_seconds = Histogram(
            'http_request_duration_seconds',
            'HTTP request duration',
            ['method', 'endpoint'],
            buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]
        )
        m.http_requests_in_progress = Gauge(
            'http_requests_in_progress',
            'HTTP requests in progress',
            ['method']
        )
        
        # 数据库
        m.db_connections_active = Gauge(
            'db_connections_active',
            'Active database connections'
        )
        m.db_queries_total = Counter(
            'db_queries_total',
            'Total database queries',
            ['operation', 'table']
        )
        m.db_query_duration_seconds = Histogram(
            'db_query_duration_seconds',
            'Database query duration',
            ['operation', 'table'],
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1]
        )
        
        # 同步
        m.sync_operations_total = Counter(
            'sync_operations_total',
            'Total sync operations',
            ['type', 'status']
        )
        m.sync_conflicts_total = Counter(
            'sync_conflicts_total',
            'Total sync conflicts',
            ['document_id']
        )
        m.sync_latency_seconds = Histogram(
            'sync_latency_seconds',
            'Sync operation latency',
            ['type'],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5]
        )
        
        # 用户
        m.active_users = Gauge(
            'active_users',
            'Number of active users',
            ['window']  # 1m, 5m, 15m, 1h
        )
        m.user_registrations_total = Counter(
            'user_registrations_total',
            'Total user registrations'
        )
        m.user_logins_total = Counter(
            'user_logins_total',
            'Total user logins'
        )
        
        # 存储
        m.storage_used_bytes = Gauge(
            'storage_used_bytes',
            'Storage used in bytes',
            ['user_id']
        )
        m.storage_available_bytes = Gauge(
            'storage_available_bytes',
            'Storage available in bytes'
        )
        
        # 错误
        m.errors_total = Counter(
            'errors_total',
            'Total errors',
            ['type', 'module']
        )
        
        self._metrics = m
    
    def record_request(self, method: str, endpoint: str, status: int, duration: float):
        """记录HTTP请求"""
        if not self._enabled:
            return
        
        self._metrics.http_requests_total.labels(
            method=method, endpoint=endpoint, status=status
        ).inc()
        self._metrics.http_request_duration_seconds.labels(
            method=method, endpoint=endpoint
        ).observe(duration)
    
    def record_db_query(self, operation: str, table: str, duration: float):
        """记录数据库查询"""
        if not self._enabled:
            return
        
        self._metrics.db_queries_total.labels(
            operation=operation, table=table
        ).inc()
        self._metrics.db_query_duration_seconds.labels(
            operation=operation, table=table
        ).observe(duration)
    
    def record_sync(self, sync_type: str, status: str, latency: float = None):
        """记录同步操作"""
        if not self._enabled:
            return
        
        self._metrics.sync_operations_total.labels(
            type=sync_type, status=status
        ).inc()
        
        if latency is not None:
            self._metrics.sync_latency_seconds.labels(type=sync_type).observe(latency)
    
    def record_conflict(self, document_id: str):
        """记录同步冲突"""
        if not self._enabled:
            return
        
        self._metrics.sync_conflicts_total.labels(document_id=document_id).inc()
    
    def record_user_login(self):
        """记录用户登录"""
        if not self._enabled:
            return
        
        self._metrics.user_logins_total.inc()
    
    def record_user_registration(self):
        """记录用户注册"""
        if not self._enabled:
            return
        
        self._metrics.user_registrations_total.inc()
    
    def record_error(self, error_type: str, module: str):
        """记录错误"""
        if not self._enabled:
            return
        
        self._metrics.errors_total.labels(type=error_type, module=module).inc()
    
    def update_active_users(self, window: str, count: int):
        """更新活跃用户数"""
        if not self._enabled:
            return
        
        self._metrics.active_users.labels(window=window).set(count)
    
    def update_storage(self, used_bytes: int, available_bytes: int):
        """更新存储使用"""
        if not self._enabled:
            return
        
        self._metrics.storage_used_bytes.set(used_bytes)
        self._metrics.storage_available_bytes.set(available_bytes)
    
    def get_metrics(self) -> bytes:
        """获取Prometheus指标"""
        if not self._enabled:
            return b'# NueroNote monitoring disabled\n'
        
        return generate_latest()
    
    def get_metrics_content_type(self) -> str:
        """获取指标内容类型"""
        return CONTENT_TYPE_LATEST if PROMETHEUS_AVAILABLE else 'text/plain'
    
    def get_status(self) -> Dict:
        """获取服务状态"""
        return {
            'status': 'healthy',
            'uptime_seconds': time.time() - self._start_time,
            'monitoring_enabled': self._enabled,
            'prometheus_available': PROMETHEUS_AVAILABLE,
            'requests_total': self._request_count,
        }


# 装饰器
def monitor_request(f: Callable) -> Callable:
    """HTTP请求监控装饰器"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        from flask import request
        from time import time
        
        start = time()
        
        try:
            response = f(*args, **kwargs)
            status = getattr(response, 'status_code', 200)
        except Exception as e:
            status = 500
            raise
        finally:
            duration = time() - start
            endpoint = request.endpoint or 'unknown'
            
            monitoring = get_monitoring_service()
            monitoring.record_request(request.method, endpoint, status, duration)
        
        return response
    
    return wrapper


# 告警规则
@dataclass
class Alert:
    """告警"""
    name: str
    severity: str  # critical, warning, info
    message: str
    value: float
    threshold: float
    fired_at: Optional[int] = None


class AlertManager:
    """告警管理器"""
    
    def __init__(self):
        self.alerts: Dict[str, Alert] = {}
        self.handlers: list = []
        
        # 默认阈值
        self.thresholds = {
            'error_rate': 0.05,  # 5%
            'response_time_p99': 2.0,  # 2秒
            'sync_conflict_rate': 0.1,  # 10%
            'storage_usage': 0.9,  # 90%
            'active_users_drop': 0.5,  # 50%下降
        }
    
    def check_error_rate(self, error_count: int, total_count: int) -> Optional[Alert]:
        """检查错误率"""
        if total_count == 0:
            return None
        
        rate = error_count / total_count
        threshold = self.thresholds['error_rate']
        
        if rate > threshold:
            return Alert(
                name='high_error_rate',
                severity='warning',
                message=f'错误率 {rate:.2%} 超过阈值 {threshold:.2%}',
                value=rate,
                threshold=threshold,
                fired_at=int(time.time())
            )
        return None
    
    def check_response_time(self, p99_time: float) -> Optional[Alert]:
        """检查响应时间"""
        threshold = self.thresholds['response_time_p99']
        
        if p99_time > threshold:
            return Alert(
                name='slow_response',
                severity='warning',
                message=f'P99响应时间 {p99_time:.2f}s 超过阈值 {threshold:.2f}s',
                value=p99_time,
                threshold=threshold,
                fired_at=int(time.time())
            )
        return None
    
    def check_storage(self, used: int, total: int) -> Optional[Alert]:
        """检查存储使用"""
        if total == 0:
            return None
        
        usage = used / total
        threshold = self.thresholds['storage_usage']
        
        if usage > threshold:
            severity = 'critical' if usage > 0.95 else 'warning'
            return Alert(
                name='high_storage_usage',
                severity=severity,
                message=f'存储使用 {usage:.2%} 超过阈值 {threshold:.2%}',
                value=usage,
                threshold=threshold,
                fired_at=int(time.time())
            )
        return None
    
    def add_handler(self, handler: Callable):
        """添加告警处理器"""
        self.handlers.append(handler)
    
    def fire_alert(self, alert: Alert):
        """触发告警"""
        self.alerts[alert.name] = alert
        
        for handler in self.handlers:
            try:
                handler(alert)
            except Exception as e:
                print(f"告警处理器执行失败: {e}")
    
    def get_active_alerts(self) -> list:
        """获取活跃告警"""
        return list(self.alerts.values())


# 全局实例
_monitoring_service: Optional[MonitoringService] = None
_alert_manager: Optional[AlertManager] = None


def get_monitoring_service() -> MonitoringService:
    """获取监控服务"""
    global _monitoring_service
    if _monitoring_service is None:
        _monitoring_service = MonitoringService()
    return _monitoring_service


def get_alert_manager() -> AlertManager:
    """获取告警管理器"""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager
