import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import yaml


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate safe human-review event report from perception detections."
    )

    parser.add_argument(
        "--config",
        required=True,
        help="Path to intelligence report YAML config file.",
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
        "output",
        "mission",
        "event_classes",
        "risk_scoring",
        "safety",
    ]

    for section in required_sections:
        if section not in config:
            raise ValueError(f"Missing required config section: {section}")

    if bool(config["safety"]["allow_targeting"]):
        raise ValueError("Unsafe config: allow_targeting must remain false.")

    if bool(config["safety"]["allow_autonomous_engagement"]):
        raise ValueError(
            "Unsafe config: allow_autonomous_engagement must remain false."
        )

    if not bool(config["safety"]["human_review_required"]):
        raise ValueError("Unsafe config: human_review_required must remain true.")


def read_detections_csv(detections_csv: Path) -> list[dict[str, Any]]:
    if not detections_csv.exists():
        raise FileNotFoundError(f"Detections CSV not found: {detections_csv}")

    detections: list[dict[str, Any]] = []

    with detections_csv.open("r", encoding="utf-8") as csv_file:
        reader = csv.DictReader(csv_file)

        for row in reader:
            detections.append(
                {
                    "frame_id": row["frame_id"],
                    "label": row["label"],
                    "confidence": float(row["confidence"]),
                    "bbox_x": int(float(row["bbox_x"])),
                    "bbox_y": int(float(row["bbox_y"])),
                    "bbox_width": int(float(row["bbox_width"])),
                    "bbox_height": int(float(row["bbox_height"])),
                    "area_px": float(row["area_px"]),
                }
            )

    return detections


def read_optional_text_file(path: Path) -> str:
    if not path.exists():
        return "Telemetry summary file was not found."

    return path.read_text(encoding="utf-8")


def list_evidence_images(evidence_images_dir: Path) -> list[Path]:
    if not evidence_images_dir.exists():
        return []

    return sorted(evidence_images_dir.glob("*.png"))


def calculate_priority_level(
    total_score: float,
    low_threshold: float,
    medium_threshold: float,
    high_threshold: float,
) -> str:
    if total_score >= high_threshold:
        return "HIGH - human review strongly recommended"

    if total_score >= medium_threshold:
        return "MEDIUM - human review recommended"

    if total_score >= low_threshold:
        return "LOW - log and review if needed"

    return "NONE - no meaningful event detected"


def build_event_summary(
    detections: list[dict[str, Any]],
    config: dict[str, Any],
) -> dict[str, Any]:
    label_counter = Counter(detection["label"] for detection in detections)
    frame_counter = Counter(detection["frame_id"] for detection in detections)

    detections_by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for detection in detections:
        detections_by_label[detection["label"]].append(detection)

    class_rows: list[dict[str, Any]] = []
    total_event_score = 0.0

    for label, label_detections in detections_by_label.items():
        class_config = config["event_classes"].get(label, {})
        priority_weight = float(class_config.get("priority_weight", 1))
        description = class_config.get("description", "Detected object class.")

        count = len(label_detections)
        average_confidence = mean(
            detection["confidence"] for detection in label_detections
        )
        max_area_px = max(detection["area_px"] for detection in label_detections)

        class_event_score = count * priority_weight
        total_event_score += class_event_score

        class_rows.append(
            {
                "label": label,
                "description": description,
                "count": count,
                "unique_frames": len(
                    {detection["frame_id"] for detection in label_detections}
                ),
                "average_confidence": average_confidence,
                "max_area_px": max_area_px,
                "priority_weight": priority_weight,
                "class_event_score": class_event_score,
            }
        )

    risk_config = config["risk_scoring"]

    priority_level = calculate_priority_level(
        total_score=total_event_score,
        low_threshold=float(risk_config["low_threshold"]),
        medium_threshold=float(risk_config["medium_threshold"]),
        high_threshold=float(risk_config["high_threshold"]),
    )

    return {
        "total_detections": len(detections),
        "unique_frames": len(frame_counter),
        "label_counts": dict(label_counter),
        "class_rows": class_rows,
        "total_event_score": total_event_score,
        "priority_level": priority_level,
    }


def save_event_summary_csv(
    class_rows: list[dict[str, Any]],
    output_file: Path,
) -> None:
    fieldnames = [
        "label",
        "description",
        "count",
        "unique_frames",
        "average_confidence",
        "max_area_px",
        "priority_weight",
        "class_event_score",
    ]

    with output_file.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(class_rows)


def create_markdown_report(
    config: dict[str, Any],
    event_summary: dict[str, Any],
    telemetry_summary: str,
    evidence_images: list[Path],
    detections_csv: Path,
    event_summary_csv: Path,
) -> str:
    mission = config["mission"]
    safety = config["safety"]

    generated_at = datetime.now(timezone.utc).isoformat()
    class_rows = event_summary["class_rows"]

    if class_rows:
        table_lines = [
            "| Class | Count | Unique Frames | Avg Confidence | Max Area px | Score |",
            "|---|---:|---:|---:|---:|---:|",
        ]

        for row in class_rows:
            table_lines.append(
                f"| {row['label']} "
                f"| {row['count']} "
                f"| {row['unique_frames']} "
                f"| {row['average_confidence']:.2f} "
                f"| {row['max_area_px']:.2f} "
                f"| {row['class_event_score']:.2f} |"
            )

        class_table = "\n".join(table_lines)
    else:
        class_table = "No detections were found."

    evidence_lines = []

    for image_path in evidence_images[:10]:
        evidence_lines.append(f"- {image_path}")

    if evidence_lines:
        evidence_section = "\n".join(evidence_lines)
    else:
        evidence_section = "No annotated evidence images found."

    report_sections = [
        "# Mission Event Report",
        "",
        "## 1. Report Metadata",
        "",
        f"Generated at UTC: {generated_at}",
        "",
        f"Mission name: {mission['mission_name']}",
        f"Platform: {mission['platform']}",
        f"Perception mode: {mission['perception_mode']}",
        f"Operator note: {mission['operator_note']}",
        "",
        "---",
        "",
        "## 2. Safety Boundary",
        "",
        "This report is generated only for surveillance, event detection, documentation, and human review.",
        "",
        f"Targeting allowed: {safety['allow_targeting']}",
        f"Autonomous engagement allowed: {safety['allow_autonomous_engagement']}",
        f"Human review required: {safety['human_review_required']}",
        "",
        "No autonomous attack, targeting, or engagement decision is performed by this system.",
        "",
        "---",
        "",
        "## 3. Input Evidence",
        "",
        f"Detections CSV: {detections_csv}",
        "",
        f"Event summary CSV: {event_summary_csv}",
        "",
        "Annotated evidence images:",
        "",
        evidence_section,
        "",
        "---",
        "",
        "## 4. Event Summary",
        "",
        f"Total detections: {event_summary['total_detections']}",
        f"Unique frames with detections: {event_summary['unique_frames']}",
        f"Detection counts by class: {event_summary['label_counts']}",
        f"Total event score: {event_summary['total_event_score']:.2f}",
        f"Priority level: {event_summary['priority_level']}",
        "",
        "---",
        "",
        "## 5. Class-wise Detection Table",
        "",
        class_table,
        "",
        "---",
        "",
        "## 6. Telemetry Summary",
        "",
        telemetry_summary,
        "",
        "---",
        "",
        "## 7. Human Review Recommendation",
        "",
        "The detected events should be reviewed by a human operator. The system only flags and summarizes observations from the simulated perception pipeline.",
        "",
        "Recommended safe follow-up actions:",
        "",
        "1. Review annotated frames.",
        "2. Compare detections with telemetry and mission path.",
        "3. Verify whether detections are persistent across frames.",
        "4. Record false positives or uncertain detections.",
        "5. Improve perception model or simulation environment in the next iteration.",
        "",
        "---",
        "",
        "## 8. Result",
        "",
        "The intelligence report was generated successfully from perception detections and telemetry analysis output. This validates the first safe event-reporting layer of the simulated UAV intelligence pipeline.",
        "",
    ]

    return "\n".join(report_sections)


def run_report_generation(config: dict[str, Any]) -> None:
    validate_config(config)

    detections_csv = Path(config["input"]["detections_csv"])
    telemetry_summary_file = Path(config["input"]["telemetry_summary_file"])
    evidence_images_dir = Path(config["input"]["evidence_images_dir"])

    output_dir = Path(config["output"]["output_dir"])
    report_file = output_dir / config["output"]["report_filename"]
    event_summary_csv = output_dir / config["output"]["event_summary_csv"]

    output_dir.mkdir(parents=True, exist_ok=True)

    detections = read_detections_csv(detections_csv)
    telemetry_summary = read_optional_text_file(telemetry_summary_file)
    evidence_images = list_evidence_images(evidence_images_dir)

    event_summary = build_event_summary(
        detections=detections,
        config=config,
    )

    save_event_summary_csv(
        class_rows=event_summary["class_rows"],
        output_file=event_summary_csv,
    )

    report = create_markdown_report(
        config=config,
        event_summary=event_summary,
        telemetry_summary=telemetry_summary,
        evidence_images=evidence_images,
        detections_csv=detections_csv,
        event_summary_csv=event_summary_csv,
    )

    report_file.write_text(report, encoding="utf-8")

    print(f"Event summary CSV saved: {event_summary_csv}")
    print(f"Mission event report saved: {report_file}")
    print(f"Priority level: {event_summary['priority_level']}")
    print(f"Total event score: {event_summary['total_event_score']:.2f}")


def main() -> None:
    args = parse_arguments()

    config = load_yaml_config(args.config)
    run_report_generation(config)


if __name__ == "__main__":
    main()