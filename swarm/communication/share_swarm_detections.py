from pathlib import Path
import json
import pandas as pd
import yaml


CONFIG_PATH = Path("configs/swarm/v1_detection_sharing.yaml")


def load_yaml(path):
    return yaml.safe_load(path.read_text())


def safe_read_detection_csv(path, drone_id):
    path = Path(path)

    if not path.exists():
        print(f"[WARN] Missing detection log for {drone_id}: {path}")
        return pd.DataFrame()

    df = pd.read_csv(path)

    if df.empty:
        print(f"[WARN] Empty detection log for {drone_id}: {path}")
        return pd.DataFrame()

    df["drone_id"] = drone_id
    df["source_detection_csv"] = str(path)

    if "confidence" in df.columns:
        df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce").fillna(0.0)

    return df


def main():
    config = load_yaml(CONFIG_PATH)

    output_dir = Path(config["output"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    shared_csv_path = output_dir / config["output"]["shared_detection_csv"]
    summary_json_path = output_dir / config["output"]["shared_summary_json"]
    report_path = output_dir / config["output"]["shared_report_md"]

    confidence_threshold = float(config["sharing"]["confidence_threshold"])

    frames = []

    for item in config["input"]["drone_detection_logs"]:
        drone_id = item["drone_id"]
        detection_csv = item["detection_csv"]

        df = safe_read_detection_csv(detection_csv, drone_id)

        if not df.empty:
            frames.append(df)

    if frames:
        shared = pd.concat(frames, ignore_index=True, sort=False)
    else:
        shared = pd.DataFrame(columns=["drone_id", "timestamp", "model_name", "class_name", "confidence"])

    if "confidence" in shared.columns:
        shared = shared[shared["confidence"] >= confidence_threshold].copy()

    if "timestamp" in shared.columns:
        shared = shared.sort_values(["timestamp", "drone_id"], ascending=True)

    shared.to_csv(shared_csv_path, index=False)

    summary = {
        "swarm_name": config["swarm"]["name"],
        "total_shared_detections": int(len(shared)),
        "confidence_threshold": confidence_threshold,
        "drones": {},
        "labels": {},
        "models": {},
    }

    if not shared.empty:
        summary["drones"] = shared["drone_id"].value_counts().to_dict() if "drone_id" in shared.columns else {}
        summary["labels"] = shared["class_name"].value_counts().to_dict() if "class_name" in shared.columns else {}
        summary["models"] = shared["model_name"].value_counts().to_dict() if "model_name" in shared.columns else {}

    summary_json_path.write_text(json.dumps(summary, indent=2))

    report = "# V1 Swarm Detection Sharing Report\n\n"
    report += "Swarm: " + config["swarm"]["name"] + "\n\n"
    report += "Total shared detections: " + str(summary["total_shared_detections"]) + "\n\n"
    report += "Confidence threshold: " + str(confidence_threshold) + "\n\n"

    report += "## Detections by Drone\n\n"
    if summary["drones"]:
        for drone_id, count in summary["drones"].items():
            report += "- " + str(drone_id) + ": " + str(count) + "\n"
    else:
        report += "No detections available yet.\n"

    report += "\n## Original Detected Labels\n\n"
    if summary["labels"]:
        for label, count in summary["labels"].items():
            report += "- " + str(label) + ": " + str(count) + "\n"
    else:
        report += "No labels available yet.\n"

    report += "\n## Models\n\n"
    if summary["models"]:
        for model, count in summary["models"].items():
            report += "- " + str(model) + ": " + str(count) + "\n"
    else:
        report += "No model detections available yet.\n"

    report_path.write_text(report)

    print("Swarm detection sharing completed.")
    print("Shared detections:", shared_csv_path)
    print("Summary:", summary_json_path)
    print("Report:", report_path)
    print("Total shared detections:", len(shared))


if __name__ == "__main__":
    main()
