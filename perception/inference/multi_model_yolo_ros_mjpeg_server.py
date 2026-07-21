from pathlib import Path
import os
from datetime import datetime
import csv
import threading
import time

import cv2
import yaml
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
from ultralytics import YOLO
from flask import Flask, Response


app = Flask(__name__)

latest_frame = None
latest_frame_lock = threading.Lock()


def load_config(path: str) -> dict:
    with open(path, "r") as file:
        return yaml.safe_load(file)


class MultiModelYoloRosMjpegServer(Node):
    def __init__(self, config: dict):
        super().__init__(
            os.environ.get(
                "SWARM_YOLO_NODE_NAME",
                "multi_model_yolo_ros_mjpeg_server",
            )
        )

        self.config = config
        self.topic = config["input"]["ros_image_topic"]

        self.csv_path = Path(config["output"]["csv_path"])
        self.annotated_frame_dir = Path(config["output"]["annotated_frame_dir"])
        self.save_annotated_frames = bool(config["output"]["save_annotated_frames"])
        self.save_every_n_frames = int(config["output"]["save_every_n_frames"])

        self.inference_every_n_frames = int(config["runtime"]["inference_every_n_frames"])
        self.jpeg_quality = int(config["stream"]["jpeg_quality"])

        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.annotated_frame_dir.mkdir(parents=True, exist_ok=True)

        self.bridge = CvBridge()
        self.frame_count = 0
        self.detection_count = 0

        self.models = []

        for model_cfg in config["models"]:
            if not model_cfg.get("enabled", True):
                continue

            weights_path = Path(model_cfg["weights_path"])

            if not weights_path.exists():
                raise FileNotFoundError(f"Model weights not found: {weights_path}")

            model_name = model_cfg["model_name"]

            self.get_logger().info(f"Loading model: {model_name} from {weights_path}")

            model = YOLO(str(weights_path))

            self.models.append({
                "model_name": model_name,
                "model": model,
                "confidence_threshold": float(model_cfg["confidence_threshold"]),
                "image_size": int(model_cfg["image_size"]),
            })

            self.get_logger().info(f"{model_name} labels: {model.names}")

        self.csv_file = open(self.csv_path, "w", newline="")
        self.csv_writer = csv.DictWriter(
            self.csv_file,
            fieldnames=[
                "timestamp",
                "frame_id",
                "model_name",
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
            self.topic,
            self.image_callback,
            10,
        )

        self.get_logger().info(f"Subscribed to ROS image topic: {self.topic}")
        self.get_logger().info("Multi-model stream: http://localhost:5001/video_feed")

    def image_callback(self, msg: Image) -> None:
        global latest_frame

        self.frame_count += 1

        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().error(f"Image conversion failed: {exc}")
            return

        if self.frame_count % self.inference_every_n_frames != 0:
            return

        annotated_frame = frame.copy()

        for model_info in self.models:
            model_name = model_info["model_name"]
            model = model_info["model"]
            conf = model_info["confidence_threshold"]
            imgsz = model_info["image_size"]

            results = model(
                frame,
                conf=conf,
                imgsz=imgsz,
                verbose=False,
            )

            result = results[0]

            if result.boxes is None:
                continue

            for box in result.boxes:
                class_id = int(box.cls[0])
                class_name = model.names[class_id]
                confidence = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()

                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

                self.detection_count += 1

                display_label_map = {
                    "person": "person",
                    "pedestrian": "person",
                    "people": "person",
                    "civilian_person": "person",
                    "uniformed_person_review": "person",
                    "person_camouflage_review": "person",

                    "car": "vehicle",
                    "van": "vehicle",
                    "truck": "vehicle",
                    "bus": "vehicle",
                    "motor": "vehicle",
                    "bicycle": "vehicle",
                    "tricycle": "vehicle",
                    "awning-tricycle": "vehicle",
                    "civilian_vehicle": "vehicle",
                    "heavy_vehicle_review": "vehicle",
                    "special_vehicle_review": "vehicle",
                    "tracked_vehicle_review": "vehicle",

                    "potted plant": "tree",
                    "plant": "tree",
                    "tree": "tree",

                    "smoke": "smoke",
                    "fire": "fire",
                }

                label = display_label_map.get(class_name, class_name)

                # Red boxes and red labels for better visibility
                red_color = (0, 0, 255)

                cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), red_color, 3)
                cv2.putText(
                    annotated_frame,
                    label,
                    (x1, max(y1 - 8, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.65,
                    red_color,
                    2,
                )

                self.csv_writer.writerow({
                    "timestamp": datetime.now().isoformat(),
                    "frame_id": self.frame_count,
                    "model_name": model_name,
                    "class_id": class_id,
                    "class_name": class_name,
                    "confidence": round(confidence, 4),
                    "x1": round(x1, 2),
                    "y1": round(y1, 2),
                    "x2": round(x2, 2),
                    "y2": round(y2, 2),
                })
                self.csv_file.flush()

        cv2.putText(
            annotated_frame,
            f"Frame: {self.frame_count} | Total detections: {self.detection_count}",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )

        if self.save_annotated_frames and self.frame_count % self.save_every_n_frames == 0:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            output_path = self.annotated_frame_dir / f"multi_model_{timestamp}.jpg"
            cv2.imwrite(str(output_path), annotated_frame)

        with latest_frame_lock:
            latest_frame = annotated_frame.copy()

    def destroy_node(self):
        try:
            self.csv_file.close()
            cv2.destroyAllWindows()
        except Exception:
            pass

        super().destroy_node()


def generate_mjpeg_stream():
    global latest_frame

    while True:
        with latest_frame_lock:
            frame = None if latest_frame is None else latest_frame.copy()

        if frame is None:
            time.sleep(0.05)
            continue

        success, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])

        if not success:
            continue

        frame_bytes = buffer.tobytes()

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n"
        )


@app.route("/")
def index():
    return "Multi-model YOLO ROS MJPEG server running. Open /video_feed"


@app.route("/video_feed")
def video_feed():
    return Response(
        generate_mjpeg_stream(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


def start_flask_server(config: dict):
    host = config["stream"]["host"]
    port = int(config["stream"]["port"])
    app.run(host=host, port=port, debug=False, threaded=True, use_reloader=False)


def main():
    config_path = os.environ.get(
        "SWARM_YOLO_CONFIG",
        "configs/perception/"
        "multi_model_yolo_ros_mjpeg_server.yaml",
    )

    config = load_config(config_path)

    flask_thread = threading.Thread(
        target=start_flask_server,
        args=(config,),
        daemon=True,
    )
    flask_thread.start()

    rclpy.init()
    node = MultiModelYoloRosMjpegServer(config)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
