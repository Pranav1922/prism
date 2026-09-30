"""PRISM-LOCAL/0 ingress: wire -> internal Event (or a clock tick, or a rejection).

Malformed input is REJECTED, never repaired: it produces a `Rejected` record and changes no kernel state.
Checks, in order: JSON -> object -> protocol version -> envelope (id, t, type, data) -> known type for this
channel -> payload schema -> duplicate id -> timestamp regression.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import jsonschema

from agent.adapter.schema import HARNESS_INPUT, INPUT_ENVELOPE, VERSION, WORKER_INPUT
from agent.model import Event, Kind

_ENV = jsonschema.Draft202012Validator(INPUT_ENVELOPE)
_DATA = {k: jsonschema.Draft202012Validator(v) for k, v in {**HARNESS_INPUT, **WORKER_INPUT}.items()}
_CHANNELS = {"harness": set(HARNESS_INPUT), "worker": set(WORKER_INPUT)}


@dataclass(frozen=True)
class Rejected:
    ref: str | None  # the message id, if one could be read
    reason: str


@dataclass(frozen=True)
class Tick:
    t: float
    wire_id: str


_STATUS = {"ok": "ok", "error": "error", "cancelled": "cancelled_ack"}


def wire_to_event(msg: dict) -> Event | Tick:
    """Pure conversion of an already-validated message."""
    typ, data, t, mid = msg["type"], msg["data"], float(msg["t"]), msg["id"]
    if typ == "clock.tick":
        return Tick(t, mid)
    simple = {"session.start": Kind.SESSION_START, "session.end": Kind.SESSION_END,
              "user.turn_end": Kind.END_OF_TURN, "user.interrupt": Kind.INTERRUPT}
    if typ in simple:
        return Event(simple[typ], t, {}, mid)
    if typ == "manifest":
        return Event(Kind.MANIFEST, t, {"tools": data["tools"]}, mid)
    if typ == "user.text":
        return Event(Kind.USER_TEXT, t, {"text": data["text"], **({"source": data["source"]} if "source" in data else {})}, mid)
    if typ == "user.audio":
        return Event(Kind.MEDIA, t, {"kind": "audio", "ref": data["ref"]}, mid)
    if typ == "user.frame":
        return Event(Kind.MEDIA, t, {"kind": "image", "ref": data["ref"]}, mid)
    if typ == "tool.result":
        return Event(Kind.TOOL_RESULT, t, {"call_id": data["call_id"], "outcome": _STATUS[data["status"]],
                                           "data": data.get("data"), "executed": data.get("executed")}, mid)
    if typ == "worker.proposal":
        return Event(Kind.PROPOSAL, t, {**data["proposal"], "req_id": data["req_id"], "based_on_seq": data["based_on_seq"]}, mid)
    if typ == "worker.proposal_failed":
        return Event(Kind.PROPOSAL_FAILED, t, dict(data), mid)
    if typ == "worker.evidence":
        return Event(Kind.EVIDENCE, t, {"frame_eid": data["frame_id"], "claims": data["claims"]}, mid)
    if typ == "worker.transcript":
        return Event(Kind.USER_TEXT, t, {"text": data["text"], "source": "asr", "source_eid": data["source_id"]}, mid)
    if typ == "worker.perception_failed":
        return Event(Kind.PERCEPTION_FAILED, t, dict(data), mid)
    raise ValueError(f"unhandled type {typ}")  # unreachable after validation


class Ingress:
    """One per channel. Holds only protocol bookkeeping (seen ids, last timestamp), never session state."""

    def __init__(self, channel: str = "harness"):
        self.allowed = _CHANNELS[channel]
        self._seen: set[str] = set()
        self._last_t = 0.0
        self.rejected: list[Rejected] = []

    def parse(self, line: str | bytes) -> Event | Tick | Rejected:
        result = self._parse(line)
        if isinstance(result, Rejected):
            self.rejected.append(result)
        return result

    def _parse(self, line: str | bytes) -> Event | Tick | Rejected:
        try:
            msg = json.loads(line)
        except (ValueError, TypeError):
            return Rejected(None, "malformed_json")
        if not isinstance(msg, dict):
            return Rejected(None, "not_an_object")
        ref = msg["id"] if isinstance(msg.get("id"), str) else None
        if msg.get("v") != VERSION:
            return Rejected(ref, "unsupported_version")
        env = next(iter(sorted(_ENV.iter_errors(msg), key=lambda e: list(e.path))), None)
        if env is not None:
            return Rejected(ref, f"invalid_envelope: {env.message}")
        if msg["type"] not in _DATA:
            return Rejected(ref, "unknown_type")
        if msg["type"] not in self.allowed:
            return Rejected(ref, "type_not_allowed_on_channel")
        bad = next(iter(sorted(_DATA[msg["type"]].iter_errors(msg["data"]), key=lambda e: list(e.path))), None)
        if bad is not None:
            return Rejected(ref, f"invalid_payload: {bad.message}")
        if msg["id"] in self._seen:
            return Rejected(ref, "duplicate_id")
        if msg["t"] < self._last_t:
            return Rejected(ref, "timestamp_regression")
        self._seen.add(msg["id"])
        self._last_t = float(msg["t"])
        return wire_to_event(msg)
