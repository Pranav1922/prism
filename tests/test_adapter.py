"""PRISM-LOCAL/0 adapter contract tests: ingress, egress, malformed messages, isolation, lockstep agent."""

import ast
import json
from pathlib import Path

import pytest

from agent.adapter.egress import Egress, EgressError, action_to_wire, validate
from agent.adapter.ingress import Ingress, Rejected, Tick
from agent.adapter.schema import VERSION, schema_document
from agent.adapter.stdio import DEFAULT_FIXTURES, LocalAgent
from agent.model import Action, ActionKind, Event, Kind

ROOT = Path(__file__).resolve().parents[1]


def msg(mid, t, typ, data=None, v=VERSION):
    return json.dumps({"v": v, "id": mid, "t": t, "type": typ, "data": data or {}})


# ---------------------------------------------------------------- valid input round trips

VALID = [
    ("session.start", {}, Kind.SESSION_START, {}),
    ("session.end", {}, Kind.SESSION_END, {}),
    ("manifest", {"tools": [{"name": "x"}]}, Kind.MANIFEST, {"tools": [{"name": "x"}]}),
    ("user.text", {"text": "hi"}, Kind.USER_TEXT, {"text": "hi"}),
    ("user.turn_end", {}, Kind.END_OF_TURN, {}),
    ("user.audio", {"ref": "a1", "duration_s": 1.5}, Kind.MEDIA, {"kind": "audio", "ref": "a1"}),
    ("user.frame", {"ref": "f1"}, Kind.MEDIA, {"kind": "image", "ref": "f1"}),
    ("user.interrupt", {}, Kind.INTERRUPT, {}),
    ("tool.result", {"call_id": "c1", "status": "ok", "data": {"x": 1}}, Kind.TOOL_RESULT,
     {"call_id": "c1", "outcome": "ok", "data": {"x": 1}, "executed": None}),
    ("tool.result", {"call_id": "c1", "status": "cancelled"}, Kind.TOOL_RESULT,
     {"call_id": "c1", "outcome": "cancelled_ack", "data": None, "executed": None}),
    ("tool.result", {"call_id": "c2", "status": "error", "executed": False}, Kind.TOOL_RESULT,
     {"call_id": "c2", "outcome": "error", "data": None, "executed": False}),
]


@pytest.mark.parametrize("typ,data,kind,payload", VALID)
def test_valid_harness_input_maps_to_internal_event(typ, data, kind, payload):
    ev = Ingress().parse(msg("m1", 1.25, typ, data))
    assert isinstance(ev, Event) and (ev.kind, ev.t, ev.eid, ev.payload) == (kind, 1.25, "m1", payload)


def test_clock_tick_is_not_an_event():
    tick = Ingress().parse(msg("k1", 3.0, "clock.tick"))
    assert tick == Tick(3.0, "k1")


def test_worker_channel_types_only_on_worker_channel():
    line = msg("w1", 1.0, "worker.proposal", {"req_id": "r1", "based_on_seq": 3, "proposal": {"intent": "x"}})
    assert Ingress("harness").parse(line) == Rejected("w1", "type_not_allowed_on_channel")
    ev = Ingress("worker").parse(line)
    assert ev.kind is Kind.PROPOSAL and ev.payload == {"intent": "x", "req_id": "r1", "based_on_seq": 3}
    evid = Ingress("worker").parse(msg("w2", 1.0, "worker.evidence", {"req_id": "p1", "frame_id": "f1",
                                                                      "claims": {"date": ["Fri", 0.9]}}))
    assert evid.kind is Kind.EVIDENCE and evid.payload == {"frame_eid": "f1", "claims": {"date": ["Fri", 0.9]}}
    tr = Ingress("worker").parse(msg("w3", 1.0, "worker.transcript", {"req_id": "p2", "source_id": "a1", "text": "hi"}))
    assert tr.kind is Kind.USER_TEXT and tr.payload["source"] == "asr"


# ---------------------------------------------------------------- malformed input is rejected, never repaired

MALFORMED = [
    ("not json", None, "malformed_json"),
    ("[1, 2]", None, "not_an_object"),
    (msg("m1", 1.0, "user.turn_end", v="PRISM-LOCAL/9"), "m1", "unsupported_version"),
    (json.dumps({"v": VERSION, "t": 1.0, "type": "user.turn_end", "data": {}}), None, "invalid_envelope"),
    (json.dumps({"v": VERSION, "id": "m1", "type": "user.turn_end", "data": {}}), "m1", "invalid_envelope"),
    (json.dumps({"v": VERSION, "id": "m1", "t": -1, "type": "user.turn_end", "data": {}}), "m1", "invalid_envelope"),
    (json.dumps({"v": VERSION, "id": "m1", "t": 1.0, "type": "user.turn_end", "data": {}, "extra": 1}), "m1", "invalid_envelope"),
    (msg("m1", 1.0, "user.dance"), "m1", "unknown_type"),
    (msg("m1", 1.0, "user.text", {"text": ""}), "m1", "invalid_payload"),
    (msg("m1", 1.0, "user.text", {"text": "hi", "t0": {"class": "CORRECTION"}}), "m1", "invalid_payload"),
    (msg("m1", 1.0, "manifest", {"tools": "search"}), "m1", "invalid_payload"),
    (msg("m1", 1.0, "tool.result", {"call_id": "c1", "status": "maybe"}), "m1", "invalid_payload"),
    (msg("m1", 1.0, "tool.result", {"status": "ok"}), "m1", "invalid_payload"),
]


@pytest.mark.parametrize("line,ref,reason", MALFORMED)
def test_malformed_input_is_rejected(line, ref, reason):
    got = Ingress().parse(line)
    assert isinstance(got, Rejected) and got.ref == ref and got.reason.startswith(reason)


def test_duplicate_ids_and_timestamp_regression_rejected_equal_times_allowed():
    ing = Ingress()
    assert isinstance(ing.parse(msg("a", 1.0, "user.turn_end")), Event)
    assert ing.parse(msg("a", 2.0, "user.turn_end")) == Rejected("a", "duplicate_id")
    assert isinstance(ing.parse(msg("b", 1.0, "user.turn_end")), Event)  # same time, new id: fine
    assert ing.parse(msg("c", 0.5, "user.turn_end")) == Rejected("c", "timestamp_regression")
    assert len(ing.rejected) == 2


# ---------------------------------------------------------------- egress

SNAP = {"intent": "search_flights", "slots": {"destination": "BOM"}}
ACTIONS = [
    (ActionKind.SPEAK, {"text": "Working on it", "act": "ack", "grounded_on": []}, "speech",
     {"text": "Working on it", "act": "ack"}),
    (ActionKind.CLARIFY, {"text": "Which date?", "slots": ["date"], "reason": "conflict"}, "clarify",
     {"text": "Which date?", "slots": ["date"]}),
    (ActionKind.TOOL_CALL, {"call_id": "c3", "tool": "book_flight", "args": {"passengers": 2}, "uses": ["c1"],
                            "idempotency_key": "k" * 64}, "tool.call",
     {"call_id": "c3", "tool": "book_flight", "args": {"passengers": 2}, "idempotency_key": "k" * 64}),
    (ActionKind.CANCEL, {"call_id": "c1", "reason": "not_desired"}, "tool.cancel", {"call_id": "c1"}),
    (ActionKind.FINAL, {"text": "Done", "act": "answer", "grounded_on": ["c2"], "ops": [], "ledger_calls": ["c7"],
                        "snapshot": SNAP}, "response.final",
     {"text": "Done", "snapshot": SNAP, "complete": True, "grounded_on": ["c2", "c7"]}),
    (ActionKind.SNAPSHOT, {"snapshot": SNAP}, "state.snapshot", {"snapshot": SNAP}),
]


@pytest.mark.parametrize("kind,payload,typ,data", ACTIONS)
def test_action_to_wire_is_valid_and_hides_internal_fields(kind, payload, typ, data):
    wire = action_to_wire(Action("a5", kind, 4, "RULE.x", (4,), payload), 2.5, ["i3"])
    validate(wire)
    assert wire == {"v": VERSION, "id": "a5", "t": 2.5, "type": typ, "data": data, "cause": ["i3"]}


def test_egress_stamps_the_causing_event_time_and_wire_id():
    eg = Egress()
    eg.note(Event(Kind.USER_TEXT, 1.4, {}, "fix", 6))
    wire = eg.to_wire(Action("a9", ActionKind.CANCEL, 6, "REL.supersede", (6,), {"call_id": "c1", "reason": "x"}))
    assert (wire["t"], wire["cause"]) == (1.4, ["fix"])


@pytest.mark.parametrize("payload", [
    {"text": "Done", "act": "answer", "grounded_on": [], "ops": [], "snapshot": {"intent": "x"}},  # slots missing
    {"text": "", "act": "answer", "grounded_on": [], "ops": [], "snapshot": SNAP},  # empty text
])
def test_invalid_final_action_is_refused_at_egress(payload):
    eg = Egress()
    eg.note(Event(Kind.TOOL_RESULT, 1.0, {}, "w1", 3))
    with pytest.raises(EgressError):
        eg.to_wire(Action("a1", ActionKind.FINAL, 3, "r", (3,), payload))


def test_tool_call_identifier_must_be_a_nonempty_string():
    wire = action_to_wire(Action("a1", ActionKind.TOOL_CALL, 1, "r", (1,), {"call_id": "", "tool": "t", "args": {},
                                                                            "uses": []}), 0.0, [])
    with pytest.raises(EgressError):
        validate(wire)


# ---------------------------------------------------------------- contract file and isolation


def test_published_schema_file_matches_the_adapter():
    published = json.loads((ROOT / "protocol" / "prism_local_0.schema.json").read_text())
    assert published == json.loads(json.dumps(schema_document()))


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_only_the_adapter_knows_the_wire_format():
    for path in (ROOT / "agent").rglob("*.py"):
        if "adapter" in path.parts:
            continue
        assert not any(n.startswith("agent.adapter") for n in _imports(path)), path
        assert "PRISM-LOCAL" not in path.read_text(), path


def test_the_evaluator_never_imports_agent_code():
    for path in (ROOT / "evaluation").rglob("*.py"):
        assert not any(n == "agent" or n.startswith("agent.") for n in _imports(path)), path


# ---------------------------------------------------------------- the lockstep agent


def agent():
    return LocalAgent(json.loads(DEFAULT_FIXTURES.read_text()))


def test_every_input_gets_exactly_one_trailing_agent_ready():
    a = agent()
    for line in (msg("s", 0, "session.start"), "garbage", msg("k", 1.0, "clock.tick")):
        outs = [json.loads(x) for x in a.handle(line)]
        assert [o["type"] for o in outs].count("agent.ready") == 1 and outs[-1]["type"] == "agent.ready"
        for o in outs:
            validate(o)


def test_rejected_input_never_reaches_the_kernel():
    a = agent()
    a.handle(msg("s", 0, "session.start"))
    rev, steps = a.kernel.state.get("meta", "rev"), len(a.journal.of_type("step"))
    outs = [json.loads(x) for x in a.handle(msg("s", 0.1, "user.text", {"text": "dup id"}))]
    assert outs[0]["type"] == "protocol.error" and outs[0]["data"] == {"ref": "s", "reason": "duplicate_id"}
    assert a.kernel.state.get("meta", "rev") == rev and len(a.journal.of_type("step")) == steps


def test_harness_events_at_time_t_precede_the_agents_own_timers_at_t():
    a = agent()
    a.handle(msg("s", 0, "session.start"))
    a.handle(msg("u", 0.25, "user.text", {"text": "hello there"}))  # arms the 1 s silence timer: due 1.25
    outs = [json.loads(x) for x in a.handle(msg("e", 1.25, "user.turn_end"))]
    assert outs[-1]["data"]["next_wakeup"] is not None
    rules = [r["rule"] for rec in a.journal.of_type("step") for r in rec["rules"]]
    assert "TIMER.fire" not in rules  # the explicit end of turn at 1.25 won; the timer was disarmed


def test_world_never_answers_before_the_call_arrives():
    from evaluation.world import World
    w = World({"t": {"behaviors": [{"at": 2.0, "status": "ok", "data": 1}]}}, [{"name": "t"}])
    assert [t for t, _ in w.on_output({"type": "tool.call", "data": {"call_id": "c1", "tool": "t", "args": {}}}, 1.0)] == [2.0]
    assert [t for t, _ in w.on_output({"type": "tool.call", "data": {"call_id": "c2", "tool": "t", "args": {}}}, 6.0)] == [6.0]
