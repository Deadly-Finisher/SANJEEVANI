# SWARM_DRONES Progress Notes

## Project
AI-Driven Autonomous Battlefield Intelligence using Cooperative Drone Swarms

## Current Completed Work

1. Created custom Gazebo battlefield-style simulation world.
2. Added PX4 SITL support with x500_mono_cam drone.
3. Fixed simulated sensor issues for IMU, barometer, magnetometer, GPS/NavSat, magnetic field, and spherical coordinates.
4. Connected PX4 SITL with QGroundControl.
5. Added battlefield simulation objects:
   - roads
   - buildings
   - damaged building
   - trees
   - vehicles
   - humans
   - barriers
   - debris
   - smoke/fire visual placeholders
6. Enabled Gazebo camera topic from x500_mono_cam.
7. Installed and configured ROS2 Humble camera bridge.
8. Bridged Gazebo camera topic to ROS2 image topic.
9. Verified live camera feed using ROS image tools.
10. Saved Gazebo camera frames to disk.
11. Ran YOLO on saved Gazebo frames.
12. Generated annotated YOLO frames and detection CSV.
13. Built live YOLO ROS camera detector.
14. Ran live YOLO detection in the simulated battlefield world.
15. Moved drone using MAVSDK while YOLO was detecting.
16. Logged drone telemetry during movement.
17. Merged detection logs with telemetry logs.
18. Generated telemetry-linked event log.
19. Generated automatic mission event report.
20. Built Streamlit dashboard.
21. Added real-time MJPEG YOLO feed to dashboard.
22. Downloaded Military Assets Dataset from Kaggle manually.
23. Manually changed dataset labels in YAML.
24. Verified dataset labels visually without changing labels again.
25. Fine-tuned YOLO for 30 epochs on the manually relabeled dataset.
26. Saved fine-tuned model weights.
27. Saved model checksums to avoid unnecessary retraining.

## Saved Model Weights

Model directory:

models/aerial_safe_objects/

Expected saved files:

- best_aerial_safe_objects.pt
- last_aerial_safe_objects.pt
- model_weight_checksums.txt

## Important Label Rule

The dataset labels were manually changed and must not be changed again unless explicitly requested.

## What Is Left

1. Test fine-tuned model on saved Gazebo camera frames.
2. Add fine-tuned model to live YOLO ROS/MJPEG detector.
3. Add fine-tuned model output to dashboard.
4. Download/select smoke/fire dataset.
5. Inspect smoke/fire labels.
6. Fine-tune smoke/fire YOLO model.
7. Save smoke/fire model in models/fire_smoke/.
8. Add smoke/fire model to live detection pipeline.
9. Add aerial/drone-view dataset.
10. Inspect aerial/drone-view labels.
11. Fine-tune drone-view general model.
12. Save drone-view model in models/drone_view_general/.
13. Create multi-model detection pipeline.
14. Upgrade Gazebo world into multi-zone surveillance scene.
15. Create waypoint mission system.
16. Fly drone through all zones automatically.
17. Save annotated frames, detection CSV, telemetry CSV during full mission.
18. Merge full-mission detection and telemetry logs.
19. Generate full mission report.
20. Add QGIS mission-area map.
21. Export zones and waypoints as GeoJSON/CSV.
22. Parse QGIS mission map in Python.
23. Add Genetic Algorithm route optimization.
24. Compare normal route vs optimized route.
25. Add AI-based autonomous route selection.
26. Update dashboard with route, zones, detections, telemetry, reports, and real-time feed.
27. Add swarm simulation with 3 drones first.
28. Add multi-drone zone assignment.
29. Add detection sharing between drones.
30. Add event sharing between drones.
31. Optional MATLAB/Simulink comparison.
32. Prepare final documentation.
33. Prepare screenshots and demo video.
34. Prepare mentor weekly progress report.
35. Prepare final internship/project report.
