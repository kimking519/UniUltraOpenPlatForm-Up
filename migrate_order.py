import sqlite3
conn = sqlite3.connect(r'e:\7_AI_APP\UniUltraOpenPlatForm\uni_platform.db')
cur = conn.cursor()
commands = [
    "ALTER TABLE uni_order ADD COLUMN inquiry_mpn TEXT;",
    "ALTER TABLE uni_order ADD COLUMN inquiry_brand TEXT;",
    "UPDATE uni_order SET offer_id = NULL WHERE offer_id = '';"
]
for cmd in commands:
    try:
        cur.execute(cmd)
        print(f"Success: {cmd}")
    except Exception as e:
        print(f"Skipped/Error: {cmd} -> {e}")
conn.commit()
conn.close()
print('Migration attempt completed')
