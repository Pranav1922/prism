# Evaluation report: `impl_a_duplex`

**INTERNAL PRISM-STYLE METRICS.** They mirror the documented Theme 05 categories; they are *not* Samsung scores.

| Scenario | Pass | Score | TC | IR | RL | SP | first-response p50 (s) | cancel latency (s) |
|---|---|---|---|---|---|---|---|---|
| backchannel_and_status_question | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| content_free_interrupt | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| deadline_governor | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| duplicate_booking_request | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| failed_clean_then_ok_anomaly | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| interrupt_1ms_after_completion | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| interrupt_1ms_before_completion | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| malformed_protocol_inputs | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| malformed_tool_arguments | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| malformed_tool_manifest | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| non_cancellable_state_changing | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | - |
| older_evidence_vs_newer_user_value | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| result_exactly_at_timeout | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| retry_budget_exhausted | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| revert_value_reruns | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| state_changing_not_executed_retry | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| state_changing_timeout_then_late_ok | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| state_changing_unknown_error_no_retry | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| twin_still_pending | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| two_interruptions_before_result | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| unattributed_correction_marker | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| unknown_call_result | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| demo_audio_interruption | yes | 97.1 | 1.00 | 1.00 | 0.81 | 1.00 | 0.82 | - |
| demo_early_retrieval | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| demo_ticket_image | yes | 95.3 | 1.00 | n/a | 0.80 | 1.00 | 0.85 | - |
| booking_count_never_given | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| correction_before_first_plan | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| injection_in_search_result | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| missing_date_asks | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.12 | - |
| parallel_weather_and_flights | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| paraphrased_request_and_correction | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| rapid_corrections_during_planning | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| search_then_book_first | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.12 | - |
| unavailable_capability | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| A_normal_search | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| B_destination_correction | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| C_timeout_retry | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| D2_booking_cancel_honoured | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| D_booking_race | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| E2_rapid_corrections_each_turn | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| E_rapid_corrections_one_turn | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| F2_evidence_after_goal_switch | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| F_evidence_after_correction | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| G_duplicate_input | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.12 | - |
| H2_same_time_correction_first | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| H_same_time_result_first | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| are_you_still_searching | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| backchannels_during_search | yes | 99.0 | 1.00 | 1.00 | 0.94 | 1.00 | 0.33 | - |
| change_the_destination | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| correction_after_result | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| correction_to_unknown_slot | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.00 | - |
| correction_with_immediate_turn_end | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| goa_instead | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| goal_switch_paraphrase | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| no_wait_to_mumbai | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| partial_transcript_marker_then_value | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| repeating_the_same_value | yes | 97.6 | 1.00 | 1.00 | 0.84 | 1.00 | 0.57 | - |
| status_question_during_search | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| two_slots_one_utterance | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |

**59/59 scenarios pass all checks; mean internal score 99.8.**

