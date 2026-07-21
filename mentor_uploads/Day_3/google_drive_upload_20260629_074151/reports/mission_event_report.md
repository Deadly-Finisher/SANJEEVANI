# Mission Event Report

Generated at: 2026-06-28T20:17:26.728072

## Mission Metadata

- Mission name: battlefield_sar_world_v1_single_drone_yolo_test
- Gazebo world: battlefield_sar_world_v1
- Drone model: PX4 x500_mono_cam
- Detector model: yolo11n.pt

## Mission Time Window

- Start time: 2026-06-28 20:08:48.362300
- End time: 2026-06-28 20:09:27.202944

## Detection Summary

- Total visual detection events: 162
- Events linked with telemetry: 142
- Events without telemetry link: 20
- Average detection confidence: 0.4524

## Detected Classes

- airplane: 70
- umbrella: 40
- sports ball: 26
- bird: 17
- person: 6
- stop sign: 2
- traffic light: 1

## Mission Phases Observed

- takeoff
- moving_forward
- moving_right
- hovering
- landing

## Altitude Summary

- Minimum relative altitude: -0.56 m
- Maximum relative altitude: 1.82 m
- Mean relative altitude: 0.74 m

## First 10 Detection Events

|   event_id | detection_timestamp        | class_name   |   confidence | mission_phase   |   relative_altitude_m |   latitude_deg |   longitude_deg |
|-----------:|:---------------------------|:-------------|-------------:|:----------------|----------------------:|---------------:|----------------:|
|          1 | 2026-06-28 20:08:48.362300 | airplane     |       0.505  | takeoff         |                -0.008 |        47.3974 |         8.54559 |
|          2 | 2026-06-28 20:08:48.362481 | airplane     |       0.446  | takeoff         |                -0.008 |        47.3974 |         8.54559 |
|          3 | 2026-06-28 20:08:48.676470 | airplane     |       0.4521 | takeoff         |                -0.005 |        47.3974 |         8.54559 |
|          4 | 2026-06-28 20:08:48.676664 | airplane     |       0.4224 | takeoff         |                -0.005 |        47.3974 |         8.54559 |
|          5 | 2026-06-28 20:08:48.922803 | airplane     |       0.5811 | takeoff         |                -0.014 |        47.3974 |         8.54559 |
|          6 | 2026-06-28 20:08:48.922910 | airplane     |       0.3771 | takeoff         |                -0.014 |        47.3974 |         8.54559 |
|          7 | 2026-06-28 20:08:49.866646 | airplane     |       0.5761 | takeoff         |                -0.025 |        47.3974 |         8.54559 |
|          8 | 2026-06-28 20:08:49.866805 | airplane     |       0.3239 | takeoff         |                -0.025 |        47.3974 |         8.54559 |
|          9 | 2026-06-28 20:08:50.403477 | airplane     |       0.4921 | takeoff         |                -0.034 |        47.3974 |         8.54559 |
|         10 | 2026-06-28 20:08:50.403883 | airplane     |       0.4691 | takeoff         |                -0.034 |        47.3974 |         8.54559 |

## Interpretation

The simulated UAV successfully collected live camera frames, ran YOLO-based visual detection, logged detections to CSV, captured drone telemetry during movement, and produced a telemetry-linked event log. This report summarizes the first complete single-drone perception and telemetry pipeline.