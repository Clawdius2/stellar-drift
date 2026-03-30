"""Stellar Drift v2 — Flask-SocketIO game server. v3: gunicorn+gevent"""
import os
import time
import uuid
import json
import gevent
from flask import Flask, render_template, request, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS

from config.balance import TICK_INTERVAL_MS
from config.buildings import BUILDINGS
from config.techs import TECHS
from config.rocket import ROCKET_PARTS
from game.state import (
    new_game_state, place_building, research_tech,
    build_rocket_part, launch_rocket, tap_node,
    check_oxygen_warnings, _recalculate_rates,
    get_client_state, can_afford,
)
from game.simulation import get_or_create_session, start_new_run, get_session, do_tick
from config.database import save_state

# =============================================================================
# APP SETUP
# =============================================================================

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "stellar-drift-v2-dev-key-2025")
CORS(app, resources={r"/*": {"origins": "*"}})

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    ping_interval=25,
    ping_timeout=60,
    message_queue=os.environ.get("REDIS_URL", None),
)

# Active game rooms: {room_id: game_state}
rooms = {}

# =============================================================================
# WEB ROUTES
# =============================================================================

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/game")
def game():
    return render_template("game.html",
        buildings_json=json.dumps(BUILDINGS),
        techs_json=json.dumps(TECHS),
        rocket_json=json.dumps(ROCKET_PARTS),
    )

# =============================================================================
# SOCKET.IO — GAME EVENTS
# =============================================================================

@socketio.on("connect")
def on_connect():
    sid = request.sid
    # Restore existing room from DB if it exists, otherwise create new
    room = session.get("room") or str(uuid.uuid4())
    session["room"] = room
    join_room(room)
    # get_or_create_session restores from PostgreSQL if the server restarted
    state = get_or_create_session(room)
    rooms[room] = state
    emit("init", {"room": room, "state": get_client_state(state)})
    print(f"[connect] sid={sid} room={room}")

@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    room = session.get("room")
    if room:
        leave_room(room)
        rooms.pop(room, None)
    print(f"[disconnect] sid={sid} room={room}")

@socketio.on("reconnect")
def on_reconnect(data):
    # Always restore from DB on reconnect — the rooms dict was wiped if the
    # server restarted, but PostgreSQL still has our game state.
    room = data.get("room") or session.get("room")
    if room:
        session["room"] = room
        join_room(room)
        state = get_or_create_session(room)  # restores from DB if needed
        rooms[room] = state
        emit("init", {"room": room, "state": get_client_state(state)})
    else:
        on_connect()

@socketio.on("new_run")
def on_new_run(data):
    room = session.get("room")
    if room:
        state = start_new_run(room)
        rooms[room] = state
        emit("state_update", {"state": get_client_state(state)})

@socketio.on("tap")
def on_tap(data):
    room = session.get("room")
    node_id = data.get("node_id", "N1")
    print(f"[tap] room={room!r} rooms={list(rooms.keys())} node={node_id}")
    if not room or room not in rooms:
        print(f"[tap] FAIL: room missing")
        return
    state = rooms[room]
    print(f"[tap] status={state['status']}")
    if state["status"] != "playing":
        emit("state_update", {"state": get_client_state(state)})
        return

    gained = tap_node(state, node_id)
    _recalculate_rates(state)
    print(f"[tap] gained={gained}, ore now={state['resources']['ore']}")

    save_state(room, state)
    emit("state_update", {
        "state": get_client_state(state),
        "tap_result": {"node_id": node_id, "gained": gained},
    })

@app.route("/api/place_building", methods=["POST"])
def http_place_building():
    """HTTP fallback when Socket.IO fails — e.g. due to WebSocket blocked by extensions."""
    from flask import jsonify
    room = session.get("room")
    if not room or room not in rooms:
        return jsonify({"success": False, "message": "No active room"}), 400

    import json
    data = json.loads(request.data or "{}")
    socket_id = data.get("socket_id")
    building_id = data.get("building_id")

    state = rooms[room]
    success, msg = place_building(state, socket_id, building_id)
    if success:
        save_state(room, state)
    return jsonify({
        "success": success,
        "message": msg,
        "state": get_client_state(state),
    })

@socketio.on("place_building")
def on_place_building(data):
    print(f"[place_building] data={data}, session.room={session.get('room')}")
    room = session.get("room")
    if not room or room not in rooms:
        print("[place_building] no room or room not in rooms")
        return
    state = rooms[room]

    socket_id = data.get("socket_id")
    building_id = data.get("building_id")
    print(f"[place_building] socket_id={socket_id}, building_id={building_id}")

    success, msg = place_building(state, socket_id, building_id)
    print(f"[place_building] success={success}, msg={msg}")

    if success:
        save_state(room, state)
    emit("state_update", {
        "state": get_client_state(state),
        "action_result": {"action": "place_building", "success": success, "message": msg},
    })

@socketio.on("research")
def on_research(data):
    room = session.get("room")
    if not room or room not in rooms:
        return
    state = rooms[room]

    tech_id = data.get("tech_id")
    success, msg = research_tech(state, tech_id)
    if success:
        save_state(room, state)

    emit("state_update", {
        "state": get_client_state(state),
        "action_result": {"action": "research", "success": success, "message": msg},
    })

@socketio.on("build_rocket_part")
def on_build_rocket_part(data):
    room = session.get("room")
    if not room or room not in rooms:
        return
    state = rooms[room]

    part_id = data.get("part_id")
    success, msg = build_rocket_part(state, part_id)
    if success:
        save_state(room, state)

    emit("state_update", {
        "state": get_client_state(state),
        "action_result": {"action": "rocket_part", "success": success, "message": msg},
    })

@socketio.on("launch")
def on_launch(data):
    room = session.get("room")
    if not room or room not in rooms:
        return
    state = rooms[room]

    success, msg = launch_rocket(state)
    if success:
        save_state(room, state)

    emit("state_update", {
        "state": get_client_state(state),
        "action_result": {"action": "launch", "success": success, "message": msg},
    })

# =============================================================================
# TICK LOOP — server-authoritative simulation (gevent greenlet)
# =============================================================================

def _tick_loop():
    """Run simulation ticks every TICK_INTERVAL_MS and broadcast state."""
    TICK_SEC = TICK_INTERVAL_MS / 1000.0
    last_tick = time.time()
    while True:
        now = time.time()
        elapsed = now - last_tick
        if elapsed >= TICK_SEC:
            # Correct for drift
            last_tick = now - (elapsed - TICK_SEC)
            global _save_counter
            # Copy keys to avoid dict changed size during iteration
            for room in list(rooms.keys()):
                state = rooms.get(room)
                if state and state["status"] == "playing":
                    do_tick(room, TICK_SEC)
                    socketio.emit("state_update", {"state": get_client_state(state)}, room=room)
            # Periodic persistence — saves all active rooms every _SAVE_INTERVAL ticks
            _save_counter += 1
            if _save_counter >= _SAVE_INTERVAL:
                _save_counter = 0
                for room, state in list(rooms.items()):
                    if state and state["status"] == "playing":
                        save_state(room, state)
        gevent.sleep(0.02)  # sleep 20ms between iterations (50 checks/sec max)

# Start tick greenlet when the module is loaded (works for both `python app.py` and gunicorn)
_tick_greenlet = gevent.spawn(_tick_loop)

# Periodic save — persist all active rooms every 30 ticks (~30s)
_save_counter = 0
_SAVE_INTERVAL = 30

# =============================================================================
# MAIN  (only used when running directly with `python app.py`)
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False)
