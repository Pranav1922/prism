"""Black-box harness: drives an agent through PRISM-LOCAL/0 in virtual time and records an external trace.

It sees only what crosses the wire (inputs sent, outputs received), what the tool world did, and timestamps.
It never inspects the agent's internal state.

Co-simulation loop: the next thing to happen is the earliest of (a) a scheduled harness message (scenario
input or tool-world result) and (b) the agent's own `next_wakeup`. At equal time, harness messages go first;
the agent is then woken with `clock.tick`.
"""

from __future__ import annotations

import heapq
import itertools
import json
from pathlib import Path

import jsonschema

from evaluation.agents import SubprocessAgent
from evaluation.world import World

VERSION = "PRISM-LOCAL/0"
SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "protocol" / "prism_local_0.schema.json").read_text())
_OUT_ENV = jsonschema.Draft202012Validator(SCHEMA["output_envelope"])
_OUT = {k: jsonschema.Draft202012Validator(v) for k, v in SCHEMA["output"].items()}


def output_problem(raw: str) -> tuple[dict | None, str | None]:
    """Parse and validate one agent output line against the contract."""
    try:
        msg = json.loads(raw)
    except ValueError:
        return None, "malformed_json"
    for err in _OUT_ENV.iter_errors(msg):
        return (msg if isinstance(msg, dict) else None), f"invalid_envelope: {err.message}"
    for err in _OUT[msg["type"]].iter_errors(msg["data"]):
        return msg, f"invalid_payload: {err.message}"
    return msg, None


def wire(mid: str, t: float, typ: str, data: dict | None = None) -> str:
    return json.dumps({"v": VERSION, "id": mid, "t": t, "type": typ, "data": data or {}}, sort_keys=True)


def run(scenario: dict, agent_cmd: list[str], reply_timeout_s: float = 10.0) -> dict:
    world = World(scenario.get("world", {}), scenario["manifest"])
    records: list[dict] = []
    violations: list[dict] = []
    heap: list = []
    order = itertools.count()

    def schedule(t: float, rank: int, item: tuple) -> None:
        heapq.heappush(heap, (t, rank, next(order), item))

    horizon = float(scenario.get("horizon", 60.0))
    schedule(0.0, 0, ("send", wire("s0", 0.0, "session.start")))
    schedule(0.0, 0, ("send", wire("m0", 0.0, "manifest", {"tools": scenario["manifest"]})))
    for i, inp in enumerate(scenario["inputs"], start=1):
        line = inp["raw"] if "raw" in inp else wire(inp.get("id", f"i{i}"), inp["t"], inp["type"], inp.get("data"))
        schedule(float(inp["t"]), int(inp.get("rank", 0)), ("send", line))
    schedule(horizon, 9, ("send", wire("s-end", horizon, "session.end")))

    agent = SubprocessAgent(agent_cmd, scenario["id"], reply_timeout_s)  # wall-clock guard only; scores use virtual time
    wake: float | None = None
    n_tick = 0
    try:
        while heap or wake is not None:
            if wake is not None and (not heap or wake < heap[0][0]) and wake <= horizon:
                now, line = wake, None
                n_tick += 1
                line = wire(f"tick{n_tick}", now, "clock.tick")
            elif heap:
                now, _, _, item = heapq.heappop(heap)
                if item[0] == "deliver":
                    data = world.deliver(item[1], now)
                    if data is None:
                        continue
                    line = wire(world._next_id(), now, "tool.result", data)
                else:
                    line = item[1]
            else:
                break
            records.append({"t": now, "dir": "in", "raw": line})
            outs, wake = agent.send(line)
            for raw in outs:
                msg, problem = output_problem(raw)
                records.append({"t": now, "dir": "out", "raw": raw, "msg": msg})
                if problem:
                    violations.append({"t": now, "kind": "malformed_output", "detail": problem, "raw": raw[:300]})
                    continue
                assert msg is not None
                for when, delivery in world.on_output(msg, now):
                    schedule(when, 0, ("deliver", delivery))
            if wake is not None and wake > horizon:
                wake = None
    finally:
        agent.close()
    return {"scenario": scenario["id"], "protocol": VERSION, "horizon": horizon, "records": records,
            "world": world.ledger(), "violations": violations}
