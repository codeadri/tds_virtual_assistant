# sync_to_fts.py

import sqlite3
from datetime import datetime

# Paths to your databases
SOURCE_DB = "tds_virtual_ta.db"
FTS_DB = "tds_virtual_ta_fts.db"

# Connect to both databases
src_conn = sqlite3.connect(SOURCE_DB)
fts_conn = sqlite3.connect(FTS_DB)

src_cursor = src_conn.cursor()
fts_cursor = fts_conn.cursor()

# Ensure FTS table exists in destination
fts_cursor.execute("""
CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
    url,
    description,
    content,
    tokenize = 'porter'
)
""")

# Fetch all course content from the original database
src_cursor.execute("SELECT url, description, content FROM course_content")
rows = src_cursor.fetchall()

# Insert or update into the FTS database
for url, desc, content in rows:
    fts_cursor.execute("""
        INSERT INTO content_fts (url, description, content)
        VALUES (?, ?, ?)
    """, (url, desc, content))

fts_conn.commit()
src_conn.close()
fts_conn.close()

print(f"[{datetime.now().isoformat()}] Synced {len(rows)} records to 'content_fts' in tds_virtual_ta_fts.db")
