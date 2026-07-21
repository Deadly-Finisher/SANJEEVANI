from pathlib import Path
import csv
import json

import yaml


CONFIG_PATH = Path("configs/qgis/v1_mission_map.yaml")


def load_yaml(path: Path) -> dict:
    with open(path, "r") as file:
        return yaml.safe_load(file)


def rectangle_polygon(center_x: float, center_y: float, width: float, height: float):
    half_width = width / 2.0
    half_height = height / 2.0

    return [
        [center_x - half_width, center_y - half_height],
        [center_x + half_width, center_y - half_height],
        [center_x + half_width, center_y + half_height],
        [center_x - half_width, center_y + half_height],
        [center_x - half_width, center_y - half_height],
    ]


def make_feature(geometry_type: str, coordinates, properties: dict) -> dict:
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {
            "type": geometry_type,
            "coordinates": coordinates,
        },
    }


def make_feature_collection(features: list) -> dict:
    return {
        "type": "FeatureCollection",
        "features": features,
    }


def mission_waypoint_to_gazebo(waypoint: dict, spawn_x: float, spawn_y: float):
    north_m = float(waypoint["north_m"])
    east_m = float(waypoint["east_m"])

    gazebo_x = spawn_x + north_m
    gazebo_y = spawn_y + east_m

    return gazebo_x, gazebo_y


def main():
    config = load_yaml(CONFIG_PATH)

    mission_config_path = Path(config["mission"]["source_mission_config"])
    mission_config = load_yaml(mission_config_path)

    output_dir = Path(config["output"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    spawn_x = float(config["coordinate_system"]["spawn_gazebo_x"])
    spawn_y = float(config["coordinate_system"]["spawn_gazebo_y"])

    zones_geojson_path = output_dir / config["output"]["zones_geojson"]
    waypoints_csv_path = output_dir / config["output"]["waypoints_csv"]
    route_geojson_path = output_dir / config["output"]["route_geojson"]
    mission_objects_geojson_path = output_dir / config["output"]["mission_objects_geojson"]

    zone_features = []

    for zone in config["zones"]:
        polygon = rectangle_polygon(
            center_x=float(zone["center_gazebo_x"]),
            center_y=float(zone["center_gazebo_y"]),
            width=float(zone["width_m"]),
            height=float(zone["height_m"]),
        )

        zone_features.append(
            make_feature(
                geometry_type="Polygon",
                coordinates=[polygon],
                properties={
                    "zone_name": zone["zone_name"],
                    "zone_type": zone["zone_type"],
                    "center_x": float(zone["center_gazebo_x"]),
                    "center_y": float(zone["center_gazebo_y"]),
                    "width_m": float(zone["width_m"]),
                    "height_m": float(zone["height_m"]),
                    "mission": config["mission"]["name"],
                    "world": config["mission"]["world_name"],
                },
            )
        )

    zones_geojson_path.write_text(json.dumps(make_feature_collection(zone_features), indent=2))

    waypoints = mission_config["waypoints"]

    route_coordinates = []

    with open(waypoints_csv_path, "w", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "sequence_id",
                "zone_name",
                "gazebo_x",
                "gazebo_y",
                "north_m",
                "east_m",
                "altitude_m",
                "yaw_deg",
                "hold_s",
                "mission",
                "world",
            ],
        )
        writer.writeheader()

        for idx, waypoint in enumerate(waypoints, start=1):
            gazebo_x, gazebo_y = mission_waypoint_to_gazebo(
                waypoint=waypoint,
                spawn_x=spawn_x,
                spawn_y=spawn_y,
            )

            route_coordinates.append([gazebo_x, gazebo_y])

            writer.writerow(
                {
                    "sequence_id": idx,
                    "zone_name": waypoint["zone_name"],
                    "gazebo_x": gazebo_x,
                    "gazebo_y": gazebo_y,
                    "north_m": waypoint["north_m"],
                    "east_m": waypoint["east_m"],
                    "altitude_m": waypoint["altitude_m"],
                    "yaw_deg": waypoint["yaw_deg"],
                    "hold_s": waypoint["hold_s"],
                    "mission": config["mission"]["name"],
                    "world": config["mission"]["world_name"],
                }
            )

    route_feature = make_feature(
        geometry_type="LineString",
        coordinates=route_coordinates,
        properties={
            "mission": config["mission"]["name"],
            "world": config["mission"]["world_name"],
            "route_type": "fixed_v1_mission_route",
            "waypoint_count": len(route_coordinates),
        },
    )

    route_geojson_path.write_text(json.dumps(make_feature_collection([route_feature]), indent=2))

    object_features = []

    for item in config["mission_objects"]:
        object_features.append(
            make_feature(
                geometry_type="Point",
                coordinates=[float(item["gazebo_x"]), float(item["gazebo_y"])],
                properties={
                    "object_name": item["object_name"],
                    "object_type": item["object_type"],
                    "mission": config["mission"]["name"],
                    "world": config["mission"]["world_name"],
                },
            )
        )

    mission_objects_geojson_path.write_text(json.dumps(make_feature_collection(object_features), indent=2))

    print("QGIS mission map layers created.")
    print("Output directory:", output_dir.resolve())
    print("Zones:", zones_geojson_path.resolve())
    print("Waypoints:", waypoints_csv_path.resolve())
    print("Route:", route_geojson_path.resolve())
    print("Mission objects:", mission_objects_geojson_path.resolve())


if __name__ == "__main__":
    main()
