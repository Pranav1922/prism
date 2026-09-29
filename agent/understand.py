"""Fast understanding (T0) interface.

The kernel calls `understand(text, payload)` inside its step, so the function must be pure and bounded.
Phase 1 ships `annotated`: it reads a scripted annotation carried by the (internal) event, which lets the
kernel's rules be tested without inventing NLU. Phase 3 replaces it with schema-derived recognisers
(ARCHITECTURE_REVIEW.md §6.4, F4) behind the same signature.

Annotation shape (payload["t0"], all optional):
  {"class": "CORRECTION" | "GOAL_SWITCH" | "ANSWER" | "STATUS_QUERY" | "BACKCHANNEL" | "REQUEST",
   "writes": {slot: value}, "confirm": bool}
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.model import TurnClass

BACKCHANNEL_WORDS = frozenset({"uh-huh", "mm", "mhm", "hmm", "um", "uh", "okay", "ok", "yeah", "right"})


@dataclass(frozen=True)
class Understanding:
    cls: TurnClass
    writes: dict = field(default_factory=dict)
    confirm: bool = False


def annotated(text: str, payload: dict) -> Understanding:
    note = payload.get("t0") or {}
    if "class" in note:
        cls = TurnClass(note["class"])
    elif text.strip().lower().strip(".,!?") in BACKCHANNEL_WORDS:
        cls = TurnClass.BACKCHANNEL
    else:
        cls = TurnClass.REQUEST
    return Understanding(cls, dict(note.get("writes") or {}), bool(note.get("confirm", False)))
