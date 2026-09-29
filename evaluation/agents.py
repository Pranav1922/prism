"""Agent launchers: the ONLY agent-specific part of the evaluation.

An agent under test is any program that speaks PRISM-LOCAL/0 as JSON lines on stdin/stdout, in lockstep:
for every input line it writes its output lines and then exactly one `agent.ready` line. The evaluator
never imports agent code, so independent implementations are scored identically.

Register an implementation by name in AGENTS, or pass a full command: --agent "cmd:<command line>".
"""

from __future__ import annotations

import json
import os
import select
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

AGENTS: dict[str, list[str]] = {
    "impl_a": [sys.executable, "-m", "agent.adapter.stdio"],
    "impl_a_scripted": [sys.executable, "-m", "agent.adapter.stdio", "--understanding", "scripted"],  # comparison only
    # "impl_b": ["<developer B's launcher command>"],
}


class AgentError(RuntimeError):
    pass


def resolve(agent: str) -> list[str]:
    if agent.startswith("cmd:"):
        return shlex.split(agent[4:])
    if agent not in AGENTS:
        raise AgentError(f"unknown agent '{agent}' (known: {', '.join(AGENTS)}; or use cmd:<command>)")
    return AGENTS[agent]


class SubprocessAgent:
    def __init__(self, cmd: list[str], scenario_id: str, timeout_s: float = 10.0):
        env = {**os.environ, "PRISM_SCENARIO": scenario_id, "PYTHONHASHSEED": "0"}
        self.proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, bufsize=0)
        self.timeout_s = timeout_s
        self._buf = b""  # own line buffer: select() only sees the fd, so no buffered reader may sit in between

    def send(self, line: str) -> tuple[list[str], float | None]:
        """Deliver one input line; return (raw output lines before agent.ready, next_wakeup)."""
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write((line + "\n").encode("utf-8"))
        except BrokenPipeError as exc:
            raise AgentError(f"agent exited: {self._stderr()}") from exc
        outputs: list[str] = []
        while True:
            raw = self._readline()
            try:
                msg = json.loads(raw)
            except ValueError:
                outputs.append(raw)  # malformed output is recorded and scored, not fatal
                continue
            if isinstance(msg, dict) and msg.get("type") == "agent.ready":
                wake = (msg.get("data") or {}).get("next_wakeup")
                return outputs, (float(wake) if isinstance(wake, (int, float)) else None)
            outputs.append(raw)

    def _readline(self) -> str:
        assert self.proc.stdout is not None
        fd = self.proc.stdout.fileno()
        while b"\n" not in self._buf:
            ready, _, _ = select.select([fd], [], [], self.timeout_s)
            if not ready:
                raise AgentError(f"agent did not answer within {self.timeout_s}s")
            chunk = os.read(fd, 65536)
            if not chunk:
                raise AgentError(f"agent exited: {self._stderr()}")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return line.decode("utf-8", errors="replace")

    def _stderr(self) -> str:
        try:
            return (self.proc.stderr.read().decode("utf-8", "replace") if self.proc.stderr else "")[-2000:]
        except Exception:
            return ""

    def close(self) -> None:
        if self.proc.stdin and not self.proc.stdin.closed:
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
