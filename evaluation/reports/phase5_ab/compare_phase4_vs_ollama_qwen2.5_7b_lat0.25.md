# Evaluation comparison: `phase4` vs `ollama_qwen2.5_7b_lat0.25`

INTERNAL PRISM-STYLE METRICS on identical scenario files; not Samsung scores.

| Metric | phase4 | ollama_qwen2.5_7b_lat0.25 |
|---|---|---|
| scenarios passing all checks | 47/47 | 34/47 |
| mean internal score | 99.9 | 90.4 |
| mean task_completion | 1.00 | 0.83 |
| mean interruption_recovery | 1.00 | 1.00 |
| mean response_latency | 0.99 | 0.99 |
| mean safety_protocol | 1.00 | 1.00 |
| first substantive response, all turns: p50 / p99 (s) | 0.25 / 1.55 | 0.25 / 1.55 |
| first substantive response, status-question scenarios: p50 / p99 (s) | 0.25 / 0.25 | 0.25 / 0.25 |
| first substantive response, state-changing (booking) scenarios: p50 / p99 (s) | 0.25 / 0.25 | 0.25 / 0.25 |
| interruption -> cancel: max (s), n | 0.00, 16 | 0.00, 14 |
| turns with no substantive response | 12 | 8 |
| end-to-end to last final, median (s) | 2.75 | 2.65 |

| Scenario | phase4 pass / score | ollama_qwen2.5_7b_lat0.25 pass / score | change |
|---|---|---|---|
| A_normal_search | yes / 100.0 | yes / 100.0 |  |
| B_destination_correction | yes / 100.0 | yes / 100.0 |  |
| C_timeout_retry | yes / 100.0 | yes / 100.0 |  |
| D2_booking_cancel_honoured | yes / 100.0 | **no** / 79.5 | -20.5 |
| D_booking_race | yes / 100.0 | **no** / 69.2 | -30.8 |
| E2_rapid_corrections_each_turn | yes / 100.0 | yes / 100.0 |  |
| E_rapid_corrections_one_turn | yes / 100.0 | **no** / 80.0 | -20.0 |
| F2_evidence_after_goal_switch | yes / 100.0 | yes / 100.0 |  |
| F_evidence_after_correction | yes / 100.0 | **no** / 69.2 | -30.8 |
| G_duplicate_input | yes / 100.0 | yes / 100.0 |  |
| H2_same_time_correction_first | yes / 100.0 | yes / 100.0 |  |
| H_same_time_result_first | yes / 100.0 | yes / 100.0 |  |
| are_you_still_searching | yes / 100.0 | yes / 100.0 |  |
| backchannel_and_status_question | yes / 100.0 | yes / 100.0 |  |
| backchannels_during_search | yes / 97.9 | yes / 97.9 |  |
| change_the_destination | yes / 100.0 | yes / 100.0 |  |
| content_free_interrupt | yes / 100.0 | yes / 100.0 |  |
| correction_after_result | yes / 100.0 | yes / 100.0 |  |
| correction_to_unknown_slot | yes / 100.0 | yes / 100.0 |  |
| correction_with_immediate_turn_end | yes / 100.0 | yes / 100.0 |  |
| deadline_governor | yes / 100.0 | yes / 100.0 |  |
| duplicate_booking_request | yes / 100.0 | **no** / 38.5 | -61.5 |
| failed_clean_then_ok_anomaly | yes / 100.0 | **no** / 38.5 | -61.5 |
| goa_instead | yes / 100.0 | **no** / 60.0 | -40.0 |
| goal_switch_paraphrase | yes / 100.0 | yes / 100.0 |  |
| interrupt_1ms_after_completion | yes / 100.0 | yes / 100.0 |  |
| interrupt_1ms_before_completion | yes / 100.0 | yes / 100.0 |  |
| malformed_protocol_inputs | yes / 100.0 | yes / 100.0 |  |
| malformed_tool_arguments | yes / 100.0 | **no** / 53.9 | -46.1 |
| malformed_tool_manifest | yes / 100.0 | yes / 100.0 |  |
| no_wait_to_mumbai | yes / 100.0 | yes / 100.0 |  |
| non_cancellable_state_changing | yes / 100.0 | yes / 100.0 |  |
| older_evidence_vs_newer_user_value | yes / 100.0 | yes / 100.0 |  |
| partial_transcript_marker_then_value | yes / 100.0 | yes / 100.0 |  |
| repeating_the_same_value | yes / 96.5 | yes / 96.5 |  |
| result_exactly_at_timeout | yes / 100.0 | yes / 100.0 |  |
| retry_budget_exhausted | yes / 100.0 | yes / 100.0 |  |
| revert_value_reruns | yes / 100.0 | **no** / 79.5 | -20.5 |
| state_changing_not_executed_retry | yes / 100.0 | **no** / 77.8 | -22.2 |
| state_changing_timeout_then_late_ok | yes / 100.0 | **no** / 53.9 | -46.1 |
| state_changing_unknown_error_no_retry | yes / 100.0 | **no** / 69.2 | -30.8 |
| status_question_during_search | yes / 100.0 | yes / 100.0 |  |
| twin_still_pending | yes / 100.0 | **no** / 84.0 | -16.0 |
| two_interruptions_before_result | yes / 100.0 | yes / 100.0 |  |
| two_slots_one_utterance | yes / 100.0 | yes / 100.0 |  |
| unattributed_correction_marker | yes / 100.0 | yes / 100.0 |  |
| unknown_call_result | yes / 100.0 | yes / 100.0 |  |
