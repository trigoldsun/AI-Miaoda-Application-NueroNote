#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote SQLAlchemy 模型
定义数据库表结构和关系
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, 
    ForeignKey, Index, JSON, BigInteger
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, Mapped, mapped_column

# 创建基类
Base = declarative_base()


class User(Base):
    """用户模型"""
    __tablename__ = 'users'
    
    id = Column(String(64), primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(Text, nullable=True)
    plan = Column(String(32), default='free')
    storage_quota = Column(BigInteger, default=512 * 1024 * 1024)
    storage_used = Column(BigInteger, default=0)
    vault_version = Column(Integer, default=1)
    created_at = Column(Integer, nullable=False)
    updated_at = Column(Integer, nullable=False)
    
    # 安全字段
    login_fails = Column(Integer, default=0)
    locked_until = Column(Integer, default=0)
    last_login = Column(Integer, default=0)
    last_ip = Column(String(64))
    cloud_config = Column(Text)
    
    # 关系
    vault = relationship("Vault", back_populates="user", uselist=False, cascade="all, delete-orphan")
    sync_logs = relationship("SyncLog", back_populates="user", cascade="all, delete-orphan")
    vault_versions = relationship("VaultVersion", back_populates="user", cascade="all, delete-orphan")
    document_versions = relationship("DocumentVersion", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User {self.email}>"


class Vault(Base):
    """Vault主表"""
    __tablename__ = 'vaults'
    
    user_id = Column(String(64), ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    vault_json = Column(Text, nullable=False)
    vault_version = Column(Integer, default=1)
    updated_at = Column(Integer, nullable=False)
    updated_seq = Column(Integer, default=0)
    storage_bytes = Column(BigInteger, default=0)
    last_synced_at = Column(Integer, default=0)
    
    # 关系
    user = relationship("User", back_populates="vault")
    
    def __repr__(self):
        return f"<Vault for {self.user_id}>"


class SyncLog(Base):
    """同步日志"""
    __tablename__ = 'sync_log'
    __table_args__ = (
        Index('idx_sync_user', 'user_id', 'created_at', postgresql_using='btree'),
    )
    
    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    record_type = Column(String(32), nullable=False)
    record_id = Column(String(64), nullable=False)
    operation = Column(String(32), nullable=False)
    encrypted_data = Column(Text, nullable=False)
    vector_clock = Column(Integer, default=0)
    created_at = Column(Integer, nullable=False)
    
    # 关系
    user = relationship("User", back_populates="sync_logs")
    
    def __repr__(self):
        return f"<SyncLog {self.id}>"


class AuditLog(Base):
    """审计日志"""
    __tablename__ = 'audit_log'
    __table_args__ = (
        Index('idx_audit_user', 'user_id', 'created_at', postgresql_using='btree'),
        Index('idx_audit_time', 'created_at', postgresql_using='btree'),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=True)
    action = Column(String(64), nullable=False)
    ip_addr = Column(String(64))
    user_agent = Column(Text)
    resource_type = Column(String(64))
    resource_id = Column(String(64))
    details = Column(Text)
    created_at = Column(Integer, nullable=False)
    
    def __repr__(self):
        return f"<AuditLog {self.action} by {self.user_id}>"


class VaultVersion(Base):
    """Vault版本历史"""
    __tablename__ = 'vault_versions'
    __table_args__ = (
        Index('idx_vaultver_user', 'user_id', 'version', postgresql_using='btree'),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    version = Column(Integer, nullable=False)
    vault_json = Column(Text, nullable=False)
    vault_bytes = Column(BigInteger, nullable=False)
    created_at = Column(Integer, nullable=False)
    note = Column(Text, default='')
    is_auto = Column(Boolean, default=True)
    
    # 关系
    user = relationship("User", back_populates="vault_versions")
    
    def __repr__(self):
        return f"<VaultVersion {self.user_id} v{self.version}>"


class DocumentVersion(Base):
    """文档版本"""
    __tablename__ = 'document_versions'
    __table_args__ = (
        Index('idx_docver_doc', 'doc_id', 'version', postgresql_using='btree'),
    )
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    doc_id = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False)
    doc_snapshot = Column(Text, nullable=False)
    created_at = Column(Integer, nullable=False)
    change_summary = Column(Text, default='')
    
    # 关系
    user = relationship("User", back_populates="document_versions")
    
    def __repr__(self):
        return f"<DocumentVersion {self.doc_id} v{self.version}>"


class RateLimit(Base):
    """限流表"""
    __tablename__ = 'rate_limit'
    
    ip_addr = Column(String(64), primary_key=True)
    action = Column(String(64), nullable=False)
    count = Column(Integer, default=1)
    window_start = Column(Integer, nullable=False)
    
    def __repr__(self):
        return f"<RateLimit {self.ip_addr}:{self.action}>"
