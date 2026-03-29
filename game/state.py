"""Server-authoritative game state model."""
import uuid
import time
import random
from config.balance import (
    STARTING_RESOURCES, STARTING_RATES, STARTING_SOCKETS,
    STARTING_VISIBLE_NODES, CRIT_CHANCE, CRIT_MULTIPLIER,
    MIN_OXYGEN_DRAIN, POWER_DEFICIT_EFFICIENCY,
)
from config.buildings import BUILDINGS
from config.techs import TECHS
from config.rocket import ROCKET_PARTS
from config.messages import MESSAGES

# Fixed spatial layout
SOCKET_POSITIONS = [
    "upper_left", "upper_right", "mid_left", "mid_right",
    "lower_left", "lower_right",
    "far_upper_left", "far_upper_right",
    "far_mid_left", "far_mid_right",
    "far_lower_left", "far_lower_right",
]
NODE_POSITIONS = [
    "node_left", "node_top", "node_right",
    "node_far_left", "node_far_right", "node_far_top",
]


def new_game_state(run_id=None):
    """Create a fresh game state for a new run."""
    sid = run_id or str(uuid.uuid4())

    # Build sockets
    sockets = []
    for i, pos in enumerate(SOCKET_POSITIONS):
        sockets.append({
            "id": f"S{i+1}",
            "position_key": pos,
            "unlocked": i < STARTING_SOCKETS,
            "occupied": False,
            "building_id": None,
        })

    # Build nodes
    nodes = []
    visible_ore = NODE_POSITIONS[:STARTING_VISIBLE_NODES]
    for i, pos in enumerate(visible_ore):
        nodes.append({
            "id": f"N{i+1}",
            "type": "ore",
            "position_key": pos,
            "unlocked": True,
            "active": True,
        })
    # Hidden crystal node
    nodes.append({
        "id": "NC1",
        "type": "crystal",
        "position_key": "node_far_top",
        "unlocked": False,
        "active": False,
    })

    # Rocket state
    rocket = {
        pid: {"unlocked": pid == "hull", "complete": False, "in_progress": False}
        for pid in ROCKET_PARTS
    }

    return {
        "run_id": sid,
        "started_at": time.time(),
        "elapsed_seconds": 0.0,
        "status": "playing",
        "resources": dict(STARTING_RESOURCES),
        "rates": dict(STARTING_RATES),
        "map": {"sockets": sockets, "nodes": nodes},
        "buildings_placed": {},
        "tech_unlocked": [],
        "tech_in_progress": None,
        "rocket": rocket,
        "rocket_assembly_enabled": False,
        "messages_shown": [],
        "flags": {},
        "telemetry": {
            "first_tap_time": None,
            "first_building_time": None,
            "first_drill_time": None,
            "first_recycler_time": None,
            "first_refinery_time": None,
            "first_rocket_part_time": None,
            "total_taps": 0,
        },
    }


def _recalculate_rates(state):
    """Recalculate all production rates."""
    resources = state["resources"]
    buildings_placed = state["buildings_placed"]
    tech_unlocked = state["tech_unlocked"]

    # Base values
    ore_ps = 0.0
    power_ps = 0.0
    alloy_ps = 0.0
    crystal_ps = 0.0
    ore_consumption = 0.0
    ore_per_tap = 1.0
    oxygen_drain = 0.12

    # Tech multipliers
    ore_tap_mult = 1.0
    ore_ps_mult = 1.0
    power_ps_mult = 1.0
    oxygen_drain_mult = 1.0

    for tid in tech_unlocked:
        t = TECHS.get(tid)
        if not t:
            continue
        eff = t.get("effects", {})
        if "ore_per_tap_multiplier" in eff:
            ore_tap_mult *= eff["ore_per_tap_multiplier"]
        if "ore_per_second_multiplier" in eff:
            ore_ps_mult *= eff["ore_per_second_multiplier"]
        if "power_per_second_multiplier" in eff:
            power_ps_mult *= eff["power_per_second_multiplier"]
        if "oxygen_drain_multiplier" in eff:
            oxygen_drain_mult *= eff["oxygen_drain_multiplier"]

    # Building effects
    for bid, count in buildings_placed.items():
        b = BUILDINGS.get(bid)
        if not b:
            continue
        eff = b.get("effects", {})
        ore_ps += eff.get("ore_per_second", 0) * count
        power_ps += eff.get("power_per_second", 0) * count
        crystal_ps += eff.get("crystal_per_second", 0) * count
        ore_consumption += eff.get("ore_consumption", 0) * count
        if "ore_per_tap" in eff:
            ore_per_tap += eff["ore_per_tap"] * count
        if "oxygen_drain_flat" in eff:
            oxygen_drain += eff["oxygen_drain_flat"] * count

    # Apply multipliers
    ore_ps *= ore_ps_mult
    ore_per_tap *= ore_tap_mult
    power_ps *= power_ps_mult

    # Refinery: if ore stock is 0, alloy production stalls
    refinery_count = buildings_placed.get("refinery", 0)
    if ore_consumption > 0 and resources["ore"] <= 0 and refinery_count > 0:
        alloy_ps = 0
    else:
        alloy_ps = (ore_consumption / 0.6) * 0.10 * refinery_count

    # Power deficit penalty
    power_demand = sum(
        BUILDINGS.get(bid, {}).get("effects", {}).get("power_per_second", 0) * count
        for bid, count in buildings_placed.items()
    )
    if power_ps < power_demand and power_demand > 0:
        factor = POWER_DEFICIT_EFFICIENCY
        ore_ps *= factor
        alloy_ps *= factor
        crystal_ps *= factor

    # Oxygen drain with multiplier, clamped to minimum
    oxygen_drain = max(MIN_OXYGEN_DRAIN, oxygen_drain * oxygen_drain_mult)

    state["rates"]["ore_per_second"] = ore_ps
    state["rates"]["power_per_second"] = power_ps
    state["rates"]["alloy_per_second"] = alloy_ps
    state["rates"]["crystal_per_second"] = crystal_ps
    state["rates"]["oxygen_drain_per_second"] = oxygen_drain
    state["rates"]["ore_per_tap"] = ore_per_tap


def tick(state, delta_seconds):
    """Advance simulation by delta_seconds."""
    if state["status"] != "playing":
        return

    state["elapsed_seconds"] += delta_seconds
    resources = state["resources"]
    rates = state["rates"]

    # Production
    resources["ore"] = max(0, resources["ore"] + rates["ore_per_second"] * delta_seconds)
    resources["power"] = max(0, resources["power"] + rates["power_per_second"] * delta_seconds)
    resources["alloy"] = max(0, resources["alloy"] + rates["alloy_per_second"] * delta_seconds)
    resources["crystal"] = max(0, resources["crystal"] + rates["crystal_per_second"] * delta_seconds)

    # Oxygen drain
    resources["oxygen"] = max(0, min(100, resources["oxygen"] - rates["oxygen_drain_per_second"] * delta_seconds))

    # Check failure
    if resources["oxygen"] <= 0:
        state["status"] = "lost"
        return

    # Check win
    if all(p["complete"] for p in state["rocket"].values()):
        state["status"] = "won"


def tap_node(state, node_id):
    """Handle a tap. Returns ore gained."""
    if state["status"] != "playing":
        return 0

    node = next((n for n in state["map"]["nodes"] if n["id"] == node_id), None)
    if not node or not node["unlocked"] or not node["active"]:
        return 0

    ore_per_tap = state["rates"]["ore_per_tap"]
    crit = random.random() < CRIT_CHANCE
    gained = ore_per_tap * (CRIT_MULTIPLIER if crit else 1.0)

    if node["type"] == "ore":
        state["resources"]["ore"] += gained
    elif node["type"] == "crystal":
        state["resources"]["crystal"] += gained

    state["telemetry"]["total_taps"] += 1
    if state["telemetry"]["first_tap_time"] is None:
        state["telemetry"]["first_tap_time"] = state["elapsed_seconds"]

    return gained


def place_building(state, socket_id, building_id):
    """Place a building on a socket. Returns (success, message)."""
    if state["status"] != "playing":
        return False, "Game not running."

    socket = next((s for s in state["map"]["sockets"] if s["id"] == socket_id), None)
    if not socket:
        return False, "Socket not found."
    if not socket["unlocked"]:
        return False, "Socket locked."
    if socket["occupied"]:
        return False, "Socket occupied."

    b = BUILDINGS.get(building_id)
    if not b:
        return False, "Building not found."

    # Check unlock tech
    unlock_tech = b.get("unlock_tech")
    if unlock_tech and unlock_tech not in state["tech_unlocked"]:
        return False, f"Requires tech: {TECHS.get(unlock_tech, {}).get('name', unlock_tech)}"

    # Check max per run
    placed = state["buildings_placed"].get(building_id, 0)
    max_count = b.get("max_per_run")
    if max_count is not None and placed >= max_count:
        return False, f"Max {max_count} per run."

    # Check cost
    resources = state["resources"]
    cost = b.get("cost", {})
    for res, amount in cost.items():
        if resources.get(res, 0) < amount:
            return False, f"Not enough {res}."

    # Deduct cost
    for res, amount in cost.items():
        resources[res] -= amount

    # Place
    socket["occupied"] = True
    socket["building_id"] = building_id
    state["buildings_placed"][building_id] = placed + 1

    _recalculate_rates(state)
    _apply_building_effects(state, building_id)
    _update_telemetry(state, building_id)

    return True, f"Placed {b['name']}"


def _apply_building_effects(state, building_id):
    """Handle immediate effects from building placement."""
    b = BUILDINGS.get(building_id)
    if not b:
        return
    eff = b.get("effects", {})

    if "unlock_sockets" in eff:
        hidden = [s for s in state["map"]["sockets"] if not s["unlocked"]]
        for s in hidden[:eff["unlock_sockets"]]:
            s["unlocked"] = True

    if "reveal_crystal_nodes" in eff:
        for n in state["map"]["nodes"]:
            if n["type"] == "crystal" and not n["unlocked"]:
                n["unlocked"] = True
                n["active"] = True
                break

    if "enable_rocket_assembly" in eff:
        state["rocket_assembly_enabled"] = True
        for pid, part in ROCKET_PARTS.items():
            unlock_tech = part.get("unlock_tech")
            if unlock_tech in state["tech_unlocked"]:
                state["rocket"][pid]["unlocked"] = True

    if building_id == "oxygen_recycler":
        _add_message(state, "first_oxygen_building")


def _update_telemetry(state, building_id):
    """Track first-time events."""
    t = state["telemetry"]
    elapsed = state["elapsed_seconds"]
    if t["first_building_time"] is None:
        t["first_building_time"] = elapsed
        _add_message(state, "first_building")
    if building_id == "drill_rig" and t["first_drill_time"] is None:
        t["first_drill_time"] = elapsed
    if building_id == "oxygen_recycler" and t["first_recycler_time"] is None:
        t["first_recycler_time"] = elapsed
    if building_id == "refinery" and t["first_refinery_time"] is None:
        t["first_refinery_time"] = elapsed


def research_tech(state, tech_id):
    """Research a tech. Returns (success, message)."""
    if state["status"] != "playing":
        return False, "Game not running."
    if tech_id in state["tech_unlocked"]:
        return False, "Already researched."

    t = TECHS.get(tech_id)
    if not t:
        return False, "Tech not found."

    for prereq in t.get("prerequisites", []):
        if prereq not in state["tech_unlocked"]:
            return False, f"Requires: {TECHS.get(prereq, {}).get('name', prereq)}"

    resources = state["resources"]
    cost = t.get("cost", {})
    for res, amount in cost.items():
        if resources.get(res, 0) < amount:
            return False, f"Not enough {res}."

    for res, amount in cost.items():
        resources[res] -= amount

    state["tech_unlocked"].append(tech_id)
    _recalculate_rates(state)
    _apply_tech_effects(state, tech_id)

    return True, f"Researched: {t['name']}"


def _apply_tech_effects(state, tech_id):
    """Apply immediate effects from tech."""
    t = TECHS.get(tech_id)
    if not t:
        return
    eff = t.get("effects", {})

    if "rocket_part_unlocks" in eff:
        for pid in eff["rocket_part_unlocks"]:
            if pid in state["rocket"]:
                state["rocket"][pid]["unlocked"] = True

    if "unlock_sockets" in eff:
        count = eff["unlock_sockets"]
        hidden = [s for s in state["map"]["sockets"] if not s["unlocked"]]
        for s in hidden[:count]:
            s["unlocked"] = True

    if "reveal_crystal_nodes" in eff:
        for n in state["map"]["nodes"]:
            if n["type"] == "crystal" and not n["unlocked"]:
                n["unlocked"] = True
                n["active"] = True


def build_rocket_part(state, part_id):
    """Complete a rocket part instantly. Returns (success, message)."""
    if state["status"] != "playing":
        return False, "Game not running."
    if not state["rocket_assembly_enabled"]:
        return False, "Build the Launch Assembly Bay first."
    if part_id not in ROCKET_PARTS:
        return False, "Part not found."

    rstate = state["rocket"].get(part_id)
    if not rstate:
        return False, "Part state missing."
    if rstate["complete"]:
        return False, "Already complete."
    if not rstate["unlocked"]:
        return False, "Not unlocked."

    part = ROCKET_PARTS[part_id]
    resources = state["resources"]
    cost = part.get("cost", {})
    for res, amount in cost.items():
        if res == "oxygen":
            continue  # oxygen cost is just visual requirement
        if resources.get(res, 0) < amount:
            return False, f"Not enough {res}."

    for res, amount in cost.items():
        if res != "oxygen":
            resources[res] -= amount

    rstate["complete"] = True
    rstate["in_progress"] = False

    if state["telemetry"]["first_rocket_part_time"] is None:
        state["telemetry"]["first_rocket_part_time"] = state["elapsed_seconds"]

    if all(p["complete"] for p in state["rocket"].values()):
        state["status"] = "won"
        _add_message(state, "rocket_complete")
        _add_message(state, "victory")

    return True, f"{part['name']} complete!"


def launch_rocket(state):
    """Trigger launch. Returns (success, message)."""
    if state["status"] != "playing":
        return False, "Game not running."
    if not all(p["complete"] for p in state["rocket"].values()):
        return False, "Rocket not complete."
    state["status"] = "won"
    _add_message(state, "rocket_complete")
    _add_message(state, "victory")
    return True, "Launched!"


def check_oxygen_warnings(state):
    """Check oxygen thresholds and queue warnings."""
    oxygen = state["resources"]["oxygen"]
    if oxygen <= 25 and "oxygen_25" not in state["messages_shown"]:
        _add_message(state, "oxygen_25")
    if oxygen <= 10 and "oxygen_10" not in state["messages_shown"]:
        _add_message(state, "oxygen_10")


def _add_message(state, key):
    """Add a message to shown list (game state) and emit to client via telemetry."""
    if key not in state["messages_shown"]:
        state["messages_shown"].append(key)


def get_client_state(state):
    """Return state for client (copy to avoid mutation)."""
    return dict(state)


def can_afford(resources, cost):
    """Check affordability."""
    if not cost:
        return True
    return all((resources.get(res, 0) >= amt) for res, amt in cost.items())
