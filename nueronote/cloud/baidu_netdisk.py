# -*- coding: utf-8 -*-
"""
百度网盘（个人云）适配器

百度网盘是国内用户量最大的个人云盘，拥有超过 7 亿用户。
特点：OAuth2 授权、S2 云收藏、个人文件管理

官方文档：https://pan.baidu.com/union/
OAuth2 授权：https://openapi.baidu.com/oauth/
Python SDK：pip install baidupcs-python

认证方式：OAuth2（用户授权码模式）
- client_id:     应用 App Key
- client_secret: 应用 Secret Key
- access_token: 用户授权后的访问令牌（有效期 30 天）
- refresh_token: 刷新令牌（有效期 30 天）

注意：百度网盘 API 对个人开发者有较多限制，
主要支持文件管理操作，上传单个文件建议 < 2GB。
"""

from __future__ import annotations

import json
import os
import time
import requests
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
# 百度网盘 OAuth2 配置
# ============================================================================

BAIDU_OAUTH_URL = "https://openapi.baidu.com/oauth/2.0/token"
BAIDU_PCS_URL = "https://pan.baidu.com/rest/2.0/pcs"
BAIDU_PCS_QUOTA = "https://pan.baidu.com/api/quota"
BAIDU_PCS_FILE = "https://pan.baidu.com/rest/2.0/pcs/file"


class BaiduNetdiskStorage(BaseCloudStorage):
    """
    百度网盘适配器

    配置项（extra 字段）：
    - client_id:      应用 App Key（从百度开放平台获取）
    - client_secret:  应用 Secret Key
    - access_token:   OAuth2 访问令牌（自动管理刷新）
    - refresh_token:  OAuth2 刷新令牌
    - app_folder:     应用专属目录名（默认 "NueroNote"）

    百度网盘 OAuth2 权限范围：
    - basic           读取用户基本信息
    - netdisk         读写用户网盘文件（需要用户授权）

    申请地址：https://pan.baidu.com/union/
    文档：https://pan.baidu.com/union/document

    费用：
    - 百度网盘超级会员：30元/月
    - 普通用户存储空间有限，超出需购买会员

    注意事项：
    1. access_token 有效期 30 天，需自动刷新
    2. 百度 API 对请求频率有限制（约 1000次/天）
    3. 单次上传建议 < 500MB（可分段）
    4. 非会员下载可能限速
    """

    PROVIDER_NAME = "baidu_netdisk"
    PROVIDER_DISPLAY = "百度网盘"

    # 百度 API 限流
    MAX_REQUESTS_PER_DAY = 1000
    REQUEST_COOLDOWN = 0.2  # 秒

    def __init__(self, config: CloudConfig):
        super().__init__(config)
        self._extra = config.extra or {}
        self._last_request = 0.0
        self._session = requests.Session()

        self.client_id = self._extra.get("client_id", "")
        self.client_secret = self._extra.get("client_secret", "")
        self.app_folder = self._extra.get("app_folder", "NueroNote")

        # 令牌（支持自动刷新）
        self._access_token = self._extra.get("access_token", "")
        self._refresh_token = self._extra.get("refresh_token", "")

        # 本地存储路径（百度网盘以 /apps/<appname>/ 为前缀）
        self.remote_prefix = f"/apps/{self.app_folder}"

    # ─── OAuth2 令牌管理 ─────────────────────────────────────────

    def _ensure_token(self) -> bool:
        """
        确保 access_token 有效，必要时自动刷新
        返回：是否可用
        """
        if self._access_token and not self._is_token_expired():
            return True

        if not self._refresh_token:
            return False

        return self._refresh_access_token()

    def _is_token_expired(self) -> bool:
        """检查令牌是否过期（简单检查：有效期 1 天内）"""
        expires_at = self._extra.get("token_expires_at", 0)
        return time.time() > (expires_at - 86400)  # 提前1天刷新

    def _refresh_access_token(self) -> bool:
        """
        刷新 access_token
        百度网盘 access_token 有效期 30 天，refresh_token 有效期也是 30 天
        """
        if not self._refresh_token:
            return False

        try:
            resp = requests.post(BAIDU_OAUTH_URL, timeout=10, params={
                "grant_type":    "refresh_token",
                "refresh_token": self._refresh_token,
                "client_id":     self.client_id,
                "client_secret": self.client_secret,
            })

            if resp.status_code != 200:
                return False

            data = resp.json()
            if "access_token" not in data:
                return False

            self._access_token = data["access_token"]
            self._refresh_token = data.get("refresh_token", self._refresh_token)

            # 保存到配置（供外部持久化）
            self._extra["access_token"] = self._access_token
            self._extra["refresh_token"] = self._refresh_token
            self._extra["token_expires_at"] = time.time() + int(data.get("expires_in", 2592000))
            self.config.extra = self._extra

            return True

        except Exception:
            return False

    def _rate_limit(self):
        """简单限速（避免触发 API 限流）"""
        elapsed = time.time() - self._last_request
        if elapsed < self.REQUEST_COOLDOWN:
            time.sleep(self.REQUEST_COOLDOWN - elapsed)
        self._last_request = time.time()

    def _api_call(
        self,
        method: str,
        url: str,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        files: Optional[dict] = None,
        stream: bool = False,
    ) -> requests.Response:
        """
        统一的 API 调用（含认证、限速、错误处理）
        """
        self._ensure_token()

        headers = {}
        if self._access_token:
            params = dict(params or {})
            params["access_token"] = self._access_token

        self._rate_limit()

        resp = self._session.request(
            method=method,
            url=url,
            params=params,
            data=data,
            files=files,
            headers=headers,
            timeout=30,
            stream=stream,
        )

        if resp.status_code == 401:
            # Token 失效，尝试刷新
            if self._refresh_access_token():
                params["access_token"] = self._access_token
                resp = self._session.request(
                    method=method, url=url, params=params,
                    data=data, files=files, headers=headers, timeout=30, stream=stream,
                )

        return resp

    # ─── 核心接口实现 ────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        """
        测试连通性（查询配额）
        权限：netdisk
        """
        if not self.client_id or not self.client_secret:
            return False, "client_id 或 client_secret 未配置"

        # 检查是否已有有效令牌
        if not self._access_token and not self._refresh_token:
            return False, (
                "尚未完成 OAuth2 授权。\n"
                "请先调用 get_oauth_url() 获取授权链接，\n"
                "然后用 receive_oauth_code(code) 完成授权。"
            )

        try:
            resp = self._api_call("GET", BAIDU_PCS_QUOTA, params={"method": "query"})
            result = resp.json()

            if result.get("errno") == 0:
                quota = result.get("quota", 0)
                used = result.get("used", 0)
                return True, (
                    f"连接成功！\n"
                    f"  总空间：{quota / (1024**3):.2f} GB\n"
                    f"  已使用：{used / (1024**3):.2f} GB"
                )

            err = result.get("errno", -1)
            if err == 31061:  # access_token 过期
                return False, "access_token 已过期，请重新授权"
            if err == 6:  # No permission
                return False, "应用权限不足，请检查 OAuth 授权范围"

            return False, f"API 错误码：{err}"

        except Exception as e:
            return False, f"连接失败：{str(e)}"

    def upload_vault(
        self,
        vault_data: dict,
        user_id: str,
        version: int,
        metadata: Optional[dict] = None,
    ) -> CloudUploadResult:
        """
        上传加密 vault（百度 PCS 文件上传 API）
        路径格式：/apps/NueroNote/vault/{user_id}/v{version}.enc.json

        百度网盘上传接口：POST /rest/2.0/pcs/file
        文件名不能含特殊字符
        """
        object_key = self._remote_path(user_id, version)
        data = self.serialize_vault(vault_data)
        data_len = len(data)

        # 百度限制单文件上传大小（约 2GB，会员更高）
        MAX_UPLOAD = 500 * 1024 * 1024  # 500MB 安全阈值
        if data_len > MAX_UPLOAD:
            return CloudUploadResult(
                success=False, object_key=object_key,
                error=f"文件过大（{data_len} bytes > {MAX_UPLOAD}）",
            )

        # 确保目标目录存在
        self._ensure_folder_exists(user_id)

        try:
            resp = self._api_call(
                "POST",
                BAIDU_PCS_FILE,
                params={"method": "create", "type": "excel"},
                data={
                    "file": (
                        f"v{version}.enc.json",
                        data,
                        "application/json; charset=utf-8",
                    )
                },
                files=None,
            )

            # 注意：百度 PCS API 用 form-data 上传
            # 重新构造
            import io
            resp = self._session.post(
                f"{BAIDU_PCS_FILE}?method=create&access_token={self._access_token}&type=file",
                files={
                    "file": (
                        f"v{version}.enc.json",
                        io.BytesIO(data),
                        "application/json; charset=utf-8",
                    )
                },
                timeout=60,
                stream=False,
            )

            result = resp.json()

            if result.get("errno") == 0:
                file_info = result.get("file_list", [{}])[0]
                return CloudUploadResult(
                    success=True,
                    object_key=object_key,
                    version_id=str(version),
                    size_bytes=data_len,
                    url=self.generate_download_url(user_id, version),
                )
            else:
                err = result.get("errno", -1)
                if err == 31061:
                    return CloudUploadResult(
                        success=False, object_key=object_key,
                        error="access_token 过期或无效，请重新授权",
                    )
                return CloudUploadResult(
                    success=False, object_key=object_key,
                    error=f"上传失败，错误码：{err}",
                )

        except Exception as e:
            return CloudUploadResult(
                success=False, object_key=object_key,
                error=f"上传异常：{str(e)}",
            )

    def download_vault(
        self,
        user_id: str,
        version: int,
    ) -> Optional[dict]:
        """
        下载加密 vault（百度 PCS 文件下载 API）
        """
        object_key = self._remote_path(user_id, version)

        try:
            # 先获取下载链接
            resp = self._api_call(
                "GET",
                BAIDU_PCS_FILE,
                params={
                    "method": "download",
                    "path": object_key,
                },
            )

            if resp.status_code == 404 or (
                resp.headers.get("Content-Type", "").startswith("application/json")
                and b'"errno"' in resp.content
            ):
                return None  # 文件不存在

            return self.deserialize_vault(resp.content)

        except Exception as e:
            raise CloudNetworkError(f"下载失败：{str(e)}")

    def list_versions(
        self,
        user_id: str,
        limit: int = 50,
    ) -> list[CloudFileInfo]:
        """
        列出用户所有 vault 版本（百度 list API）
        """
        prefix = self._remote_path(user_id, "*").replace(f"*{version}", "*").rsplit("/", 1)[0] + "/"
        prefix = f"{self.remote_prefix}/vault/{user_id}/"

        try:
            resp = self._api_call(
                "GET",
                BAIDU_PCS_FILE,
                params={
                    "method": "list",
                    "path": prefix,
                    "by": "name",
                    "order": "desc",
                    "limit": limit,
                },
            )
            result = resp.json()

            files = []
            for obj in result.get("list", []):
                if not obj.get("filename", "").endswith(".enc.json"):
                    continue
                try:
                    ver = int(
                        obj["server_filename"]
                        .replace(".enc.json", "")
                        .replace("v", "")
                    )
                except ValueError:
                    ver = 0

                files.append(CloudFileInfo(
                    object_key=obj["path"],
                    size_bytes=int(obj.get("size", 0)),
                    last_modified=int(obj.get("mtime", 0)),
                    etag=str(obj.get("md5", "")),
                    url=self.generate_download_url(user_id, ver),
                ))

            return sorted(files, key=lambda f: f.last_modified, reverse=True)[:limit]

        except Exception as e:
            raise CloudNetworkError(f"列表查询失败：{str(e)}")

    def delete_vault(self, user_id: str, version: int) -> bool:
        """删除指定 vault 版本"""
        object_key = self._remote_path(user_id, version)

        try:
            resp = self._api_call(
                "POST",
                BAIDU_PCS_FILE,
                params={"method": "delete"},
                data={"path": object_key},
            )
            result = resp.json()
            return result.get("errno") == 0
        except Exception:
            return False

    def generate_download_url(
        self,
        user_id: str,
        version: int,
        expires_seconds: int = 3600,
    ) -> str:
        """
        生成百度网盘分享链接（永久有效）
        或通过 API 获取临时下载地址

        百度网盘分享链接格式：https://pan.baidu.com/s/1xxxx
        """
        object_key = self._remote_path(user_id, version)

        try:
            resp = self._api_call(
                "GET",
                BAIDU_PCS_FILE,
                params={
                    "method": "download",
                    "path": object_key,
                },
            )
            # 返回真实下载地址（CDN URL，有时效性）
            if resp.status_code == 200:
                # 百度返回重定向，从 headers 取真实 URL
                return resp.headers.get("Location", resp.url)
        except Exception:
            pass

        return f"https://pan.baidu.com/union{object_key}"

    def get_storage_usage(self) -> tuple[int, int]:
        """获取存储用量"""
        try:
            resp = self._api_call("GET", BAIDU_PCS_QUOTA, params={"method": "query"})
            result = resp.json()
            if result.get("errno") == 0:
                return int(result.get("used", 0)), int(result.get("quota", 0))
        except Exception:
            pass
        return 0, 0

    # ─── OAuth2 授权流程 ─────────────────────────────────────────

    def get_oauth_url(self, redirect_uri: str, state: str = "") -> str:
        """
        获取百度 OAuth2 授权 URL

        Args:
            redirect_uri: 授权回调地址（需在百度开放平台注册）
            state: 随机状态字符串（防 CSRF）

        Returns:
            授权跳转 URL
        """
        import urllib.parse
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "scope": "basic netdisk",
            "state": state or "nueronote_oauth",
        }
        return f"{BAIDU_OAUTH_URL}?{urllib.parse.urlencode(params)}"

    def receive_oauth_code(self, code: str) -> bool:
        """
        用授权码换取 access_token

        Args:
            code: 百度返回的授权码（一次性）

        Returns:
            是否授权成功（成功后 token 自动保存到 extra）
        """
        try:
            resp = requests.post(BAIDU_OAUTH_URL, timeout=10, params={
                "grant_type":    "authorization_code",
                "code":           code,
                "client_id":      self.client_id,
                "client_secret":  self.client_secret,
                "redirect_uri":   "oob",  # 百度网盘通常用 oob 模式
            })

            if resp.status_code != 200:
                return False

            data = resp.json()
            if "access_token" not in data:
                return False

            self._access_token = data["access_token"]
            self._refresh_token = data.get("refresh_token", "")
            expires_in = int(data.get("expires_in", 2592000))

            self._extra.update({
                "access_token":      self._access_token,
                "refresh_token":      self._refresh_token,
                "token_expires_at":   time.time() + expires_in,
            })
            self.config.extra = self._extra

            return True

        except Exception:
            return False

    # ─── 内部方法 ───────────────────────────────────────────────

    def _remote_path(self, user_id: str, version: int) -> str:
        """生成百度网盘远程路径"""
        return f"{self.remote_prefix}/vault/{user_id}/v{version}.enc.json"

    def _ensure_folder_exists(self, user_id: str) -> bool:
        """确保用户 vault 目录存在（递归创建）"""
        path = f"{self.remote_prefix}/vault/{user_id}"
        try:
            resp = self._api_call(
                "POST",
                BAIDU_PCS_FILE,
                params={"method": "mkdir"},
                data={"path": path},
            )
            return resp.json().get("errno") in (0, -9)  # -9=已存在
        except Exception:
            return False

    @classmethod
    def required_config_fields(cls) -> list[tuple[str, str, str]]:
        return [
            ("client_id",     "App Key（从百度开放平台获取）",                    ""),
            ("client_secret",  "Secret Key（从百度开放平台获取，勿泄露）",         ""),
            ("access_token",   "access_token（授权后自动填充）",                   ""),
            ("refresh_token",  "refresh_token（授权后自动填充）",                 ""),
            ("app_folder",    "应用专属目录名（默认 NueroNote）",                  "NueroNote"),
        ]

    def __repr__(self):
        return (
            f"<BaiduNetdiskStorage folder={self.app_folder} "
            f"token={'OK' if self._access_token else 'MISSING'}>"
        )
