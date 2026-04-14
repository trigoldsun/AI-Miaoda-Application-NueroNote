#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MySQL 数据库适配器
支持MySQL 5.7+ / MariaDB 10.2+，包括InnoDB、分区、复制等特性
"""

import json
import logging
import re
from typing import Optional, Dict, Any, List, Tuple

from sqlalchemy import create_engine, Engine, text
from sqlalchemy.pool import QueuePool
from sqlalchemy.exc import SQLAlchemyError, OperationalError

from nueronote_server.db.adapters import DatabaseAdapter


logger = logging.getLogger(__name__)


class MySQLAdapter(DatabaseAdapter):
    """
    MySQL/MariaDB 数据库适配器
    
    特性：
    - InnoDB引擎优化
    - 连接池和字符集支持
    - 读写分离和复制
    - 分区表支持
    - SSL/TLS连接
    """
    
    @property
    def dialect(self) -> str:
        return "mysql"
    
    @property
    def supports_transactions(self) -> bool:
        return True
    
    @property
    def supports_json(self) -> bool:
        # MySQL 5.7+ 支持JSON
        return True
    
    @property
    def supports_full_text_search(self) -> bool:
        return True
    
    @property
    def default_isolation_level(self) -> str:
        return "REPEATABLE READ"
    
    def create_engine(self) -> Engine:
        """
        创建MySQL引擎
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
        获取MySQL连接池配置
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
        获取MySQL连接参数
        """
        connect_args = {
            'connect_timeout': 10,
            'charset': 'utf8mb4',
            'collation': 'utf8mb4_unicode_ci',
        }
        
        # 添加SSL配置
        ssl_mode = self.config.get('ssl_mode', 'PREFERRED')
        if ssl_mode != 'DISABLED':
            connect_args['ssl'] = {'ssl_mode': ssl_mode}
        
        # MySQL特定参数
        connect_args.update({
            'init_command': 'SET SESSION wait_timeout=28800',
            'autocommit': False,
        })
        
        # 连接选项
        if self.config.get('use_unicode', True):
            connect_args['use_unicode'] = True
        
        return connect_args
    
    def test_connection(self, timeout: int = 5) -> bool:
        """
        测试MySQL连接
        """
        try:
            engine = self.get_engine()
            with engine.connect() as conn:
                # 设置会话超时
                conn.execute(text(f"SET SESSION max_execution_time = {timeout * 1000}"))
                
                # 执行简单查询
                result = conn.execute(text("SELECT VERSION(), DATABASE(), USER()"))
                row = result.fetchone()
                
                if row:
                    logger.info(f"MySQL连接测试成功: {row[1]} as {row[2]}")
                    return True
                
                return False
        except Exception as e:
            logger.error(f"MySQL连接测试失败: {e}")
            return False
    
    def get_database_info(self) -> Dict[str, Any]:
        """
        获取MySQL数据库信息
        """
        try:
            engine = self.get_engine()
            with engine.connect() as conn:
                info = {}
                
                # 数据库版本
                result = conn.execute(text("SELECT VERSION(), @@version_comment"))
                version_row = result.fetchone()
                if version_row:
                    info['version'] = version_row[0]
                    info['version_comment'] = version_row[1]
                
                # 数据库名称和大小
                result = conn.execute(text("SELECT DATABASE()"))
                db_name = result.scalar()
                info['database'] = db_name
                
                # 获取数据库大小
                result = conn.execute(text("""
                    SELECT 
                        table_schema as db_name,
                        SUM(data_length + index_length) as size_bytes
                    FROM information_schema.tables
                    WHERE table_schema = DATABASE()
                    GROUP BY table_schema
                """))
                size_row = result.fetchone()
                if size_row:
                    info['size_bytes'] = size_row[1]
                
                # 连接状态
                result = conn.execute(text("SHOW STATUS LIKE 'Threads_connected'"))
                conn_row = result.fetchone()
                if conn_row:
                    info['threads_connected'] = conn_row[1]
                
                # 引擎信息
                result = conn.execute(text("SHOW ENGINES"))
                engines = []
                for row in result.fetchall():
                    engines.append({
                        'engine': row[0],
                        'support': row[1],
                        'comment': row[3],
                    })
                info['engines'] = engines
                
                # 关键配置参数
                params = [
                    'max_connections', 'innodb_buffer_pool_size',
                    'innodb_log_file_size', 'innodb_flush_log_at_trx_commit',
                    'sync_binlog', 'character_set_server', 'collation_server'
                ]
                
                for param in params:
                    try:
                        result = conn.execute(text(f"SELECT @@{param}"))
                        value = result.scalar()
                        info[param] = value
                    except:
                        pass
                
                return info
        except Exception as e:
            logger.error(f"获取MySQL数据库信息失败: {e}")
            return {'error': str(e)}
    
    def get_table_size(self, table_name: str) -> int:
        """
        获取MySQL表大小
        """
        try:
            sql = """
                SELECT 
                    data_length + index_length as total_size
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                AND table_name = %(table_name)s
            """
            result = self.execute_raw_sql(sql, {'table_name': table_name})
            if result and len(result) > 0:
                return result[0][0] or 0
            return 0
        except Exception as e:
            logger.error(f"获取MySQL表大小失败: {e}")
            return 0
    
    def get_index_info(self, table_name: str) -> List[Dict[str, Any]]:
        """
        获取MySQL表索引信息
        """
        try:
            sql = """
                SELECT 
                    index_name,
                    non_unique,
                    column_name,
                    index_type,
                    comment
                FROM information_schema.statistics
                WHERE table_schema = DATABASE()
                AND table_name = %(table_name)s
                ORDER BY index_name, seq_in_index
            """
            result = self.execute_raw_sql(sql, {'table_name': table_name})
            
            # 按索引名分组
            indexes = {}
            for row in result:
                index_name = row[0]
                if index_name not in indexes:
                    indexes[index_name] = {
                        'name': index_name,
                        'is_unique': not bool(row[1]),
                        'type': row[3],
                        'comment': row[4],
                        'columns': [],
                    }
                indexes[index_name]['columns'].append(row[2])
            
            return list(indexes.values())
        except Exception as e:
            logger.error(f"获取MySQL索引信息失败: {e}")
            return []
    
    def create_table(self, table_name: str, columns: Dict[str, str], 
                     constraints: List[str] = None, if_not_exists: bool = True) -> bool:
        """
        创建MySQL表（支持InnoDB和字符集）
        """
        # 生成列定义
        columns_sql = []
        for name, data_type in columns.items():
            columns_sql.append(f"`{name}` {data_type}")
        
        if constraints:
            columns_sql.extend(constraints)
        
        columns_str = ", ".join(columns_sql)
        
        # 表选项
        engine = self.config.get('engine', 'InnoDB')
        charset = self.config.get('charset', 'utf8mb4')
        collate = self.config.get('collation', 'utf8mb4_unicode_ci')
        row_format = self.config.get('row_format', 'DYNAMIC')
        
        if_exists_clause = "IF NOT EXISTS " if if_not_exists else ""
        
        sql = f"""
            CREATE TABLE {if_exists_clause}`{table_name}` (
                {columns_str}
            )
            ENGINE={engine}
            DEFAULT CHARSET={charset}
            COLLATE={collate}
            ROW_FORMAT={row_format}
        """
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"创建MySQL表失败: {e}")
            return False
    
    def add_index(self, table_name: str, column_name: str, 
                  index_name: Optional[str] = None, unique: bool = False) -> bool:
        """
        添加MySQL索引
        """
        if not index_name:
            index_name = f"idx_{table_name}_{column_name}"
        
        unique_str = "UNIQUE " if unique else ""
        sql = f"CREATE {unique_str}INDEX `{index_name}` ON `{table_name}` (`{column_name}`)"
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"创建MySQL索引失败: {e}")
            return False
    
    def add_fulltext_index(self, table_name: str, column_name: str, 
                          index_name: Optional[str] = None) -> bool:
        """
        添加全文索引
        """
        if not index_name:
            index_name = f"ft_{table_name}_{column_name}"
        
        sql = f"CREATE FULLTEXT INDEX `{index_name}` ON `{table_name}` (`{column_name}`)"
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"创建MySQL全文索引失败: {e}")
            return False
    
    def optimize_table(self, table_name: str) -> bool:
        """
        优化MySQL表
        """
        sql = f"OPTIMIZE TABLE `{table_name}`"
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"优化MySQL表失败: {e}")
            return False
    
    def vacuum(self, table_name: Optional[str] = None) -> bool:
        """
        MySQL表维护（使用OPTIMIZE TABLE）
        """
        if table_name:
            return self.optimize_table(table_name)
        else:
            # 优化所有表
            try:
                sql = "SHOW TABLES"
                result = self.execute_raw_sql(sql)
                
                success = True
                for row in result:
                    table = row[0]
                    if not self.optimize_table(table):
                        success = False
                
                return success
            except Exception as e:
                logger.error(f"优化所有MySQL表失败: {e}")
                return False
    
    def analyze(self, table_name: Optional[str] = None) -> bool:
        """
        MySQL表分析
        """
        if table_name:
            sql = f"ANALYZE TABLE `{table_name}`"
        else:
            sql = "ANALYZE TABLE"
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"分析MySQL表失败: {e}")
            return False
    
    def create_partition(self, table_name: str, partition_name: str, 
                        condition: str) -> bool:
        """
        创建表分区（MySQL分区）
        """
        sql = f"""
            ALTER TABLE `{table_name}`
            ADD PARTITION (
                PARTITION `{partition_name}` VALUES {condition}
            )
        """
        
        try:
            self.execute_raw_sql(sql)
            return True
        except SQLAlchemyError as e:
            logger.error(f"创建MySQL分区失败: {e}")
            return False
    
    def _get_explain_sql(self, sql: str) -> str:
        """
        生成MySQL EXPLAIN语句
        """
        # MySQL支持多种EXPLAIN格式
        explain_format = self.config.get('explain_format', 'TRADITIONAL')
        return f"EXPLAIN FORMAT={explain_format} {sql}"
    
    def _parse_query_plan(self, result: Any) -> Dict[str, Any]:
        """
        解析MySQL执行计划
        """
        if not result:
            return {'plan': [], 'summary': {}}
        
        # MySQL EXPLAIN返回表格格式
        plan_rows = []
        for row in result:
            if hasattr(row, '_mapping'):
                plan_rows.append(dict(row._mapping))
            else:
                plan_rows.append(list(row))
        
        # 提取摘要信息
        summary = {}
        if plan_rows:
            first_row = plan_rows[0]
            
            # 尝试从第一行提取关键指标
            if isinstance(first_row, dict):
                summary.update({
                    'select_type': first_row.get('select_type'),
                    'table': first_row.get('table'),
                    'type': first_row.get('type'),
                    'possible_keys': first_row.get('possible_keys'),
                    'key': first_row.get('key'),
                    'key_len': first_row.get('key_len'),
                    'rows': first_row.get('rows'),
                    'filtered': first_row.get('filtered'),
                    'extra': first_row.get('Extra'),
                })
        
        return {
            'plan_rows': plan_rows,
            'summary': summary,
            'plan_count': len(plan_rows),
        }
    
    def create_read_replica(self, replica_url: str) -> 'MySQLAdapter':
        """
        创建只读副本适配器
        
        Args:
            replica_url: 副本数据库URL
            
        Returns:
            只读副本适配器
        """
        replica_config = self.config.copy()
        replica_config['read_only'] = True
        
        return MySQLAdapter(replica_url, **replica_config)
    
    def get_replication_info(self) -> Dict[str, Any]:
        """
        获取复制信息（如果有）
        """
        try:
            engine = self.get_engine()
            with engine.connect() as conn:
                info = {}
                
                # 检查是否为主库
                result = conn.execute(text("SHOW SLAVE STATUS"))
                slave_status = result.fetchone()
                
                if slave_status:
                    # 这是从库
                    info['is_slave'] = True
                    
                    # 解析从库状态
                    if hasattr(slave_status, '_mapping'):
                        slave_dict = dict(slave_status._mapping)
                        info.update({
                            'master_host': slave_dict.get('Master_Host'),
                            'master_port': slave_dict.get('Master_Port'),
                            'slave_io_running': slave_dict.get('Slave_IO_Running'),
                            'slave_sql_running': slave_dict.get('Slave_SQL_Running'),
                            'seconds_behind_master': slave_dict.get('Seconds_Behind_Master'),
                            'last_error': slave_dict.get('Last_Error'),
                        })
                else:
                    # 可能是主库
                    info['is_slave'] = False
                    
                    # 检查主库状态
                    result = conn.execute(text("SHOW MASTER STATUS"))
                    master_status = result.fetchone()
                    if master_status:
                        if hasattr(master_status, '_mapping'):
                            master_dict = dict(master_status._mapping)
                            info.update({
                                'is_master': True,
                                'file': master_dict.get('File'),
                                'position': master_dict.get('Position'),
                            })
                
                # 检查只读模式
                result = conn.execute(text("SELECT @@read_only"))
                read_only = result.scalar()
                info['read_only'] = bool(read_only)
                
                return info
        except Exception as e:
            logger.error(f"获取MySQL复制信息失败: {e}")
            return {'error': str(e)}
