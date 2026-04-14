# -*- coding: utf-8 -*-
"""
NueroNote 云存储抽象层
统一接口，支持多云存储后端：
- 腾讯云 COS（对象存储，S3兼容）
- 阿里云盘（个人云盘，OAuth2）
- 百度网盘（个人账户，OAuth2）
"""

from __future__ import annotations

import json
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class CloudConfig:
    """云存储配置（用户填写）"""
    provider: str = ""           # "tencent_cos" | "aliyunpan" | "baidu_netdisk"
    enabled: bool = False
    auto_sync: bool = False       # 自动同步开关
    last_sync: int = 0            # 上次同步时间戳
    extra: dict = field(default_factory=dict)  # 各 provider 特有配置

    def to_json(self) -> dict:
        return {
            "provider": self.provider,
            "enabled": self.enabled,
            "auto_sync": self.auto_sync,
            "last_sync": self.last_sync,
            "extra": self.extra,
        }

    @classmethod
    def from_json(cls, d: dict) -> "CloudConfig":
        return cls(
            provider=d.get("provider", ""),
            enabled=d.get("enabled", False),
            auto_sync=d.get("auto_sync", False),
            last_sync=d.get("last_sync", 0),
            extra=d.get("extra", {}),
        )


@dataclass
class CloudUploadResult:
    """上传结果"""
    success: bool
    object_key: str              # 云端对象路径
    version_id: Optional[str] = None  # 云端版本号
    size_bytes: int = 0
    url: str = ""                # 下载/预览 URL
    error: str = ""


@dataclass
class CloudFileInfo:
    """云端文件信息"""
    object_key: str
    size_bytes: int
    last_modified: int           # Unix 时间戳
    etag: str = ""
    url: str = ""


@dataclass
class CloudListResult:
    """列表查询结果"""
    files: list[CloudFileInfo]
    prefix: str                  # 查询前缀
    next_marker: str = ""        # 分页标记


# ============================================================================
# 异常
# ============================================================================

class CloudError(Exception):
    """云存储通用错误"""


class CloudAuthError(CloudError):
    """认证失败（凭证过期/无效）"""


class CloudQuotaError(CloudError):
    """存储配额不足"""


class CloudNetworkError(CloudError):
    """网络连接失败"""


# ============================================================================
# 抽象基类
# ============================================================================

class BaseCloudStorage(ABC):
    """
    云存储适配器基类

    设计原则：
    1. 所有云存储均存储"加密后的 vault JSON"（不上传明文）
    2. 对象路径格式：nueronote/{user_id}/vault/{version}/vault.json
    3. 自动处理重试、超时
    4. 每个方法标注所需权限
    """

    PROVIDER_NAME: str = "unknown"
    MAX_FILE_SIZE: int = 50 * 1024 * 1024  # 50MB（大多数云单文件限制）

    def __init__(self, config: CloudConfig):
        self.config = config
        self._client = None

    # ─── 通用接口 ────────────────────────────────────────────────

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """
        测试连接是否可用
        返回：(success, message)
        """
        pass

    @abstractmethod
    def upload_vault(
        self,
        vault_data: dict,
        user_id: str,
        version: int,
        metadata: Optional[dict] = None,
    ) -> CloudUploadResult:
        """
        上传加密 vault 到云存储

        Args:
            vault_data: 加密的 vault JSON（FluxVault.export_vault() 输出）
            user_id: 用户 ID（用于路径隔离）
            version: vault 版本号
            metadata: 可选元数据（如时间戳、备注）

        Returns:
            CloudUploadResult

        所需权限：写入
        """
        pass

    @abstractmethod
    def download_vault(
        self,
        user_id: str,
        version: int,
    ) -> Optional[dict]:
        """
        从云存储下载加密 vault

        Args:
            user_id: 用户 ID
            version: vault 版本号（None=最新）

        Returns:
            vault JSON dict 或 None（不存在）
        """
        pass

    @abstractmethod
    def list_versions(
        self,
        user_id: str,
        limit: int = 50,
    ) -> list[CloudFileInfo]:
        """
        列出用户的所有 vault 版本

        Returns:
            按版本倒序排列
        """
        pass

    @abstractmethod
    def delete_vault(
        self,
        user_id: str,
        version: int,
    ) -> bool:
        """删除指定版本（可选）"""
        pass

    @abstractmethod
    def generate_download_url(
        self,
        user_id: str,
        version: int,
        expires_seconds: int = 3600,
    ) -> str:
        """
        生成临时下载 URL（用于分享/导出）
        返回预签名 URL
        """
        pass

    @abstractmethod
    def get_storage_usage(self) -> tuple[int, int]:
        """
        获取存储使用量

        Returns:
            (used_bytes, total_bytes)
        """
        pass

    # ─── 工具方法 ────────────────────────────────────────────────

    def vault_path(self, user_id: str, version: int) -> str:
        """
        生成 vault 对象路径
        格式：nueronote/{user_id}/vault/v{version}.enc.json
        """
        return f"nueronote/{user_id}/vault/v{version}.enc.json"

    def vault_metadata_path(self, user_id: str, version: int) -> str:
        """元数据文件路径"""
        return f"nueronote/{user_id}/vault/v{version}.meta.json"

    @staticmethod
    def serialize_vault(vault_data: dict) -> bytes:
        """序列化 vault 为 JSON bytes"""
        return json.dumps(vault_data, ensure_ascii=False, separators=(',', ':')).encode('utf-8')

    @staticmethod
    def deserialize_vault(data: bytes) -> dict:
        """反序列化 vault"""
        return json.loads(data.decode('utf-8'))

    def validate_config(self) -> list[str]:
        """
        验证配置完整性，返回缺失字段列表
        """
        errors = []
        if not self.config.provider:
            errors.append("provider（云服务商未设置）")
        if not self.config.enabled:
            errors.append("enabled（云同步未开启）")
        return errors


# ============================================================================
# 云存储工厂
# ============================================================================

def create_cloud_storage(config: CloudConfig) -> Optional[BaseCloudStorage]:
    """
    根据配置创建对应的云存储实例
    """
    if not config or not config.enabled:
        return None

    provider_map = {
        "tencent_cos": "tencent_cos",
        "aliyunpan": "aliyunpan",
        "baidu_netdisk": "baidu_netdisk",
    }

    module_name = provider_map.get(config.provider)
    if not module_name:
        return None

    try:
        if module_name == "tencent_cos":
            from nueronote.cloud.tencent_cos import TencentCOSStorage
            return TencentCOSStorage(config)
        elif module_name == "aliyunpan":
            from nueronote.cloud.aliyunpan import AliyunpanStorage
            return AliyunpanStorage(config)
        elif module_name == "baidu_netdisk":
            from nueronote.cloud.baidu_netdisk import BaiduNetdiskStorage
            return BaiduNetdiskStorage(config)
    except ImportError as e:
        raise CloudError(f"无法加载云存储模块 {module_name}: {e}")

    return None


def detect_provider(name: str) -> Optional[str]:
    """
    从名称推断云服务商标识
    """
    name_lower = name.lower()
    if "tencent" in name_lower or "cos" in name_lower or "腾讯" in name:
        return "tencent_cos"
    if "aliyunpan" in name_lower or "aliyun" in name_lower or "云盘" in name:
        return "aliyunpan"
    if "baidu" in name_lower or "netdisk" in name_lower or "百度" in name:
        return "baidu_netdisk"
    return None
