"""INTERNAL PRISM-STYLE METRICS (black-box). Not Samsung scores.

Computed only from the external trace (wire inputs and outputs, in order, with virtual timestamps), the
tool world's ledger, and the scenario's expectations. Categories mirror the documented Theme 05 scoring
(Task Completion 40, Interruption Recovery 35, Response Latency 15, Safety & Protocol 10); the internal
score renormalises the weights over the categories a scenario actually exercises.
"""

from __future__ import annotations

import json
from statistics import median

WEIGHTS = {"task_completion": 40, "interruption_recovery": 35, "response_latency": 15, "safety_protocol": 10}
CANCEL_GRACE_S = 0.01  # "within few ms"; lockstep virtual time makes a same-step cancel exactly 0
LATENCY_FULL_S, LATENCY_ZERO_S = 0.3, 3.0  # "a few hundred milliseconds" -> full marks; linear to zero at 3 s
SUBSTANTIVE = ("clarify", "response.final")


def _match(call: dict, spec: dict) -> bool:
    return call["tool"] == spec["tool"] and all(call["args"].get(k) == v for k, v in spec.get("args", {}).items())


class Trace:
    """Indexed view of the external trace. Positions give exact order, including same-time messages."""

    def __init__(self, trace: dict):
        self.records = trace["records"]
        self.world = trace["world"]
        self.violations = trace["violations"]
        self.inputs: list[tuple[int, float, dict | None]] = []
        self.outputs: list[tuple[int, float, dict]] = []
        for pos, r in enumerate(self.records):
            if r["dir"] == "in":
                try:
                    msg = json.loads(r["raw"])
                except ValueError:
                    msg = None
                self.inputs.append((pos, r["t"], msg if isinstance(msg, dict) else None))
            elif r.get("msg") is not None:
                self.outputs.append((pos, r["t"], r["msg"]))
        self.input_pos: dict[str, tuple[int, float]] = {}
        for pos, t, m in self.inputs:
            if m and isinstance(m.get("id"), str):
                self.input_pos.setdefault(m["id"], (pos, t))
        self.calls: dict[str, dict] = {}
        self.call_ids: list[str] = []
        for pos, t, m in self.outputs:
            if m["type"] == "tool.call":
                d = m["data"]
                self.call_ids.append(d["call_id"])
                self.calls.setdefault(d["call_id"], {"tool": d["tool"], "args": d["args"], "t": t, "pos": pos,
                                                     "idem": d.get("idempotency_key")})
        self.cancels: dict[str, list[tuple[int, float]]] = {}
        for pos, t, m in self.outputs:
            if m["type"] == "tool.cancel":
                self.cancels.setdefault(m["data"]["call_id"], []).append((pos, t))
        self.results: dict[str, list[tuple[int, float, str]]] = {}
        for pos, t, m in self.inputs:
            if m and m.get("type") == "tool.result" and isinstance(m.get("data"), dict):
                self.results.setdefault(m["data"].get("call_id"), []).append((pos, t, m["data"].get("status")))
        self.finals = [(pos, t, m["data"]) for pos, t, m in self.outputs if m["type"] == "response.final"]

    def of_type(self, typ: str) -> list[tuple[int, float, dict]]:
        return [o for o in self.outputs if o[2]["type"] == typ]


def evaluate(scenario: dict, trace: dict) -> dict:
    tr = Trace(trace)
    exp = scenario["expect"]
    checks: list[dict] = []

    def check(cat: str, name: str, ok: bool, **detail) -> None:
        checks.append({"category": cat, "check": name, "passed": bool(ok), **detail})

    # ---------------------------------------------------------------- task completion
    if "final" in exp:
        f = exp["final"]
        last = tr.finals[-1][2] if tr.finals else None
        if f.get("required", True):
            check("task_completion", "final_response_present", last is not None)
        else:
            check("task_completion", "no_final_response", last is None)
        if last is not None and "complete" in f:
            check("task_completion", "final_complete_flag", last.get("complete") == f["complete"], got=last.get("complete"))
        if last is not None and "snapshot" in f:
            want, got = f["snapshot"], last["snapshot"]
            ok = ("intent" not in want or want["intent"] == got["intent"]) and \
                all(got["slots"].get(k) == v for k, v in want.get("slots", {}).items())
            check("task_completion", "final_snapshot_matches", ok, got=got)
        if last is not None and last.get("complete") and "grounded_on" in last:
            fpos = tr.finals[-1][0]
            bad = []
            for cid in last["grounded_on"]:
                ok_before = any(p < fpos and s == "ok" for p, _, s in tr.results.get(cid, []))
                cancelled_before = any(p < fpos for p, _ in tr.cancels.get(cid, []))
                if cid not in tr.calls or not ok_before or cancelled_before:
                    bad.append(cid)
            check("task_completion", "final_grounded_on_completed_current_work", not bad and bool(last["grounded_on"]),
                  bad=bad)
    for spec in exp.get("calls", []):
        n = sum(1 for c in tr.calls.values() if _match(c, spec))
        ok = n >= spec.get("min", 1) and ("max" not in spec or n <= spec["max"])
        check("task_completion", f"calls:{spec['tool']}:{json.dumps(spec.get('args', {}), sort_keys=True)}", ok, count=n)
    for tool, spec in exp.get("side_effects", {}).items():
        n = sum(1 for e in tr.world["side_effects"] if e["tool"] == tool and
                all(e["args"].get(k) == v for k, v in spec.get("args", {}).items()))
        if "min" in spec:
            check("task_completion", f"side_effects_min:{tool}", n >= spec["min"], count=n)
    if "clarify" in exp:
        n = len(tr.of_type("clarify"))
        c = exp["clarify"]
        check("task_completion", "clarification", n >= c.get("min", 0) and n <= c.get("max", 10**9), count=n)

    # ---------------------------------------------------------------- interruption recovery
    cancel_latencies: list[float] = []
    for spec in exp.get("cancels", []):
        apos, at = tr.input_pos[spec["after"]]
        in_flight = [cid for cid, c in tr.calls.items() if c["pos"] < apos and _match(c, spec)
                     and not any(p < apos and s != "cancelled" for p, _, s in tr.results.get(cid, []))]
        for cid in in_flight:
            later = [(p, t) for p, t in tr.cancels.get(cid, []) if p > apos]
            lat = (later[0][1] - at) if later else None
            if lat is not None:
                cancel_latencies.append(lat)
            check("interruption_recovery", f"cancelled:{cid}", lat is not None and lat <= CANCEL_GRACE_S, latency_s=lat)
        check("interruption_recovery", f"invalidated_work_found:{spec['after']}", bool(in_flight),
              note="an invalidation expectation must refer to work in flight at that input")
    if exp.get("no_cancels"):
        check("interruption_recovery", "no_unnecessary_cancel", not tr.cancels, cancelled=sorted(tr.cancels))
    for spec in exp.get("no_calls_after", []):
        apos, _ = tr.input_pos[spec["after"]]
        stale = [cid for cid, c in tr.calls.items() if c["pos"] > apos and _match(c, spec)]
        check("interruption_recovery", f"no_stale_rerun_after:{spec['after']}", not stale, stale=stale)
    if exp.get("not_grounded_on"):
        last = tr.finals[-1][2] if tr.finals else {}
        bad = [cid for cid in last.get("grounded_on", []) for spec in exp["not_grounded_on"]
               if cid in tr.calls and _match(tr.calls[cid], spec)]
        check("interruption_recovery", "answer_not_grounded_on_superseded_work", not bad, bad=bad)

    # ---------------------------------------------------------------- response latency
    turn_latencies, unanswered = [], []
    user_positions = [pos for pos, _, m in tr.inputs if m and m.get("type", "").startswith("user.")]
    for pos, t, m in tr.inputs:
        if not m or m.get("type") != "user.turn_end":
            continue
        nxt = min([p for p in user_positions if p > pos], default=10**9)
        first = next(((p, ot) for p, ot, o in tr.outputs if pos < p < nxt and (
            o["type"] in SUBSTANTIVE or (o["type"] == "speech" and o["data"]["act"] != "filler"))), None)
        if first is None:
            unanswered.append(m.get("id"))
        else:
            turn_latencies.append(first[1] - t)
    rl_scores = [max(0.0, min(1.0, (LATENCY_ZERO_S - lat) / (LATENCY_ZERO_S - LATENCY_FULL_S))) for lat in turn_latencies]

    # ---------------------------------------------------------------- safety and protocol
    check("safety_protocol", "outputs_valid", not tr.violations, violations=len(tr.violations))
    out_ids = [m["id"] for _, _, m in tr.outputs]
    check("safety_protocol", "unique_output_ids", len(out_ids) == len(set(out_ids)))
    check("safety_protocol", "unique_call_ids", len(tr.call_ids) == len(set(tr.call_ids)))
    unknown = [cid for cid in tr.cancels if cid not in tr.calls]
    check("safety_protocol", "cancels_reference_known_calls", not unknown, unknown=unknown)
    late = [cid for cid, cs in tr.cancels.items() for p, _ in cs
            if any(rp < p and s != "cancelled" for rp, _, s in tr.results.get(cid, []))]
    check("safety_protocol", "no_cancel_after_known_result", not late, calls=late)
    doubles = [cid for cid, cs in tr.cancels.items() if len(cs) > 1]
    check("safety_protocol", "at_most_one_cancel_per_call", not doubles, calls=doubles)
    for tool, spec in exp.get("side_effects", {}).items():
        if "max" in spec:
            n = sum(1 for e in tr.world["side_effects"] if e["tool"] == tool)
            check("safety_protocol", f"side_effects_max:{tool}", n <= spec["max"], count=n)
    for tool in exp.get("same_idempotency_key", []):
        keys = {c["idem"] for c in tr.calls.values() if c["tool"] == tool}
        check("safety_protocol", f"same_idempotency_key:{tool}", len(keys) == 1 and None not in keys, keys=len(keys))
    for spec in exp.get("final_forbidden", []):
        bad = [d for _, _, d in tr.finals if d.get("complete", True)
               and all(d["snapshot"]["slots"].get(k) == v for k, v in spec.get("slots", {}).items())]
        check("safety_protocol", f"no_false_completion:{json.dumps(spec, sort_keys=True)}", not bad)
    n_err = len(tr.of_type("protocol.error"))
    check("safety_protocol", "protocol_errors_as_expected", n_err == exp.get("protocol_errors", 0), count=n_err)

    # ---------------------------------------------------------------- naturalness proxies (reported, not scored)
    fillers = sum(1 for _, _, o in tr.of_type("speech") if o["data"]["act"] == "filler")
    open_turn, spoke_over = False, 0
    events = sorted([(p, "in", m) for p, _, m in tr.inputs] + [(p, "out", m) for p, _, m in tr.outputs], key=lambda x: x[0])
    for _, d, m in events:
        if d == "in" and m:
            if m.get("type") in ("user.text", "user.audio", "user.frame"):
                open_turn = True
            elif m.get("type") == "user.turn_end":
                open_turn = False
        elif d == "out" and open_turn and m is not None and m["type"] in ("speech", "clarify", "response.final"):
            spoke_over += 1
    texts = [o["data"]["text"] for _, _, o in tr.outputs if o["type"] in ("speech", "clarify")]
    repeats = sum(1 for a, b in zip(texts, texts[1:], strict=False) if a == b)

    # ---------------------------------------------------------------- scores
    cats: dict[str, float | None] = {}
    for cat in ("task_completion", "interruption_recovery", "safety_protocol"):
        cs = [c for c in checks if c["category"] == cat]
        cats[cat] = (sum(c["passed"] for c in cs) / len(cs)) if cs else None
    cats["response_latency"] = (sum(rl_scores) / len(rl_scores)) if rl_scores else None
    applicable = {k: v for k, v in cats.items() if v is not None}
    total_w = sum(WEIGHTS[k] for k in applicable)
    score = 100 * sum(WEIGHTS[k] * v for k, v in applicable.items()) / total_w if total_w else 0.0
    return {
        "scenario": scenario["id"], "tags": scenario.get("tags", []),
        "label": "INTERNAL PRISM-STYLE METRICS (not a Samsung score)",
        "passed": all(c["passed"] for c in checks),
        "internal_score": round(score, 2),
        "categories": {k: (round(v, 4) if v is not None else None) for k, v in cats.items()},
        "latency": {
            "turn_first_substantive_s": [round(x, 6) for x in turn_latencies],
            "turn_first_substantive_p50_s": round(median(turn_latencies), 6) if turn_latencies else None,
            "interrupt_to_cancel_s": [round(x, 6) for x in cancel_latencies],
            "unanswered_turns": unanswered,
            "end_to_end_s": round(tr.finals[-1][1] - tr.inputs[0][1], 6) if tr.finals and tr.inputs else None,
        },
        "naturalness": {"fillers": fillers, "speech_while_user_speaking": spoke_over, "repeated_utterances": repeats},
        "multimodal": "multimodal" in scenario.get("tags", []),
        "checks": checks,
    }
