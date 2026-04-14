#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 验证模块测试
"""

import pytest

from nueronote_server.validation import (
    validate_user_id,
    validate_email,
    validate_version,
    validate_vault_data,
    ValidationError,
    validate_or_raise,
    VALIDATION_RULES
)


class TestValidationFunctions:
    """验证函数测试"""
    
    def test_validate_user_id(self):
        """测试用户ID验证"""
        # 有效用户ID
        assert validate_user_id("user_1234567890_abcdefghij") == True
        assert validate_user_id("test-user-id-with-dash-123") == True
        assert validate_user_id("TEST_USER_WITH_UNDERSCORE") == True
        
        # 无效用户ID
        assert validate_user_id("short") == False  # 太短
        assert validate_user_id("a" * 51) == False  # 太长
        assert validate_user_id("user@with#invalid$chars") == False  # 非法字符
        assert validate_user_id("") == False  # 空字符串
        assert validate_user_id(None) == False  # None
        assert validate_user_id(123) == False  # 非字符串
    
    def test_validate_email(self):
        """测试邮箱验证"""
        # 有效邮箱
        assert validate_email("test@example.com") == True
        assert validate_email("user.name@domain.co.uk") == True
        assert validate_email("user+tag@example.com") == True
        
        # 无效邮箱
        assert validate_email("not-an-email") == False
        assert validate_email("@example.com") == False
        assert validate_email("user@") == False
        assert validate_email("user@.com") == False
        assert validate_email("a" * 255 + "@example.com") == False  # 太长
        assert validate_email("") == False
        assert validate_email(None) == False
    
    def test_validate_version(self):
        """测试版本号验证"""
        # 有效版本号
        assert validate_version(1) == True
        assert validate_version(100) == True
        assert validate_version("1") == True  # 字符串数字
        assert validate_version("100") == True
        
        # 无效版本号
        assert validate_version(0) == False  # 必须 >= 1
        assert validate_version(-1) == False
        assert validate_version("0") == False
        assert validate_version("not-a-number") == False
        assert validate_version(None) == False
        assert validate_version("") == False
        assert validate_version(1.5) == False  # 浮点数
    
    def test_validate_vault_data(self):
        """测试vault数据验证"""
        # 有效vault数据
        valid_vault = {
            "version": 1,
            "encrypted_data": "base64-encrypted-data",
            "signature": "signature-data"
        }
        assert validate_vault_data(valid_vault) == True
        
        # 带额外字段的vault数据
        valid_vault_extended = {
            "version": 100,
            "encrypted_data": "x" * 1000,  # 1KB数据
            "signature": "sig",
            "metadata": {"key": "value"}
        }
        assert validate_vault_data(valid_vault_extended) == True
        
        # 无效vault数据
        assert validate_vault_data({}) == False  # 缺少必需字段
        assert validate_vault_data({"version": 1}) == False  # 缺少字段
        assert validate_vault_data({
            "version": 0,  # 无效版本
            "encrypted_data": "data",
            "signature": "sig"
        }) == False
        
        # 加密数据太大
        huge_data = {
            "version": 1,
            "encrypted_data": "x" * (10 * 1024 * 1024 + 1),  # 超过10MB
            "signature": "sig"
        }
        assert validate_vault_data(huge_data) == False
        
        # 非字典类型
        assert validate_vault_data("string") == False
        assert validate_vault_data(None) == False
        assert validate_vault_data([]) == False


class TestValidationTools:
    """验证工具测试"""
    
    def test_validate_or_raise(self):
        """测试验证或抛出异常"""
        # 有效数据
        data = {
            "user_id": "valid_user_id_1234567890",
            "version": "10"
        }
        
        rules = {
            "user_id": validate_user_id,
            "version": validate_version
        }
        
        validated = validate_or_raise(data, rules)
        assert validated["user_id"] == data["user_id"]
        assert validated["version"] == data["version"]
        
        # 缺少字段
        with pytest.raises(ValidationError, match="Missing field"):
            validate_or_raise({"user_id": "valid"}, rules)
        
        # 无效字段值
        with pytest.raises(ValidationError, match="Invalid value"):
            validate_or_raise({
                "user_id": "too-short",
                "version": "1"
            }, rules)
    
    def test_validation_rules(self):
        """测试预定义验证规则"""
        assert VALIDATION_RULES["user_id"] == validate_user_id
        assert VALIDATION_RULES["email"] == validate_email
        assert VALIDATION_RULES["version"] == validate_version
        assert VALIDATION_RULES["vault_data"] == validate_vault_data


class TestValidationDecorators:
    """测试验证装饰器（需要Flask上下文）"""
    
    def test_validation_error_class(self):
        """测试ValidationError异常"""
        error = ValidationError("Test error")
        assert str(error) == "Test error"
        
        # 检查是否为Exception子类
        assert issubclass(ValidationError, Exception)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
