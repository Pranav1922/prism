"""Implementation A as a black-box PRISM-LOCAL/0 agent on stdin/stdout (virtual-time lockstep).

    python -m agent.adapter.stdio [--fixtures PATH] [--journal PATH]

For each input line: fire this agent's internal deliveries (timers, worker results) due strictly before the
message's time, process the message, write the resulting output lines, then one `agent.ready` line with
`next_wakeup`. A `clock.tick` fires internal deliveries due at or before its time (the tie rule: harness
events at time t are processed before the agent's own timers at t).

Until real understanding and planning exist (Phases 3-4), the planner, fast-understanding annotations and
perception are scripted from an AGENT-SIDE fixtures file; nothing implementation-specific travels on the wire.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from pathlib import Path

from agent.adapter.egress import Egress, EgressError, encode
from agent.adapter.ingress import Ingress, Rejected, Tick
from agent.clock import FakeClock, Scheduler
from agent.journal import Journal
from agent.kernel import Config, Kernel
from agent.model import Action, Event
from agent.planner import ScriptedPerception, ScriptedPlanner
from agent.runtime import Runtime
from agent.understand import Understanding, annotated

DEFAULT_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "scripted.json"


def table_understanding(table: dict):
    """Scripted fast understanding keyed by utterance text (Phase 1 stand-in; replaced in Phase 3)."""
    def understand(text: str, payload: dict) -> Understanding:
        note = table.get(text)
        return annotated(text, {"t0": note} if note is not None else {})
    return understand


class LocalAgent:
    def __init__(self, fixtures: dict, config: Config | None = None):
        self.clock = FakeClock()
        self.sched = Scheduler(self.clock)
        self.kernel = Kernel(config, understand=table_understanding(fixtures.get("understanding", {})))
        digest = hashlib.sha256(json.dumps(fixtures, sort_keys=True).encode()).hexdigest()
        self.journal = Journal(header={"config": dataclasses.asdict(self.kernel.config), "mode": "sim-lockstep",
                                       "backends": {"planner": "scripted", "perception": "scripted"},
                                       "fixtures_sha256": digest})
        self.runtime = Runtime(self.kernel, self.journal, self._on_action, self._on_effect)
        self.ingress, self.egress = Ingress("harness"), Egress()
        self.planner = ScriptedPlanner(fixtures.get("planner", {}), fixtures.get("planner_latency", 0.3))
        self.perception = ScriptedPerception(fixtures.get("perception", {}).get("frames", {}),
                                             fixtures.get("perception", {}).get("transcripts", {}),
                                             fixtures.get("perception_latency", 1.5))
        self._out: list[dict] = []
        self._n_ctl = 0

    # ------------------------------------------------------------ one input line -> output lines

    def handle(self, line: str) -> list[str]:
        self._out = []
        parsed = self.ingress.parse(line)
        if isinstance(parsed, Rejected):
            self.journal.add({"type": "ingress_reject", "ref": parsed.ref, "reason": parsed.reason})
            self._control("protocol.error", {"ref": parsed.ref, "reason": parsed.reason})
        elif isinstance(parsed, Tick):
            self._advance(parsed.t, inclusive=True)
        else:
            self._advance(parsed.t, inclusive=False)
            self._submit(parsed)
        self._control("agent.ready", {"next_wakeup": self.sched.peek()})
        return [encode(m) for m in self._out]

    def _advance(self, t: float, inclusive: bool) -> None:
        while (due := self.sched.peek()) is not None and (due < t or (inclusive and due <= t)):
            event = self.sched.pop()
            assert event is not None
            self._submit(event)
        if t > self.clock.t:
            self.clock.advance_to(t)

    def _submit(self, event: Event) -> None:
        sequenced = self.runtime.submit(event)
        if sequenced is not None:
            self.egress.note(sequenced)
            self.runtime.run_until_idle()

    def _control(self, typ: str, data: dict) -> None:
        self._n_ctl += 1
        self._out.append(Egress.control(typ, f"x{self._n_ctl}", self.clock.t, data))

    # ------------------------------------------------------------ runtime callbacks

    def _on_action(self, action: Action) -> None:
        try:
            self._out.append(self.egress.to_wire(action))
        except EgressError as exc:  # never observed; if it happens the action is dropped and reported
            self.journal.add({"type": "egress_error", "action_id": action.action_id, "error": str(exc)})
            self._control("protocol.error", {"ref": action.action_id, "reason": "invalid_action"})

    def _on_effect(self, effect: dict) -> None:
        kind, now = effect["effect"], self.clock.t
        if kind == "reason":
            t, event = self.planner.respond(effect, now)
            self.sched.at(t, event)
        elif kind == "perceive":
            t, event = self.perception.respond(effect, now)
            self.sched.at(t, event)
        elif kind == "arm":
            self.sched.arm(effect["timer_id"], effect["due_t"], effect["purpose"], effect["ref"])
        elif kind == "disarm":
            self.sched.disarm(effect["timer_id"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fixtures", default=str(DEFAULT_FIXTURES))
    ap.add_argument("--journal", default=None, help="write the kernel journal here on exit")
    args = ap.parse_args(argv)
    agent = LocalAgent(json.loads(Path(args.fixtures).read_text()))
    for line in sys.stdin:
        if not line.strip():
            continue
        for out in agent.handle(line):
            sys.stdout.write(out + "\n")
        sys.stdout.flush()
    if args.journal:
        agent.journal.write(args.journal)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
