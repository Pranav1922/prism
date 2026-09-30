"""Infrastructure scenarios A–H. Every step runs through CheckedKernel (INV-01, 03, 04, 06–16, 18–22)."""

import json

from agent.model import ActionKind, Outcome, Relevance
from agent.scenario import (
    scenario_a,
    scenario_b,
    scenario_c,
    scenario_d,
    scenario_e,
    scenario_f,
    scenario_g,
    scenario_h,
)
from tests.invariants import CheckedKernel

CK = {"kernel_factory": CheckedKernel}


def rules(sim, name):
    return [r for rec in sim.journal.of_type("step") for r in rec["rules"] if r["rule"] == name]


def final(sim):
    finals = sim.of(ActionKind.FINAL)
    assert finals, "no FINAL"
    return finals[-1].payload


def test_a_search_result_final():
    sim = scenario_a(**CK)
    assert sim.kinds() == ["TOOL_CALL", "SPEAK", "FINAL"]
    f = final(sim)
    assert f["grounded_on"] == ["c1"] and f["act"] == "answer"
    assert f["snapshot"] == {"intent": "search_flights", "slots": {"date": "Fri", "destination": "DEL", "origin": "BLR"}}


def test_b_correction_supersedes_cancels_and_rejects_the_late_result():
    sim = scenario_b(**CK)
    calls = sim.calls()
    c1, c2 = calls["c1"], calls["c2"]
    assert c1.relevance is Relevance.SUPERSEDED and c1.outcome is Outcome.OK  # recorded as fact...
    assert "BOM" in c2.args_json and c2.relevance is Relevance.DESIRED
    assert [a.payload["call_id"] for a in sim.of(ActionKind.CANCEL)] == ["c1"]
    cancel = sim.of(ActionKind.CANCEL)[0]
    correction_seq = next(r["seq"] for r in sim.journal.of_type("in") if r["event"]["payload"].get("text") == "actually, to Mumbai")
    assert cancel.seq == correction_seq  # same step as the correction (INV-08, D3)
    assert rules(sim, "ADM.stale")[0]["call_id"] == "c1"  # ...but never used
    assert final(sim)["grounded_on"] == ["c2"]
    assert final(sim)["snapshot"]["slots"]["destination"] == "BOM"


def test_c_timeout_supersedes_cancels_and_retries_in_the_same_step():
    sim = scenario_c(**CK)
    calls = sim.calls()
    assert calls["c1"].superseded_reason == "timeout" and calls["c1"].outcome is Outcome.OK  # late OK recorded
    timeout_step = next(r for r in sim.journal.of_type("step")
                        if any(x["rule"] == "TIMER.fire" and x["purpose"] == "tool_timeout" for x in r["rules"]))
    dispatched = [x["call_id"] for x in timeout_step["rules"] if x["rule"] == "REC.dispatch"]
    assert dispatched == ["c2"]  # D2: retry at once, superseded twin still in flight
    assert [a.payload["call_id"] for a in sim.of(ActionKind.CANCEL)] == ["c1"]
    assert final(sim)["grounded_on"] == ["c2"]


def test_d_state_changing_completes_despite_cancel_no_second_create():
    sim = scenario_d(**CK)
    calls = sim.calls()
    assert list(calls) == ["c1"]  # never a second create
    assert calls["c1"].relevance is Relevance.SUPERSEDED and calls["c1"].outcome is Outcome.OK
    assert [a.payload["call_id"] for a in sim.of(ActionKind.CANCEL)] == ["c1"]
    assert rules(sim, "OP.locked")  # the corrected booking waited on the lock
    clarify = sim.of(ActionKind.CLARIFY)
    assert len(clarify) == 1 and clarify[0].payload["reason"] == "divergence"
    assert not sim.of(ActionKind.FINAL)  # never claims the corrected booking is done


def test_d2_honoured_cancel_frees_the_operation_for_the_corrected_attempt():
    sim = scenario_d(True, **CK)
    calls = sim.calls()
    assert calls["c1"].outcome is Outcome.FAILED_CLEAN
    assert json.loads(calls["c2"].args_json)["passengers"] == 2
    assert calls["c1"].idem_key != calls["c2"].idem_key
    assert final(sim)["ops"] == [["g1", "book_flight", ""]]


def test_e_rapid_corrections_in_one_open_turn_cost_one_cancel_and_one_call():
    sim = scenario_e(**CK)
    assert list(sim.calls()) == ["c1", "c2"]
    assert len(sim.of(ActionKind.CANCEL)) == 1
    assert "BOM" in sim.calls()["c2"].args_json
    assert final(sim)["grounded_on"] == ["c2"]


def test_e2_corrections_each_closing_the_turn_and_stale_planner_output():
    sim = scenario_e(True, **CK)
    calls = sim.calls()
    assert [c.relevance for c in calls.values()] == [Relevance.SUPERSEDED] * 3 + [Relevance.DESIRED]
    assert len(sim.of(ActionKind.CANCEL)) == 3
    assert any(r["slot"] == "destination" for r in rules(sim, "LWW.reject"))  # late 'GOI' proposal lost to newer 'BOM'
    assert final(sim)["grounded_on"] == ["c4"] and final(sim)["snapshot"]["slots"]["destination"] == "BOM"


def test_f_evidence_after_a_correction_conflicts_and_is_clarified_user_value_kept():
    sim = scenario_f(**CK)
    clarify = sim.of(ActionKind.CLARIFY)
    assert len(clarify) == 1 and clarify[0].payload["reason"] == "conflict"
    assert final(sim)["snapshot"]["slots"]["date"] == "Sat"
    assert '"Sat"' in sim.calls()["c1"].args_json


def test_f2_evidence_for_a_suspended_goal_is_kept_but_not_applied():
    sim = scenario_f(True, **CK)
    assert rules(sim, "EV.not_active")
    state = sim.kernel.state
    assert state.get("slots", ("g1", "date")) is None
    assert state.get("frames", "f1").claims == (("date", "Fri", 0.93),)
    assert final(sim)["snapshot"] == {"intent": "get_weather", "slots": {"city": "Pune"}}


def test_g_duplicates_are_dropped_or_ignored():
    sim = scenario_g(**CK)
    assert len(sim.journal.of_type("dup")) == 2
    assert rules(sim, "ADM.ignored")[0]["call_id"] == "c1"
    assert rules(sim, "TURN.empty")
    assert sim.kinds() == ["TOOL_CALL", "SPEAK", "FINAL"]


def test_h_result_and_correction_at_the_same_instant_either_order():
    first = scenario_h(True, **CK)  # result first: applied, then superseded without cancel (outcome known)
    assert first.calls()["c1"].outcome is Outcome.OK
    assert not first.of(ActionKind.CANCEL)
    assert not rules(first, "TIMER.fire") or all(r["timer_id"] != "to:c1" for r in rules(first, "TIMER.fire"))
    second = scenario_h(False, **CK)  # correction first: superseded + cancel, then the result is stale
    assert [a.payload["call_id"] for a in second.of(ActionKind.CANCEL)] == ["c1"]
    assert rules(second, "ADM.stale")[0]["call_id"] == "c1"
    for sim in (first, second):
        assert final(sim)["snapshot"]["slots"]["destination"] == "BOM"
