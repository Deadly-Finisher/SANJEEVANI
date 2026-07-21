#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class MissionPosition:
    latitude_deg: float
    longitude_deg: float
    absolute_altitude_m: float
    relative_altitude_m: float
    local_north_m: float
    local_east_m: float
    world_x_m: float
    world_y_m: float
    world_z_m: float


class GazeboPoseTracker:
    def __init__(
        self,
        config_path: str | Path,
        drone_id: str,
    ) -> None:
        path = Path(config_path)

        if not path.is_absolute():
            path = PROJECT_ROOT / path

        config = yaml.safe_load(path.read_text())

        world = config["world"]
        coordinates = config["coordinates"]

        self.drone_id = str(drone_id)
        self.pose_topic = str(world["pose_topic"])
        self.restart_delay_s = float(
            world["restart_delay_s"]
        )
        self.command = [
            str(item)
            for item in world["command"]
        ]

        self.earth_radius_m = float(
            coordinates["earth_radius_m"]
        )

        world_path = Path(world["sdf_path"])

        if not world_path.is_absolute():
            world_path = PROJECT_ROOT / world_path

        self.world_path = world_path

        drone_config = next(
            (
                item
                for item in config["drones"]
                if item["drone_id"] == drone_id
            ),
            None,
        )

        if drone_config is None:
            raise RuntimeError(
                f"No Gazebo pose configuration for {drone_id}"
            )

        self.model_name = str(
            drone_config["gazebo_model_name"]
        )

        (
            self.reference_latitude_deg,
            self.reference_longitude_deg,
            self.reference_elevation_m,
            self.heading_deg,
        ) = self._load_spherical_coordinates()

        self.home_x_m: float | None = None
        self.home_y_m: float | None = None
        self.home_z_m: float | None = None
        self.process: asyncio.subprocess.Process | None = None

        print(
            f"[{self.drone_id}] Gazebo pose source: "
            f"{self.pose_topic}"
        )
        print(
            f"[{self.drone_id}] Gazebo model: "
            f"{self.model_name}"
        )

    def _load_spherical_coordinates(
        self,
    ) -> tuple[float, float, float, float]:
        root = ET.parse(self.world_path).getroot()
        spherical = root.find(".//spherical_coordinates")

        if spherical is None:
            raise RuntimeError(
                "World SDF has no <spherical_coordinates> block"
            )

        def required(name: str) -> float:
            element = spherical.find(name)

            if element is None or element.text is None:
                raise RuntimeError(
                    f"Missing <{name}> in spherical coordinates"
                )

            return float(element.text.strip())

        heading = spherical.find("heading_deg")
        heading_deg = (
            float(heading.text.strip())
            if heading is not None and heading.text
            else 0.0
        )

        return (
            required("latitude_deg"),
            required("longitude_deg"),
            required("elevation"),
            heading_deg,
        )

    def _world_to_geodetic(
        self,
        x_m: float,
        y_m: float,
        z_m: float,
    ) -> MissionPosition:
        heading_rad = math.radians(self.heading_deg)

        east_m = (
            x_m * math.cos(heading_rad)
            - y_m * math.sin(heading_rad)
        )
        north_m = (
            x_m * math.sin(heading_rad)
            + y_m * math.cos(heading_rad)
        )

        latitude_deg = (
            self.reference_latitude_deg
            + math.degrees(
                north_m / self.earth_radius_m
            )
        )

        latitude_rad = math.radians(
            self.reference_latitude_deg
        )

        longitude_deg = (
            self.reference_longitude_deg
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

        if self.home_x_m is None:
            self.home_x_m = x_m
            self.home_y_m = y_m
            self.home_z_m = z_m

        relative_altitude_m = (
            z_m - float(self.home_z_m)
        )

        return MissionPosition(
            latitude_deg=latitude_deg,
            longitude_deg=longitude_deg,
            absolute_altitude_m=(
                self.reference_elevation_m + z_m
            ),
            relative_altitude_m=relative_altitude_m,
            local_north_m=(
                north_m
                - self._home_north_m()
            ),
            local_east_m=(
                east_m
                - self._home_east_m()
            ),
            world_x_m=x_m,
            world_y_m=y_m,
            world_z_m=z_m,
        )

    def _home_east_m(self) -> float:
        heading_rad = math.radians(self.heading_deg)

        return (
            float(self.home_x_m) * math.cos(heading_rad)
            - float(self.home_y_m) * math.sin(heading_rad)
        )

    def _home_north_m(self) -> float:
        heading_rad = math.radians(self.heading_deg)

        return (
            float(self.home_x_m) * math.sin(heading_rad)
            + float(self.home_y_m) * math.cos(heading_rad)
        )

    async def run(
        self,
        state: dict[str, Any],
        stop_event: asyncio.Event,
    ) -> None:
        try:
            await self._stream_once(
                state,
                stop_event,
            )
        except asyncio.CancelledError:
            raise

        if not stop_event.is_set():
            raise RuntimeError(
                "Gazebo pose stream ended unexpectedly; "
                "automatic restart is disabled after MAVSDK starts "
                "to avoid unsafe fork operations inside gRPC."
            )

    async def _stream_once(
        self,
        state: dict[str, Any],
        stop_event: asyncio.Event,
    ) -> None:
        self.process = await asyncio.create_subprocess_exec(
            *self.command,
            self.pose_topic,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        if self.process.stdout is None:
            raise RuntimeError(
                "Gazebo pose process has no stdout"
            )

        parser = _PoseTextParser(self.model_name)

        try:
            while not stop_event.is_set():
                line = await self.process.stdout.readline()

                if not line:
                    break

                pose = parser.feed(
                    line.decode(
                        errors="replace"
                    )
                )

                if pose is None:
                    continue

                x_m, y_m, z_m = pose

                state["position"] = (
                    self._world_to_geodetic(
                        x_m,
                        y_m,
                        z_m,
                    )
                )
        finally:
            await self._stop_process()

    async def _stop_process(self) -> None:
        process = self.process
        self.process = None

        if process is None:
            return

        if process.returncode is None:
            process.terminate()

            try:
                await asyncio.wait_for(
                    process.wait(),
                    timeout=2.0,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()


class _PoseTextParser:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._reset()

    def _reset(self) -> None:
        self.in_pose = False
        self.pose_depth = 0
        self.in_position = False
        self.position_depth = 0
        self.name: str | None = None
        self.x_m: float | None = None
        self.y_m: float | None = None
        self.z_m: float | None = None

    @staticmethod
    def _value(line: str) -> float:
        return float(line.split(":", 1)[1].strip())

    def feed(
        self,
        line: str,
    ) -> tuple[float, float, float] | None:
        text = line.strip()

        if not self.in_pose:
            if text == "pose {":
                self.in_pose = True
                self.pose_depth = 1

            return None

        if (
            self.pose_depth == 1
            and text.startswith("name:")
        ):
            self.name = (
                text.split(":", 1)[1]
                .strip()
                .strip('"')
            )

        if text == "position {":
            self.in_position = True
            self.position_depth = (
                self.pose_depth + 1
            )
        elif self.in_position:
            if text.startswith("x:"):
                self.x_m = self._value(text)
            elif text.startswith("y:"):
                self.y_m = self._value(text)
            elif text.startswith("z:"):
                self.z_m = self._value(text)

        self.pose_depth += (
            text.count("{")
            - text.count("}")
        )

        if (
            self.in_position
            and self.pose_depth
            < self.position_depth
        ):
            self.in_position = False

        if self.pose_depth != 0:
            return None

        result = None

        if (
            self.name == self.model_name
            and self.x_m is not None
            and self.y_m is not None
            and self.z_m is not None
        ):
            result = (
                self.x_m,
                self.y_m,
                self.z_m,
            )

        self._reset()
        return result
