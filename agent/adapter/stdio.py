"""Implementation A as a black-box PRISM-LOCAL/0 agent on stdin/stdout (virtual-time lockstep).

    python -m agent.adapter.stdio [--fixtures PATH] [--journal PATH] [--planner SPEC] [--planner-latency L]

SPEC: auto (default: PRISM_PLANNER if reachable, else scripted) | scripted | ollama:<model> | openai:<model> |
replay:<journal>. L: measured | <seconds>. --perception local (default; real ASR/OCR for media files) | scripted.
PRISM_JOURNAL_DIR=<dir> writes the journal to <dir>/<PRISM_SCENARIO>.jsonl on exit (model A/B evaluation).

For each input line: fire this agent's internal deliveries (timers, worker results) due strictly before the
message's time, process the message, write the resulting output lines, then one `agent.ready` line with
`next_wakeup`. A `clock.tick` fires internal deliveries due at or before its time (the tie rule: harness
events at time t are processed before the agent's own timers at t).

The scripted planner and perception read an AGENT-SIDE fixtures file; nothing implementation-specific travels on
the wire. A model planner (Phase 5) replaces the scripted planner behind the same `reason` effect.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from agent.adapter.egress import Egress, EgressError, encode
from agent.adapter.ingress import Ingress, Rejected, Tick
from agent.clock import FakeClock, Scheduler
from agent.journal import Journal
from agent.kernel import Config, Kernel
from agent.model import Action, Event
from agent.perception import LocalPerception
from agent.planner import ScriptedPerception, ScriptedPlanner
from agent.reasoner.planner import FallbackPlanner, ModelPlanner, ReplayPlanner, model_available, view_digest
from agent.runtime import Runtime
from agent.understand import Understanding, annotated
from agent.understand_rules import recognize

DEFAULT_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "scripted.json"


def table_understanding(table: dict):
    """Scripted fast understanding keyed by utterance text: the Phase 1-3 stand-in, kept only for comparison
    (`--understanding scripted`). The default is the deterministic recogniser (Phase 4)."""
    def understand(text: str, payload: dict, ctx: object = None) -> Understanding:
        note = table.get(text)
        return annotated(text, {"t0": note} if note is not None else {})
    return understand


def make_planner(spec: str, fixtures: dict, latency: str = "measured", timeout_s: float = 10.0) -> Any:
    """scripted | auto | ollama:<m> | openai:<m> | replay:<journal>. `auto` = PRISM_PLANNER (e.g. ollama:qwen2.5:7b) as
    PRIMARY with the scripted planner as SAFE FALLBACK if the model is reachable, else the scripted planner alone."""
    scripted = ScriptedPlanner(fixtures.get("planner", {}), fixtures.get("planner_latency", 0.3))
    if spec == "scripted":
        return scripted
    if spec == "auto":
        wanted = os.environ.get("PRISM_PLANNER", "")
        if not wanted or wanted == "scripted" or not model_available(wanted):
            return scripted
        return FallbackPlanner(make_planner(wanted, fixtures, latency, timeout_s), scripted)
    if spec.startswith(("replay:", "replay-lenient:")):
        return ReplayPlanner(spec.split(":", 1)[1], strict=spec.startswith("replay:"))
    from agent.reasoner.backends import OllamaBackend, OpenAICompatibleBackend
    kind, _, model = spec.partition(":")
    backend = {"ollama": OllamaBackend, "openai": OpenAICompatibleBackend}[kind](model)
    return ModelPlanner(backend, timeout_s, None if latency == "measured" else float(latency))  # type: ignore[arg-type]


class LocalAgent:
    def __init__(self, fixtures: dict, config: Config | None = None, understanding: str = "rules",
                 planner: str = "auto", planner_latency: str = "measured", planner_timeout_s: float = 10.0,
                 perception: str = "local", perception_latency: str = "measured"):
        self.clock = FakeClock()
        self.sched = Scheduler(self.clock)
        understand = recognize if understanding == "rules" else table_understanding(fixtures.get("understanding", {}))
        self.kernel = Kernel(config, understand=understand)
        digest = hashlib.sha256(json.dumps(fixtures, sort_keys=True).encode()).hexdigest()
        self.planner = make_planner(planner, fixtures, planner_latency, planner_timeout_s)
        described = getattr(self.planner, "describe", lambda: {"backend": "scripted"})()
        self.journal = Journal(header={"config": dataclasses.asdict(self.kernel.config), "mode": "sim-lockstep",
                                       "planner_mode": "replay" if planner.startswith("replay") else "live",
                                       "backends": {"understanding": understanding, "planner": described,
                                                    "perception": perception},
                                       "fixtures_sha256": digest})
        self.runtime = Runtime(self.kernel, self.journal, self._on_action, self._on_effect)
        self.ingress, self.egress = Ingress("harness"), Egress()
        scripted_perception = ScriptedPerception(fixtures.get("perception", {}).get("frames", {}),
                                                 fixtures.get("perception", {}).get("transcripts", {}),
                                                 fixtures.get("perception_latency", 1.5))
        self.perception: Any = scripted_perception if perception == "scripted" else LocalPerception(
            scripted_perception, None if perception_latency == "measured" else float(perception_latency))
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
            detail = self.planner.records[-1] if getattr(self.planner, "records", None) else {}
            self.journal.add({**detail, "type": "fx_io", "req_id": effect["req_id"], "view_digest": view_digest(effect["view"]),
                              "t_request": now, "virtual_latency": round(t - now, 6), "kind": event.kind.value,
                              "payload": event.payload})
            self.sched.at(t, event)
        elif kind == "perceive":
            t, event = self.perception.respond(effect, now)
            detail = self.perception.records[-1] if getattr(self.perception, "records", None) else {}
            self.journal.add({**detail, "type": "perception_io", "req_id": effect["req_id"], "t_request": now,
                              "virtual_latency": round(t - now, 6), "kind": event.kind.value})
            self.sched.at(t, event)
        elif kind == "arm":
            self.sched.arm(effect["timer_id"], effect["due_t"], effect["purpose"], effect["ref"])
        elif kind == "disarm":
            self.sched.disarm(effect["timer_id"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fixtures", default=str(DEFAULT_FIXTURES))
    ap.add_argument("--journal", default=None, help="write the kernel journal here on exit")
    ap.add_argument("--understanding", choices=("rules", "scripted"), default="rules",
                    help="rules: deterministic recogniser (default); scripted: the old per-utterance table")
    ap.add_argument("--planner", default="auto",
                    help="auto (PRISM_PLANNER if reachable, else scripted) | scripted | ollama:<model> | openai:<model> | replay:<journal>")
    ap.add_argument("--perception", default="local", choices=("local", "scripted"),
                    help="local: on-device ASR + tesseract OCR for media files, scripted fallback otherwise")
    ap.add_argument("--perception-latency", default="measured", help="measured | <virtual seconds>")
    ap.add_argument("--planner-latency", default="measured", help="measured | <virtual seconds> (model planners)")
    ap.add_argument("--planner-timeout", type=float, default=10.0)
    args = ap.parse_args(argv)
    agent = LocalAgent(json.loads(Path(args.fixtures).read_text()), understanding=args.understanding,
                       planner=args.planner, planner_latency=args.planner_latency, planner_timeout_s=args.planner_timeout,
                       perception=args.perception, perception_latency=args.perception_latency)
    for line in sys.stdin:
        if not line.strip():
            continue
        for out in agent.handle(line):
            sys.stdout.write(out + "\n")
        sys.stdout.flush()
    journal_dir = os.environ.get("PRISM_JOURNAL_DIR")
    if args.journal or journal_dir:
        agent.journal.write(args.journal or str(Path(journal_dir or ".") / f"{os.environ.get('PRISM_SCENARIO', 'session')}.jsonl"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
