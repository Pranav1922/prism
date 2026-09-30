# Submission Readiness — Theme 05 Interruptible Real-Time Agent

| | |
|---|---|
| Date | 2026-09-30 |
| Scope | Implementation A (this repository), final integration |
| Headline | **58/58 internal black-box scenarios pass** (mean 99.8). **Real speech recognition and real OCR** run in the demo. 405 tests pass on Python 3.12 and 3.10; ruff and mypy clean. The Docker image runs the whole suite on Linux. |

**Nothing here was tested with the Samsung evaluation kit.** It was not available (UNK-1).
- PRISM-LOCAL/0 is this project's own local protocol, not Samsung's.
- Every score is an INTERNAL PRISM-STYLE metric that mirrors the documented Theme 05 categories. None is a Samsung score.

## 1. Implemented capabilities

| Capability | Where | Status |
|---|---|---|
| Single-writer session kernel: decide/apply split, journal, byte-identical replay | `agent/kernel.py`, `agent/journal.py` | implemented |
| Supersession, same-step cancellation, stale-result rejection, operation ledger, commit barrier, idempotency keys | `agent/kernel.py` | implemented |
| Async runtime: workers, timeouts, advisory cancel, live/manual timers | `agent/async_runtime.py` | implemented |
| Protocol adapter (PRISM-LOCAL/0), lockstep stdio agent | `agent/adapter/` | implemented (local protocol) |
| Fast understanding: 6 turn classes, schema-driven slot corrections, partial transcripts | `agent/understand_rules.py` | implemented |
| Planner port: validation layer, provenance/taint/authorisation rules (D13), ordered late answers (D14) | `agent/reasoner/`, `agent/proposal.py` | implemented |
| Model planner backends: Ollama (local), OpenAI-compatible (remote), replay | `agent/reasoner/backends.py` | implemented; the remote backend is untested (no credentials) |
| Planner deployment policy: `auto` = the `PRISM_PLANNER` model if reachable, else deterministic; per-request fallback | `agent/adapter/stdio.py`, `FallbackPlanner` | implemented |
| **Audio → ASR → event → fast understanding → kernel** | `agent/perception.py` + `agent/perception_macos/asr.swift` | implemented (macOS on-device); scripted fallback elsewhere |
| **Image → OCR → grounded evidence → goal → kernel** | `agent/perception.py` (tesseract) | implemented |
| Response layer: accepted, searching, correction, clarification, status, completion (grounded), failure | `agent/speech.py`, `Kernel.speak` | implemented |
| Speech output | macOS `say` in the demo presenter | fallback-grade (no TTS built, as allowed by R15) |
| Black-box harness, mock tool world, evaluator, 57 scenarios | `evaluation/` | implemented |
| Demo presenter (timeline, verdict, spoken replay) | `demo/` | implemented |
| **Live web console**: real-time timeline, interruption and stale-result visualisation, task and trust panels, System view (decisions, kernel state, protocol), guided demos scored by the evaluator, live text/voice/image input | `frontend/` ([README](../frontend/README.md)) | implemented (local, one presenter) |

## 2. Theme 05 requirement mapping

The requirements R1–R16 were distilled from the Theme 05 guide ([`ARCHITECTURE.md`](ARCHITECTURE.md) §0.1).

| Req | Requirement | How it is met | Evidence |
|---|---|---|---|
| R1 | asynchronous event queues in and out | inbox → kernel step → actions/effects; the wire is JSON lines | `agent/runtime.py`, `agent/async_runtime.py` |
| R2 | text chunks, end of turn, audio, frames, interrupts, async tool results, manifests | all are ingress event types | `agent/adapter/ingress.py`, `protocol/prism_local_0.schema.json` |
| R3 | fillers, non-blocking calls with `call_id`, cancels, clarifications, FINAL + snapshot | kernel actions, validated at egress | INV-21/22 on every step |
| R4 | fast path in a few hundred ms, slow path, coordination layer | T0 runs in the kernel step (~0.03 ms); planner and perception run as effects | [`PHASE4`](PHASE4_FAST_UNDERSTANDING.md) §9, [`PHASE5_PLANNER`](PHASE5_PLANNER.md) §10 |
| R5 | quick meaningful responses, no false completion, no excessive fillers | grounded FINAL only; the ack timer; no speech while the user speaks | INV-20; `naturalness` metrics (0 fillers) |
| R6 | cancel superseded calls within ms; update snapshots; re-plan | cancel in the same step as the correcting input | interruption → cancel is 0.00 s virtual in all 16 cases; 1.1 ms wall while planning |
| R7 | session slots, localized corrections | goal-scoped last-writer-wins registers; content-key supersession | understanding suite, 13/13 |
| R8 | dynamic tools from manifests; no duplicate state-changing calls | registry from the manifest; operation ledger; D13 authorisation | adversarial suite, 22/22; `side_effects_max` never violated |
| R9 | audio and frames behind acknowledgements; clarify ambiguous perception | perception is asynchronous; evidence conflict → clarify; early evidence (D16) | `demo_ticket_image`, `F_evidence_*` |
| R10 | well-formed JSON, valid snapshots and ids | egress schema validation | 0 protocol violations in every run |
| R11 | virtual clock, deterministic replay, fault injection | lockstep virtual time; journal replay; tool-world faults | INV-23 tests; `C_timeout_retry`, `state_changing_*` |
| R12 | mixed text/audio/visual, unseen tools, adversarial timing | generic registry; 1-ms-before/after races; audio and image demos | 57 scenarios; the hidden set is unknown |
| R13 | TC 40, IR 35, RL 15, SP 10 | mirrored as INTERNAL metrics | [`evaluation/reports/final/`](../evaluation/reports/final/report.md) |
| R14 | Python 3.10–3.12, 120 s cap, warm-up, session-only memory | both versions tested; deadline governor at 110 s; nothing persists across sessions | CI runs on both; `deadline_governor` scenario |
| R15 | no wake word, TTS tuning or UI | none built | — |
| R16 | async orchestration, latency hiding, multimodal grounding | runtime, ack timer, evidence → goal | this document |

## 3. Demo scenario

See [`demo/README.md`](../demo/README.md) and the reference output [`demo/SAMPLE_OUTPUT.txt`](../demo/SAMPLE_OUTPUT.txt).

**`demo_audio_interruption` (real audio):**
1. The user says "Find a flight from Bangalore to Delhi on Friday."
2. The on-device ASR hears it; the agent answers "On it: search flights (date Fri, destination DEL, origin BLR)." and starts a slow Delhi search.
3. The user says "Wait, Mumbai instead."
4. In the step the transcript arrives, the Delhi search is cancelled and the agent says "Okay, changing the destination."
5. A Mumbai search starts, and the answer is grounded on the Mumbai result.
6. The Delhi result arrives 2.3 s later and is recorded but **not used**.

The evaluator passes it with an internal score of 99.4.

**`demo_ticket_image` (real audio + real image):**
1. The user asks for flights "on the date on this ticket" and shows a boarding pass.
2. OCR reads DATE SATURDAY, FROM BLR, TO DEL.
3. The evidence arrives *before* the planner has created the goal; it is applied when the goal is created (D16).
4. The search runs for Saturday, and the answer is grounded on it. The planner never invents the date.

The evaluator passes it with an internal score of 100.

## 4. Internal evaluation results (INTERNAL PRISM-STYLE)

| Run | Scenarios | Pass | Mean | TC | IR | RL | SP |
|---|---|---|---|---|---|---|---|
| final (`impl_a`: scripted planner, real ASR/OCR, fixed 0.8 s perception latency) | 57 | **57** | 99.8 | 1.00 | 1.00 | 0.99 | 1.00 |
| the same, in Docker (Linux, scripted ASR, real tesseract) | 57 | 57 | — | — | — | — | — |
| Phase 4 baseline vs final, on the 47 shared scenarios | 47 | 47 → 47 | 99.9 → 99.9 | identical | identical | identical | identical |

Per suite: reference 12/12, adversarial 22/22, understanding 13/13, planner 9/9, demo 2/2. First substantive response is 0.25 s p50. Interruption → cancel is 0.00 s (n = 16).

Model planners: see [`PHASE5_MODEL_EVALUATION.md`](PHASE5_MODEL_EVALUATION.md). qwen2.5:7b is the best plan quality (40/55 with latency factored out) but too slow for an 8 s budget here. No model caused an unsafe side effect in about 570 requests.

Results: [`evaluation/reports/final/`](../evaluation/reports/final/report.md) (this build) and [`evaluation/reports/phase5_ab/`](../evaluation/reports/phase5_ab/) (model A/B, with replayable journals).

## 5. Audio status

- **Implemented.** A WAV/AIFF clip (`user.audio` ref) is transcribed by **on-device** Apple speech recognition (`.build/prism_asr`, built by `scripts/build_asr.sh`). The transcript becomes a `UserText{source: asr}` event and goes through fast understanding and the kernel like typed text.
  - Recognition takes about 0.15–0.9 s per clip on the dev machine.
  - An end of turn received before the transcript closes the turn when the transcript arrives (D16).
- **Simulated.** The demo audio is synthesised with macOS `say`: real waveforms, but not a live microphone.
- **Fallback.** Scripted transcripts are used on non-macOS systems (Docker/Linux) or if the helper is missing.
- **Not implemented.** Streaming ASR and a live microphone. Interruption by voice is detected when the correction clip has been transcribed, so voice interrupt → cancel = recognition time (≈ 0.15–0.9 s), not a few ms. Pre-emptive supersession on clip arrival (review §9.3, gate G6) was not enabled.

## 6. Vision status

- **Implemented.** PNG frames (`user.frame` ref) go through tesseract OCR and schema-light extraction: weekday → `date`, `FROM`/`TO` airport codes → `origin`/`destination`, flight numbers → `flight_id`. Confidence comes from OCR word confidences.
  - Claims become evidence: attached to the frame's goal, last-writer-wins against the user, a conflict with a user value → clarification that blocks side effects, applied late if the goal did not exist yet (D16).
- **Fallback.** Scripted claims for unknown refs.
- **Not implemented.** General scene understanding (no vision-language model is available locally without a download), video beyond frame sequences, and grounding into arbitrary tool schemas beyond these value types.

## 7. Interruption status

| Aspect | Result |
|---|---|
| text correction → cancel of superseded in-flight work | same kernel step: 0.00 s virtual in every scenario; 1.1 ms median wall with a busy planner |
| voice correction → cancel | same step as the transcript (recognition time ≈ 0.15–0.9 s) |
| stale results (late, after cancel, after goal switch) | recorded, never used (INV-09); demonstrated live in demo 1 |
| status questions / backchannels during work | answered truthfully from state / ignored (no fillers) |
| late planner answers | merged by field; never override newer user input or a newer graph (D14) |

## 8. Tool-safety status

- **No duplicate state-changing call.** Enforced by the operation ledger, commit barrier and idempotency keys; checked by the invariant checker on every step and by `side_effects_max` in every run. It was never violated, including in six model-driven runs.
- **No state-changing call the user did not ask for.** A user verb, grounded values, or an explicit "yes" to the exact arguments is required (D13).
  - Tool-result injection is dropped: `injection_in_search_result`, which includes a deliberately compromised planner.
  - A planner-invented passenger count is confirmed first: `booking_count_never_given`.
- **No false completion.** Every FINAL is grounded on a DESIRED+OK call or a COMMITTED operation (INV-20). `no_false_completion` passed in every run.

## 9. Known limitations

1. **No Samsung kit.** The wire format, clock and scenarios are our own. Only `agent/adapter/` should change when the kit arrives, but that is unverified.
2. **Planner.** No available local model is reliable and fast enough on this machine. The prototype and demo use the **deterministic planner**: known examples first (tolerant of recognition noise), then a rule planner for common paraphrases of flight search, booking and weather. The rule planner uses tools from the manifest, schema-bound values, a small city→airport table, and asks rather than invents. Requests outside that domain are not planned. A configured model (`PRISM_PLANNER=ollama:qwen2.5:7b`) is used when reachable, with a per-request scripted fallback. Model quality is 44–61 % case-correct ([evidence](PHASE5_MODEL_EVALUATION.md)).
3. **Audio.** File-based, non-streaming, macOS-only real ASR, and no microphone capture. Voice interruption latency equals recognition time.
4. **Vision.** OCR + regex-level extraction only.
5. **Tools.** The mock tool world only; no real booking API.
6. **Speech.** Template wording; `say` as the output voice in the demo only; the agent emits text.
7. **Performance.** Measured on an Apple M4. A CPU-only x86 evaluation host is unmeasured (Docker runs the suite, but its timings were not benchmarked).
8. **Heuristics.** Lexical heuristics in fast understanding and D13 are conservative. Unusual phrasing leads to a question or a planner round trip, not an action.
9. **Corpora.** The corpus, planner cases and scenarios were written by the implementer. They are not real-world accuracy measures.

Per-phase limitations are listed in [`PHASE4_FAST_UNDERSTANDING.md`](PHASE4_FAST_UNDERSTANDING.md) §11, [`PHASE5_PLANNER.md`](PHASE5_PLANNER.md) §14 and [`PHASE5_MODEL_EVALUATION.md`](PHASE5_MODEL_EVALUATION.md) §4–5.

## 10. Reproducibility

```sh
# setup (macOS, Python 3.12 via uv)
uv venv --python 3.12 .venv && uv pip install -e ".[dev]"
./scripts/build_asr.sh                      # on-device ASR helper (macOS; grants speech permission once)
brew install tesseract                      # OCR, if missing

# demo
.venv/bin/python -m frontend.server --open  # live console at http://127.0.0.1:8765 (guided demos + live input)
.venv/bin/python demo/run_demo.py           # both demos + evaluator verdict (add --speak to hear it)

# validation
.venv/bin/python -m pytest                  # 405 tests
.venv/bin/python -m evaluation.run all --agent impl_a --out evaluation/reports/final
.venv/bin/ruff check agent evaluation tests scripts && .venv/bin/mypy agent evaluation

# anywhere (Linux / CI): the full suite + evaluator in Docker
docker build -t prism-theme05 . && docker run --rm prism-theme05

# optional live model planner (local)
ollama serve & PRISM_PLANNER=ollama:qwen2.5:7b .venv/bin/python demo/run_demo.py
```

## Classification summary

| Category | Items |
|---|---|
| **Implemented** | kernel, runtime, adapter, fast understanding, planner port + validation + safety rules, model backends (local), on-device ASR, OCR evidence, response layer, evaluator, demo |
| **Simulated** | tool world (flights, booking, weather), user audio (synthesised speech files), the clock (virtual, lockstep) |
| **Fallback** | scripted planner (the default where no model is configured or reachable; per-request on model failure); scripted transcripts and claims where the ASR helper or OCR is unavailable |
| **Unavailable (Samsung kit missing)** | the official wire protocol, official harness and clock, public and hidden scenarios, official scoring; nothing here is Samsung-tested |
