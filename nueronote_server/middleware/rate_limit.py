#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 速率限制模块
基于Redis的滑动窗口算法，支持IP、用户、API多维度限流
"""

import time
import hashlib
import logging
from typing import Optional, Tuple, Dict, Any
from functools import wraps
from datetime import timedelta

from flask import request, g, jsonify
from redis.exceptions import RedisError

from nueronote_server.config import settings
from nueronote_server.cache import get_cache


logger = logging.getLogger(__name__)


class RateLimiter:
    """
    速率限制器
    
    基于滑动窗口算法，使用Redis存储计数
    支持：IP限制、用户限制、API端点限制
    """
    
    def __init__(self):
        """初始化速率限制器"""
        self.cache = get_cache()
        self.enabled = settings.rate_limit.enabled
        
        # 限流配置
        self.ip_limit = settings.rate_limit.ip_limit_per_minute
        self.user_limit = settings.rate_limit.user_limit_per_minute
        self.auth_limit = settings.rate_limit.auth_limit_per_minute
        self.window_seconds = settings.rate_limit.window_seconds
        
        # 限流键名前缀
        self.prefix = "rate_limit"
    
    def _get_client_ip(self) -> str:
        """
        获取客户端IP地址
        
        Returns:
            IP地址字符串
        """
        # 优先使用X-Forwarded-For（代理后）
        forwarded = request.headers.get('X-Forwarded-For')
        if forwarded:
            ip = forwarded.split(',')[0].strip()
            if ip:
                return ip
        
        # 次选X-Real-IP
        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            return real_ip.strip()
        
        # 最后使用远程地址
        return request.remote_addr or '0.0.0.0'
    
    def _get_user_id(self) -> Optional[str]:
        """
        获取用户ID（如果已认证）
        
        Returns:
            用户ID或None
        """
        # 从Flask g对象获取用户ID
        return getattr(g, 'user_id', None)
    
    def _generate_key(self, identifier: str, action: str = "global") -> str:
        """
        生成限流键名
        
        Args:
            identifier: 标识符（IP或用户ID）
            action: 操作类型
            
        Returns:
            限流键名
        """
        # 使用哈希防止键名过长
        identifier_hash = hashlib.md5(identifier.encode()).hexdigest()[:8]
        window = int(time.time() / self.window_seconds)
        
        return f"{self.prefix}:{action}:{identifier_hash}:{window}"
    
    def _check_limit(self, key: str, limit: int) -> Tuple[bool, Dict[str, Any]]:
        """
        检查是否超过限制
        
        Args:
            key: 限流键
            limit: 限制数量
            
        Returns:
            (是否通过, 详细信息)
        """
        if not self.enabled:
            return True, {'allowed': True, 'limit': limit, 'remaining': limit}
        
        try:
            # 获取当前计数
            current = self.cache.incr(key)
            
            # 如果是新键，设置过期时间
            if current == 1:
                self.cache.expire(key, self.window_seconds)
            
            # 计算剩余请求数
            remaining = max(0, limit - current)
            allowed = current <= limit
            
            return allowed, {
                'allowed': allowed,
                'limit': limit,
                'remaining': remaining,
                'current': current,
                'key': key,
            }
            
        except RedisError as e:
            # Redis错误时放行（降级策略）
            logger.error(f"限流Redis错误: {e}")
            return True, {'allowed': True, 'error': str(e)}
    
    def check_ip_limit(self) -> Tuple[bool, Dict[str, Any]]:
        """
        检查IP限制
        
        Returns:
            (是否通过, 详细信息)
        """
        ip = self._get_client_ip()
        key = self._generate_key(ip, "ip")
        return self._check_limit(key, self.ip_limit)
    
    def check_user_limit(self, user_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        检查用户限制
        
        Args:
            user_id: 用户ID
            
        Returns:
            (是否通过, 详细信息)
        """
        key = self._generate_key(user_id, "user")
        return self._check_limit(key, self.user_limit)
    
    def check_auth_limit(self, identifier: str) -> Tuple[bool, Dict[str, Any]]:
        """
        检查认证接口限制（登录/注册等）
        
        Args:
            identifier: 标识符（IP或用户名）
            
        Returns:
            (是否通过, 详细信息)
        """
        key = self._generate_key(identifier, "auth")
        return self._check_limit(key, self.auth_limit)
    
    def check_request(self) -> Tuple[bool, Dict[str, Any]]:
        """
        检查完整请求限制（IP + 用户）
        
        Returns:
            (是否通过, 详细信息)
        """
        # 检查IP限制
        ip_allowed, ip_info = self.check_ip_limit()
        if not ip_allowed:
            return False, {
                'allowed': False,
                'reason': 'ip_limit_exceeded',
                'ip_info': ip_info,
                'limit_type': 'ip',
            }
        
        # 检查用户限制（如果已认证）
        user_id = self._get_user_id()
        if user_id:
            user_allowed, user_info = self.check_user_limit(user_id)
            if not user_allowed:
                return False, {
                    'allowed': False,
                    'reason': 'user_limit_exceeded',
                    'user_info': user_info,
                    'limit_type': 'user',
                }
        
        return True, {
            'allowed': True,
            'ip_info': ip_info,
            'user_id': user_id,
        }
    
    def get_headers(self, limit_info: Dict[str, Any]) -> Dict[str, str]:
        """
        生成限流响应头部（RFC 6585）
        
        Args:
            limit_info: 限流信息
            
        Returns:
            响应头部字典
        """
        headers = {}
        
        if 'ip_info' in limit_info:
            ip_info = limit_info['ip_info']
            if 'limit' in ip_info and 'remaining' in ip_info:
                headers['X-RateLimit-Limit'] = str(ip_info['limit'])
                headers['X-RateLimit-Remaining'] = str(ip_info['remaining'])
                headers['X-RateLimit-Reset'] = str(
                    int(time.time() / self.window_seconds) * self.window_seconds + self.window_seconds
                )
        
        return headers


# 全局限流器实例
_limiter_instance: Optional[RateLimiter] = None


def get_limiter() -> RateLimiter:
    """
    获取限流器实例（单例）
    
    Returns:
        RateLimiter实例
    """
    global _limiter_instance
    if _limiter_instance is None:
        _limiter_instance = RateLimiter()
    return _limiter_instance


def rate_limit_decorator(f):
    """
    Flask路由限流装饰器
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        limiter = get_limiter()
        
        # 检查限流
        allowed, limit_info = limiter.check_request()
        
        if not allowed:
            # 生成响应头部
            headers = limiter.get_headers(limit_info)
            
            # 返回429 Too Many Requests
            response = jsonify({
                'error': 'Too many requests',
                'message': 'Rate limit exceeded',
                'retry_after': limiter.window_seconds,
                'details': limit_info,
            })
            response.status_code = 429
            response.headers.extend(headers)
            return response
        
        # 限流通过，添加头部信息
        @wraps(f)
        def add_headers(response):
            headers = limiter.get_headers(limit_info)
            response.headers.extend(headers)
            return response
        
        # 执行原始函数并添加头部
        result = f(*args, **kwargs)
        if isinstance(result, tuple):
            response = jsonify(result[0])
            response.status_code = result[1]
            return add_headers(response)
        else:
            return add_headers(result)
    
    return decorated_function


def auth_rate_limit_decorator(f):
    """
    认证接口专用限流装饰器（更严格的限制）
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        limiter = get_limiter()
        
        # 获取标识符（优先使用用户名，否则使用IP）
        identifier = None
        if request.is_json:
            data = request.get_json(silent=True) or {}
            identifier = data.get('email') or data.get('username')
        
        if not identifier:
            identifier = limiter._get_client_ip()
        
        # 检查认证限流
        allowed, limit_info = limiter.check_auth_limit(identifier)
        
        if not allowed:
            headers = limiter.get_headers(limit_info)
            response = jsonify({
                'error': 'Too many authentication attempts',
                'message': 'Please wait before trying again',
                'retry_after': limiter.window_seconds,
            })
            response.status_code = 429
            response.headers.extend(headers)
            return response
        
        return f(*args, **kwargs)
    
    return decorated_function


def init_rate_limiter() -> Optional[RateLimiter]:
    """
    初始化限流器
    
    Returns:
        RateLimiter实例或None
    """
    if not settings.rate_limit.enabled:
        logger.warning("速率限制未启用")
        return None
    
    try:
        limiter = get_limiter()
        # 测试Redis连接
        limiter.cache.client.ping()
        logger.info("速率限制器初始化成功")
        return limiter
    except Exception as e:
        logger.error(f"速率限制器初始化失败: {e}")
        return None


# 便捷函数
def check_rate_limit() -> Tuple[bool, Dict[str, Any]]:
    """
    检查当前请求的速率限制
    
    Returns:
        (是否通过, 限流信息)
    """
    limiter = get_limiter()
    return limiter.check_request()


def get_rate_limit_headers() -> Dict[str, str]:
    """
    获取当前请求的限流头部
    
    Returns:
        头部字典
    """
    limiter = get_limiter()
    _, limit_info = limiter.check_request()
    return limiter.get_headers(limit_info)
