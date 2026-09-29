# Phase 2 Report — Real (Asynchronous) Runtime

| | |
|---|---|
| Date | 2026-09-30 |
| Plan | [`PHASE2_PLAN.md`](PHASE2_PLAN.md) §3, Phase 2 |
| Result | `AsyncRuntime` implemented; **86 tests pass on Python 3.12 and 3.10** (73 Phase 1 unchanged + 13 new; the async tests passed 20/20 repeated runs); ruff and mypy clean; replay deterministic; benchmarked |

## What was built

`agent/async_runtime.py`: **`AsyncRuntime`**, which composes the unchanged synchronous `Runtime` (inbox → kernel → journal → egress).

| Requirement | Mechanism |
|---|---|
| Kernel remains the sole state writer | Workers get a frozen request (`freeze`) and return content only; the runtime turns that into an event and `submit()`s it |
| Deterministic ordering at the kernel boundary | Every event, including worker results and timers, goes through the one inbox (`seq`). A **drain loop** runs steps sequentially. `submit()` never steps inline, so a callback cannot interleave steps or reorder egress. |
| Asynchronous worker execution | Planner and perception effects run as asyncio tasks (`Worker(fn, timeout_s, honors_cancel)`) |
| Event re-entry | Results become `Proposal` / `Evidence` / `UserText(source=asr)` events. The identity fields (`req_id`, `based_on_seq`, `frame_eid`, `source_eid`) are attached by the runtime, and anything the worker returns under those names is discarded. |
| Cancellation requests | The kernel's `cancel_effect` → the task is cancelled if the worker honours cancels. Otherwise the work continues and its late result is judged by the kernel's admission rules (per-field last-writer-wins). Both are journaled as `worker` records. |
| Concurrent tool/model/perception work | Multiple worker tasks in flight at once. Tools run in the (mock) harness and are reached through actions and events. |
| Timeouts | `asyncio.wait_for` per worker → `ProposalFailed` / `PerceptionFailed(reason="timeout")` |
| Worker failures | Any exception → failure event with `reason="error:<Type>"`; the runtime keeps running |
| Late results | Always re-enter as events; the kernel decides (stale proposal fields lose by last-writer-wins; stale tool results are recorded, never used) |
| Timers | Harness-time timers from kernel `arm`/`disarm` effects. **Live:** `loop.call_later` on a `WallClock`. **Manual:** `advance(t)` fires due timers in `(due_t, timer_id)` order, for deterministic tests. |
| Threads / processes | `submit_threadsafe()` (via `call_soon_threadsafe`) for executor threads and future worker processes |
| Metrics | A `Runtime` observer hook records step duration and queue hop (submit → step); `worker` journal records carry durations. Metrics never feed decisions. |

`agent/clock.py` gains `WallClock` (the live stand-in until the harness clock is known, G3). The **synchronous simulator is unchanged** and remains the deterministic test bed.

## Tests (`tests/test_async_runtime.py`, 13)

Workers are **gated by the test** (an `asyncio.Event` per request) and time is manual, so outcomes never depend on timing luck. Every kernel is a `CheckedKernel` (INV-01…22 on every step) that also asserts **no step re-entry**.

| Test | Proves |
|---|---|
| async correction end-to-end | Same-step cancel on correction; the late c1 result is stale; FINAL on c2; journal replays identically |
| deterministic given the same arrival order | Two async runs produce identical `in`/`step`/`out`/`fx` records |
| responsive while planner works | User events are stepped immediately while the planner is blocked; backchannels don't call the planner |
| workers concurrent, steps never overlap | Planner and perception in flight simultaneously; the re-entry assertion holds |
| planner timeout | → `ProposalFailed(timeout)` |
| worker exception | → `ProposalFailed(error:ValueError)`; the runtime keeps working |
| honoured cancel | The superseded request never delivers; `cancel_requested` + `cancelled` are journaled |
| ignored cancel | The late stale proposal loses `destination` to the newer one by last-writer-wins; the dispatch uses BOM; replay identical |
| manual timers | Timeout fires exactly at `due_t` (not at 1.49), then cancel + same-step retry; replay identical |
| live timers (wall clock) | Three 50 ms timeouts → 3 cancels + 3 dispatches → exhausted clarification (outcome-based wait) |
| perception evidence / failure | Evidence lands on its frame; failure → `PerceptionFailed` |
| thread-safe submit | An event from another thread is stepped |
| identity cannot be forged | A worker-returned `req_id` / `based_on_seq` / `frame_eid` are discarded |

## Benchmark (`scripts/bench_async_runtime.py 300`)

Live mode, wall clock, plain `Kernel`, instant scripted planner, Apple M4 dev machine. **This machine is indicative only; the evaluation host is unknown.**

| Metric | p50 | p95 | p99 | max | Path |
|---|---|---|---|---|---|
| correction submit → CANCEL action | 0.244 ms | 0.299 ms | 0.311 ms | 0.316 ms | critical |
| queue hop (submit → step start) | 0.106 ms | 1.276 ms | 1.341 ms | 2.538 ms | critical |
| kernel step | 0.082 ms | 1.175 ms | 1.236 ms | 1.657 ms | critical |
| end of turn → planner task → TOOL_CALL | 0.447 ms | 0.510 ms | 0.606 ms | 2.870 ms | background (planner is instant here) |

- The step/hop p95–p99 tail comes from the one-time manifest step (JSON Schema validation of every tool).
- **Burst throughput:** 3,381 events/s. **CPU:** 1.24 s for 300 sessions + the burst.
- **Max RSS of the benchmark process:** 200.5 MB. This includes every retained journal; per-session memory will be profiled in Phase 12.

## Defect found and fixed during this phase

The async tests first passed on 3.12 but failed deterministically on **3.10**. `drain()` promised that every spawned worker had started, but it marked "started" in the outer task. On 3.10, `asyncio.wait_for` runs the worker in an *inner* task that begins one loop iteration later, whereas on 3.12 it runs directly. The mark now sits inside the coroutine that `wait_for` executes, and a done-callback clears it if a task is cancelled before starting, so `drain()` can never hang. Verified on both versions, 10 repeated runs each.

## Remaining / limitations

- **No real workers yet.** They are Phases 3, 4 and 6; the worker interface is fixed and tested.
- **Perception worker process:** `submit_threadsafe` exists, but the multiprocessing worker is Phase 6.
- **Live clock** is `WallClock`. The Samsung harness clock semantics (G3) plug in behind the same `clock.now()` plus timer handling once the kit exists.
- **The live-mode tie rule** (events before timers at equal time) holds only in manual/sim mode. In live mode, ordering is arrival order, and the kernel's timer check (`due_t` match) keeps it correct.
