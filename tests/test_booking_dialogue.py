"""Booking follow-ups: "Book flight from Bangalore to Delhi" -> the agent asks for the flight and passengers -> the
user's (possibly noisy) answer must make progress on the SAME booking, never invent a value, never read a flight
number's digits as a passenger count, and never loop on the identical question.

Runs the production pipeline: real fast understanding, the deterministic planner (shipped known examples, then rules),
the kernel under the invariant checker; plus one run through the real agent process, as the UI drives it."""

import json
import time
from pathlib import Path

import pytest

from agent.lexicon import flight_ids, people_count
from agent.model import ActionKind, Event, Kind
from agent.planner import ScriptedPlanner
from agent.reasoner.rules import DeterministicPlanner, RulePlanner
from agent.scenario import Behavior, Sim, eot
from tests.invariants import CheckedKernel

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "evaluation" / "scenarios" / "manifests" / "flights.json").read_text())
FIXTURES = json.loads((ROOT / "agent" / "fixtures" / "scripted.json").read_text())
ASK = "Book flight from Bangalore to Delhi"


def converse(*replies):
    planner = DeterministicPlanner(ScriptedPlanner(FIXTURES["planner"], 0.25), RulePlanner(0.25))
    sim = Sim(MANIFEST, {"book_flight": Behavior(0.5, data={"booking_id": "B1"})}, planner, kernel_factory=CheckedKernel)
    script, t = [(0.1, Event(Kind.USER_TEXT, 0.0, {"text": ASK})), (0.3, eot())], 1.0
    for r in replies:
        script += [(t, Event(Kind.USER_TEXT, 0.0, {"text": r})), (t + 0.2, eot())]
        t += 1.0
    return sim.run(script)


def asked(sim):
    return [(a.payload["slots"], a.payload["text"]) for a in sim.of(ActionKind.CLARIFY)]


def bookings(sim):
    return [json.loads(c.args_json) for c in sim.calls().values() if c.tool == "book_flight"]


def slots(sim):
    return {name: r.value for (_, name), r in sim.kernel.state.items("slots")}


def goals(sim):
    return [g.intent for _, g in sim.kernel.state.items("goals")]


def test_first_question_names_both_missing_values():
    sim = converse()
    assert asked(sim)[0][0] == ["flight_id", "passengers"] and "IndiGo 6E 431" in asked(sim)[0][1]
    assert not bookings(sim)


@pytest.mark.parametrize("reply,flight", [("Indigo SE 2020", "6E-2020"), ("AI 2020", "AI-2020"), ("6E 431", "6E-431"),
                                          ("it's IndiGo 6E 431", "6E-431"), ("6E-431", "6E-431")])
def test_flight_id_supplied_asks_only_for_passengers_and_never_reads_the_number_as_a_count(reply, flight):
    sim = converse(reply)
    assert slots(sim).get("flight_id") == flight
    assert slots(sim).get("passengers") is None  # 2020 / 431 are part of the flight number, not a head count
    assert asked(sim)[-1][0] == ["passengers"] and flight in asked(sim)[-1][1]  # says what it got, asks the rest
    assert not bookings(sim) and goals(sim) == ["book_flight"]


@pytest.mark.parametrize("reply,n", [("2 passengers", 2), ("for two people", 2), ("3 travellers", 3), ("just the two of us", 2)])
def test_passengers_supplied_asks_only_for_the_flight(reply, n):
    sim = converse(reply)
    assert slots(sim).get("passengers") == n and slots(sim).get("flight_id") is None
    assert asked(sim)[-1][0] == ["flight_id"] and not bookings(sim) and goals(sim) == ["book_flight"]


@pytest.mark.parametrize("reply", ["AI 2020 for two people", "IndiGo 6E 431, 2 passengers", "6E 431 for 3 travellers"])
def test_both_supplied_books_exactly_once(reply):
    sim = converse(reply)
    assert len(bookings(sim)) == 1 and sim.of(ActionKind.FINAL)[-1].payload["act"] == "answer"
    b = bookings(sim)[0]
    assert b["passengers"] in (2, 3) and b["flight_id"] in ("AI-2020", "6E-431")


def test_one_then_the_other_completes_the_same_booking():
    sim = converse("Indigo SE 2020", "2 passengers")
    assert [a[0] for a in asked(sim)] == [["flight_id", "passengers"], ["passengers"]]
    assert bookings(sim) == [{"flight_id": "6E-2020", "passengers": 2}] and goals(sim) == ["book_flight"]


def test_a_bare_number_is_not_guessed_while_both_values_are_open():
    sim = converse("2020")
    assert slots(sim).get("passengers") is None and slots(sim).get("flight_id") is None and not bookings(sim)


def test_a_bare_number_counts_once_only_the_passengers_are_asked():
    sim = converse("6E 431", "2")
    assert bookings(sim) == [{"flight_id": "6E-431", "passengers": 2}]


@pytest.mark.parametrize("reply", ["uh the the flight", "tell me a joke", "mmm yeah the one with the thing"])
def test_noisy_or_irrelevant_reply_keeps_the_booking_and_says_what_is_missing(reply):
    sim = converse(reply)
    last = asked(sim)[-1]
    assert last[0] == ["flight_id", "passengers"] and last[1].startswith("Sorry, I didn't catch") and reply[:20] in last[1]
    assert goals(sim) == ["book_flight"] and not bookings(sim) and slots(sim).get("passengers") is None


def test_repeated_noise_does_not_loop_on_the_identical_question():
    sim = converse("uh the the flight", "hmm the the", "banana")
    texts = [t for _, t in asked(sim)]
    assert all(a != b for a, b in zip(texts, texts[1:], strict=False))  # never the same words twice in a row
    assert any(t.startswith("I still need") and "type it" in t for t in texts)
    open_questions = [p for _, p in sim.kernel.state.items("pending") if not p.resolved]
    assert len(open_questions) == 1  # a new question replaces the ones it covers; they do not pile up
    assert not bookings(sim) and goals(sim) == ["book_flight"]


def test_an_explicit_switch_still_switches():
    sim = converse("never mind, what's the weather in Pune?")
    assert goals(sim)[-1] == "get_weather" and not bookings(sim)


def test_recognisers():
    toks = lambda s: s.lower().replace(",", " ").split()  # noqa: E731
    assert [v for v, _ in flight_ids(toks("indigo se 2020"))] == ["6E-2020"]
    assert [v for v, _ in flight_ids(toks("air india 101 please"))] == ["AI-101"]
    assert flight_ids(toks("flight 2020")) == [] and flight_ids(toks("se 2020")) == []  # no airline, no guess
    fid = flight_ids(toks("ai 2020 for two people"))
    assert people_count(toks("ai 2020 for two people"), {i for _, idx in fid for i in idx}) == (2, 3)
    assert people_count(toks("book the second one")) is None and people_count(toks("indigo 2020")) is None


def test_the_live_agent_completes_the_booking_conversation():
    from frontend import server
    from frontend.live import LiveSession
    events: list = []
    s = LiveSession(events.append, server.agent_cmd(), server.MANIFEST, server.PRESETS["fast"]["world"])
    s.start()
    try:
        for text, pause in ((ASK, 1.2), ("Indigo SE 2020", 1.2), ("for two people", 3.0)):
            s.inject("user.text", {"text": text})
            s.inject("user.turn_end")
            time.sleep(pause)
    finally:
        s.stop()
        s.join(10)
    out = [(e["msg"]["type"], e["msg"]["data"]) for e in events if e["type"] == "wire" and e["dir"] == "out"
           and e["msg"] and e["msg"]["type"] in ("clarify", "tool.call", "response.final")]
    kinds = [k for k, _ in out]
    assert kinds[:2] == ["clarify", "clarify"] and "tool.call" in kinds and kinds[-1] == "response.final"
    assert out[1][1]["slots"] == ["passengers"]
    call = next(d for k, d in out if k == "tool.call")
    assert call["tool"] == "book_flight" and call["args"] == {"flight_id": "6E-2020", "passengers": 2}
