"""Black-box evaluation runner.

    python -m evaluation.run all --agent impl_a
    python -m evaluation.run reference --agent impl_a --out evaluation/reports/impl_a
    python -m evaluation.run B_destination_correction --agent "cmd:<any PRISM-LOCAL/0 agent command>"

Writes, per scenario, <out>/traces/<id>.json (the external trace) and <out>/results.json + report.md.
Everything is deterministic (virtual time only); results carry the scenario file hash for reproducibility.
Scores are INTERNAL PRISM-STYLE METRICS, not Samsung scores.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from evaluation import harness, metrics
from evaluation.agents import resolve
from evaluation.scenario import discover, load

ROOT = Path(__file__).resolve().parents[1]


def run_one(path: Path, agent: str) -> tuple[dict, dict]:
    scenario = load(path)
    trace = harness.run(scenario, resolve(agent))
    trace["agent"] = agent
    result = metrics.evaluate(scenario, trace)
    result["scenario_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return trace, result


def report_md(results: list[dict], agent: str) -> str:
    lines = [f"# Evaluation report: `{agent}`", "",
             "**INTERNAL PRISM-STYLE METRICS.** They mirror the documented Theme 05 categories; they are *not* Samsung scores.",
             "", "| Scenario | Pass | Score | TC | IR | RL | SP | first-response p50 (s) | cancel latency (s) |",
             "|---|---|---|---|---|---|---|---|---|"]
    fmt = lambda v: "n/a" if v is None else f"{v:.2f}"  # noqa: E731
    for r in results:
        c = r["categories"]
        lat = r["latency"]
        lines.append(f"| {r['scenario']} | {'yes' if r['passed'] else '**NO**'} | {r['internal_score']:.1f} | "
                     f"{fmt(c['task_completion'])} | {fmt(c['interruption_recovery'])} | {fmt(c['response_latency'])} | "
                     f"{fmt(c['safety_protocol'])} | {fmt(lat['turn_first_substantive_p50_s'])} | "
                     f"{', '.join(f'{x:.3f}' for x in lat['interrupt_to_cancel_s']) or '-'} |")
    passed = sum(r["passed"] for r in results)
    mean = sum(r["internal_score"] for r in results) / len(results) if results else 0
    lines += ["", f"**{passed}/{len(results)} scenarios pass all checks; mean internal score {mean:.1f}.**", ""]
    for r in results:
        failed = [c for c in r["checks"] if not c["passed"]]
        if failed:
            lines.append(f"- `{r['scenario']}` failed: " + "; ".join(c["check"] for c in failed))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Black-box PRISM-LOCAL/0 evaluation")
    ap.add_argument("selector", nargs="?", default="all", help="all | <suite> | <scenario id> | <path>")
    ap.add_argument("--agent", default="impl_a", help="registered agent name or cmd:<command>")
    ap.add_argument("--out", default=None, help="output directory (default evaluation/reports/<agent>)")
    args = ap.parse_args(argv)
    paths = discover(args.selector)
    if not paths:
        print(f"no scenarios match '{args.selector}'", file=sys.stderr)
        return 2
    out = Path(args.out or ROOT / "evaluation" / "reports" / args.agent.replace(":", "_").replace(" ", "_")[:60])
    (out / "traces").mkdir(parents=True, exist_ok=True)
    results = []
    for path in paths:
        trace, result = run_one(path, args.agent)
        (out / "traces" / f"{result['scenario']}.json").write_text(json.dumps(trace, indent=1, sort_keys=True))
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"{status}  {result['internal_score']:6.1f}  {result['scenario']}")
    (out / "results.json").write_text(json.dumps({"agent": args.agent, "protocol": "PRISM-LOCAL/0",
                                                 "label": "INTERNAL PRISM-STYLE METRICS (not a Samsung score)",
                                                 "results": results}, indent=1, sort_keys=True))
    (out / "report.md").write_text(report_md(results, args.agent))
    print(f"\n{sum(r['passed'] for r in results)}/{len(results)} pass. Report: {out / 'report.md'}")
    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
