#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote MFA和信任设备数据库迁移
【更新日志 2026-04-14 v1.2】

执行方法:
    python3 nueronote_server/migrate_mfa_device.py
"""

import os
import sys
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from nueronote_server.database import Database


def run_migration():
    """执行迁移"""
    db_path = os.environ.get('NN_DB', os.environ.get('FLUX_DB', 'nueronote.db'))
    print(f"数据库: {db_path}")
    
    db = Database(db_path)
    conn = db.get_connection()
    
    migrations = [
        # MFA设置表
        """
        CREATE TABLE IF NOT EXISTS mfa_settings (
            user_id         TEXT PRIMARY KEY,
            mfa_enabled     INTEGER DEFAULT 0,
            mfa_type        TEXT DEFAULT 'email',
            phone_number    TEXT,
            backup_codes    TEXT,
            created_at      INTEGER NOT NULL,
            updated_at      INTEGER NOT NULL
        );
        """,
        
        # MFA验证码表
        """
        CREATE TABLE IF NOT EXISTS mfa_codes (
            id              TEXT PRIMARY KEY,
            user_id         TEXT NOT NULL,
            code_hash       TEXT NOT NULL,
            mfa_type        TEXT NOT NULL,
            attempts        INTEGER DEFAULT 0,
            expires_at      INTEGER NOT NULL,
            created_at      INTEGER NOT NULL,
            used_at         INTEGER,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """,
        
        # 信任设备表
        """
        CREATE TABLE IF NOT EXISTS trusted_devices (
            id              TEXT PRIMARY KEY,
            user_id         TEXT NOT NULL,
            fingerprint     TEXT NOT NULL,
            device_name     TEXT,
            browser         TEXT,
            os              TEXT,
            device_type     TEXT DEFAULT 'desktop',
            ip_address      TEXT,
            user_agent      TEXT,
            is_trusted      INTEGER DEFAULT 1,
            first_seen_at  INTEGER NOT NULL,
            last_seen_at    INTEGER NOT NULL,
            expires_at      INTEGER NOT NULL,
            login_count     INTEGER DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, fingerprint)
        );
        """,
        
        # 索引
        "CREATE INDEX IF NOT EXISTS idx_mfa_codes_user ON mfa_codes(user_id);",
        "CREATE INDEX IF NOT EXISTS idx_mfa_codes_expires ON mfa_codes(expires_at);",
        "CREATE INDEX IF NOT EXISTS idx_trusted_device_user ON trusted_devices(user_id);",
        "CREATE INDEX IF NOT EXISTS idx_trusted_device_expires ON trusted_devices(expires_at);",
        
        # users表扩展 - 信任设备开关
        """
        ALTER TABLE users ADD COLUMN trust_devices INTEGER DEFAULT 1;
        """,
    ]
    
    print("\n开始迁移...")
    
    for i, sql in enumerate(migrations, 1):
        try:
            sql = sql.strip()
            if sql:
                conn.executescript(sql)
                print(f"  ✅ [{i}/{len(migrations)}] 执行成功")
        except Exception as e:
            # 忽略"已存在"错误
            err_msg = str(e).lower()
            if 'already exists' in err_msg or 'duplicate column name' in err_msg:
                print(f"  ⚠️  [{i}/{len(migrations)}] 已存在，跳过")
            else:
                print(f"  ❌ [{i}/{len(migrations)}] 错误: {e}")
    
    conn.commit()
    print("\n✅ 迁移完成！")
    
    # 显示表结构
    print("\n📋 当前表列表:")
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    for row in cursor:
        print(f"  - {row[0]}")


if __name__ == '__main__':
    run_migration()
