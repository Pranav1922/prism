"""REPLAY MODE check for model-driven runs: re-run every scenario of a recorded A/B run with
`--planner replay:<journal>` (no model is contacted) and require identical black-box results.

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


def main(argv: list[str] | None = None) -> int:
    run = Path((argv or sys.argv[1:])[0])
    recorded = {r["scenario"]: r for r in json.loads((run / "results.json").read_text())["results"]}
    os.environ["PRISM_JOURNAL_DIR"] = tempfile.mkdtemp()  # the replaying agent's own journal, not the recording
    same = 0
    for path in discover("all"):
        scenario = load(path)
        journal = run / "journals" / f"{scenario['id']}.jsonl"
        cmd = [sys.executable, "-m", "agent.adapter.stdio", "--planner", f"replay:{journal}"]
        result = metrics.evaluate(scenario, harness.run(scenario, cmd))
        ok = result == recorded[scenario["id"]]
        same += ok
        if not ok:
            print(f"DIFFERENT {scenario['id']}")
    print(f"{same}/{len(recorded)} scenarios replay identically without the model ({run.name})")
    return 0 if same == len(recorded) else 1


if __name__ == "__main__":
    raise SystemExit(main())
