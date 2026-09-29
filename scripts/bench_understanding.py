"""Phase 4 benchmark: fast-understanding latency (wall-clock on the dev machine, indicative only).

    python scripts/bench_understanding.py [repeat]

recognize() alone over both corpus splits, and in-process agent.handle() for the correction line
("actually, to Mumbai" -> tool.cancel) with the rule recogniser vs the scripted table.
"""

from __future__ import annotations

import json
import sys
import time

from agent.adapter.stdio import DEFAULT_FIXTURES, LocalAgent
from scripts.bench_adapter import session_lines
from tests.understanding_corpus import score


def pct(xs: list[float], p: float) -> float:
    return sorted(xs)[min(len(xs) - 1, int(p * len(xs)))]


def main() -> None:
    repeat = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    out: dict = {"label": "wall-clock on the dev machine (indicative)"}
    for split in ("items", "holdout_items"):
        lat = score(repeat=repeat, split=split)["latency_ms"]
        out[f"recognize_ms_{split}"] = {k: round(v, 4) if isinstance(v, float) else v for k, v in lat.items()}
    fixtures = json.loads(DEFAULT_FIXTURES.read_text())
    lines = session_lines()
    for mode in ("rules", "scripted"):
        fix: list[float] = []
        for _ in range(repeat):
            agent = LocalAgent(fixtures, understanding=mode)
            for name, line in lines:
                t0 = time.perf_counter()
                outs = agent.handle(line)
                if name == "fix":
                    fix.append((time.perf_counter() - t0) * 1000)
                    assert any('"tool.cancel"' in o for o in outs)
        out[f"handle_correction_ms_{mode}"] = {p: round(pct(fix, q), 4) for p, q in
                                               (("p50", .5), ("p95", .95), ("p99", .99), ("max", 1.0))}
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
