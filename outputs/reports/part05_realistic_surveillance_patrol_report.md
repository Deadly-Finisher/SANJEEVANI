# Part 5: Altitude-Separated Three-Drone Surveillance Patrol

## Result

PASS

## Patrol Behaviour

- Drone 1 covers the left flank at 12m.
- Drone 2 covers the center route at 16m.
- Drone 3 covers the right overwatch lane at 20m.
- The drones follow horizontal surveillance sweep paths, not only vertical motion.

## Safety

The patrol uses different lanes and different altitudes to reduce collision risk.

## Dashboard

Live telemetry is written to `outputs/live/swarm_live_state.json`.
