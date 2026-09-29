"""The mock tool world: executes tool calls the agent emits, with scripted latency and faults, and keeps
its OWN ledger of what really happened (calls received, cancels received, results delivered, side effects).

A state-changing tool performs its side effect when its `ok` result is delivered. So a booking that
"completes despite a cancel" is a real side effect here, whatever the agent believes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _flights(args: dict, n: int) -> dict:
    return {"flights": [{"id": f"{args.get('destination', 'X')}-701", "date": args.get("date"), "price": 4120}]}


def _booking(args: dict, n: int) -> dict:
    return {"booking_id": f"B{n}", "passengers": args.get("passengers")}


def _weather(args: dict, n: int) -> dict:
    return {"city": args.get("city"), "temp_c": 31}


GENERATORS = {"flights": _flights, "booking": _booking, "weather": _weather, "echo": lambda a, n: {"args": a}}


@dataclass
class Call:
    call_id: str
    tool: str
    args: dict
    t_call: float
    idempotency_key: str | None
    attempt: int
    t_cancel: float | None = None
    deliveries: list = field(default_factory=list)  # (t, status)
    executed: bool = False


class World:
    def __init__(self, spec: dict, manifest: list[dict]):
        self.spec = spec
        self.state_changing = {m["name"] for m in manifest if isinstance(m, dict) and m.get("effect") == "state_changing"}
        self.calls: dict[str, Call] = {}
        self.effects: list[dict] = []  # executed side effects
        self.events: list[dict] = []  # world-side trace
        self._attempts: dict[str, int] = {}
        self._pending: dict[str, list[dict]] = {}  # call_id -> scheduled deliveries (not yet sent)
        self._n_effect = 0
        self._n = 0

    def _tool(self, name: str) -> dict:
        return self.spec.get(name, {})

    def _next_id(self) -> str:
        self._n += 1
        return f"w{self._n}"

    # ------------------------------------------------------------ agent outputs arrive here

    def on_output(self, msg: dict, t: float) -> list[tuple[float, dict]]:
        """Returns deliveries to schedule: (t, delivery) where delivery is later passed to deliver()."""
        typ, data = msg.get("type"), msg.get("data", {})
        if typ == "tool.call":
            return self._on_call(data, t)
        if typ == "tool.cancel":
            return self._on_cancel(data["call_id"], t)
        return []

    def _on_call(self, data: dict, t: float) -> list[tuple[float, dict]]:
        tool = data["tool"]
        attempt = self._attempts.get(tool, 0)
        self._attempts[tool] = attempt + 1
        call = Call(data["call_id"], tool, dict(data["args"]), t, data.get("idempotency_key"), attempt)
        self.calls[call.call_id] = call
        self.events.append({"t": t, "event": "call_received", "call_id": call.call_id, "tool": tool, "args": call.args})
        spec = self._tool(tool)
        behaviors = spec.get("behaviors") or [{"latency": 0.5, "status": "ok", "gen": "echo"}]
        b = behaviors[min(attempt, len(behaviors) - 1)]
        out: list[tuple[float, dict]] = []
        if b.get("latency") is None and "at" not in b:
            return out  # never answers
        when = b["at"] if "at" in b else t + b["latency"]
        delivery = {"call_id": call.call_id, "status": b.get("status", "ok"), "executed": b.get("executed"),
                    "data": self._data(b, call)}
        out.append((when, delivery))
        if b.get("duplicate"):
            out.append((when, dict(delivery)))
        if "followup" in b:
            f = b["followup"]
            out.append((when + f["after"], {"call_id": call.call_id, "status": f.get("status", "ok"),
                                           "executed": f.get("executed"), "data": self._data(f, call)}))
        self._pending[call.call_id] = [d for _, d in out]
        return out

    def _data(self, b: dict, call: Call) -> Any:
        if "gen" in b:
            return GENERATORS[b["gen"]](call.args, self._n_effect + 1)
        return b.get("data")

    def _on_cancel(self, call_id: str, t: float) -> list[tuple[float, dict]]:
        call = self.calls.get(call_id)
        self.events.append({"t": t, "event": "cancel_received", "call_id": call_id, "known_call": call is not None})
        if call is None:
            return []
        call.t_cancel = t if call.t_cancel is None else call.t_cancel
        spec = self._tool(call.tool)
        pending = self._pending.get(call_id, [])
        if spec.get("honors_cancel") and pending and not call.deliveries:
            for d in pending:
                d["suppressed"] = True  # the real result will never be sent
            ack = {"call_id": call_id, "status": "cancelled", "executed": False, "data": None}
            self.events.append({"t": t, "event": "cancel_honoured", "call_id": call_id})
            return [(t + spec.get("cancel_latency", 0.05), ack)]
        self.events.append({"t": t, "event": "cancel_ignored", "call_id": call_id})
        return []

    # ------------------------------------------------------------ delivering results

    def deliver(self, delivery: dict, t: float) -> dict | None:
        """Called when a scheduled delivery is due. Returns the tool.result data to send, or None."""
        if delivery.get("suppressed"):
            return None
        call = self.calls[delivery["call_id"]]
        status = delivery["status"]
        call.deliveries.append((t, status))
        self.events.append({"t": t, "event": "result_delivered", "call_id": call.call_id, "status": status})
        if status == "ok" and call.tool in self.state_changing and not call.executed:
            spec = self._tool(call.tool)
            dup = spec.get("idempotent") and call.idempotency_key and any(
                e["idempotency_key"] == call.idempotency_key for e in self.effects)
            call.executed = True
            if not dup:
                self._n_effect += 1
                self.effects.append({"t": t, "tool": call.tool, "call_id": call.call_id, "args": call.args,
                                     "idempotency_key": call.idempotency_key})
                self.events.append({"t": t, "event": "side_effect", "call_id": call.call_id, "tool": call.tool})
        out = {"call_id": call.call_id, "status": status}
        if delivery.get("data") is not None:
            out["data"] = delivery["data"]
        if delivery.get("executed") is not None:
            out["executed"] = delivery["executed"]
        return out

    def ledger(self) -> dict:
        return {
            "calls": {cid: {"tool": c.tool, "args": c.args, "t_call": c.t_call, "idempotency_key": c.idempotency_key,
                            "t_cancel": c.t_cancel, "deliveries": c.deliveries, "executed": c.executed}
                      for cid, c in self.calls.items()},
            "side_effects": self.effects,
            "events": self.events,
        }
