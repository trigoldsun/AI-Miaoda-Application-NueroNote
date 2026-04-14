#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 数据库适配器基类
定义统一的数据库操作接口，支持多种企业级数据库
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Tuple
from contextlib import contextmanager

from sqlalchemy import create_engine, Engine, text
from sqlalchemy.orm import sessionmaker, Session, scoped_session
from sqlalchemy.pool import QueuePool, StaticPool, NullPool
from sqlalchemy.exc import SQLAlchemyError, OperationalError

# 具体适配器在工厂中动态导入，避免循环导入
# 这里只导出基类

__all__ = [
    'DatabaseAdapter',
]

logger = logging.getLogger(__name__)


class DatabaseAdapter(ABC):
    """
    数据库适配器抽象基类
    
    定义所有数据库适配器必须实现的接口
    支持：PostgreSQL, MySQL, SQLite, Oracle, SQL Server等
    """
    
    def __init__(self, connection_url: str, **kwargs):
        """
        初始化数据库适配器
        
        Args:
            connection_url: 数据库连接URL
            **kwargs: 额外配置参数
        """
        self.connection_url = connection_url
        self.config = kwargs
        
        # 数据库引擎
        self._engine: Optional[Engine] = None
        self._session_factory: Optional[sessionmaker] = None
        self._scoped_session: Optional[scoped_session] = None
        
        # 连接池统计
        self.pool_size = kwargs.get('pool_size', 5)
        self.max_overflow = kwargs.get('max_overflow', 10)
        self.pool_timeout = kwargs.get('pool_timeout', 30)
        self.pool_recycle = kwargs.get('pool_recycle', 3600)
        self.pool_pre_ping = kwargs.get('pool_pre_ping', True)
        self.echo = kwargs.get('echo', False)
    
    @property
    @abstractmethod
    def dialect(self) -> str:
        """
        数据库方言名称
        
        Returns:
            方言名称，如 'postgresql', 'mysql', 'sqlite'
        """
        pass
    
    @property
    @abstractmethod
    def supports_transactions(self) -> bool:
        """
        是否支持事务
        
        Returns:
            True 如果支持事务
        """
        pass
    
    @property
    @abstractmethod
    def supports_json(self) -> bool:
        """
        是否支持JSON类型
        
        Returns:
            True 如果支持JSON
        """
        pass
    
    @property
    @abstractmethod
    def supports_full_text_search(self) -> bool:
        """
        是否支持全文搜索
        
        Returns:
            True 如果支持全文搜索
        """
        pass
    
    @property
    @abstractmethod
    def default_isolation_level(self) -> str:
        """
        默认事务隔离级别
        
        Returns:
            隔离级别，如 'READ COMMITTED', 'REPEATABLE READ'
        """
        pass
    
    @abstractmethod
    def create_engine(self) -> Engine:
        """
        创建SQLAlchemy引擎
        
        Returns:
            SQLAlchemy引擎实例
        """
        pass
    
    @abstractmethod
    def get_connection_pool_config(self) -> Dict[str, Any]:
        """
        获取连接池配置
        
        Returns:
            连接池配置字典
        """
        pass
    
    @abstractmethod
    def get_connect_args(self) -> Dict[str, Any]:
        """
        获取连接参数
        
        Returns:
            连接参数字典
        """
        pass
    
    @abstractmethod
    def test_connection(self, timeout: int = 5) -> bool:
        """
        测试数据库连接
        
        Args:
            timeout: 超时时间（秒）
            
        Returns:
            True 如果连接成功
        """
        pass
    
    @abstractmethod
    def get_database_info(self) -> Dict[str, Any]:
        """
        获取数据库信息
        
        Returns:
            数据库信息字典（版本、字符集、大小等）
        """
        pass
    
    @abstractmethod
    def get_table_size(self, table_name: str) -> int:
        """
        获取表大小（字节）
        
        Args:
            table_name: 表名
            
        Returns:
            表大小（字节）
        """
        pass
    
    @abstractmethod
    def get_index_info(self, table_name: str) -> List[Dict[str, Any]]:
        """
        获取表索引信息
        
        Args:
            table_name: 表名
            
        Returns:
            索引信息列表
        """
        pass
    
    def get_engine(self) -> Engine:
        """
        获取数据库引擎（单例）
        
        Returns:
            SQLAlchemy引擎实例
        """
        if self._engine is None:
            self._engine = self.create_engine()
        return self._engine
    
    def get_session_factory(self) -> sessionmaker:
        """
        获取会话工厂（单例）
        
        Returns:
            SQLAlchemy sessionmaker
        """
        if self._session_factory is None:
            engine = self.get_engine()
            self._session_factory = sessionmaker(
                bind=engine,
                autocommit=False,
                autoflush=False,
                expire_on_commit=False,
            )
        return self._session_factory
    
    def get_scoped_session(self) -> scoped_session:
        """
        获取线程安全的scoped session
        
        Returns:
            scoped_session实例
        """
        if self._scoped_session is None:
            factory = self.get_session_factory()
            self._scoped_session = scoped_session(factory)
        return self._scoped_session
    
    @contextmanager
    def get_session(self) -> Session:
        """
        获取数据库会话上下文管理器
        
        Yields:
            SQLAlchemy Session
        """
        session = self.get_session_factory()()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    
    def execute_raw_sql(self, sql: str, params: Dict[str, Any] = None) -> Any:
        """
        执行原始SQL查询
        
        Args:
            sql: SQL语句
            params: 参数
            
        Returns:
            查询结果
        """
        with self.get_session() as session:
            result = session.execute(text(sql), params or {})
            return result.fetchall()
    
    def create_table(self, table_name: str, columns: Dict[str, str], 
                     constraints: List[str] = None, if_not_exists: bool = True) -> bool:
        """
        创建表
        
        Args:
            table_name: 表名
            columns: 列定义字典 {列名: 数据类型}
            constraints: 约束列表
            if_not_exists: 如果表不存在则创建
            
        Returns:
            True 如果成功
        """
        # 生成SQL语句
        columns_sql = []
        for name, data_type in columns.items():
            columns_sql.append(f"{name} {data_type}")
        
        if constraints:
            columns_sql.extend(constraints)
        
        columns_str = ", ".join(columns_sql)
        
        if if_not_exists:
            sql = f"CREATE TABLE IF NOT EXISTS {table_name} ({columns_str})"
        else:
            sql = f"CREATE TABLE {table_name} ({columns_str})"
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"创建表失败: {e}")
            return False
    
    def add_index(self, table_name: str, column_name: str, 
                  index_name: Optional[str] = None, unique: bool = False) -> bool:
        """
        添加索引
        
        Args:
            table_name: 表名
            column_name: 列名
            index_name: 索引名（可选）
            unique: 是否唯一索引
            
        Returns:
            True 如果成功
        """
        if not index_name:
            index_name = f"idx_{table_name}_{column_name}"
        
        unique_str = "UNIQUE " if unique else ""
        sql = f"CREATE {unique_str}INDEX {index_name} ON {table_name} ({column_name})"
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"创建索引失败: {e}")
            return False
    
    def vacuum(self, table_name: Optional[str] = None) -> bool:
        """
        执行VACUUM（清理未用空间）
        
        Args:
            table_name: 表名（可选，为None时清理整个数据库）
            
        Returns:
            True 如果成功
        """
        if table_name:
            sql = f"VACUUM {table_name}"
        else:
            sql = "VACUUM"
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"执行VACUUM失败: {e}")
            return False
    
    def analyze(self, table_name: Optional[str] = None) -> bool:
        """
        分析表和索引统计信息
        
        Args:
            table_name: 表名（可选，为None时分析整个数据库）
            
        Returns:
            True 如果成功
        """
        if table_name:
            sql = f"ANALYZE {table_name}"
        else:
            sql = "ANALYZE"
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"执行ANALYZE失败: {e}")
            return False
    
    def get_query_plan(self, sql: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        获取查询执行计划
        
        Args:
            sql: SQL语句
            params: 参数
            
        Returns:
            执行计划信息
        """
        # 不同数据库有不同的执行计划命令
        explain_sql = self._get_explain_sql(sql)
        
        try:
            result = self.execute_raw_sql(explain_sql, params)
            
            # 解析执行计划
            return self._parse_query_plan(result)
        except SQLAlchemyError as e:
            logger.error(f"获取执行计划失败: {e}")
            return {'error': str(e)}
    
    @abstractmethod
    def _get_explain_sql(self, sql: str) -> str:
        """
        生成EXPLAIN SQL语句
        
        Args:
            sql: 原始SQL
            
        Returns:
            EXPLAIN SQL语句
        """
        pass
    
    @abstractmethod
    def _parse_query_plan(self, result: Any) -> Dict[str, Any]:
        """
        解析执行计划结果
        
        Args:
            result: 执行计划查询结果
            
        Returns:
            结构化的执行计划信息
        """
        pass
    
    def close(self) -> None:
        """
        关闭数据库连接
        """
        if self._engine:
            self._engine.dispose()
            self._engine = None
        
        self._session_factory = None
        self._scoped_session = None
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()
    
    def __repr__(self) -> str:
        """字符串表示"""
        return f"<DatabaseAdapter dialect={self.dialect} url={self.connection_url}>"
