"""Append-only journal and deterministic replay (F9, INV-23).

Record types (one JSON object per line):
  header  code/config constants
  in      a sequenced inbox event, in full (worker outputs included) -> the replay input
  step    rules fired, state changes, revisions, desired keys per plan_rev
  out     an emitted action (with caused_by and rule)
  fx      an effect request (planner, perception, timer, cancel) -> not needed for replay
  dup     an event dropped by the inbox as a duplicate

Replay feeds the `in` records, in seq order, into a fresh kernel and requires identical step/out/fx records.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent.model import Event, Kind, canonical_json, to_jsonable

JOURNAL_VERSION = 1


class Journal:
    def __init__(self, header: dict | None = None):
        self.records: list[dict] = [{"type": "header", "version": JOURNAL_VERSION, **(header or {})}]

    def add(self, record: dict) -> None:
        self.records.append(json.loads(canonical_json(record)))

    def of_type(self, *types: str) -> list[dict]:
        return [r for r in self.records if r["type"] in types]

    def dumps(self) -> str:
        return "".join(canonical_json(r) + "\n" for r in self.records)

    def write(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.dumps())

    @classmethod
    def loads(cls, text: str) -> Journal:
        j = cls.__new__(cls)
        j.records = [json.loads(line) for line in text.splitlines() if line.strip()]
        return j


def event_record(event: Event) -> dict:
    return {"type": "in", "seq": event.seq, "event": to_jsonable(event)}


def event_from_record(record: dict) -> Event:
    e = record["event"]
    return Event(Kind(e["kind"]), e["t"], e["payload"], e["eid"], e["seq"])


@dataclass
class ReplayReport:
    identical: bool
    steps: int
    first_divergence: tuple[Any, Any] | None = None


COMPARED = ("step", "out", "fx")


def replay(journal: Journal, kernel_factory: Callable[[dict], Any]) -> ReplayReport:
    """Re-run the recorded inbox through a fresh kernel; compare decisions record by record."""
    from agent.runtime import record_step  # local import: runtime depends on journal

    header = journal.records[0]
    kernel = kernel_factory(header)
    fresh = Journal(header={k: v for k, v in header.items() if k not in ("type", "version")})
    steps = 0
    for rec in journal.of_type("in"):
        event = event_from_record(rec)
        fresh.add(event_record(event))
        record_step(fresh, event, kernel.step(event))
        steps += 1
    original = [r for r in journal.records if r["type"] in COMPARED]
    produced = [r for r in fresh.records if r["type"] in COMPARED]
    for a, b in zip(original, produced, strict=False):  # length mismatch is reported just below
        if a != b:
            return ReplayReport(False, steps, (a, b))
    if len(original) != len(produced):
        return ReplayReport(False, steps, (len(original), len(produced)))
    return ReplayReport(True, steps)
