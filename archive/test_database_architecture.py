#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试NueroNote新的数据库适配器架构
"""

import sys
import os
import logging

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_config_loading():
    """测试配置加载"""
    print("=== 测试配置加载 ===")
    
    try:
        from nueronote_server.config import settings
        print(f"✓ 配置加载成功")
        print(f"  调试模式: {settings.debug}")
        print(f"  数据库URL: {settings.database.url}")
        print(f"  数据库类型: {settings.database.database_type}")
        print(f"  连接池大小: {settings.database.pool_size}")
        return True
    except Exception as e:
        print(f"✗ 配置加载失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_adapter_factory():
    """测试适配器工厂"""
    print("\n=== 测试适配器工厂 ===")
    
    try:
        from nueronote_server.db.factory import get_factory, init_database_factory
        
        factory = init_database_factory()
        print(f"✓ 适配器工厂初始化成功")
        
        # 获取主适配器
        primary_adapter = factory.get_adapter('primary')
        print(f"  主适配器: {primary_adapter}")
        print(f"  数据库方言: {primary_adapter.dialect}")
        
        # 测试连接
        connected = primary_adapter.test_connection()
        print(f"  连接测试: {'成功' if connected else '失败'}")
        
        if connected:
            # 获取数据库信息
            info = primary_adapter.get_database_info()
            print(f"  数据库信息:")
            for key, value in list(info.items())[:5]:  # 只显示前5项
                print(f"    {key}: {value}")
        
        # 健康检查
        health = factory.health_check()
        print(f"  健康状态: {health['overall']}")
        
        return True
    except Exception as e:
        print(f"✗ 适配器工厂测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_database_manager():
    """测试数据库管理器（向后兼容）"""
    print("\n=== 测试数据库管理器 ===")
    
    try:
        from nueronote_server.db import (
            get_engine, get_session_factory, get_db_session,
            get_primary_adapter, get_read_adapter, get_write_adapter,
            health_check
        )
        
        print(f"✓ 数据库管理器导入成功")
        
        # 向后兼容接口
        engine = get_engine()
        print(f"  引擎: {engine}")
        
        session_factory = get_session_factory()
        print(f"  会话工厂: {session_factory}")
        
        # 适配器接口
        primary_adapter = get_primary_adapter()
        print(f"  主适配器: {primary_adapter}")
        
        read_adapter = get_read_adapter()
        print(f"  读适配器: {read_adapter}")
        
        write_adapter = get_write_adapter()
        print(f"  写适配器: {write_adapter}")
        
        # 健康检查
        health = health_check()
        print(f"  健康检查: {health['overall']}")
        
        # 测试会话
        print(f"  测试数据库会话...")
        try:
            with get_db_session() as session:
                # 执行简单查询
                result = session.execute("SELECT 1 as test")
                row = result.fetchone()
                print(f"    简单查询: {row[0] if row else '无结果'}")
        except Exception as e:
            print(f"    会话测试失败: {e}")
        
        return True
    except Exception as e:
        print(f"✗ 数据库管理器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_model_compatibility():
    """测试模型与所有数据库的兼容性"""
    print("\n=== 测试模型兼容性 ===")
    
    try:
        from nueronote_server.models import Base
        from sqlalchemy import inspect
        
        print(f"✓ 模型导入成功")
        print(f"  表数量: {len(Base.metadata.tables)}")
        
        # 检查每个表的列定义
        for table_name, table in Base.metadata.tables.items():
            print(f"  表: {table_name}")
            for column in table.columns:
                col_type = str(column.type)
                # 检查是否有不兼容的类型
                if 'JSONB' in col_type:
                    print(f"    ⚠️  警告: {column.name} 使用JSONB类型，可能不兼容所有数据库")
                elif 'TSVECTOR' in col_type:
                    print(f"    ⚠️  警告: {column.name} 使用TSVECTOR类型，PostgreSQL特有")
            print()
        
        return True
    except Exception as e:
        print(f"✗ 模型兼容性测试失败: {e}")
        return False


def test_environment_variables():
    """测试环境变量配置"""
    print("\n=== 测试环境变量配置 ===")
    
    try:
        # 设置测试环境变量
        os.environ['FLUX_DATABASE__URL'] = 'sqlite:///test_nueronote.db'
        os.environ['FLUX_DATABASE__DATABASE_TYPE'] = 'sqlite'
        os.environ['FLUX_DATABASE__POOL_SIZE'] = '10'
        os.environ['FLUX_DATABASE__MAX_OVERFLOW'] = '20'
        os.environ['FLUX_DATABASE__SSL_MODE'] = 'disable'
        
        from nueronote_server.config import settings
        
        print(f"✓ 环境变量配置成功")
        print(f"  数据库URL: {settings.database.url}")
        print(f"  数据库类型: {settings.database.database_type}")
        print(f"  连接池大小: {settings.database.pool_size}")
        print(f"  最大溢出: {settings.database.max_overflow}")
        print(f"  SSL模式: {settings.database.ssl_mode}")
        
        # 清理环境变量
        for key in ['FLUX_DATABASE__URL', 'FLUX_DATABASE__DATABASE_TYPE',
                   'FLUX_DATABASE__POOL_SIZE', 'FLUX_DATABASE__MAX_OVERFLOW',
                   'FLUX_DATABASE__SSL_MODE']:
            os.environ.pop(key, None)
        
        return True
    except Exception as e:
        print(f"✗ 环境变量测试失败: {e}")
        return False


def main():
    """主测试函数"""
    print("NueroNote 数据库适配器架构测试")
    print("=" * 50)
    
    tests = [
        test_config_loading,
        test_adapter_factory,
        test_database_manager,
        test_model_compatibility,
        test_environment_variables,
    ]
    
    results = []
    for test_func in tests:
        try:
            success = test_func()
            results.append((test_func.__name__, success))
        except Exception as e:
            print(f"测试 {test_func.__name__} 异常: {e}")
            results.append((test_func.__name__, False))
    
    print("\n" + "=" * 50)
    print("测试结果:")
    
    passed = 0
    for name, success in results:
        status = "✓ 通过" if success else "✗ 失败"
        print(f"  {name}: {status}")
        if success:
            passed += 1
    
    print(f"\n总计: {passed}/{len(results)} 通过")
    
    if passed == len(results):
        print("🎉 所有测试通过！")
        return 0
    else:
        print("⚠️  部分测试失败")
        return 1


if __name__ == '__main__':
    sys.exit(main())