"""Per-step checker for the FINAL ARCHITECTURAL INVARIANTS.

CheckedKernel runs decide() twice before the real step (INV-01: pure and deterministic), then checks the
step's actions and the before/after states against INV-03, 04, 06-16 and 18-22. INV-02/05/17/23 are
checked by dedicated tests. Any violation raises InvariantViolation naming the invariant.
"""

from __future__ import annotations

import json

from agent.kernel import Kernel, State, StepResult, active_goal, op_state, resolve, state_reader
from agent.model import (
    KNOWN_OUTCOMES,
    OUTCOME_MOVES,
    SPEECH_KINDS,
    ActionKind,
    Effect,
    Event,
    Kind,
    OpState,
    Outcome,
    Relevance,
    TurnClass,
    canonical_json,
    snapshot,
)
from agent.proposal import authorised
from agent.proposal import grounded as said_by_user
from agent.protocol import validate_action

RETRY_REASONS = ("timeout", "error", "unknown")


class InvariantViolation(AssertionError):
    pass


def check(cond: bool, inv: str, msg: str) -> None:
    if not cond:
        raise InvariantViolation(f"{inv}: {msg}")


def classified(res: StepResult) -> str | None:
    """The turn class the kernel journaled for this step (T0.classify), if any."""
    return next((r["cls"] for r in res.rules if r["rule"] == "T0.classify"), None)


def _canon(res: StepResult) -> str:
    return canonical_json(res)


class CheckedKernel(Kernel):
    def __init__(self, config=None, understand=None):
        kwargs = {"understand": understand} if understand else {}
        super().__init__(config, **kwargs)
        self.seen_calls: set[str] = set()
        self.seen_actions: set[str] = set()
        self.cancelled: set[str] = set()
        self.user_seqs: set[int] = set()
        self.last_action_n = 0
        self.violations_checked = 0

    def step(self, event: Event) -> StepResult:
        before = state_reader(self.state.t)
        dump = self.state.dump()
        first = self.decide(self.state, event)
        check(self.state.dump() == dump, "INV-01", "decide() mutated state")
        second = self.decide(self.state, event)
        check(_canon(first) == _canon(second), "INV-01", "decide() is not deterministic")
        res = super().step(event)
        check(_canon(res) == _canon(first), "INV-01", "step() diverged from decide()")
        if event.kind is Kind.USER_TEXT and classified(res) not in (None, TurnClass.BACKCHANNEL.value):
            self.user_seqs.add(event.seq)
        check_step(self, before, self.state, event, res)
        self.violations_checked += 1
        return res


def check_step(k: CheckedKernel, before: State, after: State, event: Event, res: StepResult) -> None:  # noqa: C901
    acts = res.actions
    kinds = [a.kind for a in acts]
    registry = after.get("meta", "registry")
    turn = after.get("meta", "turn")
    turn_open = turn is not None and turn.open
    bcalls, acalls = dict(before.items("calls")), dict(after.items("calls"))

    # INV-22 protocol validity
    for a in acts:
        validate_action(a)

    # INV-03 ordering: cancels before tool calls; action ids ascend across steps
    if ActionKind.CANCEL in kinds and ActionKind.TOOL_CALL in kinds:
        last_cancel = max(i for i, x in enumerate(kinds) if x is ActionKind.CANCEL)
        first_call = min(i for i, x in enumerate(kinds) if x is ActionKind.TOOL_CALL)
        check(last_cancel < first_call, "INV-03", "a tool call precedes a cancel in one step")
    for a in acts:
        n = int(a.action_id[1:])
        check(n > k.last_action_n, "INV-03", f"action ids not ascending ({a.action_id})")
        k.last_action_n = n

    # INV-04 execution identity
    for a in acts:
        check(a.action_id not in k.seen_actions, "INV-04", f"duplicate action id {a.action_id}")
        k.seen_actions.add(a.action_id)
        if a.kind is ActionKind.TOOL_CALL:
            cid = a.payload["call_id"]
            check(cid not in k.seen_calls, "INV-04", f"duplicate call id {cid}")
            k.seen_calls.add(cid)

    # INV-07 terminal supersession, INV-10 monotonic outcomes (calls are never deleted)
    for cid, b in bcalls.items():
        check(cid in acalls, "INV-10", f"call {cid} disappeared")
        a = acalls[cid]
        if b.relevance is Relevance.SUPERSEDED:
            check(a.relevance is Relevance.SUPERSEDED, "INV-07", f"{cid} became DESIRED again")
        if a.outcome is not b.outcome:
            check(a.outcome in OUTCOME_MOVES[b.outcome], "INV-10", f"{cid} {b.outcome.value}->{a.outcome.value}")
    if event.kind is Kind.TOOL_RESULT and event.payload.get("call_id") not in bcalls:
        check(res.changes == [], "INV-10", "a result for an unknown call id changed state")

    # INV-11 cancel semantics
    superseded_now = [cid for cid, a in acalls.items() if a.relevance is Relevance.SUPERSEDED
                      and (cid not in bcalls or bcalls[cid].relevance is Relevance.DESIRED)]
    cancels = [a.payload["call_id"] for a in acts if a.kind is ActionKind.CANCEL]
    for cid in cancels:
        check(cid in superseded_now, "INV-11", f"cancel for {cid}, which was not superseded in this step")
        check(cid not in k.cancelled, "INV-11", f"second cancel for {cid}")
        k.cancelled.add(cid)
    for cid in superseded_now:
        a = acalls[cid]
        spec = registry.get(a.tool)
        expected = a.outcome not in KNOWN_OUTCOMES and (
            a.effect is Effect.READ_ONLY or spec is None or spec.cancellable is not False)
        check(expected == (cid in cancels), "INV-11", f"cancel emission wrong for {cid} (expected {expected})")

    # INV-06 relevance consistency, INV-08 same-step supersession
    goal = active_goal(after)
    ds = resolve(after, goal)
    keys = [d.key for d in ds if d.key]
    per_key: dict = {}
    for cid, a in acalls.items():
        if a.relevance is Relevance.DESIRED:
            check(goal is not None and a.goal_id == goal.goal_id, "INV-06", f"DESIRED {cid} not in the ACTIVE goal")
            check(a.key in keys, "INV-06", f"DESIRED {cid} has a key outside the desired set")
            per_key[(a.goal_id, a.key)] = per_key.get((a.goal_id, a.key), 0) + 1
    check(all(v <= 1 for v in per_key.values()), "INV-06", "two DESIRED calls share one key")
    for cid, b in bcalls.items():
        if b.relevance is Relevance.DESIRED and not (goal and b.goal_id == goal.goal_id and b.key in keys):
            check(acalls[cid].relevance is Relevance.SUPERSEDED, "INV-08", f"{cid} left the desired set but is DESIRED")

    # INV-12 read-only dispatch; nothing dispatched while a user turn is open (D17: read-only only, in full duplex)
    tool_calls = [a for a in acts if a.kind is ActionKind.TOOL_CALL]
    if turn_open and k.config.full_duplex:
        check(all(acalls[a.payload["call_id"]].effect is Effect.READ_ONLY for a in tool_calls), "INV-12",
              "state-changing call dispatched while a user turn is open")
    if turn_open and (not k.config.full_duplex or after.get("meta", "hold")):
        check(not tool_calls, "INV-12", "tool call dispatched while a user turn is open")
    elif goal is not None and not after.get("meta", "deadline_passed") and not after.get("meta", "session_ended") \
            and after.get("meta", "switch_pending") != goal.goal_id:  # D11: withheld until the planner answers
        for d in ds:
            spec = registry.get(d.node.tool)
            if d.key is None or spec is None or spec.effect is not Effect.READ_ONLY:
                continue
            same = [c for c in acalls.values() if c.goal_id == goal.goal_id and c.key == d.key]
            failures = [c for c in same if c.superseded_reason in RETRY_REASONS]
            desired = [c for c in same if c.relevance is Relevance.DESIRED]
            if len(failures) < k.config.ro_max_attempts:
                check(len(desired) == 1, "INV-12", f"desired read-only key has {len(desired)} DESIRED calls")

    # INV-13..16 state-changing dispatch
    for tc in tool_calls:
        call = acalls[tc.payload["call_id"]]
        if call.effect is not Effect.STATE_CHANGING:
            continue
        prior = [acalls[x] for x in after.get("ops", call.op_id, ()) if x != call.call_id]
        check(all(p.outcome is Outcome.FAILED_CLEAN for p in prior), "INV-13",
              f"create {call.call_id} while an earlier attempt is not FAILED_CLEAN")
        check(op_state(before, call.op_id) is not OpState.COMMITTED, "INV-16", "re-dispatch on a COMMITTED operation")
        check(not turn_open and not after.get("meta", "hold"), "INV-14", "state-changing dispatch under hold/open turn")
        g = after.get("goals", call.goal_id)
        node = next(n for n in g.graph if n.node_id == call.node_id)
        read = [b[1] for _, b in node.args if b[0] == "slot"]
        for name in read:
            reg = after.get("slots", (g.goal_id, name))
            check(reg is not None and reg.confirmed, "INV-14", f"dispatch with unconfirmed slot {name}")
        for _, p in after.items("pending"):
            if p.goal_id == g.goal_id and not p.resolved and p.kind in ("conflict", "planner_clarify"):
                check(not set(p.slots) & set(read), "INV-14", f"dispatch with open clarification {p.pid}")
        check(g.origin_seq is not None and g.origin_seq in k.user_seqs, "INV-15",
              f"state-changing dispatch without user provenance (origin {g.origin_seq})")
        spec = registry.get(call.tool)
        said = [t for seq, t in after.get("meta", "utterances") if seq >= g.origin_seq]
        confirmed = (g.goal_id, canonical_json([call.tool, json.loads(call.args_json)])) in after.get("meta", "authorised")
        check(confirmed or authorised(call.tool, spec.description if spec else "", said), "INV-15/D13",
              f"state-changing {call.tool} that no user utterance of the goal asked for")
        for _, b in node.args:
            reg = after.get("slots", (g.goal_id, b[1])) if b[0] == "slot" else None
            if reg is not None and reg.source in ("PLANNER", "PARTIAL"):
                check(confirmed or said_by_user(reg.value, " ".join(said)), "INV-15/D13",
                      f"state-changing {call.tool} with planner value {reg.value!r} the user never said")
        check(not any(r.open and r.may_change for _, r in after.items("reqs")), "INV-14/D14",
              f"state-changing dispatch {call.call_id} while newer user input is still being planned")
    for op_id, attempts in before.items("ops"):
        if op_state(before, op_id) is OpState.COMMITTED:
            check(after.get("ops", op_id) == attempts, "INV-16", f"new attempt on COMMITTED operation {op_id}")

    # INV-18 last writer wins; backchannels never write
    bslots, aslots = dict(before.items("slots")), dict(after.items("slots"))
    for key, reg in aslots.items():
        old = bslots.get(key)
        if old is not None and reg != old:
            check(reg.writer_seq >= old.writer_seq, "INV-18", f"register {key} went back to writer {reg.writer_seq}")
    if event.kind is Kind.USER_TEXT and classified(res) == TurnClass.BACKCHANNEL.value:
        check(aslots == bslots, "INV-18", "a backchannel wrote a slot")

    # INV-19 hold liveness
    if after.get("meta", "hold"):
        clearer = turn_open or after.get("timers", "eot") is not None or \
            (after.get("timers", "deadline") is not None and not after.get("meta", "deadline_passed"))
        check(clearer, "INV-19", "hold is set with nothing that will clear it")
    if event.kind is Kind.SESSION_END:
        check(not after.get("meta", "hold"), "INV-19", "hold still set at session end")

    # INV-20 truthful speech; INV-09 stale results never used; INV-21 snapshot correctness
    if turn_open:
        check(not any(a.kind in SPEECH_KINDS for a in acts), "INV-20", "speech while a user turn is open")
    slots_now = dict(after.items("slots"))
    for a in acts:
        grounded = a.payload.get("grounded_on", []) if isinstance(a.payload, dict) else []
        uses = a.payload.get("uses", []) if a.kind is ActionKind.TOOL_CALL else []
        for cid in list(grounded) + list(uses):
            c = acalls.get(cid)
            check(c is not None and c.relevance is Relevance.DESIRED and c.outcome is Outcome.OK, "INV-09",
                  f"{a.kind.value} uses {cid}, which is not DESIRED+OK")
        if a.kind in (ActionKind.SPEAK, ActionKind.FINAL) and a.payload.get("act") in ("answer", "confirm"):
            ops = [tuple(o) for o in a.payload.get("ops", [])]
            check(bool(grounded) or any(op_state(after, o) is OpState.COMMITTED for o in ops), "INV-20",
                  "answer/confirm without a DESIRED+OK call or COMMITTED operation")
        if a.kind is ActionKind.FINAL:
            check(a.payload["snapshot"] == snapshot(goal, slots_now), "INV-21", "FINAL snapshot differs from state")
