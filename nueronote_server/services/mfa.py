#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote MFA服务
邮件/短信验证码、备用码等功能。

【更新日志 2026-04-14 v1.2】
- 新增：MFA服务
- 支持邮件验证码
- 支持短信验证码（需要配置）
- 生成一次性备用码
"""

import hashlib
import hmac
import secrets
import time
from nueronote_server.services.email import get_email_service


class MFAService:
    """MFA服务"""
    
    CODE_LENGTH = 6
    CODE_EXPIRY_MINUTES = 5
    MAX_ATTEMPTS = 3
    MAX_BACKUP_CODES = 10
    # 【v1.3】备份码哈希盐值
    _backup_salt = "NueroNote:v1.3:mfa-backup-code"
    
    def __init__(self):
        self.cache = None
    
    def generate_code(self) -> str:
        """生成6位随机验证码"""
        return ''.join([str(secrets.randbelow(10)) for _ in range(self.CODE_LENGTH)])
    
    def hash_code(self, code: str) -> str:
        """
        【v1.3安全修复】使用HMAC哈希验证码，防止彩虹表攻击
        """
        return hmac.new(
            self._backup_salt.encode('utf-8'),
            code.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()[:32]
    
    def verify_code(self, code: str, stored_hash: str) -> bool:
        """验证验证码（恒定时间比较）"""
        code_hash = self.hash_code(code)
        return hmac.compare_digest(code_hash, stored_hash)
    
    def generate_backup_codes(self) -> Tuple[list, list]:
        """
        生成备用码
        
        Returns:
            (明文列表, 哈希列表) - 明文给用户，哈希存储
        """
        codes_plain = []
        codes_hash = []
        
        for _ in range(self.MAX_BACKUP_CODES):
            code = secrets.token_hex(4).upper()  # 8位
            codes_plain.append(code)
            codes_hash.append(self.hash_code(code))
        
        return codes_plain, codes_hash
    
    def send_email(self, to_email: str, subject: str, html_body: str) -> bool:
        """
        发送邮件
        
        Args:
            to_email: 目标邮箱
            subject: 邮件主题
            html_body: HTML内容
            
        Returns:
            是否发送成功
        """
        email_service = get_email_service()
        return email_service.send(to_email, subject, html_body)
    
    def send_mfa_email(self, email: str, code: str) -> bool:
        """
        发送MFA验证码邮件
        
        Args:
            email: 目标邮箱
            code: 6位验证码
            
        Returns:
            是否发送成功
        """
        return get_email_service().send_mfa_code(email, code)
    
    def send_sms(self, phone: str, code: str) -> bool:
        """
        发送短信验证码
        
        Args:
            phone: 手机号
            code: 6位验证码
            
        Returns:
            是否发送成功
        """
        # TODO: 集成短信服务商（如阿里云、腾讯云）
        print(f"[MFA SMS] To: {phone}, Code: {code}")
        return True
    
    def get_mfa_type_name(self, mfa_type: str) -> str:
        """获取MFA类型名称"""
        names = {
            'email': '邮箱',
            'sms': '短信'
        }
        return names.get(mfa_type, mfa_type)


# 全局实例
_mfa_service: Optional[MFAService] = None


def get_mfa_service() -> MFAService:
    """获取MFA服务实例"""
    global _mfa_service
    if _mfa_service is None:
        _mfa_service = MFAService()
    return _mfa_service
