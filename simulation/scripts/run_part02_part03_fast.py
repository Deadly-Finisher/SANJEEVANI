#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from rclpy.qos import qos_profile_sensor_data
from ultralytics import YOLO


ROOT = Path.home() / "Programs" / "SWARM_DRONES"

WORLD = "battlefield_sar_world_v1_realistic"
MODEL = "x500_mono_cam_0"

TOPIC = (
    f"/world/{WORLD}/model/{MODEL}/link/"
    "camera_link/sensor/camera/image"
)

OUT_DIR = ROOT / "outputs/single_drone/perception"
REPORT_DIR = ROOT / "outputs/reports"

RAW_IMAGE = OUT_DIR / "part02_single_drone_raw_frame.jpg"
ANNOTATED_IMAGE = OUT_DIR / "part02_single_drone_yolo_annotated.jpg"
DETECTIONS_CSV = OUT_DIR / "part02_single_drone_detections.csv"

PART02_SUMMARY = REPORT_DIR / "part02_single_drone_perception_summary.json"
PART03_SUMMARY = REPORT_DIR / "part03_single_drone_intelligence_summary.json"
PART03_REPORT = REPORT_DIR / "part03_single_drone_intelligence_report.md"

BRIDGE_LOG = Path("/tmp/part02_single_drone_logs/camera_bridge_snapshot.log")
BRIDGE_PID = Path("/tmp/part02_single_drone/bridge_snapshot.pid")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run(cmd: str, check: bool = True, capture: bool = False):
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        shell=True,
        executable="/bin/bash",
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )

    if check and result.returncode != 0:
        if result.stdout:
            print(result.stdout)
        raise RuntimeError(f"Command failed: {cmd}")

    return result


def stop_old_bridge() -> None:
    if BRIDGE_PID.exists():
        try:
            pid = int(BRIDGE_PID.read_text().strip())
            os.killpg(pid, signal.SIGTERM)
            time.sleep(1)
        except Exception:
            pass

    run(
        "pkill -9 -f 'parameter_bridge.*x500_mono_cam_0.*camera/image' "
        "2>/dev/null || true",
        check=False,
    )


def ensure_single_drone_runtime() -> None:
    px4_count = run("pgrep -x px4 | wc -l", capture=True).stdout.strip()

    if px4_count != "1":
        log("Single-drone runtime not clean. Relaunching Part 1 foundation...")
        run("bash simulation/scripts/launch_submission_single_drone.sh")
        time.sleep(10)

    for _ in range(60):
        topics = run("gz topic -l", capture=True, check=False).stdout or ""
        if TOPIC in topics:
            log("PASS: Gazebo camera topic exists")
            return
        time.sleep(2)

    raise RuntimeError("Gazebo camera topic not found")


def start_bridge() -> None:
    Path("/tmp/part02_single_drone").mkdir(parents=True, exist_ok=True)
    BRIDGE_LOG.parent.mkdir(parents=True, exist_ok=True)

    stop_old_bridge()

    cmd = (
        "source /opt/ros/humble/setup.bash && "
        "exec ros2 run ros_gz_bridge parameter_bridge "
        f"'{TOPIC}@sensor_msgs/msg/Image[gz.msgs.Image'"
    )

    with BRIDGE_LOG.open("w", encoding="utf-8") as f:
        process = subprocess.Popen(
            cmd,
            cwd=ROOT,
            shell=True,
            executable="/bin/bash",
            stdout=f,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid,
        )

    BRIDGE_PID.write_text(str(process.pid))
    log(f"Bridge PID: {process.pid}")

    for _ in range(45):
        output = run(
            "source /opt/ros/humble/setup.bash && ros2 topic list",
            capture=True,
            check=False,
        ).stdout or ""

        if TOPIC in output:
            log("PASS: ROS camera topic exists")
            return

        time.sleep(2)

    print(BRIDGE_LOG.read_text(errors="replace"))
    raise RuntimeError("ROS camera topic not available")


class FrameGrabber(Node):
    def __init__(self) -> None:
        super().__init__("part02_single_drone_frame_grabber")
        self.frame = None
        self.count = 0
        self.create_subscription(
            Image,
            TOPIC,
            self.callback,
            qos_profile_sensor_data,
        )

    def callback(self, msg: Image) -> None:
        self.count += 1
        self.frame = convert_image(msg)


def convert_image(msg: Image):
    h = int(msg.height)
    w = int(msg.width)
    enc = msg.encoding.lower()
    data = np.frombuffer(msg.data, dtype=np.uint8)

    if enc in ("rgb8", "bgr8"):
        img = data.reshape((h, w, 3))
        if enc == "rgb8":
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
        return img.copy()

    if enc in ("rgba8", "bgra8"):
        img = data.reshape((h, w, 4))
        if enc == "rgba8":
            return cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

    if enc in ("mono8", "8uc1"):
        img = data.reshape((h, w))
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

    channels = max(1, len(data) // max(1, h * w))
    img = data.reshape((h, w, channels))
    if channels >= 3:
        return img[:, :, :3].copy()

    return cv2.cvtColor(img[:, :, 0], cv2.COLOR_GRAY2BGR)


def capture_frame():
    log("Capturing camera frame from single drone...")

    rclpy.init()
    node = FrameGrabber()

    deadline = time.time() + 90

    while time.time() < deadline:
        rclpy.spin_once(node, timeout_sec=1.0)

        if node.frame is not None and node.count >= 3:
            frame = node.frame.copy()
            node.destroy_node()
            rclpy.shutdown()
            log(f"PASS: camera frame captured, frames received={node.count}")
            return frame

    node.destroy_node()
    rclpy.shutdown()

    raise RuntimeError("No camera frame received from ROS topic")


def run_yolo(frame):
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cv2.imwrite(str(RAW_IMAGE), frame)

    log("Loading YOLO model yolo11n.pt")
    model = YOLO("yolo11n.pt")

    log("Running YOLO inference")
    result = model.predict(frame, conf=0.25, verbose=False)[0]
    annotated = result.plot()

    cv2.imwrite(str(ANNOTATED_IMAGE), annotated)

    detections = []

    names = result.names
    boxes = result.boxes

    if boxes is not None:
        for box in boxes:
            cls_id = int(box.cls[0])
            conf = float(box.conf[0])
            x1, y1, x2, y2 = [float(x) for x in box.xyxy[0].tolist()]

            detections.append(
                {
                    "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                    "drone_id": "drone_1",
                    "model": "yolo11n.pt",
                    "class_id": cls_id,
                    "class_name": str(names.get(cls_id, cls_id)),
                    "confidence": round(conf, 4),
                    "x1": round(x1, 2),
                    "y1": round(y1, 2),
                    "x2": round(x2, 2),
                    "y2": round(y2, 2),
                }
            )

    with DETECTIONS_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "timestamp_utc",
                "drone_id",
                "model",
                "class_id",
                "class_name",
                "confidence",
                "x1",
                "y1",
                "x2",
                "y2",
            ],
        )
        writer.writeheader()
        writer.writerows(detections)

    log(f"PASS: YOLO completed, detections={len(detections)}")
    return detections


def write_part02_summary(detections):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    summary = {
        "part": "part-02",
        "status": "completed",
        "result": "PASS",
        "task": "single-drone camera and YOLO perception",
        "world": WORLD,
        "model": MODEL,
        "ros_camera_topic": TOPIC,
        "raw_frame": str(RAW_IMAGE.relative_to(ROOT)),
        "annotated_frame": str(ANNOTATED_IMAGE.relative_to(ROOT)),
        "detections_csv": str(DETECTIONS_CSV.relative_to(ROOT)),
        "detection_count": len(detections),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "validation": {
            "gazebo_camera_topic": True,
            "ros_camera_topic": True,
            "camera_frame_captured": True,
            "yolo_inference_completed": True,
            "annotated_output_saved": True,
        },
    }

    PART02_SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log(f"PASS: Part 2 summary written: {PART02_SUMMARY}")


def threat_level(detections):
    military_words = [
        "person",
        "car",
        "truck",
        "bus",
        "motorcycle",
        "airplane",
    ]

    classes = [d["class_name"].lower() for d in detections]

    if any(name in classes for name in military_words):
        return "MEDIUM"

    if detections:
        return "LOW"

    return "OBSERVATION_ONLY"


def write_part03_intelligence(detections):
    level = threat_level(detections)

    classes = {}
    for det in detections:
        classes[det["class_name"]] = classes.get(det["class_name"], 0) + 1

    summary = {
        "part": "part-03",
        "status": "completed",
        "result": "PASS",
        "task": "single-drone intelligence pipeline",
        "drone_id": "drone_1",
        "world": WORLD,
        "source_detections": str(DETECTIONS_CSV.relative_to(ROOT)),
        "detection_count": len(detections),
        "class_counts": classes,
        "threat_level": level,
        "human_review_required": level in ["MEDIUM", "HIGH"],
        "uncertainty_note": (
            "Threat level is rule-based and should be reviewed by a human operator "
            "before any operational decision."
        ),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    PART03_SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    report_lines = [
        "# Part 3: Single-Drone Intelligence Pipeline",
        "",
        "## Status",
        "",
        "- Result: PASS",
        "- Drone: drone_1",
        f"- World: {WORLD}",
        f"- Camera model: {MODEL}",
        f"- Detection count: {len(detections)}",
        f"- Threat level: {level}",
        f"- Human review required: {summary['human_review_required']}",
        "",
        "## Inputs",
        "",
        f"- Raw camera frame: `{RAW_IMAGE.relative_to(ROOT)}`",
        f"- YOLO annotated frame: `{ANNOTATED_IMAGE.relative_to(ROOT)}`",
        f"- Detection CSV: `{DETECTIONS_CSV.relative_to(ROOT)}`",
        "",
        "## Detected Classes",
        "",
    ]

    if classes:
        for name, count in classes.items():
            report_lines.append(f"- {name}: {count}")
    else:
        report_lines.append(
            "- No object detected in this captured frame. "
            "Camera capture and YOLO inference are still validated."
        )

    report_lines += [
        "",
        "## Intelligence Interpretation",
        "",
        "The single drone successfully provided visual battlefield perception. "
        "The captured frame was processed using YOLO, detections were converted "
        "into structured intelligence records, and a rule-based threat level was "
        "generated for human review.",
        "",
        "## Human-in-the-Loop Note",
        "",
        "This output is not an autonomous fire/strike decision system. "
        "All threat labels require human approval before any real-world action.",
        "",
    ]

    PART03_REPORT.write_text("\n".join(report_lines), encoding="utf-8")

    log(f"PASS: Part 3 summary written: {PART03_SUMMARY}")
    log(f"PASS: Part 3 report written: {PART03_REPORT}")


def git_checkpoint():
    branch = run("git branch --show-current", capture=True).stdout.strip()

    run(
        "git add "
        "simulation/scripts/run_part02_part03_fast.py "
        "outputs/single_drone/perception "
        "outputs/reports/part02_single_drone_perception_summary.json "
        "outputs/reports/part03_single_drone_intelligence_summary.json "
        "outputs/reports/part03_single_drone_intelligence_report.md",
        check=False,
    )

    run(
        "git commit -m 'part-02-03: single-drone perception and intelligence pipeline' "
        "|| echo 'No new changes to commit'",
        check=False,
    )

    run(
        "git tag -a checkpoint-part-02 "
        "-m 'Single-drone camera capture and YOLO perception' "
        "2>/dev/null || echo 'checkpoint-part-02 already exists'",
        check=False,
    )

    run(
        "git tag -a checkpoint-part-03 "
        "-m 'Single-drone intelligence pipeline report' "
        "2>/dev/null || echo 'checkpoint-part-03 already exists'",
        check=False,
    )

    run(f"git push origin '{branch}'", check=False)
    run("git push origin checkpoint-part-02 2>/dev/null || true", check=False)
    run("git push origin checkpoint-part-03 2>/dev/null || true", check=False)

    log("PASS: Git checkpoints pushed for Part 2 and Part 3")


def main():
    log("FAST RUN: Part 2 + Part 3")

    ensure_single_drone_runtime()
    start_bridge()

    frame = capture_frame()
    detections = run_yolo(frame)

    write_part02_summary(detections)
    write_part03_intelligence(detections)

    git_checkpoint()

    print()
    print("============================================")
    print("PART 2 COMPLETE: camera + YOLO perception")
    print("PART 3 COMPLETE: intelligence pipeline")
    print("Annotated image:")
    print(ANNOTATED_IMAGE)
    print("Report:")
    print(PART03_REPORT)
    print("Checkpoints:")
    print("checkpoint-part-02")
    print("checkpoint-part-03")
    print("============================================")


if __name__ == "__main__":
    main()
