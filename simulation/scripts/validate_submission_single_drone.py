#!/usr/bin/env python3
from __future__ import annotations

import sys
import time

from pymavlink import mavutil


ENDPOINT = "udpin:0.0.0.0:14540"
TIMEOUT_S = 45.0
SOURCE_SYSTEM = 250
SOURCE_COMPONENT = 190


def main() -> int:
    print(f"Connecting to {ENDPOINT}...")

    connection = mavutil.mavlink_connection(
        ENDPOINT,
        source_system=SOURCE_SYSTEM,
        source_component=SOURCE_COMPONENT,
        autoreconnect=True,
    )

    deadline = time.monotonic() + TIMEOUT_S
    next_heartbeat = 0.0

    heartbeat_received = False
    position_received = False
    home_received = False

    system_id = None
    position = None
    status_messages: list[str] = []

    while time.monotonic() < deadline:
        now = time.monotonic()

        if now >= next_heartbeat:
            connection.mav.heartbeat_send(
                mavutil.mavlink.MAV_TYPE_GCS,
                mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                0,
                0,
                mavutil.mavlink.MAV_STATE_ACTIVE,
            )

            next_heartbeat = now + 1.0

        message = connection.recv_match(
            blocking=True,
            timeout=0.5,
        )

        if message is None:
            continue

        message_type = message.get_type()

        if message_type == "HEARTBEAT":
            source_system = int(
                message.get_srcSystem()
            )

            if source_system != SOURCE_SYSTEM:
                heartbeat_received = True
                system_id = source_system

        elif message_type == "GLOBAL_POSITION_INT":
            position_received = True

            position = {
                "latitude_deg":
                    float(message.lat) / 1e7,
                "longitude_deg":
                    float(message.lon) / 1e7,
                "absolute_altitude_m":
                    float(message.alt) / 1000.0,
                "relative_altitude_m":
                    float(message.relative_alt)
                    / 1000.0,
            }

        elif message_type == "HOME_POSITION":
            home_received = True

        elif message_type == "STATUSTEXT":
            text = message.text

            if isinstance(text, bytes):
                text = text.decode(
                    errors="replace"
                )

            text = str(text).rstrip("\x00")

            if text:
                status_messages.append(text)
                print(f"PX4: {text}")

        if (
            heartbeat_received
            and position_received
        ):
            break

    connection.close()

    print()
    print("===== VALIDATION =====")
    print(
        "Heartbeat:",
        "PASS" if heartbeat_received else "FAIL",
    )
    print(
        "PX4 system ID:",
        system_id,
    )
    print(
        "Global position:",
        "PASS" if position_received else "FAIL",
    )
    print(
        "Home position:",
        "PASS" if home_received else "NOT RECEIVED YET",
    )

    if position is not None:
        print("Position:", position)

    hard_failures = (
        "Battery unhealthy",
        "No valid data from Accel",
        "No valid data from Gyro",
        "barometer 0 missing",
        "ekf2 missing data",
        "Found 0 compass",
    )

    detected_failures = [
        message
        for message in status_messages
        if any(
            failure.lower() in message.lower()
            for failure in hard_failures
        )
    ]

    if detected_failures:
        print()
        print("Hard PX4 health failures detected:")

        for failure in detected_failures:
            print(f"  - {failure}")

        return 1

    if not heartbeat_received:
        return 1

    if not position_received:
        return 1

    print()
    print("========================================")
    print("SINGLE-DRONE FOUNDATION READY")
    print("========================================")

    return 0


if __name__ == "__main__":
    sys.exit(main())
