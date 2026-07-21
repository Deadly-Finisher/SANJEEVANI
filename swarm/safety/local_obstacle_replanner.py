#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import csv
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import yaml


class LocalObstacleReplanner:
    VALID_MODES = {
        "dry_run",
        "simulation_live",
    }

    def __init__(
        self,
        config_path: str | Path,
        drone_id: str,
    ) -> None:
        config = yaml.safe_load(
            Path(config_path).read_text()
        )

        replanner = config["replanner"]
        geometry = config["geometry"]

        self.drone_id = str(drone_id)
        self.mode = str(replanner["mode"])

        if self.mode not in self.VALID_MODES:
            raise RuntimeError(
                f"Unsupported replanner mode: {self.mode}"
            )

        self.environment = str(
            replanner.get(
                "environment",
                "simulation",
            )
        )
        self.allow_flight_commands = bool(
            replanner.get(
                "allow_flight_commands",
                False,
            )
        )
        self.required_safety_guard_mode = str(
            replanner.get(
                "required_safety_guard_mode",
                "dry_run",
            )
        )

        activation = replanner.get(
            "activation",
            {},
        )
        self.excluded_zone_names = {
            str(value)
            for value in activation.get(
                "excluded_zone_names",
                [],
            )
        }
        self.minimum_activation_altitude_m = float(
            activation.get(
                "minimum_altitude_m",
                0.0,
            )
        )

        self.poll_interval_s = float(
            replanner["poll_interval_s"]
        )
        self.decision_cooldown_s = float(
            replanner["decision_cooldown_s"]
        )
        self.maximum_attempts_per_waypoint = int(
            replanner[
                "maximum_attempts_per_waypoint"
            ]
        )
        self.trigger_states = {
            str(value)
            for value in replanner["trigger_states"]
        }
        self.minimum_side_clearance_m = float(
            replanner[
                "minimum_side_clearance_m"
            ]
        )
        self.side_preference_margin_m = float(
            replanner[
                "side_preference_margin_m"
            ]
        )

        temporary = replanner[
            "temporary_waypoint"
        ]

        self.forward_offset_m = float(
            temporary["forward_offset_m"]
        )
        self.lateral_offset_m = float(
            temporary["lateral_offset_m"]
        )
        self.altitude_offset_m = float(
            temporary["altitude_offset_m"]
        )
        self.minimum_temporary_altitude_m = float(
            temporary.get(
                "minimum_altitude_m",
                0.0,
            )
        )
        self.blocked_sides_action = str(
            replanner["blocked_sides_action"]
        )

        live = replanner.get(
            "live_execution",
            {},
        )

        self.hold_before_replan_s = float(
            live.get(
                "hold_before_replan_s",
                2.0,
            )
        )
        self.command_timeout_s = float(
            live.get(
                "command_timeout_s",
                12.0,
            )
        )
        self.command_retries = int(
            live.get(
                "command_retries",
                3,
            )
        )
        self.command_retry_delay_s = float(
            live.get(
                "command_retry_delay_s",
                2.0,
            )
        )
        self.temporary_arrival_timeout_s = float(
            live.get(
                "temporary_arrival_timeout_s",
                120.0,
            )
        )
        self.arrival_check_interval_s = float(
            live.get(
                "arrival_check_interval_s",
                0.5,
            )
        )
        self.horizontal_tolerance_m = float(
            live.get(
                "horizontal_tolerance_m",
                1.5,
            )
        )
        self.altitude_tolerance_m = float(
            live.get(
                "altitude_tolerance_m",
                1.0,
            )
        )
        self.clearance_verification_timeout_s = float(
            live.get(
                "clearance_verification_timeout_s",
                30.0,
            )
        )
        self.clearance_required_consecutive_checks = int(
            live.get(
                "clearance_required_consecutive_checks",
                2,
            )
        )
        self.resume_states = {
            str(value)
            for value in live.get(
                "resume_states",
                ["clear", "warning"],
            )
        }
        self.set_speed_before_replan = bool(
            live.get(
                "set_speed_before_replan",
                False,
            )
        )
        self.avoidance_speed_m_s = float(
            live.get(
                "avoidance_speed_m_s",
                0.15,
            )
        )
        self.resume_original_waypoint = bool(
            live.get(
                "resume_original_waypoint",
                True,
            )
        )

        self.earth_radius_m = float(
            geometry["earth_radius_m"]
        )
        self.minimum_target_vector_m = float(
            geometry["minimum_target_vector_m"]
        )

        log_template = str(
            replanner["event_log_csv"]
        )
        self.log_path = Path(
            log_template.format(
                drone_id=self.drone_id
            )
        )
        self.log_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        self._attempts_by_waypoint: dict[
            str,
            int,
        ] = {}
        self._last_decision_time = 0.0
        self._execution_lock = asyncio.Lock()
        self._initialize_log()

        print(
            f"[{self.drone_id}] local replanner "
            f"mode: {self.mode}"
        )
        print(
            f"[{self.drone_id}] local replanner "
            f"log: {self.log_path}"
        )

    def _initialize_log(self) -> None:
        if (
            self.log_path.exists()
            and self.log_path.stat().st_size
        ):
            return

        with self.log_path.open(
            "w",
            newline="",
        ) as file:
            csv.writer(file).writerow([
                "timestamp_utc",
                "drone_id",
                "waypoint_key",
                "zone_name",
                "attempt_number",
                "phase",
                "safety_state",
                "scan_age_s",
                "front_min_m",
                "left_min_m",
                "right_min_m",
                "selected_side",
                "temporary_north_m",
                "temporary_east_m",
                "temporary_altitude_m",
                "mode",
                "result",
                "reason",
                "command_error",
            ])

    @staticmethod
    def _number(
        value: Any,
    ) -> float | None:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None

        if not math.isfinite(number):
            return None

        return number

    def position_to_local(
        self,
        home_latitude_deg: float,
        home_longitude_deg: float,
        latitude_deg: float,
        longitude_deg: float,
    ) -> tuple[float, float]:
        north_m = (
            math.radians(
                latitude_deg
                - home_latitude_deg
            )
            * self.earth_radius_m
        )

        east_m = (
            math.radians(
                longitude_deg
                - home_longitude_deg
            )
            * self.earth_radius_m
            * math.cos(
                math.radians(
                    home_latitude_deg
                )
            )
        )

        return north_m, east_m

    def offset_lat_lon(
        self,
        latitude_deg: float,
        longitude_deg: float,
        north_m: float,
        east_m: float,
    ) -> tuple[float, float]:
        latitude_rad = math.radians(
            latitude_deg
        )

        new_latitude = (
            latitude_deg
            + math.degrees(
                north_m
                / self.earth_radius_m
            )
        )

        new_longitude = (
            longitude_deg
            + math.degrees(
                east_m
                / (
                    self.earth_radius_m
                    * max(
                        math.cos(latitude_rad),
                        0.000001,
                    )
                )
            )
        )

        return (
            new_latitude,
            new_longitude,
        )

    def _direction_to_target(
        self,
        current_north_m: float,
        current_east_m: float,
        target_north_m: float,
        target_east_m: float,
        yaw_deg: float,
    ) -> tuple[float, float]:
        delta_north = (
            target_north_m
            - current_north_m
        )
        delta_east = (
            target_east_m
            - current_east_m
        )
        norm = math.hypot(
            delta_north,
            delta_east,
        )

        if norm >= self.minimum_target_vector_m:
            return (
                delta_north / norm,
                delta_east / norm,
            )

        yaw_rad = math.radians(
            yaw_deg
        )

        return (
            math.cos(yaw_rad),
            math.sin(yaw_rad),
        )

    def choose_side(
        self,
        left_min_m: float | None,
        right_min_m: float | None,
    ) -> tuple[str | None, str]:
        left_clear = (
            left_min_m is not None
            and left_min_m
            >= self.minimum_side_clearance_m
        )
        right_clear = (
            right_min_m is not None
            and right_min_m
            >= self.minimum_side_clearance_m
        )

        if not left_clear and not right_clear:
            return (
                None,
                "both_sides_below_minimum_clearance",
            )

        if left_clear and not right_clear:
            return (
                "left",
                "left_is_only_clear_side",
            )

        if right_clear and not left_clear:
            return (
                "right",
                "right_is_only_clear_side",
            )

        assert left_min_m is not None
        assert right_min_m is not None

        difference = (
            left_min_m
            - right_min_m
        )

        if (
            abs(difference)
            < self.side_preference_margin_m
        ):
            return (
                "left",
                "clearances_similar_left_tie_break",
            )

        if difference > 0:
            return (
                "left",
                "left_has_greater_clearance",
            )

        return (
            "right",
            "right_has_greater_clearance",
        )

    def plan(
        self,
        *,
        current_north_m: float,
        current_east_m: float,
        current_altitude_m: float,
        target_north_m: float,
        target_east_m: float,
        yaw_deg: float,
        front_min_m: float | None,
        left_min_m: float | None,
        right_min_m: float | None,
        safety_state: str,
        target_altitude_m: float | None = None,
    ) -> dict[str, Any]:
        selected_side, reason = (
            self.choose_side(
                left_min_m,
                right_min_m,
            )
        )

        base = {
            "safety_state": str(safety_state),
            "front_min_m": self._number(
                front_min_m
            ),
            "left_min_m": self._number(
                left_min_m
            ),
            "right_min_m": self._number(
                right_min_m
            ),
            "selected_side": selected_side,
            "reason": reason,
        }

        if selected_side is None:
            return {
                **base,
                "can_replan": False,
                "result":
                    self.blocked_sides_action,
                "temporary_north_m": None,
                "temporary_east_m": None,
                "temporary_altitude_m": None,
            }

        forward_north, forward_east = (
            self._direction_to_target(
                current_north_m,
                current_east_m,
                target_north_m,
                target_east_m,
                yaw_deg,
            )
        )
        left_north = -forward_east
        left_east = forward_north
        side_sign = (
            1.0
            if selected_side == "left"
            else -1.0
        )

        temporary_north_m = (
            current_north_m
            + self.forward_offset_m
            * forward_north
            + side_sign
            * self.lateral_offset_m
            * left_north
        )
        temporary_east_m = (
            current_east_m
            + self.forward_offset_m
            * forward_east
            + side_sign
            * self.lateral_offset_m
            * left_east
        )

        return {
            **base,
            "can_replan": True,
            "result": "plan_created",
            "temporary_north_m":
                temporary_north_m,
            "temporary_east_m":
                temporary_east_m,
            "temporary_altitude_m": max(
                current_altitude_m
                + self.altitude_offset_m,
                self.minimum_temporary_altitude_m,
                (
                    float(target_altitude_m)
                    if target_altitude_m is not None
                    else 0.0
                ),
            ),
        }

    @staticmethod
    def _waypoint_key(
        waypoint: dict[str, Any],
    ) -> str:
        return (
            f"{waypoint.get('sequence_id', '')}:"
            f"{waypoint.get('zone_name', '')}"
        )

    def _record(
        self,
        *,
        waypoint: dict[str, Any],
        attempt_number: int,
        phase: str,
        scan_age_s: float | None,
        plan: dict[str, Any],
        result: str,
        reason: str,
        command_error: str | None = None,
    ) -> None:
        with self.log_path.open(
            "a",
            newline="",
        ) as file:
            csv.writer(file).writerow([
                datetime.now(
                    timezone.utc
                ).isoformat(),
                self.drone_id,
                self._waypoint_key(
                    waypoint
                ),
                waypoint.get(
                    "zone_name",
                    "",
                ),
                attempt_number,
                phase,
                plan.get(
                    "safety_state"
                ),
                scan_age_s,
                plan.get(
                    "front_min_m"
                ),
                plan.get(
                    "left_min_m"
                ),
                plan.get(
                    "right_min_m"
                ),
                plan.get(
                    "selected_side"
                ),
                plan.get(
                    "temporary_north_m"
                ),
                plan.get(
                    "temporary_east_m"
                ),
                plan.get(
                    "temporary_altitude_m"
                ),
                self.mode,
                result,
                reason,
                command_error,
            ])

        print(
            f"[{self.drone_id}] local replan | "
            f"phase={phase} | "
            f"waypoint="
            f"{waypoint.get('zone_name')} | "
            f"side="
            f"{plan.get('selected_side') or 'none'} | "
            f"result={result}"
        )

    async def _command_with_retry(
        self,
        label: str,
        operation: Callable[
            [],
            Awaitable[Any],
        ],
    ) -> str | None:
        last_error: str | None = None

        for attempt in range(
            1,
            self.command_retries + 1,
        ):
            try:
                await asyncio.wait_for(
                    operation(),
                    timeout=self.command_timeout_s,
                )
                return None
            except Exception as error:
                last_error = str(error)
                print(
                    f"[{self.drone_id}] "
                    f"{label} attempt "
                    f"{attempt}/"
                    f"{self.command_retries} "
                    f"not confirmed: {error}"
                )

                if (
                    attempt
                    < self.command_retries
                ):
                    await asyncio.sleep(
                        self.command_retry_delay_s
                    )

        return last_error

    async def _wait_for_local_arrival(
        self,
        *,
        mission_state: dict[str, Any],
        home_latitude_deg: float,
        home_longitude_deg: float,
        target_north_m: float,
        target_east_m: float,
        target_altitude_m: float,
    ) -> bool:
        start = time.monotonic()

        while (
            time.monotonic() - start
            <= self.temporary_arrival_timeout_s
        ):
            position = mission_state.get(
                "position"
            )

            if position is not None:
                current_north_m, current_east_m = (
                    self.position_to_local(
                        home_latitude_deg,
                        home_longitude_deg,
                        float(
                            position.latitude_deg
                        ),
                        float(
                            position.longitude_deg
                        ),
                    )
                )

                horizontal_error_m = (
                    math.hypot(
                        target_north_m
                        - current_north_m,
                        target_east_m
                        - current_east_m,
                    )
                )
                altitude_error_m = abs(
                    target_altitude_m
                    - float(
                        position.relative_altitude_m
                    )
                )

                print(
                    f"[{self.drone_id}] "
                    "avoidance target error: "
                    f"horizontal="
                    f"{horizontal_error_m:.2f} m, "
                    f"altitude="
                    f"{altitude_error_m:.2f} m"
                )

                if (
                    horizontal_error_m
                    <= self.horizontal_tolerance_m
                    and altitude_error_m
                    <= self.altitude_tolerance_m
                ):
                    return True

            await asyncio.sleep(
                self.arrival_check_interval_s
            )

        return False

    async def _wait_for_clearance(
        self,
        safety_guard: Any,
    ) -> tuple[
        bool,
        str,
        dict[str, Any],
        float | None,
    ]:
        start = time.monotonic()
        consecutive = 0
        latest_state = "no_data"
        latest_status: dict[str, Any] = {}
        latest_age: float | None = None

        while (
            time.monotonic() - start
            <= self.clearance_verification_timeout_s
        ):
            (
                latest_state,
                latest_status,
                latest_age,
            ) = safety_guard.snapshot()

            if latest_state in self.resume_states:
                consecutive += 1
            else:
                consecutive = 0

            if (
                consecutive
                >= self.clearance_required_consecutive_checks
            ):
                return (
                    True,
                    latest_state,
                    latest_status,
                    latest_age,
                )

            await asyncio.sleep(
                self.poll_interval_s
            )

        return (
            False,
            latest_state,
            latest_status,
            latest_age,
        )

    async def _execute_simulation_live(
        self,
        *,
        drone: Any,
        mission_state: dict[str, Any],
        safety_guard: Any,
        waypoint: dict[str, Any],
        attempt_number: int,
        scan_age_s: float | None,
        plan: dict[str, Any],
    ) -> None:
        if self.environment != "simulation":
            raise RuntimeError(
                "Live replanning commands are "
                "restricted to simulation"
            )

        if not self.allow_flight_commands:
            raise RuntimeError(
                "Simulation-live replanning is "
                "not explicitly enabled"
            )

        if (
            safety_guard.mode
            != self.required_safety_guard_mode
        ):
            raise RuntimeError(
                "Replanner requires safety guard "
                f"mode "
                f"{self.required_safety_guard_mode}, "
                f"received {safety_guard.mode}"
            )

        home_latitude_deg = float(
            mission_state[
                "home_latitude_deg"
            ]
        )
        home_longitude_deg = float(
            mission_state[
                "home_longitude_deg"
            ]
        )
        position = mission_state["position"]

        ground_absolute_altitude_m = (
            float(
                position.absolute_altitude_m
            )
            - float(
                position.relative_altitude_m
            )
        )
        temporary_altitude_m = float(
            plan[
                "temporary_altitude_m"
            ]
        )
        temporary_absolute_altitude_m = (
            ground_absolute_altitude_m
            + temporary_altitude_m
        )
        temporary_latitude_deg, temporary_longitude_deg = (
            self.offset_lat_lon(
                home_latitude_deg,
                home_longitude_deg,
                float(
                    plan[
                        "temporary_north_m"
                    ]
                ),
                float(
                    plan[
                        "temporary_east_m"
                    ]
                ),
            )
        )

        hold_error = await self._command_with_retry(
            "avoidance hold",
            lambda: drone.action.hold(),
        )

        await asyncio.sleep(
            self.hold_before_replan_s
        )

        speed_error = None

        if self.set_speed_before_replan:
            speed_error = await self._command_with_retry(
                "set avoidance speed",
                lambda: drone.action.set_current_speed(
                    self.avoidance_speed_m_s
                ),
            )

        temporary_goto_error = (
            await self._command_with_retry(
                "goto temporary avoidance waypoint",
                lambda: drone.action.goto_location(
                    temporary_latitude_deg,
                    temporary_longitude_deg,
                    temporary_absolute_altitude_m,
                    float(
                        waypoint["yaw_deg"]
                    ),
                ),
            )
        )

        self._record(
            waypoint=waypoint,
            attempt_number=attempt_number,
            phase="temporary_waypoint_commanded",
            scan_age_s=scan_age_s,
            plan=plan,
            result=(
                "command_sent_or_pose_verification_pending"
            ),
            reason=str(
                plan["reason"]
            ),
            command_error=(
                temporary_goto_error
                or speed_error
                or hold_error
            ),
        )

        arrived = await self._wait_for_local_arrival(
            mission_state=mission_state,
            home_latitude_deg=home_latitude_deg,
            home_longitude_deg=home_longitude_deg,
            target_north_m=float(
                plan["temporary_north_m"]
            ),
            target_east_m=float(
                plan["temporary_east_m"]
            ),
            target_altitude_m=temporary_altitude_m,
        )

        if not arrived:
            await self._command_with_retry(
                "hold after avoidance arrival timeout",
                lambda: drone.action.hold(),
            )

            self._record(
                waypoint=waypoint,
                attempt_number=attempt_number,
                phase="temporary_waypoint_arrival",
                scan_age_s=scan_age_s,
                plan=plan,
                result="temporary_waypoint_timeout",
                reason=(
                    "temporary_waypoint_not_reached"
                ),
                command_error=temporary_goto_error,
            )
            return

        (
            clearance_restored,
            clearance_state,
            clearance_status,
            clearance_age_s,
        ) = await self._wait_for_clearance(
            safety_guard
        )

        if not clearance_restored:
            await self._command_with_retry(
                "hold after clearance timeout",
                lambda: drone.action.hold(),
            )

            self._record(
                waypoint=waypoint,
                attempt_number=attempt_number,
                phase="clearance_verification",
                scan_age_s=clearance_age_s,
                plan={
                    **plan,
                    "safety_state":
                        clearance_state,
                    "front_min_m":
                        clearance_status.get(
                            "front_min_m"
                        ),
                    "left_min_m":
                        clearance_status.get(
                            "left_min_m"
                        ),
                    "right_min_m":
                        clearance_status.get(
                            "right_min_m"
                        ),
                },
                result="clearance_not_restored",
                reason=(
                    "resume_state_not_confirmed"
                ),
            )
            return

        if not self.resume_original_waypoint:
            self._record(
                waypoint=waypoint,
                attempt_number=attempt_number,
                phase="clearance_verification",
                scan_age_s=clearance_age_s,
                plan=plan,
                result=(
                    "temporary_waypoint_reached_"
                    "resume_disabled"
                ),
                reason=clearance_state,
            )
            return

        resume_error = await self._command_with_retry(
            "resume original waypoint",
            lambda: drone.action.goto_location(
                float(
                    waypoint[
                        "target_latitude_deg"
                    ]
                ),
                float(
                    waypoint[
                        "target_longitude_deg"
                    ]
                ),
                float(
                    waypoint[
                        "target_absolute_altitude_m"
                    ]
                ),
                float(
                    waypoint["yaw_deg"]
                ),
            ),
        )

        self._record(
            waypoint=waypoint,
            attempt_number=attempt_number,
            phase="resume_original_waypoint",
            scan_age_s=clearance_age_s,
            plan=plan,
            result=(
                "simulation_live_replan_"
                "executed_and_resumed"
            ),
            reason=clearance_state,
            command_error=resume_error,
        )

    async def observe_once(
        self,
        *,
        mission_state: dict[str, Any],
        safety_guard: Any,
        drone: Any,
    ) -> None:
        if not bool(
            mission_state.get(
                "replanner_enabled",
                False,
            )
        ):
            return

        waypoint = mission_state.get(
            "active_waypoint"
        )
        position = mission_state.get(
            "position"
        )
        home_latitude_deg = (
            mission_state.get(
                "home_latitude_deg"
            )
        )
        home_longitude_deg = (
            mission_state.get(
                "home_longitude_deg"
            )
        )

        if (
            waypoint is None
            or position is None
            or home_latitude_deg is None
            or home_longitude_deg is None
        ):
            return

        zone_name = str(
            waypoint.get(
                "zone_name",
                "",
            )
        )
        current_altitude_m = float(
            position.relative_altitude_m
        )

        if zone_name in self.excluded_zone_names:
            return

        if (
            current_altitude_m
            < self.minimum_activation_altitude_m
        ):
            return

        safety_state, status, scan_age_s = (
            safety_guard.snapshot()
        )

        if (
            safety_state
            not in self.trigger_states
        ):
            return

        if (
            time.monotonic()
            - self._last_decision_time
            < self.decision_cooldown_s
        ):
            return

        if self._execution_lock.locked():
            return

        waypoint_key = self._waypoint_key(
            waypoint
        )
        attempt_number = (
            self._attempts_by_waypoint.get(
                waypoint_key,
                0,
            )
            + 1
        )

        if (
            attempt_number
            > self.maximum_attempts_per_waypoint
        ):
            mission_state[
                "replanner_abort_reason"
            ] = (
                "maximum_replan_attempts_"
                "per_waypoint_exceeded"
            )
            return

        current_north_m, current_east_m = (
            self.position_to_local(
                float(home_latitude_deg),
                float(home_longitude_deg),
                float(
                    position.latitude_deg
                ),
                float(
                    position.longitude_deg
                ),
            )
        )

        plan = self.plan(
            current_north_m=current_north_m,
            current_east_m=current_east_m,
            current_altitude_m=float(
                position.relative_altitude_m
            ),
            target_north_m=float(
                waypoint["north_m"]
            ),
            target_east_m=float(
                waypoint["east_m"]
            ),
            yaw_deg=float(
                waypoint["yaw_deg"]
            ),
            front_min_m=self._number(
                status.get("front_min_m")
            ),
            left_min_m=self._number(
                status.get("left_min_m")
            ),
            right_min_m=self._number(
                status.get("right_min_m")
            ),
            safety_state=safety_state,
            target_altitude_m=float(
                waypoint["altitude_m"]
            ),
        )

        self._attempts_by_waypoint[
            waypoint_key
        ] = attempt_number
        self._last_decision_time = (
            time.monotonic()
        )

        if self.mode == "dry_run":
            plan["result"] = (
                "dry_run_plan_created"
                if plan["can_replan"]
                else (
                    "dry_run_"
                    f"{self.blocked_sides_action}"
                )
            )

            self._record(
                waypoint=waypoint,
                attempt_number=attempt_number,
                phase="decision",
                scan_age_s=scan_age_s,
                plan=plan,
                result=str(
                    plan["result"]
                ),
                reason=str(
                    plan["reason"]
                ),
            )
            return

        if not plan["can_replan"]:
            await self._command_with_retry(
                "hold because both sides are blocked",
                lambda: drone.action.hold(),
            )
            mission_state[
                "replanner_abort_reason"
            ] = (
                "both_sides_below_"
                "minimum_clearance"
            )

            self._record(
                waypoint=waypoint,
                attempt_number=attempt_number,
                phase="decision",
                scan_age_s=scan_age_s,
                plan=plan,
                result=(
                    "simulation_live_"
                    f"{self.blocked_sides_action}"
                ),
                reason=str(
                    plan["reason"]
                ),
            )
            return

        async with self._execution_lock:
            await self._execute_simulation_live(
                drone=drone,
                mission_state=mission_state,
                safety_guard=safety_guard,
                waypoint=waypoint,
                attempt_number=attempt_number,
                scan_age_s=scan_age_s,
                plan=plan,
            )

    async def run(
        self,
        *,
        mission_state: dict[str, Any],
        safety_guard: Any,
        stop_event: asyncio.Event,
        drone: Any,
    ) -> None:
        while not stop_event.is_set():
            await self.observe_once(
                mission_state=mission_state,
                safety_guard=safety_guard,
                drone=drone,
            )
            await asyncio.sleep(
                self.poll_interval_s
            )

    def close(self) -> None:
        return
