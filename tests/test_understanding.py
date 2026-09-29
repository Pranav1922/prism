"""Phase 4: deterministic fast understanding. Corpus gates, safety boundary, and kernel-level adversarial
sequences with the REAL recogniser (no annotations), every step through CheckedKernel."""

import dataclasses
import json
from pathlib import Path

import pytest

from agent.model import ActionKind, Event, Kind, Relevance, TurnClass
from agent.planner import ScriptedPerception, ScriptedPlanner
from agent.scenario import Behavior, Sim, eot, flights
from agent.understand import SlotInfo, UnderstandContext, Understanding
from agent.understand_rules import MAX_TOKENS, recognize
from tests.invariants import CheckedKernel
from tests.understanding_corpus import score

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "evaluation" / "scenarios" / "manifests" / "flights.json").read_text()) + [
    {"name": "create_ticket", "description": "Create a support ticket", "effect": "state_changing",
     "parameters": {"type": "object", "properties": {
         "issue": {"type": "string", "minLength": 1},
         "date": {"type": "string", "enum": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]}},
         "required": ["issue", "date"], "additionalProperties": False}}]
FIND = "find flights from Bangalore to Delhi on Friday"
SEARCH = [{"node_id": "n1", "tool": "search_flights",
           "args": {"origin": {"$slot": "origin"}, "destination": {"$slot": "destination"}, "date": {"$slot": "date"}}}]
PLANS = {
    FIND: {"intent": "search_flights", "slot_writes": {"origin": "BLR", "destination": "DEL", "date": "Fri"}, "graph": SEARCH},
    "no wait to Goa": {"intent": "search_flights", "slot_writes": {"destination": "GOI"}},
    "I actually want no wait to Goa": {"intent": "search_flights", "slot_writes": {"destination": "GOI"}},
    "actually, to Mumbai": {"intent": "search_flights", "slot_writes": {"destination": "BOM"}},
    "no wait, Goa": {"intent": "search_flights"},  # the planner itself cannot tell what changed
    "ticket for my cracked screen on Monday": {
        "intent": "create_ticket", "new_goal": True, "slot_writes": {"issue": "cracked screen", "date": "Mon"},
        "graph": [{"node_id": "t1", "tool": "create_ticket", "args": {"issue": {"$slot": "issue"}, "date": {"$slot": "date"}}}]},
    "change the date to Tuesday": {"intent": "create_ticket", "slot_writes": {"date": "Tue"}},
}


def say(text):
    return Event(Kind.USER_TEXT, 0.0, {"text": text})


def run(script, tools=None, plans=None, perception=None):
    sim = Sim(MANIFEST, tools or {"search_flights": Behavior(2.0, data=flights)}, ScriptedPlanner(plans or PLANS, 0.25),
              perception or ScriptedPerception(), kernel_factory=CheckedKernel)
    return sim.run(script)


def rules(sim, name):
    return [r for rec in sim.journal.of_type("step") for r in rec["rules"] if r["rule"] == name]


def speech(sim):
    return [a.payload for a in sim.actions if a.kind is ActionKind.SPEAK]


BASE = [(0.1, say(FIND)), (0.5, eot())]  # c1 search(BLR, DEL, Fri) dispatched at 0.75, result at 2.75


# ---------------------------------------------------------------- corpus gates (internal measurement)


@pytest.mark.parametrize("split", ["items", "holdout_items"])
def test_corpus_has_no_unsafe_interpretation_and_no_false_correction(split):
    res = score(split=split)
    assert res["unsafe_interpretation_rate"] == 0.0, res["errors"]
    assert res["false_correction_rate"] == 0.0, res["errors"]
    assert res["classification_accuracy"] >= 0.95 and res["slot_extraction_accuracy"] >= 0.9, res["errors"]


def test_recogniser_latency_is_bounded():
    lat = score(repeat=20)["latency_ms"]
    assert lat["p99"] < 2.0, lat  # the budget for the whole kernel step is 5 ms


# ---------------------------------------------------------------- safety boundary


CTX = UnderstandContext("search_flights", (
    SlotInfo("destination", "DEL", MANIFEST[0]["parameters"]["properties"]["destination"], (("DEL", 4, "PLANNER"),)),
    SlotInfo("date", "Fri", MANIFEST[0]["parameters"]["properties"]["date"], (("Fri", 4, "PLANNER"),))),
    (), ((4, FIND),))


def test_recogniser_is_pure_and_deterministic():
    snapshot = repr(CTX)
    outs = {repr(recognize("no wait, Sunday to Mumbai", {}, CTX)) for _ in range(5)}
    assert len(outs) == 1 and repr(CTX) == snapshot


def test_recogniser_can_only_express_an_interpretation():
    u = recognize("actually, make it Saturday", {}, CTX)
    assert set(f.name for f in dataclasses.fields(u)) == {"cls", "writes", "confirm", "attributed", "cues"}
    assert isinstance(u, Understanding) and u.writes == {"date": "Sat"}


def test_recogniser_only_writes_slots_of_the_context_and_schema_valid_values():
    u = recognize("change the passengers to 3 and the city to Pune", {}, CTX)
    assert u.writes == {"destination": None}  # "passengers" is not in this goal; "to Pune" is only retracted
    assert all(v is None or v in {"Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"}
               for v in recognize("no, Saturday or maybe Sunday", {}, CTX).writes.values())


def test_input_is_bounded():
    u = recognize("wait " * 5000 + "Saturday", {}, CTX)
    assert u.cls is TurnClass.CORRECTION and u.writes == {}  # tokens beyond MAX_TOKENS are ignored
    assert MAX_TOKENS == 64


def test_no_goal_means_no_slot_writes_and_no_goal_creation():
    sim = run([(0.1, say("actually, to Mumbai on Saturday")), (0.3, eot())])
    assert rules(sim, "T0.classify")[0]["writes"] == [] and not sim.calls()


# ---------------------------------------------------------------- kernel-level adversarial sequences


def test_attributed_correction_cancels_only_in_the_same_step_and_retracts():
    sim = run(BASE + [(1.0, say("actually, to Mumbai")), (1.2, eot())])
    c1 = sim.calls()["c1"]
    assert c1.relevance is Relevance.SUPERSEDED and c1.superseded_reason == "not_desired"
    fix = next(r["seq"] for r in sim.journal.of_type("in") if r["event"]["payload"].get("text") == "actually, to Mumbai")
    assert [a.seq for a in sim.of(ActionKind.CANCEL)] == [fix]
    assert json.loads(sim.calls()["c2"].args_json)["destination"] == "BOM"  # canonical value from the planner


def test_correction_word_alone_is_unattributed_f5():
    sim = run(BASE + [(1.0, say("no wait")), (1.2, eot())], plans={**PLANS, "no wait": {"intent": "search_flights"}})
    assert sim.calls()["c1"].superseded_reason == "unattributed_marker"
    assert rules(sim, "T0.classify")[1]["attributed"] == []


def test_unattributable_bare_value_does_not_invent_a_slot():
    # no earlier utterance names a place (the goal comes from a planner-only turn): "Goa" cannot be attributed
    plans = {**PLANS, "find me something cheap": PLANS[FIND]}
    sim = run([(0.1, say("find me something cheap")), (0.5, eot()), (1.0, say("no wait, Goa")), (1.2, eot())], plans=plans)
    t0 = rules(sim, "T0.classify")[-1]
    assert t0["cls"] == "CORRECTION" and t0["writes"] == [] and t0["attributed"] == []
    assert sim.calls()["c1"].superseded_reason == "unattributed_marker"  # F5: stop the read, invent nothing


def test_value_fitting_two_slots_abstains():
    ctx = UnderstandContext("search_flights", (
        SlotInfo("origin", "BLR", MANIFEST[0]["parameters"]["properties"]["origin"], (("BLR", 4, "PLANNER"),)),
        SlotInfo("destination", "DEL", MANIFEST[0]["parameters"]["properties"]["destination"], (("DEL", 4, "PLANNER"),))),
        (), ())
    u = recognize("no wait, BOM", {}, ctx)
    assert u.cls is TurnClass.CORRECTION and u.writes == {} and u.attributed == ()


def test_repeating_the_current_value_changes_nothing():
    sim = run(BASE + [(1.0, say("no, to Delhi")), (1.2, eot())], plans={**PLANS, "no, to Delhi": {"intent": "search_flights"}})
    assert not sim.of(ActionKind.CANCEL) and list(sim.calls()) == ["c1"]


def test_partial_transcript_waits_until_a_repair_is_actually_signalled():
    sim = run(BASE + [(1.0, say("I actually want")), (1.1, say("no wait")), (1.2, say("to Goa")), (1.4, eot())])
    cls = [r["cls"] for r in rules(sim, "T0.classify")[1:]]
    assert cls == ["REQUEST", "CORRECTION", "CORRECTION"]
    cancel = sim.of(ActionKind.CANCEL)[0]
    steps = {r["seq"]: r["event"]["payload"].get("text") for r in sim.journal.of_type("in")}
    assert steps[cancel.seq] == "no wait"  # not on "I actually want"
    assert "GOI" in sim.calls()[list(sim.calls())[-1]].args_json


def test_two_slot_changes_in_one_utterance():
    plans = {**PLANS, "actually Saturday to Mumbai": {"intent": "search_flights",
                                                     "slot_writes": {"destination": "BOM", "date": "Sat"}}}
    sim = run(BASE + [(1.0, say("actually Saturday to Mumbai")), (1.2, eot())], plans=plans)
    assert rules(sim, "T0.classify")[1]["writes"] == ["date", "destination"]
    final = sim.of(ActionKind.FINAL)[-1].payload["snapshot"]["slots"]
    assert final["date"] == "Sat" and final["destination"] == "BOM"


def test_correction_immediately_followed_by_end_of_turn():
    sim = run(BASE + [(1.0, say("actually, to Mumbai")), (1.0, eot())])
    assert sim.calls()["c1"].relevance is Relevance.SUPERSEDED
    assert sim.of(ActionKind.FINAL)[-1].payload["snapshot"]["slots"]["destination"] == "BOM"


@pytest.mark.parametrize("t", [2.749, 2.751])
def test_correction_just_before_or_after_the_old_result(t):
    sim = run(BASE + [(t, say("actually, to Mumbai")), (t + 0.1, eot())])
    assert bool(sim.of(ActionKind.CANCEL)) is (t < 2.75)
    assert sim.of(ActionKind.FINAL)[-1].payload["grounded_on"] == ["c2"]


def test_repeated_corrections_keep_the_last_value():
    sim = run(BASE + [(1.0, say("actually, to Mumbai")), (1.1, eot()), (1.2, say("no wait to Goa")), (1.3, eot())])
    assert sim.of(ActionKind.FINAL)[-1].payload["snapshot"]["slots"]["destination"] == "GOI"
    assert [c.superseded_reason for c in sim.calls().values()][:2] == ["not_desired", "not_desired"]


def test_status_question_answered_truthfully_while_running():
    sim = run(BASE + [(1.0, say("what's happening?")), (1.1, eot())])
    status = [s for s in speech(sim) if s["act"] == "narration"]
    assert status and status[0]["text"].startswith("Still working on it: search_flights") and "No result yet" in status[0]["text"]
    assert not sim.of(ActionKind.CANCEL)


def test_status_question_after_completion_and_with_nothing_running():
    done = run(BASE + [(4.0, say("is it done yet?")), (4.1, eot())])
    assert [s["text"] for s in speech(done) if s["act"] == "narration"] == ["I've already given you the search_flights result."]
    idle = run([(0.1, say("how long will this take?")), (0.2, eot())])
    assert [s["text"] for s in speech(idle) if s["act"] == "narration"] == ["Nothing is running right now."]


def test_backchannels_during_a_tool_do_nothing():
    sim = run(BASE + [(1.0, say("okay")), (1.1, eot()), (1.3, say("got it")), (1.4, eot())])
    assert not sim.of(ActionKind.CANCEL) and len(rules(sim, "PLANNER.request")) == 1
    assert [s["act"] for s in speech(sim)] == ["ack"]  # only the dispatch acknowledgement: no fillers


def test_clarification_answer_resolves_the_open_question():
    plans = {"find flights from Bangalore to Delhi on the date in this photo": {
        "intent": "search_flights", "slot_writes": {"origin": "BLR", "destination": "DEL"}, "graph": SEARCH},
        "on Sunday": {"intent": "search_flights", "slot_writes": {"date": "Sun"}},
        "the one on Saturday": {"intent": "search_flights", "slot_writes": {"date": "Sat"}}}
    sim = run([(0.1, say("find flights from Bangalore to Delhi on the date in this photo")),
               (0.2, Event(Kind.MEDIA, 0.0, {"kind": "image", "ref": "img"}, "f1")), (0.4, eot()),
               (1.0, say("on Sunday")), (1.2, eot()), (3.0, say("the one on Saturday")), (3.2, eot())],
              tools={"search_flights": Behavior(0.3, data=flights)}, plans=plans,
              perception=ScriptedPerception({"img": {"date": ["Fri", 0.95]}}, latency=1.5))
    assert any(a.payload["reason"] == "conflict" for a in sim.of(ActionKind.CLARIFY))
    assert rules(sim, "T0.classify")[-1]["cls"] == "ANSWER" and rules(sim, "PENDING.resolved")
    assert sim.of(ActionKind.FINAL)[-1].payload["snapshot"]["slots"]["date"] == "Sat"


def test_goal_isolation_a_correction_only_touches_the_active_goal():
    sim = run(BASE + [(3.0, say("ticket for my cracked screen on Monday")), (3.2, eot()),
                      (5.0, say("change the date to Tuesday")), (5.2, eot())],
              tools={"search_flights": Behavior(0.3, data=flights), "create_ticket": Behavior(None)})
    state = sim.kernel.state
    assert state.get("slots", ("g1", "date")).value == "Fri"  # the flight goal is untouched
    assert state.get("slots", ("g2", "date")).value == "Tue"
    assert state.get("goals", "g1").status.value == "SUSPENDED"


def test_retraction_the_planner_cannot_fill_is_reverted_d12():
    sim = run(BASE + [(1.0, say("actually, to Mumbai")), (1.2, eot())],
              plans={**PLANS, "actually, to Mumbai": {"intent": "search_flights"}})
    assert rules(sim, "T0.retraction_reverted")[0] == {"rule": "T0.retraction_reverted", "slot": "destination", "value": "DEL"}
    assert sim.of(ActionKind.FINAL)[-1].payload["snapshot"]["slots"]["destination"] == "DEL"


def test_goal_switch_withholds_the_abandoned_work_until_the_planner_answers_d11():
    plans = {**PLANS, "never mind": {"intent": "get_weather", "slot_writes": {"city": "Pune"},
                                    "graph": [{"node_id": "w1", "tool": "get_weather", "args": {"city": {"$slot": "city"}}}]}}
    sim = run(BASE + [(1.0, say("never mind")), (1.2, eot())], plans=plans,
              tools={"search_flights": Behavior(2.0, data=flights), "get_weather": Behavior(0.3, data={"t": 31})})
    tools = [c.tool for c in sim.calls().values()]
    assert tools == ["search_flights", "get_weather"]  # the abandoned search is not re-dispatched
    assert rules(sim, "SWITCH.pending") and rules(sim, "SWITCH.answered")


def test_fast_path_never_dispatches_a_state_changing_call_itself():
    tools = {"create_ticket": Behavior(None)}
    plans = {"ticket for my cracked screen on Monday": PLANS["ticket for my cracked screen on Monday"],
             "no, make it Wednesday": {"intent": "create_ticket"}}
    sim = run([(0.1, say("ticket for my cracked screen on Monday")), (0.3, eot()),
               (1.0, say("no, make it Wednesday"))], tools=tools, plans=plans)  # turn never closed
    calls = list(sim.calls().values())
    assert len(calls) == 1 and "Mon" in calls[0].args_json  # nothing new while the user holds the floor


def test_recogniser_does_not_depend_on_scenario_fixtures():
    import agent.understand_rules as mod
    src = Path(mod.__file__).read_text()
    assert "scripted" not in src and "fixtures" not in src and "scenario" not in src.lower()
    scen = [json.loads(p.read_text()) for p in (ROOT / "evaluation" / "scenarios").rglob("*.json") if "manifests" not in str(p)]
    texts = {e["data"]["text"] for s in scen for e in s.get("inputs", []) if isinstance(e.get("data"), dict) and "text" in e["data"]}
    assert texts and not any(t in src for t in texts if len(t) > 12)  # no scenario utterance is hard-coded
