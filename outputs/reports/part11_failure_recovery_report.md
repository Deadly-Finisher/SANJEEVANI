# Part 11: Failure Simulation and Swarm Recovery

## Result

PASS

## Failure Scenario

- Failed drone: `drone_2`
- Model: `x500_mono_cam_2`
- Failure type: `communication_loss`
- Affected zone: `zone_center_road`
- Severity: `HIGH`

## Recovery Behaviour

The affected center-road zone is marked as degraded. The remaining drones support partial coverage:

- Drone 1 expands from left flank into center-left support.
- Drone 3 expands from right overwatch into center-right support.
- Operator alert and human approval are required.

## Timeline

### t = 0 s — mission_running

- Description: Three-drone surveillance mission is available from previous patrol output.

### t = 90 s — failure_detected

- Description: simulated link loss during center-road surveillance

### t = 95 s — operator_alert_generated

- Description: Operator is alerted before recovery reassignment is accepted.

### t = 100 s — recovery_reassignment_started

- Description: Remaining drones are assigned partial coverage of the failed center zone.

### t = 120 s — degraded_coverage_established

- Description: Center zone is not fully covered by its original drone, but is monitored by neighbouring drones.

## Coverage After Failure

### zone_left_flank

- Status: ACTIVE
- Coverage: normal plus partial center support

### zone_center_road

- Status: DEGRADED_BUT_MONITORED
- Coverage: split support from left and right drones

### zone_right_overwatch

- Status: ACTIVE
- Coverage: normal plus partial center support

## Important Limitation

This module simulates failure reasoning, degraded coverage and operator alerting. It does not claim real-time MAVLink failover or dynamic replanning. Those are kept as future scope.

## Output Files

- Timeline: `outputs/failure_recovery/part11/part11_failure_timeline.json`
- Recovery plan: `outputs/failure_recovery/part11/part11_recovery_plan.json`
- Dashboard state: `outputs/failure_recovery/part11/part11_recovery_dashboard_state.json`
- Summary: `outputs/reports/part11_failure_recovery_summary.json`