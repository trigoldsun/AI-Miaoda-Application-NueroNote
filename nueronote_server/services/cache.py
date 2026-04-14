#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 缓存服务模块
提供用户信息缓存、Vault元数据缓存、会话缓存等功能。
"""

import hashlib
import json
import time
from functools import wraps
from typing import Any, Callable, Optional

# 缓存键前缀
CACHE_PREFIX_USER = "user:"
CACHE_PREFIX_VAULT = "vault:"
CACHE_PREFIX_TOKEN = "token:"
CACHE_PREFIX_RATE = "rate:"
CACHE_PREFIX_SESSION = "session:"


class CacheService:
    """缓存服务"""
    
    def __init__(self, cache_manager=None):
        """
        初始化缓存服务
        
        Args:
            cache_manager: CacheManager实例，如果为None则使用内存缓存
        """
        self.cache = cache_manager
        self._memory_store = {}  # 降级用的内存存储
        self._memory_expiry = {}
    
    def _get_cache(self):
        """获取缓存管理器"""
        if self.cache:
            return self.cache
        return self
    
    def _safe_get(self, key: str, default: Any = None) -> Any:
        """安全获取缓存"""
        cache = self._get_cache()
        if cache is self:
            # 使用内存存储
            if key in self._memory_expiry:
                if time.time() < self._memory_expiry[key]:
                    return self._memory_store.get(key, default)
                else:
                    del self._memory_store[key]
                    del self._memory_expiry[key]
            return default
        else:
            return cache.get(key, default)
    
    def _safe_set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """安全设置缓存"""
        cache = self._get_cache()
        if cache is self:
            self._memory_store[key] = value
            self._memory_expiry[key] = time.time() + ttl
            return True
        else:
            return cache.set(key, value, ttl)
    
    def _safe_delete(self, key: str) -> bool:
        """安全删除缓存"""
        cache = self._get_cache()
        if cache is self:
            self._memory_store.pop(key, None)
            self._memory_expiry.pop(key, None)
            return True
        else:
            return cache.delete(key)
    
    # ==================== 用户缓存 ====================
    
    def get_user(self, user_id: str) -> Optional[dict]:
        """获取用户缓存"""
        key = f"{CACHE_PREFIX_USER}{user_id}"
        return self._safe_get(key)
    
    def set_user(self, user_id: str, user_data: dict, ttl: int = 300) -> bool:
        """设置用户缓存"""
        key = f"{CACHE_PREFIX_USER}{user_id}"
        return self._safe_set(key, user_data, ttl)
    
    def invalidate_user(self, user_id: str) -> bool:
        """使用户缓存失效"""
        key = f"{CACHE_PREFIX_USER}{user_id}"
        return self._safe_delete(key)
    
    # ==================== Vault缓存 ====================
    
    def get_vault(self, user_id: str) -> Optional[dict]:
        """获取Vault缓存"""
        key = f"{CACHE_PREFIX_VAULT}{user_id}"
        return self._safe_get(key)
    
    def set_vault(self, user_id: str, vault_data: dict, ttl: int = 60) -> bool:
        """设置Vault缓存"""
        key = f"{CACHE_PREFIX_VAULT}{user_id}"
        return self._safe_set(key, vault_data, ttl)
    
    def invalidate_vault(self, user_id: str) -> bool:
        """使Vault缓存失效"""
        key = f"{CACHE_PREFIX_VAULT}{user_id}"
        return self._safe_delete(key)
    
    # ==================== Token缓存 ====================
    
    def get_token(self, token: str) -> Optional[str]:
        """获取Token黑名单/有效性"""
        key = f"{CACHE_PREFIX_TOKEN}{self._hash_token(token)}"
        return self._safe_get(key)
    
    def set_token_revoked(self, token: str, ttl: int = 86400) -> bool:
        """标记Token为已撤销"""
        key = f"{CACHE_PREFIX_TOKEN}{self._hash_token(token)}"
        return self._safe_set(key, "revoked", ttl)
    
    def is_token_revoked(self, token: str) -> bool:
        """检查Token是否已撤销"""
        key = f"{CACHE_PREFIX_TOKEN}{self._hash_token(token)}"
        return self._safe_get(key) == "revoked"
    
    def _hash_token(self, token: str) -> str:
        """Token哈希"""
        return hashlib.sha256(token.encode()).hexdigest()[:16]
    
    # ==================== 会话缓存 ====================
    
    def get_session(self, session_id: str) -> Optional[dict]:
        """获取会话数据"""
        key = f"{CACHE_PREFIX_SESSION}{session_id}"
        return self._safe_get(key)
    
    def set_session(self, session_id: str, session_data: dict, 
                   ttl: int = 3600) -> bool:
        """设置会话数据"""
        key = f"{CACHE_PREFIX_SESSION}{session_id}"
        return self._safe_set(key, session_data, ttl)
    
    def invalidate_session(self, session_id: str) -> bool:
        """使会话失效"""
        key = f"{CACHE_PREFIX_SESSION}{session_id}"
        return self._safe_delete(key)
    
    # ==================== 限流缓存 ====================
    
    def check_rate_limit(self, key: str, max_requests: int, 
                        window_seconds: int) -> tuple:
        """
        检查限流
        
        Returns:
            (allowed: bool, remaining: int, reset_time: float)
        """
        rate_key = f"{CACHE_PREFIX_RATE}{key}"
        
        current = self._safe_get(rate_key, {"count": 0, "window_start": time.time()})
        
        now = time.time()
        window_start = current["window_start"]
        
        # 检查是否在窗口内
        if now - window_start >= window_seconds:
            # 新窗口
            self._safe_set(rate_key, {"count": 1, "window_start": now}, window_seconds)
            return True, max_requests - 1, now + window_seconds
        
        # 在窗口内
        count = current["count"]
        if count >= max_requests:
            reset_time = window_start + window_seconds
            return False, 0, reset_time
        
        # 增加计数
        count += 1
        remaining = window_seconds - int(now - window_start)
        self._safe_set(rate_key, {"count": count, "window_start": window_start}, remaining)
        
        return True, max_requests - count, window_start + window_seconds
    
    # ==================== 批量操作 ====================
    
    def get_users_batch(self, user_ids: list) -> dict:
        """批量获取用户缓存"""
        result = {}
        for user_id in user_ids:
            data = self.get_user(user_id)
            if data:
                result[user_id] = data
        return result
    
    def set_users_batch(self, users_data: dict, ttl: int = 300) -> bool:
        """批量设置用户缓存"""
        for user_id, data in users_data.items():
            self.set_user(user_id, data, ttl)
        return True
    
    def invalidate_user_all(self, user_id: str) -> bool:
        """使用户所有相关缓存失效"""
        self.invalidate_user(user_id)
        self.invalidate_vault(user_id)
        return True


# 全局缓存服务实例
_cache_service: Optional[CacheService] = None


def get_cache_service() -> CacheService:
    """获取缓存服务实例"""
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service


def init_cache_service(cache_manager=None) -> CacheService:
    """初始化缓存服务"""
    global _cache_service
    _cache_service = CacheService(cache_manager)
    return _cache_service


def cached_user(ttl: int = 300):
    """用户数据缓存装饰器"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(user_id: str, *args, **kwargs):
            cache = get_cache_service()
            
            # 尝试从缓存获取
            cached = cache.get_user(user_id)
            if cached is not None:
                return cached
            
            # 执行函数获取数据
            result = func(user_id, *args, **kwargs)
            
            # 缓存结果
            if result is not None:
                cache.set_user(user_id, result, ttl)
            
            return result
        return wrapper
    return decorator


def cached_vault(ttl: int = 60):
    """Vault数据缓存装饰器"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(user_id: str, *args, **kwargs):
            cache = get_cache_service()
            
            # 尝试从缓存获取
            cached = cache.get_vault(user_id)
            if cached is not None:
                return cached
            
            # 执行函数获取数据
            result = func(user_id, *args, **kwargs)
            
            # 缓存结果
            if result is not None:
                cache.set_vault(user_id, result, ttl)
            
            return result
        return wrapper
    return decorator
