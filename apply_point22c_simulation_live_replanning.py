#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path


PROJECT_ROOT = Path.home() / "Programs" / "SWARM_DRONES"
BACKUP_DIR = (
    PROJECT_ROOT
    / "backups"
    / "point22c_simulation_live_replanning"
)

MODULE_PATH = (
    PROJECT_ROOT
    / "swarm"
    / "safety"
    / "local_obstacle_replanner.py"
)
LIVE_CONFIG_PATH = (
    PROJECT_ROOT
    / "configs"
    / "safety"
    / "v1_swarm_local_replanner_simulation_live.yaml"
)
RUNNER_PATH = (
    PROJECT_ROOT
    / "simulation"
    / "scripts"
    / "run_one_swarm_drone_mission.py"
)

MODULE_TEXT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport asyncio\nimport csv\nimport math\nimport time\nfrom datetime import datetime, timezone\nfrom pathlib import Path\nfrom typing import Any, Awaitable, Callable\n\nimport yaml\n\n\nclass LocalObstacleReplanner:\n    VALID_MODES = {\n        "dry_run",\n        "simulation_live",\n    }\n\n    def __init__(\n        self,\n        config_path: str | Path,\n        drone_id: str,\n    ) -> None:\n        config = yaml.safe_load(\n            Path(config_path).read_text()\n        )\n\n        replanner = config["replanner"]\n        geometry = config["geometry"]\n\n        self.drone_id = str(drone_id)\n        self.mode = str(replanner["mode"])\n\n        if self.mode not in self.VALID_MODES:\n            raise RuntimeError(\n                f"Unsupported replanner mode: {self.mode}"\n            )\n\n        self.environment = str(\n            replanner.get(\n                "environment",\n                "simulation",\n            )\n        )\n        self.allow_flight_commands = bool(\n            replanner.get(\n                "allow_flight_commands",\n                False,\n            )\n        )\n        self.required_safety_guard_mode = str(\n            replanner.get(\n                "required_safety_guard_mode",\n                "dry_run",\n            )\n        )\n\n        self.poll_interval_s = float(\n            replanner["poll_interval_s"]\n        )\n        self.decision_cooldown_s = float(\n            replanner["decision_cooldown_s"]\n        )\n        self.maximum_attempts_per_waypoint = int(\n            replanner[\n                "maximum_attempts_per_waypoint"\n            ]\n        )\n        self.trigger_states = {\n            str(value)\n            for value in replanner["trigger_states"]\n        }\n        self.minimum_side_clearance_m = float(\n            replanner[\n                "minimum_side_clearance_m"\n            ]\n        )\n        self.side_preference_margin_m = float(\n            replanner[\n                "side_preference_margin_m"\n            ]\n        )\n\n        temporary = replanner[\n            "temporary_waypoint"\n        ]\n\n        self.forward_offset_m = float(\n            temporary["forward_offset_m"]\n        )\n        self.lateral_offset_m = float(\n            temporary["lateral_offset_m"]\n        )\n        self.altitude_offset_m = float(\n            temporary["altitude_offset_m"]\n        )\n        self.blocked_sides_action = str(\n            replanner["blocked_sides_action"]\n        )\n\n        live = replanner.get(\n            "live_execution",\n            {},\n        )\n\n        self.hold_before_replan_s = float(\n            live.get(\n                "hold_before_replan_s",\n                2.0,\n            )\n        )\n        self.command_timeout_s = float(\n            live.get(\n                "command_timeout_s",\n                12.0,\n            )\n        )\n        self.command_retries = int(\n            live.get(\n                "command_retries",\n                3,\n            )\n        )\n        self.command_retry_delay_s = float(\n            live.get(\n                "command_retry_delay_s",\n                2.0,\n            )\n        )\n        self.temporary_arrival_timeout_s = float(\n            live.get(\n                "temporary_arrival_timeout_s",\n                120.0,\n            )\n        )\n        self.arrival_check_interval_s = float(\n            live.get(\n                "arrival_check_interval_s",\n                0.5,\n            )\n        )\n        self.horizontal_tolerance_m = float(\n            live.get(\n                "horizontal_tolerance_m",\n                1.5,\n            )\n        )\n        self.altitude_tolerance_m = float(\n            live.get(\n                "altitude_tolerance_m",\n                1.0,\n            )\n        )\n        self.clearance_verification_timeout_s = float(\n            live.get(\n                "clearance_verification_timeout_s",\n                30.0,\n            )\n        )\n        self.clearance_required_consecutive_checks = int(\n            live.get(\n                "clearance_required_consecutive_checks",\n                2,\n            )\n        )\n        self.resume_states = {\n            str(value)\n            for value in live.get(\n                "resume_states",\n                ["clear", "warning"],\n            )\n        }\n        self.avoidance_speed_m_s = float(\n            live.get(\n                "avoidance_speed_m_s",\n                0.15,\n            )\n        )\n        self.resume_original_waypoint = bool(\n            live.get(\n                "resume_original_waypoint",\n                True,\n            )\n        )\n\n        self.earth_radius_m = float(\n            geometry["earth_radius_m"]\n        )\n        self.minimum_target_vector_m = float(\n            geometry["minimum_target_vector_m"]\n        )\n\n        log_template = str(\n            replanner["event_log_csv"]\n        )\n        self.log_path = Path(\n            log_template.format(\n                drone_id=self.drone_id\n            )\n        )\n        self.log_path.parent.mkdir(\n            parents=True,\n            exist_ok=True,\n        )\n\n        self._attempts_by_waypoint: dict[\n            str,\n            int,\n        ] = {}\n        self._last_decision_time = 0.0\n        self._execution_lock = asyncio.Lock()\n        self._initialize_log()\n\n        print(\n            f"[{self.drone_id}] local replanner "\n            f"mode: {self.mode}"\n        )\n        print(\n            f"[{self.drone_id}] local replanner "\n            f"log: {self.log_path}"\n        )\n\n    def _initialize_log(self) -> None:\n        if (\n            self.log_path.exists()\n            and self.log_path.stat().st_size\n        ):\n            return\n\n        with self.log_path.open(\n            "w",\n            newline="",\n        ) as file:\n            csv.writer(file).writerow([\n                "timestamp_utc",\n                "drone_id",\n                "waypoint_key",\n                "zone_name",\n                "attempt_number",\n                "phase",\n                "safety_state",\n                "scan_age_s",\n                "front_min_m",\n                "left_min_m",\n                "right_min_m",\n                "selected_side",\n                "temporary_north_m",\n                "temporary_east_m",\n                "temporary_altitude_m",\n                "mode",\n                "result",\n                "reason",\n                "command_error",\n            ])\n\n    @staticmethod\n    def _number(\n        value: Any,\n    ) -> float | None:\n        try:\n            number = float(value)\n        except (TypeError, ValueError):\n            return None\n\n        if not math.isfinite(number):\n            return None\n\n        return number\n\n    def position_to_local(\n        self,\n        home_latitude_deg: float,\n        home_longitude_deg: float,\n        latitude_deg: float,\n        longitude_deg: float,\n    ) -> tuple[float, float]:\n        north_m = (\n            math.radians(\n                latitude_deg\n                - home_latitude_deg\n            )\n            * self.earth_radius_m\n        )\n\n        east_m = (\n            math.radians(\n                longitude_deg\n                - home_longitude_deg\n            )\n            * self.earth_radius_m\n            * math.cos(\n                math.radians(\n                    home_latitude_deg\n                )\n            )\n        )\n\n        return north_m, east_m\n\n    def offset_lat_lon(\n        self,\n        latitude_deg: float,\n        longitude_deg: float,\n        north_m: float,\n        east_m: float,\n    ) -> tuple[float, float]:\n        latitude_rad = math.radians(\n            latitude_deg\n        )\n\n        new_latitude = (\n            latitude_deg\n            + math.degrees(\n                north_m\n                / self.earth_radius_m\n            )\n        )\n\n        new_longitude = (\n            longitude_deg\n            + math.degrees(\n                east_m\n                / (\n                    self.earth_radius_m\n                    * max(\n                        math.cos(latitude_rad),\n                        0.000001,\n                    )\n                )\n            )\n        )\n\n        return (\n            new_latitude,\n            new_longitude,\n        )\n\n    def _direction_to_target(\n        self,\n        current_north_m: float,\n        current_east_m: float,\n        target_north_m: float,\n        target_east_m: float,\n        yaw_deg: float,\n    ) -> tuple[float, float]:\n        delta_north = (\n            target_north_m\n            - current_north_m\n        )\n        delta_east = (\n            target_east_m\n            - current_east_m\n        )\n        norm = math.hypot(\n            delta_north,\n            delta_east,\n        )\n\n        if norm >= self.minimum_target_vector_m:\n            return (\n                delta_north / norm,\n                delta_east / norm,\n            )\n\n        yaw_rad = math.radians(\n            yaw_deg\n        )\n\n        return (\n            math.cos(yaw_rad),\n            math.sin(yaw_rad),\n        )\n\n    def choose_side(\n        self,\n        left_min_m: float | None,\n        right_min_m: float | None,\n    ) -> tuple[str | None, str]:\n        left_clear = (\n            left_min_m is not None\n            and left_min_m\n            >= self.minimum_side_clearance_m\n        )\n        right_clear = (\n            right_min_m is not None\n            and right_min_m\n            >= self.minimum_side_clearance_m\n        )\n\n        if not left_clear and not right_clear:\n            return (\n                None,\n                "both_sides_below_minimum_clearance",\n            )\n\n        if left_clear and not right_clear:\n            return (\n                "left",\n                "left_is_only_clear_side",\n            )\n\n        if right_clear and not left_clear:\n            return (\n                "right",\n                "right_is_only_clear_side",\n            )\n\n        assert left_min_m is not None\n        assert right_min_m is not None\n\n        difference = (\n            left_min_m\n            - right_min_m\n        )\n\n        if (\n            abs(difference)\n            < self.side_preference_margin_m\n        ):\n            return (\n                "left",\n                "clearances_similar_left_tie_break",\n            )\n\n        if difference > 0:\n            return (\n                "left",\n                "left_has_greater_clearance",\n            )\n\n        return (\n            "right",\n            "right_has_greater_clearance",\n        )\n\n    def plan(\n        self,\n        *,\n        current_north_m: float,\n        current_east_m: float,\n        current_altitude_m: float,\n        target_north_m: float,\n        target_east_m: float,\n        yaw_deg: float,\n        front_min_m: float | None,\n        left_min_m: float | None,\n        right_min_m: float | None,\n        safety_state: str,\n    ) -> dict[str, Any]:\n        selected_side, reason = (\n            self.choose_side(\n                left_min_m,\n                right_min_m,\n            )\n        )\n\n        base = {\n            "safety_state": str(safety_state),\n            "front_min_m": self._number(\n                front_min_m\n            ),\n            "left_min_m": self._number(\n                left_min_m\n            ),\n            "right_min_m": self._number(\n                right_min_m\n            ),\n            "selected_side": selected_side,\n            "reason": reason,\n        }\n\n        if selected_side is None:\n            return {\n                **base,\n                "can_replan": False,\n                "result":\n                    self.blocked_sides_action,\n                "temporary_north_m": None,\n                "temporary_east_m": None,\n                "temporary_altitude_m": None,\n            }\n\n        forward_north, forward_east = (\n            self._direction_to_target(\n                current_north_m,\n                current_east_m,\n                target_north_m,\n                target_east_m,\n                yaw_deg,\n            )\n        )\n        left_north = -forward_east\n        left_east = forward_north\n        side_sign = (\n            1.0\n            if selected_side == "left"\n            else -1.0\n        )\n\n        temporary_north_m = (\n            current_north_m\n            + self.forward_offset_m\n            * forward_north\n            + side_sign\n            * self.lateral_offset_m\n            * left_north\n        )\n        temporary_east_m = (\n            current_east_m\n            + self.forward_offset_m\n            * forward_east\n            + side_sign\n            * self.lateral_offset_m\n            * left_east\n        )\n\n        return {\n            **base,\n            "can_replan": True,\n            "result": "plan_created",\n            "temporary_north_m":\n                temporary_north_m,\n            "temporary_east_m":\n                temporary_east_m,\n            "temporary_altitude_m": (\n                current_altitude_m\n                + self.altitude_offset_m\n            ),\n        }\n\n    @staticmethod\n    def _waypoint_key(\n        waypoint: dict[str, Any],\n    ) -> str:\n        return (\n            f"{waypoint.get(\'sequence_id\', \'\')}:"\n            f"{waypoint.get(\'zone_name\', \'\')}"\n        )\n\n    def _record(\n        self,\n        *,\n        waypoint: dict[str, Any],\n        attempt_number: int,\n        phase: str,\n        scan_age_s: float | None,\n        plan: dict[str, Any],\n        result: str,\n        reason: str,\n        command_error: str | None = None,\n    ) -> None:\n        with self.log_path.open(\n            "a",\n            newline="",\n        ) as file:\n            csv.writer(file).writerow([\n                datetime.now(\n                    timezone.utc\n                ).isoformat(),\n                self.drone_id,\n                self._waypoint_key(\n                    waypoint\n                ),\n                waypoint.get(\n                    "zone_name",\n                    "",\n                ),\n                attempt_number,\n                phase,\n                plan.get(\n                    "safety_state"\n                ),\n                scan_age_s,\n                plan.get(\n                    "front_min_m"\n                ),\n                plan.get(\n                    "left_min_m"\n                ),\n                plan.get(\n                    "right_min_m"\n                ),\n                plan.get(\n                    "selected_side"\n                ),\n                plan.get(\n                    "temporary_north_m"\n                ),\n                plan.get(\n                    "temporary_east_m"\n                ),\n                plan.get(\n                    "temporary_altitude_m"\n                ),\n                self.mode,\n                result,\n                reason,\n                command_error,\n            ])\n\n        print(\n            f"[{self.drone_id}] local replan | "\n            f"phase={phase} | "\n            f"waypoint="\n            f"{waypoint.get(\'zone_name\')} | "\n            f"side="\n            f"{plan.get(\'selected_side\') or \'none\'} | "\n            f"result={result}"\n        )\n\n    async def _command_with_retry(\n        self,\n        label: str,\n        operation: Callable[\n            [],\n            Awaitable[Any],\n        ],\n    ) -> str | None:\n        last_error: str | None = None\n\n        for attempt in range(\n            1,\n            self.command_retries + 1,\n        ):\n            try:\n                await asyncio.wait_for(\n                    operation(),\n                    timeout=self.command_timeout_s,\n                )\n                return None\n            except Exception as error:\n                last_error = str(error)\n                print(\n                    f"[{self.drone_id}] "\n                    f"{label} attempt "\n                    f"{attempt}/"\n                    f"{self.command_retries} "\n                    f"not confirmed: {error}"\n                )\n\n                if (\n                    attempt\n                    < self.command_retries\n                ):\n                    await asyncio.sleep(\n                        self.command_retry_delay_s\n                    )\n\n        return last_error\n\n    async def _wait_for_local_arrival(\n        self,\n        *,\n        mission_state: dict[str, Any],\n        home_latitude_deg: float,\n        home_longitude_deg: float,\n        target_north_m: float,\n        target_east_m: float,\n        target_altitude_m: float,\n    ) -> bool:\n        start = time.monotonic()\n\n        while (\n            time.monotonic() - start\n            <= self.temporary_arrival_timeout_s\n        ):\n            position = mission_state.get(\n                "position"\n            )\n\n            if position is not None:\n                current_north_m, current_east_m = (\n                    self.position_to_local(\n                        home_latitude_deg,\n                        home_longitude_deg,\n                        float(\n                            position.latitude_deg\n                        ),\n                        float(\n                            position.longitude_deg\n                        ),\n                    )\n                )\n\n                horizontal_error_m = (\n                    math.hypot(\n                        target_north_m\n                        - current_north_m,\n                        target_east_m\n                        - current_east_m,\n                    )\n                )\n                altitude_error_m = abs(\n                    target_altitude_m\n                    - float(\n                        position.relative_altitude_m\n                    )\n                )\n\n                print(\n                    f"[{self.drone_id}] "\n                    "avoidance target error: "\n                    f"horizontal="\n                    f"{horizontal_error_m:.2f} m, "\n                    f"altitude="\n                    f"{altitude_error_m:.2f} m"\n                )\n\n                if (\n                    horizontal_error_m\n                    <= self.horizontal_tolerance_m\n                    and altitude_error_m\n                    <= self.altitude_tolerance_m\n                ):\n                    return True\n\n            await asyncio.sleep(\n                self.arrival_check_interval_s\n            )\n\n        return False\n\n    async def _wait_for_clearance(\n        self,\n        safety_guard: Any,\n    ) -> tuple[\n        bool,\n        str,\n        dict[str, Any],\n        float | None,\n    ]:\n        start = time.monotonic()\n        consecutive = 0\n        latest_state = "no_data"\n        latest_status: dict[str, Any] = {}\n        latest_age: float | None = None\n\n        while (\n            time.monotonic() - start\n            <= self.clearance_verification_timeout_s\n        ):\n            (\n                latest_state,\n                latest_status,\n                latest_age,\n            ) = safety_guard.snapshot()\n\n            if latest_state in self.resume_states:\n                consecutive += 1\n            else:\n                consecutive = 0\n\n            if (\n                consecutive\n                >= self.clearance_required_consecutive_checks\n            ):\n                return (\n                    True,\n                    latest_state,\n                    latest_status,\n                    latest_age,\n                )\n\n            await asyncio.sleep(\n                self.poll_interval_s\n            )\n\n        return (\n            False,\n            latest_state,\n            latest_status,\n            latest_age,\n        )\n\n    async def _execute_simulation_live(\n        self,\n        *,\n        drone: Any,\n        mission_state: dict[str, Any],\n        safety_guard: Any,\n        waypoint: dict[str, Any],\n        attempt_number: int,\n        scan_age_s: float | None,\n        plan: dict[str, Any],\n    ) -> None:\n        if self.environment != "simulation":\n            raise RuntimeError(\n                "Live replanning commands are "\n                "restricted to simulation"\n            )\n\n        if not self.allow_flight_commands:\n            raise RuntimeError(\n                "Simulation-live replanning is "\n                "not explicitly enabled"\n            )\n\n        if (\n            safety_guard.mode\n            != self.required_safety_guard_mode\n        ):\n            raise RuntimeError(\n                "Replanner requires safety guard "\n                f"mode "\n                f"{self.required_safety_guard_mode}, "\n                f"received {safety_guard.mode}"\n            )\n\n        home_latitude_deg = float(\n            mission_state[\n                "home_latitude_deg"\n            ]\n        )\n        home_longitude_deg = float(\n            mission_state[\n                "home_longitude_deg"\n            ]\n        )\n        position = mission_state["position"]\n\n        ground_absolute_altitude_m = (\n            float(\n                position.absolute_altitude_m\n            )\n            - float(\n                position.relative_altitude_m\n            )\n        )\n        temporary_altitude_m = float(\n            plan[\n                "temporary_altitude_m"\n            ]\n        )\n        temporary_absolute_altitude_m = (\n            ground_absolute_altitude_m\n            + temporary_altitude_m\n        )\n        temporary_latitude_deg, temporary_longitude_deg = (\n            self.offset_lat_lon(\n                home_latitude_deg,\n                home_longitude_deg,\n                float(\n                    plan[\n                        "temporary_north_m"\n                    ]\n                ),\n                float(\n                    plan[\n                        "temporary_east_m"\n                    ]\n                ),\n            )\n        )\n\n        hold_error = await self._command_with_retry(\n            "avoidance hold",\n            lambda: drone.action.hold(),\n        )\n\n        await asyncio.sleep(\n            self.hold_before_replan_s\n        )\n\n        speed_error = await self._command_with_retry(\n            "set avoidance speed",\n            lambda: drone.action.set_current_speed(\n                self.avoidance_speed_m_s\n            ),\n        )\n\n        temporary_goto_error = (\n            await self._command_with_retry(\n                "goto temporary avoidance waypoint",\n                lambda: drone.action.goto_location(\n                    temporary_latitude_deg,\n                    temporary_longitude_deg,\n                    temporary_absolute_altitude_m,\n                    float(\n                        waypoint["yaw_deg"]\n                    ),\n                ),\n            )\n        )\n\n        self._record(\n            waypoint=waypoint,\n            attempt_number=attempt_number,\n            phase="temporary_waypoint_commanded",\n            scan_age_s=scan_age_s,\n            plan=plan,\n            result=(\n                "command_sent_or_pose_verification_pending"\n            ),\n            reason=str(\n                plan["reason"]\n            ),\n            command_error=(\n                temporary_goto_error\n                or speed_error\n                or hold_error\n            ),\n        )\n\n        arrived = await self._wait_for_local_arrival(\n            mission_state=mission_state,\n            home_latitude_deg=home_latitude_deg,\n            home_longitude_deg=home_longitude_deg,\n            target_north_m=float(\n                plan["temporary_north_m"]\n            ),\n            target_east_m=float(\n                plan["temporary_east_m"]\n            ),\n            target_altitude_m=temporary_altitude_m,\n        )\n\n        if not arrived:\n            await self._command_with_retry(\n                "hold after avoidance arrival timeout",\n                lambda: drone.action.hold(),\n            )\n\n            self._record(\n                waypoint=waypoint,\n                attempt_number=attempt_number,\n                phase="temporary_waypoint_arrival",\n                scan_age_s=scan_age_s,\n                plan=plan,\n                result="temporary_waypoint_timeout",\n                reason=(\n                    "temporary_waypoint_not_reached"\n                ),\n                command_error=temporary_goto_error,\n            )\n            return\n\n        (\n            clearance_restored,\n            clearance_state,\n            clearance_status,\n            clearance_age_s,\n        ) = await self._wait_for_clearance(\n            safety_guard\n        )\n\n        if not clearance_restored:\n            await self._command_with_retry(\n                "hold after clearance timeout",\n                lambda: drone.action.hold(),\n            )\n\n            self._record(\n                waypoint=waypoint,\n                attempt_number=attempt_number,\n                phase="clearance_verification",\n                scan_age_s=clearance_age_s,\n                plan={\n                    **plan,\n                    "safety_state":\n                        clearance_state,\n                    "front_min_m":\n                        clearance_status.get(\n                            "front_min_m"\n                        ),\n                    "left_min_m":\n                        clearance_status.get(\n                            "left_min_m"\n                        ),\n                    "right_min_m":\n                        clearance_status.get(\n                            "right_min_m"\n                        ),\n                },\n                result="clearance_not_restored",\n                reason=(\n                    "resume_state_not_confirmed"\n                ),\n            )\n            return\n\n        if not self.resume_original_waypoint:\n            self._record(\n                waypoint=waypoint,\n                attempt_number=attempt_number,\n                phase="clearance_verification",\n                scan_age_s=clearance_age_s,\n                plan=plan,\n                result=(\n                    "temporary_waypoint_reached_"\n                    "resume_disabled"\n                ),\n                reason=clearance_state,\n            )\n            return\n\n        resume_error = await self._command_with_retry(\n            "resume original waypoint",\n            lambda: drone.action.goto_location(\n                float(\n                    waypoint[\n                        "target_latitude_deg"\n                    ]\n                ),\n                float(\n                    waypoint[\n                        "target_longitude_deg"\n                    ]\n                ),\n                float(\n                    waypoint[\n                        "target_absolute_altitude_m"\n                    ]\n                ),\n                float(\n                    waypoint["yaw_deg"]\n                ),\n            ),\n        )\n\n        self._record(\n            waypoint=waypoint,\n            attempt_number=attempt_number,\n            phase="resume_original_waypoint",\n            scan_age_s=clearance_age_s,\n            plan=plan,\n            result=(\n                "simulation_live_replan_"\n                "executed_and_resumed"\n            ),\n            reason=clearance_state,\n            command_error=resume_error,\n        )\n\n    async def observe_once(\n        self,\n        *,\n        mission_state: dict[str, Any],\n        safety_guard: Any,\n        drone: Any,\n    ) -> None:\n        if not bool(\n            mission_state.get(\n                "replanner_enabled",\n                False,\n            )\n        ):\n            return\n\n        waypoint = mission_state.get(\n            "active_waypoint"\n        )\n        position = mission_state.get(\n            "position"\n        )\n        home_latitude_deg = (\n            mission_state.get(\n                "home_latitude_deg"\n            )\n        )\n        home_longitude_deg = (\n            mission_state.get(\n                "home_longitude_deg"\n            )\n        )\n\n        if (\n            waypoint is None\n            or position is None\n            or home_latitude_deg is None\n            or home_longitude_deg is None\n        ):\n            return\n\n        safety_state, status, scan_age_s = (\n            safety_guard.snapshot()\n        )\n\n        if (\n            safety_state\n            not in self.trigger_states\n        ):\n            return\n\n        if (\n            time.monotonic()\n            - self._last_decision_time\n            < self.decision_cooldown_s\n        ):\n            return\n\n        if self._execution_lock.locked():\n            return\n\n        waypoint_key = self._waypoint_key(\n            waypoint\n        )\n        attempt_number = (\n            self._attempts_by_waypoint.get(\n                waypoint_key,\n                0,\n            )\n            + 1\n        )\n\n        if (\n            attempt_number\n            > self.maximum_attempts_per_waypoint\n        ):\n            mission_state[\n                "replanner_abort_reason"\n            ] = (\n                "maximum_replan_attempts_"\n                "per_waypoint_exceeded"\n            )\n            return\n\n        current_north_m, current_east_m = (\n            self.position_to_local(\n                float(home_latitude_deg),\n                float(home_longitude_deg),\n                float(\n                    position.latitude_deg\n                ),\n                float(\n                    position.longitude_deg\n                ),\n            )\n        )\n\n        plan = self.plan(\n            current_north_m=current_north_m,\n            current_east_m=current_east_m,\n            current_altitude_m=float(\n                position.relative_altitude_m\n            ),\n            target_north_m=float(\n                waypoint["north_m"]\n            ),\n            target_east_m=float(\n                waypoint["east_m"]\n            ),\n            yaw_deg=float(\n                waypoint["yaw_deg"]\n            ),\n            front_min_m=self._number(\n                status.get("front_min_m")\n            ),\n            left_min_m=self._number(\n                status.get("left_min_m")\n            ),\n            right_min_m=self._number(\n                status.get("right_min_m")\n            ),\n            safety_state=safety_state,\n        )\n\n        self._attempts_by_waypoint[\n            waypoint_key\n        ] = attempt_number\n        self._last_decision_time = (\n            time.monotonic()\n        )\n\n        if self.mode == "dry_run":\n            plan["result"] = (\n                "dry_run_plan_created"\n                if plan["can_replan"]\n                else (\n                    "dry_run_"\n                    f"{self.blocked_sides_action}"\n                )\n            )\n\n            self._record(\n                waypoint=waypoint,\n                attempt_number=attempt_number,\n                phase="decision",\n                scan_age_s=scan_age_s,\n                plan=plan,\n                result=str(\n                    plan["result"]\n                ),\n                reason=str(\n                    plan["reason"]\n                ),\n            )\n            return\n\n        if not plan["can_replan"]:\n            await self._command_with_retry(\n                "hold because both sides are blocked",\n                lambda: drone.action.hold(),\n            )\n            mission_state[\n                "replanner_abort_reason"\n            ] = (\n                "both_sides_below_"\n                "minimum_clearance"\n            )\n\n            self._record(\n                waypoint=waypoint,\n                attempt_number=attempt_number,\n                phase="decision",\n                scan_age_s=scan_age_s,\n                plan=plan,\n                result=(\n                    "simulation_live_"\n                    f"{self.blocked_sides_action}"\n                ),\n                reason=str(\n                    plan["reason"]\n                ),\n            )\n            return\n\n        async with self._execution_lock:\n            await self._execute_simulation_live(\n                drone=drone,\n                mission_state=mission_state,\n                safety_guard=safety_guard,\n                waypoint=waypoint,\n                attempt_number=attempt_number,\n                scan_age_s=scan_age_s,\n                plan=plan,\n            )\n\n    async def run(\n        self,\n        *,\n        mission_state: dict[str, Any],\n        safety_guard: Any,\n        stop_event: asyncio.Event,\n        drone: Any,\n    ) -> None:\n        while not stop_event.is_set():\n            await self.observe_once(\n                mission_state=mission_state,\n                safety_guard=safety_guard,\n                drone=drone,\n            )\n            await asyncio.sleep(\n                self.poll_interval_s\n            )\n\n    def close(self) -> None:\n        return\n'
LIVE_CONFIG_TEXT = 'replanner:\n  mode: simulation_live\n  environment: simulation\n  allow_flight_commands: true\n  required_safety_guard_mode: dry_run\n\n  poll_interval_s: 0.5\n  decision_cooldown_s: 5.0\n  maximum_attempts_per_waypoint: 3\n\n  trigger_states:\n    - critical\n    - emergency_stop\n\n  minimum_side_clearance_m: 8.0\n  side_preference_margin_m: 1.0\n\n  temporary_waypoint:\n    forward_offset_m: 2.0\n    lateral_offset_m: 5.0\n    altitude_offset_m: 0.0\n\n  blocked_sides_action: hold_and_abort_replan\n\n  live_execution:\n    hold_before_replan_s: 2.0\n    command_timeout_s: 12.0\n    command_retries: 3\n    command_retry_delay_s: 2.0\n    temporary_arrival_timeout_s: 120.0\n    arrival_check_interval_s: 0.5\n    horizontal_tolerance_m: 1.5\n    altitude_tolerance_m: 1.0\n    clearance_verification_timeout_s: 30.0\n    clearance_required_consecutive_checks: 2\n    resume_states:\n      - clear\n      - warning\n    avoidance_speed_m_s: 0.15\n    resume_original_waypoint: true\n\n  event_log_csv: outputs/swarm/v1_three_drone_swarm/safety/{drone_id}_local_replanning_events_live.csv\n\ngeometry:\n  earth_radius_m: 6371000.0\n  minimum_target_vector_m: 0.25\n'


def backup(path: Path) -> None:
    if not path.exists():
        return

    BACKUP_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )
    destination = (
        BACKUP_DIR
        / path.name
    )
    counter = 1

    while destination.exists():
        destination = (
            BACKUP_DIR
            / (
                f"{path.stem}_{counter}"
                f"{path.suffix}"
            )
        )
        counter += 1

    shutil.copy2(
        path,
        destination,
    )


def replace_once(
    text: str,
    old: str,
    new: str,
    description: str,
) -> str:
    if new in text:
        return text

    if old not in text:
        raise RuntimeError(
            "Unable to find marker for "
            f"{description}"
        )

    return text.replace(
        old,
        new,
        1,
    )


def patch_runner() -> None:
    backup(RUNNER_PATH)
    text = RUNNER_PATH.read_text()

    text = replace_once(
        text,
        """        "home_longitude_deg": None,
    }
""",
        """        "home_longitude_deg": None,
        "replanner_enabled": False,
        "replanner_abort_reason": None,
    }
""",
        "replanner state controls",
    )

    text = replace_once(
        text,
        """                stop_event=stop_event,
            )
""",
        """                stop_event=stop_event,
                drone=drone,
            )
""",
        "replanner drone integration",
    )

    active_waypoint_marker = """            state["active_waypoint"] = {
                "sequence_id": sequence_id,
                "zone_name": zone_name,
                "north_m": float(
                    waypoint["north_m"]
                ),
                "east_m": float(
                    waypoint["east_m"]
                ),
                "altitude_m": float(
                    waypoint["altitude_m"]
                ),
                "yaw_deg": float(
                    waypoint["yaw_deg"]
                ),
            }

"""

    active_waypoint_replacement = (
        active_waypoint_marker
        + """            state["replanner_enabled"] = False
            state["replanner_abort_reason"] = None

"""
    )

    text = replace_once(
        text,
        active_waypoint_marker,
        active_waypoint_replacement,
        "replanner waypoint gate",
    )

    target_marker = """            target_absolute_altitude = (
                ground_absolute_altitude
                + float(waypoint["altitude_m"])
            )

"""

    target_replacement = (
        target_marker
        + """            state["active_waypoint"].update({
                "target_latitude_deg": target_lat,
                "target_longitude_deg": target_lon,
                "target_absolute_altitude_m":
                    target_absolute_altitude,
            })

"""
    )

    text = replace_once(
        text,
        target_marker,
        target_replacement,
        "active waypoint target coordinates",
    )

    arrival_marker = """            arrived = await wait_for_arrival(
"""

    arrival_replacement = """            state["replanner_enabled"] = True

""" + arrival_marker

    text = replace_once(
        text,
        arrival_marker,
        arrival_replacement,
        "enable replanner during arrival",
    )

    summary_marker = """            summary["completed_waypoints"].append({
"""

    summary_replacement = """            state["replanner_enabled"] = False

""" + summary_marker

    text = replace_once(
        text,
        summary_marker,
        summary_replacement,
        "disable replanner after arrival",
    )

    hold_marker = """            await safety_aware_wait(
                float(waypoint["hold_s"]),
"""

    hold_replacement = """            state["active_waypoint"] = None

""" + hold_marker

    text = replace_once(
        text,
        hold_marker,
        hold_replacement,
        "clear active waypoint before hold",
    )

    RUNNER_PATH.write_text(text)


def main() -> None:
    if not PROJECT_ROOT.exists():
        raise SystemExit(
            f"Project root not found: "
            f"{PROJECT_ROOT}"
        )

    backup(MODULE_PATH)
    backup(LIVE_CONFIG_PATH)

    MODULE_PATH.write_text(
        MODULE_TEXT
    )
    MODULE_PATH.chmod(0o755)

    LIVE_CONFIG_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    LIVE_CONFIG_PATH.write_text(
        LIVE_CONFIG_TEXT
    )

    patch_runner()

    print(
        "Point 22C simulation-live local "
        "replanning installed."
    )
    print(
        "Default replanner config remains "
        "dry_run."
    )
    print(
        "Live commands require the explicit "
        "simulation-live config."
    )


if __name__ == "__main__":
    main()
