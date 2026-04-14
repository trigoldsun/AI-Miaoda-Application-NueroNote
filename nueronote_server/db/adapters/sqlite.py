#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQLite 数据库适配器
轻量级适配器，支持SQLite 3.8+，包括WAL模式、连接池等
"""

import os
import logging
import sqlite3
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path

from sqlalchemy import create_engine, Engine, text
from sqlalchemy.pool import StaticPool, QueuePool
from sqlalchemy.exc import SQLAlchemyError

from nueronote_server.db.adapters import DatabaseAdapter


logger = logging.getLogger(__name__)


class SQLiteAdapter(DatabaseAdapter):
    """
    SQLite 数据库适配器
    
    特性：
    - WAL模式（Write-Ahead Logging）
    - 内存数据库支持
    - 连接池（有限支持）
    - 自动创建目录
    - 性能优化参数
    """
    
    @property
    def dialect(self) -> str:
        return "sqlite"
    
    @property
    def supports_transactions(self) -> bool:
        return True
    
    @property
    def supports_json(self) -> bool:
        # SQLite 3.9+ 支持JSON扩展
        # 检查是否启用了JSON扩展
        return True
    
    @property
    def supports_full_text_search(self) -> bool:
        # SQLite支持FTS5扩展
        return True
    
    @property
    def default_isolation_level(self) -> str:
        return "DEFERRED"
    
    def create_engine(self) -> Engine:
        """
        创建SQLite引擎
        """
        pool_config = self.get_connection_pool_config()
        connect_args = self.get_connect_args()
        
        # 确保数据库文件目录存在
        if self.connection_url.startswith('sqlite:///') and 'sqlite:///:memory:' not in self.connection_url:
            db_path = self._extract_db_path()
            if db_path:
                db_dir = os.path.dirname(db_path)
                if db_dir and not os.path.exists(db_dir):
                    os.makedirs(db_dir, exist_ok=True)
                    logger.info(f"创建数据库目录: {db_dir}")
        
        # 创建引擎
        engine = create_engine(
            self.connection_url,
            echo=self.echo,
            **pool_config,
            connect_args=connect_args,
        )
        
        # 设置SQLite优化参数
        self._configure_sqlite(engine)
        
        return engine
    
    def _extract_db_path(self) -> Optional[str]:
        """
        从连接URL提取数据库文件路径
        """
        if self.connection_url.startswith('sqlite:///'):
            path_part = self.connection_url[10:]  # 移除'sqlite:///'
            if path_part.startswith('/'):
                return path_part
            elif path_part.startswith('./'):
                return os.path.abspath(path_part)
            else:
                return path_part
        return None
    
    def _configure_sqlite(self, engine: Engine) -> None:
        """
        配置SQLite优化参数
        """
        if self.connection_url == 'sqlite:///:memory:':
            # 内存数据库，不需要WAL
            return
        
        # 设置WAL模式和优化参数
        init_commands = [
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = NORMAL",
            "PRAGMA foreign_keys = ON",
            "PRAGMA temp_store = MEMORY",
            "PRAGMA mmap_size = 268435456",  # 256MB mmap
        ]
        
        if self.config.get('cache_size'):
            init_commands.append(f"PRAGMA cache_size = -{self.config['cache_size']}")
        
        # 执行初始化命令
        with engine.connect() as conn:
            for cmd in init_commands:
                try:
                    conn.execute(text(cmd))
                except Exception as e:
                    logger.warning(f"SQLite配置命令失败 {cmd}: {e}")
    
    def get_connection_pool_config(self) -> Dict[str, Any]:
        """
        获取SQLite连接池配置
        """
        if self.connection_url == 'sqlite:///:memory:':
            # 内存数据库使用StaticPool
            return {
                'poolclass': StaticPool,
                'connect_args': self.get_connect_args(),
            }
        else:
            # 文件数据库使用QueuePool
            return {
                'poolclass': QueuePool,
                'pool_size': self.pool_size,
                'max_overflow': self.max_overflow,
                'pool_timeout': self.pool_timeout,
                'pool_recycle': self.pool_recycle,
                'pool_pre_ping': False,  # SQLite不需要pre-ping
            }
    
    def get_connect_args(self) -> Dict[str, Any]:
        """
        获取SQLite连接参数
        """
        connect_args = {
            'check_same_thread': False,
            'timeout': self.config.get('timeout', 30.0),
        }
        
        # 添加自定义函数（如果需要）
        if self.config.get('register_json'):
            connect_args['detect_types'] = sqlite3.PARSE_DECLTYPES
        
        return connect_args
    
    def test_connection(self, timeout: int = 5) -> bool:
        """
        测试SQLite连接
        """
        try:
            engine = self.get_engine()
            with engine.connect() as conn:
                # 执行简单查询
                result = conn.execute(text("SELECT sqlite_version(), 1"))
                row = result.fetchone()
                
                if row:
                    logger.info(f"SQLite连接测试成功: version {row[0]}")
                    return True
                
                return False
        except Exception as e:
            logger.error(f"SQLite连接测试失败: {e}")
            return False
    
    def get_database_info(self) -> Dict[str, Any]:
        """
        获取SQLite数据库信息
        """
        try:
            engine = self.get_engine()
            with engine.connect() as conn:
                info = {}
                
                # SQLite版本
                result = conn.execute(text("SELECT sqlite_version()"))
                info['version'] = result.scalar()
                
                # 数据库文件信息
                if self.connection_url.startswith('sqlite:///') and self.connection_url != 'sqlite:///:memory:':
                    db_path = self._extract_db_path()
                    if db_path and os.path.exists(db_path):
                        info['file_path'] = db_path
                        info['file_size'] = os.path.getsize(db_path)
                        info['modified_time'] = os.path.getmtime(db_path)
                
                # 编译选项
                result = conn.execute(text("PRAGMA compile_options"))
                compile_options = [row[0] for row in result.fetchall()]
                info['compile_options'] = compile_options
                
                # 数据库大小
                result = conn.execute(text("SELECT page_count * page_size FROM pragma_page_count(), pragma_page_size()"))
                size_row = result.fetchone()
                if size_row:
                    info['size_bytes'] = size_row[0]
                
                # 表数量
                result = conn.execute(text("SELECT COUNT(*) FROM sqlite_master WHERE type='table'"))
                info['table_count'] = result.scalar()
                
                # 索引数量
                result = conn.execute(text("SELECT COUNT(*) FROM sqlite_master WHERE type='index'"))
                info['index_count'] = result.scalar()
                
                # 当前设置
                pragmas = [
                    'journal_mode', 'synchronous', 'foreign_keys',
                    'temp_store', 'cache_size', 'mmap_size',
                ]
                
                settings = {}
                for pragma in pragmas:
                    try:
                        result = conn.execute(text(f"PRAGMA {pragma}"))
                        value = result.scalar()
                        settings[pragma] = value
                    except:
                        pass
                
                info['settings'] = settings
                
                return info
        except Exception as e:
            logger.error(f"获取SQLite数据库信息失败: {e}")
            return {'error': str(e)}
    
    def get_table_size(self, table_name: str) -> int:
        """
        获取SQLite表大小
        """
        try:
            # SQLite没有直接获取表大小的函数
            # 使用PRAGMA table_info和页大小估算
            sql = """
                SELECT 
                    (SELECT COUNT(*) FROM pragma_page_count()) * 
                    (SELECT page_size FROM pragma_page_size()) *
                    (SELECT (COUNT(*) * 1.0) / (SELECT COUNT(*) FROM pragma_page_count()) 
                     FROM "{table_name}")
            """.format(table_name=table_name)
            
            result = self.execute_raw_sql(sql)
            if result and len(result) > 0:
                return int(result[0][0] or 0)
            return 0
        except Exception as e:
            logger.error(f"获取SQLite表大小失败: {e}")
            return 0
    
    def get_index_info(self, table_name: str) -> List[Dict[str, Any]]:
        """
        获取SQLite表索引信息
        """
        try:
            # 获取索引信息
            sql = """
                SELECT 
                    name as index_name,
                    sql as index_sql,
                    (CASE WHEN [unique] = 1 THEN 1 ELSE 0 END) as is_unique,
                    (CASE WHEN partial = 1 THEN 1 ELSE 0 END) as is_partial
                FROM sqlite_master
                WHERE type = 'index'
                AND tbl_name = :table_name
            """
            result = self.execute_raw_sql(sql, {'table_name': table_name})
            
            indexes = []
            for row in result:
                index_info = {
                    'name': row[0],
                    'sql': row[1],
                    'is_unique': bool(row[2]),
                    'is_partial': bool(row[3]),
                }
                indexes.append(index_info)
            
            return indexes
        except Exception as e:
            logger.error(f"获取SQLite索引信息失败: {e}")
            return []
    
    def create_table(self, table_name: str, columns: Dict[str, str], 
                     constraints: List[str] = None, if_not_exists: bool = True) -> bool:
        """
        创建SQLite表
        """
        # 生成列定义
        columns_sql = []
        for name, data_type in columns.items():
            columns_sql.append(f'"{name}" {data_type}')
        
        if constraints:
            columns_sql.extend(constraints)
        
        columns_str = ", ".join(columns_sql)
        
        if_exists_clause = "IF NOT EXISTS " if if_not_exists else ""
        
        sql = f'CREATE TABLE {if_exists_clause}"{table_name}" ({columns_str})'
        
        try:
            self.execute_raw_sql(sql)
            
            # SQLite自动为INTEGER PRIMARY KEY创建索引
            # 不需要额外操作
            
            return True
        except SQLAlchemyError as e:
            logger.error(f"创建SQLite表失败: {e}")
            return False
    
    def add_index(self, table_name: str, column_name: str, 
                  index_name: Optional[str] = None, unique: bool = False) -> bool:
        """
        添加SQLite索引
        """
        if not index_name:
            index_name = f"idx_{table_name}_{column_name}"
        
        unique_str = "UNIQUE " if unique else ""
        sql = f'CREATE {unique_str}INDEX "{index_name}" ON "{table_name}" ("{column_name}")'
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"创建SQLite索引失败: {e}")
            return False
    
    def enable_fts(self, table_name: str, columns: List[str], 
                  fts_version: str = 'fts5') -> bool:
        """
        启用全文搜索（FTS）
        
        Args:
            table_name: 表名
            columns: 要索引的列
            fts_version: FTS版本（fts4或fts5）
        """
        if fts_version not in ['fts4', 'fts5']:
            logger.error(f"不支持的FTS版本: {fts_version}")
            return False
        
        columns_str = ", ".join(f'"{col}"' for col in columns)
        
        sql = f"""
            CREATE VIRTUAL TABLE "{table_name}_fts" 
            USING {fts_version}({columns_str})
        """
        
        try:
            self.execute_raw_sql(sql)
            
            # 创建触发器以保持FTS表同步
            trigger_sql = f"""
                CREATE TRIGGER "{table_name}_ai" AFTER INSERT ON "{table_name}"
                BEGIN
                    INSERT INTO "{table_name}_fts" (rowid, {columns_str})
                    VALUES (new.rowid, {', '.join(f'new."{col}"' for col in columns)});
                END;
            """
            self.execute_raw_sql(trigger_sql)
            
            return True
        except SQLAlchemyError as e:
            logger.error(f"启用SQLite FTS失败: {e}")
            return False
    
    def vacuum(self, table_name: Optional[str] = None) -> bool:
        """
        SQLite VACUUM
        """
        if table_name:
            # SQLite不支持针对单个表的VACUUM
            logger.warning("SQLite不支持针对单个表的VACUUM，将执行整个数据库VACUUM")
        
        sql = "VACUUM"
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"执行SQLite VACUUM失败: {e}")
            return False
    
    def analyze(self, table_name: Optional[str] = None) -> bool:
        """
        SQLite ANALYZE
        """
        if table_name:
            sql = f'ANALYZE "{table_name}"'
        else:
            sql = "ANALYZE"
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"执行SQLite ANALYZE失败: {e}")
            return False
    
    def backup(self, backup_path: str) -> bool:
        """
        备份SQLite数据库
        
        Args:
            backup_path: 备份文件路径
            
        Returns:
            True 如果备份成功
        """
        if self.connection_url == 'sqlite:///:memory:':
            logger.error("无法备份内存数据库")
            return False
        
        try:
            engine = self.get_engine()
            
            # 使用SQLite备份API
            source_db = self._extract_db_path()
            if not source_db:
                logger.error("无法获取源数据库路径")
                return False
            
            # 确保备份目录存在
            backup_dir = os.path.dirname(backup_path)
            if backup_dir and not os.path.exists(backup_dir):
                os.makedirs(backup_dir, exist_ok=True)
            
            # 执行备份
            with engine.connect() as conn:
                # 开始事务以确保一致性
                conn.execute(text("BEGIN IMMEDIATE"))
                
                # 备份数据库文件
                import shutil
                shutil.copy2(source_db, backup_path)
                
                conn.execute(text("COMMIT"))
            
            logger.info(f"SQLite数据库备份完成: {backup_path}")
            return True
        except Exception as e:
            logger.error(f"SQLite数据库备份失败: {e}")
            return False
    
    def _get_explain_sql(self, sql: str) -> str:
        """
        生成SQLite EXPLAIN语句
        """
        return f"EXPLAIN QUERY PLAN {sql}"
    
    def _parse_query_plan(self, result: Any) -> Dict[str, Any]:
        """
        解析SQLite执行计划
        """
        if not result:
            return {'plan': [], 'summary': {}}
        
        plan_lines = []
        for row in result:
            plan_lines.append(f"{row[0]}|{row[1]}|{row[2]}|{row[3]}")
        
        plan_text = "\n".join(plan_lines)
        
        # 解析计划摘要
        summary = {}
        
        # 从最后一行提取摘要信息
        if plan_lines:
            last_line = plan_lines[-1]
            parts = last_line.split('|')
            if len(parts) >= 4:
                summary['detail'] = parts[3]
        
        return {
            'plan_text': plan_text,
            'summary': summary,
            'raw_plan': plan_lines,
        }
    
    def integrity_check(self) -> Dict[str, Any]:
        """
        执行完整性检查
        
        Returns:
            检查结果
        """
        try:
            result = self.execute_raw_sql("PRAGMA integrity_check")
            
            check_result = []
            for row in result:
                check_result.append(row[0])
            
            return {
                'integrity_check': check_result,
                'is_ok': len(check_result) == 1 and check_result[0] == 'ok',
            }
        except Exception as e:
            logger.error(f"SQLite完整性检查失败: {e}")
            return {'error': str(e)}
