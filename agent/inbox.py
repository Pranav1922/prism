"""The single ordered inbox (F2, PHASE0_PREFLIGHT §8.2).

Every accepted event gets exactly one seq, in arrival order; seq is the only total order.
Duplicates are dropped by harness event id only, never by content (a user may legitimately repeat "yes").
Worker results (proposals, evidence, timers, tool results) enter through the same put().
"""

from __future__ import annotations

import dataclasses
from collections import deque

from agent.model import Event, freeze


class Inbox:
    def __init__(self) -> None:
        self._queue: deque[Event] = deque()
        self._seq = 0
        self._seen: set[str] = set()
        self.dropped: list[Event] = []

    def put(self, event: Event) -> Event | None:
        """Returns the sequenced event, or None if it was a duplicate."""
        if event.eid is not None:
            if event.eid in self._seen:
                self.dropped.append(event)
                return None
            self._seen.add(event.eid)
        self._seq += 1
        sequenced = dataclasses.replace(
            event, seq=self._seq, eid=event.eid or f"e{self._seq}", payload=freeze(event.payload)
        )
        self._queue.append(sequenced)
        return sequenced

    def get(self) -> Event | None:
        return self._queue.popleft() if self._queue else None

    def __len__(self) -> int:
        return len(self._queue)
