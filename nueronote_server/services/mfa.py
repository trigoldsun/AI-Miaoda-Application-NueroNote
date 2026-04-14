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
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional, Tuple, Dict, Any
import os


class MFAService:
    """MFA服务"""
    
    CODE_LENGTH = 6
    CODE_EXPIRY_MINUTES = 5
    MAX_ATTEMPTS = 3
    MAX_BACKUP_CODES = 10
    
    def __init__(self):
        self.cache = None
        self._smtp_config = None
    
    @property
    def smtp_config(self) -> Dict[str, str]:
        """获取SMTP配置"""
        if self._smtp_config is None:
            self._smtp_config = {
                'server': os.environ.get('SMTP_SERVER', ''),
                'port': int(os.environ.get('SMTP_PORT', '587')),
                'user': os.environ.get('SMTP_USER', ''),
                'password': os.environ.get('SMTP_PASSWORD', ''),
                'from_email': os.environ.get('SMTP_FROM', os.environ.get('SMTP_USER', '')),
                'use_tls': os.environ.get('SMTP_TLS', 'true').lower() == 'true',
            }
        return self._smtp_config
    
    def generate_code(self) -> str:
        """生成6位随机验证码"""
        return ''.join([str(secrets.randbelow(10)) for _ in range(self.CODE_LENGTH)])
    
    def hash_code(self, code: str) -> str:
        """哈希验证码"""
        return hashlib.sha256(code.encode()).hexdigest()[:32]
    
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
        cfg = self.smtp_config
        
        # 如果没有配置SMTP，打印到日志（开发环境）
        if not cfg['server'] or not cfg['user']:
            print(f"[MFA Email] To: {to_email}, Subject: {subject}")
            print(f"[MFA Email] Preview: {html_body[:200]}...")
            return True
        
        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = cfg['from_email']
            msg['To'] = to_email
            msg['Subject'] = subject
            
            msg.attach(MIMEText(html_body, 'html'))
            
            server = smtplib.SMTP(cfg['server'], cfg['port'])
            if cfg['use_tls']:
                server.starttls()
            server.login(cfg['user'], cfg['password'])
            server.send_message(msg)
            server.quit()
            
            return True
            
        except Exception as e:
            print(f"[MFA Email] Failed to send: {e}")
            return False
    
    def send_mfa_email(self, email: str, code: str) -> bool:
        """
        发送MFA验证码邮件
        
        Args:
            email: 目标邮箱
            code: 6位验证码
            
        Returns:
            是否发送成功
        """
        subject = "【NueroNote】您的登录验证码"
        
        html_body = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
                .container {{ max-width: 480px; margin: 0 auto; padding: 20px; }}
                .code {{ 
                    font-size: 32px; 
                    letter-spacing: 12px; 
                    color: #2563eb;
                    font-weight: bold;
                    text-align: center;
                    padding: 20px;
                    background: #f3f4f6;
                    border-radius: 8px;
                    margin: 20px 0;
                }}
                .warning {{ 
                    color: #dc2626; 
                    font-size: 14px;
                    margin-top: 20px;
                }}
                .footer {{ 
                    color: #6b7280; 
                    font-size: 12px;
                    margin-top: 30px;
                    border-top: 1px solid #e5e7eb;
                    padding-top: 15px;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <h2>您好，</h2>
                <p>您正在进行 NueroNote 安全登录验证，您的验证码是：</p>
                
                <div class="code">{code}</div>
                
                <p>验证码有效期为 <strong>5 分钟</strong>。</p>
                
                <p class="warning">
                    ⚠️ 请勿将验证码告诉他人。如果您没有进行登录操作，请忽略此邮件。
                </p>
                
                <div class="footer">
                    <p>NueroNote - 端到端加密笔记</p>
                    <p>此邮件由系统自动发送，请勿回复。</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        return self.send_email(email, subject, html_body)
    
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
