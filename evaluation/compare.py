"""Compare two evaluation runs (e.g. before/after, or implementation A vs B) on the same scenarios.

    python -m evaluation.compare <before>/results.json <after>/results.json [--out compare.md]

Uses only the machine-readable results (INTERNAL PRISM-STYLE METRICS); never agent internals.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import mean, median

CATS = ("task_completion", "interruption_recovery", "response_latency", "safety_protocol")


def _load(path: str) -> dict:
    data = json.loads(Path(path).read_text())
    return {r["scenario"]: r for r in data["results"]}


def _pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))]


def _lat(results: dict, pred=lambda r: True) -> list[float]:
    return [x for r in results.values() if pred(r) for x in r["latency"]["turn_first_substantive_s"]]


def compare(a_path: str, b_path: str, a_name: str = "before", b_name: str = "after") -> str:
    a, b = _load(a_path), _load(b_path)
    common = sorted(set(a) & set(b))
    f = lambda v: "n/a" if v is None else f"{v:.2f}"  # noqa: E731
    lines = [f"# Evaluation comparison: `{a_name}` vs `{b_name}`", "",
             "INTERNAL PRISM-STYLE METRICS on identical scenario files; not Samsung scores.", "",
             f"| Metric | {a_name} | {b_name} |", "|---|---|---|"]
    pa, pb = [a[s] for s in common], [b[s] for s in common]
    lines.append(f"| scenarios passing all checks | {sum(r['passed'] for r in pa)}/{len(common)} | "
                 f"{sum(r['passed'] for r in pb)}/{len(common)} |")
    lines.append(f"| mean internal score | {mean(r['internal_score'] for r in pa):.1f} | {mean(r['internal_score'] for r in pb):.1f} |")
    for c in CATS:
        va = [r["categories"][c] for r in pa if r["categories"][c] is not None]
        vb = [r["categories"][c] for r in pb if r["categories"][c] is not None]
        lines.append(f"| mean {c} | {f(mean(va) if va else None)} | {f(mean(vb) if vb else None)} |")
    groups = {
        "all turns": lambda r: True,
        "status-question scenarios": lambda r: any("status" in t for t in [r["scenario"]]),
        "state-changing (booking) scenarios": lambda r: "state_changing" in r["tags"] or "booking" in r["scenario"],
    }
    for name, pred in groups.items():
        la, lb = _lat(a, pred), _lat(b, pred)
        lines.append(f"| first substantive response, {name}: p50 / p99 (s) | "
                     f"{f(_pct(la, .5))} / {f(_pct(la, .99))} | {f(_pct(lb, .5))} / {f(_pct(lb, .99))} |")
    ca = [x for r in pa for x in r["latency"]["interrupt_to_cancel_s"]]
    cb = [x for r in pb for x in r["latency"]["interrupt_to_cancel_s"]]
    lines.append(f"| interruption -> cancel: max (s), n | {f(max(ca) if ca else None)}, {len(ca)} | "
                 f"{f(max(cb) if cb else None)}, {len(cb)} |")
    ua = sum(len(r["latency"]["unanswered_turns"]) for r in pa)
    ub = sum(len(r["latency"]["unanswered_turns"]) for r in pb)
    lines.append(f"| turns with no substantive response | {ua} | {ub} |")
    ea = [r["latency"]["end_to_end_s"] for r in pa if r["latency"]["end_to_end_s"] is not None]
    eb = [r["latency"]["end_to_end_s"] for r in pb if r["latency"]["end_to_end_s"] is not None]
    lines.append(f"| end-to-end to last final, median (s) | {f(median(ea) if ea else None)} | {f(median(eb) if eb else None)} |")
    lines += ["", "| Scenario | " + a_name + " pass / score | " + b_name + " pass / score | change |", "|---|---|---|---|"]
    for s in common:
        ra, rb = a[s], b[s]
        delta = rb["internal_score"] - ra["internal_score"]
        mark = "" if abs(delta) < 0.05 and ra["passed"] == rb["passed"] else f"{delta:+.1f}"
        lines.append(f"| {s} | {'yes' if ra['passed'] else '**no**'} / {ra['internal_score']:.1f} | "
                     f"{'yes' if rb['passed'] else '**no**'} / {rb['internal_score']:.1f} | {mark} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--names", default="before,after")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    na, nb = args.names.split(",")
    text = compare(args.a, args.b, na, nb)
    if args.out:
        Path(args.out).write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
