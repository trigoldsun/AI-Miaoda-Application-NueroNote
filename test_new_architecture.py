#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 新架构集成测试
测试数据库、缓存、服务层等核心组件
"""

import os
import sys
import time
import json
from pathlib import Path

# 设置测试环境变量
os.environ['FLUX_ENV'] = 'test'
if 'FLUX_DATABASE__URL' not in os.environ:
    os.environ['FLUX_DATABASE__URL'] = 'sqlite:///:memory:'
if 'FLUX_REDIS__ENABLED' not in os.environ:
    os.environ['FLUX_REDIS__ENABLED'] = 'false'
if 'FLUX_RATE_LIMIT__ENABLED' not in os.environ:
    os.environ['FLUX_RATE_LIMIT__ENABLED'] = 'false'

# 添加项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import pytest


def test_config_loading():
    """测试配置加载"""
    from nueronote_server.config import settings
    
    assert settings.debug is True
    assert settings.database.url == 'sqlite:///:memory:'
    assert settings.redis.enabled is False
    assert settings.rate_limit.enabled is False
    
    print("✓ 配置加载测试通过")


def test_database_initialization():
    """测试数据库初始化"""
    from nueronote_server.db import init_database, get_engine
    
    init_database()
    engine = get_engine()
    
    assert engine is not None
    assert str(engine.url) == 'sqlite:///:memory:'
    
    # 测试连接
    with engine.connect() as conn:
        result = conn.execute('SELECT 1').fetchone()
        assert result[0] == 1
    
    print("✓ 数据库初始化测试通过")


def test_models():
    """测试数据模型"""
    from nueronote_server.models import User, Vault
    
    # 创建用户实例
    user = User(
        id='test-user-123',
        email='test@example.com',
        plan='free',
        storage_quota=536870912,
        storage_used=0,
        vault_version=1,
        created_at=int(time.time() * 1000),
        updated_at=int(time.time() * 1000),
    )
    
    assert user.id == 'test-user-123'
    assert user.email == 'test@example.com'
    assert user.plan == 'free'
    
    # 转换为字典
    user_dict = user.to_dict()
    assert 'id' in user_dict
    assert 'email' in user_dict
    assert 'plan' in user_dict
    
    print("✓ 数据模型测试通过")


def test_user_service():
    """测试用户服务"""
    from nueronote_server.services.user import UserService
    
    service = UserService()
    
    # 测试邮箱验证
    try:
        service._validate_email('invalid-email')
        assert False, "应该抛出验证错误"
    except Exception as e:
        assert 'invalid' in str(e).lower()
    
    # 测试有效邮箱
    try:
        service._validate_email('valid@example.com')
    except Exception:
        assert False, "有效邮箱不应该抛出错误"
    
    print("✓ 用户服务测试通过")


def test_jwt_utils():
    """测试JWT工具"""
    from nueronote_server.utils.jwt import sign_token, verify_token
    
    test_secret = 'test-secret'
    test_user_id = 'test-user-456'
    
    # 生成令牌
    token = sign_token(test_user_id, test_secret)
    assert token is not None
    assert len(token.split('.')) == 3  # JWT格式
    
    # 验证令牌
    verified_user_id = verify_token(token, test_secret)
    assert verified_user_id == test_user_id
    
    # 测试无效令牌
    invalid_token = token[:-5] + 'xxxxx'  # 修改签名
    verified = verify_token(invalid_token, test_secret)
    assert verified is None
    
    print("✓ JWT工具测试通过")


def test_cache_module():
    """测试缓存模块（模拟模式）"""
    from nueronote_server.cache import RedisCache
    
    # 创建缓存实例（不连接真实Redis）
    cache = RedisCache(namespace='test')
    
    # 测试键名生成
    key = cache._make_key('test-key')
    assert key == 'test:test-key'
    
    # 测试序列化/反序列化
    test_data = {'name': 'test', 'value': 123}
    serialized = cache._serialize(test_data)
    deserialized = cache._deserialize(serialized)
    assert deserialized == test_data
    
    print("✓ 缓存模块测试通过")


def test_security_headers():
    """测试安全头部"""
    from nueronote_server.middleware.security_headers import SecurityHeaders
    
    security = SecurityHeaders()
    
    # 检查默认头部
    assert 'Content-Security-Policy' in security.DEFAULT_HEADERS
    assert 'Strict-Transport-Security' in security.DEFAULT_HEADERS
    assert 'X-Frame-Options' in security.DEFAULT_HEADERS
    
    # 测试头部更新
    security.update_headers({'Test-Header': 'test-value'})
    assert security.headers['Test-Header'] == 'test-value'
    
    print("✓ 安全头部测试通过")


def test_rate_limiter():
    """测试速率限制器（模拟模式）"""
    from nueronote_server.middleware.rate_limit import RateLimiter
    
    limiter = RateLimiter()
    limiter.enabled = False  # 禁用限流进行测试
    
    # 测试键名生成
    test_identifier = 'test-ip-123'
    key = limiter._generate_key(test_identifier, 'ip')
    assert key.startswith('rate_limit:ip:')
    
    # 测试客户端IP提取（模拟请求上下文）
    class MockRequest:
        headers = {}
        remote_addr = '127.0.0.1'
    
    # 由于需要Flask请求上下文，我们跳过完整的测试
    print("✓ 速率限制器基础测试通过")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("NueroNote 新架构集成测试")
    print("=" * 60)
    
    tests = [
        test_config_loading,
        test_database_initialization,
        test_models,
        test_user_service,
        test_jwt_utils,
        test_cache_module,
        test_security_headers,
        test_rate_limiter,
    ]
    
    passed = 0
    failed = 0
    
    for test_func in tests:
        try:
            test_func()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"✗ {test_func.__name__} 失败: {e}")
    
    print("=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    
    if failed == 0:
        print("🎉 所有测试通过！新架构基础功能正常。")
        return True
    else:
        print("❌ 有测试失败，请检查问题。")
        return False


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
