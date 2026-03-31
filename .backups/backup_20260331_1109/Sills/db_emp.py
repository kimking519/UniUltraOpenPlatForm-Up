import sqlite3
import hashlib
from Sills.base import get_db_connection

def hash_password(password):
    return hashlib.md5(password.encode()).hexdigest()

def get_next_emp_id():
    with get_db_connection() as conn:
        row = conn.execute("SELECT MAX(emp_id) FROM uni_emp").fetchone()
        if row and row[0]:
            next_id = int(row[0]) + 1
            return f"{next_id:03d}"
        return "001"

def get_emp_list(page=1, page_size=10, search=""):
    offset = (page - 1) * page_size
    query = "SELECT * FROM uni_emp"
    params = []
    if search:
        query += " WHERE emp_name LIKE ? OR account LIKE ?"
        params.extend([f"%{search}%", f"%{search}%"])
    
    query += " ORDER BY emp_id ASC LIMIT ? OFFSET ?"
    params.extend([page_size, offset])
    
    with get_db_connection() as conn:
        items = conn.execute(query, params).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM uni_emp").fetchone()[0]
        results = [
            {k: ("" if v is None else v) for k, v in dict(row).items()}
            for row in items
        ]
        return results, total

def add_employee(data):
    # data is a dict containing all fields except emp_id
    try:
        emp_id = get_next_emp_id()
        data['emp_id'] = emp_id
        data['password'] = hash_password(data.get('password', '12345'))
        data['rule'] = data.get('rule', '1') # Default to read-only if not provided or empty
        
        columns = ', '.join(data.keys())
        placeholders = ', '.join(['?'] * len(data))
        sql = f"INSERT INTO uni_emp ({columns}) VALUES ({placeholders})"
        
        with get_db_connection() as conn:
            conn.execute(sql, list(data.values()))
            conn.commit()
            return True, f"员工 {emp_id} 添加成功"
    except Exception as e:
        return False, str(e)

def batch_import_text(text):
    lines = text.strip().split('\n')
    success_count = 0
    errors = []
    for line in lines:
        parts = [p.strip() for p in line.split(',')]
        if len(parts) < 4: continue # min: name, account, password, rule
        
        data = {
            "emp_name": parts[0],
            "account": parts[1],
            "password": parts[2] if parts[2] else '12345',
            "rule": parts[3] if parts[3] else '1',
            "department": parts[4] if len(parts) > 4 else "",
            "position": parts[5] if len(parts) > 5 else "",
            "contact": parts[6] if len(parts) > 6 else ""
        }
        ok, msg = add_employee(data)
        if ok: success_count += 1
        else: errors.append(f"{parts[0]}: {msg}")
    
    return success_count, errors

def verify_login(account, password):
    with get_db_connection() as conn:
        user = conn.execute("SELECT * FROM uni_emp WHERE account = ?", (account,)).fetchone()
        if not user:
            return False, None, "账号不存在"
        if user['rule'] == '4':
            return False, None, "此账号被限制登录"
        if user['password'] != hash_password(password):
            return False, None, "密码错误"
        return True, dict(user), "登录成功"

def change_password(emp_id, new_password):
    with get_db_connection() as conn:
        conn.execute("UPDATE uni_emp SET password = ? WHERE emp_id = ?", (hash_password(new_password), emp_id))
        conn.commit()
        return True, "密码修改成功"

def update_employee(emp_id, data):
    try:
        set_cols = []
        params = []
        for k, v in data.items():
            set_cols.append(f"{k} = ?")
            params.append(v)
        
        params.append(emp_id)
        sql = f"UPDATE uni_emp SET {(', '.join(set_cols))} WHERE emp_id = ?"
        
        with get_db_connection() as conn:
            conn.execute(sql, params)
            conn.commit()
            return True, "更新成功"
    except Exception as e:
        return False, str(e)

def delete_employee(emp_id):
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM uni_emp WHERE emp_id = ?", (emp_id,))
            conn.commit()
            return True, "删除成功"
    except Exception as e:
        return False, str(e)
