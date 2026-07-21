from pathlib import Path
from datetime import datetime
import html
import json

import pandas as pd
import requests
import streamlit as st
import yaml
from streamlit_autorefresh import st_autorefresh


CONFIG_PATH = Path(
    "configs/dashboard/v1_swarm_live_dashboard.yaml"
)


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def read_json(path_value):
    path = Path(path_value)

    if not path.exists():
        return {}

    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def read_csv(path_value):
    path = Path(path_value)

    if not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def server_is_running(base_url: str) -> bool:
    try:
        requests.get(base_url, timeout=0.4)
        return True
    except requests.RequestException:
        return False


def normalize_label(value):
    return str(value).strip().lower()


def classify_severity(label, severity_config):
    normalized = normalize_label(label)

    for severity_name in (
        "critical",
        "high",
        "medium",
        "low",
    ):
        configured = {
            normalize_label(item)
            for item in severity_config.get(
                severity_name,
                [],
            )
        }

        if normalized in configured:
            return severity_name

    return "unknown"


def prepare_detection_dataframe(
    dataframe,
    drone_id,
    severity_config,
):
    if dataframe.empty:
        return dataframe

    output = dataframe.copy()

    output["drone_id"] = drone_id

    if "class_name" not in output.columns:
        output["class_name"] = "unknown"

    if "confidence" in output.columns:
        output["confidence"] = pd.to_numeric(
            output["confidence"],
            errors="coerce",
        )
    else:
        output["confidence"] = pd.NA

    if "timestamp" in output.columns:
        output["timestamp"] = pd.to_datetime(
            output["timestamp"],
            errors="coerce",
            utc=True,
        )
    else:
        output["timestamp"] = pd.NaT

    output["severity"] = output[
        "class_name"
    ].map(
        lambda label: classify_severity(
            label,
            severity_config,
        )
    )

    return output


def latest_detection_table(dataframe, maximum_rows):
    if dataframe.empty:
        return pd.DataFrame(
            columns=[
                "Time",
                "Object",
                "Confidence",
                "Model",
                "Severity",
            ]
        )

    latest = dataframe.sort_values(
        "timestamp",
        ascending=False,
    ).head(maximum_rows)

    table = pd.DataFrame()

    if "timestamp" in latest.columns:
        table["Time"] = latest["timestamp"].dt.strftime(
            "%H:%M:%S"
        )

    table["Object"] = latest["class_name"]

    if "confidence" in latest.columns:
        table["Confidence"] = (
            latest["confidence"] * 100
        ).round(1).astype(str) + "%"
    else:
        table["Confidence"] = "N/A"

    if "model_name" in latest.columns:
        table["Model"] = latest["model_name"]
    else:
        table["Model"] = "unknown"

    table["Severity"] = latest["severity"].str.upper()

    return table


def telemetry_statistics(path_value):
    dataframe = read_csv(path_value)

    if dataframe.empty:
        return {
            "samples": 0,
            "maximum_altitude": None,
            "current_zone": "No telemetry",
            "mission_status": "Unknown",
        }

    maximum_altitude = None

    if "relative_altitude_m" in dataframe.columns:
        altitude = pd.to_numeric(
            dataframe["relative_altitude_m"],
            errors="coerce",
        ).dropna()

        if not altitude.empty:
            maximum_altitude = float(
                altitude.max()
            )

    current_zone = "Unknown"

    if "current_zone" in dataframe.columns:
        zones = dataframe[
            "current_zone"
        ].dropna()

        if not zones.empty:
            current_zone = str(zones.iloc[-1])

    mission_status = "Unknown"

    if "mission_status" in dataframe.columns:
        statuses = dataframe[
            "mission_status"
        ].dropna()

        if not statuses.empty:
            mission_status = str(
                statuses.iloc[-1]
            )

    return {
        "samples": int(len(dataframe)),
        "maximum_altitude": maximum_altitude,
        "current_zone": current_zone,
        "mission_status": mission_status,
    }


def status_badge(is_live):
    if is_live:
        return (
            '<span class="status-live">'
            "● LIVE"
            "</span>"
        )

    return (
        '<span class="status-offline">'
        "● OFFLINE"
        "</span>"
    )


config = load_yaml(CONFIG_PATH)

st.set_page_config(
    page_title=config["dashboard"]["page_title"],
    page_icon=config["dashboard"]["page_icon"],
    layout="wide",
    initial_sidebar_state="expanded",
)

refresh_seconds = int(
    config["dashboard"]["refresh_seconds"]
)

st_autorefresh(
    interval=refresh_seconds * 1000,
    key="swarm-dashboard-refresh",
)

st.markdown(
    """
<style>
    .stApp {
        background:
            radial-gradient(
                circle at top left,
                #16233b 0%,
                #080d17 42%,
                #05080e 100%
            );
    }

    .block-container {
        padding-top: 1.4rem;
        padding-bottom: 3rem;
        max-width: 1900px;
    }

    h1, h2, h3 {
        color: #f5f8ff;
    }

    .dashboard-header {
        padding: 1.3rem 1.5rem;
        margin-bottom: 1.2rem;
        border-radius: 18px;
        border: 1px solid rgba(114, 166, 255, 0.23);
        background:
            linear-gradient(
                135deg,
                rgba(20, 44, 80, 0.96),
                rgba(8, 15, 28, 0.96)
            );
        box-shadow: 0 16px 45px rgba(0, 0, 0, 0.32);
    }

    .dashboard-title {
        font-size: 2rem;
        font-weight: 800;
        color: #ffffff;
        letter-spacing: 0.02em;
    }

    .dashboard-subtitle {
        margin-top: 0.35rem;
        color: #aebbd0;
        font-size: 0.95rem;
    }

    .video-card {
        background: rgba(10, 17, 29, 0.95);
        border: 1px solid rgba(103, 157, 255, 0.23);
        border-radius: 18px;
        overflow: hidden;
        box-shadow: 0 14px 32px rgba(0, 0, 0, 0.35);
        margin-bottom: 0.85rem;
    }

    .video-header {
        min-height: 72px;
        padding: 0.85rem 1rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.7rem;
        background:
            linear-gradient(
                135deg,
                rgba(24, 46, 78, 0.96),
                rgba(10, 20, 36, 0.96)
            );
    }

    .video-title {
        color: #f7faff;
        font-weight: 750;
        font-size: 0.92rem;
    }

    .video-caption {
        color: #8ea2bf;
        font-size: 0.78rem;
        margin-top: 0.22rem;
    }

    .video-frame {
        width: 100%;
        aspect-ratio: 16 / 10;
        object-fit: cover;
        display: block;
        background: #020408;
    }

    .status-live {
        color: #49f29c;
        background: rgba(29, 166, 99, 0.15);
        border: 1px solid rgba(73, 242, 156, 0.34);
        padding: 0.25rem 0.55rem;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 800;
        white-space: nowrap;
    }

    .status-offline {
        color: #ff6b7e;
        background: rgba(213, 54, 75, 0.15);
        border: 1px solid rgba(255, 107, 126, 0.32);
        padding: 0.25rem 0.55rem;
        border-radius: 999px;
        font-size: 0.72rem;
        font-weight: 800;
        white-space: nowrap;
    }

    .object-summary {
        padding: 0.8rem 0.9rem;
        border-radius: 14px;
        border: 1px solid rgba(108, 145, 204, 0.18);
        background: rgba(10, 17, 29, 0.82);
        margin-bottom: 0.75rem;
        color: #dce7f8;
    }

    .object-chip {
        display: inline-block;
        margin: 0.15rem 0.18rem 0.15rem 0;
        padding: 0.22rem 0.5rem;
        border-radius: 999px;
        background: rgba(52, 107, 190, 0.22);
        border: 1px solid rgba(90, 148, 237, 0.3);
        color: #dbe9ff;
        font-size: 0.73rem;
    }

    [data-testid="stMetric"] {
        background: rgba(12, 20, 34, 0.88);
        border: 1px solid rgba(103, 157, 255, 0.18);
        border-radius: 15px;
        padding: 0.8rem;
        box-shadow: 0 10px 28px rgba(0, 0, 0, 0.2);
    }

    [data-testid="stDataFrame"] {
        border: 1px solid rgba(103, 157, 255, 0.18);
        border-radius: 13px;
        overflow: hidden;
    }

    .section-heading {
        margin-top: 0.5rem;
        margin-bottom: 0.8rem;
        color: #f5f8ff;
        font-size: 1.25rem;
        font-weight: 750;
    }
</style>
""",
    unsafe_allow_html=True,
)

now_text = datetime.now().strftime(
    "%d %b %Y · %I:%M:%S %p"
)

st.markdown(
    f"""
<div class="dashboard-header">
    <div class="dashboard-title">
        🛡️ AI Swarm Battlefield Intelligence
    </div>
    <div class="dashboard-subtitle">
        Three-drone autonomous surveillance, object detection,
        shared events and synchronized mission telemetry
        · Updated {html.escape(now_text)}
    </div>
</div>
""",
    unsafe_allow_html=True,
)

severity_config = config["severity"]
maximum_rows = int(
    config["dashboard"]["maximum_table_rows"]
)

drone_data = {}
active_feeds = 0
total_live_detections = 0
total_critical_detections = 0

for drone in config["drones"]:
    drone_id = drone["drone_id"]

    is_live = server_is_running(
        drone["stream_base_url"]
    )

    if is_live:
        active_feeds += 1

    detections = prepare_detection_dataframe(
        read_csv(drone["detection_csv"]),
        drone_id,
        severity_config,
    )

    telemetry = telemetry_statistics(
        drone["telemetry_csv"]
    )

    mission_summary = read_json(
        drone["mission_summary_json"]
    )

    total_live_detections += len(detections)

    if not detections.empty:
        total_critical_detections += int(
            (
                detections["severity"]
                == "critical"
            ).sum()
        )

    drone_data[drone_id] = {
        "configuration": drone,
        "is_live": is_live,
        "detections": detections,
        "telemetry": telemetry,
        "mission_summary": mission_summary,
    }

merge_summary = read_json(
    config["intelligence"]["merge_summary_json"]
)

mission_report_summary = read_json(
    config["intelligence"][
        "mission_report_summary_json"
    ]
)

linked_detections = int(
    merge_summary.get("matched_detections", 0)
)

total_detection_records = int(
    merge_summary.get("detection_records", 0)
)

linkage_rate = (
    100.0
    * linked_detections
    / total_detection_records
    if total_detection_records
    else 0.0
)

metric_columns = st.columns(5)

metric_columns[0].metric(
    "Active video feeds",
    f"{active_feeds}/3",
)

metric_columns[1].metric(
    "Live detection records",
    total_live_detections,
)

metric_columns[2].metric(
    "Critical detections",
    total_critical_detections,
)

metric_columns[3].metric(
    "Telemetry-linked",
    linked_detections,
)

metric_columns[4].metric(
    "Synchronization rate",
    f"{linkage_rate:.1f}%",
)

with st.sidebar:
    st.markdown("## Mission Control")

    st.write(
        f"**Swarm:** "
        f"{config['mission']['swarm_name']}"
    )

    st.write(
        f"**World:** "
        f"{config['mission']['world_name']}"
    )

    st.write(
        f"**Refresh:** every "
        f"{refresh_seconds} seconds"
    )

    st.divider()

    st.markdown("### Video endpoints")

    for drone in config["drones"]:
        data = drone_data[drone["drone_id"]]

        icon = "🟢" if data["is_live"] else "🔴"

        st.write(
            f"{icon} **{drone['drone_id']}**"
        )

        st.caption(
            drone["video_feed_url"]
        )

    st.divider()

    if st.button(
        "Refresh dashboard now",
        use_container_width=True,
    ):
        st.rerun()

tabs = st.tabs(
    [
        "📡 Live Swarm Operations",
        "🎯 Object Intelligence",
        "🚨 Shared Events",
        "📊 Mission Analytics",
    ]
)

with tabs[0]:
    st.markdown(
        '<div class="section-heading">'
        "Live YOLO Camera Feeds"
        "</div>",
        unsafe_allow_html=True,
    )

    feed_columns = st.columns(3)

    for column, drone in zip(
        feed_columns,
        config["drones"],
    ):
        drone_id = drone["drone_id"]
        data = drone_data[drone_id]

        with column:
            feed_url = html.escape(
                drone["video_feed_url"]
            )

            title = html.escape(
                drone["display_name"]
            )

            assigned_zone = html.escape(
                drone["assigned_zone"]
            )

            st.markdown(
                f"""
<div class="video-card">
    <div class="video-header">
        <div>
            <div class="video-title">{title}</div>
            <div class="video-caption">
                Assigned zone: {assigned_zone}
            </div>
        </div>
        {status_badge(data["is_live"])}
    </div>
    <img
        class="video-frame"
        src="{feed_url}"
        alt="{title}"
    />
</div>
""",
                unsafe_allow_html=True,
            )

            detections = data["detections"]

            if detections.empty:
                chip_text = (
                    '<span class="object-chip">'
                    "No detections available"
                    "</span>"
                )
            else:
                counts = (
                    detections["class_name"]
                    .value_counts()
                    .head(6)
                )

                chip_text = "".join(
                    (
                        '<span class="object-chip">'
                        f"{html.escape(str(label))}: "
                        f"{int(count)}"
                        "</span>"
                    )
                    for label, count in counts.items()
                )

            st.markdown(
                f"""
<div class="object-summary">
    <strong>Objects detected</strong><br/>
    {chip_text}
</div>
""",
                unsafe_allow_html=True,
            )

            col_a, col_b, col_c = st.columns(3)

            col_a.metric(
                "Detections",
                len(detections),
            )

            col_b.metric(
                "Labels",
                (
                    detections[
                        "class_name"
                    ].nunique()
                    if not detections.empty
                    else 0
                ),
            )

            col_c.metric(
                "Max altitude",
                (
                    f"{data['telemetry']['maximum_altitude']:.1f} m"
                    if data["telemetry"][
                        "maximum_altitude"
                    ] is not None
                    else "N/A"
                ),
            )

            st.caption(
                f"Mission status: "
                f"{data['mission_summary'].get('status', 'unknown')}"
                f" · Current/last zone: "
                f"{data['telemetry']['current_zone']}"
            )

            st.markdown("##### Latest detections")

            st.dataframe(
                latest_detection_table(
                    detections,
                    maximum_rows=12,
                ),
                use_container_width=True,
                hide_index=True,
                height=315,
            )

with tabs[1]:
    combined_detections = []

    for drone_id, data in drone_data.items():
        if not data["detections"].empty:
            combined_detections.append(
                data["detections"]
            )

    if combined_detections:
        detections = pd.concat(
            combined_detections,
            ignore_index=True,
            sort=False,
        )

        chart_col_1, chart_col_2 = st.columns(2)

        with chart_col_1:
            st.markdown(
                "### Detections by object label"
            )

            label_counts = (
                detections["class_name"]
                .value_counts()
                .rename_axis("Object")
                .to_frame("Count")
            )

            st.bar_chart(label_counts)

        with chart_col_2:
            st.markdown(
                "### Detections by drone"
            )

            drone_counts = (
                detections["drone_id"]
                .value_counts()
                .rename_axis("Drone")
                .to_frame("Count")
            )

            st.bar_chart(drone_counts)

        model_col, severity_col = st.columns(2)

        with model_col:
            st.markdown(
                "### Detection models"
            )

            if "model_name" in detections.columns:
                model_counts = (
                    detections["model_name"]
                    .value_counts()
                    .rename_axis("Model")
                    .to_frame("Count")
                )

                st.bar_chart(model_counts)

        with severity_col:
            st.markdown(
                "### Detection severity"
            )

            severity_counts = (
                detections["severity"]
                .value_counts()
                .rename_axis("Severity")
                .to_frame("Count")
            )

            st.bar_chart(severity_counts)

        st.markdown("### Complete detection log")

        display_columns = [
            column
            for column in [
                "timestamp",
                "drone_id",
                "class_name",
                "confidence",
                "model_name",
                "severity",
                "frame_id",
                "x1",
                "y1",
                "x2",
                "y2",
            ]
            if column in detections.columns
        ]

        detection_table = detections.sort_values(
            "timestamp",
            ascending=False,
        )[display_columns].head(maximum_rows)

        st.dataframe(
            detection_table,
            use_container_width=True,
            hide_index=True,
            height=500,
        )

    else:
        st.warning(
            "No live detection records are available."
        )

with tabs[2]:
    shared_events = read_csv(
        config["intelligence"]["shared_events_csv"]
    )

    event_summary = read_json(
        config["intelligence"][
            "event_summary_json"
        ]
    )

    event_metrics = st.columns(4)

    event_metrics[0].metric(
        "Shared events",
        int(event_summary.get("total_events", 0)),
    )

    event_metrics[1].metric(
        "Broadcast messages",
        int(
            event_summary.get(
                "total_broadcast_messages",
                0,
            )
        ),
    )

    severity_distribution = event_summary.get(
        "events_by_severity",
        {},
    )

    event_metrics[2].metric(
        "Critical events",
        int(
            severity_distribution.get(
                "critical",
                0,
            )
        ),
    )

    event_metrics[3].metric(
        "High-priority events",
        int(
            severity_distribution.get(
                "high",
                0,
            )
        ),
    )

    if severity_distribution:
        severity_dataframe = pd.DataFrame(
            {
                "Severity": list(
                    severity_distribution.keys()
                ),
                "Count": list(
                    severity_distribution.values()
                ),
            }
        ).set_index("Severity")

        st.markdown("### Event severity distribution")
        st.bar_chart(severity_dataframe)

    if not shared_events.empty:
        st.markdown("### Latest shared swarm events")

        available_columns = [
            column
            for column in [
                "event_id",
                "timestamp",
                "source_drone_id",
                "original_detected_label",
                "severity",
                "severity_score",
                "confidence",
                "model_name",
                "sharing_status",
            ]
            if column in shared_events.columns
        ]

        st.dataframe(
            shared_events[
                available_columns
            ].head(maximum_rows),
            use_container_width=True,
            hide_index=True,
            height=520,
        )
    else:
        st.info(
            "No shared swarm events are available."
        )

with tabs[3]:
    mission_information = (
        mission_report_summary.get(
            "mission",
            {},
        )
    )

    intelligence_information = (
        mission_report_summary.get(
            "intelligence",
            {},
        )
    )

    mission_metrics = st.columns(5)

    mission_metrics[0].metric(
        "Mission success",
        (
            f"{mission_information.get('mission_success_rate_percent', 0):.1f}%"
        ),
    )

    mission_metrics[1].metric(
        "Successful drones",
        (
            f"{mission_information.get('successful_drones', 0)}/"
            f"{mission_information.get('total_drones', 3)}"
        ),
    )

    mission_metrics[2].metric(
        "Telemetry samples",
        int(
            mission_information.get(
                "total_telemetry_samples",
                0,
            )
        ),
    )

    mission_metrics[3].metric(
        "Flight distance",
        (
            f"{mission_information.get('estimated_total_distance_m', 0):.1f} m"
        ),
    )

    mission_metrics[4].metric(
        "Linked intelligence",
        int(
            intelligence_information.get(
                "matched_detections",
                0,
            )
        ),
    )

    st.markdown("### Per-drone mission performance")

    mission_rows = []

    for drone_id, data in drone_data.items():
        summary = data["mission_summary"]
        telemetry = data["telemetry"]
        detections = data["detections"]

        mission_rows.append(
            {
                "Drone": drone_id,
                "Status": summary.get(
                    "status",
                    "unknown",
                ),
                "Mission": summary.get(
                    "mission_name",
                    "",
                ),
                "Assigned zone": data[
                    "configuration"
                ]["assigned_zone"],
                "Telemetry samples": telemetry[
                    "samples"
                ],
                "Maximum altitude (m)": telemetry[
                    "maximum_altitude"
                ],
                "Detection records": len(
                    detections
                ),
                "Completed waypoints": len(
                    summary.get(
                        "completed_waypoints",
                        [],
                    )
                ),
            }
        )

    st.dataframe(
        pd.DataFrame(mission_rows),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown(
        "### Telemetry–intelligence synchronization"
    )

    synchronization_columns = st.columns(4)

    synchronization_columns[0].metric(
        "Telemetry samples",
        int(
            merge_summary.get(
                "telemetry_samples",
                0,
            )
        ),
    )

    synchronization_columns[1].metric(
        "Detection records",
        int(
            merge_summary.get(
                "detection_records",
                0,
            )
        ),
    )

    synchronization_columns[2].metric(
        "Matched detections",
        int(
            merge_summary.get(
                "matched_detections",
                0,
            )
        ),
    )

    synchronization_columns[3].metric(
        "Matched events",
        int(
            merge_summary.get(
                "matched_events",
                0,
            )
        ),
    )
