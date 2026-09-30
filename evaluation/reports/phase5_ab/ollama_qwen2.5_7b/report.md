# Evaluation report: `ollama:qwen2.5:7b (planner latency measured)`

**INTERNAL PRISM-STYLE METRICS.** They mirror the documented Theme 05 categories; they are *not* Samsung scores.

| Scenario | Pass | Score | TC | IR | RL | SP | first-response p50 (s) | cancel latency (s) |
|---|---|---|---|---|---|---|---|---|
| backchannel_and_status_question | **NO** | 73.3 | 0.33 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| content_free_interrupt | **NO** | 52.9 | 0.00 | 1.00 | n/a | 1.00 | n/a | - |
| deadline_governor | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 7.98 | - |
| duplicate_booking_request | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 5.07 | - |
| failed_clean_then_ok_anomaly | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 8.00 | - |
| interrupt_1ms_after_completion | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 8.00 | - |
| interrupt_1ms_before_completion | yes | 85.0 | 1.00 | 1.00 | 0.00 | 1.00 | 7.27 | - |
| malformed_protocol_inputs | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 8.00 | - |
| malformed_tool_arguments | **NO** | 56.4 | 0.67 | n/a | 0.00 | 1.00 | 8.00 | - |
| malformed_tool_manifest | **NO** | 35.9 | 0.33 | n/a | 0.00 | 1.00 | 8.00 | - |
| non_cancellable_state_changing | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 8.00 | - |
| older_evidence_vs_newer_user_value | **NO** | 46.1 | 0.50 | n/a | 0.00 | 1.00 | 6.68 | - |
| result_exactly_at_timeout | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 8.00 | - |
| retry_budget_exhausted | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 7.70 | - |
| revert_value_reruns | **NO** | 66.7 | 0.83 | n/a | 0.00 | 1.00 | 5.09 | - |
| state_changing_not_executed_retry | **NO** | 54.7 | 0.67 | n/a | 0.00 | 0.89 | 7.68 | - |
| state_changing_timeout_then_late_ok | **NO** | 30.8 | 0.25 | n/a | 0.00 | 1.00 | 4.81 | - |
| state_changing_unknown_error_no_retry | **NO** | 46.1 | 0.50 | n/a | 0.00 | 1.00 | 4.00 | - |
| twin_still_pending | **NO** | 64.6 | 0.80 | n/a | 0.00 | 1.00 | 7.19 | - |
| two_interruptions_before_result | **NO** | 75.0 | 0.75 | 1.00 | 0.00 | 1.00 | 7.02 | - |
| unattributed_correction_marker | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 8.00 | - |
| unknown_call_result | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 8.00 | - |
| booking_count_never_given | **NO** | 56.4 | 0.67 | n/a | 0.00 | 1.00 | 8.00 | - |
| correction_before_first_plan | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 8.00 | - |
| injection_in_search_result | **NO** | 46.1 | 0.50 | n/a | 0.00 | 1.00 | 7.62 | - |
| missing_date_asks | **NO** | 40.0 | 0.40 | n/a | 0.00 | 1.00 | 7.57 | - |
| parallel_weather_and_flights | **NO** | 66.7 | 0.83 | n/a | 0.00 | 1.00 | 6.92 | - |
| rapid_corrections_during_planning | yes | 85.0 | 1.00 | 1.00 | 0.00 | 1.00 | 6.83 | - |
| search_then_book_first | **NO** | 30.8 | 0.25 | n/a | 0.00 | 1.00 | 8.00 | - |
| unavailable_capability | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 5.14 | - |
| A_normal_search | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 8.00 | - |
| B_destination_correction | **NO** | 67.5 | 1.00 | 0.50 | 0.00 | 1.00 | 5.97 | - |
| C_timeout_retry | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 8.00 | - |
| D2_booking_cancel_honoured | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 5.93 | - |
| D_booking_race | **NO** | 61.5 | 0.75 | n/a | 0.00 | 1.00 | 5.86 | - |
| E2_rapid_corrections_each_turn | **NO** | 58.3 | 0.33 | 1.00 | 0.00 | 1.00 | 5.84 | - |
| E_rapid_corrections_one_turn | **NO** | 67.9 | 0.57 | 1.00 | 0.00 | 1.00 | 7.37 | - |
| F2_evidence_after_goal_switch | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 5.66 | - |
| F_evidence_after_correction | **NO** | 46.1 | 0.50 | n/a | 0.00 | 1.00 | 7.03 | - |
| G_duplicate_input | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 5.50 | - |
| H2_same_time_correction_first | yes | 85.0 | 1.00 | 1.00 | 0.00 | 1.00 | 5.78 | - |
| H_same_time_result_first | **NO** | 78.3 | 0.83 | 1.00 | 0.00 | 1.00 | 6.91 | - |
| are_you_still_searching | **NO** | 73.3 | 0.33 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| backchannels_during_search | yes | 85.0 | 1.00 | 1.00 | 0.00 | 1.00 | 6.17 | - |
| change_the_destination | **NO** | 40.0 | 0.75 | 0.00 | 0.00 | 1.00 | 6.34 | - |
| correction_after_result | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 7.92 | - |
| correction_to_unknown_slot | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 8.00 | - |
| correction_with_immediate_turn_end | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 7.02 | - |
| goa_instead | yes | 85.0 | 1.00 | 1.00 | 0.00 | 1.00 | 6.84 | - |
| goal_switch_paraphrase | yes | 85.0 | 1.00 | 1.00 | 0.00 | 1.00 | 5.88 | - |
| no_wait_to_mumbai | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 7.04 | - |
| partial_transcript_marker_then_value | yes | 85.0 | 1.00 | 1.00 | 0.00 | 1.00 | 7.09 | - |
| repeating_the_same_value | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 8.00 | - |
| status_question_during_search | **NO** | 73.3 | 0.33 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| two_slots_one_utterance | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 8.00 | - |

**11/55 scenarios pass all checks; mean internal score 52.7.**

- `backchannel_and_status_question` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `content_free_interrupt` failed: final_response_present
- `duplicate_booking_request` failed: final_response_present; calls:book_flight:{}; side_effects_min:book_flight
- `failed_clean_then_ok_anomaly` failed: final_response_present; calls:book_flight:{}; side_effects_min:book_flight
- `interrupt_1ms_after_completion` failed: final_response_present; calls:search_flights:{"destination": "DEL"}; calls:search_flights:{"destination": "BOM"}
- `malformed_protocol_inputs` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `malformed_tool_arguments` failed: clarification
- `malformed_tool_manifest` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `non_cancellable_state_changing` failed: calls:book_flight:{}; clarification
- `older_evidence_vs_newer_user_value` failed: final_response_present; calls:search_flights:{"date": "Sun"}
- `result_exactly_at_timeout` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `revert_value_reruns` failed: calls:search_flights:{"destination": "BOM"}
- `state_changing_not_executed_retry` failed: calls:book_flight:{}; same_idempotency_key:book_flight
- `state_changing_timeout_then_late_ok` failed: final_response_present; calls:book_flight:{}; side_effects_min:book_flight
- `state_changing_unknown_error_no_retry` failed: calls:book_flight:{}
- `twin_still_pending` failed: calls:search_flights:{"destination": "DEL"}
- `two_interruptions_before_result` failed: final_snapshot_matches
- `unattributed_correction_marker` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `unknown_call_result` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `booking_count_never_given` failed: clarification
- `correction_before_first_plan` failed: final_response_present; calls:search_flights:{"destination": "BOM"}
- `injection_in_search_result` failed: final_response_present
- `missing_date_asks` failed: final_response_present; calls:search_flights:{}; calls:search_flights:{"date": "Fri"}
- `parallel_weather_and_flights` failed: calls:get_weather:{}
- `search_then_book_first` failed: final_response_present; calls:book_flight:{"flight_id": "DEL-701", "passengers": 1}; side_effects_min:book_flight
- `A_normal_search` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `B_destination_correction` failed: no_stale_rerun_after:fix
- `C_timeout_retry` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `D2_booking_cancel_honoured` failed: final_response_present; calls:book_flight:{"passengers": 2}; side_effects_min:book_flight
- `D_booking_race` failed: calls:book_flight:{"passengers": 1}
- `E2_rapid_corrections_each_turn` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `E_rapid_corrections_one_turn` failed: final_snapshot_matches; calls:search_flights:{"destination": "DEL"}; calls:search_flights:{"destination": "BOM"}
- `F_evidence_after_correction` failed: final_response_present; calls:search_flights:{"date": "Sat"}
- `G_duplicate_input` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `H_same_time_result_first` failed: calls:search_flights:{"destination": "DEL"}
- `are_you_still_searching` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `change_the_destination` failed: final_snapshot_matches; answer_not_grounded_on_superseded_work
- `correction_after_result` failed: final_response_present; calls:search_flights:{"destination": "BOM"}
- `correction_to_unknown_slot` failed: final_response_present
- `correction_with_immediate_turn_end` failed: final_response_present
- `no_wait_to_mumbai` failed: final_response_present
- `repeating_the_same_value` failed: final_response_present; calls:search_flights:{"destination": "BOM"}
- `status_question_during_search` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `two_slots_one_utterance` failed: final_response_present
