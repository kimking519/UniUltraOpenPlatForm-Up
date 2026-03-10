import sqlite3
import os

def upgrade_db():
    db_paths = ["uni_platform.db", "uni_platform_dev.db"]
    for db_path in db_paths:
        if not os.path.exists(db_path):
            print(f"Skipping {db_path}, not found.")
            continue
            
        print(f"Upgrading {db_path}...")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 获取现有列
        cursor.execute("PRAGMA table_info(uni_order)")
        columns = [col[1] for col in cursor.fetchall()]
        
        new_cols = [
            ("order_no", "TEXT"),
            ("price_rmb", "REAL"),
            ("price_kwr", "REAL"),
            ("price_usd", "REAL"),
            ("cost_price_rmb", "REAL"),
            ("return_status", "TEXT DEFAULT '正常'")
        ]
        
        for col_name, col_type in new_cols:
            if col_name not in columns:
                try:
                    cursor.execute(f"ALTER TABLE uni_order ADD COLUMN {col_name} {col_type}")
                    print(f"Added column {col_name} to uni_order.")
                except Exception as e:
                    print(f"Error adding {col_name}: {e}")
                    
        # 获取现有 offer 列
        cursor.execute("PRAGMA table_info(uni_offer)")
        offer_columns = [col[1] for col in cursor.fetchall()]
        
        offer_new_cols = [
            ("price_kwr", "REAL"),
            ("price_usd", "REAL")
        ]
        
        for col_name, col_type in offer_new_cols:
            if col_name not in offer_columns:
                try:
                    cursor.execute(f"ALTER TABLE uni_offer ADD COLUMN {col_name} {col_type}")
                    print(f"Added column {col_name} to uni_offer.")
                except Exception as e:
                    print(f"Error adding {col_name} to uni_offer: {e}")
        
        conn.commit()
        conn.close()
        print(f"Done upgrading {db_path}.")

if __name__ == "__main__":
    upgrade_db()
