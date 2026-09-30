# Evaluation report: `ollama:qwen2.5:3b (planner latency measured)`

**INTERNAL PRISM-STYLE METRICS.** They mirror the documented Theme 05 categories; they are *not* Samsung scores.

| Scenario | Pass | Score | TC | IR | RL | SP | first-response p50 (s) | cancel latency (s) |
|---|---|---|---|---|---|---|---|---|
| backchannel_and_status_question | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| content_free_interrupt | yes | 100.0 | 1.00 | 1.00 | n/a | 1.00 | n/a | - |
| deadline_governor | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 4.05 | - |
| duplicate_booking_request | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 3.27 | - |
| failed_clean_then_ok_anomaly | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 5.43 | - |
| interrupt_1ms_after_completion | **NO** | 71.7 | 0.67 | 1.00 | 0.00 | 1.00 | 3.39 | - |
| interrupt_1ms_before_completion | **NO** | 75.0 | 0.75 | 1.00 | 0.00 | 1.00 | 3.24 | - |
| malformed_protocol_inputs | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 5.97 | - |
| malformed_tool_arguments | **NO** | 56.4 | 0.67 | n/a | 0.00 | 1.00 | 5.17 | - |
| malformed_tool_manifest | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 6.13 | - |
| non_cancellable_state_changing | **NO** | 65.0 | 0.50 | 1.00 | 0.00 | 1.00 | 5.04 | - |
| older_evidence_vs_newer_user_value | **NO** | 50.5 | 0.57 | n/a | 0.00 | 1.00 | 5.77 | - |
| result_exactly_at_timeout | yes | 85.0 | 1.00 | 1.00 | 0.00 | 1.00 | 5.87 | - |
| retry_budget_exhausted | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 4.51 | - |
| revert_value_reruns | **NO** | 76.5 | 0.83 | n/a | 0.43 | 1.00 | 1.85 | - |
| state_changing_not_executed_retry | **NO** | 54.7 | 0.67 | n/a | 0.00 | 0.89 | 5.60 | - |
| state_changing_timeout_then_late_ok | **NO** | 30.8 | 0.25 | n/a | 0.00 | 1.00 | 4.21 | - |
| state_changing_unknown_error_no_retry | **NO** | 46.1 | 0.50 | n/a | 0.00 | 1.00 | 3.33 | - |
| twin_still_pending | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 4.85 | - |
| two_interruptions_before_result | yes | 85.0 | 1.00 | 1.00 | 0.00 | 1.00 | 4.84 | - |
| unattributed_correction_marker | **NO** | 64.6 | 0.80 | n/a | 0.00 | 1.00 | 3.89 | - |
| unknown_call_result | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 5.68 | - |
| booking_count_never_given | **NO** | 56.4 | 0.67 | n/a | 0.00 | 1.00 | 5.63 | - |
| correction_before_first_plan | **NO** | 69.0 | 0.60 | 1.00 | 0.00 | 1.00 | 5.42 | - |
| injection_in_search_result | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 5.53 | - |
| missing_date_asks | **NO** | 73.1 | 0.75 | n/a | 0.50 | 1.00 | 2.71 | - |
| parallel_weather_and_flights | **NO** | 30.8 | 0.25 | n/a | 0.00 | 1.00 | 8.00 | - |
| rapid_corrections_during_planning | yes | 85.0 | 1.00 | 1.00 | 0.00 | 1.00 | 6.00 | - |
| search_then_book_first | **NO** | 52.3 | 0.60 | n/a | 0.00 | 1.00 | 6.02 | - |
| unavailable_capability | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 7.17 | - |
| A_normal_search | yes | 85.0 | 1.00 | 1.00 | 0.00 | 1.00 | 5.99 | - |
| B_destination_correction | **NO** | 51.5 | 0.60 | 0.50 | 0.00 | 1.00 | 4.17 | - |
| C_timeout_retry | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 5.55 | - |
| D2_booking_cancel_honoured | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 4.70 | - |
| D_booking_race | **NO** | 61.5 | 0.75 | n/a | 0.00 | 1.00 | 4.37 | - |
| E2_rapid_corrections_each_turn | **NO** | 36.7 | 0.67 | 0.00 | 0.00 | 1.00 | 4.31 | - |
| E_rapid_corrections_one_turn | **NO** | 50.4 | 0.57 | 0.50 | 0.00 | 1.00 | 3.37 | - |
| F2_evidence_after_goal_switch | **NO** | 35.9 | 0.33 | n/a | 0.00 | 1.00 | 3.34 | - |
| F_evidence_after_correction | **NO** | 68.1 | 0.86 | n/a | 0.00 | 1.00 | 3.90 | - |
| G_duplicate_input | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 3.01 | - |
| H2_same_time_correction_first | **NO** | 80.1 | 0.75 | 1.00 | 0.34 | 1.00 | 2.08 | - |
| H_same_time_result_first | **NO** | 55.9 | 0.67 | 0.50 | 0.12 | 1.00 | 2.68 | - |
| are_you_still_searching | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| backchannels_during_search | yes | 89.3 | 1.00 | 1.00 | 0.28 | 1.00 | 2.23 | - |
| change_the_destination | **NO** | 75.0 | 0.75 | 1.00 | 0.00 | 1.00 | 3.53 | - |
| correction_after_result | **NO** | 60.3 | 0.60 | 0.50 | 0.59 | 1.00 | 1.42 | - |
| correction_to_unknown_slot | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 5.01 | - |
| correction_with_immediate_turn_end | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 5.00 | - |
| goa_instead | yes | 85.0 | 1.00 | 1.00 | 0.00 | 1.00 | 3.83 | - |
| goal_switch_paraphrase | **NO** | 10.0 | 0.00 | 0.00 | 0.00 | 1.00 | 3.77 | - |
| no_wait_to_mumbai | **NO** | 57.5 | 0.75 | 0.50 | 0.00 | 1.00 | 4.12 | - |
| partial_transcript_marker_then_value | **NO** | 67.5 | 1.00 | 0.50 | 0.00 | 1.00 | 3.80 | - |
| repeating_the_same_value | **NO** | 42.0 | 0.80 | 0.00 | 0.00 | 1.00 | 5.21 | - |
| status_question_during_search | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| two_slots_one_utterance | **NO** | 40.0 | 0.75 | 0.00 | 0.00 | 1.00 | 3.02 | - |

**21/55 scenarios pass all checks; mean internal score 63.9.**

- `duplicate_booking_request` failed: final_response_present; calls:book_flight:{}; side_effects_min:book_flight
- `failed_clean_then_ok_anomaly` failed: final_response_present; calls:book_flight:{}; side_effects_min:book_flight
- `interrupt_1ms_after_completion` failed: final_snapshot_matches; calls:search_flights:{"destination": "BOM"}
- `interrupt_1ms_before_completion` failed: final_snapshot_matches
- `malformed_tool_arguments` failed: calls:book_flight:{}
- `non_cancellable_state_changing` failed: calls:book_flight:{}
- `older_evidence_vs_newer_user_value` failed: final_snapshot_matches; calls:search_flights:{"date": "Sun"}; clarification
- `revert_value_reruns` failed: calls:search_flights:{"destination": "BOM"}
- `state_changing_not_executed_retry` failed: calls:book_flight:{}; same_idempotency_key:book_flight
- `state_changing_timeout_then_late_ok` failed: final_response_present; calls:book_flight:{}; side_effects_min:book_flight
- `state_changing_unknown_error_no_retry` failed: calls:book_flight:{}
- `unattributed_correction_marker` failed: calls:search_flights:{"destination": "DEL"}
- `booking_count_never_given` failed: clarification
- `correction_before_first_plan` failed: final_snapshot_matches; calls:search_flights:{"destination": "BOM"}
- `missing_date_asks` failed: calls:search_flights:{}; clarification
- `parallel_weather_and_flights` failed: final_response_present; calls:search_flights:{"date": "Fri", "destination": "DEL"}; calls:get_weather:{}
- `search_then_book_first` failed: calls:book_flight:{"flight_id": "DEL-701", "passengers": 1}; side_effects_min:book_flight
- `B_destination_correction` failed: final_snapshot_matches; calls:search_flights:{"destination": "BOM"}; no_stale_rerun_after:fix
- `D2_booking_cancel_honoured` failed: final_response_present; calls:book_flight:{"passengers": 2}; side_effects_min:book_flight
- `D_booking_race` failed: calls:book_flight:{"passengers": 1}
- `E2_rapid_corrections_each_turn` failed: final_snapshot_matches; calls:search_flights:{"destination": "BOM"}; no_stale_rerun_after:m2; answer_not_grounded_on_superseded_work
- `E_rapid_corrections_one_turn` failed: final_snapshot_matches; calls:search_flights:{"destination": "BOM"}; calls:search_flights:{"destination": "GOI"}; no_stale_rerun_after:m1
- `F2_evidence_after_goal_switch` failed: final_response_present; clarification
- `F_evidence_after_correction` failed: clarification
- `H2_same_time_correction_first` failed: final_snapshot_matches
- `H_same_time_result_first` failed: final_snapshot_matches; calls:search_flights:{"destination": "BOM"}; no_stale_rerun_after:fix
- `change_the_destination` failed: final_snapshot_matches
- `correction_after_result` failed: final_snapshot_matches; calls:search_flights:{"destination": "BOM"}; no_stale_rerun_after:fix
- `correction_with_immediate_turn_end` failed: final_response_present
- `goal_switch_paraphrase` failed: final_response_present; no_stale_rerun_after:sw
- `no_wait_to_mumbai` failed: final_snapshot_matches; no_stale_rerun_after:fix
- `partial_transcript_marker_then_value` failed: no_stale_rerun_after:v
- `repeating_the_same_value` failed: final_snapshot_matches; no_unnecessary_cancel
- `two_slots_one_utterance` failed: final_snapshot_matches; no_stale_rerun_after:fix
