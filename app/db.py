import sqlite3
from contextlib import contextmanager

DB_PATH = "app/store.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        store_id TEXT,
        camera_id TEXT,
        visitor_id TEXT,
        event_type TEXT,
        timestamp TEXT,
        zone_id TEXT,
        dwell_ms INTEGER,
        is_staff INTEGER,
        confidence REAL
    )
    """)
    conn.commit()
    conn.close()

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()