#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 输入验证模块

提供请求参数验证和清洗功能，防止注入和恶意输入。
"""

import re
import json
from typing import Any, Dict, Optional, Callable, TypeVar, cast
from functools import wraps

from flask import request, jsonify


T = TypeVar('T')


# ============================================================================
# 验证器函数
# ============================================================================

def validate_user_id(user_id: str) -> bool:
    """
    验证用户ID格式
    规则：长度20-50，只包含字母、数字、下划线、减号
    """
    if not isinstance(user_id, str):
        return False
    if not (20 <= len(user_id) <= 50):
        return False
    if not re.match(r'^[a-zA-Z0-9_-]+$', user_id):
        return False
    return True


def validate_email(email: str) -> bool:
    """
    验证邮箱格式（简单版）
    """
    if not isinstance(email, str):
        return False
    if len(email) > 254:
        return False
    # 简单的邮箱正则
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_version(version: Any) -> bool:
    """
    验证版本号（正整数）
    """
    try:
        v = int(version)
        return v >= 1
    except (ValueError, TypeError):
        return False


def validate_vault_data(data: Any) -> bool:
    """
    验证vault数据格式
    必须是字典，且包含必需字段
    """
    if not isinstance(data, dict):
        return False
    
    # 检查必需字段
    required_fields = {'version', 'encrypted_data', 'signature'}
    if not required_fields.issubset(data.keys()):
        return False
    
    # 检查版本号
    if not validate_version(data.get('version')):
        return False
    
    # 检查加密数据大小（不超过10MB）
    encrypted_data = data.get('encrypted_data', '')
    if not isinstance(encrypted_data, str):
        return False
    if len(encrypted_data.encode('utf-8')) > 10 * 1024 * 1024:
        return False
    
    return True


def validate_json_payload(max_size: int = 10 * 1024 * 1024) -> bool:
    """
    验证JSON请求体
    """
    if not request.is_json:
        return False
    
    # 检查内容长度
    content_length = request.content_length or 0
    if content_length > max_size:
        return False
    
    return True


# ============================================================================
# 验证装饰器
# ============================================================================

def validate_request(*, required_fields: Optional[Dict[str, Callable]] = None,
                     json_schema: Optional[Dict] = None,
                     max_size: int = 10 * 1024 * 1024):
    """
    请求验证装饰器
    
    Args:
        required_fields: 必需字段及其验证函数
        json_schema: JSON Schema验证（暂未实现）
        max_size: 最大请求体大小
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            # 1. 检查请求体大小
            content_length = request.content_length or 0
            if content_length > max_size:
                return jsonify({
                    "error": f"Request too large (max {max_size} bytes)"
                }), 413
            
            # 2. 如果是JSON请求，验证JSON
            if request.is_json:
                try:
                    data = request.get_json(force=True, silent=False)
                except Exception:
                    return jsonify({"error": "Invalid JSON"}), 400
                
                # 3. 验证必需字段
                if required_fields:
                    for field_name, validator in required_fields.items():
                        if field_name not in data:
                            return jsonify({
                                "error": f"Missing required field: {field_name}"
                            }), 400
                        
                        field_value = data[field_name]
                        if not validator(field_value):
                            return jsonify({
                                "error": f"Invalid value for field: {field_name}"
                            }), 400
                
                # 将验证后的数据传递给视图函数
                request.validated_data = data
            
            return f(*args, **kwargs)
        return wrapper
    return decorator


def validate_user_id_param(param_name: str = "user_id"):
    """
    验证URL参数中的用户ID
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user_id = kwargs.get(param_name)
            if not user_id or not validate_user_id(user_id):
                return jsonify({
                    "error": f"Invalid {param_name} format"
                }), 400
            return f(*args, **kwargs)
        return wrapper
    return decorator


def validate_version_param(param_name: str = "version"):
    """
    验证URL参数中的版本号
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            version_str = kwargs.get(param_name)
            try:
                version = int(version_str)
                if version < 1:
                    raise ValueError
                kwargs[param_name] = version  # 转换为整数
            except (ValueError, TypeError):
                return jsonify({
                    "error": f"Invalid {param_name}: must be positive integer"
                }), 400
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ============================================================================
# 验证工具
# ============================================================================

class ValidationError(Exception):
    """验证错误异常"""
    pass


def validate_or_raise(data: Dict, rules: Dict[str, Callable]) -> Dict:
    """
    验证数据字典，如果验证失败则抛出ValidationError
    
    Args:
        data: 要验证的数据字典
        rules: 字段验证规则 {字段名: 验证函数}
    
    Returns:
        验证后的数据（可能经过转换）
    
    Raises:
        ValidationError: 验证失败
    """
    validated = {}
    
    for field, validator in rules.items():
        if field not in data:
            raise ValidationError(f"Missing field: {field}")
        
        value = data[field]
        try:
            if not validator(value):
                raise ValidationError(f"Invalid value for field: {field}")
            validated[field] = value
        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            raise ValidationError(f"Validation failed for field {field}: {e}")
    
    return validated


# ============================================================================
# 常用验证规则
# ============================================================================

# 预定义的验证规则
VALIDATION_RULES = {
    "user_id": validate_user_id,
    "email": validate_email,
    "version": validate_version,
    "vault_data": validate_vault_data,
}
