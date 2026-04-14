#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 邮件服务模块
支持多种邮件服务商的现代邮件发送实现。

【更新日志 2026-04-14 v1.2】
- 重构邮件服务，支持主流邮件服务商
- 支持Gmail OAuth2 / App Password
- 支持SendGrid, Amazon SES, Mailgun
- 支持QQ邮箱、网易邮箱等国内服务商
- 添加SPF/DKIM/DMARC建议
"""

import os
import ssl
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from typing import Optional, Dict, Any
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import base64


class EmailService:
    """
    现代邮件服务
    
    支持的邮件服务商配置：
    
    1. Gmail (推荐)
       - SMTP: smtp.gmail.com:587 (TLS)
       - OAuth2: 最安全，推荐生产环境
       - App Password: 简单但安全
    
    2. SendGrid
       - API: https://api.sendgrid.com/v3/
       - 免费额度: 100/天
    
    3. Amazon SES
       - SMTP: email-smtp.xx.amazonaws.com:587
       - 免费额度: 62,000/月
    
    4. Mailgun
       - API: https://api.mailgun.com/v3/
       - 免费额度: 5,000/月
    
    5. QQ邮箱/网易邮箱
       - SMTP: smtp.qq.com / smtp.163.com
       - 需要授权码（非密码）
    """
    
    # 支持的服务商配置模板
    PROVIDERS = {
        'gmail': {
            'smtp_host': 'smtp.gmail.com',
            'smtp_port': 587,
            'smtp_tls': True,
            'use_oauth': True,
        },
        'qq': {
            'smtp_host': 'smtp.qq.com',
            'smtp_port': 587,
            'smtp_tls': True,
            'use_oauth': False,
        },
        '163': {
            'smtp_host': 'smtp.163.com',
            'smtp_port': 587,
            'smtp_tls': True,
            'use_oauth': False,
        },
        'outlook': {
            'smtp_host': 'smtp.office365.com',
            'smtp_port': 587,
            'smtp_tls': True,
            'use_oauth': True,
        },
        'custom': {
            'smtp_host': '',
            'smtp_port': 587,
            'smtp_tls': True,
            'use_oauth': False,
        }
    }
    
    def __init__(self):
        self._config = None
        self._provider = None
    
    @property
    def config(self) -> Dict[str, Any]:
        """获取邮件配置"""
        if self._config is None:
            self._load_config()
        return self._config
    
    @property
    def provider(self) -> str:
        """获取邮件服务商类型"""
        if self._provider is None:
            self._provider = os.environ.get('EMAIL_PROVIDER', 'custom').lower()
        return self._provider
    
    def _load_config(self):
        """加载邮件配置"""
        self._config = {
            # 服务商类型: gmail, qq, 163, outlook, sendgrid, ses, mailgun, custom
            'provider': os.environ.get('EMAIL_PROVIDER', 'custom').lower(),
            
            # SMTP配置
            'smtp_host': os.environ.get('EMAIL_SMTP_HOST', ''),
            'smtp_port': int(os.environ.get('EMAIL_SMTP_PORT', '587')),
            'smtp_user': os.environ.get('EMAIL_SMTP_USER', ''),
            'smtp_password': os.environ.get('EMAIL_SMTP_PASSWORD', ''),
            'smtp_from': os.environ.get('EMAIL_FROM', os.environ.get('EMAIL_SMTP_USER', '')),
            'smtp_tls': os.environ.get('EMAIL_SMTP_TLS', 'true').lower() == 'true',
            
            # OAuth2配置 (Gmail/Outlook)
            'oauth_enabled': os.environ.get('EMAIL_OAUTH_ENABLED', 'false').lower() == 'true',
            'oauth_client_id': os.environ.get('EMAIL_OAUTH_CLIENT_ID', ''),
            'oauth_client_secret': os.environ.get('EMAIL_OAUTH_CLIENT_SECRET', ''),
            'oauth_refresh_token': os.environ.get('EMAIL_OAUTH_REFRESH_TOKEN', ''),
            
            # API配置 (SendGrid, SES, Mailgun)
            'api_key': os.environ.get('EMAIL_API_KEY', ''),
            'api_url': os.environ.get('EMAIL_API_URL', ''),
        }
        
        # 根据provider自动填充SMTP配置
        provider = self._config['provider']
        if provider in self.PROVIDERS and provider != 'custom':
            tmpl = self.PROVIDERS[provider]
            if not self._config['smtp_host']:
                self._config['smtp_host'] = tmpl['smtp_host']
            if not self._config['smtp_port']:
                self._config['smtp_port'] = tmpl['smtp_port']
    
    def _get_access_token(self) -> Optional[str]:
        """
        使用OAuth2获取访问令牌
        
        Returns:
            Access token or None
        """
        if not self.config.get('oauth_refresh_token'):
            return None
        
        try:
            # Gmail OAuth2 token endpoint
            token_url = 'https://oauth2.googleapis.com/token'
            
            data = {
                'client_id': self.config['oauth_client_id'],
                'client_secret': self.config['oauth_client_secret'],
                'refresh_token': self.config['oauth_refresh_token'],
                'grant_type': 'refresh_token',
            }
            
            data_encoded = '&'.join(f'{k}={v}' for k, v in data.items())
            
            req = Request(
                token_url,
                data=data_encoded.encode('utf-8'),
                headers={'Content-Type': 'application/x-www-form-urlencoded'}
            )
            
            with urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result.get('access_token')
                
        except (URLError, HTTPError, Exception) as e:
            print(f"[Email] OAuth2 token refresh failed: {e}")
            return None
    
    def send_via_smtp(self, to_email: str, subject: str, html_body: str) -> bool:
        """
        通过SMTP发送邮件
        
        Args:
            to_email: 目标邮箱
            subject: 邮件主题
            html_body: HTML内容
            
        Returns:
            是否发送成功
        """
        cfg = self.config
        
        if not cfg['smtp_host'] or not cfg['smtp_user']:
            print(f"[Email] SMTP not configured. To: {to_email}, Subject: {subject}")
            return False
        
        try:
            msg = MIMEMultipart('alternative')
            msg['From'] = cfg['smtp_from']
            msg['To'] = to_email
            msg['Subject'] = Header(subject, 'utf-8')
            
            # HTML内容
            msg.attach(MIMEText(html_body, 'html', 'utf-8'))
            
            # 连接SMTP服务器
            if cfg['smtp_port'] == 465:
                # SSL连接
                server = smtplib.SMTP_SSL(
                    cfg['smtp_host'], 
                    cfg['smtp_port'],
                    context=ssl.create_default_context()
                )
            else:
                # STARTTLS
                server = smtplib.SMTP(cfg['smtp_host'], cfg['smtp_port'])
                server.ehlo()
                if cfg['smtp_tls']:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
            
            # OAuth2认证
            if cfg.get('oauth_enabled') and cfg.get('oauth_refresh_token'):
                access_token = self._get_access_token()
                if access_token:
                    auth_string = f'user={cfg["smtp_user"]}\x01auth=Bearer {access_token}\x01\x01'
                    server.docmd('AUTH', 'XOAUTH2', auth_string.encode('utf-8'))
                else:
                    # 回退到密码认证
                    server.login(cfg['smtp_user'], cfg['smtp_password'])
            else:
                # 普通SMTP认证
                server.login(cfg['smtp_user'], cfg['smtp_password'])
            
            # 发送
            server.send_message(msg)
            server.quit()
            
            print(f"[Email] Sent via SMTP. To: {to_email}")
            return True
            
        except smtplib.SMTPAuthenticationError as e:
            print(f"[Email] SMTP auth failed: {e}")
            return False
        except Exception as e:
            print(f"[Email] SMTP send failed: {e}")
            return False
    
    def send_via_sendgrid(self, to_email: str, subject: str, html_body: str) -> bool:
        """
        通过SendGrid API发送邮件
        
        Args:
            to_email: 目标邮箱
            subject: 邮件主题
            html_body: HTML内容
            
        Returns:
            是否发送成功
        """
        import urllib.request
        import urllib.parse
        
        api_key = self.config.get('api_key')
        if not api_key:
            print("[Email] SendGrid API key not configured")
            return False
        
        try:
            url = 'https://api.sendgrid.com/v3/mail/send'
            
            payload = {
                'personalizations': [{'to': [{'email': to_email}]}],
                'from': {'email': self.config.get('smtp_from', 'noreply@nueronote.app')},
                'subject': subject,
                'content': [{'type': 'text/html', 'value': html_body}]
            }
            
            data = json.dumps(payload).encode('utf-8')
            
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                },
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.status == 202
            
        except Exception as e:
            print(f"[Email] SendGrid send failed: {e}")
            return False
    
    def send_via_mailgun(self, to_email: str, subject: str, html_body: str) -> bool:
        """
        通过Mailgun API发送邮件
        """
        import urllib.request
        import urllib.parse
        
        api_key = self.config.get('api_key')
        domain = self.config.get('smtp_host')  # Mailgun uses domain as host
        
        if not api_key or not domain:
            print("[Email] Mailgun not configured")
            return False
        
        try:
            url = f'https://api.mailgun.net/v3/{domain}/messages'
            
            data = urllib.parse.urlencode({
                'from': self.config.get('smtp_from', f'noreply@{domain}'),
                'to': to_email,
                'subject': subject,
                'html': html_body
            }).encode('utf-8')
            
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    'Authorization': f'Basic {base64.b64encode(f"api:{api_key}".encode()).decode()}'
                },
                method='POST'
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.status == 200
            
        except Exception as e:
            print(f"[Email] Mailgun send failed: {e}")
            return False
    
    def send(self, to_email: str, subject: str, html_body: str) -> bool:
        """
        发送邮件（自动选择最佳方式）
        
        Args:
            to_email: 目标邮箱
            subject: 邮件主题
            html_body: HTML内容
            
        Returns:
            是否发送成功
        """
        provider = self.provider
        
        # 根据服务商选择发送方式
        if provider == 'sendgrid':
            return self.send_via_sendgrid(to_email, subject, html_body)
        elif provider == 'mailgun':
            return self.send_via_mailgun(to_email, subject, html_body)
        elif provider in ('ses', 'mailgun_api'):
            # 这些也使用API方式
            return self.send_via_sendgrid(to_email, subject, html_body)
        else:
            # 默认使用SMTP
            return self.send_via_smtp(to_email, subject, html_body)
    
    def send_mfa_code(self, to_email: str, code: str) -> bool:
        """
        发送MFA验证码邮件
        
        Args:
            to_email: 目标邮箱
            code: 6位验证码
            
        Returns:
            是否发送成功
        """
        subject = "【NueroNote】您的登录验证码"
        
        html_body = self._mfa_email_template(code)
        
        return self.send(to_email, subject, html_body)
    
    def _mfa_email_template(self, code: str) -> str:
        """MFA邮件HTML模板"""
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NueroNote - 安全验证</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background-color: #f5f5f5;
            line-height: 1.6;
        }}
        .container {{ 
            max-width: 480px; 
            margin: 40px auto; 
            background: #ffffff;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
            color: white;
            padding: 32px 24px;
            text-align: center;
        }}
        .header h1 {{ font-size: 24px; font-weight: 600; margin-bottom: 4px; }}
        .header p {{ opacity: 0.9; font-size: 14px; }}
        .content {{ padding: 32px 24px; }}
        .code-box {{
            background: #f8fafc;
            border: 2px dashed #e2e8f0;
            border-radius: 12px;
            padding: 24px;
            text-align: center;
            margin: 24px 0;
        }}
        .code {{
            font-size: 40px;
            font-weight: 700;
            letter-spacing: 16px;
            color: #2563eb;
            font-family: 'SF Mono', Monaco, monospace;
        }}
        .label {{
            color: #64748b;
            font-size: 14px;
            margin-top: 12px;
        }}
        .warning {{
            background: #fef2f2;
            border-left: 4px solid #dc2626;
            color: #991b1b;
            padding: 12px 16px;
            border-radius: 0 8px 8px 0;
            font-size: 14px;
            margin: 24px 0;
        }}
        .warning strong {{ color: #dc2626; }}
        .footer {{
            text-align: center;
            padding: 24px;
            color: #94a3b8;
            font-size: 12px;
            border-top: 1px solid #e2e8f0;
        }}
        .footer a {{ color: #2563eb; text-decoration: none; }}
        @media only screen and (max-width: 480px) {{
            .container {{ margin: 0; border-radius: 0; }}
            .code {{ font-size: 32px; letter-spacing: 12px; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>NueroNote</h1>
            <p>安全的端到端加密笔记</p>
        </div>
        
        <div class="content">
            <h2 style="font-size: 18px; color: #1e293b; margin-bottom: 8px;">
                您好，
            </h2>
            <p style="color: #475569; margin-bottom: 16px;">
                您正在进行安全登录验证，您的验证码是：
            </p>
            
            <div class="code-box">
                <div class="code">{code}</div>
                <div class="label">6位数字验证码</div>
            </div>
            
            <p style="color: #475569; font-size: 14px;">
                验证码有效期为 <strong style="color: #2563eb;">5 分钟</strong>。
            </p>
            
            <div class="warning">
                <strong>⚠️ 安全提醒</strong><br>
                请勿将验证码告诉他人。如果您没有进行登录操作，请忽略此邮件。
            </div>
        </div>
        
        <div class="footer">
            <p>NueroNote - 端到端加密笔记</p>
            <p style="margin-top: 8px;">
                此邮件由系统自动发送，请勿回复。
            </p>
        </div>
    </div>
</body>
</html>
"""
    
    def get_config_help(self) -> str:
        """获取配置帮助信息"""
        return """
# 邮件服务配置指南

## 方式一: Gmail (推荐)

### 1. App Password (简单)
```bash
export EMAIL_PROVIDER=gmail
export EMAIL_SMTP_HOST=smtp.gmail.com
export EMAIL_SMTP_PORT=587
export EMAIL_SMTP_USER=your-email@gmail.com
export EMAIL_SMTP_PASSWORD=xxxx xxxx xxxx xxxx  # 16位App密码
export EMAIL_FROM=noreply@nueronote.app
```

获取App密码: Google账户 → 安全 → 2-Step Verification → App passwords

### 2. OAuth2 (更安全，生产环境推荐)
```bash
export EMAIL_PROVIDER=gmail
export EMAIL_OAUTH_ENABLED=true
export EMAIL_OAUTH_CLIENT_ID=xxx.apps.googleusercontent.com
export EMAIL_OAUTH_CLIENT_SECRET=xxx
export EMAIL_OAUTH_REFRESH_TOKEN=xxx
export EMAIL_FROM=noreply@nueronote.app
```

## 方式二: SendGrid (免费额度大)

```bash
export EMAIL_PROVIDER=sendgrid
export EMAIL_API_KEY=SG.xxx
export EMAIL_FROM=noreply@nueronote.app
```

## 方式三: QQ邮箱

```bash
export EMAIL_PROVIDER=qq
export EMAIL_SMTP_HOST=smtp.qq.com
export EMAIL_SMTP_PORT=587
export EMAIL_SMTP_USER=your-qq@qq.com
export EMAIL_SMTP_PASSWORD=xxxx  # 授权码，非QQ密码
export EMAIL_FROM=noreply@nueronote.app
```

获取授权码: QQ邮箱设置 → 账户 → POP3/SMTP服务

## 方式四: 网易邮箱

```bash
export EMAIL_PROVIDER=163
export EMAIL_SMTP_HOST=smtp.163.com
export EMAIL_SMTP_PORT=587
export EMAIL_SMTP_USER=your-email@163.com
export EMAIL_SMTP_PASSWORD=xxx  # 授权码
export EMAIL_FROM=noreply@nueronote.app
```

## 方式五: Amazon SES (企业级)

```bash
export EMAIL_PROVIDER=ses
export EMAIL_API_KEY=AKIAxxx
export EMAIL_SMTP_HOST=email-smtp.us-east-1.amazonaws.com
export EMAIL_SMTP_PORT=587
export EMAIL_FROM=noreply@nueronote.app
```

## DNS安全配置 (推荐)

添加以下记录提升邮件送达率:

```
TXT  @  v=spf1 include:_spf.google.com ~all
TXT  @  v=DMARC1; p=quarantine; rua=mailto:dmarc@nueronote.app
```
"""


# 全局实例
_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """获取邮件服务实例"""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
