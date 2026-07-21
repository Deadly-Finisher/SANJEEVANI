from pathlib import Path
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


class YoloRosMjpegServer(Node):
    def __init__(self, config: dict):
        super().__init__("yolo_ros_mjpeg_server")

        self.config = config

        self.topic = config["input"]["ros_image_topic"]

        self.model_name = config["model"]["name"]
        self.confidence_threshold = float(config["model"]["confidence_threshold"])
        self.image_size = int(config["model"]["image_size"])
        self.device = config["model"].get("device", "cpu")

        self.jpeg_quality = int(config["stream"]["jpeg_quality"])

        self.csv_path = Path(config["output"]["csv_path"])
        self.annotated_frame_dir = Path(config["output"]["annotated_frame_dir"])
        self.save_annotated_frames = bool(config["output"]["save_annotated_frames"])
        self.save_every_n_frames = int(config["output"]["save_every_n_frames"])

        self.inference_every_n_frames = int(config["runtime"]["inference_every_n_frames"])
        self.window_display = bool(config["runtime"]["window_display"])

        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self.annotated_frame_dir.mkdir(parents=True, exist_ok=True)

        self.bridge = CvBridge()
        self.frame_count = 0
        self.detection_count = 0

        self.get_logger().info(f"Loading YOLO model: {self.model_name}")
        self.model = YOLO(self.model_name)

        self.csv_file = open(self.csv_path, "w", newline="")
        self.csv_writer = csv.DictWriter(
            self.csv_file,
            fieldnames=[
                "timestamp",
                "frame_id",
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
        self.get_logger().info("MJPEG stream will be available at: http://localhost:5001/video_feed")

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

        results = self.model(
            frame,
            conf=self.confidence_threshold,
            imgsz=self.image_size,
            device=self.device,
            verbose=False,
        )

        result = results[0]
        annotated_frame = result.plot()

        if result.boxes is not None:
            for box in result.boxes:
                class_id = int(box.cls[0])
                class_name = self.model.names[class_id]
                confidence = float(box.conf[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()

                self.detection_count += 1

                self.csv_writer.writerow({
                    "timestamp": datetime.now().isoformat(),
                    "frame_id": self.frame_count,
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
            f"Frame: {self.frame_count} | Detections: {self.detection_count}",
            (10, 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )

        if self.save_annotated_frames and self.frame_count % self.save_every_n_frames == 0:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            output_path = self.annotated_frame_dir / f"live_yolo_{timestamp}.jpg"
            cv2.imwrite(str(output_path), annotated_frame)

        with latest_frame_lock:
            latest_frame = annotated_frame.copy()

        if self.window_display:
            cv2.imshow("YOLO MJPEG Server", annotated_frame)
            cv2.waitKey(1)

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
    return "YOLO ROS MJPEG server running. Open /video_feed"


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
    config = load_config("configs/perception/yolo_ros_mjpeg_server.yaml")

    flask_thread = threading.Thread(
        target=start_flask_server,
        args=(config,),
        daemon=True,
    )
    flask_thread.start()

    rclpy.init()
    node = YoloRosMjpegServer(config)

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
