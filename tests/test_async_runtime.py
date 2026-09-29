"""Phase 2: asynchronous runtime. Kernel steps stay sequential and invariant-checked (CheckedKernel);
workers are gated by the test (no sleeps), so every outcome is deterministic."""

import asyncio
import dataclasses
import threading
from collections.abc import Callable

from agent.async_runtime import AsyncRuntime, Worker
from agent.clock import FakeClock, WallClock
from agent.journal import Journal, replay
from agent.kernel import Config, Kernel
from agent.model import ActionKind, Event, Kind, Relevance
from agent.scenario import FIND, MANIFEST, PLANS, eot, flights, result, say, to_mumbai
from tests.invariants import CheckedKernel


class Gated:
    """A worker whose requests wait until the test releases them (or answer at once if auto)."""

    def __init__(self, answer: dict | Callable, auto: bool = False):
        self.answer, self.auto = answer, auto
        self.gates: dict[str, asyncio.Event] = {}
        self.started: list[str] = []

    async def __call__(self, request: dict) -> dict:
        rid = request["req_id"]
        self.started.append(rid)
        if not self.auto:
            await self.gates.setdefault(rid, asyncio.Event()).wait()
        out = self.answer(request) if callable(self.answer) else self.answer[request["view"]["turn_text"]]
        if isinstance(out, Exception):
            raise out
        return out

    def release(self, *rids: str) -> None:
        for rid in rids:
            self.gates.setdefault(rid, asyncio.Event()).set()


class NonReentrantKernel(CheckedKernel):
    active = False
    steps = 0

    def step(self, event):
        assert not self.active, "kernel step re-entered"
        self.active = True
        try:
            self.steps += 1
            return super().step(event)
        finally:
            self.active = False


def make(planner=None, perceiver=None, manual=True, clock=None, manifest=None):
    kernel = NonReentrantKernel()
    journal = Journal(header={"config": dataclasses.asdict(kernel.config)})
    rt = AsyncRuntime(kernel, journal, clock or FakeClock(), planner=planner, perceiver=perceiver, manual_time=manual)
    rt.manifest = manifest or MANIFEST  # type: ignore[attr-defined]
    return rt


async def put(rt, event, t):
    if rt.manual_time:
        await rt.advance(t)
    rt.submit(dataclasses.replace(event, t=t))
    await rt.drain()


async def start(rt, t0=0.0):
    await put(rt, Event(Kind.SESSION_START, 0.0, {}), t0)
    await put(rt, Event(Kind.MANIFEST, 0.0, {"tools": rt.manifest}), t0)


def kinds(rt):
    return [a.kind.value for a in rt.actions]


def rules(rt, name):
    return [r for rec in rt.journal.of_type("step") for r in rec["rules"] if r["rule"] == name]


def comparable(journal):
    return [r for r in journal.records if r["type"] in ("in", "step", "out", "fx")]


def replays(journal):
    return replay(journal, lambda h: Kernel(Config(**h["config"]))).identical


async def correction_flow(planner):
    rt = make(Worker(planner))
    async with rt:
        await start(rt)
        await put(rt, say(FIND), 0.1)
        await put(rt, eot(), 0.5)
        assert planner.started == ["r1"] and kinds(rt) == []
        planner.release("r1")
        await rt.quiesce()
        assert kinds(rt) == ["TOOL_CALL", "SPEAK"]
        await put(rt, to_mumbai(), 1.4)
        assert kinds(rt)[-1] == "CANCEL"  # same step as the correction, no model involved
        await put(rt, eot(), 1.6)
        assert rt.actions[-3].kind is ActionKind.TOOL_CALL and "BOM" in str(rt.actions[-3].payload["args"])
        await put(rt, result("c1", data=flights({"destination": "DEL", "date": "Fri"})), 2.8)
        planner.release("r2")
        await rt.quiesce()
        await put(rt, result("c2", data=flights({"destination": "BOM", "date": "Fri"})), 3.6)
    return rt


def test_async_correction_end_to_end_stale_result_rejected_and_replayable():
    rt = asyncio.run(correction_flow(Gated(PLANS)))
    assert rules(rt, "ADM.stale")[0]["call_id"] == "c1"
    final = [a for a in rt.actions if a.kind is ActionKind.FINAL][-1]
    assert final.payload["grounded_on"] == ["c2"]
    assert replays(rt.journal)


def test_async_runs_are_deterministic_given_the_same_arrival_order():
    a = asyncio.run(correction_flow(Gated(PLANS)))
    b = asyncio.run(correction_flow(Gated(PLANS)))
    assert comparable(a.journal) == comparable(b.journal)


def test_conversation_stays_responsive_while_the_planner_works():
    async def main():
        planner = Gated(PLANS)
        rt = make(Worker(planner))
        async with rt:
            await start(rt)
            await put(rt, say(FIND), 0.1)
            await put(rt, eot(), 0.5)
            steps = rt.core.kernel.steps
            await put(rt, say("uh-huh"), 0.6)  # the planner is still blocked
            await put(rt, eot(), 0.7)
            assert rt.core.kernel.steps == steps + 2  # both stepped immediately
            assert planner.started == ["r1"]  # a backchannel turn does not ask the planner
            planner.release("r1")
            await rt.quiesce()
        return rt
    rt = asyncio.run(main())
    assert kinds(rt) == ["TOOL_CALL", "SPEAK"]


def test_workers_run_concurrently_while_kernel_steps_never_overlap():
    async def main():
        planner = Gated(PLANS)
        perceiver = Gated(lambda r: {"claims": {"date": ["Fri", 0.9]}})
        rt = make(Worker(planner), Worker(perceiver))
        async with rt:
            await start(rt)
            await put(rt, say(FIND), 0.1)
            await put(rt, Event(Kind.MEDIA, 0.0, {"kind": "image", "ref": "img"}, "f1"), 0.2)
            await put(rt, eot(), 0.5)
            await asyncio.sleep(0)
            assert planner.started == ["r1"] and perceiver.started == ["p1"]  # both in flight at once
            perceiver.release("p1")
            planner.release("r1")
            await rt.quiesce()
        return rt
    rt = asyncio.run(main())  # NonReentrantKernel asserts no overlap on every step
    assert any(r["event"]["kind"] == "Evidence" and r["event"]["payload"]["frame_eid"] == "f1"
               for r in rt.journal.of_type("in"))


def test_planner_timeout_becomes_proposal_failed():
    async def hang(request):
        await asyncio.Event().wait()
    async def main():
        rt = make(Worker(hang, timeout_s=0.05))
        async with rt:
            await start(rt)
            await put(rt, say(FIND), 0.1)
            await put(rt, eot(), 0.5)
            await rt.quiesce()
        return rt
    rt = asyncio.run(main())
    assert rules(rt, "PROP.failed")[0]["reason"] == "timeout"
    assert [r["event"] for r in rt.journal.of_type("worker")] == ["timeout"]


def test_worker_exception_becomes_a_failure_event_not_a_crash():
    async def main():
        rt = make(Worker(Gated(lambda r: ValueError("backend down"), auto=True)))
        async with rt:
            await start(rt)
            await put(rt, say(FIND), 0.1)
            await put(rt, eot(), 0.5)
            await rt.quiesce()
            await put(rt, say("hello again"), 1.0)  # the runtime keeps working
        return rt
    rt = asyncio.run(main())
    assert rules(rt, "PROP.failed")[0]["reason"] == "error:ValueError"
    assert rt.core.kernel.steps >= 6


def test_honoured_cancel_means_the_superseded_proposal_never_arrives():
    async def main():
        planner = Gated(PLANS)
        rt = make(Worker(planner))
        async with rt:
            await start(rt)
            await put(rt, say(FIND), 0.1)
            await put(rt, eot(), 0.5)
            await put(rt, to_mumbai(), 0.6)
            await put(rt, eot(), 0.7)  # new planner request r2; r1 is cancelled (advisory, honoured)
            planner.release("r1", "r2")
            await rt.quiesce()
        return rt
    rt = asyncio.run(main())
    proposals = [r["event"]["payload"]["req_id"] for r in rt.journal.of_type("in") if r["event"]["kind"] == "Proposal"]
    assert proposals == ["r2"]
    events = {(r["req_id"], r["event"]) for r in rt.journal.of_type("worker")}
    assert ("r1", "cancelled") in events and ("r1", "cancel_requested") in events


def test_ignored_cancel_late_proposal_is_admitted_field_by_field():
    async def main():
        planner = Gated(PLANS)
        rt = make(Worker(planner, honors_cancel=False))
        async with rt:
            await start(rt)
            await put(rt, say(FIND), 0.1)
            await put(rt, eot(), 0.5)
            await put(rt, to_mumbai(), 0.6)  # no goal yet: T0 cannot attribute
            await put(rt, eot(), 0.7)  # r2 requested; r1 cancel requested but not honoured
            planner.release("r2")
            while rt.journal.of_type("in")[-1]["event"]["kind"] != "Proposal":
                await asyncio.sleep(0)
            await rt.drain()
            planner.release("r1")  # the stale proposal arrives after the newer one
            await rt.quiesce()
        return rt
    rt = asyncio.run(main())
    reject = [r for r in rules(rt, "LWW.reject") if r["slot"] == "destination"]
    assert reject, "stale DEL must lose to the newer BOM"
    call = next(a for a in rt.actions if a.kind is ActionKind.TOOL_CALL)
    assert call.payload["args"]["destination"] == "BOM"
    assert ("r1", "cancel_requested") in {(r["req_id"], r["event"]) for r in rt.journal.of_type("worker")}
    assert replays(rt.journal)


def test_manual_timers_fire_deterministically_and_retry():
    manifest = [dict(MANIFEST[0], timeout_s=1.0)] + MANIFEST[1:]
    async def main():
        rt = make(Worker(Gated(PLANS, auto=True)), manifest=manifest)
        async with rt:
            await start(rt)
            await put(rt, say(FIND), 0.1)
            await put(rt, eot(), 0.5)
            await rt.quiesce()  # proposal stamped at clock 0.5 -> c1 dispatched, timeout due 1.5
            assert kinds(rt) == ["TOOL_CALL", "SPEAK"]
            await rt.advance(1.49)
            assert kinds(rt) == ["TOOL_CALL", "SPEAK"]
            await rt.advance(1.5)
        return rt
    rt = asyncio.run(main())
    assert kinds(rt)[2:4] == ["CANCEL", "TOOL_CALL"]
    assert rt.core.kernel.state.get("calls", "c1").relevance is Relevance.SUPERSEDED
    assert replays(rt.journal)


def test_live_timers_on_the_wall_clock():
    manifest = [dict(MANIFEST[0], timeout_s=0.05)] + MANIFEST[1:]
    async def main():
        rt = make(Worker(Gated(PLANS, auto=True)), manual=False, clock=WallClock(), manifest=manifest)
        async with rt:
            for ev in (Event(Kind.SESSION_START, 0, {}), Event(Kind.MANIFEST, 0, {"tools": manifest}), say(FIND), eot()):
                rt.submit(dataclasses.replace(ev, t=rt.now()))
                await rt.drain()
            await rt.quiesce()
            for _ in range(100):  # outcome-based wait: up to 2 s for 3 timeouts of 0.05 s
                if any(a.kind is ActionKind.CLARIFY for a in rt.actions):
                    break
                await asyncio.sleep(0.02)
        return rt
    rt = asyncio.run(main())
    assert kinds(rt).count("TOOL_CALL") == 3 and kinds(rt).count("CANCEL") == 3  # 1 + 2 retries
    assert rt.actions[-1].payload["reason"] == "exhausted"


def test_perception_worker_evidence_and_failure():
    async def main(perceiver):
        rt = make(Worker(Gated(PLANS, auto=True)), Worker(perceiver))
        async with rt:
            await start(rt)
            await put(rt, Event(Kind.MEDIA, 0.0, {"kind": "image", "ref": "img"}, "f1"), 0.1)
            await rt.quiesce()
        return rt
    ok = asyncio.run(main(Gated(lambda r: {"claims": {"model": ["WW90T", 0.93]}}, auto=True)))
    assert ok.core.kernel.state.get("frames", "f1").claims == (("model", "WW90T", 0.93),)
    bad = asyncio.run(main(Gated(lambda r: RuntimeError("camera"), auto=True)))
    assert [r for r in rules(bad, "PERCEPTION.failed")]


def test_submit_threadsafe_from_another_thread():
    async def main():
        rt = make(Worker(Gated(PLANS, auto=True)))
        async with rt:
            await start(rt)
            thread = threading.Thread(target=rt.submit_threadsafe,
                                      args=(Event(Kind.TOOL_RESULT, 0.3, {"call_id": "c7", "outcome": "ok"}),))
            thread.start()
            thread.join()
            for _ in range(100):
                await asyncio.sleep(0)
                if rules(rt, "ADM.unknown_call"):
                    break
        return rt
    assert rules(asyncio.run(main()), "ADM.unknown_call")


def test_workers_cannot_forge_identity_fields():
    forged = {**PLANS[FIND], "req_id": "r99", "based_on_seq": 999, "frame_eid": "x"}
    async def main():
        rt = make(Worker(Gated(lambda r: forged, auto=True)))
        async with rt:
            await start(rt)
            await put(rt, say(FIND), 0.1)
            await put(rt, eot(), 0.5)
            await rt.quiesce()
        return rt
    rt = asyncio.run(main())
    proposal = next(r["event"]["payload"] for r in rt.journal.of_type("in") if r["event"]["kind"] == "Proposal")
    assert proposal["req_id"] == "r1" and proposal["based_on_seq"] == 3 and "frame_eid" not in proposal
    assert rules(rt, "GOAL.create")
