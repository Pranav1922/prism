# Evaluation comparison: `phase4` vs `ollama_qwen2.5_3b`

INTERNAL PRISM-STYLE METRICS on identical scenario files; not Samsung scores.

| Metric | phase4 | ollama_qwen2.5_3b |
|---|---|---|
| scenarios passing all checks | 47/47 | 18/47 |
| mean internal score | 99.9 | 63.8 |
| mean task_completion | 1.00 | 0.72 |
| mean interruption_recovery | 1.00 | 0.72 |
| mean response_latency | 0.99 | 0.10 |
| mean safety_protocol | 1.00 | 1.00 |
| first substantive response, all turns: p50 / p99 (s) | 0.25 / 1.55 | 4.37 / 8.00 |
| first substantive response, status-question scenarios: p50 / p99 (s) | 0.25 / 0.25 | 0.00 / 0.00 |
| first substantive response, state-changing (booking) scenarios: p50 / p99 (s) | 0.25 / 0.25 | 5.17 / 6.10 |
| interruption -> cancel: max (s), n | 0.00, 16 | n/a, 0 |
| turns with no substantive response | 12 | 46 |
| end-to-end to last final, median (s) | 2.75 | 7.34 |

| Scenario | phase4 pass / score | ollama_qwen2.5_3b pass / score | change |
|---|---|---|---|
| A_normal_search | yes / 100.0 | yes / 85.0 | -15.0 |
| B_destination_correction | yes / 100.0 | **no** / 51.5 | -48.5 |
| C_timeout_retry | yes / 100.0 | yes / 76.9 | -23.1 |
| D2_booking_cancel_honoured | yes / 100.0 | **no** / 15.4 | -84.6 |
| D_booking_race | yes / 100.0 | **no** / 61.5 | -38.5 |
| E2_rapid_corrections_each_turn | yes / 100.0 | **no** / 36.7 | -63.3 |
| E_rapid_corrections_one_turn | yes / 100.0 | **no** / 50.4 | -49.6 |
| F2_evidence_after_goal_switch | yes / 100.0 | **no** / 35.9 | -64.1 |
| F_evidence_after_correction | yes / 100.0 | **no** / 68.1 | -31.9 |
| G_duplicate_input | yes / 100.0 | yes / 76.9 | -23.1 |
| H2_same_time_correction_first | yes / 100.0 | **no** / 80.1 | -19.9 |
| H_same_time_result_first | yes / 100.0 | **no** / 55.9 | -44.1 |
| are_you_still_searching | yes / 100.0 | yes / 100.0 |  |
| backchannel_and_status_question | yes / 100.0 | yes / 100.0 |  |
| backchannels_during_search | yes / 97.9 | yes / 89.3 | -8.7 |
| change_the_destination | yes / 100.0 | **no** / 75.0 | -25.0 |
| content_free_interrupt | yes / 100.0 | yes / 100.0 |  |
| correction_after_result | yes / 100.0 | **no** / 60.3 | -39.7 |
| correction_to_unknown_slot | yes / 100.0 | yes / 76.9 | -23.1 |
| correction_with_immediate_turn_end | yes / 100.0 | **no** / 45.0 | -55.0 |
| deadline_governor | yes / 100.0 | yes / 76.9 | -23.1 |
| duplicate_booking_request | yes / 100.0 | **no** / 15.4 | -84.6 |
| failed_clean_then_ok_anomaly | yes / 100.0 | **no** / 15.4 | -84.6 |
| goa_instead | yes / 100.0 | yes / 85.0 | -15.0 |
| goal_switch_paraphrase | yes / 100.0 | **no** / 10.0 | -90.0 |
| interrupt_1ms_after_completion | yes / 100.0 | **no** / 71.7 | -28.3 |
| interrupt_1ms_before_completion | yes / 100.0 | **no** / 75.0 | -25.0 |
| malformed_protocol_inputs | yes / 100.0 | yes / 76.9 | -23.1 |
| malformed_tool_arguments | yes / 100.0 | **no** / 56.4 | -43.6 |
| malformed_tool_manifest | yes / 100.0 | yes / 76.9 | -23.1 |
| no_wait_to_mumbai | yes / 100.0 | **no** / 57.5 | -42.5 |
| non_cancellable_state_changing | yes / 100.0 | **no** / 65.0 | -35.0 |
| older_evidence_vs_newer_user_value | yes / 100.0 | **no** / 50.5 | -49.5 |
| partial_transcript_marker_then_value | yes / 100.0 | **no** / 67.5 | -32.5 |
| repeating_the_same_value | yes / 96.5 | **no** / 42.0 | -54.5 |
| result_exactly_at_timeout | yes / 100.0 | yes / 85.0 | -15.0 |
| retry_budget_exhausted | yes / 100.0 | yes / 76.9 | -23.1 |
| revert_value_reruns | yes / 100.0 | **no** / 76.5 | -23.5 |
| state_changing_not_executed_retry | yes / 100.0 | **no** / 54.7 | -45.3 |
| state_changing_timeout_then_late_ok | yes / 100.0 | **no** / 30.8 | -69.2 |
| state_changing_unknown_error_no_retry | yes / 100.0 | **no** / 46.1 | -53.9 |
| status_question_during_search | yes / 100.0 | yes / 100.0 |  |
| twin_still_pending | yes / 100.0 | yes / 76.9 | -23.1 |
| two_interruptions_before_result | yes / 100.0 | yes / 85.0 | -15.0 |
| two_slots_one_utterance | yes / 100.0 | **no** / 40.0 | -60.0 |
| unattributed_correction_marker | yes / 100.0 | **no** / 64.6 | -35.4 |
| unknown_call_result | yes / 100.0 | yes / 76.9 | -23.1 |
