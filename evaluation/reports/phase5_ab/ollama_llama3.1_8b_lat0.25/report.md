# Evaluation report: `ollama:llama3.1:8b (planner latency 0.25)`

**INTERNAL PRISM-STYLE METRICS.** They mirror the documented Theme 05 categories; they are *not* Samsung scores.

| Scenario | Pass | Score | TC | IR | RL | SP | first-response p50 (s) | cancel latency (s) |
|---|---|---|---|---|---|---|---|---|
| backchannel_and_status_question | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | - |
| content_free_interrupt | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.25 | - |
| deadline_governor | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| duplicate_booking_request | **NO** | 38.5 | 0.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| failed_clean_then_ok_anomaly | **NO** | 38.5 | 0.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| interrupt_1ms_after_completion | **NO** | 86.7 | 0.67 | 1.00 | 1.00 | 1.00 | 0.12 | - |
| interrupt_1ms_before_completion | **NO** | 60.0 | 0.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| malformed_protocol_inputs | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| malformed_tool_arguments | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| malformed_tool_manifest | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| non_cancellable_state_changing | **NO** | 80.0 | 0.50 | 1.00 | 1.00 | 1.00 | 0.12 | - |
| older_evidence_vs_newer_user_value | **NO** | 68.4 | 0.50 | n/a | 0.96 | 1.00 | 0.38 | - |
| result_exactly_at_timeout | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.25 | - |
| retry_budget_exhausted | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| revert_value_reruns | **NO** | 79.5 | 0.67 | n/a | 1.00 | 1.00 | 0.25 | - |
| state_changing_not_executed_retry | **NO** | 77.8 | 0.67 | n/a | 1.00 | 0.89 | 0.25 | - |
| state_changing_timeout_then_late_ok | **NO** | 53.9 | 0.25 | n/a | 1.00 | 1.00 | 0.25 | - |
| state_changing_unknown_error_no_retry | **NO** | 69.2 | 0.50 | n/a | 1.00 | 1.00 | 0.25 | - |
| twin_still_pending | **NO** | 84.0 | 0.60 | 1.00 | 1.00 | 1.00 | 0.05 | 0.000 |
| two_interruptions_before_result | **NO** | 60.0 | 0.00 | 1.00 | 1.00 | 1.00 | 0.05 | 0.000 |
| unattributed_correction_marker | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| unknown_call_result | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| booking_count_never_given | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| correction_before_first_plan | **NO** | 60.0 | 0.00 | 1.00 | 1.00 | 1.00 | 0.10 | - |
| injection_in_search_result | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| missing_date_asks | **NO** | 63.1 | 0.40 | n/a | 1.00 | 1.00 | 0.12 | - |
| parallel_weather_and_flights | **NO** | 89.7 | 0.83 | n/a | 1.00 | 1.00 | 0.25 | - |
| rapid_corrections_during_planning | **NO** | 60.0 | 0.00 | 1.00 | 1.00 | 1.00 | 0.05 | - |
| search_then_book_first | **NO** | 75.4 | 0.60 | n/a | 1.00 | 1.00 | 0.25 | - |
| unavailable_capability | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| A_normal_search | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.25 | - |
| B_destination_correction | **NO** | 60.0 | 0.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| C_timeout_retry | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| D2_booking_cancel_honoured | **NO** | 38.5 | 0.00 | n/a | 1.00 | 1.00 | 0.12 | - |
| D_booking_race | **NO** | 84.6 | 0.75 | n/a | 1.00 | 1.00 | 0.12 | - |
| E2_rapid_corrections_each_turn | **NO** | 73.3 | 0.33 | 1.00 | 1.00 | 1.00 | 0.00 | 0.000 |
| E_rapid_corrections_one_turn | **NO** | 59.5 | 0.57 | 0.33 | 1.00 | 1.00 | 0.12 | 0.000 |
| F2_evidence_after_goal_switch | **NO** | 59.0 | 0.33 | n/a | 1.00 | 1.00 | 0.12 | - |
| F_evidence_after_correction | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.25 | - |
| G_duplicate_input | yes | 100.0 | 1.00 | n/a | 1.00 | 1.00 | 0.15 | - |
| H2_same_time_correction_first | **NO** | 60.0 | 0.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| H_same_time_result_first | **NO** | 86.7 | 0.67 | 1.00 | 1.00 | 1.00 | 0.12 | - |
| are_you_still_searching | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | - |
| backchannels_during_search | yes | 97.9 | 1.00 | 1.00 | 0.86 | 1.00 | 0.65 | - |
| change_the_destination | **NO** | 60.0 | 0.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| correction_after_result | **NO** | 84.0 | 0.60 | 1.00 | 1.00 | 1.00 | 0.12 | - |
| correction_to_unknown_slot | **NO** | 38.5 | 0.00 | n/a | 1.00 | 1.00 | 0.12 | - |
| correction_with_immediate_turn_end | **NO** | 60.0 | 0.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| goa_instead | **NO** | 90.0 | 0.75 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| goal_switch_paraphrase | **NO** | 55.0 | 0.75 | 0.00 | 1.00 | 1.00 | 0.12 | - |
| no_wait_to_mumbai | **NO** | 60.0 | 0.00 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| partial_transcript_marker_then_value | **NO** | 90.0 | 0.75 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |
| repeating_the_same_value | yes | 96.5 | 1.00 | 1.00 | 0.77 | 1.00 | 0.90 | - |
| status_question_during_search | yes | 100.0 | 1.00 | 1.00 | 1.00 | 1.00 | 0.12 | - |
| two_slots_one_utterance | **NO** | 90.0 | 0.75 | 1.00 | 1.00 | 1.00 | 0.12 | 0.000 |

**21/55 scenarios pass all checks; mean internal score 79.8.**

- `duplicate_booking_request` failed: final_response_present; calls:book_flight:{}; side_effects_min:book_flight
- `failed_clean_then_ok_anomaly` failed: final_response_present; calls:book_flight:{}; side_effects_min:book_flight
- `interrupt_1ms_after_completion` failed: final_snapshot_matches; calls:search_flights:{"destination": "BOM"}
- `interrupt_1ms_before_completion` failed: final_response_present
- `non_cancellable_state_changing` failed: calls:book_flight:{}
- `older_evidence_vs_newer_user_value` failed: final_response_present; calls:search_flights:{"date": "Sun"}
- `revert_value_reruns` failed: calls:search_flights:{"destination": "DEL"}; calls:search_flights:{"destination": "BOM"}
- `state_changing_not_executed_retry` failed: calls:book_flight:{}; same_idempotency_key:book_flight
- `state_changing_timeout_then_late_ok` failed: final_response_present; calls:book_flight:{}; side_effects_min:book_flight
- `state_changing_unknown_error_no_retry` failed: calls:book_flight:{}
- `twin_still_pending` failed: final_snapshot_matches; calls:search_flights:{"destination": "DEL"}
- `two_interruptions_before_result` failed: final_response_present
- `correction_before_first_plan` failed: final_response_present; calls:search_flights:{"destination": "BOM"}
- `missing_date_asks` failed: final_response_present; calls:search_flights:{}; calls:search_flights:{"date": "Fri"}
- `parallel_weather_and_flights` failed: calls:get_weather:{}
- `rapid_corrections_during_planning` failed: final_response_present; calls:search_flights:{"destination": "GOI"}
- `search_then_book_first` failed: calls:book_flight:{"flight_id": "DEL-701", "passengers": 1}; side_effects_min:book_flight
- `B_destination_correction` failed: final_response_present; calls:search_flights:{"destination": "BOM"}
- `D2_booking_cancel_honoured` failed: final_response_present; calls:book_flight:{"passengers": 2}; side_effects_min:book_flight
- `D_booking_race` failed: calls:book_flight:{"passengers": 1}
- `E2_rapid_corrections_each_turn` failed: final_response_present; calls:search_flights:{"destination": "BOM"}
- `E_rapid_corrections_one_turn` failed: final_snapshot_matches; calls:search_flights:{"destination": "DEL"}; calls:search_flights:{"destination": "BOM"}; no_stale_rerun_after:m1; answer_not_grounded_on_superseded_work
- `F2_evidence_after_goal_switch` failed: final_response_present; clarification
- `H2_same_time_correction_first` failed: final_response_present
- `H_same_time_result_first` failed: final_snapshot_matches; calls:search_flights:{"destination": "BOM"}
- `change_the_destination` failed: final_response_present
- `correction_after_result` failed: final_snapshot_matches; calls:search_flights:{"destination": "BOM"}
- `correction_to_unknown_slot` failed: final_response_present
- `correction_with_immediate_turn_end` failed: final_response_present
- `goa_instead` failed: final_snapshot_matches
- `goal_switch_paraphrase` failed: final_snapshot_matches; no_stale_rerun_after:sw
- `no_wait_to_mumbai` failed: final_response_present
- `partial_transcript_marker_then_value` failed: final_snapshot_matches
- `two_slots_one_utterance` failed: final_snapshot_matches
