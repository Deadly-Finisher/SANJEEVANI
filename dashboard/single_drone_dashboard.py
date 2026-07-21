from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yaml
from PIL import Image

try:
    from streamlit_autorefresh import st_autorefresh
except Exception:
    st_autorefresh = None


def load_config(path: str) -> dict:
    with open(path, "r") as file:
        return yaml.safe_load(file)


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()

    if path.stat().st_size == 0:
        return pd.DataFrame()

    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()
    except Exception as exc:
        st.warning(f"Could not read {path}: {exc}")
        return pd.DataFrame()


def get_latest_image(image_dir: Path):
    if not image_dir.exists():
        return None

    images = sorted(
        list(image_dir.glob("*.jpg"))
        + list(image_dir.glob("*.jpeg"))
        + list(image_dir.glob("*.png")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not images:
        return None

    return images[0]


def main():
    config = load_config("configs/dashboard/single_drone_dashboard.yaml")

    detection_csv_path = Path(config["input"]["detection_csv_path"])
    telemetry_csv_path = Path(config["input"]["telemetry_csv_path"])
    event_log_csv_path = Path(config["input"]["event_log_csv_path"])
    report_path = Path(config["input"]["report_path"])
    annotated_frame_dir = Path(config["input"]["annotated_frame_dir"])

    title = config["dashboard"]["title"]
    refresh_seconds = int(config["dashboard"].get("refresh_seconds", 2))

    st.set_page_config(page_title=title, layout="wide")
    st.title(title)

    if st_autorefresh is not None:
        st_autorefresh(interval=refresh_seconds * 1000, key="dashboard_refresh")

    detections = load_csv(detection_csv_path)
    telemetry = load_csv(telemetry_csv_path)
    event_log = load_csv(event_log_csv_path)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Live Detections", len(detections))

    with col2:
        if not detections.empty and "class_name" in detections.columns:
            st.metric("Detected Classes", detections["class_name"].nunique())
        else:
            st.metric("Detected Classes", 0)

    with col3:
        st.metric("Telemetry Samples", len(telemetry))

    with col4:
        st.metric("Linked Events", len(event_log))

    st.divider()

    left, right = st.columns([1.3, 1])

    with left:
        st.subheader("Real-time YOLO Drone Camera Feed")

        components.html(
            """
            <div style="width:100%;">
                <img src="http://172.18.181.223:5001/video_feed"
                     style="width:100%; border-radius:10px; border:1px solid #444;" />
            </div>
            """,
            height=520,
        )

    with right:
        st.subheader("Detection Summary")

        if not detections.empty and "class_name" in detections.columns:
            class_counts = detections["class_name"].value_counts().reset_index()
            class_counts.columns = ["Class", "Count"]
            st.dataframe(class_counts, use_container_width=True)
        else:
            st.warning("No detection data available yet.")

        st.subheader("Latest Telemetry")

        if not telemetry.empty:
            latest_telemetry = telemetry.tail(1).T
            latest_telemetry.columns = ["Latest Value"]
            st.dataframe(latest_telemetry, use_container_width=True)
        else:
            st.warning("No telemetry data available yet.")

    st.divider()

    st.subheader("Telemetry-linked Event Log")

    if not event_log.empty:
        st.dataframe(event_log.tail(20), use_container_width=True)
    else:
        st.warning("No telemetry-linked event log available yet.")

    st.divider()

    st.subheader("Mission Event Report")

    if report_path.exists() and report_path.stat().st_size > 0:
        st.markdown(report_path.read_text())
    else:
        st.warning("Mission report not found yet.")


if __name__ == "__main__":
    main()
