import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "uni_platform.db")

def migrate():
    print(f"Connecting to {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 检查字段是否存在
    cursor.execute("PRAGMA table_info(uni_quote)")
    columns = [row[1] for row in cursor.fetchall()]
    
    new_cols = [
        ("date_code", "TEXT"),
        ("delivery_date", "TEXT"),
        ("status", "TEXT DEFAULT '询价中'")
    ]
    
    for col_name, col_type in new_cols:
        if col_name not in columns:
            print(f"Adding column {col_name} to uni_quote...")
            cursor.execute(f"ALTER TABLE uni_quote ADD COLUMN {col_name} {col_type}")
        else:
            print(f"Column {col_name} already exists.")
            
    conn.commit()
    conn.close()
    print("Migration completed.")

if __name__ == "__main__":
    migrate()
