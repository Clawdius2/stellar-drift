# STELLAR DRIFT v2 — Developer Handoff

## Document Purpose
Full handoff spec for Stellar Drift v2 — survival incremental / colony builder.

## Acceptance Criteria (v1)
1. Player can start a run and understand the goal without tutorial text.
2. Tapping an ore node yields immediate feedback and ore.
3. Player can place at least 6 building sockets on asteroid.
4. Buildings are visibly represented on asteroid.
5. Oxygen drains continuously and can cause failure.
6. At least 8 buildings are functional.
7. Tech tree with 12 techs is functional.
8. Rocket with 4 parts is visible and completable.
9. Launch triggers victory before oxygen zero.
10. Failure screen and victory screen both work.
11. All rates and costs are data-driven.
12. Basic telemetry events are emitted.

## Core Stats
- Starting Ore: 0 | Power: 0 | Alloy: 0 | Crystal: 0 | Oxygen: 100
- Base Ore per Tap: 1.0
- Base Oxygen Drain/sec: 0.12
- Starting Unlocked Sockets: 6
- Starting Visible Ore Nodes: 3
- Tick rate: 200ms (5 ticks/sec)

## Buildings (8 total)
| Building | Cost Ore | Effects |
|---|---|---|
| Drill Rig | 15 | +0.35 ore/sec |
| Hand Drill Upgrade Bay | 20 | +1.0 ore/tap |
| Solar Array | 25 | +0.50 power/sec |
| Oxygen Recycler | 30 | -0.03 drain |
| Refinery | 45 | +0.10 alloy/sec |
| Survey Scanner | 35 | reveals 2 sockets + 1 node |
| Crystal Harvester | 50 | +0.05 crystal/sec |
| Launch Assembly Bay | 60 | enables rocket |

## Techs (12 total across 3 branches)
Extraction: Efficient Strikes I (12 ore), Passive Drilling (20), Deep Survey (35), Precision Extraction (45)
Sustainment: Air Filters (16), Improved Recycling (28), Power Routing (36), Pressure Seals (50)
Escape: Smelting Protocols (26), Launch Assembly (55), Guidance Systems (65), Life Support Integration (70)

## Rocket Parts (4)
Hull, Engine, Guidance, Life Support

## Visual Feedback
- Tap mining: floating number popup
- Crit: x2 multiplier, 10% chance
- Building placement: valid sockets glow
- Oxygen thresholds: color transitions at 50, 25, 10
- Rocket progress: visible frame completion
