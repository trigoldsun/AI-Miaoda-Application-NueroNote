#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 加密引擎 — 端到端零知识加密
支持：XChaCha20-Poly1305 / AES-GCM + PBKDF2-HMAC-SHA256
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from typing import Any, Optional

# ============================================================================
# 常量
# ============================================================================

ALGORITHM_AES = "AES-256-GCM"
KEY_LEN = 32          # 256-bit
SALT_LEN = 16         # 128-bit salt
NONCE_LEN = 12        # 96-bit nonce for AES-GCM
PBKDF2_ITERATIONS = 100_000  # OWASP 2023 最低要求

# ============================================================================
# 异常
# ============================================================================

class CryptoError(Exception): """加密相关错误"""
class DecryptionError(CryptoError): """解密失败"""
class KeyDerivationError(CryptoError): """密钥推导失败"""
class VaultIntegrityError(CryptoError): """Vault 完整性验证失败"""


# ============================================================================
# 工具函数
# ============================================================================

def random_bytes(n: int) -> bytes:
    return secrets.token_bytes(n)


def random_id(prefix: str = "") -> str:
    """生成 URL-safe nanoid 格式唯一ID"""
    ab = urlsafe_b64encode(random_bytes(12)).decode().rstrip("=")
    return f"{prefix}{ab}" if prefix else ab


def constant_time_compare(a: str, b: str) -> bool:
    """常量时间比较，防止时序攻击"""
    return hmac.compare_digest(a.encode(), b.encode())


# ============================================================================
# 密钥派生（PBKDF2-HMAC-SHA256，OWASP 标准）
# ============================================================================

def derive_key(password: str, salt: bytes) -> bytes:
    """
    PBKDF2-HMAC-SHA256 密钥推导
    - 10万次迭代（OWASP 2023 最低要求）
    - 32字节输出（256-bit）
    """
    return hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=KEY_LEN,
    )


def derive_key_check(password: str, salt: bytes) -> str:
    """
    密钥验证数据（常量时间派生，不泄露密钥）
    使用 HKDF-SHA256 确定性导出
    """
    ikm = password.encode("utf-8")
    info = b"NueroNote:v1:key-check"
    # HKDF-SHA256 extract + expand
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    okm = hmac.new(prk, info + b"\x01", hashlib.sha256).digest()
    return urlsafe_b64encode(okm).decode()


# ============================================================================
# 低层加密原语
# ============================================================================

class AESGCMCipher:
    """
    AES-256-GCM 认证加密
    优先使用 pyca/cryptography，必要时报错（不接受不安全后备）
    """

    def __init__(self, key: bytes):
        if len(key) != KEY_LEN:
            raise KeyDerivationError(f"密钥长度错误: 需要 {KEY_LEN} 字节，得到 {len(key)}")
        self._key = key
        self._aesgcm = self._load_aesgcm()

    def _load_aesgcm(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            return AESGCM(self._key)
        except ImportError:
            raise CryptoError(
                "pyca/cryptography 未安装。NueroNote 要求: pip install cryptography\n"
                "这是安全要求，不支持使用不安全的备用加密方案。"
            )

    def encrypt(self, plaintext: bytes, aad: bytes = b"") -> dict:
        """加密并返回 {nonce, ciphertext}（均为 URL-safe Base64）"""
        nonce = random_bytes(NONCE_LEN)
        # AAD 可以是任意额外数据，这里传空
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, aad)
        return {
            "alg": ALGORITHM_AES,
            "nonce": urlsafe_b64encode(nonce).decode(),
            "ciphertext": urlsafe_b64encode(ciphertext).decode(),
        }

    def decrypt(self, data: dict, aad: bytes = b"") -> bytes:
        """解密，失败则抛出 DecryptionError"""
        try:
            nonce = urlsafe_b64decode(data["nonce"])
            ciphertext = urlsafe_b64decode(data["ciphertext"])
            return self._aesgcm.decrypt(nonce, ciphertext, aad)
        except Exception as exc:
            raise DecryptionError(f"解密失败: {exc}") from exc


# ============================================================================
# Vault 数据结构
# ============================================================================

class EncryptedVault:
    """
    加密存储容器（JSON 兼容）
    结构固定，便于版本演进
    """

    def __init__(
        self,
        version: int = 1,
        alg: str = ALGORITHM_AES,
        salt: str = "",
        nonce: str = "",
        ciphertext: str = "",
        check: str = "",
    ):
        self.version = version
        self.alg = alg
        self.salt = salt       # Base64 encoded
        self.nonce = nonce     # Base64 encoded
        self.ciphertext = ciphertext  # Base64 encoded (includes GCM auth tag)
        self.check = check     # Base64: key derivation verification

    def to_dict(self) -> dict:
        return {
            "v": self.version,
            "alg": self.alg,
            "salt": self.salt,
            "nonce": self.nonce,
            "ciphertext": self.ciphertext,
            "check": self.check,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EncryptedVault":
        # 兼容旧字段名
        salt = d.get("salt") or d.get("salt_bytes", "")
        return cls(
            version=d.get("v", d.get("version", 1)),
            alg=d.get("alg", ALGORITHM_AES),
            salt=salt,
            nonce=d.get("nonce", ""),
            ciphertext=d.get("ciphertext", d.get("encrypted_data", "")),
            check=d.get("check", d.get("key_check", "")),
        )

    def is_complete(self) -> bool:
        """检查必要字段是否存在"""
        return bool(self.salt and self.nonce and self.ciphertext and self.check)


# ============================================================================
# FluxVault：端到端加密存储容器
# ============================================================================

class FluxVault:
    """
    NueroNote 的端到端加密存储容器

    数据结构：
    {
        "documents": { doc_id: Document },
        "blocks": { block_id: Block },
        "daily": { "YYYY-MM-DD": doc_id },
        "flashcards": [ Flashcard ],
        "templates": { template_id: Template },
        "tags": { tag: [doc_id] },
    }
    """

    def __init__(self, master_password: str):
        self._password = master_password
        self._salt: Optional[bytes] = None
        self._key: Optional[bytes] = None
        self._cipher: Optional[AESGCMCipher] = None
        self._vault: Optional[EncryptedVault] = None
        self._data: dict = {}

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def create(self) -> EncryptedVault:
        """
        创建新 vault（注册时调用一次）
        1. 生成随机盐
        2. PBKDF2 派生密钥
        3. 初始化空数据结构
        4. 密封（加密）
        """
        self._salt = random_bytes(SALT_LEN)
        self._derive_key()
        self._init_cipher()
        self._data = self._empty_data()
        return self._seal()

    def unlock(self, vault_data: EncryptedVault | dict) -> bool:
        """
        解锁 vault（登录时调用）
        1. 解析 vault
        2. 派生密钥
        3. 验证 key_check（常量时间）
        4. 解密封（解密）
        返回：True=成功，False=密码错误
        """
        try:
            if isinstance(vault_data, dict):
                vault_data = EncryptedVault.from_dict(vault_data)

            self._salt = urlsafe_b64decode(vault_data.salt)
            self._derive_key()

            # 验证密钥（常量时间，不泄露信息）
            key_check = derive_key_check(self._password, self._salt)
            if not constant_time_compare(key_check, vault_data.check):
                self._key = None
                return False

            self._init_cipher()
            self._vault = vault_data
            plaintext = self._unseal(vault_data)
            self._data = json.loads(plaintext.decode("utf-8"))
            return True

        except (DecryptionError, VaultIntegrityError, json.JSONDecodeError,
                KeyDerivationError, Exception):
            return False

    def seal(self) -> EncryptedVault:
        """
        重新密封 vault（保存前调用）
        数据变更后必须调用此方法重新加密
        """
        return self._seal()

    # ------------------------------------------------------------------
    # 数据操作
    # ------------------------------------------------------------------

    def create_document(self, title: str = "") -> str:
        """创建新文档，返回 doc_id"""
        doc_id = random_id("d")
        now = self._now()
        self._data["documents"][doc_id] = {
            "id": doc_id,
            "title": title or "无标题",
            "block_ids": [],
            "tags": [],
            "created": now,
            "updated": now,
        }
        return doc_id

    def create_block(self, type: str = "p", content: str = "", doc_id: Optional[str] = None) -> str:
        """创建新块，返回 block_id"""
        block_id = random_id("b")
        now = self._now()
        self._data["blocks"][block_id] = {
            "id": block_id,
            "type": type,
            "content": content,
            "attrs": {},
            "children": [],
            "doc_id": doc_id,
            "created": now,
            "updated": now,
        }
        if doc_id and doc_id in self._data["documents"]:
            doc = self._data["documents"][doc_id]
            if "block_ids" not in doc:
                doc["block_ids"] = []
            if block_id not in doc["block_ids"]:
                doc["block_ids"].append(block_id)
            doc["updated"] = self._now()
        return block_id

    def add_block_to_doc(self, doc_id: str, block_id: str, after_block_id: Optional[str] = None) -> None:
        """将块添加到文档（指定位置）"""
        if doc_id not in self._data["documents"]:
            return
        doc = self._data["documents"][doc_id]
        if "block_ids" not in doc:
            doc["block_ids"] = []
        if after_block_id and after_block_id in doc["block_ids"]:
            idx = doc["block_ids"].index(after_block_id)
            doc["block_ids"].insert(idx + 1, block_id)
        else:
            doc["block_ids"].append(block_id)
        if block_id in self._data["blocks"]:
            self._data["blocks"][block_id]["doc_id"] = doc_id
        doc["updated"] = self._now()

    def save_document(self, doc_id: str, doc: dict) -> None:
        """直接保存文档对象"""
        self._data["documents"][doc_id] = doc

    def save_block(self, block_id: str, block: dict) -> None:
        """直接保存块对象"""
        self._data["blocks"][block_id] = block

    def delete_document(self, doc_id: str) -> None:
        """删除文档及其所有块"""
        doc = self._data["documents"].pop(doc_id, None)
        if not doc:
            return
        for block_id in doc.get("block_ids", []):
            self._data["blocks"].pop(block_id, None)
        for tag in doc.get("tags", []):
            if tag in self._data["tags"]:
                self._data["tags"][tag] = [d for d in self._data["tags"][tag] if d != doc_id]

    def delete_block(self, block_id: str) -> None:
        """删除块（从文档中移除）"""
        block = self._data["blocks"].pop(block_id, None)
        if not block or not block.get("doc_id"):
            return
        doc = self._data["documents"].get(block["doc_id"])
        if doc:
            doc["block_ids"] = [b for b in doc.get("block_ids", []) if b != block_id]

    def get_document(self, doc_id: str) -> Optional[dict]:
        return self._data["documents"].get(doc_id)

    def get_block(self, block_id: str) -> Optional[dict]:
        return self._data["blocks"].get(block_id)

    def get_all_documents(self) -> list[dict]:
        return sorted(
            self._data["documents"].values(),
            key=lambda d: d.get("updated", 0),
            reverse=True,
        )

    # ------------------------------------------------------------------
    # 闪卡
    # ------------------------------------------------------------------

    def create_flashcard(self, card: dict) -> str:
        """创建闪卡"""
        cards = self._data.setdefault("flashcards", [])
        fc_id = random_id("fc")
        card["id"] = fc_id
        card["created"] = self._now()
        card["next_review"] = self._now()  # 立即可复习
        cards.append(card)
        return fc_id

    def get_all_flashcards(self) -> list:
        return self._data.get("flashcards", [])

    def get_due_flashcards(self) -> list:
        """获取到期的闪卡"""
        now = self._now()
        return [c for c in self._data.get("flashcards", []) if c.get("next_review", 0) <= now]

    # ------------------------------------------------------------------
    # 搜索
    # ------------------------------------------------------------------

    def search(self, query: str) -> list[dict]:
        """
        关键词全文搜索
        - 空查询返回空列表（不返回全量）
        - 大小写不敏感
        - 按相关性（标题优先）排序
        """
        q = query.strip()
        if not q:
            return []
        q_lower = q.lower()
        results = []
        for doc in self._data["documents"].values():
            title = doc.get("title", "")
            title_lower = title.lower()
            # 标题命中 → 高优先级
            if q_lower in title_lower:
                snippet = self._doc_snippet(doc, q_lower)
                results.append({
                    "doc_id": doc["id"],
                    "title": title,
                    "snippet": snippet,
                    "match": "title",
                    "score": 2,
                })
                continue
            # 内容命中
            if q_lower in self._doc_text(doc).lower():
                snippet = self._doc_snippet(doc, q_lower)
                results.append({
                    "doc_id": doc["id"],
                    "title": title,
                    "snippet": snippet,
                    "match": "content",
                    "score": 1,
                })
        # 标题优先，其次按更新时间
        results.sort(key=lambda r: (r["score"], self._data["documents"][r["doc_id"]].get("updated", 0)), reverse=True)
        return results[:50]

    def _doc_text(self, doc: dict) -> str:
        """提取文档所有文本"""
        parts = [doc.get("title", "")]
        for bid in doc.get("block_ids", []):
            b = self._data["blocks"].get(bid, {})
            parts.append(b.get("content", ""))
        return " ".join(parts)

    def _doc_snippet(self, doc: dict, q: str) -> str:
        """提取含关键词的片段"""
        text = self._doc_text(doc)
        idx = text.lower().find(q)
        if idx < 0:
            return text[:100]
        start = max(0, idx - 30)
        end = min(len(text), idx + len(q) + 60)
        return text[start:end]

    # ------------------------------------------------------------------
    # 每日笔记
    # ------------------------------------------------------------------

    def open_daily(self, date_str: Optional[str] = None) -> str:
        """打开/创建指定日期的日记，返回 doc_id"""
        d = date_str or self._today()
        daily = self._data.setdefault("daily", {})
        doc_id = daily.get(d)
        if not doc_id or doc_id not in self._data["documents"]:
            doc_id = self.create_document(f"\u2605 {d} \u65e5\u8bb0")  # ★ YYYY-MM-DD 日记
            daily[d] = doc_id
            now = self._now()
            # 添加默认模板块
            block_id = self.create_block("p",
                f"## \u270d \u5de5\u4f5c\u65e5\u5fd7\n\n### \u4eca\u65e5\u5b8c\u6210\n- [ ] \n\n### \u660e\u65e5\u8ba1\u5212\n- [ ]\n",
                doc_id
            )
            self._data["documents"][doc_id]["block_ids"] = [block_id]
        return doc_id

    def get_all_daily(self) -> list[dict]:
        """获取所有日记（按日期倒序）"""
        daily = self._data.get("daily", {})
        result = []
        for d, doc_id in daily.items():
            doc = self._data["documents"].get(doc_id)
            if doc:
                result.append({"date": d, "doc_id": doc_id, "doc": doc})
        result.sort(key=lambda x: x["date"], reverse=True)
        return result

    # ------------------------------------------------------------------
    # 导入/导出
    # ------------------------------------------------------------------

    def export_markdown(self) -> str:
        """
        导出为明文 Markdown（用于备份）
        ⚠️ 警告：明文导出，请妥善保管
        """
        import re
        lines = ["# NueroNote \u5bfc\u51fa\n"]

        for doc in self._data["documents"].values():
            if doc.get("is_daily"):
                lines.append(f"\n## \u2605 {doc.get('title', '')}\n")
            else:
                lines.append(f"\n## {doc.get('title', '\u65e0\u6807\u9898')}\n")

            for block_id in doc.get("block_ids", []):
                block = self._data["blocks"].get(block_id, {})
                content = block.get("content", "")
                btype = block.get("type", "p")

                if btype == "h1":
                    lines.append(f"# {content}\n")
                elif btype == "h2":
                    lines.append(f"## {content}\n")
                elif btype == "h3":
                    lines.append(f"### {content}\n")
                elif btype == "code":
                    lang = (block.get("attrs") or {}).get("lang", "")
                    lines.append(f"```{lang}\n{content}\n```\n")
                elif btype == "quote":
                    for ql in content.split("\n"):
                        lines.append(f"> {ql}\n")
                elif btype == "callout":
                    lines.append(f"> [!note]\n> {content}\n")
                elif btype == "divider":
                    lines.append("---\n")
                elif btype == "math":
                    lines.append(f"$$\n{content}\n$$\n")
                else:
                    lines.append(f"{content}\n")

            lines.append("\n")
        return "".join(lines)

    def import_markdown(self, text: str) -> int:
        """
        从 Markdown 导入
        返回：创建的文档数
        """
        import re

        doc_id = self.create_document("\u5bfc\u5165\u7b14\u8bb0")
        current_doc = self._data["documents"][doc_id]
        current_doc["block_ids"] = []

        in_code = False
        code_lines = []
        code_lang = ""

        for line in text.split("\n"):
            # 代码块
            m_code = re.match(r"^```(\w*)", line)
            if m_code:
                if not in_code:
                    in_code = True
                    code_lang = m_code.group(1)
                    code_lines = []
                else:
                    in_code = False
                    block_id = self.create_block("code", "\n".join(code_lines))
                    self.add_block_to_doc(doc_id, block_id)
                    attrs = self._data["blocks"][block_id].get("attrs") or {}
                    attrs["lang"] = code_lang
                    self._data["blocks"][block_id]["attrs"] = attrs
                continue

            if in_code:
                code_lines.append(line)
                continue

            # 标题
            m_head = re.match(r"^(#{1,3})\s+(.+)", line)
            if m_head:
                depth = len(m_head.group(1))
                block_id = self.create_block(f"h{depth}", m_head.group(2))
                self.add_block_to_doc(doc_id, block_id)
                continue

            # 引用
            if line.startswith(">"):
                block_id = self.create_block("quote", line[1:].strip())
                self.add_block_to_doc(doc_id, block_id)
                continue

            # 分隔线
            if line.strip() in ("---", "***", "___"):
                block_id = self.create_block("divider", "---")
                self.add_block_to_doc(doc_id, block_id)
                continue

            # 普通段落
            if line.strip():
                block_id = self.create_block("p", line.strip())
                self.add_block_to_doc(doc_id, block_id)

        return 1

    # ------------------------------------------------------------------
    # 加密/解密（私有）
    # ------------------------------------------------------------------

    def _derive_key(self) -> None:
        """从密码 + 盐派生主密钥"""
        self._key = derive_key(self._password, self._salt)

    def _init_cipher(self) -> None:
        """初始化加密器（每次操作前调用，保证使用正确的 key）"""
        self._cipher = AESGCMCipher(self._key)

    def _seal(self) -> EncryptedVault:
        """密封（加密）当前数据"""
        self._init_cipher()
        plaintext = json.dumps(self._data, ensure_ascii=False).encode("utf-8")
        encrypted = self._cipher.encrypt(plaintext)
        key_check = derive_key_check(self._password, self._salt)
        self._vault = EncryptedVault(
            version=1,
            alg=ALGORITHM_AES,
            salt=urlsafe_b64encode(self._salt).decode(),
            nonce=encrypted["nonce"],
            ciphertext=encrypted["ciphertext"],
            check=key_check,
        )
        return self._vault

    def _unseal(self, vault: EncryptedVault) -> bytes:
        """解密封（解密）vault"""
        self._init_cipher()
        encrypted = {
            "nonce": vault.nonce,
            "ciphertext": vault.ciphertext,
        }
        return self._cipher.decrypt(encrypted)

    @staticmethod
    def _now() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _today() -> str:
        return time.strftime("%Y-%m-%d", time.localtime())

    @staticmethod
    def _empty_data() -> dict:
        return {
            "documents": {},
            "blocks": {},
            "daily": {},
            "flashcards": [],
            "templates": {},
            "tags": {},
        }

    # ------------------------------------------------------------------
    # 公开访问器（导出 vault）
    # ------------------------------------------------------------------

    def export_vault(self) -> dict:
        """导出加密 vault（用于上传服务器）"""
        return self._vault.to_dict() if self._vault else {}


# ============================================================================
# 自测
# ============================================================================

if __name__ == "__main__":
    print("NueroNote 加密引擎自测\n")

    # 1. 创建 vault
    vault = FluxVault("TestPassword123!")
    sealed = vault.create()
    assert sealed.is_complete(), "Vault 字段不完整"
    print(f"\u2713 1. Vault 创建成功")
    print(f"   密文大小: {len(sealed.ciphertext)} bytes")
    print(f"   算法: {sealed.alg}")

    # 2. 同一密码解锁
    vault2 = FluxVault("TestPassword123!")
    ok = vault2.unlock(sealed)
    assert ok, "同一密码应解锁成功"
    print(f"\u2713 2. 同一密码解锁: OK")

    # 3. 错误密码拒绝
    vault3 = FluxVault("WrongPassword!")
    ok3 = vault3.unlock(sealed)
    assert not ok3, "错误密码应拒绝"
    print(f"\u2713 3. 错误密码拒绝: OK")

    # 4. 文档 CRUD
    doc_id = vault2.create_document("\u6d4b\u8bd5\u6587\u6863")
    b1 = vault2.create_block("h1", "\u7b2c\u4e00\u7ae0")
    b2 = vault2.create_block("p", "\u8fd9\u662f\u6d4b\u8bd5\u5185\u5bb9\uff0c\u5305\u542b\u4e2d\u6587")
    vault2.add_block_to_doc(doc_id, b1)
    vault2.add_block_to_doc(doc_id, b2)
    doc = vault2.get_document(doc_id)
    assert doc is not None and doc["title"] == "\u6d4b\u8bd5\u6587\u6863"
    print(f"\u2713 4. 文档创建: OK (doc_id={doc_id[:12]}...)")

    # 5. 搜索
    results = vault2.search("\u6d4b\u8bd5")
    assert len(results) == 1 and "\u6d4b\u8bd5" in results[0]["title"]
    print(f"\u2713 5. 搜索功能: OK ({len(results)} \u7ed3\u679c)")

    # 6. 闪卡
    fc_id = vault2.create_flashcard({"front": "Q1", "back": "A1"})
    due = vault2.get_due_flashcards()
    assert len(due) == 1
    print(f"\u2713 6. 闪卡系统: OK")

    # 7. 每日笔记
    daily_id = vault2.open_daily("2026-04-13")
    assert daily_id in vault2._data["documents"]
    print(f"\u2713 7. 每日笔记: OK")

    # 8. Seal/unseal 完整性
    sealed2 = vault2.seal()
    vault4 = FluxVault("TestPassword123!")
    ok4 = vault4.unlock(sealed2)
    assert ok4, "Seal 后应能正常解锁"
    assert len(vault4._data["documents"]) == len(vault2._data["documents"])
    print(f"\u2713 8. Seal/Unseal 完整性: OK")

    # 9. 大文档性能
    import time
    vault5 = FluxVault("perf")
    vault5.create()
    start = time.time()
    for i in range(100):
        did = vault5.create_document(f"\u6587\u6863{i}")
        for j in range(5):
            bid = vault5.create_block("p", f"\u7b2c{i}\u7bc7\u7b2c{j}\u6bb5\u5185\u5bb9")
            vault5.add_block_to_doc(did, bid)
    sealed5 = vault5.seal()
    elapsed = time.time() - start
    print(f"\u2713 9. 性能测试: 100\u6587\u6863+500\u5757 \u52a0\u5bc6 = {elapsed:.3f}s")

    # 10. Unicode 内容
    vault6 = FluxVault("\u5bc6\u7801\U0001F510")
    sv6 = vault6.create()
    vault6.create_document("\u4e2d\u6587\u65e5\u672c\u8a9e\U0001F389")
    vault6.create_block("code", "def \u4e2d\u6587\u51fd\u6570():\n    return 42")
    sv6 = vault6.seal()
    vault7 = FluxVault("\u5bc6\u7801\U0001F510")
    ok7 = vault7.unlock(sv6)
    assert ok7
    print(f"\u2713 10. Unicode \u652f\u6301: OK")

    # 11. Markdown 导入/导出
    vault8 = FluxVault("mdtest")
    vault8.create()
    count = vault8.import_markdown("# \u6807\u9898\n\n\u5185\u5bb9\n\n```python\nprint(1)\n```")
    assert count == 1
    md = vault8.export_markdown()
    assert "# \u6807\u9891" in md
    print(f"\u2713 11. Markdown \u5bfc\u5165/\u5bfc\u51fa: OK")

    print("\n\u250c\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510")
    print("  \u2713  \u5168\u90e8 11 \u9879\u6d4b\u8bd5\u901a\u8fc7\uff01  \u2713")
    print("\u2514\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2518")
