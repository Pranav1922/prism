"""Response wording (pure). The kernel decides WHETHER an act is allowed (INV-20: no speech while the user holds the
floor; answers only from DESIRED+OK calls or COMMITTED operations); this module only turns state and admitted results
into short, truthful sentences. Nothing here claims more than its inputs show."""

from __future__ import annotations

import json
from typing import Any


def words(tool: str) -> str:
    return tool.replace("_", " ").replace("-", " ")


def args_text(args: dict) -> str:
    return ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in sorted(args.items()))


def working_on(calls: list[tuple[str, dict]]) -> str:
    """Request accepted / searching: what was just started (never a completion claim)."""
    return "On it: " + "; ".join(f"{words(t)} ({args_text(a)})" for t, a in calls) + "."


def accepted() -> str:
    return "Got it, working that out."


def correction(slots: list[str]) -> str:
    return f"Okay, changing the {' and '.join(s.replace('_', ' ') for s in slots)}."


def summarise(data: Any, limit: int = 140) -> str:
    """A compact, literal summary of an admitted tool result (first list item's scalar fields, or scalar fields)."""
    if isinstance(data, dict):
        lists = [(k, v) for k, v in data.items() if isinstance(v, list)]
        if lists:
            k, items = lists[0]
            if not items:
                return f"no {k}"
            first = items[0]
            head = ", ".join(f"{a} {b}" for a, b in first.items() if isinstance(b, (str, int, float))) \
                if isinstance(first, dict) else str(first)
            text = f"{len(items)} {k}; first: {head}" if len(items) > 1 else f"{k[:-1] if k.endswith('s') else k}: {head}"
        else:
            text = ", ".join(f"{a.replace('_', ' ')} {b}" for a, b in data.items() if isinstance(b, (str, int, float)))
    else:
        text = json.dumps(data, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def done(results: list[tuple[str, Any]], committed: list[str]) -> str:
    """Completed task: grounded only on the calls/operations the kernel passes in."""
    parts = [f"{words(tool)} done: {summarise(data)}" for tool, data in results]
    parts += [f"{words(tool)} went through" for tool in committed if tool not in {t for t, _ in results}]
    return "; ".join(parts) + "." if parts else "Done."
