#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 统一数据库管理器
基于适配器工厂支持多数据库：PostgreSQL、MySQL、SQLite等
支持读写分离、连接池、SSL/TLS、监控等高并发企业级特性
"""

import os
import logging
from typing import Optional, Dict, Any, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, scoped_session
from sqlalchemy.engine import Engine

from nueronote_server.config import settings
from nueronote_server.db.factory import DatabaseAdapterFactory, get_factory, init_database_factory, close_database_factory
from nueronote_server.db.adapters import DatabaseAdapter

logger = logging.getLogger(__name__)


# 全局适配器工厂
_adapter_factory: Optional[DatabaseAdapterFactory] = None


def get_adapter_factory() -> DatabaseAdapterFactory:
    """
    获取数据库适配器工厂（单例）
    
    Returns:
        DatabaseAdapterFactory 实例
    """
    global _adapter_factory
    if _adapter_factory is None:
        _adapter_factory = init_database_factory()
    return _adapter_factory


def get_primary_adapter() -> DatabaseAdapter:
    """
    获取主数据库适配器
    
    Returns:
        主数据库适配器实例
    """
    factory = get_adapter_factory()
    return factory.get_adapter('primary')


def get_read_adapter(use_replica: bool = True) -> DatabaseAdapter:
    """
    获取读取操作的适配器
    
    Args:
        use_replica: 是否使用只读副本（默认True）
        
    Returns:
        读取适配器实例
    """
    factory = get_adapter_factory()
    return factory.get_read_adapter(use_replica)


def get_write_adapter() -> DatabaseAdapter:
    """
    获取写入操作的适配器
    
    Returns:
        写入适配器实例
    """
    factory = get_adapter_factory()
    return factory.get_write_adapter()


# ====== 向后兼容接口 ======


def get_engine() -> Engine:
    """
    获取数据库引擎（向后兼容）
    注意：此函数返回主数据库的引擎
    
    Returns:
        SQLAlchemy 引擎实例
    """
    adapter = get_primary_adapter()
    return adapter.get_engine()


def create_database_engine() -> Engine:
    """
    创建数据库引擎（向后兼容）
    注意：此函数返回主数据库的引擎
    
    Returns:
        SQLAlchemy 引擎实例
    """
    return get_engine()


def get_session_factory() -> sessionmaker:
    """
    获取会话工厂（向后兼容）
    
    Returns:
        SQLAlchemy sessionmaker
    """
    # 使用主数据库的会话工厂
    adapter = get_primary_adapter()
    engine = adapter.get_engine()
    
    return sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )


def get_scoped_session() -> scoped_session:
    """
    获取线程安全的scoped session（用于Web应用）
    
    Returns:
        scoped_session 实例
    """
    factory = get_session_factory()
    return scoped_session(factory)


@contextmanager
def get_db_session() -> Iterator[Session]:
    """
    获取数据库会话上下文管理器
    
    Yields:
        SQLAlchemy Session
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_read_session(use_replica: bool = True) -> Iterator[Session]:
    """
    获取只读数据库会话（支持读写分离）
    
    Args:
        use_replica: 是否使用只读副本（默认True）
        
    Yields:
        SQLAlchemy Session
    """
    adapter = get_read_adapter(use_replica)
    engine = adapter.get_engine()
    
    session_factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_write_session() -> Iterator[Session]:
    """
    获取写入数据库会话（支持读写分离）
    
    Yields:
        SQLAlchemy Session
    """
    adapter = get_write_adapter()
    engine = adapter.get_engine()
    
    session_factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_database() -> None:
    """
    初始化数据库（创建所有表）
    在所有配置的数据库上创建表
    """
    from nueronote_server.db.models import Base
    
    factory = get_adapter_factory()
    
    # 在所有适配器上创建表
    for name, adapter in factory._adapters.items():
        try:
            engine = adapter.get_engine()
            Base.metadata.create_all(bind=engine)
            logger.info(f"在适配器 '{name}' 上创建表成功")
        except Exception as e:
            logger.error(f"在适配器 '{name}' 上创建表失败: {e}")
            raise
    
    logger.info("数据库初始化完成")


def create_tables() -> None:
    """创建表的别名（兼容性）"""
    init_database()


def drop_tables() -> None:
    """
    删除所有表（仅用于测试）
    """
    from nueronote_server.db.models import Base
    
    factory = get_adapter_factory()
    
    # 在所有适配器上删除表
    for name, adapter in factory._adapters.items():
        try:
            engine = adapter.get_engine()
            Base.metadata.drop_all(bind=engine)
            logger.info(f"在适配器 '{name}' 上删除表成功")
        except Exception as e:
            logger.error(f"在适配器 '{name}' 上删除表失败: {e}")


def health_check() -> Dict[str, Any]:
    """
    数据库健康检查
    
    Returns:
        健康状态报告
    """
    factory = get_adapter_factory()
    return factory.health_check()


def close_database() -> None:
    """
    关闭所有数据库连接
    """
    close_database_factory()
    global _adapter_factory
    _adapter_factory = None
    logger.info("数据库连接已关闭")
