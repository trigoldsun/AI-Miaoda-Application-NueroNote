#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 审计日志系统
提供全面的操作审计和日志管理功能。

特性:
- 标准化审计事件格式
- 多种存储后端支持
- 日志搜索和导出
- 实时告警支持
"""

import json
import os
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class AuditAction(Enum):
    """审计动作类型"""
    # 认证
    AUTH_LOGIN = "AUTH_LOGIN"
    AUTH_LOGOUT = "AUTH_LOGOUT"
    AUTH_REGISTER = "AUTH_REGISTER"
    AUTH_FAILED_LOGIN = "AUTH_FAILED_LOGIN"
    AUTH_PASSWORD_RESET = "AUTH_PASSWORD_RESET"
    
    # Vault操作
    VAULT_CREATE = "VAULT_CREATE"
    VAULT_UPDATE = "VAULT_UPDATE"
    VAULT_READ = "VAULT_READ"
    VAULT_DELETE = "VAULT_DELETE"
    VAULT_RESTORE = "VAULT_RESTORE"
    
    # 同步操作
    SYNC_PUSH = "SYNC_PUSH"
    SYNC_PULL = "SYNC_PULL"
    
    # 云存储
    CLOUD_CONFIGURE = "CLOUD_CONFIGURE"
    CLOUD_SYNC = "CLOUD_SYNC"
    CLOUD_DISCONNECT = "CLOUD_DISCONNECT"
    
    # 账户
    ACCOUNT_UPGRADE = "ACCOUNT_UPGRADE"
    ACCOUNT_UPDATE = "ACCOUNT_UPDATE"
    PLAN_UPGRADE = "PLAN_UPGRADE"
    
    # 安全
    SECURITY_SUSPICIOUS = "SECURITY_SUSPICIOUS"
    SECURITY_RATE_LIMIT = "SECURITY_RATE_LIMIT"
    SECURITY_INVALID_TOKEN = "SECURITY_INVALID_TOKEN"
    
    # 管理员
    ADMIN_USER_DISABLE = "ADMIN_USER_DISABLE"
    ADMIN_USER_ENABLE = "ADMIN_USER_ENABLE"
    ADMIN_DATA_EXPORT = "ADMIN_DATA_EXPORT"


class AuditSeverity(Enum):
    """审计严重级别"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class AuditEvent:
    """审计事件"""
    id: Optional[int] = None
    event_id: str = ""  # UUID
    timestamp: int = 0
    action: str = ""
    user_id: Optional[str] = None
    ip_addr: Optional[str] = None
    user_agent: Optional[str] = None
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    severity: str = "INFO"
    success: bool = True
    details: Dict = field(default_factory=dict)
    error_message: Optional[str] = None
    duration_ms: int = 0
    
    def to_dict(self) -> Dict:
        return {k: v for k, v in asdict(self).items() if v is not None}
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'AuditEvent':
        return cls(**data)


class AuditLogger:
    """审计日志记录器"""
    
    def __init__(self, db_path: str = "nueronote.db"):
        self.db_path = db_path
        self._ensure_table()
    
    def _ensure_table(self):
        """确保审计日志表存在"""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                action TEXT NOT NULL,
                user_id TEXT,
                ip_addr TEXT,
                user_agent TEXT,
                resource_type TEXT,
                resource_id TEXT,
                severity TEXT DEFAULT 'INFO',
                success INTEGER DEFAULT 1,
                details TEXT,
                error_message TEXT,
                duration_ms INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp 
            ON audit_log(timestamp DESC)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_user_action 
            ON audit_log(user_id, action)
        """)
        conn.commit()
        conn.close()
    
    def log(self, event: AuditEvent) -> int:
        """
        记录审计事件
        
        Returns:
            事件ID
        """
        if not event.event_id:
            import uuid
            event.event_id = str(uuid.uuid4())[:16]
        
        if not event.timestamp:
            event.timestamp = int(time.time() * 1000)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("""
            INSERT INTO audit_log 
            (event_id, timestamp, action, user_id, ip_addr, user_agent,
             resource_type, resource_id, severity, success, details, 
             error_message, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.event_id,
            event.timestamp,
            event.action,
            event.user_id,
            event.ip_addr,
            event.user_agent,
            event.resource_type,
            event.resource_id,
            event.severity,
            1 if event.success else 0,
            json.dumps(event.details) if event.details else None,
            event.error_message,
            event.duration_ms,
        ))
        conn.commit()
        event_id = cursor.lastrowid
        conn.close()
        
        return event_id
    
    def query(self, 
              user_id: str = None,
              action: str = None,
              resource_type: str = None,
              start_time: int = None,
              end_time: int = None,
              severity: str = None,
              success: bool = None,
              limit: int = 100,
              offset: int = 0) -> List[Dict]:
        """
        查询审计日志
        
        Args:
            user_id: 用户ID过滤
            action: 动作类型过滤
            resource_type: 资源类型过滤
            start_time: 开始时间戳
            end_time: 结束时间戳
            severity: 严重级别过滤
            success: 成功/失败过滤
            limit: 返回数量限制
            offset: 偏移量
            
        Returns:
            审计事件列表
        """
        conditions = []
        params = []
        
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        
        if action:
            conditions.append("action = ?")
            params.append(action)
        
        if resource_type:
            conditions.append("resource_type = ?")
            params.append(resource_type)
        
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time)
        
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time)
        
        if severity:
            conditions.append("severity = ?")
            params.append(severity)
        
        if success is not None:
            conditions.append("success = ?")
            params.append(1 if success else 0)
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        query = f"""
            SELECT * FROM audit_log
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        events = []
        for row in rows:
            event = dict(row)
            if event.get('details'):
                try:
                    event['details'] = json.loads(event['details'])
                except:
                    pass
            event['success'] = bool(event['success'])
            events.append(event)
        
        return events
    
    def get_user_activity(self, user_id: str, 
                         days: int = 7) -> Dict:
        """
        获取用户活动统计
        
        Args:
            user_id: 用户ID
            days: 统计天数
            
        Returns:
            活动统计
        """
        start_time = int((time.time() - days * 86400) * 1000)
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        
        # 动作统计
        cursor = conn.execute("""
            SELECT action, COUNT(*) as count
            FROM audit_log
            WHERE user_id = ? AND timestamp >= ?
            GROUP BY action
            ORDER BY count DESC
        """, (user_id, start_time))
        action_stats = {row['action']: row['count'] for row in cursor}
        
        # 成功率统计
        cursor = conn.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as success_count
            FROM audit_log
            WHERE user_id = ? AND timestamp >= ?
        """, (user_id, start_time))
        row = cursor.fetchone()
        total = row['total'] if row else 0
        success_count = row['success_count'] if row else 0
        
        # 每日统计
        cursor = conn.execute("""
            SELECT 
                DATE(timestamp / 1000, 'unixepoch') as date,
                COUNT(*) as count
            FROM audit_log
            WHERE user_id = ? AND timestamp >= ?
            GROUP BY date
            ORDER BY date
        """, (user_id, start_time))
        daily_stats = [{'date': row['date'], 'count': row['count']} for row in cursor]
        
        conn.close()
        
        return {
            "user_id": user_id,
            "period_days": days,
            "total_events": total,
            "success_rate": success_count / total if total > 0 else 0,
            "action_stats": action_stats,
            "daily_stats": daily_stats,
        }
    
    def export(self, start_time: int, end_time: int,
              format: str = "json") -> str:
        """
        导出审计日志
        
        Args:
            start_time: 开始时间戳
            end_time: 结束时间戳
            format: 导出格式 (json/csv)
            
        Returns:
            导出数据
        """
        events = self.query(
            start_time=start_time,
            end_time=end_time,
            limit=100000,
        )
        
        if format == "json":
            return json.dumps(events, indent=2, ensure_ascii=False)
        elif format == "csv":
            import csv
            import io
            
            output = io.StringIO()
            if events:
                writer = csv.DictWriter(output, fieldnames=events[0].keys())
                writer.writeheader()
                writer.writerows(events)
            return output.getvalue()
        else:
            raise ValueError(f"不支持的格式: {format}")


# 全局审计日志记录器
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """获取审计日志记录器"""
    global _audit_logger
    if _audit_logger is None:
        db_path = os.environ.get('FLUX_DB', 'nueronote.db')
        _audit_logger = AuditLogger(db_path)
    return _audit_logger


def log_audit(action: str,
              user_id: str = None,
              resource_type: str = None,
              resource_id: str = None,
              ip_addr: str = None,
              user_agent: str = None,
              severity: str = "INFO",
              success: bool = True,
              details: Dict = None,
              error_message: str = None,
              duration_ms: int = 0) -> int:
    """
    便捷审计日志函数
    
    Returns:
        事件ID
    """
    event = AuditEvent(
        action=action,
        user_id=user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_addr=ip_addr,
        user_agent=user_agent,
        severity=severity,
        success=success,
        details=details or {},
        error_message=error_message,
        duration_ms=duration_ms,
    )
    
    logger = get_audit_logger()
    return logger.log(event)


# 上下文管理器用于审计
from contextlib import contextmanager

@contextmanager
def audit_operation(action: str, 
                   user_id: str = None,
                   resource_type: str = None,
                   resource_id: str = None,
                   **kwargs):
    """
    审计操作上下文管理器
    
    Usage:
        with audit_operation("VAULT_UPDATE", user_id=user_id, resource_type="vault"):
            # 执行操作
            update_vault()
    """
    start_time = time.time()
    success = True
    error_msg = None
    
    try:
        yield
    except Exception as e:
        success = False
        error_msg = str(e)
        raise
    finally:
        duration = int((time.time() - start_time) * 1000)
        
        severity = "INFO"
        if not success:
            severity = "ERROR"
        elif "FAILED" in action or "INVALID" in action:
            severity = "WARNING"
        
        log_audit(
            action=action,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            severity=severity,
            success=success,
            error_message=error_msg,
            duration_ms=duration,
            **kwargs
        )


# 向后兼容别名
def write_audit(user_id: str = None, action: str = None, details: Dict = None,
               resource_type: str = None, resource_id: str = None) -> int:
    """
    向后兼容的审计日志函数

    【安全修复 v1.2】
    现在强制从Flask g对象获取user_id，不接受外部传入的值。
    这防止攻击者伪造审计日志。

    Args:
        user_id: 已废弃，被忽略（为了向后兼容保留参数）
        action: 动作类型
        details: 详细信息
        resource_type: 资源类型
        resource_id: 资源ID

    Returns:
        事件ID
    """
    # 【安全修复 v1.2】强制从Flask g获取用户ID，防止伪造
    try:
        from flask import g
        actual_user_id = getattr(g, 'user_id', None) or 'SYSTEM'
    except RuntimeError:
        # 不在Flask请求上下文中
        actual_user_id = 'SYSTEM'

    return log_audit(
        action=action or "UNKNOWN",
        user_id=actual_user_id,  # 忽略传入的user_id，使用g.user_id
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
    )


def get_client_ip(request=None) -> str:
    """
    获取客户端IP地址
    
    【v1.3安全修复】
    - 如果在Flask请求上下文中，自动使用全局request对象
    - 仅信任X-Forwarded-For的第一个IP（最左侧是客户端）
    - 在反向代理环境下，应在代理层过滤伪造的IP头
    
    Args:
        request: Flask请求对象（可选，不传则自动从flask import）
        
    Returns:
        客户端IP地址
    """
    # 【v1.3】自动获取request对象
    if request is None:
        try:
            from flask import request
        except RuntimeError:
            return '0.0.0.0'
    
    # 【v1.3安全修复】仅信任X-Forwarded-For的第一个IP
    # 这应该是反向代理添加的真实客户端IP
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        # 只取第一个IP（最接近代理入口）
        return forwarded_for.split(',')[0].strip()
    
    real_ip = request.headers.get('X-Real-IP')
    if real_ip:
        return real_ip.strip()
    
    return request.remote_addr or '0.0.0.0'
