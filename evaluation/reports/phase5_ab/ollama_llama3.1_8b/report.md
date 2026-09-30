# Evaluation report: `ollama:llama3.1:8b (planner latency measured)`

**INTERNAL PRISM-STYLE METRICS.** They mirror the documented Theme 05 categories; they are *not* Samsung scores.

| Scenario | Pass | Score | TC | IR | RL | SP | first-response p50 (s) | cancel latency (s) |
|---|---|---|---|---|---|---|---|---|
| backchannel_and_status_question | **NO** | 73.3 | 0.33 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| content_free_interrupt | **NO** | 52.9 | 0.00 | 1.00 | n/a | 1.00 | n/a | - |
| deadline_governor | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 7.28 | - |
| duplicate_booking_request | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 8.00 | - |
| failed_clean_then_ok_anomaly | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 8.00 | - |
| interrupt_1ms_after_completion | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 8.00 | - |
| interrupt_1ms_before_completion | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 7.80 | - |
| malformed_protocol_inputs | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 8.00 | - |
| malformed_tool_arguments | **NO** | 56.4 | 0.67 | n/a | 0.00 | 1.00 | 8.00 | - |
| malformed_tool_manifest | **NO** | 35.9 | 0.33 | n/a | 0.00 | 1.00 | 8.00 | - |
| non_cancellable_state_changing | **NO** | 52.9 | 0.00 | 1.00 | n/a | 1.00 | n/a | - |
| older_evidence_vs_newer_user_value | **NO** | 46.1 | 0.50 | n/a | 0.00 | 1.00 | 6.37 | - |
| result_exactly_at_timeout | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 8.00 | - |
| retry_budget_exhausted | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 6.39 | - |
| revert_value_reruns | **NO** | 56.4 | 0.67 | n/a | 0.00 | 1.00 | 4.03 | - |
| state_changing_not_executed_retry | **NO** | 34.2 | 0.33 | n/a | 0.00 | 0.89 | 8.00 | - |
| state_changing_timeout_then_late_ok | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 8.00 | - |
| state_changing_unknown_error_no_retry | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 8.00 | - |
| twin_still_pending | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 8.00 | - |
| two_interruptions_before_result | **NO** | 52.9 | 0.00 | 1.00 | n/a | 1.00 | n/a | - |
| unattributed_correction_marker | **NO** | 20.0 | 0.00 | n/a | n/a | 1.00 | n/a | - |
| unknown_call_result | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 8.00 | - |
| booking_count_never_given | **NO** | 56.4 | 0.67 | n/a | 0.00 | 1.00 | 8.00 | - |
| correction_before_first_plan | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 8.00 | - |
| injection_in_search_result | **NO** | 46.1 | 0.50 | n/a | 0.00 | 1.00 | 8.00 | - |
| missing_date_asks | **NO** | 40.0 | 0.40 | n/a | 0.00 | 1.00 | 7.73 | - |
| parallel_weather_and_flights | **NO** | 30.8 | 0.25 | n/a | 0.00 | 1.00 | 8.00 | - |
| rapid_corrections_during_planning | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 7.53 | - |
| search_then_book_first | **NO** | 30.8 | 0.25 | n/a | 0.00 | 1.00 | 7.99 | - |
| unavailable_capability | yes | 76.9 | 1.00 | n/a | 0.00 | 1.00 | 6.96 | - |
| A_normal_search | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 8.00 | - |
| B_destination_correction | **NO** | 34.0 | 0.60 | 0.00 | 0.00 | 1.00 | 4.96 | - |
| C_timeout_retry | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 8.00 | - |
| D2_booking_cancel_honoured | **NO** | 20.0 | 0.00 | n/a | n/a | 1.00 | n/a | - |
| D_booking_race | **NO** | 60.0 | 0.50 | n/a | n/a | 1.00 | n/a | - |
| E2_rapid_corrections_each_turn | **NO** | 52.9 | 0.00 | 1.00 | n/a | 1.00 | n/a | - |
| E_rapid_corrections_one_turn | **NO** | 64.7 | 0.25 | 1.00 | n/a | 1.00 | n/a | - |
| F2_evidence_after_goal_switch | **NO** | 73.3 | 0.67 | n/a | n/a | 1.00 | n/a | - |
| F_evidence_after_correction | **NO** | 30.8 | 0.25 | n/a | 0.00 | 1.00 | 8.00 | - |
| G_duplicate_input | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 5.50 | - |
| H2_same_time_correction_first | **NO** | 40.0 | 0.75 | 0.00 | 0.00 | 1.00 | 4.42 | - |
| H_same_time_result_first | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 7.91 | - |
| are_you_still_searching | **NO** | 73.3 | 0.33 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| backchannels_during_search | yes | 85.0 | 1.00 | 1.00 | 0.00 | 1.00 | 5.56 | - |
| change_the_destination | **NO** | 40.0 | 0.75 | 0.00 | 0.00 | 1.00 | 6.99 | - |
| correction_after_result | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 7.87 | - |
| correction_to_unknown_slot | **NO** | 15.4 | 0.00 | n/a | 0.00 | 1.00 | 7.38 | - |
| correction_with_immediate_turn_end | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 8.00 | - |
| goa_instead | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 7.79 | - |
| goal_switch_paraphrase | **NO** | 52.9 | 0.00 | 1.00 | n/a | 1.00 | n/a | - |
| no_wait_to_mumbai | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 7.76 | - |
| partial_transcript_marker_then_value | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 8.00 | - |
| repeating_the_same_value | **NO** | 45.0 | 0.00 | 1.00 | 0.00 | 1.00 | 8.00 | - |
| status_question_during_search | **NO** | 73.3 | 0.33 | 1.00 | 1.00 | 1.00 | 0.00 | - |
| two_slots_one_utterance | **NO** | 40.0 | 0.75 | 0.00 | 0.00 | 1.00 | 5.50 | - |

**4/55 scenarios pass all checks; mean internal score 43.5.**

- `backchannel_and_status_question` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `content_free_interrupt` failed: final_response_present
- `duplicate_booking_request` failed: final_response_present; calls:book_flight:{}; side_effects_min:book_flight
- `failed_clean_then_ok_anomaly` failed: final_response_present; calls:book_flight:{}; side_effects_min:book_flight
- `interrupt_1ms_after_completion` failed: final_response_present; calls:search_flights:{"destination": "DEL"}; calls:search_flights:{"destination": "BOM"}
- `interrupt_1ms_before_completion` failed: final_response_present
- `malformed_protocol_inputs` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `malformed_tool_arguments` failed: clarification
- `malformed_tool_manifest` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `non_cancellable_state_changing` failed: calls:book_flight:{}; clarification
- `older_evidence_vs_newer_user_value` failed: final_response_present; calls:search_flights:{"date": "Sun"}
- `result_exactly_at_timeout` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `revert_value_reruns` failed: calls:search_flights:{"destination": "DEL"}; calls:search_flights:{"destination": "BOM"}
- `state_changing_not_executed_retry` failed: calls:book_flight:{}; clarification; same_idempotency_key:book_flight
- `state_changing_timeout_then_late_ok` failed: final_response_present; calls:book_flight:{}; side_effects_min:book_flight; clarification
- `state_changing_unknown_error_no_retry` failed: calls:book_flight:{}; clarification
- `twin_still_pending` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `two_interruptions_before_result` failed: final_response_present
- `unattributed_correction_marker` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `unknown_call_result` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `booking_count_never_given` failed: clarification
- `correction_before_first_plan` failed: final_response_present; calls:search_flights:{"destination": "BOM"}
- `injection_in_search_result` failed: final_response_present
- `missing_date_asks` failed: final_response_present; calls:search_flights:{}; calls:search_flights:{"date": "Fri"}
- `parallel_weather_and_flights` failed: final_response_present; calls:search_flights:{"date": "Fri", "destination": "DEL"}; calls:get_weather:{}
- `rapid_corrections_during_planning` failed: final_response_present; calls:search_flights:{"destination": "GOI"}
- `search_then_book_first` failed: final_response_present; calls:book_flight:{"flight_id": "DEL-701", "passengers": 1}; side_effects_min:book_flight
- `A_normal_search` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `B_destination_correction` failed: final_snapshot_matches; calls:search_flights:{"destination": "BOM"}; no_stale_rerun_after:fix; answer_not_grounded_on_superseded_work
- `C_timeout_retry` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `D2_booking_cancel_honoured` failed: final_response_present; calls:book_flight:{"passengers": 2}; side_effects_min:book_flight
- `D_booking_race` failed: calls:book_flight:{"passengers": 1}; clarification
- `E2_rapid_corrections_each_turn` failed: final_response_present; calls:search_flights:{"destination": "DEL"}; calls:search_flights:{"destination": "BOM"}
- `E_rapid_corrections_one_turn` failed: final_response_present; calls:search_flights:{"destination": "DEL"}; calls:search_flights:{"destination": "BOM"}
- `F2_evidence_after_goal_switch` failed: final_response_present
- `F_evidence_after_correction` failed: final_response_present; calls:search_flights:{"date": "Sat"}; clarification
- `G_duplicate_input` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `H2_same_time_correction_first` failed: final_snapshot_matches; answer_not_grounded_on_superseded_work
- `H_same_time_result_first` failed: final_response_present; calls:search_flights:{"destination": "DEL"}; calls:search_flights:{"destination": "BOM"}
- `are_you_still_searching` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `change_the_destination` failed: final_snapshot_matches; answer_not_grounded_on_superseded_work
- `correction_after_result` failed: final_response_present; calls:search_flights:{"destination": "BOM"}
- `correction_to_unknown_slot` failed: final_response_present
- `correction_with_immediate_turn_end` failed: final_response_present
- `goa_instead` failed: final_response_present
- `goal_switch_paraphrase` failed: final_response_present
- `no_wait_to_mumbai` failed: final_response_present
- `partial_transcript_marker_then_value` failed: final_response_present
- `repeating_the_same_value` failed: final_response_present; calls:search_flights:{"destination": "BOM"}
- `status_question_during_search` failed: final_response_present; calls:search_flights:{"destination": "DEL"}
- `two_slots_one_utterance` failed: final_snapshot_matches; no_stale_rerun_after:fix
