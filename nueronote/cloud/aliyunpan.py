# -*- coding: utf-8 -*-
"""
阿里云盘（Aliyunpan）适配器

阿里云盘是阿里巴巴推出的个人云盘服务，提供大容量云存储。

官方文档：https://help.aliyun.com/zh/pds/drive-and-photo-service-dev/
OpenAPI门户：https://next.api.aliyun.com/product/pds

认证方式：OAuth 2.0（授权码模式）
- client_id:     应用 App ID
- client_secret: 应用 Secret Key
- access_token:  用户授权后的访问令牌
- refresh_token: 刷新令牌

OAuth2 端点：
- 授权URL: https://auth.aliyun.com/oauth2/authorize
- Token URL: https://oauth.aliyun.com/v1/token

API Base: https://api.aliyunpds.com

文件上传流程（分片上传）：
1. POST /v2/file/create - 创建文件，获取 file_id 和 upload_id
2. POST /v2/file/get_upload_url - 获取上传地址
3. 上传到 OSS
4. POST /v2/file/complete - 完成上传

申请地址：https://help.aliyun.com/zh/pds/drive-and-photo-service-dev/developer-reference/authorize-oauth2

费用：
- 阿里云盘会员：具体费用见官方
"""

from __future__ import annotations

import io
import json
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
# 阿里云盘 API 配置
# ============================================================================

# OAuth2 端点
ALIYUN_OAUTH_URL = "https://auth.aliyun.com/oauth2/authorize"
ALIYUN_TOKEN_URL = "https://oauth.aliyun.com/v1/token"

# API Base URL
ALIYUN_API_BASE = "https://api.aliyunpds.com"

# 内部 API（用于上传）
ALIYUN_DATA_API = "https://api.aliyunpds.com"


class AliyunpanStorage(BaseCloudStorage):
    """
    阿里云盘适配器

    配置项（extra 字段）：
    - client_id:       应用 App ID（从阿里云开放平台获取）
    - client_secret:   应用 Secret Key
    - access_token:    OAuth2 访问令牌（自动管理刷新）
    - refresh_token:   OAuth2 刷新令牌
    - drive_id:        用户云盘 ID（自动获取，可手动指定）
    - root_folder_id:  根目录 Folder ID（自动获取）

    申请步骤：
    1. 访问 https://help.aliyun.com/zh/pds/drive-and-photo-service-dev/
    2. 注册开发者账号并创建应用
    3. 获取 Client ID 和 Client Secret
    4. 通过 OAuth2 授权获取 token

    注意事项：
    1. access_token 有效期约 2 小时，需用 refresh_token 刷新
    2. refresh_token 有效期约 30 天
    3. 上传文件需通过分片上传流程
    4. 大文件建议分片上传（每片建议 10MB）
    """

    PROVIDER_NAME = "aliyunpan"
    PROVIDER_DISPLAY = "阿里云盘"

    # API 限流（无明确限制，但建议控制频率）
    REQUEST_COOLDOWN = 0.1  # 秒

    # 分片大小（10MB）
    CHUNK_SIZE = 10 * 1024 * 1024

    def __init__(self, config: CloudConfig):
        super().__init__(config)
        self._extra = config.extra or {}
        self._last_request = 0.0
        self._session = requests.Session()

        self.client_id = self._extra.get("client_id", "")
        self.client_secret = self._extra.get("client_secret", "")

        # 令牌（支持自动刷新）
        self._access_token = self._extra.get("access_token", "")
        self._refresh_token = self._extra.get("refresh_token", "")
        self._token_expires_at = self._extra.get("token_expires_at", 0)

        # Drive 信息
        self._drive_id = self._extra.get("drive_id", "")
        self._root_folder_id = self._extra.get("root_folder_id", "")

        # 用户信息缓存
        self._user_id = self._extra.get("user_id", "")

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
        """检查令牌是否过期（提前 5 分钟刷新）"""
        return time.time() > (self._token_expires_at - 300)

    def _refresh_access_token(self) -> bool:
        """
        刷新 access_token
        """
        if not self._refresh_token:
            return False

        try:
            resp = requests.post(
                ALIYUN_TOKEN_URL,
                timeout=10,
                data={
                    "grant_type":    "refresh_token",
                    "refresh_token": self._refresh_token,
                    "client_id":     self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if resp.status_code != 200:
                return False

            data = resp.json()
            if "access_token" not in data:
                return False

            self._access_token = data["access_token"]
            self._refresh_token = data.get("refresh_token", self._refresh_token)
            expires_in = data.get("expires_in", 7200)

            self._token_expires_at = time.time() + expires_in

            # 保存到配置
            self._extra["access_token"] = self._access_token
            self._extra["refresh_token"] = self._refresh_token
            self._extra["token_expires_at"] = self._token_expires_at
            self.config.extra = self._extra

            return True

        except Exception:
            return False

    def _rate_limit(self):
        """简单限速"""
        elapsed = time.time() - self._last_request
        if elapsed < self.REQUEST_COOLDOWN:
            time.sleep(self.REQUEST_COOLDOWN - elapsed)
        self._last_request = time.time()

    def _api_call(
        self,
        method: str,
        path: str,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        stream: bool = False,
    ) -> requests.Response:
        """
        统一的 API 调用（含认证、限速、错误处理）
        """
        if not self._ensure_token():
            raise CloudAuthError("无效的访问令牌，请重新授权")

        self._rate_limit()

        url = f"{ALIYUN_API_BASE}{path}"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        resp = self._session.request(
            method=method,
            url=url,
            params=params,
            json=data,
            headers=headers,
            timeout=30,
            stream=stream,
        )

        if resp.status_code == 401:
            # Token 失效，尝试刷新
            if self._refresh_access_token():
                headers["Authorization"] = f"Bearer {self._access_token}"
                resp = self._session.request(
                    method=method, url=url, params=params,
                    json=data, headers=headers, timeout=30, stream=stream,
                )

        return resp

    def _ensure_drive_info(self) -> bool:
        """
        确保获取到 drive_id 和 root_folder_id
        """
        if self._drive_id and self._root_folder_id:
            return True

        try:
            # 获取用户信息
            resp = self._api_call("POST", "/v2/user/get")
            result = resp.json()

            if result.get("code"):
                return False

            user_info = result.get("result", {})
            self._user_id = user_info.get("user_id", "")
            self._extra["user_id"] = self._user_id

            # 获取 drive 列表
            resp = self._api_call("POST", "/v2/drive/list")
            result = resp.json()

            drives = result.get("result", {}).get("drives", [])
            if not drives:
                return False

            # 默认使用第一个 drive（主云盘）
            drive = drives[0]
            self._drive_id = drive.get("drive_id", "")
            self._root_folder_id = drive.get("root_folder_id", "")

            self._extra["drive_id"] = self._drive_id
            self._extra["root_folder_id"] = self._root_folder_id
            self.config.extra = self._extra

            return True

        except Exception:
            return False

    # ─── 核心接口实现 ────────────────────────────────────────────

    def test_connection(self) -> tuple[bool, str]:
        """
        测试连通性（获取 drive 信息）
        """
        if not self.client_id or not self.client_secret:
            return False, "client_id 或 client_secret 未配置"

        if not self._access_token and not self._refresh_token:
            return False, (
                "尚未完成 OAuth2 授权。\n"
                "请先调用 get_oauth_url() 获取授权链接，\n"
                "然后用 receive_oauth_code(code) 完成授权。"
            )

        try:
            if not self._ensure_drive_info():
                return False, "无法获取云盘信息，可能授权已过期"

            resp = self._api_call("POST", "/v2/drive/list")
            result = resp.json()

            if result.get("code"):
                return False, f"API 错误：{result.get('message', result.get('code'))}"

            drives = result.get("result", {}).get("drives", [])
            if not drives:
                return False, "未找到可用的云盘"

            drive = drives[0]
            return True, (
                f"连接成功！\n"
                f"  云盘 ID：{drive.get('drive_id')}\n"
                f"  云盘名称：{drive.get('drive_name', '默认云盘')}\n"
                f"  总空间：{int(drive.get('total_size', 0)) / (1024**4):.2f} TB\n"
                f"  已使用：{int(drive.get('used_size', 0)) / (1024**4):.2f} TB"
            )

        except CloudAuthError as e:
            return False, f"授权失败：{str(e)}"
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
        上传加密 vault（阿里云盘分片上传）
        路径格式：nueronote/{user_id}/v{version}.enc.json
        """
        if not self._ensure_drive_info():
            return CloudUploadResult(
                success=False, object_key="",
                error="无法获取云盘信息，请检查授权",
            )

        object_key = self.vault_path(user_id, version)
        data = self.serialize_vault(vault_data)
        data_len = len(data)

        try:
            # 文件名（从路径提取）
            file_name = f"v{version}.enc.json"
            parent_path = f"nueronote/{user_id}"

            # 1. 创建文件（初始化上传）
            create_resp = self._api_call("POST", "/v2/file/create", data={
                "drive_id":      self._drive_id,
                "parent_file_id": self._root_folder_id,
                "name":          file_name,
                "type":          "file",
                "check_name_mode": "overwrite",
                "size":          data_len,
            })

            create_result = create_resp.json()
            if create_result.get("code"):
                return CloudUploadResult(
                    success=False, object_key=object_key,
                    error=f"创建文件失败：{create_result.get('message', create_result.get('code'))}",
                )

            file_info = create_result.get("result", {})
            file_id = file_info.get("file_id", "")
            upload_id = file_info.get("upload_id", "")

            if not file_id or not upload_id:
                return CloudUploadResult(
                    success=False, object_key=object_key,
                    error="创建文件未返回有效 file_id 或 upload_id",
                )

            # 2. 分片上传
            part_number = 1
            part_info_list = []
            offset = 0

            while offset < data_len:
                chunk_size = min(self.CHUNK_SIZE, data_len - offset)
                chunk_data = data[offset:offset + chunk_size]

                # 获取上传地址
                upload_url_resp = self._api_call("POST", "/v2/file/get_upload_url", data={
                    "drive_id":    self._drive_id,
                    "file_id":     file_id,
                    "upload_id":   upload_id,
                    "part_info_list": [{
                        "part_number": part_number,
                    }],
                })

                upload_url_result = upload_url_resp.json()
                part_list = upload_url_result.get("result", {}).get("part_info_list", [])
                
                if not part_list:
                    return CloudUploadResult(
                        success=False, object_key=object_key,
                        error=f"获取上传地址失败（第 {part_number} 片）",
                    )

                upload_url_info = part_list[0]
                upload_url = upload_url_info.get("upload_url", "")

                if not upload_url:
                    return CloudUploadResult(
                        success=False, object_key=object_key,
                        error=f"上传地址为空（第 {part_number} 片）",
                    )

                # 上传到 OSS
                put_resp = requests.put(
                    upload_url,
                    data=chunk_data,
                    timeout=60,
                    headers={"Content-Type": "application/octet-stream"},
                )

                if put_resp.status_code not in (200, 201):
                    return CloudUploadResult(
                        success=False, object_key=object_key,
                        error=f"上传失败（第 {part_number} 片），HTTP {put_resp.status_code}",
                    )

                # 记录 ETag
                etag = put_resp.headers.get("ETag", "").strip('"')
                part_info_list.append({
                    "part_number": part_number,
                    "etag":        etag,
                })

                offset += chunk_size
                part_number += 1

            # 3. 完成上传
            complete_resp = self._api_call("POST", "/v2/file/complete", data={
                "drive_id":      self._drive_id,
                "file_id":       file_id,
                "upload_id":     upload_id,
                "part_info_list": part_info_list,
            })

            complete_result = complete_resp.json()
            if complete_result.get("code"):
                return CloudUploadResult(
                    success=False, object_key=object_key,
                    error=f"完成上传失败：{complete_result.get('message', complete_result.get('code'))}",
                )

            return CloudUploadResult(
                success=True,
                object_key=object_key,
                version_id=str(version),
                size_bytes=data_len,
                url=self.generate_download_url(user_id, version),
            )

        except CloudAuthError as e:
            return CloudUploadResult(
                success=False, object_key=object_key,
                error=f"授权失败：{str(e)}",
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
        下载加密 vault
        """
        if not self._ensure_drive_info():
            raise CloudAuthError("无法获取云盘信息，请检查授权")

        object_key = self.vault_path(user_id, version)

        try:
            # 获取文件信息
            resp = self._api_call("POST", "/v2/file/get", data={
                "drive_id": self._drive_id,
                "file_id":  object_key,  # 阿里云盘可以用路径作为 file_id
            })

            result = resp.json()
            if result.get("code"):
                # 文件可能不存在
                if "not_found" in str(result.get("code", "")).lower():
                    return None
                raise CloudError(f"获取文件失败：{result.get('message')}")

            file_info = result.get("result", {})
            download_url = file_info.get("download_url", "")

            if not download_url:
                raise CloudError("文件下载链接为空")

            # 下载文件内容
            content_resp = requests.get(download_url, timeout=60)
            if content_resp.status_code != 200:
                raise CloudNetworkError(f"下载失败，HTTP {content_resp.status_code}")

            return self.deserialize_vault(content_resp.content)

        except CloudAuthError:
            raise
        except Exception as e:
            raise CloudNetworkError(f"下载失败：{str(e)}")

    def list_versions(
        self,
        user_id: str,
        limit: int = 50,
    ) -> list[CloudFileInfo]:
        """
        列出用户所有 vault 版本
        """
        if not self._ensure_drive_info():
            raise CloudAuthError("无法获取云盘信息，请检查授权")

        parent_path = f"nueronote/{user_id}"

        try:
            # 先搜索目录
            resp = self._api_call("POST", "/v2/file/search", data={
                "drive_id":      self._drive_id,
                "query":         f"parent_file_id = '{self._root_folder_id}' and name = '{user_id}'",
                "order_by":      "updated_at",
                "order_direction": "DESC",
                "limit":         100,
            })

            result = resp.json()
            folder_id = self._root_folder_id

            # 如果没有找到用户目录，使用根目录
            items = result.get("result", {}).get("items", [])
            for item in items:
                if item.get("name") == user_id and item.get("type") == "folder":
                    folder_id = item.get("file_id", self._root_folder_id)
                    break

            # 列出 vault 文件
            resp = self._api_call("POST", "/v2/file/list", data={
                "drive_id":      self._drive_id,
                "parent_file_id": folder_id,
                "order_by":      "updated_at",
                "order_direction": "DESC",
                "limit":         limit,
            })

            result = resp.json()
            files = []

            for obj in result.get("result", {}).get("items", []):
                if not obj.get("name", "").endswith(".enc.json"):
                    continue

                try:
                    ver = int(obj["name"].replace(".enc.json", "").replace("v", ""))
                except ValueError:
                    continue

                files.append(CloudFileInfo(
                    object_key=obj.get("file_path", obj.get("name", "")),
                    size_bytes=int(obj.get("size", 0)),
                    last_modified=int(
                        time.mktime(
                            time.strptime(
                                obj.get("updated_at", "1970-01-01T00:00:00Z"),
                                "%Y-%m-%dT%H:%M:%SZ"
                            )
                        )
                    ),
                    etag=str(obj.get("file_id", "")),
                    url=self.generate_download_url(user_id, ver),
                ))

            return sorted(files, key=lambda f: f.last_modified, reverse=True)

        except CloudAuthError:
            raise
        except Exception as e:
            raise CloudNetworkError(f"列表查询失败：{str(e)}")

    def delete_vault(self, user_id: str, version: int) -> bool:
        """删除指定 vault 版本"""
        if not self._ensure_drive_info():
            return False

        try:
            # 搜索文件
            file_name = f"v{version}.enc.json"
            resp = self._api_call("POST", "/v2/file/search", data={
                "drive_id": self._drive_id,
                "query":    f"parent_file_id = '{self._root_folder_id}' and name = '{file_name}'",
                "limit":    1,
            })

            result = resp.json()
            items = result.get("result", {}).get("items", [])
            
            if not items:
                return False

            file_id = items[0].get("file_id")
            if not file_id:
                return False

            # 删除文件
            resp = self._api_call("POST", "/v2/file/delete", data={
                "drive_id": self._drive_id,
                "file_id":  file_id,
            })

            return not resp.json().get("code")

        except Exception:
            return False

    def generate_download_url(
        self,
        user_id: str,
        version: int,
        expires_seconds: int = 3600,
    ) -> str:
        """
        生成临时下载 URL
        """
        if not self._ensure_drive_info():
            return ""

        try:
            file_name = f"v{version}.enc.json"
            resp = self._api_call("POST", "/v2/file/search", data={
                "drive_id": self._drive_id,
                "query":    f"parent_file_id = '{self._root_folder_id}' and name = '{file_name}'",
                "limit":    1,
            })

            result = resp.json()
            items = result.get("result", {}).get("items", [])
            
            if items:
                return items[0].get("download_url", "")

        except Exception:
            pass

        return ""

    def get_storage_usage(self) -> tuple[int, int]:
        """获取存储用量"""
        if not self._ensure_drive_info():
            return 0, 0

        try:
            resp = self._api_call("POST", "/v2/drive/get", data={
                "drive_id": self._drive_id,
            })

            result = resp.json()
            drive = result.get("result", {})

            used = int(drive.get("used_size", 0))
            total = int(drive.get("total_size", 0))
            return used, total

        except Exception:
            return 0, 0

    # ─── OAuth2 授权流程 ─────────────────────────────────────────

    def get_oauth_url(self, redirect_uri: str, state: str = "") -> str:
        """
        获取阿里云盘 OAuth2 授权 URL

        Args:
            redirect_uri: 授权回调地址（需在阿里云开放平台注册）
            state: 随机状态字符串（防 CSRF）

        Returns:
            授权跳转 URL
        """
        import urllib.parse
        params = {
            "client_id":     self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope":         "user:base,file:all",
            "state":         state or "nueronote_oauth",
        }
        return f"{ALIYUN_OAUTH_URL}?{urllib.parse.urlencode(params)}"

    def receive_oauth_code(self, code: str) -> bool:
        """
        用授权码换取 access_token

        Args:
            code: 授权码（一次性）

        Returns:
            是否授权成功（成功后 token 自动保存到 extra）
        """
        try:
            resp = requests.post(
                ALIYUN_TOKEN_URL,
                timeout=10,
                data={
                    "grant_type":    "authorization_code",
                    "code":          code,
                    "client_id":     self.client_id,
                    "client_secret": self.client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

            if resp.status_code != 200:
                return False

            data = resp.json()
            if "access_token" not in data:
                return False

            self._access_token = data["access_token"]
            self._refresh_token = data.get("refresh_token", "")
            expires_in = data.get("expires_in", 7200)
            self._token_expires_at = time.time() + expires_in

            self._extra.update({
                "access_token":     self._access_token,
                "refresh_token":     self._refresh_token,
                "token_expires_at":  self._token_expires_at,
            })
            self.config.extra = self._extra

            return True

        except Exception:
            return False

    # ─── 内部方法 ───────────────────────────────────────────────

    def vault_path(self, user_id: str, version: int) -> str:
        """生成 vault 对象路径"""
        return f"nueronote/{user_id}/v{version}.enc.json"

    def vault_metadata_path(self, user_id: str, version: int) -> str:
        """元数据文件路径"""
        return f"nueronote/{user_id}/v{version}.meta.json"

    @classmethod
    def required_config_fields(cls) -> list[tuple[str, str, str]]:
        return [
            ("client_id",     "App ID（从阿里云开放平台获取）",                    ""),
            ("client_secret", "Secret Key（从阿里云开放平台获取，勿泄露）",         ""),
            ("access_token",  "access_token（授权后自动填充）",                    ""),
            ("refresh_token", "refresh_token（授权后自动填充）",                   ""),
            ("drive_id",      "云盘 ID（授权后自动获取）",                          ""),
        ]

    def __repr__(self):
        return (
            f"<AliyunpanStorage drive={self._drive_id[:8]}... "
            f"token={'OK' if self._access_token else 'MISSING'}>"
        )
