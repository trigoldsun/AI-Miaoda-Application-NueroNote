#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NueroNote 数据库连接池测试
测试不同并发级别下的数据库连接池表现。

用法:
    python3 test_connection_pool.py
    python3 test_connection_pool.py --threads 50 --iterations 100
"""

import argparse
import concurrent.futures
import sqlite3
import statistics
import sys
import time
from dataclasses import dataclass
from typing import List


@dataclass
class PoolTestResult:
    """连接池测试结果"""
    num_threads: int
    total_operations: int
    total_time: float
    throughput: float  # ops per second
    avg_latency: float
    min_latency: float
    max_latency: float
    p95_latency: float
    errors: int


class ConnectionPoolTester:
    """数据库连接池测试"""
    
    def __init__(self, db_path: str = "nueronote.db"):
        self.db_path = db_path
    
    def single_query(self, operation_num: int) -> float:
        """执行单个查询操作"""
        start = time.time()
        
        try:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.row_factory = sqlite3.Row
            
            # 执行多个查询
            cursor = conn.execute(
                "SELECT * FROM users LIMIT 10"
            )
            _ = cursor.fetchall()
            
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM sync_log"
            )
            _ = cursor.fetchone()
            
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM audit_log"
            )
            _ = cursor.fetchone()
            
            conn.close()
            
            return time.time() - start
            
        except Exception as e:
            return -1
    
    def test_pool(self, num_threads: int, iterations_per_thread: int) -> PoolTestResult:
        """测试连接池"""
        total_ops = num_threads * iterations_per_thread
        latencies = []
        errors = 0
        
        start_time = time.time()
        
        def worker(thread_id: int) -> List[float]:
            thread_latencies = []
            for i in range(iterations_per_thread):
                latency = self.single_query(thread_id * iterations_per_thread + i)
                if latency > 0:
                    thread_latencies.append(latency)
                else:
                    nonlocal errors
                    errors += 1
            return thread_latencies
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker, i) for i in range(num_threads)]
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    latencies.extend(future.result())
                except Exception:
                    errors += 1
        
        total_time = time.time() - start_time
        latencies.sort()
        
        if not latencies:
            return PoolTestResult(
                num_threads=num_threads,
                total_operations=total_ops,
                total_time=total_time,
                throughput=0,
                avg_latency=0,
                min_latency=0,
                max_latency=0,
                p95_latency=0,
                errors=errors,
            )
        
        n = len(latencies)
        
        return PoolTestResult(
            num_threads=num_threads,
            total_operations=total_ops,
            total_time=total_time,
            throughput=total_ops / total_time,
            avg_latency=statistics.mean(latencies),
            min_latency=min(latencies),
            max_latency=max(latencies),
            p95_latency=latencies[int(n * 0.95)],
            errors=errors,
        )
    
    def run_test_suite(self, thread_levels: List[int] = None,
                      iterations: int = 100) -> List[PoolTestResult]:
        """运行测试套件"""
        if thread_levels is None:
            thread_levels = [1, 5, 10, 20, 50]
        
        results = []
        
        print("=" * 70)
        print("NueroNote 数据库连接池性能测试")
        print("=" * 70)
        print(f"数据库: {self.db_path}")
        print(f"每个线程操作数: {iterations}")
        print()
        
        for num_threads in thread_levels:
            print(f"测试并发级别: {num_threads} 线程 ...", end=" ", flush=True)
            
            result = self.test_pool(num_threads, iterations)
            results.append(result)
            
            status = "✓" if result.errors == 0 else "⚠"
            print(f"{status} "
                  f"完成 {result.total_operations} 操作, "
                  f"耗时 {result.total_time:.2f}s, "
                  f"吞吐量 {result.throughput:.1f} ops/s, "
                  f"平均延迟 {result.avg_latency*1000:.1f}ms")
        
        return results
    
    def print_summary(self, results: List[PoolTestResult]):
        """打印测试摘要"""
        print()
        print("=" * 70)
        print("连接池性能测试摘要")
        print("=" * 70)
        print(f"{'线程数':<10} {'吞吐量':<15} {'平均延迟':<15} {'P95延迟':<15} {'错误数':<10}")
        print("-" * 70)
        
        for result in results:
            print(f"{result.num_threads:<10} "
                  f"{result.throughput:<15.1f} "
                  f"{result.avg_latency*1000:<15.1f} "
                  f"{result.p95_latency*1000:<15.1f} "
                  f"{result.errors:<10}")
        
        print()
        
        # 找出最佳并发级别
        best = max(results, key=lambda r: r.throughput)
        print(f"最佳并发级别: {best.num_threads} 线程 "
              f"(吞吐量 {best.throughput:.1f} ops/s)")
        
        # 性能趋势分析
        if len(results) >= 2:
            throughput_increase = (
                (results[-1].throughput - results[0].throughput) 
                / results[0].throughput * 100
            )
            print(f"吞吐量变化: {throughput_increase:+.1f}% "
                  f"(从 {results[0].num_threads} 到 {results[-1].num_threads} 线程)")
        
        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="NueroNote 连接池测试")
    parser.add_argument("--db", default="nueronote.db",
                        help="数据库文件路径")
    parser.add_argument("--threads", type=int, nargs="+",
                        default=[1, 5, 10, 20, 50],
                        help="测试的并发级别列表")
    parser.add_argument("--iterations", type=int, default=100,
                        help="每个线程的操作数")
    
    args = parser.parse_args()
    
    tester = ConnectionPoolTester(db_path=args.db)
    results = tester.run_test_suite(
        thread_levels=args.threads,
        iterations=args.iterations,
    )
    tester.print_summary(results)


if __name__ == "__main__":
    main()
