"""Black-box evaluation: every scenario through the real subprocess agent; determinism; replay of the agent's
own journal; and proof that the evaluator discriminates (broken agents must fail)."""

import ast
import json
import sys
from pathlib import Path

import pytest

from agent.adapter.stdio import DEFAULT_FIXTURES, table_understanding
from agent.journal import Journal, replay
from agent.kernel import Config, Kernel
from evaluation import harness, metrics
from evaluation.agents import resolve
from evaluation.scenario import discover, load

ROOT = Path(__file__).resolve().parents[1]
ALL = discover("all")
INTERNAL_WORDS = ("t0", "slot_writes", "graph", "writer_seq", "relevance", "SUPERSEDED", "REL.", "ADM.")


def test_scenario_suite_is_large_enough_and_valid():
    assert len(ALL) >= 30
    assert {p.parent.name for p in ALL} == {"reference", "adversarial"}
    for p in ALL:
        load(p)


@pytest.mark.parametrize("path", ALL, ids=[p.stem for p in ALL])
def test_scenarios_contain_no_agent_internals(path):
    text = path.read_text()
    for word in INTERNAL_WORDS:
        assert f'"{word}' not in text, f"{path.name} mentions agent-internal '{word}'"


@pytest.mark.parametrize("path", ALL, ids=[p.stem for p in ALL])
def test_impl_a_passes_every_scenario_black_box(path):
    scenario = load(path)
    trace = harness.run(scenario, resolve("impl_a"))
    result = metrics.evaluate(scenario, trace)
    failed = [c for c in result["checks"] if not c["passed"]]
    assert result["passed"], failed
    assert not trace["violations"]
    assert result["label"].startswith("INTERNAL PRISM-STYLE")


def test_traces_are_deterministic():
    scenario = load(discover("B_destination_correction")[0])
    a = harness.run(scenario, resolve("impl_a"))
    b = harness.run(scenario, resolve("impl_a"))
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_trace_answers_what_happened():
    trace = harness.run(load(discover("B_destination_correction")[0]), resolve("impl_a"))
    kinds = {r["dir"] for r in trace["records"]}
    assert kinds == {"in", "out"}
    world = [e["event"] for e in trace["world"]["events"]]
    assert {"call_received", "cancel_received", "cancel_ignored", "result_delivered"} <= set(world)
    for r in trace["records"]:
        assert set(r) <= {"t", "dir", "raw", "msg"}  # nothing internal to the agent is recorded


def test_agent_journal_from_a_black_box_run_replays_identically(tmp_path):
    journal_path = tmp_path / "j.jsonl"
    cmd = [sys.executable, "-m", "agent.adapter.stdio", "--journal", str(journal_path)]
    harness.run(load(discover("E2_rapid_corrections_each_turn")[0]), cmd)
    journal = Journal.loads(journal_path.read_text())
    understand = table_understanding(json.loads(DEFAULT_FIXTURES.read_text())["understanding"])
    report = replay(journal, lambda h: Kernel(Config(**h["config"]), understand=understand))
    assert report.identical, report.first_divergence
    assert journal.records[0]["mode"] == "sim-lockstep"


def broken(mode):
    return [sys.executable, "-m", "tests.broken_agents", mode]


def test_evaluator_catches_an_agent_that_never_cancels():
    for sid in ("B_destination_correction", "D_booking_race", "interrupt_1ms_before_completion"):
        scenario = load(discover(sid)[0])
        result = metrics.evaluate(scenario, harness.run(scenario, broken("nocancel")))
        assert not result["passed"], sid
        assert result["categories"]["interruption_recovery"] < 1.0, sid


def test_evaluator_catches_duplicate_state_changing_calls():
    scenario = load(discover("duplicate_booking_request")[0])
    result = metrics.evaluate(scenario, harness.run(scenario, broken("doublecall")))
    failed = {c["check"] for c in result["checks"] if not c["passed"]}
    assert "side_effects_max:book_flight" in failed and result["categories"]["safety_protocol"] < 1.0


def test_evaluator_module_has_no_agent_specific_names():
    for path in (ROOT / "evaluation").glob("*.py"):
        if path.name == "agents.py":
            continue  # the launcher registry is the one agent-specific place
        assert "agent.adapter" not in path.read_text() and "agent.kernel" not in path.read_text(), path
        tree = ast.parse(path.read_text())
        assert not [n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("agent")]
