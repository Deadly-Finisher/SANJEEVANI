from pathlib import Path
from datetime import datetime

import pandas as pd
import yaml


def load_config(path: str) -> dict:
    with open(path, "r") as file:
        return yaml.safe_load(file)


def safe_value(value, default="N/A"):
    if pd.isna(value):
        return default
    return value


def main() -> None:
    config = load_config("configs/reporting/mission_event_report.yaml")

    event_log_path = Path(config["input"]["event_log_csv_path"])
    report_path = Path(config["output"]["report_path"])

    mission_name = config["metadata"]["mission_name"]
    drone_model = config["metadata"]["drone_model"]
    world_name = config["metadata"]["world_name"]
    detector_model = config["metadata"]["detector_model"]

    if not event_log_path.exists():
        raise FileNotFoundError(f"Event log not found: {event_log_path}")

    report_path.parent.mkdir(parents=True, exist_ok=True)

    events = pd.read_csv(event_log_path)

    if events.empty:
        raise ValueError("Event log is empty.")

    total_events = len(events)

    linked_events = 0
    if "telemetry_timestamp" in events.columns:
        linked_events = events["telemetry_timestamp"].notna().sum()

    unlinked_events = total_events - linked_events

    if "class_name" in events.columns:
        class_counts = events["class_name"].value_counts()
    else:
        class_counts = pd.Series(dtype=int)

    avg_confidence = None
    if "confidence" in events.columns:
        avg_confidence = events["confidence"].mean()

    mission_phases = []
    if "mission_phase" in events.columns:
        mission_phases = list(events["mission_phase"].dropna().unique())

    altitude_summary = {}
    if "relative_altitude_m" in events.columns:
        altitude_values = pd.to_numeric(events["relative_altitude_m"], errors="coerce").dropna()
        if not altitude_values.empty:
            altitude_summary = {
                "min": altitude_values.min(),
                "max": altitude_values.max(),
                "mean": altitude_values.mean(),
            }

    start_time = "N/A"
    end_time = "N/A"

    if "detection_timestamp" in events.columns:
        times = pd.to_datetime(events["detection_timestamp"], errors="coerce").dropna()
        if not times.empty:
            start_time = times.min()
            end_time = times.max()

    report_lines = []

    report_lines.append("# Mission Event Report")
    report_lines.append("")
    report_lines.append(f"Generated at: {datetime.now().isoformat()}")
    report_lines.append("")
    report_lines.append("## Mission Metadata")
    report_lines.append("")
    report_lines.append(f"- Mission name: {mission_name}")
    report_lines.append(f"- Gazebo world: {world_name}")
    report_lines.append(f"- Drone model: {drone_model}")
    report_lines.append(f"- Detector model: {detector_model}")
    report_lines.append("")
    report_lines.append("## Mission Time Window")
    report_lines.append("")
    report_lines.append(f"- Start time: {start_time}")
    report_lines.append(f"- End time: {end_time}")
    report_lines.append("")
    report_lines.append("## Detection Summary")
    report_lines.append("")
    report_lines.append(f"- Total visual detection events: {total_events}")
    report_lines.append(f"- Events linked with telemetry: {linked_events}")
    report_lines.append(f"- Events without telemetry link: {unlinked_events}")

    if avg_confidence is not None:
        report_lines.append(f"- Average detection confidence: {avg_confidence:.4f}")

    report_lines.append("")
    report_lines.append("## Detected Classes")
    report_lines.append("")

    if class_counts.empty:
        report_lines.append("No class information available.")
    else:
        for class_name, count in class_counts.items():
            report_lines.append(f"- {class_name}: {count}")

    report_lines.append("")
    report_lines.append("## Mission Phases Observed")
    report_lines.append("")

    if mission_phases:
        for phase in mission_phases:
            report_lines.append(f"- {phase}")
    else:
        report_lines.append("No mission phase information available.")

    report_lines.append("")
    report_lines.append("## Altitude Summary")
    report_lines.append("")

    if altitude_summary:
        report_lines.append(f"- Minimum relative altitude: {altitude_summary['min']:.2f} m")
        report_lines.append(f"- Maximum relative altitude: {altitude_summary['max']:.2f} m")
        report_lines.append(f"- Mean relative altitude: {altitude_summary['mean']:.2f} m")
    else:
        report_lines.append("No altitude information available.")

    report_lines.append("")
    report_lines.append("## First 10 Detection Events")
    report_lines.append("")

    selected_columns = [
        "event_id",
        "detection_timestamp",
        "class_name",
        "confidence",
        "mission_phase",
        "relative_altitude_m",
        "latitude_deg",
        "longitude_deg",
    ]

    available_columns = [col for col in selected_columns if col in events.columns]

    if available_columns:
        preview = events[available_columns].head(10)
        report_lines.append(preview.to_markdown(index=False))
    else:
        report_lines.append("No preview columns available.")

    report_lines.append("")
    report_lines.append("## Interpretation")
    report_lines.append("")
    report_lines.append(
        "The simulated UAV successfully collected live camera frames, ran YOLO-based "
        "visual detection, logged detections to CSV, captured drone telemetry during "
        "movement, and produced a telemetry-linked event log. This report summarizes "
        "the first complete single-drone perception and telemetry pipeline."
    )

    report_path.write_text("\n".join(report_lines))

    print("Mission event report generated.")
    print(f"Saved to: {report_path.resolve()}")


if __name__ == "__main__":
    main()
