#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote WebSocket 实时同步模块
支持WebSocket连接、实时推送、同步状态更新等功能。

依赖: pip install flask-socketio
"""

import json
import time
from typing import Dict, Optional, Set
from functools import wraps

try:
    from flask_socketio import SocketIO, emit, join_room, leave_room
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False


class SyncNamespace:
    """同步命名空间处理器"""
    
    # 连接的客户端
    connected_clients: Set[str] = set()
    
    # 用户房间映射
    user_rooms: Dict[str, str] = {}  # user_id -> room
    
    def __init__(self, socketio: 'SocketIO'):
        self.socketio = socketio
        self.namespace = '/sync'
    
    def register_handlers(self):
        """注册事件处理器"""
        from flask import request
        
        @self.socketio.on('connect', namespace=self.namespace)
        def handle_connect():
            """处理客户端连接"""
            print(f"客户端连接: {request.sid}")
            emit('connected', {'status': 'ok', 'sid': request.sid})
        
        @self.socketio.on('disconnect', namespace=self.namespace)
        def handle_disconnect():
            """处理客户端断开"""
            sid = request.sid
            user_id = self._get_user_by_sid(sid)
            if user_id:
                self._handle_user_leave(user_id)
            print(f"客户端断开: {sid}")
        
        @self.socketio.on('authenticate', namespace=self.namespace)
        def handle_authenticate(data):
            """处理用户认证"""
            token = data.get('token', '')
            user_id = self._verify_token(token)
            
            if user_id:
                # 将用户加入其专属房间
                room = f"user_{user_id}"
                join_room(room)
                self.user_rooms[request.sid] = room
                self.connected_clients.add(request.sid)
                
                emit('authenticated', {
                    'status': 'ok',
                    'user_id': user_id,
                    'room': room
                })
                print(f"用户认证成功: {user_id}")
            else:
                emit('error', {'message': '认证失败'})
        
        @self.socketio.on('subscribe', namespace=self.namespace)
        def handle_subscribe(data):
            """处理订阅请求"""
            user_id = data.get('user_id')
            document_id = data.get('document_id')
            
            if user_id and document_id:
                room = f"doc_{document_id}"
                join_room(room)
                emit('subscribed', {
                    'document_id': document_id,
                    'room': room
                })
                print(f"用户 {user_id} 订阅文档 {document_id}")
        
        @self.socketio.on('unsubscribe', namespace=self.namespace)
        def handle_unsubscribe(data):
            """处理取消订阅"""
            document_id = data.get('document_id')
            if document_id:
                room = f"doc_{document_id}"
                leave_room(room)
                emit('unsubscribed', {'document_id': document_id})
        
        @self.socketio.on('sync_push', namespace=self.namespace)
        def handle_sync_push(data):
            """处理增量同步推送"""
            user_id = data.get('user_id')
            changes = data.get('changes', [])
            
            if not user_id:
                emit('error', {'message': '未认证'})
                return
            
            # 处理变更
            processed = self._process_changes(user_id, changes)
            
            # 广播给订阅者
            for change in processed:
                doc_id = change.get('document_id')
                room = f"doc_{doc_id}"
                self.socketio.emit('remote_change', change, room=room, namespace=self.namespace)
            
            emit('sync_ack', {
                'processed': len(processed),
                'timestamp': int(time.time() * 1000)
            })
        
        @self.socketio.on('presence_update', namespace=self.namespace)
        def handle_presence(data):
            """处理在线状态更新"""
            user_id = data.get('user_id')
            document_id = data.get('document_id')
            status = data.get('status', 'online')  # online, offline, typing
            
            if user_id and document_id:
                room = f"doc_{document_id}"
                self.socketio.emit('presence', {
                    'user_id': user_id,
                    'status': status,
                    'timestamp': int(time.time() * 1000)
                }, room=room, namespace=self.namespace)
        
        @self.socketio.on('cursor_update', namespace=self.namespace)
        def handle_cursor(data):
            """处理光标位置更新"""
            user_id = data.get('user_id')
            document_id = data.get('document_id')
            position = data.get('position')
            
            if user_id and document_id:
                room = f"doc_{document_id}"
                self.socketio.emit('cursor', {
                    'user_id': user_id,
                    'position': position,
                    'timestamp': int(time.time() * 1000)
                }, room=room, include_self=False, namespace=self.namespace)
    
    def _verify_token(self, token: str) -> Optional[str]:
        """验证JWT token"""
        if not token:
            return None
        try:
            from nueronote_server.utils.jwt import verify_token
            from flask import current_app
            return verify_token(token, current_app.config.get('JWT_SECRET', ''))
        except:
            return None
    
    def _get_user_by_sid(self, sid: str) -> Optional[str]:
        """根据会话ID获取用户ID"""
        room = self.user_rooms.get(sid)
        if room and room.startswith('user_'):
            return room[5:]
        return None
    
    def _handle_user_leave(self, user_id: str):
        """处理用户离开"""
        room = f"user_{user_id}"
        leave_room(room)
        self.connected_clients.discard(user_id)
        if user_id in self.user_rooms.values():
            self.user_rooms = {k: v for k, v in self.user_rooms.items() if v != room}
    
    def _process_changes(self, user_id: str, changes: list) -> list:
        """处理变更并返回需要广播的变更"""
        processed = []
        for change in changes:
            processed.append({
                'user_id': user_id,
                'document_id': change.get('document_id'),
                'operation': change.get('operation'),
                'data': change.get('data'),
                'timestamp': int(time.time() * 1000),
                'vector_clock': change.get('vector_clock', 0),
            })
        return processed
    
    def broadcast_to_user(self, user_id: str, event: str, data: dict):
        """向指定用户广播消息"""
        room = f"user_{user_id}"
        self.socketio.emit(event, data, room=room, namespace=self.namespace)
    
    def broadcast_to_document(self, document_id: str, event: str, data: dict):
        """向文档订阅者广播消息"""
        room = f"doc_{document_id}"
        self.socketio.emit(event, data, room=room, namespace=self.namespace)


class SyncServer:
    """同步服务器"""
    
    def __init__(self, app=None):
        self.app = app
        self.socketio: Optional[SocketIO] = None
        self.sync_namespace: Optional[SyncNamespace] = None
    
    def init_app(self, app):
        """初始化应用"""
        self.app = app
        
        if not WEBSOCKET_AVAILABLE:
            print("警告: flask-socketio未安装，WebSocket功能不可用")
            print("安装命令: pip install flask-socketio")
            return
        
        # 创建SocketIO实例
        self.socketio = SocketIO(
            app,
            cors_allowed_origins="*",
            async_mode='threading',
            message_queue=None,  # 使用内存消息队列
            channel='sync'
        )
        
        # 创建命名空间处理器
        self.sync_namespace = SyncNamespace(self.socketio)
        self.sync_namespace.register_handlers()
        
        print("✓ WebSocket同步服务已初始化")
    
    def push_sync_update(self, user_id: str, document_id: str, operation: str, data: dict):
        """推送同步更新"""
        if self.socketio and self.sync_namespace:
            self.sync_namespace.broadcast_to_document(document_id, 'sync_update', {
                'user_id': user_id,
                'operation': operation,
                'data': data,
                'timestamp': int(time.time() * 1000)
            })
    
    def push_notification(self, user_id: str, title: str, body: str):
        """推送通知"""
        if self.socketio and self.sync_namespace:
            self.sync_namespace.broadcast_to_user(user_id, 'notification', {
                'title': title,
                'body': body,
                'timestamp': int(time.time() * 1000)
            })
    
    def run(self, host: str = '0.0.0.0', port: int = 5000, **kwargs):
        """运行服务器"""
        if self.socketio:
            print(f"启动WebSocket服务器: ws://{host}:{port}")
            self.socketio.run(self.app, host=host, port=port, **kwargs)
        else:
            print("错误: WebSocket未初始化")


# 全局实例
_sync_server: Optional[SyncServer] = None


def get_sync_server() -> Optional[SyncServer]:
    """获取同步服务器实例"""
    return _sync_server


def init_sync_server(app=None) -> Optional[SyncServer]:
    """初始化同步服务器"""
    global _sync_server
    if _sync_server is None and WEBSOCKET_AVAILABLE:
        _sync_server = SyncServer(app)
        if app:
            _sync_server.init_app(app)
    return _sync_server
