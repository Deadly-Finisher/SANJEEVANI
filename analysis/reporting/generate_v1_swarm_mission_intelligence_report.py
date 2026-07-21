from pathlib import Path
from datetime import datetime, timezone
import argparse
import json
import math

import pandas as pd
import yaml


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text())


def load_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing JSON file: {path}")
    return json.loads(path.read_text())


def safe_json(path: Path):
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def parse_time(value):
    if not value:
        return None

    try:
        return pd.Timestamp(value)
    except Exception:
        return None


def calculate_duration_seconds(start_value, end_value):
    start = parse_time(start_value)
    end = parse_time(end_value)

    if start is None or end is None:
        return None

    return float((end - start).total_seconds())


def calculate_route_distance(dataframe, north_column, east_column):
    if dataframe.empty:
        return 0.0

    if north_column not in dataframe.columns or east_column not in dataframe.columns:
        return 0.0

    north = pd.to_numeric(dataframe[north_column], errors="coerce")
    east = pd.to_numeric(dataframe[east_column], errors="coerce")

    valid = pd.DataFrame({
        "north": north,
        "east": east,
    }).dropna()

    if len(valid) < 2:
        return 0.0

    delta_north = valid["north"].diff()
    delta_east = valid["east"].diff()

    segment_distance = (
        delta_north.pow(2) + delta_east.pow(2)
    ).pow(0.5)

    return float(segment_distance.fillna(0.0).sum())


def telemetry_summary(path, config):
    path = Path(path)

    if not path.exists():
        return {
            "available": False,
            "samples": 0,
            "duration_s": None,
            "estimated_distance_m": 0.0,
            "maximum_relative_altitude_m": None,
            "zones_recorded": [],
        }

    dataframe = pd.read_csv(path)

    timestamp_column = config["telemetry"]["timestamp_column"]
    north_column = config["telemetry"]["north_column"]
    east_column = config["telemetry"]["east_column"]
    altitude_column = config["telemetry"]["relative_altitude_column"]
    zone_column = config["telemetry"]["zone_column"]

    duration_s = None

    if timestamp_column in dataframe.columns and not dataframe.empty:
        timestamps = pd.to_datetime(
            dataframe[timestamp_column],
            utc=True,
            errors="coerce",
        ).dropna()

        if not timestamps.empty:
            duration_s = float(
                (timestamps.max() - timestamps.min()).total_seconds()
            )

    max_altitude = None

    if altitude_column in dataframe.columns:
        altitudes = pd.to_numeric(
            dataframe[altitude_column],
            errors="coerce",
        ).dropna()

        if not altitudes.empty:
            max_altitude = float(altitudes.max())

    zones = []

    if zone_column in dataframe.columns:
        zones = [
            str(value)
            for value in dataframe[zone_column].dropna().unique().tolist()
            if str(value).strip()
        ]

    return {
        "available": True,
        "samples": int(len(dataframe)),
        "duration_s": duration_s,
        "estimated_distance_m": calculate_route_distance(
            dataframe,
            north_column,
            east_column,
        ),
        "maximum_relative_altitude_m": max_altitude,
        "zones_recorded": zones,
    }


def format_number(value, digits=2):
    if value is None:
        return "N/A"
    return f"{float(value):.{digits}f}"


def format_duration(seconds):
    if seconds is None:
        return "N/A"

    seconds = int(round(seconds))
    minutes, remaining_seconds = divmod(seconds, 60)

    return f"{minutes} min {remaining_seconds} s"


def percentage(numerator, denominator):
    if not denominator:
        return 0.0
    return 100.0 * float(numerator) / float(denominator)


def get_assigned_zones(zone_assignment, drone_id):
    for drone in zone_assignment.get("drones", []):
        if str(drone.get("drone_id")) == drone_id:
            return drone.get("assigned_zones", [])
    return []


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--config",
        default="configs/reporting/v1_swarm_mission_intelligence_report.yaml",
    )

    args = parser.parse_args()

    config = load_yaml(Path(args.config))

    zone_assignment = load_json(
        Path(config["inputs"]["zone_assignment_json"])
    )

    detection_summary = safe_json(
        Path(config["inputs"]["shared_detection_summary_json"])
    )

    event_summary = safe_json(
        Path(config["inputs"]["shared_event_summary_json"])
    )

    merge_summary = safe_json(
        Path(config["inputs"]["merge_summary_json"])
    )

    successful_statuses = set(
        config["assessment"]["successful_statuses"]
    )

    drone_results = []

    mission_summary_paths = {
        item["drone_id"]: item["path"]
        for item in config["inputs"]["mission_summaries"]
    }

    telemetry_paths = {
        item["drone_id"]: item["path"]
        for item in config["inputs"]["telemetry_logs"]
    }

    drone_ids = sorted(
        set(mission_summary_paths.keys())
        | set(telemetry_paths.keys())
    )

    for drone_id in drone_ids:
        mission_summary = safe_json(
            Path(mission_summary_paths[drone_id])
        )

        telemetry = telemetry_summary(
            telemetry_paths[drone_id],
            config,
        )

        mission_status = mission_summary.get(
            "status",
            "unknown",
        )

        completed_waypoints = mission_summary.get(
            "completed_waypoints",
            [],
        )

        successful_waypoints = sum(
            1
            for waypoint in completed_waypoints
            if waypoint.get("arrived_within_tolerance") is True
        )

        mission_duration_s = calculate_duration_seconds(
            mission_summary.get("started_at_utc"),
            mission_summary.get("completed_at_utc"),
        )

        drone_results.append({
            "drone_id": drone_id,
            "mission_name": mission_summary.get(
                "mission_name",
                "",
            ),
            "mission_status": mission_status,
            "mission_successful": (
                mission_status in successful_statuses
            ),
            "mission_duration_s": mission_duration_s,
            "assigned_zones": get_assigned_zones(
                zone_assignment,
                drone_id,
            ),
            "completed_waypoint_count": len(
                completed_waypoints
            ),
            "waypoints_within_tolerance": successful_waypoints,
            "mission_error": mission_summary.get("error"),
            "landing_error": mission_summary.get(
                "landing_error"
            ),
            "telemetry": telemetry,
            "detection_count": int(
                detection_summary.get("drones", {}).get(
                    drone_id,
                    0,
                )
            ),
            "source_event_count": int(
                event_summary.get(
                    "events_by_source_drone",
                    {},
                ).get(drone_id, 0)
            ),
        })

    total_drones = len(drone_results)

    successful_drones = sum(
        1
        for drone in drone_results
        if drone["mission_successful"]
    )

    total_telemetry_samples = sum(
        drone["telemetry"]["samples"]
        for drone in drone_results
    )

    total_estimated_distance = sum(
        drone["telemetry"]["estimated_distance_m"]
        for drone in drone_results
    )

    total_detections = int(
        detection_summary.get(
            "total_shared_detections",
            merge_summary.get("detection_records", 0),
        )
    )

    total_events = int(
        event_summary.get(
            "total_events",
            merge_summary.get("event_records", 0),
        )
    )

    matched_detections = int(
        merge_summary.get("matched_detections", 0)
    )

    matched_events = int(
        merge_summary.get("matched_events", 0)
    )

    detection_link_rate = percentage(
        matched_detections,
        total_detections,
    )

    event_link_rate = percentage(
        matched_events,
        total_events,
    )

    point_17_complete = (
        matched_detections
        >= int(
            config["assessment"][
                "minimum_linked_detection_count"
            ]
        )
        and matched_events
        >= int(
            config["assessment"][
                "minimum_linked_event_count"
            ]
        )
    )

    generated_at = datetime.now(
        timezone.utc
    ).isoformat()

    summary = {
        "report_title": config["report"]["title"],
        "swarm_name": config["report"]["swarm_name"],
        "generated_at_utc": generated_at,
        "mission": {
            "total_drones": total_drones,
            "successful_drones": successful_drones,
            "mission_success_rate_percent": percentage(
                successful_drones,
                total_drones,
            ),
            "total_telemetry_samples": total_telemetry_samples,
            "estimated_total_distance_m": total_estimated_distance,
        },
        "intelligence": {
            "total_shared_detections": total_detections,
            "total_shared_events": total_events,
            "total_broadcast_messages": int(
                event_summary.get(
                    "total_broadcast_messages",
                    0,
                )
            ),
            "matched_detections": matched_detections,
            "matched_events": matched_events,
            "detection_link_rate_percent": detection_link_rate,
            "event_link_rate_percent": event_link_rate,
        },
        "point_17_complete": point_17_complete,
        "drones": drone_results,
        "detected_labels": detection_summary.get(
            "labels",
            {},
        ),
        "detection_models": detection_summary.get(
            "models",
            {},
        ),
        "event_severity_distribution": event_summary.get(
            "events_by_severity",
            {},
        ),
    }

    summary_path = Path(
        config["report"]["generated_summary_path"]
    )
    report_path = Path(
        config["report"]["generated_report_path"]
    )

    summary_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary_path.write_text(
        json.dumps(summary, indent=2)
    )

    report = (
        f"# {config['report']['title']}\n\n"
    )

    report += (
        f"Generated at: {generated_at}\n\n"
        f"Swarm: {config['report']['swarm_name']}\n\n"
    )

    report += "## Executive Summary\n\n"
    report += (
        f"- Drones participating: {total_drones}\n"
        f"- Successful drone missions: "
        f"{successful_drones}/{total_drones}\n"
        f"- Mission success rate: "
        f"{percentage(successful_drones, total_drones):.2f}%\n"
        f"- Telemetry samples collected: "
        f"{total_telemetry_samples}\n"
        f"- Estimated aggregate flight distance: "
        f"{total_estimated_distance:.2f} m\n"
        f"- Shared detections: {total_detections}\n"
        f"- Shared events: {total_events}\n"
        f"- Broadcast event messages: "
        f"{event_summary.get('total_broadcast_messages', 0)}\n"
        f"- Telemetry-linked detections: "
        f"{matched_detections}\n"
        f"- Telemetry-linked events: "
        f"{matched_events}\n"
    )

    report += "\n## Mission Execution by Drone\n\n"

    for drone in drone_results:
        report += f"### {drone['drone_id']}\n\n"
        report += (
            f"- Mission: {drone['mission_name']}\n"
            f"- Status: {drone['mission_status']}\n"
            f"- Duration: "
            f"{format_duration(drone['mission_duration_s'])}\n"
            f"- Assigned zones: "
            f"{' -> '.join(drone['assigned_zones']) if drone['assigned_zones'] else 'None'}\n"
            f"- Completed waypoints: "
            f"{drone['completed_waypoint_count']}\n"
            f"- Waypoints reached within tolerance: "
            f"{drone['waypoints_within_tolerance']}\n"
            f"- Telemetry samples: "
            f"{drone['telemetry']['samples']}\n"
            f"- Estimated flight distance: "
            f"{drone['telemetry']['estimated_distance_m']:.2f} m\n"
            f"- Maximum relative altitude: "
            f"{format_number(drone['telemetry']['maximum_relative_altitude_m'])} m\n"
            f"- Shared detections contributed: "
            f"{drone['detection_count']}\n"
            f"- Shared events contributed: "
            f"{drone['source_event_count']}\n"
        )

        if drone["mission_error"]:
            report += (
                f"- Mission warning/error: "
                f"{drone['mission_error']}\n"
            )

        if drone["landing_error"]:
            report += (
                f"- Landing warning/error: "
                f"{drone['landing_error']}\n"
            )

        report += "\n"

    report += "## Zone Assignment\n\n"

    for drone in zone_assignment.get("drones", []):
        zones = drone.get("assigned_zones", [])

        report += (
            f"- {drone.get('drone_id')}: "
            f"{' -> '.join(zones) if zones else 'None'}\n"
        )

    report += "\n## Detection Intelligence\n\n"
    report += (
        f"- Total detections: {total_detections}\n"
        f"- Telemetry-linked detections: "
        f"{matched_detections}\n"
        f"- Detection linkage rate: "
        f"{detection_link_rate:.2f}%\n"
    )

    report += "\n### Original Detected Labels\n\n"

    labels = detection_summary.get("labels", {})

    if labels:
        for label, count in labels.items():
            report += f"- {label}: {count}\n"
    else:
        report += "No detection labels were available.\n"

    report += "\n### Detection Models\n\n"

    models = detection_summary.get("models", {})

    if models:
        for model, count in models.items():
            report += f"- {model}: {count}\n"
    else:
        report += "No model statistics were available.\n"

    report += "\n## Shared Event Intelligence\n\n"
    report += (
        f"- Total events: {total_events}\n"
        f"- Broadcast messages: "
        f"{event_summary.get('total_broadcast_messages', 0)}\n"
        f"- Telemetry-linked events: {matched_events}\n"
        f"- Event linkage rate: {event_link_rate:.2f}%\n"
    )

    report += "\n### Events by Severity\n\n"

    severity = event_summary.get(
        "events_by_severity",
        {},
    )

    if severity:
        for level, count in severity.items():
            report += f"- {level}: {count}\n"
    else:
        report += "No event severity statistics were available.\n"

    report += "\n## Telemetry–Intelligence Synchronization\n\n"
    report += (
        f"- Telemetry samples: "
        f"{merge_summary.get('telemetry_samples', 0)}\n"
        f"- Detection records: "
        f"{merge_summary.get('detection_records', 0)}\n"
        f"- Matched detections: {matched_detections}\n"
        f"- Unmatched detections: "
        f"{merge_summary.get('unmatched_detections', 0)}\n"
        f"- Event records: "
        f"{merge_summary.get('event_records', 0)}\n"
        f"- Matched events: {matched_events}\n"
        f"- Unmatched events: "
        f"{merge_summary.get('unmatched_events', 0)}\n"
        f"- Synchronization tolerance: "
        f"{merge_summary.get('nearest_match_tolerance_s', 'N/A')} seconds\n"
    )

    report += "\n## System Assessment\n\n"

    if point_17_complete:
        report += (
            "The synchronized swarm intelligence pipeline was "
            "successfully validated. Drone telemetry, visual "
            "detections and shared events were linked using their "
            "timestamps.\n"
        )
    else:
        report += (
            "The pipeline generated outputs, but insufficient "
            "telemetry-linked detections or events were available.\n"
        )

    report += "\n## Generated Artifacts\n\n"
    report += (
        "- Zone assignment JSON\n"
        "- Per-drone mission summaries\n"
        "- Per-drone telemetry CSV files\n"
        "- Shared detection log and summary\n"
        "- Shared event log and per-drone inboxes\n"
        "- Telemetry-linked detection CSV\n"
        "- Telemetry-linked event CSV\n"
        "- Swarm mission intelligence summary JSON\n"
        "- Swarm mission intelligence Markdown report\n"
    )

    report_path.write_text(report)

    print("Swarm mission intelligence report generated.")
    print("Report:", report_path)
    print("Summary:", summary_path)
    print("Successful drones:", successful_drones, "/", total_drones)
    print("Matched detections:", matched_detections)
    print("Matched events:", matched_events)
    print("Point 17 complete:", point_17_complete)


if __name__ == "__main__":
    main()
