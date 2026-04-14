#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote Redis 缓存模块
支持多级缓存、连接池、自动重连
"""

import json
import logging
import pickle
from typing import Optional, Any, Union, List, Dict, Tuple
from datetime import timedelta
from contextlib import contextmanager

import redis
from redis.exceptions import ConnectionError, TimeoutError, RedisError

from nueronote_server.config import settings


logger = logging.getLogger(__name__)


class RedisCache:
    """
    Redis缓存客户端封装
    
    特性：
    1. 连接池管理
    2. 自动重连
    3. 序列化/反序列化
    4. 命名空间支持
    5. 统计监控
    """
    
    def __init__(self, namespace: str = "nueronote"):
        """
        初始化Redis缓存
        
        Args:
            namespace: 缓存键名前缀
        """
        self.namespace = namespace
        self._client: Optional[redis.Redis] = None
        self._stats = {
            'hits': 0,
            'misses': 0,
            'errors': 0,
            'connections': 0,
        }
    
    def _get_client(self) -> redis.Redis:
        """
        获取Redis客户端（延迟初始化）
        
        Returns:
            redis.Redis客户端实例
        """
        if self._client is None:
            if not settings.redis.enabled:
                raise RuntimeError("Redis缓存未启用")
            
            try:
                # 解析Redis URL
                redis_url = settings.redis.url
                
                # 创建连接池
                pool = redis.ConnectionPool.from_url(
                    redis_url,
                    max_connections=settings.redis.max_connections,
                    socket_timeout=settings.redis.socket_timeout,
                    socket_connect_timeout=settings.redis.socket_connect_timeout,
                    socket_keepalive=settings.redis.socket_keepalive,
                    health_check_interval=settings.redis.health_check_interval,
                    retry_on_timeout=True,
                )
                
                self._client = redis.Redis(
                    connection_pool=pool,
                    decode_responses=False,  # 返回bytes，便于自定义序列化
                )
                
                # 测试连接
                self._client.ping()
                self._stats['connections'] += 1
                logger.info(f"Redis连接成功: {redis_url}")
                
            except Exception as e:
                logger.error(f"Redis连接失败: {e}")
                raise
        
        return self._client
    
    @property
    def client(self) -> redis.Redis:
        """获取Redis客户端"""
        return self._get_client()
    
    def _make_key(self, key: str) -> str:
        """
        生成带命名空间的键名
        
        Args:
            key: 原始键名
            
        Returns:
            带命名空间的键名
        """
        return f"{self.namespace}:{key}"
    
    def _serialize(self, value: Any) -> bytes:
        """
        序列化值
        
        Args:
            value: 要序列化的值
            
        Returns:
            序列化后的字节
        """
        # 尝试JSON序列化（对简单类型更高效）
        try:
            return json.dumps(value).encode('utf-8')
        except (TypeError, ValueError):
            # 复杂类型使用pickle
            return pickle.dumps(value)
    
    def _deserialize(self, data: bytes) -> Any:
        """
        反序列化值
        
        Args:
            data: 序列化的字节
            
        Returns:
            反序列化的值
        """
        if data is None:
            return None
        
        try:
            # 先尝试JSON反序列化
            return json.loads(data.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            # 回退到pickle
            try:
                return pickle.loads(data)
            except pickle.UnpicklingError:
                # 如果都失败，返回原始字节
                return data
    
    @contextmanager
    def _safe_operation(self):
        """
        安全的Redis操作上下文
        自动处理连接异常和重试
        """
        try:
            yield
        except (ConnectionError, TimeoutError) as e:
            self._stats['errors'] += 1
            logger.warning(f"Redis操作失败，尝试重连: {e}")
            
            # 关闭旧连接
            if self._client:
                try:
                    self._client.close()
                except:
                    pass
                self._client = None
            
            # 重试一次
            try:
                self._get_client()
                yield
            except Exception as retry_e:
                logger.error(f"Redis重连失败: {retry_e}")
                raise
        except RedisError as e:
            self._stats['errors'] += 1
            logger.error(f"Redis操作错误: {e}")
            raise
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            default: 默认值
            
        Returns:
            缓存值或默认值
        """
        cache_key = self._make_key(key)
        
        with self._safe_operation():
            data = self.client.get(cache_key)
            
            if data is None:
                self._stats['misses'] += 1
                return default
            
            self._stats['hits'] += 1
            return self._deserialize(data)
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间（秒），None表示永不过期
            
        Returns:
            是否设置成功
        """
        cache_key = self._make_key(key)
        serialized = self._serialize(value)
        
        with self._safe_operation():
            if ttl is not None and ttl > 0:
                return bool(self.client.setex(cache_key, ttl, serialized))
            else:
                return bool(self.client.set(cache_key, serialized))
    
    def delete(self, key: str) -> bool:
        """
        删除缓存键
        
        Args:
            key: 缓存键
            
        Returns:
            是否删除成功
        """
        cache_key = self._make_key(key)
        
        with self._safe_operation():
            return bool(self.client.delete(cache_key))
    
    def exists(self, key: str) -> bool:
        """
        检查键是否存在
        
        Args:
            key: 缓存键
            
        Returns:
            是否存在
        """
        cache_key = self._make_key(key)
        
        with self._safe_operation():
            return bool(self.client.exists(cache_key))
    
    def expire(self, key: str, ttl: int) -> bool:
        """
        设置键的过期时间
        
        Args:
            key: 缓存键
            ttl: 过期时间（秒）
            
        Returns:
            是否设置成功
        """
        cache_key = self._make_key(key)
        
        with self._safe_operation():
            return bool(self.client.expire(cache_key, ttl))
    
    def incr(self, key: str, amount: int = 1) -> int:
        """
        递增计数器
        
        Args:
            key: 缓存键
            amount: 递增数量
            
        Returns:
            递增后的值
        """
        cache_key = self._make_key(key)
        
        with self._safe_operation():
            return self.client.incrby(cache_key, amount)
    
    def decr(self, key: str, amount: int = 1) -> int:
        """
        递减计数器
        
        Args:
            key: 缓存键
            amount: 递减数量
            
        Returns:
            递减后的值
        """
        cache_key = self._make_key(key)
        
        with self._safe_operation():
            return self.client.decrby(cache_key, amount)
    
    def get_or_set(self, key: str, default_func, ttl: Optional[int] = None) -> Any:
        """
        获取或设置缓存值（缓存穿透保护）
        
        Args:
            key: 缓存键
            default_func: 默认值生成函数
            ttl: 过期时间（秒）
            
        Returns:
            缓存值
        """
        # 先尝试获取
        value = self.get(key)
        if value is not None:
            return value
        
        # 缓存未命中，调用函数生成值
        value = default_func()
        
        # 设置缓存
        if value is not None:
            self.set(key, value, ttl)
        
        return value
    
    def clear_namespace(self, pattern: str = "*") -> int:
        """
        清空命名空间下的所有键
        
        Args:
            pattern: 匹配模式
            
        Returns:
            删除的键数量
        """
        namespace_pattern = self._make_key(pattern)
        
        with self._safe_operation():
            keys = self.client.keys(namespace_pattern)
            if keys:
                return self.client.delete(*keys)
            return 0
    
    def get_stats(self) -> Dict[str, int]:
        """
        获取缓存统计信息
        
        Returns:
            统计信息字典
        """
        return self._stats.copy()
    
    def close(self):
        """
        关闭Redis连接
        """
        if self._client:
            try:
                self._client.close()
                logger.info("Redis连接已关闭")
            except:
                pass
            self._client = None


# 全局缓存实例
_cache_instance: Optional[RedisCache] = None


def get_cache() -> RedisCache:
    """
    获取缓存实例（单例）
    
    Returns:
        RedisCache实例
    """
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = RedisCache()
    return _cache_instance


def init_cache() -> Optional[RedisCache]:
    """
    初始化缓存（测试连接）
    
    Returns:
        缓存实例或None（如果未启用）
    """
    if not settings.redis.enabled:
        logger.warning("Redis缓存未启用，使用内存缓存或直接数据库访问")
        return None
    
    try:
        cache = get_cache()
        # 测试连接
        cache.client.ping()
        logger.info("Redis缓存初始化成功")
        return cache
    except Exception as e:
        logger.error(f"Redis缓存初始化失败: {e}")
        return None


def close_cache():
    """
    关闭缓存连接
    """
    global _cache_instance
    if _cache_instance:
        _cache_instance.close()
        _cache_instance = None
