"""D17 full duplex: while the user is still speaking, the partial turn is planned and READ-ONLY work may start; later
chunks revise it with the same relevance rules; state-changing work never starts before the turn ends.

Numbered after the brief's test list (K1-K19). Production pipeline: real fast understanding, the deterministic planner
(known examples, then rules), the kernel under the invariant checker, `Config(full_duplex=True)` unless noted."""

import asyncio
import dataclasses
import json
from pathlib import Path

import pytest

from agent.async_runtime import AsyncRuntime, Worker
from agent.clock import FakeClock
from agent.journal import Journal, replay
from agent.kernel import Config, Kernel
from agent.model import ActionKind, Event, Kind, Outcome, Relevance
from agent.planner import ScriptedPerception, ScriptedPlanner
from agent.reasoner.rules import DeterministicPlanner, RulePlanner
from agent.scenario import SCENARIOS, Behavior, Sim, eot, image
from evaluation.agents import AGENTS
from tests.invariants import CheckedKernel

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "evaluation" / "scenarios" / "manifests" / "flights.json").read_text())
FIXTURES = json.loads((ROOT / "agent" / "fixtures" / "scripted.json").read_text())
DUPLEX = Config(full_duplex=True)
PART1, PART2, FIX = "Find a flight from Bangalore to Delhi", "on Friday", "Actually, Mumbai"


def text(t: str, **extra) -> Event:
    return Event(Kind.USER_TEXT, 0.0, {"text": t, **extra})


def flights(a: dict) -> dict:
    return {"flights": [{"id": f"{a['destination']}-701", "price": 4120}]}


def run(script, tools=None, config=DUPLEX, perception=None) -> Sim:
    planner = DeterministicPlanner(ScriptedPlanner(FIXTURES["planner"], 0.25), RulePlanner(0.25))
    tools = tools or {"search_flights": Behavior(2.0, data=flights)}
    sim = Sim(MANIFEST, tools, planner, perception or ScriptedPerception(), config=config, kernel_factory=CheckedKernel)
    return sim.run(script)


def times(sim) -> dict[int, float]:
    return {r["seq"]: r["event"]["t"] for r in sim.journal.records if r["type"] == "in"}


def rules(sim, name) -> list[dict]:
    return [r for rec in sim.journal.records if rec["type"] == "step" for r in rec["rules"] if r["rule"] == name]


def calls(sim) -> list:
    return list(sim.calls().values())


def dests(sim) -> list[str]:
    return [json.loads(c.args_json).get("destination") for c in calls(sim)]


def said(sim) -> list[str]:
    return [a.payload["text"] for a in sim.actions if a.kind in (ActionKind.SPEAK, ActionKind.CLARIFY, ActionKind.FINAL)]


def demo(**kw) -> Sim:
    """The brief's case: partial -> early search -> more input -> correction -> end of turn."""
    return run([(0.1, text(PART1)), (0.6, text(PART2)), (1.2, text(FIX)), (1.6, eot())], **kw)


def dispatched_at(sim, call_id) -> float:
    a = next(a for a in sim.actions if a.kind is ActionKind.TOOL_CALL and a.payload["call_id"] == call_id)
    return times(sim)[a.seq]


# ---------------------------------------------------------------- K1-K5: the early-retrieval case


def test_k1_partial_utterance_starts_read_only_retrieval_before_end_of_turn():
    sim = demo()
    first = calls(sim)[0]
    assert first.tool == "search_flights" and json.loads(first.args_json) == {"origin": "BLR", "destination": "DEL", "date": "Fri"}
    assert dispatched_at(sim, first.call_id) == 0.6 < 1.6  # the chunk that completed the arguments, not the end of turn


def test_k2_early_work_is_marked_partial_and_speculative():
    sim = demo()
    purposes = [r.get("purpose", "understand") for r in rules(sim, "PLANNER.request")]
    assert purposes[0] == "speculate" and purposes[-1] == "understand"  # partial plans, then the finished turn
    assert rules(sim, "PROP.speculative")  # partial proposals are recorded as such
    assert rules(sim, "REC.dispatch")[0].get("early") is True
    fx = [r for r in sim.journal.records if r["type"] == "fx" and r.get("effect", {}).get("effect") == "reason"]
    assert all(r["effect"]["view"].get("partial") is (r["effect"]["purpose"] == "speculate") or
               (r["effect"]["purpose"] != "speculate" and "partial" not in r["effect"]["view"]) for r in fx)
    end = next(s for s, t in times(sim).items() if t == 1.6)
    partial = [r for rec in sim.journal.records if rec["type"] == "step" and rec["seq"] < end for r in rec["rules"]
               if r["rule"] == "LWW.apply" and r["source"] == "PARTIAL"]
    assert {r["slot"] for r in partial} >= {"origin", "destination"}  # planned from the unfinished sentence ...
    unconfirmed = [c for rec in sim.journal.records if rec["type"] == "step" and rec["seq"] < end
                   for c in rec["changes"] if c[0] == "slots" and c[2]["source"] == "PARTIAL"]
    assert unconfirmed and not any(c[2]["confirmed"] for c in unconfirmed)  # ... and never committed as if final
    assert all(a.seq >= end for a in sim.actions if a.kind in (ActionKind.SPEAK, ActionKind.FINAL))  # user holds the floor


def test_k3_the_finished_turn_completes_the_same_task_without_a_duplicate():
    sim = run([(0.1, text(PART1)), (0.6, text(PART2)), (0.9, eot())])
    assert len(calls(sim)) == 1 and [g.intent for _, g in sim.kernel.state.items("goals")] == ["search_flights"]
    assert said(sim)[0].startswith("Already on it: search flights")
    final = sim.of(ActionKind.FINAL)[-1]
    assert final.payload["grounded_on"] == ["c1"] and final.payload["act"] == "answer"
    assert {r["slot"] for r in rules(sim, "SLOT.confirm") if r["by"] == "final_plan"} >= {"origin", "destination"}
    assert all(r.confirmed and r.source != "PARTIAL" for _, r in sim.kernel.state.items("slots"))


def test_k4_a_later_chunk_changes_the_destination_and_supersedes_early_work():
    sim = demo()
    c1, c2 = calls(sim)
    assert (c1.relevance, c1.superseded_reason) == (Relevance.SUPERSEDED, "not_desired") and dests(sim) == ["DEL", "BOM"]
    fix_seq = next(s for s, t in times(sim).items() if t == 1.2)
    assert c1.superseded_seq == fix_seq  # in the correction's own step, not at the end of turn
    cancel = next(a for a in sim.actions if a.kind is ActionKind.CANCEL)
    assert cancel.payload["call_id"] == "c1" and cancel.seq == fix_seq


def test_k5_the_late_early_result_is_recorded_but_refused():
    sim = demo()
    c1 = sim.calls()["c1"]
    assert c1.outcome is Outcome.OK and c1.result_json  # admitted to the journal ...
    assert [r["call_id"] for r in rules(sim, "ADM.stale")] == ["c1"]  # ... and refused
    finals = sim.of(ActionKind.FINAL)
    assert len(finals) == 1 and finals[0].payload["grounded_on"] == ["c2"] and "BOM-701" in finals[0].payload["text"]
    assert finals[0].payload["snapshot"]["slots"]["destination"] == "BOM"


# ---------------------------------------------------------------- K6-K12: safety and existing behaviour


@pytest.mark.parametrize("script", [
    [(0.1, text("Book flight 6E-431")), (0.4, text("for 2 passengers")), (1.0, eot())],
    [(0.1, text("find flights from Bangalore to Delhi on Friday")), (0.4, eot()),  # results, then book by position
     (3.0, text("book the first one")), (3.3, text("for two people")), (4.0, eot())],
])
def test_k6_no_state_changing_call_is_ever_dispatched_speculatively(script):
    tools = {"search_flights": Behavior(0.3, data=flights), "book_flight": Behavior(0.5, data={"booking_id": "B1"})}
    sim, half = run(script, tools=tools), run(script, tools=tools, config=Config())
    book = [a for a in sim.of(ActionKind.TOOL_CALL) if a.payload["tool"] == "book_flight"]
    assert len(book) == 1 and times(sim)[book[0].seq] >= script[-1][0]  # only after the turn that asked for it ended
    assert not any(r.get("early") for r in rules(sim, "REC.dispatch") if r["call_id"] == book[0].payload["call_id"])
    assert book[0].payload["args"] == next(a for a in half.of(ActionKind.TOOL_CALL) if a.payload["tool"] == "book_flight").payload["args"]


def test_k7_an_interruption_during_early_work_supersedes_it_at_once():
    sim = run([(0.1, text("find flights from Bangalore to Delhi on Friday")), (0.5, text("wait, cancel that")),
               (0.9, eot())])
    c1 = sim.calls()["c1"]
    assert dispatched_at(sim, "c1") < 0.5 and c1.relevance is Relevance.SUPERSEDED  # started early (partial plan)
    assert times(sim)[c1.superseded_seq] == 0.5  # superseded in the marker's own step


def test_k8_multi_turn_slot_completion_still_works():
    sim = run([(0.1, text("find me flights from Bangalore to Delhi")), (0.4, eot()),
               (1.5, text("on Friday")), (1.7, eot())], tools={"search_flights": Behavior(0.5, data=flights)})
    assert sim.of(ActionKind.CLARIFY)[0].payload["slots"] == ["date"]  # asked after the turn, never mid-sentence
    assert times(sim)[sim.of(ActionKind.CLARIFY)[0].seq] > 0.4
    assert dests(sim) == ["DEL"] and sim.of(ActionKind.FINAL)[-1].payload["grounded_on"] == ["c1"]


def converse(*turns, config=DUPLEX) -> Sim:
    script, t = [], 0.1
    for turn in turns:
        for chunk in turn:
            script.append((t, text(chunk)))
            t += 0.2
        script.append((t, eot()))
        t += 1.0
    return run(script, tools={"book_flight": Behavior(0.5, data={"booking_id": "B1"})}, config=config)


def slots(sim) -> dict:
    return {n: r.value for (_, n), r in sim.kernel.state.items("slots")}


def test_k9_flight_number_and_passenger_recognition_is_unchanged():
    sim = converse(["Book flight from Bangalore", "to Delhi"], ["Indigo SE", "2020"])
    assert slots(sim).get("flight_id") == "6E-2020" and slots(sim).get("passengers") is None
    assert sim.of(ActionKind.CLARIFY)[-1].payload["slots"] == ["passengers"]


def test_k10_the_booking_dialogue_books_exactly_once():
    sim = converse(["Book flight from Bangalore to Delhi"], ["Indigo SE 2020"], ["for two", "people"])
    books = [json.loads(c.args_json) for c in calls(sim) if c.tool == "book_flight"]
    assert books == [{"flight_id": "6E-2020", "passengers": 2}]
    assert [a.payload["slots"] for a in sim.of(ActionKind.CLARIFY)] == [["flight_id", "passengers"], ["passengers"]]


def test_k11_an_unsupported_request_is_answered_after_the_turn_and_changes_nothing():
    sim = converse(["Book a cab", "from Bangalore to the airport"])
    assert not calls(sim) and not sim.kernel.state.items("goals")
    speech = [a for a in sim.actions if a.kind is ActionKind.SPEAK]
    assert len(speech) == 1 and "can't book a cab" in speech[0].payload["text"]
    assert times(sim)[speech[0].seq] >= 0.5  # after the end of turn, never while the user speaks


def test_k12_a_goal_switch_during_early_work():
    tools = {"search_flights": Behavior(3.0, data=flights), "get_weather": Behavior(0.3, data={"temp_c": 31})}
    sim = run([(0.1, text(PART1)), (0.4, text(PART2)), (0.7, eot()),  # the search started early and is running
               (1.2, text("never mind,")), (1.4, text("what's the weather in Pune?")), (1.8, eot())], tools=tools)
    c1 = sim.calls()["c1"]
    assert dispatched_at(sim, "c1") < 0.7 and c1.relevance is Relevance.SUPERSEDED
    assert times(sim)[c1.superseded_seq] == 1.2  # the switch marker cancels at once
    assert rules(sim, "PROP.speculative_no_switch")  # half a sentence never switches the task ...
    assert not [a for a in sim.of(ActionKind.TOOL_CALL) if a.payload["tool"] == "get_weather" and times(sim)[a.seq] < 1.8]
    assert [c.tool for c in calls(sim)] == ["search_flights", "get_weather"]  # ... the finished turn does; no re-search
    assert "Okay, leaving search_flights for now." in said(sim)
    goals = [g for _, g in sim.kernel.state.items("goals")]
    assert [g.intent for g in goals] == ["search_flights", "get_weather"] and goals[0].status.value == "SUSPENDED"
    final = sim.of(ActionKind.FINAL)[-1]
    assert final.payload["snapshot"]["intent"] == "get_weather" and final.payload["grounded_on"] != ["c1"]


# ---------------------------------------------------------------- K13: multimodal orderings


PERCEPTION = ScriptedPerception({"pass": {"date": ["Fri", 0.95]}, "sat": {"date": ["Sat", 0.95]}},
                                {"clip": {"text": "on Friday"}}, latency=0.3)


@pytest.mark.parametrize("order", ["image_first", "image_mid_turn", "audio_chunk"])
def test_k13_audio_text_and_image_in_different_orders_reach_the_same_state(order):
    words = [(0.1, text(PART1))]
    if order == "image_first":
        script = [(0.05, image("pass", "f1"))] + words + [(1.0, eot())]
    elif order == "image_mid_turn":
        script = words + [(0.5, image("pass", "f1")), (1.0, eot())]
    else:
        script = words + [(0.3, Event(Kind.MEDIA, 0.0, {"kind": "audio", "ref": "clip"})), (1.0, eot())]
    sim = run(script, perception=PERCEPTION)
    assert slots(sim) == {"origin": "BLR", "destination": "DEL", "date": "Fri"}
    assert dests(sim) == ["DEL"] and sim.of(ActionKind.FINAL)[-1].payload["grounded_on"] == ["c1"]


def test_k13_conflicting_evidence_asks_instead_of_choosing():
    sim = run([(0.1, text("find flights from Bangalore to Delhi on Friday")), (0.3, image("sat", "f1")), (1.0, eot())],
              perception=PERCEPTION)
    assert rules(sim, "EV.conflict") and slots(sim)["date"] == "Fri"  # the user's word stands until they answer
    clar = sim.of(ActionKind.CLARIFY)
    assert clar and clar[0].payload["reason"] == "conflict" and times(sim)[clar[0].seq] >= 1.0


def test_k13_evidence_for_an_abandoned_goal_does_not_contaminate_the_new_one():
    tools = {"search_flights": Behavior(2.0, data=flights), "get_weather": Behavior(0.3, data={"temp_c": 31})}
    slow = ScriptedPerception({"pass": {"date": ["Fri", 0.95]}}, latency=2.0)
    sim = run([(0.1, text("find flights from Bangalore to Delhi")), (0.2, image("pass", "f1")), (0.5, eot()),
               (1.0, text("forget it, what's the weather in Pune")), (1.3, eot())], tools=tools, perception=slow)
    weather = next(g for _, g in sim.kernel.state.items("goals") if g.intent == "get_weather")
    assert not any(g == weather.goal_id and n == "date" for (g, n), _ in sim.kernel.state.items("slots"))


# ---------------------------------------------------------------- K14-K15: a slow planner never blocks the fast path


class Gate:
    """Planner worker: speculative requests plan at once; the finished-turn request waits until released."""

    def __init__(self):
        self.rules = RulePlanner(0.0)
        self.release = asyncio.Event()
        self.started: list[str] = []

    async def __call__(self, request: dict) -> dict:
        self.started.append(request["purpose"])
        if request["purpose"] != "speculate":
            await self.release.wait()
        proposal, why = self.rules.plan(request["view"])
        if proposal is None:
            raise RuntimeError(why)
        return proposal


async def put(rt, event, t):
    await rt.advance(t)
    rt.submit(dataclasses.replace(event, t=t))
    await rt.drain()
    await rt.quiesce()


def make_async(gate) -> AsyncRuntime:
    kernel = CheckedKernel(DUPLEX)
    journal = Journal(header={"config": dataclasses.asdict(kernel.config)})
    return AsyncRuntime(kernel, journal, FakeClock(), planner=Worker(gate, timeout_s=30), manual_time=True)


def test_k14_a_slow_planner_does_not_block_the_acknowledgement():
    async def main():
        gate = Gate()
        rt = make_async(gate)
        async with rt:
            await put(rt, Event(Kind.SESSION_START, 0.0, {}), 0.0)
            await put(rt, Event(Kind.MANIFEST, 0.0, {"tools": MANIFEST}), 0.0)
            await put(rt, text("what's the weather"), 0.1)
            await put(rt, text("in Pune"), 0.3)
            await put(rt, eot(), 0.5)
            await rt.advance(1.2)  # the ack timer (0.6 s) fires; the finished-turn plan is still blocked
            await rt.drain()
            spoken = [a.payload["text"] for a in rt.actions if a.kind is ActionKind.SPEAK]
            assert "understand" in gate.started and not gate.release.is_set()  # the finished-turn plan is still blocked
            gate.release.set()
            await rt.quiesce()
            return spoken, rt
    spoken, rt = asyncio.run(main())
    assert spoken == ["Already on it: get weather (city Pune)."]  # early work, said at the end of turn, not after the plan


def test_k15_a_slow_planner_does_not_block_interruption_handling():
    async def main():
        gate = Gate()
        rt = make_async(gate)
        async with rt:
            await put(rt, Event(Kind.SESSION_START, 0.0, {}), 0.0)
            await put(rt, Event(Kind.MANIFEST, 0.0, {"tools": MANIFEST}), 0.0)
            await put(rt, text(PART1), 0.1)
            await put(rt, text(PART2), 0.4)
            await put(rt, eot(), 0.6)  # the finished-turn plan now waits on the gate
            assert [a.kind for a in rt.actions][:1] == [ActionKind.TOOL_CALL]
            await put(rt, text(FIX), 0.9)  # interruption while the planner is busy
            cancel = [a for a in rt.actions if a.kind is ActionKind.CANCEL]
            assert cancel and cancel[0].payload["call_id"] == "c1" and not gate.release.is_set()
            gate.release.set()
            await rt.quiesce()
    asyncio.run(main())


# ---------------------------------------------------------------- K16-K19: determinism and the existing guarantees


def test_k16_replay_is_byte_identical():
    sim = demo()
    assert replay(sim.journal, lambda h: Kernel(Config(**h["config"]))).identical
    again = demo()
    strip = lambda j: [r for r in j.records if r["type"] in ("in", "step", "out", "fx")]  # noqa: E731
    assert strip(sim.journal) == strip(again.journal)


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_k17_k18_reference_scenarios_keep_their_guarantees_in_full_duplex(name):
    """Operation ledger / idempotency (INV-13..16) and stale-result rejection (INV-09) are checked on every step by
    CheckedKernel; the scenario outcomes must match the half-duplex run."""
    on = SCENARIOS[name](config=DUPLEX, kernel_factory=CheckedKernel)
    off = SCENARIOS[name](kernel_factory=CheckedKernel)
    committed = lambda s: sorted(c.op_id for c in s.calls().values() if c.op_id and c.outcome is Outcome.OK)  # noqa: E731
    assert committed(on) == committed(off)  # never a second booking
    grounded = lambda s: [a.payload["grounded_on"] for a in s.of(ActionKind.FINAL)]  # noqa: E731
    args = lambda s, ids: [s.calls()[c].args_json for g in ids for c in g]  # noqa: E731
    assert args(on, grounded(on))[-1:] == args(off, grounded(off))[-1:]  # the same final answer
    for s in (on, off):  # a stale result is never what an answer is grounded on
        stale = {r["call_id"] for rec in s.journal.records if rec["type"] == "step" for r in rec["rules"] if r["rule"] == "ADM.stale"}
        assert not stale & {c for g in grounded(s) for c in g}


def test_k19_the_validated_baseline_is_unchanged_by_default():
    assert Config().full_duplex is False and "--full-duplex" not in AGENTS["impl_a"]  # the 58-scenario baseline
    sim = demo(config=Config())  # half duplex: D5, nothing starts while the user speaks
    assert all(dispatched_at(sim, c.call_id) >= 1.6 for c in calls(sim)) and dests(sim) == ["BOM"]
    assert not rules(sim, "PROP.speculative") and all(r.get("purpose") is None for r in rules(sim, "PLANNER.request"))


@pytest.mark.parametrize("agent", ["impl_a", "impl_a_duplex"])
def test_a_tool_latency_is_relative_to_the_actual_call_in_both_modes(agent):
    """`result_exactly_at_timeout`: the result lands exactly timeout_s after the call, whether the call starts at the
    end of turn (half duplex) or before it (full duplex); events before timers, so it is on time: no cancel, no retry."""
    from evaluation import harness, metrics
    from evaluation.agents import resolve
    from evaluation.scenario import load
    scenario = load(ROOT / "evaluation" / "scenarios" / "adversarial" / "result_exactly_at_timeout.json")
    trace = harness.run(scenario, resolve(agent))
    msgs = [(r["t"], r.get("msg") or json.loads(r["raw"])) for r in trace["records"]]
    call = next(t for t, m in msgs if m["type"] == "tool.call")
    result = next(t for t, m in msgs if m["type"] == "tool.result")
    timeout = next(t["timeout_s"] for t in scenario["manifest"] if t["name"] == "search_flights")
    assert result - call == pytest.approx(timeout, abs=1e-9)
    assert (call < 0.5) is (agent == "impl_a_duplex")  # early only with full duplex (the turn ends at 0.5)
    assert not [m for _, m in msgs if m["type"] == "tool.cancel"]
    assert metrics.evaluate(scenario, trace)["passed"]
