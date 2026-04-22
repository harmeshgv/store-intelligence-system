import sqlite3
from contextlib import contextmanager

DB_PATH = "app/store.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Create table (new DB case)
    c.execute("""
    CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        store_id TEXT NOT NULL,
        camera_id TEXT NOT NULL,
        visitor_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        zone_id TEXT,
        dwell_ms INTEGER NOT NULL DEFAULT 0,
        is_staff INTEGER NOT NULL DEFAULT 0,
        confidence REAL NOT NULL DEFAULT 0.0,
        metadata TEXT
    )
    """)
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_store_time ON events(store_id, timestamp)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_store_visitor ON events(store_id, visitor_id)"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_store_type ON events(store_id, event_type)"
    )

    # Migration (old DB case)
    c.execute("PRAGMA table_info(events)")
    columns = [row[1] for row in c.fetchall()]

    if "metadata" not in columns:
        print("[DB] Adding metadata column...")
        c.execute("ALTER TABLE events ADD COLUMN metadata TEXT")

    conn.commit()
    conn.close()

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()