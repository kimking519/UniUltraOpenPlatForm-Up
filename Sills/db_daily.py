from Sills.base import get_db_connection

def get_daily_list(page=1, page_size=10):
    offset = (page - 1) * page_size
    with get_db_connection() as conn:
        total = conn.execute("SELECT COUNT(*) FROM uni_daily").fetchone()[0]
        items = conn.execute("""
            SELECT * FROM uni_daily 
            ORDER BY id ASC 
            LIMIT ? OFFSET ?
        """, (page_size, offset)).fetchall()
        return [dict(row) for row in items], total

def add_daily(record_date, currency_code, exchange_rate):
    try:
        with get_db_connection() as conn:
            conn.execute("""
                INSERT INTO uni_daily (record_date, currency_code, exchange_rate)
                VALUES (?, ?, ?)
            """, (record_date, currency_code, exchange_rate))
            conn.commit()
            return True, "成功添加"
    except Exception as e:
        return False, str(e)

def update_daily(id, exchange_rate):
    try:
        with get_db_connection() as conn:
            conn.execute("""
                UPDATE uni_daily SET exchange_rate = ? WHERE id = ?
            """, (exchange_rate, id))
            conn.commit()
            return True, "更新成功"
    except Exception as e:
        return False, str(e)
