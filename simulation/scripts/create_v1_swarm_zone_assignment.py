from pathlib import Path
import csv
import json
import math
import yaml


CONFIG_PATH = Path("configs/swarm/v1_swarm_zone_assignment.yaml")


def load_yaml(path):
    return yaml.safe_load(path.read_text())


def load_json(path):
    return json.loads(path.read_text())


def distance(ax, ay, bx, by):
    dx = float(ax) - float(bx)
    dy = float(ay) - float(by)
    return math.sqrt(dx * dx + dy * dy)


def find_waypoint(parsed, zone_name):
    for wp in parsed["waypoints"]:
        if wp["zone_name"] == zone_name:
            return wp
    raise RuntimeError("Waypoint not found: " + zone_name)


def gazebo_to_local(drone, gazebo_x, gazebo_y):
    north_m = float(gazebo_x) - float(drone["spawn_gazebo_x"])
    east_m = float(gazebo_y) - float(drone["spawn_gazebo_y"])
    return north_m, east_m


def assign_zones(cfg, parsed):
    drones = cfg["swarm"]["drones"]
    target_zones = [find_waypoint(parsed, name) for name in cfg["assignment"]["target_zone_names"]]
    load_penalty = float(cfg["assignment"]["load_penalty_m"])

    assignments = {drone["drone_id"]: [] for drone in drones}

    for zone in target_zones:
        best_drone = None
        best_score = None

        for drone in drones:
            dist_score = distance(
                drone["spawn_gazebo_x"],
                drone["spawn_gazebo_y"],
                zone["gazebo_x"],
                zone["gazebo_y"],
            )
            load_score = load_penalty * len(assignments[drone["drone_id"]])
            total_score = dist_score + load_score

            if best_score is None or total_score < best_score:
                best_score = total_score
                best_drone = drone

        assignments[best_drone["drone_id"]].append(zone)

    return assignments


def write_drone_mission(path, drone, zones, cfg):
    defaults = cfg["mission_defaults"]

    mission = {
        "connection": {
            "system_address": "udpin://0.0.0.0:" + str(drone["mavsdk_port"])
        },
        "mission": {
            "mission_name": "v1_swarm_" + drone["drone_id"] + "_mission",
            "takeoff_altitude_m": float(defaults["takeoff_altitude_m"]),
            "takeoff_wait_s": float(defaults["takeoff_wait_s"]),
            "waypoint_command_interval_s": float(defaults["waypoint_command_interval_s"]),
            "landing_wait_s": float(defaults["landing_wait_s"]),
        },
        "logging": {
            "telemetry_csv_path": "outputs/swarm/v1_three_drone_swarm/" + drone["drone_id"] + "_telemetry.csv",
            "sample_interval_s": float(defaults["sample_interval_s"]),
        },
        "waypoints": [],
    }

    mission["waypoints"].append({
        "zone_name": drone["drone_id"] + "_takeoff",
        "north_m": 0.0,
        "east_m": 0.0,
        "altitude_m": float(defaults["takeoff_altitude_m"]),
        "yaw_deg": 0.0,
        "hold_s": 3.0,
    })

    for zone in zones:
        north_m, east_m = gazebo_to_local(drone, zone["gazebo_x"], zone["gazebo_y"])
        mission["waypoints"].append({
            "zone_name": zone["zone_name"],
            "north_m": round(north_m, 3),
            "east_m": round(east_m, 3),
            "altitude_m": round(float(zone.get("altitude_m", defaults["default_altitude_m"])), 3),
            "yaw_deg": round(float(zone.get("yaw_deg", 0.0)), 3),
            "hold_s": float(zone.get("hold_s", defaults["default_hold_s"])),
        })

    mission["waypoints"].append({
        "zone_name": drone["drone_id"] + "_return",
        "north_m": 0.0,
        "east_m": 0.0,
        "altitude_m": float(defaults["takeoff_altitude_m"]),
        "yaw_deg": 0.0,
        "hold_s": 3.0,
    })

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(mission, sort_keys=False))


def main():
    cfg = load_yaml(CONFIG_PATH)
    parsed = load_json(Path(cfg["input"]["parsed_mission_json"]))

    out_dir = Path(cfg["output"]["output_dir"])
    mission_dir = Path(cfg["output"]["mission_yaml_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    mission_dir.mkdir(parents=True, exist_ok=True)

    assignments = assign_zones(cfg, parsed)

    rows = []
    summary = {
        "strategy": cfg["assignment"]["strategy"],
        "drones": []
    }

    report = "# V1 Three-Drone Swarm Zone Assignment\n\n"

    for drone in cfg["swarm"]["drones"]:
        drone_id = drone["drone_id"]
        zones = assignments[drone_id]
        mission_path = mission_dir / (drone_id + "_mission.yaml")

        write_drone_mission(mission_path, drone, zones, cfg)

        zone_names = [zone["zone_name"] for zone in zones]

        summary["drones"].append({
            "drone_id": drone_id,
            "px4_instance": drone["px4_instance"],
            "mavsdk_port": drone["mavsdk_port"],
            "spawn_gazebo_x": drone["spawn_gazebo_x"],
            "spawn_gazebo_y": drone["spawn_gazebo_y"],
            "assigned_zones": zone_names,
            "mission_yaml": str(mission_path),
        })

        report += "## " + drone_id + "\n\n"
        report += "MAVSDK port: " + str(drone["mavsdk_port"]) + "\n\n"
        report += "Assigned zones: " + (" -> ".join(zone_names) if zone_names else "none") + "\n\n"
        report += "Mission YAML: `" + str(mission_path) + "`\n\n"

        for i, zone in enumerate(zones, start=1):
            rows.append({
                "drone_id": drone_id,
                "sequence_id": i,
                "zone_name": zone["zone_name"],
                "gazebo_x": zone["gazebo_x"],
                "gazebo_y": zone["gazebo_y"],
                "mavsdk_port": drone["mavsdk_port"],
                "mission_yaml": str(mission_path),
            })

    (out_dir / cfg["output"]["assignment_json"]).write_text(json.dumps(summary, indent=2))
    (out_dir / cfg["output"]["assignment_report"]).write_text(report)

    with open(out_dir / cfg["output"]["assignment_csv"], "w", newline="") as f:
        fields = ["drone_id", "sequence_id", "zone_name", "gazebo_x", "gazebo_y", "mavsdk_port", "mission_yaml"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print("Swarm zone assignment completed.")
    print("Report:", out_dir / cfg["output"]["assignment_report"])
    print("Mission YAML directory:", mission_dir)


if __name__ == "__main__":
    main()
