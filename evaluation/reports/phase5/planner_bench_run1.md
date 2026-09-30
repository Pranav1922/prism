# Planner-quality benchmark (INTERNAL; not a Samsung score)

| Backend | correct | valid | intent | tool/graph | slots | clarify | safety | repair | repeatable | p50 s | p95 s | startup s | memory MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ollama:qwen2.5:3b | 22% | 100% | 54% | 44% | 36% | 79% | 83% | 6% | 100% | 2.669 | 4.634 | 1.47 | 2283 |
| ollama:qwen2.5:7b | 28% | 94% | 75% | 62% | 54% | 69% | 92% | 11% | 100% | 5.005 | 9.892 | 3.47 | 4749 |
| ollama:llama3.1:8b | 11% | 83% | 82% | 43% | 0% | 18% | 100% | 17% | 100% | 7.221 | 16.802 | 3.51 | 5535 |

- `ollama:qwen2.5:3b` wrong on: missing_date (slots, clarify, safety); correct_destination (intent, slots); correct_date (intent, slots); two_slots (intent, slots); correct_origin (intent, slots); goal_switch (slots); parallel (tools); dependent_booking (tools); book_by_id (tools); book_missing_count (intent, tools, slots, clarify); unavailable (intent, tools); ambiguous_destination (clarify, safety); answer_clarification (slots); answer_passengers (slots)
- `ollama:qwen2.5:7b` wrong on: missing_date (clarify); correct_date (slots); two_slots (slots); correct_origin (slots); goal_switch (intent); parallel (tools, slots, clarify); dependent_booking (tools); book_by_id (valid); book_missing_count (clarify, safety); unavailable (intent, tools); ambiguous_destination (clarify); answer_clarification (slots); answer_passengers (intent, slots)
- `ollama:llama3.1:8b` wrong on: new_search (slots, clarify); missing_date (slots, clarify); correct_destination (slots, clarify); correct_date (slots); two_slots (slots, clarify); correct_origin (slots, clarify); goal_switch (intent, tools, slots); weather_simple (slots, clarify); parallel (tools, slots, clarify); dependent_booking (tools, slots, clarify); book_by_id (valid); book_missing_count (valid); unavailable (intent, tools); ambiguous_destination (valid); answer_clarification (slots, clarify); answer_passengers (slots)
