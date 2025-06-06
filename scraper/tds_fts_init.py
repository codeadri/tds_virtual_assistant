#tds_fts_init.py

import sqlite3

# Create a separate FTS-enabled database
conn = sqlite3.connect("tds_virtual_ta_fts.db")
cursor = conn.cursor()

# Create FTS5 virtual table (if not already exists)
cursor.execute("""
CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
    url,
    description,
    content,
    tokenize = 'porter'
)
""")

conn.commit()
conn.close()
print("FTS-enabled database 'tds_virtual_ta_fts.db' with table 'content_fts' created successfully.")

