import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import rclpy
import yaml
from rclpy.node import Node
from sensor_msgs.msg import Image


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Save frames from a ROS 2 camera image topic."
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to ROS camera capture YAML config file.",
    )
    return parser.parse_args()


def load_yaml_config(config_path: str) -> dict[str, Any]:
    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError("Config file must contain a YAML dictionary.")

    return config


def validate_config(config: dict[str, Any]) -> None:
    for section in ["camera", "output", "safety"]:
        if section not in config:
            raise ValueError(f"Missing required config section: {section}")

    safety = config["safety"]

    if bool(safety["allow_targeting"]):
        raise ValueError("Unsafe config: allow_targeting must remain false.")

    if bool(safety["allow_autonomous_engagement"]):
        raise ValueError("Unsafe config: allow_autonomous_engagement must remain false.")

    if not bool(safety["human_review_required"]):
        raise ValueError("Unsafe config: human_review_required must remain true.")


def create_output_paths(config: dict[str, Any]) -> dict[str, Path]:
    output_dir = Path(config["output"]["output_dir"])
    frames_dir = output_dir / config["output"]["frames_dir"]
    metadata_csv = output_dir / config["output"]["metadata_csv"]
    summary_file = output_dir / config["output"]["summary_file"]

    frames_dir.mkdir(parents=True, exist_ok=True)

    return {
        "output_dir": output_dir,
        "frames_dir": frames_dir,
        "metadata_csv": metadata_csv,
        "summary_file": summary_file,
    }


def ros_image_to_cv2_bgr(message: Image) -> np.ndarray:
    height = int(message.height)
    width = int(message.width)
    step = int(message.step)
    encoding = message.encoding.lower()

    raw = np.frombuffer(message.data, dtype=np.uint8)

    if encoding == "rgb8":
        image = raw.reshape((height, step))[:, : width * 3]
        image = image.reshape((height, width, 3))
        return cv2.cvtColor(image, cv2.COLOR_RGB2BGR)

    if encoding == "bgr8":
        image = raw.reshape((height, step))[:, : width * 3]
        return image.reshape((height, width, 3))

    if encoding == "rgba8":
        image = raw.reshape((height, step))[:, : width * 4]
        image = image.reshape((height, width, 4))
        return cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)

    if encoding == "bgra8":
        image = raw.reshape((height, step))[:, : width * 4]
        image = image.reshape((height, width, 4))
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

    if encoding in ["mono8", "8uc1"]:
        image = raw.reshape((height, step))[:, :width]
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

    raise ValueError(f"Unsupported image encoding: {message.encoding}")


class CameraFrameSaver(Node):
    def __init__(self, config: dict[str, Any], paths: dict[str, Path]) -> None:
        super().__init__("camera_frame_saver")

        self.config = config
        self.paths = paths

        self.camera_topic = config["camera"]["ros_topic"]
        self.max_frames = int(config["camera"]["max_frames"])
        self.save_every_n_frames = int(config["camera"]["save_every_n_frames"])

        self.received_frame_count = 0
        self.saved_frame_count = 0
        self.metadata_rows: list[dict[str, Any]] = []

        self.create_subscription(
            Image,
            self.camera_topic,
            self.image_callback,
            10,
        )

        self.get_logger().info(f"Subscribed to camera topic: {self.camera_topic}")
        self.get_logger().info(f"Target saved frames: {self.max_frames}")

    def image_callback(self, message: Image) -> None:
        self.received_frame_count += 1

        if self.received_frame_count % self.save_every_n_frames != 0:
            return

        if self.saved_frame_count >= self.max_frames:
            return

        frame_bgr = ros_image_to_cv2_bgr(message)

        timestamp_utc = datetime.now(timezone.utc).isoformat()
        frame_id = f"camera_frame_{self.saved_frame_count:04d}"
        frame_file = self.paths["frames_dir"] / f"{frame_id}.png"

        success = cv2.imwrite(str(frame_file), frame_bgr)

        if not success:
            self.get_logger().error(f"Failed to save frame: {frame_file}")
            return

        self.metadata_rows.append(
            {
                "frame_id": frame_id,
                "timestamp_utc": timestamp_utc,
                "ros_topic": self.camera_topic,
                "height": int(message.height),
                "width": int(message.width),
                "encoding": message.encoding,
                "step": int(message.step),
                "saved_path": str(frame_file),
            }
        )

        self.saved_frame_count += 1

        self.get_logger().info(
            f"Saved {frame_file} ({self.saved_frame_count}/{self.max_frames})"
        )

    def is_done(self) -> bool:
        return self.saved_frame_count >= self.max_frames

    def save_metadata(self) -> None:
        fieldnames = [
            "frame_id",
            "timestamp_utc",
            "ros_topic",
            "height",
            "width",
            "encoding",
            "step",
            "saved_path",
        ]

        with self.paths["metadata_csv"].open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.metadata_rows)

    def save_summary(self) -> None:
        summary = f"""
ROS Camera Frame Capture Summary

Camera topic:
{self.camera_topic}

Received frames:
{self.received_frame_count}

Saved frames:
{self.saved_frame_count}

Output directory:
{self.paths["frames_dir"]}

Metadata CSV:
{self.paths["metadata_csv"]}

Result:
Real simulated drone-camera frames were captured from the Gazebo x500_mono_cam model through ROS 2 and saved as image files.

Safety boundary:
This module only captures simulated camera frames for perception and human-review analysis. It does not perform targeting or autonomous engagement.
""".strip()

        self.paths["summary_file"].write_text(summary, encoding="utf-8")


def main() -> None:
    args = parse_arguments()

    config = load_yaml_config(args.config)
    validate_config(config)
    paths = create_output_paths(config)

    rclpy.init()
    node = CameraFrameSaver(config=config, paths=paths)

    try:
        while rclpy.ok() and not node.is_done():
            rclpy.spin_once(node, timeout_sec=1.0)

        node.save_metadata()
        node.save_summary()

        print(f"Saved frames: {node.saved_frame_count}")
        print(f"Frame directory: {paths['frames_dir']}")
        print(f"Metadata CSV: {paths['metadata_csv']}")
        print(f"Summary file: {paths['summary_file']}")

    finally:
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
