"""Core domain types, canonical JSON and content/idempotency keys.

Terms follow ARCHITECTURE_REVIEW.md -> FINAL ARCHITECTURE -> Terms. Every value stored in session
state is immutable (frozen dataclass, tuple, str, number) so the kernel's decide/apply split can share
values without copying.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
from dataclasses import dataclass
from typing import Any


class Kind(str, enum.Enum):
    """Normalised internal event kinds (review §7.2)."""

    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    MANIFEST = "Manifest"
    USER_TEXT = "UserText"
    END_OF_TURN = "EndOfTurn"
    MEDIA = "Media"
    EVIDENCE = "Evidence"
    INTERRUPT = "Interrupt"
    TOOL_RESULT = "ToolResult"
    PROPOSAL = "Proposal"
    PROPOSAL_FAILED = "ProposalFailed"
    PERCEPTION_FAILED = "PerceptionFailed"
    TIMER = "Timer"


class Relevance(str, enum.Enum):
    DESIRED = "DESIRED"
    SUPERSEDED = "SUPERSEDED"  # terminal (INV-07)


class Outcome(str, enum.Enum):
    PENDING = "PENDING"
    OK = "OK"
    FAILED_CLEAN = "FAILED_CLEAN"  # explicitly not executed
    UNKNOWN = "UNKNOWN"  # timeout, malformed, or execution unknown


# Monotonic outcome transitions (Terms: Outcome). OK is terminal.
OUTCOME_MOVES: dict[Outcome, tuple[Outcome, ...]] = {
    Outcome.PENDING: (Outcome.OK, Outcome.FAILED_CLEAN, Outcome.UNKNOWN),
    Outcome.UNKNOWN: (Outcome.OK, Outcome.FAILED_CLEAN),
    Outcome.FAILED_CLEAN: (Outcome.OK,),  # anomaly, journaled
    Outcome.OK: (),
}
KNOWN_OUTCOMES = (Outcome.OK, Outcome.FAILED_CLEAN)


class OpState(str, enum.Enum):
    FREE = "FREE"
    LOCKED = "LOCKED"
    COMMITTED = "COMMITTED"


class Effect(str, enum.Enum):
    READ_ONLY = "read_only"
    STATE_CHANGING = "state_changing"


class GoalStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class TurnClass(str, enum.Enum):
    BACKCHANNEL = "BACKCHANNEL"
    ANSWER = "ANSWER"
    STATUS_QUERY = "STATUS_QUERY"
    CORRECTION = "CORRECTION"
    GOAL_SWITCH = "GOAL_SWITCH"
    REQUEST = "REQUEST"


# ---------------------------------------------------------------- canonical JSON and keys


def to_jsonable(obj: Any) -> Any:
    """Deterministic plain-JSON view of any state value."""
    if isinstance(obj, enum.Enum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {(k if isinstance(k, str) else canonical_json(k)): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    raise TypeError(f"not JSON-able: {type(obj).__name__}")


def canonical_json(obj: Any) -> str:
    return json.dumps(to_jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _sha(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def content_key(tool: str, canonical_args: dict) -> str:
    """What work a call performs (INV-05). Never Python's hash()."""
    return _sha(["content", tool, canonical_args])


def idempotency_key(op_id: tuple, canonical_args: dict) -> str:
    """Same for retries with identical arguments (INV-17)."""
    return _sha(["idem", list(op_id), canonical_args])


def freeze(obj: Any) -> Any:
    """Deep, JSON-level copy used at trust boundaries so producers cannot alias state."""
    return json.loads(canonical_json(obj))


# ---------------------------------------------------------------- events and actions


@dataclass(frozen=True)
class Event:
    kind: Kind
    t: float  # harness time; the kernel's only notion of "now" (INV-02)
    payload: Any = None  # JSON-compatible, never mutated
    eid: str | None = None  # harness id when the wire provides one
    seq: int = 0  # assigned by the inbox only


class ActionKind(str, enum.Enum):
    SPEAK = "SPEAK"
    TOOL_CALL = "TOOL_CALL"
    CANCEL = "CANCEL"
    CLARIFY = "CLARIFY"
    FINAL = "FINAL"
    SNAPSHOT = "SNAPSHOT"


SPEECH_KINDS = (ActionKind.SPEAK, ActionKind.CLARIFY, ActionKind.FINAL)


@dataclass(frozen=True)
class Action:
    action_id: str
    kind: ActionKind
    seq: int  # step that emitted it
    rule: str
    caused_by: tuple[int, ...]
    payload: Any


# ---------------------------------------------------------------- session state values


@dataclass(frozen=True)
class Register:
    value: Any
    writer_seq: int
    source: str  # T0 | PLANNER | USER | EVIDENCE
    confirmed: bool
    history: tuple = ()  # ((value, writer_seq, source), ...)


@dataclass(frozen=True)
class Node:
    node_id: str
    tool: str
    args: tuple  # ((param, binding), ...); binding = ("slot", name) | ("node", node_id, path) | ("const", value)
    instance_tag: str = ""


@dataclass(frozen=True)
class Goal:
    goal_id: str
    intent: str
    status: GoalStatus
    origin_seq: int | None  # user-content seq that established it (provenance, INV-15)
    created_seq: int
    graph: tuple[Node, ...] = ()
    plan_rev: int = 0
    final_keys: tuple | None = None  # desired keys when the last FINAL was emitted


@dataclass(frozen=True)
class Call:
    call_id: str  # execution identity (INV-04)
    goal_id: str
    node_id: str
    tool: str
    args_json: str  # canonical
    key: str  # content key
    effect: Effect
    relevance: Relevance
    outcome: Outcome
    dispatched_seq: int
    op_id: tuple | None = None
    idem_key: str | None = None
    result_json: str | None = None
    superseded_reason: str | None = None
    superseded_seq: int | None = None


@dataclass(frozen=True)
class Turn:
    turn_id: int
    open: bool
    text: str = ""
    classes: tuple[str, ...] = ()
    content: bool = False
    interrupting: bool = False
    t0_writes: tuple = ()  # ((goal_id, slot, writer_seq), ...)
    marker_seqs: tuple[int, ...] = ()  # seqs of chunks carrying correction / goal-switch markers


@dataclass(frozen=True)
class Timer:
    timer_id: str
    purpose: str  # tool_timeout | eot_silence | deadline
    due_t: float
    ref: str | None = None


@dataclass(frozen=True)
class Pending:
    pid: str
    goal_id: str
    kind: str  # conflict | invalid_args | divergence | unknown_outcome | exhausted | planner_clarify
    slots: tuple[str, ...]
    text: str
    asked: bool
    created_seq: int
    resolved: bool = False


@dataclass(frozen=True)
class Request:
    req_id: str
    purpose: str
    based_on_seq: int
    user_seq: int | None  # user-content seq behind the request (provenance); None if there was none
    open: bool = True


@dataclass(frozen=True)
class Frame:
    frame_eid: str
    seq: int
    goal_id: str | None
    claims: tuple = ()  # ((key, value, confidence), ...) once evidence arrives


def snapshot(goal: Goal | None, slots: dict) -> dict:
    """snapshot(ACTIVE goal): intent + best current register values (F7). Pure."""
    if goal is None:
        return {"intent": None, "slots": {}}
    values = {name: reg.value for (gid, name), reg in slots.items() if gid == goal.goal_id and reg.value is not None}
    return {"intent": goal.intent, "slots": dict(sorted(values.items()))}
