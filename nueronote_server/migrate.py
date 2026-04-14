#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote Alembic 迁移管理脚本
统一管理数据库迁移，支持多数据库环境。

用法:
    python migrate.py status      # 查看当前版本
    python migrate.py upgrade    # 升级到最新版本
    python migrate.py downgrade  # 回滚一个版本
    python migrate.py history   # 查看迁移历史
    python migrate.py create <message>  # 创建新迁移
"""

import os
import sys
from pathlib import Path

# 设置路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(Path(__file__).parent)

# 必须设置环境变量
os.environ.setdefault('FLUX_SECRET_KEY', 'alembic_migration_key_32chars!')
os.environ.setdefault('FLUX_DB', '../nueronote.db')

from alembic.config import Config
from alembic import command
from alembic.script import ScriptDirectory


def get_alembic_config() -> Config:
    """获取Alembic配置"""
    alembic_cfg = Config('alembic.ini')
    
    # 设置SQLAlchemy URL
    db_path = os.environ.get('FLUX_DB', '../nueronote.db')
    if not db_path.startswith('sqlite:///'):
        db_path = f'sqlite:///{os.path.abspath(db_path)}'
    
    alembic_cfg.set_main_option('sqlalchemy.url', db_path)
    
    return alembic_cfg


def cmd_status():
    """显示当前数据库版本"""
    alembic_cfg = get_alembic_config()
    
    from alembic.runtime.migration import MigrationContext
    from sqlalchemy import create_engine, text
    
    engine = create_engine(alembic_cfg.get_main_option('sqlalchemy.url'))
    with engine.connect() as conn:
        context = MigrationContext.configure(conn)
        current = context.get_current_revision()
        
        if current is None:
            print("❌ 数据库未初始化（无版本）")
        else:
            print(f"✅ 当前版本: {current}")
        
        # 显示所有可用迁移
        script = ScriptDirectory.from_config(alembic_cfg)
        heads = script.get_heads()
        
        if heads:
            print(f"📌 目标版本: {heads[0]}")
        
        if current != (heads[0] if heads else None):
            print("⚠️  数据库需要迁移")
        else:
            print("✅ 数据库已是最新版本")


def cmd_upgrade(revision: str = 'head'):
    """升级数据库"""
    alembic_cfg = get_alembic_config()
    command.upgrade(alembic_cfg, revision)
    print(f"✅ 迁移完成: {revision}")


def cmd_downgrade(revision: str = '-1'):
    """回滚数据库"""
    alembic_cfg = get_alembic_config()
    command.downgrade(alembic_cfg, revision)
    print(f"✅ 回滚完成: {revision}")


def cmd_history():
    """显示迁移历史"""
    alembic_cfg = get_alembic_config()
    script = ScriptDirectory.from_config(alembic_cfg)
    
    print("📜 迁移历史:")
    for rev in script.walk_revisions():
        if rev.revision == script.get_head():
            marker = " → (HEAD)"
        elif rev.revision == script.get_head('heads'):
            marker = ""
        else:
            marker = ""
        
        print(f"  {rev.revision}{marker} - {rev.message or 'no message'}")


def cmd_create(message: str):
    """创建新迁移"""
    alembic_cfg = get_alembic_config()
    command.revision(alembic_cfg, message=message, autogenerate=True)
    print(f"✅ 新迁移已创建: {message}")


def cmd_init():
    """初始化Alembic"""
    if not Path('alembic').exists():
        command.init_config('alembic')
        print("✅ Alembic配置已初始化")
    else:
        print("⚠️  Alembic配置已存在")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == 'status':
        cmd_status()
    elif cmd == 'upgrade':
        revision = sys.argv[2] if len(sys.argv) > 2 else 'head'
        cmd_upgrade(revision)
    elif cmd == 'downgrade':
        revision = sys.argv[2] if len(sys.argv) > 2 else '-1'
        cmd_downgrade(revision)
    elif cmd == 'history':
        cmd_history()
    elif cmd == 'create':
        if len(sys.argv) < 3:
            print("错误: 请提供迁移消息")
            sys.exit(1)
        cmd_create(sys.argv[2])
    elif cmd == 'init':
        cmd_init()
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()
