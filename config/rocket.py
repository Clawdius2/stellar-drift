"""Rocket part definitions."""
ROCKET_PARTS = {
    "hull": {
        "id": "hull",
        "name": "Hull",
        "description": "Structural integrity",
        "cost": {"ore": 40, "alloy": 12},
        "unlock_tech": "launch_assembly",
    },
    "engine": {
        "id": "engine",
        "name": "Engine",
        "description": "Propulsion system",
        "cost": {"ore": 20, "power": 8, "alloy": 18},
        "unlock_tech": "life_support_integration",
    },
    "guidance": {
        "id": "guidance",
        "name": "Guidance",
        "description": "Navigation computer",
        "cost": {"ore": 10, "power": 8, "alloy": 8, "crystal": 4},
        "unlock_tech": "guidance_systems",
    },
    "life_support": {
        "id": "life_support",
        "name": "Life Support",
        "description": "Survival systems",
        "cost": {"power": 4, "alloy": 14, "crystal": 2, "oxygen": 10},
        "unlock_tech": "life_support_integration",
    },
}
