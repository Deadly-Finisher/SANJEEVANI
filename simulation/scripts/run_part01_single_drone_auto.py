#!/usr/bin/env python3
from __future__ import annotations

import csv, json, math, os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pymavlink import mavutil

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "configs/missions/part01_single_drone_auto.yaml"


def now():
    return datetime.now(timezone.utc).isoformat()


def load():
    return yaml.safe_load(CFG.read_text(encoding="utf-8"))


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def offset(lat, lon, north, east):
    r = 6378137.0
    return (
        lat + math.degrees(north / r),
        lon + math.degrees(east / (r * max(math.cos(math.radians(lat)), 1e-6))),
    )


def call(args, *, env=None, check=True):
    return subprocess.run(args, cwd=ROOT, env=env, check=check, text=True)


class Vehicle:
    def __init__(self, cfg):
        c = cfg["connection"]
        self.cfg = cfg
        self.source_system = int(c["source_system"])
        self.master = mavutil.mavlink_connection(
            c["endpoint"],
            source_system=self.source_system,
            source_component=int(c["source_component"]),
            autoreconnect=True,
        )
        self.target_system = 0
        self.target_component = 1
        self.last_gcs = 0.0
        self.position = None
        self.armed = False
        self.current = -1
        self.reached = set()
        self.status = ""

    def close(self):
        self.master.close()

    def heartbeat(self):
        if time.monotonic() - self.last_gcs < 1:
            return
        self.master.mav.heartbeat_send(
            mavutil.mavlink.MAV_TYPE_GCS,
            mavutil.mavlink.MAV_AUTOPILOT_INVALID,
            0, 0, mavutil.mavlink.MAV_STATE_ACTIVE,
        )
        self.last_gcs = time.monotonic()

    def pump(self, timeout=0.5):
        self.heartbeat()
        m = self.master.recv_match(blocking=True, timeout=timeout)
        if m is None:
            return None
        t = m.get_type()
        src = int(m.get_srcSystem())

        if t == "HEARTBEAT" and src != self.source_system:
            if not self.target_system:
                self.target_system = src
                self.target_component = int(m.get_srcComponent()) or 1
                log(f"Connected to PX4 system {src}")
            if src == self.target_system:
                self.armed = bool(
                    int(m.base_mode)
                    & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
                )

        elif t == "GLOBAL_POSITION_INT":
            self.position = {
                "lat": m.lat / 1e7,
                "lon": m.lon / 1e7,
                "abs": m.alt / 1000.0,
                "rel": m.relative_alt / 1000.0,
            }

        elif t == "MISSION_CURRENT":
            seq = int(m.seq)
            if seq != self.current:
                if self.current >= 0 and seq > self.current:
                    self.reached.add(self.current)
                self.current = seq
                log(f"Mission current: {seq}")

        elif t == "MISSION_ITEM_REACHED":
            seq = int(m.seq)
            self.reached.add(seq)
            log(f"Mission item reached: {seq}")

        elif t == "STATUSTEXT":
            text = m.text.decode(errors="replace") if isinstance(m.text, bytes) else str(m.text)
            text = text.rstrip("\x00")
            if text and text != self.status:
                self.status = text
                log(f"PX4: {text}")

        elif t == "COMMAND_ACK":
            log(f"ACK command={int(m.command)} result={int(m.result)}")

        return m

    def wait_ready(self, timeout):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.pump()
            if self.target_system and self.position:
                log(f"Global position ready: {self.position}")
                return
        raise TimeoutError("PX4 connection/global position timeout")

    def command(self, command, params):
        p = (list(params) + [0.0] * 7)[:7]
        self.master.mav.command_long_send(
            self.target_system, self.target_component, command, 0, *p
        )

    def clear_mission(self):
        try:
            self.master.mav.mission_clear_all_send(
                self.target_system,
                self.target_component,
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION,
            )
        except TypeError:
            self.master.mav.mission_clear_all_send(
                self.target_system, self.target_component
            )
        end = time.monotonic() + 2
        while time.monotonic() < end:
            self.pump(0.2)

    def mission_count(self, count):
        try:
            self.master.mav.mission_count_send(
                self.target_system,
                self.target_component,
                count,
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION,
                0,
            )
        except TypeError:
            try:
                self.master.mav.mission_count_send(
                    self.target_system,
                    self.target_component,
                    count,
                    mavutil.mavlink.MAV_MISSION_TYPE_MISSION,
                )
            except TypeError:
                self.master.mav.mission_count_send(
                    self.target_system, self.target_component, count
                )

    def send_item(self, item, integer=True):
        common = [
            self.target_system,
            self.target_component,
            item["seq"],
            item["frame_int"] if integer else item["frame"],
            item["cmd"],
            item["current"],
            1,
            item["p1"], item["p2"], 0.0, math.nan,
            int(round(item["lat"] * 1e7)) if integer else item["lat"],
            int(round(item["lon"] * 1e7)) if integer else item["lon"],
            item["alt"],
        ]
        fn = (
            self.master.mav.mission_item_int_send
            if integer
            else self.master.mav.mission_item_send
        )
        try:
            fn(*common, mavutil.mavlink.MAV_MISSION_TYPE_MISSION)
        except TypeError:
            fn(*common)

    def upload(self, items, timeout):
        self.clear_mission()
        self.mission_count(len(items))
        log(f"Uploading {len(items)} mission items")
        end = time.monotonic() + timeout
        last = time.monotonic()
        retries = 0

        while time.monotonic() < end:
            m = self.pump()
            if m is None:
                if time.monotonic() - last > 2:
                    retries += 1
                    if retries > 5:
                        break
                    log(f"Upload retry {retries}/5")
                    self.mission_count(len(items))
                    last = time.monotonic()
                continue

            t = m.get_type()
            if t in ("MISSION_REQUEST_INT", "MISSION_REQUEST"):
                seq = int(m.seq)
                if not 0 <= seq < len(items):
                    raise RuntimeError(f"Invalid mission request {seq}")
                self.send_item(items[seq], t == "MISSION_REQUEST_INT")
                log(f"Sent mission item {seq}")
                last = time.monotonic()

            elif t == "MISSION_ACK":
                result = int(m.type)
                if result == mavutil.mavlink.MAV_MISSION_ACCEPTED:
                    log("Mission upload accepted")
                    return
                raise RuntimeError(f"Mission upload rejected: {result}")

        raise TimeoutError("Mission upload timed out")

    def arm(self, timeout, force, resend):
        command = mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
        end = time.monotonic() + timeout
        next_send = 0
        accepted = False
        last_result = None

        while time.monotonic() < end:
            if time.monotonic() >= next_send:
                log(f"Sending arm command (force={force})")
                self.command(command, [1.0, 21196.0 if force else 0.0])
                next_send = time.monotonic() + resend

            m = self.pump()
            if self.armed:
                log("Armed state confirmed")
                return

            if m and m.get_type() == "COMMAND_ACK" and int(m.command) == command:
                last_result = int(m.result)
                if last_result == mavutil.mavlink.MAV_RESULT_ACCEPTED:
                    accepted = True
                    log("Arm accepted by PX4")
                    break

        if not accepted and not self.armed:
            raise RuntimeError(
                f"Arming failed; ACK={last_result}; status={self.status}"
            )

        end = time.monotonic() + 3
        while time.monotonic() < end:
            self.pump(0.2)

    def start(self, last_sequence):
        try:
            self.master.mav.mission_set_current_send(
                self.target_system,
                self.target_component,
                0,
                mavutil.mavlink.MAV_MISSION_TYPE_MISSION,
            )
        except TypeError:
            self.master.mav.mission_set_current_send(
                self.target_system, self.target_component, 0
            )
        log("Starting mission")
        self.command(
            mavutil.mavlink.MAV_CMD_MISSION_START,
            [0.0, float(last_sequence)],
        )

    def monitor(self, items, telemetry, timeout, sample_s, landed_m):
        telemetry.parent.mkdir(parents=True, exist_ok=True)
        expected = {
            x["seq"]
            for x in items
            if x["cmd"] == mavutil.mavlink.MAV_CMD_NAV_WAYPOINT
        }
        land_seq = items[-1]["seq"]
        end = time.monotonic() + timeout
        last_sample = 0.0
        samples = 0
        low = 0

        with telemetry.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp_utc", "mission_sequence", "latitude_deg",
                    "longitude_deg", "absolute_altitude_m",
                    "relative_altitude_m", "armed",
                ],
            )
            w.writeheader()

            while time.monotonic() < end:
                self.pump()
                t = time.monotonic()

                if self.position and t - last_sample >= sample_s:
                    w.writerow(
                        {
                            "timestamp_utc": now(),
                            "mission_sequence": self.current,
                            "latitude_deg": self.position["lat"],
                            "longitude_deg": self.position["lon"],
                            "absolute_altitude_m": self.position["abs"],
                            "relative_altitude_m": self.position["rel"],
                            "armed": self.armed,
                        }
                    )
                    f.flush()
                    samples += 1
                    last_sample = t

                if (
                    self.current >= land_seq
                    and self.position
                    and self.position["rel"] <= landed_m
                ):
                    low += 1
                else:
                    low = 0

                if low >= 6:
                    self.reached.add(land_seq)
                    break
            else:
                raise TimeoutError("Mission timed out")

        return {
            "expected_waypoint_sequences": sorted(expected),
            "reached_sequences": sorted(self.reached),
            "all_waypoints_reached": expected <= self.reached,
            "land_sequence": land_seq,
            "landed": land_seq in self.reached,
            "position_samples": samples,
        }

    def land(self, timeout):
        if not self.position:
            return
        log("Emergency landing")
        self.command(
            mavutil.mavlink.MAV_CMD_NAV_LAND,
            [0, 0, 0, math.nan, self.position["lat"], self.position["lon"], 0],
        )
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.pump()
            if self.position and self.position["rel"] <= 0.7:
                return


def build_items(cfg, home_lat, home_lon):
    m = cfg["mission"]
    frame = mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT
    frame_int = mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
    alt = float(m["takeoff_altitude_m"])
    radius = float(m["acceptance_radius_m"])
    items = [
        {
            "seq": 0, "frame": frame, "frame_int": frame_int,
            "cmd": mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            "current": 1, "p1": 0.0, "p2": radius,
            "lat": home_lat, "lon": home_lon, "alt": alt,
        }
    ]

    for seq, wp in enumerate(m["waypoints"], start=1):
        lat, lon = offset(
            home_lat, home_lon, float(wp["north_m"]), float(wp["east_m"])
        )
        items.append(
            {
                "seq": seq, "frame": frame, "frame_int": frame_int,
                "cmd": mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                "current": 0, "p1": float(wp["hold_s"]), "p2": radius,
                "lat": lat, "lon": lon,
                "alt": float(wp.get("altitude_m", alt)),
            }
        )

    land = m["land_offset"]
    lat, lon = offset(
        home_lat, home_lon, float(land["north_m"]), float(land["east_m"])
    )
    items.append(
        {
            "seq": len(items), "frame": frame, "frame_int": frame_int,
            "cmd": mavutil.mavlink.MAV_CMD_NAV_LAND,
            "current": 0, "p1": 0.0, "p2": radius,
            "lat": lat, "lon": lon, "alt": 0.0,
        }
    )
    return items


def launch(cfg):
    c = cfg["launch"]
    env = os.environ.copy()
    env.update(
        {
            "WORLD_NAME": str(c["world_name"]),
            "MODEL_NAME": str(c["model_name"]),
            "MODEL_POSE": str(c["model_pose"]),
            "AUTOSTART_ID": str(c["autostart_id"]),
        }
    )
    for name, value in c["px4_parameters"].items():
        env[f"PX4_PARAM_{name}"] = str(value)

    log("Launching clean single-drone runtime")
    result = call([str(ROOT / c["launcher"])], env=env, check=False)
    if result.returncode:
        raise RuntimeError(f"Launcher failed with code {result.returncode}")


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def checkpoint(cfg, summary_path):
    if not cfg["checkpoint"]["enabled"]:
        return
    paths = [
        str(CFG.relative_to(ROOT)),
        "simulation/scripts/run_part01_single_drone_auto.py",
        str(summary_path.relative_to(ROOT)),
        "simulation/scripts/launch_submission_single_drone.sh",
        "simulation/scripts/validate_submission_single_drone.py",
    ]
    paths = [p for p in paths if (ROOT / p).exists()]
    call(["git", "add", *paths])
    subprocess.run(
        ["git", "commit", "-m", cfg["checkpoint"]["commit_message"]],
        cwd=ROOT,
        text=True,
    )
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"], cwd=ROOT, text=True
    ).strip()
    tag = cfg["checkpoint"]["tag_name"]
    call(["git", "tag", "-f", "-a", tag, "-m", tag])
    call(["git", "push", "origin", branch])
    call(["git", "push", "--force", "origin", tag])
    log(f"Private GitHub checkpoint pushed: {tag}")


def main():
    cfg = load()
    out = cfg["output"]
    telemetry = ROOT / out["telemetry_csv"]
    summary_path = ROOT / out["summary_json"]
    summary = {
        "part": 1,
        "status": "started",
        "started_at_utc": now(),
        "completed_at_utc": None,
        "transport": "MAVLink mission protocol",
        "error": None,
    }
    vehicle = None

    try:
        log("PART 1 AUTOMATIC RUN STARTED")
        log("Only monitor Gazebo and this terminal.")
        launch(cfg)

        vehicle = Vehicle(cfg)
        vehicle.wait_ready(float(cfg["timeouts"]["connection_s"]))
        items = build_items(
            cfg, vehicle.position["lat"], vehicle.position["lon"]
        )
        vehicle.upload(items, float(cfg["timeouts"]["upload_s"]))
        vehicle.arm(
            float(cfg["timeouts"]["arm_s"]),
            bool(cfg["mission"]["force_arm_in_simulation"]),
            float(cfg["mission"]["command_resend_interval_s"]),
        )
        vehicle.start(items[-1]["seq"])

        result = vehicle.monitor(
            items,
            telemetry,
            float(cfg["timeouts"]["mission_s"]),
            float(out["sample_interval_s"]),
            float(cfg["mission"]["landing_altitude_threshold_m"]),
        )
        summary.update(result)
        summary["checks"] = {
            "all_waypoints_reached": result["all_waypoints_reached"],
            "landed": result["landed"],
            "telemetry_recorded": result["position_samples"]
            >= int(out["minimum_telemetry_samples"]),
        }
        if not all(summary["checks"].values()):
            raise RuntimeError(f"Strict validation failed: {summary['checks']}")

        summary["status"] = "completed"
        summary["completed_at_utc"] = now()
        save(summary_path, summary)
        log("PART 1 VALIDATION: PASS")
        log("Drone completed all waypoints and landed.")
        checkpoint(cfg, summary_path)
        log("PART 1 COMPLETE")
        return 0

    except Exception as error:
        summary["status"] = "completed_with_errors"
        summary["completed_at_utc"] = now()
        summary["error"] = str(error)
        log(f"PART 1 ERROR: {error}")
        if vehicle:
            try:
                vehicle.land(float(cfg["timeouts"]["emergency_land_s"]))
            except Exception as landing_error:
                summary["emergency_landing_error"] = str(landing_error)
        save(summary_path, summary)
        return 1

    finally:
        save(summary_path, summary)
        if vehicle:
            vehicle.close()
        log(f"Summary: {summary_path}")
        log(f"Telemetry: {telemetry}")


if __name__ == "__main__":
    sys.exit(main())
