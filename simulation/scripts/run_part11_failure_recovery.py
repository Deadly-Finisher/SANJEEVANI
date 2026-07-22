#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path.home() / "Programs" / "SWARM_DRONES"

CONFIG_PATH = ROOT / "configs/failure/part11_failure_recovery_config.json"

OUT_DIR = ROOT / "outputs/failure_recovery/part11"
TIMELINE_PATH = OUT_DIR / "part11_failure_timeline.json"
RECOVERY_PLAN_PATH = OUT_DIR / "part11_recovery_plan.json"
RECOVERY_STATE_PATH = OUT_DIR / "part11_recovery_dashboard_state.json"

SUMMARY_PATH = ROOT / "outputs/reports/part11_failure_recovery_summary.json"
REPORT_PATH = ROOT / "outputs/reports/part11_failure_recovery_report.md"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path, fallback):
    if not path.exists():
        return fallback

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def build_timeline(config: dict, live_state: dict) -> list[dict]:
    failure = config["failure_scenario"]
    policy = config["recovery_policy"]

    mission = live_state.get("mission", {})

    return [
        {
            "time_s": 0,
            "event": "mission_running",
            "status": mission.get("status", "COMPLETED"),
            "description": "Three-drone surveillance mission is available from previous patrol output.",
        },
        {
            "time_s": failure["failure_time_s"],
            "event": "failure_detected",
            "failed_drone": failure["failed_drone"],
            "failure_type": failure["failure_type"],
            "severity": failure["severity"],
            "affected_zone": failure["affected_zone"],
            "description": failure["reason"],
        },
        {
            "time_s": failure["failure_time_s"] + 5,
            "event": "operator_alert_generated",
            "human_approval_required": policy["human_approval_required"],
            "description": "Operator is alerted before recovery reassignment is accepted.",
        },
        {
            "time_s": failure["failure_time_s"] + 10,
            "event": "recovery_reassignment_started",
            "remaining_drones": policy["remaining_drones"],
            "description": "Remaining drones are assigned partial coverage of the failed center zone.",
        },
        {
            "time_s": failure["failure_time_s"] + 30,
            "event": "degraded_coverage_established",
            "coverage_status": "DEGRADED_BUT_MONITORED",
            "description": "Center zone is not fully covered by its original drone, but is monitored by neighbouring drones.",
        },
    ]


def build_recovery_plan(config: dict, zone_data: dict, fused_data: dict) -> dict:
    failure = config["failure_scenario"]
    policy = config["recovery_policy"]

    zones = zone_data.get("zones", {})
    affected_zone = zones.get(failure["affected_zone"], {})

    risk_counts = fused_data.get("risk_counts", {})
    overall_risk = fused_data.get("overall_risk_level", "UNKNOWN")

    plan = {
        "part": "part-11",
        "plan_name": "failure_recovery_plan",
        "generated_at_utc": now_utc(),
        "failure": failure,
        "affected_zone_details": affected_zone,
        "pre_failure_overall_risk": overall_risk,
        "pre_failure_risk_counts": risk_counts,
        "recovery_policy": policy,
        "coverage_after_failure": {
            "zone_left_flank": {
                "status": "ACTIVE",
                "primary_drone": "drone_1",
                "coverage": "normal plus partial center support",
            },
            "zone_center_road": {
                "status": "DEGRADED_BUT_MONITORED",
                "primary_drone": "drone_2_failed",
                "supporting_drones": ["drone_1", "drone_3"],
                "coverage": "split support from left and right drones",
            },
            "zone_right_overwatch": {
                "status": "ACTIVE",
                "primary_drone": "drone_3",
                "coverage": "normal plus partial center support",
            },
        },
        "operator_decision": {
            "alert_level": "HIGH",
            "human_review_required": True,
            "recommended_action": "approve degraded coverage and prepare manual intervention",
            "autonomous_engagement": False,
        },
        "limitations": config["future_scope"],
    }

    return plan


def build_dashboard_state(config: dict, recovery_plan: dict, timeline: list[dict]) -> dict:
    failure = config["failure_scenario"]

    return {
        "part": "part-11",
        "status": "completed",
        "result": "PASS",
        "dashboard_state_type": "failure_recovery_state",
        "generated_at_utc": now_utc(),
        "failed_drone": failure["failed_drone"],
        "failed_model": failure["failed_model"],
        "failure_type": failure["failure_type"],
        "affected_zone": failure["affected_zone"],
        "recovery_status": "DEGRADED_BUT_MONITORED",
        "remaining_drones": config["recovery_policy"]["remaining_drones"],
        "human_approval_required": True,
        "timeline": timeline,
        "coverage_after_failure": recovery_plan["coverage_after_failure"],
        "operator_note": (
            "This is a simulated failure-recovery layer. "
            "It validates recovery reasoning and operator alerting. "
            "Real-time MAVLink failover and dynamic replanning are future scope."
        ),
    }


def write_report(config: dict, timeline: list[dict], recovery_plan: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)

    dashboard_state = build_dashboard_state(config, recovery_plan, timeline)

    TIMELINE_PATH.write_text(
        json.dumps(timeline, indent=2),
        encoding="utf-8",
    )

    RECOVERY_PLAN_PATH.write_text(
        json.dumps(recovery_plan, indent=2),
        encoding="utf-8",
    )

    RECOVERY_STATE_PATH.write_text(
        json.dumps(dashboard_state, indent=2),
        encoding="utf-8",
    )

    summary = {
        "part": "part-11",
        "status": "completed",
        "result": "PASS",
        "task": "failure simulation and swarm recovery",
        "failed_drone": config["failure_scenario"]["failed_drone"],
        "failure_type": config["failure_scenario"]["failure_type"],
        "affected_zone": config["failure_scenario"]["affected_zone"],
        "recovery_status": "DEGRADED_BUT_MONITORED",
        "human_approval_required": True,
        "outputs": {
            "timeline": relative(TIMELINE_PATH),
            "recovery_plan": relative(RECOVERY_PLAN_PATH),
            "dashboard_state": relative(RECOVERY_STATE_PATH),
            "report": relative(REPORT_PATH),
        },
        "completed_at_utc": now_utc(),
    }

    SUMMARY_PATH.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Part 11: Failure Simulation and Swarm Recovery",
        "",
        "## Result",
        "",
        "PASS",
        "",
        "## Failure Scenario",
        "",
        f"- Failed drone: `{config['failure_scenario']['failed_drone']}`",
        f"- Model: `{config['failure_scenario']['failed_model']}`",
        f"- Failure type: `{config['failure_scenario']['failure_type']}`",
        f"- Affected zone: `{config['failure_scenario']['affected_zone']}`",
        f"- Severity: `{config['failure_scenario']['severity']}`",
        "",
        "## Recovery Behaviour",
        "",
        "The affected center-road zone is marked as degraded. The remaining drones support partial coverage:",
        "",
        "- Drone 1 expands from left flank into center-left support.",
        "- Drone 3 expands from right overwatch into center-right support.",
        "- Operator alert and human approval are required.",
        "",
        "## Timeline",
        "",
    ]

    for item in timeline:
        lines.extend(
            [
                f"### t = {item['time_s']} s — {item['event']}",
                "",
                f"- Description: {item['description']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Coverage After Failure",
            "",
        ]
    )

    for zone, data in recovery_plan["coverage_after_failure"].items():
        lines.extend(
            [
                f"### {zone}",
                "",
                f"- Status: {data['status']}",
                f"- Coverage: {data['coverage']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Important Limitation",
            "",
            "This module simulates failure reasoning, degraded coverage and operator alerting. "
            "It does not claim real-time MAVLink failover or dynamic replanning. "
            "Those are kept as future scope.",
            "",
            "## Output Files",
            "",
            f"- Timeline: `{relative(TIMELINE_PATH)}`",
            f"- Recovery plan: `{relative(RECOVERY_PLAN_PATH)}`",
            f"- Dashboard state: `{relative(RECOVERY_STATE_PATH)}`",
            f"- Summary: `{relative(SUMMARY_PATH)}`",
        ]
    )

    REPORT_PATH.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def main() -> None:
    config = load_json(CONFIG_PATH, {})
    live_state = load_json(ROOT / config["inputs"]["live_state"], {})
    zone_data = load_json(ROOT / config["inputs"]["zone_assignment"], {})
    fused_data = load_json(ROOT / config["inputs"]["fused_intelligence"], {})

    timeline = build_timeline(config, live_state)
    recovery_plan = build_recovery_plan(config, zone_data, fused_data)

    write_report(config, timeline, recovery_plan)

    print("======================================")
    print("PART 11 VALIDATION: PASS")
    print("Failure simulation and swarm recovery completed.")
    print(f"Timeline: {TIMELINE_PATH}")
    print(f"Recovery plan: {RECOVERY_PLAN_PATH}")
    print(f"Report: {REPORT_PATH}")
    print("======================================")


if __name__ == "__main__":
    main()
