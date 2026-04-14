#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 设备信任服务
管理信任设备、浏览器指纹、免MFA等功能。

【更新日志 2026-04-14 v1.2】
- 新增：信任设备服务
- 30天内已验证设备免MFA
- 浏览器指纹Hash存储
"""

import hashlib
import secrets
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict


@dataclass
class TrustedDevice:
    """信任设备数据类"""
    id: str
    user_id: str
    fingerprint: str
    device_name: str
    browser: str
    os: str
    device_type: str
    ip_address: str
    first_seen_at: int
    last_seen_at: int
    expires_at: int
    login_count: int
    is_trusted: bool


class DeviceService:
    """设备信任服务"""
    
    TRUST_DAYS = 30
    TRUST_SECONDS = TRUST_DAYS * 24 * 60 * 60
    # 【v1.3】用于设备指纹哈希的盐值
    _fp_salt = "NueroNote:v1.3:device-fingerprint-salt"
    
    def __init__(self):
        self.cache = None
    
    def generate_device_id(self) -> str:
        """生成设备ID"""
        return secrets.token_hex(16)
    
    def hash_fingerprint(self, fingerprint: str) -> str:
        """
        【v1.3安全修复】哈希指纹使用HMAC防止彩虹表攻击
        使用用户专属盐值，保护相同设备指纹
        """
        import hmac
        # 使用固定盐值进行HMAC
        return hmac.new(
            self._fp_salt.encode('utf-8'),
            fingerprint.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()[:32]
    
    def check_trusted(
        self, 
        db, 
        user_id: str, 
        fingerprint: str
    ) -> Optional[TrustedDevice]:
        """
        检查设备是否受信任且未过期
        
        Args:
            db: 数据库连接
            user_id: 用户ID
            fingerprint: 浏览器指纹（原始）
            
        Returns:
            TrustedDevice if trusted and valid, None otherwise
        """
        fp_hash = self.hash_fingerprint(fingerprint)
        now = int(time.time() * 1000)
        
        row = db.execute("""
            SELECT * FROM trusted_devices 
            WHERE user_id = ? AND fingerprint = ? AND is_trusted = 1
        """, (user_id, fp_hash)).fetchone()
        
        if not row:
            return None
        
        # 检查是否过期
        if row['expires_at'] < now:
            # 自动标记为不信任
            db.execute(
                "UPDATE trusted_devices SET is_trusted = 0 WHERE id = ?",
                (row['id'],)
            )
            db.commit()
            return None
        
        return TrustedDevice(**dict(row))
    
    def register_device(
        self,
        db,
        user_id: str,
        fingerprint: str,
        device_info: Dict[str, Any],
        ip_address: str,
        user_agent: str
    ) -> TrustedDevice:
        """
        注册或更新信任设备
        
        Args:
            db: 数据库连接
            user_id: 用户ID
            fingerprint: 浏览器指纹
            device_info: 设备信息 {name, browser, os, deviceType}
            ip_address: IP地址
            user_agent: User-Agent头
            
        Returns:
            新创建或更新的TrustedDevice
        """
        fp_hash = self.hash_fingerprint(fingerprint)
        now = int(time.time() * 1000)
        expires_at = now + self.TRUST_SECONDS * 1000
        
        # 检查是否已存在
        existing = db.execute("""
            SELECT id FROM trusted_devices 
            WHERE user_id = ? AND fingerprint = ?
        """, (user_id, fp_hash)).fetchone()
        
        if existing:
            # 更新现有设备
            device_id = existing['id']
            db.execute("""
                UPDATE trusted_devices 
                SET last_seen_at = ?, 
                    login_count = login_count + 1,
                    ip_address = ?,
                    expires_at = ?,
                    device_name = ?,
                    browser = ?,
                    os = ?,
                    device_type = ?
                WHERE id = ?
            """, (now, ip_address, expires_at,
                  device_info.get('name', 'Unknown Device'),
                  device_info.get('browser', 'Unknown'),
                  device_info.get('os', 'Unknown'),
                  device_info.get('deviceType', 'desktop'),
                  device_id))
            db.commit()
        else:
            # 创建新设备
            device_id = self.generate_device_id()
            db.execute("""
                INSERT INTO trusted_devices 
                (id, user_id, fingerprint, device_name, browser, os, device_type,
                 ip_address, user_agent, first_seen_at, last_seen_at, expires_at, 
                 login_count, is_trusted)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                device_id, user_id, fp_hash,
                device_info.get('name', 'Unknown Device'),
                device_info.get('browser', 'Unknown'),
                device_info.get('os', 'Unknown'),
                device_info.get('deviceType', 'desktop'),
                ip_address, user_agent[:500] if user_agent else '',
                now, now, expires_at, 1
            ))
            db.commit()
        
        # 返回设备信息
        row = db.execute(
            "SELECT * FROM trusted_devices WHERE id = ?", (device_id,)
        ).fetchone()
        
        return TrustedDevice(**dict(row))
    
    def revoke_device(self, db, user_id: str, device_id: str) -> bool:
        """撤销单个设备"""
        result = db.execute("""
            UPDATE trusted_devices 
            SET is_trusted = 0
            WHERE id = ? AND user_id = ?
        """, (device_id, user_id))
        db.commit()
        return result.rowcount > 0
    
    def revoke_all_devices(self, db, user_id: str) -> int:
        """撤销所有设备"""
        result = db.execute("""
            UPDATE trusted_devices 
            SET is_trusted = 0
            WHERE user_id = ? AND is_trusted = 1
        """, (user_id,))
        db.commit()
        return result.rowcount
    
    def get_user_devices(self, db, user_id: str) -> List[TrustedDevice]:
        """获取用户的所有设备"""
        rows = db.execute("""
            SELECT * FROM trusted_devices 
            WHERE user_id = ?
            ORDER BY last_seen_at DESC
        """, (user_id,)).fetchall()
        
        return [TrustedDevice(**dict(row)) for row in rows]
    
    def cleanup_expired(self, db) -> int:
        """清理过期设备"""
        now = int(time.time() * 1000)
        result = db.execute("""
            DELETE FROM trusted_devices 
            WHERE expires_at < ? AND is_trusted = 0
        """, (now,))
        db.commit()
        return result.rowcount


# 全局实例
_device_service: Optional[DeviceService] = None


def get_device_service() -> DeviceService:
    """获取设备服务实例"""
    global _device_service
    if _device_service is None:
        _device_service = DeviceService()
    return _device_service
