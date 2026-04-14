#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 最终验收测试
全面测试所有功能模块，确保系统就绪。

用法:
    python3 test_acceptance.py
    python3 test_acceptance.py --verbose
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import requests


@dataclass
class TestCase:
    """测试用例"""
    name: str
    category: str
    passed: bool
    duration_ms: float
    message: str
    details: Optional[Dict] = None


class AcceptanceTester:
    """验收测试器"""
    
    def __init__(self, base_url: str = "http://localhost:5000", verbose: bool = False):
        self.base_url = base_url.rstrip('/')
        self.verbose = verbose
        self.results: List[TestCase] = []
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self.test_user = None
        self.test_token = None
    
    def log(self, message: str, category: str = "INFO"):
        """日志输出"""
        markers = {
            "INFO": "ℹ️",
            "PASS": "✅",
            "FAIL": "❌",
            "WARN": "⚠️",
        }
        marker = markers.get(category, "•")
        print(f"  {marker} {message}")
    
    def run_test(self, name: str, category: str, test_func) -> TestCase:
        """运行单个测试"""
        start = time.time()
        passed = False
        message = ""
        details = None
        
        try:
            result = test_func()
            if isinstance(result, tuple):
                passed, message, details = result
            elif isinstance(result, dict):
                passed = result.get("passed", False)
                message = result.get("message", "")
                details = result.get("details")
            else:
                passed = bool(result)
                message = "通过" if passed else "失败"
        except Exception as e:
            message = f"错误: {str(e)}"
            passed = False
        
        duration = (time.time() - start) * 1000
        
        test_case = TestCase(
            name=name,
            category=category,
            passed=passed,
            duration_ms=duration,
            message=message,
            details=details
        )
        
        self.results.append(test_case)
        
        status = "PASS" if passed else "FAIL"
        self.log(f"{name}: {message} ({duration:.0f}ms)", status)
        
        return test_case
    
    # ==================== API测试 ====================
    
    def test_health_check(self) -> TestCase:
        """测试健康检查"""
        return self.run_test("健康检查", "API", lambda: self._test_health())
    
    def test_api_info(self) -> TestCase:
        """测试API信息端点"""
        return self.run_test("API信息", "API", lambda: self._test_api_info())
    
    def test_cloud_providers(self) -> TestCase:
        """测试云服务商列表"""
        return self.run_test("云服务商列表", "API", lambda: self._test_cloud_providers())
    
    def _test_health(self) -> tuple:
        resp = self.session.get(f"{self.base_url}/health", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return True, f"服务正常 (版本: {data.get('version')})", data
        return False, f"状态码: {resp.status_code}", None
    
    def _test_api_info(self) -> tuple:
        resp = self.session.get(f"{self.base_url}/api/v1", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return True, f"API版本: {data.get('api')}", data
        return False, f"状态码: {resp.status_code}", None
    
    def _test_cloud_providers(self) -> tuple:
        resp = self.session.get(f"{self.base_url}/api/v1/cloud/providers", timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            providers = data.get("providers", [])
            return True, f"支持{len(providers)}个云服务商", {"providers": len(providers)}
        return False, f"状态码: {resp.status_code}", None
    
    # ==================== 认证测试 ====================
    
    def test_register(self) -> TestCase:
        """测试用户注册"""
        return self.run_test("用户注册", "认证", lambda: self._test_register())
    
    def test_login(self) -> TestCase:
        """测试用户登录"""
        return self.run_test("用户登录", "认证", lambda: self._test_login())
    
    def test_invalid_login(self) -> TestCase:
        """测试错误登录"""
        return self.run_test("错误登录拒绝", "认证", lambda: self._test_invalid_login())
    
    def _test_register(self) -> tuple:
        email = f"test_{int(time.time())}@acceptance.com"
        password = "TestPassword123!"
        
        resp = self.session.post(
            f"{self.base_url}/api/v1/auth/register",
            json={"email": email, "password": password},
            timeout=10
        )
        
        if resp.status_code in (201, 409):
            data = resp.json()
            self.test_user = email
            if "token" in data:
                self.test_token = data["token"]
            return True, f"用户 {email} 注册成功", {"email": email}
        return False, f"状态码: {resp.status_code}, {resp.json()}", None
    
    def _test_login(self) -> tuple:
        if not self.test_user:
            self._test_register()
        
        resp = self.session.post(
            f"{self.base_url}/api/v1/auth/login",
            json={"email": self.test_user, "password": "TestPassword123!"},
            timeout=10
        )
        
        if resp.status_code == 200:
            data = resp.json()
            if "token" in data:
                self.test_token = data["token"]
            return True, "登录成功", {"has_token": bool(self.test_token)}
        return False, f"状态码: {resp.status_code}", None
    
    def _test_invalid_login(self) -> tuple:
        resp = self.session.post(
            f"{self.base_url}/api/v1/auth/login",
            json={"email": "invalid@test.com", "password": "wrong"},
            timeout=10
        )
        
        if resp.status_code == 401:
            return True, "正确拒绝无效凭证", None
        return False, f"应返回401,实际: {resp.status_code}", None
    
    # ==================== 账户测试 ====================
    
    def test_account_info(self) -> TestCase:
        """测试获取账户信息"""
        return self.run_test("账户信息查询", "账户", lambda: self._test_account_info())
    
    def test_account_upgrade(self) -> TestCase:
        """测试套餐升级"""
        return self.run_test("套餐升级", "账户", lambda: self._test_account_upgrade())
    
    def _test_account_info(self) -> tuple:
        if not self.test_token:
            return False, "未认证，跳过", None
        
        resp = self.session.get(
            f"{self.base_url}/api/v1/account/",
            headers={"Authorization": f"Bearer {self.test_token}"},
            timeout=10
        )
        
        if resp.status_code == 200:
            data = resp.json()
            return True, f"邮箱: {data.get('email')}", data
        return False, f"状态码: {resp.status_code}", None
    
    def _test_account_upgrade(self) -> tuple:
        if not self.test_token:
            return False, "未认证，跳过", None
        
        resp = self.session.post(
            f"{self.base_url}/api/v1/account/upgrade",
            json={"plan": "pro"},
            headers={"Authorization": f"Bearer {self.test_token}"},
            timeout=10
        )
        
        if resp.status_code == 200:
            data = resp.json()
            return True, f"升级到 {data.get('plan')}", data
        return False, f"状态码: {resp.status_code}", None
    
    # ==================== 同步测试 ====================
    
    def test_sync_status(self) -> TestCase:
        """测试同步状态"""
        return self.run_test("同步状态查询", "同步", lambda: self._test_sync_status())
    
    def test_sync_push(self) -> TestCase:
        """测试同步推送"""
        return self.run_test("同步推送", "同步", lambda: self._test_sync_push())
    
    def test_sync_pull(self) -> TestCase:
        """测试同步拉取"""
        return self.run_test("同步拉取", "同步", lambda: self._test_sync_pull())
    
    def _test_sync_status(self) -> tuple:
        if not self.test_token:
            return False, "未认证，跳过", None
        
        resp = self.session.get(
            f"{self.base_url}/api/v1/sync/status",
            headers={"Authorization": f"Bearer {self.test_token}"},
            timeout=10
        )
        
        if resp.status_code == 200:
            return True, "同步状态正常", resp.json()
        return False, f"状态码: {resp.status_code}", None
    
    def _test_sync_push(self) -> tuple:
        if not self.test_token:
            return False, "未认证，跳过", None
        
        resp = self.session.post(
            f"{self.base_url}/api/v1/sync/push",
            json={"records": [{"record_id": "test_1", "operation": "upsert"}]},
            headers={"Authorization": f"Bearer {self.test_token}"},
            timeout=10
        )
        
        if resp.status_code == 200:
            return True, f"推送{resp.json().get('pushed')}条记录", resp.json()
        return False, f"状态码: {resp.status_code}", None
    
    def _test_sync_pull(self) -> tuple:
        if not self.test_token:
            return False, "未认证，跳过", None
        
        resp = self.session.get(
            f"{self.base_url}/api/v1/sync/pull",
            headers={"Authorization": f"Bearer {self.test_token}"},
            timeout=10
        )
        
        if resp.status_code == 200:
            data = resp.json()
            return True, f"拉取{len(data.get('records', []))}条记录", data
        return False, f"状态码: {resp.status_code}", None
    
    # ==================== 运行所有测试 ====================
    
    def run_all_tests(self) -> bool:
        """运行所有测试"""
        print("=" * 70)
        print("NueroNote 最终验收测试")
        print("=" * 70)
        print(f"测试目标: {self.base_url}")
        print()
        
        # API测试
        print("\n📡 API测试")
        self.test_health_check()
        self.test_api_info()
        self.test_cloud_providers()
        
        # 认证测试
        print("\n🔐 认证测试")
        self.test_register()
        self.test_login()
        self.test_invalid_login()
        
        # 账户测试
        print("\n👤 账户测试")
        self.test_account_info()
        self.test_account_upgrade()
        
        # 同步测试
        print("\n🔄 同步测试")
        self.test_sync_status()
        self.test_sync_push()
        self.test_sync_pull()
        
        return self._print_summary()
    
    def _print_summary(self) -> bool:
        """打印测试摘要"""
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        failed = total - passed
        total_time = sum(r.duration_ms for r in self.results)
        
        print("\n" + "=" * 70)
        print("测试结果摘要")
        print("=" * 70)
        
        # 按类别统计
        categories = {}
        for r in self.results:
            if r.category not in categories:
                categories[r.category] = {"passed": 0, "failed": 0}
            if r.passed:
                categories[r.category]["passed"] += 1
            else:
                categories[r.category]["failed"] += 1
        
        print(f"\n{'类别':<15} {'通过':<10} {'失败':<10} {'总计':<10}")
        print("-" * 45)
        for category, stats in categories.items():
            print(f"{category:<15} {stats['passed']:<10} {stats['failed']:<10} {stats['passed'] + stats['failed']:<10}")
        
        print("-" * 70)
        print(f"总计: {passed}/{total} 通过 ({passed/total*100:.1f}%)")
        print(f"总耗时: {total_time:.0f}ms")
        
        # 失败测试详情
        if failed > 0:
            print(f"\n❌ 失败测试 ({failed}):")
            for r in self.results:
                if not r.passed:
                    print(f"  - {r.category}/{r.name}: {r.message}")
        
        print("=" * 70)
        
        # 性能评级
        avg_time = total_time / total if total > 0 else 0
        if failed == 0:
            if avg_time < 100:
                grade = "A (优秀)"
            elif avg_time < 300:
                grade = "B (良好)"
            else:
                grade = "C (一般)"
        else:
            grade = "D (需修复)"
        
        print(f"\n性能评级: {grade}")
        print("=" * 70)
        
        return failed == 0


def main():
    parser = argparse.ArgumentParser(description="NueroNote 最终验收测试")
    parser.add_argument("--url", default="http://localhost:5000",
                       help="API基础URL")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="详细输出")
    
    args = parser.parse_args()
    
    tester = AcceptanceTester(base_url=args.url, verbose=args.verbose)
    success = tester.run_all_tests()
    
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
