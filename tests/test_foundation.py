"""Foundations: keys (INV-05, INV-17), clock tie rule (INV-02), inbox, registry, egress schema (INV-22),
and static guarantees that the kernel cannot read time, randomness or wire types (INV-01/02)."""

import ast
import os
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agent.clock import FakeClock, Scheduler
from agent.inbox import Inbox
from agent.model import Action, ActionKind, Event, Kind, canonical_json, content_key, idempotency_key
from agent.protocol import validate_action
from agent.registry import ArgError, Registry
from agent.scenario import MANIFEST

ROOT = Path(__file__).resolve().parents[1]
json_values = st.recursive(st.none() | st.booleans() | st.integers() | st.text(max_size=8),
                           lambda c: st.lists(c, max_size=3) | st.dictionaries(st.text(max_size=5), c, max_size=3),
                           max_leaves=8)


# ---------------------------------------------------------------- INV-05 content key


def test_content_key_ignores_argument_order_and_distinguishes_values():
    assert content_key("t", {"a": 1, "b": "x"}) == content_key("t", {"b": "x", "a": 1})
    assert content_key("t", {"a": 1}) != content_key("t", {"a": 2})
    assert content_key("t", {"a": 1}) != content_key("u", {"a": 1})
    assert len(content_key("t", {})) == 64  # SHA-256 hex


def test_content_key_stable_across_processes_and_hash_seeds():
    code = "from agent.model import content_key; print(content_key('search', {'b': [1, 2], 'a': 'x'}))"
    outs = set()
    for seed in ("0", "1", "12345", "random"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        outs.add(subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True,
                                text=True, check=True).stdout)
    assert len(outs) == 1


def test_canonical_json_rejects_nan():
    with pytest.raises(ValueError):
        canonical_json({"x": float("nan")})


# ---------------------------------------------------------------- INV-17 idempotency key


@settings(derandomize=True, max_examples=200)
@given(args=st.dictionaries(st.text(max_size=5), json_values, max_size=4), other=json_values)
def test_idempotency_key_equality_rules(args, other):
    op = ("g1", "book_flight", "")
    assert idempotency_key(op, args) == idempotency_key(op, dict(reversed(list(args.items()))))
    assert idempotency_key(op, args) != idempotency_key(("g1", "book_flight", "second"), args)
    changed = {**args, "__extra__": other}
    assert idempotency_key(op, args) != idempotency_key(op, changed)


# ---------------------------------------------------------------- INV-02 clock tie rule


def _timer_event(t):
    return Event(Kind.TIMER, t, {"timer_id": "x", "purpose": "p", "due_t": t, "ref": None})


def test_scheduler_delivers_events_before_timers_at_equal_time():
    s = Scheduler(FakeClock())
    s.arm("x", 2.0, "p", None)
    s.at(2.0, Event(Kind.TOOL_RESULT, 2.0, {"call_id": "c1"}))
    s.at(1.0, Event(Kind.USER_TEXT, 1.0, {"text": "hi"}))
    assert [s.pop().kind for _ in range(3)] == [Kind.USER_TEXT, Kind.TOOL_RESULT, Kind.TIMER]


def test_scheduler_rearm_replaces_and_disarm_drops():
    s = Scheduler(FakeClock())
    s.arm("x", 1.0, "p", None)
    s.arm("x", 3.0, "p", None)  # replaces the 1.0 instance
    s.arm("y", 2.0, "p", None)
    s.disarm("y")
    popped = [(e.payload["timer_id"], e.t) for e in iter(s.pop, None)]
    assert popped == [("x", 3.0)]


def test_fake_clock_is_monotonic():
    c = FakeClock(1.0)
    with pytest.raises(ValueError):
        c.advance_to(0.5)


# ---------------------------------------------------------------- inbox


def test_inbox_assigns_one_seq_per_event_and_dedupes_by_harness_id_only():
    box = Inbox()
    a = box.put(Event(Kind.USER_TEXT, 0.1, {"text": "yes"}, "u1"))
    assert box.put(Event(Kind.USER_TEXT, 0.1, {"text": "yes"}, "u1")) is None  # same harness id
    b = box.put(Event(Kind.USER_TEXT, 0.2, {"text": "yes"}))  # same content, no id: kept
    assert (a.seq, b.seq) == (1, 2) and len(box) == 2 and len(box.dropped) == 1
    assert [box.get().seq, box.get().seq, box.get()] == [1, 2, None]


def test_inbox_freezes_payload_against_producer_mutation():
    box = Inbox()
    payload = {"text": "hi", "t0": {"writes": {"x": 1}}}
    ev = box.put(Event(Kind.USER_TEXT, 0.0, payload))
    payload["t0"]["writes"]["x"] = 99
    assert ev.payload["t0"]["writes"]["x"] == 1


# ---------------------------------------------------------------- registry


def test_registry_classifies_by_manifest_then_verb_then_default():
    reg = Registry.from_manifest(MANIFEST + [
        {"name": "lookup_order", "parameters": {"type": "object"}},
        {"name": "order_status", "description": "Check an order", "parameters": {"type": "object"}},
        {"name": "create_ticket", "parameters": {"type": "object"}},
    ])
    got = {t.name: (t.effect.value, t.effect_reason) for t in reg.tools}
    assert got["book_flight"] == ("state_changing", "manifest")
    assert got["search_flights"] == ("read_only", "name_verb:search")
    assert got["lookup_order"] == ("read_only", "name_verb:lookup")
    assert got["order_status"] == ("read_only", "description_verb:check")
    assert got["create_ticket"] == ("state_changing", "default")


def test_registry_quarantines_malformed_tools_and_keeps_the_rest():
    reg = Registry.from_manifest([
        {"name": "ok_tool", "parameters": {"type": "object"}},
        {"parameters": {"type": "object"}},  # missing name
        {"name": "ok_tool", "parameters": {"type": "object"}},  # duplicate
        {"name": "bad_schema", "parameters": {"type": "object", "properties": {"x": {"type": 7}}}},
        {"name": "bad_timeout", "parameters": {"type": "object"}, "timeout_s": -1},
        {"name": "bad_params", "parameters": ["not", "an", "object"]},
        "not a dict",
    ])
    assert [t.name for t in reg.tools] == ["ok_tool"]
    assert len(reg.quarantined) == 6
    assert Registry.from_manifest(None).tools == ()


def test_canonicalize_validates_and_trims():
    spec = Registry.from_manifest(MANIFEST).get("book_flight")
    assert spec.canonicalize({"flight_id": " 6E-701 ", "passengers": 2}) == {"flight_id": "6E-701", "passengers": 2}
    for bad in ({"flight_id": "6E-701", "passengers": "two"}, {"flight_id": "6E-701"},
                {"flight_id": "6E-701", "passengers": 0}, {"flight_id": "x", "passengers": 1, "extra": 1}):
        with pytest.raises(ArgError):
            spec.canonicalize(bad)


# ---------------------------------------------------------------- INV-22 egress schema


def test_validate_action_accepts_valid_and_rejects_malformed():
    ok = Action("a1", ActionKind.CANCEL, 3, "REL.supersede", (3,), {"call_id": "c1", "reason": "x"})
    validate_action(ok)
    bad = [
        Action("a1", ActionKind.CANCEL, 3, "r", (3,), {"call_id": "c1"}),  # missing reason
        Action("x1", ActionKind.CANCEL, 3, "r", (3,), {"call_id": "c1", "reason": "x"}),  # bad id
        Action("a1", ActionKind.CANCEL, 3, "r", (), {"call_id": "c1", "reason": "x"}),  # no cause
        Action("a1", ActionKind.FINAL, 3, "r", (3,), {"text": "t", "act": "answer", "grounded_on": [], "ops": [],
                                                      "snapshot": {"intent": None}}),  # snapshot incomplete
        Action("a1", ActionKind.SPEAK, 3, "r", (3,), {"text": "", "act": "ack", "grounded_on": []}),  # empty text
    ]
    for action in bad:
        with pytest.raises(jsonschema.ValidationError):
            validate_action(action)


# ---------------------------------------------------------------- INV-01 / INV-02 static guarantees

PURE_MODULES = ["kernel.py", "model.py", "registry.py", "understand.py", "protocol.py"]
FORBIDDEN_IMPORTS = {"time", "datetime", "random", "uuid", "os", "asyncio", "threading", "socket", "subprocess",
                     "requests", "urllib"}


@pytest.mark.parametrize("module", PURE_MODULES)
def test_kernel_side_modules_cannot_read_time_randomness_or_do_io(module):
    tree = ast.parse((ROOT / "agent" / module).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not {a.name.split(".")[0] for a in node.names} & FORBIDDEN_IMPORTS, module
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in FORBIDDEN_IMPORTS, module
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("hash", "open", "print", "input", "eval", "exec"), f"{module}: {node.func.id}()"


def test_only_kernel_apply_assigns_into_state_tables():
    """INV-01 structurally: the only writes into State.t[...][...] are in Kernel.apply (and _meta_defaults)."""
    tree = ast.parse((ROOT / "agent" / "kernel.py").read_text())
    writers = []
    for func in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for node in ast.walk(func):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AugAssign) else []
            for t in targets:
                if isinstance(t, ast.Subscript) and "state.t" in ast.unparse(t):
                    writers.append(func.name)
    assert set(writers) == {"apply"}, writers
    for other in ("runtime.py", "scenario.py", "planner.py", "journal.py", "inbox.py", "clock.py"):
        assert ".state.t[" not in (ROOT / "agent" / other).read_text().replace(" ", ""), other
