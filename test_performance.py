#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 性能测试套件
测试高并发场景下的系统表现。

用法:
    python3 test_performance.py
    python3 test_performance.py --concurrency 50 --requests 1000
"""

import argparse
import concurrent.futures
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional

import requests


@dataclass
class PerformanceResult:
    """性能测试结果"""
    endpoint: str
    total_requests: int
    success_count: int
    error_count: int
    min_latency: float = 0
    max_latency: float = 0
    avg_latency: float = 0
    median_latency: float = 0
    p95_latency: float = 0
    p99_latency: float = 0
    throughput: float = 0  # requests per second
    total_time: float = 0
    
    def to_dict(self):
        return {
            "endpoint": self.endpoint,
            "total_requests": self.total_requests,
            "success_count": self.success_count,
            "error_count": self.error_count,
            "min_latency_ms": round(self.min_latency * 1000, 2),
            "max_latency_ms": round(self.max_latency * 1000, 2),
            "avg_latency_ms": round(self.avg_latency * 1000, 2),
            "median_latency_ms": round(self.median_latency * 1000, 2),
            "p95_latency_ms": round(self.p95_latency * 1000, 2),
            "p99_latency_ms": round(self.p99_latency * 1000, 2),
            "throughput_rps": round(self.throughput, 2),
            "total_time_s": round(self.total_time, 2),
        }


class PerformanceTester:
    """性能测试器"""
    
    def __init__(self, base_url: str = "http://localhost:5000"):
        self.base_url = base_url.rstrip('/')
        self.results: List[PerformanceResult] = []
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
        })
    
    def register_test_user(self) -> Optional[str]:
        """注册测试用户并返回token"""
        email = f"perf_test_{int(time.time())}@test.com"
        password = "test_password_123"
        
        try:
            resp = self.session.post(
                f"{self.base_url}/api/v1/auth/register",
                json={"email": email, "password": password},
                timeout=10
            )
            if resp.status_code in (201, 409):
                # 尝试登录
                resp = self.session.post(
                    f"{self.base_url}/api/v1/auth/login",
                    json={"email": email, "password": password},
                    timeout=10
                )
                if resp.status_code == 200:
                    return resp.json().get("token")
        except Exception as e:
            print(f"注册测试用户失败: {e}")
        
        return None
    
    def make_request(self, method: str, endpoint: str, 
                    token: Optional[str] = None,
                    json_data: Optional[dict] = None) -> tuple:
        """
        发起请求并返回(成功,延迟)
        """
        start = time.time()
        url = f"{self.base_url}{endpoint}"
        
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        
        try:
            if method.upper() == "GET":
                resp = self.session.get(url, headers=headers, timeout=30)
            elif method.upper() == "POST":
                resp = self.session.post(url, headers=headers, json=json_data, timeout=30)
            elif method.upper() == "PUT":
                resp = self.session.put(url, headers=headers, json=json_data, timeout=30)
            else:
                return False, time.time() - start
            
            latency = time.time() - start
            return resp.status_code < 400, latency
            
        except Exception:
            return False, time.time() - start
    
    def test_endpoint(self, method: str, endpoint: str,
                     token: Optional[str] = None,
                     json_data: Optional[dict] = None,
                     num_requests: int = 100,
                     concurrency: int = 10) -> PerformanceResult:
        """测试单个端点的性能"""
        latencies = []
        success_count = 0
        error_count = 0
        
        def make_call():
            success, latency = self.make_request(method, endpoint, token, json_data)
            return success, latency
        
        start_time = time.time()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(make_call) for _ in range(num_requests)]
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    success, latency = future.result()
                    latencies.append(latency)
                    if success:
                        success_count += 1
                    else:
                        error_count += 1
                except Exception:
                    error_count += 1
        
        total_time = time.time() - start_time
        
        # 计算统计数据
        latencies.sort()
        n = len(latencies)
        
        result = PerformanceResult(
            endpoint=f"{method} {endpoint}",
            total_requests=num_requests,
            success_count=success_count,
            error_count=error_count,
            min_latency=min(latencies) if latencies else 0,
            max_latency=max(latencies) if latencies else 0,
            avg_latency=statistics.mean(latencies) if latencies else 0,
            median_latency=latencies[n//2] if latencies else 0,
            p95_latency=latencies[int(n * 0.95)] if latencies and n > 0 else 0,
            p99_latency=latencies[int(n * 0.99)] if latencies and n > 0 else 0,
            throughput=num_requests / total_time if total_time > 0 else 0,
            total_time=total_time,
        )
        
        self.results.append(result)
        return result
    
    def run_full_test(self, token: str, 
                    concurrency: int = 10,
                    requests_per_endpoint: int = 50) -> dict:
        """运行完整性能测试"""
        print("=" * 60)
        print("NueroNote 性能测试")
        print("=" * 60)
        print(f"基础URL: {self.base_url}")
        print(f"并发数: {concurrency}")
        print(f"每个端点请求数: {requests_per_endpoint}")
        print()
        
        test_cases = [
            ("GET", "/api/v1/health", None, None),
            ("GET", "/api/v1/cloud/providers", None, None),
            ("GET", "/api/v1/account/", token, None),
            ("GET", "/api/v1/sync/status", token, None),
            ("GET", "/api/v1/vault", token, None),
        ]
        
        all_results = []
        
        for method, endpoint, tok, json_data in test_cases:
            print(f"测试: {method} {endpoint} ...", end=" ", flush=True)
            
            result = self.test_endpoint(
                method=method,
                endpoint=endpoint,
                token=tok,
                json_data=json_data,
                num_requests=requests_per_endpoint,
                concurrency=concurrency,
            )
            
            status = "✓" if result.error_count == 0 else "⚠"
            print(f"{status} {result.success_count}/{result.total_requests} 成功, "
                  f"平均 {result.avg_latency*1000:.1f}ms, "
                  f"吞吐量 {result.throughput:.1f} rps")
            
            all_results.append(result)
        
        return {"results": [r.to_dict() for r in all_results]}
    
    def print_summary(self):
        """打印测试摘要"""
        print()
        print("=" * 60)
        print("性能测试摘要")
        print("=" * 60)
        
        for result in self.results:
            print(f"\n{result.endpoint}:")
            print(f"  请求数: {result.total_requests} "
                  f"(成功:{result.success_count} 失败:{result.error_count})")
            print(f"  延迟: 平均 {result.avg_latency*1000:.1f}ms, "
                  f"中位数 {result.median_latency*1000:.1f}ms, "
                  f"P95 {result.p95_latency*1000:.1f}ms, "
                  f"P99 {result.p99_latency*1000:.1f}ms")
            print(f"  吞吐量: {result.throughput:.1f} requests/s")
        
        print()
        
        # 计算总体统计
        total_requests = sum(r.total_requests for r in self.results)
        total_success = sum(r.success_count for r in self.results)
        total_errors = sum(r.error_count for r in self.results)
        avg_latency = statistics.mean([r.avg_latency for r in self.results])
        total_throughput = sum(r.throughput for r in self.results)
        
        print(f"总计: {total_requests} 请求 "
              f"(成功:{total_success} 失败:{total_errors})")
        print(f"平均延迟: {avg_latency*1000:.1f}ms")
        print(f"总吞吐量: {total_throughput:.1f} requests/s")
        
        # 性能评级
        if avg_latency < 0.1 and total_errors == 0:
            grade = "A (优秀)"
        elif avg_latency < 0.3 and total_errors < total_requests * 0.05:
            grade = "B (良好)"
        elif avg_latency < 0.5 and total_errors < total_requests * 0.1:
            grade = "C (一般)"
        else:
            grade = "D (需优化)"
        
        print(f"性能评级: {grade}")
        print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="NueroNote 性能测试")
    parser.add_argument("--url", default="http://localhost:5000",
                        help="API基础URL")
    parser.add_argument("--concurrency", type=int, default=10,
                        help="并发数")
    parser.add_argument("--requests", type=int, default=50,
                        help="每个端点的请求数")
    
    args = parser.parse_args()
    
    tester = PerformanceTester(base_url=args.url)
    
    # 注册测试用户
    print("注册测试用户...")
    token = tester.register_test_user()
    if not token:
        print("错误: 无法注册测试用户，请确保服务器正在运行")
        sys.exit(1)
    print(f"测试用户已注册，Token: {token[:20]}...")
    
    # 运行测试
    tester.run_full_test(
        token=token,
        concurrency=args.concurrency,
        requests_per_endpoint=args.requests,
    )
    
    # 打印摘要
    tester.print_summary()


if __name__ == "__main__":
    main()
