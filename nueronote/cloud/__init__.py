# -*- coding: utf-8 -*-
"""
NueroNote 云存储模块

支持三大国内云存储服务：
- 阿里云盘（个人云盘，OAuth2，推荐）
- 百度网盘（个人账户，OAuth2）
- 腾讯云 COS（对象存储，S3兼容）

使用方式：
    from nueronote.cloud import create_cloud_storage, CloudConfig

    config = CloudConfig(
        provider="aliyunpan",
        enabled=True,
        extra={
            "client_id": "xxx",
            "client_secret": "xxx",
            "access_token": "xxx",
            "refresh_token": "xxx",
        }
    )
    storage = create_cloud_storage(config)
    result = storage.upload_vault(vault_data, user_id="u123", version=1)
"""

from nueronote.cloud.base import (
    CloudConfig,
    CloudUploadResult,
    CloudFileInfo,
    CloudListResult,
    CloudError,
    CloudAuthError,
    CloudQuotaError,
    CloudNetworkError,
    BaseCloudStorage,
    create_cloud_storage,
    detect_provider,
)

from nueronote.cloud.aliyunpan import AliyunpanStorage
from nueronote.cloud.baidu_netdisk import BaiduNetdiskStorage

__all__ = [
    # 核心类
    "BaseCloudStorage",
    "CloudConfig",
    "CloudUploadResult",
    "CloudFileInfo",
    "CloudListResult",
    # 异常
    "CloudError",
    "CloudAuthError",
    "CloudQuotaError",
    "CloudNetworkError",
    # 工厂
    "create_cloud_storage",
    "detect_provider",
    # 具体实现
    "AliyunpanStorage",
    "BaiduNetdiskStorage",
]
