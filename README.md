# Interruptible Real-Time Agent: Samsung PRISM GenAI Hackathon 2026-27, Theme 05

## What this is

A working prototype of an **interruptible, real-time, multimodal agent**. You can change what you asked for while the agent is still working. It then:
- cancels the superseded work immediately;
- ignores results that arrive late;
- never duplicates a side effect;
- never claims something is done without a result to show for it.

It takes spoken requests (real on-device speech recognition) and images (real OCR). It plans through a validated planner port: a model when one is configured and reachable, otherwise a deterministic fallback. It is evaluated black-box with our own harness and **INTERNAL PRISM-style metrics**.

> Nothing here has been run on the Samsung evaluation kit, which was not available. **PRISM-LOCAL/0** is this project's own local protocol, not Samsung's; only `agent/adapter/` should change when the kit arrives.

## Quick start

```sh
uv venv --python 3.12 .venv && uv pip install -e ".[dev]"   # setup (Python 3.10-3.12)
./scripts/build_asr.sh                                      # macOS: on-device speech recognition helper
.venv/bin/python -m frontend.server --open                  # the live console: http://127.0.0.1:8765
.venv/bin/python demo/run_demo.py                           # the two demos in the terminal (add --speak to hear them)
.venv/bin/python -m pytest                                  # 449 tests
.venv/bin/python -m evaluation.run all --agent impl_a       # black-box evaluation, 59 scenarios (impl_a_duplex: full duplex)
.venv/bin/python scripts/bench_duplex.py                    # full-duplex measurements (virtual / wall / real ASR-OCR)
docker build -t prism-theme05 . && docker run --rm prism-theme05   # tests + evaluation on Linux
```

- **Live console:** [`frontend/README.md`](frontend/README.md). It shows the real agent in real time: a timeline of your input, perception, planning, tool calls and speech; each interruption cutting across the running work; late results visibly refused; and why the final answer can be trusted. It has guided demos (scored by the evaluator), live text, voice and image input, and a System view of the kernel's decisions and state.
- **Demo:** [`demo/README.md`](demo/README.md), with a reference run in [`demo/SAMPLE_OUTPUT.txt`](demo/SAMPLE_OUTPUT.txt).
- **Submission status, requirement mapping and limitations:** [`docs/SUBMISSION_READINESS.md`](docs/SUBMISSION_READINESS.md).

## Current status (full-duplex pass)

- **Full duplex (D17, opt-in; on in the console):**
  - While the user is still speaking or typing in pieces, the partial turn is planned, and **read-only** calls start before the end of turn.
  - A later chunk ("Actually, Mumbai") supersedes early work in the same step, and its late result is refused.
  - State-changing calls never start before the turn ends.
  - Spoken input streams too: the on-device recogniser's partial results reach the agent word by word while the button is held.
  - See the architecture decision [D17](docs/ARCHITECTURE_REVIEW.md) and the audit in [`SUBMISSION_READINESS.md`](docs/SUBMISSION_READINESS.md).
- **Black-box evaluation (INTERNAL):** 59/59 scenarios pass with the evaluator baseline (`impl_a`, full duplex off). The original 58 are score-identical to before; mean internal score 99.8 ([report](evaluation/reports/final/report.md)).
  - Suites: reference 12/12, adversarial 22/22, understanding 13/13, planner 9/9, demo 3/3.
  - With full duplex on (`impl_a_duplex`): 59/59 as well; no scenario is skipped or special-cased (one fixture's result time was re-expressed relative to the call, see D17).
  - Interruption → cancel is 0.00 s (virtual; same kernel step), and 1.1 ms wall-clock while a planner call is running.
- **Real input:**
  - audio via Apple on-device speech recognition (macOS) → fast understanding → kernel;
  - images via tesseract OCR → grounded evidence → the right goal.
  - Scripted fallbacks are used elsewhere, for example in Docker.
- **Planner policy:** `--planner auto` uses the model named by `PRISM_PLANNER` if its server is reachable, with a per-request deterministic fallback. Otherwise it uses the deterministic planner: known examples, then rules for common paraphrases of the supported tasks. Three local models were measured ([evidence](docs/PHASE5_MODEL_EVALUATION.md)): none is both reliable and fast enough on this machine, so the demo uses the deterministic planner.
- **Safety:**
  - no duplicate side effects;
  - no state-changing call the user did not ask for or whose values the user never said;
  - tool-result injection is refused;
  - no false completion.

  Each is checked on every kernel step by the invariant checker (INV-01…23 plus decisions D13/D14).
- **Tests:** 449 pass on Python 3.10 and 3.12; ruff and mypy clean.

### Build history

| Phase | Report |
|---|---|
| Architecture (locked), hostile review, decisions D1–D17 | [`ARCHITECTURE_REVIEW.md`](docs/ARCHITECTURE_REVIEW.md) |
| 1: Deterministic kernel, journal, replay | [`PHASE1_IMPLEMENTATION.md`](docs/PHASE1_IMPLEMENTATION.md) |
| 2: Async runtime | [`PHASE2_RUNTIME.md`](docs/PHASE2_RUNTIME.md) |
| 3: PRISM-LOCAL/0 adapter + black-box evaluation | [`PHASE3_PROTOCOL_ADAPTER.md`](docs/PHASE3_PROTOCOL_ADAPTER.md) |
| 4: Fast understanding | [`PHASE4_FAST_UNDERSTANDING.md`](docs/PHASE4_FAST_UNDERSTANDING.md) |
| 5: Planner / deep reasoning, model A/B | [`PHASE5_PLANNER.md`](docs/PHASE5_PLANNER.md), [`PHASE5_MODEL_EVALUATION.md`](docs/PHASE5_MODEL_EVALUATION.md) |
| Final integration: audio, vision, response layer, demo, Docker | [`SUBMISSION_READINESS.md`](docs/SUBMISSION_READINESS.md) |
| Full duplex: early read-only work, streaming speech (D17) | [`SUBMISSION_READINESS.md`](docs/SUBMISSION_READINESS.md) §Theme 05 audit |

### More commands

```sh
python -m agent.scenario B                         # kernel-level timeline: correction mid-search, stale result rejected
python -m tests.understanding_corpus               # fast-understanding corpus (internal measurement)
PRISM_PLANNER=ollama:qwen2.5:7b python demo/run_demo.py   # live local model planner (needs `ollama serve`)
python -m scripts.ab_planners --backends scripted,ollama:qwen2.5:3b   # A/B planner backends (INTERNAL)
python -m scripts.replay_models evaluation/reports/phase5_ab/ollama_qwen2.5_7b_lat0.25   # replay a model run, no model
```

## Architecture

![Master architecture](docs/diagrams/01_master_architecture.svg)

The agent is an event processor. It is not a turn-taking chatbot. Everything the evaluation harness sends arrives in one ordered inbox, including text chunks, audio, image frames, interrupt signals, tool manifests, and tool results that may arrive late. A single **session kernel** processes one event per step. Each step takes milliseconds and never waits on a model or a tool, and the kernel is the only component that changes session state. Planning, speech-to-text, image understanding and timers run concurrently as workers that only send results back as new events. Slow work therefore never blocks the conversation, and it can never race with a state update.

Interruptions are handled by comparing the work we *want* with the work that is *in flight*. Every tool call is identified by its tool and argument values. When the user corrects a value ("actually, to Mumbai"), the kernel recomputes which calls are wanted in the same step. It marks the affected calls **superseded** and sends the harness an advisory cancel. Unrelated work keeps running. Harness tools may finish anyway, so every result is recorded as fact but is only *used* if its call is still wanted, which means a late or stale result can never reach an answer or a state snapshot. Tools that change state (booking, ticket creation) pass through a commit barrier and a strict ledger that allows at most one unresolved attempt per operation and never a second create. The speech the agent produces is derived from state, so it never claims something is done before a successful result exists.

The harness wire format is isolated in one adapter module. Every event and decision is journaled, so any run can be replayed exactly, offline, to explain why each call was made and why each stale result was ignored.

| Document | Contents |
|---|---|
| [`docs/ARCHITECTURE_REVIEW.md`](docs/ARCHITECTURE_REVIEW.md) | Hostile review and the **final approved architecture** (authoritative) |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Requirements analysis and design rationale (non-normative); v0.1 kept in `docs/archive/` |
| [`docs/PHASE1_IMPLEMENTATION.md`](docs/PHASE1_IMPLEMENTATION.md) | Phase 1: modules, interfaces, journal/replay, invariant coverage, limitations |
| [`docs/PHASE0_PREFLIGHT.md`](docs/PHASE0_PREFLIGHT.md) | Environment and harness preflight, interface contracts, invariant-to-test map, build order |
| [`docs/diagrams/`](docs/diagrams/README.md) | Diagram set (Mermaid sources, SVG, PNG), conventions, and resolved consistency issues |
