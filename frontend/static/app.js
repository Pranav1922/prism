// PRISM Theme 05 console. Everything shown here is derived from two real streams sent by frontend/server.py:
//   - the agent's own journal (each kernel step: the input event, rules fired, state changes, actions), and
//   - the PRISM-LOCAL/0 wire messages plus the simulated tool world's ledger.
// The browser keeps a MIRROR of the kernel's tables (it applies the journaled changes); it decides nothing.

import { MAX_SECONDS, MIN_SECONDS, Recorder, SILENCE_PEAK, TARGET_RATE, concat, downsample, pcm16, unsupportedReason } from "./recorder.js";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtT = (t) => (t == null ? "–" : `${t.toFixed(2)}s`);
const words = (s) => String(s || "").replace(/_/g, " ");
const title = (s) => { const w = words(s); return w.charAt(0).toUpperCase() + w.slice(1); };
const kstr = (k) => (typeof k === "string" ? k : JSON.stringify(k));

// ---------------------------------------------------------------------------------------------- state

let S;
function fresh(info = null, caps = null) {
  S = {
    info, caps, epoch: info?.started_epoch_ms ?? 0, status: info ? "starting" : "idle", error: null, verdict: null,
    tLast: 0, header: null,
    tables: { calls: {}, slots: {}, goals: {}, pending: {}, reqs: {}, ops: {}, frames: {}, meta: {}, timers: {} },
    seqT: {}, seqEvent: {},
    inputs: [], calls: {}, callOrder: [], percep: [], plans: {}, planOrder: [], classes: [], speech: [],
    moments: [], cuts: [], steps: [], wire: [], sideEffects: [], cancelIgnored: {}, early: {}, specT: null,
    prevSlots: {}, dirty: true,
  };
}
fresh();
let META = null;
let voiceOut = false;

// ---------------------------------------------------------------------------------------------- stream

function connect() {
  const es = new EventSource("/api/events");
  es.onmessage = (m) => { handle(JSON.parse(m.data)); };
  es.onerror = () => { if (S.status === "running") setStatus("reconnecting"); };
}

function handle(ev) {
  switch (ev.type) {
    case "reset": fresh(ev.info, ev.capabilities); renderHonesty(); showMode(); $("#moments").innerHTML = ""; window.refreshMic?.(); break;
    case "session":
      if (ev.state === "running") setStatus("running");
      else if (ev.state === "ended" || ev.state === "stopped") { setStatus("ended"); S.tLast = Math.max(S.tLast, ev.t || 0); }
      else if (ev.state === "error") { S.error = ev.detail; setStatus("error"); toast(`Agent stopped: ${ev.detail.split("\n").slice(-2).join(" ")}`); }
      break;
    case "wire": S.wire.push(ev); if (S.wire.length > 600) S.wire.splice(0, 100); break;
    case "world": onWorld(ev.event); break;
    case "journal": onJournal(ev.rec); break;
    case "verdict": S.verdict = ev.result; addMoment(S.tLast, ev.result.passed ? "done" : "stale",
      `Evaluator: ${ev.result.passed ? "PASS" : "FAIL"} · ${ev.result.internal_score}`, "Unchanged black-box evaluator, INTERNAL metric"); break;
  }
  S.dirty = true;
}

function setStatus(st) { S.status = st; document.body.dataset.session = st; S.dirty = true; }

function onWorld(e) {
  if (e.event === "side_effect") S.sideEffects.push(e);
  if (e.event === "cancel_ignored") S.cancelIgnored[e.call_id] = e.t;
}

// ---------------------------------------------------------------------------------------------- journal -> mirror

let currentStep = null;
function onJournal(r) {
  if (r.type === "header") { S.header = r; return; }
  if (r.type === "in") return onIn(r);
  if (r.type === "step") return onStep(r);
  if (r.type === "out") return onOut(r);
  if (r.type === "fx") return onFx(r);
  if (r.type === "perception_io") {
    const p = S.percep.find((x) => x.req === r.req_id);
    if (p) { p.backend = r.backend; p.wall = r.wall_s; p.error = r.error; }
    return;
  }
  if (r.type === "fx_io") {
    const p = S.plans[r.req_id];
    if (p) { p.detail = r; }
  }
}

function onIn(r) {
  const e = r.event, t = e.t, p = e.payload || {};
  S.seqT[r.seq] = t; S.seqEvent[r.seq] = e; S.tLast = Math.max(S.tLast, t);
  switch (e.kind) {
    case "UserText":
      if (p.source === "asr") {
        const span = S.percep.find((x) => x.kind === "asr" && x.t1 == null && (!p.source_eid || x.eid === p.source_eid)) ||
          S.percep.find((x) => x.kind === "asr" && x.t1 == null);
        if (span) { span.t1 = t; span.text = p.text; }
        const audio = S.inputs.find((i) => i.kind === "audio" && i.heard == null && (!span || i.eid === span.eid));
        if (audio) { audio.heard = p.text; audio.heardSeq = r.seq; } else S.inputs.push({ t, kind: "heard", text: p.text, seq: r.seq });
      } else S.inputs.push({ t, kind: p.source === "asr_stream" ? "heard" : "text", text: p.text, seq: r.seq, streamed: p.source === "asr_stream" });
      break;
    case "Media": S.inputs.push({ t, kind: p.kind === "image" ? "image" : "audio", ref: p.ref, eid: e.eid, seq: r.seq }); break;
    case "EndOfTurn": S.inputs.push({ t, kind: "eot", seq: r.seq }); break;
    case "Interrupt": S.inputs.push({ t, kind: "interrupt", seq: r.seq }); break;
    case "ToolResult": {
      const c = S.calls[p.call_id];
      if (c && c.t_result == null) { c.t_result = t; c.hint = p.outcome; }
      break;
    }
    case "Evidence": {
      const span = S.percep.find((x) => x.kind === "vision" && x.eid === p.frame_eid && x.t1 == null);
      if (span) { span.t1 = t; span.claims = p.claims; }
      break;
    }
    case "PerceptionFailed": {
      const span = S.percep.find((x) => x.req === p.req_id);
      if (span) { span.t1 = t; span.failed = true; }
      const audio = span && S.inputs.find((i) => i.kind === "audio" && i.eid === span.eid);
      if (audio) audio.notHeard = true;
      break;
    }
    case "Proposal": case "ProposalFailed": {
      const pl = S.plans[p.req_id];
      if (pl && pl.t1 == null) { pl.t1 = t; pl.ok = e.kind === "Proposal"; pl.reason = p.reason; pl.payload = p; }
      if (e.kind === "ProposalFailed" && !pl?.partial && (S.caps || META?.capabilities)?.planner.mode === "deterministic" && ["no_script", "no_plan"].includes(p.reason))
        addMoment(t, "plan", "No plan for that request",
          "Your words were heard and classified by the real fast path, but the deterministic planner (known examples, then rules for flight search, booking and weather) could not map them to a tool. Nothing was invented.");
      break;
    }
  }
}

function applyChange([table, key, val]) {
  const tb = S.tables[table] || (S.tables[table] = {});
  const k = kstr(key);
  if (val === null) delete tb[k]; else tb[k] = val;
  if (table === "calls" && S.calls[key]) { S.calls[key].rel = val.relevance; S.calls[key].outcome = val.outcome; S.calls[key].reason = val.superseded_reason; }
}

function onStep(r) {
  const t = S.seqT[r.seq] ?? S.tLast;
  const ev = S.seqEvent[r.seq];
  (r.changes || []).forEach(applyChange);
  currentStep = { seq: r.seq, t, ev, rules: r.rules || [], actions: [] };
  S.steps.push(currentStep);
  if (S.steps.length > 400) S.steps.shift();
  const superseded = [];
  for (const x of r.rules || []) {
    switch (x.rule) {
      case "T0.classify": {
        S.classes.push({ t, cls: x.cls, attributed: x.attributed, writes: x.writes, seq: r.seq });
        const inp = [...S.inputs].reverse().find((i) => i.seq === r.seq || i.heardSeq === r.seq);
        if (inp) inp.cls = x.cls;
        break;
      }
      case "REL.supersede": {
        const c = S.calls[x.call_id];
        if (c && c.t_cancel == null) { c.t_cancel = t; c.reason = x.reason; }
        superseded.push(x);
        break;
      }
      case "ADM.stale": {
        const c = S.calls[x.call_id];
        if (c) { c.stale = true; c.t_stale = t; }
        if (c && sideEffecting(c.tool))
          addMoment(t, "safety", `${title(c.tool)} ${x.call_id} completed despite the cancel`,
            `The tool ignored the cancel, so the side effect happened. It is recorded as done (never repeated), and the agent asks you what to do instead of claiming the corrected version.`);
        else addMoment(t, "stale", `Late result for ${x.call_id} ignored`,
          `${describeCall(c)} was superseded${c?.t_cancel != null ? ` at ${fmtT(c.t_cancel)}` : ""}; its result arrived at ${fmtT(t)} and is recorded but never used.`);
        break;
      }
      case "REC.dispatch":  // D17: started while the user was still speaking (read-only only)
        if (x.early) { S.early[x.call_id] = t; addMoment(t, "plan", `Search started before you finished: ${x.call_id}`, "Full duplex: read-only work may start on the partial sentence; a later correction supersedes it."); }
        break;
      case "PROP.speculative": if (S.specT == null) S.specT = t; break;
      case "PLANNER.request":
        if (!S.plans[x.req_id]) { S.plans[x.req_id] = { req: x.req_id, t0: t, based: x.based_on_seq, partial: x.purpose === "speculate" }; S.planOrder.push(x.req_id); }
        break;
      case "PROP.invalid": addMoment(t, "safety", "Invalid plan rejected", (x.errors || []).join("; ")); break;
      case "PROP.injection_dropped":
        if (x.tool) addMoment(t, "safety", `Injected ${words(x.tool)} dropped`, "Not asked for by the user, and built from tool-result content. Nothing was executed.");
        break;
      case "PROP.tainted": addMoment(t, "safety", `Refused a ${words(x.slot)} copied from a tool result`, "Only values the user said, or bound to a current result, may reach a side effect."); break;
      case "BARRIER.block":
        if (x.reason === "unauthorised" || String(x.reason).startsWith("ungrounded"))
          addMoment(t, "safety", `${title(x.op?.[1] || "operation")} held for confirmation`, x.reason === "unauthorised" ? "The user never asked for this operation." : `A value the user never said (${x.reason.split(":")[1]}).`);
        else if (x.reason === "replanning") addMoment(t, "safety", "Side effect waits for the newer plan", "Newer input is still being planned; nothing irreversible goes out meanwhile.");
        break;
      case "OP.locked": addMoment(t, "safety", "No second booking", "An earlier attempt of the same operation is still unresolved: the ledger blocks a duplicate."); break;
      case "EV.conflict": addMoment(t, "evidence", `Image says ${x.evidence}, you said ${x.current}`, "Conflict: the agent asks instead of overwriting you."); break;
      case "EV.not_active": addMoment(t, "evidence", "Image read before the task exists", "Kept; it is applied as soon as the task is created."); break;
      case "LWW.apply":
        if (x.source === "EVIDENCE") addMoment(t, "evidence", `From the image: ${words(x.slot)} = ${x.value}`, "Grounded evidence written to the current task.");
        break;
      case "LWW.reject": addMoment(t, "stale", `Stale ${words(x.slot)} from an older plan ignored`, `Written by input #${x.writer_seq}; the current value comes from newer input #${x.current_seq}.`); break;
      case "GOAL.create": addMoment(t, "plan", `New task: ${title(x.intent)}`, `Started by your request (input #${x.origin_seq}).`); break;
      case "GOAL.suspend": addMoment(t, "plan", "Previous task paused", x.goal_id); break;
      case "AUTH.confirmed": addMoment(t, "done", "You confirmed the exact operation", ""); break;
      case "PROP.reply": addMoment(t, "plan", "Request not supported: nothing changed", "No tool offers that task; the agent said so, dispatched nothing and left the current task as it was."); break;
    }
  }
  const byUser = ev && (ev.kind === "UserText" || ev.kind === "Interrupt");
  const interrupting = superseded.filter((x) => ["not_desired", "unattributed_marker", "goal_inactive"].includes(x.reason));
  if (byUser && interrupting.length) {
    const text = ev.payload?.text;
    // running = no result yet when superseded (the kernel cancels it); finished = its result was already in (replaced)
    const running = interrupting.filter((x) => S.calls[x.call_id]?.t_result == null);
    const finished = interrupting.filter((x) => S.calls[x.call_id]?.t_result != null);
    S.cuts.push({ t, label: text ? `“${text}”` : "interrupt", running: running.length });
    const who = `Same step as ${text ? `“${text}”` : "the interruption"} (0 ms, t=${fmtT(t)})`;
    if (running.length)
      addMoment(t, "interrupt", `Interrupted → ${running.length} running call${running.length > 1 ? "s" : ""} cancelled`,
        `${who}: ${running.map((x) => describeCall(S.calls[x.call_id])).join(", ")}.`);
    if (finished.length)
      addMoment(t, "interrupt", `Changed after the result → ${finished.length} earlier result${finished.length > 1 ? "s" : ""} no longer used`,
        `${who}: ${finished.map((x) => describeCall(S.calls[x.call_id])).join(", ")} had already finished; nothing to cancel, new work replaces it.`);
  }
}

function onOut(r) {
  const a = r.action, t = S.seqT[r.seq] ?? S.tLast, p = a.payload;
  currentStep?.seq === r.seq && currentStep.actions.push(a);
  switch (a.kind) {
    case "TOOL_CALL":
      S.calls[p.call_id] = { id: p.call_id, tool: p.tool, args: p.args, t_call: t, uses: p.uses, idem: p.idempotency_key };
      S.callOrder.push(p.call_id);
      break;
    case "CANCEL": { const c = S.calls[p.call_id]; if (c) c.t_cancel_sent = t; break; }
    case "SPEAK": pushSpeech({ t, kind: p.act, text: p.text }); break;
    case "CLARIFY": pushSpeech({ t, kind: "clarify", text: p.text }); break;
    case "FINAL": {
      pushSpeech({ t, kind: "final", text: p.text, grounded: p.grounded_on, snapshot: p.snapshot, ops: p.ops, act: p.act });
      if (p.act === "answer") addMoment(t, "done", "Answer grounded", `On ${(p.grounded_on || []).join(", ") || "committed operations"}; snapshot ${fmtSlots(p.snapshot?.slots)}.`);
      break;
    }
  }
}

function onFx(r) {
  const e = r.effect, t = S.seqT[r.seq] ?? S.tLast;
  if (e.effect === "perceive") S.percep.push({ req: e.req_id, kind: e.kind, ref: e.ref, eid: e.source_eid, t0: t });
  if (e.effect === "reason" && !S.plans[e.req_id]) { S.plans[e.req_id] = { req: e.req_id, t0: t, based: e.based_on_seq }; S.planOrder.push(e.req_id); }
}

function pushSpeech(s) {
  S.speech.push(s);
  const now = clock();
  if (voiceOut && S.status === "running" && now - s.t < 2.5 && "speechSynthesis" in window) {
    const u = new SpeechSynthesisUtterance(s.text);
    u.rate = 1.05;
    speechSynthesis.speak(u);
  }
}

function addMoment(t, kind, head, detail) {
  if (S.moments.some((m) => m.kind === kind && m.head === head && Math.abs(m.t - t) < 2)) return;  // same fact, repeated steps
  S.moments.push({ t, kind, head, detail, at: performance.now() });
}

// ---------------------------------------------------------------------------------------------- derived views

function clock() {
  if (S.status === "running" && S.epoch) return Math.max(S.tLast, ((Date.now() - S.epoch) / 1000) * (S.info?.speed || 1));
  return S.tLast;
}
function sideEffecting(tool) { return (META?.manifest || []).some((t) => t.name === tool && t.effect === "state_changing"); }
function describeCall(c) { return c ? `${c.id} ${words(c.tool)} (${argsShort(c.args)})` : "a call"; }
function argsShort(a = {}) {
  if (a.origin && a.destination) return `${a.origin} → ${a.destination}${a.date ? " · " + a.date : ""}`;
  return Object.entries(a).map(([k, v]) => `${words(k)} ${v}`).join(", ");
}
function fmtSlots(slots = {}) { return Object.entries(slots || {}).map(([k, v]) => `${k}=${v}`).join(", ") || "–"; }
function lastFinal() { return [...S.speech].reverse().find((s) => s.kind === "final"); }
function activeGoal() { const id = S.tables.meta.active_goal; return id ? S.tables.goals[id] : null; }
function goalSlots(gid) {
  const out = {};
  for (const [k, v] of Object.entries(S.tables.slots)) { const [g, n] = JSON.parse(k); if (g === gid) out[n] = v; }
  return out;
}
function callState(c) {
  const rel = c.rel || "DESIRED", out = c.outcome || (c.t_result != null ? "OK" : "PENDING");
  if (rel === "SUPERSEDED") return "superseded";
  if (out === "PENDING") return "running";
  if (out === "UNKNOWN") return "unknown";  // e.g. a booking that timed out: it may or may not have happened
  if (out === "FAILED_CLEAN") return "failed";
  const f = lastFinal();
  return f && (f.grounded || []).includes(c.id) ? "used" : "ok";
}

// ---------------------------------------------------------------------------------------------- render

function render() {
  const now = clock();
  $("#clock").textContent = `${now.toFixed(1)} s`;
  $("#session-label").textContent = sessionLabel();
  renderNow(now);
  renderTimeline(now);
  if (!S.dirty) return;
  S.dirty = false;
  $("#landing").hidden = S.status !== "idle";
  renderMoments();
  renderChain();
  renderFacts();
  renderTask();
  renderTrust();
  if (document.body.dataset.view === "story") renderConvo(); else renderSystem();
}

function sessionLabel() {
  if (!S.info) return "Not started";
  const what = S.info.mode === "guided" ? `Guided · ${S.info.title}${S.info.speed > 1 ? ` · ${S.info.speed}× playback` : ""}` : "Live";
  return { starting: `${what} · starting`, running: `${what} · running`, ended: `${what} · ended`, error: `${what} · agent stopped`, reconnecting: "Reconnecting…" }[S.status] || what;
}

function renderNow(now) {
  let tone = "", kicker = "Ready", head = "Ask for something, then change your mind while it works.", detail = "";
  const running = S.callOrder.map((id) => S.calls[id]).filter((c) => callState(c) === "running");
  const openPlans = S.planOrder.map((id) => S.plans[id]).filter((p) => p.t1 == null);
  const listening = S.percep.filter((p) => p.t1 == null);
  const recentCut = [...S.moments].reverse().find((m) => m.kind === "interrupt" && now - m.t < 2.5);  // cancel or replace
  const final = lastFinal();
  const g = activeGoal();
  const waiting = Object.values(S.tables.pending).find((p) => p.asked && !p.resolved && g && p.goal_id === g.goal_id);
  if (S.status === "idle") { /* default copy */ }
  else if (S.error) { tone = "error"; kicker = "Agent stopped"; head = "The agent process exited."; detail = S.error.split("\n").slice(-1)[0]; }
  else if (recentCut && S.status === "running") { tone = "interrupt"; kicker = "Change of plan"; head = recentCut.head; detail = recentCut.detail; }
  else if (listening.length) {
    tone = "listen"; kicker = listening[0].kind === "asr" ? "Listening" : "Looking";
    head = listening[0].kind === "asr" ? "Recognising your speech on-device…" : "Reading the image…";
    detail = "Perception runs in the background; the conversation is never blocked.";
  } else if (running.length) {
    tone = "run"; kicker = running.length > 1 ? `Working · ${running.length} calls in parallel` : "Working";
    head = running.map((c) => `${title(c.tool)} · ${argsShort(c.args)}`).join("   |   ");
    detail = `Running for ${(now - Math.min(...running.map((c) => c.t_call))).toFixed(1)} s. Say or type a correction any time.`;
  } else if (openPlans.length) { tone = "plan"; kicker = "Planning"; head = "Working out what to do…"; detail = "The planner proposes; the kernel checks every proposal before anything runs."; }
  else if (waiting) { tone = "wait"; kicker = "Waiting for you"; head = waiting.text; detail = "Nothing that depends on this runs until you answer."; }
  else if (S.speech.length && S.speech[S.speech.length - 1].kind === "narration" && (!final || S.speech[S.speech.length - 1].t > final.t)) {
    const last = S.speech[S.speech.length - 1];
    kicker = "Agent"; head = last.text;
    detail = final ? "The completed task on the left is unchanged." : "";
  }
  else if (final && final.act === "answer") { tone = "done"; kicker = "Answer"; head = final.text; detail = `Grounded on ${(final.grounded || []).join(", ") || "a committed operation"} · snapshot ${fmtSlots(final.snapshot?.slots)}`; }
  else if (S.status === "ended") { kicker = "Session ended"; head = S.verdict ? `Evaluator: ${S.verdict.passed ? "PASS" : "FAIL"} · internal score ${S.verdict.internal_score}` : "Session ended."; }
  else if (S.status === "running") { kicker = "Listening"; head = "Waiting for your next request."; }
  const el = $("#now");
  el.dataset.tone = tone;
  setText("#now-kicker", kicker); setText("#now-title", head); setText("#now-detail", detail);
}
function setText(sel, text) { const el = $(sel); if (el.textContent !== text) el.textContent = text; }

function renderMoments() {
  const box = $("#moments");
  const items = [...S.moments].slice(-8).reverse();
  if (!items.length) { box.innerHTML = `<div class="empty-note" data-k="empty">Key moments (interruptions, stale results, safety decisions, grounded answers) appear here as they happen.</div>`; return; }
  reconcile(box, items.map((m) => ({ key: `${m.kind}|${m.head}|${m.t}`, tag: "div", cls: `moment ${m.kind} ${performance.now() - m.at < 3000 ? "fresh" : ""}`,
    html: `<span class="t">${fmtT(m.t)}</span>${esc(m.head)}`, title: `${m.head}\n${m.detail}` })));
}

// The causal chain a judge should see, in order. Each stage lights up only when its event is in the journal.
function renderChain() {
  const box = $("#chain");
  if (S.status === "idle") { box.innerHTML = ""; return; }
  const first = (xs) => (xs.length ? Math.min(...xs) : null);
  const asked = first(S.inputs.filter((i) => i.kind !== "eot").map((i) => i.t));
  const eot = first(S.inputs.filter((i) => i.kind === "eot").map((i) => i.t));
  const spoke = first(S.speech.map((s) => s.t));
  const working = first(S.callOrder.map((id) => S.calls[id].t_call));
  const changed = first([...S.cuts.map((c) => c.t), ...S.classes.filter((c) => c.cls === "CORRECTION" || c.cls === "GOAL_SWITCH").map((c) => c.t)]);
  const cancelled = first(S.callOrder.map((id) => S.calls[id]).filter((c) => c.t_cancel != null && (c.t_result == null || c.t_result > c.t_cancel)
    && ["not_desired", "unattributed_marker", "goal_inactive"].includes(c.reason)).map((c) => c.t_cancel));
  // a side effect that completed despite the cancel is recorded as done, not "refused": only read-only results count
  const stale = first(S.callOrder.map((id) => S.calls[id]).filter((c) => c.stale && !sideEffecting(c.tool)).map((c) => c.t_result));
  let f = [...S.speech].filter((s) => s.kind === "final" && s.act === "answer").pop();
  const lastChange = S.cuts.length ? S.cuts[S.cuts.length - 1].t : null;
  if (f && lastChange != null && f.t < lastChange) f = undefined;  // that answer predates your latest change
  const ended = S.status === "ended";
  const short = box.clientWidth > 1100;  // room for the notes inline; otherwise they are in the tooltip
  const stage = (label, t, note) => {
    const state = t != null ? "done" : ended ? "absent" : "waiting";
    return `<li class="${state}" title="${esc(label + (t != null ? ` at ${fmtT(t)}` : "") + (note ? ` · ${note}` : ""))}"><b>${label}</b><span>${t != null ? fmtT(t) + (short && note ? " · " + esc(note) : "") : ended ? "not in this run" : "…"}</span></li>`;
  };
  const earlyIds = S.callOrder.filter((id) => S.early[id] != null);
  if (earlyIds.length) {  // D17: the full-duplex story, every stage read off a journaled event
    const early = S.early[earlyIds[0]];
    const more = first(S.inputs.filter((i) => i.kind !== "eot" && i.t > asked && (eot == null || i.t <= eot)).map((i) => i.t));
    const fresh = changed != null ? first(S.callOrder.map((id) => S.calls[id]).filter((c) => c.t_call >= changed).map((c) => c.t_call)) : null;
    box.innerHTML =
      stage("Partial input", asked) +
      stage("Understood so far", S.specT, "planned from the unfinished sentence") +
      stage("More input", more) +
      stage("Search started early", early, eot == null || early < eot ? "before end of turn" : "") +
      stage("You changed it", changed) +
      stage("Old work cancelled", cancelled, cancelled != null && changed != null ? (cancelled === changed ? "same step" : `+${(cancelled - changed).toFixed(2)} s`) : "") +
      stage("Late result refused", stale) +
      stage("New work", fresh) +
      stage("Grounded answer", f?.t, f ? `on ${(f.grounded || []).join(", ") || "committed operation"}` : "");
    return;
  }
  box.innerHTML =
    stage("You asked", asked) +
    stage("First reply", spoke, spoke != null && eot != null && spoke >= eot ? `+${(spoke - eot).toFixed(2)} s` : "") +
    stage("Work started", working, working != null ? S.calls[S.callOrder[0]].tool.replace(/_/g, " ") : "") +
    stage("You changed it", changed) +
    stage("Old work cancelled", cancelled, cancelled != null && changed != null ? (cancelled === changed ? "same step" : `+${(cancelled - changed).toFixed(2)} s`) : "") +
    stage("Stale result refused", stale) +
    stage("Grounded answer", f?.t, f ? `on ${(f.grounded || []).join(", ") || "committed operation"}` : "");
}

// Session facts: counts and latencies read off this session's journal (nothing estimated).
function renderFacts() {
  const box = $("#facts");
  if (S.status === "idle") { box.innerHTML = ""; return; }
  const calls = S.callOrder.map((id) => S.calls[id]);
  const superseded = calls.filter((c) => c.rel === "SUPERSEDED");
  const f = lastFinal();
  const used = f ? (f.grounded || []).length : 0;
  const stale = calls.filter((c) => c.stale).length;
  // a cut is recorded only when running work was superseded IN the step of the correcting input: latency 0 by construction
  const asr = S.percep.filter((p) => p.kind === "asr" && p.t1 != null && !p.failed).map((p) => p.t1 - p.t0);
  const sm = (META?.manifest || []).filter((t) => t.effect === "state_changing").map((t) => t.name);
  const effects = S.sideEffects.length;
  const fact = (v, l, tip) => `<div class="fact" title="${esc(tip)}"><b>${v}</b> <span>${l}</span></div>`;
  box.innerHTML =
    fact(calls.length, "calls", "every tool.call the agent emitted") +
    (Object.keys(S.early).length ? fact(Object.keys(S.early).length, "started early", "read-only calls started before the end of your turn (full duplex); state-changing calls never are") : "") +
    fact(superseded.length, "superseded", "calls the kernel marked no longer wanted (and cancelled if still running)") +
    fact(used, "in the answer", "the calls the final answer rests on") +
    fact(stale, "stale refused", "results that arrived for superseded calls: recorded, never used") +
    fact(S.cuts.some((c) => c.running) ? "0 ms" : "–", "interrupt → cancel", "decided in the same kernel step as the correcting input (virtual time)") +
    (asr.length ? fact(`${(asr.reduce((a, b) => a + b, 0) / asr.length).toFixed(2)} s`, "speech recognition", "mean on-device recognition time this session (voice interruptions land after recognition)") : "") +
    fact(sm.length ? `${effects}` : "–", "side effects", "state-changing tool executions in the tool world's own ledger") +
    fact(S.steps.length, "kernel steps", "each input handled by one deterministic, journaled step");
}

// timeline ------------------------------------------------------------------------------------------

// Cap each label at the space before the next item in the same row (the full text stays in the tooltip).
function fitRows(items, pps) {
  for (const row of [0, 1]) {
    const r = items.filter((it) => it.row === row && it.t != null).sort((a, b) => a.t - b.t);
    r.forEach((it, i) => {
      const room = i + 1 < r.length ? (r[i + 1].t - it.t) * pps - 6 : 420;
      it.style += `;max-width:${Math.max(70, Math.min(420, room)).toFixed(0)}px`;
    });
  }
}

// Keyed reconciliation: elements are created once and then only moved/resized/relabelled, so entrance animations
// play exactly once and running bars keep animating while the clock advances every frame.
function reconcile(box, items) {
  const existing = new Map([...box.children].map((el) => [el.dataset.k, el]));
  let prev = null;
  for (const it of items) {
    let el = existing.get(it.key);
    if (!el) { el = document.createElement(it.tag || "span"); el.dataset.k = it.key; }
    existing.delete(it.key);
    if (el.className !== it.cls) el.className = it.cls;
    if (el.getAttribute("style") !== it.style) el.setAttribute("style", it.style);
    if (it.html !== undefined && el._html !== it.html) { el.innerHTML = it.html; el._html = it.html; }
    const tip = it.title || "";
    if (el.title !== tip) el.title = tip;
    const next = prev ? prev.nextSibling : box.firstChild;
    if (el !== next) box.insertBefore(el, next);
    prev = el;
  }
  for (const el of existing.values()) el.remove();
}

const LANES = [["you", "You", "text · voice · image"], ["per", "Perception", "speech & image"], ["und", "Understanding", "fast path · planner"],
  ["tools", "Tools", "calls & results"], ["agent", "Agent", "what it says"]];

function timelineSkeleton(tl) {
  if (tl.dataset.built) return;
  tl.dataset.built = "1";
  tl.innerHTML = `<div class="axis" data-box="axis"></div><div class="lanes" style="position:relative"><div data-box="overlay"></div>
    ${LANES.map(([k, label, sub]) => `<div class="lane" data-lane="${k}"><div class="lane-label">${label}<small>${sub}</small></div><div data-box="${k}"></div></div>`).join("")}</div>`;
}

function renderTimeline(now) {
  const tl = $("#timeline");
  timelineSkeleton(tl);
  const box = (k) => tl.querySelector(`[data-box="${k}"]`);
  const width = Math.max(480, tl.clientWidth - 174);
  const win = Math.max(10, Math.ceil((now + 1.5) / 5) * 5);
  const pps = width / win;
  const x = (t) => Math.max(0, t * pps).toFixed(1);
  const w = (a, b) => Math.max(6, (b - a) * pps).toFixed(1);

  const step = win <= 15 ? 1 : win <= 40 ? 2 : 5;
  const ticks = [], grid = [];
  for (let s = 0; s <= win; s += step) {
    ticks.push({ key: `t${s}`, cls: "tick", style: `left:${x(s)}px`, html: `${s}s` });
    grid.push({ key: `g${s}`, tag: "i", cls: "gridline", style: `left:${x(s)}px` });
  }
  reconcile(box("axis"), ticks);

  // YOU (two rows so neighbouring inputs do not overlap)
  const you = [];
  let row = 0;
  S.inputs.forEach((i, n) => {
    if (i.kind === "eot") { you.push({ key: `e${n}`, tag: "i", cls: "item mark eot", style: `left:${x(i.t)}px;top:${row ? 36 : 4}px`, title: `end of turn ${fmtT(i.t)}` }); return; }
    const top = row ? 36 : 4; row = 1 - row;
    const corr = i.cls === "CORRECTION" || i.cls === "GOAL_SWITCH";
    const icon = { text: "⌨", heard: "🎙", audio: "🎙", image: "▣", interrupt: "✋" }[i.kind];
    const label = i.kind === "audio" ? (i.heard != null ? `“${esc(i.heard)}”` : i.notHeard ? "(speech not recognised)" : `recognising… (${esc(i.ref.split("/").pop())})`) : i.kind === "image" ? `image: ${esc(i.ref.split("/").pop())}`
      : i.kind === "interrupt" ? "interrupt" : `“${esc(i.text)}”`;
    you.push({ key: `i${n}`, t: i.t, row: top > 4 ? 1 : 0, cls: `item pill ${corr ? "correction" : ""}`, style: `left:${x(i.t)}px;top:${top}px`,
      html: `<span class="ico">${icon}</span>${label}`, title: `${fmtT(i.t)} ${i.kind} ${i.text || i.ref || ""}${i.cls ? " · " + i.cls : ""}` });
  });
  fitRows(you, pps);
  reconcile(box("you"), you);

  // PERCEPTION
  reconcile(box("per"), S.percep.map((p, idx) => {
    const end = p.t1 ?? now, top = idx % 2 ? 26 : 4;
    const claims = fmtSlots(Object.fromEntries(Object.entries(p.claims || {}).map(([k, v]) => [k, v[0]])));
    const what = p.kind === "asr" ? (p.t1 == null ? "recognising speech…" : p.failed ? "not understood" : `heard “${p.text}”`)
      : (p.t1 == null ? "reading image…" : p.failed ? "nothing readable" : `read ${claims}`);
    const src = p.backend === "scripted_fallback" ? " · fallback" : p.backend ? ` · ${p.backend === "asr" ? "on-device ASR" : "OCR"} ${p.wall != null ? p.wall.toFixed(2) + " s" : ""}` : "";
    return { key: p.req, cls: `item span ev ${p.t1 == null ? "open" : ""} ${p.failed ? "fail" : ""}`, style: `left:${x(p.t0)}px;width:${w(p.t0, end)}px;top:${top + 8}px`,
      html: esc(what + src), title: what + src };
  }));

  // UNDERSTANDING (fast path tags) & PLANNING (planner spans)
  const und = S.classes.map((c, n) => ({
    key: `c${n}`, cls: `item tag ${c.cls}`, style: `left:${x(c.t)}px;top:4px`, title: `fast understanding, inside the kernel step: ${c.cls}`,
    html: esc(c.cls === "CORRECTION" ? `correction${c.attributed?.length ? ": " + c.attributed.join(", ") : ""}` : words(c.cls).toLowerCase()),
  }));
  S.planOrder.forEach((id) => {
    const p = S.plans[id], end = p.t1 ?? now;
    const lab = p.partial ? "partial" : p.t1 == null ? "planning…" : p.ok ? `plan: ${words(p.payload?.intent || "no change")}` : `plan failed (${p.reason})`;
    const fb = (p.detail?.fallback ? " (model failed → deterministic fallback)" : "") +
      (p.detail?.fixture ? `\ndeterministic planner: matched known request “${p.detail.fixture}” (similarity ${p.detail.similarity})` : "");
    und.push({ key: id, cls: `item span plan ${p.t1 == null ? "open" : ""} ${p.ok === false && !p.partial ? "fail" : ""} ${p.partial ? "partial" : ""}`, style: `left:${x(p.t0)}px;width:${w(p.t0, end)}px;top:34px`,
      html: esc(lab), title: `${id}: ${p.partial ? "plan of the unfinished sentence (D17: read-only work only; questions wait for the end of turn)" : lab}${fb}` });
  });
  reconcile(box("und"), und);

  // TOOLS: one row per call; superseded bars turn hatched, a dashed tail shows the tool still running, a red mark the stale result
  const tools = [];
  const ROW = innerHeight < 720 ? 30 : 34;  // tool rows: tighter on short screens so the whole story stays visible
  S.callOrder.forEach((id, idx) => {
    const c = S.calls[id], st = callState(c), top = 8 + idx * ROW;
    const endActive = st === "superseded" ? (c.t_cancel ?? c.t_result ?? now) : (c.t_result ?? now);
    const tip = `${c.id} ${c.tool} ${JSON.stringify(c.args)}\ncalled ${fmtT(c.t_call)}` + (c.t_cancel != null ? `\nsuperseded ${fmtT(c.t_cancel)} (${c.reason})` : "") +
      (S.cancelIgnored[c.id] != null ? "\nthe tool ignored the cancel and kept running" : "") +
      (c.t_result != null ? `\nresult ${fmtT(c.t_result)}${c.stale ? " — STALE: recorded, never used" : ""}` : "");
    const early = S.early[id] != null;
    tools.push({ key: id, cls: `item call ${st}${early ? " early" : ""}`, style: `left:${x(c.t_call)}px;width:${w(c.t_call, endActive)}px;top:${top}px`,
      html: `<span class="cid">${c.id}</span>${early ? `<span class="early-tag">early</span>` : ""}<span class="label">${esc(title(c.tool) + " · " + argsShort(c.args))}</span>${st === "used" ? " ✓" : ""}`,
      title: tip + (early ? "\nstarted before the end of your turn (full duplex, read-only)" : "") });
    if (st === "superseded" && c.t_cancel != null && (c.t_result == null || c.t_result > c.t_cancel))
      tools.push({ key: `${id}-tail`, cls: "item ghost-tail", style: `left:${x(c.t_cancel)}px;width:${w(c.t_cancel, c.t_result ?? now)}px;top:${top}px`,
        title: "cancelled, but the (simulated) tool keeps running; its result will not be used" });
    if (c.stale) {
      const sc = sideEffecting(c.tool);
      tools.push({ key: `${id}-stale`, cls: `item stale-hit ${sc ? "committed" : ""}`, style: `left:${x(c.t_result)}px;top:${top - 4}px`,
        html: `<span>${sc ? "completed despite cancel · recorded, never repeated" : "stale · ignored"}</span>`,
        title: sc ? `the tool ignored the cancel; the side effect happened at ${fmtT(c.t_result)}. Recorded as committed; no second attempt.` : `late result at ${fmtT(c.t_result)}: recorded, never used` });
    }
    else if (c.t_result != null && st !== "superseded")
      tools.push({ key: `${id}-res`, tag: "i", cls: "item result-dot", style: `left:${x(c.t_result)}px;top:${top + 9}px;background:${st === "used" ? "var(--done)" : st === "failed" ? "var(--stale)" : "#7f8aa3"}`,
        title: `result ${fmtT(c.t_result)}` });
  });
  reconcile(box("tools"), tools);
  tl.querySelector('[data-lane="tools"]').style.height = `${Math.max(46, 16 + S.callOrder.length * ROW)}px`;

  // AGENT
  const agent = S.speech.map((s, n) => ({
    key: `s${n}`, cls: `item speech ${s.kind}`, style: `left:${x(s.t)}px;top:${n % 2 ? 36 : 4}px`, title: `${fmtT(s.t)} ${s.text}`,
    html: `${s.kind === "final" ? "★ " : s.kind === "clarify" ? "? " : ""}${esc(s.text)}`, t: s.t, row: n % 2,
  }));
  fitRows(agent, pps);
  reconcile(box("agent"), agent);

  // overlay: grid, interruption cut lines, the moving "now"
  const overlay = [...grid, ...S.cuts.map((c, n) => ({ key: `cut${n}`, tag: "i", cls: "cutline", style: `left:${x(c.t)}px`, html: `<span>✂ ${esc(c.label)}</span>` }))];
  if (S.status === "running") overlay.push({ key: "now", tag: "i", cls: "nowline", style: `left:${x(now)}px` });
  reconcile(box("overlay"), overlay);
}

// task & trust ---------------------------------------------------------------------------------------

const SRC = { T0: ["heard", "fast understanding, in the same step"], PLANNER: ["understood", "from the planner, checked by the kernel"],
  EVIDENCE: ["from image", "read from the image (OCR)"],
  PARTIAL: ["heard so far", "planned from the unfinished sentence; confirmed only when the whole turn is planned"], USER: ["you confirmed", ""] };

function renderTask() {
  const g = activeGoal();
  const body = $("#task-body");
  if (!g) {
    const planning = S.planOrder.some((id) => S.plans[id].t1 == null);
    body.className = "empty-note";
    body.textContent = S.status === "idle" ? "No task yet." : planning ? "Understanding your request…" : "No active task.";
    return;
  }
  body.className = "";
  const slots = goalSlots(g.goal_id);
  const order = [];
  for (const n of g.graph || []) for (const [, b] of n.args) if (b[0] === "slot" && !order.includes(b[1])) order.push(b[1]);
  for (const n of Object.keys(slots)) if (!order.includes(n)) order.push(n);
  const field = (name, big) => {
    const r = slots[name];
    const prevKey = `${g.goal_id}/${name}`, val = r ? r.value : undefined;
    const changed = S.prevSlots[prevKey] !== undefined && S.prevSlots[prevKey] !== JSON.stringify(val);
    S.prevSlots[prevKey] = JSON.stringify(val);
    const hist = r ? [...new Set((r.history || []).map((h) => h[0]).filter((v) => v != null && v !== r.value))] : [];
    const src = r ? SRC[r.source] || [r.source.toLowerCase(), ""] : null;
    const value = !r ? `<div class="field-value" style="color:var(--muted)">?</div>`
      : r.value == null ? `<div class="field-value changing" title="a correction retracted the old value; the new one is being resolved">changing…</div>`
      : `<div class="field-value">${esc(r.value)}</div>`;
    return `<div class="field ${big ? "" : "field-row"} ${changed ? "flash" : ""}">
      <div class="field-label">${esc(words(name))}</div>
      <div>${value}
        ${hist.length ? `<div class="field-history">was ${hist.map((h) => `<s>${esc(h)}</s>`).join(" ")}</div>` : ""}
        ${src ? `<div class="src ${r.source}" title="${esc(src[1])}">${esc(src[0])}${r.confirmed ? " · confirmed" : " · unconfirmed"}</div>` : `<div class="src">not given yet</div>`}
      </div></div>`;
  };
  const pendingOpen = Object.values(S.tables.pending).some((p) => p.goal_id === g.goal_id && !p.resolved);
  const completed = g.final_keys != null && !pendingOpen;
  let html = `<div class="task-title">${esc(title(g.intent))}${completed ? ' <span class="done-badge">✓ completed</span>' : ""}</div>
    <div class="task-sub">task ${g.goal_id} · plan revision ${g.plan_rev} · ${(g.graph || []).length} step${(g.graph || []).length === 1 ? "" : "s"}: ${(g.graph || []).map((n) => words(n.tool)).join(" → ")}</div>`;
  if (order.includes("origin") && order.includes("destination")) {
    html += `<div class="route">${field("origin", true)}<div class="arrow">→</div>${field("destination", true)}</div>`;
    order.filter((n) => n !== "origin" && n !== "destination").forEach((n) => (html += field(n)));
  } else order.forEach((n) => (html += field(n)));
  const pend = Object.values(S.tables.pending).filter((p) => p.goal_id === g.goal_id && !p.resolved);
  for (const p of pend) html += `<div class="pending"><b>${p.asked ? "Asked you" : "Needs your input"}</b>${esc(p.text)}</div>`;
  const paused = Object.values(S.tables.goals).filter((x) => x.status === "SUSPENDED");
  if (paused.length) html += `<div class="paused">Paused: ${paused.map((x) => esc(title(x.intent))).join(", ")}</div>`;
  body.innerHTML = html;
}

function renderTrust() {
  const f = lastFinal();
  const body = $("#trust-body");
  const refusedCalls = S.callOrder.map((id) => S.calls[id]).filter((c) => c.rel === "SUPERSEDED");
  const sm = (META?.manifest || []).filter((t) => t.effect === "state_changing").map((t) => t.name);
  const smCalls = S.callOrder.map((id) => S.calls[id]).filter((c) => sm.includes(c.tool));
  if (!f && !refusedCalls.length && !S.verdict && !smCalls.length) {
    body.className = "empty-note";
    body.textContent = "The answer will appear here with the exact tool results it rests on, and the results it refused to use.";
    return;
  }
  body.className = "";
  let html = "";
  const outdated = f && S.cuts.length && f.t < S.cuts[S.cuts.length - 1].t;
  if (f) html += outdated ? `<div class="fineprint" style="margin:0 0 4px">Earlier answer, before your latest change (a new one is on its way):</div><div class="answer" style="opacity:.6">${esc(f.text)}</div>`
    : `<div class="answer">${esc(f.text)}</div>`;
  html += `<ul class="basis">`;
  if (f && !outdated) for (const id of f.grounded || []) {
    const c = S.calls[id];
    html += `<li class="used">Used <code>${esc(id)}</code> ${esc(c ? `${words(c.tool)} (${argsShort(c.args)})` : "")}${c?.t_result != null ? ` — result at ${fmtT(c.t_result)}` : ""}</li>`;
  }
  for (const c of refusedCalls) {
    const why = { not_desired: "your correction made it obsolete", unattributed_marker: "you interrupted", goal_inactive: "you switched task",
      timeout: "timed out", error: "failed", deadline: "deadline" }[c.reason] || c.reason;
    const sc = sideEffecting(c.tool);
    html += `<li class="refused">${sc ? "Superseded" : "Not used"} <code>${esc(c.id)}</code> ${esc(words(c.tool))} (${esc(argsShort(c.args))}) — ${esc(why)}${c.t_cancel != null ? ` at ${fmtT(c.t_cancel)}` : ""}` +
      `${c.stale ? (sc ? `; the tool ignored the cancel and it completed at ${fmtT(c.t_result)} — recorded as done, never repeated, and not claimed as your corrected request`
        : `; its result arrived at ${fmtT(c.t_result)} and was ignored`) : c.t_result == null ? "; no result yet" : ""}</li>`;
  }
  for (const tool of new Set(smCalls.map((c) => c.tool))) {
    const n = S.sideEffects.filter((e) => e.tool === tool).length;
    const attempts = smCalls.filter((c) => c.tool === tool).length;
    html += `<li class="ledger">${esc(title(tool))}: executed ${n}× in the tool world, ${attempts} attempt${attempts === 1 ? "" : "s"} sent — duplicates blocked by the operation ledger</li>`;
  }
  html += `</ul>`;
  if (S.verdict) {
    const v = S.verdict, cats = v.categories;
    const bar = (k, label) => cats[k] == null ? "" : `<div class="bar"><span>${label}</span><span class="bar-track"><span class="bar-fill" style="width:${cats[k] * 100}%"></span></span><span>${Math.round(cats[k] * 100)}</span></div>`;
    const failed = v.checks.filter((c) => !c.passed).map((c) => c.check);
    html += `<div class="verdict"><div class="verdict-head"><span class="eyebrow" style="margin:0">Evaluator</span>
      <span class="${v.passed ? "verdict-pass" : "verdict-fail"}">${v.passed ? "PASS" : "FAIL"} · ${v.internal_score}</span></div>
      <div class="bars">${bar("task_completion", "Task completion")}${bar("interruption_recovery", "Interruption recovery")}${bar("response_latency", "Response latency")}${bar("safety_protocol", "Safety & protocol")}</div>
      ${failed.length ? `<div class="fineprint">Failed checks: ${esc(failed.join(", "))}</div>` : ""}
      <div class="fineprint">${v.checks.length} checks, unchanged black-box evaluator, this run's wire trace. INTERNAL metric, not a Samsung score.</div></div>`;
  }
  body.innerHTML = html;
}

// right rail -----------------------------------------------------------------------------------------

function renderConvo() {
  const items = [];
  let streamed = null;  // one line per spoken turn: the words the streaming recogniser sent while you spoke
  for (const i of S.inputs) {
    if (i.kind === "eot") { streamed = null; continue; }
    if (i.streamed) {
      if (!streamed) { streamed = { t: i.t, words: [] }; items.push(streamed); }
      streamed.words.push(i.text);
      streamed.html = `<li class="user"><span class="t">${fmtT(streamed.t)}</span><div><div class="who">You · voice, streamed</div><div class="say">🎙 <span class="heard">heard “${esc(streamed.words.join(" "))}”</span></div></div></li>`;
      continue;
    }
    if (i.kind === "heard") continue;
    let say = i.kind === "text" ? esc(i.text) : i.kind === "interrupt" ? "✋ (interrupt)" : "";
    if (i.kind === "audio") {
      const span = S.percep.find((p) => p.eid === i.eid && p.kind === "asr");
      say = `🎙 <span class="heard">${span?.t1 != null ? (span.failed ? "not understood" : `heard “${esc(span.text)}”`) : "recognising…"}</span>`;
    }
    if (i.kind === "image") {
      const span = S.percep.find((p) => p.eid === i.eid && p.kind === "vision");
      say = `▣ image <span class="heard">${span?.t1 != null ? (span.failed ? "— nothing readable" : `— read ${esc(fmtSlots(Object.fromEntries(Object.entries(span.claims || {}).map(([k, v]) => [k, v[0]]))))}`) : "— reading…"}</span>`;
    }
    items.push({ t: i.t, html: `<li class="user"><span class="t">${fmtT(i.t)}</span><div><div class="who">You</div><div class="say">${say}</div></div></li>` });
  }
  for (const s of S.speech) items.push({ t: s.t, html: `<li class="agent ${s.kind}"><span class="t">${fmtT(s.t)}</span><div><div class="who">Agent${s.kind === "clarify" ? " · asks" : s.kind === "final" ? " · answer" : ""}</div><div class="say">${esc(s.text)}</div></div></li>` });
  items.sort((a, b) => a.t - b.t);
  const box = $("#convo");
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
  box.innerHTML = items.length ? items.map((i) => i.html).join("") : `<li class="empty-note">Nothing said yet.</li>`;
  if (atBottom) box.scrollTop = box.scrollHeight;
}

const RULES = {
  "T0.classify": (x) => [`fast understanding: <code>${x.cls}</code>${x.attributed?.length ? ` · ${x.attributed.join(", ")}` : ""}${x.writes?.length ? ` · writes ${x.writes.join(", ")}` : ""}`, x.cls === "CORRECTION" ? "interrupt" : ""],
  "LWW.apply": (x) => [`<code>${x.slot}</code> = <code>${esc(JSON.stringify(x.value))}</code> (${(SRC[x.source] || [x.source])[0]}, writer #${x.writer_seq})`, ""],
  "LWW.reject": (x) => [`kept newer <code>${x.slot}</code>: older write #${x.writer_seq} &lt; #${x.current_seq}`, "stale"],
  "REL.supersede": (x) => [`superseded <code>${x.call_id}</code> (${x.reason})`, "interrupt"],
  "ADM.stale": (x) => [`late result for <code>${x.call_id}</code>: recorded, never used`, "stale"],
  "ADM.outcome": (x) => [`<code>${x.call_id}</code> outcome ${x.frm} → ${x.to}`, ""],
  "ADM.ignored": (x) => [`result for <code>${x.call_id}</code> ignored (already ${x.current})`, "stale"],
  "REC.dispatch": (x) => [`dispatch <code>${x.call_id}</code>${x.op ? " (operation " + x.op.join("/") + ")" : ""}${x.early ? " — early: before the end of your turn (read-only)" : ""}`, ""],
  "PLANNER.request": (x) => [`asked the planner <code>${x.req_id}</code> (sees input up to #${x.based_on_seq})${x.purpose === "speculate" ? " — partial sentence" : ""}`, ""],
  "PROP.speculative": (x) => [`partial plan <code>${x.req_id}</code> applied: values marked partial; no questions while you speak`, ""],
  "PROP.speculative_no_switch": (x) => [`partial plan <code>${x.req_id}</code> would switch task: waits for the end of turn`, "safety"],
  "PROP.speculative_late": (x) => [`partial plan <code>${x.req_id}</code> arrived after the turn ended: ignored`, "stale"],
  "PLANNER.skip": () => ["status-only turn: answered from state, planner not called", ""],
  "PLAN.graph": (x) => [`plan for ${x.goal_id}: ${x.nodes.join(", ")}`, ""],
  "PLAN.rev": (x) => [`desired work changed (revision ${x.plan_rev})`, ""],
  "GOAL.create": (x) => [`new task <code>${x.goal_id}</code>: ${words(x.intent)}`, "done"],
  "GOAL.suspend": (x) => [`paused task <code>${x.goal_id}</code>`, ""],
  "PROP.structure_stale": (x) => [`older plan <code>${x.req_id}</code>: structure ignored`, "stale"],
  "PROP.graph_stale": (x) => [`older plan <code>${x.req_id}</code>: graph not applied`, "stale"],
  "PROP.invalid": (x) => [`rejected invalid plan: ${esc((x.errors || []).join("; "))}`, "safety"],
  "PROP.failed": (x) => S.plans[x.req_id]?.partial ? [`partial sentence: nothing to plan yet (${x.reason})`, ""] : [`planner failed (${x.reason})`, "safety"],
  "PROP.tainted": (x) => [`refused tool-derived value for <code>${x.slot}</code>`, "safety"],
  "PROP.injection_dropped": (x) => [`dropped injected ${x.tool ? words(x.tool) : "write " + x.slot}`, "safety"],
  "BARRIER.block": (x) => [`held back ${(x.op || []).join("/")}: ${x.reason}`, "safety"],
  "OP.locked": (x) => [`operation ${(x.op || []).join("/")} locked: no duplicate`, "safety"],
  "PENDING.open": (x) => [`question opened <code>${x.pid}</code>`, ""],
  "PENDING.resolved": (x) => [`question resolved <code>${x.pid}</code>`, "done"],
  "HOLD.set": (x) => [`hold: side effects paused while you talk (${x.by})`, ""],
  "HOLD.clear": (x) => [`hold cleared (${x.by})`, ""],
  "TURN.open": () => ["your turn started", ""], "TURN.close": (x) => [`turn ended${x.inferred ? " (silence)" : ""}`, ""],
  "TURN.await_transcript": () => ["end of turn: waiting for the transcript", ""],
  "TIMER.fire": (x) => [`timer: ${words(x.purpose)}`, ""],
  "SWITCH.pending": () => ["goal switch: old task's work withheld until the planner answers", ""],
  "T0.retraction_reverted": (x) => [`restored <code>${x.slot}</code> = ${esc(x.value)}`, ""],
  "EV.conflict": (x) => [`image says ${x.evidence}, you said ${x.current}: ask`, "safety"],
  "EV.not_active": () => ["image evidence kept until its task exists", ""],
  "SLOT.confirm": (x) => [`<code>${x.slot}</code> confirmed (${x.by})`, ""],
  "AUTH.confirmed": () => ["you confirmed the exact operation", "done"],
};

function describeEvent(e) {
  if (!e) return "step";
  const p = e.payload || {};
  switch (e.kind) {
    case "UserText": return p.source === "asr" ? `Heard “${esc(p.text)}”` : p.source === "asr_stream" ? `Heard so far “${esc(p.text)}” (streaming)` : `You: “${esc(p.text)}”`;
    case "Media": return p.kind === "image" ? "Image received" : "Audio received";
    case "EndOfTurn": return "End of your turn";
    case "ToolResult": return `Result for <code>${p.call_id}</code> (${p.outcome})`;
    case "Proposal": return `Plan <code>${p.req_id}</code> arrived`;
    case "ProposalFailed": return `Plan <code>${p.req_id}</code> failed (${p.reason})`;
    case "Evidence": return "Image evidence";
    case "Timer": return `Timer: ${words(p.purpose)}`;
    default: return words(e.kind);
  }
}

function renderSystem() {
  const tab = document.querySelector('.tabs [aria-selected="true"]').dataset.tab;
  if (tab === "why") {
    const steps = S.steps.filter((s) => (s.rules.length && !(s.rules.length === 1 && s.rules[0].rule === "TIMER.stale")) || s.actions.length).slice(-80).reverse();
    $("#tab-why").innerHTML = steps.length ? steps.map((s) => {
      const lis = s.rules.filter((x) => RULES[x.rule]).map((x) => { const [txt, cls] = RULES[x.rule](x); return `<li class="${cls}">${txt}</li>`; });
      for (const a of s.actions) {
        const p = a.payload;
        const txt = a.kind === "TOOL_CALL" ? `→ tool.call <code>${p.call_id}</code> ${words(p.tool)} ${esc(argsShort(p.args))}` : a.kind === "CANCEL" ? `→ tool.cancel <code>${p.call_id}</code>`
          : a.kind === "FINAL" ? `→ final answer grounded on ${esc((p.grounded_on || []).join(", ") || "–")}`
          : a.kind === "SNAPSHOT" ? `→ state snapshot after the interruption: ${esc(fmtSlots(p.snapshot?.slots))}` : `→ ${a.kind.toLowerCase()}: “${esc(p.text || "")}”`;
        lis.push(`<li class="${a.kind === "CANCEL" ? "interrupt" : a.kind === "FINAL" ? "done" : ""}">${txt}</li>`);
      }
      return `<div class="step"><div class="step-head"><span class="t">${fmtT(s.t)}</span><span class="what">${describeEvent(s.ev)}</span><span class="t">#${s.seq}</span></div><ul>${lis.join("")}</ul></div>`;
    }).join("") : `<div class="empty-note">Every kernel step appears here: the input, the rules that fired, and the actions it emitted.</div>`;
  } else if (tab === "state") {
    const calls = Object.values(S.tables.calls);
    const slots = Object.entries(S.tables.slots).map(([k, v]) => [JSON.parse(k), v]);
    const reqs = Object.values(S.tables.reqs);
    const ops = Object.entries(S.tables.ops);
    $("#tab-state").innerHTML = `
      <div class="kt-title">Calls (relevance × outcome)</div>
      <table class="kt"><tr><th>call</th><th>relevance</th><th>outcome</th></tr>
      ${calls.map((c) => `<tr><td>${c.call_id} <span class="sub">${esc(words(c.tool))}<br>${esc(argsShort(JSON.parse(c.args_json)))}</span></td>
        <td class="${c.relevance}">${c.relevance}${c.superseded_reason ? `<br><span class="sub">${esc(c.superseded_reason)}</span>` : ""}</td><td class="${c.outcome}">${c.outcome}</td></tr>`).join("") || `<tr><td colspan="3">–</td></tr>`}</table>
      <div class="kt-title">Slots (last writer wins)</div>
      <table class="kt"><tr><th>task</th><th>slot</th><th>value</th><th>source</th><th>writer</th><th>conf.</th></tr>
      ${slots.map(([[g, n], r]) => `<tr><td>${g}</td><td>${esc(n)}</td><td>${esc(JSON.stringify(r.value))}</td><td>${r.source}</td><td>#${r.writer_seq}</td><td>${r.confirmed ? "✓" : ""}</td></tr>`).join("") || `<tr><td colspan="6">–</td></tr>`}</table>
      <div class="kt-title">Operation ledger (state-changing)</div>
      <table class="kt"><tr><th>operation</th><th>attempts</th></tr>
      ${ops.map(([k, v]) => `<tr><td>${esc(JSON.parse(k).join("/"))}</td><td>${esc((v || []).join(", "))}</td></tr>`).join("") || `<tr><td colspan="2">–</td></tr>`}</table>
      <div class="kt-title">Planner requests</div>
      <table class="kt"><tr><th>req</th><th>based on</th><th>open</th><th>may change task</th></tr>
      ${reqs.map((r) => `<tr><td>${r.req_id}</td><td>#${r.based_on_seq}</td><td>${r.open ? "open" : "answered"}</td><td>${r.may_change ? "yes" : "no"}</td></tr>`).join("") || `<tr><td colspan="4">–</td></tr>`}</table>
      <div class="fineprint">Mirrored from the agent's journal: each kernel step's recorded changes, applied in order.</div>`;
  } else {
    const lines = S.wire.slice(-160).reverse().filter((w) => w.msg && w.msg.type !== "agent.ready");
    $("#tab-wire").innerHTML = lines.length ? lines.map((w) => `<div class="wire-line"><span>${fmtT(w.t)}</span><span class="dir-${w.dir}">${w.dir === "in" ? "↓" : "↑"}</span>
      <span><span class="ty">${esc(w.msg.type)}</span> ${esc(JSON.stringify(w.msg.data || {})).slice(0, 180)}</span></div>`).join("")
      : `<div class="empty-note">PRISM-LOCAL/0 messages (this project's local protocol, not Samsung's) between the harness and the agent.</div>`;
  }
}

function renderHonesty() {
  const c = S.caps || META?.capabilities;
  if (!c) return;
  const chip = (cls, label, value, tip) => `<span class="chip ${cls}" tabindex="0" title="${esc(tip)}"><span class="dot"></span>${label} <b>${value}</b></span>`;
  const chips =
    chip(c.asr.real ? "real" : "fallback", "Speech", c.asr.real ? "on-device" : "fallback", c.asr.detail) +
    chip(c.ocr.real ? "real" : "fallback", "Vision", c.ocr.real ? "OCR" : "fallback", c.ocr.detail) +
    chip(c.planner.mode === "model" ? "real" : "fallback", "Planner", c.planner.mode === "model" ? "model" : "deterministic", c.planner.detail) +
    chip("sim", "Tools", "simulated", c.tools.detail) +
    (S.info?.speed > 1 ? chip("sim", "Clock", `${S.info.speed}× playback`, "Guided demo played faster: virtual time runs at this multiple of real time; event order and the evaluator result are unchanged.")
      : chip("real", "Clock", "real time", c.clock.detail));
  // wide screens: the chips inline; narrower ones: one "What's real" chip that expands on hover/focus (same content)
  $("#honesty").innerHTML = `<div class="honesty-full">${chips}</div>
    <div class="honesty-compact"><button class="chip summary" aria-haspopup="true"><span class="dot"></span>What's real ▾</button>
      <div class="honesty-pop" role="list">${chips}</div></div>`;
}

// ---------------------------------------------------------------------------------------------- actions

async function api(path, body, raw) {
  const res = await fetch(path, { method: "POST", headers: raw ? { "Content-Type": "application/octet-stream" } : { "Content-Type": "application/json" }, body: raw ? body : JSON.stringify(body || {}) });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

async function startLive() {
  await api("/api/session", { mode: "live", preset: $("#preset").value });
}
async function ensureLive() {
  if (!S.info || S.info.mode !== "live" || S.status === "ended" || S.status === "error") {
    await startLive();
    await new Promise((r) => setTimeout(r, 150));
  }
}
async function startGuided(key) {
  $("#library").close();
  try { await api("/api/session", { mode: "guided", scenario: key, speed: Number($("#guided-speed").value) }); lastGuided = key; } catch (e) { toast(e.message); }
}
let lastGuided = null;

async function sendText(text) {
  if (!text.trim()) return;
  try { await ensureLive(); await api("/api/input", { kind: "text", text }); } catch (e) { toast(e.message); }
}
async function sendMedia(kind, ref) {
  try { await ensureLive(); await api("/api/input", { kind, ref }); } catch (e) { toast(e.message); }
}
async function uploadAndSend(kind, blob, ext) {
  try {
    const { ref } = await api(`/api/upload?ext=${ext}`, blob, true);
    await sendMedia(kind, ref);
  } catch (e) { toast(`Upload failed: ${e.message}`); }
}

function showMode() {
  const guided = S.info?.mode === "guided";
  $("#dock-live").hidden = guided;
  $("#dock-guided").hidden = !guided;
  if (guided && META) {
    const g = META.guided.find((x) => x.key.endsWith(S.info.scenario));
    $("#guided-title").textContent = `${S.info.title} — ${g?.setup || ""}`;
    $("#guided-watch").innerHTML = (g?.watch || []).map((w) => `<li>${esc(w)}</li>`).join("");
  }
}

let toastTimer;
function toast(msg, info = false) {
  const t = $("#toast");
  t.textContent = msg; t.className = `toast ${info ? "info" : ""}`; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), 4200);
}

// ---------------------------------------------------------------------------------------------- wiring

async function init() {
  try { META = await (await fetch("/api/meta")).json(); } catch { toast("Cannot reach the console server."); return; }
  renderHonesty();
  $("#preset").innerHTML = Object.entries(META.presets).map(([k, v]) => `<option value="${k}" title="${esc(v.detail)}">${esc(v.label)}</option>`).join("");
  $("#prompts").innerHTML = META.prompts.map((p) => `<button class="prompt" data-text="${esc(p.text)}">${esc(p.text)}<small>${esc(p.hint)}</small></button>`).join("");
  $("#clips-menu").innerHTML = `<div class="menu-note">Plays the clip here and sends the same audio to the agent's speech recogniser.</div>` +
    META.clips.map((c) => `<button data-ref="${esc(c.ref)}">♪ ${esc(c.label)}</button>`).join("");
  $("#image-menu").innerHTML = META.images.map((i) => `<button data-ref="${esc(i.ref)}"><img src="/media/${esc(i.ref)}" alt="" width="54" style="border-radius:3px"> ${esc(i.label)}</button>`).join("") +
    `<button data-upload="1">⤒ Upload a PNG/JPEG…</button><div class="menu-note">OCR reads dates, FROM/TO airport codes and flight numbers.</div>`;
  $("#library-list").innerHTML = META.guided.map((g, i) => `<li><button data-key="${esc(g.key)}"><span class="lib-title">${i + 1}. ${esc(g.title)}</span><span class="lib-mod">${esc(g.modality)}</span><div class="lib-setup">${esc(g.setup)}</div></button></li>`).join("");

  $("#prompts").addEventListener("click", (e) => { const b = e.target.closest(".prompt"); if (b) sendText(b.dataset.text); });
  $("#text-form").addEventListener("submit", (e) => { e.preventDefault(); const i = $("#dock-text"); sendText(i.value); i.value = ""; });
  document.querySelectorAll(".view-switch button").forEach((b) => b.addEventListener("click", () => {
    document.body.dataset.view = b.dataset.view;
    document.querySelectorAll(".view-switch button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    S.dirty = true;
  }));
  document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    ["why", "state", "wire"].forEach((t) => ($(`#tab-${t}`).hidden = t !== b.dataset.tab));
    S.dirty = true;
  }));
  const lib = $("#library");
  $("#open-library").addEventListener("click", () => lib.showModal());
  $("#library-close").addEventListener("click", () => lib.close());
  $("#library-list").addEventListener("click", (e) => { const b = e.target.closest("button[data-key]"); if (b) startGuided(b.dataset.key); });
  $("#landing-guided").addEventListener("click", () => startGuided(META.guided[0].key));
  $("#landing-live").addEventListener("click", async () => { try { await startLive(); $("#dock-text").focus(); } catch (e) { toast(e.message); } });
  $("#guided-replay").addEventListener("click", () => lastGuided && startGuided(lastGuided));
  $("#guided-exit").addEventListener("click", () => startLive().catch((e) => toast(e.message)));
  $("#reset").addEventListener("click", () => startLive().catch((e) => toast(e.message)));
  $("#voice-out").addEventListener("click", (e) => {
    voiceOut = !voiceOut; e.currentTarget.setAttribute("aria-pressed", String(voiceOut));
    e.currentTarget.textContent = voiceOut ? "🔊 Voice" : "🔈 Voice";
    if (!voiceOut && "speechSynthesis" in window) speechSynthesis.cancel();
  });

  // menus
  const menu = (btn, box) => {
    $(btn).addEventListener("click", () => { const open = $(box).hidden; closeMenus(); $(box).hidden = !open; $(btn).setAttribute("aria-expanded", String(open)); });
  };
  const closeMenus = () => { ["#clips-menu", "#image-menu"].forEach((m) => ($(m).hidden = true)); };
  menu("#clips-btn", "#clips-menu"); menu("#image-btn", "#image-menu");
  document.addEventListener("click", (e) => { if (!e.target.closest(".menu-wrap")) closeMenus(); });
  $("#clips-menu").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-ref]"); if (!b) return;
    closeMenus(); new Audio(`/media/${b.dataset.ref}`).play().catch(() => {}); sendMedia("audio", b.dataset.ref);
  });
  $("#image-menu").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    closeMenus();
    if (b.dataset.upload) $("#image-file").click(); else sendMedia("frame", b.dataset.ref);
  });
  $("#image-file").addEventListener("change", (e) => {
    const f = e.target.files[0]; if (!f) return;
    uploadAndSend("frame", f, f.type === "image/png" ? "png" : "jpg"); e.target.value = "";
  });
  // drag & drop an image anywhere
  let dragDepth = 0;
  window.addEventListener("dragenter", (e) => { if ([...e.dataTransfer.items].some((i) => i.type.startsWith("image/"))) { dragDepth++; $("#dropzone").hidden = false; } });
  window.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $("#dropzone").hidden = true; });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => {
    e.preventDefault(); dragDepth = 0; $("#dropzone").hidden = true;
    const f = [...e.dataTransfer.files].find((x) => /image\/(png|jpeg)/.test(x.type));
    if (f) uploadAndSend("frame", f, f.type === "image/png" ? "png" : "jpg");
  });

  // push-to-talk: hold the button, or hold M. While held, 16 kHz PCM streams to the on-device recogniser for every
  // 250 ms of captured audio (paced by the audio callback, not a page timer, which browsers throttle in background tabs) and the words it is sure of reach the agent as the turn goes on (D17). Release -> the rest + end of turn.
  // No streaming (or nothing recognised) -> the file path: 16 kHz WAV -> upload -> user.audio -> on-device recognition.
  const mic = $("#mic");
  const status = (text) => { $("#mic-status").textContent = text; };
  let rec = null, busy = false, tick = null, autoStop = null, stream = null;
  const openStream = (r) => {
    if (!(S.caps || META?.capabilities)?.asr.stream) return null;
    const st = { id: null, failed: false, blocks: [], buffered: 0 };
    st.chain = api("/api/voice/start", {}).then((x) => { st.id = x.id; }).catch(() => { st.failed = true; });
    st.flush = () => {
      if (!st.blocks.length || st.failed) return st.chain;
      const pcm = pcm16(downsample(concat(st.blocks.splice(0)), r.rate, TARGET_RATE));
      st.chain = st.chain.then(() => st.id && !st.failed && api(`/api/voice/chunk?id=${st.id}`, pcm, true)).catch(() => { st.failed = true; });
      return st.chain;
    };
    st.push = (block) => {
      st.blocks.push(block);
      st.buffered += block.length;
      if (st.buffered >= r.rate / 4) { st.buffered = 0; st.flush(); }
    };
    return st;
  };
  const closeStream = async (st, cancel) => {
    await st.flush();
    if (st.failed || !st.id) return null;
    try { return await api(`/api/voice/end?id=${st.id}${cancel ? "&cancel=1" : ""}`, {}); } catch { return null; }
  };
  const level = (v) => ($("#mic-level").style.transform = `scale(${1 + v * 0.5})`);
  const micBlocked = () => unsupportedReason(window) ||
    ((S.caps || META?.capabilities)?.asr.real ? null : "speech recognition is not available on this machine (the prepared clips still work, with scripted transcripts)");
  const down = () => {
    if (rec || busy) return;
    if (S.info?.mode === "guided") { toast("A guided demo is running: its inputs come from the scenario file. Click “Go live” to talk.", true); return; }
    const blocked = micBlocked();
    if (blocked) { toast(`Microphone unavailable: ${blocked}.`); return; }
    rec = new Recorder(level, (block) => stream?.push(block));
    let started;
    try { started = rec.start(); } catch (e) { rec = null; toast(`Microphone unavailable: ${e.message}`); return; }  // inside the gesture
    stream = openStream(rec);
    mic.classList.add("recording");
    const t0 = performance.now();
    status("● recording… release to send");
    tick = setInterval(() => status(`● ${((performance.now() - t0) / 1000).toFixed(1)} s · release to send`), 100);
    autoStop = setTimeout(() => { toast(`Stopped at ${MAX_SECONDS} s: push-to-talk is for short requests.`, true); up(); }, MAX_SECONDS * 1000);
    started.catch(() => {});  // errors are reported by stop()
  };
  const up = async () => {
    if (!rec) return;
    const r = rec, st = stream; rec = null; stream = null;
    clearInterval(tick); clearTimeout(autoStop);
    mic.classList.remove("recording"); busy = true; mic.classList.add("busy"); status("");
    const res = await r.stop();
    const unusable = res.error || res.seconds < MIN_SECONDS || res.peak < SILENCE_PEAK;
    const streamed = st ? await closeStream(st, unusable) : null;
    busy = false; mic.classList.remove("busy");
    if (streamed?.streamed) {  // the words already reached the agent while you spoke; the turn is closed
      if (streamed.revised) toast("The recogniser revised a word after it was sent; the agent works from what was sent.", true);
      return;
    }
    if (res.error) {
      const n = res.error.name;
      toast(n === "NotAllowedError" || n === "SecurityError" ? "Microphone permission was denied. Allow it in the browser, or use the prepared clips (♪ Clips)."
        : n === "StartTimeout" || n === "Suspended" ? `The microphone did not start${n === "Suspended" ? " (the browser blocked audio capture)" : ""}. Click the page once and hold the button again, or use the prepared clips.`
        : n === "NotFoundError" ? "No microphone was found. Use the prepared clips (♪ Clips)."
        : `Microphone error: ${res.error.message || n}`);
      return;
    }
    if (res.seconds < MIN_SECONDS) { toast("Hold to talk: keep the button (or M) pressed while you speak.", true); return; }
    if (res.peak < SILENCE_PEAK) { toast("No sound was captured. Check the microphone / input device, or use the prepared clips.", true); return; }
    status("sending…");
    await uploadAndSend("audio", res.wav, "wav");
    status("");
  };
  const refreshMic = () => {
    const blocked = micBlocked();
    mic.disabled = Boolean(blocked);
    mic.title = blocked ? `Microphone unavailable: ${blocked}` : "Hold to talk (or hold M), release to send";
  };
  refreshMic();
  window.refreshMic = refreshMic;
  mic.addEventListener("pointerdown", (e) => { e.preventDefault(); down(); });
  window.addEventListener("pointerup", up);
  window.addEventListener("pointercancel", up);
  window.addEventListener("blur", up);
  window.addEventListener("keydown", (e) => {
    if (e.target.matches("input, textarea, select")) return;
    if (e.key === "m" && !e.repeat) down();
    if (e.key === "/") { e.preventDefault(); $("#dock-text").focus(); }
  });
  window.addEventListener("keyup", (e) => { if (e.key === "m") up(); });
  window.addEventListener("resize", () => (S.dirty = true));

  connect();
  const loop = () => { render(); requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
}

init();
