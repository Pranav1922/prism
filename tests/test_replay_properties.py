"""INV-23 deterministic replay, and seeded property tests over adversarial timings.

Hypothesis runs derandomized (fixed example sequence) so the suite never depends on luck; every generated
run is checked step-by-step by CheckedKernel and must replay identically.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from agent.journal import Journal, replay
from agent.kernel import Config, Kernel, active_goal, desired_ok_call, resolve
from agent.model import ActionKind, Outcome, Relevance, snapshot
from agent.planner import ScriptedPlanner
from agent.scenario import FIND, MANIFEST, PLANS, SCENARIOS, Behavior, Sim, eot, flights, say
from tests.invariants import CheckedKernel

ROOT = Path(__file__).resolve().parents[1]
# Default: derandomized, 60 examples per property (fast, reproducible CI).
# PRISM_DEEP=N: N random examples per property (quality gate / nightly); failures print a reproducible seed.
_DEEP = int(os.environ.get("PRISM_DEEP", "0"))
PROPS = settings(derandomize=not _DEEP, max_examples=_DEEP or 60, deadline=None,
                 suppress_health_check=[HealthCheck.too_slow])


def kernel_from_header(header: dict) -> Kernel:
    return Kernel(Config(**header["config"]))


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_every_scenario_replays_identically(name):
    sim = SCENARIOS[name]()
    report = replay(sim.journal, kernel_from_header)
    assert report.identical, report.first_divergence
    assert report.steps == len(sim.journal.of_type("in"))


@pytest.mark.parametrize("name", ["B", "D", "E2", "F"])
def test_replay_repeated_and_through_jsonl_round_trip(name, tmp_path):
    sim = SCENARIOS[name]()
    path = tmp_path / "j.jsonl"
    sim.journal.write(str(path))
    loaded = Journal.loads(path.read_text())
    for _ in range(3):
        assert replay(loaded, kernel_from_header).identical
    assert SCENARIOS[name]().journal.dumps() == sim.journal.dumps()  # same inputs -> same journal, byte for byte


def test_journal_identical_across_processes_and_hash_seeds():
    code = "from agent.scenario import SCENARIOS; import hashlib; " \
           "print(hashlib.sha256(''.join(SCENARIOS[k]().journal.dumps() for k in sorted(SCENARIOS)).encode()).hexdigest())"
    digests = set()
    for seed in ("0", "1", "4242", "random"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        digests.add(subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
                                   check=True).stdout.strip())
    assert len(digests) == 1


def test_replay_detects_a_tampered_journal():
    sim = SCENARIOS["B"]()
    tampered = Journal.loads(sim.journal.dumps())
    for rec in tampered.records:
        if rec["type"] == "in" and rec["event"]["payload"].get("text") == "actually, to Mumbai":
            rec["event"]["payload"]["t0"]["writes"]["destination"] = "GOI"
    report = replay(tampered, kernel_from_header)
    assert not report.identical and report.first_divergence is not None


# ---------------------------------------------------------------- seeded timing perturbations of the scenarios


@PROPS
@given(name=st.sampled_from(["B", "C", "D", "D2", "E", "E2", "F", "H", "H2"]), seed=st.integers(0, 10_000),
       jitter=st.sampled_from([0.0, 0.3, 1.0, 2.5]))
def test_scenarios_hold_invariants_under_jittered_timing(name, seed, jitter):
    sim = SCENARIOS[name](kernel_factory=CheckedKernel, seed=seed, jitter=jitter)
    assert replay(sim.journal, kernel_from_header).identical
    # INV-09 at the moment of use is checked per step by CheckedKernel. At the end: if the active goal is
    # satisfied, the last answer must rest on current work and match the current snapshot. (If later work
    # never completed, e.g. retries exhausted, an earlier answer legitimately stays the last one.)
    state = sim.kernel.state
    goal = active_goal(state)
    ds = resolve(state, goal)
    satisfied = bool(ds) and all(desired_ok_call(state, goal.goal_id, d.key) for d in ds if d.key) and all(d.key for d in ds)
    finals = sim.of(ActionKind.FINAL)
    if satisfied and goal.intent == "search_flights":
        last = finals[-1].payload
        assert last["snapshot"] == snapshot(goal, dict(state.items("slots")))
        calls = sim.calls()
        for cid in last["grounded_on"]:
            assert calls[cid].relevance is Relevance.DESIRED and calls[cid].outcome is Outcome.OK


# ---------------------------------------------------------------- generated correction storms

DESTS = ["DEL", "BOM", "GOI", "MAA"]


@st.composite
def correction_storm(draw):
    events, t = [(0.1, say(FIND)), (0.5, eot())], draw(st.floats(0.6, 3.0))
    plans = dict(PLANS)
    for i in range(draw(st.integers(1, 5))):
        dest = draw(st.sampled_from(DESTS))
        text = f"make it {dest} #{i}"
        plans[text] = {"intent": "search_flights", "slot_writes": {"destination": dest}}
        events.append((t, say(text, "CORRECTION", {"destination": dest})))
        if draw(st.booleans()):
            t += draw(st.floats(0.0, 1.0))
            events.append((t, eot()))
        t += draw(st.floats(0.0, 1.5))
    events.append((t + 0.1, eot()))
    # a closing turn text is the concatenation of its chunks; teach the planner every suffix it may see
    texts = [e.payload["text"] for _, e in events if e.payload and "text" in e.payload and e.payload["text"] != FIND]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts) + 1):
            joined = " ".join(texts[i:j])
            plans.setdefault(joined, {"intent": "search_flights",
                                      "slot_writes": {"destination": texts[j - 1].split()[2]}})
    latency = draw(st.floats(0.05, 4.0))
    return events, plans, latency, draw(st.booleans())


@PROPS
@given(storm=correction_storm())
def test_correction_storms_final_answer_matches_last_correction(storm):
    events, plans, latency, honors = storm
    sim = Sim(MANIFEST, {"search_flights": Behavior(latency, data=flights, honors_cancel=honors)},
              ScriptedPlanner(plans), kernel_factory=CheckedKernel).run(events)
    assert replay(sim.journal, kernel_from_header).identical
    last_dest = [e for _, e in events if e.payload.get("t0")][-1].payload["t0"]["writes"]["destination"]
    fin = sim.of(ActionKind.FINAL)
    assert fin, "every storm ends with a closed turn and a responding tool, so it must be answered"
    assert fin[-1].payload["snapshot"]["slots"]["destination"] == last_dest
    grounded = sim.calls()[fin[-1].payload["grounded_on"][0]]
    assert json.loads(grounded.args_json)["destination"] == last_dest
    cancels = [a.payload["call_id"] for a in sim.of(ActionKind.CANCEL)]
    assert len(cancels) == len(set(cancels))  # at most one cancel per call


@PROPS
@given(correct_at=st.floats(0.61, 2.5), latency=st.floats(0.05, 2.0), honors=st.booleans(),
       close_after=st.floats(0.0, 1.0))
def test_booking_races_never_create_twice_while_unresolved(correct_at, latency, honors, close_after):
    tools = {"book_flight": Behavior(latency, data={"booking_id": "B1"}, honors_cancel=honors)}
    sim = Sim(MANIFEST, tools, ScriptedPlanner(PLANS), kernel_factory=CheckedKernel).run(
        [(0.1, say("book flight 6E-701")), (0.3, eot()),
         (correct_at, say("wait, two of us", "CORRECTION", {"passengers": 2})), (correct_at + close_after, eot())])
    assert replay(sim.journal, kernel_from_header).identical
    calls = list(sim.calls().values())
    ok = [c for c in calls if c.outcome is Outcome.OK]
    assert len(ok) <= 1  # a single side effect, whatever the race
    if len(calls) > 1:  # a second attempt only after the first was known not to have executed
        assert calls[0].outcome is Outcome.FAILED_CLEAN
    if ok and json.loads(ok[0].args_json)["passengers"] == 1:  # committed before the correction could stop it
        assert any(a.payload["reason"] == "divergence" for a in sim.of(ActionKind.CLARIFY))
        # a FINAL may truthfully report the 1-passenger booking if it completed before the correction,
        # but no FINAL may ever claim 2 passengers on the strength of it
        assert all(f.payload["snapshot"]["slots"]["passengers"] == 1 for f in sim.of(ActionKind.FINAL))
