"""REPLAY MODE check for model-driven runs: re-run every scenario of a recorded A/B run with
`--planner replay:<journal>` (no model is contacted). Reports runs whose black-box result is identical, and runs
whose TOOL-LEVEL behaviour is identical (every tool/cancel/side-effect/safety/final check and the cancel latencies;
speech timing excluded, since the response policy may have changed after the recording). Tool-level must be 100%.

    python -m scripts.replay_models evaluation/reports/phase5_ab/ollama_qwen2.5_7b_lat0.25
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from evaluation import harness, metrics
from evaluation.scenario import discover, load


def tool_level(result: dict) -> dict:
    speech_checks = ("turn_answered",)
    return {"checks": {c["check"]: c["passed"] for c in result["checks"]
                       if c["category"] != "response_latency" and not c["check"].startswith(speech_checks)},
            "cancel": result["latency"]["interrupt_to_cancel_s"]}


def main(argv: list[str] | None = None) -> int:
    run = Path((argv or sys.argv[1:])[0])
    recorded = {r["scenario"]: r for r in json.loads((run / "results.json").read_text())["results"]}
    os.environ["PRISM_JOURNAL_DIR"] = tempfile.mkdtemp()  # the replaying agent's own journal, not the recording
    same, tools_same = 0, 0
    for path in discover("all"):
        scenario = load(path)
        journal = run / "journals" / f"{scenario['id']}.jsonl"
        cmd = [sys.executable, "-m", "agent.adapter.stdio", "--planner", f"replay-lenient:{journal}"]
        result = metrics.evaluate(scenario, harness.run(scenario, cmd))
        same += result == recorded[scenario["id"]]
        ok = tool_level(result) == tool_level(recorded[scenario["id"]])
        tools_same += ok
        if not ok:
            print(f"DIFFERENT {scenario['id']}")
    print(f"{run.name}: {tools_same}/{len(recorded)} tool-level identical, {same}/{len(recorded)} fully identical, "
          "without the model")
    return 0 if tools_same == len(recorded) else 1


if __name__ == "__main__":
    raise SystemExit(main())
