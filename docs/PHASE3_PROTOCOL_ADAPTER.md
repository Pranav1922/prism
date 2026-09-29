# Phase 3 Report — Protocol Adapter and Black-Box Local Evaluation Baseline

| | |
|---|---|
| Date | 2026-09-30 |
| Plan mapping | [`PHASE2_PLAN.md`](PHASE2_PLAN.md) execution-order items 2–4: Phase 8 (protocol adapter), Phase 9 + 5 (harness + tool world, first version), Phase 10 (evaluator, first version). Reported here as "Phase 3", as requested. |
| Result | **204 tests pass on Python 3.12 and 3.10**; ruff and mypy clean; **34/34 black-box scenarios pass**; baseline recorded in [`evaluation/reports/impl_a/`](../evaluation/reports/impl_a/report.md) |

> **PRISM-LOCAL/0 is this project's own local protocol. It is not the Samsung evaluation protocol**, which is still unavailable (UNK-1). It exists so the agent can be driven end to end as a black box, and so two independent implementations can be evaluated identically. When the official kit arrives, only `agent/adapter/` changes.

## 1. PRISM-LOCAL/0

- **Transport:** JSON lines. **Machine-readable contract:** [`protocol/prism_local_0.schema.json`](../protocol/prism_local_0.schema.json), generated from `agent/adapter/schema.py`; a test keeps the two identical.
- **Time:** virtual seconds. Message timestamps must not decrease.
- **Lockstep:**
  - For every input message, the agent emits zero or more output messages followed by **exactly one** `agent.ready {next_wakeup}`.
  - `next_wakeup` is the earliest virtual time at which the agent needs to act on its own: its timers, or its internal workers finishing. It is `null` if there is nothing pending.
  - The harness advances time only through message timestamps or `clock.tick`.
- **Ordering at equal times:** the harness delivers its own messages at time *t* first; the agent then processes its own due items at *t* when it receives `clock.tick(t)`. This is the kernel's tie rule, "events before timers", made part of the contract.

### 1.1 Input envelope

`{"v": "PRISM-LOCAL/0", "id": <string>, "t": <number ≥ 0>, "type": <string>, "data": <object>}`. No other fields are allowed.

| Field | Why it exists |
|---|---|
| `v` | Version negotiation; any other value is rejected (`unsupported_version`) |
| `id` | Event identity: duplicate detection, and `cause` references on outputs |
| `t` | Harness time; the kernel's only notion of "now" |
| `type` | Event type |
| `data` | Payload, validated per type |

Correlation lives in the payload where it is needed (`tool.result.call_id`, `worker.*.req_id`). Outputs carry `cause`.

### 1.2 Input types, harness channel

| Type | Data | Internal event |
|---|---|---|
| `session.start` / `session.end` | `{}` | `SessionStart` / `SessionEnd` |
| `manifest` | `{tools: [object]}`; each tool is validated by the agent's registry, and bad tools are quarantined | `Manifest` |
| `user.text` | `{text}` (a chunk; non-empty) | `UserText` |
| `user.turn_end` | `{}` | `EndOfTurn` |
| `user.audio` | `{ref, duration_s?}` (a reference, not bytes) | `Media(kind=audio)` |
| `user.frame` | `{ref}` (image or video frame reference) | `Media(kind=image)` |
| `user.interrupt` | `{}` | `Interrupt` |
| `tool.result` | `{call_id, status: ok\|error\|cancelled, data?, executed?: bool\|null, message?}` | `ToolResult` (`cancelled` → `cancelled_ack`) |
| `clock.tick` | `{}` | not an event: advances time and fires due timers |

### 1.3 Input types, worker channel (agent-internal)

`worker.proposal {req_id, based_on_seq, proposal}`, `worker.proposal_failed`, `worker.evidence {req_id, frame_id, claims}`, `worker.transcript {req_id, source_id, text}`, `worker.perception_failed`.

These exist so that out-of-process workers (the Phase 6 perception process) return results through the **same validated ingress**. A harness-channel ingress **rejects** them (`type_not_allowed_on_channel`), so the environment cannot forge planner or perception results.

### 1.4 Output envelope and types

`{"v", "id", "t", "type", "data", "cause": [input ids]}`. `t` is the harness time of the event that caused the action.

| Type | Data | From internal action |
|---|---|---|
| `speech` | `{text, act: ack\|narration\|filler\|answer\|confirm}` | `SPEAK` |
| `clarify` | `{text, slots?}` | `CLARIFY` |
| `tool.call` | `{call_id, tool, args, idempotency_key?}` | `TOOL_CALL`; `call_id` is minted by the kernel |
| `tool.cancel` | `{call_id}` | `CANCEL` (advisory) |
| `response.final` | `{text, snapshot: {intent, slots}, complete?, grounded_on?}` | `FINAL`. `complete=false` marks a truthful partial report (deadline governor). `grounded_on` lists the calls the answer rests on: DESIRED results plus, for committed state-changing operations, the committed attempt (D6). |
| `state.snapshot` | `{snapshot: {intent, slots}}` | `SNAPSHOT` |
| `protocol.error` | `{ref, reason}` | not from the kernel: an input rejected at ingress, or an action refused at egress |
| `agent.ready` | `{next_wakeup}` | not from the kernel: the lockstep terminator |

**Not on the wire:** internal rule names, reason codes, `uses`, `ops`, state revisions, relevance and outcome states.

## 2. Adapter boundaries

| Layer | Knows | Code |
|---|---|---|
| Kernel, runtime, registry, model | Internal `Event` / `Action` only | `agent/*.py` except `agent/adapter/` |
| Adapter | PRISM-LOCAL/0 | `agent/adapter/schema.py`, `ingress.py` (`wire_to_event`), `egress.py` (`action_to_wire`, `validate`), `stdio.py` (lockstep process) |
| Harness / evaluator | PRISM-LOCAL/0 + the shared schema file | `evaluation/`, which **never imports `agent`** |

These are enforced by tests:
- no module under `agent/` outside `agent/adapter/` imports the adapter or mentions `PRISM-LOCAL`;
- no evaluation module imports agent code or names agent modules (only the launcher registry in `evaluation/agents.py` holds agent commands).

## 3. Malformed-message behaviour

Ingress checks, in order: JSON → object → version → envelope → known type → allowed on this channel → payload schema → duplicate id → timestamp regression.

Any failure yields `Rejected(ref, reason)`. The agent emits `protocol.error {ref, reason}` and **never passes the message to the kernel**: a test asserts that the state revision and journal step count are unchanged. Nothing is repaired. Reasons:
- `malformed_json`, `not_an_object`, `unsupported_version`;
- `invalid_envelope: …` (missing or negative `t`, missing `id`, extra fields);
- `unknown_type`, `type_not_allowed_on_channel`;
- `invalid_payload: …` (including any attempt to smuggle fields such as `t0` into `user.text`);
- `duplicate_id`, `timestamp_regression`.

A malformed **manifest entry** is not a protocol error. The envelope is valid, and the kernel's registry quarantines that tool while the rest of the manifest works (scenario `malformed_tool_manifest`).

Egress validates every output against the schema before it is written. An invalid action is dropped, journaled, and reported as `protocol.error {ref: action_id, reason: invalid_action}`; this has never happened in any test.

## 4. Black-box harness

`evaluation/harness.py` co-simulates in virtual time: the scenario's inputs, the mock tool world, and the agent's `next_wakeup`.

| It sees | It never sees |
|---|---|
| inputs it sent, outputs it received (raw + parsed), timestamps, record order | agent state, journal, rules, internal ids beyond the wire |
| its own tool world: calls received, cancels received (honoured or ignored), results delivered, **side effects executed** | |

- **Tool world** (`evaluation/world.py`):
  - scripted behaviours per attempt: latency or absolute `at`; `ok` / `error` with `executed`; duplicate delivery; a follow-up delivery (e.g. "not executed" then OK); never answers;
  - honouring or ignoring cancels;
  - optional idempotency.

  A state-changing tool performs its side effect when its OK is delivered. A booking that completes despite a cancel is therefore a real side effect, whatever the agent believes.
- **Launcher** (`evaluation/agents.py`): any command that speaks PRISM-LOCAL/0 on stdin/stdout. `impl_a` = `python -m agent.adapter.stdio`. Developer B registers a command, or passes `--agent "cmd:…"`. It reads the raw file descriptor with its own buffer and a timeout, so a hung agent cannot hang the evaluation.
- **Implementation A's current stand-ins** (scripted understanding, planner and perception) live in `agent/fixtures/scripted.json`, on the agent side. The scenarios contain none of it; a test forbids agent-internal vocabulary in scenario files.

## 5. Scenario format

`evaluation/scenarios/<suite>/<id>.json` is validated by `evaluation/scenario.py`.

```json
{"id": "B_destination_correction", "description": "...", "tags": ["reference", "interruption"],
 "manifest": {"use": "flights", "overrides": {"search_flights": {"timeout_s": 1.0}}, "extra": []},
 "world": {"search_flights": {"behaviors": [{"latency": 2.0, "status": "ok", "gen": "flights"}], "honors_cancel": false}},
 "inputs": [{"t": 0.1, "id": "ask", "type": "user.text", "data": {"text": "..."}},
            {"t": 1.4, "id": "fix", "type": "user.text", "data": {"text": "actually, to Mumbai"}, "rank": 0},
            {"t": 0.3, "raw": "<any line, sent verbatim>"}],
 "horizon": 30,
 "expect": {"final": {"complete": true, "snapshot": {"intent": "search_flights", "slots": {"destination": "BOM"}}},
            "calls": [{"tool": "search_flights", "args": {"destination": "BOM"}, "min": 1, "max": 1}],
            "cancels": [{"after": "fix", "tool": "search_flights", "args": {"destination": "DEL"}}],
            "no_calls_after": [...], "not_grounded_on": [...], "no_cancels": true,
            "side_effects": {"book_flight": {"min": 1, "max": 1, "args": {}}}, "clarify": {"min": 1},
            "final_forbidden": [{"slots": {"passengers": 2}}], "protocol_errors": 0,
            "same_idempotency_key": ["book_flight"]}}
```

Every expectation is about something visible on the wire or in the tool world: tool calls and their arguments, cancels relative to a named input, side effects, clarifications, the final snapshot, and protocol errors. `rank: 1` places an input after tool-world deliveries at the same instant; that is how same-time ordering is scripted in both directions.

**Suites:**
- **reference (12):** A–H plus variants D2, E2, F2, H2;
- **adversarial (22):**
  - interrupt 1 ms before and after completion, and at the same instant (H/H2);
  - two interruptions; value revert (D1); pending twin (D2);
  - retry budget; state-changing timeout then late OK; not executed then retry (same idempotency key); unknown-execution error (no retry); duplicate booking request;
  - malformed arguments; non-cancellable state-changing tool;
  - backchannel and status question; unattributed correction; content-free interrupt;
  - deadline governor; unknown `call_id` result;
  - older evidence vs newer user value;
  - malformed protocol inputs (6 kinds); malformed manifest;
  - result exactly at the timeout instant; FAILED_CLEAN → OK anomaly.

## 6. Metrics: INTERNAL PRISM-STYLE (not Samsung scores)

`evaluation/metrics.py` uses only the trace and the tool world's ledger.

| Category (weight) | Checks |
|---|---|
| Task completion (40) | final response present / absent as expected; `complete` flag; final snapshot matches (intent + expected slots); **the answer is grounded on completed current work** (every `grounded_on` call exists, had an OK result delivered before the answer, and was not cancelled); expected tool calls (count ranges); side effects performed (min); clarification counts |
| Interruption recovery (35) | every call matching an invalidated argument set that was in flight at the named input is **cancelled**, within the grace period (virtual cancel latency ≤ 0.01 s); **no stale rerun** after the input; **answer not grounded on superseded work**; no unnecessary cancels where none are warranted |
| Response latency (15) | for each user turn end: virtual time to the first substantive output (non-filler speech, clarify, final). ≤ 0.3 s scores 1, falling linearly to 0 at 3.0 s. Turns without any substantive output are listed. |
| Safety and protocol (10) | every output schema-valid; unique output ids and call ids; cancels reference known calls; **no cancel after the agent already received a result**; at most one cancel per call; **side effects ≤ max** (duplicate state-changing actions, counted in the world); same idempotency key across retries; **no false completion** (no `complete` final claiming forbidden values); protocol errors exactly as expected |
| Reported, not scored | fillers, speech while the user is speaking, repeated utterances, multimodal tag |

The internal score renormalises the weights over the categories a scenario exercises.

**The evaluator is shown to discriminate:**
- a `nocancel` agent (Implementation A with cancels stripped) **fails** B, D and interrupt-1 ms-before, and its interruption-recovery score drops;
- a `doublecall` agent **fails** the side-effect maximum and safety.

## 7. Test results

| Suite | Tests |
|---|---|
| Phase 1 (unchanged) | 73 |
| Phase 2 async runtime (unchanged) | 13 |
| Adapter contract (`tests/test_adapter.py`) | 43 (parametrised): valid round trips for all harness types, worker channel, 13 malformed-input cases, duplicate/regression, egress for all action kinds, causing time/id, invalid finals, identifier rules, schema-file sync, isolation, lockstep terminator, rejected input never reaching the kernel, tie rule |
| Black-box (`tests/test_blackbox.py`) | 75 (parametrised): suite validity, no internals in scenarios (34), impl_a passes each scenario (34 via subprocess), deterministic traces, the trace answers what happened, agent-journal replay identical, broken agents caught, evaluator isolation |
| **Total** | **204 pass on Python 3.12 and 3.10; 0 fail; 0 skipped** |

**Baseline** (`python -m evaluation.run all --agent impl_a`): **34/34 pass all checks; mean internal score 98.6.**

| Category | Mean |
|---|---|
| Task completion | 1.00 (n = 34) |
| Interruption recovery | 1.00 (n = 17) |
| Safety and protocol | 1.00 (n = 34) |
| Response latency | **0.93** (n = 34) |

**Measured weaknesses found by the baseline** (for the speech-policy phase):
- **State-changing dispatch produces no acknowledgement.** Only read-only dispatch acks, so booking turns wait for the tool; the FAILED_CLEAN → OK anomaly scores RL 0.02.
- **Status questions are not answered** (review F7 lists this as future speech work).
- **An unattributed correction marker re-runs identical work** (F5 literal churn; scenario `unattributed_correction_marker` passes because it expects exactly this documented behaviour).

## 8. Benchmark (`scripts/bench_adapter.py 200`)

Wall clock on the dev machine is indicative only; virtual metrics are exact.

| Metric | p50 | p99 |
|---|---|---|
| Ingress parse (per message) | 0.016 ms | 0.020 ms |
| Egress serialise + validate (per action) | 0.025 ms | 0.037 ms |
| In-process `handle()`: correction → cancel | 0.281 ms | 0.362 ms |
| In-process `handle()`: turn end → tool.call + snapshot + ack | 0.466 ms | 0.524 ms |
| In-process `handle()`: manifest (schema checks, once per session) | 1.336 ms | 2.069 ms |
| **Subprocess round trip: correction → `tool.cancel`** | 0.338 ms | 0.458 ms |
| **Subprocess round trip: turn end → `tool.call` + speech** | 0.523 ms | 0.577 ms |
| Virtual: turn end → first substantive action (51 turns) | 0.25 s | 2.95 s (booking turns, see above) |
| Virtual: interruption → cancel (13 cases) | 0.0 s | 0.0 s |

## 9. Limitations caused by the missing official harness

- **Wire format.** PRISM-LOCAL/0 field names, types and the lockstep model are our design. The Samsung harness may stream asynchronously with a real or virtual clock (G3). Only `agent/adapter/` has to change; the kernel, runtime and evaluator logic do not.
- **Time model.** Lockstep virtual time makes runs exact and comparable, but it does not measure wall-clock compute inside a step. Wall latencies are therefore benchmarked separately (§8). A live wall-clock harness mode (`AsyncRuntime` + worker tasks) is planned with real models.
- **Media.** Audio and frames are references (`ref`), not bytes; the scripted perception resolves them. Real media handling comes with Phase 6.
- **Scoring.** The metric definitions and the latency curve (0.3 s → 3 s) are our reading of the Guide's categories. They are labelled INTERNAL throughout and must not be reported as Samsung scores.
- **Implementation A still uses scripted understanding and planning** (agent-side fixtures), so the scores measure the runtime, protocol and decision logic, not language understanding.
