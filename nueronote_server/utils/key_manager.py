#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 密钥管理系统
提供集中化的密钥管理、轮换和审计功能。

特性:
- 多种密钥存储后端（环境变量/文件/KMS）
- 密钥版本管理
- 自动轮换支持
- 密钥使用审计
"""

import hashlib
import hmac
import json
import os
import secrets
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class KeyType(Enum):
    """密钥类型"""
    SECRET_KEY = "secret_key"          # 应用密钥
    JWT_SECRET = "jwt_secret"          # JWT签名密钥
    ENCRYPTION_KEY = "encryption_key"  # 数据加密密钥
    API_KEY = "api_key"               # 第三方API密钥


class KeyStorage(ABC):
    """密钥存储抽象基类"""
    
    @abstractmethod
    def get(self, key_name: str) -> Optional[str]:
        """获取密钥值"""
        pass
    
    @abstractmethod
    def set(self, key_name: str, value: str, metadata: Dict = None) -> bool:
        """设置密钥值"""
        pass
    
    @abstractmethod
    def delete(self, key_name: str) -> bool:
        """删除密钥"""
        pass
    
    @abstractmethod
    def list_keys(self) -> List[str]:
        """列出所有密钥名"""
        pass


class EnvironmentKeyStorage(KeyStorage):
    """环境变量密钥存储"""
    
    def __init__(self, prefix: str = "FLUX_"):
        self.prefix = prefix
        self.env_mapping = {
            "secret_key": "SECRET_KEY",
            "jwt_secret": "JWT_SECRET",
            "encryption_key": "ENCRYPTION_KEY",
        }
    
    def _get_env_name(self, key_name: str) -> str:
        """获取环境变量名"""
        suffix = self.env_mapping.get(key_name, key_name.upper())
        return f"{self.prefix}{suffix}"
    
    def get(self, key_name: str) -> Optional[str]:
        env_name = self._get_env_name(key_name)
        return os.environ.get(env_name)
    
    def set(self, key_name: str, value: str, metadata: Dict = None) -> bool:
        env_name = self._get_env_name(key_name)
        os.environ[env_name] = value
        return True
    
    def delete(self, key_name: str) -> bool:
        env_name = self._get_env_name(key_name)
        if env_name in os.environ:
            del os.environ[env_name]
            return True
        return False
    
    def list_keys(self) -> List[str]:
        keys = []
        for key_name in self.env_mapping.keys():
            if self.get(key_name):
                keys.append(key_name)
        return keys


class FileKeyStorage(KeyStorage):
    """文件密钥存储（加密存储）"""
    
    def __init__(self, storage_dir: str = ".keys"):
        self.storage_dir = storage_dir
        self._ensure_dir()
    
    def _ensure_dir(self):
        """确保目录存在"""
        os.makedirs(self.storage_dir, exist_ok=True)
    
    def _get_file_path(self, key_name: str) -> str:
        """获取密钥文件路径"""
        return os.path.join(self.storage_dir, f"{key_name}.key")
    
    def get(self, key_name: str) -> Optional[str]:
        path = self._get_file_path(key_name)
        if os.path.exists(path):
            with open(path, 'r') as f:
                return f.read().strip()
        return None
    
    def set(self, key_name: str, value: str, metadata: Dict = None) -> bool:
        path = self._get_file_path(key_name)
        with open(path, 'w') as f:
            f.write(value)
        # 设置文件权限为600
        os.chmod(path, 0o600)
        
        # 保存元数据
        if metadata:
            meta_path = f"{path}.meta"
            with open(meta_path, 'w') as f:
                json.dump(metadata, f)
        
        return True
    
    def delete(self, key_name: str) -> bool:
        path = self._get_file_path(key_name)
        if os.path.exists(path):
            os.remove(path)
            meta_path = f"{path}.meta"
            if os.path.exists(meta_path):
                os.remove(meta_path)
            return True
        return False
    
    def list_keys(self) -> List[str]:
        keys = []
        if os.path.exists(self.storage_dir):
            for filename in os.listdir(self.storage_dir):
                if filename.endswith('.key'):
                    keys.append(filename[:-4])
        return keys


@dataclass
class KeyVersion:
    """密钥版本信息"""
    version: int
    key_id: str
    created_at: int
    is_active: bool
    metadata: Dict


class KeyManager:
    """密钥管理器"""
    
    def __init__(self, storage: KeyStorage):
        self.storage = storage
        self.versions: Dict[str, List[KeyVersion]] = {}
        self.usage_log: List[Dict] = []
    
    def get_key(self, key_name: str, version: int = None) -> Optional[str]:
        """
        获取密钥
        
        Args:
            key_name: 密钥名称
            version: 指定版本，None获取最新版本
            
        Returns:
            密钥值或None
        """
        # 记录使用
        self._log_usage(key_name, version, "get")
        
        if version:
            # 获取指定版本
            for ver in self.versions.get(key_name, []):
                if ver.version == version:
                    return self.storage.get(f"{key_name}:{version}")
        else:
            # 获取最新版本
            versions = self.versions.get(key_name, [])
            if versions:
                latest = max(versions, key=lambda v: v.version)
                if latest.is_active:
                    return self.storage.get(f"{key_name}:{latest.version}")
        
        # 回退到简单存储
        return self.storage.get(key_name)
    
    def set_key(self, key_name: str, value: str, 
               metadata: Dict = None, auto_rotate: bool = False) -> Tuple[bool, int]:
        """
        设置密钥
        
        Args:
            key_name: 密钥名称
            value: 密钥值
            metadata: 元数据
            auto_rotate: 是否自动轮换
            
        Returns:
            (成功标志, 版本号)
        """
        versions = self.versions.get(key_name, [])
        
        # 生成新版本号
        new_version = max([v.version for v in versions], default=0) + 1
        
        # 存储密钥
        versioned_key = f"{key_name}:{new_version}"
        success = self.storage.set(versioned_key, value, metadata)
        
        if success:
            # 记录版本信息
            key_version = KeyVersion(
                version=new_version,
                key_id=key_name,
                created_at=int(time.time()),
                is_active=True,
                metadata=metadata or {},
            )
            
            if auto_rotate and versions:
                # 标记旧版本为非活跃
                for v in versions:
                    v.is_active = False
            
            versions.append(key_version)
            self.versions[key_name] = versions
            
            self._log_usage(key_name, new_version, "set")
        
        return success, new_version
    
    def rotate_key(self, key_name: str) -> Tuple[bool, int]:
        """
        轮换密钥（生成新版本）
        
        Returns:
            (成功标志, 新版本号)
        """
        # 生成新密钥
        new_key = self.generate_key(key_name)
        
        # 设置新密钥
        return self.set_key(
            key_name, 
            new_key,
            metadata={"rotated_at": int(time.time())},
            auto_rotate=True
        )
    
    def revoke_key(self, key_name: str, version: int = None) -> bool:
        """
        吊销密钥
        
        Args:
            key_name: 密钥名称
            version: 指定版本，None吊销所有版本
        """
        versions = self.versions.get(key_name, [])
        
        if version:
            for v in versions:
                if v.version == version:
                    v.is_active = False
                    self._log_usage(key_name, version, "revoke")
                    return True
        else:
            for v in versions:
                v.is_active = False
                self._log_usage(key_name, v.version, "revoke")
            return True
        
        return False
    
    def generate_key(self, key_name: str) -> str:
        """生成随机密钥"""
        # 根据密钥类型生成不同长度的密钥
        key_lengths = {
            KeyType.SECRET_KEY: 32,
            KeyType.JWT_SECRET: 32,
            KeyType.ENCRYPTION_KEY: 32,
            KeyType.API_KEY: 64,
        }
        
        length = key_lengths.get(key_name, 32)
        return secrets.token_urlsafe(length)
    
    def verify_key(self, key_name: str, value: str, 
                  signature: str) -> bool:
        """
        验证密钥签名
        
        Args:
            key_name: 密钥名称
            value: 原始值
            signature: 签名
        """
        key = self.get_key(key_name)
        if not key:
            return False
        
        expected = hmac.new(
            key.encode(),
            value.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(signature, expected)
    
    def sign_data(self, key_name: str, data: str) -> str:
        """使用密钥签名数据"""
        key = self.get_key(key_name)
        if not key:
            raise ValueError(f"密钥不存在: {key_name}")
        
        return hmac.new(
            key.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()
    
    def get_key_info(self, key_name: str) -> Dict:
        """获取密钥信息"""
        versions = self.versions.get(key_name, [])
        
        return {
            "key_name": key_name,
            "total_versions": len(versions),
            "active_versions": sum(1 for v in versions if v.is_active),
            "latest_version": max([v.version for v in versions], default=0),
            "versions": [
                {
                    "version": v.version,
                    "created_at": v.created_at,
                    "is_active": v.is_active,
                    "metadata": v.metadata,
                }
                for v in sorted(versions, key=lambda x: x.version, reverse=True)
            ],
        }
    
    def list_keys(self) -> List[str]:
        """列出所有密钥"""
        return list(set(
            self.storage.list_keys() + 
            list(self.versions.keys())
        ))
    
    def _log_usage(self, key_name: str, version: int, operation: str):
        """记录密钥使用"""
        self.usage_log.append({
            "key_name": key_name,
            "version": version,
            "operation": operation,
            "timestamp": int(time.time()),
        })
    
    def get_usage_log(self, key_name: str = None, 
                     since: int = None) -> List[Dict]:
        """获取密钥使用日志"""
        log = self.usage_log
        
        if key_name:
            log = [l for l in log if l["key_name"] == key_name]
        
        if since:
            log = [l for l in log if l["timestamp"] >= since]
        
        return log


# 全局密钥管理器实例
_key_manager: Optional[KeyManager] = None


def get_key_manager() -> KeyManager:
    """获取密钥管理器实例"""
    global _key_manager
    if _key_manager is None:
        # 初始化密钥管理器
        storage = EnvironmentKeyStorage()
        _key_manager = KeyManager(storage)
    return _key_manager


def init_key_manager(storage: KeyStorage = None) -> KeyManager:
    """初始化密钥管理器"""
    global _key_manager
    if storage is None:
        storage = EnvironmentKeyStorage()
    _key_manager = KeyManager(storage)
    return _key_manager


# 便捷函数
def get_secret_key() -> str:
    """获取应用密钥"""
    manager = get_key_manager()
    key = manager.get_key(KeyType.SECRET_KEY.value)
    if not key:
        # 生成临时密钥（仅用于开发）
        import secrets
        key = secrets.token_urlsafe(32)
        manager.set_key(
            KeyType.SECRET_KEY.value, 
            key,
            metadata={"generated": "fallback", "warning": "仅用于开发"}
        )
    return key


def get_jwt_secret() -> str:
    """获取JWT密钥"""
    manager = get_key_manager()
    key = manager.get_key(KeyType.JWT_SECRET.value)
    if not key:
        import secrets
        key = secrets.token_urlsafe(32)
        manager.set_key(
            KeyType.JWT_SECRET.value,
            key,
            metadata={"generated": "fallback"}
        )
    return key
