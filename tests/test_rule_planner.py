"""Deterministic rule planner (fallback after the known examples): common paraphrases of the supported tasks, with
the same safety behaviour. Each case is planned on the REAL planner view the kernel builds."""

import json
from pathlib import Path

import pytest

from agent.model import Event, Kind
from agent.planner import ScriptedPlanner
from agent.reasoner.rules import DeterministicPlanner, RulePlanner, extract
from agent.scenario import Behavior, Sim, eot
from tests.invariants import CheckedKernel

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "evaluation" / "scenarios" / "manifests" / "flights.json").read_text())
FIND = "find flights from Bangalore to Delhi on Friday"
SEARCH = {"node_id": "n1", "tool": "search_flights", "args": {p: {"$slot": p} for p in ("origin", "destination", "date")}}
FIND_PLAN = {"intent": "search_flights", "slot_writes": {"origin": "BLR", "destination": "DEL", "date": "Fri"}, "graph": [SEARCH]}


class Capture:
    def __init__(self, plans):
        self.plans, self.views = plans, []

    def respond(self, request, now):
        self.views.append(request["view"])
        base = {"req_id": request["req_id"], "based_on_seq": request["based_on_seq"]}
        prop = self.plans.get(request["view"]["turn_text"])
        if prop is None:
            return now + 0.25, Event(Kind.PROPOSAL_FAILED, now + 0.25, {**base, "reason": "capture"})
        return now + 0.25, Event(Kind.PROPOSAL, now + 0.25, {**base, **prop})


def view_for(turn, setup=False, results=None):
    cap = Capture({FIND: FIND_PLAN} if setup else {})
    flights = results or (lambda a: {"flights": [{"id": f"{a['destination']}-701", "price": 4120}, {"id": f"{a['destination']}-455", "price": 5230}]})
    sim = Sim(MANIFEST, {"search_flights": Behavior(0.5, data=flights)}, cap)
    script = ([(0.1, Event(Kind.USER_TEXT, 0.0, {"text": FIND})), (0.3, eot())] if setup else []) + \
        [(5.0, Event(Kind.USER_TEXT, 0.0, {"text": turn})), (5.2, eot())]
    sim.run(script)
    return [v for v in cap.views if v["turn_text"] == turn][-1]


@pytest.mark.parametrize("turn,writes", [
    ("I need a flight from Bengaluru to Delhi this Friday", {"origin": "BLR", "destination": "DEL", "date": "Fri"}),
    ("show me flights Bangalore to Mumbai on saturday", {"origin": "BLR", "destination": "BOM", "date": "Sat"}),
    ("any flights to Goa from Chennai on Monday?", {"origin": "MAA", "destination": "GOI", "date": "Mon"}),
    ("can you search flights from New Delhi to Kolkata for Sunday", {"origin": "DEL", "destination": "CCU", "date": "Sun"}),
])
def test_new_flight_search_paraphrases(turn, writes):
    p, why = RulePlanner().plan(view_for(turn))
    assert p is not None, why
    assert p["intent"] == "search_flights" and p["new_goal"] and p["slot_writes"] == writes
    assert [n["tool"] for n in p["graph"]] == ["search_flights"] and "clarify" not in p


def test_missing_value_is_asked_not_invented():
    p, _ = RulePlanner().plan(view_for("find me flights from Bangalore to Delhi"))
    assert "date" not in p["slot_writes"] and p["clarify"]["slots"] == ["date"]


def test_unknown_city_is_not_guessed():
    p, _ = RulePlanner().plan(view_for("flights to Atlantis on Friday"))
    assert "destination" not in p["slot_writes"] and set(p["clarify"]["slots"]) == {"origin", "destination"}


@pytest.mark.parametrize("turn,writes", [
    ("switch the destination to Goa", {"destination": "GOI"}),
    ("make it Sunday instead", {"date": "Sun"}),
    ("actually from Chennai", {"origin": "MAA"}),
    ("change it to Mumbai on Saturday", {"destination": "BOM", "date": "Sat"}),
])
def test_corrections_of_the_current_search(turn, writes):
    view = view_for(turn, setup=True)
    p, why = RulePlanner().plan(view)
    assert p is not None, why
    assert p["intent"] == "search_flights" and not p["new_goal"] and "graph" not in p
    after = {**{k: v["value"] for k, v in view["slots"].items()}, **p["slot_writes"]}  # the fast path may have written some
    assert {k: after[k] for k in writes} == writes
    assert {k: after[k] for k in ("origin", "destination", "date") if k not in writes} == \
        {k: v for k, v in {"origin": "BLR", "destination": "DEL", "date": "Fri"}.items() if k not in writes}  # untouched


def test_weather_and_parallel_requests():
    p, _ = RulePlanner().plan(view_for("what's the temperature in Pune"))
    assert p["intent"] == "get_weather" and p["slot_writes"] == {"city": "Pune"}
    p, _ = RulePlanner().plan(view_for("find flights from Bangalore to Delhi on Friday and the weather in Delhi"))
    assert {n["tool"] for n in p["graph"]} == {"search_flights", "get_weather"}
    assert p["slot_writes"]["city"] == "Delhi" and p["slot_writes"]["destination"] == "DEL"
    assert not any("$node" in b for n in p["graph"] for b in n["args"].values() if isinstance(b, dict))  # independent


def test_booking_by_position_binds_to_the_current_result_not_a_copied_literal():
    p, _ = RulePlanner().plan(view_for("please book the second one for 2 passengers", setup=True))
    book = next(n for n in p["graph"] if n["tool"] == "book_flight")
    assert book["args"]["flight_id"] == {"$node": "n1", "path": ["flights", 1, "id"]}
    assert p["slot_writes"]["passengers"] == 2 and "flight_id" not in p["slot_writes"]


def test_booking_by_id_and_count_or_ask():
    p, _ = RulePlanner().plan(view_for("reserve flight 6E-702 for three people"))
    assert p["intent"] == "book_flight" and p["slot_writes"] == {"flight_id": "6E-702", "passengers": 3}
    p, _ = RulePlanner().plan(view_for("book flight 6E-701"))
    assert p["slot_writes"] == {"flight_id": "6E-701"} and p["clarify"]["slots"] == ["passengers"]  # never assumes 1


@pytest.mark.parametrize("turn", ["which one is cheapest?", "tell me a joke"])
def test_requests_no_tool_serves_are_not_planned(turn):
    assert RulePlanner().plan(view_for(turn, setup=True))[0] is None


@pytest.mark.parametrize("turn,thing", [("order me a large pizza", "order a large pizza"), ("Book a cab from Bangalore Kapa", "book a cab"),
                                        ("Book a car from Bangalore to Hyderabad", "book a car"), ("please rent a scooter", "rent a scooter")])
def test_an_unsupported_task_gets_an_explicit_reply_and_no_tool(turn, thing):
    for setup in (False, True):
        p, why = RulePlanner().plan(view_for(turn, setup=setup))
        assert why == "unsupported task" and "graph" not in p and p["intent"] is None and p["slot_writes"] == {}
        assert p["clarify"]["slots"] == [] and f"can't {thing}" in p["clarify"]["text"]
        assert "search flights" in p["clarify"]["text"]  # what IS available comes from the tool manifest


@pytest.mark.parametrize("turn", ["book a cab to the airport", "book it for the car", "book a table for two"])
def test_the_booking_verb_alone_never_selects_the_flight_booking_tool(turn):
    p, _ = RulePlanner().plan(view_for(turn))
    assert p is None or not any(n["tool"] == "book_flight" for n in p.get("graph", []))


def test_mentioning_flights_never_selects_a_booking():
    p, _ = RulePlanner().plan(view_for("are there flights from Bangalore to Goa on Friday"))
    assert [n["tool"] for n in p["graph"]] == ["search_flights"]


def test_known_examples_still_win_and_every_step_passes_the_invariants():
    known = ScriptedPlanner({FIND: FIND_PLAN}, 0.25)
    planner = DeterministicPlanner(known, RulePlanner())
    sim = Sim(MANIFEST, {"search_flights": Behavior(2.0, data=lambda a: {"flights": [{"id": f"{a['destination']}-701"}]})},
              planner, kernel_factory=CheckedKernel)
    sim.run([(0.1, Event(Kind.USER_TEXT, 0.0, {"text": FIND})), (0.3, eot()),
             (1.0, Event(Kind.USER_TEXT, 0.0, {"text": "switch the destination to Goa"})), (1.2, eot())])
    assert [r["backend"] for r in planner.records] == ["scripted", "rules"]
    calls = list(sim.calls().values())
    assert [json.loads(c.args_json)["destination"] for c in calls] == ["DEL", "GOI"]
    assert calls[0].relevance.value == "SUPERSEDED"  # cancelled in the correction's own step, as before


def test_extract_is_schema_bound():
    schema = next(t for t in MANIFEST if t["name"] == "search_flights")["parameters"]
    assert extract("from Bangalore to Delhi on Blursday", schema) == {"origin": "BLR", "destination": "DEL"}
