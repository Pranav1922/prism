"""Fast understanding (T0) interface.

The kernel calls `understand(text, payload, ctx)` inside its step, so an implementation must be pure,
bounded and fast. It returns an interpretation; the KERNEL decides every state change and action.

Implementations:
  * agent.understand_rules.recognize: the deterministic, schema-derived recogniser (default, Phase 4);
  * annotated: reads a scripted annotation carried by internal test events (Phase 1 simulator tests).

Annotation shape (payload["t0"], internal tests only; the wire protocol cannot carry it):
  {"class": "CORRECTION" | ..., "writes": {slot: value}, "confirm": bool}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent.model import TurnClass

BACKCHANNEL_WORDS = frozenset({"uh-huh", "mm", "mhm", "hmm", "um", "uh", "okay", "ok", "yeah", "right"})


@dataclass(frozen=True)
class Understanding:
    cls: TurnClass
    writes: dict = field(default_factory=dict)  # slot -> canonical value, or None to retract (attributed, value unknown)
    confirm: bool = False  # the user confirmed an open confirmation question
    attributed: tuple[str, ...] = ()  # slots the utterance refers to, whether or not a write is needed
    cues: tuple[str, ...] = ()  # why: journaled for the trace, never used for decisions


@dataclass(frozen=True)
class SlotInfo:
    name: str
    value: Any
    schema: dict  # JSON Schema of the tool parameter the slot is bound to ({} if unknown)
    history: tuple = ()  # ((value, writer_seq, source), ...) oldest first, current last


@dataclass(frozen=True)
class UnderstandContext:
    """Read-only view of what the fast path may use. Built by the kernel from the active goal only."""

    intent: str | None = None
    slots: tuple[SlotInfo, ...] = ()
    pending: tuple = ()  # ((kind, slots, asked), ...) unresolved clarifications of the active goal
    utterances: tuple = ()  # ((based_seq, text), ...) closed content turns, oldest first
    turn_text: str = ""  # the current open turn's text before this chunk


EMPTY_CONTEXT = UnderstandContext()


def annotated(text: str, payload: dict, ctx: UnderstandContext | None = None) -> Understanding:
    note = payload.get("t0") or {}
    if "class" in note:
        cls = TurnClass(note["class"])
    elif text.strip().lower().strip(".,!?") in BACKCHANNEL_WORDS:
        cls = TurnClass.BACKCHANNEL
    else:
        cls = TurnClass.REQUEST
    writes = dict(note.get("writes") or {})
    return Understanding(cls, writes, bool(note.get("confirm", False)), tuple(sorted(writes)), ("annotated",))
