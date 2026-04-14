#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 数据库适配器工厂
根据配置自动选择合适的数据库适配器，支持企业级数据库
"""

import logging
import re
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

from nueronote_server.db.adapters import DatabaseAdapter
from nueronote_server.db.adapters.postgresql import PostgreSQLAdapter
from nueronote_server.db.adapters.mysql import MySQLAdapter
from nueronote_server.db.adapters.sqlite import SQLiteAdapter
from nueronote_server.config import settings


logger = logging.getLogger(__name__)


class DatabaseAdapterFactory:
    """
    数据库适配器工厂
    
    根据连接URL自动检测数据库类型，创建合适的适配器实例
    支持：PostgreSQL, MySQL, SQLite, 以及未来可能的Oracle, SQL Server
    """
    
    # 数据库URL模式检测
    URL_PATTERNS = {
        'postgresql': [
            r'^postgresql://',
            r'^postgres://',
            r'^postgresql\+psycopg2://',
            r'^postgresql\+pg8000://',
            r'^postgresql\+pygresql://',
        ],
        'mysql': [
            r'^mysql://',
            r'^mysql\+pymysql://',
            r'^mysql\+mysqlconnector://',
            r'^mysql\+oursql://',
            r'^mariadb://',
            r'^mariadb\+pymysql://',
        ],
        'sqlite': [
            r'^sqlite://',
            r'^sqlite\+pysqlite://',
        ],
    }
    
    def __init__(self):
        self._adapters: Dict[str, DatabaseAdapter] = {}
        self._primary_adapter: Optional[DatabaseAdapter] = None
        self._read_replica_adapters: List[DatabaseAdapter] = []
        self._write_replica_adapters: List[DatabaseAdapter] = []
    
    def create_adapter(self, connection_url: str, config: Optional[Dict[str, Any]] = None) -> DatabaseAdapter:
        """
        创建数据库适配器
        
        Args:
            connection_url: 数据库连接URL
            config: 额外配置参数
            
        Returns:
            数据库适配器实例
        """
        if config is None:
            config = {}
        
        # 检测数据库类型
        db_type = self.detect_database_type(connection_url)
        
        # 合并全局配置
        db_config = self._get_database_config()
        db_config.update(config)
        
        # 根据类型创建适配器
        adapter = self._create_adapter_by_type(db_type, connection_url, db_config)
        
        logger.info(f"创建数据库适配器: {db_type} -> {connection_url}")
        
        return adapter
    
    def detect_database_type(self, connection_url: str) -> str:
        """
        根据连接URL检测数据库类型
        
        Args:
            connection_url: 数据库连接URL
            
        Returns:
            数据库类型: postgresql, mysql, sqlite
        """
        # 首先检查配置中指定的类型
        if hasattr(settings, 'database') and hasattr(settings.database, 'database_type'):
            if settings.database.database_type != 'auto':
                return settings.database.database_type.lower()
        
        # 通过URL模式检测
        for db_type, patterns in self.URL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, connection_url, re.IGNORECASE):
                    return db_type
        
        # 默认假设为SQLite
        return 'sqlite'
    
    def _create_adapter_by_type(self, db_type: str, connection_url: str, config: Dict[str, Any]) -> DatabaseAdapter:
        """
        根据类型创建适配器实例
        
        Args:
            db_type: 数据库类型
            connection_url: 连接URL
            config: 配置参数
            
        Returns:
            适配器实例
        """
        # 添加数据库特定配置
        db_config = config.copy()
        
        if db_type == 'postgresql':
            # PostgreSQL特定配置
            db_config.update({
                'ssl_mode': getattr(settings.database, 'ssl_mode', 'prefer'),
                'connect_timeout': getattr(settings.database, 'connect_timeout', 10),
                'application_name': getattr(settings.database, 'postgresql_application_name', 'nueronote'),
                'keepalives': getattr(settings.database, 'postgresql_keepalives', True),
                'keepalives_idle': getattr(settings.database, 'postgresql_keepalives_idle', 30),
            })
            
            # SSL证书配置
            if hasattr(settings.database, 'ssl_cert') and settings.database.ssl_cert:
                db_config['ssl_cert'] = settings.database.ssl_cert
            if hasattr(settings.database, 'ssl_key') and settings.database.ssl_key:
                db_config['ssl_key'] = settings.database.ssl_key
            if hasattr(settings.database, 'ssl_ca') and settings.database.ssl_ca:
                db_config['ssl_ca'] = settings.database.ssl_ca
            
            return PostgreSQLAdapter(connection_url, **db_config)
        
        elif db_type == 'mysql':
            # MySQL特定配置
            db_config.update({
                'ssl_mode': getattr(settings.database, 'ssl_mode', 'PREFERRED').upper(),
                'charset': getattr(settings.database, 'mysql_charset', 'utf8mb4'),
                'collation': getattr(settings.database, 'mysql_collation', 'utf8mb4_unicode_ci'),
                'engine': getattr(settings.database, 'mysql_engine', 'InnoDB'),
                'connect_timeout': getattr(settings.database, 'connect_timeout', 10),
            })
            
            return MySQLAdapter(connection_url, **db_config)
        
        elif db_type == 'sqlite':
            # SQLite特定配置
            db_config.update({
                'cache_size': getattr(settings.database, 'cache_size', 2000),
                'timeout': getattr(settings.database, 'connect_timeout', 30.0),
            })
            
            return SQLiteAdapter(connection_url, **db_config)
        
        else:
            raise ValueError(f"不支持的数据库类型: {db_type}")
    
    def _get_database_config(self) -> Dict[str, Any]:
        """
        获取数据库全局配置
        
        Returns:
            数据库配置字典
        """
        if not hasattr(settings, 'database'):
            return {}
        
        db_config = {}
        
        # 通用配置
        common_fields = [
            'pool_size', 'max_overflow', 'pool_timeout',
            'pool_recycle', 'pool_pre_ping', 'echo',
        ]
        
        for field in common_fields:
            if hasattr(settings.database, field):
                value = getattr(settings.database, field)
                db_config[field] = value
        
        # 超时配置
        if hasattr(settings.database, 'statement_timeout'):
            db_config['statement_timeout'] = settings.database.statement_timeout
        
        if hasattr(settings.database, 'idle_in_transaction_timeout'):
            db_config['idle_in_transaction_timeout'] = settings.database.idle_in_transaction_timeout
        
        # 监控配置
        if hasattr(settings.database, 'monitoring_enabled'):
            db_config['monitoring_enabled'] = settings.database.monitoring_enabled
        
        if hasattr(settings.database, 'slow_query_threshold'):
            db_config['slow_query_threshold'] = settings.database.slow_query_threshold
        
        if hasattr(settings.database, 'log_queries'):
            db_config['log_queries'] = settings.database.log_queries
        
        if hasattr(settings.database, 'log_slow_queries'):
            db_config['log_slow_queries'] = settings.database.log_slow_queries
        
        return db_config
    
    def setup_replication(self) -> None:
        """
        设置数据库复制（读写分离）
        """
        if not hasattr(settings, 'database'):
            return
        
        # 主数据库适配器
        primary_url = settings.database.url
        self._primary_adapter = self.create_adapter(primary_url)
        self._adapters['primary'] = self._primary_adapter
        
        # 只读副本
        if hasattr(settings.database, 'read_replica_urls') and settings.database.read_replica_urls:
            for i, replica_url in enumerate(settings.database.read_replica_urls):
                replica_adapter = self.create_adapter(replica_url)
                self._read_replica_adapters.append(replica_adapter)
                self._adapters[f'read_replica_{i}'] = replica_adapter
            
            logger.info(f"已配置 {len(self._read_replica_adapters)} 个只读副本")
        
        # 写副本
        if hasattr(settings.database, 'write_replica_urls') and settings.database.write_replica_urls:
            for i, replica_url in enumerate(settings.database.write_replica_urls):
                replica_adapter = self.create_adapter(replica_url)
                self._write_replica_adapters.append(replica_adapter)
                self._adapters[f'write_replica_{i}'] = replica_adapter
            
            logger.info(f"已配置 {len(self._write_replica_adapters)} 个写副本")
    
    def get_adapter(self, name: str = 'primary') -> Optional[DatabaseAdapter]:
        """
        获取指定名称的适配器
        
        Args:
            name: 适配器名称（primary, read_replica_0, write_replica_0等）
            
        Returns:
            适配器实例或None
        """
        return self._adapters.get(name)
    
    def get_read_adapter(self, use_replica: bool = True) -> DatabaseAdapter:
        """
        获取读取操作的适配器
        
        Args:
            use_replica: 是否使用只读副本
            
        Returns:
            读取适配器
        """
        if use_replica and self._read_replica_adapters:
            # 简单的轮询负载均衡
            import random
            return random.choice(self._read_replica_adapters)
        
        return self._primary_adapter or self._adapters['primary']
    
    def get_write_adapter(self) -> DatabaseAdapter:
        """
        获取写入操作的适配器
        
        Returns:
            写入适配器
        """
        if self._write_replica_adapters:
            # 如果有写副本，返回第一个
            return self._write_replica_adapters[0]
        
        return self._primary_adapter or self._adapters['primary']
    
    def close_all(self) -> None:
        """
        关闭所有数据库连接
        """
        for name, adapter in self._adapters.items():
            try:
                adapter.close()
                logger.info(f"关闭数据库适配器: {name}")
            except Exception as e:
                logger.error(f"关闭数据库适配器 {name} 失败: {e}")
        
        self._adapters.clear()
        self._primary_adapter = None
        self._read_replica_adapters.clear()
        self._write_replica_adapters.clear()
    
    def health_check(self) -> Dict[str, Any]:
        """
        检查所有数据库连接的健康状态
        
        Returns:
            健康状态报告
        """
        report = {
            'primary': {'connected': False, 'error': None},
            'read_replicas': [],
            'write_replicas': [],
            'overall': 'healthy',
        }
        
        # 检查主数据库
        if self._primary_adapter:
            try:
                connected = self._primary_adapter.test_connection()
                report['primary']['connected'] = connected
                if not connected:
                    report['overall'] = 'degraded'
            except Exception as e:
                report['primary']['error'] = str(e)
                report['overall'] = 'unhealthy'
        
        # 检查只读副本
        for i, adapter in enumerate(self._read_replica_adapters):
            try:
                connected = adapter.test_connection()
                report['read_replicas'].append({
                    'index': i,
                    'connected': connected,
                    'error': None,
                })
                if not connected:
                    report['overall'] = 'degraded'
            except Exception as e:
                report['read_replicas'].append({
                    'index': i,
                    'connected': False,
                    'error': str(e),
                })
                report['overall'] = 'degraded'
        
        # 检查写副本
        for i, adapter in enumerate(self._write_replica_adapters):
            try:
                connected = adapter.test_connection()
                report['write_replicas'].append({
                    'index': i,
                    'connected': connected,
                    'error': None,
                })
                if not connected:
                    report['overall'] = 'degraded'
            except Exception as e:
                report['write_replicas'].append({
                    'index': i,
                    'connected': False,
                    'error': str(e),
                })
                report['overall'] = 'degraded'
        
        return report


# 全局工厂实例
_factory_instance: Optional[DatabaseAdapterFactory] = None


def get_factory() -> DatabaseAdapterFactory:
    """
    获取数据库适配器工厂实例（单例）
    
    Returns:
        DatabaseAdapterFactory实例
    """
    global _factory_instance
    if _factory_instance is None:
        _factory_instance = DatabaseAdapterFactory()
    return _factory_instance


def init_database_factory() -> DatabaseAdapterFactory:
    """
    初始化数据库适配器工厂
    
    Returns:
        初始化后的工厂实例
    """
    factory = get_factory()
    factory.setup_replication()
    
    # 测试连接
    health = factory.health_check()
    if health['overall'] == 'healthy':
        logger.info("数据库适配器工厂初始化成功")
    elif health['overall'] == 'degraded':
        logger.warning("数据库适配器工厂初始化完成，但有副本连接失败")
    else:
        logger.error("数据库适配器工厂初始化失败，主数据库连接失败")
    
    return factory


def close_database_factory() -> None:
    """
    关闭数据库适配器工厂
    """
    global _factory_instance
    if _factory_instance:
        _factory_instance.close_all()
        _factory_instance = None
        logger.info("数据库适配器工厂已关闭")
