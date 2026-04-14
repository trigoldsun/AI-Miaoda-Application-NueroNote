#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 缓存模块
提供Redis缓存支持，降级策略为内存缓存。
"""

import json
import time
from typing import Any, Optional, Callable
from functools import wraps

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


class CacheManager:
    """缓存管理器"""
    
    def __init__(self, redis_url: Optional[str] = None, 
                 default_ttl: int = 300,
                 enabled: bool = True):
        """
        初始化缓存管理器
        
        Args:
            redis_url: Redis连接URL
            default_ttl: 默认TTL（秒）
            enabled: 是否启用缓存
        """
        self.redis_url = redis_url
        self.default_ttl = default_ttl
        self.enabled = enabled and REDIS_AVAILABLE
        self._client: Optional['redis.Redis'] = None
        self._memory_cache: dict = {}
        self._memory_expiry: dict = {}
    
    @property
    def client(self) -> Optional['redis.Redis']:
        """获取Redis客户端"""
        if not self.enabled:
            return None
        
        if self._client is None and self.redis_url:
            try:
                self._client = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    socket_connect_timeout=5
                )
                self._client.ping()  # 测试连接
            except Exception:
                self._client = None
                self.enabled = False
        
        return self._client
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            default: 默认值
            
        Returns:
            缓存值或默认值
        """
        # 检查内存缓存
        if key in self._memory_expiry:
            if time.time() < self._memory_expiry[key]:
                return self._memory_cache.get(key, default)
            else:
                del self._memory_cache[key]
                del self._memory_expiry[key]
        
        # 检查Redis
        if self.client:
            try:
                value = self.client.get(key)
                if value is not None:
                    return json.loads(value)
            except Exception:
                pass
        
        return default
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: TTL（秒），None使用默认值
            
        Returns:
            是否设置成功
        """
        ttl = ttl or self.default_ttl
        
        # 设置内存缓存
        self._memory_cache[key] = value
        self._memory_expiry[key] = time.time() + ttl
        
        # 设置Redis
        if self.client:
            try:
                serialized = json.dumps(value)
                self.client.setex(key, ttl, serialized)
                return True
            except Exception:
                return False
        
        return True
    
    def delete(self, key: str) -> bool:
        """
        删除缓存
        
        Args:
            key: 缓存键
            
        Returns:
            是否删除成功
        """
        # 删除内存缓存
        self._memory_cache.pop(key, None)
        self._memory_expiry.pop(key, None)
        
        # 删除Redis
        if self.client:
            try:
                self.client.delete(key)
            except Exception:
                pass
        
        return True
    
    def clear(self, pattern: str = "*") -> int:
        """
        清除匹配的缓存
        
        Args:
            pattern: 键匹配模式
            
        Returns:
            清除的键数量
        """
        count = 0
        
        # 清除内存缓存
        keys_to_delete = [k for k in self._memory_cache.keys() 
                         if self._matches_pattern(k, pattern)]
        for key in keys_to_delete:
            del self._memory_cache[key]
            del self._memory_expiry[key]
            count += 1
        
        # 清除Redis
        if self.client:
            try:
                for key in self.client.scan_iter(pattern):
                    self.client.delete(key)
                    count += 1
            except Exception:
                pass
        
        return count
    
    def _matches_pattern(self, key: str, pattern: str) -> bool:
        """检查键是否匹配模式"""
        if pattern == "*":
            return True
        if pattern.endswith("*"):
            return key.startswith(pattern[:-1])
        return key == pattern
    
    def get_many(self, keys: list) -> dict:
        """
        批量获取缓存
        
        Args:
            keys: 缓存键列表
            
        Returns:
            键值对字典
        """
        result = {}
        for key in keys:
            value = self.get(key)
            if value is not None:
                result[key] = value
        return result
    
    def set_many(self, mapping: dict, ttl: Optional[int] = None) -> bool:
        """
        批量设置缓存
        
        Args:
            mapping: 键值对字典
            ttl: TTL（秒）
            
        Returns:
            是否设置成功
        """
        for key, value in mapping.items():
            self.set(key, value, ttl)
        return True
    
    def increment(self, key: str, delta: int = 1) -> Optional[int]:
        """
        递增缓存值
        
        Args:
            key: 缓存键
            delta: 增量
            
        Returns:
            递增后的值，失败返回None
        """
        # Redis递增
        if self.client:
            try:
                return self.client.incrby(key, delta)
            except Exception:
                pass
        return None
    
    def decrement(self, key: str, delta: int = 1) -> Optional[int]:
        """
        递减缓存值
        
        Args:
            key: 缓存键
            delta: 减量
            
        Returns:
            递减后的值，失败返回None
        """
        if self.client:
            try:
                return self.client.decrby(key, delta)
            except Exception:
                pass
        return None
    
    def exists(self, key: str) -> bool:
        """
        检查键是否存在
        
        Args:
            key: 缓存键
            
        Returns:
            是否存在
        """
        # 检查内存缓存
        if key in self._memory_expiry:
            if time.time() < self._memory_expiry[key]:
                return True
        
        # 检查Redis
        if self.client:
            try:
                return bool(self.client.exists(key))
            except Exception:
                pass
        
        return False
    
    def ttl(self, key: str) -> int:
        """
        获取键的剩余TTL
        
        Args:
            key: 缓存键
            
        Returns:
            剩余秒数，-1表示永久，-2表示不存在
        """
        # 检查内存缓存
        if key in self._memory_expiry:
            remaining = self._memory_expiry[key] - time.time()
            if remaining > 0:
                return int(remaining)
            return -2
        
        # 检查Redis
        if self.client:
            try:
                return self.client.ttl(key)
            except Exception:
                pass
        
        return -2
    
    def close(self) -> None:
        """关闭缓存连接"""
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None


# 全局缓存实例
_cache_instance: Optional[CacheManager] = None


def get_cache() -> CacheManager:
    """获取缓存实例（单例）"""
    global _cache_instance
    if _cache_instance is None:
        from nueronote_server.config import settings
        
        redis_url = None
        if settings.redis.enabled:
            redis_url = getattr(settings.redis, 'url', None)
        
        _cache_instance = CacheManager(
            redis_url=redis_url,
            default_ttl=300,
            enabled=settings.redis.enabled
        )
    return _cache_instance


def init_cache() -> Optional[CacheManager]:
    """初始化缓存"""
    cache = get_cache()
    if cache.enabled and not cache.client:
        print("警告: Redis缓存初始化失败，将使用内存缓存")
    return cache


def close_cache() -> None:
    """关闭缓存"""
    global _cache_instance
    if _cache_instance:
        _cache_instance.close()
        _cache_instance = None


def cached(ttl: int = 300, key_prefix: str = ""):
    """
    缓存装饰器
    
    Args:
        ttl: TTL（秒）
        key_prefix: 键前缀
        
    Usage:
        @cached(ttl=60, key_prefix="user")
        def get_user(user_id):
            return database.query(user_id)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # 生成缓存键
            cache_key = f"{key_prefix}:{func.__name__}"
            if args:
                cache_key += f":{':'.join(str(a) for a in args)}"
            if kwargs:
                cache_key += f":{':'.join(f'{k}={v}' for k, v in kwargs.items())}"
            
            # 尝试从缓存获取
            cache = get_cache()
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # 执行函数
            result = func(*args, **kwargs)
            
            # 缓存结果
            cache.set(cache_key, result, ttl)
            
            return result
        
        return wrapper
    return decorator


def invalidate_cache(pattern: str = "*") -> int:
    """
    使缓存失效
    
    Args:
        pattern: 键匹配模式
        
    Returns:
        失效的键数量
    """
    cache = get_cache()
    return cache.clear(pattern)
