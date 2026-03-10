#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的 HTTP API 服务
用法: python3 server.py
查询: curl "http://localhost:8765/api/query?cli_name=XXX&days=7"

通过 openclaw_bridge 接口操作数据库，无直接SQL语句。
"""

import json
import os
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

# 设置项目根目录
PROJECT_ROOT = os.environ.get('UNIULTRA_PROJECT_ROOT',
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, PROJECT_ROOT)

# 导入桥接层
from openclaw_bridge import get_db_connection, get_cli_id_by_name, DB_PATH


def query_needs(cli_name, days):
    """查询询价记录"""
    # 计算日期范围
    today = datetime.now()
    start_date = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    try:
        cli_id = get_cli_id_by_name(cli_name)
        if not cli_id:
            return {
                "success": True,
                "cli_name": cli_name,
                "date_range": f"{start_date} ~ {end_date}",
                "total": 0,
                "date_distribution": {},
                "records": []
            }

        with get_db_connection() as conn:
            query = """
            SELECT
                q.quote_id,
                q.quote_date,
                q.inquiry_mpn,
                q.quoted_mpn,
                q.inquiry_brand,
                q.inquiry_qty,
                q.target_price_rmb,
                q.date_code,
                q.delivery_date,
                q.status,
                q.is_transferred,
                c.cli_name
            FROM uni_quote q
            LEFT JOIN uni_cli c ON q.cli_id = c.cli_id
            WHERE q.cli_id = ?
              AND q.quote_date >= ?
              AND q.quote_date <= ?
            ORDER BY q.quote_date DESC, q.created_at DESC
            """

            rows = conn.execute(query, (cli_id, start_date, end_date)).fetchall()
            records = [dict(row) for row in rows]

            # 按日期分组
            date_counts = {}
            for r in records:
                dt = r.get('quote_date', '未知')
                date_counts[dt] = date_counts.get(dt, 0) + 1

            return {
                "success": True,
                "cli_name": records[0]['cli_name'] if records else cli_name,
                "date_range": f"{start_date} ~ {end_date}",
                "total": len(records),
                "date_distribution": date_counts,
                "records": records
            }

    except Exception as e:
        return {"success": False, "error": str(e)}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/query":
            params = parse_qs(parsed.query)
            cli_name = params.get("cli_name", [""])[0]
            days = int(params.get("days", ["7"])[0])

            if not cli_name:
                self.send_error(400, "Missing cli_name")
                return

            result = query_needs(cli_name, days)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result, ensure_ascii=False).encode())

        else:
            self.send_error(404, "Not Found")

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")


if __name__ == "__main__":
    print(f"数据库: {DB_PATH}")
    print("服务启动: http://localhost:8765")
    print("查询示例: curl 'http://localhost:8765/api/query?cli_name=EPL&days=7'")

    server = HTTPServer(("0.0.0.0", 8765), Handler)
    server.serve_forever()