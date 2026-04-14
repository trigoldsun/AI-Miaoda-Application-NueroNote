#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 安全头部中间件
设置安全的HTTP响应头部，防止常见Web攻击
"""

import logging
from typing import Dict, Any, Optional
from functools import wraps

from flask import request, g, jsonify, Response, make_response


logger = logging.getLogger(__name__)


class SecurityHeaders:
    """
    安全头部管理器
    
    设置安全的HTTP响应头部：
    - CSP: 内容安全策略
    - HSTS: HTTP严格传输安全
    - X-Frame-Options: 防止点击劫持
    - X-Content-Type-Options: 防止MIME类型嗅探
    - Referrer-Policy: 控制Referrer信息
    - Permissions-Policy: 浏览器功能权限
    """
    
    # 默认安全头部配置
    DEFAULT_HEADERS = {
        # 内容安全策略（CSP）
        'Content-Security-Policy': (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "connect-src 'self' https: wss:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self';"
        ),
        
        # HTTP严格传输安全（HSTS）
        'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
        
        # 防止点击劫持
        'X-Frame-Options': 'DENY',
        
        # 防止MIME类型嗅探
        'X-Content-Type-Options': 'nosniff',
        
        # XSS保护（已废弃，但保持兼容）
        'X-XSS-Protection': '0',
        
        # 引用策略
        'Referrer-Policy': 'strict-origin-when-cross-origin',
        
        # 权限策略
        'Permissions-Policy': (
            'camera=(), '
            'microphone=(), '
            'geolocation=(), '
            'payment=()'
        ),
        
        # 跨域资源策略
        'Cross-Origin-Resource-Policy': 'same-origin',
        
        # 跨域嵌入器策略
        'Cross-Origin-Embedder-Policy': 'require-corp',
        
        # 跨域开放者策略
        'Cross-Origin-Opener-Policy': 'same-origin',
    }
    
    # API端点的简化头部
    API_HEADERS = {
        'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none';",
        'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
        'X-Frame-Options': 'DENY',
        'X-Content-Type-Options': 'nosniff',
        'Referrer-Policy': 'no-referrer',
        'Permissions-Policy': (
            'camera=(), '
            'microphone=(), '
            'geolocation=(), '
            'payment=()'
        ),
    }
    
    def __init__(self, app=None):
        """
        初始化安全头部管理器
        
        Args:
            app: Flask应用实例
        """
        self.app = app
        self.headers = self.DEFAULT_HEADERS.copy()
        
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app):
        """
        初始化Flask应用
        
        Args:
            app: Flask应用实例
        """
        self.app = app
        
        # 注册后请求处理器
        @app.after_request
        def add_security_headers(response):
            return self._add_headers_to_response(response)
        
        # 注册错误处理器（确保错误页面也有安全头部）
        @app.errorhandler(404)
        @app.errorhandler(500)
        @app.errorhandler(429)
        def error_handler(e):
            response = make_response(jsonify({
                'error': str(e.code) if hasattr(e, 'code') else 'Server Error',
                'message': str(e.description) if hasattr(e, 'description') else str(e),
            }), e.code if hasattr(e, 'code') else 500)
            
            # 添加安全头部
            headers = self._get_headers_for_request(request)
            for key, value in headers.items():
                response.headers[key] = value
            
            return response
    
    def _get_headers_for_request(self, req) -> Dict[str, str]:
        """
        根据请求类型返回适当的头部
        
        Args:
            req: Flask请求对象
            
        Returns:
            安全头部字典
        """
        # API端点使用简化头部
        if req.path.startswith('/api/'):
            return self.API_HEADERS.copy()
        
        # 静态文件使用基本头部
        if req.path.startswith('/static/') or req.path.endswith(('.js', '.css', '.png', '.jpg', '.ico')):
            return {
                'X-Content-Type-Options': 'nosniff',
                'Cache-Control': 'public, max-age=31536000',
            }
        
        # 其他请求使用完整头部
        return self.headers.copy()
    
    def _add_headers_to_response(self, response: Response) -> Response:
        """
        添加安全头部到响应
        
        Args:
            response: Flask响应对象
            
        Returns:
            添加了安全头部的响应
        """
        headers = self._get_headers_for_request(request)
        
        for key, value in headers.items():
            # 如果响应还没有这个头部，则添加
            if key not in response.headers:
                response.headers[key] = value
        
        return response
    
    def update_headers(self, new_headers: Dict[str, str]):
        """
        更新安全头部配置
        
        Args:
            new_headers: 新的头部配置
        """
        self.headers.update(new_headers)
    
    def remove_header(self, header_name: str):
        """
        移除指定的安全头部
        
        Args:
            header_name: 头部名称
        """
        if header_name in self.headers:
            del self.headers[header_name]
    
    def set_csp(self, csp_directives: str):
        """
        设置内容安全策略
        
        Args:
            csp_directives: CSP指令字符串
        """
        self.headers['Content-Security-Policy'] = csp_directives
    
    def set_hsts(self, max_age: int = 31536000, include_subdomains: bool = True):
        """
        设置HSTS头部
        
        Args:
            max_age: 最大年龄（秒）
            include_subdomains: 是否包含子域名
        """
        hsts_value = f'max-age={max_age}'
        if include_subdomains:
            hsts_value += '; includeSubDomains'
        
        self.headers['Strict-Transport-Security'] = hsts_value


def security_headers_decorator(f):
    """
    安全头部装饰器（为单个路由添加安全头部）
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        response = f(*args, **kwargs)
        
        if isinstance(response, tuple):
            # 处理 (data, status) 或 (data, status, headers) 格式
            if len(response) == 2:
                data, status = response
                headers = {}
            elif len(response) == 3:
                data, status, headers = response
            else:
                return response
            
            # 创建响应对象
            resp = make_response(data, status)
            resp.headers.update(headers)
        else:
            resp = response
        
        # 添加安全头部
        security = SecurityHeaders()
        headers_to_add = security._get_headers_for_request(request)
        
        for key, value in headers_to_add.items():
            if key not in resp.headers:
                resp.headers[key] = value
        
        return resp
    
    return decorated_function


# 便捷函数
def add_security_headers(response: Response) -> Response:
    """
    为响应添加安全头部
    
    Args:
        response: Flask响应对象
        
    Returns:
        添加了安全头部的响应
    """
    security = SecurityHeaders()
    return security._add_headers_to_response(response)


def get_security_headers() -> Dict[str, str]:
    """
    获取当前请求的推荐安全头部
    
    Returns:
        安全头部字典
    """
    security = SecurityHeaders()
    return security._get_headers_for_request(request)
