"""Stellar Drift v2 — Flask-SocketIO game server."""
import os
import time
import uuid
import json
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

# =============================================================================
# APP SETUP
# =============================================================================

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "stellar-drift-v2-dev-key-2025")
CORS(app, resources={r"/*": {"origins": "*"}})

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="eventlet",
    ping_interval=25,
    ping_timeout=60,
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
    # Inject game config data into the page
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
    room = str(uuid.uuid4())
    session["room"] = room
    join_room(room)
    state = start_new_run(room)
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
    room = data.get("room")
    if room and room in rooms:
        join_room(room)
        session["room"] = room
        state = rooms[room]
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
    if not room or room not in rooms:
        return
    state = rooms[room]
    if state["status"] != "playing":
        emit("state_update", {"state": get_client_state(state)})
        return

    node_id = data.get("node_id", "N1")
    gained = tap_node(state, node_id)
    _recalculate_rates(state)

    emit("state_update", {
        "state": get_client_state(state),
        "tap_result": {"node_id": node_id, "gained": gained},
    })

@socketio.on("place_building")
def on_place_building(data):
    room = session.get("room")
    if not room or room not in rooms:
        return
    state = rooms[room]

    socket_id = data.get("socket_id")
    building_id = data.get("building_id")

    success, msg = place_building(state, socket_id, building_id)

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

    emit("state_update", {
        "state": get_client_state(state),
        "action_result": {"action": "launch", "success": success, "message": msg},
    })

# =============================================================================
# TICK LOOP — server-authoritative simulation
# =============================================================================

def run_tick_loop():
    """Background loop running the server simulation tick."""
    last_tick = time.time()
    TICK_SEC = TICK_INTERVAL_MS / 1000.0
    while True:
        now = time.time()
        elapsed = now - last_tick
        if elapsed >= TICK_SEC:
            last_tick = now - (elapsed - TICK_SEC)  # don't drift
            for room, state in list(rooms.items()):
                if state["status"] == "playing":
                    do_tick(room, TICK_SEC)
                    # Broadcast state to room
                    socketio.emit("state_update", {"state": get_client_state(state)}, room=room)

# Start tick loop in background thread
import threading
tick_thread = threading.Thread(target=run_tick_loop, daemon=True)
tick_thread.start()

# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False)
