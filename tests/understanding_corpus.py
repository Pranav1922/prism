"""Score the fast-understanding corpus (tests/data/fast_understanding_corpus.json). Internal measurement only."""

from __future__ import annotations

import json
import time
from pathlib import Path

from agent.understand import SlotInfo, UnderstandContext
from agent.understand_rules import recognize

CORPUS = Path(__file__).resolve().parent / "data" / "fast_understanding_corpus.json"


def load_contexts(data: dict) -> dict[str, UnderstandContext]:
    out = {}
    for name, c in data["contexts"].items():
        slots = tuple(SlotInfo(s["name"], s["value"], s["schema"], tuple(tuple(h) for h in s["history"]))
                      for s in c["slots"])
        out[name] = UnderstandContext(c["intent"], slots, tuple((k, tuple(sl), a) for k, sl, a in c["pending"]),
                                      tuple(tuple(u) for u in c["utterances"]), "")
    return out


def score(repeat: int = 1, split: str = "items") -> dict:
    """split: "items" (development set, tuned on) or "holdout_items" (written after tuning, never tuned on)."""
    data = json.loads(CORPUS.read_text())
    ctxs = load_contexts(data)
    rows, times = [], []
    for item in data[split]:
        for _ in range(repeat):
            t0 = time.perf_counter()
            u = recognize(item["text"], {}, ctxs[item["context"]])
            times.append((time.perf_counter() - t0) * 1000)
        writes = dict(u.writes)
        wrong_slots = [k for k in writes if k not in item["writes"] or writes[k] != item["writes"][k]]
        rows.append({
            "text": item["text"], "context": item["context"], "group": item["group"],
            "want_cls": item["cls"], "got_cls": u.cls.value, "want_writes": item["writes"], "got_writes": writes,
            "cls_ok": u.cls.value == item["cls"] and u.confirm == item["confirm"],
            "writes_ok": writes == item["writes"],
            "false_correction": item["cls"] not in ("CORRECTION", "GOAL_SWITCH") and u.cls.value in ("CORRECTION", "GOAL_SWITCH"),
            "unsafe": bool(wrong_slots),  # wrote a slot the user did not refer to, or a wrong value
            "cues": list(u.cues),
        })
    n = len(rows)
    non_corr = [r for r in rows if r["want_cls"] not in ("CORRECTION", "GOAL_SWITCH")]
    times.sort()
    return {
        "items": n,
        "classification_accuracy": sum(r["cls_ok"] for r in rows) / n,
        "slot_extraction_accuracy": sum(r["writes_ok"] for r in rows) / n,
        "false_correction_rate": sum(r["false_correction"] for r in non_corr) / len(non_corr),
        "unsafe_interpretation_rate": sum(r["unsafe"] for r in rows) / n,
        "latency_ms": {"p50": times[len(times) // 2], "p95": times[int(.95 * len(times))],
                       "p99": times[int(.99 * len(times))], "max": times[-1], "n": len(times)},
        "errors": [r for r in rows if not (r["cls_ok"] and r["writes_ok"])],
    }


if __name__ == "__main__":
    for split in ("items", "holdout_items"):
        res = score(repeat=50, split=split)
        print(f"== {split}")
        for k, v in res.items():
            if k != "errors":
                print(k, v)
        for e in res["errors"]:
            print("ERR", e["context"], repr(e["text"]), "want", e["want_cls"], e["want_writes"], "got", e["got_cls"],
                  e["got_writes"], e["cues"])
