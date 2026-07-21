import argparse
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import yaml


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Streamlit dashboard for UAV simulation intelligence pipeline."
    )

    parser.add_argument(
        "--config",
        default="configs/dashboard.yaml",
        help="Path to dashboard YAML config file.",
    )

    args, _ = parser.parse_known_args()
    return args


def load_yaml_config(config_path: str) -> dict[str, Any]:
    path = Path(config_path)

    if not path.exists():
        raise FileNotFoundError(f"Dashboard config file not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        raise ValueError("Dashboard config must contain a YAML dictionary.")

    return config


def validate_safety(config: dict[str, Any]) -> None:
    safety = config["safety"]

    if bool(safety["allow_targeting"]):
        raise ValueError("Unsafe dashboard config: allow_targeting must remain false.")

    if bool(safety["allow_autonomous_engagement"]):
        raise ValueError(
            "Unsafe dashboard config: allow_autonomous_engagement must remain false."
        )

    if not bool(safety["human_review_required"]):
        raise ValueError(
            "Unsafe dashboard config: human_review_required must remain true."
        )


def get_latest_file(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None

    files = sorted(
        directory.glob(pattern),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )

    if not files:
        return None

    return files[0]


def read_text_file(path: Path) -> str:
    if not path.exists():
        return f"File not found: {path}"

    return path.read_text(encoding="utf-8")


def read_csv_if_exists(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None

    return pd.read_csv(path)


def render_header(config: dict[str, Any]) -> None:
    project = config["project"]

    st.set_page_config(
        page_title=project["title"],
        layout="wide",
    )

    st.title(project["title"])
    st.caption(project["subtitle"])

    st.info(
        "This dashboard is for simulation-based UAV surveillance, telemetry analysis, "
        "perception output review, and human-review event reporting. "
        "No targeting or autonomous engagement is performed."
    )


def render_sidebar(config: dict[str, Any]) -> None:
    st.sidebar.header("Project Status")

    st.sidebar.success("PX4 SITL simulation completed")
    st.sidebar.success("Python MAVSDK control completed")
    st.sidebar.success("Waypoint navigation completed")
    st.sidebar.success("Telemetry logging completed")
    st.sidebar.success("Telemetry analysis completed")
    st.sidebar.success("Synthetic perception completed")
    st.sidebar.success("Human-review report completed")

    st.sidebar.header("Safety Boundary")
    safety = config["safety"]

    st.sidebar.write(f"Targeting allowed: `{safety['allow_targeting']}`")
    st.sidebar.write(
        f"Autonomous engagement allowed: `{safety['allow_autonomous_engagement']}`"
    )
    st.sidebar.write(f"Human review required: `{safety['human_review_required']}`")


def render_telemetry_section(config: dict[str, Any]) -> None:
    st.header("1. Telemetry and Navigation Analysis")

    telemetry_dir = Path(config["paths"]["telemetry_dir"])
    analysis_dir = Path(config["paths"]["analysis_dir"])

    altitude_plot = analysis_dir / config["files"]["altitude_plot"]
    distance_plot = analysis_dir / config["files"]["distance_plot"]
    telemetry_summary_file = analysis_dir / config["files"]["telemetry_summary"]

    latest_telemetry_csv = get_latest_file(
        directory=telemetry_dir,
        pattern=config["patterns"]["waypoint_telemetry_csv"],
    )

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Mission altitude")
        if altitude_plot.exists():
            st.image(str(altitude_plot), caption="Waypoint mission altitude plot")
        else:
            st.warning(f"Altitude plot not found: {altitude_plot}")

    with col2:
        st.subheader("Distance to waypoint")
        if distance_plot.exists():
            st.image(str(distance_plot), caption="Waypoint distance plot")
        else:
            st.warning(f"Distance plot not found: {distance_plot}")

    st.subheader("Telemetry summary")
    st.text(read_text_file(telemetry_summary_file))

    st.subheader("Latest waypoint telemetry CSV preview")

    if latest_telemetry_csv is None:
        st.warning("No waypoint telemetry CSV found.")
        return

    st.caption(f"Latest telemetry file: {latest_telemetry_csv}")

    telemetry_df = pd.read_csv(latest_telemetry_csv)

    max_rows = int(config["dashboard"]["max_rows_preview"])
    st.dataframe(telemetry_df.tail(max_rows), use_container_width=True)


def render_perception_section(config: dict[str, Any]) -> None:
    st.header("2. Perception Pipeline Output")

    perception_dir = Path(config["paths"]["perception_dir"])
    detections_csv = perception_dir / config["files"]["detections_csv"]
    perception_summary_file = perception_dir / config["files"]["perception_summary"]
    annotated_dir = perception_dir / "annotated"

    detections_df = read_csv_if_exists(detections_csv)

    col1, col2, col3 = st.columns(3)

    if detections_df is not None:
        total_detections = len(detections_df)
        unique_frames = detections_df["frame_id"].nunique()
        unique_classes = detections_df["label"].nunique()

        col1.metric("Total detections", total_detections)
        col2.metric("Frames with detections", unique_frames)
        col3.metric("Detected classes", unique_classes)
    else:
        col1.metric("Total detections", 0)
        col2.metric("Frames with detections", 0)
        col3.metric("Detected classes", 0)

    st.subheader("Perception summary")
    st.text(read_text_file(perception_summary_file))

    st.subheader("Detection CSV preview")

    if detections_df is None:
        st.warning(f"Detections CSV not found: {detections_csv}")
    else:
        st.dataframe(detections_df, use_container_width=True)

    st.subheader("Annotated evidence images")

    if not annotated_dir.exists():
        st.warning(f"Annotated image directory not found: {annotated_dir}")
        return

    max_images = int(config["dashboard"]["max_annotated_images"])
    annotated_images = sorted(annotated_dir.glob("*.png"))[:max_images]

    if not annotated_images:
        st.warning("No annotated images found.")
        return

    image_columns = st.columns(min(len(annotated_images), 3))

    for index, image_path in enumerate(annotated_images):
        with image_columns[index % len(image_columns)]:
            st.image(str(image_path), caption=image_path.name)


def render_intelligence_section(config: dict[str, Any]) -> None:
    st.header("3. Human-Review Event Intelligence Report")

    reports_dir = Path(config["paths"]["reports_dir"])
    event_summary_csv = reports_dir / config["files"]["event_summary_csv"]
    mission_event_report = reports_dir / config["files"]["mission_event_report"]

    event_summary_df = read_csv_if_exists(event_summary_csv)

    if event_summary_df is None:
        st.warning(f"Event summary CSV not found: {event_summary_csv}")
    else:
        st.subheader("Class-wise event summary")
        st.dataframe(event_summary_df, use_container_width=True)

        total_score = event_summary_df["class_event_score"].sum()
        total_count = event_summary_df["count"].sum()

        col1, col2 = st.columns(2)
        col1.metric("Total event score", f"{total_score:.2f}")
        col2.metric("Total event count", int(total_count))

    st.subheader("Mission event report")

    if not mission_event_report.exists():
        st.warning(f"Mission event report not found: {mission_event_report}")
        return

    report_text = read_text_file(mission_event_report)
    st.markdown(report_text)


def main() -> None:
    args = parse_arguments()

    config = load_yaml_config(args.config)
    validate_safety(config)

    render_header(config)
    render_sidebar(config)

    render_telemetry_section(config)
    st.divider()

    render_perception_section(config)
    st.divider()

    render_intelligence_section(config)


if __name__ == "__main__":
    main()