"""Server-side simulation sessions — persisted to SQLite."""
from game.state import (
    new_game_state, tick as sim_tick,
    check_oxygen_warnings,
)
from config.database import save_state, load_state, delete_state

# In-memory cache: {room_id: state}
_sessions = {}


def get_or_create_session(room):
    if room not in _sessions:
        # Try to restore from DB first
        persisted = load_state(room)
        if persisted:
            _sessions[room] = persisted
        else:
            _sessions[room] = new_game_state(room)
    return _sessions[room]


def start_new_run(room):
    """Start a fresh run, deleting any persisted state for this room."""
    delete_state(room)
    _sessions[room] = new_game_state(room)
    save_state(room, _sessions[room])
    return _sessions[room]


def get_session(room):
    return _sessions.get(room)


def do_tick(room, delta_seconds):
    state = _sessions.get(room)
    if not state or state["status"] != "playing":
        return None
    sim_tick(state, delta_seconds)
    check_oxygen_warnings(state)
    return state
