#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PostgreSQL 数据库适配器
支持PostgreSQL 9.6+，包括高级功能如JSONB、全文搜索、分区表等
"""

import json
import logging
import re
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime

from sqlalchemy import create_engine, Engine, text
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import SQLAlchemyError, OperationalError

from nueronote_server.db.adapters import DatabaseAdapter


logger = logging.getLogger(__name__)


class PostgreSQLAdapter(DatabaseAdapter):
    """
    PostgreSQL 数据库适配器
    
    特性：
    - 连接池和连接复用
    - SSL/TLS 支持
    - 读写分离
    - 故障转移
    - 高级监控和调优
    """
    
    @property
    def dialect(self) -> str:
        return "postgresql"
    
    @property
    def supports_transactions(self) -> bool:
        return True
    
    @property
    def supports_json(self) -> bool:
        return True  # PostgreSQL支持JSON和JSONB
    
    @property
    def supports_full_text_search(self) -> bool:
        return True
    
    @property
    def default_isolation_level(self) -> str:
        return "READ COMMITTED"
    
    def create_engine(self) -> Engine:
        """
        创建PostgreSQL引擎
        """
        pool_config = self.get_connection_pool_config()
        connect_args = self.get_connect_args()
        
        # 创建引擎
        engine = create_engine(
            self.connection_url,
            echo=self.echo,
            **pool_config,
            connect_args=connect_args,
        )
        
        return engine
    
    def get_connection_pool_config(self) -> Dict[str, Any]:
        """
        获取PostgreSQL连接池配置
        """
        return {
            'poolclass': QueuePool,
            'pool_size': self.pool_size,
            'max_overflow': self.max_overflow,
            'pool_timeout': self.pool_timeout,
            'pool_recycle': self.pool_recycle,
            'pool_pre_ping': self.pool_pre_ping,
        }
    
    def get_connect_args(self) -> Dict[str, Any]:
        """
        获取PostgreSQL连接参数
        """
        connect_args = {
            'connect_timeout': 10,
            'application_name': 'nueronote',
            'keepalives': 1,
            'keepalives_idle': 30,
            'keepalives_interval': 10,
            'keepalives_count': 5,
        }
        
        # 添加SSL配置
        ssl_mode = self.config.get('ssl_mode', 'prefer')
        if ssl_mode != 'disable':
            connect_args['sslmode'] = ssl_mode
        
        # 添加连接超时和重试
        connect_args.update({
            'connect_timeout': self.config.get('connect_timeout', 10),
            'target_session_attrs': self.config.get('target_session_attrs', 'read-write'),
        })
        
        return connect_args
    
    def test_connection(self, timeout: int = 5) -> bool:
        """
        测试PostgreSQL连接
        """
        try:
            engine = self.get_engine()
            with engine.connect() as conn:
                # 设置查询超时
                conn.execute(text(f"SET statement_timeout = {timeout * 1000}"))
                
                # 执行简单查询
                result = conn.execute(text("SELECT version(), current_database(), current_user"))
                row = result.fetchone()
                
                if row:
                    logger.info(f"PostgreSQL连接测试成功: {row[1]} as {row[2]}")
                    return True
                
                return False
        except Exception as e:
            logger.error(f"PostgreSQL连接测试失败: {e}")
            return False
    
    def get_database_info(self) -> Dict[str, Any]:
        """
        获取PostgreSQL数据库信息
        """
        try:
            engine = self.get_engine()
            with engine.connect() as conn:
                info = {}
                
                # 数据库版本
                result = conn.execute(text("SELECT version()"))
                info['version'] = result.scalar()
                
                # 数据库名称和大小
                result = conn.execute(text("""
                    SELECT 
                        current_database() as name,
                        pg_database_size(current_database()) as size_bytes,
                        pg_size_pretty(pg_database_size(current_database())) as size_pretty
                """))
                db_row = result.fetchone()
                if db_row:
                    info['database'] = dict(db_row._mapping)
                
                # 连接数
                result = conn.execute(text("""
                    SELECT 
                        COUNT(*) as total_connections,
                        COUNT(*) FILTER (WHERE state = 'active') as active_connections,
                        COUNT(*) FILTER (WHERE state = 'idle') as idle_connections,
                        COUNT(*) FILTER (WHERE state = 'idle in transaction') as idle_in_transaction
                    FROM pg_stat_activity 
                    WHERE datname = current_database()
                """))
                conn_row = result.fetchone()
                if conn_row:
                    info['connections'] = dict(conn_row._mapping)
                
                # 表空间信息
                result = conn.execute(text("""
                    SELECT 
                        spcname as name,
                        pg_tablespace_size(oid) as size_bytes,
                        pg_size_pretty(pg_tablespace_size(oid)) as size_pretty
                    FROM pg_tablespace
                """))
                tablespaces = [dict(row._mapping) for row in result.fetchall()]
                if tablespaces:
                    info['tablespaces'] = tablespaces
                
                # 配置参数
                result = conn.execute(text("""
                    SELECT name, setting, unit, context 
                    FROM pg_settings 
                    WHERE name IN (
                        'max_connections', 'shared_buffers', 'work_mem', 
                        'maintenance_work_mem', 'effective_cache_size',
                        'wal_buffers', 'checkpoint_timeout', 'checkpoint_completion_target'
                    )
                """))
                settings = {row.name: {'value': row.setting, 'unit': row.unit} 
                           for row in result.fetchall()}
                if settings:
                    info['settings'] = settings
                
                return info
        except Exception as e:
            logger.error(f"获取PostgreSQL数据库信息失败: {e}")
            return {'error': str(e)}
    
    def get_table_size(self, table_name: str) -> int:
        """
        获取PostgreSQL表大小
        """
        try:
            sql = """
                SELECT pg_total_relation_size(%(table_name)s) as total_size
            """
            result = self.execute_raw_sql(sql, {'table_name': table_name})
            if result and len(result) > 0:
                return result[0][0] or 0
            return 0
        except Exception as e:
            logger.error(f"获取PostgreSQL表大小失败: {e}")
            return 0
    
    def get_index_info(self, table_name: str) -> List[Dict[str, Any]]:
        """
        获取PostgreSQL表索引信息
        """
        try:
            sql = """
                SELECT
                    i.relname as index_name,
                    am.amname as index_type,
                    ix.indisunique as is_unique,
                    ix.indisprimary as is_primary,
                    pg_size_pretty(pg_relation_size(i.oid)) as index_size,
                    ix.indkey as column_positions,
                    pg_get_indexdef(ix.indexrelid) as index_definition
                FROM pg_index ix
                JOIN pg_class t ON t.oid = ix.indrelid
                JOIN pg_class i ON i.oid = ix.indexrelid
                JOIN pg_am am ON i.relam = am.oid
                WHERE t.relname = %(table_name)s
                ORDER BY i.relname
            """
            result = self.execute_raw_sql(sql, {'table_name': table_name})
            
            indexes = []
            for row in result:
                index_info = {
                    'name': row[0],
                    'type': row[1],
                    'is_unique': row[2],
                    'is_primary': row[3],
                    'size': row[4],
                    'definition': row[6],
                }
                indexes.append(index_info)
            
            return indexes
        except Exception as e:
            logger.error(f"获取PostgreSQL索引信息失败: {e}")
            return []
    
    def create_table(self, table_name: str, columns: Dict[str, str], 
                     constraints: List[str] = None, if_not_exists: bool = True) -> bool:
        """
        创建PostgreSQL表（支持高级特性）
        """
        # 生成列定义
        columns_sql = []
        for name, data_type in columns.items():
            # 处理PostgreSQL特有的数据类型
            if data_type.upper() == 'JSON':
                data_type = 'JSONB'  # 默认使用JSONB以获得更好的性能
            columns_sql.append(f"{name} {data_type}")
        
        if constraints:
            columns_sql.extend(constraints)
        
        columns_str = ", ".join(columns_sql)
        
        # 构建CREATE TABLE语句
        if_exists_clause = "IF NOT EXISTS " if if_not_exists else ""
        
        # 添加表空间和分区选项
        tablespace = self.config.get('tablespace')
        tablespace_clause = f" TABLESPACE {tablespace}" if tablespace else ""
        
        sql = f"CREATE TABLE {if_exists_clause}{table_name} ({columns_str}){tablespace_clause}"
        
        try:
            self.execute_raw_sql(sql)
            
            # 自动为JSONB列创建GIN索引
            for name, data_type in columns.items():
                if data_type.upper() in ['JSON', 'JSONB']:
                    self.add_jsonb_index(table_name, name)
            
            return True
        except SQLAlchemyError as e:
            logger.error(f"创建PostgreSQL表失败: {e}")
            return False
    
    def add_jsonb_index(self, table_name: str, column_name: str, 
                       index_name: Optional[str] = None) -> bool:
        """
        为JSONB列创建GIN索引
        """
        if not index_name:
            index_name = f"idx_{table_name}_{column_name}_gin"
        
        sql = f"CREATE INDEX {index_name} ON {table_name} USING GIN ({column_name})"
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"创建JSONB GIN索引失败: {e}")
            return False
    
    def vacuum(self, table_name: Optional[str] = None) -> bool:
        """
        PostgreSQL VACUUM（支持ANALYZE和FULL选项）
        """
        options = self.config.get('vacuum_options', '')
        
        if table_name:
            sql = f"VACUUM {options} {table_name}"
        else:
            sql = f"VACUUM {options}"
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"执行PostgreSQL VACUUM失败: {e}")
            return False
    
    def analyze(self, table_name: Optional[str] = None) -> bool:
        """
        PostgreSQL ANALYZE
        """
        options = self.config.get('analyze_options', '')
        
        if table_name:
            sql = f"ANALYZE {options} {table_name}"
        else:
            sql = f"ANALYZE {options}"
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"执行PostgreSQL ANALYZE失败: {e}")
            return False
    
    def create_partition(self, table_name: str, partition_name: str, 
                        condition: str) -> bool:
        """
        创建表分区（PostgreSQL 10+）
        """
        sql = f"""
            CREATE TABLE {partition_name} 
            PARTITION OF {table_name}
            FOR VALUES {condition}
        """
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"创建PostgreSQL分区失败: {e}")
            return False
    
    def _get_explain_sql(self, sql: str) -> str:
        """
        生成PostgreSQL EXPLAIN语句
        """
        # 支持多种EXPLAIN选项
        options = self.config.get('explain_options', 'ANALYZE, BUFFERS, TIMING')
        return f"EXPLAIN ({options}) {sql}"
    
    def _parse_query_plan(self, result: Any) -> Dict[str, Any]:
        """
        解析PostgreSQL执行计划
        """
        if not result:
            return {'plan': [], 'summary': {}}
        
        plan_lines = []
        for row in result:
            plan_lines.append(row[0])
        
        plan_text = "\n".join(plan_lines)
        
        # 解析计划摘要
        summary = {}
        
        # 提取关键指标
        cost_match = re.search(r'cost=(\d+\.\d+)\.\.(\d+\.\d+)', plan_text)
        if cost_match:
            summary['startup_cost'] = float(cost_match.group(1))
            summary['total_cost'] = float(cost_match.group(2))
        
        rows_match = re.search(r'rows=(\d+)', plan_text)
        if rows_match:
            summary['estimated_rows'] = int(rows_match.group(1))
        
        width_match = re.search(r'width=(\d+)', plan_text)
        if width_match:
            summary['estimated_width'] = int(width_match.group(1))
        
        # 查找实际执行信息（如果有ANALYZE）
        actual_rows_match = re.search(r'actual rows=(\d+)', plan_text)
        if actual_rows_match:
            summary['actual_rows'] = int(actual_rows_match.group(1))
        
        actual_time_match = re.search(r'actual time=(\d+\.\d+)\.\.(\d+\.\d+)', plan_text)
        if actual_time_match:
            summary['actual_start_time'] = float(actual_time_match.group(1))
            summary['actual_total_time'] = float(actual_time_match.group(2))
        
        return {
            'plan_text': plan_text,
            'summary': summary,
            'raw_plan': plan_lines,
        }
    
    def create_read_replica(self, replica_url: str) -> 'PostgreSQLAdapter':
        """
        创建只读副本适配器
        
        Args:
            replica_url: 副本数据库URL
            
        Returns:
            只读副本适配器
        """
        replica_config = self.config.copy()
        replica_config['target_session_attrs'] = 'read-only'
        
        return PostgreSQLAdapter(replica_url, **replica_config)
    
    def get_replication_info(self) -> Dict[str, Any]:
        """
        获取复制信息（如果有）
        """
        try:
            engine = self.get_engine()
            with engine.connect() as conn:
                # 检查是否为主库
                result = conn.execute(text("""
                    SELECT pg_is_in_recovery() as is_standby
                """))
                is_standby = result.scalar()
                
                info = {'is_standby': is_standby}
                
                if not is_standby:
                    # 主库复制信息
                    result = conn.execute(text("""
                        SELECT 
                            application_name,
                            client_addr,
                            state,
                            sync_state,
                            replay_lag
                        FROM pg_stat_replication
                    """))
                    
                    replicas = []
                    for row in result.fetchall():
                        replicas.append({
                            'application_name': row[0],
                            'client_addr': row[1],
                            'state': row[2],
                            'sync_state': row[3],
                            'replay_lag': row[4],
                        })
                    
                    info['replicas'] = replicas
                else:
                    # 备库复制信息
                    result = conn.execute(text("""
                        SELECT 
                            pg_last_xlog_receive_location() as receive_location,
                            pg_last_xlog_replay_location() as replay_location,
                            pg_last_xact_replay_timestamp() as last_replay_time
                    """))
                    
                    row = result.fetchone()
                    if row:
                        info.update({
                            'receive_location': row[0],
                            'replay_location': row[1],
                            'last_replay_time': row[2],
                        })
                
                return info
        except Exception as e:
            logger.error(f"获取PostgreSQL复制信息失败: {e}")
            return {'error': str(e)}
