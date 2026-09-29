"""Runtime: inbox -> kernel -> egress (F1–F2). Owns no session state.

Workers (planner, perception, harness tools, timers) never touch the kernel. They produce events that
re-enter through submit(). Phase 1 drives this synchronously from the scenario simulator; the asyncio
event loop and the harness adapter wrap the same object once the evaluation kit exists.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import jsonschema

from agent.inbox import Inbox
from agent.journal import Journal, event_record
from agent.kernel import Kernel, StepResult
from agent.model import Action, Event, to_jsonable
from agent.protocol import validate_action


def record_step(journal: Journal, event: Event, res: StepResult) -> None:
    journal.add({"type": "step", "seq": res.seq, "rev_before": res.rev_before, "rev_after": res.rev_after,
                 "rules": res.rules, "changes": [[t, k, v] for t, k, v in res.changes], "desired": res.desired})
    for action in res.actions:
        journal.add({"type": "out", "seq": res.seq, "action": to_jsonable(action)})
    for effect in res.effects:
        journal.add({"type": "fx", "seq": res.seq, "effect": effect})


class Runtime:
    def __init__(self, kernel: Kernel, journal: Journal,
                 on_action: Callable[[Action], None] = lambda a: None,
                 on_effect: Callable[[dict], None] = lambda e: None,
                 observer: Callable[[Event, StepResult, float], None] | None = None):
        self.kernel, self.journal = kernel, journal
        self.inbox = Inbox()
        self.on_action, self.on_effect = on_action, on_effect
        self.observer = observer  # (event, result, step wall seconds): metrics only, never decisions
        self.egress_errors: list[tuple[Action, str]] = []

    def submit(self, event: Event) -> Event | None:
        sequenced = self.inbox.put(event)
        if sequenced is None:
            self.journal.add({"type": "dup", "event": to_jsonable(event)})
        else:
            self.journal.add(event_record(sequenced))
        return sequenced

    def run_until_idle(self) -> None:
        while (event := self.inbox.get()) is not None:
            started = time.perf_counter()
            res = self.kernel.step(event)
            elapsed = time.perf_counter() - started
            record_step(self.journal, event, res)
            if self.observer is not None:
                self.observer(event, res, elapsed)
            for action in res.actions:
                try:
                    validate_action(action)  # egress (INV-22)
                except jsonschema.ValidationError as exc:
                    self.egress_errors.append((action, exc.message))
                    self.journal.add({"type": "egress_error", "seq": res.seq, "action_id": action.action_id,
                                      "error": exc.message})
                    continue
                self.on_action(action)
            for effect in res.effects:
                self.on_effect(effect)
