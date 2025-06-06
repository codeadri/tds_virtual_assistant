import sqlite3
conn = sqlite3.connect("tds_virtual_ta.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT,
    title TEXT,
    description TEXT,
    source_url TEXT,
    scraped_at TEXT
)
""")
conn.commit()
conn.close()
