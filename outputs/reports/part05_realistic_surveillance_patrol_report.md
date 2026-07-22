# Part 5: Safe Continuous Overlapping Autonomous Surveillance Patrol

## Result

PASS

## Behaviour

The drones now move through long overlapping surveillance routes.

They do not move in a fixed formation and do not maintain a fixed distance.

## Safety and Stability

This version uses slower sequential Gazebo pose updates to avoid overloading Gazebo.

## Output Files

- Summary: `outputs/reports/part05_realistic_surveillance_patrol_summary.json`
- Telemetry: `outputs/swarm_missions/part05_surveillance_patrol/part05_safe_continuous_overlapping_surveillance_telemetry.csv`
- Live state: `outputs/live/swarm_live_state.json`
