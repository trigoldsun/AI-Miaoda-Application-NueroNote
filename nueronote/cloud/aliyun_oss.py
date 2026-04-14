# -*- coding: utf-8 -*-
"""
阿里云 OSS（对象存储）适配器

阿里云 OSS 是国内最成熟的企业级对象存储，
特点：S3Compatible API、SDK 完善、按量付费

官方文档：https://help.aliyun.com/zh/oss/
Python SDK：pip install oss2

认证方式：AccessKeyId + AccessKeySecret（从环境变量或配置读取）
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from typing import Optional

from nueronote.cloud.base import (
    BaseCloudStorage,
    CloudConfig,
    CloudUploadResult,
    CloudFileInfo,
    CloudAuthError,
    CloudNetworkError,
    CloudError,
)


class AliyunOSSStorage(BaseCloudStorage):
    """
    阿里云 OSS 适配器

    配置项（extra 字段）：
    - access_key_id:      AccessKey ID（可从环境变量 ALIYUN_ACCESS_KEY_ID 读取）
    - access_key_secret:  AccessKey Secret（可从环境变量 ALIYUN_ACCESS_KEY_SECRET 读取）
    - bucket:             存储桶名称
    - region:             地域 ID（如 cn-hangzhou, cn-shanghai）
    - endpoint:           可选，自定义 endpoint（默认自动）
    - storage_class:      存储类型：Standard | IA | Archive | ColdArchive

    所需权限（RAM 策略）：
    {
        "Version": "1",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "oss:PutObject",
                    "oss:GetObject",
                    "oss:HeadObject",
                    "oss:DeleteObject",
                    "oss:ListObjects",
                    "oss:GetBucketInfo"
                ],
                "Resource": [
                    "acs:oss:*:*:<bucket-name>",
                    "acs:oss:*:*:<bucket-name>/*"
                ]
            }
        ]
    }

    费用（2025）：
    - 标准存储：0.12 元/GB/月（华东1）
    - 内网流量免费
    - 免费额度：30GB 存储 + 免费请求次数
    """

    PROVIDER_NAME = "aliyun_oss"
    PROVIDER_DISPLAY = "阿里云 OSS"

    def __init__(self, config: CloudConfig):
        super().__init__(config)
        self._client = None
        self._extra = config.extra or {}

        self.access_key_id = (
            os.environ.get("ALIYUN_ACCESS_KEY_ID") or
            self._extra.get("access_key_id") or
            ""
        )
        self.access_key_secret = (
            os.environ.get("ALIYUN_ACCESS_KEY_SECRET") or
            self._extra.get("access_key_secret") or
            ""
        )
        self.region = self._extra.get("region", "cn-hangzhou")
        self.bucket_name = self._extra.get("bucket", "")
        self.storage_class = self._extra.get("storage_class", "Standard")

        # 构造 endpoint（自动格式）
        custom_endpoint = self._extra.get("endpoint", "")
        if custom_endpoint:
            self.endpoint = custom_endpoint
        else:
            self.endpoint = f"oss-{self.region}.aliyuncs.com"

    # ─── 连接管理 ────────────────────────────────────────────────

    def _get_client(self):
        """获取/创建 OSS 客户端（延迟初始化）"""
        if self._client is not None:
            return self._client

        try:
            import oss2
        except ImportError:
            raise CloudError(
                "阿里云 OSS SDK 未安装。\n"
                "请运行：pip install oss2\n"
                "文档：https://help.aliyun.com/zh/oss/developer-reference/install-the-python-sdk"
            )

        # 凭证来源优先级：环境变量 > 配置
        auth = oss2.ProviderAuthV4(
            credentials_provider=oss2.credentials.EnvironmentVariableCredentialsProvider()
        )

        self._client = oss2.BucketV2(
            auth,
            self.endpoint,
            self.bucket_name,
        )
        return self._client

    # ─── 核心接口实现 ────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        """
        测试连通性（GetBucketInfo）
        权限：GetBucketInfo
        """
        if not self.access_key_id:
            return False, "AccessKeyId 未配置"
        if not self.bucket_name:
            return False, "Bucket 名称未配置"

        try:
            client = self._get_client()
            info = client.get_bucket_info()
            return True, (
                f"连接成功：{self.bucket_name}\n"
                f"  地域：{info.bucket_location}\n"
                f"  存储类型：{info.bucket_storage_capacity} GB\n"
                f"  创建时间：{info.bucket_creation_date}"
            )
        except Exception as e:
            err_msg = str(e)
            if "NoSuchBucket" in err_msg:
                return False, f"Bucket 不存在：{self.bucket_name}"
            if "InvalidAccessKeyId" in err_msg:
                return False, "AccessKeyId 无效"
            if "SignatureDoesNotMatch" in err_msg:
                return False, "AccessKeySecret 不正确"
            return False, f"连接失败：{err_msg}"

    def upload_vault(
        self,
        vault_data: dict,
        user_id: str,
        version: int,
        metadata: Optional[dict] = None,
    ) -> CloudUploadResult:
        """
        上传加密 vault（PutObject）
        权限：PutObject
        """
        if not self.access_key_id:
            return CloudUploadResult(
                success=False, object_key="", error="AccessKeyId 未配置",
            )

        object_key = self.vault_path(user_id, version)
        data = self.serialize_vault(vault_data)
        data_len = len(data)

        if data_len > self.MAX_FILE_SIZE:
            return CloudUploadResult(
                success=False, object_key=object_key,
                error=f"文件过大（{data_len} bytes > {self.MAX_FILE_SIZE}）",
            )

        # 构建请求头
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "x-oss-storage-class": self.storage_class,
        }

        if metadata:
            headers.update({
                f"x-oss-meta-{k}": str(v)
                for k, v in metadata.items()
                if k in ("version", "note", "timestamp", "platform")
            })

        try:
            client = self._get_client()
            result = client.put_object(
                key=object_key,
                data=data,
                headers=headers,
            )

            version_id = result.version_id or str(version)
            request_id = result.request_id

            return CloudUploadResult(
                success=True,
                object_key=object_key,
                version_id=version_id,
                size_bytes=data_len,
                url=self.generate_download_url(user_id, version),
            )

        except Exception as e:
            return CloudUploadResult(
                success=False, object_key=object_key,
                error=f"上传失败：{str(e)}",
            )

    def download_vault(
        self,
        user_id: str,
        version: int,
    ) -> Optional[dict]:
        """
        下载加密 vault（GetObject）
        权限：GetObject
        """
        object_key = self.vault_path(user_id, version)

        try:
            client = self._get_client()
            result = client.get_object(object_key)
            data = result.read()
            return self.deserialize_vault(data)
        except Exception as e:
            err_msg = str(e)
            if "NoSuchKey" in err_msg or "NoSuchVersion" in err_msg:
                return None  # 版本不存在，正常
            raise CloudNetworkError(f"下载失败：{err_msg}")

    def list_versions(
        self,
        user_id: str,
        limit: int = 50,
    ) -> list[CloudFileInfo]:
        """
        列出用户所有 vault 版本（ListObjects）
        权限：ListObjects
        """
        prefix = f"nueronote/{user_id}/vault/"

        try:
            client = self._get_client()
            files = []

            # 阿里云 OSS 分页遍历
            for obj in oss2.ObjectIterator(client, prefix=prefix, max_keys=limit):
                if not obj.key.endswith(".enc.json"):
                    continue

                try:
                    ver = int(obj.key.split("/v")[-1].replace(".enc.json", ""))
                except ValueError:
                    ver = 0

                files.append(CloudFileInfo(
                    object_key=obj.key,
                    size_bytes=int(obj.size),
                    last_modified=int(obj.last_modified),
                    etag=obj.etag or "",
                    url=self.generate_download_url(user_id, ver),
                ))

            files.sort(key=lambda f: f.object_key, reverse=True)
            return files[:limit]

        except Exception as e:
            raise CloudNetworkError(f"列表查询失败：{str(e)}")

    def delete_vault(self, user_id: str, version: int) -> bool:
        """删除指定 vault 版本"""
        object_key = self.vault_path(user_id, version)
        try:
            client = self._get_client()
            client.delete_object(object_key)
            return True
        except Exception:
            return False

    def generate_download_url(
        self,
        user_id: str,
        version: int,
        expires_seconds: int = 3600,
    ) -> str:
        """
        生成带签名的下载 URL（V4 签名）
        阿里云 OSS 支持 URL 签名，格式：
        ?Expires=<exp>&OSSAccessKeyId=<key>&Signature=<sig>
        """
        object_key = self.vault_path(user_id, version)
        if expires_seconds <= 0:
            return f"https://{self.bucket_name}.{self.endpoint}/{urllib.parse.quote(object_key)}"

        try:
            import oss2
        except ImportError:
            return ""

        try:
            client = self._get_client()
            # oss2.sign_url 生成带签名的 URL
            url = client.sign_url(
                "GET",
                object_key,
                expires=expires_seconds,
                headers={"Content-Type": "application/json"},
            )
            return url
        except Exception:
            return ""

    def get_storage_usage(self) -> tuple[int, int]:
        """
        获取 bucket 存储使用量
        权限：GetBucketStat
        注意：GetBucketStat 返回的是存储量估算值，非实时
        """
        try:
            client = self._get_client()
            stat = client.get_bucket_stat()
            return int(stat.body.storage_size_in_bytes), 0
        except Exception:
            return 0, 0

    @classmethod
    def required_config_fields(cls) -> list[tuple[str, str, str]]:
        return [
            ("access_key_id",     "AccessKeyId（从 RAM 控制台获取）",                 ""),
            ("access_key_secret",  "AccessKeySecret（从 RAM 控制台获取，勿泄露）",      ""),
            ("region",             "地域 ID（如 cn-hangzhou）",                         "cn-hangzhou"),
            ("bucket",            "存储桶名称",                                        ""),
            ("storage_class",     "存储类型：Standard | IA | Archive | ColdArchive",    "Standard"),
        ]

    def __repr__(self):
        return (
            f"<AliyunOSSStorage bucket={self.bucket_name} "
            f"region={self.region} enabled={self.config.enabled}>"
        )
