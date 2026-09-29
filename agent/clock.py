"""Deterministic time (PHASE0_PREFLIGHT §4.4).

The kernel never reads a clock. Time exists only in event timestamps. This module provides the test and
simulation side: a FakeClock and a discrete-event Scheduler that fires timers in harness time.
The real ClockSource (event-driven / tick / wall-mapped) waits for the evaluation kit (gate G3).
"""

from __future__ import annotations

import heapq
import itertools
import time

from agent.model import Event, Kind


class WallClock:
    """Live clock: seconds since construction, on the monotonic clock. Stands in for the harness clock
    until the evaluation kit defines one (G3); the kernel still only sees event timestamps."""

    def __init__(self) -> None:
        self._t0 = time.monotonic()

    def now(self) -> float:
        return time.monotonic() - self._t0


class FakeClock:
    def __init__(self, t: float = 0.0):
        self.t = t

    def now(self) -> float:
        return self.t

    def advance_to(self, t: float) -> None:
        if t < self.t:
            raise ValueError(f"time went backwards: {t} < {self.t}")
        self.t = t


class Scheduler:
    """Future deliveries ordered by (t, class, insertion order).

    Tie rule (fixed, independent of clock source): at equal t, ordinary events are delivered before
    timers, so a result arriving exactly at its timeout instant counts as on time.
    """

    _EVENT, _TIMER = 0, 1

    def __init__(self, clock: FakeClock):
        self.clock = clock
        self._heap: list = []
        self._order = itertools.count()
        self._live: dict[str, float] = {}  # timer_id -> due_t of its latest arm

    def at(self, t: float, event: Event) -> None:
        rank = self._TIMER if event.kind is Kind.TIMER else self._EVENT
        heapq.heappush(self._heap, (t, rank, next(self._order), event))

    def arm(self, timer_id: str, due_t: float, purpose: str, ref: str | None) -> None:
        self._live[timer_id] = due_t  # re-arming replaces the earlier instance
        payload = {"timer_id": timer_id, "purpose": purpose, "due_t": due_t, "ref": ref}
        self.at(due_t, Event(Kind.TIMER, due_t, payload))

    def disarm(self, timer_id: str) -> None:
        self._live.pop(timer_id, None)

    def peek(self) -> float | None:
        """Time of the next live delivery (dead timer instances are discarded), or None."""
        while self._heap:
            _, _, _, event = self._heap[0]
            if event.kind is Kind.TIMER and self._live.get(event.payload["timer_id"]) != event.payload["due_t"]:
                heapq.heappop(self._heap)
                continue
            return self._heap[0][0]
        return None

    def pop(self) -> Event | None:
        while self._heap:
            t, _, _, event = heapq.heappop(self._heap)
            if event.kind is Kind.TIMER:
                tid = event.payload["timer_id"]
                if self._live.get(tid) != event.payload["due_t"]:
                    continue  # disarmed or replaced; the kernel would ignore it anyway
                del self._live[tid]
            self.clock.advance_to(t)
            return event
        return None

    def __bool__(self) -> bool:
        return bool(self._heap)
