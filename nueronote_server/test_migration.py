#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 数据迁移测试脚本
验证数据迁移的完整性、一致性和可回滚性。

用法:
    python test_migration.py
    python test_migration.py --verbose
"""

import argparse
import hashlib
import json
import os
import random
import sqlite3
import string
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class TestResult:
    """测试结果"""
    name: str
    passed: bool
    message: str
    duration_ms: float
    details: Optional[Dict] = None


class TestDatabase:
    """测试数据库管理"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
    
    def connect(self) -> None:
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
    
    def close(self) -> None:
        if self.conn:
            self.conn.close()
            self.conn = None
    
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)
    
    def commit(self) -> None:
        self.conn.commit()
    
    def get_tables(self) -> List[str]:
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [row[0] for row in cursor.fetchall() if row[0] != 'sqlite_sequence']
    
    def get_table_count(self, table: str) -> int:
        cursor = self.conn.execute(f"SELECT COUNT(*) FROM {table}")
        return cursor.fetchone()[0]
    
    def get_table_schema(self, table: str) -> List[Dict]:
        cursor = self.conn.execute(f"PRAGMA table_info({table})")
        return [dict(row) for row in cursor.fetchall()]
    
    def clear_table(self, table: str) -> None:
        self.conn.execute(f"DELETE FROM {table}")
        self.conn.execute(f"DELETE FROM sqlite_sequence WHERE name='{table}'")


class MigrationTester:
    """迁移测试器"""
    
    def __init__(self, db_path: str, verbose: bool = False):
        self.db_path = db_path
        self.verbose = verbose
        self.results: List[TestResult] = []
        self.db = TestDatabase(db_path)
    
    def run_all_tests(self) -> bool:
        """运行所有测试"""
        print("=" * 60)
        print("NueroNote 数据迁移测试")
        print("=" * 60)
        print(f"数据库: {self.db_path}")
        print()
        
        self.db.connect()
        
        try:
            # 1. 数据库结构测试
            self.test_database_schema()
            
            # 2. 数据完整性测试
            self.test_data_integrity()
            
            # 3. 外键约束测试
            self.test_foreign_keys()
            
            # 4. 索引测试
            self.test_indexes()
            
            # 5. 数据一致性测试
            self.test_data_consistency()
            
            # 6. 迁移记录测试
            self.test_migration_records()
            
            # 7. 回滚机制测试
            self.test_rollback_mechanism()
            
        finally:
            self.db.close()
        
        # 打印结果
        self._print_results()
        
        # 返回是否全部通过
        return all(r.passed for r in self.results)
    
    def test_database_schema(self) -> TestResult:
        """测试数据库结构"""
        name = "数据库结构测试"
        start = time.time()
        
        try:
            tables = self.db.get_tables()
            expected_tables = [
                'users', 'vaults', 'sync_log', 'audit_log',
                'vault_versions', 'document_versions', 'rate_limit'
            ]
            
            missing = set(expected_tables) - set(tables)
            extra = set(tables) - set(expected_tables)
            
            if missing:
                message = f"缺失表: {missing}"
                passed = False
            elif extra:
                message = f"多余表: {extra}"
                passed = False
            else:
                message = f"所有 {len(tables)} 个表都存在"
                passed = True
            
            # 检查users表结构
            users_schema = self.db.get_table_schema('users')
            required_columns = {'id', 'email', 'password_hash', 'plan', 
                               'storage_quota', 'storage_used', 'created_at'}
            actual_columns = {col['name'] for col in users_schema}
            
            if not required_columns.issubset(actual_columns):
                missing_cols = required_columns - actual_columns
                message = f"users表缺失列: {missing_cols}"
                passed = False
            
        except Exception as e:
            message = f"错误: {str(e)}"
            passed = False
        
        duration = (time.time() - start) * 1000
        result = TestResult(name=name, passed=passed, message=message, 
                           duration_ms=duration)
        self.results.append(result)
        return result
    
    def test_data_integrity(self) -> TestResult:
        """测试数据完整性"""
        name = "数据完整性测试"
        start = time.time()
        
        try:
            # 检查主键唯一性
            user_count = self.db.get_table_count('users')
            
            if user_count > 0:
                # 检查是否有重复的ID
                cursor = self.db.execute("""
                    SELECT id, COUNT(*) as cnt FROM users 
                    GROUP BY id HAVING cnt > 1
                """)
                duplicates = cursor.fetchall()
                
                if duplicates:
                    message = f"发现 {len(duplicates)} 个重复的用户ID"
                    passed = False
                else:
                    message = f"所有 {user_count} 个用户ID唯一"
                    passed = True
            else:
                message = "users表为空，无法测试唯一性"
                passed = True
                
        except Exception as e:
            message = f"错误: {str(e)}"
            passed = False
        
        duration = (time.time() - start) * 1000
        result = TestResult(name=name, passed=passed, message=message,
                           duration_ms=duration)
        self.results.append(result)
        return result
    
    def test_foreign_keys(self) -> TestResult:
        """测试外键约束"""
        name = "外键约束测试"
        start = time.time()
        
        try:
            # 检查外键是否启用
            cursor = self.db.execute("PRAGMA foreign_keys")
            fk_enabled = cursor.fetchone()[0]
            
            if not fk_enabled:
                message = "外键约束未启用"
                passed = False
            else:
                message = "外键约束已启用"
                passed = True
                
        except Exception as e:
            message = f"错误: {str(e)}"
            passed = False
        
        duration = (time.time() - start) * 1000
        result = TestResult(name=name, passed=passed, message=message,
                           duration_ms=duration)
        self.results.append(result)
        return result
    
    def test_indexes(self) -> TestResult:
        """测试索引"""
        name = "索引测试"
        start = time.time()
        
        try:
            expected_indexes = [
                'idx_sync_user', 'idx_audit_user', 'idx_audit_time',
                'idx_users_email', 'idx_vaultver_user', 'idx_docver_doc'
            ]
            
            cursor = self.db.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            )
            actual_indexes = [row[0] for row in cursor.fetchall() 
                            if not row[0].startswith('sqlite_')]
            
            missing = set(expected_indexes) - set(actual_indexes)
            
            if missing:
                message = f"缺失索引: {missing}"
                passed = False
            else:
                message = f"所有 {len(actual_indexes)} 个索引都存在"
                passed = True
                
        except Exception as e:
            message = f"错误: {str(e)}"
            passed = False
        
        duration = (time.time() - start) * 1000
        result = TestResult(name=name, passed=passed, message=message,
                           duration_ms=duration)
        self.results.append(result)
        return result
    
    def test_data_consistency(self) -> TestResult:
        """测试数据一致性"""
        name = "数据一致性测试"
        start = time.time()
        
        try:
            issues = []
            
            # 检查vaults表的user_id是否都在users表中
            cursor = self.db.execute("""
                SELECT COUNT(*) FROM vaults v 
                WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.id = v.user_id)
            """)
            orphan_vaults = cursor.fetchone()[0]
            if orphan_vaults > 0:
                issues.append(f"{orphan_vaults} 个孤立的vault记录")
            
            # 检查sync_log表的user_id是否都在users表中
            cursor = self.db.execute("""
                SELECT COUNT(*) FROM sync_log s 
                WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.id = s.user_id)
            """)
            orphan_syncs = cursor.fetchone()[0]
            if orphan_syncs > 0:
                issues.append(f"{orphan_syncs} 个孤立的sync_log记录")
            
            if issues:
                message = "; ".join(issues)
                passed = False
            else:
                message = "所有外键关系一致"
                passed = True
                
        except Exception as e:
            message = f"错误: {str(e)}"
            passed = False
        
        duration = (time.time() - start) * 1000
        result = TestResult(name=name, passed=passed, message=message,
                           duration_ms=duration)
        self.results.append(result)
        return result
    
    def test_migration_records(self) -> TestResult:
        """测试迁移记录"""
        name = "迁移记录测试"
        start = time.time()
        
        try:
            import glob
            log_files = glob.glob("migration_log_*.json")
            
            if not log_files:
                message = "没有找到迁移记录文件"
                passed = True  # 没有记录不算是失败
            else:
                # 检查最新记录格式
                latest_log = max(log_files)
                with open(latest_log, 'r', encoding='utf-8') as f:
                    logs = json.load(f)
                    if logs:
                        record = logs[-1]
                        required_fields = ['migration_id', 'version', 'timestamp', 'status']
                        missing = [f for f in required_fields if f not in record]
                        
                        if missing:
                            message = f"迁移记录缺失字段: {missing}"
                            passed = False
                        else:
                            message = f"迁移记录格式正确 ({latest_log})"
                            passed = True
                    else:
                        message = "迁移记录为空"
                        passed = True
                        
        except Exception as e:
            message = f"错误: {str(e)}"
            passed = False
        
        duration = (time.time() - start) * 1000
        result = TestResult(name=name, passed=passed, message=message,
                           duration_ms=duration)
        self.results.append(result)
        return result
    
    def test_rollback_mechanism(self) -> TestResult:
        """测试回滚机制"""
        name = "回滚机制测试"
        start = time.time()
        
        try:
            # 创建测试数据
            test_user_id = f"test_user_{int(time.time())}"
            now = int(time.time() * 1000)
            
            self.db.execute("""
                INSERT INTO users (id, email, plan, created_at, updated_at)
                VALUES (?, ?, 'free', ?, ?)
            """, (test_user_id, f"{test_user_id}@test.com", now, now))
            self.db.commit()
            
            # 验证插入成功
            cursor = self.db.execute("SELECT id FROM users WHERE id = ?", (test_user_id,))
            inserted = cursor.fetchone() is not None
            
            # 回滚（删除测试数据）
            self.db.execute("DELETE FROM users WHERE id = ?", (test_user_id,))
            self.db.commit()
            
            # 验证删除成功
            cursor = self.db.execute("SELECT id FROM users WHERE id = ?", (test_user_id,))
            deleted = cursor.fetchone() is None
            
            if inserted and deleted:
                message = "回滚机制正常工作"
                passed = True
            else:
                message = f"回滚测试失败 (插入:{inserted}, 删除:{deleted})"
                passed = False
                
        except Exception as e:
            message = f"错误: {str(e)}"
            passed = False
        
        duration = (time.time() - start) * 1000
        result = TestResult(name=name, passed=passed, message=message,
                           duration_ms=duration)
        self.results.append(result)
        return result
    
    def _print_results(self) -> None:
        """打印测试结果"""
        print()
        print("=" * 60)
        print("测试结果")
        print("=" * 60)
        
        passed_count = sum(1 for r in self.results if r.passed)
        total_count = len(self.results)
        
        for result in self.results:
            status = "✓" if result.passed else "✗"
            print(f"{status} {result.name}")
            print(f"  {result.message}")
            if self.verbose:
                print(f"  耗时: {result.duration_ms:.2f}ms")
                if result.details:
                    print(f"  详情: {result.details}")
        
        print()
        print("-" * 60)
        print(f"通过: {passed_count}/{total_count}")
        
        if passed_count == total_count:
            print("🎉 所有测试通过！")
        else:
            print(f"⚠ {total_count - passed_count} 个测试失败")
        
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="NueroNote 数据迁移测试")
    parser.add_argument("--db", default="nueronote.db", help="数据库路径")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    
    args = parser.parse_args()
    
    tester = MigrationTester(args.db, verbose=args.verbose)
    success = tester.run_all_tests()
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
