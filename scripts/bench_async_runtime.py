"""Phase 2 benchmark: live AsyncRuntime latencies (wall clock, plain Kernel, instant scripted planner).

    python scripts/bench_async_runtime.py [iterations]

Critical path:   submit -> kernel step (queue hop), step duration, correction -> CANCEL action.
Background path: end of turn -> planner task -> proposal -> TOOL_CALL action.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import resource
import sys
import time

from agent.async_runtime import AsyncRuntime, Worker
from agent.clock import WallClock
from agent.journal import Journal
from agent.kernel import Kernel
from agent.model import ActionKind, Event, Kind
from agent.scenario import FIND, MANIFEST, PLANS, eot, say, to_mumbai


async def planner(request: dict) -> dict:
    return PLANS[request["view"]["turn_text"]]


async def wait_for(rt: AsyncRuntime, kind: ActionKind, count: int) -> float:
    while sum(1 for a in rt.actions if a.kind is kind) < count:
        await asyncio.sleep(0)
    return time.perf_counter()


async def one(samples: dict) -> None:
    rt = AsyncRuntime(Kernel(), Journal(), WallClock(), planner=Worker(planner))
    async with rt:
        for ev in (Event(Kind.SESSION_START, 0, {}), Event(Kind.MANIFEST, 0, {"tools": MANIFEST}), say(FIND)):
            rt.submit(dataclasses.replace(ev, t=rt.now()))
        await rt.drain()
        t0 = time.perf_counter()
        rt.submit(dataclasses.replace(eot(), t=rt.now()))
        samples["eot_to_tool_call_ms"].append((await wait_for(rt, ActionKind.TOOL_CALL, 1) - t0) * 1000)
        t1 = time.perf_counter()
        rt.submit(dataclasses.replace(to_mumbai(), t=rt.now()))
        samples["correction_to_cancel_ms"].append((await wait_for(rt, ActionKind.CANCEL, 1) - t1) * 1000)
        samples["hop_ms"] += rt.metrics["hop_ms"]
        samples["step_ms"] += rt.metrics["step_ms"]


async def burst(n: int) -> float:
    rt = AsyncRuntime(Kernel(), Journal(), WallClock(), planner=Worker(planner))
    async with rt:
        rt.submit(Event(Kind.SESSION_START, 0, {}))
        t0 = time.perf_counter()
        for i in range(n):
            rt.submit(Event(Kind.USER_TEXT, rt.now(), {"text": "uh-huh"}, f"b{i}"))
        await rt.drain()
        return n / (time.perf_counter() - t0)


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    samples: dict[str, list[float]] = {"eot_to_tool_call_ms": [], "correction_to_cancel_ms": [], "hop_ms": [], "step_ms": []}
    cpu0 = time.process_time()
    for _ in range(n):
        asyncio.run(one(samples))
    report = {k: {"p50": round(pct(v, .5), 3), "p95": round(pct(v, .95), 3), "p99": round(pct(v, .99), 3),
                  "max": round(max(v), 3), "n": len(v)} for k, v in samples.items()}
    report["burst_events_per_s"] = round(asyncio.run(burst(2000)))
    report["cpu_s"] = round(time.process_time() - cpu0, 2)
    report["max_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
