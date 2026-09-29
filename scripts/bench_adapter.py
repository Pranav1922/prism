"""Phase 3 benchmark: PRISM-LOCAL/0 adapter and black-box path latencies.

    python scripts/bench_adapter.py [sessions]

Wall-clock (dev machine, indicative only):
  ingress parse, egress serialise+validate, in-process agent.handle() per message,
  subprocess round trip for the correction (-> tool.cancel) and for the turn end (-> tool.call + speech).
Virtual time (from the full scenario suite, exact and deterministic):
  end of turn -> first substantive action, interruption -> cancel.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from agent.adapter.egress import Egress
from agent.adapter.ingress import Ingress
from agent.adapter.stdio import DEFAULT_FIXTURES, LocalAgent
from agent.model import Action, ActionKind, Event, Kind
from evaluation import harness, metrics
from evaluation.agents import SubprocessAgent, resolve
from evaluation.scenario import discover, load

W = harness.wire
FIND = "find flights from Bangalore to Delhi on Friday"


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def summary(xs: list[float]) -> dict:
    return {"p50": round(pct(xs, .5), 4), "p99": round(pct(xs, .99), 4), "max": round(max(xs), 4), "n": len(xs)}


def session_lines() -> list[tuple[str, str]]:
    manifest = json.loads((Path("evaluation/scenarios/manifests/flights.json")).read_text())
    return [("start", W("s0", 0.0, "session.start")), ("manifest", W("m0", 0.0, "manifest", {"tools": manifest})),
            ("ask", W("i1", 0.1, "user.text", {"text": FIND})), ("ask_end", W("i2", 0.5, "user.turn_end")),
            ("tick", W("k1", 0.75, "clock.tick")),  # planner result -> tool.call + ack
            ("fix", W("i3", 1.4, "user.text", {"text": "actually, to Mumbai"})),  # -> tool.cancel
            ("fix_end", W("i4", 1.6, "user.turn_end"))]  # -> tool.call + snapshot + ack


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    lines = session_lines()
    out: dict = {"label": "wall-clock on the dev machine (indicative); virtual metrics are exact"}

    samples = [line for _, line in lines if "manifest" not in line] * 500
    t_parse = []
    for i, line in enumerate(samples):
        ing = Ingress()
        t0 = time.perf_counter()
        ing.parse(line)
        t_parse.append((time.perf_counter() - t0) * 1000)
    out["ingress_parse_ms"] = summary(t_parse)

    eg = Egress()
    eg.note(Event(Kind.USER_TEXT, 1.4, {}, "i3", 6))
    acts = [Action("a1", ActionKind.CANCEL, 6, "r", (6,), {"call_id": "c1", "reason": "x"}),
            Action("a2", ActionKind.TOOL_CALL, 6, "r", (6,), {"call_id": "c2", "tool": "search_flights",
                                                            "args": {"destination": "BOM"}, "uses": []}),
            Action("a3", ActionKind.FINAL, 6, "r", (6,), {"text": "Done", "act": "answer", "grounded_on": ["c2"], "ops": [],
                                                        "snapshot": {"intent": "x", "slots": {"a": 1}}})] * 1000
    t_egress = []
    for a in acts:
        t0 = time.perf_counter()
        eg.to_wire(a)
        t_egress.append((time.perf_counter() - t0) * 1000)
    out["egress_serialise_validate_ms"] = summary(t_egress)

    fixtures = json.loads(DEFAULT_FIXTURES.read_text())
    per: dict[str, list[float]] = {k: [] for k, _ in lines}
    for _ in range(n):
        agent = LocalAgent(fixtures)
        for name, line in lines:
            t0 = time.perf_counter()
            agent.handle(line)
            per[name].append((time.perf_counter() - t0) * 1000)
    out["agent_handle_in_process_ms"] = {k: summary(v) for k, v in per.items()}

    rt: dict[str, list[float]] = {"fix->tool.cancel": [], "fix_end->tool.call+speech": []}
    for _ in range(max(20, n // 4)):
        sub = SubprocessAgent(resolve("impl_a"), "bench")
        try:
            for name, line in lines:
                t0 = time.perf_counter()
                outs, _ = sub.send(line)
                ms = (time.perf_counter() - t0) * 1000
                types = [json.loads(o)["type"] for o in outs]
                if name == "fix":
                    assert "tool.cancel" in types
                    rt["fix->tool.cancel"].append(ms)
                if name == "fix_end":
                    assert "tool.call" in types and "speech" in types
                    rt["fix_end->tool.call+speech"].append(ms)
        finally:
            sub.close()
    out["subprocess_round_trip_ms"] = {k: summary(v) for k, v in rt.items()}

    turn, cancel = [], []
    for path in discover("all"):
        s = load(path)
        r = metrics.evaluate(s, harness.run(s, resolve("impl_a")))
        turn += r["latency"]["turn_first_substantive_s"]
        cancel += r["latency"]["interrupt_to_cancel_s"]
    out["virtual_turn_end_to_first_substantive_s"] = summary(turn)
    out["virtual_interrupt_to_cancel_s"] = summary(cancel)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
