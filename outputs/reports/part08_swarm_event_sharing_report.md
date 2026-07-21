# Part 8: Swarm Communication and Event Sharing

## Result

PASS

## Objective

Each drone converts detections into structured events and shares them with the other drones and the operator dashboard.

## Communication Design

- Drone events use a common JSON schema.
- Each event contains source drone, zone, object class, confidence, priority and position.
- Events are broadcast to peer drones and operator dashboard.
- Receiver acknowledgements are recorded.
- Nearby duplicate events are merged.

## Event Counts

- Raw events: 4
- Shared events: 4
- Deduplicated swarm events: 4

## Shared Events

### person — MEDIUM

- Type: possible human activity
- Source drones: drone_1
- Position: x=-27.0, y=-34.0, z=1.0
- Confidence: 0.73
- Fusion status: unique_event

### truck — HIGH

- Type: possible vehicle movement
- Source drones: drone_2
- Position: x=2.0, y=-40.0, z=1.0
- Confidence: 0.81
- Fusion status: unique_event

### smoke — HIGH

- Type: possible fire or battlefield disturbance
- Source drones: drone_2
- Position: x=-4.0, y=-33.0, z=1.0
- Confidence: 0.64
- Fusion status: unique_event

### truck — HIGH

- Type: possible vehicle movement
- Source drones: drone_3
- Position: x=22.0, y=-37.0, z=1.0
- Confidence: 0.76
- Fusion status: unique_event

## Output Files

- Raw events: `outputs/swarm_events/part08/part08_raw_drone_events.json`
- Shared event bus: `outputs/swarm_events/part08/part08_shared_event_bus.json`
- Deduplicated events: `outputs/swarm_events/part08/part08_deduplicated_swarm_events.json`
- Summary: `outputs/reports/part08_swarm_event_sharing_summary.json`