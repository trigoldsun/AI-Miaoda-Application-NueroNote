#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 认证和授权中间件
JWT令牌验证、权限检查、会话管理
"""

import logging
import time
from typing import Optional, Dict, Any, Callable
from functools import wraps

from flask import request, g, jsonify, current_app
from redis.exceptions import RedisError

from nueronote_server.config import settings
from nueronote_server.utils.jwt import verify_token, decode_token
from nueronote_server.cache import get_cache


logger = logging.getLogger(__name__)


class AuthMiddleware:
    """
    认证和授权中间件
    
    功能：
    1. JWT令牌验证
    2. 权限检查
    3. 会话管理
    4. 令牌吊销
    5. 安全审计
    """
    
    def __init__(self):
        """初始化认证中间件"""
        self.cache = get_cache()
        self.token_header = 'Authorization'
        self.token_type = 'Bearer'
        
        # 会话配置
        self.session_ttl = settings.security.token_expire_hours * 3600
        self.blacklist_prefix = 'token_blacklist:'
        
        # 权限级别
        self.PERMISSION_LEVELS = {
            'none': 0,
            'read': 1,
            'write': 2,
            'admin': 3,
        }
    
    def extract_token(self) -> Optional[str]:
        """
        从请求中提取JWT令牌
        
        Returns:
            JWT令牌或None
        """
        # 从Authorization头部提取
        auth_header = request.headers.get(self.token_header)
        if auth_header and auth_header.startswith(f'{self.token_type} '):
            return auth_header[len(f'{self.token_type} '):].strip()
        
        # 从查询参数提取（用于WebSocket等）
        token = request.args.get('token')
        if token:
            return token
        
        # 从cookie提取（Web界面）
        token = request.cookies.get('nueronote_token')
        if token:
            return token
        
        return None
    
    def verify_token(self, token: str) -> Optional[str]:
        """
        验证JWT令牌
        
        Args:
            token: JWT令牌
            
        Returns:
            用户ID或None（验证失败）
        """
        if not token:
            return None
        
        # 检查令牌是否在黑名单中
        if self.is_token_blacklisted(token):
            logger.warning(f"令牌在黑名单中: {token[:20]}...")
            return None
        
        # 验证JWT签名和过期时间
        user_id = verify_token(token, settings.security.jwt_secret)
        if not user_id:
            return None
        
        # 检查令牌是否在缓存中（可选会话管理）
        cache_key = f"user_token:{user_id}:{self._token_hash(token)}"
        cached = self.cache.get(cache_key)
        if cached is None:
            # 令牌不在缓存中，可能是新令牌或已过期
            # 可以在这里添加额外的验证逻辑
            pass
        
        return user_id
    
    def _token_hash(self, token: str) -> str:
        """
        生成令牌哈希（用于缓存键）
        
        Args:
            token: JWT令牌
            
        Returns:
            令牌哈希
        """
        import hashlib
        return hashlib.sha256(token.encode()).hexdigest()[:16]
    
    def blacklist_token(self, token: str, ttl: Optional[int] = None) -> bool:
        """
        将令牌加入黑名单
        
        Args:
            token: JWT令牌
            ttl: 黑名单有效期（秒），默认使用会话TTL
            
        Returns:
            是否成功
        """
        if ttl is None:
            ttl = self.session_ttl
        
        token_hash = self._token_hash(token)
        blacklist_key = f"{self.blacklist_prefix}{token_hash}"
        
        try:
            return self.cache.set(blacklist_key, 'blacklisted', ttl)
        except RedisError as e:
            logger.error(f"令牌黑名单失败: {e}")
            return False
    
    def is_token_blacklisted(self, token: str) -> bool:
        """
        检查令牌是否在黑名单中
        
        Args:
            token: JWT令牌
            
        Returns:
            是否在黑名单中
        """
        token_hash = self._token_hash(token)
        blacklist_key = f"{self.blacklist_prefix}{token_hash}"
        
        try:
            return self.cache.exists(blacklist_key)
        except RedisError as e:
            logger.error(f"检查令牌黑名单失败: {e}")
            return False
    
    def create_user_session(self, user_id: str, token: str, metadata: Dict[str, Any] = None) -> bool:
        """
        创建用户会话（缓存用户信息和令牌）
        
        Args:
            user_id: 用户ID
            token: JWT令牌
            metadata: 会话元数据
            
        Returns:
            是否成功
        """
        if metadata is None:
            metadata = {}
        
        token_hash = self._token_hash(token)
        
        # 缓存令牌到用户映射
        cache_key = f"user_token:{user_id}:{token_hash}"
        session_data = {
            'token_hash': token_hash,
            'created_at': int(time.time()),
            'last_activity': int(time.time()),
            'ip': request.remote_addr,
            'user_agent': request.headers.get('User-Agent', ''),
            **metadata,
        }
        
        try:
            # 存储会话数据
            success = self.cache.set(cache_key, session_data, self.session_ttl)
            
            # 存储用户活跃令牌列表
            tokens_key = f"user_tokens:{user_id}"
            current_tokens = self.cache.get(tokens_key) or []
            if token_hash not in current_tokens:
                current_tokens.append(token_hash)
                self.cache.set(tokens_key, current_tokens, self.session_ttl)
            
            return success
        except RedisError as e:
            logger.error(f"创建用户会话失败: {e}")
            return False
    
    def update_session_activity(self, user_id: str, token: str) -> bool:
        """
        更新会话活跃时间
        
        Args:
            user_id: 用户ID
            token: JWT令牌
            
        Returns:
            是否成功
        """
        token_hash = self._token_hash(token)
        cache_key = f"user_token:{user_id}:{token_hash}"
        
        try:
            session_data = self.cache.get(cache_key)
            if session_data:
                session_data['last_activity'] = int(time.time())
                # 更新过期时间
                return self.cache.set(cache_key, session_data, self.session_ttl)
            return False
        except RedisError as e:
            logger.error(f"更新会话活跃时间失败: {e}")
            return False
    
    def destroy_user_session(self, user_id: str, token: str) -> bool:
        """
        销毁用户会话
        
        Args:
            user_id: 用户ID
            token: JWT令牌
            
        Returns:
            是否成功
        """
        token_hash = self._token_hash(token)
        
        # 从用户令牌列表中移除
        tokens_key = f"user_tokens:{user_id}"
        try:
            current_tokens = self.cache.get(tokens_key) or []
            if token_hash in current_tokens:
                current_tokens.remove(token_hash)
                self.cache.set(tokens_key, current_tokens, self.session_ttl)
        except RedisError:
            pass
        
        # 删除会话数据
        cache_key = f"user_token:{user_id}:{token_hash}"
        try:
            return self.cache.delete(cache_key)
        except RedisError as e:
            logger.error(f"销毁用户会话失败: {e}")
            return False
    
    def destroy_all_user_sessions(self, user_id: str) -> bool:
        """
        销毁用户的所有会话
        
        Args:
            user_id: 用户ID
            
        Returns:
            是否成功
        """
        tokens_key = f"user_tokens:{user_id}"
        
        try:
            token_hashes = self.cache.get(tokens_key) or []
            
            # 将所有令牌加入黑名单
            for token_hash in token_hashes:
                blacklist_key = f"{self.blacklist_prefix}{token_hash}"
                self.cache.set(blacklist_key, 'blacklisted', self.session_ttl)
            
            # 删除令牌列表
            self.cache.delete(tokens_key)
            
            # 删除所有会话数据
            for token_hash in token_hashes:
                cache_key = f"user_token:{user_id}:{token_hash}"
                self.cache.delete(cache_key)
            
            return True
        except RedisError as e:
            logger.error(f"销毁所有用户会话失败: {e}")
            return False
    
    def check_permission(self, user_id: str, required_permission: str, resource_type: str = None, resource_id: str = None) -> bool:
        """
        检查用户权限
        
        Args:
            user_id: 用户ID
            required_permission: 所需权限级别
            resource_type: 资源类型（可选）
            resource_id: 资源ID（可选）
            
        Returns:
            是否具有权限
        """
        # 这里实现权限检查逻辑
        # 可以根据用户角色、资源所有权等检查
        
        required_level = self.PERMISSION_LEVELS.get(required_permission.lower(), 0)
        
        # 简化权限检查：管理员有所有权限
        # TODO: 实现完整的RBAC或ABAC权限系统
        
        # 从数据库获取用户信息（简化示例）
        from nueronote_server.db import get_db_session
        from nueronote_server.models import User
        
        with get_db_session() as session:
            user = session.query(User).filter_by(id=user_id).first()
            if not user:
                return False
            
            # 检查用户计划对应的权限
            if user.plan == 'admin':
                user_level = self.PERMISSION_LEVELS['admin']
            elif user.plan == 'team':
                user_level = self.PERMISSION_LEVELS['write']
            elif user.plan == 'pro':
                user_level = self.PERMISSION_LEVELS['write']
            else:  # free
                user_level = self.PERMISSION_LEVELS['read']
            
            return user_level >= required_level


# 全局认证实例
_auth_instance: Optional[AuthMiddleware] = None


def get_auth() -> AuthMiddleware:
    """
    获取认证中间件实例（单例）
    
    Returns:
        AuthMiddleware实例
    """
    global _auth_instance
    if _auth_instance is None:
        _auth_instance = AuthMiddleware()
    return _auth_instance


def require_auth_decorator(f):
    """
    要求认证的装饰器
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth = get_auth()
        
        # 提取和验证令牌
        token = auth.extract_token()
        if not token:
            return jsonify({
                'error': 'Authentication required',
                'message': 'No authorization token provided'
            }), 401
        
        user_id = auth.verify_token(token)
        if not user_id:
            return jsonify({
                'error': 'Invalid token',
                'message': 'The provided token is invalid or expired'
            }), 401
        
        # 将用户ID存储到g对象
        g.user_id = user_id
        g.auth_token = token
        
        # 更新会话活跃时间
        auth.update_session_activity(user_id, token)
        
        # 执行原始函数
        return f(*args, **kwargs)
    
    return decorated_function


def require_permission_decorator(permission: str, resource_type: str = None):
    """
    要求特定权限的装饰器
    
    Args:
        permission: 所需权限级别
        resource_type: 资源类型
    """
    def decorator(f):
        @wraps(f)
        @require_auth_decorator
        def decorated_function(*args, **kwargs):
            auth = get_auth()
            
            # 获取用户ID
            user_id = g.user_id
            
            # 获取资源ID（从URL参数或请求体）
            resource_id = None
            if resource_type:
                # 尝试从URL参数获取资源ID
                resource_id = kwargs.get(f'{resource_type}_id')
                if not resource_id and request.is_json:
                    # 尝试从请求体获取
                    data = request.get_json(silent=True) or {}
                    resource_id = data.get(f'{resource_type}_id')
            
            # 检查权限
            has_permission = auth.check_permission(
                user_id, permission, resource_type, resource_id
            )
            
            if not has_permission:
                return jsonify({
                    'error': 'Insufficient permissions',
                    'message': f'You do not have {permission} permission for this resource'
                }), 403
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def optional_auth_decorator(f):
    """
    可选认证的装饰器（认证用户有user_id，未认证用户为None）
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth = get_auth()
        
        # 尝试提取和验证令牌
        token = auth.extract_token()
        if token:
            user_id = auth.verify_token(token)
            if user_id:
                g.user_id = user_id
                g.auth_token = token
                auth.update_session_activity(user_id, token)
        
        # 执行原始函数
        return f(*args, **kwargs)
    
    return decorated_function


# 便捷权限检查装饰器
require_read = require_permission_decorator('read')
require_write = require_permission_decorator('write')
require_admin = require_permission_decorator('admin')


def init_auth_middleware() -> Optional[AuthMiddleware]:
    """
    初始化认证中间件
    
    Returns:
        AuthMiddleware实例或None
    """
    try:
        auth = get_auth()
        # 测试缓存连接
        auth.cache.client.ping()
        logger.info("认证中间件初始化成功")
        return auth
    except Exception as e:
        logger.error(f"认证中间件初始化失败: {e}")
        return None


# 便捷函数
def get_current_user_id() -> Optional[str]:
    """
    获取当前认证用户的ID
    
    Returns:
        用户ID或None
    """
    return getattr(g, 'user_id', None)


def get_current_token() -> Optional[str]:
    """
    获取当前认证令牌
    
    Returns:
        JWT令牌或None
    """
    return getattr(g, 'auth_token', None)


def logout_current_user() -> bool:
    """
    注销当前用户（将当前令牌加入黑名单）
    
    Returns:
        是否成功
    """
    auth = get_auth()
    user_id = get_current_user_id()
    token = get_current_token()
    
    if user_id and token:
        # 将令牌加入黑名单
        auth.blacklist_token(token)
        # 销毁会话
        return auth.destroy_user_session(user_id, token)
    
    return False


# =============================================================================
# CSRF 保护（状态变更API需要）
# =============================================================================
from functools import wraps

def csrf_protect(f):
    """
    CSRF保护装饰器
    
    检查请求来源是否来自信任的域名
    对于POST/PUT/DELETE请求，验证Origin或Referer头
    
    注意: 这不是完整的CSRF token实现
    对于高安全性需求，应使用 flask-wtf 或类似的CSRF token方案
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 只对非GET请求检查
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return f(*args, **kwargs)
        
        # 获取请求来源
        origin = request.headers.get('Origin', '')
        referer = request.headers.get('Referer', '')
        
        # 允许的空来源（如同源请求）
        if not origin and not referer:
            # 允许无来源的请求，但记录警告
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"CSRF: Request without origin/referer to {request.path}")
            # 在生产环境中可以考虑拒绝
        
        # 信任的来源（可配置）
        trusted_origins = app.config.get('TRUSTED_ORIGINS', [
            'https://nueronote.app',
            'https://app.nueronote.com',
            'http://localhost:3000',  # 开发环境
            'http://localhost:5173',  # 开发环境
        ])
        
        # 检查来源是否在信任列表中
        if origin and origin not in trusted_origins:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"CSRF: Untrusted origin '{origin}' for {request.path}")
            # 在生产环境中可以考虑拒绝
            # return jsonify({"error": "Invalid request origin"}), 403
        
        return f(*args, **kwargs)
    
    return decorated_function
