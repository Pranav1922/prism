# Evaluation comparison: `after_scripted_t0` vs `after_rules`

INTERNAL PRISM-STYLE METRICS on identical scenario files; not Samsung scores.

| Metric | after_scripted_t0 | after_rules |
|---|---|---|
| scenarios passing all checks | 41/47 | 47/47 |
| mean internal score | 97.6 | 99.9 |
| mean task_completion | 1.00 | 1.00 |
| mean interruption_recovery | 0.91 | 1.00 |
| mean response_latency | 0.98 | 0.99 |
| mean safety_protocol | 1.00 | 1.00 |
| first substantive response, all turns: p50 / p99 (s) | 0.25 / 1.55 | 0.25 / 1.55 |
| first substantive response, status-question scenarios: p50 / p99 (s) | 0.25 / 1.55 | 0.25 / 0.25 |
| first substantive response, state-changing (booking) scenarios: p50 / p99 (s) | 0.25 / 0.25 | 0.25 / 0.25 |
| interruption -> cancel: max (s), n | 0.65, 19 | 0.00, 16 |
| turns with no substantive response | 12 | 12 |
| end-to-end to last final, median (s) | 2.75 | 2.75 |

| Scenario | after_scripted_t0 pass / score | after_rules pass / score | change |
|---|---|---|---|
| A_normal_search | yes / 100.0 | yes / 100.0 |  |
| B_destination_correction | yes / 100.0 | yes / 100.0 |  |
| C_timeout_retry | yes / 100.0 | yes / 100.0 |  |
| D2_booking_cancel_honoured | yes / 100.0 | yes / 100.0 |  |
| D_booking_race | yes / 100.0 | yes / 100.0 |  |
| E2_rapid_corrections_each_turn | yes / 100.0 | yes / 100.0 |  |
| E_rapid_corrections_one_turn | yes / 100.0 | yes / 100.0 |  |
| F2_evidence_after_goal_switch | yes / 100.0 | yes / 100.0 |  |
| F_evidence_after_correction | yes / 100.0 | yes / 100.0 |  |
| G_duplicate_input | yes / 100.0 | yes / 100.0 |  |
| H2_same_time_correction_first | yes / 100.0 | yes / 100.0 |  |
| H_same_time_result_first | yes / 100.0 | yes / 100.0 |  |
| are_you_still_searching | yes / 96.5 | yes / 100.0 | +3.5 |
| backchannel_and_status_question | yes / 100.0 | yes / 100.0 |  |
| backchannels_during_search | yes / 97.9 | yes / 97.9 |  |
| change_the_destination | **no** / 82.5 | yes / 100.0 | +17.5 |
| content_free_interrupt | yes / 100.0 | yes / 100.0 |  |
| correction_after_result | yes / 100.0 | yes / 100.0 |  |
| correction_to_unknown_slot | yes / 94.7 | yes / 100.0 | +5.3 |
| correction_with_immediate_turn_end | **no** / 82.5 | yes / 100.0 | +17.5 |
| deadline_governor | yes / 100.0 | yes / 100.0 |  |
| duplicate_booking_request | yes / 100.0 | yes / 100.0 |  |
| failed_clean_then_ok_anomaly | yes / 100.0 | yes / 100.0 |  |
| goa_instead | **no** / 82.5 | yes / 100.0 | +17.5 |
| goal_switch_paraphrase | yes / 100.0 | yes / 100.0 |  |
| interrupt_1ms_after_completion | yes / 100.0 | yes / 100.0 |  |
| interrupt_1ms_before_completion | yes / 100.0 | yes / 100.0 |  |
| malformed_protocol_inputs | yes / 100.0 | yes / 100.0 |  |
| malformed_tool_arguments | yes / 100.0 | yes / 100.0 |  |
| malformed_tool_manifest | yes / 100.0 | yes / 100.0 |  |
| no_wait_to_mumbai | **no** / 88.3 | yes / 100.0 | +11.7 |
| non_cancellable_state_changing | yes / 100.0 | yes / 100.0 |  |
| older_evidence_vs_newer_user_value | yes / 100.0 | yes / 100.0 |  |
| partial_transcript_marker_then_value | **no** / 88.3 | yes / 100.0 | +11.7 |
| repeating_the_same_value | yes / 96.5 | yes / 96.5 |  |
| result_exactly_at_timeout | yes / 100.0 | yes / 100.0 |  |
| retry_budget_exhausted | yes / 100.0 | yes / 100.0 |  |
| revert_value_reruns | yes / 100.0 | yes / 100.0 |  |
| state_changing_not_executed_retry | yes / 100.0 | yes / 100.0 |  |
| state_changing_timeout_then_late_ok | yes / 100.0 | yes / 100.0 |  |
| state_changing_unknown_error_no_retry | yes / 100.0 | yes / 100.0 |  |
| status_question_during_search | yes / 96.5 | yes / 100.0 | +3.5 |
| twin_still_pending | yes / 100.0 | yes / 100.0 |  |
| two_interruptions_before_result | yes / 100.0 | yes / 100.0 |  |
| two_slots_one_utterance | **no** / 82.5 | yes / 100.0 | +17.5 |
| unattributed_correction_marker | yes / 100.0 | yes / 100.0 |  |
| unknown_call_result | yes / 100.0 | yes / 100.0 |  |
