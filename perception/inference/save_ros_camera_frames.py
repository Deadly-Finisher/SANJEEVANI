import os
from pathlib import Path
from datetime import datetime

import cv2
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge


class CameraFrameSaver(Node):
    def __init__(self):
        super().__init__("camera_frame_saver")

        self.topic = (
            "/world/battlefield_sar_world_v1/model/x500_mono_cam_0/"
            "link/camera_link/sensor/camera/image"
        )

        self.output_dir = Path("outputs/camera_frames")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.bridge = CvBridge()
        self.frame_count = 0
        self.save_every_n_frames = 5
        self.max_saved_frames = 50

        self.subscription = self.create_subscription(
            Image,
            self.topic,
            self.image_callback,
            10,
        )

        self.get_logger().info(f"Subscribed to: {self.topic}")
        self.get_logger().info(f"Saving frames to: {self.output_dir.resolve()}")

    def image_callback(self, msg):
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().error(f"Failed to convert image: {exc}")
            return

        self.frame_count += 1

        if self.frame_count % self.save_every_n_frames != 0:
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = self.output_dir / f"gazebo_frame_{timestamp}.jpg"

        cv2.imwrite(str(filename), frame)
        self.get_logger().info(f"Saved: {filename}")

        saved_count = len(list(self.output_dir.glob("*.jpg")))
        if saved_count >= self.max_saved_frames:
            self.get_logger().info("Reached max saved frames. Stopping.")
            rclpy.shutdown()


def main():
    rclpy.init()
    node = CameraFrameSaver()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()