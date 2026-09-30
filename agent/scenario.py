"""Local deterministic scenario runner (internal; NOT the Samsung harness).

A discrete-event simulator: scripted user events, scripted tool behaviour (latency, outcome, whether a
cancel is honoured), the scripted planner and perception, and timers, all on a FakeClock. Same inputs and
seed -> the same journal, byte for byte.

    python -m agent.scenario            # list scenarios
    python -m agent.scenario B          # run one and print its timeline
"""

from __future__ import annotations

import dataclasses
import random
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent.clock import FakeClock, Scheduler
from agent.journal import Journal
from agent.kernel import Config, Kernel
from agent.model import Action, ActionKind, Event, Kind
from agent.planner import ScriptedPerception, ScriptedPlanner
from agent.runtime import Runtime


@dataclass
class Behavior:
    latency: float | None = 0.5  # None: the tool never answers
    outcome: str = "ok"  # ok | error | malformed
    data: Any = None  # value or callable(args) -> value
    executed: bool | None = None  # for errors: was the side effect executed?
    honors_cancel: bool = False
    cancel_latency: float = 0.05
    duplicate: bool = False  # deliver the same result twice


@dataclass
class Sim:
    manifest: list
    tools: dict[str, Any] = field(default_factory=dict)  # tool -> Behavior | [Behavior per attempt]
    planner: ScriptedPlanner = field(default_factory=ScriptedPlanner)
    perception: ScriptedPerception = field(default_factory=ScriptedPerception)
    config: Config = field(default_factory=Config)
    seed: int | None = None
    jitter: float = 0.0  # seeded extra latency in [0, jitter) for tools and the planner
    horizon: float = 60.0
    kernel_factory: Callable[[Config], Kernel] = Kernel

    def __post_init__(self) -> None:
        self.clock = FakeClock()
        self.scheduler = Scheduler(self.clock)
        self.kernel = self.kernel_factory(self.config)
        self.journal = Journal(header={"config": dataclasses.asdict(self.config)})
        self.runtime = Runtime(self.kernel, self.journal, self._on_action, self._on_effect)
        self.actions: list[Action] = []
        self._rng = random.Random(self.seed)
        self._attempts: dict[str, int] = {}
        self._behavior: dict[str, Behavior] = {}
        self._delivered: set[str] = set()
        self._suppressed: set[str] = set()

    def _lat(self, base: float) -> float:
        return base + (self._rng.random() * self.jitter if self.jitter else 0.0)

    def run(self, script: list[tuple[float, Event]], end_session: bool = True) -> Sim:
        self.scheduler.at(0.0, Event(Kind.SESSION_START, 0.0, {}))
        self.scheduler.at(0.0, Event(Kind.MANIFEST, 0.0, {"tools": self.manifest}))
        for t, scripted in script:
            self.scheduler.at(t, dataclasses.replace(scripted, t=t))
        if end_session:
            self.scheduler.at(self.horizon, Event(Kind.SESSION_END, self.horizon, {}))
        while (event := self.scheduler.pop()) is not None and self.clock.t <= self.horizon:
            if event.kind is Kind.TOOL_RESULT:
                cid = event.payload.get("call_id")
                if cid in self._suppressed and event.payload.get("outcome") != "cancelled_ack":
                    continue  # the harness honoured the cancel: the real result never comes
                self._delivered.add(cid)
            self.runtime.submit(event)
            self.runtime.run_until_idle()
        return self

    # ------------------------------------------------------------ the simulated world

    def _on_action(self, action: Action) -> None:
        self.actions.append(action)
        now, p = self.clock.t, action.payload
        if action.kind is ActionKind.TOOL_CALL:
            spec = self.tools.get(p["tool"], Behavior())
            i = self._attempts.get(p["tool"], 0)
            self._attempts[p["tool"]] = i + 1
            b = spec[min(i, len(spec) - 1)] if isinstance(spec, list) else spec
            self._behavior[p["call_id"]] = b
            if b.latency is not None:
                data = b.data(p["args"]) if callable(b.data) else b.data
                t = now + self._lat(b.latency)
                payload = {"call_id": p["call_id"], "outcome": b.outcome, "data": data, "executed": b.executed}
                for _ in range(2 if b.duplicate else 1):
                    self.scheduler.at(t, Event(Kind.TOOL_RESULT, t, payload))
        elif action.kind is ActionKind.CANCEL:
            b = self._behavior.get(p["call_id"])
            if b is not None and b.honors_cancel and p["call_id"] not in self._delivered:
                self._suppressed.add(p["call_id"])
                t = now + b.cancel_latency
                self.scheduler.at(t, Event(Kind.TOOL_RESULT, t, {"call_id": p["call_id"], "outcome": "cancelled_ack"}))

    def _on_effect(self, effect: dict) -> None:
        now, kind = self.clock.t, effect["effect"]
        if kind == "reason":
            t, event = self.planner.respond(effect, self._lat(now))
            self.scheduler.at(t, event)
        elif kind == "perceive":
            t, event = self.perception.respond(effect, now)
            self.scheduler.at(t, event)
        elif kind == "arm":
            self.scheduler.arm(effect["timer_id"], effect["due_t"], effect["purpose"], effect["ref"])
        elif kind == "disarm":
            self.scheduler.disarm(effect["timer_id"])
        # "cancel_effect": advisory; scripted workers ignore it, so late proposals still arrive (per-field LWW)

    # ------------------------------------------------------------ inspection helpers

    def kinds(self) -> list[str]:
        return [a.kind.value for a in self.actions]

    def of(self, kind: ActionKind) -> list[Action]:
        return [a for a in self.actions if a.kind is kind]

    def calls(self) -> dict:
        return dict(self.kernel.state.items("calls"))


# ---------------------------------------------------------------- script helpers


def say(text: str, cls: str | None = None, writes: dict | None = None, confirm: bool = False,
        eid: str | None = None) -> Event:
    note: dict = {}
    if cls:
        note["class"] = cls
    if writes:
        note["writes"] = writes
    if confirm:
        note["confirm"] = True
    return Event(Kind.USER_TEXT, 0.0, {"text": text, **({"t0": note} if note else {})}, eid)


def eot(eid: str | None = None) -> Event:
    return Event(Kind.END_OF_TURN, 0.0, {}, eid)


def interrupt() -> Event:
    return Event(Kind.INTERRUPT, 0.0, {})


def image(ref: str, eid: str) -> Event:
    return Event(Kind.MEDIA, 0.0, {"kind": "image", "ref": ref}, eid)


def result(call_id: str, outcome: str = "ok", data: Any = None, executed: bool | None = None) -> Event:
    return Event(Kind.TOOL_RESULT, 0.0, {"call_id": call_id, "outcome": outcome, "data": data, "executed": executed})


# ---------------------------------------------------------------- shared fixtures

S = {"type": "string", "minLength": 1}
MANIFEST: list[dict] = [
    {"name": "search_flights", "description": "Search flights",
     "parameters": {"type": "object", "properties": {"origin": S, "destination": S, "date": S},
                    "required": ["origin", "destination", "date"], "additionalProperties": False}, "timeout_s": 5},
    {"name": "book_flight", "description": "Book a flight", "effect": "state_changing",
     "parameters": {"type": "object", "properties": {"flight_id": S, "passengers": {"type": "integer", "minimum": 1}},
                    "required": ["flight_id", "passengers"], "additionalProperties": False}, "timeout_s": 5},
    {"name": "get_weather", "description": "Weather for a city",
     "parameters": {"type": "object", "properties": {"city": S}, "required": ["city"], "additionalProperties": False}},
]
SEARCH_GRAPH: list[dict] = [{"node_id": "n1", "tool": "search_flights",
                 "args": {"origin": {"$slot": "origin"}, "destination": {"$slot": "destination"}, "date": {"$slot": "date"}}}]
FIND = "find flights from Bangalore to Delhi on Friday"
PLANS: dict[str, dict] = {
    FIND: {"intent": "search_flights", "slot_writes": {"origin": "BLR", "destination": "DEL", "date": "Fri"},
           "graph": SEARCH_GRAPH},
    "actually, to Mumbai": {"intent": "search_flights", "slot_writes": {"destination": "BOM"}},
    "book flight 6E-701 for one person": {"intent": "book_flight", "slot_writes": {"flight_id": "6E-701", "passengers": 1},
                           "graph": [{"node_id": "b1", "tool": "book_flight",
                                      "args": {"flight_id": {"$slot": "flight_id"}, "passengers": {"$slot": "passengers"}}}]},
    "wait, two of us": {"intent": "book_flight", "slot_writes": {"passengers": 2}},
}


def flights(args: dict) -> dict:
    return {"flights": [{"id": f"{args['destination']}-701", "date": args["date"], "price": 4120}]}


def to_mumbai() -> Event:
    return say("actually, to Mumbai", "CORRECTION", {"destination": "BOM"})


def scenario_a(**kw: Any) -> Sim:
    """Search -> result -> final response."""
    sim = Sim(MANIFEST, {"search_flights": Behavior(0.5, data=flights)}, ScriptedPlanner(PLANS), **kw)
    return sim.run([(0.1, say(FIND)), (0.5, eot())])


def scenario_b(**kw: Any) -> Sim:
    """BLR->DEL search, user changes to Mumbai, old work superseded, new search, old result rejected."""
    sim = Sim(MANIFEST, {"search_flights": Behavior(2.0, data=flights)}, ScriptedPlanner(PLANS), **kw)
    return sim.run([(0.1, say(FIND)), (0.5, eot()), (1.4, to_mumbai()), (1.6, eot())])


def scenario_c(**kw: Any) -> Sim:
    """Read-only call times out -> superseded + cancel -> retried; the late original result is stale."""
    manifest = [dict(MANIFEST[0], timeout_s=1.0)] + MANIFEST[1:]
    tools = {"search_flights": [Behavior(4.0, data=flights), Behavior(0.5, data=flights)]}
    sim = Sim(manifest, tools, ScriptedPlanner(PLANS), **kw)
    return sim.run([(0.1, say(FIND)), (0.5, eot())])


def scenario_d(honors_cancel: bool = False, **kw: Any) -> Sim:
    """Booking starts, correction supersedes it, cancel requested; the tool may still complete."""
    tools = {"book_flight": Behavior(1.0, data={"booking_id": "B1"}, honors_cancel=honors_cancel)}
    sim = Sim(MANIFEST, tools, ScriptedPlanner(PLANS), **kw)
    return sim.run([(0.1, say("book flight 6E-701 for one person")), (0.3, eot()),
                    (0.8, say("wait, two of us", "CORRECTION", {"passengers": 2})), (1.0, eot())])


RAPID = [("no, Mumbai", "BOM"), ("no wait, Goa", "GOI"), ("actually Mumbai", "BOM")]


def scenario_e(eot_each: bool = False, **kw: Any) -> Sim:
    """Rapid successive corrections, inside one open turn (default) or each closing its turn."""
    plans: dict[str, dict] = dict(PLANS)
    for text, dest in RAPID:
        plans[text] = {"intent": "search_flights", "slot_writes": {"destination": dest}}
    plans[" ".join(t for t, _ in RAPID)] = {"intent": "search_flights", "slot_writes": {"destination": "BOM"}}
    sim = Sim(MANIFEST, {"search_flights": Behavior(3.0, data=flights)}, ScriptedPlanner(plans), **kw)
    script: list[tuple[float, Event]] = [(0.1, say(FIND)), (0.5, eot())]
    t = 1.0
    for text, dest in RAPID:
        script.append((t, say(text, "CORRECTION", {"destination": dest})))
        if eot_each:
            script.append((t + 0.1, eot()))
        t += 0.3
    if not eot_each:
        script.append((t, eot()))
    return sim.run(script)


PHOTO = "find flights from Bangalore to Delhi on the date in this photo"


def scenario_f(goal_switch: bool = False, **kw: Any) -> Sim:
    """Evidence arrives after a correction (conflict -> clarify) or after a goal switch (not applied)."""
    plans: dict[str, dict] = {
        PHOTO: {"intent": "search_flights", "slot_writes": {"origin": "BLR", "destination": "DEL"}, "graph": SEARCH_GRAPH},
        "the date is Saturday": {"intent": "search_flights", "slot_writes": {"date": "Sat"}},
        "forget it, weather in Pune": {"intent": "get_weather", "slot_writes": {"city": "Pune"},
                                       "graph": [{"node_id": "w1", "tool": "get_weather", "args": {"city": {"$slot": "city"}}}]},
    }
    tools = {"search_flights": Behavior(0.5, data=flights), "get_weather": Behavior(0.3, data={"temp_c": 31})}
    sim = Sim(MANIFEST, tools, ScriptedPlanner(plans), ScriptedPerception({"img1": {"date": ["Fri", 0.93]}}), **kw)
    second = say("forget it, weather in Pune", "GOAL_SWITCH") if goal_switch else \
        say("the date is Saturday", "CORRECTION", {"date": "Sat"})
    return sim.run([(0.1, say(PHOTO)), (0.2, image("img1", "f1")), (0.4, eot()), (1.0, second), (1.2, eot())])


def scenario_g(**kw: Any) -> Sim:
    """Duplicate events: a repeated user chunk and end-of-turn (same harness id), and a duplicated tool result."""
    sim = Sim(MANIFEST, {"search_flights": Behavior(0.5, data=flights, duplicate=True)}, ScriptedPlanner(PLANS), **kw)
    return sim.run([(0.1, say(FIND, eid="u1")), (0.2, say(FIND, eid="u1")), (0.5, eot(eid="t1")), (0.6, eot(eid="t1")),
                    (3.0, eot())])


def scenario_h(result_first: bool = True, **kw: Any) -> Sim:
    """Same-time ordering: tool result and correction at t=2.0 in either delivery order; timeout also due at 2.0."""
    manifest = [dict(MANIFEST[0], timeout_s=1.2)] + MANIFEST[1:]  # c1 dispatched at 0.8 -> timeout due at 2.0
    sim = Sim(manifest, {"search_flights": [Behavior(None), Behavior(0.5, data=flights)]}, ScriptedPlanner(PLANS), **kw)
    both = [(2.0, result("c1", data=flights({"destination": "DEL", "date": "Fri"}))), (2.0, to_mumbai())]
    return sim.run([(0.1, say(FIND)), (0.5, eot())] + (both if result_first else both[::-1]) + [(2.3, eot())])


SCENARIOS: dict[str, Callable[..., Sim]] = {
    "A": scenario_a, "B": scenario_b, "C": scenario_c, "D": scenario_d, "D2": lambda **kw: scenario_d(True, **kw),
    "E": scenario_e, "E2": lambda **kw: scenario_e(True, **kw), "F": scenario_f,
    "F2": lambda **kw: scenario_f(True, **kw), "G": scenario_g, "H": scenario_h, "H2": lambda **kw: scenario_h(False, **kw),
}


def timeline(sim: Sim) -> str:
    lines = []
    for rec in sim.journal.records:
        if rec["type"] == "in":
            e = rec["event"]
            lines.append(f"t={e['t']:6.2f}  seq={e['seq']:3d}  IN   {e['kind']:<15} {_brief(e['payload'])}")
        elif rec["type"] == "out":
            a = rec["action"]
            lines.append(f"{'':21}OUT  {a['kind']:<15} {_brief(a['payload'])}   [{a['rule']}]")
        elif rec["type"] == "dup":
            lines.append(f"{'':21}DUP  {rec['event']['kind']} eid={rec['event']['eid']}")
    return "\n".join(lines)


def _brief(p: Any) -> str:
    if not isinstance(p, dict):
        return ""
    keep = {k: v for k, v in p.items() if k in ("text", "call_id", "tool", "args", "outcome", "reason", "timer_id",
                                                  "intent", "slot_writes", "snapshot", "grounded_on", "claims")}
    return str(keep)[:150]


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in SCENARIOS:
        print("scenarios:", ", ".join(f"{k} ({(SCENARIOS[k].__doc__ or '').strip()})" for k in SCENARIOS))
        return 0
    print(timeline(SCENARIOS[argv[0]]()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
