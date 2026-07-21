from pathlib import Path
import csv
import json
import math
import yaml


CONFIG_PATH = Path("configs/decision/v1_autonomous_route_selection.yaml")


def load_yaml(path):
    return yaml.safe_load(Path(path).read_text())


def load_json(path):
    return json.loads(Path(path).read_text())


def distance(a, b):
    dn = float(a["north_m"]) - float(b["north_m"])
    de = float(a["east_m"]) - float(b["east_m"])
    return math.sqrt(dn * dn + de * de)


def route_distance(route):
    return sum(distance(route[i], route[i + 1]) for i in range(len(route) - 1))


def route_order(route):
    return [wp["zone_name"] for wp in route]


def load_zone_event_scores(event_csv_path, label_weights):
    scores = {}

    path = Path(event_csv_path)
    if not path.exists():
        return scores

    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            zone = row.get("zone_name", "")
            label = row.get("class_name", "")

            if not zone:
                continue

            weight = float(label_weights.get(label, label_weights.get("default", 1.0)))
            scores[zone] = scores.get(zone, 0.0) + weight

    return scores


def arrival_priority_cost(route, zone_scores):
    cost = 0.0

    for index, waypoint in enumerate(route, start=1):
        zone = waypoint["zone_name"]
        urgency = float(zone_scores.get(zone, 0.0))
        cost += urgency * index

    return cost


def normalize_pair(value, other):
    highest = max(value, other)
    lowest = min(value, other)

    if highest == lowest:
        return 0.5

    return (value - lowest) / (highest - lowest)


def write_selected_mission(path, selected_mission, cfg, selected_name):
    selected_mission["mission"]["mission_name"] = "v1_ai_selected_" + selected_name + "_mission"
    selected_mission["logging"]["telemetry_csv_path"] = cfg["logging"]["selected_mission_telemetry_csv"]

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(yaml.safe_dump(selected_mission, sort_keys=False))


def main():
    cfg = load_yaml(CONFIG_PATH)

    original = load_yaml(cfg["input"]["original_mission_yaml"])
    optimized = load_yaml(cfg["input"]["optimized_mission_yaml"])
    comparison = load_json(cfg["input"]["route_comparison_json"])

    original_route = original["waypoints"]
    optimized_route = optimized["waypoints"]

    label_weights = cfg["event_priority_weights"]
    zone_scores = {}

    if cfg["selection"]["use_event_log_if_available"]:
        zone_scores = load_zone_event_scores(cfg["input"]["event_log_csv"], label_weights)

    original_distance = route_distance(original_route)
    optimized_distance = route_distance(optimized_route)

    original_event_cost = arrival_priority_cost(original_route, zone_scores)
    optimized_event_cost = arrival_priority_cost(optimized_route, zone_scores)

    original_distance_norm = normalize_pair(original_distance, optimized_distance)
    optimized_distance_norm = normalize_pair(optimized_distance, original_distance)

    original_event_norm = normalize_pair(original_event_cost, optimized_event_cost)
    optimized_event_norm = normalize_pair(optimized_event_cost, original_event_cost)

    dw = float(cfg["selection"]["distance_weight"])
    ew = float(cfg["selection"]["event_priority_weight"])

    original_score = dw * original_distance_norm + ew * original_event_norm
    optimized_score = dw * optimized_distance_norm + ew * optimized_event_norm

    improvement = float(comparison["improvement_percent"])
    min_improvement = float(cfg["selection"]["minimum_distance_improvement_percent"])

    if improvement >= min_improvement and optimized_score <= original_score:
        selected_name = "optimized"
        selected_mission = optimized
    else:
        selected_name = "original"
        selected_mission = original

    out_dir = Path(cfg["output"]["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    decision = {
        "selected_route": selected_name,
        "original_route_distance_m": round(original_distance, 3),
        "optimized_route_distance_m": round(optimized_distance, 3),
        "distance_improvement_percent": round(improvement, 3),
        "original_event_arrival_cost": round(original_event_cost, 3),
        "optimized_event_arrival_cost": round(optimized_event_cost, 3),
        "original_score": round(original_score, 4),
        "optimized_score": round(optimized_score, 4),
        "zone_event_scores": zone_scores,
        "original_route_order": route_order(original_route),
        "optimized_route_order": route_order(optimized_route),
    }

    decision_json_path = out_dir / cfg["output"]["decision_json"]
    decision_report_path = out_dir / cfg["output"]["decision_report"]

    decision_json_path.write_text(json.dumps(decision, indent=2))

    report = "# V1 Autonomous Route Selection Decision\n\n"
    report += "Selected route: " + selected_name + "\n\n"
    report += "Original distance: " + str(round(original_distance, 3)) + " m\n\n"
    report += "Optimized distance: " + str(round(optimized_distance, 3)) + " m\n\n"
    report += "Distance improvement: " + str(round(improvement, 3)) + " percent\n\n"
    report += "Original route score: " + str(round(original_score, 4)) + "\n\n"
    report += "Optimized route score: " + str(round(optimized_score, 4)) + "\n\n"
    report += "Original route:\n" + " -> ".join(decision["original_route_order"]) + "\n\n"
    report += "Optimized route:\n" + " -> ".join(decision["optimized_route_order"]) + "\n\n"
    report += "Decision logic: lower score is better. The score combines route distance and event-priority arrival cost.\n"

    decision_report_path.write_text(report)

    write_selected_mission(
        cfg["output"]["selected_mission_yaml"],
        selected_mission,
        cfg,
        selected_name,
    )

    print("Autonomous route selection completed.")
    print("Selected route:", selected_name)
    print("Original score:", round(original_score, 4))
    print("Optimized score:", round(optimized_score, 4))
    print("Decision report:", decision_report_path)
    print("Selected mission YAML:", cfg["output"]["selected_mission_yaml"])


if __name__ == "__main__":
    main()
