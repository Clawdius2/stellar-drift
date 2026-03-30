"""PostgreSQL persistence for game state — uses Railway's attached DB (fully persistent)."""
import json
import os
import threading
import psycopg2
from psycopg2 import pool

# Railway provides DATABASE_URL pointing to a persistent PostgreSQL instance.
# Fall back to localhost for local dev.
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://localhost/stellar_drift")
_db_pool = None
_pool_lock = threading.Lock()

def _get_pool():
    """Lazy-init thread-safe connection pool."""
    global _db_pool
    if _db_pool is None:
        with _pool_lock:
            if _db_pool is None:
                _db_pool = pool.ThreadedConnectionPool(1, 10, DATABASE_URL)
    return _db_pool

def init_db():
    """Create tables if they don't exist."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS game_state (
                room       TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.commit()
        cur.close()
    finally:
        pool.putconn(conn)

def save_state(room, state):
    """Atomically upsert state JSON to DB. Call after every mutation."""
    import time
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO game_state (room, state_json, updated_at)
               VALUES (%s, %s, %s)
               ON CONFLICT (room) DO UPDATE SET state_json = EXCLUDED.state_json, updated_at = EXCLUDED.updated_at""",
            (room, json.dumps(state), time.time()),
        )
        conn.commit()
        cur.close()
    finally:
        pool.putconn(conn)

def load_state(room):
    """Load state JSON from DB, or None if not found."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT state_json FROM game_state WHERE room = %s", (room,))
        row = cur.fetchone()
        cur.close()
        if row:
            return json.loads(row[0])
        return None
    finally:
        pool.putconn(conn)

def delete_state(room):
    """Delete a room from DB (on new_run)."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM game_state WHERE room = %s", (room,))
        conn.commit()
        cur.close()
    finally:
        pool.putconn(conn)

# Initialize on module load
init_db()
