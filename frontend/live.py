"""Live (wall-clock) driver for the PRISM-LOCAL/0 agent: the evaluator's co-simulation loop, paced by real time.

The black-box harness (evaluation/harness.py) runs a scenario as fast as possible in virtual time. This driver runs
the SAME pieces (the agent subprocess, the mock tool world, the wire format) with virtual time = wall-clock seconds
since the session started, so a person can watch it, and speak, type or show images into it while it works.

Nothing here decides anything for the agent. It delivers inputs and tool results, ticks the clock when the agent
asks for it (`agent.ready.next_wakeup`), and publishes what crossed the wire, plus the agent's own journal records
(written by the agent to PRISM_JOURNAL_STREAM as it steps), to the frontend.
"""

from __future__ import annotations

import heapq
import itertools
import json
import queue
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

from evaluation import metrics
from evaluation.agents import AgentError, SubprocessAgent
from evaluation.harness import output_problem, wire
from evaluation.world import World

Publish = Callable[[dict], None]


class LiveSession(threading.Thread):
    def __init__(self, publish: Publish, agent_cmd: list[str], manifest: list[dict], world_spec: dict,
                 scenario: dict | None = None, speed: float = 1.0, session_id: str = "live"):
        super().__init__(daemon=True)
        self.publish, self.cmd, self.manifest, self.world_spec = publish, agent_cmd, manifest, world_spec
        self.scenario, self.speed, self.session_id = scenario, speed, session_id
        self.inputs: queue.Queue[tuple[str, dict, str | None]] = queue.Queue()
        self.stopped = threading.Event()
        self.t0 = time.monotonic()
        self.last_t = 0.0
        self.records: list[dict] = []
        self._n = itertools.count(1)
        self._journal = Path(tempfile.mkstemp(prefix="prism-journal-", suffix=".jsonl")[1])
        self._offset = 0
        self.world: World | None = None
        self.result: dict | None = None
        self._tick = 0
        self._world_seen = 0

    # ------------------------------------------------------------ control (any thread)

    def now(self) -> float:
        return (time.monotonic() - self.t0) * self.speed

    def inject(self, typ: str, data: dict | None = None, mid: str | None = None) -> None:
        self.inputs.put((typ, data or {}, mid))

    def stop(self) -> None:
        self.stopped.set()

    # ------------------------------------------------------------ the loop

    def run(self) -> None:
        self.world = World(self.world_spec, self.manifest)
        heap: list = []
        order = itertools.count()

        def schedule(t: float, rank: int, item: tuple) -> None:
            heapq.heappush(heap, (t, rank, next(order), item))

        horizon = float(self.scenario.get("horizon", 60.0)) if self.scenario else None
        for i, inp in enumerate((self.scenario or {}).get("inputs", []), start=1):
            line = inp["raw"] if "raw" in inp else wire(inp.get("id", f"i{i}"), inp["t"], inp["type"], inp.get("data"))
            schedule(float(inp["t"]), int(inp.get("rank", 0)), ("send", line))
        pending_inputs = len(heap)
        try:
            agent = SubprocessAgent(self.cmd, self.session_id, timeout_s=60.0,
                                    env={"PRISM_JOURNAL_STREAM": str(self._journal)})
        except OSError as exc:
            self.publish({"type": "session", "state": "error", "detail": f"could not start the agent: {exc}"})
            return
        wake: float | None = None
        idle_since: float | None = None
        self.publish({"type": "session", "state": "running", "t": 0.0})
        try:
            wake = self._send(agent, wire("s0", 0.0, "session.start"), 0.0, schedule)
            wake = self._send(agent, wire("m0", 0.0, "manifest", {"tools": self.manifest}), 0.0, schedule)
            while not self.stopped.is_set():
                now = self.now()
                due_heap = heap[0][0] if heap else None
                # 1) everything already due, in harness order (harness messages before agent timers at equal t)
                if wake is not None and wake <= now and (due_heap is None or wake < due_heap):
                    self._tick += 1
                    wake = self._send(agent, wire(f"tick{self._tick}", wake, "clock.tick"), wake, schedule)
                    continue
                if due_heap is not None and due_heap <= now:
                    t, _, _, item = heapq.heappop(heap)
                    if item[0] == "deliver":
                        data = self.world.deliver(item[1], t)
                        if data is None:
                            continue
                        line = wire(self.world._next_id(), t, "tool.result", data)
                    else:
                        line = item[1]
                        pending_inputs -= 1
                    wake = self._send(agent, line, t, schedule)
                    continue
                # 2) live input from the person (not during a scripted scenario)
                try:
                    typ, data, mid = self.inputs.get_nowait()
                    t = max(self.now(), self.last_t)
                    wake = self._send(agent, wire(mid or f"u{next(self._n)}", round(t, 4), typ, data), t, schedule)
                    continue
                except queue.Empty:
                    pass
                # 3) scenario end: all inputs sent, nothing in flight but far timers -> stop after a short quiet period
                if self.scenario is not None:
                    quiet = pending_inputs == 0 and not heap and (wake is None or wake - now > 5.0)
                    if quiet or (horizon is not None and now >= horizon):
                        idle_since = idle_since if idle_since is not None else now
                        if now - idle_since >= 1.5 or (horizon is not None and now >= horizon):
                            break
                    else:
                        idle_since = None
                nxt = min([x for x in (wake, heap[0][0] if heap else None) if x is not None], default=now + 0.05)
                time.sleep(max(0.0, min(0.02, (nxt - now) / self.speed)))
            end = max(self.now(), self.last_t)
            self._send(agent, wire("s-end", round(end, 4), "session.end"), end, schedule)
        except AgentError as exc:
            self.publish({"type": "session", "state": "error", "detail": str(exc)[-600:]})
            return
        finally:
            agent.close()
            self._pump()
        trace = {"scenario": (self.scenario or {}).get("id", "live"), "protocol": "PRISM-LOCAL/0",
                 "horizon": horizon or self.last_t, "records": self.records, "world": self.world.ledger(), "violations": []}
        if self.scenario is not None and not self.stopped.is_set():  # a demo stopped half-way is not scored
            self.result = metrics.evaluate(self.scenario, trace)
            self.publish({"type": "verdict", "result": self.result})
        self.publish({"type": "session", "state": "stopped" if self.stopped.is_set() else "ended", "t": self.last_t})

    def _send(self, agent: SubprocessAgent, line: str, t: float, schedule: Callable) -> float | None:
        assert self.world is not None
        self._publish_world()  # e.g. a result just delivered (and a side effect it executed)
        self.last_t = max(self.last_t, t)
        self.records.append({"t": t, "dir": "in", "raw": line})
        try:
            msg_in = json.loads(line)
        except ValueError:
            msg_in = None
        self.publish({"type": "wire", "dir": "in", "t": t, "msg": msg_in})
        outs, wake = agent.send(line)
        self._pump()
        for raw in outs:
            msg, problem = output_problem(raw)
            self.records.append({"t": t, "dir": "out", "raw": raw, "msg": msg})
            self.publish({"type": "wire", "dir": "out", "t": t, "msg": msg, "problem": problem})
            if problem or msg is None:
                continue
            for when, delivery in self.world.on_output(msg, t):
                schedule(when, 0, ("deliver", delivery))
        self._publish_world()
        return wake

    def _publish_world(self) -> None:
        """The tool world's own ledger events (calls received, cancels honoured/ignored, results, side effects)."""
        assert self.world is not None
        for ev in self.world.events[self._world_seen:]:
            self.publish({"type": "world", "event": ev})
        self._world_seen = len(self.world.events)

    def _pump(self) -> None:
        """Forward the agent's new journal records (it flushes each record before answering agent.ready)."""
        try:
            with open(self._journal, "rb") as f:
                f.seek(self._offset)
                chunk = f.read()
        except OSError:
            return
        complete = chunk[: chunk.rfind(b"\n") + 1]
        self._offset += len(complete)
        for line in complete.decode("utf-8").splitlines():
            if line.strip():
                self.publish({"type": "journal", "rec": json.loads(line)})
