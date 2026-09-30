# Planner-quality benchmark (INTERNAL; not a Samsung score)

| Backend | correct | valid | intent | tool/graph | slots | clarify | safety | repair | repeatable | p50 s | p95 s | startup s | memory MiB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ollama:qwen2.5:3b | 44% | 100% | 85% | 44% | 64% | 79% | 83% | 6% | 100% | 3.781 | 6.278 | 1.74 | 2283 |
| ollama:qwen2.5:7b | 61% | 100% | 92% | 67% | 79% | 86% | 92% | 0% | 100% | 6.134 | 9.538 | 3.27 | 4749 |
| ollama:llama3.1:8b | 28% | 100% | 77% | 44% | 21% | 57% | 100% | 0% | 100% | 7.897 | 11.624 | 3.86 | 5535 |

- `ollama:qwen2.5:3b` wrong on: missing_date (slots, clarify, safety); correct_destination (slots); correct_origin (slots); goal_switch (slots); parallel (tools); dependent_booking (tools); book_by_id (tools); book_missing_count (intent, tools, slots, clarify); unavailable (intent, tools); ambiguous_destination (clarify, safety)
- `ollama:qwen2.5:7b` wrong on: correct_origin (slots); parallel (tools, slots); dependent_booking (tools); book_by_id (slots); book_missing_count (clarify, safety); unavailable (intent, tools); ambiguous_destination (clarify)
- `ollama:llama3.1:8b` wrong on: new_search (slots); missing_date (slots, clarify); correct_destination (slots); two_slots (slots, clarify); correct_origin (slots); goal_switch (intent, tools, slots); weather_simple (slots, clarify); parallel (tools, slots); dependent_booking (tools, slots); book_by_id (slots, clarify); book_missing_count (intent, tools, slots, clarify); unavailable (intent, tools); ambiguous_destination (clarify)
