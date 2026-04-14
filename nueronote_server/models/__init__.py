#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote SQLAlchemy 数据模型
支持 SQLite（开发）和 PostgreSQL（生产）
"""

from datetime import datetime
from typing import Optional, Dict, Any
import uuid

from sqlalchemy import (
    Column, String, Integer, BigInteger, Boolean, Text,
    ForeignKey, DateTime, Index, UniqueConstraint, CheckConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

Base = declarative_base()


class User(Base):
    """
    用户账户模型
    """
    __tablename__ = 'users'
    
    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    email = Column(String(255), unique=True, nullable=False, index=True)
    
    # 密码哈希（服务端不存储明文密码，客户端端到端加密）
    password_hash = Column(String(255), nullable=True)
    
    # 账户计划
    plan = Column(String(20), default='free', nullable=False)  # free, pro, team
    storage_quota = Column(BigInteger, default=512 * 1024 * 1024)  # 512 MB
    storage_used = Column(BigInteger, default=0)
    vault_version = Column(Integer, default=1)
    
    # 时间戳
    created_at = Column(BigInteger, nullable=False)  # 毫秒时间戳
    updated_at = Column(BigInteger, nullable=False)
    
    # 账户安全字段
    login_fails = Column(Integer, default=0)
    locked_until = Column(BigInteger, default=0)  # 锁定截止时间戳
    last_login = Column(BigInteger, default=0)
    last_ip = Column(String(45))  # 支持IPv6
    
    # 云存储配置（JSON）
    cloud_config = Column(Text, default='[]')
    
    # 关系
    vault = relationship("Vault", uselist=False, back_populates="user", cascade="all, delete-orphan")
    vault_versions = relationship("VaultVersion", back_populates="user", cascade="all, delete-orphan")
    sync_logs = relationship("SyncLog", back_populates="user", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user", cascade="all, delete-orphan")
    document_versions = relationship("DocumentVersion", back_populates="user", cascade="all, delete-orphan")
    
    __table_args__ = (
        Index('idx_users_plan', 'plan'),
        Index('idx_users_created', 'created_at'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（不含敏感信息）"""
        return {
            'id': self.id,
            'email': self.email,
            'plan': self.plan,
            'storage_quota': self.storage_quota,
            'storage_used': self.storage_used,
            'vault_version': self.vault_version,
            'created_at': self.created_at,
            'last_login': self.last_login,
        }


class Vault(Base):
    """
    用户Vault存储（加密的笔记数据）
    """
    __tablename__ = 'vaults'
    
    user_id = Column(String(32), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    vault_json = Column(Text, nullable=False)  # 加密的JSON数据
    
    # 版本控制
    vault_version = Column(Integer, default=1)
    updated_at = Column(BigInteger, nullable=False)
    updated_seq = Column(Integer, default=0)  # 操作序列号
    
    # 存储统计
    storage_bytes = Column(Integer, default=0)
    last_synced_at = Column(BigInteger, default=0)
    
    # 关系
    user = relationship("User", back_populates="vault")
    
    __table_args__ = (
        Index('idx_vaults_updated', 'updated_at'),
        Index('idx_vaults_synced', 'last_synced_at'),
    )


class VaultVersion(Base):
    """
    Vault版本历史（自动快照）
    """
    __tablename__ = 'vault_versions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(32), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    version = Column(Integer, nullable=False)
    vault_json = Column(Text, nullable=False)
    vault_bytes = Column(Integer, nullable=False)
    created_at = Column(BigInteger, nullable=False)
    note = Column(Text, default='')
    is_auto = Column(Integer, default=1)  # 1=自动快照，0=手动
    
    # 关系
    user = relationship("User", back_populates="vault_versions")
    
    __table_args__ = (
        Index('idx_vaultver_user_version', 'user_id', 'version'),
        Index('idx_vaultver_created', 'created_at'),
        UniqueConstraint('user_id', 'version', name='uq_vaultver_user_version'),
    )


class SyncLog(Base):
    """
    同步操作日志（CRDT/OT操作记录）
    """
    __tablename__ = 'sync_log'
    
    id = Column(String(32), primary_key=True, default=lambda: uuid.uuid4().hex)
    user_id = Column(String(32), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    record_type = Column(String(50), nullable=False)  # note, folder, tag, etc.
    record_id = Column(String(50), nullable=False)
    operation = Column(String(20), nullable=False)  # create, update, delete
    encrypted_data = Column(Text, nullable=False)  # 加密的操作数据
    vector_clock = Column(Integer, default=0)
    created_at = Column(BigInteger, nullable=False)
    
    # 关系
    user = relationship("User", back_populates="sync_logs")
    
    __table_args__ = (
        Index('idx_sync_user_created', 'user_id', 'created_at'),
        Index('idx_sync_record', 'record_type', 'record_id'),
    )


class AuditLog(Base):
    """
    安全审计日志
    """
    __tablename__ = 'audit_log'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(32), ForeignKey('users.id', ondelete='CASCADE'), nullable=True)
    action = Column(String(100), nullable=False)
    ip_addr = Column(String(45))  # 支持IPv6
    user_agent = Column(String(512))
    resource_type = Column(String(50))
    resource_id = Column(String(50))
    details = Column(Text, default='{}')  # JSON格式
    created_at = Column(BigInteger, nullable=False)
    
    # 关系
    user = relationship("User", back_populates="audit_logs")
    
    __table_args__ = (
        Index('idx_audit_user_created', 'user_id', 'created_at'),
        Index('idx_audit_action_time', 'action', 'created_at'),
        Index('idx_audit_ip_time', 'ip_addr', 'created_at'),
    )


class DocumentVersion(Base):
    """
    文档版本历史
    """
    __tablename__ = 'document_versions'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(32), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    doc_id = Column(String(50), nullable=False)
    version = Column(Integer, nullable=False)
    doc_snapshot = Column(Text, nullable=False)  # 加密的文档快照
    created_at = Column(BigInteger, nullable=False)
    change_summary = Column(Text, default='')
    
    # 关系
    user = relationship("User", back_populates="document_versions")
    
    __table_args__ = (
        Index('idx_docver_doc_version', 'doc_id', 'version'),
        Index('idx_docver_user_doc', 'user_id', 'doc_id'),
        UniqueConstraint('user_id', 'doc_id', 'version', name='uq_docver_user_doc_version'),
    )


class RateLimit(Base):
    """
    速率限制记录
    """
    __tablename__ = 'rate_limit'
    
    ip_addr = Column(String(45), primary_key=True)  # 支持IPv6
    action = Column(String(100), primary_key=True)
    count = Column(Integer, default=1)
    window_start = Column(BigInteger, nullable=False)
    
    __table_args__ = (
        Index('idx_ratelimit_window', 'window_start'),
    )
