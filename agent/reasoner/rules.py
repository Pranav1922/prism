"""Deterministic rule planner: the fallback when no known example matches (no model, no network).

It reads the SAME planner view a model would (turn text, current goal and graph, slots, admitted results, the live
tool manifest) and proposes the SAME internal proposal, which then passes agent/proposal.check and the kernel's
admission rules (last-writer-wins, D13 authorisation/grounding/taint, D14 ordering) exactly like any other planner.

What it understands, all derived from the tool manifest where possible:
  * which tool(s) the user asks for: tool-name words and their common synonyms ("find/show/need … flights",
    "book/reserve", "weather/temperature/forecast"); several tools in one request become parallel nodes;
  * slot values by parameter schema: weekday enums; origin/destination airport codes from "from X", "to X", "X to Y"
    (city names via a small airport table, or literal IATA codes); flight numbers; passenger counts ("two people",
    "for 3 passengers", "the two of us"); free-text places ("weather in Pune");
  * dependent bookings: "book the first/second/last one" binds the flight to the current search result by position.

It never invents a value: whatever a required parameter still lacks becomes a clarification question.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from agent.model import Event, Kind
from agent.proposal import check
from agent.registry import Registry

# City -> IATA code: a deliberately small, explicit table (the scenarios' domain). Unknown cities are not guessed.
AIRPORTS = {
    "bangalore": "BLR", "bengaluru": "BLR", "delhi": "DEL", "new delhi": "DEL", "mumbai": "BOM", "bombay": "BOM",
    "goa": "GOI", "chennai": "MAA", "madras": "MAA", "kolkata": "CCU", "calcutta": "CCU", "hyderabad": "HYD",
    "pune": "PNQ", "ahmedabad": "AMD", "kochi": "COK", "cochin": "COK", "jaipur": "JAI", "lucknow": "LKO",
    "dubai": "DXB", "singapore": "SIN", "london": "LHR",
}
WEEKDAYS = {"monday": "Mon", "tuesday": "Tue", "wednesday": "Wed", "thursday": "Thu", "friday": "Fri",
            "saturday": "Sat", "sunday": "Sun", "mon": "Mon", "tue": "Tue", "tues": "Tue", "wed": "Wed", "thu": "Thu",
            "thur": "Thu", "thurs": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
           "a": 1, "single": 1, "couple": 2, "both": 2}
PEOPLE = {"person", "people", "passenger", "passengers", "adult", "adults", "traveller", "travellers", "traveler", "travelers", "seat", "seats"}
ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "last": -1}
# Tool-name words -> the words people use for them. The tool's own words always count.
SYNONYMS = {
    "search": {"search", "find", "show", "look", "looking", "need", "want", "get", "any", "check", "list"},
    "flights": {"flight", "flights", "fly", "flying", "plane", "planes"},
    "book": {"book", "reserve", "booking"},
    "weather": {"weather", "temperature", "forecast", "rain", "raining", "sunny", "hot", "cold"},
    "get": set(),
}
VERB_ONLY = {"search", "get", "find", "check", "list", "fetch", "lookup", "query", "create", "update", "send"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)?", text.lower())


def _content(tool: dict) -> set[str]:
    """A tool's content words with synonyms ("flight" ~ "flights"), for overlap between tools."""
    out: set[str] = set()
    for p in re.split(r"[_\-]", tool["name"].lower()):
        if p and p not in VERB_ONLY and p not in ("book", "reserve"):
            out |= SYNONYMS.get(p, set()) | {p} | ({p.rstrip("s")} if p.endswith("s") else {p + "s"})
    return out


def _tool_score(tool: dict, words: set[str]) -> int:
    """How many of the tool's CONTENT words (not generic verbs) the utterance mentions. State-changing tools also
    need their own verb (book/reserve): mentioning "flights" never selects booking."""
    parts = [p for p in re.split(r"[_\-]", tool["name"].lower()) if p]
    content = [p for p in parts if p not in VERB_ONLY]
    hits = sum(1 for p in content if (SYNONYMS.get(p, set()) | {p}) & words)
    if tool.get("effect") == "state_changing":
        verb = parts[0]
        if not ((SYNONYMS.get(verb, set()) | {verb}) & words):
            return 0
        hits += 1
    return hits


def _place(text: str, start: int) -> tuple[str | None, str | None]:
    """Airport code for the place named at `start` (1-2 word city names, or a literal IATA code)."""
    rest = text[start:].strip()
    m = re.match(r"([A-Za-z]+)(?:\s+([A-Za-z]+))?", rest)
    if not m:
        return None, None
    one, two = m.group(1), m.group(2)
    if two and f"{one} {two}".lower() in AIRPORTS:
        return AIRPORTS[f"{one} {two}".lower()], f"{one} {two}"
    if one.lower() in AIRPORTS:
        return AIRPORTS[one.lower()], one
    if re.fullmatch(r"[A-Z]{3}", one):
        return one, one
    return None, one


def _role(name: str) -> str | None:
    n = name.lower()
    if any(k in n for k in ("origin", "from", "source", "depart")):
        return "from"
    if any(k in n for k in ("dest", "arriv")) or n == "to":
        return "to"
    return None


def extract(text: str, schema: dict) -> dict[str, Any]:
    """Values for the parameters of one tool schema that the text states. Only schema-valid values."""
    props = schema.get("properties", {})
    words = _words(text)
    out: dict[str, Any] = {}
    places: dict[str, str] = {}
    # "from X", "to X"; and "X to Y" without "from"
    for hit in re.finditer(r"\b(from|to|into|towards)\s+", text, re.I):
        code, _ = _place(text, hit.end())
        if code:
            places.setdefault("from" if hit.group(1).lower() == "from" else "to", code)
    if "from" not in places:
        pair = re.search(r"\b([A-Za-z]+(?:\s[A-Za-z]+)?)\s+to\s+", text)
        if pair:
            for cand in (pair.group(1), pair.group(1).split()[-1]):
                code, _ = _place(cand, 0)
                if code and code != places.get("to"):
                    places["from"] = code
                    break
    for name, spec in props.items():
        kind = spec.get("type")
        enum = spec.get("enum")
        role = _role(name)
        if enum and set(enum) & set(WEEKDAYS.values()):
            day = next((WEEKDAYS[w] for w in words if w in WEEKDAYS), None)
            if day in enum:
                out[name] = day
        elif role and kind == "string" and spec.get("pattern") == "^[A-Z]{3}$":
            if role in places:
                out[name] = places[role]
        elif kind == "integer":
            n = _count(words)
            if n is not None and n >= spec.get("minimum", 0):
                out[name] = n
        elif kind == "string" and "id" in name.lower():
            fid = re.search(r"\b([0-9A-Z]{2}-\d{3,4})\b", text)
            if fid:
                out[name] = fid.group(1)
        elif kind == "string":  # a free-text place: "weather in Pune", "for Mumbai"
            where = re.search(r"\b(?:in|at|for)\s+([A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)?)", text)
            if where and where.group(1).lower() not in WEEKDAYS:
                out[name] = where.group(1)
    return out


def _count(words: list[str]) -> int | None:
    """A head count: "two people", "3 passengers", "the two of us", "for two". Never the pronoun in "the second one"."""
    for i, w in enumerate(words):
        n = int(w) if w.isdigit() else NUMBERS.get(w)
        if n is None:
            continue
        prev, nxt = (words[i - 1] if i else ""), words[i + 1:i + 3]
        if w == "one" and (prev in ORDINALS or prev in ("the", "this", "that", "which", "cheapest", "earliest")):
            continue  # "the first one", "that one": a pronoun, not a count
        if (nxt and nxt[0] in PEOPLE) or nxt[:2] == ["of", "us"] or (prev == "for" and w != "a"):
            return n
    return None


@dataclass
class RulePlanner:
    latency: float = 0.25
    records: list[dict] = field(default_factory=list)

    def plan(self, view: dict) -> tuple[dict | None, str]:
        text = view.get("turn_text", "")
        words = set(_words(text))
        tools = view.get("tools") or []
        goal = view.get("goal")
        slots = {n: s.get("value") for n, s in (view.get("slots") or {}).items()}
        scored = sorted(((i, t) for i, t in enumerate(tools) if _tool_score(t, words) > 0),
                        key=lambda it: (-_tool_score(it[1], words), it[0]))
        wanted = [t for _, t in scored]
        if any(t.get("effect") == "state_changing" for t in wanted):  # "book flight X" is not also a flight search
            acts = [t for t in wanted if t.get("effect") == "state_changing"]
            wanted = acts + [t for t in wanted if t not in acts and not (_content(t) & set().union(*map(_content, acts)))]
        writes: dict[str, Any] = {}
        graph: list[dict] = []
        if not wanted:  # no tool named: a continuation/correction of the current task
            if goal is None:
                return None, "no tool matches the request"
            tool = next((t for t in tools if t["name"] == goal["intent"]), None)
            params = {}
            for n in goal.get("graph", []):
                t = next((x for x in tools if x["name"] == n["tool"]), None)
                if t:
                    params.update(extract(text, t["parameters"]))
            writes = {k: v for k, v in params.items() if slots.get(k) != v}
            if not params:
                return None, "nothing in the request maps to the current task"
            # values equal to the current ones are already applied (the fast path wrote them): a no-op, not a failure
            proposal: dict[str, Any] = {"intent": goal["intent"], "new_goal": False, "slot_writes": writes}
            return self._finish(proposal, view, tool)
        primary = wanted[0]
        same_task = goal is not None and any(n["tool"] == primary["name"] for n in goal.get("graph", []))
        for t in wanted:
            vals = extract(text, t["parameters"])
            writes.update(vals)
            node_args: dict[str, Any] = {p: {"$slot": p} for p in t["parameters"].get("properties", {})}
            if t.get("effect") == "state_changing":
                dep = self._dependency(text, t, goal, view)
                if dep:
                    graph[:0] = [dep[0]] if dep[0] not in graph else []
                    node_args.update(dep[1])
                    writes = {k: v for k, v in writes.items() if k not in dep[1]}
            graph.append({"node_id": f"{t['name']}_{len(graph) + 1}", "tool": t["name"], "args": node_args})
        intent = primary["name"]
        if goal is not None and same_task and len(wanted) == 1 and primary.get("effect") != "state_changing":
            proposal = {"intent": goal["intent"], "new_goal": False, "slot_writes": {k: v for k, v in writes.items() if slots.get(k) != v}}
        else:
            intent = goal["intent"] if goal is not None and any(n["tool"] == goal["intent"] for n in graph) else intent
            proposal = {"intent": intent, "new_goal": goal is None or goal["intent"] != intent, "slot_writes": writes,
                        "graph": graph}
        return self._finish(proposal, view, primary)

    def _dependency(self, text: str, tool: dict, goal: dict | None, view: dict) -> tuple[dict, dict] | None:
        """"book the first one": bind an id parameter to the current search result, by position."""
        pos = next((ORDINALS[w] for w in _words(text) if w in ORDINALS), None)
        if pos is None or goal is None:
            return None
        for node in goal.get("graph", []):
            res = next((r for r in view.get("results", []) if r["node_id"] == node["node_id"] and r.get("data")), None)
            lists = [(k, v) for k, v in (res or {}).get("data", {}).items() if isinstance(v, list) and v and isinstance(v[0], dict)]
            if not lists:
                continue
            key, items = lists[0]
            id_field = next((k for k in items[0] if k.lower() == "id" or k.lower().endswith("_id")), None)
            param = next((p for p in tool["parameters"].get("properties", {}) if "id" in p.lower()), None)
            if id_field and param and -len(items) <= pos < len(items):
                return node, {param: {"$node": node["node_id"], "path": [key, pos, id_field]}}
        return None

    def _finish(self, proposal: dict, view: dict, tool: dict | None) -> tuple[dict | None, str]:
        known = {n: s.get("value") for n, s in (view.get("slots") or {}).items() if s.get("value") is not None}
        have = {**known, **{k: v for k, v in proposal.get("slot_writes", {}).items() if v is not None}}
        nodes = proposal.get("graph") or (view.get("goal") or {}).get("graph", [])
        missing: list[str] = []
        awaiting = any(e.get("awaiting") for e in view.get("evidence") or [])
        for n in nodes:
            spec = next((t for t in view.get("tools", []) if t["name"] == n["tool"]), None)
            for p in (spec or {}).get("parameters", {}).get("required", []):
                b = n["args"].get(p)
                if isinstance(b, dict) and "$slot" in b and b["$slot"] not in have and b["$slot"] not in missing:
                    missing.append(b["$slot"])
        if missing and not awaiting:
            proposal["clarify"] = {"text": "What " + " and ".join(m.replace("_", " ") for m in missing) + " should I use?",
                                   "slots": missing}
        errors = check(proposal, Registry.from_manifest(view.get("tools") or []))
        return (None, "; ".join(errors)) if errors else (proposal, "ok")

    def respond(self, request: dict, now: float) -> tuple[float, Event]:
        base = {"req_id": request["req_id"], "based_on_seq": request["based_on_seq"]}
        proposal, why = self.plan(request["view"])
        self.records.append({"backend": "rules", "outcome": why})
        t = now + self.latency
        if proposal is None:
            return t, Event(Kind.PROPOSAL_FAILED, t, {**base, "reason": "no_plan"})
        return t, Event(Kind.PROPOSAL, t, {**base, **json.loads(json.dumps(proposal))})


@dataclass
class DeterministicPlanner:
    """The default planner on this machine: known examples first (the validated behaviour, keyed by utterance and
    tolerant of recognition noise), then the rule planner for requests no example covers. Deterministic throughout."""

    known: Any  # agent.planner.ScriptedPlanner
    rules: RulePlanner
    records: list[dict] = field(default_factory=list)

    def respond(self, request: dict, now: float) -> tuple[float, Event]:
        key, _ = self.known.match(request["view"]["turn_text"])
        chosen = self.known if key is not None else self.rules
        t, event = chosen.respond(request, now)
        self.records.append(dict(chosen.records[-1]))
        return t, event

    def describe(self) -> dict:
        return {"backend": "deterministic", "stages": ["known examples", "rules"]}
