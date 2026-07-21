import time
import requests
import streamlit as st
import streamlit.components.v1 as components


st.set_page_config(
    page_title="V1 Swarm Live Dashboard",
    page_icon="🛰️",
    layout="wide",
)

st.title("🛰️ V1 Three-Drone Swarm Live Dashboard")

FEEDS = {
    "Drone 1": {
        "model": "x500_mono_cam_1",
        "port": 5011,
        "url": "http://127.0.0.1:5011/video_feed",
    },
    "Drone 2": {
        "model": "x500_mono_cam_2",
        "port": 5012,
        "url": "http://127.0.0.1:5012/video_feed",
    },
    "Drone 3": {
        "model": "x500_mono_cam_3",
        "port": 5013,
        "url": "http://127.0.0.1:5013/video_feed",
    },
}


def feed_status(port: int) -> str:
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


st.subheader("Camera Feed Status")

status_cols = st.columns(3)

for col, (name, item) in zip(status_cols, FEEDS.items()):
    status = feed_status(item["port"])
    with col:
        if status == "READY":
            st.success(f"{name}: READY")
        else:
            st.error(f"{name}: {status}")
        st.caption(f"{item['model']} | port {item['port']}")

st.divider()

st.subheader("Live YOLO Camera Feeds")

cols = st.columns(3)

for col, (name, item) in zip(cols, FEEDS.items()):
    with col:
        st.markdown(f"### {name}")
        st.caption(item["model"])

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
                    src="{item['url']}?t={int(time.time())}"
                    style="
                        width: 100%;
                        height: 360px;
                        object-fit: contain;
                        background: black;
                    "
                />
            </div>
            <p style="font-size: 12px;">
                Feed: {item['url']}
            </p>
            """,
            height=430,
        )

st.divider()

st.subheader("Project State")

st.write(
    {
        "simulation": "three PX4 drones running",
        "perception": "three YOLO MJPEG feeds",
        "feeds": {
            "drone_1": "http://127.0.0.1:5011/video_feed",
            "drone_2": "http://127.0.0.1:5012/video_feed",
            "drone_3": "http://127.0.0.1:5013/video_feed",
        },
    }
)

st.info(
    "Obstacle avoidance, LiDAR safety, local replanning and inter-drone "
    "collision modules are paused and not used in this dashboard."
)
