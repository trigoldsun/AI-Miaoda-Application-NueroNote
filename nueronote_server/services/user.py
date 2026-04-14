#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 用户服务
处理用户注册、登录、账户管理等业务逻辑
"""

import time
import logging
import hashlib
from typing import Optional, Dict, Any, Tuple
from datetime import datetime

from sqlalchemy.orm import Session

from nueronote_server.config import settings
from nueronote_server.models import User, Vault, VaultVersion
from nueronote_server.services.base import BaseService, ServiceError, ValidationError, NotFoundError, PermissionError
from nueronote_server.utils.jwt import sign_token
from nueronote_server.cache import get_cache


logger = logging.getLogger(__name__)


class UserService(BaseService[User]):
    """用户服务"""
    
    def __init__(self):
        super().__init__(User)
        self.cache = get_cache()
    
    def register(self, email: str, vault_data: Optional[Dict[str, Any]] = None) -> Tuple[User, str]:
        """
        注册新用户
        
        Args:
            email: 邮箱地址
            vault_data: 初始vault数据（可选）
            
        Returns:
            (用户对象, JWT令牌)
        """
        # 验证邮箱
        self._validate_email(email)
        
        # 检查邮箱是否已注册
        existing = self.get_by_field('email', email.lower())
        if existing:
            raise ValidationError(
                "Email already registered",
                {'email': 'already_registered'}
            )
        
        # 准备用户数据
        now = int(time.time() * 1000)
        user_data = {
            'id': hashlib.sha256(f"{email}:{now}".encode()).hexdigest()[:32],
            'email': email.lower(),
            'plan': 'free',
            'storage_quota': settings.storage.quota_free,
            'storage_used': 0,
            'vault_version': 1,
            'created_at': now,
            'updated_at': now,
            'login_fails': 0,
            'locked_until': 0,
            'last_login': 0,
            'cloud_config': '[]',
        }
        
        # 创建用户
        user = self.create(user_data)
        
        # 创建初始vault
        self._create_initial_vault(user, vault_data)
        
        # 生成JWT令牌
        token = sign_token(user.id, settings.security.jwt_secret)
        
        # 创建用户会话
        self._create_user_session(user, token)
        
        logger.info(f"用户注册成功: {email}")
        
        return user, token
    
    def login(self, email: str, client_ip: str) -> Tuple[User, str]:
        """
        用户登录
        
        Args:
            email: 邮箱地址
            client_ip: 客户端IP地址
            
        Returns:
            (用户对象, JWT令牌)
        """
        # 查找用户
        user = self.get_by_field('email', email.lower())
        if not user:
            raise NotFoundError('User', email)
        
        # 检查账户是否被锁定
        if self._is_account_locked(user):
            raise PermissionError("Account is locked due to too many failed login attempts")
        
        # 重置登录失败计数（模拟成功登录）
        self._reset_login_fails(user.id)
        
        # 更新最后登录信息
        self._update_last_login(user.id, client_ip)
        
        # 生成JWT令牌
        token = sign_token(user.id, settings.security.jwt_secret)
        
        # 更新用户会话
        self._create_user_session(user, token)
        
        logger.info(f"用户登录成功: {email} from {client_ip}")
        
        return user, token
    
    def logout(self, user_id: str, token: str) -> bool:
        """
        用户登出
        
        Args:
            user_id: 用户ID
            token: JWT令牌
            
        Returns:
            是否成功
        """
        # 将令牌加入黑名单
        from nueronote_server.middleware.auth import get_auth
        auth = get_auth()
        
        return auth.blacklist_token(token)
    
    def get_account_info(self, user_id: str) -> Dict[str, Any]:
        """
        获取账户信息
        
        Args:
            user_id: 用户ID
            
        Returns:
            账户信息字典
        """
        user = self.get_by_id(user_id)
        if not user:
            raise NotFoundError('User', user_id)
        
        # 获取vault信息
        with self._db_session() as session:
            vault = session.query(Vault).filter_by(user_id=user_id).first()
            
            return {
                'id': user.id,
                'email': user.email,
                'plan': user.plan,
                'storage_quota': user.storage_quota,
                'storage_used': user.storage_used or (vault.storage_bytes if vault else 0),
                'vault_version': user.vault_version,
                'created_at': user.created_at,
                'last_login': user.last_login,
                'login_fails': user.login_fails,
                'locked_until': user.locked_until,
            }
    
    def update_account(self, user_id: str, updates: Dict[str, Any]) -> User:
        """
        更新账户信息
        
        Args:
            user_id: 用户ID
            updates: 更新字段
            
        Returns:
            更新后的用户对象
        """
        # 过滤允许更新的字段
        allowed_fields = {'email', 'plan'}
        filtered_updates = {
            k: v for k, v in updates.items() 
            if k in allowed_fields
        }
        
        if not filtered_updates:
            raise ValidationError("No valid fields to update")
        
        # 如果更新邮箱，需要验证
        if 'email' in filtered_updates:
            self._validate_email(filtered_updates['email'])
            
            # 检查邮箱是否已被其他用户使用
            existing = self.get_by_field('email', filtered_updates['email'].lower())
            if existing and existing.id != user_id:
                raise ValidationError(
                    "Email already in use by another account",
                    {'email': 'already_in_use'}
                )
        
        # 添加更新时间戳
        filtered_updates['updated_at'] = int(time.time() * 1000)
        
        # 更新用户
        user = self.update(user_id, filtered_updates)
        if not user:
            raise NotFoundError('User', user_id)
        
        return user
    
    def upgrade_plan(self, user_id: str, new_plan: str) -> User:
        """
        升级用户计划
        
        Args:
            user_id: 用户ID
            new_plan: 新计划（free, pro, team, admin）
            
        Returns:
            更新后的用户对象
        """
        # 验证计划类型
        valid_plans = {'free', 'pro', 'team', 'admin'}
        if new_plan not in valid_plans:
            raise ValidationError(
                f"Invalid plan. Must be one of: {', '.join(valid_plans)}",
                {'plan': 'invalid'}
            )
        
        # 计算新的存储配额
        quota_map = {
            'free': settings.storage.quota_free,
            'pro': settings.storage.quota_pro,
            'team': settings.storage.quota_team,
        }
        
        new_quota = quota_map.get(new_plan, settings.storage.quota_free)
        
        # 更新用户
        updates = {
            'plan': new_plan,
            'storage_quota': new_quota,
            'updated_at': int(time.time() * 1000),
        }
        
        user = self.update(user_id, updates)
        if not user:
            raise NotFoundError('User', user_id)
        
        logger.info(f"用户计划升级: {user.email} -> {new_plan}")
        
        return user
    
    def check_storage_quota(self, user_id: str, additional_bytes: int = 0) -> Tuple[bool, int, int]:
        """
        检查存储配额
        
        Args:
            user_id: 用户ID
            additional_bytes: 要增加的字节数
            
        Returns:
            (是否足够, 已使用量, 配额)
        """
        user = self.get_by_id(user_id)
        if not user:
            raise NotFoundError('User', user_id)
        
        current_used = user.storage_used or 0
        total_quota = user.storage_quota
        
        # 如果用户有vault，使用实际的vault大小
        with self._db_session() as session:
            vault = session.query(Vault).filter_by(user_id=user_id).first()
            if vault and vault.storage_bytes:
                current_used = vault.storage_bytes
        
        has_space = (current_used + additional_bytes) <= total_quota
        
        return has_space, current_used, total_quota
    
    def record_login_failure(self, email: str, client_ip: str) -> None:
        """
        记录登录失败
        
        Args:
            email: 邮箱地址
            client_ip: 客户端IP
        """
        user = self.get_by_field('email', email.lower())
        if not user:
            # 用户不存在，不记录失败计数
            return
        
        try:
            with self._db_session() as session:
                # 重新获取用户（在事务中）
                user = session.query(User).filter_by(id=user.id).with_for_update().first()
                if not user:
                    return
                
                # 增加失败计数
                user.login_fails = (user.login_fails or 0) + 1
                
                # 如果达到阈值，锁定账户
                if user.login_fails >= settings.security.max_login_fails:
                    user.locked_until = int(time.time()) + settings.security.lockout_duration
                    logger.warning(f"账户锁定: {email} from {client_ip}")
                
                session.commit()
        except Exception as e:
            logger.error(f"记录登录失败失败: {e}")
    
    def _validate_email(self, email: str) -> None:
        """
        验证邮箱格式
        
        Args:
            email: 邮箱地址
            
        Raises:
            ValidationError: 如果邮箱无效
        """
        if not email or '@' not in email:
            raise ValidationError(
                "Invalid email format",
                {'email': 'invalid_format'}
            )
        
        # 简单的邮箱验证
        parts = email.split('@')
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValidationError(
                "Invalid email format",
                {'email': 'invalid_format'}
            )
    
    def _create_initial_vault(self, user: User, vault_data: Optional[Dict[str, Any]] = None):
        """
        创建初始vault
        
        Args:
            user: 用户对象
            vault_data: vault数据
        """
        if vault_data is None:
            vault_data = {
                'version': 1,
                'folders': [],
                'notes': [],
                'tags': [],
                'settings': {},
            }
        
        vault_json = '{}'  # 实际应该加密，这里简化
        vault_size = len(str(vault_data).encode())
        
        now = int(time.time() * 1000)
        
        try:
            with self._db_session() as session:
                # 创建vault
                vault = Vault(
                    user_id=user.id,
                    vault_json=vault_json,
                    vault_version=1,
                    updated_at=now,
                    updated_seq=0,
                    storage_bytes=vault_size,
                    last_synced_at=0,
                )
                session.add(vault)
                
                # 创建初始版本
                vault_version = VaultVersion(
                    user_id=user.id,
                    version=1,
                    vault_json=vault_json,
                    vault_bytes=vault_size,
                    created_at=now,
                    note='Initial vault',
                    is_auto=1,
                )
                session.add(vault_version)
                
                # 更新用户存储使用量
                user.storage_used = vault_size
                session.commit()
        except Exception as e:
            logger.error(f"创建初始vault失败: {e}")
            raise ServiceError("Failed to create initial vault")
    
    def _create_user_session(self, user: User, token: str):
        """
        创建用户会话（缓存用户信息）
        
        Args:
            user: 用户对象
            token: JWT令牌
        """
        if not self.cache:
            return
        
        try:
            # 缓存用户信息
            user_key = f"user:{user.id}"
            user_info = {
                'id': user.id,
                'email': user.email,
                'plan': user.plan,
                'storage_quota': user.storage_quota,
            }
            
            self.cache.set(user_key, user_info, ttl=settings.redis.user_cache_ttl)
        except Exception as e:
            logger.warning(f"缓存用户会话失败: {e}")
    
    def _is_account_locked(self, user: User) -> bool:
        """
        检查账户是否被锁定
        
        Args:
            user: 用户对象
            
        Returns:
            是否被锁定
        """
        if not user.locked_until:
            return False
        
        current_time = int(time.time())
        return user.locked_until > current_time
    
    def _reset_login_fails(self, user_id: str):
        """
        重置登录失败计数
        
        Args:
            user_id: 用户ID
        """
        try:
            with self._db_session() as session:
                user = session.query(User).filter_by(id=user_id).first()
                if user:
                    user.login_fails = 0
                    user.locked_until = 0
                    session.commit()
        except Exception as e:
            logger.error(f"重置登录失败计数失败: {e}")
    
    def _update_last_login(self, user_id: str, client_ip: str):
        """
        更新最后登录信息
        
        Args:
            user_id: 用户ID
            client_ip: 客户端IP
        """
        try:
            with self._db_session() as session:
                user = session.query(User).filter_by(id=user_id).first()
                if user:
                    user.last_login = int(time.time())
                    user.last_ip = client_ip
                    session.commit()
        except Exception as e:
            logger.error(f"更新最后登录信息失败: {e}")


# 全局用户服务实例
_user_service_instance: Optional[UserService] = None


def get_user_service() -> UserService:
    """
    获取用户服务实例（单例）
    
    Returns:
        UserService实例
    """
    global _user_service_instance
    if _user_service_instance is None:
        _user_service_instance = UserService()
    return _user_service_instance


def init_user_service() -> Optional[UserService]:
    """
    初始化用户服务
    
    Returns:
        UserService实例或None
    """
    try:
        service = get_user_service()
        logger.info("用户服务初始化成功")
        return service
    except Exception as e:
        logger.error(f"用户服务初始化失败: {e}")
        return None
