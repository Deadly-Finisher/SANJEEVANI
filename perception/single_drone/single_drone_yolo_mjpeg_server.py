#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
import rclpy
from flask import Flask, Response, jsonify
from rclpy.node import Node
from sensor_msgs.msg import Image
from ultralytics import YOLO


class SingleDroneYoloServer(Node):
    def __init__(
        self,
        *,
        topic: str,
        model_path: str,
        output_csv: Path,
        confidence: float,
        inference_every_n_frames: int,
        jpeg_quality: int,
    ) -> None:
        super().__init__("single_drone_yolo_mjpeg_server")

        self.topic = topic
        self.model = YOLO(model_path)
        self.confidence = confidence
        self.inference_every_n_frames = max(1, inference_every_n_frames)
        self.jpeg_quality = jpeg_quality

        self.lock = threading.Lock()
        self.latest_jpeg: bytes | None = None
        self.latest_detections: list[dict] = []
        self.frame_count = 0
        self.image_count = 0
        self.detection_count = 0

        output_csv.parent.mkdir(parents=True, exist_ok=True)
        self.csv_file = output_csv.open("w", newline="", encoding="utf-8")
        self.csv_writer = csv.DictWriter(
            self.csv_file,
            fieldnames=[
                "timestamp_utc",
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
        self.csv_writer.writeheader()

        self.subscription = self.create_subscription(
            Image,
            topic,
            self.on_image,
            10,
        )

        self.get_logger().info(f"Subscribed to ROS image topic: {topic}")
        self.get_logger().info(f"Loaded YOLO model: {model_path}")

    def image_to_bgr(self, msg: Image) -> np.ndarray:
        height = int(msg.height)
        width = int(msg.width)
        encoding = msg.encoding.lower()

        array = np.frombuffer(msg.data, dtype=np.uint8)

        if encoding in ("rgb8", "bgr8"):
            image = array.reshape((height, width, 3))
            if encoding == "rgb8":
                image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            return image.copy()

        if encoding in ("rgba8", "bgra8"):
            image = array.reshape((height, width, 4))
            if encoding == "rgba8":
                image = cv2.cvtColor(image, cv2.COLOR_RGBA2BGR)
            else:
                image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            return image.copy()

        if encoding in ("mono8", "8uc1"):
            image = array.reshape((height, width))
            return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

        # Common Gazebo fallback
        channels = max(1, int(len(array) / max(1, height * width)))
        image = array.reshape((height, width, channels))
        if channels >= 3:
            return image[:, :, :3].copy()

        return cv2.cvtColor(image[:, :, 0], cv2.COLOR_GRAY2BGR)

    def on_image(self, msg: Image) -> None:
        self.image_count += 1
        self.frame_count += 1

        frame = self.image_to_bgr(msg)
        annotated = frame
        detections: list[dict] = []

        if self.frame_count % self.inference_every_n_frames == 0:
            results = self.model.predict(
                frame,
                conf=self.confidence,
                verbose=False,
            )

            annotated = results[0].plot()

            names = results[0].names
            boxes = results[0].boxes

            if boxes is not None:
                for box in boxes:
                    cls_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    x1, y1, x2, y2 = [
                        float(v)
                        for v in box.xyxy[0].tolist()
                    ]

                    item = {
                        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                        "model": "single_drone_yolo",
                        "class_id": cls_id,
                        "class_name": str(names.get(cls_id, cls_id)),
                        "confidence": round(conf, 4),
                        "x1": round(x1, 2),
                        "y1": round(y1, 2),
                        "x2": round(x2, 2),
                        "y2": round(y2, 2),
                    }

                    detections.append(item)
                    self.csv_writer.writerow(item)

                self.csv_file.flush()
                self.detection_count += len(detections)

            self.latest_detections = detections

        ok, encoded = cv2.imencode(
            ".jpg",
            annotated,
            [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
        )

        if ok:
            with self.lock:
                self.latest_jpeg = encoded.tobytes()

    def get_frame(self) -> bytes | None:
        with self.lock:
            return self.latest_jpeg

    def get_status(self) -> dict:
        return {
            "status": "ready" if self.latest_jpeg else "waiting_for_image",
            "topic": self.topic,
            "images_received": self.image_count,
            "total_detections": self.detection_count,
            "latest_detections": self.latest_detections,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", required=True)
    parser.add_argument("--model", default="yolo11n.pt")
    parser.add_argument("--port", type=int, default=5021)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--inference-every-n-frames", type=int, default=6)
    parser.add_argument("--jpeg-quality", type=int, default=75)

    args = parser.parse_args()

    rclpy.init()

    node = SingleDroneYoloServer(
        topic=args.topic,
        model_path=args.model,
        output_csv=Path(args.output_csv),
        confidence=args.confidence,
        inference_every_n_frames=args.inference_every_n_frames,
        jpeg_quality=args.jpeg_quality,
    )

    ros_thread = threading.Thread(
        target=lambda: rclpy.spin(node),
        daemon=True,
    )
    ros_thread.start()

    app = Flask(__name__)

    @app.route("/")
    @app.route("/health")
    def health():
        return jsonify(node.get_status())

    @app.route("/detections")
    def detections():
        return jsonify(node.get_status()["latest_detections"])

    @app.route("/video_feed")
    def video_feed():
        def generate():
            while True:
                frame = node.get_frame()
                if frame is None:
                    time.sleep(0.1)
                    continue

                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + frame
                    + b"\r\n"
                )
                time.sleep(0.03)

        return Response(
            generate(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    try:
        app.run(host="0.0.0.0", port=args.port, threaded=True)
    finally:
        node.csv_file.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
