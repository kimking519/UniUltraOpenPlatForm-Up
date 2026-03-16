#!/usr/bin/env python3
"""
SQLite 数据库性能测试脚本
测试项目：写入、读取、更新、删除、批量操作、并发性能
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import sqlite3
import time
import os
import threading
import random
import string
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# 测试配置
TEST_CONFIG = {
    'db_path': 'performance_test.db',
    'single_insert_count': 1000,      # 单条插入测试数量
    'batch_insert_count': 10000,       # 批量插入测试数量
    'batch_size': 100,                 # 批量插入每批数量
    'select_count': 5000,              # 查询测试次数
    'update_count': 2000,              # 更新测试数量
    'delete_count': 1000,              # 删除测试数量
    'concurrent_threads': 5,           # 并发线程数
    'concurrent_ops_per_thread': 200,  # 每线程操作数
}

class PerformanceTester:
    def __init__(self, config):
        self.config = config
        self.results = {}
        self.test_data_ids = []

    def setup(self):
        """准备测试环境"""
        print("=" * 60)
        print("SQLite 数据库性能测试")
        print("=" * 60)
        print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"数据库路径: {self.config['db_path']}")
        print()

        # 删除旧测试数据库
        if os.path.exists(self.config['db_path']):
            os.remove(self.config['db_path'])
            print("已删除旧测试数据库")

        # 创建测试表
        conn = sqlite3.connect(self.config['db_path'])
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute('PRAGMA cache_size=-64000')  # 64MB cache

        conn.execute('''
            CREATE TABLE perf_test (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value REAL,
                category TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        conn.execute('CREATE INDEX idx_category ON perf_test(category)')
        conn.execute('CREATE INDEX idx_value ON perf_test(value)')

        conn.commit()
        conn.close()
        print("测试表创建完成\n")

    def cleanup(self):
        """清理测试环境"""
        if os.path.exists(self.config['db_path']):
            os.remove(self.config['db_path'])
            print("\n测试数据库已清理")

    def generate_random_string(self, length=20):
        """生成随机字符串"""
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

    def test_single_insert(self):
        """测试单条插入性能"""
        print("【1】单条插入测试")
        print(f"    插入 {self.config['single_insert_count']} 条记录...")

        conn = sqlite3.connect(self.config['db_path'])
        start_time = time.time()

        for i in range(self.config['single_insert_count']):
            conn.execute('''
                INSERT INTO perf_test (name, value, category, description)
                VALUES (?, ?, ?, ?)
            ''', (f'test_{i}', random.uniform(0, 1000), f'cat_{i % 10}', self.generate_random_string(50)))

        conn.commit()
        elapsed = time.time() - start_time
        conn.close()

        ops_per_sec = self.config['single_insert_count'] / elapsed
        self.results['单条插入'] = {
            'count': self.config['single_insert_count'],
            'time': elapsed,
            'ops_per_sec': ops_per_sec
        }
        print(f"    完成: {elapsed:.3f}秒, {ops_per_sec:.1f} ops/sec\n")

    def test_batch_insert(self):
        """测试批量插入性能"""
        print("【2】批量插入测试")
        print(f"    插入 {self.config['batch_insert_count']} 条记录 (每批 {self.config['batch_size']} 条)...")

        conn = sqlite3.connect(self.config['db_path'])
        start_time = time.time()

        batch_data = []
        for i in range(self.config['batch_insert_count']):
            batch_data.append((
                f'batch_{i}',
                random.uniform(0, 1000),
                f'cat_{i % 10}',
                self.generate_random_string(50)
            ))

            if len(batch_data) >= self.config['batch_size']:
                conn.executemany('''
                    INSERT INTO perf_test (name, value, category, description)
                    VALUES (?, ?, ?, ?)
                ''', batch_data)
                conn.commit()
                batch_data = []

        if batch_data:
            conn.executemany('''
                INSERT INTO perf_test (name, value, category, description)
                VALUES (?, ?, ?, ?)
            ''', batch_data)
            conn.commit()

        elapsed = time.time() - start_time
        conn.close()

        ops_per_sec = self.config['batch_insert_count'] / elapsed
        self.results['批量插入'] = {
            'count': self.config['batch_insert_count'],
            'time': elapsed,
            'ops_per_sec': ops_per_sec
        }
        print(f"    完成: {elapsed:.3f}秒, {ops_per_sec:.1f} ops/sec\n")

    def test_select(self):
        """测试查询性能"""
        print("【3】查询测试")
        print(f"    执行 {self.config['select_count']} 次查询...")

        conn = sqlite3.connect(self.config['db_path'])
        start_time = time.time()

        for i in range(self.config['select_count']):
            # 随机选择查询类型
            query_type = i % 4

            if query_type == 0:
                # 主键查询
                conn.execute('SELECT * FROM perf_test WHERE id = ?', (random.randint(1, 11000),)).fetchall()
            elif query_type == 1:
                # 索引查询
                conn.execute('SELECT * FROM perf_test WHERE category = ?', (f'cat_{random.randint(0, 9)}',)).fetchall()
            elif query_type == 2:
                # 范围查询
                conn.execute('SELECT * FROM perf_test WHERE value BETWEEN ? AND ?',
                           (random.uniform(0, 500), random.uniform(500, 1000))).fetchall()
            else:
                # 模糊查询
                conn.execute('SELECT * FROM perf_test WHERE name LIKE ?',
                           (f'%{random.randint(0, 100)}%',)).fetchall()

        elapsed = time.time() - start_time
        conn.close()

        ops_per_sec = self.config['select_count'] / elapsed
        self.results['查询'] = {
            'count': self.config['select_count'],
            'time': elapsed,
            'ops_per_sec': ops_per_sec
        }
        print(f"    完成: {elapsed:.3f}秒, {ops_per_sec:.1f} ops/sec\n")

    def test_update(self):
        """测试更新性能"""
        print("【4】更新测试")
        print(f"    执行 {self.config['update_count']} 次更新...")

        conn = sqlite3.connect(self.config['db_path'])
        start_time = time.time()

        for i in range(self.config['update_count']):
            record_id = random.randint(1, 11000)
            conn.execute('''
                UPDATE perf_test
                SET value = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            ''', (random.uniform(0, 1000), record_id))

            if i % 100 == 0:
                conn.commit()

        conn.commit()
        elapsed = time.time() - start_time
        conn.close()

        ops_per_sec = self.config['update_count'] / elapsed
        self.results['更新'] = {
            'count': self.config['update_count'],
            'time': elapsed,
            'ops_per_sec': ops_per_sec
        }
        print(f"    完成: {elapsed:.3f}秒, {ops_per_sec:.1f} ops/sec\n")

    def test_delete(self):
        """测试删除性能"""
        print("【5】删除测试")
        print(f"    执行 {self.config['delete_count']} 次删除...")

        conn = sqlite3.connect(self.config['db_path'])
        start_time = time.time()

        # 获取要删除的ID
        ids = conn.execute('SELECT id FROM perf_test ORDER BY RANDOM() LIMIT ?',
                          (self.config['delete_count'],)).fetchall()
        ids = [row[0] for row in ids]

        for record_id in ids:
            conn.execute('DELETE FROM perf_test WHERE id = ?', (record_id,))

        conn.commit()
        elapsed = time.time() - start_time
        conn.close()

        ops_per_sec = self.config['delete_count'] / elapsed
        self.results['删除'] = {
            'count': self.config['delete_count'],
            'time': elapsed,
            'ops_per_sec': ops_per_sec
        }
        print(f"    完成: {elapsed:.3f}秒, {ops_per_sec:.1f} ops/sec\n")

    def test_concurrent(self):
        """测试并发性能"""
        print("【6】并发测试")
        print(f"    {self.config['concurrent_threads']} 线程, 每线程 {self.config['concurrent_ops_per_thread']} 次操作...")

        results = {'success': 0, 'failed': 0, 'total_time': 0}

        def worker(thread_id):
            local_success = 0
            local_failed = 0
            start = time.time()

            try:
                conn = sqlite3.connect(self.config['db_path'], timeout=30)

                for i in range(self.config['concurrent_ops_per_thread']):
                    try:
                        op = random.randint(0, 3)

                        if op == 0:
                            # INSERT
                            conn.execute('''
                                INSERT INTO perf_test (name, value, category, description)
                                VALUES (?, ?, ?, ?)
                            ''', (f'concurrent_{thread_id}_{i}', random.uniform(0, 100),
                                  f'cat_{thread_id}', self.generate_random_string(30)))
                        elif op == 1:
                            # SELECT
                            conn.execute('SELECT * FROM perf_test WHERE category = ?',
                                       (f'cat_{random.randint(0, 9)}',)).fetchall()
                        elif op == 2:
                            # UPDATE
                            conn.execute('''
                                UPDATE perf_test SET value = ? WHERE id = ?
                            ''', (random.uniform(0, 1000), random.randint(1, 10000)))
                        else:
                            # DELETE
                            conn.execute('DELETE FROM perf_test WHERE id = ?',
                                       (random.randint(1, 10000),))

                        local_success += 1
                        if i % 50 == 0:
                            conn.commit()
                    except Exception as e:
                        local_failed += 1

                conn.commit()
                conn.close()
            except Exception as e:
                local_failed += self.config['concurrent_ops_per_thread'] - local_success

            return local_success, local_failed, time.time() - start

        start_time = time.time()

        with ThreadPoolExecutor(max_workers=self.config['concurrent_threads']) as executor:
            futures = [executor.submit(worker, i) for i in range(self.config['concurrent_threads'])]

            for future in as_completed(futures):
                success, failed, elapsed = future.result()
                results['success'] += success
                results['failed'] += failed

        elapsed = time.time() - start_time
        total_ops = results['success'] + results['failed']
        ops_per_sec = total_ops / elapsed

        self.results['并发'] = {
            'count': total_ops,
            'time': elapsed,
            'ops_per_sec': ops_per_sec,
            'success_rate': results['success'] / total_ops * 100
        }
        print(f"    完成: {elapsed:.3f}秒, {ops_per_sec:.1f} ops/sec")
        print(f"    成功率: {results['success']}/{total_ops} ({results['success']/total_ops*100:.1f}%)\n")

    def test_complex_query(self):
        """测试复杂查询性能"""
        print("【7】复杂查询测试")

        conn = sqlite3.connect(self.config['db_path'])

        # 统计当前记录数
        total_records = conn.execute('SELECT COUNT(*) FROM perf_test').fetchone()[0]
        print(f"    当前记录数: {total_records}")

        queries = [
            ('聚合查询', 'SELECT category, COUNT(*), AVG(value), SUM(value) FROM perf_test GROUP BY category'),
            ('排序查询', 'SELECT * FROM perf_test ORDER BY value DESC LIMIT 100'),
            ('连接查询(自连接)', 'SELECT a.*, b.name as related_name FROM perf_test a JOIN perf_test b ON a.category = b.category LIMIT 100'),
            ('子查询', 'SELECT * FROM perf_test WHERE value > (SELECT AVG(value) FROM perf_test)'),
        ]

        for name, query in queries:
            start_time = time.time()
            try:
                result = conn.execute(query).fetchall()
                elapsed = time.time() - start_time
                print(f"    {name}: {elapsed:.3f}秒, 返回 {len(result)} 条记录")

                if name not in self.results:
                    self.results[name] = {}
                self.results[name] = {'time': elapsed, 'rows': len(result)}
            except Exception as e:
                print(f"    {name}: 错误 - {str(e)}")

        conn.close()
        print()

    def generate_report(self):
        """生成测试报告"""
        print("=" * 60)
        print("性能测试报告")
        print("=" * 60)
        print()

        # 表格头
        print(f"{'测试项目':<15} {'操作数':>10} {'耗时(秒)':>12} {'ops/sec':>12} {'备注':>15}")
        print("-" * 65)

        for test_name, data in self.results.items():
            count = data.get('count', '-')
            time_val = data.get('time', '-')
            ops = data.get('ops_per_sec', '-')

            if isinstance(ops, float):
                ops_str = f"{ops:.1f}"
            else:
                ops_str = str(ops)

            if isinstance(time_val, float):
                time_str = f"{time_val:.3f}"
            else:
                time_str = str(time_val)

            note = ''
            if 'success_rate' in data:
                note = f"成功率 {data['success_rate']:.1f}%"

            print(f"{test_name:<15} {count:>10} {time_str:>12} {ops_str:>12} {note:>15}")

        print("-" * 65)
        print()

        # 性能评级
        print("性能评级:")
        insert_ops = self.results.get('单条插入', {}).get('ops_per_sec', 0)
        batch_ops = self.results.get('批量插入', {}).get('ops_per_sec', 0)
        select_ops = self.results.get('查询', {}).get('ops_per_sec', 0)

        def rate_performance(ops, thresholds):
            if ops >= thresholds[0]:
                return '优秀'
            elif ops >= thresholds[1]:
                return '良好'
            elif ops >= thresholds[2]:
                return '一般'
            else:
                return '较慢'

        print(f"  单条插入: {rate_performance(insert_ops, [5000, 2000, 500])} ({insert_ops:.1f} ops/sec)")
        print(f"  批量插入: {rate_performance(batch_ops, [50000, 20000, 5000])} ({batch_ops:.1f} ops/sec)")
        print(f"  查询性能: {rate_performance(select_ops, [10000, 5000, 1000])} ({select_ops:.1f} ops/sec)")
        print()

        # 保存报告到文件
        report_path = 'performance_test_report.txt'
        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write("SQLite 数据库性能测试报告\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"数据库: {self.config['db_path']}\n\n")

            f.write(f"{'测试项目':<15} {'操作数':>10} {'耗时(秒)':>12} {'ops/sec':>12}\n")
            f.write("-" * 50 + "\n")

            for test_name, data in self.results.items():
                count = data.get('count', '-')
                time_val = data.get('time', '-')
                ops = data.get('ops_per_sec', '-')

                if isinstance(ops, float):
                    ops_str = f"{ops:.1f}"
                else:
                    ops_str = str(ops)

                if isinstance(time_val, float):
                    time_str = f"{time_val:.3f}"
                else:
                    time_str = str(time_val)

                f.write(f"{test_name:<15} {count:>10} {time_str:>12} {ops_str:>12}\n")

            f.write("\n配置参数:\n")
            for key, value in self.config.items():
                f.write(f"  {key}: {value}\n")

        print(f"报告已保存到: {report_path}")

    def run_all_tests(self):
        """运行所有测试"""
        self.setup()

        try:
            self.test_single_insert()
            self.test_batch_insert()
            self.test_select()
            self.test_update()
            self.test_delete()
            self.test_concurrent()
            self.test_complex_query()

            self.generate_report()
        finally:
            self.cleanup()


if __name__ == '__main__':
    tester = PerformanceTester(TEST_CONFIG)
    tester.run_all_tests()