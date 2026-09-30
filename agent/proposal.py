"""Planner proposals: the internal shape, and the pure checks the kernel applies before admitting one.

A proposal is DATA from an untrusted proposer (a model, or a script standing in for one). The kernel admits it
only after `check()` passes, and still applies its own rules (last-writer-wins, structure staleness, commit
barrier, provenance). Nothing here reads state or has side effects, so the kernel may call it inside decide().

Internal proposal payload (produced by agent/reasoner or by the scripted planner):
  {"intent": <tool-name-like str> | null, "new_goal": bool,
   "slot_writes": {slot: value},
   "graph": [{"node_id": str, "tool": str, "instance_tag": str,
              "args": {param: {"$slot": name} | {"$node": node_id, "path": [...]} | {"$const": v} | <literal>}}],
   "clarify": {"text": str, "slots": [slot, ...]}}
"""

from __future__ import annotations

import json
import re
from typing import Any

from agent.model import Effect, canonical_json
from agent.registry import Registry

MAX_NODES = 8
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
KEYS = {"intent", "new_goal", "slot_writes", "graph", "clarify"}

# Operation verbs a user must have used for a state-changing tool to be authorised (D13). The tool's own verb
# (first word of its name) always counts; these are its synonyms.
VERB_SYNONYMS: dict[str, frozenset[str]] = {
    "book": frozenset({"book", "reserve"}),
    "create": frozenset({"create", "file", "raise", "log", "submit"}),
    "cancel": frozenset({"cancel"}),
    "send": frozenset({"send", "email"}),
    "buy": frozenset({"buy", "purchase", "order"}),
    "order": frozenset({"order", "buy", "purchase"}),
    "pay": frozenset({"pay"}),
    "delete": frozenset({"delete", "remove"}),
    "update": frozenset({"update", "change", "modify", "edit"}),
}


def check(payload: Any, registry: Registry) -> list[str]:
    """Structural admission check. Returns errors (empty = admissible). Values are NOT checked here: argument
    values are validated against the tool schema when the graph is resolved, which yields a clarification."""
    if not isinstance(payload, dict):
        return ["proposal is not an object"]
    errors = [f"unknown field {k}" for k in sorted(set(payload) - KEYS - {"req_id", "based_on_seq"})]
    intent = payload.get("intent")
    if intent is not None and (not isinstance(intent, str) or not _NAME.match(intent)):
        errors.append("intent must be a name")
    if not isinstance(payload.get("new_goal", False), bool):
        errors.append("new_goal must be a boolean")
    writes = payload.get("slot_writes", {})
    if not isinstance(writes, dict):
        errors.append("slot_writes must be an object")
    else:
        for name, value in writes.items():
            if not _NAME.match(str(name)):
                errors.append(f"bad slot name {name!r}")
            try:
                canonical_json(value)
            except (TypeError, ValueError):
                errors.append(f"slot {name} value is not JSON")
    clarify = payload.get("clarify")
    if clarify is not None and not (isinstance(clarify, dict) and isinstance(clarify.get("text"), str)
                                    and clarify["text"].strip() and isinstance(clarify.get("slots", []), list)
                                    and all(isinstance(s, str) for s in clarify.get("slots", []))):
        errors.append("clarify must be {text, slots}")
    graph = payload.get("graph", [])
    if not isinstance(graph, list):
        return errors + ["graph must be a list"]
    if graph and not isinstance(intent, str):
        errors.append("a graph needs an intent")
    if len(graph) > MAX_NODES:
        errors.append(f"graph has more than {MAX_NODES} nodes")
    seen: list[str] = []
    state_changing: set[str] = set()
    for i, node in enumerate(graph):
        where = f"node {i}"
        if not isinstance(node, dict) or not isinstance(node.get("tool"), str):
            errors.append(f"{where}: needs a tool")
            continue
        nid = str(node.get("node_id", f"n{i + 1}"))
        spec = registry.get(node["tool"])
        if spec is None:
            errors.append(f"{where}: unknown tool {node['tool']}")
            continue
        if nid in seen:
            errors.append(f"{where}: duplicate node id {nid}")
        args = node.get("args", {})
        if not isinstance(args, dict):
            errors.append(f"{where}: args must be an object")
            continue
        props = json.loads(spec.params_json).get("properties")
        for param, b in args.items():
            if isinstance(props, dict) and param not in props:
                errors.append(f"{where}: {spec.name} has no parameter {param}")
            if isinstance(b, dict) and "$node" in b:
                if b["$node"] not in seen:  # forward or self reference: a cycle or an order the kernel can't resolve
                    errors.append(f"{where}: {param} depends on {b['$node']}, which is not an earlier node")
                if not isinstance(b.get("path", []), list):
                    errors.append(f"{where}: path must be a list")
            elif isinstance(b, dict) and "$slot" in b and not _NAME.match(str(b["$slot"])):
                errors.append(f"{where}: bad slot name {b['$slot']!r}")
        if spec.effect is Effect.STATE_CHANGING:
            sig = canonical_json([spec.name, args])
            if sig in state_changing:
                errors.append(f"{where}: duplicate state-changing work {spec.name}")
            state_changing.add(sig)
        seen.append(nid)
    return errors


def order_nodes(graph: list[dict]) -> list[dict] | None:
    """Topological order by $node dependencies (stable). None if there is a cycle or a dangling reference."""
    ids = [str(n.get("node_id", f"n{i + 1}")) for i, n in enumerate(graph)]
    deps = {nid: {b["$node"] for b in (n.get("args") or {}).values() if isinstance(b, dict) and "$node" in b}
            for nid, n in zip(ids, graph, strict=True)}
    if any(d not in ids for ds in deps.values() for d in ds):
        return None
    out: list[dict] = []
    done: set[str] = set()
    while len(out) < len(graph):
        ready = [i for i, nid in enumerate(ids) if nid not in done and deps[nid] <= done]
        if not ready:
            return None
        done.add(ids[ready[0]])
        out.append(graph[ready[0]])
    return out


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def operation_verbs(tool: str, description: str = "") -> frozenset[str]:
    verb = re.split(r"[_\-\s]", tool.lower())[0]
    first = (description.lower().split() or [""])[0].strip(".,:")
    return VERB_SYNONYMS.get(verb, frozenset({verb})) | VERB_SYNONYMS.get(first, frozenset())


def authorised(tool: str, description: str, utterances: list[str]) -> bool:
    """D13: a state-changing operation is authorised only if a USER utterance of the goal names the operation."""
    verbs = operation_verbs(tool, description)
    return any(verbs & _words(u) for u in utterances)


NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
                "ten": 10, "eleven": 11, "twelve": 12, "single": 1, "couple": 2, "both": 2}


def grounded(value: Any, text: str) -> bool:
    """Did the user actually say this value? (D13: planner values reaching a state-changing call.) Strings match as a
    whole token or as a word prefix ("Fri" / "Friday"); numbers as digits or number words."""
    t = text.casefold()
    words = re.findall(r"[a-z0-9]+", t)
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return str(value) in words or any(NUMBER_WORDS.get(w) == value for w in words)
    if isinstance(value, str) and value.strip():
        v = value.strip().casefold()
        if re.search(r"(?<![a-z0-9])" + re.escape(v) + r"(?![a-z0-9])", t):
            return True
        return len(v) >= 3 and v.isalpha() and any(w.startswith(v) for w in words)
    return False


def leaves(data: Any) -> set[str]:
    """Scalar string leaves of tool-result / evidence data, case-folded (for taint checks)."""
    out: set[str] = set()
    stack = [data]
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
        elif isinstance(x, str) and len(x.strip()) >= 2:
            out.add(x.strip().casefold())
    return out


def tainted(value: Any, non_user: set[str], user_text: str) -> bool:
    """A string value that appears (as a whole token) in tool-result/evidence content but was never said by the user. Such a value
    may reach a state-changing call only through a {$node} binding to a DESIRED result, never as a literal."""
    if not isinstance(value, str):
        return False  # ponytail: strings only; numbers collide with ordinary result fields (counts, prices)
    v = value.strip().casefold()
    if len(v) < 2:
        return False
    bounded = re.compile(r"(?<![a-z0-9])" + re.escape(v) + r"(?![a-z0-9])")
    return any(bounded.search(leaf) for leaf in non_user) and not bounded.search(user_text.casefold())
