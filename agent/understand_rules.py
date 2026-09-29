"""Deterministic fast understanding (T0), derived from the active tool schemas.

recognize(text, payload, ctx) -> Understanding. Pure, bounded (<= 64 tokens), no I/O, no model.

Classification (first match wins):
  GOAL_SWITCH   explicit switch phrases ("forget it", "never mind", "scratch that", ...); writes nothing
                (values in a switch belong to the NEW goal, which only the planner can create)
  STATUS_QUERY  status phrases ("how long", "what's happening", "are you still", ...) carrying no slot values
  BACKCHANNEL   every token is an acknowledgement ("okay", "got it", "uh-huh", "yes") -> ANSWER(confirm)
                instead, only if an asked confirmation is open
  CORRECTION    a repair marker at the start ("no", "wait", "actually", "make it", "change", "instead", ...),
                or a new value for an already-filled slot
  ANSWER        values for slots an open clarification asked about
  REQUEST       everything else

Slot extraction uses only the active goal's slots and their parameter JSON Schemas, in this order:
  1. named:  a slot's name is mentioned ("change the destination to X", "the date is X")
  2. role:   a preposition whose role matches exactly one slot name ("to X" -> destination-like, "from X")
  3. typed:  a token that only one slot can hold (an enum value, a number for the only integer slot)
  4. bare:   after a repair marker, leftover content words ("no, Mumbai") go to the one string slot that
             can take them, or to the most recently mentioned such slot; otherwise ABSTAIN.
A value is written only if it validates against the parameter schema (directly, or through an alias the
user taught earlier in the session: a surface form the planner then wrote canonically). If a correction is
clearly attributed but its value cannot be made schema-valid, the slot is RETRACTED (None): dependent work
is superseded at once and the planner supplies the canonical value. Nothing is ever invented.
"""

from __future__ import annotations

import functools
import json
import re
from typing import Any

import jsonschema

from agent.model import TurnClass
from agent.understand import EMPTY_CONTEXT, SlotInfo, UnderstandContext, Understanding, annotated

MAX_TOKENS = 64
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:['\-][A-Za-z0-9]+)*")

FILLERS = frozenset({"um", "uh", "er", "erm", "oh", "hmm", "so", "well"})
ACK = frozenset({"ok", "okay", "k", "yes", "yeah", "yep", "yup", "sure", "right", "alright", "cool", "great", "fine",
                 "good", "nice", "perfect", "thanks", "thank", "you", "mm", "mhm", "mmhmm", "mm-hmm", "uh-huh", "hmm",
                 "gotcha", "got", "it", "i", "see", "understood", "noted", "awesome", "sounds", "go", "ahead", "that", "please"})
AFFIRM = frozenset({"yes", "yeah", "yep", "yup", "sure", "correct", "right", "ok", "okay", "exactly", "please", "ahead"})
MARKER_WORDS = frozenset({"no", "nope", "nah", "wait", "actually", "sorry", "oops", "correction", "instead", "rather",
                          "hold", "hang", "change", "switch", "update", "not"})
MARKER_PAIRS = (("make", "it"), ("make", "that"), ("i", "mean"), ("i", "meant"))
SWITCH = (("forget", "it"), ("forget", "that"), ("forget", "about"), ("never", "mind"), ("nevermind",),
          ("scratch", "that"), ("cancel", "that"), ("something", "else"), ("do", "something", "else"))
STATUS = (("how", "long"), ("how", "much", "longer"), ("what's", "happening"), ("whats", "happening"),
          ("what", "is", "happening"), ("what's", "going", "on"), ("what", "is", "going", "on"), ("are", "you", "still"),
          ("still", "there"), ("still", "working"), ("still", "searching"), ("is", "it", "done"), ("are", "you", "done"),
          ("is", "it", "ready"), ("any", "update"), ("any", "updates"), ("any", "news"), ("what's", "the", "status"),
          ("status",), ("taking", "so", "long"), ("how's", "it", "going"), ("how", "is", "it", "going"),
          ("did", "it", "work"), ("where", "are", "we"))
STOP = frozenset({"the", "a", "an", "and", "instead", "please", "then", "on", "from", "to", "for", "at", "in", "of",
                  "actually", "rather", "not", "but", "with", "by", "is", "it", "that", "this", "right", "okay", "ok",
                  "now", "too", "also", "again", "be", "will", "would", "like", "make", "change", "flight", "flights",
                  "no", "wait", "sorry", "yes", "should", "can", "you", "i", "me", "my", "us", "want", "need", "let's",
                  "go", "there", "here", "so", "just", "do", "switch", "update", "as", "was", "meant", "mean", "hold",
                  "one", "nope", "nah", "oops", "hang"})
CONNECT = frozenset({"to", "is", "as", "be", "should", "into", "=", "for"})
ROLES = {  # preposition -> fragments a slot-name token must start with for that role
    "to": ("dest", "to", "arriv", "target"), "into": ("dest", "arriv"), "towards": ("dest",),
    "from": ("orig", "from", "source", "depart", "start"),
    "on": ("date", "day"), "in": ("city", "locat", "place", "where"), "at": ("time", "hour", "locat"),
    "for": ("passenger", "people", "guest", "count", "quantity", "seat", "ticket", "person", "adult"),
}
NUMBERS = {w: i for i, w in enumerate(("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
                                       "ten", "eleven", "twelve"))}
PENDING_CONFIRM = ("planner_clarify", "confirm")
LEAD = frozenset({"ok", "okay", "yes", "yeah", "yep", "sure", "right", "alright", "oh", "well", "so", "hmm", "um", "uh"})
QUESTION_OPENERS = frozenset({"is", "has", "have", "did", "are", "was"})


def _tokens(text: str) -> list[tuple[str, str]]:
    return [(m.group(0), m.group(0).lower()) for m in _TOKEN.finditer(text)][:MAX_TOKENS]


def _has_seq(low: list[str], seq: tuple[str, ...], start_only: bool = False) -> bool:
    n = len(seq)
    rng = range(1) if start_only else range(len(low) - n + 1)
    return any(tuple(low[i:i + n]) == seq for i in rng if i + n <= len(low))


@functools.lru_cache(maxsize=512)
def _validator(schema_json: str) -> Any:
    schema = json.loads(schema_json)
    return jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)(schema)


def _valid(schema: dict, value: Any) -> bool:
    return _validator(json.dumps(schema, sort_keys=True)).is_valid(value)


def _name_tokens(slot: str) -> list[str]:
    return [t for t in slot.lower().split("_") if t]


def _role_fits(prep: str, slot: str) -> bool:
    return any(tok.startswith(frag) for frag in ROLES.get(prep, ()) for tok in _name_tokens(slot))


def _number(low: list[str]) -> int | None:
    for w in low:
        if w.isdigit():
            return int(w)
        if w in NUMBERS:
            return NUMBERS[w]
    return None


def _enum_match(schema: dict, low: list[str]) -> Any:
    for value in schema.get("enum", []):
        v = str(value).lower()
        for w in low:
            if w == v or (len(v) >= 3 and w.startswith(v)) or (len(w) >= 3 and v.startswith(w)):
                return value
    return None


def _kind(schema: dict) -> str:
    if "enum" in schema:
        return "enum"
    t = schema.get("type")
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    return "string"


def _span(toks: list[tuple[str, str]], start: int, used: set[int]) -> list[int]:
    """Up to 3 content tokens starting at `start`, stopping at stop words or consumed tokens."""
    out: list[int] = []
    for j in range(start, min(len(toks), start + 4)):
        if j in used or toks[j][1] in STOP:
            if out:
                break
            continue
        out.append(j)
        if len(out) == 3:
            break
    return out


class _Recogniser:
    def __init__(self, ctx: UnderstandContext):
        self.ctx = ctx
        self.slots = {s.name: s for s in ctx.slots}
        self.cues: list[str] = []
        self._surface_only = False  # while scanning past utterances: attribute only, no validation/aliases
        self._aliases: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------ canonical values

    def aliases(self, slot: SlotInfo) -> dict[str, Any]:
        """Surface -> canonical value, taught by the user earlier this session: an utterance attributed a
        surface form to this slot and the planner then wrote the slot canonically based on that turn."""
        if slot.name in self._aliases:
            return self._aliases[slot.name]
        texts = dict(self.ctx.utterances)
        out: dict[str, Any] = {}
        for value, writer_seq, source in slot.history:
            if source != "PLANNER" or value is None or writer_seq not in texts:
                continue
            for s_name, surface in self.surface_mentions(texts[writer_seq]):
                if s_name == slot.name:
                    out[surface.lower()] = value
        self._aliases[slot.name] = out
        return out

    def canon(self, slot: SlotInfo, toks: list[tuple[str, str]], idx: list[int]) -> tuple[str, Any]:
        """-> ("ok", value) | ("unresolved", None) | ("nomatch", None)."""
        low = [toks[i][1] for i in idx]
        kind = _kind(slot.schema)
        if kind == "enum":
            v = _enum_match(slot.schema, low)
            return ("ok", v) if v is not None else ("nomatch", None)
        if kind == "number":
            n = _number(low)
            return ("ok", n) if n is not None and _valid(slot.schema, n) else ("nomatch", None)
        if kind == "boolean":
            return ("nomatch", None)
        surface = " ".join(toks[i][0] for i in idx)
        if not surface:
            return ("nomatch", None)
        if self._surface_only:
            return ("ok", surface)
        if not slot.schema or _valid(slot.schema, surface):
            return ("ok", surface)
        alias = self.aliases(slot).get(surface.lower())
        if alias is not None:
            return ("ok", alias)
        return ("unresolved", None)

    # ------------------------------------------------------------ attribution passes

    def named(self, toks, used) -> dict:
        low = [t[1] for t in toks]
        claims = {}
        for slot in self.slots.values():
            name = _name_tokens(slot.name)
            for i in range(len(low) - len(name) + 1):
                if [w.rstrip("s") for w in low[i:i + len(name)]] != [w.rstrip("s") for w in name]:
                    continue
                j = i + len(name)
                while j < len(low) and j < i + len(name) + 3 and low[j] not in CONNECT and low[j] in STOP:
                    j += 1
                if j < len(low) and low[j] in CONNECT:
                    j += 1
                idx = _span(toks, j, used)
                if not idx:
                    continue
                status, value = self.canon(slot, toks, idx)
                if status != "nomatch":
                    claims[slot.name] = (status, value, idx)
                    used.update(range(i, idx[-1] + 1))
                    self.cues.append(f"named:{slot.name}")
                    break
        return claims

    def role(self, toks, used) -> dict:
        claims = {}
        for i, (_, w) in enumerate(toks):
            if w not in ROLES or i in used:
                continue
            idx = _span(toks, i + 1, used)
            if not idx:
                continue
            fits = [s for s in self.slots.values() if s.name not in claims and _role_fits(w, s.name)
                    and self.canon(s, toks, idx)[0] != "nomatch"]
            if len(fits) == 1:
                status, value = self.canon(fits[0], toks, idx)
                claims[fits[0].name] = (status, value, idx)
                used.update([i, *idx])
                self.cues.append(f"role:{w}->{fits[0].name}")
            elif len(fits) > 1:
                self.cues.append(f"ambiguous_role:{w}:{'|'.join(sorted(s.name for s in fits))}")
        return claims

    def typed(self, toks, used, taken: set[str]) -> dict:
        claims = {}
        free = [i for i in range(len(toks)) if i not in used]
        for kind in ("enum", "number"):
            slots = [s for s in self.slots.values() if s.name not in taken and _kind(s.schema) == kind]
            for i in reversed(free):  # self-repair: the LAST value stated for a slot wins ("Friday... make it Sunday")
                if i in used:
                    continue
                fits = [s for s in slots if s.name not in claims and self.canon(s, toks, [i])[0] == "ok"]
                if len(fits) == 1:
                    claims[fits[0].name] = ("ok", self.canon(fits[0], toks, [i])[1], [i])
                    used.add(i)
                    self.cues.append(f"typed:{fits[0].name}")
                elif len(fits) > 1:
                    self.cues.append(f"ambiguous_value:{'|'.join(sorted(s.name for s in fits))}")
        return claims

    def bare(self, toks, used, taken: set[str], extra_text: str) -> dict:
        slot_words = {w.rstrip("s") for s in self.slots for w in _name_tokens(s)}
        idx = [i for i in range(len(toks)) if i not in used and toks[i][1] not in STOP
               and toks[i][1] not in MARKER_WORDS and toks[i][1] not in FILLERS and toks[i][1] not in ACK
               and toks[i][1].rstrip("s") not in slot_words]  # a slot's NAME is a mention, never a value
        if len(idx) != 1:  # a bare value is weak evidence: only a single token ("no, Mumbai"); else abstain
            if idx:
                self.cues.append("bare_too_long")
            return {}
        if idx[0] == 0 or not toks[idx[0]][0][:1].isupper():  # must look like a named value, not a stray word
            self.cues.append("bare_not_a_name")
            return {}
        strings = [s for s in self.slots.values() if s.name not in taken and _kind(s.schema) == "string"
                   and self.canon(s, toks, idx)[0] != "nomatch"]
        if not strings:
            return {}
        if len(strings) > 1:
            recent = self.most_recent(strings, extra_text)
            if recent is None:
                self.cues.append(f"ambiguous_bare:{'|'.join(sorted(s.name for s in strings))}")
                return {}
            strings = [recent]
            self.cues.append(f"recency:{recent.name}")
        status, value = self.canon(strings[0], toks, idx)
        used.update(idx)
        self.cues.append(f"bare:{strings[0].name}")
        return {strings[0].name: (status, value, idx)}

    # ------------------------------------------------------------ mentions and recency

    def surface_mentions(self, text: str) -> list[tuple[str, str]]:
        """(slot, surface) attributed by name or role in `text`, in order of appearance (no side effects)."""
        toks = _tokens(text)
        saved, self._surface_only = list(self.cues), True
        used: set[int] = set()
        try:
            claims = {**self.named(toks, used), **self.role(toks, used)}
        finally:
            self.cues, self._surface_only = saved, False
        order = sorted(claims.items(), key=lambda kv: kv[1][2][0])
        return [(name, " ".join(toks[i][0] for i in idx)) for name, (_, _, idx) in order]

    def most_recent(self, candidates: list[SlotInfo], extra_text: str) -> SlotInfo | None:
        names = {s.name for s in candidates}
        last = None
        for _, text in [*self.ctx.utterances, (None, extra_text)]:
            for name, _ in self.surface_mentions(text):
                if name in names:
                    last = name
        return self.slots.get(last) if last else None

    def unclaimed(self, toks, claims: dict) -> list[str]:
        used = {i for _, _, idx in claims.values() for i in idx}
        slot_words = {w.rstrip("s") for s in self.slots for w in _name_tokens(s)}
        return [w for i, (_, w) in enumerate(toks) if i not in used and w not in STOP and w not in FILLERS
                and w not in ACK and w not in MARKER_WORDS and w.rstrip("s") not in slot_words]

    # ------------------------------------------------------------ top level

    def run(self, text: str) -> Understanding:
        toks = _tokens(text)
        low = [w for _, w in toks]
        core = [w for w in low if w not in FILLERS]
        if not core:
            return Understanding(TurnClass.BACKCHANNEL, cues=("empty",))
        if any(_has_seq(core, p) for p in SWITCH):
            return Understanding(TurnClass.GOAL_SWITCH, cues=("goal_switch",))
        lead = list(core)
        while lead and lead[0] in LEAD:
            lead = lead[1:]
        marker = bool(lead) and (lead[0] in MARKER_WORDS or any(_has_seq(lead, p, start_only=True) for p in MARKER_PAIRS)
                                 or "instead" in core)
        if marker:
            self.cues.append(f"marker:{lead[0] if lead[0] in MARKER_WORDS else ' '.join(lead[:2])}")
        used: set[int] = set()
        claims = {**self.named(toks, used)}
        claims.update({k: v for k, v in self.role(toks, used).items() if k not in claims})
        claims.update({k: v for k, v in self.typed(toks, used, set(claims)).items() if k not in claims})
        if marker and not claims:  # bare values are only a fallback for an otherwise empty correction
            claims.update({k: v for k, v in self.bare(toks, used, set(claims), self.ctx.turn_text).items()
                           if k not in claims})
        is_status = any(_has_seq(low, p) for p in STATUS) or (
            bool(low) and low[0] in QUESTION_OPENERS and "yet" in low)  # "is it booked yet?", "has it finished yet?"
        if is_status and not claims:
            return Understanding(TurnClass.STATUS_QUERY, cues=(*self.cues, "status"))
        if not marker and not claims and all(w in ACK for w in core):
            asked = [p for p in self.ctx.pending if p[0] in PENDING_CONFIRM and p[2]]
            if asked and set(core) & AFFIRM:
                return Understanding(TurnClass.ANSWER, confirm=True, cues=("affirm_open_confirmation",))
            return Understanding(TurnClass.BACKCHANNEL, cues=("acknowledgement",))
        writes: dict[str, Any] = {}
        changed_filled = False
        for name, (status, value, _) in claims.items():
            current = self.slots[name].value
            if status == "ok":
                if value != current:
                    writes[name] = value
                    changed_filled = changed_filled or current is not None
            elif current is not None:  # attributed, but the value cannot be made schema-valid: retract
                writes[name] = None
                changed_filled = True
                self.cues.append(f"retract:{name}")
        attributed = tuple(sorted(claims))
        asked_slots = {s for p in self.ctx.pending if p[2] for s in p[1]}
        if marker:
            cls = TurnClass.CORRECTION
        elif claims and set(claims) & asked_slots:  # answering what was asked, even if it changes the value
            cls = TurnClass.ANSWER
        elif changed_filled and len(self.unclaimed(toks, claims)) >= 2:
            # no marker, and much the value does not explain ("ticket for my cracked screen on Monday"): likely a
            # new request whose value belongs to another goal. Never write the active goal; the planner decides.
            self.cues.append("unclaimed_content")
            return Understanding(TurnClass.REQUEST, {}, False, (), tuple(self.cues))
        elif changed_filled:
            cls = TurnClass.CORRECTION
        else:
            cls = TurnClass.REQUEST
        return Understanding(cls, writes, False, attributed, tuple(self.cues))


def recognize(text: str, payload: dict, ctx: UnderstandContext | None = None) -> Understanding:
    """The Phase 4 fast-understanding entry point. An explicit internal test annotation wins (simulator only;
    the external wire format cannot carry one)."""
    if payload.get("t0"):
        return annotated(text, payload, ctx)
    return _Recogniser(ctx or EMPTY_CONTEXT).run(text)
