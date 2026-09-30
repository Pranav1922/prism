"""D17 full-duplex measurements (INTERNAL, not a Samsung score).

    python scripts/bench_duplex.py [--blackbox] [--model qwen2.5:7b] [--out report.json]

Every number says which clock it is on:
  virtual  - scenario seconds (deterministic; mock tools with scripted latencies; planner latency 0.25 s virtual)
  wall     - measured on this machine (time.perf_counter)
  real     - wall time of the real on-device recogniser / OCR on the demo media

Sections: (1) the early-retrieval case, half vs full duplex, virtual; (2) black-box: all scenarios through the
unchanged evaluator, early-call counts read from the agent's own journals (virtual); (3) kernel step cost, wall;
(4) interruption while a deep (model) planner is busy, wall; (5) real ASR (file + streaming) and OCR, wall.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.async_runtime import AsyncRuntime, Worker  # noqa: E402
from agent.clock import WallClock  # noqa: E402
from agent.journal import Journal  # noqa: E402
from agent.kernel import Config, Kernel  # noqa: E402
from agent.model import ActionKind, Event, Kind  # noqa: E402
from agent.planner import ScriptedPlanner  # noqa: E402
from agent.reasoner.rules import DeterministicPlanner, RulePlanner  # noqa: E402
from agent.scenario import Behavior, Sim, eot  # noqa: E402

MANIFEST = json.loads((ROOT / "evaluation" / "scenarios" / "manifests" / "flights.json").read_text())
FIXTURES = json.loads((ROOT / "agent" / "fixtures" / "scripted.json").read_text())
CHUNKS = [(0.1, "Find a flight from Bangalore to Delhi"), (0.6, "on Friday"), (1.3, "Actually, Mumbai")]
EOT_T = 1.7


def text(t: str) -> Event:
    return Event(Kind.USER_TEXT, 0.0, {"text": t})


def flights(a: dict) -> dict:
    return {"flights": [{"id": f"{a['destination']}-701", "price": 4120}]}


def planner() -> Any:  # Sim is typed for ScriptedPlanner; any object with respond() works
    return DeterministicPlanner(ScriptedPlanner(FIXTURES["planner"], 0.25), RulePlanner(0.25))


# ---------------------------------------------------------------- (1) the early-retrieval case, virtual


def early_case(duplex: bool) -> dict:
    sim = Sim(MANIFEST, {"search_flights": [Behavior(4.0, data=flights), Behavior(1.0, data=flights)]}, planner(),
              config=Config(full_duplex=duplex))
    sim.run([(t, text(x)) for t, x in CHUNKS] + [(EOT_T, eot())])
    t_of = {r["seq"]: r["event"]["t"] for r in sim.journal.records if r["type"] == "in"}
    rules = [(rec["seq"], r) for rec in sim.journal.records if rec["type"] == "step" for r in rec["rules"]]
    acts = [(t_of[a.seq], a) for a in sim.actions]
    calls = [(t, a) for t, a in acts if a.kind is ActionKind.TOOL_CALL]
    early = {r["call_id"] for _, r in rules if r["rule"] == "REC.dispatch" and r.get("early")}
    cancels = [t for t, a in acts if a.kind is ActionKind.CANCEL]
    stale = {r["call_id"] for _, r in rules if r["rule"] == "ADM.stale"}
    superseded = {r["call_id"] for _, r in rules if r["rule"] == "REL.supersede"}
    speech = [(t, a) for t, a in acts if a.kind in (ActionKind.SPEAK, ActionKind.CLARIFY, ActionKind.FINAL)]
    final = next(t for t, a in acts if a.kind is ActionKind.FINAL)
    after_eot = [t for t, _ in acts if t >= EOT_T]
    return {
        "mode": "full duplex" if duplex else "half duplex (D5, evaluator baseline)",
        "first_partial_input_to_first_retrieval_s": round(calls[0][0] - CHUNKS[0][0], 3) if calls else None,
        "informative_chunk_to_first_retrieval_s": round(calls[0][0] - CHUNKS[1][0], 3) if calls and calls[0][0] < EOT_T else None,
        "retrieval_started_before_end_of_turn": bool(calls) and calls[0][0] < EOT_T,
        "end_of_turn_to_next_action_s": round(min(after_eot) - EOT_T, 3) if after_eot else None,
        "end_of_turn_to_first_speech_s": round(min(t for t, _ in speech if t >= EOT_T) - EOT_T, 3),
        "first_speech": next(a.payload["text"] for t, a in speech if t >= EOT_T),
        "correction_to_cancel_s": round(cancels[0] - CHUNKS[2][0], 3) if cancels else None,
        "first_input_to_grounded_answer_s": round(final - CHUNKS[0][0], 3),
        "calls": [f"{a.payload['call_id']} {a.payload['args']['destination']} @{t}" for t, a in calls],
        "speculative_calls_started": len(early),
        "speculative_calls_superseded": len(early & superseded),
        "speculative_late_results_refused": len(early & stale),
        "speculative_state_changing_calls": sum(1 for _, r in rules if r["rule"] == "REC.dispatch" and r.get("early") and r.get("op")),
        "clock": "virtual; mock tools (Delhi 4.0 s, Mumbai 1.0 s); planner 0.25 s virtual",
    }


# ---------------------------------------------------------------- (2) black-box, all scenarios, virtual


def blackbox(agent: str) -> dict:
    from evaluation import harness, metrics
    from evaluation.agents import resolve
    from evaluation.scenario import discover, load
    out: dict = {"agent": agent, "passed": 0, "total": 0, "first_substantive_s": [], "speculative_calls_started": 0,
                 "speculative_calls_superseded": 0, "speculative_late_results_refused": 0,
                 "speculative_state_changing_calls": 0, "scenarios_with_early_work": 0, "tool_calls_total": 0}
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["PRISM_JOURNAL_DIR"] = tmp
        try:
            for path in discover("all"):
                scenario = load(path)
                result = metrics.evaluate(scenario, harness.run(scenario, resolve(agent)))
                out["total"] += 1
                out["passed"] += bool(result["passed"])
                out["first_substantive_s"] += result["latency"]["turn_first_substantive_s"]
                journal = Path(tmp) / f"{scenario['id']}.jsonl"
                recs = [json.loads(line) for line in journal.read_text().splitlines()] if journal.is_file() else []
                rules = [r for rec in recs if rec.get("type") == "step" for r in rec.get("rules", [])]
                early = {r["call_id"] for r in rules if r["rule"] == "REC.dispatch" and r.get("early")}
                out["scenarios_with_early_work"] += bool(early)
                out["tool_calls_total"] += sum(1 for r in rules if r["rule"] == "REC.dispatch")  # the cost of speculating
                out["speculative_calls_started"] += len(early)
                out["speculative_calls_superseded"] += len(early & {r["call_id"] for r in rules if r["rule"] == "REL.supersede"})
                out["speculative_late_results_refused"] += len(early & {r["call_id"] for r in rules if r["rule"] == "ADM.stale"})
                out["speculative_state_changing_calls"] += sum(1 for r in rules if r["rule"] == "REC.dispatch" and r.get("early") and r.get("op"))
        finally:
            os.environ.pop("PRISM_JOURNAL_DIR", None)
    xs = out.pop("first_substantive_s")
    out["first_substantive_response_p50_s"] = round(statistics.median(xs), 3) if xs else None
    out["first_substantive_response_mean_s"] = round(statistics.fmean(xs), 3) if xs else None
    out["clock"] = "virtual; the unchanged black-box evaluator; mock tools"
    return out


# ---------------------------------------------------------------- (3) kernel step cost, wall


def step_cost(duplex: bool, n: int = 200) -> dict:
    per: list[float] = []
    for _ in range(n):
        k = Kernel(Config(full_duplex=duplex))
        k.step(Event(Kind.SESSION_START, 0.0, {}, seq=1))
        k.step(Event(Kind.MANIFEST, 0.0, {"tools": MANIFEST}, seq=2))
        for i, (t, x) in enumerate(CHUNKS):
            t0 = time.perf_counter()
            k.step(Event(Kind.USER_TEXT, t, {"text": x}, seq=3 + i))
            per.append((time.perf_counter() - t0) * 1000)
    per.sort()
    return {"mode": "full duplex" if duplex else "half duplex", "user_chunk_step_ms_p50": round(per[len(per) // 2], 3),
            "p95": round(per[int(len(per) * .95)], 3), "n": len(per), "clock": "wall (decide + apply of one kernel step)"}


# ---------------------------------------------------------------- (4) interruption while a deep planner is busy, wall


def busy_planner(model: str | None) -> dict:
    from agent.reasoner.planner import ModelPlanner, model_available
    real = None
    if model and model_available(f"ollama:{model}"):
        from agent.reasoner.backends import OllamaBackend
        real = ModelPlanner(OllamaBackend(model), timeout_s=60.0)
    rules = RulePlanner(0.0)
    model_ms: list[float] = []

    async def worker(request: dict) -> dict:
        t0 = time.perf_counter()
        if real is not None and request["purpose"] != "speculate":
            _, ev = await asyncio.to_thread(real.respond, request, 0.0)
        elif real is None and request["purpose"] != "speculate":
            await asyncio.sleep(3.0)  # stand-in for a slow model (labelled below)
            _, ev = rules.respond(request, 0.0)
        else:
            _, ev = rules.respond(request, 0.0)
        if request["purpose"] != "speculate":
            model_ms.append((time.perf_counter() - t0) * 1000)
        if ev.kind is not Kind.PROPOSAL:
            raise RuntimeError(ev.payload.get("reason", "failed"))
        return {k: v for k, v in ev.payload.items() if k not in ("req_id", "based_on_seq")}

    async def main() -> dict:
        rt = AsyncRuntime(Kernel(Config(full_duplex=True)), Journal(), WallClock(), planner=Worker(worker, timeout_s=90))
        async with rt:
            for ev in (Event(Kind.SESSION_START, 0, {}), Event(Kind.MANIFEST, 0, {"tools": MANIFEST}),
                       text("Find a flight from Bangalore to Delhi on Friday")):
                rt.submit(dataclasses.replace(ev, t=rt.now()))
            while not any(a.kind is ActionKind.TOOL_CALL for a in rt.actions):
                await asyncio.sleep(0.005)
            rt.submit(dataclasses.replace(eot(), t=rt.now()))  # the finished turn goes to the deep planner
            await rt.drain()
            await asyncio.sleep(0.2)
            busy = not model_ms  # the deep planner has not answered yet
            t0 = time.perf_counter()
            rt.submit(dataclasses.replace(text("wait, cancel that"), t=rt.now()))
            while not any(a.kind is ActionKind.CANCEL for a in rt.actions):
                await asyncio.sleep(0.0005)
            cancel_ms = (time.perf_counter() - t0) * 1000
            while not model_ms:
                await asyncio.sleep(0.05)
            return {"deep_planner": f"ollama:{model}" if real else "stand-in: 3.0 s sleep (no model server)",
                    "planner_busy_when_interrupted": busy, "interruption_to_cancel_ms_while_planner_busy": round(cancel_ms, 2),
                    "deep_planner_execution_ms": round(model_ms[0], 1), "clock": "wall (live AsyncRuntime)"}
    return asyncio.run(main())


# ---------------------------------------------------------------- (5) real ASR and OCR, wall


def real_perception() -> dict:
    asr = ROOT / ".build" / "prism_asr"
    out: dict[str, Any] = {}
    if not (sys.platform == "darwin" and asr.is_file()):
        return {"asr": "not available (macOS helper not built)"}
    files = {}
    for clip in ("find_delhi", "wait_mumbai"):
        t0 = time.perf_counter()
        r = subprocess.run([str(asr), str(ROOT / "demo" / "media" / f"{clip}.aiff")], capture_output=True, text=True)
        files[clip] = {"text": r.stdout.strip(), "wall_s": round(time.perf_counter() - t0, 3)}
    out["asr_file_after_release"] = files
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "c.wav"
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(ROOT / "demo/media/find_delhi.aiff"), str(wav)], check=True)
        with wave.open(str(wav)) as w:
            pcm = w.readframes(w.getnframes())
    p = subprocess.Popen([str(asr), "--stream"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    hyps: list[tuple[float, str, bool]] = []
    t0 = time.perf_counter()

    def read() -> None:
        assert p.stdout is not None
        for line in p.stdout:
            m = json.loads(line)
            hyps.append((time.perf_counter() - t0, m["text"], m["final"]))
    th = threading.Thread(target=read)
    th.start()
    assert p.stdin is not None
    for i in range(0, len(pcm), 3200):  # 100 ms of audio every 100 ms: real time
        p.stdin.write(pcm[i:i + 3200])
        p.stdin.flush()
        time.sleep(0.1)
    audio_end = time.perf_counter() - t0
    p.stdin.close()
    th.join(10)
    out["asr_streaming"] = {
        "audio_s": round(len(pcm) / 32000, 2), "partial_hypotheses": sum(1 for h in hyps if not h[2]),
        "first_partial_at_s": round(hyps[0][0], 2) if hyps else None,
        "partials_before_audio_ended": sum(1 for h in hyps if h[0] < audio_end and not h[2]),
        "final_after_audio_end_s": round(hyps[-1][0] - audio_end, 3) if hyps else None,
        "final_text": hyps[-1][1] if hyps else None}
    if shutil.which("tesseract"):
        t0 = time.perf_counter()
        subprocess.run(["tesseract", str(ROOT / "demo/media/ticket.png"), "stdout"], capture_output=True)
        out["ocr_ticket_wall_s"] = round(time.perf_counter() - t0, 3)
    out["clock"] = "real wall time of the on-device recogniser (Apple Speech) and tesseract on this machine"
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--blackbox", action="store_true", help="also run every scenario through the evaluator (2 agents)")
    ap.add_argument("--model", default="qwen2.5:7b", help="Ollama model for the busy-planner measurement")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    report: dict = {"label": "INTERNAL PRISM-STYLE MEASUREMENTS (not a Samsung score)",
                    "early_retrieval_case": [early_case(False), early_case(True)],
                    "kernel_step_cost": [step_cost(False), step_cost(True)],
                    "busy_deep_planner": busy_planner(args.model),
                    "real_perception": real_perception()}
    if args.blackbox:
        report["blackbox"] = [blackbox("impl_a"), blackbox("impl_a_duplex")]
    text_out = json.dumps(report, indent=2)
    print(text_out)
    if args.out:
        Path(args.out).write_text(text_out + "\n")


if __name__ == "__main__":
    main()
