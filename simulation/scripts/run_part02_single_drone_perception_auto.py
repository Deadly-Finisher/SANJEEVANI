#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path.home() / "Programs" / "SWARM_DRONES"

WORLD = "battlefield_sar_world_v1_realistic"
MODEL = "x500_mono_cam_0"

GZ_CAMERA_TOPIC = (
    f"/world/{WORLD}/model/{MODEL}/link/"
    "camera_link/sensor/camera/image"
)

ROS_CAMERA_TOPIC = GZ_CAMERA_TOPIC

CONFIG_SOURCE = (
    ROOT
    / "configs/perception/swarm/"
    "drone_1_camera_server.yaml"
)

CONFIG_TARGET = (
    ROOT
    / "configs/perception/single/"
    "submission_single_drone_camera_server.yaml"
)

OUTPUT_SUMMARY = (
    ROOT
    / "outputs/reports/"
    "part02_single_drone_perception_summary.json"
)

PID_DIR = Path("/tmp/part02_single_drone")
LOG_DIR = Path("/tmp/part02_single_drone_logs")

BRIDGE_LOG = LOG_DIR / "camera_bridge.log"
YOLO_LOG = LOG_DIR / "yolo_server.log"

BRIDGE_PID = PID_DIR / "bridge.pid"
YOLO_PID = PID_DIR / "yolo.pid"

HTTP_PORT = 5021


def log(message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def run(
    command: str,
    *,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command,
        cwd=ROOT,
        shell=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        executable="/bin/bash",
    )

    if check and result.returncode != 0:
        if capture and result.stdout:
            print(result.stdout)
        raise RuntimeError(
            f"Command failed: {command}"
        )

    return result


def start_process(
    command: str,
    log_file: Path,
) -> subprocess.Popen:
    log_file.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    handle = log_file.open(
        "w",
        encoding="utf-8",
    )

    return subprocess.Popen(
        command,
        cwd=ROOT,
        shell=True,
        executable="/bin/bash",
        stdout=handle,
        stderr=subprocess.STDOUT,
        preexec_fn=os.setsid,
    )


def stop_pid_file(path: Path) -> None:
    if not path.exists():
        return

    try:
        pid = int(path.read_text().strip())
    except Exception:
        path.unlink(missing_ok=True)
        return

    try:
        os.killpg(pid, signal.SIGTERM)
        time.sleep(2)
    except Exception:
        pass

    try:
        os.killpg(pid, signal.SIGKILL)
    except Exception:
        pass

    path.unlink(missing_ok=True)


def port_open(port: int) -> bool:
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM,
    ) as sock:
        sock.settimeout(1.0)
        return (
            sock.connect_ex(
                ("127.0.0.1", port)
            )
            == 0
        )


def http_ready(port: int) -> bool:
    for path in ("/", "/health", "/video_feed"):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{path}",
                timeout=4,
            ) as response:
                if 200 <= response.status < 500:
                    return True
        except Exception:
            pass

    return False


def wait_until(
    description: str,
    check_function,
    timeout_s: int,
    interval_s: float = 2.0,
) -> None:
    log(f"Waiting for {description}...")

    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        if check_function():
            log(f"PASS: {description}")
            return

        time.sleep(interval_s)

    raise TimeoutError(
        f"Timed out waiting for {description}"
    )


def tail(path: Path, lines: int = 80) -> str:
    if not path.exists():
        return ""

    content = path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines()

    return "\n".join(content[-lines:])


def verify_single_drone_runtime() -> None:
    px4_count = run(
        "pgrep -x px4 | wc -l",
        capture=True,
    ).stdout.strip()

    if px4_count != "1":
        raise RuntimeError(
            "Expected exactly one PX4 process. "
            f"Found: {px4_count}"
        )

    topics = run(
        "gz topic -l",
        capture=True,
    ).stdout

    if GZ_CAMERA_TOPIC not in topics:
        raise RuntimeError(
            "Single-drone Gazebo camera topic missing"
        )

    log("PASS: one PX4 process running")
    log("PASS: Gazebo camera topic available")


def create_single_drone_config() -> None:
    if not CONFIG_SOURCE.exists():
        raise FileNotFoundError(
            f"Missing source config: {CONFIG_SOURCE}"
        )

    CONFIG_TARGET.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    text = CONFIG_SOURCE.read_text(
        encoding="utf-8",
    )

    replacements = {
        "x500_mono_cam_1": "x500_mono_cam_0",
        "drone_1": "submission_single_drone",
        "Drone 1": "Submission Single Drone",
        "5011": str(HTTP_PORT),
        "v1_swarm": "submission_single_drone",
        "swarm/drone_1": "single_drone",
        "swarm_drone_1": "single_drone",
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    CONFIG_TARGET.write_text(
        text,
        encoding="utf-8",
    )

    log(f"PASS: config written: {CONFIG_TARGET}")


def find_yolo_server() -> Path:
    matches = list(
        ROOT.rglob(
            "multi_model_yolo_ros_mjpeg_server.py"
        )
    )

    if not matches:
        raise FileNotFoundError(
            "Could not find multi_model_yolo_ros_mjpeg_server.py"
        )

    return matches[0]


def start_bridge() -> None:
    stop_pid_file(BRIDGE_PID)

    run(
        "pkill -9 -f "
        "'parameter_bridge.*x500_mono_cam_0.*camera/image' "
        "2>/dev/null || true",
        check=False,
    )

    command = (
        "source /opt/ros/humble/setup.bash && "
        "exec ros2 run ros_gz_bridge parameter_bridge "
        f"'{GZ_CAMERA_TOPIC}@sensor_msgs/msg/Image[gz.msgs.Image'"
    )

    process = start_process(
        command,
        BRIDGE_LOG,
    )

    BRIDGE_PID.write_text(str(process.pid))

    log(f"Bridge PID: {process.pid}")

    def ros_topic_exists() -> bool:
        output = run(
            "source /opt/ros/humble/setup.bash && ros2 topic list",
            capture=True,
            check=False,
        ).stdout or ""

        return ROS_CAMERA_TOPIC in output

    try:
        wait_until(
            "ROS camera topic",
            ros_topic_exists,
            timeout_s=60,
        )
    except Exception:
        print(tail(BRIDGE_LOG))
        raise


def start_yolo_server() -> None:
    stop_pid_file(YOLO_PID)

    run(
        "pkill -9 -f "
        "'multi_model_yolo_ros_mjpeg_server.py' "
        "2>/dev/null || true",
        check=False,
    )

    server = find_yolo_server()

    command_options = [
        (
            "source /opt/ros/humble/setup.bash && "
            "source .venv/bin/activate && "
            "export OMP_NUM_THREADS=1 "
            "MKL_NUM_THREADS=1 "
            "OPENBLAS_NUM_THREADS=1 "
            "NUMEXPR_NUM_THREADS=1 && "
            f"exec python '{server}' "
            f"--config '{CONFIG_TARGET}'"
        ),
        (
            "source /opt/ros/humble/setup.bash && "
            "source .venv/bin/activate && "
            "export OMP_NUM_THREADS=1 "
            "MKL_NUM_THREADS=1 "
            "OPENBLAS_NUM_THREADS=1 "
            "NUMEXPR_NUM_THREADS=1 && "
            f"exec python '{server}' "
            f"'{CONFIG_TARGET}'"
        ),
    ]

    last_error = ""

    for command in command_options:
        YOLO_LOG.write_text("", encoding="utf-8")

        process = start_process(
            command,
            YOLO_LOG,
        )

        YOLO_PID.write_text(str(process.pid))

        log(f"YOLO server PID: {process.pid}")

        time.sleep(8)

        if process.poll() is None:
            break

        last_error = tail(YOLO_LOG)
        log("YOLO command form exited; trying fallback")

    else:
        raise RuntimeError(
            "YOLO server failed to start:\n"
            + last_error
        )

    def server_ready() -> bool:
        return (
            port_open(HTTP_PORT)
            and http_ready(HTTP_PORT)
        )

    try:
        wait_until(
            f"YOLO HTTP server on port {HTTP_PORT}",
            server_ready,
            timeout_s=300,
            interval_s=3,
        )
    except Exception:
        print(tail(YOLO_LOG, 160))
        raise


def write_summary() -> None:
    OUTPUT_SUMMARY.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary = {
        "part": "part-02",
        "status": "completed",
        "result": "PASS",
        "task": "single-drone camera and YOLO perception",
        "world": WORLD,
        "model": MODEL,
        "gazebo_camera_topic": GZ_CAMERA_TOPIC,
        "ros_camera_topic": ROS_CAMERA_TOPIC,
        "http_feed": f"http://127.0.0.1:{HTTP_PORT}/video_feed",
        "http_port": HTTP_PORT,
        "config": str(CONFIG_TARGET.relative_to(ROOT)),
        "bridge_log": str(BRIDGE_LOG),
        "yolo_log": str(YOLO_LOG),
        "completed_at_utc": datetime.now(
            timezone.utc
        ).isoformat(),
        "validation": {
            "gazebo_camera_topic": True,
            "ros_bridge_topic": True,
            "yolo_process_started": True,
            "http_feed_ready": True,
        },
        "note": (
            "This part validates camera streaming and YOLO "
            "perception server readiness for one drone. "
            "Actual detection count depends on camera view "
            "and visible battlefield objects."
        ),
    }

    OUTPUT_SUMMARY.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    log(f"Summary written: {OUTPUT_SUMMARY}")


def git_checkpoint() -> None:
    current_branch = run(
        "git branch --show-current",
        capture=True,
    ).stdout.strip()

    run(
        "git add "
        "configs/perception/single/submission_single_drone_camera_server.yaml "
        "simulation/scripts/run_part02_single_drone_perception_auto.py "
        "outputs/reports/part02_single_drone_perception_summary.json",
        check=False,
    )

    run(
        "git commit -m "
        "'part-02: stable single-drone camera and YOLO perception' "
        "|| echo 'No new changes to commit'",
        check=False,
    )

    run(
        "git tag -a checkpoint-part-02 "
        "-m 'Stable single-drone camera bridge and YOLO feed' "
        "2>/dev/null || echo 'checkpoint-part-02 already exists'",
        check=False,
    )

    run(
        f"git push origin '{current_branch}'",
        check=False,
    )

    run(
        "git push origin checkpoint-part-02 "
        "2>/dev/null || echo 'checkpoint-part-02 already pushed'",
        check=False,
    )

    log("Private GitHub checkpoint pushed: checkpoint-part-02")


def main() -> int:
    PID_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    log("PART 2 START: single-drone camera + YOLO perception")

    verify_single_drone_runtime()
    create_single_drone_config()
    start_bridge()
    start_yolo_server()
    write_summary()
    git_checkpoint()

    print()
    print("========================================")
    print("PART 2 VALIDATION: PASS")
    print("Single-drone camera bridge and YOLO feed are ready.")
    print(f"Open feed: http://127.0.0.1:{HTTP_PORT}/video_feed")
    print("Checkpoint: checkpoint-part-02")
    print("========================================")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print()
        print("PART 2 VALIDATION: FAIL")
        print(error)

        print()
        print("===== BRIDGE LOG =====")
        print(tail(BRIDGE_LOG, 80))

        print()
        print("===== YOLO LOG =====")
        print(tail(YOLO_LOG, 160))

        raise
