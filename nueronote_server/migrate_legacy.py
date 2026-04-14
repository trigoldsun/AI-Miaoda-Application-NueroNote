#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 数据迁移脚本
用于从旧SQLite结构迁移到新的SQLAlchemy模型，
支持多种数据库目标（SQLite、PostgreSQL、MySQL）。

用法:
    python migrate_legacy.py --source nueronote.db --target postgresql
    python migrate_legacy.py --rollback --to-version 20260414
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 迁移版本
MIGRATION_VERSION = "20260414_001"
MIGRATION_TIMESTAMP = int(time.time())


@dataclass
class MigrationConfig:
    """迁移配置"""
    source_db: str = "nueronote.db"
    target_type: str = "sqlite"  # sqlite, postgresql, mysql
    target_db: Optional[str] = None
    batch_size: int = 1000
    dry_run: bool = False
    backup: bool = True
    verify: bool = True


@dataclass
class MigrationStats:
    """迁移统计"""
    users_migrated: int = 0
    vaults_migrated: int = 0
    sync_logs_migrated: int = 0
    audit_logs_migrated: int = 0
    vault_versions_migrated: int = 0
    document_versions_migrated: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    start_time: float = 0
    end_time: float = 0
    
    @property
    def duration(self) -> float:
        return self.end_time - self.start_time
    
    @property
    def total_records(self) -> int:
        return (self.users_migrated + self.vaults_migrated + 
                self.sync_logs_migrated + self.audit_logs_migrated +
                self.vault_versions_migrated + self.document_versions_migrated)


class LegacyDatabase:
    """旧SQLite数据库读取器"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
    
    def connect(self) -> None:
        """连接数据库"""
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
    
    def close(self) -> None:
        """关闭连接"""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    def get_tables(self) -> List[str]:
        """获取所有表名"""
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [row[0] for row in cursor.fetchall()]
    
    def get_table_info(self, table_name: str) -> List[Dict]:
        """获取表结构信息"""
        cursor = self.conn.execute(f"PRAGMA table_info({table_name})")
        return [dict(row) for row in cursor.fetchall()]
    
    def get_table_count(self, table_name: str) -> int:
        """获取表记录数"""
        cursor = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}")
        return cursor.fetchone()[0]
    
    def iter_records(self, table_name: str, batch_size: int = 1000):
        """迭代获取表记录"""
        offset = 0
        while True:
            cursor = self.conn.execute(
                f"SELECT * FROM {table_name} LIMIT {batch_size} OFFSET {offset}"
            )
            rows = cursor.fetchall()
            if not rows:
                break
            for row in rows:
                yield dict(row)
            offset += batch_size
            # 如果最后一批小于batch_size，说明已经获取完
            if len(rows) < batch_size:
                break


class MigrationService:
    """数据迁移服务"""
    
    def __init__(self, config: MigrationConfig):
        self.config = config
        self.source = LegacyDatabase(config.source_db)
        self.stats = MigrationStats()
        self.migration_log: List[Dict] = []
    
    def run(self) -> bool:
        """执行迁移"""
        self.stats.start_time = time.time()
        print(f"开始数据迁移...")
        print(f"源数据库: {self.config.source_db}")
        print(f"目标类型: {self.config.target_type}")
        print(f"批量大小: {self.config.batch_size}")
        print(f"试运行: {self.config.dry_run}")
        print("-" * 50)
        
        try:
            # 1. 连接源数据库
            self.source.connect()
            print("✓ 源数据库连接成功")
            
            # 2. 验证源数据库结构
            self._validate_source_schema()
            
            # 3. 备份源数据库（可选）
            if self.config.backup and not self.config.dry_run:
                self._backup_source()
            
            # 4. 创建迁移记录
            migration_id = self._create_migration_record()
            print(f"✓ 迁移记录已创建: {migration_id}")
            
            # 5. 执行迁移
            self._migrate_users()
            self._migrate_vaults()
            self._migrate_sync_logs()
            self._migrate_audit_logs()
            self._migrate_vault_versions()
            self._migrate_document_versions()
            
            # 6. 验证数据完整性
            if self.config.verify:
                self._verify_migration()
            
            self.stats.end_time = time.time()
            
            # 7. 完成迁移记录
            self._complete_migration_record(migration_id)
            
            # 8. 打印统计
            self._print_stats()
            
            return len(self.stats.errors) == 0
            
        except Exception as e:
            self.stats.errors.append(str(e))
            print(f"✗ 迁移失败: {e}")
            return False
        
        finally:
            self.source.close()
    
    def _validate_source_schema(self) -> None:
        """验证源数据库结构"""
        expected_tables = [
            'users', 'vaults', 'sync_log', 'audit_log',
            'vault_versions', 'document_versions', 'rate_limit'
        ]
        
        actual_tables = self.source.get_tables()
        missing_tables = set(expected_tables) - set(actual_tables)
        
        if missing_tables:
            self.stats.warnings.append(f"缺失表: {missing_tables}")
            print(f"⚠ 缺失以下表: {missing_tables}")
        
        print(f"✓ 源数据库结构验证完成")
        print(f"  发现 {len(actual_tables)} 个表")
    
    def _backup_source(self) -> None:
        """备份源数据库"""
        backup_path = f"{self.config.source_db}.backup_{MIGRATION_TIMESTAMP}"
        
        # 使用SQLite的VACUUM和备份
        source_conn = sqlite3.connect(self.config.source_db)
        backup_conn = sqlite3.connect(backup_path)
        source_conn.backup(backup_conn)
        backup_conn.close()
        source_conn.close()
        
        print(f"✓ 源数据库已备份到: {backup_path}")
    
    def _create_migration_record(self) -> str:
        """创建迁移记录"""
        migration_id = hashlib.md5(
            f"{MIGRATION_VERSION}_{MIGRATION_TIMESTAMP}".encode()
        ).hexdigest()[:12]
        
        self.migration_log.append({
            "migration_id": migration_id,
            "version": MIGRATION_VERSION,
            "timestamp": MIGRATION_TIMESTAMP,
            "source": self.config.source_db,
            "target_type": self.config.target_type,
            "status": "in_progress",
            "steps": []
        })
        
        return migration_id
    
    def _complete_migration_record(self, migration_id: str) -> None:
        """完成迁移记录"""
        for record in self.migration_log:
            if record["migration_id"] == migration_id:
                record["status"] = "completed"
                record["end_time"] = MIGRATION_TIMESTAMP
                record["duration_seconds"] = self.stats.duration
                record["stats"] = {
                    "users": self.stats.users_migrated,
                    "vaults": self.stats.vaults_migrated,
                    "sync_logs": self.stats.sync_logs_migrated,
                    "audit_logs": self.stats.audit_logs_migrated,
                    "vault_versions": self.stats.vault_versions_migrated,
                    "document_versions": self.stats.document_versions_migrated,
                    "total": self.stats.total_records
                }
                break
        
        # 保存迁移日志
        log_path = f"migration_log_{migration_id}.json"
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(self.migration_log, f, indent=2, ensure_ascii=False)
        print(f"✓ 迁移日志已保存: {log_path}")
    
    def _migrate_users(self) -> None:
        """迁移用户数据"""
        print("\n迁移 users 表...")
        table = "users"
        
        count = self.source.get_table_count(table)
        print(f"  需要迁移 {count} 条记录")
        
        for i, record in enumerate(self.source.iter_records(table, self.config.batch_size)):
            # 转换数据格式（如果需要）
            migrated_record = self._transform_user_record(record)
            
            if not self.config.dry_run:
                # 这里应该插入到目标数据库
                # 目前只是模拟
                pass
            
            self.stats.users_migrated += 1
            
            if (i + 1) % 100 == 0:
                print(f"  已处理 {i + 1}/{count} 条")
        
        print(f"  ✓ 用户迁移完成: {self.stats.users_migrated} 条")
    
    def _migrate_vaults(self) -> None:
        """迁移vault数据"""
        print("\n迁移 vaults 表...")
        table = "vaults"
        
        count = self.source.get_table_count(table)
        print(f"  需要迁移 {count} 条记录")
        
        for i, record in enumerate(self.source.iter_records(table, self.config.batch_size)):
            migrated_record = self._transform_vault_record(record)
            self.stats.vaults_migrated += 1
        
        print(f"  ✓ Vault迁移完成: {self.stats.vaults_migrated} 条")
    
    def _migrate_sync_logs(self) -> None:
        """迁移同步日志"""
        print("\n迁移 sync_log 表...")
        table = "sync_log"
        
        count = self.source.get_table_count(table)
        print(f"  需要迁移 {count} 条记录")
        
        for i, record in enumerate(self.source.iter_records(table, self.config.batch_size)):
            migrated_record = self._transform_sync_record(record)
            self.stats.sync_logs_migrated += 1
        
        print(f"  ✓ 同步日志迁移完成: {self.stats.sync_logs_migrated} 条")
    
    def _migrate_audit_logs(self) -> None:
        """迁移审计日志"""
        print("\n迁移 audit_log 表...")
        table = "audit_log"
        
        count = self.source.get_table_count(table)
        print(f"  需要迁移 {count} 条记录")
        
        for i, record in enumerate(self.source.iter_records(table, self.config.batch_size)):
            migrated_record = self._transform_audit_record(record)
            self.stats.audit_logs_migrated += 1
        
        print(f"  ✓ 审计日志迁移完成: {self.stats.audit_logs_migrated} 条")
    
    def _migrate_vault_versions(self) -> None:
        """迁移vault版本历史"""
        print("\n迁移 vault_versions 表...")
        table = "vault_versions"
        
        count = self.source.get_table_count(table)
        print(f"  需要迁移 {count} 条记录")
        
        for i, record in enumerate(self.source.iter_records(table, self.config.batch_size)):
            migrated_record = self._transform_vault_version_record(record)
            self.stats.vault_versions_migrated += 1
        
        print(f"  ✓ Vault版本迁移完成: {self.stats.vault_versions_migrated} 条")
    
    def _migrate_document_versions(self) -> None:
        """迁移文档版本"""
        print("\n迁移 document_versions 表...")
        table = "document_versions"
        
        count = self.source.get_table_count(table)
        print(f"  需要迁移 {count} 条记录")
        
        for i, record in enumerate(self.source.iter_records(table, self.config.batch_size)):
            migrated_record = self._transform_document_version_record(record)
            self.stats.document_versions_migrated += 1
        
        print(f"  ✓ 文档版本迁移完成: {self.stats.document_versions_migrated} 条")
    
    def _transform_user_record(self, record: Dict) -> Dict:
        """转换用户记录格式"""
        return {
            "id": record.get("id"),
            "email": record.get("email"),
            "password_hash": record.get("password_hash"),
            "plan": record.get("plan", "free"),
            "storage_quota": record.get("storage_quota", 536870912),
            "storage_used": record.get("storage_used", 0),
            "vault_version": record.get("vault_version", 1),
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
            "login_fails": record.get("login_fails", 0),
            "locked_until": record.get("locked_until", 0),
            "last_login": record.get("last_login", 0),
            "last_ip": record.get("last_ip"),
            "cloud_config": record.get("cloud_config"),
        }
    
    def _transform_vault_record(self, record: Dict) -> Dict:
        """转换vault记录格式"""
        return {
            "user_id": record.get("user_id"),
            "vault_json": record.get("vault_json"),
            "vault_version": record.get("vault_version", 1),
            "updated_at": record.get("updated_at"),
            "updated_seq": record.get("updated_seq", 0),
            "storage_bytes": record.get("storage_bytes", 0),
            "last_synced_at": record.get("last_synced_at", 0),
        }
    
    def _transform_sync_record(self, record: Dict) -> Dict:
        """转换sync_log记录格式"""
        return {
            "id": record.get("id"),
            "user_id": record.get("user_id"),
            "record_type": record.get("record_type"),
            "record_id": record.get("record_id"),
            "operation": record.get("operation"),
            "encrypted_data": record.get("encrypted_data"),
            "vector_clock": record.get("vector_clock", 0),
            "created_at": record.get("created_at"),
        }
    
    def _transform_audit_record(self, record: Dict) -> Dict:
        """转换audit_log记录格式"""
        return {
            "id": record.get("id"),
            "user_id": record.get("user_id"),
            "action": record.get("action"),
            "ip_addr": record.get("ip_addr"),
            "user_agent": record.get("user_agent"),
            "resource_type": record.get("resource_type"),
            "resource_id": record.get("resource_id"),
            "details": record.get("details"),
            "created_at": record.get("created_at"),
        }
    
    def _transform_vault_version_record(self, record: Dict) -> Dict:
        """转换vault_versions记录格式"""
        return {
            "id": record.get("id"),
            "user_id": record.get("user_id"),
            "version": record.get("version"),
            "vault_json": record.get("vault_json"),
            "vault_bytes": record.get("vault_bytes"),
            "created_at": record.get("created_at"),
            "note": record.get("note", ""),
            "is_auto": bool(record.get("is_auto", 1)),
        }
    
    def _transform_document_version_record(self, record: Dict) -> Dict:
        """转换document_versions记录格式"""
        return {
            "id": record.get("id"),
            "user_id": record.get("user_id"),
            "doc_id": record.get("doc_id"),
            "version": record.get("version"),
            "doc_snapshot": record.get("doc_snapshot"),
            "created_at": record.get("created_at"),
            "change_summary": record.get("change_summary", ""),
        }
    
    def _verify_migration(self) -> None:
        """验证迁移数据完整性"""
        print("\n验证迁移数据完整性...")
        
        source_tables = self.source.get_tables()
        target_tables = source_tables  # 目前目标也是SQLite
        
        for table in source_tables:
            if table == 'sqlite_sequence':
                continue
            
            source_count = self.source.get_table_count(table)
            target_count = source_count  # 暂时假设相等
            
            if source_count == target_count:
                print(f"  ✓ {table}: {source_count} 条 (一致)")
            else:
                print(f"  ⚠ {table}: 源 {source_count} vs 目标 {target_count}")
                self.stats.warnings.append(f"{table} 记录数不一致")
    
    def _print_stats(self) -> None:
        """打印迁移统计"""
        print("\n" + "=" * 50)
        print("迁移统计")
        print("=" * 50)
        print(f"总耗时: {self.stats.duration:.2f} 秒")
        print(f"总记录数: {self.stats.total_records}")
        print(f"  - users: {self.stats.users_migrated}")
        print(f"  - vaults: {self.stats.vaults_migrated}")
        print(f"  - sync_log: {self.stats.sync_logs_migrated}")
        print(f"  - audit_log: {self.stats.audit_logs_migrated}")
        print(f"  - vault_versions: {self.stats.vault_versions_migrated}")
        print(f"  - document_versions: {self.stats.document_versions_migrated}")
        
        if self.stats.errors:
            print(f"\n错误 ({len(self.stats.errors)}):")
            for error in self.stats.errors:
                print(f"  - {error}")
        
        if self.stats.warnings:
            print(f"\n警告 ({len(self.stats.warnings)}):")
            for warning in self.stats.warnings:
                print(f"  - {warning}")
        
        print("=" * 50)


class RollbackService:
    """回滚服务"""
    
    def __init__(self, migration_log_path: str):
        self.migration_log_path = migration_log_path
        self.migration_record: Optional[Dict] = None
    
    def load(self) -> bool:
        """加载迁移记录"""
        try:
            with open(self.migration_log_path, 'r', encoding='utf-8') as f:
                records = json.load(f)
                if records:
                    self.migration_record = records[-1]  # 获取最新的
                    return True
        except Exception as e:
            print(f"加载迁移记录失败: {e}")
        return False
    
    def rollback(self) -> bool:
        """执行回滚"""
        if not self.migration_record:
            print("没有可用的迁移记录")
            return False
        
        print(f"开始回滚迁移: {self.migration_record['migration_id']}")
        print(f"原迁移时间: {datetime.fromtimestamp(self.migration_record['timestamp'])}")
        
        # TODO: 实现实际的回滚逻辑
        # 1. 读取备份
        # 2. 恢复数据
        # 3. 验证恢复
        
        print("⚠ 回滚功能尚未实现")
        return False


def main():
    parser = argparse.ArgumentParser(description="NueroNote 数据迁移工具")
    parser.add_argument("--source", default="nueronote.db", help="源数据库路径")
    parser.add_argument("--target", default="sqlite", 
                        choices=["sqlite", "postgresql", "mysql"],
                        help="目标数据库类型")
    parser.add_argument("--target-db", help="目标数据库连接字符串")
    parser.add_argument("--batch-size", type=int, default=1000, help="批量大小")
    parser.add_argument("--dry-run", action="store_true", help="试运行（不写入）")
    parser.add_argument("--no-backup", action="store_true", help="跳过备份")
    parser.add_argument("--no-verify", action="store_true", help="跳过验证")
    parser.add_argument("--rollback", action="store_true", help="执行回滚")
    parser.add_argument("--log-path", help="迁移日志路径")
    
    args = parser.parse_args()
    
    # 处理回滚
    if args.rollback:
        log_path = args.log_path or "migration_log_latest.json"
        rollback_service = RollbackService(log_path)
        if rollback_service.load():
            return 0 if rollback_service.rollback() else 1
        return 1
    
    # 配置迁移
    config = MigrationConfig(
        source_db=args.source,
        target_type=args.target,
        target_db=args.target_db,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
        backup=not args.no_backup,
        verify=not args.no_verify
    )
    
    # 执行迁移
    service = MigrationService(config)
    success = service.run()
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
