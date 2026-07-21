from pathlib import Path
import argparse
import json

import pandas as pd
import yaml


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def parse_timestamp(value, naive_timezone: str):
    if pd.isna(value) or str(value).strip() == "":
        return pd.NaT

    try:
        timestamp = pd.Timestamp(value)

        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize(naive_timezone)

        return timestamp.tz_convert("UTC")

    except Exception:
        return pd.NaT


def parse_timestamp_series(series: pd.Series, naive_timezone: str):
    parsed = series.map(
        lambda value: parse_timestamp(value, naive_timezone)
    )
    return pd.to_datetime(parsed, utc=True, errors="coerce")


def timestamp_text(value):
    if pd.isna(value):
        return None
    return pd.Timestamp(value).isoformat()


def dataframe_time_range(dataframe, column):
    if dataframe.empty or column not in dataframe.columns:
        return {"start": None, "end": None}

    valid = dataframe[column].dropna()

    if valid.empty:
        return {"start": None, "end": None}

    return {
        "start": timestamp_text(valid.min()),
        "end": timestamp_text(valid.max()),
    }


def load_telemetry(config):
    timestamp_column = config["columns"]["telemetry_timestamp"]
    timezone = config["time"]["telemetry_timezone_if_naive"]

    frames = []

    for item in config["input"]["telemetry_logs"]:
        drone_id = str(item["drone_id"])
        path = Path(item["path"])

        if not path.exists():
            raise FileNotFoundError(
                f"Telemetry file missing for {drone_id}: {path}"
            )

        dataframe = pd.read_csv(path)

        if timestamp_column not in dataframe.columns:
            raise KeyError(
                f"Column '{timestamp_column}' missing from {path}"
            )

        dataframe["drone_id"] = drone_id
        dataframe["source_telemetry_csv"] = str(path)

        dataframe["_telemetry_time_utc"] = parse_timestamp_series(
            dataframe[timestamp_column],
            timezone,
        )

        frames.append(dataframe)

    telemetry = pd.concat(frames, ignore_index=True, sort=False)

    telemetry = telemetry.sort_values(
        ["drone_id", "_telemetry_time_utc"]
    ).reset_index(drop=True)

    return telemetry


def load_records(
    path,
    timestamp_column,
    drone_column,
    naive_timezone,
    record_type,
):
    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"{record_type} file missing: {path}")

    dataframe = pd.read_csv(path)

    if dataframe.empty:
        dataframe["_record_time_utc"] = pd.Series(
            dtype="datetime64[ns, UTC]"
        )
        dataframe["_record_drone_id"] = pd.Series(dtype="object")
        return dataframe

    if timestamp_column not in dataframe.columns:
        raise KeyError(
            f"Column '{timestamp_column}' missing from {path}"
        )

    if drone_column not in dataframe.columns:
        raise KeyError(
            f"Column '{drone_column}' missing from {path}"
        )

    dataframe["_record_time_utc"] = parse_timestamp_series(
        dataframe[timestamp_column],
        naive_timezone,
    )

    dataframe["_record_drone_id"] = (
        dataframe[drone_column].astype(str)
    )

    return dataframe


def prefix_telemetry_columns(telemetry):
    renamed = telemetry.copy()

    rename_map = {}

    for column in renamed.columns:
        if column == "_telemetry_time_utc":
            continue

        rename_map[column] = f"telemetry_{column}"

    return renamed.rename(columns=rename_map)


def link_records_to_telemetry(
    records,
    telemetry,
    tolerance_seconds,
):
    if records.empty:
        output = records.copy()
        output["matched_telemetry"] = pd.Series(dtype="bool")
        output["time_difference_s"] = pd.Series(dtype="float")
        return output

    linked_frames = []
    telemetry_prefixed = prefix_telemetry_columns(telemetry)

    all_record_drones = sorted(
        records["_record_drone_id"].dropna().unique().tolist()
    )

    for drone_id in all_record_drones:
        record_group = records[
            records["_record_drone_id"] == drone_id
        ].copy()

        record_group = record_group.sort_values(
            "_record_time_utc"
        ).reset_index(drop=True)

        telemetry_group = telemetry_prefixed[
            telemetry_prefixed["telemetry_drone_id"] == drone_id
        ].copy()

        telemetry_group = telemetry_group.sort_values(
            "_telemetry_time_utc"
        ).reset_index(drop=True)

        if telemetry_group.empty:
            merged = record_group.copy()

            for column in telemetry_prefixed.columns:
                if column not in merged.columns:
                    merged[column] = pd.NA

            merged["matched_telemetry"] = False
            merged["time_difference_s"] = pd.NA
            linked_frames.append(merged)
            continue

        merged = pd.merge_asof(
            record_group,
            telemetry_group,
            left_on="_record_time_utc",
            right_on="_telemetry_time_utc",
            direction="nearest",
            tolerance=pd.Timedelta(
                seconds=float(tolerance_seconds)
            ),
        )

        merged["matched_telemetry"] = (
            merged["_telemetry_time_utc"].notna()
        )

        merged["time_difference_s"] = (
            merged["_record_time_utc"]
            - merged["_telemetry_time_utc"]
        ).abs().dt.total_seconds()

        linked_frames.append(merged)

    linked = pd.concat(
        linked_frames,
        ignore_index=True,
        sort=False,
    )

    return linked.sort_values(
        ["_record_time_utc", "_record_drone_id"]
    ).reset_index(drop=True)


def count_matches(dataframe):
    if dataframe.empty or "matched_telemetry" not in dataframe.columns:
        return 0

    return int(dataframe["matched_telemetry"].fillna(False).sum())


def write_report(path, summary):
    report = "# V1 Swarm Telemetry–Intelligence Merge Report\n\n"

    report += "## Input Records\n\n"
    report += (
        f"- Telemetry samples: "
        f"{summary['telemetry_samples']}\n"
    )
    report += (
        f"- Shared detections: "
        f"{summary['detection_records']}\n"
    )
    report += (
        f"- Shared source events: "
        f"{summary['event_records']}\n"
    )
    report += (
        f"- Nearest-match tolerance: "
        f"{summary['nearest_match_tolerance_s']} seconds\n"
    )

    report += "\n## Merge Results\n\n"
    report += (
        f"- Detections matched to telemetry: "
        f"{summary['matched_detections']}\n"
    )
    report += (
        f"- Detections without telemetry match: "
        f"{summary['unmatched_detections']}\n"
    )
    report += (
        f"- Events matched to telemetry: "
        f"{summary['matched_events']}\n"
    )
    report += (
        f"- Events without telemetry match: "
        f"{summary['unmatched_events']}\n"
    )

    report += "\n## Time Ranges in UTC\n\n"

    for name, value in summary["time_ranges_utc"].items():
        report += (
            f"- {name}: "
            f"{value['start']} to {value['end']}\n"
        )

    if (
        summary["matched_detections"] == 0
        and summary["detection_records"] > 0
    ):
        report += (
            "\n## Important Observation\n\n"
            "The detection timestamps do not overlap the mission "
            "telemetry timestamps within the configured tolerance. "
            "Run YOLO recording concurrently with the swarm mission "
            "to produce valid telemetry-linked detections.\n"
        )

    path.write_text(report)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--config",
        default=(
            "configs/logging/"
            "v1_swarm_merge_telemetry_intelligence.yaml"
        ),
    )

    args = parser.parse_args()

    config = load_yaml(Path(args.config))

    output_dir = Path(config["output"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    telemetry = load_telemetry(config)

    detections = load_records(
        config["input"]["shared_detections_csv"],
        config["columns"]["detection_timestamp"],
        config["columns"]["detection_drone_id"],
        config["time"]["detection_timezone_if_naive"],
        "Detection",
    )

    events = load_records(
        config["input"]["shared_events_csv"],
        config["columns"]["event_timestamp"],
        config["columns"]["event_drone_id"],
        config["time"]["event_timezone_if_naive"],
        "Event",
    )

    tolerance = float(
        config["time"]["nearest_match_tolerance_s"]
    )

    linked_detections = link_records_to_telemetry(
        detections,
        telemetry,
        tolerance,
    )

    linked_events = link_records_to_telemetry(
        events,
        telemetry,
        tolerance,
    )

    telemetry_output = (
        output_dir / config["output"]["combined_telemetry_csv"]
    )
    detections_output = (
        output_dir / config["output"]["linked_detections_csv"]
    )
    events_output = (
        output_dir / config["output"]["linked_events_csv"]
    )

    telemetry.to_csv(telemetry_output, index=False)
    linked_detections.to_csv(detections_output, index=False)
    linked_events.to_csv(events_output, index=False)

    matched_detections = count_matches(linked_detections)
    matched_events = count_matches(linked_events)

    summary = {
        "telemetry_samples": int(len(telemetry)),
        "detection_records": int(len(detections)),
        "event_records": int(len(events)),
        "nearest_match_tolerance_s": tolerance,
        "matched_detections": matched_detections,
        "unmatched_detections": (
            int(len(detections)) - matched_detections
        ),
        "matched_events": matched_events,
        "unmatched_events": (
            int(len(events)) - matched_events
        ),
        "time_ranges_utc": {
            "telemetry": dataframe_time_range(
                telemetry,
                "_telemetry_time_utc",
            ),
            "detections": dataframe_time_range(
                detections,
                "_record_time_utc",
            ),
            "events": dataframe_time_range(
                events,
                "_record_time_utc",
            ),
        },
        "outputs": {
            "combined_telemetry_csv": str(telemetry_output),
            "linked_detections_csv": str(detections_output),
            "linked_events_csv": str(events_output),
        },
    }

    summary_path = (
        output_dir / config["output"]["summary_json"]
    )
    report_path = (
        output_dir / config["output"]["report_md"]
    )

    summary_path.write_text(json.dumps(summary, indent=2))
    write_report(report_path, summary)

    print("Swarm telemetry-intelligence merge completed.")
    print("Telemetry samples:", len(telemetry))
    print("Detection records:", len(detections))
    print("Matched detections:", matched_detections)
    print("Event records:", len(events))
    print("Matched events:", matched_events)
    print("Report:", report_path)


if __name__ == "__main__":
    main()
