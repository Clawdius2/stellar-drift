"""Balance constants and starting values."""
STARTING_RESOURCES = {
    "ore": 0,
    "power": 0,
    "oxygen": 100.0,
    "alloy": 0,
    "crystal": 0,
}
STARTING_RATES = {
    "ore_per_second": 0,
    "power_per_second": 0,
    "alloy_per_second": 0,
    "crystal_per_second": 0,
    "oxygen_drain_per_second": 0.12,
    "ore_per_tap": 1.0,
}
STARTING_SOCKETS = 6
STARTING_VISIBLE_NODES = 3
TICK_INTERVAL_MS = 200
OFFLINE_EFFICIENCY = 0.75
CRIT_CHANCE = 0.10
CRIT_MULTIPLIER = 2.0
MIN_OXYGEN_DRAIN = 0.03
POWER_DEFICIT_EFFICIENCY = 0.5
