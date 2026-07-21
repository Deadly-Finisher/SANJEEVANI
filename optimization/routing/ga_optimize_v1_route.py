from pathlib import Path
import csv
import json
import math
import itertools
import yaml

CONFIG = Path("configs/optimization/v1_ga_route_optimization.yaml")


def load_yaml(path):
    return yaml.safe_load(path.read_text())


def dist(a, b):
    dn = float(a["north_m"]) - float(b["north_m"])
    de = float(a["east_m"]) - float(b["east_m"])
    return math.sqrt(dn * dn + de * de)


def route_distance(route):
    return sum(dist(route[i], route[i + 1]) for i in range(len(route) - 1))


def write_waypoints_csv(path, route):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["sequence_id", "zone_name", "gazebo_x", "gazebo_y", "north_m", "east_m", "altitude_m", "yaw_deg", "hold_s"]

    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for i, wp in enumerate(route, start=1):
            writer.writerow({
                "sequence_id": i,
                "zone_name": wp["zone_name"],
                "gazebo_x": wp.get("gazebo_x", ""),
                "gazebo_y": wp.get("gazebo_y", ""),
                "north_m": round(float(wp["north_m"]), 3),
                "east_m": round(float(wp["east_m"]), 3),
                "altitude_m": round(float(wp["altitude_m"]), 3),
                "yaw_deg": round(float(wp["yaw_deg"]), 3),
                "hold_s": float(wp["hold_s"]),
            })


def write_route_geojson(path, route):
    path.parent.mkdir(parents=True, exist_ok=True)

    geojson = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {
                "route_type": "optimized_route",
                "route_distance_m": round(route_distance(route), 3),
                "waypoint_count": len(route),
            },
            "geometry": {
                "type": "LineString",
                "coordinates": [[float(wp["gazebo_x"]), float(wp["gazebo_y"])] for wp in route],
            },
        }],
    }

    path.write_text(json.dumps(geojson, indent=2))


def write_mission_yaml(path, cfg, route):
    path.parent.mkdir(parents=True, exist_ok=True)

    mission_yaml = {
        "connection": cfg["mission"]["connection"],
        "mission": {
            "mission_name": cfg["mission"]["mission_name"],
            "takeoff_altitude_m": float(cfg["mission"]["flight"]["takeoff_altitude_m"]),
            "takeoff_wait_s": float(cfg["mission"]["flight"]["takeoff_wait_s"]),
            "waypoint_command_interval_s": float(cfg["mission"]["flight"]["waypoint_command_interval_s"]),
            "landing_wait_s": float(cfg["mission"]["flight"]["landing_wait_s"]),
        },
        "logging": cfg["mission"]["logging"],
        "waypoints": [],
    }

    for wp in route:
        mission_yaml["waypoints"].append({
            "zone_name": wp["zone_name"],
            "north_m": round(float(wp["north_m"]), 3),
            "east_m": round(float(wp["east_m"]), 3),
            "altitude_m": round(float(wp["altitude_m"]), 3),
            "yaw_deg": round(float(wp["yaw_deg"]), 3),
            "hold_s": float(wp["hold_s"]),
        })

    path.write_text(yaml.safe_dump(mission_yaml, sort_keys=False))


def main():
    cfg = load_yaml(CONFIG)
    parsed = json.loads(Path(cfg["input"]["parsed_mission_json"]).read_text())
    waypoints = parsed["waypoints"]

    start_name = cfg["mission"]["start_zone_name"]
    end_name = cfg["mission"]["end_zone_name"]

    start = [w for w in waypoints if w["zone_name"] == start_name][0]
    end = [w for w in waypoints if w["zone_name"] == end_name][-1]
    middle = [w for w in waypoints if w["zone_name"] not in {start_name, end_name}]

    original_route = [start] + middle + [end]

    candidate_routes = []
    for order in itertools.permutations(middle):
        candidate_routes.append([start] + list(order) + [end])

    optimized_route = min(candidate_routes, key=route_distance)

    original_distance = route_distance(original_route)
    optimized_distance = route_distance(optimized_route)
    saved = original_distance - optimized_distance
    improvement = 0.0 if original_distance == 0 else saved * 100.0 / original_distance

    out = Path(cfg["output"]["output_dir"])
    out.mkdir(parents=True, exist_ok=True)

    comparison = {
        "method": "exhaustive_route_optimizer_for_small_qgis_mission",
        "original_route_distance_m": round(original_distance, 3),
        "optimized_route_distance_m": round(optimized_distance, 3),
        "distance_saved_m": round(saved, 3),
        "improvement_percent": round(improvement, 3),
        "original_route_zone_order": [w["zone_name"] for w in original_route],
        "optimized_route_zone_order": [w["zone_name"] for w in optimized_route],
    }

    write_waypoints_csv(out / cfg["output"]["optimized_waypoints_csv"], optimized_route)
    write_route_geojson(out / cfg["output"]["optimized_route_geojson"], optimized_route)
    write_mission_yaml(Path(cfg["output"]["optimized_mission_yaml"]), cfg, optimized_route)

    (out / cfg["output"]["comparison_json"]).write_text(json.dumps(comparison, indent=2))

    md = "# V1 Route Optimization Comparison\n\n"
    md += "Original distance: " + str(round(original_distance, 3)) + " m\n\n"
    md += "Optimized distance: " + str(round(optimized_distance, 3)) + " m\n\n"
    md += "Distance saved: " + str(round(saved, 3)) + " m\n\n"
    md += "Improvement: " + str(round(improvement, 3)) + " percent\n\n"
    md += "Original route:\n" + " -> ".join(comparison["original_route_zone_order"]) + "\n\n"
    md += "Optimized route:\n" + " -> ".join(comparison["optimized_route_zone_order"]) + "\n"

    (out / cfg["output"]["comparison_markdown"]).write_text(md)

    print("Route optimization completed.")
    print("Original distance:", round(original_distance, 3), "m")
    print("Optimized distance:", round(optimized_distance, 3), "m")
    print("Distance saved:", round(saved, 3), "m")
    print("Improvement:", round(improvement, 3), "%")
    print("Original route:", " -> ".join(comparison["original_route_zone_order"]))
    print("Optimized route:", " -> ".join(comparison["optimized_route_zone_order"]))


if __name__ == "__main__":
    main()
