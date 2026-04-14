#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 数据库模块
封装数据库连接、初始化和连接池管理。
"""

import os
import sqlite3
from typing import Optional

from flask import g


class Database:
    """数据库管理类"""
    
    def __init__(self, db_path: Optional[str] = None):
        """
        初始化数据库
        
        Args:
            db_path: 数据库文件路径，默认为环境变量FLUX_DB或nueronote.db
        """
        self.db_path = db_path or os.environ.get("FLUX_DB", "nueronote.db")
        self._init_done = False
    
    def get_connection(self) -> sqlite3.Connection:
        """
        获取数据库连接（Flask请求上下文）
        
        Returns:
            sqlite3.Connection: 数据库连接对象
        """
        if "db" not in g:
            g.db = sqlite3.connect(
                self.db_path,
                timeout=30,          # 30秒锁等待（高并发场景）
                isolation_level=None,  # 显式事务管理
                check_same_thread=False,
            )
            g.db.row_factory = sqlite3.Row
            
            # 优化SQLite配置
            g.db.execute("PRAGMA journal_mode=WAL")
            g.db.execute("PRAGMA synchronous=NORMAL")
            g.db.execute("PRAGMA foreign_keys=ON")
            g.db.execute("PRAGMA temp_store=MEMORY")
        
        return g.db
    
    def init_database(self) -> None:
        """
        初始化数据库表结构
        如果已初始化则跳过
        """
        if self._init_done:
            return
        
        db = self.get_connection()
        
        # 启用外键约束
        db.execute("PRAGMA foreign_keys = ON")
        
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id              TEXT PRIMARY KEY,
            email           TEXT UNIQUE NOT NULL,
            password_hash   TEXT,
            plan            TEXT DEFAULT 'free',
            storage_quota   INTEGER DEFAULT 536870912,  -- 512 MB
            storage_used    INTEGER DEFAULT 0,
            vault_version   INTEGER DEFAULT 1,
            created_at      INTEGER NOT NULL,
            updated_at      INTEGER NOT NULL,

            -- 账户安全字段
            login_fails     INTEGER DEFAULT 0,
            locked_until    INTEGER DEFAULT 0,
            last_login      INTEGER DEFAULT 0,
            last_ip         TEXT,
            cloud_config   TEXT
        );

        CREATE TABLE IF NOT EXISTS vaults (
            user_id         TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            vault_json      TEXT NOT NULL,
            vault_version   INTEGER DEFAULT 1,
            updated_at      INTEGER NOT NULL,
            updated_seq     INTEGER DEFAULT 0,
            storage_bytes   INTEGER DEFAULT 0,
            last_synced_at INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sync_log (
            id              TEXT PRIMARY KEY,
            user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            record_type     TEXT NOT NULL,
            record_id       TEXT NOT NULL,
            operation       TEXT NOT NULL,
            encrypted_data  TEXT NOT NULL,
            vector_clock    INTEGER DEFAULT 0,
            created_at      INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT,
            action          TEXT NOT NULL,
            ip_addr         TEXT,
            user_agent      TEXT,
            resource_type   TEXT,
            resource_id     TEXT,
            details         TEXT,
            created_at      INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS vault_versions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            version         INTEGER NOT NULL,
            vault_json      TEXT NOT NULL,
            vault_bytes     INTEGER NOT NULL,
            created_at      INTEGER NOT NULL,
            note            TEXT DEFAULT '',
            is_auto         INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS document_versions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            doc_id          TEXT NOT NULL,
            version         INTEGER NOT NULL,
            doc_snapshot    TEXT NOT NULL,
            created_at      INTEGER NOT NULL,
            change_summary  TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS rate_limit (
            ip_addr         TEXT PRIMARY KEY,
            action          TEXT NOT NULL,
            count           INTEGER DEFAULT 1,
            window_start    INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sync_user      ON sync_log(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_user    ON audit_log(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_audit_time    ON audit_log(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_users_email   ON users(email);
        CREATE INDEX IF NOT EXISTS idx_vaultver_user ON vault_versions(user_id, version DESC);
        CREATE INDEX IF NOT EXISTS idx_docver_doc    ON document_versions(doc_id, version DESC);
        """)
        db.commit()
        
        self._init_done = True
    
    def close_connection(self, exception: Optional[Exception] = None) -> None:
        """
        关闭数据库连接（Flask teardown）
        
        Args:
            exception: 如果有异常发生
        """
        db = g.pop("db", None)
        if db is not None:
            db.close()
    
    def execute_query(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """
        执行SQL查询（参数化查询，防止SQL注入）
        
        Args:
            sql: SQL语句，使用?作为占位符
            params: 参数元组
            
        Returns:
            sqlite3.Cursor: 执行结果的游标
        """
        db = self.get_connection()
        return db.execute(sql, params)
    
    def execute_many(self, sql: str, params_list: list) -> None:
        """
        批量执行SQL
        
        Args:
            sql: SQL语句
            params_list: 参数列表
        """
        db = self.get_connection()
        db.executemany(sql, params_list)
    
    def fetch_one(self, sql: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        """
        获取单条记录
        
        Returns:
            单行记录或None
        """
        cursor = self.execute_query(sql, params)
        return cursor.fetchone()
    
    def fetch_all(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """
        获取所有记录
        
        Returns:
            记录列表
        """
        cursor = self.execute_query(sql, params)
        return cursor.fetchall()


# 全局数据库实例
_db_instance: Optional[Database] = None


def get_database() -> Database:
    """
    获取数据库实例（单例）
    
    Returns:
        Database: 数据库实例
    """
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance


def init_db() -> None:
    """初始化数据库（兼容旧接口）"""
    db = get_database()
    db.init_database()


def get_db() -> sqlite3.Connection:
    """获取数据库连接（兼容旧接口）"""
    db = get_database()
    return db.get_connection()


def close_db(exception: Optional[Exception] = None) -> None:
    """关闭数据库连接（兼容旧接口）"""
    db = get_database()
    db.close_connection(exception)
