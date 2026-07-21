from pathlib import Path
import pandas as pd
import yaml


CONFIG_PATH = Path("configs/reporting/v1_ai_selected_mission_intelligence_report.yaml")


def load_config():
    with open(CONFIG_PATH, "r") as file:
        return yaml.safe_load(file)


def safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(path)


def to_markdown_table(df: pd.DataFrame, max_rows: int = 20) -> str:
    if df.empty:
        return "No data available."

    df = df.head(max_rows).copy()

    try:
        return df.to_markdown(index=False)
    except Exception:
        return df.to_string(index=False)


def add_original_detected_label(class_name: str) -> str:
    """
    Keep the original detector/model label for easier understanding.
    This does not modify dataset labels or model labels.
    """
    if pd.isna(class_name):
        return "unknown"
    return str(class_name).strip()

def main():
    config = load_config()

    event_log_path = Path(config["input"]["event_log_csv_path"])
    telemetry_path = Path(config["input"]["telemetry_csv_path"])
    detection_path = Path(config["input"]["detection_csv_path"])
    report_path = Path(config["output"]["report_path"])

    metadata = config["metadata"]

    events = safe_read_csv(event_log_path)
    telemetry = safe_read_csv(telemetry_path)
    detections = safe_read_csv(detection_path)

    if events.empty:
        raise ValueError(f"Event log is empty: {event_log_path}")

    if "class_name" in events.columns:
        events["original_detected_label"] = events["class_name"].apply(add_original_detected_label)
    else:
        events["original_detected_label"] = "unknown"

    if "confidence" in events.columns:
        events["confidence"] = pd.to_numeric(events["confidence"], errors="coerce")

    mission_start = telemetry["timestamp_utc"].iloc[0] if not telemetry.empty and "timestamp_utc" in telemetry.columns else "unknown"
    mission_end = telemetry["timestamp_utc"].iloc[-1] if not telemetry.empty and "timestamp_utc" in telemetry.columns else "unknown"

    zone_summary = (
        events.groupby(["zone_name", "original_detected_label"])
        .size()
        .reset_index(name="detection_count")
        .sort_values(["zone_name", "detection_count"], ascending=[True, False])
        if {"zone_name", "original_detected_label"}.issubset(events.columns)
        else pd.DataFrame()
    )

    raw_class_summary = (
        events.groupby(["model_name", "class_name"])
        .agg(
            detection_count=("class_name", "size"),
            avg_confidence=("confidence", "mean"),
            max_confidence=("confidence", "max"),
        )
        .reset_index()
        .sort_values("detection_count", ascending=False)
        if {"model_name", "class_name", "confidence"}.issubset(events.columns)
        else pd.DataFrame()
    )

    category_summary = (
        events.groupby("original_detected_label")
        .agg(
            detection_count=("original_detected_label", "size"),
            avg_confidence=("confidence", "mean"),
            max_confidence=("confidence", "max"),
        )
        .reset_index()
        .sort_values("detection_count", ascending=False)
        if "confidence" in events.columns
        else pd.DataFrame()
    )

    zone_phase_summary = (
        telemetry.groupby(["mission_phase", "zone_name"])
        .size()
        .reset_index(name="telemetry_samples")
        if not telemetry.empty and {"mission_phase", "zone_name"}.issubset(telemetry.columns)
        else pd.DataFrame()
    )

    high_confidence_events = (
        events.sort_values("confidence", ascending=False)[
            [
                "detection_time_utc",
                "model_name",
                "class_name",
                "original_detected_label",
                "confidence",
                "zone_name",
                "mission_phase",
                "north_m",
                "east_m",
                "down_m",
            ]
        ]
        if {
            "detection_time_utc",
            "model_name",
            "class_name",
            "confidence",
            "zone_name",
            "mission_phase",
            "north_m",
            "east_m",
            "down_m",
        }.issubset(events.columns)
        else pd.DataFrame()
    )

    lines = []

    lines.append(f"# V1 Mission Intelligence Report\n")
    lines.append(f"## Mission Metadata\n")
    lines.append(f"- Mission name: `{metadata['mission_name']}`")
    lines.append(f"- World: `{metadata['world_name']}`")
    lines.append(f"- Drone model: `{metadata['drone_model']}`")
    lines.append(f"- Detector pipeline: `{metadata['detector_pipeline']}`")
    lines.append(f"- Mission start UTC: `{mission_start}`")
    lines.append(f"- Mission end UTC: `{mission_end}`")
    lines.append(f"- Note: {metadata['note']}\n")

    lines.append("## Data Files\n")
    lines.append(f"- Event log: `{event_log_path}`")
    lines.append(f"- Telemetry log: `{telemetry_path}`")
    lines.append(f"- Detection log: `{detection_path}`\n")

    lines.append("## Mission Data Summary\n")
    lines.append(f"- Total raw detection rows: `{len(detections)}`")
    lines.append(f"- Total telemetry rows: `{len(telemetry)}`")
    lines.append(f"- Telemetry-linked event rows: `{len(events)}`")
    lines.append(f"- Unique mission zones with linked detections: `{events['zone_name'].nunique() if 'zone_name' in events.columns else 0}`")
    lines.append(f"- Unique raw classes detected: `{events['class_name'].nunique() if 'class_name' in events.columns else 0}`")
    lines.append(f"- Unique detector models used: `{events['model_name'].nunique() if 'model_name' in events.columns else 0}`\n")

    lines.append("## Original Detected Label Summary\n")
    lines.append(to_markdown_table(category_summary, max_rows=20))
    lines.append("\n")

    lines.append("## Zone-wise Detection Summary\n")
    lines.append(to_markdown_table(zone_summary, max_rows=50))
    lines.append("\n")

    lines.append("## Raw Model/Class Detection Summary\n")
    lines.append(to_markdown_table(raw_class_summary, max_rows=40))
    lines.append("\n")

    lines.append("## Mission Phase / Zone Telemetry Summary\n")
    lines.append(to_markdown_table(zone_phase_summary, max_rows=40))
    lines.append("\n")

    lines.append("## Highest Confidence Linked Events\n")
    lines.append(to_markdown_table(high_confidence_events, max_rows=25))
    lines.append("\n")

    lines.append("## Interpretation\n")
    lines.append(
        "The mission successfully produced a synchronized event log where visual detections are linked "
        "with drone telemetry, mission phase, and zone information. This enables later analysis of where "
        "objects were detected during the drone route."
    )
    lines.append("\n")
    lines.append(
        "Some raw labels such as `airplane`, `bird`, or other unusual classes may appear because simulation "
        "objects and camera perspective differ from real training data. These detections should be treated "
        "as review candidates rather than final ground truth."
    )
    lines.append("\n")

    lines.append("## Current Limitation\n")
    lines.append(
        "This is still a fixed waypoint mission. Route optimization, QGIS route parsing, autonomous re-routing, "
        "and swarm coordination are planned in the next stages."
    )
    lines.append("\n")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines))

    print("V1 mission intelligence report generated.")
    print("Report:", report_path.resolve())


if __name__ == "__main__":
    main()
