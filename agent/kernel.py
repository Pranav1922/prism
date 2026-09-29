"""Session kernel: the single writer of session state (FINAL ARCHITECTURE F2–F7).

step(event) = decide(state, event) -> StepResult, then apply(changes).
  * decide reads state through a write-overlay (Tx) and never mutates state (INV-01);
  * apply is the ONLY code that writes state; it performs plain assignments;
  * nothing here reads a clock, sleeps, performs I/O or calls a model; "now" is event.t (INV-02).

Reconciliation is level-triggered: after every event the kernel recomputes the ACTIVE goal's desired key
set and reconciles calls against it (supersede / dispatch / keep), so duplicated or reordered events
cannot desynchronise it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any

from agent.model import (
    KNOWN_OUTCOMES,
    OUTCOME_MOVES,
    Action,
    ActionKind,
    Call,
    Effect,
    Event,
    Frame,
    Goal,
    GoalStatus,
    Node,
    OpState,
    Outcome,
    Pending,
    Register,
    Relevance,
    Request,
    Timer,
    Turn,
    TurnClass,
    canonical_json,
    content_key,
    idempotency_key,
    snapshot,
)
from agent.registry import ArgError, Registry
from agent.understand import SlotInfo, UnderstandContext, Understanding
from agent.understand_rules import recognize

TABLES = ("meta", "goals", "slots", "calls", "ops", "frames", "timers", "pending", "reqs")
RETRY_REASONS = ("timeout", "error", "unknown")
MARKERS = (TurnClass.CORRECTION, TurnClass.GOAL_SWITCH)


@dataclass(frozen=True)
class Config:
    silence_s: float = 1.0  # inferred end of turn / content-free interrupt clearing (D4)
    deadline_s: float = 110.0  # deadline governor, before the 120 s cap
    tool_timeout_s: float = 5.0  # default when the manifest gives none
    ro_max_attempts: int = 3  # read-only: at most 2 retries
    sm_max_same_args: int = 2  # state-changing: one retry with identical arguments
    evidence_theta: float = 0.8


def _meta_defaults() -> dict:
    return {
        "rev": 0, "last_content_seq": 0, "active_goal": None, "hold": False, "turn": None,
        "goal_switch_seq": 0, "registry": Registry(), "n_call": 0, "n_action": 0, "n_goal": 0,
        "n_req": 0, "n_percept": 0, "deadline_passed": False, "session_ended": False,
        "switch_pending": None,  # D11: goal whose work is withheld until the planner answers a goal switch
        "utterances": (),  # ((based_seq, text), ...) of recent closed content turns: fast-understanding context
    }


class State:
    """Session state: named tables of immutable values. Mutated only by Kernel.apply."""

    def __init__(self) -> None:
        self.t: dict[str, dict] = {name: {} for name in TABLES}
        self.t["meta"].update(_meta_defaults())

    def get(self, table: str, key: Any, default: Any = None) -> Any:
        value = self.t[table].get(key, default)
        return default if value is None else value

    def items(self, table: str) -> list[tuple[Any, Any]]:
        return [(k, v) for k, v in self.t[table].items() if v is not None]

    def dump(self) -> str:
        return canonical_json({name: [[k, v] for k, v in rows.items()] for name, rows in self.t.items()})


class Tx:
    """Read-your-writes overlay used by decide. Writing None deletes."""

    def __init__(self, state: State):
        self.state = state
        self.w: dict[str, dict] = {name: {} for name in TABLES}
        self.order: list[tuple[str, Any]] = []

    def get(self, table: str, key: Any, default: Any = None) -> Any:
        w = self.w[table]
        if key in w:
            return default if w[key] is None else w[key]
        return self.state.get(table, key, default)

    def set(self, table: str, key: Any, value: Any) -> None:
        if key not in self.w[table]:
            self.order.append((table, key))
        self.w[table][key] = value

    def items(self, table: str) -> list[tuple[Any, Any]]:
        merged = dict(self.state.t[table])
        merged.update(self.w[table])
        return [(k, v) for k, v in merged.items() if v is not None]

    def changes(self) -> list[tuple[str, Any, Any]]:
        out = []
        for table, key in self.order:
            new = self.w[table][key]
            if self.state.t[table].get(key) != new:
                out.append((table, key, new))
        return out


@dataclass
class StepResult:
    seq: int
    rev_before: int
    rev_after: int
    changes: list
    actions: list[Action]
    effects: list[dict]
    rules: list[dict]
    desired: dict = field(default_factory=dict)


# ---------------------------------------------------------------- pure derivations (shared with tests)


@dataclass(frozen=True)
class Desired:
    node: Node
    key: str | None
    args: dict | None
    uses: tuple[str, ...] = ()
    error: str | None = None


_MISSING = object()


def _path(data: Any, path: tuple) -> Any:
    for step in path:
        if isinstance(data, dict) and step in data:
            data = data[step]
        elif isinstance(data, list) and isinstance(step, int) and -len(data) <= step < len(data):
            data = data[step]
        else:
            return _MISSING
    return data


def active_goal(r: Any) -> Goal | None:
    gid = r.get("meta", "active_goal")
    goal = r.get("goals", gid) if gid else None
    return goal if goal is not None and goal.status is GoalStatus.ACTIVE else None


def desired_ok_call(r: Any, goal_id: str, key: str | None) -> Call | None:
    for _, c in r.items("calls"):
        if c.goal_id == goal_id and c.key == key and c.relevance is Relevance.DESIRED and c.outcome is Outcome.OK:
            return c
    return None


def resolve(r: Any, goal: Goal | None) -> list[Desired]:
    """Resolve the goal's task graph against current registers and DESIRED upstream results."""
    if goal is None:
        return []
    registry: Registry = r.get("meta", "registry")
    out: list[Desired] = []
    node_key: dict[str, str] = {}
    for node in goal.graph:
        spec = registry.get(node.tool)
        if spec is None:
            out.append(Desired(node, None, None, (), "unknown_tool"))
            continue
        args: dict = {}
        uses: list[str] = []
        ok = True
        for param, b in node.args:
            if b[0] == "slot":
                reg = r.get("slots", (goal.goal_id, b[1]))
                if reg is None or reg.value is None:
                    ok = False
                    break
                args[param] = reg.value
            elif b[0] == "node":
                upstream = desired_ok_call(r, goal.goal_id, node_key.get(b[1]))
                value = _path(json.loads(upstream.result_json), b[2]) if upstream and upstream.result_json else _MISSING
                if value is _MISSING:
                    ok = False
                    break
                args[param] = value
                uses.append(upstream.call_id)  # type: ignore[union-attr]
            else:
                args[param] = b[1]
        if not ok:
            out.append(Desired(node, None, None))
            continue
        try:
            canon = spec.canonicalize(args)
        except ArgError as exc:
            out.append(Desired(node, None, None, (), str(exc)))
            continue
        key = content_key(node.tool, canon)
        node_key[node.node_id] = key
        out.append(Desired(node, key, canon, tuple(uses)))
    return out


def op_state(r: Any, op_id: tuple) -> OpState:
    outcomes = [r.get("calls", cid).outcome for cid in r.get("ops", op_id, ())]
    if Outcome.OK in outcomes:
        return OpState.COMMITTED
    if Outcome.PENDING in outcomes or Outcome.UNKNOWN in outcomes:
        return OpState.LOCKED
    return OpState.FREE


def committed_attempt(r: Any, op_id: tuple) -> Call | None:
    for cid in r.get("ops", op_id, ()):
        call = r.get("calls", cid)
        if call.outcome is Outcome.OK:
            return call
    return None


# ---------------------------------------------------------------- the kernel


class Kernel:
    def __init__(self, config: Config | None = None,
                 understand: Callable[..., Understanding] = recognize):
        self.config = config or Config()
        self.understand = understand
        self.state = State()

    def step(self, event: Event) -> StepResult:
        try:
            result = self.decide(self.state, event)
        except Exception as exc:  # state is untouched; journal a poison record
            result = self._poison(event, exc)
        self.apply(result.changes)
        return result

    def apply(self, changes: list) -> None:
        """The only place session state changes."""
        for table, key, value in changes:
            self.state.t[table][key] = value
        if changes:
            self.state.t["meta"]["rev"] += 1

    def decide(self, state: State, event: Event) -> StepResult:
        s = _Step(Tx(state), event, self.config, self.understand)
        before = s.desired_keys(state)
        getattr(s, "on_" + event.kind.name.lower())()
        s.reconcile(before)
        s.speak()
        actions = s.finish_actions()
        changes = s.tx.changes()
        rev = state.t["meta"]["rev"]
        return StepResult(event.seq, rev, rev + (1 if changes else 0), changes, actions, s.effects, s.rules,
                          s.desired_keys(s.tx, with_rev=True))

    def _poison(self, event: Event, exc: Exception) -> StepResult:
        rev = self.state.t["meta"]["rev"]
        rules = [{"rule": "KERNEL.poison", "error": f"{type(exc).__name__}: {exc}"}]
        turn = self.state.get("meta", "turn")
        if turn is not None and turn.open:
            return StepResult(event.seq, rev, rev, [], [], [], rules)
        n = self.state.t["meta"]["n_action"] + 1
        action = Action(f"a{n}", ActionKind.SPEAK, event.seq, "KERNEL.poison", (event.seq,),
                        {"text": "Sorry, something went wrong on my side.", "act": "filler", "grounded_on": []})
        return StepResult(event.seq, rev, rev + 1, [("meta", "n_action", n)], [action], [], rules)


class _Step:
    """Everything decided while processing one event."""

    def __init__(self, tx: Tx, event: Event, config: Config, understand: Callable):
        self.tx, self.ev, self.cfg, self.understand = tx, event, config, understand
        self.seq, self.now = event.seq, event.t
        self.payload: dict = event.payload or {}
        self.rules: list[dict] = []
        self.effects: list[dict] = []
        self._actions: list[tuple] = []
        self.dispatched: list[Call] = []
        self.want_snapshot = False
        self.closed_turn: Turn | None = None  # the user turn this step closed (drives turn-close responses)

    # ------------------------------------------------------------ small helpers

    def rule(self, name: str, **info: Any) -> None:
        self.rules.append({"rule": name, **info})

    def meta(self, key: str) -> Any:
        return self.tx.get("meta", key)

    def set_meta(self, key: str, value: Any) -> None:
        self.tx.set("meta", key, value)

    def next_n(self, counter: str) -> int:
        n = self.meta(counter) + 1
        self.set_meta(counter, n)
        return n

    def emit(self, kind: ActionKind, rule: str, payload: dict) -> None:
        self._actions.append((kind, rule, payload))

    def arm(self, timer_id: str, purpose: str, due_t: float, ref: str | None = None) -> None:
        self.tx.set("timers", timer_id, Timer(timer_id, purpose, due_t, ref))
        self.effects.append({"effect": "arm", "timer_id": timer_id, "purpose": purpose, "due_t": due_t, "ref": ref})

    def disarm(self, timer_id: str) -> None:
        if self.tx.get("timers", timer_id) is not None:
            self.tx.set("timers", timer_id, None)
            self.effects.append({"effect": "disarm", "timer_id": timer_id})

    def turn(self) -> Turn | None:
        return self.meta("turn")

    def turn_open(self) -> bool:
        t = self.turn()
        return t is not None and t.open

    def registry(self) -> Registry:
        return self.meta("registry")

    def desired_keys(self, r: Any, with_rev: bool = False) -> dict:
        goal = active_goal(r)
        if goal is None:
            return {}
        keys = [d.key for d in resolve(r, goal) if d.key]
        return {goal.goal_id: {"plan_rev": goal.plan_rev, "keys": keys}} if with_rev else {goal.goal_id: keys}

    def finish_actions(self) -> list[Action]:
        rank = {ActionKind.CANCEL: 0, ActionKind.TOOL_CALL: 1}
        ordered = sorted(self._actions, key=lambda a: rank.get(a[0], 2))  # stable: cancels first (INV-03)
        out = []
        for kind, rule, payload in ordered:
            n = self.next_n("n_action")
            out.append(Action(f"a{n}", kind, self.seq, rule, (self.seq,), payload))
        return out

    # ------------------------------------------------------------ registers (last writer wins)

    def write_register(self, goal_id: str, name: str, value: Any, writer_seq: int, source: str, confirmed: bool) -> bool:
        key = (goal_id, name)
        reg = self.tx.get("slots", key)
        if reg is not None and writer_seq < reg.writer_seq:
            self.rule("LWW.reject", slot=name, writer_seq=writer_seq, current_seq=reg.writer_seq)
            return False
        if reg is not None and reg.value == value:
            upgraded = replace(reg, writer_seq=max(reg.writer_seq, writer_seq), confirmed=reg.confirmed or confirmed)
            self.tx.set("slots", key, upgraded)
            self.rule("LWW.reassert", slot=name, writer_seq=writer_seq)
            return True
        history = (reg.history + ((reg.value, reg.writer_seq, reg.source),)) if reg else ()
        self.tx.set("slots", key, Register(value, writer_seq, source, confirmed, history))
        self.rule("LWW.apply", slot=name, value=value, writer_seq=writer_seq, source=source)
        return True

    # ------------------------------------------------------------ calls: supersede, outcome, dispatch

    def supersede(self, call: Call, reason: str) -> None:
        call = self.tx.get("calls", call.call_id)  # re-read: the caller's copy may be stale within this step
        if call.relevance is Relevance.SUPERSEDED:
            return
        self.tx.set("calls", call.call_id,
                    replace(call, relevance=Relevance.SUPERSEDED, superseded_reason=reason, superseded_seq=self.seq))
        self.rule("REL.supersede", call_id=call.call_id, key=call.key, reason=reason)
        spec = self.registry().get(call.tool)
        cancellable = spec.cancellable if spec is not None else None
        if call.outcome not in KNOWN_OUTCOMES and (call.effect is Effect.READ_ONLY or cancellable is not False):
            self.emit(ActionKind.CANCEL, "REL.supersede", {"call_id": call.call_id, "reason": reason})  # D7
        if call.effect is Effect.READ_ONLY:
            self.disarm(f"to:{call.call_id}")

    def set_outcome(self, call: Call, outcome: Outcome, data: Any = None) -> bool:
        if outcome not in OUTCOME_MOVES[call.outcome]:
            return False
        result_json = canonical_json(data) if outcome is Outcome.OK else call.result_json
        self.tx.set("calls", call.call_id, replace(call, outcome=outcome, result_json=result_json))
        self.rule("ADM.outcome", call_id=call.call_id, frm=call.outcome.value, to=outcome.value)
        if call.outcome is Outcome.FAILED_CLEAN and outcome is Outcome.OK:
            self.rule("ADM.anomaly", call_id=call.call_id)
        if outcome in KNOWN_OUTCOMES:
            self.disarm(f"to:{call.call_id}")
        return True

    def dispatch(self, goal: Goal, d: Desired, op_id: tuple | None = None) -> None:
        spec = self.registry().get(d.node.tool)
        assert spec is not None and d.args is not None and d.key is not None
        cid = f"c{self.next_n('n_call')}"
        idem = idempotency_key(op_id, d.args) if op_id else None
        call = Call(cid, goal.goal_id, d.node.node_id, spec.name, canonical_json(d.args), d.key, spec.effect,
                    Relevance.DESIRED, Outcome.PENDING, self.seq, op_id, idem)
        self.tx.set("calls", cid, call)
        if op_id is not None:
            self.tx.set("ops", op_id, self.tx.get("ops", op_id, ()) + (cid,))
        payload = {"call_id": cid, "tool": spec.name, "args": d.args, "uses": list(d.uses)}
        if idem:
            payload["idempotency_key"] = idem
        self.emit(ActionKind.TOOL_CALL, "REC.dispatch", payload)
        self.rule("REC.dispatch", call_id=cid, key=d.key, node=d.node.node_id, op=list(op_id) if op_id else None)
        self.arm(f"to:{cid}", "tool_timeout", self.now + (spec.timeout_s or self.cfg.tool_timeout_s), cid)
        self.dispatched.append(call)

    def calls_for(self, goal_id: str, key: str) -> list[Call]:
        return [c for _, c in self.tx.items("calls") if c.goal_id == goal_id and c.key == key]

    def ensure_pending(self, goal_id: str, kind: str, slots: tuple, text: str, disc: str = "") -> None:
        pid = f"{kind}:{goal_id}:{disc}"
        if self.tx.get("pending", pid) is None:
            self.tx.set("pending", pid, Pending(pid, goal_id, kind, slots, text, False, self.seq))
            self.rule("PENDING.open", pid=pid)

    def resolve_pendings(self, goal_id: str, slots: tuple | None) -> None:
        for pid, p in self.tx.items("pending"):
            if p.goal_id == goal_id and not p.resolved and p.kind in ("conflict", "planner_clarify") and \
                    (slots is None or set(p.slots) & set(slots)):
                self.tx.set("pending", pid, replace(p, resolved=True))
                self.rule("PENDING.resolved", pid=pid)

    # ------------------------------------------------------------ turns and the planner request

    def close_turn(self, inferred: bool) -> None:
        turn = self.turn()
        if turn is None or not turn.open:
            self.rule("TURN.empty")
            return
        self.set_meta("turn", replace(turn, open=False))
        self.rule("TURN.close", turn_id=turn.turn_id, inferred=inferred)
        self.closed_turn = turn
        if turn.content:
            self.set_meta("utterances", (*self.meta("utterances"), (self.meta("last_content_seq"), turn.text))[-12:])
        if self.meta("hold"):
            self.set_meta("hold", False)
            self.rule("HOLD.clear", by="turn_close")
        self.disarm("eot")
        for goal_id, name, wseq in turn.t0_writes:  # F3: unambiguous T0 attribution in a closed turn
            reg = self.tx.get("slots", (goal_id, name))
            if reg and reg.writer_seq == wseq and reg.source == "T0" and not reg.confirmed \
                    and not any(m > wseq for m in turn.marker_seqs):
                self.tx.set("slots", (goal_id, name), replace(reg, confirmed=True))
                self.rule("SLOT.confirm", slot=name, by="closed_turn")
        if turn.interrupting and turn.t0_writes:
            self.want_snapshot = True
        if turn.content and not self.meta("deadline_passed"):
            self.request_planner(turn)

    def request_planner(self, turn: Turn) -> None:
        for rid, req in self.tx.items("reqs"):
            if req.open:
                self.tx.set("reqs", rid, replace(req, open=False))
                self.effects.append({"effect": "cancel_effect", "target": "reasoner", "req_id": rid})
        rid = f"r{self.next_n('n_req')}"
        based = self.meta("last_content_seq")
        self.tx.set("reqs", rid, Request(rid, "understand", based, based if based > 0 else None))
        goal = active_goal(self.tx)
        view = {
            "turn_text": turn.text,
            "intent": goal.intent if goal else None,
            "slots": {n: r.value for (g, n), r in self.tx.items("slots") if goal and g == goal.goal_id},
        }
        self.effects.append({"effect": "reason", "req_id": rid, "based_on_seq": based, "purpose": "understand", "view": view})
        self.rule("PLANNER.request", req_id=rid, based_on_seq=based)

    def understand_context(self, turn: Turn | None) -> UnderstandContext:
        """Read-only view for fast understanding: the ACTIVE goal only, never another goal's slots."""
        goal = active_goal(self.tx)
        open_text = turn.text if turn is not None and turn.open else ""
        if goal is None:
            return UnderstandContext(utterances=self.meta("utterances"), turn_text=open_text)
        registry = self.registry()
        schemas: dict[str, dict] = {}
        for node in goal.graph:
            spec = registry.get(node.tool)
            props = json.loads(spec.params_json).get("properties", {}) if spec else {}
            for param, b in node.args:
                if b[0] == "slot":
                    schemas.setdefault(b[1], props.get(param, {}))
        regs = {n: r for (g, n), r in self.tx.items("slots") if g == goal.goal_id}
        slots = tuple(
            SlotInfo(name, regs[name].value if name in regs else None, schemas.get(name, {}),
                     (*regs[name].history, (regs[name].value, regs[name].writer_seq, regs[name].source))
                     if name in regs else ())
            for name in sorted(set(schemas) | set(regs)))
        pending = tuple((p.kind, p.slots, p.asked) for _, p in self.tx.items("pending")
                        if p.goal_id == goal.goal_id and not p.resolved)
        return UnderstandContext(goal.intent, slots, pending, self.meta("utterances"), open_text)

    # ------------------------------------------------------------ event handlers

    def on_session_start(self) -> None:
        self.arm("deadline", "deadline", self.now + self.cfg.deadline_s)

    def on_session_end(self) -> None:
        self.set_meta("session_ended", True)
        turn = self.turn()
        if turn is not None and turn.open:
            self.set_meta("turn", replace(turn, open=False))
        if self.meta("hold"):
            self.set_meta("hold", False)
            self.rule("HOLD.clear", by="session_end")

    def on_manifest(self) -> None:
        reg = Registry.from_manifest(self.payload.get("tools"))
        self.set_meta("registry", reg)
        self.rule("REG.load", tools=[t.name for t in reg.tools], effects=[t.effect.value for t in reg.tools],
                  reasons=[t.effect_reason for t in reg.tools], quarantined=[list(q) for q in reg.quarantined])

    def on_user_text(self) -> None:
        text = str(self.payload.get("text", ""))
        turn = self.turn()
        u = self.understand(text, self.payload, self.understand_context(turn))
        if turn is None or not turn.open:
            turn = Turn(turn_id=(turn.turn_id + 1) if turn else 1, open=True)
            self.rule("TURN.open", turn_id=turn.turn_id)
        content = u.cls is not TurnClass.BACKCHANNEL
        marker = u.cls in MARKERS
        writes = turn.t0_writes
        if content:
            self.set_meta("last_content_seq", self.seq)
        if marker and not self.meta("hold"):
            self.set_meta("hold", True)
            self.rule("HOLD.set", by=u.cls.value)
        goal = active_goal(self.tx)
        if u.cls is TurnClass.GOAL_SWITCH:
            self.set_meta("goal_switch_seq", self.seq)
            if goal is not None:  # D11: do not re-dispatch abandoned work before the planner answers
                self.set_meta("switch_pending", goal.goal_id)
                self.rule("SWITCH.pending", goal_id=goal.goal_id)
        if u.writes and goal is None:
            self.rule("T0.no_goal", writes=sorted(u.writes))
        if goal is not None and content:
            for name, value in sorted(u.writes.items()):
                if self.write_register(goal.goal_id, name, value, self.seq, "T0", False):
                    writes = writes + ((goal.goal_id, name, self.seq),)
            if u.writes:
                self.resolve_pendings(goal.goal_id, tuple(u.writes))
            if marker and not u.writes and not u.attributed:  # F5: marker WITHOUT attribution -> read-only calls
                for _, call in self.tx.items("calls"):
                    if call.goal_id == goal.goal_id and call.relevance is Relevance.DESIRED \
                            and call.effect is Effect.READ_ONLY and call.outcome not in KNOWN_OUTCOMES:
                        self.supersede(call, "unattributed_marker")
            if u.confirm:
                for (g, name), reg in self.tx.items("slots"):
                    if g == goal.goal_id and not reg.confirmed:
                        self.tx.set("slots", (g, name), replace(reg, confirmed=True))
                        self.rule("SLOT.confirm", slot=name, by="user")
                self.resolve_pendings(goal.goal_id, None)
        self.set_meta("turn", replace(
            turn, text=(turn.text + " " + text).strip(), classes=turn.classes + (u.cls.value,),
            content=turn.content or content, interrupting=turn.interrupting or marker, t0_writes=writes,
            marker_seqs=turn.marker_seqs + ((self.seq,) if marker else ())))
        self.rule("T0.classify", cls=u.cls.value, cues=list(u.cues), attributed=list(u.attributed),
                  writes=sorted(u.writes))
        self.arm("eot", "eot_silence", self.now + self.cfg.silence_s)

    def on_end_of_turn(self) -> None:
        self.close_turn(inferred=False)

    def on_interrupt(self) -> None:
        if not self.meta("hold"):
            self.set_meta("hold", True)
            self.rule("HOLD.set", by="interrupt")
        if not self.turn_open():  # D4: a content-free interrupt must still clear
            self.arm("eot", "eot_silence", self.now + self.cfg.silence_s)

    def on_timer(self) -> None:
        tid = self.payload.get("timer_id")
        timer = self.tx.get("timers", tid)
        if timer is None or timer.due_t != self.payload.get("due_t"):
            self.rule("TIMER.stale", timer_id=tid)
            return
        self.tx.set("timers", tid, None)
        self.rule("TIMER.fire", timer_id=tid, purpose=timer.purpose)
        if timer.purpose == "eot_silence":
            if self.turn_open():
                self.close_turn(inferred=True)
            elif self.meta("hold"):
                self.set_meta("hold", False)
                self.rule("HOLD.clear", by="silence_timer")
        elif timer.purpose == "tool_timeout":
            call = self.tx.get("calls", timer.ref)
            if call is not None and call.outcome is Outcome.PENDING:
                self.set_outcome(call, Outcome.UNKNOWN)
                call = self.tx.get("calls", timer.ref)
                if call.effect is Effect.READ_ONLY:
                    self.supersede(call, "timeout")
                else:
                    self.ensure_pending(call.goal_id, "unknown_outcome", (),
                                        f"I can't confirm whether {call.tool} went through yet.", call.call_id)
        elif timer.purpose == "deadline":
            self.deadline()

    def deadline(self) -> None:
        self.set_meta("deadline_passed", True)
        for _, call in self.tx.items("calls"):
            if call.relevance is Relevance.DESIRED and call.effect is Effect.READ_ONLY \
                    and call.outcome not in KNOWN_OUTCOMES:
                self.supersede(call, "deadline")
        turn = self.turn()
        if turn is not None and turn.open:
            self.set_meta("turn", replace(turn, open=False))
        if self.meta("hold"):
            self.set_meta("hold", False)
            self.rule("HOLD.clear", by="deadline")
        goal = active_goal(self.tx)
        done, grounded, ops = self.satisfied(goal)
        self.emit(ActionKind.FINAL, "DEADLINE.final", {
            "text": "Here is where things stand." if not done else f"Done: {goal.intent}.",  # type: ignore[union-attr]
            "act": "answer" if done else "narration", "grounded_on": grounded, "ops": ops,
            "ledger_calls": self.ledger_calls(ops),
            "snapshot": snapshot(goal, dict(self.tx.items("slots")))})

    def on_tool_result(self) -> None:
        call = self.tx.get("calls", self.payload.get("call_id"))
        if call is None:
            self.rule("ADM.unknown_call", call_id=self.payload.get("call_id"))
            return
        hint, executed = self.payload.get("outcome"), self.payload.get("executed")
        sm = call.effect is Effect.STATE_CHANGING
        if hint == "ok":
            outcome = Outcome.OK
        elif hint == "cancelled_ack" or (hint == "error" and executed is False):
            outcome = Outcome.FAILED_CLEAN
        else:  # error with executed true/unknown, malformed, or unrecognised hint
            outcome = Outcome.UNKNOWN if sm else Outcome.FAILED_CLEAN
        if not self.set_outcome(call, outcome, self.payload.get("data")):
            self.rule("ADM.ignored", call_id=call.call_id, current=call.outcome.value, hint=hint)
            return
        call = self.tx.get("calls", call.call_id)
        if call.relevance is Relevance.SUPERSEDED:
            self.rule("ADM.stale", call_id=call.call_id, outcome=outcome.value)  # recorded, never used (D1)
        elif outcome is Outcome.FAILED_CLEAN:
            self.supersede(call, "error")
        elif outcome is Outcome.UNKNOWN:
            self.ensure_pending(call.goal_id, "unknown_outcome", (),
                                f"I can't confirm whether {call.tool} went through.", call.call_id)

    def on_proposal(self) -> None:
        req = self.tx.get("reqs", self.payload.get("req_id"))
        if req is None or req.based_on_seq != self.payload.get("based_on_seq"):
            self.rule("ADM.unknown_request", req_id=self.payload.get("req_id"))
            return
        if req.open:
            self.tx.set("reqs", req.req_id, replace(req, open=False))
        based = req.based_on_seq
        structure_ok = based >= self.meta("goal_switch_seq")
        if self.meta("switch_pending") is not None and structure_ok:
            self.set_meta("switch_pending", None)
            self.rule("SWITCH.answered", req_id=req.req_id)
        intent = self.payload.get("intent")
        goal = active_goal(self.tx)
        if intent and structure_ok and (goal is None or goal.intent != intent or self.payload.get("new_goal")):
            if goal is not None:
                self.tx.set("goals", goal.goal_id, replace(goal, status=GoalStatus.SUSPENDED))
                self.rule("GOAL.suspend", goal_id=goal.goal_id)
            gid = f"g{self.next_n('n_goal')}"
            goal = Goal(gid, intent, GoalStatus.ACTIVE, req.user_seq, self.seq)
            self.tx.set("goals", gid, goal)
            self.set_meta("active_goal", gid)
            self.rule("GOAL.create", goal_id=gid, intent=intent, origin_seq=req.user_seq)
            for fid, frame in self.tx.items("frames"):
                if frame.goal_id is None:
                    self.tx.set("frames", fid, replace(frame, goal_id=gid))
        elif intent and not structure_ok:
            self.rule("PROP.structure_stale", req_id=req.req_id, based_on_seq=based)
        if goal is None:
            self.rule("PROP.no_goal", req_id=req.req_id)
            return
        gid = goal.goal_id
        written = self.payload.get("slot_writes") or {}
        for name, value in sorted(written.items()):
            self.write_register(gid, name, value, based, "PLANNER", True)
        for (g, name), reg in self.tx.items("slots"):  # D12: a retraction the planner saw but did not fill
            if g == gid and reg.value is None and reg.source == "T0" and reg.writer_seq <= based \
                    and name not in written and reg.history and reg.history[-1][0] is not None:
                previous = reg.history[-1][0]
                self.tx.set("slots", (g, name), Register(previous, based, "PLANNER", True,
                                                           reg.history + ((None, reg.writer_seq, "T0"),)))
                self.rule("T0.retraction_reverted", slot=name, value=previous)
        if structure_ok and "graph" in self.payload:
            nodes = tuple(self.parse_node(gid, i, n, based) for i, n in enumerate(self.payload["graph"]))
            self.tx.set("goals", gid, replace(self.tx.get("goals", gid), graph=nodes))
            self.rule("PLAN.graph", goal_id=gid, nodes=[n.node_id for n in nodes])
        clarify = self.payload.get("clarify")
        if clarify:
            self.ensure_pending(gid, "planner_clarify", tuple(clarify.get("slots", ())), clarify["text"], req.req_id)

    def parse_node(self, gid: str, i: int, raw: dict, based: int) -> Node:
        args: list[tuple[str, tuple]] = []
        for param, b in sorted((raw.get("args") or {}).items()):
            if isinstance(b, dict) and "$slot" in b:
                args.append((param, ("slot", b["$slot"])))
            elif isinstance(b, dict) and "$node" in b:
                args.append((param, ("node", b["$node"], tuple(b.get("path", ())))))
            elif isinstance(b, dict) and "$const" in b:
                args.append((param, ("const", b["$const"])))
            else:  # F4: a literal is rebound to a slot of equal value, else written into the slot `param`
                same = [n for (g, n), r in self.tx.items("slots") if g == gid and r.value == b]
                name = param if param in same else (same[0] if same else None)
                if name is None:
                    self.write_register(gid, param, b, based, "PLANNER", True)
                    name = param
                args.append((param, ("slot", name)))
                self.rule("PLAN.rebind", param=param, slot=name)
        return Node(str(raw.get("node_id", f"n{i + 1}")), str(raw["tool"]), tuple(args), str(raw.get("instance_tag", "")))

    def on_proposal_failed(self) -> None:
        req = self.tx.get("reqs", self.payload.get("req_id"))
        if req is not None and req.open:
            self.tx.set("reqs", req.req_id, replace(req, open=False))
        self.rule("PROP.failed", req_id=self.payload.get("req_id"), reason=self.payload.get("reason"))

    def on_media(self) -> None:
        kind = self.payload.get("kind")
        req_id = f"p{self.next_n('n_percept')}"
        if kind == "image":
            goal = active_goal(self.tx)
            self.tx.set("frames", self.ev.eid, Frame(str(self.ev.eid), self.seq, goal.goal_id if goal else None))
            hints = sorted(name for (g, name), _ in self.tx.items("slots") if goal and g == goal.goal_id)
            self.effects.append({"effect": "perceive", "req_id": req_id, "kind": "vision",
                                 "source_eid": self.ev.eid, "ref": self.payload.get("ref"), "hints": hints})
        else:
            self.effects.append({"effect": "perceive", "req_id": req_id, "kind": "asr",
                                 "source_eid": self.ev.eid, "ref": self.payload.get("ref")})

    def on_perception_failed(self) -> None:
        self.rule("PERCEPTION.failed", req_id=self.payload.get("req_id"))

    def on_evidence(self) -> None:
        fid = self.payload.get("frame_eid")
        frame = self.tx.get("frames", fid)
        if frame is None:
            self.rule("EV.unknown_frame", frame_eid=fid)
            return
        claims = tuple((k, v[0], v[1]) for k, v in sorted((self.payload.get("claims") or {}).items()))
        gid = frame.goal_id
        if gid is None:
            goal = active_goal(self.tx)
            gid = goal.goal_id if goal else None
        self.tx.set("frames", fid, replace(frame, claims=claims, goal_id=gid))
        goal = self.tx.get("goals", gid) if gid else None
        if goal is None or goal.status is not GoalStatus.ACTIVE:
            self.rule("EV.not_active", frame_eid=fid, goal_id=gid)  # kept, not applied (§8.5)
            return
        for key, value, conf in claims:
            reg = self.tx.get("slots", (gid, key))
            if reg is not None and reg.source != "EVIDENCE" and reg.value != value:
                self.ensure_pending(gid, "conflict", (key,),
                                    f"The image shows {value} but you said {reg.value}. Which one is right?", key)
                self.rule("EV.conflict", slot=key, evidence=value, current=reg.value)
                continue
            self.write_register(gid, key, value, frame.seq, "EVIDENCE", conf >= self.cfg.evidence_theta)

    # ------------------------------------------------------------ reconciliation (every step)

    def reconcile(self, before: dict) -> None:
        goal = active_goal(self.tx)
        ds = resolve(self.tx, goal)
        keys = {d.key for d in ds if d.key}
        for _, call in self.tx.items("calls"):
            if call.relevance is Relevance.DESIRED and (goal is None or call.goal_id != goal.goal_id):
                self.supersede(call, "goal_inactive")
            elif call.relevance is Relevance.DESIRED and call.key not in keys:
                self.supersede(call, "not_desired")
        if goal is None:
            return
        after = [d.key for d in ds if d.key]
        if before.get(goal.goal_id) != after:
            goal = replace(self.tx.get("goals", goal.goal_id), plan_rev=goal.plan_rev + 1)
            self.tx.set("goals", goal.goal_id, goal)
            self.rule("PLAN.rev", goal_id=goal.goal_id, plan_rev=goal.plan_rev, keys=after)
        for d in ds:
            if d.error and d.error != "unknown_tool":
                self.ensure_pending(goal.goal_id, "invalid_args", (), f"I need a valid value: {d.error}", d.node.node_id)
        if self.turn_open() or self.meta("deadline_passed") or self.meta("session_ended"):
            return  # D5: never dispatch while a user turn is open
        for d in ds:
            if d.key is None or any(c.relevance is Relevance.DESIRED for c in self.calls_for(goal.goal_id, d.key)):
                continue
            if self.meta("switch_pending") == goal.goal_id:
                continue  # D11
            spec = self.registry().get(d.node.tool)
            if spec is None:
                continue
            if spec.effect is Effect.READ_ONLY:
                failures = [c for c in self.calls_for(goal.goal_id, d.key) if c.superseded_reason in RETRY_REASONS]
                if len(failures) >= self.cfg.ro_max_attempts:
                    self.ensure_pending(goal.goal_id, "exhausted", (), f"{spec.name} is not responding.", d.key)
                    continue
                self.dispatch(goal, d)  # D2: superseded twins with the same key don't matter
            else:
                self.reconcile_state_changing(goal, d)

    def reconcile_state_changing(self, goal: Goal, d: Desired) -> None:
        op_id = (goal.goal_id, d.node.tool, d.node.instance_tag)
        state = op_state(self.tx, op_id)
        if state is OpState.COMMITTED:
            done = committed_attempt(self.tx, op_id)
            if done is not None and done.args_json != canonical_json(d.args):  # INV-16: never re-create
                self.ensure_pending(goal.goal_id, "divergence", (),
                                    f"{d.node.tool} already went through with different details. "
                                    "Should I change it, or leave it as it is?", done.call_id)
            return
        if state is OpState.LOCKED:
            self.rule("OP.locked", op=list(op_id))
            return
        attempts = [self.tx.get("calls", cid) for cid in self.tx.get("ops", op_id, ())]
        same = [c for c in attempts if c.args_json == canonical_json(d.args) and c.outcome is Outcome.FAILED_CLEAN]
        if len(same) >= self.cfg.sm_max_same_args:
            self.ensure_pending(goal.goal_id, "exhausted", (), f"{d.node.tool} keeps failing.", d.key or "")
            return
        blocked = self.barrier(goal, d)
        if blocked:
            self.rule("BARRIER.block", op=list(op_id), reason=blocked)
            return
        self.dispatch(goal, d, op_id)

    def barrier(self, goal: Goal, d: Desired) -> str | None:
        """Commit barrier + provenance (F6, INV-14, INV-15). Turn-closed is checked by the caller."""
        if self.meta("hold"):
            return "hold"
        if goal.origin_seq is None:
            return "provenance"
        read = [b[1] for _, b in d.node.args if b[0] == "slot"]
        for name in read:
            reg = self.tx.get("slots", (goal.goal_id, name))
            if reg is None or not reg.confirmed:
                return f"unconfirmed:{name}"
        for _, p in self.tx.items("pending"):
            if p.goal_id == goal.goal_id and not p.resolved and p.kind in ("conflict", "planner_clarify") \
                    and set(p.slots) & set(read):
                return f"pending:{p.pid}"
        return None

    # ------------------------------------------------------------ speech, snapshots, completion

    def satisfied(self, goal: Goal | None) -> tuple[bool, list[str], list[list]]:
        if goal is None or not goal.graph:
            return False, [], []
        grounded: list[str] = []
        ops: list[list] = []
        complete = True
        for d in resolve(self.tx, goal):
            spec = self.registry().get(d.node.tool)
            if d.key is None or spec is None:
                complete = False
                continue
            if spec.effect is Effect.READ_ONLY:
                call = desired_ok_call(self.tx, goal.goal_id, d.key)
                if call is None:
                    complete = False
                else:
                    grounded.append(call.call_id)
            else:
                op_id = (goal.goal_id, d.node.tool, d.node.instance_tag)
                done = committed_attempt(self.tx, op_id)
                if done is None or done.args_json != canonical_json(d.args):
                    complete = False
                else:
                    ops.append(list(op_id))
                    if done.relevance is Relevance.DESIRED:
                        grounded.append(done.call_id)
        return complete, grounded, ops

    def ledger_calls(self, ops: list[list]) -> list[str]:
        """D6: the committed attempts behind COMMITTED operations, for truthful external reporting only.
        They are never bindings or grounding (INV-09 still reads `grounded_on`, which holds DESIRED calls only)."""
        attempts = (committed_attempt(self.tx, tuple(op)) for op in ops)
        return [c.call_id for c in attempts if c is not None]

    def status_text(self, goal: Goal | None) -> str:
        """Answer a status question from state only: what is running, what is done, what is missing."""
        if goal is None:
            return "Nothing is running right now."
        running = [c for _, c in self.tx.items("calls") if c.goal_id == goal.goal_id
                   and c.relevance is Relevance.DESIRED and c.outcome not in KNOWN_OUTCOMES]
        if running:
            return "Still working on it: " + "; ".join(f"{c.tool} {c.args_json}" for c in running) + ". No result yet."
        keys = tuple(d.key for d in resolve(self.tx, goal))
        if goal.final_keys is not None and goal.final_keys == keys:
            return f"I've already given you the {goal.intent} result."
        asked = [p for _, p in self.tx.items("pending") if p.goal_id == goal.goal_id and p.asked and not p.resolved]
        if asked:
            return f"I'm waiting on your answer: {asked[-1].text}"
        return "I still need a few details before I can continue."

    def speak(self) -> None:
        if self.turn_open():
            return  # INV-20: no speech while the user holds the floor
        goal = active_goal(self.tx)
        slots = dict(self.tx.items("slots"))
        if self.want_snapshot:
            self.emit(ActionKind.SNAPSHOT, "SNAPSHOT.interruption", {"snapshot": snapshot(goal, slots)})
        for pid, p in self.tx.items("pending"):
            if not p.asked and not p.resolved and goal is not None and p.goal_id == goal.goal_id:
                self.tx.set("pending", pid, replace(p, asked=True))
                self.emit(ActionKind.CLARIFY, "PENDING.ask", {"text": p.text, "slots": list(p.slots), "reason": p.kind})
        spoke = False
        if self.dispatched:  # progressive wording only: dispatch is never a completion claim
            what = "; ".join(f"{c.tool} {c.args_json}" for c in self.dispatched)
            self.emit(ActionKind.SPEAK, "SPEECH.ack", {"text": f"Working on it: {what}", "act": "ack", "grounded_on": []})
            spoke = True
        turn = self.closed_turn
        if turn is not None and not spoke:  # a closed user turn gets a grounded response, never a filler
            classes = set(turn.classes)
            if TurnClass.STATUS_QUERY.value in classes:
                self.emit(ActionKind.SPEAK, "SPEECH.status",
                          {"text": self.status_text(goal), "act": "narration", "grounded_on": []})
            elif TurnClass.GOAL_SWITCH.value in classes and goal is not None:
                self.emit(ActionKind.SPEAK, "SPEECH.switch",
                          {"text": f"Okay, leaving {goal.intent} for now.", "act": "ack", "grounded_on": []})
            elif TurnClass.CORRECTION.value in classes and turn.t0_writes:
                names = ", ".join(sorted({n for _, n, _ in turn.t0_writes}))
                self.emit(ActionKind.SPEAK, "SPEECH.correction",
                          {"text": f"Okay, updating the {names}.", "act": "ack", "grounded_on": []})
        if goal is None or self.meta("deadline_passed") or self.meta("hold"):
            return
        done, grounded, ops = self.satisfied(goal)
        keys = tuple(d.key for d in resolve(self.tx, goal))
        if done and goal.final_keys != keys:
            self.tx.set("goals", goal.goal_id, replace(self.tx.get("goals", goal.goal_id), final_keys=keys))
            self.emit(ActionKind.FINAL, "FINAL.complete", {
                "text": f"Done: {goal.intent}.", "act": "answer", "grounded_on": grounded, "ops": ops,
                "ledger_calls": self.ledger_calls(ops),
                "snapshot": snapshot(goal, dict(self.tx.items("slots")))})


def state_reader(tables: dict) -> State:
    """A read-only State over copied tables (used by tests to inspect a past revision)."""
    s = State.__new__(State)
    s.t = {name: dict(rows) for name, rows in tables.items()}
    return s


__all__ = ["Kernel", "Config", "State", "StepResult", "resolve", "active_goal", "op_state", "committed_attempt",
           "desired_ok_call", "state_reader"]
