import sqlite3
from Sills.base import get_db_connection

def get_next_vendor_id():
    with get_db_connection() as conn:
        row = conn.execute("SELECT MAX(vendor_id) FROM uni_vendor").fetchone()
        if row and row[0]:
            # Assuming format like V001
            num_part = ''.join(filter(str.isdigit, row[0]))
            next_num = int(num_part) + 1 if num_part else 1
            return f"V{next_num:03d}"
        return "V001"

def add_vendor(data):
    try:
        if 'vendor_id' not in data or not data['vendor_id']:
            data['vendor_id'] = get_next_vendor_id()
            
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['?'] * len(data))
        sql = f"INSERT INTO uni_vendor ({columns}) VALUES ({placeholders})"
        
        with get_db_connection() as conn:
            conn.execute(sql, list(data.values()))
            conn.commit()
            return True, f"供应商 {data['vendor_id']} 添加成功"
    except Exception as e:
        return False, str(e)

def batch_import_vendor_text(text):
    lines = text.strip().split('\n')
    success_count = 0
    errors = []
    for line in lines:
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 1: continue
        
        data = {
            "vendor_name": parts[0],
            "address": parts[1] if len(parts) > 1 else "",
            "qq": parts[2] if len(parts) > 2 else "",
            "wechat": parts[3] if len(parts) > 3 else "",
            "email": parts[4] if len(parts) > 4 else "",
            "remark": parts[5] if len(parts) > 5 else ""
        }
        ok, msg = add_vendor(data)
        if ok: success_count += 1
        else: errors.append(f"{parts[0]}: {msg}")
    
    return success_count, errors

def update_vendor(vendor_id, data):
    try:
        set_cols = []
        params = []
        for k, v in data.items():
            set_cols.append(f"{k} = ?")
            params.append(v)
        
        params.append(vendor_id)
        sql = f"UPDATE uni_vendor SET {(', '.join(set_cols))} WHERE vendor_id = ?"
        
        with get_db_connection() as conn:
            conn.execute(sql, params)
            conn.commit()
            return True, "更新成功"
    except Exception as e:
        return False, str(e)

def delete_vendor(vendor_id):
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM uni_vendor WHERE vendor_id = ?", (vendor_id,))
            conn.commit()
            return True, "删除成功"
    except Exception as e:
        return False, str(e)
