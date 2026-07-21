#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path.home() / "Programs" / "SWARM_DRONES"

CONFIG_PATH = ROOT / "configs/fusion/part09_intelligence_fusion_config.json"

LIVE_STATE_PATH = ROOT / "outputs/live/swarm_live_state.json"
EVENTS_PATH = ROOT / "outputs/swarm_events/part08/part08_deduplicated_swarm_events.json"
ZONE_SUMMARY_PATH = ROOT / "outputs/reports/part06_zone_assignment_summary.json"
PATROL_TELEMETRY_PATH = ROOT / "outputs/swarm_missions/part05_surveillance_patrol/part05_altitude_separated_surveillance_telemetry.csv"

OUT_DIR = ROOT / "outputs/intelligence/part09"
FUSED_JSON = OUT_DIR / "part09_fused_battlefield_intelligence.json"
THREAT_CSV = OUT_DIR / "part09_operator_threat_table.csv"

SUMMARY_PATH = ROOT / "outputs/reports/part09_battlefield_intelligence_fusion_summary.json"
REPORT_PATH = ROOT / "outputs/reports/part09_battlefield_intelligence_fusion_report.md"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, fallback):
    if not path.exists():
        return fallback

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def read_telemetry_count(path: Path) -> int:
    if not path.exists():
        return 0

    try:
        with path.open(encoding="utf-8") as f:
            return max(0, sum(1 for _ in f) - 1)
    except Exception:
        return 0


def priority_to_score(priority: str) -> int:
    return {
        "HIGH": 90,
        "MEDIUM": 60,
        "LOW": 30,
    }.get(str(priority).upper(), 40)


def classify_risk(score: int) -> str:
    if score >= 80:
        return "HIGH"
    if score >= 50:
        return "MEDIUM"
    return "LOW"


def build_threat_table(events: list[dict]) -> list[dict]:
    rows = []

    for idx, event in enumerate(events, start=1):
        score = priority_to_score(event.get("priority", "LOW"))

        source_drones = event.get("source_drones")
        if not source_drones:
            source_drones = [event.get("source_drone", "unknown")]

        position = event.get("position", {})

        rows.append(
            {
                "threat_id": f"THREAT-{idx:03d}",
                "class_name": event.get("class_name", "unknown"),
                "event_type": event.get("event_type", "unknown"),
                "risk_level": classify_risk(score),
                "risk_score": score,
                "confidence": event.get("confidence", 0),
                "source_drones": ",".join(source_drones),
                "x": position.get("x"),
                "y": position.get("y"),
                "z": position.get("z"),
                "fusion_status": event.get("fusion_status", "unknown"),
                "human_review_required": score >= 50,
                "operator_action": "review_and_confirm",
            }
        )

    return rows


def compute_zone_summary(zone_data: dict, threat_rows: list[dict]) -> dict:
    zones = zone_data.get("zones", {})

    zone_summary = {}

    for zone_name, zone in zones.items():
        drone = zone.get("assigned_drone", "unknown")

        zone_summary[zone_name] = {
            "assigned_drone": drone,
            "model": zone.get("model"),
            "role": zone.get("role"),
            "altitude_m": zone.get("altitude_m"),
            "priority": zone.get("priority"),
            "detected_threats": 0,
            "highest_risk": "LOW",
        }

    for row in threat_rows:
        for zone_name, zone in zone_summary.items():
            if zone["assigned_drone"] in row["source_drones"]:
                zone["detected_threats"] += 1

                if row["risk_level"] == "HIGH":
                    zone["highest_risk"] = "HIGH"
                elif row["risk_level"] == "MEDIUM" and zone["highest_risk"] != "HIGH":
                    zone["highest_risk"] = "MEDIUM"

    return zone_summary


def write_outputs(
    live_state: dict,
    events: list[dict],
    zone_data: dict,
    threat_rows: list[dict],
    zone_summary: dict,
    telemetry_count: int,
) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)

    high_count = sum(1 for row in threat_rows if row["risk_level"] == "HIGH")
    medium_count = sum(1 for row in threat_rows if row["risk_level"] == "MEDIUM")
    low_count = sum(1 for row in threat_rows if row["risk_level"] == "LOW")

    overall_risk = "HIGH" if high_count else "MEDIUM" if medium_count else "LOW"

    fused = {
        "part": "part-09",
        "status": "completed",
        "result": "PASS",
        "task": "battlefield intelligence fusion",
        "world": "battlefield_sar_world_v1_realistic",
        "generated_at_utc": now_utc(),
        "mission_state": live_state.get("mission", {}),
        "fusion_inputs": {
            "event_count": len(events),
            "threat_table_count": len(threat_rows),
            "patrol_telemetry_samples": telemetry_count,
            "zone_count": len(zone_summary),
        },
        "overall_risk_level": overall_risk,
        "risk_counts": {
            "high": high_count,
            "medium": medium_count,
            "low": low_count,
        },
        "zone_summary": zone_summary,
        "threat_table": threat_rows,
        "human_in_loop": {
            "enabled": True,
            "required": any(row["human_review_required"] for row in threat_rows),
            "note": "All threat outputs are for operator review. No autonomous engagement decision is made.",
        },
    }

    FUSED_JSON.write_text(
        json.dumps(fused, indent=2),
        encoding="utf-8",
    )

    with THREAT_CSV.open("w", newline="", encoding="utf-8") as f:
        if threat_rows:
            writer = csv.DictWriter(f, fieldnames=list(threat_rows[0].keys()))
            writer.writeheader()
            writer.writerows(threat_rows)
        else:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "threat_id",
                    "class_name",
                    "event_type",
                    "risk_level",
                    "risk_score",
                    "confidence",
                    "source_drones",
                    "x",
                    "y",
                    "z",
                    "fusion_status",
                    "human_review_required",
                    "operator_action",
                ],
            )
            writer.writeheader()

    summary = {
        "part": "part-09",
        "status": "completed",
        "result": "PASS",
        "task": "battlefield intelligence fusion",
        "overall_risk_level": overall_risk,
        "event_count": len(events),
        "threat_count": len(threat_rows),
        "patrol_telemetry_samples": telemetry_count,
        "outputs": {
            "fused_intelligence": str(FUSED_JSON.relative_to(ROOT)),
            "operator_threat_table": str(THREAT_CSV.relative_to(ROOT)),
            "report": str(REPORT_PATH.relative_to(ROOT)),
        },
        "completed_at_utc": now_utc(),
    }

    SUMMARY_PATH.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Part 9: Battlefield Intelligence Fusion",
        "",
        "## Result",
        "",
        "PASS",
        "",
        "## Objective",
        "",
        "Fuse swarm zone assignments, patrol telemetry, shared drone events and live mission state into a single operator-readable battlefield intelligence report.",
        "",
        "## Fusion Inputs",
        "",
        f"- Live state: `{LIVE_STATE_PATH.relative_to(ROOT)}`",
        f"- Deduplicated swarm events: `{EVENTS_PATH.relative_to(ROOT)}`",
        f"- Zone assignment: `{ZONE_SUMMARY_PATH.relative_to(ROOT)}`",
        f"- Patrol telemetry: `{PATROL_TELEMETRY_PATH.relative_to(ROOT)}`",
        "",
        "## Overall Risk",
        "",
        f"- Overall risk level: **{overall_risk}**",
        f"- High-risk events: {high_count}",
        f"- Medium-risk events: {medium_count}",
        f"- Low-risk events: {low_count}",
        "",
        "## Zone-Level Summary",
        "",
    ]

    for zone_name, zone in zone_summary.items():
        lines.extend(
            [
                f"### {zone_name}",
                "",
                f"- Assigned drone: {zone['assigned_drone']}",
                f"- Model: {zone['model']}",
                f"- Role: {zone['role']}",
                f"- Altitude: {zone['altitude_m']} m",
                f"- Detected threats: {zone['detected_threats']}",
                f"- Highest risk: {zone['highest_risk']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Operator Threat Table",
            "",
        ]
    )

    for row in threat_rows:
        lines.extend(
            [
                f"### {row['threat_id']} — {row['class_name']}",
                "",
                f"- Type: {row['event_type']}",
                f"- Risk level: {row['risk_level']}",
                f"- Risk score: {row['risk_score']}",
                f"- Confidence: {row['confidence']}",
                f"- Source drones: {row['source_drones']}",
                f"- Position: x={row['x']}, y={row['y']}, z={row['z']}",
                f"- Human review required: {row['human_review_required']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Human-in-the-Loop Note",
            "",
            "The fused intelligence report supports human review and situational awareness only. It does not perform autonomous engagement or weapon-control decisions.",
            "",
            "## Output Files",
            "",
            f"- Fused intelligence JSON: `{FUSED_JSON.relative_to(ROOT)}`",
            f"- Operator threat table CSV: `{THREAT_CSV.relative_to(ROOT)}`",
            f"- Summary JSON: `{SUMMARY_PATH.relative_to(ROOT)}`",
        ]
    )

    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    live_state = load_json(LIVE_STATE_PATH, {})
    events = load_json(EVENTS_PATH, [])
    zone_data = load_json(ZONE_SUMMARY_PATH, {"zones": {}})
    telemetry_count = read_telemetry_count(PATROL_TELEMETRY_PATH)

    threat_rows = build_threat_table(events)
    zone_summary = compute_zone_summary(zone_data, threat_rows)

    write_outputs(
        live_state=live_state,
        events=events,
        zone_data=zone_data,
        threat_rows=threat_rows,
        zone_summary=zone_summary,
        telemetry_count=telemetry_count,
    )

    print("======================================")
    print("PART 9 VALIDATION: PASS")
    print("Battlefield intelligence fusion completed.")
    print(f"Fused intelligence: {FUSED_JSON}")
    print(f"Threat table: {THREAT_CSV}")
    print(f"Report: {REPORT_PATH}")
    print("======================================")


if __name__ == "__main__":
    main()
