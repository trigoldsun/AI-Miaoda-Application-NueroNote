#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 配置模块测试
"""

import os
import secrets
import pytest

from nueronote_server.config import settings, get_settings
from nueronote_server.config import (
    get_env_bool, get_env_int, get_env_str,
    PYDANTIC_AVAILABLE
)


class TestConfig:
    """配置模块测试"""
    
    def test_settings_singleton(self):
        """测试单例模式"""
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
    
    def test_security_config_defaults(self):
        """测试安全配置默认值"""
        # 临时设置环境变量
        os.environ['FLUX_SECRET_KEY'] = 'test-secret-key-123'
        os.environ['FLUX_JWT_SECRET'] = 'test-jwt-secret-456'
        
        # 重新加载配置
        if hasattr(get_settings, '_instance'):
            delattr(get_settings, '_instance')
        
        s = get_settings()
        
        # 检查安全配置
        assert s.security.secret_key == 'test-secret-key-123'
        assert s.security.jwt_secret == 'test-jwt-secret-456'
        assert s.security.token_expire_hours == 24
        assert s.security.max_login_fails == 5
        assert s.security.lockout_minutes == 15
        
        # 清理环境变量
        del os.environ['FLUX_SECRET_KEY']
        del os.environ['FLUX_JWT_SECRET']
    
    def test_storage_config(self):
        """测试存储配置"""
        s = settings
        
        # 检查配额配置
        assert s.storage.quota_free == 512 * 1024 * 1024  # 512MB
        assert s.storage.quota_pro == 10 * 1024**3        # 10GB
        assert s.storage.quota_team == 100 * 1024**3      # 100GB
        assert s.storage.max_request_size == 10 * 1024 * 1024  # 10MB
    
    def test_cloud_config(self):
        """测试云存储配置"""
        s = settings
        
        # 检查云配置
        assert s.cloud.default_provider == "aliyunpan"  # 优先阿里云
        assert s.cloud.sync_interval == 300  # 5分钟
        assert s.cloud.chunk_size == 10 * 1024 * 1024  # 10MB
    
    def test_database_config(self):
        """测试数据库配置"""
        s = settings
        
        assert s.database.url == "sqlite:///nueronote.db"
        assert s.database.pool_size == 5
        assert s.database.pool_timeout == 30
        assert s.database.echo == False
    
    def test_env_var_functions(self):
        """测试环境变量工具函数"""
        # 测试布尔值
        os.environ['TEST_BOOL_TRUE'] = 'true'
        os.environ['TEST_BOOL_FALSE'] = 'false'
        os.environ['TEST_BOOL_1'] = '1'
        os.environ['TEST_BOOL_0'] = '0'
        
        assert get_env_bool('TEST_BOOL_TRUE') == True
        assert get_env_bool('TEST_BOOL_FALSE') == False
        assert get_env_bool('TEST_BOOL_1') == True
        assert get_env_bool('TEST_BOOL_0') == False
        assert get_env_bool('NOT_EXIST', default=True) == True
        
        # 测试整数
        os.environ['TEST_INT'] = '123'
        os.environ['TEST_INT_INVALID'] = 'abc'
        
        assert get_env_int('TEST_INT') == 123
        assert get_env_int('TEST_INT_INVALID') == 0
        assert get_env_int('NOT_EXIST', default=999) == 999
        
        # 测试字符串
        os.environ['TEST_STR'] = 'hello'
        
        assert get_env_str('TEST_STR') == 'hello'
        assert get_env_str('NOT_EXIST', default='default') == 'default'
        
        # 清理
        for key in ['TEST_BOOL_TRUE', 'TEST_BOOL_FALSE', 'TEST_BOOL_1', 
                    'TEST_BOOL_0', 'TEST_INT', 'TEST_INT_INVALID', 'TEST_STR']:
            if key in os.environ:
                del os.environ[key]
    
    def test_secret_key_generation(self):
        """测试密钥自动生成（开发模式）"""
        # 设置开发模式
        os.environ['FLUX_DEBUG'] = 'true'
        
        # 清除现有实例
        if hasattr(get_settings, '_instance'):
            delattr(get_settings, '_instance')
        
        # 不设置密钥，应该自动生成
        if 'FLUX_SECRET_KEY' in os.environ:
            del os.environ['FLUX_SECRET_KEY']
        if 'FLUX_JWT_SECRET' in os.environ:
            del os.environ['FLUX_JWT_SECRET']
        
        # 应该能成功创建配置（自动生成密钥）
        s = get_settings()
        
        # 检查密钥已生成
        assert s.security.secret_key
        assert s.security.jwt_secret
        assert len(s.security.secret_key) >= 32
        assert len(s.security.jwt_secret) >= 32
        
        # 清理
        del os.environ['FLUX_DEBUG']
        if 'FLUX_SECRET_KEY' in os.environ:
            del os.environ['FLUX_SECRET_KEY']
        if 'FLUX_JWT_SECRET' in os.environ:
            del os.environ['FLUX_JWT_SECRET']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
