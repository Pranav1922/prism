# Phase 5 Report — Real Planner / Deep Reasoning

| | |
|---|---|
| Date | 2026-09-30 |
| Plan mapping | [`PHASE2_PLAN.md`](PHASE2_PLAN.md) Phase 4 ("planner and model evaluation layer"). Reported here as "Phase 5", as requested. |
| Result | **323 tests pass on Python 3.12 and 3.10**; ruff and mypy clean; **55/55 black-box scenarios pass with the scripted backend** (47 unchanged vs Phase 4, plus 8 planner scenarios); zero unsafe side effects across ≈ 570 real-model planner requests |
| Model evidence | [`PHASE5_MODEL_EVALUATION.md`](PHASE5_MODEL_EVALUATION.md) |

All numbers are **INTERNAL** measurements on this project's own cases and scenarios, on one development machine (Apple M4, 16 GB, Metal). They are not Samsung scores, and they do not represent the evaluation environment.

## 1. Planner architecture

```
USER ─► FAST UNDERSTANDING (T0, in step) ─► SESSION KERNEL ─► effect "reason" {req_id, based_on_seq, view}
                                               ▲                     │  (async; never on the interruption path)
                                               │                     ▼
                                               │        PLANNER  (agent/reasoner/planner.py)
                                               │          prompt(view) ─► backend.generate(schema) ─► raw JSON
                                               │          convert + validate (+1 repair) ─► internal proposal
                                               │                     │
                                               └── Proposal / ProposalFailed event ◄┘
                          KERNEL ADMISSION (agent/proposal.py + kernel on_proposal):
                          structure check → D14 ordering → LWW fields → taint/injection (D13) → graph
                          → reconcile → commit barrier (hold, provenance, D13 authorisation + grounding, D14)
                          → VALIDATED EXECUTION (tool.call / tool.cancel / speech, all emitted by the kernel)
```

- **The planner proposes; the kernel decides.**
  - The planner returns data. It cannot emit actions, choose call ids, cancel, write snapshots, touch the ledger or declare completion. None of those exist in its output schema.
  - The runtime attaches identity (`req_id`, `based_on_seq`) and strips any identity fields a worker tries to set (unchanged from Phase 2).
- **Off the critical path.**
  - Interruption → cancel happens in the same kernel step as the user input (T0, D3). No model is ever awaited for a supersede or cancel.
  - Status questions are answered from state (D15); they never wait for the planner.

## 2. Planner contract

**INPUT** — `Kernel.planner_view(turn)`, built inside the kernel step (pure), journaled with the effect.

| Field | Content |
|---|---|
| `turn_text`, `turn_classes`, `turn_attributed` | the closing turn, its T0 classes, the slots T0 attributed in it |
| `utterances` | recent closed user turns `[seq, text]` (≤ 12) |
| `goal` | the ACTIVE goal: `goal_id`, `intent`, `plan_rev`, current graph in proposal form |
| `slots` | value, source (T0/PLANNER/USER/EVIDENCE), confirmed, `writer_seq` |
| `results` | DESIRED calls of the goal: node, tool, args, outcome, admitted result data |
| `evidence` | frame claims `{key: [value, confidence]}`, or `awaiting` |
| `pending` | open clarifications (kind, slots, text, asked) |
| `suspended_goals` | ids and intents |
| `tools` | the registry (name, description, effect, JSON-schema parameters) — never a fixed list |

**OUTPUT** — the internal proposal (`agent/proposal.py`):

```
{"intent": <tool-name> | null, "new_goal": bool,
 "slot_writes": {slot: value},
 "graph": [{"node_id", "tool", "instance_tag",
            "args": {param: {"$slot": s} | {"$node": id, "path": [...]} | {"$const": v} | literal}}],
 "clarify": {"text", "slots": [...]}}
```

- **Provenance.**
  - The kernel records it: each written register carries `writer_seq = based_on_seq` and `source = PLANNER`. Each call carries `caused_by`, its content key, and the `writer_seq` of every bound slot.
  - The raw model output, validation errors, corrections, tokens and latency are journaled as `fx_io` records.
- **Reasoning metadata.** The model may add `notes` (≤ 200 characters). They are journaled and never become state.

## 3. Structured output schema

The model does not write the internal format. It writes a simpler, grammar-constrained schema (`output_schema(tool_names)`; the tool enum is built from the live registry):

```
{"intent": <enum of tools> | null, "new_goal": bool,
 "slots": [{"name", "value": scalar, "source": "user"|"evidence"|"result"|"assumed"}],
 "tasks": [{"id", "tool": <enum of tools>, "args": [{"param","slot"} | {"param","from_task","path"} | {"param","value"}]}],
 "clarify": {"question", "slots": [...]} | null, "notes"?: string}
```

- The Ollama backend passes this schema as `format`, so decoding is constrained to it. The OpenAI-compatible backend passes it as `response_format`.
- Parameters are bound per task, and dependencies are expressed by `from_task` (a data dependency).
- There is no separate "after" edge. The kernel's graph has none, and nothing in the problem needs one (DAG machinery is not added).

## 4. Model backends

`agent/reasoner/backends.py` defines a single method, `generate(messages, schema, timeout_s) -> Generation(text, wall_s, tokens)`. It uses stdlib HTTP, with no SDK dependency.

| Backend | Use |
|---|---|
| `scripted` (`agent/planner.py`) | deterministic regression; the fixtures file is keyed by utterance |
| `ollama:<model>` | local models: temperature 0, seed 7, `num_ctx` 8192, grammar-constrained JSON |
| `openai:<model>` | any hosted `/chat/completions` endpoint. Enabled only by `PRISM_OPENAI_BASE_URL` + `PRISM_OPENAI_API_KEY` (never committed or logged). Not exercised: no credentials exist. |
| `replay:<journal>` | REPLAY MODE: returns recorded planner events; never calls a model |
| `FakeBackend` | tests |

Selection: `python -m agent.adapter.stdio --planner ollama:qwen2.5:7b [--planner-latency measured|<s>] [--planner-timeout 8]`. The journal header records the backend, model, decoding options, prompt version and `planner_mode: live|replay`. A/B comparisons use `python -m scripts.ab_planners`.

## 5. Validation layer

Validation happens in two stages. Neither trusts the other.

**1. Worker side (`convert`)** — raw text → internal proposal:
- JSON parse, then the output schema (unknown tool = schema violation).
- Structural check (`agent/proposal.check`).
- One repair round-trip: the errors are sent back to the model.
- Deterministic corrections, each recorded as a note:
  - `assumed` values are dropped (a missing value becomes a question, never a default);
  - an unbound required parameter is bound to its slot and asked for, if it has no value and no image is pending;
  - a change to an already-filled slot that this turn is not about is dropped (the user's value stays);
  - a dependency on an existing task the model didn't repeat keeps that task;
  - nodes are sorted topologically; a cycle is an error;
  - two generic small-model slips are normalised: a value placed in the `slot` field, and `"slot": "null"`;
  - `new_goal=true` on a turn T0 classified as a correction or answer is ignored (it would have suspended the user's task).

**2. Kernel side (`check_proposal` + admission)** — whatever a proposer sends:
- Unknown field, bad intent name, unknown tool or parameter, a `$node` forward/self reference (cycle), a duplicate state-changing task, a bad clarify, or more than 8 nodes → `PROP.invalid`. Nothing changes.
- Values are validated against the tool schema when the graph is resolved. An invalid value produces an `invalid_args` clarification, never a call.

## 6. Provenance and injection safety (D13)

The chain is user input → T0 → kernel → planner request (`user_seq`) → proposal (`based_on_seq`) → goal (`origin_seq`) → graph → barrier → dispatch (`caused_by`). The kernel enforces three rules at admission and dispatch; the invariant checker re-verifies them on every step:

1. **Authorisation.** A state-changing task needs a user utterance of its goal that names the operation (the tool's verb or a synonym), or the user's explicit "yes" to the exact arguments.
2. **Grounding.** Every planner-chosen value in a state-changing call must be something the user said. Otherwise the kernel asks for confirmation of the exact arguments first.
3. **Taint.** A string that appears in tool results or evidence but was never said by the user cannot reach a state-changing argument as a literal or slot value, only through `$node` (which resolves to DESIRED results only, INV-09).
   - An unauthorised *and* tainted task is dropped, along with the slot writes only it would read, without asking the user about it (injection shape).
   - An authorised task with a tainted literal is asked about.

This is tested with:
- an injected instruction inside a search result, run both through a deliberately compromised scripted planner (the black-box scenario `injection_in_search_result`) and through kernel tests 13 / 13b;
- a planner-invented passenger count (`booking_count_never_given`, `test_planner_invented_value_for_a_side_effect_is_confirmed_first`);
- a forged proposal with no request (test 18);
- unauthorised booking (test 04).

The prompt also tells the model that results and evidence are data, not instructions, but no safety property depends on the model obeying that.

## 7. Replanning

- Every content turn (except status-only turns, D15) requests the planner at turn close. The request carries the newest content seq as `based_on_seq`.
- The previous open request is cancelled (advisory): the async runtime cancels the worker task, while lockstep workers let it finish. Either way, the kernel decides what its late answer may change.
- **Corrections during planning.** T0 writes the new value in the user's own step (`writer_seq` = that seq) and cancels in-flight read-only work (D3). Planner fields based on older input lose by last-writer-wins. Tests: 05/06, 15, 16; scenarios `correction_before_first_plan`, `rapid_corrections_during_planning`.
- **Unrelated valid work continues.** Read-only calls that the newer input did not affect keep running. State-changing dispatch waits while a newer task-changing request is still open (D14), so a booking never goes out on a plan the user already corrected (test 06).

## 8. Stale planner results

A proposal is identified by `req_id` + `based_on_seq`. It is admitted only if that request exists (test 18: a forged or unknown request changes nothing). What remains valid is decided per part:

| Part | Rule |
|---|---|
| slot fields | last-writer-wins against `based_on_seq`: a newer user or T0 value always wins; unrelated older fields still apply (F4) |
| intent / goal switch | only if `based_on_seq` ≥ the goal-switch seq and ≥ the active goal's `origin_seq`; otherwise the **whole** proposal is stale (it describes a superseded framing) |
| graph | only if `based_on_seq` ≥ the graph's own `graph_seq`: an older plan fills in a graph that no newer proposal set, but never overwrites a newer one |
| side effects | none while a newer task-changing request is open (D14) |

Stale planner results are therefore merged by field, not discarded wholesale (test 15a: the older graph plus the newer destination produce exactly one BOM search).

## 9. Failure handling

| Failure | Behaviour | Test |
|---|---|---|
| model timeout / backend error | `ProposalFailed(timeout\|backend)`; the kernel says it couldn't work that out; state unchanged | `test_backend_timeout…`, test 11 |
| invalid JSON / partial output / schema violation | one repair; then `ProposalFailed(invalid)` | `test_invalid_model_output…`, `test_planner_repairs_once…` |
| hallucinated tool / unknown parameter | schema enum, then `check` → repair or failure; the kernel's own check → `PROP.invalid` | test 01, parametrised cases |
| missing required argument | bound to its slot and asked for; never dispatched without a value | test 02 |
| contradictory / circular plan | `PROP.invalid` | tests 09, 10 |
| duplicate state-changing work | `PROP.invalid` | test 08 |
| worker cancelled | the task is cancelled; nothing re-enters | test 12 |
| worker exception (async) | `ProposalFailed(error:…)` | `test_model_planner_runs_as_an_async_worker…` |
| result after correction / goal switch / out of order | see §8 | tests 05–07, 15, 16 |

A bad proposal never corrupts state: it is rejected before any change (`PROP.invalid`), or admitted field by field under the kernel's rules. Every test step runs under `CheckedKernel` (INV-01…23 plus the D13/D14 checks).

## 10. Performance

- **Critical path.** Unchanged, and model-free: interruption → cancel is the same kernel step (0.00 s virtual in every scenario and every backend).
- **While a planner call is running** (live AsyncRuntime, 1.5 s model call in progress): interruption → `tool.cancel` takes 1.1 ms median (4.0 ms max), and turn close → acknowledgement 1.3 ms (`scripts/bench_planner_path.py`).
- **Model latency** (warm, this machine): qwen2.5:3b p50 3.8–5.5 s; qwen2.5:7b 6.1–9.4 s; llama3.1:8b 7.9–9.5 s. Startup is 1.7 / 3.3 / 3.9 s. Planner answer → first tool call is 0.00 s (the same kernel step). Details: [`PHASE5_MODEL_EVALUATION.md`](PHASE5_MODEL_EVALUATION.md).
- **Planner timeout** (8 s budget): 1/95 requests for qwen2.5:3b, 53/95 for qwen2.5:7b, 61/95 for llama3.1:8b. Each ends as "couldn't work that out", and the session stays usable.
- **Output tokens dominate.** Compact single-line JSON with optional notes halved the latency (qwen2.5:3b 4.5 → 2.5 s; qwen2.5:7b 9.0 → 5.4 s per call, warm).

## 11. Deterministic replay

- **Kernel replay (INV-23).** Unchanged. Planner outputs are ordinary inbox events (`Proposal`/`ProposalFailed`), so replaying a journal never calls a model.
- **Black-box replay of a model-driven run.** `--planner replay:<journal>`:
  - it returns each recorded planner event at its recorded virtual latency;
  - it verifies that the request view's digest matches the recording (otherwise "replay diverged");
  - it never contacts a model.
- `test_live_model_run_replays_identically_without_the_model` runs a live (fake-backend, measured-latency) session, then replays it: the wire output is byte-identical, and a diverging input is detected.
- `planner_mode: live|replay` is recorded in the journal header.

## 12. Test results

| Suite | Result |
|---|---|
| `tests/test_planner.py` (new) | 48 tests: validation layer, the 18 adversarial cases (+13b, 10 × 8 invalid graphs), worker cancel, async worker, live→replay equivalence, 3 recorded real-model replays, invented-value confirmation, truthful status during planning |
| all earlier tests | pass unchanged. Input text only: 3 Phase 1 test files and 8 scenarios now say "for one person" (see the evaluation doc §7); `test_understanding`'s ticket request now says "create" |
| invariant checker | INV-01…23 + D13 (authorisation, grounding) + D14 (no side effect while replanning), on every step |
| black-box, scripted | 55/55; Phase 4 vs Phase 5 on the 47 shared scenarios: identical scores and latencies |
| replay | INV-23 journal replay; black-box replay of 3 × 55 recorded model runs identical |
| total | **323 passed** on 3.12 and 3.10; ruff, mypy clean |

## 13. A/B model comparison

| Backend | quality-only pass (mean) | measured pass (mean) | planner p50 | unsafe side effects |
|---|---|---|---|---|
| scripted | 55/55 (99.9) | 55/55 (99.9) | — | 0 |
| qwen2.5:3b | 22/55 (86.4) | 21/55 (63.9) | 4.4–5.5 s | 0 |
| **qwen2.5:7b** | **40/55 (91.1)** | 11/55 (52.7) | 8–9.4 s | 0 |
| llama3.1:8b | 21/55 (79.8) | 4/55 (43.6) | 8–9.5 s | 0 |

- **Selected:** qwen2.5:7b for quality, qwen2.5:3b as the latency fallback. `scripted` remains the default, because no local model passes the suite.
- The full evidence and failure modes are in [`PHASE5_MODEL_EVALUATION.md`](PHASE5_MODEL_EVALUATION.md).

## 14. Known limitations

- **No local model is good enough to plan unsupervised.** The kernel keeps every observed model error from becoming a side effect, but plan quality still limits task completion (see the evaluation).
- **Lexical authorisation and grounding.** The rules are deliberately conservative:
  - "ticket for my cracked screen" (no verb) and "Mumbai" vs a planner-canonicalised `BOM` in a state-changing argument lead to a confirmation question rather than an action;
  - synonyms are a short hand-written list.
- **Taint covers strings only.** Numbers collide with ordinary result fields. The grounding rule covers numbers for state-changing calls instead.
- **Unrelated-slot guard.** The validator drops a model's change to a filled slot that the turn is not about (not attributed by T0, not named, value not present). An unusual paraphrase ("the weekend instead") is therefore dropped rather than applied; the user must restate it.
- **No conditional or ordering edges** beyond data dependencies. "Book if the weather is fine" is not expressible.
- **The remote backend is untested** (no credentials).
- **Measured model latency.** It becomes virtual time, so live runs are not reproducible by re-running; replay mode reproduces them exactly.
- **Development-machine numbers** (Apple M4 + Metal) say nothing about a CPU-only evaluation host. There, the 7–8B models would be many times slower.

## 15. Next phase

Phase 6 — multimodal perception (PHASE2_PLAN Phase 6):
- a perception worker process behind the existing `perceive` effect;
- evidence events with confidence and alternatives.

Nothing in the planner contract changes: evidence already reaches the planner view as data, and the kernel's conflict rule already blocks side effects on conflicting evidence.
