# Evaluation report: `impl_a`

**INTERNAL PRISM-STYLE METRICS.** They mirror the documented Theme 05 categories; they are *not* Samsung scores.

| Scenario | Pass | Score | TC | IR | RL | SP | first-response p50 (s) | cancel latency (s) |
|---|---|---|---|---|---|---|---|---|
| backchannel_and_status_question | yes | 97.6 | 1.00 | 1.00 | 0.84 | 1.00 | 0.70 | - |
| content_free_interrupt | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.25 | - |
| deadline_governor | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| duplicate_booking_request | yes | 96.2 | 1.00 | n/a | 0.83 | 1.00 | 0.75 | - |
| failed_clean_then_ok_anomaly | yes | 77.3 | 1.00 | n/a | 0.02 | 1.00 | 2.95 | - |
| interrupt_1ms_after_completion | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | - |
| interrupt_1ms_before_completion | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| malformed_protocol_inputs | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| malformed_tool_arguments | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| malformed_tool_manifest | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| non_cancellable_state_changing | yes | 98.6 | 1.00 | 1.00 | 0.91 | 1.00 | 0.55 | - |
| older_evidence_vs_newer_user_value | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| result_exactly_at_timeout | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.25 | - |
| retry_budget_exhausted | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| revert_value_reruns | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| state_changing_not_executed_retry | yes | 97.0 | 1.00 | n/a | 0.87 | 1.00 | 0.65 | - |
| state_changing_timeout_then_late_ok | yes | 91.9 | 1.00 | n/a | 0.65 | 1.00 | 1.25 | - |
| state_changing_unknown_error_no_retry | yes | 98.7 | 1.00 | n/a | 0.94 | 1.00 | 0.45 | - |
| twin_still_pending | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| two_interruptions_before_result | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000, 0.000 |
| unattributed_correction_marker | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| unknown_call_result | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| A_normal_search | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.25 | - |
| B_destination_correction | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| C_timeout_retry | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| D2_booking_cancel_honoured | yes | 96.1 | 1.00 | 1.00 | 0.74 | 1.00 | 1.00 | 0.000 |
| D_booking_race | yes | 98.6 | 1.00 | 1.00 | 0.91 | 1.00 | 0.55 | 0.000 |
| E2_rapid_corrections_each_turn | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000, 0.000, 0.000 |
| E_rapid_corrections_one_turn | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| F2_evidence_after_goal_switch | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| F_evidence_after_correction | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| G_duplicate_input | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.15 | - |
| H2_same_time_correction_first | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| H_same_time_result_first | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | - |

**34/34 scenarios pass all checks; mean internal score 98.6.**

