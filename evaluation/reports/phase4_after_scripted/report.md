# Evaluation report: `impl_a_scripted`

**INTERNAL PRISM-STYLE METRICS.** They mirror the documented Theme 05 categories; they are *not* Samsung scores.

| Scenario | Pass | Score | TC | IR | RL | SP | first-response p50 (s) | cancel latency (s) |
|---|---|---|---|---|---|---|---|---|
| backchannel_and_status_question | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | - |
| content_free_interrupt | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.25 | - |
| deadline_governor | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| duplicate_booking_request | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| failed_clean_then_ok_anomaly | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| interrupt_1ms_after_completion | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | - |
| interrupt_1ms_before_completion | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| malformed_protocol_inputs | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| malformed_tool_arguments | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| malformed_tool_manifest | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| non_cancellable_state_changing | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | - |
| older_evidence_vs_newer_user_value | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| result_exactly_at_timeout | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.25 | - |
| retry_budget_exhausted | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| revert_value_reruns | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| state_changing_not_executed_retry | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| state_changing_timeout_then_late_ok | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| state_changing_unknown_error_no_retry | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| twin_still_pending | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| two_interruptions_before_result | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000, 0.000 |
| unattributed_correction_marker | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| unknown_call_result | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| A_normal_search | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.25 | - |
| B_destination_correction | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| C_timeout_retry | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| D2_booking_cancel_honoured | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| D_booking_race | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| E2_rapid_corrections_each_turn | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000, 0.000, 0.000 |
| E_rapid_corrections_one_turn | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| F2_evidence_after_goal_switch | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| F_evidence_after_correction | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| G_duplicate_input | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.15 | - |
| H2_same_time_correction_first | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| H_same_time_result_first | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | - |
| are_you_still_searching | yes | 96.5 | 1.00 | 1.00 | 0.77 | 1.00 | 0.90 | - |
| backchannels_during_search | yes | 97.9 | 1.00 | 1.00 | 0.86 | 1.00 | 0.65 | - |
| change_the_destination | **NO** | 82.5 | 1.00 | 0.50 | 1.00 | 1.00 | 0.25 | 0.450 |
| correction_after_result | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.25 | - |
| correction_to_unknown_slot | yes | 94.7 | 1.00 | n/a | 0.77 | 1.00 | 0.90 | - |
| correction_with_immediate_turn_end | **NO** | 82.5 | 1.00 | 0.50 | 1.00 | 1.00 | 0.25 | 0.250 |
| goa_instead | **NO** | 82.5 | 1.00 | 0.50 | 1.00 | 1.00 | 0.25 | 0.450 |
| goal_switch_paraphrase | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.25 | - |
| no_wait_to_mumbai | **NO** | 88.3 | 1.00 | 0.67 | 1.00 | 1.00 | 0.25 | 0.450 |
| partial_transcript_marker_then_value | **NO** | 88.3 | 1.00 | 0.67 | 1.00 | 1.00 | 0.25 | 0.650 |
| repeating_the_same_value | yes | 96.5 | 1.00 | 1.00 | 0.77 | 1.00 | 0.90 | - |
| status_question_during_search | yes | 96.5 | 1.00 | 1.00 | 0.77 | 1.00 | 0.90 | - |
| two_slots_one_utterance | **NO** | 82.5 | 1.00 | 0.50 | 1.00 | 1.00 | 0.25 | 0.450 |

**41/47 scenarios pass all checks; mean internal score 97.6.**

- `change_the_destination` failed: cancelled:c1
- `correction_with_immediate_turn_end` failed: cancelled:c1
- `goa_instead` failed: cancelled:c1
- `no_wait_to_mumbai` failed: cancelled:c1
- `partial_transcript_marker_then_value` failed: cancelled:c1
- `two_slots_one_utterance` failed: cancelled:c1
