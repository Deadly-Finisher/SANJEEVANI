#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]

CONFIG_PATH = (
    PROJECT_ROOT
    / "configs"
    / "dashboard"
    / "v1_swarm_results_dashboard.yaml"
)


def project_path(path_value: str) -> Path:
    path = Path(path_value)

    if path.is_absolute():
        return path

    return PROJECT_ROOT / path


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        data = yaml.safe_load(file)

    if not isinstance(data, dict):
        raise ValueError(
            f"Invalid dashboard configuration: {path}"
        )

    return data


def read_json(path_value: str) -> dict[str, Any]:
    path = project_path(path_value)

    if not path.exists():
        return {}

    try:
        with path.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def read_csv(path_value: str) -> pd.DataFrame:
    path = project_path(path_value)

    if not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def read_text(path_value: str) -> str:
    path = project_path(path_value)

    if not path.exists():
        return ""

    try:
        return path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return ""


def last_non_empty(
    dataframe: pd.DataFrame,
    column: str,
    default: str = "Unknown",
) -> str:
    if column not in dataframe.columns:
        return default

    values = dataframe[column].dropna()

    if values.empty:
        return default

    return str(values.iloc[-1])


def maximum_numeric(
    dataframe: pd.DataFrame,
    column: str,
) -> float | None:
    if column not in dataframe.columns:
        return None

    values = pd.to_numeric(
        dataframe[column],
        errors="coerce",
    ).dropna()

    if values.empty:
        return None

    return float(values.max())


def metric_number(value: Any) -> str:
    if value is None:
        return "—"

    try:
        number = float(value)

        if number.is_integer():
            return f"{int(number):,}"

        return f"{number:,.2f}"
    except (TypeError, ValueError):
        return str(value)


def file_health(
    label: str,
    path_value: str,
) -> dict[str, Any]:
    path = project_path(path_value)

    return {
        "resource": label,
        "available": path.exists(),
        "size_kb": (
            round(path.stat().st_size / 1024, 2)
            if path.exists()
            else None
        ),
        "path": str(
            path.relative_to(PROJECT_ROOT)
        ),
    }


config = load_yaml(CONFIG_PATH)

dashboard_config = config["dashboard"]
project_config = config["project"]
paths = config["paths"]
drone_config = config["drones"]

st.set_page_config(
    page_title=dashboard_config["page_title"],
    page_icon=dashboard_config["page_icon"],
    layout="wide",
)

st.title("🛰️ Three-Drone Swarm Intelligence Dashboard")

st.caption(
    f"{project_config['title']} · "
    f"{project_config['swarm_name']} · "
    f"{project_config['world_name']}"
)

with st.sidebar:
    st.header("Dashboard controls")

    if st.button(
        "Refresh results",
        width="stretch",
    ):
        st.rerun()

    st.info(
        "This dashboard displays stable swarm "
        "mission outputs. Obstacle-avoidance "
        "experiments are excluded."
    )

mission_summary = read_json(
    paths["mission_summary_json"]
)
mission_report = read_text(
    paths["mission_report_md"]
)
zone_assignment = read_csv(
    paths["zone_assignment_csv"]
)
shared_detections = read_csv(
    paths["shared_detections_csv"]
)
shared_events = read_csv(
    paths["shared_events_csv"]
)
event_inbox = read_csv(
    paths["swarm_event_inbox_csv"]
)

detection_summary = read_json(
    paths["shared_detection_summary_json"]
)
event_summary = read_json(
    paths["shared_event_summary_json"]
)

telemetry = {
    drone["drone_id"]: read_csv(
        drone["telemetry_csv"]
    )
    for drone in drone_config
}

mission = mission_summary.get(
    "mission",
    {},
)
intelligence = mission_summary.get(
    "intelligence",
    {},
)
drone_summaries = mission_summary.get(
    "drones",
    [],
)

actual_telemetry_rows = sum(
    len(dataframe)
    for dataframe in telemetry.values()
)

metric_columns = st.columns(7)

metric_columns[0].metric(
    "Drones",
    metric_number(
        mission.get(
            "total_drones",
            len(telemetry),
        )
    ),
)

metric_columns[1].metric(
    "Successful drones",
    metric_number(
        mission.get(
            "successful_drones"
        )
    ),
)

mission_success_rate = metric_number(
    mission.get(
        "mission_success_rate_percent"
    )
)

metric_columns[2].metric(
    "Mission success",
    f"{mission_success_rate}%",
)

metric_columns[3].metric(
    "Telemetry records",
    metric_number(
        actual_telemetry_rows
    ),
)

metric_columns[4].metric(
    "Shared detections",
    metric_number(
        len(shared_detections)
    ),
)

metric_columns[5].metric(
    "Shared events",
    metric_number(
        len(shared_events)
    ),
)

estimated_distance = metric_number(
    mission.get(
        "estimated_total_distance_m"
    )
)

metric_columns[6].metric(
    "Estimated distance",
    f"{estimated_distance} m",
)

(
    live_camera_tab,
    overview_tab,
    drones_tab,
    detections_tab,
    events_tab,
    report_tab,
    health_tab,
) = st.tabs([
    "Live camera feeds",
    "Mission overview",
    "Per-drone telemetry",
    "Shared detections",
    "Shared events",
    "Mission report",
    "File health",
])



with live_camera_tab:
    st.subheader(
        "Live annotated three-drone surveillance"
    )

    st.caption(
        "The video panels become active when Gazebo, "
        "the ROS camera bridge and all three YOLO/MJPEG "
        "servers are running."
    )

    camera_columns = st.columns(3)

    for column, drone in zip(
        camera_columns,
        drone_config,
    ):
        with column:
            st.markdown(
                f"### {drone['display_name']}"
            )

            feed_url = drone.get(
                "video_feed_url",
                "",
            )

            if feed_url:
                st.markdown(
                    f"""
                    <div style="
                        border:1px solid #374151;
                        border-radius:12px;
                        padding:6px;
                        background:#05080e;
                    ">
                        <img
                            src="{feed_url}"
                            style="
                                width:100%;
                                min-height:260px;
                                object-fit:contain;
                                border-radius:8px;
                            "
                        />
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                st.code(
                    feed_url,
                    language=None,
                )
            else:
                st.warning(
                    "No video-feed URL configured."
                )


with overview_tab:
    st.subheader("Mission intelligence")

    overview_columns = st.columns(4)

    overview_columns[0].metric(
        "Broadcast messages",
        metric_number(
            intelligence.get(
                "total_broadcast_messages"
            )
        ),
    )

    overview_columns[1].metric(
        "Matched detections",
        metric_number(
            intelligence.get(
                "matched_detections"
            )
        ),
    )

    detection_link_rate = metric_number(
        intelligence.get(
            "detection_link_rate_percent"
        )
    )

    overview_columns[2].metric(
        "Detection link rate",
        f"{detection_link_rate}%",
    )

    event_link_rate = metric_number(
        intelligence.get(
            "event_link_rate_percent"
        )
    )

    overview_columns[3].metric(
        "Event link rate",
        f"{event_link_rate}%",
    )

    left_column, right_column = st.columns(2)

    with left_column:
        st.subheader("Zone assignments")

        if zone_assignment.empty:
            st.warning(
                "Zone-assignment CSV is unavailable."
            )
        else:
            st.dataframe(
                zone_assignment,
                width="stretch",
                hide_index=True,
            )

    with right_column:
        st.subheader("Drone mission summaries")

        if drone_summaries:
            summary_rows = []

            for item in drone_summaries:
                telemetry_summary = item.get(
                    "telemetry",
                    {},
                )

                summary_rows.append({
                    "drone_id":
                        item.get("drone_id"),
                    "mission_status":
                        item.get("mission_status"),
                    "mission_successful":
                        item.get(
                            "mission_successful"
                        ),
                    "assigned_zones":
                        ", ".join(
                            item.get(
                                "assigned_zones",
                                [],
                            )
                        ),
                    "completed_waypoints":
                        item.get(
                            "completed_waypoint_count"
                        ),
                    "telemetry_samples":
                        telemetry_summary.get(
                            "samples"
                        ),
                    "distance_m":
                        telemetry_summary.get(
                            "estimated_distance_m"
                        ),
                    "maximum_altitude_m":
                        telemetry_summary.get(
                            "maximum_relative_altitude_m"
                        ),
                    "detections":
                        item.get(
                            "detection_count"
                        ),
                    "events":
                        item.get(
                            "source_event_count"
                        ),
                })

            st.dataframe(
                pd.DataFrame(summary_rows),
                width="stretch",
                hide_index=True,
            )
        else:
            st.warning(
                "Drone mission summaries are unavailable."
            )


with drones_tab:
    display_names = {
        drone["drone_id"]:
            drone["display_name"]
        for drone in drone_config
    }

    selected_drone = st.selectbox(
        "Select drone",
        options=list(telemetry.keys()),
        format_func=lambda value:
            display_names.get(
                value,
                value,
            ),
    )

    selected_telemetry = telemetry[
        selected_drone
    ]

    if selected_telemetry.empty:
        st.warning(
            f"No telemetry available for "
            f"{selected_drone}."
        )
    else:
        drone_metrics = st.columns(4)

        drone_metrics[0].metric(
            "Telemetry samples",
            metric_number(
                len(selected_telemetry)
            ),
        )

        drone_metrics[1].metric(
            "Latest mission status",
            last_non_empty(
                selected_telemetry,
                "mission_status",
            ),
        )

        drone_metrics[2].metric(
            "Latest zone",
            last_non_empty(
                selected_telemetry,
                "current_zone",
                "Not assigned",
            ),
        )

        maximum_altitude = maximum_numeric(
            selected_telemetry,
            "relative_altitude_m",
        )

        maximum_altitude_text = metric_number(
            maximum_altitude
        )

        drone_metrics[3].metric(
            "Maximum altitude",
            f"{maximum_altitude_text} m",
        )

        chart_column, route_column = st.columns(2)

        with chart_column:
            st.subheader("Altitude profile")

            if (
                "relative_altitude_m"
                in selected_telemetry.columns
            ):
                altitude_data = pd.to_numeric(
                    selected_telemetry[
                        "relative_altitude_m"
                    ],
                    errors="coerce",
                )

                st.line_chart(
                    altitude_data,
                    height=350,
                )

        with route_column:
            st.subheader("Local mission route")

            route_columns = {
                "local_east_m",
                "local_north_m",
            }

            if route_columns.issubset(
                selected_telemetry.columns
            ):
                route = selected_telemetry[
                    [
                        "local_east_m",
                        "local_north_m",
                    ]
                ].copy()

                route["local_east_m"] = (
                    pd.to_numeric(
                        route["local_east_m"],
                        errors="coerce",
                    )
                )
                route["local_north_m"] = (
                    pd.to_numeric(
                        route["local_north_m"],
                        errors="coerce",
                    )
                )
                route = route.dropna()

                st.scatter_chart(
                    route,
                    x="local_east_m",
                    y="local_north_m",
                    height=350,
                )

        st.subheader("Recent telemetry")

        st.dataframe(
            selected_telemetry.tail(
                int(
                    dashboard_config[
                        "maximum_table_rows"
                    ]
                )
            ),
            width="stretch",
            hide_index=True,
        )


with detections_tab:
    if shared_detections.empty:
        st.warning(
            "Shared-detection data is unavailable."
        )
    else:
        filter_columns = st.columns(3)

        available_drones = sorted(
            shared_detections[
                "drone_id"
            ].dropna().astype(str).unique()
        )
        available_labels = sorted(
            shared_detections[
                "class_name"
            ].dropna().astype(str).unique()
        )

        selected_drones = (
            filter_columns[0].multiselect(
                "Source drones",
                available_drones,
                default=available_drones,
                key="detection_source_drones",
            )
        )

        selected_labels = (
            filter_columns[1].multiselect(
                "Object classes",
                available_labels,
                default=available_labels,
                key="detection_object_classes",
            )
        )

        minimum_confidence = (
            filter_columns[2].slider(
                "Minimum confidence",
                min_value=0.0,
                max_value=1.0,
                value=0.25,
                step=0.05,
            )
        )

        filtered_detections = (
            shared_detections[
                shared_detections[
                    "drone_id"
                ].astype(str).isin(
                    selected_drones
                )
            ]
        )

        filtered_detections = (
            filtered_detections[
                filtered_detections[
                    "class_name"
                ].astype(str).isin(
                    selected_labels
                )
            ]
        )

        confidence = pd.to_numeric(
            filtered_detections[
                "confidence"
            ],
            errors="coerce",
        )

        filtered_detections = (
            filtered_detections[
                confidence
                >= minimum_confidence
            ]
        )

        detection_columns = st.columns(2)

        with detection_columns[0]:
            st.subheader(
                "Detections by object class"
            )
            st.bar_chart(
                filtered_detections[
                    "class_name"
                ].value_counts()
            )

        with detection_columns[1]:
            st.subheader(
                "Detections by drone"
            )
            st.bar_chart(
                filtered_detections[
                    "drone_id"
                ].value_counts()
            )

        st.dataframe(
            filtered_detections.tail(
                int(
                    dashboard_config[
                        "maximum_table_rows"
                    ]
                )
            ),
            width="stretch",
            hide_index=True,
        )

        with st.expander(
            "Detection-sharing summary"
        ):
            st.json(detection_summary)


with events_tab:
    if shared_events.empty:
        st.warning(
            "Shared-event data is unavailable."
        )
    else:
        event_filter_columns = st.columns(2)

        available_severities = sorted(
            shared_events[
                "severity"
            ].dropna().astype(str).unique()
        )

        available_source_drones = sorted(
            shared_events[
                "source_drone_id"
            ].dropna().astype(str).unique()
        )

        selected_severities = (
            event_filter_columns[0].multiselect(
                "Severities",
                available_severities,
                default=available_severities,
                key="event_severities",
            )
        )

        selected_event_drones = (
            event_filter_columns[1].multiselect(
                "Source drones",
                available_source_drones,
                default=available_source_drones,
                key="event_source_drones",
            )
        )

        filtered_events = shared_events[
            shared_events[
                "severity"
            ].astype(str).isin(
                selected_severities
            )
        ]

        filtered_events = filtered_events[
            filtered_events[
                "source_drone_id"
            ].astype(str).isin(
                selected_event_drones
            )
        ]

        event_columns = st.columns(2)

        with event_columns[0]:
            st.subheader(
                "Events by severity"
            )
            st.bar_chart(
                filtered_events[
                    "severity"
                ].value_counts()
            )

        with event_columns[1]:
            st.subheader(
                "Events by source drone"
            )
            st.bar_chart(
                filtered_events[
                    "source_drone_id"
                ].value_counts()
            )

        st.dataframe(
            filtered_events.tail(
                int(
                    dashboard_config[
                        "maximum_table_rows"
                    ]
                )
            ),
            width="stretch",
            hide_index=True,
        )

        with st.expander(
            "Event-sharing summary"
        ):
            st.json(event_summary)

        with st.expander(
            "Swarm event inbox"
        ):
            st.dataframe(
                event_inbox.tail(
                    int(
                        dashboard_config[
                            "maximum_table_rows"
                        ]
                    )
                ),
                width="stretch",
                hide_index=True,
            )


with report_tab:
    if mission_report:
        st.markdown(mission_report)
    else:
        st.warning(
            "Mission intelligence report is unavailable."
        )


with health_tab:
    health_records = [
        file_health(
            "Mission summary",
            paths["mission_summary_json"],
        ),
        file_health(
            "Mission report",
            paths["mission_report_md"],
        ),
        file_health(
            "Zone assignment CSV",
            paths["zone_assignment_csv"],
        ),
        file_health(
            "Shared detections",
            paths["shared_detections_csv"],
        ),
        file_health(
            "Shared events",
            paths["shared_events_csv"],
        ),
        file_health(
            "Event inbox",
            paths["swarm_event_inbox_csv"],
        ),
    ]

    for drone in drone_config:
        health_records.append(
            file_health(
                f"{drone['drone_id']} telemetry",
                drone["telemetry_csv"],
            )
        )

    st.dataframe(
        pd.DataFrame(
            health_records
        ),
        width="stretch",
        hide_index=True,
    )

    st.caption(
        f"Dashboard configuration: "
        f"{CONFIG_PATH.relative_to(PROJECT_ROOT)}"
    )
