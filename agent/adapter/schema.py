"""PRISM-LOCAL/0: the documented LOCAL wire protocol of this project.

This is NOT the Samsung evaluation protocol (which is unavailable, UNK-1). It is our own contract so the
agent can be driven end-to-end as a black box, and so two independent implementations can be evaluated
identically. Only modules in agent/adapter/ may know this format.

Transport: JSON lines. Every message has an envelope {v, id, t, type, data}; outputs add `cause`.
Time: virtual seconds. Lockstep: after processing each input message the agent emits its outputs followed
by exactly one `agent.ready` carrying `next_wakeup` (the earliest virtual time it needs to be woken, or
null). The harness advances time only by message timestamps or `clock.tick`.

Run `python -m agent.adapter.schema` to print the JSON Schema document (protocol/prism_local_0.schema.json).
"""

from __future__ import annotations

import json
import sys

VERSION = "PRISM-LOCAL/0"

_ID = {"type": "string", "minLength": 1, "maxLength": 128}
_T = {"type": "number", "minimum": 0}
_EMPTY = {"type": "object", "additionalProperties": False}
_SNAPSHOT = {
    "type": "object", "required": ["intent", "slots"], "additionalProperties": False,
    "properties": {"intent": {"type": ["string", "null"]}, "slots": {"type": "object"}},
}

# ---------------------------------------------------------------- inputs: harness channel
HARNESS_INPUT = {
    "session.start": _EMPTY,
    "session.end": _EMPTY,
    "manifest": {"type": "object", "required": ["tools"], "additionalProperties": False,
                 "properties": {"tools": {"type": "array", "items": {"type": "object"}}}},
    "user.text": {"type": "object", "required": ["text"], "additionalProperties": False,
                  "properties": {"text": {"type": "string", "minLength": 1},
                                 # D17 (optional): the chunk came from streaming on-device recognition, not typing
                                 "source": {"enum": ["asr_stream"]}}},
    "user.turn_end": _EMPTY,
    "user.audio": {"type": "object", "required": ["ref"], "additionalProperties": False,
                   "properties": {"ref": _ID, "duration_s": {"type": "number", "minimum": 0}}},
    "user.frame": {"type": "object", "required": ["ref"], "additionalProperties": False, "properties": {"ref": _ID}},
    "user.interrupt": _EMPTY,
    "tool.result": {"type": "object", "required": ["call_id", "status"], "additionalProperties": False,
                    "properties": {"call_id": _ID, "status": {"enum": ["ok", "error", "cancelled"]},
                                   "data": {}, "executed": {"type": ["boolean", "null"]},
                                   "message": {"type": "string"}}},
    "clock.tick": _EMPTY,
}

# ---------------------------------------------------------------- inputs: worker channel (agent-internal)
# Out-of-process workers (e.g. the Phase 6 perception process) return results through the same validated
# ingress. The harness channel rejects these types, so the environment cannot forge worker results.
WORKER_INPUT = {
    "worker.proposal": {"type": "object", "required": ["req_id", "based_on_seq", "proposal"], "additionalProperties": False,
                        "properties": {"req_id": _ID, "based_on_seq": {"type": "integer", "minimum": 0},
                                       "proposal": {"type": "object"}}},
    "worker.proposal_failed": {"type": "object", "required": ["req_id", "based_on_seq", "reason"],
                               "additionalProperties": False,
                               "properties": {"req_id": _ID, "based_on_seq": {"type": "integer", "minimum": 0},
                                              "reason": {"type": "string"}}},
    "worker.evidence": {"type": "object", "required": ["req_id", "frame_id", "claims"], "additionalProperties": False,
                        "properties": {"req_id": _ID, "frame_id": _ID, "claims": {
                            "type": "object", "additionalProperties": {
                                "type": "array", "prefixItems": [{}, {"type": "number", "minimum": 0, "maximum": 1}],
                                "minItems": 2, "maxItems": 2}}}},
    "worker.transcript": {"type": "object", "required": ["req_id", "source_id", "text"], "additionalProperties": False,
                          "properties": {"req_id": _ID, "source_id": _ID, "text": {"type": "string", "minLength": 1}}},
    "worker.perception_failed": {"type": "object", "required": ["req_id", "reason"], "additionalProperties": False,
                                 "properties": {"req_id": _ID, "reason": {"type": "string"}}},
}

INPUT_ENVELOPE = {
    "type": "object", "required": ["v", "id", "t", "type", "data"], "additionalProperties": False,
    "properties": {"v": {"const": VERSION}, "id": _ID, "t": _T, "type": {"type": "string"}, "data": {"type": "object"}},
}

# ---------------------------------------------------------------- outputs
OUTPUT = {
    "speech": {"type": "object", "required": ["text", "act"], "additionalProperties": False,
               "properties": {"text": {"type": "string", "minLength": 1},
                              "act": {"enum": ["ack", "narration", "filler", "answer", "confirm"]}}},
    "clarify": {"type": "object", "required": ["text"], "additionalProperties": False,
                "properties": {"text": {"type": "string", "minLength": 1},
                               "slots": {"type": "array", "items": {"type": "string"}}}},
    "tool.call": {"type": "object", "required": ["call_id", "tool", "args"], "additionalProperties": False,
                  "properties": {"call_id": _ID, "tool": {"type": "string", "minLength": 1}, "args": {"type": "object"},
                                 "idempotency_key": {"type": "string", "minLength": 1}}},
    "tool.cancel": {"type": "object", "required": ["call_id"], "additionalProperties": False,
                    "properties": {"call_id": _ID}},
    "response.final": {"type": "object", "required": ["text", "snapshot"], "additionalProperties": False,
                       "properties": {"text": {"type": "string", "minLength": 1}, "snapshot": _SNAPSHOT,
                                      "complete": {"type": "boolean"},  # false: truthful partial report
                                      "grounded_on": {"type": "array", "items": _ID}}},
    "state.snapshot": {"type": "object", "required": ["snapshot"], "additionalProperties": False,
                       "properties": {"snapshot": _SNAPSHOT}},
    "protocol.error": {"type": "object", "required": ["reason"], "additionalProperties": False,
                       "properties": {"ref": {"type": ["string", "null"]}, "reason": {"type": "string"}}},
    "agent.ready": {"type": "object", "required": ["next_wakeup"], "additionalProperties": False,
                    "properties": {"next_wakeup": {"type": ["number", "null"]}}},
}

OUTPUT_ENVELOPE = {
    "type": "object", "required": ["v", "id", "t", "type", "data", "cause"], "additionalProperties": False,
    "properties": {"v": {"const": VERSION}, "id": _ID, "t": _T, "type": {"enum": sorted(OUTPUT)},
                   "data": {"type": "object"}, "cause": {"type": "array", "items": _ID}},
}


def schema_document() -> dict:
    """The complete contract as one JSON Schema document (shared with any harness)."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "prism_local_0",
        "title": "PRISM-LOCAL/0 (local project protocol, not the Samsung evaluation protocol)",
        "version": VERSION,
        "input_envelope": INPUT_ENVELOPE,
        "harness_input": HARNESS_INPUT,
        "worker_input": WORKER_INPUT,
        "output_envelope": OUTPUT_ENVELOPE,
        "output": OUTPUT,
    }


if __name__ == "__main__":
    json.dump(schema_document(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
