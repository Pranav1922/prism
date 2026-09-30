"""Theme 05 demo: run a demo scenario through the black-box harness and show what happened, step by step.

    python demo/run_demo.py                       # both demos, timeline + evaluator verdict
    python demo/run_demo.py interruption --speak  # replay the timeline aloud (afplay + say), in real time
    python demo/run_demo.py ticket --planner scripted --perception scripted   # fully deterministic fallback

The agent runs as a separate process speaking PRISM-LOCAL/0 (this project's local protocol, not Samsung's).
Scores are INTERNAL PRISM-STYLE metrics. Transcript / OCR / stale-result annotations come from the agent's own
journal and are shown in [brackets]; everything else is the external wire trace.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation import harness, metrics  # noqa: E402
from evaluation.scenario import load  # noqa: E402

DEMOS = {"interruption": "demo_audio_interruption", "ticket": "demo_ticket_image"}
OUT = ROOT / "demo" / "output"


def annotations(journal: Path) -> dict[float, list[str]]:
    """Agent-side facts worth showing (from its journal): transcripts, OCR claims, stale results, planner answers."""
    notes: dict[float, list[str]] = {}
    recs = [json.loads(line) for line in journal.read_text().splitlines() if line.strip()]
    for r in recs:
        if r["type"] == "in":
            e = r["event"]
            if e["kind"] == "UserText" and e["payload"].get("source") == "asr":
                notes.setdefault(e["t"], []).append(f"[heard: \"{e['payload']['text']}\"]")
            elif e["kind"] == "Evidence":
                claims = ", ".join(f"{k}={v[0]} ({v[1]:.2f})" for k, v in e["payload"]["claims"].items())
                notes.setdefault(e["t"], []).append(f"[image read: {claims}]")
            elif e["kind"] == "Proposal":
                notes.setdefault(e["t"], []).append(f"[plan: {e['payload'].get('intent')} {e['payload'].get('slot_writes', {})}]")
    ts = {r["seq"]: r["event"]["t"] for r in recs if r["type"] == "in"}
    for r in recs:
        if r["type"] == "step":
            for x in r["rules"]:
                if x["rule"] == "ADM.stale":
                    notes.setdefault(ts[r["seq"]], []).append(f"[late result for superseded {x['call_id']}: recorded, NOT used]")
                elif x["rule"] == "EV.not_active":
                    notes.setdefault(ts[r["seq"]], []).append("[image evidence kept until its task exists]")
    return notes


def timeline(trace: dict, notes: dict[float, list[str]]) -> list[tuple[float, str, str | None, str | None]]:
    """(t, line, audio file to play, text to say)."""
    rows: list[tuple[float, str, str | None, str | None]] = []
    shown: set[float] = set()
    cancelled: set[str] = set()
    for rec in trace["records"]:
        t = rec["t"]
        msg = rec.get("msg") or (json.loads(rec["raw"]) if rec["dir"] == "in" else None)
        if not isinstance(msg, dict):
            continue
        typ, d = msg.get("type"), msg.get("data", {})
        line, audio, say = None, None, None
        if typ == "user.text":
            line = f"USER   says: \"{d['text']}\""
        elif typ == "user.audio":
            line, audio = f"USER   speaks ({Path(d['ref']).name})", str(ROOT / d["ref"])
        elif typ == "user.frame":
            line = f"USER   shows an image ({Path(d['ref']).name})"
        elif typ == "tool.call":
            line = f"AGENT  -> tool.call {d['call_id']} {d['tool']} {json.dumps(d['args'], sort_keys=True)}"
        elif typ == "tool.cancel":
            cancelled.add(d["call_id"])
            line = f"AGENT  -> tool.cancel {d['call_id']}  (superseded by the newer request)"
        elif typ == "tool.result":
            late = "  <-- STALE (call was superseded)" if d["call_id"] in cancelled else ""
            line = f"TOOL   <- result {d['call_id']} {d.get('status')} {json.dumps(d.get('data'))[:70]}{late}"
        elif typ in ("speech", "clarify"):
            line, say = f"AGENT  says: \"{d['text']}\"", d["text"]
        elif typ == "response.final":
            line = f"AGENT  FINAL: \"{d['text']}\"  grounded_on={d.get('grounded_on')}  snapshot={d['snapshot']['slots']}"
            say = d["text"]
        if line:
            rows.append((t, line, audio, say))
        for nt in sorted(k for k in notes if k <= t and k not in shown):
            shown.add(nt)
            rows.extend((nt, n, None, None) for n in notes[nt])
    return sorted(rows, key=lambda r: r[0])


def speak(rows: list, rate: float) -> None:
    start, player = time.monotonic(), None
    for t, line, audio, text in rows:
        delay = t / rate - (time.monotonic() - start)
        if delay > 0:
            time.sleep(delay)
        print(f"{t:6.2f}s  {line}", flush=True)
        if audio and shutil.which("afplay"):
            player = subprocess.Popen(["afplay", audio])
        if text and shutil.which("say"):
            if player is not None:
                player.wait()
            subprocess.run(["say", text])


def run(name: str, args: argparse.Namespace) -> bool:
    sid = DEMOS[name]
    scenario = load(ROOT / "evaluation" / "scenarios" / "demo" / f"{sid}.json")
    OUT.mkdir(parents=True, exist_ok=True)
    os.environ["PRISM_JOURNAL_DIR"] = str(OUT)
    cmd = [sys.executable, "-m", "agent.adapter.stdio", "--planner", args.planner, "--perception", args.perception,
           "--perception-latency", args.perception_latency]
    trace = harness.run(scenario, cmd)
    result = metrics.evaluate(scenario, trace)
    (OUT / f"{sid}.trace.json").write_text(json.dumps(trace, indent=1))
    header = json.loads((OUT / f"{sid}.jsonl").read_text().splitlines()[0])
    rows = timeline(trace, annotations(OUT / f"{sid}.jsonl"))
    print(f"\n=== {sid} ===\n{scenario['description']}\n")
    print(f"agent: planner={header['backends']['planner']}  perception={args.perception} (latency {args.perception_latency})\n")
    if args.speak:
        speak(rows, args.rate)
    else:
        for t, line, _, _ in rows:
            print(f"{t:6.2f}s  {line}")
    lat = result["latency"]
    print(f"\nevaluator (INTERNAL PRISM-STYLE): {'PASS' if result['passed'] else 'FAIL'}  score {result['internal_score']}"
          f"  first-response per turn {lat['turn_first_substantive_s']} s  end-to-end {lat['end_to_end_s']} s")
    for c in result["checks"]:
        if not c["passed"]:
            print(f"  failed check: {c['check']}")
    (OUT / f"{sid}.result.json").write_text(json.dumps(result, indent=1))
    return bool(result["passed"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("demo", nargs="?", choices=[*DEMOS, "all"], default="all")
    ap.add_argument("--speak", action="store_true", help="replay the timeline aloud in real time (macOS afplay + say)")
    ap.add_argument("--rate", type=float, default=1.0, help="timeline speed for --speak")
    ap.add_argument("--planner", default="auto", help="auto (PRISM_PLANNER model if reachable, else scripted) | scripted | ...")
    ap.add_argument("--perception", default="local", choices=("local", "scripted"))
    ap.add_argument("--perception-latency", default="measured")
    args = ap.parse_args()
    names = list(DEMOS) if args.demo == "all" else [args.demo]
    ok = all([run(n, args) for n in names])
    print(f"\ntraces and agent journals: {OUT}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
