"""Asynchronous runtime (Phase 2): concurrent workers around the single-writer kernel.

AsyncRuntime wraps the synchronous Runtime (inbox -> kernel -> journal -> egress), so every kernel step is
still one synchronous call, in inbox (seq) order, and never re-entered. What it adds:

  * a drain loop: submit() only enqueues; steps run in the loop, so a callback can never interleave steps;
  * worker tasks for planner/perception effects, each with a timeout; failures become events;
  * advisory cancellation: honoured by cancelling the task, or ignored by workers that cannot stop;
    either way the kernel's admission rules decide what a late result may change;
  * timers in harness time, fired live (loop.call_later) or manually (deterministic tests);
  * thread-safe submission for executor threads and worker processes.

Workers return CONTENT only. Identity fields (req_id, based_on_seq, frame ids) are attached here, so a
worker cannot forge them; call ids, snapshots and state remain the kernel's alone.
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from agent.journal import Journal
from agent.kernel import Kernel, StepResult
from agent.model import Action, Event, Kind, freeze
from agent.runtime import Runtime

WorkerFn = Callable[[dict], Awaitable[dict]]
_RESERVED = ("req_id", "based_on_seq", "frame_eid", "source_eid")


@dataclass
class Worker:
    fn: WorkerFn
    timeout_s: float = 10.0
    honors_cancel: bool = True  # False: the work cannot be stopped (e.g. a busy process); its result still arrives


class AsyncRuntime:
    def __init__(self, kernel: Kernel, journal: Journal, clock: Any, *, planner: Worker | None = None,
                 perceiver: Worker | None = None, manual_time: bool = False,
                 on_action: Callable[[Action], None] | None = None):
        self.core = Runtime(kernel, journal, self._on_action, self._on_effect, self._observe)
        self.journal, self.clock = journal, clock
        self.workers = {"reason": planner, "perceive": perceiver}
        self.manual_time = manual_time
        self.actions: list[Action] = []
        self.outbox: asyncio.Queue[Action] = asyncio.Queue()
        self._on_action_cb = on_action
        self._tasks: dict[str, asyncio.Task] = {}
        self._unstarted: set[str] = set()  # spawned worker tasks that have not begun running yet
        self._timers: dict[str, tuple[float, dict, asyncio.TimerHandle | None]] = {}
        self._submitted_at: dict[int, float] = {}
        self._wake = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._drainer: asyncio.Task | None = None
        self.metrics: dict[str, list[float]] = {"step_ms": [], "hop_ms": [], "worker_ms": []}

    # ------------------------------------------------------------ lifecycle

    async def __aenter__(self) -> AsyncRuntime:
        self._loop = asyncio.get_running_loop()
        self._drainer = self._loop.create_task(self._drain_loop())
        return self

    async def __aexit__(self, *exc: Any) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        for _, _, handle in self._timers.values():
            if handle is not None:
                handle.cancel()
        if self._drainer is not None:
            self._drainer.cancel()
            await asyncio.gather(self._drainer, *self._tasks.values(), return_exceptions=True)

    async def _drain_loop(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            self.core.run_until_idle()

    # ------------------------------------------------------------ ingress

    def now(self) -> float:
        return float(self.clock.now())

    def submit(self, event: Event) -> Event | None:
        """Enqueue an event (loop thread only). The kernel step happens in the drain loop."""
        sequenced = self.core.submit(event)
        if sequenced is not None:
            self._submitted_at[sequenced.seq] = time.perf_counter()
        self._wake.set()
        return sequenced

    def submit_threadsafe(self, event: Event) -> None:
        assert self._loop is not None, "runtime not started"
        self._loop.call_soon_threadsafe(self.submit, event)

    async def drain(self) -> None:
        """Wait until every submitted event has been stepped and every worker it spawned has started
        (workers may still be running). Independent of event-loop scheduling details."""
        while self._wake.is_set() or len(self.core.inbox) or self._unstarted:
            await asyncio.sleep(0)

    async def quiesce(self) -> None:
        """Wait until no event is queued and no worker is running (don't use with gated workers)."""
        while True:
            await self.drain()
            pending = [t for t in self._tasks.values() if not t.done()]
            if not pending:
                await self.drain()
                if not self._tasks and not len(self.core.inbox):
                    return
                continue
            await asyncio.wait(pending)

    async def advance(self, t: float) -> None:
        """Manual time: move the clock to t, fire due timers in (due_t, timer_id) order, then drain."""
        assert self.manual_time, "advance() is for manual time"
        self.clock.advance_to(t)
        for tid, (due, _, _) in sorted(self._timers.items(), key=lambda kv: (kv[1][0], kv[0])):
            if due <= t:
                self._fire(tid, due)
        await self.drain()

    # ------------------------------------------------------------ egress and effects (called inside a step)

    def _on_action(self, action: Action) -> None:
        self.actions.append(action)
        self.outbox.put_nowait(action)
        if self._on_action_cb is not None:
            self._on_action_cb(action)

    def _on_effect(self, effect: dict) -> None:
        kind = effect["effect"]
        if kind in ("reason", "perceive"):
            loop = asyncio.get_running_loop()
            rid = effect["req_id"]
            self._unstarted.add(rid)
            task = loop.create_task(self._work(kind, effect))
            task.add_done_callback(functools.partial(self._forget_unstarted, rid))  # also if cancelled before start
            self._tasks[rid] = task
        elif kind == "cancel_effect":
            self._cancel(effect["req_id"], "reason" if effect.get("target") == "reasoner" else "perceive")
        elif kind == "arm":
            self._arm(effect)
        elif kind == "disarm":
            self._disarm(effect["timer_id"])

    def _forget_unstarted(self, rid: str, _task: asyncio.Task) -> None:
        self._unstarted.discard(rid)

    def _observe(self, event: Event, res: StepResult, elapsed: float) -> None:
        self.metrics["step_ms"].append(elapsed * 1000)
        submitted = self._submitted_at.pop(event.seq, None)
        if submitted is not None:
            self.metrics["hop_ms"].append((time.perf_counter() - submitted) * 1000 - elapsed * 1000)

    # ------------------------------------------------------------ workers

    def _cancel(self, req_id: str, kind: str) -> None:
        worker = self.workers.get(kind)
        task = self._tasks.get(req_id)
        honoured = worker is not None and worker.honors_cancel and task is not None and not task.done()
        self.journal.add({"type": "worker", "req_id": req_id, "event": "cancel_requested", "honoured": honoured})
        if honoured and task is not None:
            task.cancel()

    async def _work(self, kind: str, request: dict) -> None:
        worker = self.workers.get(kind)
        rid = request["req_id"]
        started = time.perf_counter()
        outcome = "ok"
        event: Event | None = None

        async def call(fn: WorkerFn) -> dict:
            # Runs where the worker actually runs: on 3.10 wait_for wraps it in an inner task, on 3.12 not.
            self._unstarted.discard(rid)
            return await fn(freeze(request))

        try:
            if worker is None:
                raise RuntimeError(f"no {kind} worker configured")
            content = await asyncio.wait_for(call(worker.fn), worker.timeout_s)
            event = self._result_event(kind, request, content)
        except asyncio.CancelledError:
            outcome = "cancelled"  # honoured cancel: nothing re-enters
        except asyncio.TimeoutError:
            outcome, event = "timeout", self._failure_event(kind, request, "timeout")
        except Exception as exc:  # a worker bug or backend failure must never take the runtime down
            outcome, event = "error", self._failure_event(kind, request, f"error:{type(exc).__name__}")
        finally:
            self._tasks.pop(rid, None)
        duration = (time.perf_counter() - started) * 1000
        self.metrics["worker_ms"].append(duration)
        self.journal.add({"type": "worker", "req_id": rid, "kind": kind, "event": outcome, "ms": round(duration, 3)})
        if event is not None:
            self.submit(event)

    def _result_event(self, kind: str, request: dict, content: dict) -> Event:
        if not isinstance(content, dict):
            raise TypeError("worker must return a dict")
        body = {k: v for k, v in content.items() if k not in _RESERVED}  # identity is not the worker's to set
        now = self.now()
        if kind == "reason":
            return Event(Kind.PROPOSAL, now, {**body, "req_id": request["req_id"], "based_on_seq": request["based_on_seq"]})
        if "claims" in body:
            return Event(Kind.EVIDENCE, now, {"claims": body["claims"], "frame_eid": request["source_eid"]})
        if "text" in body:
            return Event(Kind.USER_TEXT, now, {**body, "source": "asr", "source_eid": request["source_eid"]})
        raise ValueError("perception result needs 'claims' or 'text'")

    def _failure_event(self, kind: str, request: dict, reason: str) -> Event:
        now = self.now()
        if kind == "reason":
            return Event(Kind.PROPOSAL_FAILED, now,
                         {"req_id": request["req_id"], "based_on_seq": request["based_on_seq"], "reason": reason})
        return Event(Kind.PERCEPTION_FAILED, now, {"req_id": request["req_id"], "reason": reason})

    # ------------------------------------------------------------ timers (harness time)

    def _arm(self, effect: dict) -> None:
        tid, due = effect["timer_id"], effect["due_t"]
        self._disarm(tid)
        payload = {k: effect[k] for k in ("timer_id", "purpose", "due_t", "ref")}
        handle = None
        if not self.manual_time:
            loop = asyncio.get_running_loop()
            handle = loop.call_later(max(0.0, due - self.now()), self._fire, tid, due)
        self._timers[tid] = (due, payload, handle)

    def _disarm(self, tid: str) -> None:
        entry = self._timers.pop(tid, None)
        if entry is not None and entry[2] is not None:
            entry[2].cancel()

    def _fire(self, tid: str, due: float) -> None:
        entry = self._timers.get(tid)
        if entry is None or entry[0] != due:
            return
        del self._timers[tid]
        self.submit(Event(Kind.TIMER, due, entry[1]))
