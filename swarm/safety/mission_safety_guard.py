#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import csv
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml


class MissionSafetyGuard:
    def __init__(self, config_path, drone_id):
        config = yaml.safe_load(Path(config_path).read_text())
        controller = config["controller"]

        self.drone_id = drone_id
        self.mode = str(controller["mode"])
        self.command_cooldown_s = float(
            controller["command_cooldown_s"]
        )
        self.status_timeout_s = float(
            controller["status_timeout_s"]
        )
        self.require_initial_status = bool(
            controller["require_initial_status"]
        )
        self.initial_status_timeout_s = float(
            controller["initial_status_timeout_s"]
        )
        self.poll_interval_s = float(
            controller["safety_poll_interval_s"]
        )
        self.normal_speed_m_s = float(
            controller["normal_speed_m_s"]
        )
        self.status_csv_path = Path(
            controller["obstacle_status_csv"]
        )
        self.actions = config["actions"]
        policy = config["policy"]

        self.allowed_takeoff_states = set(
            policy["allowed_takeoff_states"]
        )
        self.enforce_takeoff_gate_in_dry_run = bool(
            policy["enforce_takeoff_gate_in_dry_run"]
        )
        self.takeoff_wait_timeout_s = float(
            policy["takeoff_wait_timeout_s"]
        )
        self.takeoff_poll_interval_s = float(
            policy["takeoff_poll_interval_s"]
        )
        self.maximum_hold_duration_s = float(
            policy["maximum_hold_duration_s"]
        )
        self.resume_clear_delay_s = float(
            policy["resume_clear_delay_s"]
        )
        self.fail_on_hold_timeout = bool(
            policy["fail_on_hold_timeout"]
        )

        if not any(
            item["drone_id"] == drone_id
            for item in config["drones"]
        ):
            raise RuntimeError(
                f"No safety configuration for {drone_id}"
            )

        log_template = controller["mission_event_log_template"]
        self.log_path = Path(
            log_template.format(drone_id=drone_id)
        )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_log()

        self._last_state = None
        self._last_command_time = 0.0
        self._hold_active = False
        self._warning_active = False

        print(
            f"[{drone_id}] safety guard reading "
            f"{self.status_csv_path}"
        )
        print(f"[{drone_id}] safety mode: {self.mode}")

    def _initialize_log(self):
        if self.log_path.exists() and self.log_path.stat().st_size:
            return

        with self.log_path.open("w", newline="") as file:
            csv.writer(file).writerow([
                "timestamp_utc",
                "drone_id",
                "safety_state",
                "command",
                "front_min_m",
                "scan_age_s",
                "mode",
                "result",
            ])

    @staticmethod
    def _number(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _latest_row(self):
        if not self.status_csv_path.exists():
            return None

        latest = None

        try:
            with self.status_csv_path.open(newline="") as file:
                for row in csv.DictReader(file):
                    if row.get("drone_id") == self.drone_id:
                        latest = row
        except (OSError, csv.Error):
            return None

        return latest

    @staticmethod
    def _timestamp_age(timestamp_text):
        try:
            timestamp = datetime.fromisoformat(
                timestamp_text.replace("Z", "+00:00")
            )

            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)

            return max(
                0.0,
                (
                    datetime.now(timezone.utc)
                    - timestamp.astimezone(timezone.utc)
                ).total_seconds(),
            )
        except (AttributeError, TypeError, ValueError):
            return None

    def _snapshot(self):
        row = self._latest_row()

        if row is None:
            return "no_data", {}, None

        status = {
            "front_min_m": self._number(row.get("front_min_m")),
            "left_min_m": self._number(row.get("left_min_m")),
            "right_min_m": self._number(row.get("right_min_m")),
            "scan_age_s": self._number(row.get("scan_age_s")),
            "safety_state": row.get("safety_state", "no_data"),
        }

        row_age_s = self._timestamp_age(
            row.get("timestamp_utc")
        )

        ages = [
            value
            for value in (status["scan_age_s"], row_age_s)
            if value is not None
        ]

        effective_age_s = max(ages) if ages else None
        state = str(status["safety_state"])

        if (
            effective_age_s is None
            or effective_age_s > self.status_timeout_s
        ):
            state = "no_data"

        return state, status, effective_age_s

    def snapshot(self):
        state, status, age_s = self._snapshot()

        return (
            state,
            dict(status),
            age_s,
        )

    async def wait_for_initial_status(self):
        start = time.monotonic()

        while True:
            state, _, _ = self._snapshot()

            if state != "no_data":
                print(
                    f"[{self.drone_id}] initial safety "
                    f"status ready: {state}"
                )
                return

            if (
                time.monotonic() - start
                > self.initial_status_timeout_s
            ):
                if self.require_initial_status:
                    raise TimeoutError(
                        "Fresh obstacle status was not received"
                    )

                return

            await asyncio.sleep(self.poll_interval_s)

    async def wait_for_takeoff_clearance(self):
        start = time.monotonic()

        while True:
            state, status, age_s = self._snapshot()

            if state in self.allowed_takeoff_states:
                print(
                    f"[{self.drone_id}] takeoff safety "
                    f"clearance granted: {state}"
                )
                return state

            if (
                self.mode != "live"
                and not self.enforce_takeoff_gate_in_dry_run
            ):
                self._record(
                    state,
                    "takeoff_gate",
                    "dry_run_bypassed",
                    status,
                    age_s,
                )
                return state

            if (
                time.monotonic() - start
                > self.takeoff_wait_timeout_s
            ):
                raise TimeoutError(
                    f"Takeoff blocked by safety state: {state}"
                )

            await asyncio.sleep(
                self.takeoff_poll_interval_s
            )

    def _cooldown_complete(self):
        return (
            time.monotonic() - self._last_command_time
            >= self.command_cooldown_s
        )

    def _record(
        self,
        state,
        command,
        result,
        status=None,
        age_s=None,
    ):
        if status is None:
            _, status, age_s = self._snapshot()

        print(
            f"[{self.drone_id}] safety={state} | "
            f"command={command} | result={result}"
        )

        with self.log_path.open("a", newline="") as file:
            csv.writer(file).writerow([
                datetime.now(timezone.utc).isoformat(),
                self.drone_id,
                state,
                command,
                status.get("front_min_m"),
                age_s,
                self.mode,
                result,
            ])

    async def _set_speed(self, drone, speed, state):
        result = "dry_run_logged"

        if self.mode == "live":
            await drone.action.set_current_speed(float(speed))
            result = "command_sent"

        self._record(
            state,
            f"set_current_speed({speed})",
            result,
        )
        self._last_command_time = time.monotonic()

    async def _hold(self, drone, state):
        result = "dry_run_logged"

        if self.mode == "live":
            await drone.action.hold()
            result = "command_sent"

        self._record(state, "hold", result)
        self._last_command_time = time.monotonic()

    async def enforce(
        self,
        drone,
        mission_in_air,
        resume_command=None,
    ):
        state, status, age_s = self._snapshot()

        if self.mode != "live":
            if state != self._last_state:
                action = self.actions.get(
                    state,
                    self.actions["no_data"],
                )
                command = str(action["command"])

                if command == "set_current_speed":
                    command = (
                        f"set_current_speed("
                        f"{action['speed_m_s']})"
                    )

                self._record(
                    state,
                    command,
                    "dry_run_logged",
                    status,
                    age_s,
                )
                self._last_state = state

            return state

        if not mission_in_air:
            self._last_state = state
            return state

        if state == "clear":
            if self._hold_active or self._warning_active:
                await self._set_speed(
                    drone,
                    self.normal_speed_m_s,
                    state,
                )

            if self._hold_active and resume_command is not None:
                await resume_command()
                self._record(
                    state,
                    "resume_waypoint",
                    "command_sent",
                    status,
                    age_s,
                )

            self._hold_active = False
            self._warning_active = False
            self._last_state = state
            return state

        if state == "warning":
            warning_speed = float(
                self.actions["warning"]["speed_m_s"]
            )

            if (
                not self._warning_active
                or self._cooldown_complete()
            ):
                await self._set_speed(
                    drone,
                    warning_speed,
                    state,
                )

            self._warning_active = True
            self._last_state = state
            return state

        if state in {
            "critical",
            "emergency_stop",
            "no_data",
        }:
            if (
                not self._hold_active
                or self._cooldown_complete()
            ):
                await self._hold(drone, state)

            self._hold_active = True
            self._last_state = state
            hold_started = time.monotonic()

            while True:
                await asyncio.sleep(self.poll_interval_s)

                if (
                    time.monotonic() - hold_started
                    > self.maximum_hold_duration_s
                ):
                    self._record(
                        state,
                        "hold_timeout",
                        "maximum_hold_duration_exceeded",
                        status,
                        age_s,
                    )

                    if self.fail_on_hold_timeout:
                        raise TimeoutError(
                            "Maximum safety hold duration exceeded"
                        )

                    return state

                next_state, next_status, next_age = (
                    self._snapshot()
                )

                if next_state not in {"clear", "warning"}:
                    continue

                if self.resume_clear_delay_s > 0:
                    await asyncio.sleep(
                        self.resume_clear_delay_s
                    )

                    next_state, next_status, next_age = (
                        self._snapshot()
                    )

                    if next_state not in {"clear", "warning"}:
                        continue

                speed = self.normal_speed_m_s

                if next_state == "warning":
                    speed = float(
                        self.actions["warning"]["speed_m_s"]
                    )

                await self._set_speed(
                    drone,
                    speed,
                    next_state,
                )

                if resume_command is not None:
                    await resume_command()
                    self._record(
                        next_state,
                        "resume_waypoint",
                        "command_sent",
                        next_status,
                        next_age,
                    )

                self._hold_active = False
                self._warning_active = (
                    next_state == "warning"
                )
                self._last_state = next_state
                return next_state

        return state

    def close(self):
        return
