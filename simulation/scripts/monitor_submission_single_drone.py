#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from pymavlink import mavutil


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--config",
        default=(
            "configs/missions/"
            "submission_single_drone_qgc.yaml"
        ),
    )

    args = parser.parse_args()

    config = yaml.safe_load(
        Path(args.config).read_text(
            encoding="utf-8"
        )
    )

    connection = config["connection"]
    mission = config["mission"]
    output = config["output"]

    expected_waypoints = {
        int(sequence)
        for sequence
        in mission["expected_waypoint_sequences"]
    }

    land_sequence = int(
        mission["land_sequence"]
    )

    telemetry_path = Path(
        output["telemetry_csv"]
    )

    summary_path = Path(
        output["summary_json"]
    )

    telemetry_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    summary_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    master = mavutil.mavlink_connection(
        connection["endpoint"],
        source_system=int(
            connection["source_system"]
        ),
        source_component=int(
            connection["source_component"]
        ),
        autoreconnect=True,
    )

    source_system = int(
        connection["source_system"]
    )

    target_system = None
    current_sequence = -1
    reached_sequences: set[int] = set()

    armed = False
    ever_armed = False

    position_samples = 0

    last_heartbeat_sent = 0.0
    last_sample_written = 0.0

    summary = {
        "mission_name": mission["name"],
        "status": "started",
        "started_at_utc": utc_now(),
        "completed_at_utc": None,
        "expected_waypoint_sequences":
            sorted(expected_waypoints),
        "reached_sequences": [],
        "land_sequence": land_sequence,
        "landed": False,
        "position_samples": 0,
        "error": None,
    }

    with telemetry_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as telemetry_file:

        writer = csv.DictWriter(
            telemetry_file,
            fieldnames=[
                "timestamp_utc",
                "mission_sequence",
                "latitude_deg",
                "longitude_deg",
                "absolute_altitude_m",
                "relative_altitude_m",
                "armed",
            ],
        )

        writer.writeheader()

        deadline = (
            time.monotonic()
            + float(mission["timeout_s"])
        )

        try:
            while time.monotonic() < deadline:

                now = time.monotonic()

                if (
                    now - last_heartbeat_sent
                    >= 1.0
                ):
                    master.mav.heartbeat_send(
                        mavutil.mavlink.MAV_TYPE_GCS,
                        mavutil.mavlink
                        .MAV_AUTOPILOT_INVALID,
                        0,
                        0,
                        mavutil.mavlink
                        .MAV_STATE_ACTIVE,
                    )

                    last_heartbeat_sent = now

                message = master.recv_match(
                    blocking=True,
                    timeout=0.5,
                )

                if message is None:
                    continue

                message_type = (
                    message.get_type()
                )

                message_source = int(
                    message.get_srcSystem()
                )

                if (
                    message_type == "HEARTBEAT"
                    and message_source
                    != source_system
                ):
                    if target_system is None:
                        target_system = (
                            message_source
                        )

                        print(
                            "Connected to PX4 "
                            f"system {target_system}",
                            flush=True,
                        )

                    if (
                        message_source
                        == target_system
                    ):
                        armed = bool(
                            int(message.base_mode)
                            & mavutil.mavlink
                            .MAV_MODE_FLAG_SAFETY_ARMED
                        )

                        ever_armed = (
                            ever_armed or armed
                        )

                elif (
                    message_type
                    == "MISSION_CURRENT"
                ):
                    current_sequence = int(
                        message.seq
                    )

                    print(
                        "Mission current "
                        f"sequence: "
                        f"{current_sequence}",
                        flush=True,
                    )

                elif (
                    message_type
                    == "MISSION_ITEM_REACHED"
                ):
                    sequence = int(
                        message.seq
                    )

                    reached_sequences.add(
                        sequence
                    )

                    print(
                        "Mission item reached: "
                        f"{sequence}",
                        flush=True,
                    )

                elif (
                    message_type
                    == "GLOBAL_POSITION_INT"
                ):
                    if (
                        now - last_sample_written
                        >= float(
                            output[
                                "sample_interval_s"
                            ]
                        )
                    ):
                        writer.writerow({
                            "timestamp_utc":
                                utc_now(),
                            "mission_sequence":
                                current_sequence,
                            "latitude_deg":
                                float(
                                    message.lat
                                ) / 1e7,
                            "longitude_deg":
                                float(
                                    message.lon
                                ) / 1e7,
                            "absolute_altitude_m":
                                float(
                                    message.alt
                                ) / 1000.0,
                            "relative_altitude_m":
                                float(
                                    message.relative_alt
                                ) / 1000.0,
                            "armed":
                                armed,
                        })

                        telemetry_file.flush()

                        position_samples += 1
                        last_sample_written = now

                elif (
                    message_type
                    == "STATUSTEXT"
                ):
                    text = message.text

                    if isinstance(text, bytes):
                        text = text.decode(
                            errors="replace"
                        )

                    text = str(text).rstrip(
                        "\x00"
                    )

                    if text:
                        print(
                            f"PX4: {text}",
                            flush=True,
                        )

                waypoints_complete = (
                    expected_waypoints
                    <= reached_sequences
                )

                landing_complete = (
                    land_sequence
                    in reached_sequences
                    or current_sequence
                    >= land_sequence
                )

                if (
                    ever_armed
                    and not armed
                    and waypoints_complete
                    and landing_complete
                ):
                    summary["status"] = (
                        "completed"
                    )

                    summary[
                        "completed_at_utc"
                    ] = utc_now()

                    summary["landed"] = True

                    print(
                        "Single-drone mission "
                        "completed",
                        flush=True,
                    )

                    break

            else:
                raise TimeoutError(
                    "Mission monitor timed out"
                )

        except KeyboardInterrupt:
            summary["status"] = (
                "interrupted"
            )

            summary["completed_at_utc"] = (
                utc_now()
            )

            summary["error"] = (
                "Interrupted by user"
            )

        except Exception as error:
            summary["status"] = (
                "completed_with_errors"
            )

            summary["completed_at_utc"] = (
                utc_now()
            )

            summary["error"] = str(error)

            print(
                f"MONITOR ERROR: {error}",
                flush=True,
            )

        finally:
            master.close()

    summary["reached_sequences"] = sorted(
        reached_sequences
    )

    summary["position_samples"] = (
        position_samples
    )

    summary_path.write_text(
        json.dumps(
            summary,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Telemetry: {telemetry_path}")
    print(f"Summary: {summary_path}")

    if summary["status"] == "completed":
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
