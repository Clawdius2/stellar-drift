"""
Stellar Drift — Space Mining Idle Game
Flask backend with SQLite persistence
"""

import os
import time
import math
import json
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# =============================================================================
# APP SETUP
# =============================================================================

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "stellar-drift-dev-key-2024")

# Database
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg://", 1)

if DATABASE_URL:
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///stellar_drift.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

# =============================================================================
# GAME CONSTANTS
# =============================================================================

COST_MULTIPLIER = 1.15
PRODUCTION_EXPONENT = 0.7
OFFLINE_EFFICIENCY = 0.75
OFFLINE_CAP_HOURS = 4
AUTO_SAVE_INTERVAL = 30
PRESTIGE_THRESHOLD_MULTIPLIER = 1_000_000
PRESTIGE_BONUS_PER_POINT = 0.10
SOUL_GAINS_MULTIPLIER = 0.5  # sqrt(total_earned / 1M) ^ 0.5

# Number formatting thresholds
def format_number(n):
    if n < 1_000:
        return str(int(n)) if n == int(n) else f"{n:.1f}"
    if n < 1_000_000:
        return f"{n/1_000:.1f}K"
    if n < 1_000_000_000:
        return f"{n/1_000_000:.1f}M"
    if n < 1_000_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    return f"{n/1_000_000_000_000:.1f}T"

# =============================================================================
# GAME CONFIGURATION
# =============================================================================

RESOURCES = {
    "ore":     {"name": "Ore",     "tap": 1,   "color": "#f4a460"},
    "gas":     {"name": "Gas",     "tap": 0,   "color": "#9370db"},
    "crystals": {"name": "Crystals","tap": 0,   "color": "#00ced1"},
    "dark_matter": {"name": "Dark Matter", "tap": 0, "color": "#8b0000"},
}

BUILDINGS = {
    "mining_laser": {
        "name": "Mining Laser",
        "description": "A focused beam that extracts ore from asteroids.",
        "base_cost": 10,
        "base_output": 0.5,      # ore/sec per unit
        "produces": "ore",
        "tier": 1,
        "cost_resource": "ore",
    },
    "ore_drill": {
        "name": "Ore Drill",
        "description": "Automated drill that harvests ore continuously.",
        "base_cost": 100,
        "base_output": 4,
        "produces": "ore",
        "tier": 1,
        "cost_resource": "ore",
    },
    "asteroid_harvester": {
        "name": "Asteroid Harvester",
        "description": "A massive station that mines entire asteroids.",
        "base_cost": 1_000,
        "base_output": 20,
        "produces": "ore",
        "tier": 1,
        "cost_resource": "ore",
    },
    "gas_collector": {
        "name": "Gas Collector",
        "description": "Harvests gas from nearby nebulae.",
        "base_cost": 50,
        "base_output": 0.5,
        "produces": "gas",
        "tier": 2,
        "cost_resource": "ore",
        "requires": "basic_research",
    },
    "orbital_refinery": {
        "name": "Orbital Refinery",
        "description": "Processes raw ore into refined materials.",
        "base_cost": 500,
        "base_output": 3,
        "produces": "ore",
        "tier": 2,
        "cost_resource": "ore",
        "requires": "advanced_research",
        "upgrade": True,
    },
    "crystal_extractor": {
        "name": "Crystal Extractor",
        "description": "Mines rare crystals from deep-space formations.",
        "base_cost": 5_000,
        "base_output": 2,
        "produces": "crystals",
        "tier": 2,
        "cost_resource": "ore",
        "requires": "crystal_research",
    },
    "warp_gate": {
        "name": "Warp Gate",
        "description": "Bends space to instantly transport resources.",
        "base_cost": 50_000,
        "base_output": 100,
        "produces": "ore",
        "tier": 3,
        "cost_resource": "ore",
        "requires": "warp_research",
    },
    "dark_matter_reactor": {
        "name": "Dark Matter Reactor",
        "description": "Converts dark matter into pure energy.",
        "base_cost": 10,
        "base_output": 1,
        "produces": "dark_matter",
        "tier": 3,
        "cost_resource": "dark_matter",
        "requires": "quantum_research",
    },
}

RESEARCH = {
    "efficient_drilling": {
        "name": "Efficient Drilling",
        "description": "Improves all ore production by 25%.",
        "cost": 500,
        "effect": {"ore_mult": 1.25},
        "tier": 1,
        "cost_resource": "ore",
    },
    "basic_automation": {
        "name": "Basic Automation",
        "description": "Unlocks Ore Drill.",
        "cost": 800,
        "effect": {"unlock": "ore_drill"},
        "tier": 1,
        "cost_resource": "ore",
    },
    "gas_harvesting": {
        "name": "Gas Harvesting",
        "description": "Unlocks Gas Collector.",
        "cost": 2_000,
        "effect": {"unlock": "gas_collector"},
        "tier": 2,
        "cost_resource": "ore",
        "requires": "basic_automation",
    },
    "advanced_research": {
        "name": "Advanced Smelting",
        "description": "Unlocks Orbital Refinery. 2x ore value.",
        "cost": 5_000,
        "effect": {"unlock": "orbital_refinery", "ore_mult": 2.0},
        "tier": 2,
        "cost_resource": "ore",
        "requires": "efficient_drilling",
    },
    "crystal_research": {
        "name": "Crystal Mining",
        "description": "Unlocks Crystal Extractor.",
        "cost": 10_000,
        "effect": {"unlock": "crystal_extractor"},
        "tier": 2,
        "cost_resource": "ore",
        "requires": "gas_harvesting",
    },
    "warp_research": {
        "name": "Warp Technology",
        "description": "Unlocks Warp Gate. 50% offline efficiency.",
        "cost": 50_000,
        "effect": {"unlock": "warp_gate", "offline_mult": 1.5},
        "tier": 3,
        "cost_resource": "ore",
        "requires": "advanced_research",
    },
    "quantum_research": {
        "name": "Quantum Mechanics",
        "description": "Unlocks Dark Matter Reactor.",
        "cost": 100_000,
        "effect": {"unlock": "dark_matter_reactor"},
        "tier": 3,
        "cost_resource": "crystals",
        "requires": "warp_research",
    },
}

MILESTONES = {
    "ore": [
        {"threshold": 100,      "reward": 1.05, "label": "First 100 Ore!"},
        {"threshold": 1_000,    "reward": 1.10, "label": "1K Ore Club"},
        {"threshold": 10_000,   "reward": 1.10, "label": "10K Ore!"},
        {"threshold": 100_000,  "reward": 1.15, "label": "100K — Tycoon!"},
        {"threshold": 1_000_000, "reward": 1.20, "label": "1M — Legend!"},
    ],
    "gas": [
        {"threshold": 50,       "reward": 1.10, "label": "First Gas!"},
        {"threshold": 1_000,    "reward": 1.15, "label": "1K Gas!"},
        {"threshold": 10_000,   "reward": 1.20, "label": "10K Gas!"},
    ],
    "crystals": [
        {"threshold": 10,       "reward": 1.10, "label": "First Crystal!"},
        {"threshold": 100,      "reward": 1.15, "label": "100 Crystals!"},
        {"threshold": 1_000,    "reward": 1.25, "label": "1K Crystals!"},
    ],
}

PRESTIGE_UPGRADES = {
    "dark_mining":    {"name": "Dark Mining",    "cost": 5,  "bonus": 1.25, "desc": "+25% ore production"},
    "deep_extraction": {"name": "Deep Extraction","cost": 20, "bonus": 1.50, "desc": "+50% all production"},
    "warp_logistics": {"name": "Warp Logistics", "cost": 100,"bonus": 2.00, "desc": "2x all production"},
}

# =============================================================================
# DATABASE MODELS
# =============================================================================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    username = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Game state
    # Resources (stored as JSON in PlayerState)
    # PlayerState relationship
    state = db.relationship("PlayerState", backref="user", uselist=False, cascade="all, delete-orphan")


class PlayerState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True)

    # Core resources
    ore = db.Column(db.Float, default=0)
    gas = db.Column(db.Float, default=0)
    crystals = db.Column(db.Float, default=0)
    dark_matter = db.Column(db.Float, default=0)

    # Soul earnings (lifetime resources for prestige)
    total_ore_earned = db.Column(db.Float, default=0)
    total_gas_earned = db.Column(db.Float, default=0)
    total_crystals_earned = db.Column(db.Float, default=0)

    # Buildings owned (JSON: {"building_name": count})
    buildings_json = db.Column(db.Text, default="{}")

    # Research completed (JSON: ["research_id", ...])
    research_json = db.Column(db.Text, default="[]")

    # Milestones earned (JSON: {"resource": [milestone_ids]})
    milestones_json = db.Column(db.Text, default="{}")

    # Prestige
    prestige_count = db.Column(db.Integer, default=0)
    prestige_upgrades_json = db.Column(db.Text, default="{}")  # {"upgrade_id": level}

    # Timestamps
    last_save_timestamp = db.Column(db.Float, default=lambda: time.time())
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    @property
    def buildings(self):
        return json.loads(self.buildings_json or "{}")

    @buildings.setter
    def buildings(self, value):
        self.buildings_json = json.dumps(value)

    @property
    def research(self):
        return json.loads(self.research_json or "[]")

    @research.setter
    def research(self, value):
        self.research_json = json.dumps(value)

    @property
    def milestones(self):
        return json.loads(self.milestones_json or "{}")

    @milestones.setter
    def milestones(self, value):
        self.milestones_json = json.dumps(value)

    @property
    def prestige_upgrades(self):
        return json.loads(self.prestige_upgrades_json or "{}")

    @prestige_upgrades.setter
    def prestige_upgrades(self, value):
        self.prestige_upgrades_json = json.dumps(value)

    def get_resource(self, name):
        return getattr(self, name, 0)

    def set_resource(self, name, value):
        setattr(self, name, max(0, value))

    def add_resource(self, name, amount):
        current = self.get_resource(name)
        self.set_resource(name, current + amount)
        if name == "ore":
            self.total_ore_earned += amount
        elif name == "gas":
            self.total_gas_earned += amount
        elif name == "crystals":
            self.total_crystals_earned += amount

    def get_offline_rate(self):
        """Calculate offline efficiency multiplier from research + prestige."""
        offline_mult = 1.0
        # Research bonuses
        for rid in self.research:
            if rid in RESEARCH:
                effect = RESEARCH[rid].get("effect", {})
                if "offline_mult" in effect:
                    offline_mult *= effect["offline_mult"]
        # Prestige upgrades
        for uid, level in self.prestige_upgrades.items():
            if uid in PRESTIGE_UPGRADES:
                offline_mult *= PRESTIGE_UPGRADES[uid]["bonus"]
        return min(offline_mult, 3.0)  # cap at 3x

    def get_production_multiplier(self):
        """Total production multiplier from milestones + research + prestige."""
        mult = 1.0
        # Milestones
        for resource, earned_ids in self.milestones.items():
            if resource in MILESTONES:
                for mid in earned_ids:
                    for m in MILESTONES[resource]:
                        if m["threshold"] == mid or id(m) == mid:
                            mult *= m["reward"]
        # Research ore mult
        for rid in self.research:
            if rid in RESEARCH:
                effect = RESEARCH[rid].get("effect", {})
                if "ore_mult" in effect:
                    mult *= effect["ore_mult"]
        # Prestige upgrades
        for uid, level in self.prestige_upgrades.items():
            if uid in PRESTIGE_UPGRADES:
                mult *= PRESTIGE_UPGRADES[uid]["bonus"]
        return mult

    def get_research_bonuses(self):
        """Returns dict of research bonuses for building output."""
        bonuses = {}
        for rid in self.research:
            if rid in RESEARCH:
                effect = RESEARCH[rid].get("effect", {})
                for k, v in effect.items():
                    if k.endswith("_mult"):
                        resource = k.replace("_mult", "")
                        bonuses[resource] = bonuses.get(resource, 1.0) * v
        return bonuses


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# =============================================================================
# GAME ENGINE
# =============================================================================

def calculate_offline_gains(state):
    """Calculate resources earned while away."""
    elapsed = min(time.time() - state.last_save_timestamp, OFFLINE_CAP_HOURS * 3600)
    if elapsed < 10:  # less than 10 seconds, no offline gains
        return {}

    rps = calculate_rps(state)
    offline_mult = state.get_offline_rate() * OFFLINE_EFFICIENCY
    # Diminishing rate the longer you're away
    effective_rate = sum(rps.values()) * offline_mult * (1 / (1 + elapsed / 7200))

    gains = {}
    for resource, rate in rps.items():
        share = rate / sum(rps.values()) if sum(rps.values()) > 0 else 0
        gains[resource] = effective_rate * share * elapsed * (rate / sum(rps.values()) if sum(rps.values()) > 0 else 0) if rate > 0 else 0

    return gains


def calculate_rps(state):
    """Calculate resources per second for all resource types."""
    rps = {"ore": 0, "gas": 0, "crystals": 0, "dark_matter": 0}
    buildings = state.buildings
    bonuses = state.get_research_bonuses()
    prod_mult = state.get_production_multiplier()

    for bid, count in buildings.items():
        if bid not in BUILDINGS:
            continue
        building = BUILDINGS[bid]
        if count <= 0:
            continue

        resource = building["produces"]
        output_per_building = building["base_output"]
        building_mult = bonuses.get(resource, 1.0)

        # Diminishing returns per building
        effective_output = output_per_building * (count ** PRODUCTION_EXPONENT)
        contribution = effective_output * building_mult * prod_mult

        rps[resource] += contribution

    return rps


def get_building_cost(state, bid):
    """Calculate current cost of buying one building."""
    if bid not in BUILDINGS:
        return float("inf")
    building = BUILDINGS[bid]
    owned = state.buildings.get(bid, 0)
    base = building["base_cost"]
    multiplier = 1.15
    return base * (multiplier ** owned)


def can_afford(state, bid):
    """Check if player can afford a building."""
    cost = get_building_cost(state, bid)
    resource = BUILDINGS[bid]["cost_resource"]
    return state.get_resource(resource) >= cost


def buy_building(state, bid):
    """Purchase a building. Returns (success, message)."""
    if bid not in BUILDINGS:
        return False, "Building not found."

    building = BUILDINGS[bid]
    # Check prerequisites
    requires = building.get("requires")
    if requires and requires not in state.research:
        return False, f"Requires research: {RESEARCH[requires]['name']}"

    if not can_afford(state, bid):
        return False, "Not enough resources."

    cost = get_building_cost(state, bid)
    resource = building["cost_resource"]
    state.set_resource(resource, state.get_resource(resource) - cost)

    buildings = state.buildings
    buildings[bid] = buildings.get(bid, 0) + 1
    state.buildings = buildings

    return True, f"Bought {building['name']}!"


def tap_resource(state, resource_name="ore", tap_amount=None):
    """Handle a tap on a resource."""
    if resource_name not in RESOURCES:
        return 0
    if tap_amount is None:
        tap_amount = RESOURCES[resource_name]["tap"]
    if tap_amount <= 0:
        return 0
    state.add_resource(resource_name, tap_amount)
    return tap_amount


def process_research(state, research_id):
    """Purchase a research. Returns (success, message)."""
    if research_id not in RESEARCH:
        return False, "Research not found."

    research = RESEARCH[research_id]
    if research_id in state.research:
        return False, "Already researched."

    # Check prerequisites
    requires = research.get("requires")
    if requires and requires not in state.research:
        return False, f"Requires: {RESEARCH[requires]['name']}"

    cost_resource = research.get("cost_resource", "ore")
    if state.get_resource(cost_resource) < research["cost"]:
        return False, f"Not enough {cost_resource}."

    state.set_resource(cost_resource, state.get_resource(cost_resource) - research["cost"])
    research_list = state.research
    research_list.append(research_id)
    state.research = research_list

    return True, f"Researched: {research['name']}!"


def check_milestones(state):
    """Check and award new milestones. Returns list of newly earned milestones."""
    newly_earned = []
    for resource_name, milestones in MILESTONES.items():
        current = state.get_resource(resource_name)
        earned = state.milestones.get(resource_name, [])

        for m in milestones:
            threshold = m["threshold"]
            if current >= threshold and threshold not in earned:
                earned.append(threshold)
                newly_earned.append(m)

        state.milestones[resource_name] = earned

    return newly_earned


def calculate_prestige_points(state):
    """Calculate how many prestige points would be earned from a reset."""
    # Dark matter earned = sqrt(total_ore / 1M)
    soul = math.sqrt(state.total_ore_earned / PRESTIGE_THRESHOLD_MULTIPLIER) ** SOUL_GAINS_MULTIPLIER
    return math.floor(soul)


def can_prestige(state):
    """Check if player meets prestige requirements."""
    return state.prestige_count == 0 or state.total_ore_earned >= PRESTIGE_THRESHOLD_MULTIPLIER


def do_prestige(state):
    """Perform a prestige reset. Returns soul points gained."""
    if not can_prestige(state):
        return 0

    soul = calculate_prestige_points(state)

    # Reset resources
    state.ore = 0
    state.gas = 0
    state.crystals = 0
    state.total_ore_earned = 0
    state.total_gas_earned = 0
    state.total_crystals_earned = 0

    # Reset buildings
    state.buildings = {}
    state.research = []
    state.milestones = {}

    # Award dark matter
    state.dark_matter += max(1, soul)

    # Increment prestige count
    state.prestige_count += 1

    return max(1, soul)


def buy_prestige_upgrade(state, upgrade_id):
    """Purchase a prestige upgrade using dark matter."""
    if upgrade_id not in PRESTIGE_UPGRADES:
        return False, "Upgrade not found."

    upgrades = state.prestige_upgrades
    current_level = upgrades.get(upgrade_id, 0)
    upgrade = PRESTIGE_UPGRADES[upgrade_id]
    cost = upgrade["cost"] * (2 ** current_level)

    if state.dark_matter < cost:
        return False, "Not enough dark matter."

    state.dark_matter -= cost
    upgrades[upgrade_id] = current_level + 1
    state.prestige_upgrades = upgrades

    return True, f"Bought {upgrade['name']}!"


def get_game_state(state, include_offline_gains=True):
    """Get full game state for the client."""
    if include_offline_gains:
        offline_gains = calculate_offline_gains(state)
        for resource, amount in offline_gains.items():
            if amount > 0:
                state.add_resource(resource, amount)

    # Update timestamp
    state.last_save_timestamp = time.time()

    rps = calculate_rps(state)

    return {
        "resources": {
            "ore":        {"value": state.ore,        "rps": rps["ore"],        "color": RESOURCES["ore"]["color"]},
            "gas":        {"value": state.gas,        "rps": rps["gas"],        "color": RESOURCES["gas"]["color"]},
            "crystals":   {"value": state.crystals,   "rps": rps["crystals"],   "color": RESOURCES["crystals"]["color"]},
            "dark_matter": {"value": state.dark_matter, "rps": rps["dark_matter"], "color": RESOURCES["dark_matter"]["color"]},
        },
        "buildings": {
            bid: {
                "count": state.buildings.get(bid, 0),
                "cost": get_building_cost(state, bid),
                "can_afford": can_afford(state, bid),
                **BUILDINGS[bid],
            }
            for bid in BUILDINGS
        },
        "research": {
            rid: {
                "completed": rid in state.research,
                "can_buy": (rid not in state.research and
                           (not RESEARCH[rid].get("requires") or RESEARCH[rid]["requires"] in state.research) and
                           state.get_resource(RESEARCH[rid].get("cost_resource", "ore")) >= RESEARCH[rid]["cost"]),
                **RESEARCH[rid],
            }
            for rid in RESEARCH
        },
        "prestige": {
            "count": state.prestige_count,
            "can_prestige": can_prestige(state),
            "would_earn": calculate_prestige_points(state),
            "upgrades": {
                uid: {
                    "level": state.prestige_upgrades.get(uid, 0),
                    "cost": PRESTIGE_UPGRADES[uid]["cost"] * (2 ** state.prestige_upgrades.get(uid, 0)),
                    "can_afford": state.dark_matter >= PRESTIGE_UPGRADES[uid]["cost"] * (2 ** state.prestige_upgrades.get(uid, 0)),
                    **PRESTIGE_UPGRADES[uid],
                }
                for uid in PRESTIGE_UPGRADES
            },
        },
        "milestones": state.milestones,
        "rps": rps,
        "multiplier": state.get_production_multiplier(),
        "offline_rate": state.get_offline_rate(),
    }


def format_resources(state):
    """Format resource display values."""
    out = {}
    for k, v in RESOURCES.items():
        out[k] = {
            "name": v["name"],
            "value": format_number(state.get_resource(k)),
            "color": v["color"],
        }
    return out


# =============================================================================
# WEB ROUTES
# =============================================================================

@app.route("/")
def index():
    if current_user.is_authenticated:
        return render_template("game.html")
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        username = request.form.get("username", "").strip()

        if not email or not password:
            return render_template("register.html", error="Email and password required.")

        if User.query.filter_by(email=email).first():
            return render_template("register.html", error="Email already registered.")

        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            username=username or email.split("@")[0],
        )
        db.session.add(user)
        db.session.flush()

        # Create player state
        state = PlayerState(user_id=user.id)
        # Give starting building
        state.buildings = {"mining_laser": 1}
        db.session.add(state)
        db.session.commit()

        login_user(user)
        return redirect(url_for("index"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("index"))

        return render_template("login.html", error="Invalid email or password.")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


@app.route("/api/game/state")
@login_required
def api_state():
    state = current_user.state
    if not state:
        state = PlayerState(user_id=current_user.id)
        db.session.add(state)
        db.session.commit()

    return jsonify(get_game_state(state))


@app.route("/api/game/tap", methods=["POST"])
@login_required
def api_tap():
    state = current_user.state
    data = request.get_json() or {}
    resource = data.get("resource", "ore")
    amount = data.get("amount")

    earned = tap_resource(state, resource, amount)
    db.session.commit()

    return jsonify({
        "earned": earned,
        "resources": format_resources(state),
        "ore": state.ore,
    })


@app.route("/api/game/buy/building", methods=["POST"])
@login_required
def api_buy_building():
    state = current_user.state
    data = request.get_json() or {}
    bid = data.get("building_id")

    success, msg = buy_building(state, bid)
    db.session.commit()

    return jsonify({
        "success": success,
        "message": msg,
        "game_state": get_game_state(state, include_offline_gains=False),
    })


@app.route("/api/game/buy/research", methods=["POST"])
@login_required
def api_buy_research():
    state = current_user.state
    data = request.get_json() or {}
    rid = data.get("research_id")

    success, msg = process_research(state, rid)
    db.session.commit()

    return jsonify({
        "success": success,
        "message": msg,
        "game_state": get_game_state(state, include_offline_gains=False),
    })


@app.route("/api/game/prestige", methods=["POST"])
@login_required
def api_prestige():
    state = current_user.state
    data = request.get_json() or {}

    if not can_prestige(state):
        return jsonify({"success": False, "message": "Not ready to prestige."})

    soul = do_prestige(state)
    db.session.commit()

    return jsonify({
        "success": True,
        "soul_earned": soul,
        "game_state": get_game_state(state),
    })


@app.route("/api/game/buy/prestige-upgrade", methods=["POST"])
@login_required
def api_buy_prestige_upgrade():
    state = current_user.state
    data = request.get_json() or {}
    uid = data.get("upgrade_id")

    success, msg = buy_prestige_upgrade(state, uid)
    db.session.commit()

    return jsonify({
        "success": success,
        "message": msg,
        "game_state": get_game_state(state, include_offline_gains=False),
    })


@app.route("/api/game/tick", methods=["POST"])
@login_required
def api_tick():
    """Called by client periodically. Updates resources based on time elapsed."""
    state = current_user.state
    data = request.get_json() or {}

    # Calculate time-based gains
    now = time.time()
    elapsed = now - state.last_save_timestamp

    if elapsed > 1:
        rps = calculate_rps(state)
        for resource, rate in rps.items():
            if rate > 0:
                state.add_resource(resource, rate * elapsed)

        state.last_save_timestamp = now

    # Check milestones
    new_milestones = check_milestones(state)
    db.session.commit()

    return jsonify({
        "game_state": get_game_state(state, include_offline_gains=False),
        "new_milestones": [{"label": m["label"], "reward": m["reward"]} for m in new_milestones],
        "elapsed": elapsed,
    })


# =============================================================================
# MAIN
# =============================================================================

# Create tables on startup (works with gunicorn/WSGI — runs after models are defined)
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)

