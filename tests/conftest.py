#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 测试配置
"""

import os
import tempfile
import pytest
import sys

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from nueronote_server.app import app as flask_app
from nueronote_server.config import settings


@pytest.fixture
def app():
    """Flask应用fixture"""
    # 使用临时数据库
    db_fd, db_path = tempfile.mkstemp()
    flask_app.config['DATABASE_PATH'] = db_path
    flask_app.config['TESTING'] = True
    flask_app.config['SECRET_KEY'] = 'test-secret-key'
    flask_app.config['JWT_SECRET'] = 'test-jwt-secret'
    
    with flask_app.app_context():
        # 初始化测试数据库
        from nueronote_server.app import init_db
        init_db()
    
    yield flask_app
    
    # 清理
    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture
def client(app):
    """测试客户端fixture"""
    return app.test_client()


@pytest.fixture
def auth_headers():
    """生成认证头部（模拟JWT）"""
    # 简化测试：使用固定的用户ID
    return {
        'Authorization': 'Bearer test-token-user-1234567890',
        'Content-Type': 'application/json'
    }


@pytest.fixture
def sample_vault_data():
    """测试用的vault数据"""
    return {
        "version": 1,
        "encrypted_data": "test-encrypted-data-base64",
        "signature": "test-signature",
        "metadata": {
            "created_at": 1234567890,
            "device_id": "test-device"
        }
    }


@pytest.fixture
def sample_user_data():
    """测试用的用户数据"""
    return {
        "email": "test@example.com",
        "password_hash": "test-hash-not-real",
        "plan": "free"
    }
