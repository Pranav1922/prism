"""Adversarial sequences. Expected behaviour comes from the locked architecture (D1–D9, F2–F7).
Every step also runs through CheckedKernel."""

import json

from agent.kernel import Config, Kernel
from agent.model import ActionKind, Event, Kind, OpState, Outcome, Relevance, Request
from agent.planner import ScriptedPlanner
from agent.scenario import (
    FIND,
    MANIFEST,
    PLANS,
    Behavior,
    Sim,
    eot,
    flights,
    interrupt,
    result,
    say,
    to_mumbai,
)
from tests.invariants import CheckedKernel

BOOK = "book flight 6E-701"


def sim(tools=None, plans=None, manifest=None, **kw):
    return Sim(manifest or MANIFEST, tools or {"search_flights": Behavior(2.0, data=flights)},
               ScriptedPlanner(plans or PLANS), kernel_factory=CheckedKernel, **kw)


def rules(s, name):
    return [r for rec in s.journal.of_type("step") for r in rec["rules"] if r["rule"] == name]


def finals(s):
    return [a.payload for a in s.of(ActionKind.FINAL)]


START = [(0.1, say(FIND)), (0.5, eot())]  # proposal at 0.8 -> c1 dispatched at 0.8, result at 2.8


def test_interrupt_1ms_before_completion():
    s = sim().run(START + [(2.799, to_mumbai()), (3.0, eot())])
    c1 = s.calls()["c1"]
    assert c1.relevance is Relevance.SUPERSEDED and c1.outcome is Outcome.OK
    assert [a.payload["call_id"] for a in s.of(ActionKind.CANCEL)] == ["c1"]
    assert finals(s)[-1]["grounded_on"] == ["c2"]


def test_interrupt_immediately_after_completion_no_cancel_for_a_known_outcome():
    s = sim().run(START + [(2.801, to_mumbai()), (3.0, eot())])
    assert s.calls()["c1"].superseded_reason == "not_desired"
    assert not s.of(ActionKind.CANCEL)
    assert [f["grounded_on"] for f in finals(s)] == [["c1"], ["c2"]]  # DEL answered, then BOM answered


def test_two_interruptions_before_any_result():
    plans = {**PLANS, "no, Goa": {"intent": "search_flights", "slot_writes": {"destination": "GOI"}}}
    s = sim(plans=plans).run(START + [(1.0, to_mumbai()), (1.1, eot()),
                                      (1.2, say("no, Goa", "CORRECTION", {"destination": "GOI"})), (1.3, eot())])
    calls = s.calls()
    assert [c.relevance for c in calls.values()] == [Relevance.SUPERSEDED, Relevance.SUPERSEDED, Relevance.DESIRED]
    assert sorted(a.payload["call_id"] for a in s.of(ActionKind.CANCEL)) == ["c1", "c2"]
    assert len(rules(s, "ADM.stale")) == 2
    assert finals(s)[-1]["grounded_on"] == ["c3"]


def test_revert_to_an_earlier_value_reruns_instead_of_reusing_d1():
    plans = {**PLANS, "no, Delhi after all": {"intent": "search_flights", "slot_writes": {"destination": "DEL"}}}
    tools = {"search_flights": Behavior(0.3, data=flights)}
    s = sim(tools, plans).run(START + [(2.0, to_mumbai()), (2.1, eot()),
                                       (3.0, say("no, Delhi after all", "CORRECTION", {"destination": "DEL"})),
                                       (3.1, eot())])
    calls = s.calls()
    assert calls["c1"].key == calls["c3"].key  # same work...
    assert calls["c1"].relevance is Relevance.SUPERSEDED  # ...but c1 is never used again
    assert finals(s)[-1]["grounded_on"] == ["c3"]


def test_new_call_while_superseded_twin_is_pending_dispatches_immediately_d2():
    plans = {**PLANS, "no, Delhi": {"intent": "search_flights", "slot_writes": {"destination": "DEL"}}}
    s = sim(plans=plans).run(START + [(1.0, to_mumbai()), (1.1, eot()),
                                      (1.2, say("no, Delhi", "CORRECTION", {"destination": "DEL"})), (1.3, eot())])
    calls = s.calls()
    assert calls["c1"].key == calls["c3"].key and calls["c1"].outcome is Outcome.OK  # c1 still pending at 1.3
    dispatch_step = next(r for r in s.journal.of_type("step")
                         if any(x["rule"] == "REC.dispatch" and x["call_id"] == "c3" for x in r["rules"]))
    assert dispatch_step["seq"] < next(r["seq"] for r in s.journal.of_type("in")
                                       if r["event"]["payload"].get("call_id") == "c1")
    assert finals(s)[-1]["grounded_on"] == ["c3"]


def test_timeout_then_late_result_is_recorded_but_unused():
    manifest = [dict(MANIFEST[0], timeout_s=1.0)] + MANIFEST[1:]
    s = sim({"search_flights": [Behavior(None), Behavior(0.4, data=flights)]}, manifest=manifest)
    s.run(START + [(5.0, result("c1", data={"flights": []}))])
    c1 = s.calls()["c1"]
    assert c1.superseded_reason == "timeout" and c1.outcome is Outcome.OK  # UNKNOWN -> OK recorded
    assert rules(s, "ADM.stale")[0]["call_id"] == "c1"
    assert finals(s)[-1]["grounded_on"] == ["c2"]


def test_read_only_retry_budget_is_bounded():
    manifest = [dict(MANIFEST[0], timeout_s=0.5)] + MANIFEST[1:]
    s = sim({"search_flights": Behavior(None)}, manifest=manifest).run(START)
    assert len(s.calls()) == 3  # 1 + 2 retries
    assert any(a.payload["reason"] == "exhausted" for a in s.of(ActionKind.CLARIFY))
    assert not finals(s)


def test_state_changing_timeout_then_late_ok_commits_and_never_recreates():
    tools = {"book_flight": Behavior(None)}
    manifest = [MANIFEST[0], dict(MANIFEST[1], timeout_s=1.0), MANIFEST[2]]
    s = sim(tools, manifest=manifest).run([(0.1, say(BOOK)), (0.3, eot()),
                                           (4.0, result("c1", data={"booking_id": "B1"}))])
    calls = s.calls()
    assert list(calls) == ["c1"] and calls["c1"].outcome is Outcome.OK
    assert any(a.payload["reason"] == "unknown_outcome" for a in s.of(ActionKind.CLARIFY))
    assert finals(s)[-1]["ops"] == [["g1", "book_flight", ""]]


def test_state_changing_explicit_not_executed_retries_once_with_same_idempotency_key():
    tools = {"book_flight": Behavior(0.2, outcome="error", executed=False)}
    s = sim(tools).run([(0.1, say(BOOK)), (0.3, eot())])
    calls = list(s.calls().values())
    assert len(calls) == 2 and calls[0].idem_key == calls[1].idem_key
    assert all(c.outcome is Outcome.FAILED_CLEAN for c in calls)
    assert any(a.payload["reason"] == "exhausted" for a in s.of(ActionKind.CLARIFY))


def test_state_changing_error_with_unknown_execution_locks_and_never_retries():
    tools = {"book_flight": Behavior(0.2, outcome="error", executed=None)}
    s = sim(tools).run([(0.1, say(BOOK)), (0.3, eot()), (1.0, say("please try again")), (1.2, eot())])
    assert list(s.calls()) == ["c1"] and s.calls()["c1"].outcome is Outcome.UNKNOWN


def test_failed_clean_then_ok_anomaly_is_recorded_as_committed():
    tools = {"book_flight": [Behavior(0.2, outcome="error", executed=False), Behavior(None)]}
    s = sim(tools).run([(0.1, say(BOOK)), (0.3, eot()), (3.0, result("c1", data={"booking_id": "B1"}))])
    assert rules(s, "ADM.anomaly")[0]["call_id"] == "c1"
    from agent.kernel import op_state
    assert op_state(s.kernel.state, ("g1", "book_flight", "")) is OpState.COMMITTED


def test_duplicate_state_changing_request_is_not_redispatched():
    plans = {**PLANS, "book it again": PLANS[BOOK]}  # planner re-proposes the identical booking
    tools = {"book_flight": Behavior(0.5, data={"booking_id": "B1"}, duplicate=True)}
    s = sim(tools, plans).run([(0.1, say(BOOK)), (0.3, eot()), (2.0, say("book it again")), (2.2, eot())])
    assert list(s.calls()) == ["c1"]
    assert rules(s, "ADM.ignored")  # the duplicated result changed nothing


def test_malformed_tool_arguments_never_dispatch_and_ask():
    plans = {BOOK: {"intent": "book_flight", "slot_writes": {"flight_id": "6E-701", "passengers": "two"},
                    "graph": PLANS[BOOK]["graph"]}}
    s = sim({}, plans).run([(0.1, say(BOOK)), (0.3, eot())])
    assert not s.calls()
    assert [a.payload["reason"] for a in s.of(ActionKind.CLARIFY)] == ["invalid_args"]


def test_unsolicited_proposal_is_rejected():
    fake = Event(Kind.PROPOSAL, 0.4, {"req_id": "r99", "based_on_seq": 0, **PLANS[BOOK]})
    s = sim({}).run([(0.4, fake)])
    assert rules(s, "ADM.unknown_request") and not s.calls() and s.kernel.state.get("meta", "active_goal") is None


def test_state_changing_call_without_user_provenance_is_blocked():
    k = Kernel()
    k.step(Event(Kind.MANIFEST, 0.0, {"tools": MANIFEST}, "m", 1))
    k.apply([("reqs", "r1", Request("r1", "understand", 0, None))])  # a request with no user content behind it
    res = k.step(Event(Kind.PROPOSAL, 0.1, {"req_id": "r1", "based_on_seq": 0, **PLANS[BOOK]}, "p", 2))
    assert not [a for a in res.actions if a.kind is ActionKind.TOOL_CALL]
    assert {"rule": "BARRIER.block", "op": ["g1", "book_flight", ""], "reason": "provenance"} in res.rules


def test_non_cancellable_state_changing_call_is_superseded_without_cancel():
    manifest = [MANIFEST[0], dict(MANIFEST[1], cancellable=False), MANIFEST[2]]
    s = sim({"book_flight": Behavior(1.0, data={"booking_id": "B1"})}, manifest=manifest)
    s.run([(0.1, say(BOOK)), (0.3, eot()), (0.8, say("wait, two of us", "CORRECTION", {"passengers": 2})), (1.0, eot())])
    assert s.calls()["c1"].relevance is Relevance.SUPERSEDED
    assert not s.of(ActionKind.CANCEL)
    assert list(s.calls()) == ["c1"]


def test_backchannel_and_status_question_supersede_nothing():
    s = sim().run(START + [(1.0, say("uh-huh")), (1.1, eot()), (1.5, say("how long will this take?", "STATUS_QUERY")),
                           (1.6, eot())])
    assert not s.of(ActionKind.CANCEL) and list(s.calls()) == ["c1"]
    assert finals(s)[-1]["grounded_on"] == ["c1"]


def test_unattributed_correction_supersedes_active_read_only_calls():
    plans = {**PLANS, "no no, wait": {"intent": "search_flights"}}
    s = sim(plans=plans).run(START + [(1.0, say("no no, wait", "CORRECTION")), (1.2, eot())])
    assert s.calls()["c1"].superseded_reason == "unattributed_marker"
    assert [a.payload["call_id"] for a in s.of(ActionKind.CANCEL)] == ["c1"]
    assert s.calls()["c2"].key == s.calls()["c1"].key  # F5 literal: same key re-dispatched at turn close


def test_content_free_interrupt_hold_is_cleared_by_the_silence_timer_d4():
    s = sim().run(START + [(1.0, interrupt())])
    assert any(r["by"] == "silence_timer" for r in rules(s, "HOLD.clear"))
    assert not s.kernel.state.get("meta", "hold")
    assert finals(s)  # FINAL was not blocked forever


def test_deadline_governor_emits_final_before_the_cap():
    s = sim({"search_flights": Behavior(None)}, config=Config(deadline_s=3.0, tool_timeout_s=50.0)).run(START)
    fin = s.of(ActionKind.FINAL)
    assert len(fin) == 1 and fin[0].rule == "DEADLINE.final" and fin[0].payload["act"] == "narration"
    deadline_seq = fin[0].seq
    t = next(r["event"]["t"] for r in s.journal.of_type("in") if r["seq"] == deadline_seq)
    assert t == 3.0
    assert s.calls()["c1"].superseded_reason == "deadline"


def test_unknown_call_id_result_changes_nothing():
    s = sim().run(START + [(1.0, result("c42"))])
    assert rules(s, "ADM.unknown_call")  # CheckedKernel asserts res.changes == [] (INV-10)


def test_older_evidence_never_overrides_a_newer_user_value():
    plans = {"trip": {"intent": "search_flights", "slot_writes": {"origin": "BLR", "destination": "DEL"},
                      "graph": PLANS[FIND]["graph"]}}
    from agent.planner import ScriptedPerception
    from agent.scenario import image
    s = Sim(MANIFEST, {"search_flights": Behavior(0.5, data=flights)}, ScriptedPlanner(plans),
            ScriptedPerception({"img": {"date": ["Fri", 0.99], "origin": ["BLR", 0.99]}}, latency=2.0),
            kernel_factory=CheckedKernel)
    s.run([(0.1, say("trip")), (0.2, Event(Kind.MEDIA, 0.0, {"kind": "image", "ref": "img"}, "f9")), (0.4, eot()),
           (1.0, say("on Sunday", "ANSWER", {"date": "Sun"})), (1.2, eot())])
    assert s.kernel.state.get("slots", ("g1", "date")).value == "Sun"
    assert s.kernel.state.get("slots", ("g1", "origin")).source == "PLANNER"  # agreeing evidence: re-assert only
    assert json.loads(s.calls()["c1"].args_json)["date"] == "Sun"
    assert image  # helper exists for other tests
