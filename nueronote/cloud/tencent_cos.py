# -*- coding: utf-8 -*-
"""
腾讯云 COS（对象存储）适配器

腾讯云 COS 是 S3 兼容的对象存储，
特点：接入简单、S3 兼容 SDK、按量付费、免费额度大

官方文档：https://cloud.tencent.com/document/product/436
Python SDK：pip install cos-python-sdk-v5

认证方式：SecretId + SecretKey（从环境变量或配置读取）
"""

from __future__ import annotations

import os

import hashlib
import hmac
import json
import time
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


# ============================================================================
# 腾讯云 COS 存储适配器
# ============================================================================

class TencentCOSStorage(BaseCloudStorage):
    """
    腾讯云 COS 适配器

    配置项（extra 字段）：
    - secret_id:      密钥 ID（可从环境变量 TENCENT_SECRET_ID 读取）
    - secret_key:     密钥 Key（可从环境变量 TENCENT_SECRET_KEY 读取）
    - region:         地域（如 ap-guangzhou, ap-shanghai）
    - bucket:         存储桶名称（不含 .cos. 前缀）
    - endpoint_suffix: 可选，自定义域名后缀（默认自动）
    - storage_class:  存储类型（STANDARD | STANDARD_IA | ARCHIVE）

    所需权限（CAM 策略）：
    {
        "Version": "2.0",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "cos:PutObject",
                    "cos:GetObject",
                    "cos:HeadObject",
                    "cos:DeleteObject",
                    "cos:GetBucket",
                    "cos:ListBucket"
                ],
                "Resource": "qcs::cos:<region>::<bucket>/*"
            }
        ]
    }

    费用（2025）：
    - 存储：0.118 元/GB/月（标准存储）
    - 外网下行：0.5 元/GB
    - 免费额度：50GB 存储 + 10GB 月流量
    """

    PROVIDER_NAME = "tencent_cos"
    PROVIDER_DISPLAY = "腾讯云 COS"

    def __init__(self, config: CloudConfig):
        super().__init__(config)
        self._client = None
        self._extra = config.extra or {}

        # 从环境变量或配置读取凭证
        self.secret_id = (
            os.environ.get("TENCENT_SECRET_ID") or
            self._extra.get("secret_id") or
            ""
        )
        self.secret_key = (
            os.environ.get("TENCENT_SECRET_KEY") or
            self._extra.get("secret_key") or
            ""
        )
        self.region = self._extra.get("region", "ap-guangzhou")
        self.bucket = self._extra.get("bucket", "")
        self.storage_class = self._extra.get("storage_class", "STANDARD")
        self.endpoint_suffix = self._extra.get(
            "endpoint_suffix",
            f"cos.{self.region}.myqcloud.com"
        )

    # ─── 连接管理 ────────────────────────────────────────────────

    def _get_client(self):
        """
        获取/创建 COS 客户端（延迟初始化）
        使用标准 urllib3，无需额外依赖
        """
        if self._client is not None:
            return self._client

        try:
            from qcloud_cos import CosConfig, CosS3Client
        except ImportError:
            raise CloudError(
                "腾讯云 COS SDK 未安装。\n"
                "请运行：pip install cos-python-sdk-v5\n"
                "文档：https://cloud.tencent.com/document/product/436/65763"
            )

        config = CosConfig(
            Region=self.region,
            SecretId=self.secret_id,
            SecretKey=self.secret_key,
            Endpoint=self.endpoint_suffix,
            Token="",  # 暂不支持 STS 临时凭证
        )
        self._client = CosS3Client(config)
        return self._client

    # ─── 核心接口实现 ────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        """
        测试连通性（HEAD Bucket）
        权限：ListBucket
        """
        if not self.secret_id or not self.secret_key:
            return False, "SecretId 或 SecretKey 未配置"
        if not self.bucket:
            return False, "Bucket 名称未配置"

        try:
            client = self._get_client()
            client.head_bucket(Bucket=self.bucket)
            return True, f"连接成功：{self.bucket} ({self.region})"
        except Exception as e:
            err_msg = str(e)
            if "NoSuchBucket" in err_msg:
                return False, f"Bucket 不存在：{self.bucket}"
            if "AccessDenied" in err_msg:
                return False, "凭证权限不足，请检查 CAM 策略"
            if "AuthFailure" in err_msg:
                return False, "SecretId/SecretKey 无效"
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
        if not self.secret_id:
            return CloudUploadResult(
                success=False,
                object_key="",
                error="SecretId 未配置",
            )

        object_key = self.vault_path(user_id, version)
        data = self.serialize_vault(vault_data)
        data_len = len(data)

        if data_len > self.MAX_FILE_SIZE:
            return CloudUploadResult(
                success=False,
                object_key=object_key,
                error=f"文件过大（{data_len} bytes > {self.MAX_FILE_SIZE}）",
            )

        extra_headers = {
            "Content-Type": "application/json; charset=utf-8",
            "x-cos-storage-class": self.storage_class,
        }

        # 自定义元数据（服务端不透传）
        if metadata:
            meta_headers = {
                f"x-cos-meta-{k}": str(v)
                for k, v in metadata.items()
                if k in ("version", "note", "timestamp", "platform")
            }
            extra_headers.update(meta_headers)

        try:
            client = self._get_client()
            response = client.put_object(
                Bucket=self.bucket,
                Body=data,
                Key=object_key,
                Headers=extra_headers,
            )

            version_id = response.get("x-cos-version-id", "")
            etag = response.get("ETag", "").strip('"')

            # 生成下载 URL
            download_url = self.generate_download_url(user_id, version)

            return CloudUploadResult(
                success=True,
                object_key=object_key,
                version_id=version_id or str(version),
                size_bytes=data_len,
                url=download_url,
            )

        except Exception as e:
            return CloudUploadResult(
                success=False,
                object_key=object_key,
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
            response = client.get_object(
                Bucket=self.bucket,
                Key=object_key,
            )
            data = response["Body"].get_raw_content().read()
            return self.deserialize_vault(data)
        except Exception as e:
            err_msg = str(e)
            if "NoSuchKey" in err_msg or "NoSuchVersion" in err_msg:
                return None  # 版本不存在，正常情况
            raise CloudNetworkError(f"下载失败：{err_msg}")

    def list_versions(
        self,
        user_id: str,
        limit: int = 50,
    ) -> list[CloudFileInfo]:
        """
        列出用户所有 vault 版本（ListObjects + 前缀匹配）
        权限：ListBucket + GetObject
        """
        prefix = f"nueronote/{user_id}/vault/"

        try:
            client = self._get_client()
            response = client.list_objects(
                Bucket=self.bucket,
                Prefix=prefix,
                MaxKeys=limit,
            )

            files = []
            for obj in response.get("Contents", []):
                key = obj["Key"]
                # 只取 .enc.json 文件
                if not key.endswith(".enc.json"):
                    continue
                # 从文件名提取版本号
                try:
                    ver = int(key.split("/v")[-1].replace(".enc.json", ""))
                except ValueError:
                    ver = 0

                files.append(CloudFileInfo(
                    object_key=key,
                    size_bytes=int(obj.get("Size", 0)),
                    last_modified=int(obj["LastModified"].timestamp()
                                     if hasattr(obj["LastModified"], "timestamp")
                                     else time.time()),
                    etag=obj.get("ETag", "").strip('"'),
                    url=self.generate_download_url(user_id, ver),
                ))

            # 按版本倒序
            files.sort(key=lambda f: f.object_key, reverse=True)
            return files[:limit]

        except Exception as e:
            raise CloudNetworkError(f"列表查询失败：{str(e)}")

    def delete_vault(self, user_id: str, version: int) -> bool:
        """删除指定 vault 版本"""
        object_key = self.vault_path(user_id, version)
        try:
            client = self._get_client()
            client.delete_object(Bucket=self.bucket, Key=object_key)
            return True
        except Exception as e:
            return False

    def generate_download_url(
        self,
        user_id: str,
        version: int,
        expires_seconds: int = 3600,
    ) -> str:
        """
        生成预签名下载 URL（1小时后过期）
        腾讯云 COS 签名算法：HMAC-SHA1
        """
        object_key = self.vault_path(user_id, version)
        if expires_seconds <= 0:
            # 公开读 bucket，不需要签名
            return f"https://{self.bucket}.{self.endpoint_suffix}/{object_key}"

        # 手动生成签名 URL（避免引入额外依赖）
        import urllib.parse
        now = int(time.time())
        exp = now + expires_seconds

        # 签名串格式：a=[method]&b=[host]&c=[path]&d=[expire]
        sign_str = f"GET\n{self.bucket}.{self.endpoint_suffix}\n/{object_key}\n{exp}"

        sign = hmac.new(
            self.secret_key.encode(),
            sign_str.encode(),
            hashlib.sha1
        ).digest().hex()

        # q-sign-algorithm: sha1（腾讯云固定）
        params = urllib.parse.urlencode({
            "q-sign-algorithm": "sha1",
            "q-ak": self.secret_id,
            "q-sign-time": f"{now};{exp}",
            "q-key-time": f"{now};{exp}",
            "q-signature": sign,
        })

        return f"https://{self.bucket}.{self.endpoint_suffix}/{object_key}?{params}"

    def get_storage_usage(self) -> tuple[int, int]:
        """
        获取存储用量（ListObjects 遍历统计）
        腾讯云 COS 控制台可直接查看，此处遍历前缀统计
        """
        prefix = f"nueronote/"
        total_bytes = 0
        marker = ""
        max_iterations = 100  # 最多100次迭代（防止无限循环）

        try:
            client = self._get_client()
            for _ in range(max_iterations):
                if marker:
                    response = client.list_objects(
                        Bucket=self.bucket, Prefix=prefix, Marker=marker, MaxKeys=1000
                    )
                else:
                    response = client.list_objects(
                        Bucket=self.bucket, Prefix=prefix, MaxKeys=1000
                    )

                for obj in response.get("Contents", []):
                    total_bytes += int(obj.get("Size", 0))

                if response.get("IsTruncated"):
                    marker = response.get("NextMarker", "")
                else:
                    break

            return total_bytes, 0  # 配额从账户层面管理，无单 bucket 限制

        except Exception:
            return 0, 0

    # ─── 便捷方法 ────────────────────────────────────────────────

    @classmethod
    def required_config_fields(cls) -> list[tuple[str, str, str]]:
        """
        返回需要的配置字段说明
        (字段名, 说明, 默认值)
        """
        return [
            ("secret_id",     "SecretId（从 CAM 控制台获取）",                  ""),
            ("secret_key",    "SecretKey（从 CAM 控制台获取，勿泄露）",          ""),
            ("region",        "地域（如 ap-guangzhou）",                        "ap-guangzhou"),
            ("bucket",        "存储桶名称（不含 .cos. 前缀）",                  ""),
            ("storage_class", "存储类型：STANDARD | STANDARD_IA | ARCHIVE",    "STANDARD"),
        ]

    def __repr__(self):
        return (
            f"<TencentCOSStorage bucket={self.bucket} "
            f"region={self.region} enabled={self.config.enabled}>"
        )


# 必须 import os（在类外部）
import os
