from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yaml


CONFIG_PATH = Path("configs/dashboard/v1_mission_dashboard.yaml")


def load_config():
    with open(CONFIG_PATH, "r") as file:
        return yaml.safe_load(file)


def safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()

    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    except Exception as exc:
        st.warning(f"Could not read {path}: {exc}")
        return pd.DataFrame()


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

    title = config["dashboard"]["title"]
    mjpeg_url = config["stream"]["mjpeg_url"]

    detection_path = Path(config["input"]["detection_csv_path"])
    telemetry_path = Path(config["input"]["telemetry_csv_path"])
    event_log_path = Path(config["input"]["event_log_csv_path"])
    report_path = Path(config["input"]["report_path"])

    st.set_page_config(page_title=title, layout="wide")
    st.title(title)

    st.caption("Single-drone V1 mission: live camera, multi-model detections, telemetry, merged events, and mission report.")

    detections = safe_read_csv(detection_path)
    telemetry = safe_read_csv(telemetry_path)
    events = safe_read_csv(event_log_path)

    if not events.empty and "class_name" in events.columns:
        events["original_detected_label"] = events["class_name"].apply(add_original_detected_label)

    if not events.empty and "confidence" in events.columns:
        events["confidence"] = pd.to_numeric(events["confidence"], errors="coerce")

    left, right = st.columns([2, 1])

    with left:
        st.subheader("Live YOLO Camera Feed")
        components.html(
            f"""
            <div style="width:100%;">
                <img src="{mjpeg_url}"
                     style="width:100%; border-radius:10px; border:1px solid #444;" />
            </div>
            """,
            height=520,
        )

    with right:
        st.subheader("Mission Summary")

        total_events = len(events)
        total_detections = len(detections)
        total_telemetry = len(telemetry)

        unique_zones = events["zone_name"].nunique() if not events.empty and "zone_name" in events.columns else 0
        unique_classes = events["class_name"].nunique() if not events.empty and "class_name" in events.columns else 0
        unique_models = events["model_name"].nunique() if not events.empty and "model_name" in events.columns else 0

        st.metric("Linked Events", total_events)
        st.metric("Raw Detections", total_detections)
        st.metric("Telemetry Samples", total_telemetry)
        st.metric("Zones with Events", unique_zones)
        st.metric("Raw Classes", unique_classes)
        st.metric("Detector Models", unique_models)

    st.divider()

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        [
            "Zone-wise Events",
            "Original Labels",
            "Raw Classes",
            "Telemetry",
            "Mission Report",
        ]
    )

    with tab1:
        st.subheader("Zone-wise Linked Detection Events")

        if events.empty:
            st.info("No merged event log found yet.")
        else:
            zone_summary = (
                events.groupby(["zone_name", "original_detected_label"])
                .size()
                .reset_index(name="detection_count")
                .sort_values(["zone_name", "detection_count"], ascending=[True, False])
            )

            st.dataframe(zone_summary, use_container_width=True)

            chart_data = zone_summary.pivot_table(
                index="zone_name",
                columns="original_detected_label",
                values="detection_count",
                fill_value=0,
            )

            st.bar_chart(chart_data)

    with tab2:
        st.subheader("Original Detected Label Summary")

        if events.empty:
            st.info("No merged event log found yet.")
        else:
            category_summary = (
                events.groupby("original_detected_label")
                .agg(
                    detection_count=("original_detected_label", "size"),
                    avg_confidence=("confidence", "mean"),
                    max_confidence=("confidence", "max"),
                )
                .reset_index()
                .sort_values("detection_count", ascending=False)
            )

            st.dataframe(category_summary, use_container_width=True)

            chart_data = category_summary.set_index("original_detected_label")["detection_count"]
            st.bar_chart(chart_data)

    with tab3:
        st.subheader("Raw Model/Class Summary")

        if events.empty:
            st.info("No merged event log found yet.")
        else:
            raw_summary = (
                events.groupby(["model_name", "class_name"])
                .agg(
                    detection_count=("class_name", "size"),
                    avg_confidence=("confidence", "mean"),
                    max_confidence=("confidence", "max"),
                )
                .reset_index()
                .sort_values("detection_count", ascending=False)
            )

            st.dataframe(raw_summary, use_container_width=True)

            st.subheader("Highest Confidence Events")

            columns = [
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

            available_columns = [column for column in columns if column in events.columns]

            high_confidence = events.sort_values("confidence", ascending=False)[available_columns].head(50)
            st.dataframe(high_confidence, use_container_width=True)

    with tab4:
        st.subheader("Telemetry Summary")

        if telemetry.empty:
            st.info("No telemetry log found yet.")
        else:
            if {"mission_phase", "zone_name"}.issubset(telemetry.columns):
                telemetry_summary = (
                    telemetry.groupby(["mission_phase", "zone_name"])
                    .size()
                    .reset_index(name="telemetry_samples")
                )
                st.dataframe(telemetry_summary, use_container_width=True)

            st.subheader("Recent Telemetry")
            st.dataframe(telemetry.tail(100), use_container_width=True)

    with tab5:
        st.subheader("Generated Mission Intelligence Report")

        if report_path.exists():
            st.markdown(report_path.read_text())
        else:
            st.info(f"Report not found: {report_path}")

    st.divider()

    st.subheader("Merged Event Log Preview")
    if events.empty:
        st.info("No merged event log available.")
    else:
        st.dataframe(events.tail(200), use_container_width=True)


if __name__ == "__main__":
    main()
