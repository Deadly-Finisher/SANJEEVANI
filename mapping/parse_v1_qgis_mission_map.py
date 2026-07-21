from pathlib import Path
import csv
import json
import math
from typing import Dict, List, Tuple

import yaml


CONFIG_PATH = Path("configs/qgis/v1_parse_qgis_map.yaml")


def load_yaml(path: Path) -> dict:
    with open(path, "r") as file:
        return yaml.safe_load(file)


def load_geojson(path: Path) -> dict:
    with open(path, "r") as file:
        return json.load(file)


def gazebo_to_ned(gazebo_x: float, gazebo_y: float, spawn_x: float, spawn_y: float) -> Tuple[float, float]:
    north_m = gazebo_x - spawn_x
    east_m = gazebo_y - spawn_y
    return north_m, east_m


def distance_2d(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def read_waypoints_csv(path: Path, spawn_x: float, spawn_y: float) -> List[dict]:
    waypoints = []

    with open(path, "r", newline="") as file:
        reader = csv.DictReader(file)

        for row in reader:
            gazebo_x = float(row["gazebo_x"])
            gazebo_y = float(row["gazebo_y"])
            north_m, east_m = gazebo_to_ned(gazebo_x, gazebo_y, spawn_x, spawn_y)

            waypoints.append(
                {
                    "sequence_id": int(row["sequence_id"]),
                    "zone_name": row["zone_name"],
                    "gazebo_x": gazebo_x,
                    "gazebo_y": gazebo_y,
                    "north_m": north_m,
                    "east_m": east_m,
                    "altitude_m": float(row["altitude_m"]),
                    "yaw_deg": float(row["yaw_deg"]),
                    "hold_s": float(row["hold_s"]),
                    "mission": row.get("mission", ""),
                    "world": row.get("world", ""),
                }
            )

    return waypoints


def parse_zones(zones_geojson: dict, spawn_x: float, spawn_y: float) -> List[dict]:
    parsed_zones = []

    for feature in zones_geojson.get("features", []):
        props = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates", [[]])[0]

        center_x = float(props.get("center_x"))
        center_y = float(props.get("center_y"))
        north_m, east_m = gazebo_to_ned(center_x, center_y, spawn_x, spawn_y)

        parsed_zones.append(
            {
                "zone_name": props.get("zone_name"),
                "zone_type": props.get("zone_type"),
                "center_gazebo_x": center_x,
                "center_gazebo_y": center_y,
                "center_north_m": north_m,
                "center_east_m": east_m,
                "width_m": float(props.get("width_m")),
                "height_m": float(props.get("height_m")),
                "polygon_gazebo_xy": coords,
            }
        )

    return parsed_zones


def parse_objects(objects_geojson: dict, spawn_x: float, spawn_y: float) -> List[dict]:
    parsed_objects = []

    for feature in objects_geojson.get("features", []):
        props = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates", [0.0, 0.0])

        gazebo_x = float(coords[0])
        gazebo_y = float(coords[1])
        north_m, east_m = gazebo_to_ned(gazebo_x, gazebo_y, spawn_x, spawn_y)

        parsed_objects.append(
            {
                "object_name": props.get("object_name"),
                "object_type": props.get("object_type"),
                "gazebo_x": gazebo_x,
                "gazebo_y": gazebo_y,
                "north_m": north_m,
                "east_m": east_m,
            }
        )

    return parsed_objects


def parse_route(route_geojson: dict, spawn_x: float, spawn_y: float) -> dict:
    features = route_geojson.get("features", [])

    if not features:
        return {"route_points": [], "route_distance_m": 0.0}

    coordinates = features[0].get("geometry", {}).get("coordinates", [])

    route_points = []
    total_distance = 0.0
    previous_point = None

    for idx, point in enumerate(coordinates, start=1):
        gazebo_x = float(point[0])
        gazebo_y = float(point[1])
        north_m, east_m = gazebo_to_ned(gazebo_x, gazebo_y, spawn_x, spawn_y)

        current_point = (gazebo_x, gazebo_y)

        if previous_point is not None:
            total_distance += distance_2d(previous_point, current_point)

        previous_point = current_point

        route_points.append(
            {
                "sequence_id": idx,
                "gazebo_x": gazebo_x,
                "gazebo_y": gazebo_y,
                "north_m": north_m,
                "east_m": east_m,
            }
        )

    return {
        "route_points": route_points,
        "route_distance_m": total_distance,
    }


def write_parsed_waypoints_csv(path: Path, waypoints: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "sequence_id",
        "zone_name",
        "gazebo_x",
        "gazebo_y",
        "north_m",
        "east_m",
        "altitude_m",
        "yaw_deg",
        "hold_s",
    ]

    with open(path, "w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for waypoint in waypoints:
            writer.writerow({field: waypoint[field] for field in fieldnames})


def write_mission_yaml(path: Path, config: dict, waypoints: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    mission_yaml = {
        "connection": config["mission_defaults"]["connection"],
        "mission": config["mission_defaults"]["mission"],
        "logging": config["mission_defaults"]["logging"],
        "waypoints": [],
    }

    for waypoint in waypoints:
        mission_yaml["waypoints"].append(
            {
                "zone_name": waypoint["zone_name"],
                "north_m": round(float(waypoint["north_m"]), 3),
                "east_m": round(float(waypoint["east_m"]), 3),
                "altitude_m": round(float(waypoint["altitude_m"]), 3),
                "yaw_deg": round(float(waypoint["yaw_deg"]), 3),
                "hold_s": float(waypoint["hold_s"]),
            }
        )

    path.write_text(yaml.safe_dump(mission_yaml, sort_keys=False))


def main():
    config = load_yaml(CONFIG_PATH)

    qgis_map_dir = Path(config["input"]["qgis_map_dir"])

    zones_path = qgis_map_dir / config["input"]["zones_geojson"]
    route_path = qgis_map_dir / config["input"]["route_geojson"]
    objects_path = qgis_map_dir / config["input"]["mission_objects_geojson"]
    waypoints_path = qgis_map_dir / config["input"]["waypoints_csv"]

    spawn_x = float(config["coordinate_system"]["spawn_gazebo_x"])
    spawn_y = float(config["coordinate_system"]["spawn_gazebo_y"])

    zones = parse_zones(load_geojson(zones_path), spawn_x, spawn_y)
    objects = parse_objects(load_geojson(objects_path), spawn_x, spawn_y)
    route = parse_route(load_geojson(route_path), spawn_x, spawn_y)
    waypoints = read_waypoints_csv(waypoints_path, spawn_x, spawn_y)

    parsed_mission = {
        "mission_name": config["mission_defaults"]["mission"]["mission_name"],
        "source": {
            "qgis_map_dir": str(qgis_map_dir),
            "zones_geojson": str(zones_path),
            "route_geojson": str(route_path),
            "mission_objects_geojson": str(objects_path),
            "waypoints_csv": str(waypoints_path),
        },
        "coordinate_system": config["coordinate_system"],
        "summary": {
            "zone_count": len(zones),
            "object_count": len(objects),
            "waypoint_count": len(waypoints),
            "fixed_route_distance_m": round(float(route["route_distance_m"]), 3),
        },
        "zones": zones,
        "mission_objects": objects,
        "fixed_route": route,
        "waypoints": waypoints,
    }

    parsed_json_path = Path(config["output"]["parsed_mission_json"])
    parsed_waypoints_csv_path = Path(config["output"]["parsed_waypoints_csv"])
    mission_yaml_path = Path(config["output"]["mission_yaml"])

    parsed_json_path.parent.mkdir(parents=True, exist_ok=True)

    parsed_json_path.write_text(json.dumps(parsed_mission, indent=2))
    write_parsed_waypoints_csv(parsed_waypoints_csv_path, waypoints)
    write_mission_yaml(mission_yaml_path, config, waypoints)

    print("QGIS mission map parsed successfully.")
    print("Zones:", len(zones))
    print("Mission objects:", len(objects))
    print("Waypoints:", len(waypoints))
    print("Fixed route distance:", round(float(route["route_distance_m"]), 3), "m")
    print("Parsed JSON:", parsed_json_path.resolve())
    print("Parsed waypoint CSV:", parsed_waypoints_csv_path.resolve())
    print("Mission YAML:", mission_yaml_path.resolve())


if __name__ == "__main__":
    main()
