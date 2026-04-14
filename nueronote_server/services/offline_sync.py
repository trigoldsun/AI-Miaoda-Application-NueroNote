#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 离线同步支持模块
支持操作队列、冲突解决、网络状态感知、离线存储等功能。

客户端使用示例:
```javascript
// 初始化离线同步
const syncManager = new OfflineSyncManager({
    storage: localStorage,
    onSync: (changes) => syncToServer(changes),
    onConflict: (conflict) => resolveConflict(conflict)
});

// 监听网络状态
window.addEventListener('online', () => syncManager.sync());
window.addEventListener('offline', () => syncManager.goOffline());
```

服务端辅助函数:
```python
from services.offline_sync import get_operation_store, resolve_conflicts

# 合并冲突
merged = resolve_conflicts(local_ops, remote_ops)
```
"""

import json
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Callable


class OperationType(Enum):
    """操作类型"""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    MOVE = "move"
    COPY = "copy"


class ConflictResolution(Enum):
    """冲突解决策略"""
    LOCAL_WINS = "local_wins"
    REMOTE_WINS = "remote_wins"
    MERGE = "merge"
    MANUAL = "manual"


@dataclass
class Operation:
    """同步操作"""
    id: str
    type: str  # OperationType
    document_id: str
    user_id: str
    data: Dict[str, Any]
    vector_clock: int
    timestamp: int  # 毫秒时间戳
    retry_count: int = 0
    status: str = "pending"  # pending, synced, failed, conflict
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Operation':
        return cls(**data)


@dataclass
class Conflict:
    """冲突描述"""
    document_id: str
    local_op: Operation
    remote_op: Operation
    resolution: str = ConflictResolution.MANUAL.value
    merged_data: Optional[Dict] = None
    resolved_at: Optional[int] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)


class OperationStore:
    """操作存储（服务端）"""
    
    def __init__(self, db_path: str = "nueronote.db"):
        self.db_path = db_path
        self._ensure_table()
    
    def _ensure_table(self):
        """确保存储表存在"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_operations (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                document_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                data TEXT NOT NULL,
                vector_clock INTEGER NOT NULL,
                timestamp INTEGER NOT NULL,
                retry_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending'
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_sync_ops_user_doc
            ON sync_operations(user_id, document_id, timestamp)
        """)
        conn.commit()
        conn.close()
    
    def add(self, op: Operation) -> bool:
        """添加操作"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                INSERT INTO sync_operations 
                (id, type, document_id, user_id, data, vector_clock, timestamp, retry_count, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                op.id, op.type, op.document_id, op.user_id,
                json.dumps(op.data), op.vector_clock, op.timestamp,
                op.retry_count, op.status
            ))
            conn.commit()
            return True
        except Exception as e:
            print(f"添加操作失败: {e}")
            return False
        finally:
            conn.close()
    
    def get_pending(self, user_id: str, limit: int = 100) -> List[Operation]:
        """获取待同步操作"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT * FROM sync_operations
            WHERE user_id = ? AND status = 'pending'
            ORDER BY timestamp ASC
            LIMIT ?
        """, (user_id, limit))
        
        ops = []
        for row in cursor.fetchall():
            op_dict = dict(row)
            op_dict['data'] = json.loads(op_dict['data'])
            ops.append(Operation(**op_dict))
        
        conn.close()
        return ops
    
    def mark_synced(self, op_id: str) -> bool:
        """标记为已同步"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                UPDATE sync_operations SET status = 'synced'
                WHERE id = ?
            """, (op_id,))
            conn.commit()
            return True
        finally:
            conn.close()
    
    def mark_failed(self, op_id: str) -> bool:
        """标记为失败"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("""
                UPDATE sync_operations 
                SET status = 'failed', retry_count = retry_count + 1
                WHERE id = ?
            """, (op_id,))
            conn.commit()
            return True
        finally:
            conn.close()
    
    def get_conflicts(self, user_id: str) -> List[Operation]:
        """获取冲突操作"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("""
            SELECT * FROM sync_operations
            WHERE user_id = ? AND status = 'conflict'
            ORDER BY timestamp ASC
        """, (user_id,))
        
        ops = []
        for row in cursor.fetchall():
            op_dict = dict(row)
            op_dict['data'] = json.loads(op_dict['data'])
            ops.append(Operation(**op_dict))
        
        conn.close()
        return ops


def resolve_conflicts(local_ops: List[Operation], 
                     remote_ops: List[Operation]) -> tuple:
    """
    解决同步冲突
    
    Args:
        local_ops: 本地操作列表
        remote_ops: 远程操作列表
    
    Returns:
        (merged_ops, conflicts)
        merged_ops: 合并后的操作列表
        conflicts: 无法自动解决的冲突列表
    """
    merged = []
    conflicts = []
    
    # 按文档ID分组
    local_by_doc = {}
    remote_by_doc = {}
    
    for op in local_ops:
        local_by_doc.setdefault(op.document_id, []).append(op)
    
    for op in remote_ops:
        remote_by_doc.setdefault(op.document_id, []).append(op)
    
    # 处理每个文档的操作
    all_docs = set(local_by_doc.keys()) | set(remote_by_doc.keys())
    
    for doc_id in all_docs:
        local_doc_ops = local_by_doc.get(doc_id, [])
        remote_doc_ops = remote_by_doc.get(doc_id, [])
        
        if not local_doc_ops:
            # 只有远程操作，直接采用
            merged.extend(remote_doc_ops)
        elif not remote_doc_ops:
            # 只有本地操作，直接采用
            merged.extend(local_doc_ops)
        else:
            # 都有操作，检查冲突
            local_latest = max(local_doc_ops, key=lambda x: x.vector_clock)
            remote_latest = max(remote_doc_ops, key=lambda x: x.vector_clock)
            
            # 使用向量时钟判断
            if local_latest.vector_clock > remote_latest.vector_clock:
                # 本地更新，使用本地
                merged.extend(local_doc_ops)
            elif remote_latest.vector_clock > local_latest.vector_clock:
                # 远程更新，使用远程
                merged.extend(remote_doc_ops)
            else:
                # 时钟相同，检查时间戳
                if local_latest.timestamp >= remote_latest.timestamp:
                    merged.extend(local_doc_ops)
                else:
                    merged.extend(remote_doc_ops)
    
    return merged, conflicts


class SyncQueue:
    """客户端同步队列（用于本地存储）"""
    
    def __init__(self, storage: Any = None):
        """
        初始化同步队列
        
        Args:
            storage: 存储后端（localStorage, IndexedDB等）
        """
        self.storage = storage or {}
        self.queue_key = "sync_queue"
        self.pending_ops: deque = deque()
        self._load_from_storage()
    
    def _load_from_storage(self):
        """从存储加载队列"""
        try:
            data = self.storage.get(self.queue_key)
            if data:
                ops = json.loads(data)
                self.pending_ops = deque([Operation(**op) for op in ops])
        except:
            self.pending_ops = deque()
    
    def _save_to_storage(self):
        """保存队列到存储"""
        try:
            ops_data = [op.to_dict() for op in self.pending_ops]
            self.storage.set(self.queue_key, json.dumps(ops_data))
        except:
            pass
    
    def enqueue(self, op: Operation) -> None:
        """入队"""
        self.pending_ops.append(op)
        self._save_to_storage()
    
    def dequeue(self) -> Optional[Operation]:
        """出队"""
        try:
            op = self.pending_ops.popleft()
            self._save_to_storage()
            return op
        except IndexError:
            return None
    
    def peek(self) -> Optional[Operation]:
        """查看队首"""
        try:
            return self.pending_ops[0]
        except IndexError:
            return None
    
    def size(self) -> int:
        """队列大小"""
        return len(self.pending_ops)
    
    def clear(self) -> None:
        """清空队列"""
        self.pending_ops.clear()
        self._save_to_storage()
    
    def get_all(self) -> List[Operation]:
        """获取所有待同步操作"""
        return list(self.pending_ops)
    
    def retry_failed(self) -> int:
        """重试失败的操作"""
        retried = 0
        for op in self.pending_ops:
            if op.status == "failed" and op.retry_count < 3:
                op.status = "pending"
                retried += 1
        self._save_to_storage()
        return retried


class ConflictResolver:
    """冲突解决器"""
    
    def __init__(self, strategy: str = ConflictResolution.LAST_WRITE_WINS.value):
        """
        初始化冲突解决器
        
        Args:
            strategy: 解决策略
        """
        self.strategy = strategy
    
    def resolve(self, local_op: Operation, remote_op: Operation) -> Operation:
        """
        解决冲突
        
        Returns:
            解决后的操作
        """
        if self.strategy == ConflictResolution.LOCAL_WINS.value:
            return local_op
        elif self.strategy == ConflictResolution.REMOTE_WINS.value:
            return remote_op
        elif self.strategy == ConflictResolution.MERGE.value:
            return self._merge(local_op, remote_op)
        else:
            # MANUAL - 标记为冲突需要手动解决
            local_op.status = "conflict"
            return local_op
    
    def _merge(self, local_op: Operation, remote_op: Operation) -> Operation:
        """合并操作"""
        # 简单的字段级别合并
        merged_data = {**remote_op.data, **local_op.data}
        
        return Operation(
            id=local_op.id,
            type=local_op.type,
            document_id=local_op.document_id,
            user_id=local_op.user_id,
            data=merged_data,
            vector_clock=max(local_op.vector_clock, remote_op.vector_clock) + 1,
            timestamp=int(time.time() * 1000),
            status="pending"
        )


# 便捷函数
def get_operation_store(db_path: str = "nueronote.db") -> OperationStore:
    """获取操作存储实例"""
    return OperationStore(db_path)
