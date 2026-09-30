# PRISM Theme 05 console: live view of the real agent

A local web frontend for judges and presenters. It shows, in real time, what the interruptible agent is doing:
- what you asked, and what it heard and saw;
- what work runs concurrently;
- what your correction cancelled, and which late results it refused to use;
- why the final answer can be trusted.

It is a view over the **real system**. Nothing in the browser is simulated or decided client-side.

```sh
.venv/bin/python -m frontend.server --open        # http://127.0.0.1:8765
```

It uses the standard library only: no Node, no build step, no CDN, so it works offline. It listens on 127.0.0.1 only.

## How it connects to the system

```
browser ──HTTP/SSE──► frontend/server.py ──► frontend/live.py (LiveSession)
                                                │  the evaluator's co-simulation loop, paced by the wall clock
                                                ├─► agent subprocess: python -m agent.adapter.stdio  (PRISM-LOCAL/0, lockstep)
                                                │      └─ writes its own journal to PRISM_JOURNAL_STREAM as it steps
                                                └─► evaluation/world.py (simulated tools)
```

- **Wire.** The agent is started exactly as in the black-box evaluation: a separate process speaking PRISM-LOCAL/0 (this project's local protocol, not Samsung's). The server delivers inputs and tool results and ticks the clock when the agent asks for it. Virtual time = seconds since the session started.
- **Events.** The browser receives three streams over Server-Sent Events:
  1. every wire message;
  2. the tool world's own ledger (calls received, cancels ignored or honoured, results, side effects);
  3. the agent's journal: each kernel step's input, the rules that fired, the exact state changes, and the actions.
- **State.** The browser keeps a mirror of the kernel's tables by applying the journaled changes in order. This is observation only: the journal stream is written by the agent and never read back by it. There is no second state machine. The frontend does not change how the agent behaves.
- **Guided demos** replay scenario files from `evaluation/scenarios/` in real time. At the end, the **unchanged black-box evaluator** scores the run's wire trace. `tests/test_frontend.py` checks that every guided demo passes when run this way.

## What you see

| Area | Shows | Source |
|---|---|---|
| **Now** (top) | the single most important thing happening: listening, working (with elapsed time and parallel calls), change of plan, waiting for you, answer | derived from the mirrored state |
| **Key moments** | interruptions, stale results, safety decisions (injection dropped, confirmation required, no second booking), evidence applied, grounded answers, the evaluator verdict | kernel rules in the journal |
| **Timeline** | lanes for You, Perception (speech/image), Understanding (fast-path class, planner spans), Tools (one bar per call), and Agent (what it said), all on one clock | journal + wire |
| **Current task** | the agent's current understanding: each value and where it came from (heard / understood / from image), whether it is confirmed, what it replaced, open questions, paused tasks | slot registers, goals, pending |
| **Why this answer** | the calls the answer is grounded on; the calls it refused to use and why; side effects executed in the tool world; the evaluator's category scores for guided demos | FINAL action + calls + tool-world ledger + evaluator |
| **System view** | *Decisions*: every kernel step with its input, rules and actions. *Kernel state*: calls (relevance × outcome), slots (last writer wins), operation ledger, planner requests. *Protocol*: raw PRISM-LOCAL/0 messages | journal + wire |

**Timeline colours.**

| Colour | Meaning |
|---|---|
| blue | running |
| green ✓ | used in the answer |
| grey | finished but not used |
| amber hatched | cancelled or superseded; a dashed tail means the tool ignored the cancel and kept running |
| red marker | a late result, recorded and never used |
| amber marker | a side effect that completed despite the cancel (recorded as done, never repeated) |
| teal | perception |
| violet | planning |
| ✂ dashed line | the moment your correction arrived |

Every state also has a text label.

## Interactions

| Input | How | Reaches the agent as |
|---|---|---|
| typed request or correction | the text box, or a suggested-request chip | `user.text` + `user.turn_end` |
| voice | **hold** the mic button, or hold **M** | 16 kHz mono WAV → `user.audio` + `user.turn_end` → on-device speech recognition |
| prepared voice clips | ♪ Clips (plays the clip in the room and sends the same audio) | `user.audio` |
| image | ▣ Image: the boarding-pass sample, an upload, or drag and drop a PNG/JPEG anywhere | `user.frame` → tesseract OCR |
| speak replies aloud | 🔈 Voice (browser speech synthesis) | none; output only |
| tool behaviour | *Realistic* (search 5 s; cancels ignored, so stale results arrive) or *Fast* (1 s) | the simulated tool world |
| reset / replay | **Reset** starts a fresh live session; **↻ Replay** re-runs the current guided demo; **Go live** leaves a demo | a new agent process |

Keyboard: `/` focuses the text box; hold `M` to talk.

## Recommended demo flow (about 5 minutes)

1. **Landing → "Watch: change of mind, mid-search"** (guided, real voice). Point out, in order:
   - the Delhi search running (blue);
   - the spoken "Wait, Mumbai instead" cutting across all lanes;
   - the Delhi bar turning hatched **in the same step**;
   - the Mumbai search;
   - the Delhi result arriving later and landing on the red "stale · ignored" marker;
   - the answer grounded on Mumbai only;
   - the evaluator PASS in "Why this answer".
2. **Guided demos → "A boarding pass fills in the date".** The OCR evidence arrives before the task exists and is applied when the task is created. The task card shows "from image".
3. **Guided demos → "Booking race".** The tool ignores the cancel and the booking completes. The agent records it, never books twice, and asks instead of claiming the two-passenger booking.
4. **Guided demos → "Prompt injection in a tool result"** (2× playback). The injected booking is dropped, and nothing enters the task.
5. **Go live.** Click "Find flights from Bangalore to Delhi on Friday". While the bar is blue, click "Actually, to Mumbai", or hold the mic and say it. Switch to **System** to show the decision feed and the kernel tables.

## Real vs simulated vs fallback

| Part | Status |
|---|---|
| agent kernel, fast understanding, safety rules, protocol, journal | **real**: the same code the tests and evaluator run |
| speech recognition | **real**: Apple on-device recognition (macOS, after `./scripts/build_asr.sh`). Fallback: scripted transcripts for the demo clips (the Speech chip says which) |
| image understanding | **real**: tesseract OCR, extracting weekday, FROM/TO airport codes and flight numbers. Other images yield "nothing readable" |
| planner | **deterministic** by default: it matches the request against known examples, tolerating recognition noise. Free-form requests outside them are reported honestly ("the deterministic planner doesn't know that request"). With `PRISM_PLANNER=ollama:qwen2.5:7b` and a running Ollama, a model plans, with a deterministic fallback per request |
| tools (flights, booking, weather) | **simulated**: the evaluator's mock tool world with scripted latencies |
| clock | **real time** in live mode. Guided demos can play at 2×, which changes virtual speed only, not event order or scores |
| evaluator verdict | **real**: the unchanged black-box evaluator on this run's trace; an INTERNAL metric, not a Samsung score |

## Fallback and error behaviour

- **No ASR helper** (not macOS, or not built): the Speech chip shows *fallback*. The prepared clips use scripted transcripts, and a recorded voice clip is reported as not understood.
- **No tesseract:** the Vision chip shows *fallback*. The sample image uses scripted claims.
- **Microphone denied:** a notice points to the prepared clips.
- **Agent crash:** the header turns red, and the Now panel shows the agent's last error line.
- **Server connection lost:** the browser reconnects automatically. On reconnect, it receives the whole current session again.
- **Refused input:** bad input (unknown media, path traversal, unsupported upload, live input during a guided demo) is refused with a message.

## Known limitations

- **One session at a time** (single presenter). Starting a new one replaces the current one.
- **Planning is deterministic** on this machine (see `docs/PHASE5_MODEL_EVALUATION.md`), so free-form requests outside the known examples do not plan. Fast understanding still reacts to them: corrections still cancel work at once.
- **Voice is push-to-talk.** Recognition runs when you release (it is not streaming). A spoken interruption therefore lands after recognition (about 0.2–0.9 s), not mid-utterance.
- **Model planner blocks new input.** With a model planner, the lockstep adapter processes the next input only after the model answers.
- **Stored files.** Uploaded audio and images are stored under `demo/uploads/` (git-ignored).
- **Layout.** It is designed for a laptop or projector (≥ 1280 px). Narrower screens stack the panels.

## Tests

`tests/test_frontend.py` checks four things:
- every guided demo, run through the live driver, passes the unchanged evaluator;
- the kernel's journal is streamed;
- live input reaches the agent and comes back over SSE;
- bad input is refused.
