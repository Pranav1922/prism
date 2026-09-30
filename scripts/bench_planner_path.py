"""Phase 5: deep planning stays off the interruption path (wall clock, live AsyncRuntime, indicative only).

    python -m scripts.bench_planner_path [runs]

A search is in flight and the planner is busy in a worker thread (a 1.5 s model call). The user corrects the
destination: we measure wall ms from submit() to the tool.cancel action and to the spoken acknowledgement at turn
close, while the planner call is still running.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import sys
import time

from agent.async_runtime import AsyncRuntime, Worker
from agent.clock import FakeClock
from agent.journal import Journal
from agent.kernel import Kernel
from agent.model import ActionKind, Event, Kind
from agent.reasoner.backends import FakeBackend
from agent.reasoner.planner import ModelPlanner
from agent.scenario import eot
from tests.test_planner import FIND, MANIFEST, TASK, model_out


def backend(messages: list[dict]) -> str:
    view = json.loads(messages[1]["content"])
    if view["turn_text"] == FIND:
        return model_out(slots=[{"name": n, "value": v, "source": "user"} for n, v in
                                (("origin", "BLR"), ("destination", "DEL"), ("date", "Fri"))], tasks=[TASK])
    time.sleep(1.5)  # a slow deep-planning call, in the worker thread
    return model_out(new_goal=False, slots=[])


async def once() -> tuple[float, float, bool]:
    planner = ModelPlanner(FakeBackend(backend), timeout_s=10)
    rt = AsyncRuntime(Kernel(), Journal(), FakeClock(), planner=Worker(planner.worker, 10.0), manual_time=True)
    async with rt:
        for t, e in [(0.0, Event(Kind.SESSION_START, 0.0, {})), (0.0, Event(Kind.MANIFEST, 0.0, {"tools": MANIFEST})),
                     (0.1, Event(Kind.USER_TEXT, 0.0, {"text": FIND})), (0.3, eot())]:
            rt.clock.advance_to(t)
            rt.submit(Event(e.kind, t, e.payload))
            await rt.drain()
        while not any(a.kind is ActionKind.TOOL_CALL for a in rt.actions):
            await asyncio.sleep(0.001)  # the first plan arrives; the search is dispatched and never answers
        rt.clock.advance_to(1.0)
        rt.submit(Event(Kind.USER_TEXT, 1.0, {"text": "what's the weather like there"}))  # a content turn: slow plan
        rt.submit(Event(Kind.END_OF_TURN, 1.1, {}))
        await rt.drain()
        busy = bool(rt._tasks)
        t0 = time.perf_counter()
        rt.submit(Event(Kind.USER_TEXT, 1.2, {"text": "actually, to Mumbai"}))
        await rt.drain()
        cancel = (time.perf_counter() - t0) * 1000
        assert any(a.kind is ActionKind.CANCEL for a in rt.actions)
        t1 = time.perf_counter()
        rt.submit(Event(Kind.END_OF_TURN, 1.3, {}))
        await rt.drain()
        ack = (time.perf_counter() - t1) * 1000
        await rt.quiesce()
    return cancel, ack, busy


def main() -> None:
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    res = [asyncio.run(once()) for _ in range(runs)]
    cancel, ack = [r[0] for r in res], [r[1] for r in res]
    print(json.dumps({"planner_busy_during_interrupt": all(r[2] for r in res),
                      "interrupt_to_cancel_ms": {"median": round(statistics.median(cancel), 3), "max": round(max(cancel), 3)},
                      "turn_close_to_ack_ms": {"median": round(statistics.median(ack), 3), "max": round(max(ack), 3)},
                      "planner_call_s": 1.5, "runs": runs}, indent=1))


if __name__ == "__main__":
    main()
