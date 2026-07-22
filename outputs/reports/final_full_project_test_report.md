# Final Full Project Test Report

## Result

PASS

## Modules Tested

- part05_surveillance_patrol: PASS
- part06_zone_assignment: PASS
- part08_event_sharing: PASS
- part09_intelligence_fusion: PASS
- part11_failure_recovery: PASS
- part12_rag_vlm_hitl: PASS

## Runtime Checks

- drone_1_feed_http: 200
- drone_2_feed_http: 200
- drone_3_feed_http: 200
- live_dashboard_http: 200

## Mission Outputs

- patrol_telemetry_rows: 126
- raw_events: 4
- shared_events: 4
- deduplicated_events: 4
- overall_risk: HIGH
- failure_recovery_status: DEGRADED_BUT_MONITORED
- uncertainty_status: CONTROLLED_UNCERTAINTY
- human_review_required: True
- final_mission_status: COMPLETED
- safety_status: SAFE
- minimum_3d_separation_m: 30.0

## Dashboards

- Live dashboard: http://127.0.0.1:8502
- Results dashboard: http://127.0.0.1:8503