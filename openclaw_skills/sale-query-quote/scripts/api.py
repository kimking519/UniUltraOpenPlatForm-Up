#!/usr/bin/env python3
"""
报价查询 API 服务
启动后用 curl 调用：
  curl "http://localhost:8765/query?cli_name=EPL&days=7"

通过 openclaw_bridge 接口操作数据库，无直接SQL语句。
"""

import os
import sys
from datetime import datetime, timedelta
from flask import Flask, request, jsonify

# 设置项目根目录
PROJECT_ROOT = os.environ.get('UNIULTRA_PROJECT_ROOT',
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
sys.path.insert(0, PROJECT_ROOT)

# 导入桥接层
from openclaw_bridge import get_db_connection, get_cli_id_by_name

app = Flask(__name__)


def query_quotes_data(cli_name, start_date, end_date):
    """返回 JSON 格式的查询结果"""
    try:
        cli_id = get_cli_id_by_name(cli_name)
        if not cli_id:
            return {"data": [], "count": 0}

        with get_db_connection() as conn:
            sql = """
            SELECT o.offer_date, o.offer_id, c.cli_name,
                   o.quoted_mpn, o.quoted_brand, o.quoted_qty,
                   o.date_code, o.delivery_date, o.remark
            FROM uni_offer o
            LEFT JOIN uni_quote q ON o.quote_id = q.quote_id
            LEFT JOIN uni_cli c ON q.cli_id = c.cli_id
            WHERE q.cli_id = ? AND o.offer_date BETWEEN ? AND ?
            ORDER BY o.offer_date DESC, o.created_at DESC
            """

            rows = conn.execute(sql, (cli_id, start_date, end_date)).fetchall()

            results = []
            for row in rows:
                results.append({
                    "date": str(row['offer_date']) if row['offer_date'] else "",
                    "offer_id": str(row['offer_id']) if row['offer_id'] else "",
                    "cli_name": str(row['cli_name']) if row['cli_name'] else "",
                    "quoted_mpn": str(row['quoted_mpn']) if row['quoted_mpn'] else "",
                    "quoted_brand": str(row['quoted_brand']) if row['quoted_brand'] else "",
                    "quoted_qty": str(row['quoted_qty']) if row['quoted_qty'] is not None else "",
                    "date_code": str(row['date_code']) if row['date_code'] else "",
                    "delivery_date": str(row['delivery_date']) if row['delivery_date'] else "",
                    "remark": str(row['remark']) if row['remark'] else ""
                })

            return {"data": results, "count": len(results)}

    except Exception as e:
        return {"error": f"数据库执行错误: {e}"}


def parse_date_range():
    """解析请求参数中的日期范围"""
    today = datetime.now().date()

    if request.args.get('start_date') and request.args.get('end_date'):
        return request.args.get('start_date'), request.args.get('end_date')

    if request.args.get('days'):
        days = int(request.args.get('days'))
        start = today - timedelta(days=days)
        return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")

    if request.args.get('date'):
        d = request.args.get('date')
        return d, d

    return today.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


@app.route('/query')
def query():
    cli_name = request.args.get('cli_name', '')
    if not cli_name:
        return jsonify({"error": "缺少参数 cli_name"})

    start_date, end_date = parse_date_range()
    result = query_quotes_data(cli_name, start_date, end_date)
    return jsonify(result)


@app.route('/health')
def health():
    return jsonify({"status": "ok"})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8765, debug=False)