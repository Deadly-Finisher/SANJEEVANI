#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path


PROJECT_ROOT = Path.home() / "Programs" / "SWARM_DRONES"
BACKUP_DIR = (
    PROJECT_ROOT
    / "backups"
    / "point22b_replanner_integration"
)

MODULE_PATH = (
    PROJECT_ROOT
    / "swarm"
    / "safety"
    / "local_obstacle_replanner.py"
)
GUARD_PATH = (
    PROJECT_ROOT
    / "swarm"
    / "safety"
    / "mission_safety_guard.py"
)
RUNNER_PATH = (
    PROJECT_ROOT
    / "simulation"
    / "scripts"
    / "run_one_swarm_drone_mission.py"
)

MODULE_TEXT = '#!/usr/bin/env python3\nfrom __future__ import annotations\n\nimport asyncio\nimport csv\nimport math\nimport time\nfrom datetime import datetime, timezone\nfrom pathlib import Path\nfrom typing import Any\n\nimport yaml\n\n\nclass LocalObstacleReplanner:\n    def __init__(\n        self,\n        config_path: str | Path,\n        drone_id: str,\n    ) -> None:\n        config = yaml.safe_load(\n            Path(config_path).read_text()\n        )\n\n        replanner = config["replanner"]\n        geometry = config["geometry"]\n\n        self.drone_id = str(drone_id)\n        self.mode = str(replanner["mode"])\n        self.poll_interval_s = float(\n            replanner["poll_interval_s"]\n        )\n        self.decision_cooldown_s = float(\n            replanner["decision_cooldown_s"]\n        )\n        self.maximum_attempts_per_waypoint = int(\n            replanner[\n                "maximum_attempts_per_waypoint"\n            ]\n        )\n        self.trigger_states = {\n            str(value)\n            for value in replanner["trigger_states"]\n        }\n        self.minimum_side_clearance_m = float(\n            replanner[\n                "minimum_side_clearance_m"\n            ]\n        )\n        self.side_preference_margin_m = float(\n            replanner[\n                "side_preference_margin_m"\n            ]\n        )\n\n        temporary = replanner[\n            "temporary_waypoint"\n        ]\n\n        self.forward_offset_m = float(\n            temporary["forward_offset_m"]\n        )\n        self.lateral_offset_m = float(\n            temporary["lateral_offset_m"]\n        )\n        self.altitude_offset_m = float(\n            temporary["altitude_offset_m"]\n        )\n        self.blocked_sides_action = str(\n            replanner["blocked_sides_action"]\n        )\n        self.earth_radius_m = float(\n            geometry["earth_radius_m"]\n        )\n        self.minimum_target_vector_m = float(\n            geometry["minimum_target_vector_m"]\n        )\n\n        log_template = str(\n            replanner["event_log_csv"]\n        )\n        self.log_path = Path(\n            log_template.format(\n                drone_id=self.drone_id\n            )\n        )\n        self.log_path.parent.mkdir(\n            parents=True,\n            exist_ok=True,\n        )\n\n        self._attempts_by_waypoint: dict[\n            str,\n            int,\n        ] = {}\n        self._last_decision_time = 0.0\n        self._initialize_log()\n\n        print(\n            f"[{self.drone_id}] local replanner "\n            f"mode: {self.mode}"\n        )\n        print(\n            f"[{self.drone_id}] local replanner "\n            f"log: {self.log_path}"\n        )\n\n    def _initialize_log(self) -> None:\n        if (\n            self.log_path.exists()\n            and self.log_path.stat().st_size\n        ):\n            return\n\n        with self.log_path.open(\n            "w",\n            newline="",\n        ) as file:\n            csv.writer(file).writerow([\n                "timestamp_utc",\n                "drone_id",\n                "waypoint_key",\n                "zone_name",\n                "attempt_number",\n                "safety_state",\n                "scan_age_s",\n                "front_min_m",\n                "left_min_m",\n                "right_min_m",\n                "selected_side",\n                "temporary_north_m",\n                "temporary_east_m",\n                "temporary_altitude_m",\n                "mode",\n                "result",\n                "reason",\n            ])\n\n    @staticmethod\n    def _number(\n        value: Any,\n    ) -> float | None:\n        try:\n            number = float(value)\n        except (TypeError, ValueError):\n            return None\n\n        if not math.isfinite(number):\n            return None\n\n        return number\n\n    def position_to_local(\n        self,\n        home_latitude_deg: float,\n        home_longitude_deg: float,\n        latitude_deg: float,\n        longitude_deg: float,\n    ) -> tuple[float, float]:\n        north_m = (\n            math.radians(\n                latitude_deg\n                - home_latitude_deg\n            )\n            * self.earth_radius_m\n        )\n\n        east_m = (\n            math.radians(\n                longitude_deg\n                - home_longitude_deg\n            )\n            * self.earth_radius_m\n            * math.cos(\n                math.radians(\n                    home_latitude_deg\n                )\n            )\n        )\n\n        return north_m, east_m\n\n    def _direction_to_target(\n        self,\n        current_north_m: float,\n        current_east_m: float,\n        target_north_m: float,\n        target_east_m: float,\n        yaw_deg: float,\n    ) -> tuple[float, float]:\n        delta_north = (\n            target_north_m\n            - current_north_m\n        )\n        delta_east = (\n            target_east_m\n            - current_east_m\n        )\n        norm = math.hypot(\n            delta_north,\n            delta_east,\n        )\n\n        if norm >= self.minimum_target_vector_m:\n            return (\n                delta_north / norm,\n                delta_east / norm,\n            )\n\n        yaw_rad = math.radians(\n            yaw_deg\n        )\n\n        return (\n            math.cos(yaw_rad),\n            math.sin(yaw_rad),\n        )\n\n    def choose_side(\n        self,\n        left_min_m: float | None,\n        right_min_m: float | None,\n    ) -> tuple[str | None, str]:\n        left_clear = (\n            left_min_m is not None\n            and left_min_m\n            >= self.minimum_side_clearance_m\n        )\n        right_clear = (\n            right_min_m is not None\n            and right_min_m\n            >= self.minimum_side_clearance_m\n        )\n\n        if not left_clear and not right_clear:\n            return (\n                None,\n                "both_sides_below_minimum_clearance",\n            )\n\n        if left_clear and not right_clear:\n            return (\n                "left",\n                "left_is_only_clear_side",\n            )\n\n        if right_clear and not left_clear:\n            return (\n                "right",\n                "right_is_only_clear_side",\n            )\n\n        assert left_min_m is not None\n        assert right_min_m is not None\n\n        difference = (\n            left_min_m\n            - right_min_m\n        )\n\n        if (\n            abs(difference)\n            < self.side_preference_margin_m\n        ):\n            return (\n                "left",\n                "clearances_similar_left_tie_break",\n            )\n\n        if difference > 0:\n            return (\n                "left",\n                "left_has_greater_clearance",\n            )\n\n        return (\n            "right",\n            "right_has_greater_clearance",\n        )\n\n    def plan(\n        self,\n        *,\n        current_north_m: float,\n        current_east_m: float,\n        current_altitude_m: float,\n        target_north_m: float,\n        target_east_m: float,\n        yaw_deg: float,\n        front_min_m: float | None,\n        left_min_m: float | None,\n        right_min_m: float | None,\n        safety_state: str,\n    ) -> dict[str, Any]:\n        selected_side, reason = (\n            self.choose_side(\n                left_min_m,\n                right_min_m,\n            )\n        )\n\n        base = {\n            "safety_state": str(safety_state),\n            "front_min_m": self._number(\n                front_min_m\n            ),\n            "left_min_m": self._number(\n                left_min_m\n            ),\n            "right_min_m": self._number(\n                right_min_m\n            ),\n            "selected_side": selected_side,\n            "reason": reason,\n        }\n\n        if selected_side is None:\n            return {\n                **base,\n                "can_replan": False,\n                "result":\n                    self.blocked_sides_action,\n                "temporary_north_m": None,\n                "temporary_east_m": None,\n                "temporary_altitude_m": None,\n            }\n\n        forward_north, forward_east = (\n            self._direction_to_target(\n                current_north_m,\n                current_east_m,\n                target_north_m,\n                target_east_m,\n                yaw_deg,\n            )\n        )\n        left_north = -forward_east\n        left_east = forward_north\n        side_sign = (\n            1.0\n            if selected_side == "left"\n            else -1.0\n        )\n\n        temporary_north_m = (\n            current_north_m\n            + self.forward_offset_m\n            * forward_north\n            + side_sign\n            * self.lateral_offset_m\n            * left_north\n        )\n        temporary_east_m = (\n            current_east_m\n            + self.forward_offset_m\n            * forward_east\n            + side_sign\n            * self.lateral_offset_m\n            * left_east\n        )\n\n        return {\n            **base,\n            "can_replan": True,\n            "result": "plan_created",\n            "temporary_north_m":\n                temporary_north_m,\n            "temporary_east_m":\n                temporary_east_m,\n            "temporary_altitude_m": (\n                current_altitude_m\n                + self.altitude_offset_m\n            ),\n        }\n\n    @staticmethod\n    def _waypoint_key(\n        waypoint: dict[str, Any],\n    ) -> str:\n        return (\n            f"{waypoint.get(\'sequence_id\', \'\')}:"\n            f"{waypoint.get(\'zone_name\', \'\')}"\n        )\n\n    def _record_plan(\n        self,\n        *,\n        waypoint: dict[str, Any],\n        attempt_number: int,\n        scan_age_s: float | None,\n        plan: dict[str, Any],\n    ) -> None:\n        with self.log_path.open(\n            "a",\n            newline="",\n        ) as file:\n            csv.writer(file).writerow([\n                datetime.now(\n                    timezone.utc\n                ).isoformat(),\n                self.drone_id,\n                self._waypoint_key(\n                    waypoint\n                ),\n                waypoint.get(\n                    "zone_name",\n                    "",\n                ),\n                attempt_number,\n                plan.get(\n                    "safety_state"\n                ),\n                scan_age_s,\n                plan.get(\n                    "front_min_m"\n                ),\n                plan.get(\n                    "left_min_m"\n                ),\n                plan.get(\n                    "right_min_m"\n                ),\n                plan.get(\n                    "selected_side"\n                ),\n                plan.get(\n                    "temporary_north_m"\n                ),\n                plan.get(\n                    "temporary_east_m"\n                ),\n                plan.get(\n                    "temporary_altitude_m"\n                ),\n                self.mode,\n                plan.get("result"),\n                plan.get("reason"),\n            ])\n\n        print(\n            f"[{self.drone_id}] local replan "\n            f"dry-run | waypoint="\n            f"{waypoint.get(\'zone_name\')} | "\n            f"state={plan.get(\'safety_state\')} | "\n            f"side="\n            f"{plan.get(\'selected_side\') or \'none\'} | "\n            f"result={plan.get(\'result\')}"\n        )\n\n    async def observe_once(\n        self,\n        *,\n        mission_state: dict[str, Any],\n        safety_guard: Any,\n    ) -> None:\n        waypoint = mission_state.get(\n            "active_waypoint"\n        )\n        position = mission_state.get(\n            "position"\n        )\n        home_latitude_deg = (\n            mission_state.get(\n                "home_latitude_deg"\n            )\n        )\n        home_longitude_deg = (\n            mission_state.get(\n                "home_longitude_deg"\n            )\n        )\n\n        if (\n            waypoint is None\n            or position is None\n            or home_latitude_deg is None\n            or home_longitude_deg is None\n        ):\n            return\n\n        safety_state, status, scan_age_s = (\n            safety_guard.snapshot()\n        )\n\n        if (\n            safety_state\n            not in self.trigger_states\n        ):\n            return\n\n        if (\n            time.monotonic()\n            - self._last_decision_time\n            < self.decision_cooldown_s\n        ):\n            return\n\n        waypoint_key = self._waypoint_key(\n            waypoint\n        )\n        attempt_number = (\n            self._attempts_by_waypoint.get(\n                waypoint_key,\n                0,\n            )\n            + 1\n        )\n\n        if (\n            attempt_number\n            > self.maximum_attempts_per_waypoint\n        ):\n            return\n\n        current_north_m, current_east_m = (\n            self.position_to_local(\n                float(home_latitude_deg),\n                float(home_longitude_deg),\n                float(\n                    position.latitude_deg\n                ),\n                float(\n                    position.longitude_deg\n                ),\n            )\n        )\n\n        plan = self.plan(\n            current_north_m=current_north_m,\n            current_east_m=current_east_m,\n            current_altitude_m=float(\n                position.relative_altitude_m\n            ),\n            target_north_m=float(\n                waypoint["north_m"]\n            ),\n            target_east_m=float(\n                waypoint["east_m"]\n            ),\n            yaw_deg=float(\n                waypoint["yaw_deg"]\n            ),\n            front_min_m=self._number(\n                status.get("front_min_m")\n            ),\n            left_min_m=self._number(\n                status.get("left_min_m")\n            ),\n            right_min_m=self._number(\n                status.get("right_min_m")\n            ),\n            safety_state=safety_state,\n        )\n\n        if plan["can_replan"]:\n            plan["result"] = (\n                "dry_run_plan_created"\n            )\n        else:\n            plan["result"] = (\n                "dry_run_"\n                f"{self.blocked_sides_action}"\n            )\n\n        self._attempts_by_waypoint[\n            waypoint_key\n        ] = attempt_number\n        self._last_decision_time = (\n            time.monotonic()\n        )\n\n        self._record_plan(\n            waypoint=waypoint,\n            attempt_number=attempt_number,\n            scan_age_s=scan_age_s,\n            plan=plan,\n        )\n\n    async def run(\n        self,\n        *,\n        mission_state: dict[str, Any],\n        safety_guard: Any,\n        stop_event: asyncio.Event,\n    ) -> None:\n        while not stop_event.is_set():\n            await self.observe_once(\n                mission_state=mission_state,\n                safety_guard=safety_guard,\n            )\n            await asyncio.sleep(\n                self.poll_interval_s\n            )\n\n    def close(self) -> None:\n        return\n'


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


def patch_guard() -> None:
    backup(GUARD_PATH)
    text = GUARD_PATH.read_text()

    marker = """    async def wait_for_initial_status(self):
"""

    addition = """    def snapshot(self):
        state, status, age_s = self._snapshot()

        return (
            state,
            dict(status),
            age_s,
        )

"""

    if "    def snapshot(self):\n" not in text:
        text = replace_once(
            text,
            marker,
            addition + marker,
            "public safety snapshot",
        )

    GUARD_PATH.write_text(text)


def patch_runner() -> None:
    backup(RUNNER_PATH)
    text = RUNNER_PATH.read_text()

    old_import = (
        "from swarm.safety."
        "mission_safety_guard import "
        "MissionSafetyGuard\n"
    )
    new_import = (
        old_import
        + "from swarm.safety."
        "local_obstacle_replanner import "
        "LocalObstacleReplanner\n"
    )

    text = replace_once(
        text,
        old_import,
        new_import,
        "local replanner import",
    )

    pose_argument = """    parser.add_argument(
        "--pose-config",
        default=(
            "configs/safety/"
            "v1_swarm_gazebo_pose.yaml"
        ),
    )

"""

    replanner_argument = (
        pose_argument
        + """    parser.add_argument(
        "--replanner-config",
        default=(
            "configs/safety/"
            "v1_swarm_local_replanner.yaml"
        ),
    )

"""
    )

    text = replace_once(
        text,
        pose_argument,
        replanner_argument,
        "replanner argument",
    )

    text = replace_once(
        text,
        """        "current_zone": "",
    }
""",
        """        "current_zone": "",
        "active_waypoint": None,
        "home_latitude_deg": None,
        "home_longitude_deg": None,
    }
""",
        "mission state fields",
    )

    text = replace_once(
        text,
        """    safety_guard = None
""",
        """    safety_guard = None
    local_replanner = None
    replanner_task = None
""",
        "replanner task variables",
    )

    safety_summary = """        summary["safety_event_log"] = str(
            safety_guard.log_path
        )

"""

    replanner_setup = (
        safety_summary
        + """        local_replanner = LocalObstacleReplanner(
            args.replanner_config,
            drone_id,
        )

        summary["local_replanner_mode"] = (
            local_replanner.mode
        )
        summary["local_replanner_event_log"] = str(
            local_replanner.log_path
        )

"""
    )

    text = replace_once(
        text,
        safety_summary,
        replanner_setup,
        "replanner initialization",
    )

    home_marker = """        home_lat = start_position.latitude_deg
        home_lon = start_position.longitude_deg

"""

    home_setup = (
        home_marker
        + """        state["home_latitude_deg"] = home_lat
        state["home_longitude_deg"] = home_lon

        replanner_task = asyncio.create_task(
            local_replanner.run(
                mission_state=state,
                safety_guard=safety_guard,
                stop_event=stop_event,
            )
        )

"""
    )

    text = replace_once(
        text,
        home_marker,
        home_setup,
        "replanner background task",
    )

    waypoint_marker = """            state["current_zone"] = zone_name

"""

    waypoint_setup = (
        waypoint_marker
        + """            state["active_waypoint"] = {
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
    )

    text = replace_once(
        text,
        waypoint_marker,
        waypoint_setup,
        "active waypoint state",
    )

    close_marker = """        if safety_guard is not None:
            safety_guard.close()
"""

    close_setup = """        if replanner_task is not None:
            replanner_task.cancel()

            try:
                await replanner_task
            except asyncio.CancelledError:
                pass

        if local_replanner is not None:
            local_replanner.close()

""" + close_marker

    text = replace_once(
        text,
        close_marker,
        close_setup,
        "replanner shutdown",
    )

    RUNNER_PATH.write_text(text)


def main() -> None:
    if not PROJECT_ROOT.exists():
        raise SystemExit(
            f"Project root not found: "
            f"{PROJECT_ROOT}"
        )

    backup(MODULE_PATH)
    MODULE_PATH.write_text(
        MODULE_TEXT
    )
    MODULE_PATH.chmod(0o755)

    patch_guard()
    patch_runner()

    print(
        "Point 22B dry-run mission integration "
        "installed."
    )
    print(
        "The replanner now observes real mission "
        "and LiDAR state but sends no avoidance "
        "flight commands."
    )


if __name__ == "__main__":
    main()
