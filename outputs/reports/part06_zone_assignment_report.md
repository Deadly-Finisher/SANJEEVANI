# Part 6: Swarm Zone Assignment

## Result

PASS

## Objective

The battlefield area is divided into three surveillance zones so that each drone has a clear responsibility.

## Zone Allocation

### Drone 1 — Left Flank

- Model: x500_mono_cam_1
- Zone: left flank surveillance
- Altitude: 12 m
- Purpose: observe left-side movement and flank activity

### Drone 2 — Center Road

- Model: x500_mono_cam_2
- Zone: center road and asset surveillance
- Altitude: 16 m
- Purpose: monitor central movement, road activity and battlefield assets

### Drone 3 — Right Overwatch

- Model: x500_mono_cam_3
- Zone: right flank overwatch
- Altitude: 20 m
- Purpose: provide high-altitude overwatch and right-side surveillance

## Safety Design

The drones are separated by both horizontal search lanes and altitude levels:

- Drone 1: 12 m
- Drone 2: 16 m
- Drone 3: 20 m

This reduces collision risk during simulated patrol.

## Future Scope

Dynamic obstacle avoidance, LiDAR-based safety and live replanning are kept as future scope.

## Output Files

- Config: `configs/swarm/part06_swarm_zone_assignment.yaml`
- Summary: `outputs/reports/part06_zone_assignment_summary.json`
