"""Tool registry (F6): normalised manifest -> ToolSpec, validation, classification, canonical arguments.

Input is the *normalised* manifest the protocol adapter will produce; the wire format is unknown (UNK-1):
  {"name": str, "description": str, "parameters": <JSON Schema object>,
   "effect": "read_only" | "state_changing" (optional), "cancellable": bool (optional), "timeout_s": number (optional)}
"""

from __future__ import annotations

import functools
import json
from dataclasses import dataclass
from typing import Any

import jsonschema

from agent.model import Effect, canonical_json

READ_ONLY_VERBS = ("get", "search", "list", "find", "lookup", "check", "status", "fetch", "query")


class ArgError(ValueError):
    pass


@functools.lru_cache(maxsize=256)
def _validator(schema_json: str) -> jsonschema.protocols.Validator:
    schema = json.loads(schema_json)
    cls = jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
    return cls(schema)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    params_json: str  # canonical JSON Schema
    effect: Effect
    effect_reason: str
    cancellable: bool | None = None
    timeout_s: float | None = None

    def canonicalize(self, args: dict) -> dict:
        """Schema-validated canonical arguments; strings trimmed. Raises ArgError."""
        clean = {k: (v.strip() if isinstance(v, str) else v) for k, v in args.items()}
        errors = sorted(_validator(self.params_json).iter_errors(clean), key=lambda e: list(e.path))
        if errors:
            raise ArgError(f"{self.name}: {errors[0].message}")
        return json.loads(canonical_json(clean))


def classify(entry: dict) -> tuple[Effect, str]:
    declared = entry.get("effect")
    if declared in [e.value for e in Effect]:
        return Effect(declared), "manifest"
    first = entry["name"].replace("-", "_").split("_")[0].lower()
    if first in READ_ONLY_VERBS:
        return Effect.READ_ONLY, f"name_verb:{first}"
    words = str(entry.get("description", "")).lower().split()
    if words and words[0].strip(".,:") in READ_ONLY_VERBS:
        return Effect.READ_ONLY, f"description_verb:{words[0]}"
    return Effect.STATE_CHANGING, "default"


@dataclass(frozen=True)
class Registry:
    tools: tuple[ToolSpec, ...] = ()
    quarantined: tuple[tuple[str, str], ...] = ()

    def get(self, name: str) -> ToolSpec | None:
        return next((t for t in self.tools if t.name == name), None)

    @staticmethod
    def from_manifest(entries: Any) -> Registry:
        tools: list[ToolSpec] = []
        bad: list[tuple[str, str]] = []
        for i, entry in enumerate(entries if isinstance(entries, list) else []):
            name = entry.get("name") if isinstance(entry, dict) else None
            label = name if isinstance(name, str) and name else f"#{i}"
            try:
                if not isinstance(name, str) or not name:
                    raise ValueError("missing name")
                if any(t.name == name for t in tools):
                    raise ValueError("duplicate name")
                params = entry.get("parameters", {"type": "object"})
                if not isinstance(params, dict) or params.get("type", "object") != "object":
                    raise ValueError("parameters must be an object schema")
                jsonschema.validators.validator_for(params, default=jsonschema.Draft202012Validator).check_schema(params)
                timeout = entry.get("timeout_s")
                if timeout is not None and (not isinstance(timeout, (int, float)) or timeout <= 0):
                    raise ValueError("bad timeout_s")
                cancellable = entry.get("cancellable")
                if cancellable is not None and not isinstance(cancellable, bool):
                    raise ValueError("bad cancellable")
                effect, reason = classify(entry)
                tools.append(
                    ToolSpec(name, str(entry.get("description", "")), canonical_json(params), effect, reason,
                             cancellable, float(timeout) if timeout is not None else None)
                )
            except (ValueError, jsonschema.SchemaError) as exc:
                bad.append((label, str(exc).splitlines()[0]))
        return Registry(tuple(tools), tuple(bad))
