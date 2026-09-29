"""Deliberately broken PRISM-LOCAL/0 agents, used only to prove the black-box evaluator discriminates.

    python -m tests.broken_agents nocancel    # never emits tool.cancel
    python -m tests.broken_agents doublecall  # emits every tool.call twice (second copy with a new call_id)
"""

from __future__ import annotations

import json
import sys

from agent.adapter.stdio import DEFAULT_FIXTURES, LocalAgent


def mutate(mode: str, lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        msg = json.loads(line)
        if mode == "nocancel" and msg["type"] == "tool.cancel":
            continue
        out.append(line)
        if mode == "doublecall" and msg["type"] == "tool.call":
            twin = json.loads(line)
            twin["id"] += "-dup"
            twin["data"]["call_id"] += "-dup"
            out.append(json.dumps(twin, sort_keys=True))
    return out


def main() -> int:
    mode = sys.argv[1]
    agent = LocalAgent(json.loads(DEFAULT_FIXTURES.read_text()))
    for line in sys.stdin:
        if line.strip():
            for out in mutate(mode, agent.handle(line)):
                sys.stdout.write(out + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
