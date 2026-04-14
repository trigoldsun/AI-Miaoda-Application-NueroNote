#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote Server - Modern Architecture
高并发、高安全性、高用户体验的笔记同步服务
"""

import os
import sys
import logging
import time
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from flask import Flask, jsonify, request
from flask_cors import CORS

from nueronote_server.config import settings
from nueronote_server.db import init_database, get_engine
from nueronote_server.cache import init_cache, close_cache
from nueronote_server.middleware.security_headers import SecurityHeaders
from nueronote_server.middleware.rate_limit import init_rate_limiter
from nueronote_server.middleware.auth import init_auth_middleware
from nueronote_server.services.user import init_user_service

# 导入蓝图
from nueronote_server.api.auth import auth_bp
from nueronote_server.api.vault import vault_bp
from nueronote_server.api.sync import sync_bp
from nueronote_server.api.cloud import cloud_bp
from nueronote_server.api.account import account_bp
from nueronote_server.api.core import core_bp
# 其他蓝图将在后续添加

# 配置日志
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)

logger = logging.getLogger(__name__)


def create_app():
    """
    创建Flask应用工厂函数
    
    Returns:
        Flask应用实例
    """
    # 创建Flask应用
    app = Flask(__name__)
    
    # 应用配置
    app.config.update(
        SECRET_KEY=settings.security.secret_key,
        JWT_SECRET=settings.security.jwt_secret,
        MAX_CONTENT_LENGTH=settings.storage.max_request_size,
        JSON_SORT_KEYS=False,
        PROPAGATE_EXCEPTIONS=True,
    )
    
    # 启用CORS（生产环境应限制来源）
    CORS(app, resources={
        r"/api/*": {
            "origins": "*" if settings.debug else [
                "https://nueronote.app",
                "https://app.nueronote.com",
            ],
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Authorization", "Content-Type"],
            "max_age": 86400,
        }
    })
    
    # 初始化组件
    initialize_components(app)
    
    # 注册蓝图
    register_blueprints(app)
    
    # 注册错误处理器
    register_error_handlers(app)
    
    # 注册健康检查
    register_health_check(app)
    
    # 注册中间件
    register_middleware(app)
    
    logger.info("NueroNote应用创建完成")
    
    return app


def initialize_components(app):
    """
    初始化所有组件
    
    Args:
        app: Flask应用实例
    """
    logger.info("开始初始化组件...")
    
    # 初始化数据库
    try:
        init_database()
        engine = get_engine()
        logger.info(f"数据库初始化成功: {engine.url}")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        if not settings.debug:
            raise
    
    # 初始化Redis缓存
    cache = init_cache()
    if cache:
        logger.info("Redis缓存初始化成功")
    else:
        logger.warning("Redis缓存未启用或初始化失败，将使用降级策略")
    
    # 初始化限流器
    limiter = init_rate_limiter()
    if limiter:
        logger.info("速率限制器初始化成功")
    
    # 初始化认证中间件
    auth = init_auth_middleware()
    if auth:
        logger.info("认证中间件初始化成功")
    
    # 初始化业务服务
    user_service = init_user_service()
    if user_service:
        logger.info("用户服务初始化成功")
    
    logger.info("所有组件初始化完成")


def register_blueprints(app):
    """
    注册API蓝图
    
    Args:
        app: Flask应用实例
    """
    # 核心API（无前缀）
    app.register_blueprint(core_bp)
    
    # 认证API
    app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')
    
    # Vault管理API
    app.register_blueprint(vault_bp, url_prefix='/api/v1/vault')
    
    # 同步API
    app.register_blueprint(sync_bp, url_prefix='/api/v1/sync')
    
    # 云存储API
    app.register_blueprint(cloud_bp, url_prefix='/api/v1/cloud')
    
    # 账户管理API
    app.register_blueprint(account_bp, url_prefix='/api/v1/account')
    
    logger.info("API蓝图注册完成，共注册6个蓝图")
    logger.info(f"  - {core_bp.name}: {core_bp.url_prefix or '/'}")
    logger.info(f"  - {auth_bp.name}: {auth_bp.url_prefix}")
    logger.info(f"  - {vault_bp.name}: {vault_bp.url_prefix}")
    logger.info(f"  - {sync_bp.name}: {sync_bp.url_prefix}")
    logger.info(f"  - {cloud_bp.name}: {cloud_bp.url_prefix}")
    logger.info(f"  - {account_bp.name}: {account_bp.url_prefix}")


def register_error_handlers(app):
    """
    注册错误处理器
    
    Args:
        app: Flask应用实例
    """
    
    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({
            'error': 'Bad Request',
            'message': str(error.description) if hasattr(error, 'description') else 'Invalid request',
        }), 400
    
    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify({
            'error': 'Unauthorized',
            'message': 'Authentication required',
        }), 401
    
    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({
            'error': 'Forbidden',
            'message': 'Insufficient permissions',
        }), 403
    
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({
            'error': 'Not Found',
            'message': 'The requested resource was not found',
        }), 404
    
    @app.errorhandler(405)
    def method_not_allowed(error):
        return jsonify({
            'error': 'Method Not Allowed',
            'message': 'The HTTP method is not allowed for this endpoint',
        }), 405
    
    @app.errorhandler(413)
    def payload_too_large(error):
        return jsonify({
            'error': 'Payload Too Large',
            'message': f'Request body exceeds {settings.storage.max_content_length} bytes limit',
        }), 413
    
    @app.errorhandler(429)
    def too_many_requests(error):
        return jsonify({
            'error': 'Too Many Requests',
            'message': 'Rate limit exceeded. Please try again later.',
        }), 429
    
    @app.errorhandler(500)
    def internal_server_error(error):
        logger.error(f"Internal Server Error: {error}")
        return jsonify({
            'error': 'Internal Server Error',
            'message': 'An unexpected error occurred',
        }), 500
    
    logger.info("错误处理器注册完成")


def register_health_check(app):
    """
    注册健康检查端点
    
    Args:
        app: Flask应用实例
    """
    
    @app.route('/health', methods=['GET'])
    def health_check():
        """
        健康检查端点
        返回服务状态和组件健康状态
        """
        health_status = {
            'status': 'healthy',
            'timestamp': time.time(),
            'version': '1.0.0',
            'components': {},
        }
        
        # 检查数据库连接
        try:
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute('SELECT 1')
            health_status['components']['database'] = 'healthy'
        except Exception as e:
            health_status['components']['database'] = 'unhealthy'
            health_status['status'] = 'degraded'
            logger.error(f"数据库健康检查失败: {e}")
        
        # 检查Redis缓存
        from nueronote_server.cache import get_cache
        try:
            cache = get_cache()
            if cache:
                cache.client.ping()
                health_status['components']['redis'] = 'healthy'
            else:
                health_status['components']['redis'] = 'disabled'
        except Exception as e:
            health_status['components']['redis'] = 'unhealthy'
            health_status['status'] = 'degraded'
            logger.error(f"Redis健康检查失败: {e}")
        
        # 计算运行时间
        if hasattr(app, 'start_time'):
            health_status['uptime'] = time.time() - app.start_time
        
        return jsonify(health_status), 200 if health_status['status'] == 'healthy' else 503
    
    @app.route('/version', methods=['GET'])
    def version_info():
        """
        版本信息端点
        """
        return jsonify({
            'name': 'NueroNote',
            'version': '1.0.0',
            'architecture': 'modern',
            'description': 'End-to-end encrypted note synchronization service',
            'features': [
                'Zero-knowledge encryption',
                'Real-time synchronization',
                'Cloud storage integration',
                'High concurrency support',
                'Enterprise-grade security',
            ]
        })
    
    logger.info("健康检查端点注册完成")


def register_middleware(app):
    """
    注册中间件
    
    Args:
        app: Flask应用实例
    """
    # 安全头部中间件
    security = SecurityHeaders()
    security.init_app(app)
    
    logger.info("中间件注册完成")


def main():
    """
    应用主入口点
    """
    # 创建应用
    app = create_app()
    
    # 记录启动时间
    app.start_time = time.time()
    
    # 启动服务器
    host = settings.host
    port = settings.port
    debug = settings.debug
    
    logger.info(f"启动NueroNote服务器: http://{host}:{port}")
    logger.info(f"调试模式: {debug}")
    logger.info(f"数据库: {settings.database.url}")
    logger.info(f"Redis缓存: {settings.redis.enabled}")
    
    app.run(
        host=host,
        port=port,
        debug=debug,
        threaded=True,
    )


if __name__ == '__main__':
    main()
