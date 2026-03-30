"""SQLite persistence for game state — survives Railway redeploys."""
import sqlite3
import json
import os
import threading
from functools import wraps

DB_PATH = os.environ.get("DATABASE_PATH", "/var/data/stellar_drift.db")
_db_lock = threading.Lock()

def _get_db():
    """Thread-safe DB connection."""
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create tables if they don't exist."""
    conn = _get_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS game_state (
                room       TEXT PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.commit()
    finally:
        conn.close()

def save_state(room, state):
    """Atomically save state JSON to DB (upsert). Call after every mutation."""
    import time
    conn = _get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO game_state (room, state_json, updated_at) VALUES (?, ?, ?)",
            (room, json.dumps(state), time.time()),
        )
        conn.commit()
    finally:
        conn.close()

def load_state(room):
    """Load state JSON from DB, or None if not found."""
    conn = _get_db()
    try:
        row = conn.execute(
            "SELECT state_json FROM game_state WHERE room = ?", (room,)
        ).fetchone()
        if row:
            return json.loads(row["state_json"])
        return None
    finally:
        conn.close()

def delete_state(room):
    """Delete a room from DB (on new_run)."""
    conn = _get_db()
    try:
        conn.execute("DELETE FROM game_state WHERE room = ?", (room,))
        conn.commit()
    finally:
        conn.close()

# Initialize on module load
init_db()
