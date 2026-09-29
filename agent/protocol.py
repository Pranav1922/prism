"""Protocol egress validation (F8, INV-22).

The harness wire format is unknown (UNK-1). Until the kit arrives, every action is validated against
this *internal* action schema at egress; the kit's wire schema will be added here, in the adapter,
without touching the kernel.
"""

from __future__ import annotations

import jsonschema

from agent.model import Action, ActionKind, to_jsonable

_SNAPSHOT = {
    "type": "object", "required": ["intent", "slots"], "additionalProperties": False,
    "properties": {"intent": {"type": ["string", "null"]}, "slots": {"type": "object"}},
}
_IDS = {"type": "array", "items": {"type": "string"}}
_PAYLOAD = {
    ActionKind.TOOL_CALL: {
        "type": "object", "required": ["call_id", "tool", "args", "uses"],
        "properties": {"call_id": {"type": "string", "pattern": "^c[0-9]+$"}, "tool": {"type": "string"},
                       "args": {"type": "object"}, "uses": _IDS, "idempotency_key": {"type": "string"}},
        "additionalProperties": False,
    },
    ActionKind.CANCEL: {
        "type": "object", "required": ["call_id", "reason"], "additionalProperties": False,
        "properties": {"call_id": {"type": "string"}, "reason": {"type": "string"}},
    },
    ActionKind.SPEAK: {
        "type": "object", "required": ["text", "act", "grounded_on"], "additionalProperties": False,
        "properties": {"text": {"type": "string", "minLength": 1},
                       "act": {"enum": ["ack", "narration", "filler", "confirm", "answer"]}, "grounded_on": _IDS},
    },
    ActionKind.CLARIFY: {
        "type": "object", "required": ["text", "slots", "reason"], "additionalProperties": False,
        "properties": {"text": {"type": "string", "minLength": 1}, "slots": {"type": "array"}, "reason": {"type": "string"}},
    },
    ActionKind.FINAL: {
        "type": "object", "required": ["text", "act", "grounded_on", "ops", "snapshot"], "additionalProperties": False,
        "properties": {"text": {"type": "string", "minLength": 1}, "act": {"enum": ["answer", "narration"]},
                       "grounded_on": _IDS, "ops": {"type": "array"}, "ledger_calls": _IDS, "snapshot": _SNAPSHOT},
    },
    ActionKind.SNAPSHOT: {
        "type": "object", "required": ["snapshot"], "additionalProperties": False,
        "properties": {"snapshot": _SNAPSHOT},
    },
}
_ACTION = {
    "type": "object", "required": ["action_id", "kind", "seq", "rule", "caused_by", "payload"],
    "properties": {"action_id": {"type": "string", "pattern": "^a[0-9]+$"}, "kind": {"enum": [k.value for k in ActionKind]},
                   "seq": {"type": "integer", "minimum": 1}, "rule": {"type": "string"},
                   "caused_by": {"type": "array", "items": {"type": "integer"}, "minItems": 1}},
}
_VALIDATORS = {k: jsonschema.Draft202012Validator(s) for k, s in _PAYLOAD.items()}
_ACTION_VALIDATOR = jsonschema.Draft202012Validator(_ACTION)


def validate_action(action: Action) -> None:
    """Raises jsonschema.ValidationError if the action is not protocol-valid."""
    data = to_jsonable(action)
    _ACTION_VALIDATOR.validate(data)
    _VALIDATORS[action.kind].validate(data["payload"])
