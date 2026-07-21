from pathlib import Path
import argparse
import json
import pandas as pd
import yaml


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text())


def load_json_if_exists(path: Path):
    if path.exists():
        return json.loads(path.read_text())
    return None


def normalize_label(label):
    return str(label).strip().lower()


def classify_label(label, rules):
    label_norm = normalize_label(label)

    critical = {normalize_label(x) for x in rules.get("critical_labels", [])}
    high = {normalize_label(x) for x in rules.get("high_priority_labels", [])}
    medium = {normalize_label(x) for x in rules.get("medium_priority_labels", [])}
    low = {normalize_label(x) for x in rules.get("low_priority_labels", [])}
    scores = rules.get("severity_scores", {})

    if label_norm in critical:
        return "critical_threat_event", "critical", int(scores.get("critical", 5))

    if label_norm in high:
        return "high_priority_observation_event", "high", int(scores.get("high", 4))

    if label_norm in medium:
        return "medium_priority_context_event", "medium", int(scores.get("medium", 3))

    if label_norm in low:
        return "low_priority_background_event", "low", int(scores.get("low", 2))

    return "unknown_detection_event", "unknown", int(scores.get("unknown", 1))


def get_value(row, column, default=""):
    if column in row.index:
        value = row[column]
        if pd.isna(value):
            return default
        return value
    return default


def get_drone_ids(zone_assignment, detections):
    drone_ids = []

    if zone_assignment and "drones" in zone_assignment:
        for drone in zone_assignment["drones"]:
            drone_id = drone.get("drone_id")
            if drone_id:
                drone_ids.append(str(drone_id))

    if not drone_ids and "drone_id" in detections.columns:
        drone_ids = sorted(detections["drone_id"].dropna().astype(str).unique().tolist())

    return drone_ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/swarm/v1_event_sharing.yaml",
        help="Path to event sharing YAML config",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_yaml(config_path)

    shared_detections_path = Path(config["input"]["shared_detections_csv"])
    zone_assignment_path = Path(config["input"]["zone_assignment_json"])

    output_dir = Path(config["output"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    inbox_dir = output_dir / config["output"]["per_drone_inbox_dir"]
    inbox_dir.mkdir(parents=True, exist_ok=True)

    if not shared_detections_path.exists():
        raise FileNotFoundError(f"Missing shared detections file: {shared_detections_path}")

    detections = pd.read_csv(shared_detections_path)

    threshold = float(config["event_rules"]["confidence_threshold"])

    if "confidence" in detections.columns:
        detections["confidence"] = pd.to_numeric(detections["confidence"], errors="coerce").fillna(0.0)
        detections = detections[detections["confidence"] >= threshold].copy()

    if "timestamp" in detections.columns:
        detections = detections.sort_values("timestamp").copy()

    zone_assignment = load_json_if_exists(zone_assignment_path)
    drone_ids = get_drone_ids(zone_assignment, detections)

    event_rows = []

    for index, row in detections.reset_index(drop=True).iterrows():
        label = get_value(row, "class_name", "unknown")
        event_type, severity, severity_score = classify_label(label, config["event_rules"])

        event_rows.append({
            "event_id": f"EVT-{index + 1:06d}",
            "timestamp": get_value(row, "timestamp", ""),
            "source_drone_id": get_value(row, "drone_id", ""),
            "original_detected_label": label,
            "event_type": event_type,
            "severity": severity,
            "severity_score": severity_score,
            "model_name": get_value(row, "model_name", ""),
            "confidence": get_value(row, "confidence", ""),
            "frame_id": get_value(row, "frame_id", ""),
            "x1": get_value(row, "x1", ""),
            "y1": get_value(row, "y1", ""),
            "x2": get_value(row, "x2", ""),
            "y2": get_value(row, "y2", ""),
            "source_detection_csv": get_value(row, "source_detection_csv", ""),
            "sharing_status": "shared_to_swarm",
        })

    events = pd.DataFrame(event_rows)

    if not events.empty:
        events = events.sort_values(["severity_score", "confidence"], ascending=[False, False]).copy()

    shared_events_path = output_dir / config["output"]["shared_events_csv"]
    events.to_csv(shared_events_path, index=False)

    include_self = bool(config["sharing"]["include_source_drone_in_own_inbox"])
    inbox_rows = []

    for _, event in events.iterrows():
        source_drone = str(event["source_drone_id"])

        for receiver_drone in drone_ids:
            if not include_self and receiver_drone == source_drone:
                continue

            message = event.to_dict()
            message["recipient_drone_id"] = receiver_drone
            message["message_type"] = "swarm_event_broadcast"
            inbox_rows.append(message)

    inbox = pd.DataFrame(inbox_rows)

    swarm_inbox_path = output_dir / config["output"]["swarm_event_inbox_csv"]
    inbox.to_csv(swarm_inbox_path, index=False)

    for drone_id in drone_ids:
        if inbox.empty:
            drone_inbox = pd.DataFrame()
        else:
            drone_inbox = inbox[inbox["recipient_drone_id"] == drone_id].copy()

        drone_inbox.to_csv(inbox_dir / f"{drone_id}_event_inbox.csv", index=False)

    summary = {
        "total_events": int(len(events)),
        "total_broadcast_messages": int(len(inbox)),
        "confidence_threshold": threshold,
        "drones_in_swarm": drone_ids,
        "events_by_source_drone": {},
        "events_by_original_label": {},
        "events_by_severity": {},
        "events_by_model": {},
    }

    if not events.empty:
        summary["events_by_source_drone"] = events["source_drone_id"].value_counts().to_dict()
        summary["events_by_original_label"] = events["original_detected_label"].value_counts().to_dict()
        summary["events_by_severity"] = events["severity"].value_counts().to_dict()
        summary["events_by_model"] = events["model_name"].value_counts().to_dict()

    summary_path = output_dir / config["output"]["shared_event_summary_json"]
    summary_path.write_text(json.dumps(summary, indent=2))

    report = "# V1 Swarm Event Sharing Report\n\n"
    report += f"Total shared events: {summary['total_events']}\n\n"
    report += f"Total broadcast messages: {summary['total_broadcast_messages']}\n\n"
    report += f"Confidence threshold: {threshold}\n\n"

    report += "## Drones in Swarm\n\n"
    for drone_id in drone_ids:
        report += f"- {drone_id}\n"

    report += "\n## Events by Source Drone\n\n"
    if summary["events_by_source_drone"]:
        for key, value in summary["events_by_source_drone"].items():
            report += f"- {key}: {value}\n"
    else:
        report += "No events available.\n"

    report += "\n## Events by Severity\n\n"
    if summary["events_by_severity"]:
        for key, value in summary["events_by_severity"].items():
            report += f"- {key}: {value}\n"
    else:
        report += "No severity data available.\n"

    report += "\n## Original Detected Labels\n\n"
    if summary["events_by_original_label"]:
        for key, value in summary["events_by_original_label"].items():
            report += f"- {key}: {value}\n"
    else:
        report += "No labels available.\n"

    report += "\n## Per-Drone Event Inbox Files\n\n"
    for drone_id in drone_ids:
        inbox_path = inbox_dir / f"{drone_id}_event_inbox.csv"
        report += f"- {drone_id}: `{inbox_path}`\n"

    report_path = output_dir / config["output"]["shared_event_report_md"]
    report_path.write_text(report)

    print("Swarm event sharing completed.")
    print("Shared events:", shared_events_path)
    print("Swarm inbox:", swarm_inbox_path)
    print("Summary:", summary_path)
    print("Report:", report_path)
    print("Total events:", len(events))
    print("Total broadcast messages:", len(inbox))


if __name__ == "__main__":
    main()
