#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 配置管理模块

支持环境变量配置,优先级:环境变量 > .env文件 > 默认值
如果pydantic-settings可用,使用类型安全验证;否则使用简单配置。
"""

import os
import secrets
import warnings
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


# 尝试导入pydantic,如果不可用则使用dataclass回退
try:
    from pydantic import BaseModel, Field, field_validator
    from pydantic_settings import BaseSettings
    PYDANTIC_AVAILABLE = True
except ImportError:
    PYDANTIC_AVAILABLE = False
    warnings.warn("pydantic-settings未安装,使用简单配置管理。建议安装:pip install pydantic-settings")


if PYDANTIC_AVAILABLE:
    # ====== 使用pydantic的配置类 ======

    class DatabaseConfig(BaseModel):
        """数据库配置"""
        # 基础连接配置
        url: str = Field(default="sqlite:///nueronote.db", description="数据库连接URL")
        database_type: str = Field(default="auto", description="数据库类型: auto, postgresql, mysql, sqlite")
        
        # 连接池配置
        pool_size: int = Field(default=5, ge=1, le=100, description="连接池大小")
        max_overflow: int = Field(default=10, ge=0, le=100, description="连接池最大溢出")
        pool_timeout: int = Field(default=30, ge=10, le=120, description="连接超时(秒)")
        pool_recycle: int = Field(default=3600, description="连接回收时间(秒)")
        pool_pre_ping: bool = Field(default=True, description="连接前ping检查")
        
        # SSL/TLS配置
        ssl_mode: str = Field(default="prefer", description="SSL模式: disable, allow, prefer, require, verify-ca, verify-full")
        ssl_cert: Optional[str] = Field(default=None, description="SSL客户端证书路径")
        ssl_key: Optional[str] = Field(default=None, description="SSL客户端密钥路径")
        ssl_ca: Optional[str] = Field(default=None, description="SSL CA证书路径")
        
        # 超时配置
        connect_timeout: int = Field(default=10, ge=1, le=60, description="连接超时(秒)")
        statement_timeout: int = Field(default=30000, ge=0, description="SQL语句超时(毫秒)")
        idle_in_transaction_timeout: int = Field(default=0, ge=0, description="空闲事务超时(毫秒)")
        
        # 读写分离配置
        read_replica_urls: List[str] = Field(default_factory=list, description="只读副本URL列表")
        write_replica_urls: List[str] = Field(default_factory=list, description="写副本URL列表")
        load_balance: bool = Field(default=False, description="是否启用负载均衡")
        
        # 监控和调优
        monitoring_enabled: bool = Field(default=False, description="是否启用数据库监控")
        slow_query_threshold: int = Field(default=1000, description="慢查询阈值(毫秒)")
        log_queries: bool = Field(default=False, description="是否记录所有查询")
        log_slow_queries: bool = Field(default=True, description="是否记录慢查询")
        
        # 数据库特定配置
        echo: bool = Field(default=False, description="是否输出SQL日志")
        cache_size: int = Field(default=2000, description="SQLite缓存大小(KB)")
        
        # PostgreSQL特定
        postgresql_application_name: str = Field(default="nueronote", description="PostgreSQL应用名称")
        postgresql_keepalives: bool = Field(default=True, description="PostgreSQL保持连接")
        postgresql_keepalives_idle: int = Field(default=30, description="PostgreSQL保持连接空闲时间")
        
        # MySQL特定
        mysql_charset: str = Field(default="utf8mb4", description="MySQL字符集")
        mysql_collation: str = Field(default="utf8mb4_unicode_ci", description="MySQL排序规则")
        mysql_engine: str = Field(default="InnoDB", description="MySQL存储引擎")
        
        @field_validator('database_type')
        @classmethod
        def validate_database_type(cls, v: str) -> str:
            valid_types = ['auto', 'postgresql', 'mysql', 'sqlite', 'oracle', 'sqlserver']
            if v.lower() not in valid_types:
                raise ValueError(f'数据库类型必须是: {valid_types}')
            return v.lower()
        
        @field_validator('ssl_mode')
        @classmethod
        def validate_ssl_mode(cls, v: str) -> str:
            valid_modes = ['disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full']
            if v.lower() not in valid_modes:
                raise ValueError(f'SSL模式必须是: {valid_modes}')
            return v.lower()

    class SecurityConfig(BaseModel):
        """安全配置"""
        secret_key: str = Field(..., description="Flask应用密钥,必须设置")
        jwt_secret: str = Field(..., description="JWT签名密钥,建议与secret_key不同")
        token_expire_hours: int = Field(default=24, ge=1, le=168, description="JWT过期时间(小时)")
        bcrypt_rounds: int = Field(default=12, ge=10, le=15, description="密码哈希轮数")
        max_login_fails: int = Field(default=5, ge=1, le=10, description="最大登录失败次数")
        lockout_minutes: int = Field(default=15, ge=5, le=60, description="账户锁定时间(分钟)")

    class StorageConfig(BaseModel):
        """存储配额配置(字节)"""
        quota_free: int = Field(default=512 * 1024 * 1024, description="免费用户配额512MB")
        quota_pro: int = Field(default=10 * 1024**3, description="Pro用户配额10GB")
        quota_team: int = Field(default=100 * 1024**3, description="团队用户配额100GB")
        max_request_size: int = Field(default=10 * 1024 * 1024, description="最大请求体大小10MB")

        @field_validator('quota_free', 'quota_pro', 'quota_team', 'max_request_size')
        @classmethod
        def validate_positive(cls, v: int) -> int:
            if v <= 0:
                raise ValueError('必须为正整数')
            return v

    class RedisConfig(BaseModel):
        """Redis缓存配置"""
        enabled: bool = Field(default=True, description="是否启用Redis缓存")
        url: str = Field(default="redis://localhost:6379/0", description="Redis连接URL")
        socket_timeout: int = Field(default=5, description="Socket超时(秒)")
        socket_connect_timeout: int = Field(default=5, description="连接超时(秒)")
        socket_keepalive: bool = Field(default=True, description="保持连接")
        max_connections: int = Field(default=50, description="最大连接数")
        health_check_interval: int = Field(default=30, description="健康检查间隔(秒)")

        # 缓存TTL配置(秒)
        user_cache_ttl: int = Field(default=300, description="用户信息缓存时间")
        vault_cache_ttl: int = Field(default=60, description="Vault元数据缓存时间")
        token_cache_ttl: int = Field(default=86400, description="会话令牌缓存时间")
        rate_limit_ttl: int = Field(default=60, description="限流计数缓存时间")

    class CloudConfig(BaseModel):
        """云存储配置"""
        enabled: bool = Field(default=False, description="是否启用云存储")
        default_provider: str = Field(default="aliyunpan", description="默认云服务商")
        sync_interval: int = Field(default=300, description="自动同步间隔(秒)")
        chunk_size: int = Field(default=10 * 1024 * 1024, description="分片上传大小")

    class RateLimitConfig(BaseModel):
        """速率限制配置"""
        enabled: bool = Field(default=True, description="是否启用速率限制")
        ip_limit_per_minute: int = Field(default=60, description="IP每分钟请求限制")
        user_limit_per_minute: int = Field(default=120, description="用户每分钟请求限制")
        auth_limit_per_minute: int = Field(default=10, description="认证接口每分钟限制")
        window_seconds: int = Field(default=60, description="滑动窗口时间(秒)")

        @field_validator('ip_limit_per_minute', 'user_limit_per_minute', 'auth_limit_per_minute')
        @classmethod
        def validate_positive(cls, v: int) -> int:
            if v <= 0:
                raise ValueError('必须为正整数')
            return v

    class Settings(BaseSettings):
        """主配置类"""

        # 应用配置
        debug: bool = Field(default=False, description="调试模式")
        host: str = Field(default="127.0.0.1", description="监听地址")
        port: int = Field(default=5000, ge=1, le=65535, description="监听端口")
        workers: int = Field(default=1, ge=1, le=32, description="工作进程数")

        # 子配置
        database: DatabaseConfig = Field(default_factory=DatabaseConfig)
        security: SecurityConfig
        storage: StorageConfig = Field(default_factory=StorageConfig)
        cloud: CloudConfig = Field(default_factory=CloudConfig)
        redis: RedisConfig = Field(default_factory=RedisConfig)
        rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)

        class Config:
            env_prefix = "NN_"  # 环境变量前缀
            env_nested_delimiter = "__"  # 嵌套分隔符
            case_sensitive = False
            env_file = ".env"
            env_file_encoding = "utf-8"

        @classmethod
        def create(cls) -> "Settings":
            """
            创建配置实例,处理密钥自动生成
            """
            # 检查必需的安全密钥
            secret_key = os.environ.get("NN_SECRET_KEY")
            jwt_secret = os.environ.get("NN_JWT_SECRET")

            if not secret_key:
                if os.environ.get("NN_DEBUG") == "true":
                    # 开发环境:生成临时密钥(每次重启变化)
                    secret_key = secrets.token_urlsafe(32)
                    print("⚠️  警告:使用临时生成的SECRET_KEY,生产环境必须设置NN_SECRET_KEY环境变量")
                else:
                    raise ValueError("生产环境必须设置NN_SECRET_KEY环境变量")

            if not jwt_secret:
                if secret_key and os.environ.get("NN_DEBUG") == "true":
                    # 开发环境:使用不同的密钥
                    jwt_secret = secrets.token_urlsafe(32)
                else:
                    raise ValueError("必须设置NN_JWT_SECRET环境变量")

            # 确保环境变量已设置,以便pydantic能读取
            os.environ["NN_SECRET_KEY"] = secret_key
            os.environ["NN_JWT_SECRET"] = jwt_secret

            return cls()

else:
    # ====== 使用dataclass的简单配置类 ======

    @dataclass
    class DatabaseConfig:
        """数据库配置"""
        # 基础连接配置
        url: str = "sqlite:///nueronote.db"
        database_type: str = "auto"
        
        # 连接池配置
        pool_size: int = 5
        max_overflow: int = 10
        pool_timeout: int = 30
        pool_recycle: int = 3600
        pool_pre_ping: bool = True
        
        # SSL/TLS配置
        ssl_mode: str = "prefer"
        ssl_cert: Optional[str] = None
        ssl_key: Optional[str] = None
        ssl_ca: Optional[str] = None
        
        # 超时配置
        connect_timeout: int = 10
        statement_timeout: int = 30000
        idle_in_transaction_timeout: int = 0
        
        # 读写分离配置
        read_replica_urls: List[str] = field(default_factory=list)
        write_replica_urls: List[str] = field(default_factory=list)
        load_balance: bool = False
        
        # 监控和调优
        monitoring_enabled: bool = False
        slow_query_threshold: int = 1000
        log_queries: bool = False
        log_slow_queries: bool = True
        
        # 数据库特定配置
        echo: bool = False
        cache_size: int = 2000
        
        # PostgreSQL特定
        postgresql_application_name: str = "nueronote"
        postgresql_keepalives: bool = True
        postgresql_keepalives_idle: int = 30
        
        # MySQL特定
        mysql_charset: str = "utf8mb4"
        mysql_collation: str = "utf8mb4_unicode_ci"
        mysql_engine: str = "InnoDB"

        def __post_init__(self):
            """从环境变量加载数据库配置"""
            import os
            env_prefix = "NN_DATABASE__"
            
            # 基础连接配置
            if url_env := os.environ.get(env_prefix + "URL"):
                self.url = url_env
            if db_type_env := os.environ.get(env_prefix + "DATABASE_TYPE"):
                self.database_type = db_type_env.lower()
            
            # 连接池配置
            if pool_size_env := os.environ.get(env_prefix + "POOL_SIZE"):
                self.pool_size = int(pool_size_env)
            if max_overflow_env := os.environ.get(env_prefix + "MAX_OVERFLOW"):
                self.max_overflow = int(max_overflow_env)
            if pool_timeout_env := os.environ.get(env_prefix + "POOL_TIMEOUT"):
                self.pool_timeout = int(pool_timeout_env)
            if pool_recycle_env := os.environ.get(env_prefix + "POOL_RECYCLE"):
                self.pool_recycle = int(pool_recycle_env)
            if pool_pre_ping_env := os.environ.get(env_prefix + "POOL_PRE_PING"):
                self.pool_pre_ping = pool_pre_ping_env.lower() == "true"
            
            # SSL/TLS配置
            if ssl_mode_env := os.environ.get(env_prefix + "SSL_MODE"):
                self.ssl_mode = ssl_mode_env.lower()
            if ssl_cert_env := os.environ.get(env_prefix + "SSL_CERT"):
                self.ssl_cert = ssl_cert_env
            if ssl_key_env := os.environ.get(env_prefix + "SSL_KEY"):
                self.ssl_key = ssl_key_env
            if ssl_ca_env := os.environ.get(env_prefix + "SSL_CA"):
                self.ssl_ca = ssl_ca_env
            
            # 超时配置
            if connect_timeout_env := os.environ.get(env_prefix + "CONNECT_TIMEOUT"):
                self.connect_timeout = int(connect_timeout_env)
            if statement_timeout_env := os.environ.get(env_prefix + "STATEMENT_TIMEOUT"):
                self.statement_timeout = int(statement_timeout_env)
            if idle_timeout_env := os.environ.get(env_prefix + "IDLE_IN_TRANSACTION_TIMEOUT"):
                self.idle_in_transaction_timeout = int(idle_timeout_env)
            
            # 读写分离配置
            if read_replicas_env := os.environ.get(env_prefix + "READ_REPLICA_URLS"):
                self.read_replica_urls = [url.strip() for url in read_replicas_env.split(",") if url.strip()]
            if write_replicas_env := os.environ.get(env_prefix + "WRITE_REPLICA_URLS"):
                self.write_replica_urls = [url.strip() for url in write_replicas_env.split(",") if url.strip()]
            if load_balance_env := os.environ.get(env_prefix + "LOAD_BALANCE"):
                self.load_balance = load_balance_env.lower() == "true"
            
            # 监控和调优
            if monitoring_env := os.environ.get(env_prefix + "MONITORING_ENABLED"):
                self.monitoring_enabled = monitoring_env.lower() == "true"
            if slow_query_env := os.environ.get(env_prefix + "SLOW_QUERY_THRESHOLD"):
                self.slow_query_threshold = int(slow_query_env)
            if log_queries_env := os.environ.get(env_prefix + "LOG_QUERIES"):
                self.log_queries = log_queries_env.lower() == "true"
            if log_slow_queries_env := os.environ.get(env_prefix + "LOG_SLOW_QUERIES"):
                self.log_slow_queries = log_slow_queries_env.lower() == "true"
            
            # 数据库特定配置
            if echo_env := os.environ.get(env_prefix + "ECHO"):
                self.echo = echo_env.lower() == "true"
            if cache_size_env := os.environ.get(env_prefix + "CACHE_SIZE"):
                self.cache_size = int(cache_size_env)
            
            # PostgreSQL特定
            if pg_app_name_env := os.environ.get(env_prefix + "POSTGRESQL_APPLICATION_NAME"):
                self.postgresql_application_name = pg_app_name_env
            if pg_keepalives_env := os.environ.get(env_prefix + "POSTGRESQL_KEEPALIVES"):
                self.postgresql_keepalives = pg_keepalives_env.lower() == "true"
            if pg_keepalives_idle_env := os.environ.get(env_prefix + "POSTGRESQL_KEEPALIVES_IDLE"):
                self.postgresql_keepalives_idle = int(pg_keepalives_idle_env)
            
            # MySQL特定
            if mysql_charset_env := os.environ.get(env_prefix + "MYSQL_CHARSET"):
                self.mysql_charset = mysql_charset_env
            if mysql_collation_env := os.environ.get(env_prefix + "MYSQL_COLLATION"):
                self.mysql_collation = mysql_collation_env
            if mysql_engine_env := os.environ.get(env_prefix + "MYSQL_ENGINE"):
                self.mysql_engine = mysql_engine_env
    
    @dataclass
    class SecurityConfig:
        """安全配置"""
        secret_key: str = field(default_factory=lambda: os.environ.get("NN_SECRET_KEY", ""))
        jwt_secret: str = field(default_factory=lambda: os.environ.get("NN_JWT_SECRET", ""))
        token_expire_hours: int = 24
        bcrypt_rounds: int = 12
        max_login_fails: int = 5
        lockout_minutes: int = 15

        def __post_init__(self):
            if not self.secret_key:
                if os.environ.get("NN_DEBUG", "false").lower() == "true":
                    self.secret_key = secrets.token_urlsafe(32)
                    print("⚠️  警告:使用临时生成的SECRET_KEY,生产环境必须设置NN_SECRET_KEY环境变量")
                else:
                    raise ValueError("生产环境必须设置NN_SECRET_KEY环境变量")
            if not self.jwt_secret:
                self.jwt_secret = secrets.token_urlsafe(32)
                if os.environ.get("NN_DEBUG", "false").lower() != "true":
                    print("⚠️  警告:使用临时生成的JWT_SECRET,建议设置NN_JWT_SECRET环境变量")

    @dataclass
    class StorageConfig:
        """存储配额配置(字节)"""
        quota_free: int = 512 * 1024 * 1024
        quota_pro: int = 10 * 1024**3
        quota_team: int = 100 * 1024**3
        max_request_size: int = 10 * 1024 * 1024

    @dataclass
    class RedisConfig:
        """Redis缓存配置"""
        enabled: bool = True
        url: str = "redis://localhost:6379/0"
        socket_timeout: int = 5
        socket_connect_timeout: int = 5
        socket_keepalive: bool = True
        max_connections: int = 50
        health_check_interval: int = 30
        user_cache_ttl: int = 300
        vault_cache_ttl: int = 60
        token_cache_ttl: int = 86400
        rate_limit_ttl: int = 60
    
    @dataclass
    class CloudConfig:
        """云存储配置"""
        enabled: bool = False
        default_provider: str = "aliyunpan"
        sync_interval: int = 300
        chunk_size: int = 10 * 1024 * 1024
    
    @dataclass
    class RateLimitConfig:
        """速率限制配置"""
        enabled: bool = True
        ip_limit_per_minute: int = 60
        user_limit_per_minute: int = 120
        auth_limit_per_minute: int = 10
        window_seconds: int = 60
    
    @dataclass
    class Settings:
        """主配置类"""
        debug: bool = False
        host: str = "127.0.0.1"
        port: int = 5000
        workers: int = 1
        database: DatabaseConfig = field(default_factory=DatabaseConfig)
        security: SecurityConfig = field(default_factory=SecurityConfig)
        storage: StorageConfig = field(default_factory=StorageConfig)
        cloud: CloudConfig = field(default_factory=CloudConfig)
        redis: RedisConfig = field(default_factory=RedisConfig)
        rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)

        @classmethod
        def create(cls) -> "Settings":
            """创建配置实例"""
            return cls()


def get_settings() -> Settings:
    """
    获取配置实例(单例模式)
    """
    if not hasattr(get_settings, "_instance"):
        get_settings._instance = Settings.create()
    return get_settings._instance


# 导出配置实例
settings = get_settings()


# 环境变量读取工具函数
def get_env_bool(key: str, default: bool = False) -> bool:
    """从环境变量读取布尔值"""
    val = os.environ.get(key, "").lower()
    if val in ("1", "true", "yes", "on"):
        return True
    elif val in ("0", "false", "no", "off"):
        return False
    return default


def get_env_int(key: str, default: int = 0) -> int:
    """从环境变量读取整数"""
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


def get_env_str(key: str, default: str = "") -> str:
    """从环境变量读取字符串"""
    return os.environ.get(key, default)
