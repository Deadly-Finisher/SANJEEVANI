import argparse
import csv
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Synthetic perception pipeline demo using config-driven frames."
    )

    parser.add_argument(
        "--config",
        required=True,
        help="Path to perception YAML config file.",
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
    required_sections = [
        "input",
        "classes",
        "synthetic_objects",
        "detection",
        "output",
        "safety",
    ]

    for section in required_sections:
        if section not in config:
            raise ValueError(f"Missing required config section: {section}")

    if bool(config["safety"]["allow_targeting"]):
        raise ValueError("Unsafe config: allow_targeting must remain false.")


def create_output_paths(config: dict[str, Any]) -> dict[str, Path]:
    output_dir = Path(config["output"]["output_dir"])
    frames_dir = output_dir / config["output"]["frames_dir"]
    annotated_dir = output_dir / config["output"]["annotated_dir"]
    detections_csv = output_dir / config["output"]["detections_csv"]
    summary_file = output_dir / config["output"]["summary_file"]

    frames_dir.mkdir(parents=True, exist_ok=True)
    annotated_dir.mkdir(parents=True, exist_ok=True)

    return {
        "output_dir": output_dir,
        "frames_dir": frames_dir,
        "annotated_dir": annotated_dir,
        "detections_csv": detections_csv,
        "summary_file": summary_file,
    }


def generate_synthetic_frame(
    config: dict[str, Any],
    frame_index: int,
) -> np.ndarray:
    image_width = int(config["input"]["image_width"])
    image_height = int(config["input"]["image_height"])
    background_color = config["input"]["background_color_bgr"]

    frame = np.full(
        shape=(image_height, image_width, 3),
        fill_value=background_color,
        dtype=np.uint8,
    )

    for object_config in config["synthetic_objects"]:
        label = object_config["label"]
        shape = object_config["shape"]
        color = tuple(config["classes"][label]["bgr_color"])
        velocity_x, velocity_y = object_config["velocity_px_per_frame"]

        offset_x = int(velocity_x * frame_index)
        offset_y = int(velocity_y * frame_index)

        if shape == "circle":
            center_x, center_y = object_config["center_px"]
            radius = int(object_config["radius_px"])

            center = (
                int(center_x + offset_x),
                int(center_y + offset_y),
            )

            cv2.circle(frame, center, radius, color, thickness=-1)

        elif shape == "rectangle":
            top_left_x, top_left_y = object_config["top_left_px"]
            bottom_right_x, bottom_right_y = object_config["bottom_right_px"]

            top_left = (
                int(top_left_x + offset_x),
                int(top_left_y + offset_y),
            )

            bottom_right = (
                int(bottom_right_x + offset_x),
                int(bottom_right_y + offset_y),
            )

            cv2.rectangle(frame, top_left, bottom_right, color, thickness=-1)

        else:
            raise ValueError(f"Unsupported synthetic shape: {shape}")

    return frame


def detect_colored_objects(
    frame: np.ndarray,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    detections: list[dict[str, Any]] = []
    min_area_px = float(config["detection"]["min_area_px"])

    for label, class_config in config["classes"].items():
        color = np.array(class_config["bgr_color"], dtype=np.uint8)

        lower_bound = color
        upper_bound = color

        mask = cv2.inRange(frame, lower_bound, upper_bound)

        contours, _ = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        for contour in contours:
            area_px = float(cv2.contourArea(contour))

            if area_px < min_area_px:
                continue

            x, y, width, height = cv2.boundingRect(contour)

            detections.append(
                {
                    "label": label,
                    "confidence": 1.0,
                    "bbox_x": x,
                    "bbox_y": y,
                    "bbox_width": width,
                    "bbox_height": height,
                    "area_px": area_px,
                }
            )

    return detections


def annotate_frame(
    frame: np.ndarray,
    detections: list[dict[str, Any]],
) -> np.ndarray:
    annotated = frame.copy()

    for detection in detections:
        x = int(detection["bbox_x"])
        y = int(detection["bbox_y"])
        width = int(detection["bbox_width"])
        height = int(detection["bbox_height"])
        label = detection["label"]
        confidence = float(detection["confidence"])

        cv2.rectangle(
            annotated,
            (x, y),
            (x + width, y + height),
            (255, 255, 255),
            thickness=2,
        )

        text = f"{label}: {confidence:.2f}"

        cv2.putText(
            annotated,
            text,
            (x, max(y - 10, 20)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 255),
            thickness=2,
        )

    return annotated


def save_detections_csv(
    detections_rows: list[dict[str, Any]],
    output_file: Path,
) -> None:
    fieldnames = [
        "frame_id",
        "label",
        "confidence",
        "bbox_x",
        "bbox_y",
        "bbox_width",
        "bbox_height",
        "area_px",
    ]

    with output_file.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(detections_rows)


def save_summary(
    detections_rows: list[dict[str, Any]],
    output_file: Path,
) -> None:
    total_detections = len(detections_rows)

    label_counts: dict[str, int] = {}

    for row in detections_rows:
        label = row["label"]
        label_counts[label] = label_counts.get(label, 0) + 1

    summary = f"""
Synthetic Perception Pipeline Summary

Total detections:
{total_detections}

Detections by class:
{label_counts}

Result:
The synthetic perception pipeline successfully generated simulated camera frames, detected configured objects, saved annotated frames, and exported detections to CSV.

Note:
This is a placeholder perception module. The next stage is to replace synthetic frames with real Gazebo camera frames or video frames, and later replace color-based detection with a trained object detection model.
""".strip()

    output_file.write_text(summary, encoding="utf-8")


def run_pipeline(config: dict[str, Any]) -> None:
    validate_config(config)

    paths = create_output_paths(config)
    frame_count = int(config["input"]["frame_count"])

    all_detection_rows: list[dict[str, Any]] = []

    for frame_index in range(frame_count):
        frame = generate_synthetic_frame(
            config=config,
            frame_index=frame_index,
        )

        detections = detect_colored_objects(
            frame=frame,
            config=config,
        )

        annotated = annotate_frame(
            frame=frame,
            detections=detections,
        )

        frame_id = f"frame_{frame_index:04d}"

        frame_file = paths["frames_dir"] / f"{frame_id}.png"
        annotated_file = paths["annotated_dir"] / f"{frame_id}_annotated.png"

        cv2.imwrite(str(frame_file), frame)
        cv2.imwrite(str(annotated_file), annotated)

        for detection in detections:
            all_detection_rows.append(
                {
                    "frame_id": frame_id,
                    **detection,
                }
            )

        print(
            f"{frame_id} | "
            f"detections={len(detections)} | "
            f"saved={annotated_file}"
        )

    save_detections_csv(
        detections_rows=all_detection_rows,
        output_file=paths["detections_csv"],
    )

    save_summary(
        detections_rows=all_detection_rows,
        output_file=paths["summary_file"],
    )

    print(f"Detections CSV saved: {paths['detections_csv']}")
    print(f"Summary saved: {paths['summary_file']}")


def main() -> None:
    args = parse_arguments()

    config = load_yaml_config(args.config)
    run_pipeline(config)


if __name__ == "__main__":
    main()