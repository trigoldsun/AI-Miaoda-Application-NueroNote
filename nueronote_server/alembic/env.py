#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Alembic 环境配置
配置数据库迁移的上下文和连接
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from alembic import context
from sqlalchemy import engine_from_config, pool

# 导入数据库模型
from nueronote_server.db.models import Base
from nueronote_server.config import settings

# Alembic Config对象
config = context.config

# 设置SQLAlchemy URL
if hasattr(settings.database, 'url') and settings.database.url:
    config.set_main_option('sqlalchemy.url', settings.database.url)
else:
    # 使用默认的SQLite URL
    db_path = os.environ.get('FLUX_DB', 'nueronote.db')
    if not db_path.startswith('sqlite:///'):
        db_path = f'sqlite:///{db_path}'
    config.set_main_option('sqlalchemy.url', db_path)

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 设置目标元数据（用于自动生成迁移）
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """在离线模式下运行迁移"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # 检测列类型变化
        render_as_batch=True,  # SQLite使用批量模式
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在在线模式下运行迁移"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=True,  # SQLite使用批量模式
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
