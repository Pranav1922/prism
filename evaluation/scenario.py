"""Scenario files: implementation-agnostic inputs, tool-world behaviour and externally observable expectations.

A scenario never contains agent internals (no slot annotations, no planner scripts, no internal rule names).
See docs/PHASE3_PROTOCOL_ADAPTER.md for the format.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema

HERE = Path(__file__).resolve().parent
SCENARIOS = HERE / "scenarios"

_MATCH = {"type": "object", "required": ["tool"], "properties": {"tool": {"type": "string"}, "args": {"type": "object"}}}
_BEHAVIOR = {
    "type": "object", "additionalProperties": False,
    "properties": {"latency": {"type": ["number", "null"], "minimum": 0}, "at": {"type": "number", "minimum": 0},
                   "status": {"enum": ["ok", "error", "cancelled"]}, "executed": {"type": ["boolean", "null"]},
                   "gen": {"type": "string"}, "data": {}, "duplicate": {"type": "boolean"},
                   "followup": {"type": "object"}},
}
SCENARIO_SCHEMA = {
    "type": "object", "required": ["id", "description", "manifest", "inputs", "expect"], "additionalProperties": False,
    "properties": {
        "id": {"type": "string", "pattern": "^[A-Za-z0-9_]+$"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "manifest": {"oneOf": [{"type": "array"}, {"type": "object", "required": ["use"]}]},
        "world": {"type": "object", "additionalProperties": {
            "type": "object", "additionalProperties": False,
            "properties": {"behaviors": {"type": "array", "items": _BEHAVIOR}, "honors_cancel": {"type": "boolean"},
                           "cancel_latency": {"type": "number", "minimum": 0}, "idempotent": {"type": "boolean"}}}},
        "inputs": {"type": "array", "items": {"type": "object", "required": ["t"], "properties": {
            "t": {"type": "number", "minimum": 0}, "id": {"type": "string"}, "type": {"type": "string"},
            "data": {"type": "object"}, "raw": {"type": "string"}, "rank": {"type": "integer"}}}},
        "horizon": {"type": "number", "exclusiveMinimum": 0},
        "expect": {"type": "object", "additionalProperties": False, "properties": {
            "final": {"type": "object"},
            "calls": {"type": "array", "items": _MATCH},
            "cancels": {"type": "array", "items": {**_MATCH, "required": ["tool", "after"]}},
            "no_cancels": {"type": "boolean"},
            "no_calls_after": {"type": "array", "items": {**_MATCH, "required": ["tool", "after"]}},
            "not_grounded_on": {"type": "array", "items": _MATCH},
            "side_effects": {"type": "object"},
            "clarify": {"type": "object"},
            "final_forbidden": {"type": "array", "items": {"type": "object"}},
            "protocol_errors": {"type": "integer", "minimum": 0},
            "same_idempotency_key": {"type": "array", "items": {"type": "string"}},
            "answer_turns": {"type": "array", "items": {"type": "string"}},
        }},
    },
}
_VALIDATOR = jsonschema.Draft202012Validator(SCENARIO_SCHEMA)


def _manifest(spec: list | dict) -> list[dict]:
    if isinstance(spec, list):
        return spec
    tools = json.loads((SCENARIOS / "manifests" / f"{spec['use']}.json").read_text())
    tools = copy.deepcopy(tools)
    for tool in tools:
        tool.update(spec.get("overrides", {}).get(tool.get("name"), {}))
    return tools + list(spec.get("extra", []))


def load(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text())
    errors = sorted(_VALIDATOR.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        raise ValueError(f"{path}: {errors[0].message} at {list(errors[0].path)}")
    data["manifest"] = _manifest(data["manifest"])
    data["_path"] = str(path)
    return data


def discover(selector: str = "all") -> list[Path]:
    """'all', a suite directory name, a scenario id, or a path."""
    p = Path(selector)
    if p.suffix == ".json" and p.exists():
        return [p]
    files = sorted(f for f in SCENARIOS.rglob("*.json") if f.parent.name != "manifests")
    if selector == "all":
        return files
    by_suite = [f for f in files if f.parent.name == selector]
    return by_suite or [f for f in files if f.stem == selector]
