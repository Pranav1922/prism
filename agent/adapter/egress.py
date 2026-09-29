"""PRISM-LOCAL/0 egress: internal Action -> wire message, validated before it leaves the agent.

The kernel keeps producing internal Action objects; only this module knows their wire form.
"""

from __future__ import annotations

import json

import jsonschema

from agent.adapter.schema import OUTPUT, OUTPUT_ENVELOPE, VERSION
from agent.model import Action, ActionKind, Event

_ENV = jsonschema.Draft202012Validator(OUTPUT_ENVELOPE)
_DATA = {k: jsonschema.Draft202012Validator(v) for k, v in OUTPUT.items()}


class EgressError(ValueError):
    pass


def action_to_wire(action: Action, t: float, cause: list[str]) -> dict:
    """Pure conversion. Internal-only fields (rule, reason codes, uses, ops) do not leave the agent."""
    p = action.payload
    if action.kind is ActionKind.SPEAK:
        typ, data = "speech", {"text": p["text"], "act": p["act"]}
    elif action.kind is ActionKind.CLARIFY:
        typ, data = "clarify", {"text": p["text"], "slots": list(p.get("slots", []))}
    elif action.kind is ActionKind.TOOL_CALL:
        typ, data = "tool.call", {"call_id": p["call_id"], "tool": p["tool"], "args": p["args"]}
        if p.get("idempotency_key"):
            data["idempotency_key"] = p["idempotency_key"]
    elif action.kind is ActionKind.CANCEL:
        typ, data = "tool.cancel", {"call_id": p["call_id"]}
    elif action.kind is ActionKind.FINAL:
        typ, data = "response.final", {"text": p["text"], "snapshot": p["snapshot"],
                                       "complete": p.get("act") == "answer",
                                       # external evidence list: DESIRED results + committed ledger attempts (D6)
                                       "grounded_on": list(dict.fromkeys([*p.get("grounded_on", []),
                                                                          *p.get("ledger_calls", [])]))}
    elif action.kind is ActionKind.SNAPSHOT:
        typ, data = "state.snapshot", {"snapshot": p["snapshot"]}
    else:  # pragma: no cover - every ActionKind is mapped above
        raise EgressError(f"no wire form for {action.kind}")
    return {"v": VERSION, "id": action.action_id, "t": t, "type": typ, "data": data, "cause": cause}


def validate(msg: dict) -> None:
    for err in _ENV.iter_errors(msg):
        raise EgressError(f"envelope: {err.message}")
    for err in _DATA[msg["type"]].iter_errors(msg["data"]):
        raise EgressError(f"{msg['type']}: {err.message}")


def encode(msg: dict) -> str:
    return json.dumps(msg, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


class Egress:
    """Maps each action to the wire, stamping the harness time of the event that caused it."""

    def __init__(self) -> None:
        self._events: dict[int, tuple[str, float]] = {}  # seq -> (wire id, t)

    def note(self, event: Event) -> None:
        self._events[event.seq] = (str(event.eid), event.t)

    def to_wire(self, action: Action) -> dict:
        _, t = self._events[action.seq]
        cause = [self._events[s][0] for s in action.caused_by if s in self._events]
        msg = action_to_wire(action, t, cause)
        validate(msg)
        return msg

    @staticmethod
    def control(typ: str, mid: str, t: float, data: dict) -> dict:
        msg = {"v": VERSION, "id": mid, "t": t, "type": typ, "data": data, "cause": []}
        validate(msg)
        return msg
