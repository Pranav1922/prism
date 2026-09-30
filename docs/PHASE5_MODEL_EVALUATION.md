# Phase 5 — Model Selection Evidence

**INTERNAL measurements only.**
- The machine is one development laptop: Apple M4 (10 cores), 16 GB, Metal GPU offload, Ollama 0.32.4, all models Q4_K_M.
- This says nothing about the evaluation environment: CPU-only x86 hosts would be several times slower for every model.
- These are not Samsung scores. Both the cases and the scenarios were written by the implementer.

## 1. Environment and candidates

| Candidate | Why considered | Local | Network | Size (Q4_K_M) | Context |
|---|---|---|---|---|---|
| `scripted` | deterministic regression baseline (not a model) | yes | no | — | — |
| `qwen2.5:3b` | smallest capable instruction model already cached | yes | no | 1.8 GB on disk / 2.3 GB loaded | 32k (8k used) |
| `qwen2.5:7b` | stronger reasoning, same family | yes | no | 4.5 GB / 4.7 GB | 32k (8k used) |
| `llama3.1:8b` | a different family, for comparison | yes | no | 4.7 GB / 5.5 GB | 128k (8k used) |
| remote (`openai:<model>`) | backend implemented | — | yes | — | — |

Notes on the candidate set:
- **Remote models were not measured.** No credentials exist in this environment, and none were requested.
- **No new model was downloaded.** Downloads need approval (PHASE2_PLAN §6); the three cached models were compared.
- **Decoding** is identical for all candidates: temperature 0, seed 7, grammar-constrained JSON (the same output schema), the same prompt (`p5.3`) and one repair attempt.

## 2. Planner-quality benchmark (offline, 18 cases × 3 repeats)

`python -m scripts.planner_bench` builds each case's state through the real kernel, then scores the validated proposal ([`tests/data/planner_cases.json`](../tests/data/planner_cases.json)). The cases cover:
- new search, missing value, corrections (1 or 2 slots), goal switch;
- parallel and dependent tasks, booking by id, booking without a count;
- injection in a tool result, an impossible request, an ambiguous destination;
- answering a clarification, and "nothing to do".

**Run 1** (first, honest; [`planner_bench_run1.md`](../evaluation/reports/phase5/planner_bench_run1.md)):

| Backend | correct | valid | intent | tools/graph | slots | clarify | safety | p50 s | p95 s |
|---|---|---|---|---|---|---|---|---|---|
| qwen2.5:3b | 22% | 100% | 54% | 44% | 36% | 79% | 83% | 2.67 | 4.63 |
| qwen2.5:7b | 28% | 94% | 75% | 62% | 54% | 69% | 92% | 5.01 | 9.89 |
| llama3.1:8b | 11% | 83% | 82% | 43% | 0% | 18% | 100% | 7.22 | 16.80 |

**Run 2** ([`planner_bench.md`](../evaluation/reports/phase5/planner_bench.md)). It follows two changes informed by run 1, so it is **not independent**:
1. A scoring fix: slots are judged on the resulting state, so a value the fast path already wrote counts.
2. Two generic validator normalisations: a value placed in the `slot` field, and `new_goal` on a correction or answer turn.

| Backend | correct | valid | intent | tools/graph | slots | clarify | safety | repair | repeatable | p50 s | p95 s | startup s | memory |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5:3b | 44% | 100% | 85% | 44% | 64% | 79% | 83% | 6% | 100% | 3.78 | 6.28 | 1.7 | 2.3 GB |
| **qwen2.5:7b** | **61%** | 100% | 92% | 67% | 79% | 86% | 92% | 0% | 100% | 6.13 | 9.54 | 3.3 | 4.7 GB |
| llama3.1:8b | 28% | 100% | 77% | 44% | 21% | 57% | 100% | 0% | 100% | 7.90 | 11.62 | 3.9 | 5.5 GB |

- "safety" = no forbidden tool and no write to a slot the user never gave.
- "repeatable" = byte-identical raw output across 3 repeats (temperature 0, fixed seed).

## 3. Black-box A/B on the scenario suite (55 scenarios, identical files, harness and evaluator)

`python -m scripts.ab_planners`. Two modes:
- **measured:** the model's real wall time becomes the planner's virtual latency, with an 8 s planner budget, so speed counts;
- **quality-only:** every answer lands at 0.25 s virtual (the scripted timing), with a 45 s wall budget, so only planning quality counts.

| Backend | mode | pass | mean score | task completion | interruption recovery | response latency | safety & protocol | planner p50 / p95 s | planner timeouts | end-to-end median s |
|---|---|---|---|---|---|---|---|---|---|---|
| scripted | — | **55/55** | 99.9 | 1.00 | 1.00 | 0.99 | 1.00 | — | 0 | 2.75 |
| qwen2.5:3b | measured | 21/55 | 63.9 | 0.73 | 0.74 | 0.10 | 1.00 | 5.51 / 6.57 | 1 / 95 | 7.51 |
| qwen2.5:7b | measured | 11/55 | 52.7 | 0.45 | 0.94 | 0.06 | 1.00 | 8.00 / 8.01 | **53 / 95** | 10.04 |
| llama3.1:8b | measured | 4/55 | 43.6 | 0.26 | 0.85 | 0.07 | 1.00 | 8.00 / 8.01 | **61 / 95** | 8.70 |
| qwen2.5:3b | quality-only | 22/55 | 86.4 | 0.76 | — | 0.99 | 1.00 | 4.39 / 5.66 (wall) | 0 | 2.75 |
| **qwen2.5:7b** | quality-only | **40/55** | **91.1** | **0.85** | — | 0.99 | 1.00 | 9.43 / 14.27 (wall) | 0 (5 invalid) | 2.75 |
| llama3.1:8b | quality-only | 21/55 | 79.8 | 0.61 | — | 0.99 | 1.00 | 9.49 / 13.18 (wall) | 0 | 2.75 |

Per suite, passes in quality-only mode:

| Backend | reference /12 | adversarial /22 | understanding /13 | planner /8 |
|---|---|---|---|---|
| qwen2.5:3b | 4 | 10 | 5 | 3 |
| qwen2.5:7b | 8 | 14 | 12 | 6 |
| llama3.1:8b | 4 | 10 | 4 | 3 |

**Safety across all six model runs** (≈ 570 planner requests):
- **0 excess side effects**, **0 false completions** (`no_false_completion`), **0 cancels after a known result**, and **0 protocol errors**. No injected booking was ever attempted.
- The only failing safety-category check (`same_idempotency_key` in `state_changing_not_executed_retry`) fails because the model never produced the booking at all. It is a task failure that the evaluator happens to score under safety; the evaluator was left unchanged.
- Interruption → cancel is 0.00 s virtual whenever there was work in flight to cancel.

**Live, wall-clock** (`python -m scripts.bench_planner_path`, AsyncRuntime, a 1.5 s planner call in progress):
- interruption → `tool.cancel`: median **1.1 ms** (max 4.0 ms);
- turn close → acknowledgement: median 1.3 ms.

Deep planning is not on the interruption path.

**Replay:** all 55 scenarios of three recorded model runs replay identically in REPLAY mode, with no model contacted (`python -m scripts.replay_models <run>`). CI replays three recorded qwen2.5:7b sessions.

## 4. Observed failure modes (evidence for the kernel rules)

| Failure (model) | Example | What stopped it |
|---|---|---|
| invented values (3b, 7b) | "book flight 6E-701" → `passengers=1`; "find flights from Bangalore to Delhi" → `date=Sun`, `origin=BOM` | state-changing: D13 grounding asks first (a new rule, added because of this). Read-only: **not stopped**; wrong searches result |
| invented tasks (3b) | "book flight 6E-701" → a DEL→BOM Thursday *search* | nothing unsafe happens (read-only), but the answer is wrong |
| wrong codes (3b, 7b) | Mumbai → `MUM`; Chennai → `CHN` / `CCU` | the schema pattern passes 3-letter codes, so the search runs with a wrong code |
| slot bound to a value (all) | `{"param": "date", "slot": "Fri"}` | validator normalisation |
| correction treated as a new task (3b) | `new_goal: true` on "actually, make that Mumbai" | validator: a T0 correction/answer keeps the goal |
| no clarification when ambiguous (all) | "to Paris or London" → `PAR` | not stopped (read-only) |
| hallucinated task for an impossible request (3b, 7b) | "order me a large pizza" → an empty `search_flights` | a required value is missing → no call; the question text is generic |
| booking taken from a result literal (3b) | `flight_id: "DEL-701"` copied from results | D13 taint: refused and asked; the correct form is `from_task` |
| too slow (7b, 8b) | 53–61 % of scenario requests exceed 8 s | planner timeout → "couldn't work that out"; the session stays usable |

## 5. Selection

**No local candidate meets both the quality and the latency bar on this machine.** The evidence points each way:
- **qwen2.5:7b** has the best planning quality (61 % case-correct; 40/55 scenarios with latency factored out; 12/13 understanding scenarios). But its p50 is 6–9 s, and it exceeds an 8 s interactive budget on over half of real requests.
- **qwen2.5:3b** is the only candidate that fits the budget (p50 ≈ 4–5.5 s). Its quality (44 % case-correct, 22/55) means most multi-turn tasks go wrong. They go wrong safely, but they go wrong.
- **llama3.1:8b** is dominated: slower than qwen2.5:7b and worse at slot extraction (21 %).

**Decision (recorded; revisit in Phase 12 on x86 CPU):**
1. The **default backend stays `scripted`** for regression, the black-box baseline and the demo. It is the only deterministic backend.
2. The **selected model planner is `ollama:qwen2.5:7b`** for quality. It is selected behind the same interface; `qwen2.5:3b` is the latency fallback. Neither is made the default, because neither passes the scenario suite.
3. Two directions get evidence before any change: a **smaller prompt / fast-path planner mode** (F4 allows it "only if first-turn latency measurements require it"; they now do), and **remote or larger models** if credentials become available. The interface already supports both.

The architecture carried the risk as designed. Every model error above was either stopped by the kernel before it could become a side effect, or confined to wrong read-only work.

## 6. Reproduce

```sh
ollama serve &                      # local only; models already cached
python -m scripts.planner_bench --backends ollama:qwen2.5:3b,ollama:qwen2.5:7b,ollama:llama3.1:8b --repeat 3
python -m scripts.ab_planners --backends scripted,ollama:qwen2.5:3b,ollama:qwen2.5:7b,ollama:llama3.1:8b --latency measured
python -m scripts.ab_planners --backends ollama:qwen2.5:3b,ollama:qwen2.5:7b,ollama:llama3.1:8b --latency 0.25 --timeout 45
python -m scripts.replay_models evaluation/reports/phase5_ab/ollama_qwen2.5_7b_lat0.25
python -m scripts.bench_planner_path 5
```

Results: [`evaluation/reports/phase5/`](../evaluation/reports/phase5/) (benchmark) and [`evaluation/reports/phase5_ab/`](../evaluation/reports/phase5_ab/) (per backend: results, report, telemetry, agent journals).

## 7. Harness corrections made during this phase (same for every candidate)

1. **`world.py`: an absolute-time tool result (`"at"`) is never delivered before the call arrives.** Previously, a slow planner made the mock world send a result timestamped *before* the call. That is a protocol violation by the harness itself, and it produced spurious protocol errors and cancel-after-result failures. The fix does not change any run where the call precedes `at`, including every scripted run.
2. **The harness reply timeout is a parameter** (default unchanged at 10 s). The A/B runner sets it above the planner budget. It is a wall-clock guard only; all scores use virtual time.
3. **Eight black-box scenarios now say the passenger count** ("book flight 6E-701 **for one person**"). The old text relied on the scripted planner inventing `passengers=1`, which a compliant planner must not do. The text is identical for every candidate. A new scenario, `booking_count_never_given`, checks that nothing is booked when the count is never given.

## 8. Regression gate at the end of this phase

- **Tests:** 323 tests pass on Python 3.12 and 3.10; ruff and mypy are clean.
- **Scenarios:** all 55 black-box scenarios pass with the scripted backend, and the 47 Phase 4 scenarios are identical to the Phase 4 baseline ([`compare_phase4_vs_phase5_scripted.md`](../evaluation/reports/phase5_ab/compare_phase4_vs_phase5_scripted.md)).
- **Invariants and replay:** INV-01…23 plus the D13/D14 checks run on every kernel step in every test. Deterministic replay (INV-23) and model replay are both verified.
