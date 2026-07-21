# BSERC Drone Swarm Project Progress Update
## Milestone: Simulated Drone Camera Feed + YOLO Detection Validation

### Objective
The objective of this milestone was to validate the perception pipeline for the drone swarm intelligence project using simulation before moving to hardware.

### Completed Work
1. Started PX4 SITL with the x500_mono_cam drone model.
2. Verified the Gazebo camera topic was publishing image data.
3. Bridged the Gazebo camera topic to ROS 2 using ros_gz_bridge.
4. Created a Python ROS 2 frame saver to capture camera frames.
5. Saved simulated drone-camera frames into the project output directory.
6. Created a YOLO validation scene using COCO-detectable objects.
7. Ran YOLOv8n inference on captured camera frames.
8. Verified successful detection of persons and vehicle/bus/truck-like classes.
9. Created a larger battlefield-style validation panel with multiple regions.

### Key Result
The end-to-end perception pipeline is now working:

PX4/Gazebo simulated drone camera
→ ROS 2 image stream
→ Python/OpenCV frame capture
→ YOLO object detection
→ annotated output images

### Observed YOLO Result
In the validation scene, YOLO detected visible COCO-known objects such as persons and bus/truck-like vehicles. It did not detect custom scene elements such as barricade structures or incident markers because these are not part of the pretrained COCO classes.

### Current Limitation
The pretrained YOLO model can detect standard COCO classes but cannot reliably detect custom battlefield-specific classes such as barricades, tents, smoke markers, or custom military structures.

### Next Step
The next step is to create or obtain a custom dataset and fine-tune YOLO for project-specific classes. The future model will be used for human-review event reporting only, not autonomous targeting or engagement.

### Safety Boundary
This project is limited to surveillance, perception, telemetry analysis, event flagging, and human-review reporting. It does not include autonomous targeting, weapon control, or attack planning.
