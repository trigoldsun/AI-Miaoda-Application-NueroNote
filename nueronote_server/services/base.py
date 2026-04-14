#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 基础服务层
所有业务服务的基类，提供通用的数据库操作和错误处理
"""

import logging
from typing import Optional, Dict, Any, List, TypeVar, Generic, Type
from contextlib import contextmanager

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from nueronote_server.db import get_db_session
from nueronote_server.cache import get_cache


logger = logging.getLogger(__name__)

T = TypeVar('T')


class ServiceError(Exception):
    """服务层异常基类"""
    
    def __init__(self, message: str, code: str = None, details: Dict[str, Any] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于API响应）"""
        return {
            'error': self.code or 'SERVICE_ERROR',
            'message': self.message,
            'details': self.details,
        }


class ValidationError(ServiceError):
    """数据验证错误"""
    
    def __init__(self, message: str, field_errors: Dict[str, str] = None):
        super().__init__(message, 'VALIDATION_ERROR')
        self.details['field_errors'] = field_errors or {}


class NotFoundError(ServiceError):
    """资源未找到错误"""
    
    def __init__(self, resource_type: str, resource_id: str):
        message = f"{resource_type} with ID {resource_id} not found"
        super().__init__(message, 'NOT_FOUND')
        self.details['resource_type'] = resource_type
        self.details['resource_id'] = resource_id


class PermissionError(ServiceError):
    """权限错误"""
    
    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(message, 'PERMISSION_ERROR')


class BaseService(Generic[T]):
    """
    基础服务类
    
    提供：
    1. 数据库会话管理
    2. 缓存管理
    3. 错误处理
    4. 通用CRUD操作
    """
    
    def __init__(self, model_class: Type[T]):
        """
        初始化服务
        
        Args:
            model_class: SQLAlchemy模型类
        """
        self.model_class = model_class
        self.cache = get_cache()
        self.table_name = model_class.__tablename__
    
    @contextmanager
    def _db_session(self) -> Session:
        """
        获取数据库会话上下文管理器
        
        Yields:
            SQLAlchemy会话
        """
        with get_db_session() as session:
            yield session
    
    def _cache_key(self, key: str) -> str:
        """
        生成缓存键
        
        Args:
            key: 原始键名
            
        Returns:
            带表名前缀的缓存键
        """
        return f"{self.table_name}:{key}"
    
    def _handle_db_error(self, error: SQLAlchemyError, operation: str) -> ServiceError:
        """
        处理数据库错误
        
        Args:
            error: 数据库异常
            operation: 操作名称
            
        Returns:
            ServiceError异常
        """
        logger.error(f"Database error during {operation}: {error}")
        
        # 根据错误类型返回适当的ServiceError
        error_str = str(error)
        
        if "UNIQUE constraint failed" in error_str:
            return ValidationError(
                f"{self.table_name} already exists",
                {'constraint': 'unique'}
            )
        elif "FOREIGN KEY constraint failed" in error_str:
            return ValidationError(
                f"Referenced resource does not exist",
                {'constraint': 'foreign_key'}
            )
        elif "CHECK constraint failed" in error_str:
            return ValidationError(
                f"Data validation failed",
                {'constraint': 'check'}
            )
        else:
            return ServiceError(
                f"Database error: {error_str}",
                'DATABASE_ERROR'
            )
    
    def get_by_id(self, id: str, use_cache: bool = True) -> Optional[T]:
        """
        根据ID获取记录
        
        Args:
            id: 记录ID
            use_cache: 是否使用缓存
            
        Returns:
            模型实例或None
        """
        cache_key = self._cache_key(f"id:{id}")
        
        # 尝试从缓存获取
        if use_cache and self.cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        
        try:
            with self._db_session() as session:
                instance = session.query(self.model_class).filter_by(id=id).first()
                
                # 存储到缓存
                if instance and use_cache and self.cache:
                    self.cache.set(cache_key, instance, ttl=300)  # 5分钟缓存
                
                return instance
        except SQLAlchemyError as e:
            raise self._handle_db_error(e, f"get_by_id({id})")
    
    def get_by_field(self, field: str, value: Any, use_cache: bool = True) -> Optional[T]:
        """
        根据字段值获取记录
        
        Args:
            field: 字段名
            value: 字段值
            use_cache: 是否使用缓存
            
        Returns:
            模型实例或None
        """
        cache_key = self._cache_key(f"{field}:{value}")
        
        # 尝试从缓存获取
        if use_cache and self.cache:
            cached = self.cache.get(cache_key)
            if cached is not None:
                return cached
        
        try:
            with self._db_session() as session:
                filter_kwargs = {field: value}
                instance = session.query(self.model_class).filter_by(**filter_kwargs).first()
                
                # 存储到缓存
                if instance and use_cache and self.cache:
                    self.cache.set(cache_key, instance, ttl=300)
                
                return instance
        except SQLAlchemyError as e:
            raise self._handle_db_error(e, f"get_by_field({field}={value})")
    
    def create(self, data: Dict[str, Any], validate: bool = True) -> T:
        """
        创建新记录
        
        Args:
            data: 记录数据
            validate: 是否验证数据
            
        Returns:
            创建的模型实例
        """
        if validate:
            self._validate_create_data(data)
        
        try:
            with self._db_session() as session:
                instance = self.model_class(**data)
                session.add(instance)
                session.commit()
                
                # 清除相关缓存
                self._clear_related_cache(instance)
                
                return instance
        except SQLAlchemyError as e:
            session.rollback()
            raise self._handle_db_error(e, f"create")
    
    def update(self, id: str, data: Dict[str, Any], validate: bool = True) -> Optional[T]:
        """
        更新记录
        
        Args:
            id: 记录ID
            data: 更新数据
            validate: 是否验证数据
            
        Returns:
            更新后的模型实例或None（如果记录不存在）
        """
        if validate:
            self._validate_update_data(data)
        
        try:
            with self._db_session() as session:
                instance = session.query(self.model_class).filter_by(id=id).first()
                if not instance:
                    return None
                
                # 更新字段
                for key, value in data.items():
                    if hasattr(instance, key):
                        setattr(instance, key, value)
                
                session.commit()
                
                # 清除缓存
                self._clear_instance_cache(instance)
                
                return instance
        except SQLAlchemyError as e:
            session.rollback()
            raise self._handle_db_error(e, f"update({id})")
    
    def delete(self, id: str) -> bool:
        """
        删除记录
        
        Args:
            id: 记录ID
            
        Returns:
            是否删除成功
        """
        try:
            with self._db_session() as session:
                instance = session.query(self.model_class).filter_by(id=id).first()
                if not instance:
                    return False
                
                # 清除缓存（在删除前）
                self._clear_instance_cache(instance)
                
                session.delete(instance)
                session.commit()
                
                return True
        except SQLAlchemyError as e:
            session.rollback()
            raise self._handle_db_error(e, f"delete({id})")
    
    def list_all(self, limit: int = 100, offset: int = 0) -> List[T]:
        """
        列出所有记录（分页）
        
        Args:
            limit: 每页数量
            offset: 偏移量
            
        Returns:
            记录列表
        """
        try:
            with self._db_session() as session:
                return session.query(self.model_class)\
                    .limit(limit)\
                    .offset(offset)\
                    .all()
        except SQLAlchemyError as e:
            raise self._handle_db_error(e, "list_all")
    
    def count_all(self) -> int:
        """
        统计记录总数
        
        Returns:
            记录总数
        """
        try:
            with self._db_session() as session:
                return session.query(self.model_class).count()
        except SQLAlchemyError as e:
            raise self._handle_db_error(e, "count_all")
    
    def _validate_create_data(self, data: Dict[str, Any]):
        """
        验证创建数据（子类可以重写）
        
        Args:
            data: 创建数据
            
        Raises:
            ValidationError: 如果数据无效
        """
        # 基础验证：检查必需字段
        if hasattr(self.model_class, 'id'):
            # 确保ID不存在
            existing = self.get_by_id(data.get('id'), use_cache=False)
            if existing:
                raise ValidationError(
                    f"{self.table_name} with ID {data.get('id')} already exists",
                    {'id': 'already_exists'}
                )
    
    def _validate_update_data(self, data: Dict[str, Any]):
        """
        验证更新数据（子类可以重写）
        
        Args:
            data: 更新数据
            
        Raises:
            ValidationError: 如果数据无效
        """
        # 基础验证：检查字段是否存在
        for field in data.keys():
            if not hasattr(self.model_class, field):
                raise ValidationError(
                    f"Field '{field}' does not exist in {self.table_name}",
                    {field: 'invalid_field'}
                )
    
    def _clear_instance_cache(self, instance: T):
        """
        清除实例相关缓存
        
        Args:
            instance: 模型实例
        """
        if not self.cache:
            return
        
        # 清除ID缓存
        id_cache_key = self._cache_key(f"id:{instance.id}")
        self.cache.delete(id_cache_key)
        
        # 清除其他可能的缓存键
        # 子类可以重写此方法以清除更多缓存
    
    def _clear_related_cache(self, instance: T):
        """
        清除相关缓存（子类可以重写）
        
        Args:
            instance: 模型实例
        """
        self._clear_instance_cache(instance)
