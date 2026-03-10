import sqlite3
from Sills.base import get_db_connection

def get_cli_list(page=1, page_size=10, search_kw=""):
    offset = (page - 1) * page_size
    query = """
    SELECT * FROM uni_cli 
    WHERE cli_name LIKE ? OR region LIKE ? OR cli_id LIKE ?
    ORDER BY created_at DESC
    LIMIT ? OFFSET ?
    """
    count_query = "SELECT COUNT(*) FROM uni_cli WHERE cli_name LIKE ? OR region LIKE ? OR cli_id LIKE ?"
    params = (f"%{search_kw}%", f"%{search_kw}%", f"%{search_kw}%")
    
    with get_db_connection() as conn:
        total = conn.execute(count_query, params).fetchone()[0]
        items = conn.execute(query, params + (page_size, offset)).fetchall()
        
        results = [
            {k: ("" if v is None else v) for k, v in dict(row).items()}
            for row in items
        ]
        return results, total

def get_next_cli_id():
    with get_db_connection() as conn:
        row = conn.execute("SELECT MAX(cli_id) FROM uni_cli").fetchone()
        if row and row[0]:
            # Assuming format like C001
            num_part = ''.join(filter(str.isdigit, row[0]))
            next_num = int(num_part) + 1 if num_part else 1
            return f"C{next_num:03d}"
        return "C001"

def add_cli(data):
    try:
        if 'cli_id' not in data or not data['cli_id']:
            data['cli_id'] = get_next_cli_id()
            
        # Defaults
        if 'region' not in data or not data['region']:
            data['region'] = '韩国'
        if 'credit_level' not in data or not data['credit_level']:
            data['credit_level'] = 'A'
        if 'margin_rate' not in data or not str(data['margin_rate']).strip():
            data['margin_rate'] = 10.0
            
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['?'] * len(data))
        sql = f"INSERT INTO uni_cli ({columns}) VALUES ({placeholders})"
        
        with get_db_connection() as conn:
            conn.execute(sql, list(data.values()))
            conn.commit()
            return True, f"客户 {data['cli_id']} 添加成功"
    except Exception as e:
        return False, str(e)

def batch_import_cli_text(text):
    lines = text.strip().split('\n')
    success_count = 0
    errors = []
    for line in lines:
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 1: continue
        
        data = {
            "cli_name": parts[0],
            "region": parts[1] if len(parts) > 1 else "韩国",
            "credit_level": parts[2] if len(parts) > 2 else "A",
            "margin_rate": parts[3] if len(parts) > 3 else 10.0,
            "emp_id": parts[4] if len(parts) > 4 else "000",
            "website": parts[5] if len(parts) > 5 else "",
            "payment_terms": parts[6] if len(parts) > 6 else "",
            "email": parts[7] if len(parts) > 7 else "",
            "phone": parts[8] if len(parts) > 8 else "",
            "remark": parts[9] if len(parts) > 9 else ""
        }
        ok, msg = add_cli(data)
        if ok: success_count += 1
        else: errors.append(f"{parts[0]}: {msg}")
    
    return success_count, errors

def update_cli(cli_id, data):
    try:
        set_cols = []
        params = []
        for k, v in data.items():
            set_cols.append(f"{k} = ?")
            params.append(v)
        
        params.append(cli_id)
        sql = f"UPDATE uni_cli SET {(', '.join(set_cols))} WHERE cli_id = ?"
        
        with get_db_connection() as conn:
            conn.execute(sql, params)
            conn.commit()
            return True, "更新成功"
    except Exception as e:
        return False, str(e)

def delete_cli(cli_id):
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM uni_cli WHERE cli_id = ?", (cli_id,))
            conn.commit()
            return True, "删除成功"
    except Exception as e:
        return False, str(e)
