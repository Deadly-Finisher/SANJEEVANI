from pathlib import Path
import json
import time

import requests
import streamlit as st
import streamlit.components.v1 as components


ROOT = Path.home() / "Programs" / "SWARM_DRONES"
LIVE_STATE = ROOT / "outputs/live/swarm_live_state.json"

FEEDS = {
    "drone_1": {
        "name": "Drone 1",
        "model": "x500_mono_cam_1",
        "port": 5011,
        "url": "http://127.0.0.1:5011/video_feed",
    },
    "drone_2": {
        "name": "Drone 2",
        "model": "x500_mono_cam_2",
        "port": 5012,
        "url": "http://127.0.0.1:5012/video_feed",
    },
    "drone_3": {
        "name": "Drone 3",
        "model": "x500_mono_cam_3",
        "port": 5013,
        "url": "http://127.0.0.1:5013/video_feed",
    },
}


st.set_page_config(
    page_title="V1 Swarm Operator Dashboard",
    page_icon="🛰️",
    layout="wide",
)

st.title("🛰️ V1 Three-Drone Swarm Operator Dashboard")


def check_feed(port: int) -> str:
    try:
        response = requests.get(
            f"http://127.0.0.1:{port}/",
            timeout=2,
        )
        if response.status_code == 200:
            return "READY"
        return f"HTTP {response.status_code}"
    except Exception:
        return "OFFLINE"


def load_state() -> dict:
    if not LIVE_STATE.exists():
        return {
            "mission": {
                "status": "WAITING",
                "phase": "no_live_state_yet",
                "elapsed_s": 0,
                "updated_at_utc": None,
            },
            "drones": {},
            "safety": {},
            "operator_notes": [
                "Run the surveillance patrol script to populate live telemetry."
            ],
        }

    try:
        return json.loads(LIVE_STATE.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "mission": {
                "status": "ERROR",
                "phase": f"state_read_error: {exc}",
                "elapsed_s": 0,
                "updated_at_utc": None,
            },
            "drones": {},
            "safety": {},
            "operator_notes": [],
        }


state = load_state()
mission = state.get("mission", {})
drones = state.get("drones", {})
safety = state.get("safety", {})

top = st.columns(5)

top[0].metric("Mission Status", mission.get("status", "UNKNOWN"))
top[1].metric("Phase", mission.get("phase", "UNKNOWN"))
top[2].metric("Elapsed", f"{mission.get('elapsed_s', 0)} s")
top[3].metric("Loop", f"{mission.get('loop', 0)}/{mission.get('total_loops', 0)}")
top[4].metric("Safety", safety.get("status", "UNKNOWN"))

st.caption(f"Last update UTC: {mission.get('updated_at_utc')}")

st.divider()

st.subheader("📷 Live YOLO Camera Feeds")

feed_statuses = {}

status_cols = st.columns(3)
for col, (drone_id, feed) in zip(status_cols, FEEDS.items()):
    status = check_feed(feed["port"])
    feed_statuses[drone_id] = status

    with col:
        if status == "READY":
            st.success(f"{feed['name']}: READY")
        else:
            st.error(f"{feed['name']}: {status}")

        st.caption(f"{feed['model']} | port {feed['port']}")

feed_cols = st.columns(3)
for col, (drone_id, feed) in zip(feed_cols, FEEDS.items()):
    with col:
        st.markdown(f"### {feed['name']}")
        components.html(
            f"""
            <div style="
                border: 2px solid #444;
                border-radius: 10px;
                padding: 6px;
                background: #111;
                text-align: center;
            ">
                <img
                    src="{feed['url']}?t={int(time.time())}"
                    style="
                        width: 100%;
                        height: 330px;
                        object-fit: contain;
                        background: black;
                    "
                />
            </div>
            <p style="font-size: 12px;">{feed['url']}</p>
            """,
            height=400,
        )

st.divider()

st.subheader("📡 Drone Telemetry")

rows = []

for drone_id, data in drones.items():
    rows.append(
        {
            "drone": drone_id,
            "model": data.get("model"),
            "status": data.get("status"),
            "zone": data.get("zone"),
            "phase": data.get("phase"),
            "x": data.get("x"),
            "y": data.get("y"),
            "z_altitude_m": data.get("z"),
            "assigned_altitude_m": data.get("assigned_altitude_m"),
            "current_waypoint": data.get("current_waypoint"),
            "next_waypoint": data.get("next_waypoint"),
            "yaw_rad": data.get("yaw_rad"),
            "feed": feed_statuses.get(drone_id),
        }
    )

if rows:
    st.dataframe(rows, use_container_width=True)
else:
    st.warning("No live drone telemetry yet. Start the patrol script.")

st.subheader("🛡️ Swarm Separation Safety")

safety_cols = st.columns(3)
safety_cols[0].metric(
    "Minimum 3D Separation",
    f"{safety.get('minimum_3d_separation_m', 'NA')} m",
)
safety_cols[1].metric(
    "Closest Pair",
    safety.get("closest_pair", "NA"),
)
safety_cols[2].metric(
    "Altitude Separation",
    "ENABLED"
    if safety.get("altitude_separation_enabled")
    else "UNKNOWN",
)

pairwise = safety.get("pairwise_distances_m", {})
if pairwise:
    st.json(pairwise)

st.subheader("🗺️ Mission Map Data")

map_rows = []
for drone_id, data in drones.items():
    map_rows.append(
        {
            "drone": drone_id,
            "x": data.get("x"),
            "y": data.get("y"),
            "altitude": data.get("z"),
            "zone": data.get("zone"),
        }
    )

if map_rows:
    st.dataframe(map_rows, use_container_width=True)

st.subheader("🧠 Operator Notes")

for note in state.get("operator_notes", []):
    st.info(note)

st.divider()

st.subheader("Raw Live State JSON")
with st.expander("Show full live state"):
    st.json(state)

time.sleep(1)
st.rerun()
