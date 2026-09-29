# Phase 1 — Deterministic Runtime Foundation

| | |
|---|---|
| Date | 2026-09-30 |
| Contract | [`ARCHITECTURE_REVIEW.md`](ARCHITECTURE_REVIEW.md) → FINAL ARCHITECTURE (Terms, F1–F10, INV-01…23); interfaces from [`PHASE0_PREFLIGHT.md`](PHASE0_PREFLIGHT.md) §8 |
| Result | Runnable deterministic core; **73 tests pass on Python 3.12 and 3.10**, 0 skipped; ruff and mypy clean; a deep randomized property run of 1,500 generated races per property passed |

## 1. What was implemented

- **A single-writer session kernel** with the decide/apply split. It covers:
  - goals and slot registers (last writer wins);
  - task-graph resolution into content keys;
  - supersession and cancel emission (D3, D7);
  - dispatch timing (D5, and D2 for superseded twins);
  - result admission with monotonic outcomes (D1, D6);
  - the operation ledger, commit barrier and provenance (INV-13–17);
  - `hold` (D4);
  - multimodal evidence by frame;
  - clarifications, snapshots, the FINAL answer and the deadline governor.
- **Core types:** frozen dataclasses with canonical JSON, SHA-256 content keys and idempotency keys.
- **Deterministic time:** a `FakeClock` and a discrete-event `Scheduler` with the fixed tie rule (events before timers at equal time; re-arming replaces).
- **Ordered inbox:** one `seq` per event, dedupe by harness id only, and payloads frozen at the boundary.
- **Journal + replay:** a full JSONL record of each event, rule, state change, action and effect. Replay reproduces it byte for byte.
- **Tool registry:** manifest validation and quarantine, read-only vs state-changing classification with the reason recorded, and schema-validated canonical arguments.
- **Egress validation** of every action against an internal action schema (INV-22).
- **Scripted planner and perception** (not models) behind the Phase 0 request/response shapes.
- **A local scenario runner:** a discrete-event simulator with scripted tools (latency, outcome, whether a cancel is honoured, duplicate delivery). It provides scenarios A–H with variants, and a CLI.

## 2. Module structure

```
agent/
  model.py        domain types, enums, canonical JSON, content_key, idempotency_key, snapshot()
  clock.py        FakeClock, Scheduler (tie rule, live-timer tracking)
  inbox.py        Inbox: seq assignment, dedupe by harness id, payload freezing
  journal.py      Journal (JSONL), replay()
  registry.py     ToolSpec, Registry.from_manifest, classify, canonicalize
  understand.py   fast-understanding interface; Phase 1 'annotated' implementation
  kernel.py       State, Tx (write overlay), Kernel.decide/apply, pure derivations (resolve, op_state, …)
  protocol.py     egress action schema validation
  runtime.py      Runtime: inbox -> kernel -> egress; record_step()
  planner.py      ScriptedPlanner, ScriptedPerception
  scenario.py     Sim (discrete-event world), scenarios A–H, CLI
tests/
  invariants.py               CheckedKernel: per-step checker for INV-01, 03, 04, 06–16, 18–22
  test_foundation.py          keys, clock, inbox, registry, egress schema, static purity checks
  test_scenarios.py           scenarios A–H with exact expected behaviour
  test_adversarial.py         22 adversarial sequences
  test_replay_properties.py   replay (INV-23), hash-seed/process independence, seeded property tests
```

**Run:**
- `uv venv --python 3.12 .venv && uv pip install -e ".[dev]"`
- `python -m pytest` (CI: `.github/workflows/ci.yml`, a 3.10 + 3.12 matrix with ruff and mypy)
- `python -m agent.scenario B` prints a scenario's timeline
- `PRISM_DEEP=1500 python -m pytest tests/test_replay_properties.py` runs the deep randomized race search

## 3. Important interfaces

| Interface | Shape |
|---|---|
| Event input | `Event(kind, t, payload, eid=None, seq=0)`. `kind` ∈ `Kind`. `t` is harness time and the kernel's only "now". |
| Sequencing | `Inbox.put(event) -> Event \| None` (None = duplicate harness id); `Inbox.get()` |
| Kernel | `Kernel.step(event) -> StepResult{seq, rev_before, rev_after, changes, actions, effects, rules, desired}` |
| State store | `State.get(table, key)`, `State.items(table)`; written only by `Kernel.apply(changes)` |
| Fast understanding | `understand(text, payload) -> Understanding(cls, writes, confirm)`, pure |
| Planner worker | effect `{"effect": "reason", req_id, based_on_seq, purpose, view}` → `Proposal` / `ProposalFailed` event |
| Perception worker | effect `{"effect": "perceive", req_id, kind: vision\|asr, source_eid, ref, hints}` → `Evidence` / `UserText(source=asr)` / `PerceptionFailed` |
| Tool I/O | action `TOOL_CALL{call_id, tool, args, uses, idempotency_key?}`; event `ToolResult{call_id, outcome: ok\|error\|cancelled_ack\|malformed, executed?, data}` |
| Cancellation | action `CANCEL{call_id, reason}` (advisory, to the harness); effect `cancel_effect{target: reasoner, req_id}` |
| Timers | effects `arm{timer_id, purpose, due_t, ref}` / `disarm{timer_id}` → `Timer` event |
| Egress | `validate_action(action)` raises on protocol-invalid payloads |
| Journal/replay | `Journal.add/dumps/write/loads`; `replay(journal, kernel_factory) -> ReplayReport{identical, steps, first_divergence}` |

## 4. State ownership and the concurrency boundary

- **Ownership.** `State` holds named tables (`meta`, `goals`, `slots`, `calls`, `ops`, `frames`, `timers`, `pending`, `reqs`) of **immutable** values.
  - `Kernel.decide` reads through a `Tx` overlay and returns a change list.
  - `Kernel.apply` is the **only** code that writes a table, and it increments the state revision.
  - A test enforces this structurally, using the syntax tree of the kernel module and a scan of every other module.
- **Serialized:** everything in a step (§6.1 of the review).
  - A step never awaits, reads no clock, does no I/O and calls no model. A syntax-tree test forbids `time`, `datetime`, `random`, `uuid`, `os`, `asyncio`, sockets, `hash()`, `open()` and similar in kernel-side modules.
  - Measured step latency over 4,127 steps: **p50 0.10 ms, p99 1.21 ms, max 1.75 ms** (dev machine; the review's budget is p99 < 5 ms).
- **Concurrent:** in Phase 1, "concurrency" is simulated by the discrete-event scheduler. Workers (tools, planner, perception, timers) only ever produce events that re-enter through `Runtime.submit`. None of them holds a reference to state; they receive frozen views.

## 5. Journal format

One canonical-JSON object per line:

| `type` | Content |
|---|---|
| `header` | `version`, `config` (all kernel constants) |
| `in` | `seq`, full `event` (including every worker output: proposals, evidence, tool results, timers) |
| `step` | `seq`, `rev_before`, `rev_after`, `rules` (named decisions with reasons, e.g. `REL.supersede`, `ADM.stale`, `LWW.reject`, `BARRIER.block`, `PLAN.rev`), `changes` (table, key, new value), `desired` (active goal's `plan_rev` and desired keys) |
| `out` | `seq`, full `action` (`action_id`, `kind`, `rule`, `caused_by`, payload with `uses` / `grounded_on`) |
| `fx` | `seq`, effect request (planner, perception, timer arm/disarm, cancel) |
| `dup` | an event dropped as a duplicate |
| `egress_error` | an action rejected by egress validation (never observed in tests) |

This answers the jury's two questions:
- **"Why this call?"** Follow `out.caused_by` → the `step` rules at that seq (`REC.dispatch` with key and node) → the `in` event.
- **"Why was c1 ignored?"** Look at `REL.supersede` (reason and seq) and `ADM.stale`.

## 6. Replay mechanism

`replay()` builds a fresh kernel from the header's config and feeds the `in` records in `seq` order. It then requires identical `step`, `out` and `fx` records. No harness, model or timer runs: their outputs are already inbox events.

Replay is tested in four ways:
- every scenario;
- repeated runs and a JSONL round-trip;
- **across processes with `PYTHONHASHSEED` 0 / 1 / 4242 / random**, where the journals are byte-identical;
- after tampering with one input, where the first divergent record is reported.

## 7. Tests and invariant coverage

`CheckedKernel` wraps **every step of every scenario, adversarial and property test**:
- it runs `decide` twice on the same state (INV-01 purity and determinism);
- it verifies the step against the invariants listed below.

| INV | Covered by |
|---|---|
| 01 single writer | `CheckedKernel` (every step); syntax-tree test that only `apply` writes state |
| 02 time | syntax-tree test (no clock or randomness imports in kernel modules); scheduler tie-rule tests; replay under different processes |
| 03 ordering | `CheckedKernel`: cancels before calls; action ids ascend |
| 04 execution identity | `CheckedKernel`: unique `call_id` / `action_id` |
| 05 content key | order-independence, value sensitivity; subprocesses with 4 hash seeds |
| 06 relevance consistency | `CheckedKernel`: every DESIRED call's key is desired; at most one per key |
| 07 supersession terminal | `CheckedKernel`; revert test (D1) |
| 08 prompt supersession | `CheckedKernel`; scenario B asserts the cancel is in the correction's own step |
| 09 stale-result rejection | `CheckedKernel` at the moment of use (`uses`, `grounded_on`); scenarios B, C, E2, H2; property tests |
| 10 outcome recording | `CheckedKernel` transition table; unknown-call-id test; anomaly test |
| 11 cancel semantics | `CheckedKernel` (exactly when D7 requires, at most once); non-cancellable tool test; timeout coincidence (scenario C) |
| 12 read-only dispatch | `CheckedKernel`; the D2 twin test; no dispatch while a turn is open |
| 13 one unresolved attempt | `CheckedKernel`; booking-race property test (1,500 deep examples) |
| 14 commit barrier | `CheckedKernel` at every state-changing dispatch |
| 15 provenance | `CheckedKernel` (goal origin must be a user-content seq); unsolicited-proposal and no-provenance tests |
| 16 reconciliation | `CheckedKernel`; scenarios D and D2; duplicate-request test |
| 17 idempotency key | property test (200 generated cases); retry-with-same-key test |
| 18 last writer wins | `CheckedKernel`; scenario E2 (stale planner output rejected); older-evidence test |
| 19 hold liveness | `CheckedKernel` (a clearer always exists; cleared at session end); content-free interrupt test |
| 20 truthful speech | `CheckedKernel` (no speech during an open turn; answers grounded); scenario D (no false FINAL) |
| 21 snapshot correctness | `CheckedKernel` (FINAL snapshot equals state); deadline governor test |
| 22 protocol validity | `CheckedKernel` validates every action; malformed-action tests |
| 23 deterministic replay | replay tests (all scenarios, repeated, JSONL, cross-process, tamper detection); every property example |

**Test counts:**
- 73 test functions, 0 skipped, 0 failed, on Python 3.12 and 3.10.
- The three property tests run 60 derandomized examples each by default, and passed 1,500 random examples each in the deep run.

**Failures found and fixed during this phase:**

| Finding | Kind | Resolution |
|---|---|---|
| `supersede()` checked relevance on a possibly stale copy of the call, so it could double-cancel | kernel bug, caught in self-review before first run | re-read the call from the overlay first |
| The scheduler delivered stale instances of re-armed timers | simulator defect | the kernel already ignored them (`TIMER.stale`); now fixed at source |
| Three property assertions were stronger than the architecture | test bugs: an earlier truthful answer, a pre-correction booking, retries exhausted by jitter | corrected to the precise contract |
| `agent/__init__.py` missing | packaging (found by mypy) | added |

## 8. Known limitations

These are Phase 1 simplifications; none violates an invariant.

1. **Runtime is synchronous.** The discrete-event simulator stands in for the asyncio loop. The real loop, the `ClockSource` implementations and the wall-time watchdog (PHASE0 §4.5) wait for the evaluation kit.
2. **Fast understanding is scripted.** Turn classes and slot values come from annotations on internal test events. Schema-derived recognisers are Phase 3.
3. **Churn from an unattributed correction.** Per F5, a correction marker without a slot value supersedes the active goal's read-only calls. Because of INV-12, the same keys are re-dispatched when the turn closes, before the planner re-plans, which is a rerun of identical work. This follows the locked text literally and is **flagged for review** in Phase 2/3; the architecture was not changed.
4. **Speech is minimal and templated.** It covers one acknowledgement per dispatching step, clarifications and FINAL. There is no progress narration, filler budget, status-query answers or LLM wording.
5. **Compensation is not implemented.** A committed operation whose arguments diverge always becomes a CLARIFY, which F6 allows ("otherwise CLARIFY"). A modify/cancel tool as a new operation comes later.
6. **Evidence conflicts block only state-changing calls.** A read-only goal may still answer with the user's value while the clarification is outstanding (review §8.5: "user value wins for read-only work").
7. **Planner requests are made only at turn close** (purpose `understand`). There are no mid-task re-planning requests for judgement over results.
8. **`agent_speaking` / barge-in yield is not modelled** (UNK-7), because there is no simulated speech duration.
9. **A frame that arrives before any goal** attaches to the next goal created.
10. **The journal is in memory** and written on demand; it has no asynchronous file writer yet.

## 9. Deliberately NOT implemented yet

- the protocol ingress/egress **wire mapping** (UNK-1; evaluation kit);
- a real clock source (G3);
- real planner, ASR and vision backends (G11), and the perception worker process;
- schema-derived fast understanding (T0);
- asyncio runtime and effect executors;
- the deadline wall-time watchdog;
- compensation tools;
- natural speech wording;
- Docker, deployment, UI, timeline viewer;
- any model, agent framework or infrastructure dependency. Runtime dependencies are `jsonschema` only.
