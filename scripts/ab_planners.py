"""A/B planner-backend comparison on the black-box scenario suite (INTERNAL PRISM-STYLE; not Samsung scores).

    python -m scripts.ab_planners --backends scripted,ollama:qwen2.5:3b --latency measured --out evaluation/reports/phase5_ab

Every backend runs exactly the same scenario files, manifests, tool world, input timing and evaluator
(evaluation.metrics). Only the agent's --planner flag differs. Scores come from the external trace only.
Planner telemetry (latency, invalid proposals, repairs, staleness handling) is read from the AGENT's journal,
written by the agent itself (PRISM_JOURNAL_DIR), and is reported separately as internal telemetry.

--latency measured: the model's real wall time becomes the planner's virtual latency (speed counts).
--latency 0.25: every planner answers after 0.25 s virtual (planning quality only, same timing as scripted).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

from evaluation import harness, metrics
from evaluation.run import report_md
from evaluation.scenario import discover, load
from scripts.planner_bench import _ollama_memory

ROOT = Path(__file__).resolve().parents[1]


def agent_cmd(spec: str, latency: str, timeout_s: float) -> list[str]:
    return [sys.executable, "-m", "agent.adapter.stdio", "--planner", spec, "--planner-latency", latency,
            "--planner-timeout", str(timeout_s)]


def telemetry(journal: Path) -> dict:
    recs = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()]
    fx = [r for r in recs if r["type"] == "fx_io"]
    rules = [x for r in recs if r["type"] == "step" for x in r["rules"]]
    outs = [r for r in recs if r["type"] == "out"]
    ins = {r["seq"]: r["event"] for r in recs if r["type"] == "in"}
    first_tool = []  # planner answer -> first tool call caused by that step or a later one (virtual s)
    for seq, ev in ins.items():
        if ev["kind"] == "Proposal":
            calls = [ins[o["seq"]]["t"] for o in outs if o["action"]["kind"] == "TOOL_CALL" and o["seq"] >= seq]
            if calls:
                first_tool.append(min(calls) - ev["t"])
    return {
        "requests": len(fx),
        "proposals": sum(1 for f in fx if f["kind"] == "Proposal"),
        "failed": [f["payload"].get("reason") for f in fx if f["kind"] == "ProposalFailed"],
        "invalid_admission": sum(1 for x in rules if x["rule"] == "PROP.invalid"),
        "repairs": sum(1 for f in fx if len(f.get("attempts", [])) > 1),
        "wall_s": [f["wall_s"] for f in fx if "wall_s" in f],
        "virtual_latency": [f["virtual_latency"] for f in fx],
        "planner_to_first_tool_s": first_tool,
        "stale": {k: sum(1 for x in rules if x["rule"] == k) for k in
                  ("PROP.structure_stale", "PROP.graph_stale", "LWW.reject", "PROP.tainted", "PROP.injection_dropped")},
        "clarify": sum(1 for o in outs if o["action"]["kind"] == "CLARIFY"),
        "blocked": sorted({x["reason"] for x in rules if x["rule"] == "BARRIER.block"}),
    }


def pct(xs: list[float], p: float) -> float | None:
    return round(sorted(xs)[int(p * (len(xs) - 1))], 3) if xs else None


def run_backend(spec: str, paths: list[Path], latency: str, timeout_s: float, out: Path) -> dict:
    startup = None
    if spec.startswith("ollama:"):
        from agent.reasoner.backends import OllamaBackend
        startup = round(OllamaBackend(spec.split(":", 1)[1]).warm(), 2)
    jdir = out / "journals"
    jdir.mkdir(parents=True, exist_ok=True)
    os.environ["PRISM_JOURNAL_DIR"] = str(jdir)
    cmd = agent_cmd(spec, latency, timeout_s)
    results, tele = [], {}
    started = time.perf_counter()
    for path in paths:
        scenario = load(path)
        trace = harness.run(scenario, cmd, reply_timeout_s=timeout_s + 15)
        result = metrics.evaluate(scenario, trace)
        results.append(result)
        tele[result["scenario"]] = telemetry(jdir / f"{scenario['id']}.jsonl")
        print(f"  {'PASS' if result['passed'] else 'FAIL'} {result['internal_score']:6.1f} {result['scenario']}", flush=True)
    wall = time.perf_counter() - started
    (out / "results.json").write_text(json.dumps({"agent": spec, "planner_latency": latency, "protocol": "PRISM-LOCAL/0",
                                                 "label": "INTERNAL PRISM-STYLE METRICS (not a Samsung score)",
                                                 "results": results}, indent=1, sort_keys=True))
    (out / "report.md").write_text(report_md(results, f"{spec} (planner latency {latency})"))
    t = list(tele.values())
    walls = [x for v in t for x in v["wall_s"]]
    e2e = [r["latency"]["end_to_end_s"] for r in results if r["latency"]["end_to_end_s"] is not None]
    summary = {
        "backend": spec, "latency_mode": latency, "startup_s": startup, "suite_wall_s": round(wall, 1),
        "scenarios": len(results), "passed": sum(r["passed"] for r in results),
        "mean_score": round(statistics.mean(r["internal_score"] for r in results), 2),
        "task_completion": round(statistics.mean(r["categories"]["task_completion"] for r in results
                                                  if r["categories"]["task_completion"] is not None), 3),
        "planner_requests": sum(v["requests"] for v in t),
        "planner_failed": sum(len(v["failed"]) for v in t),
        "failed_reasons": sorted({x for v in t for x in v["failed"]}),
        "invalid_admission": sum(v["invalid_admission"] for v in t),
        "repairs": sum(v["repairs"] for v in t),
        "clarifications": sum(v["clarify"] for v in t),
        "stale_handled": {k: sum(v["stale"][k] for v in t) for k in t[0]["stale"]} if t else {},
        "planner_wall_s": {"p50": pct(walls, .5), "p95": pct(walls, .95), "max": pct(walls, 1.0), "n": len(walls)},
        "planner_to_first_tool_s": {"p50": pct([x for v in t for x in v["planner_to_first_tool_s"]], .5)},
        "end_to_end_s": {"median": round(statistics.median(e2e), 3) if e2e else None},
        "memory": _ollama_memory(spec.split(":", 1)[1]) if spec.startswith("ollama:") else {},
    }
    (out / "telemetry.json").write_text(json.dumps({"summary": summary, "per_scenario": tele}, indent=1))
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backends", required=True)
    ap.add_argument("--latency", default="measured")
    ap.add_argument("--timeout", type=float, default=8.0,
                    help="planner budget, wall seconds. Measured mode: part of the product (default 8 s). "
                         "Fixed-latency (quality-only) mode: use a generous value so slow models are not cut off.")
    ap.add_argument("--selector", default="all")
    ap.add_argument("--out", default=str(ROOT / "evaluation" / "reports" / "phase5_ab"))
    args = ap.parse_args(argv)
    paths = discover(args.selector)
    root = Path(args.out)
    summaries = []
    for spec in args.backends.split(","):
        print(f"== {spec} (latency {args.latency})", flush=True)
        name = spec.replace(":", "_") + ("" if args.latency == "measured" else f"_lat{args.latency}")
        summaries.append(run_backend(spec, paths, args.latency, args.timeout, root / name))
    existing = json.loads((root / "summary.json").read_text()) if (root / "summary.json").exists() else []
    keep = [s for s in existing if (s["backend"], s["latency_mode"]) not in {(x["backend"], x["latency_mode"]) for x in summaries}]
    (root / "summary.json").write_text(json.dumps(keep + summaries, indent=1))
    for s in summaries:
        print(json.dumps({k: v for k, v in s.items() if k not in ("stale_handled",)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
