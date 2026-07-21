from pathlib import Path
import pandas as pd
import yaml


CONFIG_PATH = Path("configs/logging/v1_ai_selected_merge_detection_telemetry.yaml")


def load_config():
    with open(CONFIG_PATH, "r") as file:
        return yaml.safe_load(file)


def find_timestamp_column(df: pd.DataFrame, file_name: str) -> str:
    possible_columns = [
        "timestamp_utc",
        "timestamp",
        "time_utc",
        "datetime",
        "created_at",
    ]

    for column in possible_columns:
        if column in df.columns:
            return column

    raise ValueError(
        f"No timestamp column found in {file_name}. "
        f"Available columns: {list(df.columns)}"
    )


def parse_timestamp_series(series: pd.Series, timezone_if_naive: str) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce")

    if parsed.dt.tz is None:
        parsed = parsed.dt.tz_localize(timezone_if_naive)

    return parsed.dt.tz_convert("UTC")


def main():
    config = load_config()

    detection_csv_path = Path(config["input"]["detection_csv_path"])
    telemetry_csv_path = Path(config["input"]["telemetry_csv_path"])
    event_log_csv_path = Path(config["output"]["event_log_csv_path"])

    max_time_difference_s = float(config["merge"]["max_time_difference_s"])
    mission_name = config["metadata"]["mission_name"]
    event_type = config["metadata"]["event_type"]

    detection_timezone = config.get("time", {}).get(
        "detection_timezone_if_naive",
        "Asia/Kolkata",
    )
    telemetry_timezone = config.get("time", {}).get(
        "telemetry_timezone_if_naive",
        "UTC",
    )

    detections = pd.read_csv(detection_csv_path)
    telemetry = pd.read_csv(telemetry_csv_path)

    if detections.empty:
        raise ValueError("Detection CSV is empty.")

    if telemetry.empty:
        raise ValueError("Telemetry CSV is empty.")

    detection_time_col = find_timestamp_column(detections, "detection CSV")
    telemetry_time_col = find_timestamp_column(telemetry, "telemetry CSV")

    detections["detection_time_utc"] = parse_timestamp_series(
        detections[detection_time_col],
        detection_timezone,
    )

    telemetry["telemetry_time_utc"] = parse_timestamp_series(
        telemetry[telemetry_time_col],
        telemetry_timezone,
    )

    detections = detections.dropna(subset=["detection_time_utc"])
    telemetry = telemetry.dropna(subset=["telemetry_time_utc"])

    telemetry_start = telemetry["telemetry_time_utc"].min()
    telemetry_end = telemetry["telemetry_time_utc"].max()

    detections_inside_mission = detections[
        (detections["detection_time_utc"] >= telemetry_start - pd.Timedelta(seconds=max_time_difference_s))
        & (detections["detection_time_utc"] <= telemetry_end + pd.Timedelta(seconds=max_time_difference_s))
    ].copy()

    detections_inside_mission = detections_inside_mission.sort_values("detection_time_utc")
    telemetry = telemetry.sort_values("telemetry_time_utc")

    merged = pd.merge_asof(
        detections_inside_mission,
        telemetry,
        left_on="detection_time_utc",
        right_on="telemetry_time_utc",
        direction="nearest",
        tolerance=pd.Timedelta(seconds=max_time_difference_s),
        suffixes=("_detection", "_telemetry"),
    )

    merged.insert(0, "event_type", event_type)
    merged.insert(1, "mission_name_linked", mission_name)

    event_log_csv_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(event_log_csv_path, index=False)

    matched_count = merged["mission_phase"].notna().sum() if "mission_phase" in merged.columns else 0

    print("Detection + telemetry merge completed.")
    print("Detection original rows:", len(detections))
    print("Telemetry rows:", len(telemetry))
    print("Telemetry time range UTC:", telemetry_start, "to", telemetry_end)
    print("Detection rows inside mission time:", len(detections_inside_mission))
    print("Merged event rows:", len(merged))
    print("Rows linked with telemetry:", matched_count)
    print("Output:", event_log_csv_path.resolve())


if __name__ == "__main__":
    main()
