from pathlib import Path
import yaml
import pandas as pd


def load_config(path: str) -> dict:
    with open(path, "r") as file:
        return yaml.safe_load(file)


def main() -> None:
    config = load_config("configs/logging/merge_detection_telemetry.yaml")

    detection_csv_path = Path(config["input"]["detection_csv_path"])
    telemetry_csv_path = Path(config["input"]["telemetry_csv_path"])
    output_csv_path = Path(config["output"]["event_log_csv_path"])

    max_time_difference_s = float(config["merge"]["max_time_difference_s"])
    mission_name = config["metadata"]["mission_name"]
    event_type = config["metadata"]["event_type"]

    output_csv_path.parent.mkdir(parents=True, exist_ok=True)

    if not detection_csv_path.exists():
        raise FileNotFoundError(f"Detection CSV not found: {detection_csv_path}")

    if not telemetry_csv_path.exists():
        raise FileNotFoundError(f"Telemetry CSV not found: {telemetry_csv_path}")

    detections = pd.read_csv(detection_csv_path)
    telemetry = pd.read_csv(telemetry_csv_path)

    if detections.empty:
        raise ValueError("Detection CSV is empty.")

    if telemetry.empty:
        raise ValueError("Telemetry CSV is empty.")

    detections["detection_timestamp"] = pd.to_datetime(detections["timestamp"])
    telemetry["telemetry_timestamp"] = pd.to_datetime(telemetry["timestamp"])

    detections = detections.sort_values("detection_timestamp")
    telemetry = telemetry.sort_values("telemetry_timestamp")

    detections = detections.drop(columns=["timestamp"])
    telemetry = telemetry.drop(columns=["timestamp"])

    merged = pd.merge_asof(
        detections,
        telemetry,
        left_on="detection_timestamp",
        right_on="telemetry_timestamp",
        direction="nearest",
        tolerance=pd.Timedelta(seconds=max_time_difference_s),
    )

    merged.insert(0, "event_id", range(1, len(merged) + 1))
    merged.insert(1, "mission_name", mission_name)
    merged.insert(2, "event_type", event_type)

    merged["time_difference_s"] = (
        merged["detection_timestamp"] - merged["telemetry_timestamp"]
    ).dt.total_seconds().abs()

    merged.to_csv(output_csv_path, index=False)

    linked_count = merged["telemetry_timestamp"].notna().sum()

    print("Telemetry-linked detection event log created.")
    print(f"Detections: {len(detections)}")
    print(f"Linked with telemetry: {linked_count}")
    print(f"Unlinked detections: {len(detections) - linked_count}")
    print(f"Saved to: {output_csv_path.resolve()}")


if __name__ == "__main__":
    main()