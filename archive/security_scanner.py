#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 安全扫描工具
检测常见安全漏洞和配置问题。

用法:
    python3 security_scanner.py
    python3 security_scanner.py --report json
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional


@dataclass
class SecurityFinding:
    """安全问题"""
    severity: str  # HIGH, MEDIUM, LOW, INFO
    category: str   # e.g., "SQL Injection", "XSS", "Hardcoded Secret"
    file: str
    line: int
    message: str
    code: str = ""
    recommendation: str = ""


class SecurityScanner:
    """安全扫描器"""
    
    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.findings: List[SecurityFinding] = []
        
        # 扫描规则
        self.rules = [
            # 硬编码密钥
            {
                "pattern": r'["\']?(SECRET|PASSWORD|API_KEY|TOKEN|PRIVATE_KEY)["\']?\s*[=:]\s*["\'][^"\']{8,}["\']',
                "severity": "HIGH",
                "category": "Hardcoded Secret",
                "message": "发现可能的硬编码密钥",
                "recommendation": "使用环境变量或安全的密钥管理系统"
            },
            # SQL注入风险（简单检测）
            {
                "pattern": r'\.execute\s*\(\s*["\'].*\%|format\(|["\'].*\.format\(|["\'].*\+.*["\']',
                "severity": "MEDIUM",
                "category": "SQL Injection",
                "message": "可能存在SQL注入风险",
                "recommendation": "使用参数化查询"
            },
            # eval使用
            {
                "pattern": r'\beval\s*\(',
                "severity": "HIGH",
                "category": "Code Injection",
                "message": "发现eval()使用，可能导致代码注入",
                "recommendation": "避免使用eval，考虑ast.literal_eval"
            },
            # pickle.loads
            {
                "pattern": r'pickle\.loads?\s*\(',
                "severity": "HIGH",
                "category": "Deserialization",
                "message": "发现pickle使用，可能存在反序列化漏洞",
                "recommendation": "使用JSON或自定义安全序列化"
            },
            # 调试模式开启
            {
                "pattern": r'DEBUG\s*=\s*True',
                "severity": "LOW",
                "category": "Configuration",
                "message": "发现DEBUG模式开启",
                "recommendation": "生产环境应关闭DEBUG模式"
            },
            # 弱随机数
            {
                "pattern": r'random\.(random|randint|choice)\s*\(',
                "severity": "MEDIUM",
                "category": "Weak Random",
                "message": "使用弱随机数生成器",
                "recommendation": "加密用途使用secrets模块"
            },
            # 硬编码IP
            {
                "pattern": r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
                "severity": "LOW",
                "category": "Hardcoded Config",
                "message": "发现硬编码IP地址",
                "recommendation": "使用配置文件或环境变量"
            },
            # 缺少CSRF保护（Flask）
            {
                "pattern": r'@app\.route.*methods\s*=\s*\[["\']POST["\']',
                "severity": "MEDIUM",
                "category": "CSRF",
                "message": "POST路由可能缺少CSRF保护",
                "recommendation": "添加CSRF令牌验证"
            },
        ]
    
    def scan_file(self, file_path: Path) -> List[SecurityFinding]:
        """扫描单个文件"""
        findings = []
        
        if not file_path.is_file():
            return findings
        
        # 只扫描Python文件
        if file_path.suffix != '.py':
            return findings
        
        # 跳过测试和虚拟环境
        skip_dirs = {'venv', '.venv', '__pycache__', '.git', 'tests', 'node_modules'}
        if any(d in file_path.parts for d in skip_dirs):
            return findings
        
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
            lines = content.split('\n')
            
            for i, line in enumerate(lines, 1):
                for rule in self.rules:
                    pattern = rule["pattern"]
                    if re.search(pattern, line, re.IGNORECASE):
                        finding = SecurityFinding(
                            severity=rule["severity"],
                            category=rule["category"],
                            file=str(file_path.relative_to(self.project_root)),
                            line=i,
                            message=rule["message"],
                            code=line.strip()[:100],
                            recommendation=rule["recommendation"]
                        )
                        findings.append(finding)
                        
        except Exception as e:
            pass  # 跳过无法读取的文件
        
        return findings
    
    def scan_directory(self, directory: Path) -> List[SecurityFinding]:
        """扫描目录"""
        all_findings = []
        
        for file_path in directory.rglob('*.py'):
            findings = self.scan_file(file_path)
            all_findings.extend(findings)
        
        return all_findings
    
    def scan(self) -> List[SecurityFinding]:
        """执行扫描"""
        print(f"开始安全扫描: {self.project_root}")
        print("-" * 60)
        
        self.findings = self.scan_directory(self.project_root)
        
        return self.findings
    
    def print_report(self):
        """打印报告"""
        if not self.findings:
            print("✅ 未发现安全问题!")
            return
        
        # 按严重级别分组
        by_severity = {"HIGH": [], "MEDIUM": [], "LOW": [], "INFO": []}
        for f in self.findings:
            by_severity[f.severity].append(f)
        
        # 打印摘要
        print(f"\n发现 {len(self.findings)} 个问题:")
        print(f"  🔴 HIGH: {len(by_severity['HIGH'])}")
        print(f"  🟡 MEDIUM: {len(by_severity['MEDIUM'])}")
        print(f"  🟢 LOW: {len(by_severity['LOW'])}")
        print(f"  🔵 INFO: {len(by_severity['INFO'])}")
        
        print()
        
        # 打印HIGH问题详情
        if by_severity['HIGH']:
            print("🔴 高危问题 (需要立即修复):")
            print("-" * 60)
            for f in by_severity['HIGH'][:10]:  # 最多显示10个
                print(f"  [{f.category}] {f.file}:{f.line}")
                print(f"    {f.message}")
                print(f"    代码: {f.code}")
                print(f"    建议: {f.recommendation}")
                print()
        
        # 打印MEDIUM问题
        if by_severity['MEDIUM']:
            print("🟡 中等问题 (建议修复):")
            print("-" * 60)
            for f in by_severity['MEDIUM'][:5]:
                print(f"  [{f.category}] {f.file}:{f.line}")
                print(f"    {f.message}")
                print()
        
        print("-" * 60)
        print("完整报告请使用: python security_scanner.py --report json")
    
    def to_json(self) -> str:
        """导出JSON报告"""
        report = {
            "scan_time": datetime.now().isoformat(),
            "project_root": str(self.project_root),
            "total_findings": len(self.findings),
            "findings": [
                {
                    "severity": f.severity,
                    "category": f.category,
                    "file": f.file,
                    "line": f.line,
                    "message": f.message,
                    "code": f.code,
                    "recommendation": f.recommendation,
                }
                for f in self.findings
            ],
        }
        return json.dumps(report, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="NueroNote 安全扫描工具")
    parser.add_argument("--root", default="nueronote_server",
                        help="扫描目录")
    parser.add_argument("--report", choices=["text", "json"], default="text",
                        help="报告格式")
    
    args = parser.parse_args()
    
    # 确定项目根目录
    script_dir = Path(__file__).parent.parent
    scan_root = script_dir / args.root
    
    if not scan_root.exists():
        print(f"错误: 目录不存在 {scan_root}")
        sys.exit(1)
    
    # 执行扫描
    scanner = SecurityScanner(scan_root)
    scanner.scan()
    
    # 输出报告
    if args.report == "json":
        print(scanner.to_json())
    else:
        scanner.print_report()
        
        # 根据结果返回退出码
        high_count = sum(1 for f in scanner.findings if f.severity == "HIGH")
        if high_count > 0:
            sys.exit(1)


if __name__ == "__main__":
    main()
