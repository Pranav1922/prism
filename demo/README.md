# Theme 05 demo: interruptible real-time multimodal agent

Two scenarios, each run through the **same black-box harness and evaluator** as the test suite. The agent is a separate process speaking PRISM-LOCAL/0 (this project's local protocol, *not* Samsung's). Scores are INTERNAL PRISM-STYLE metrics, not Samsung scores.

| Demo | Input | What it shows |
|---|---|---|
| `interruption` ([scenario](../evaluation/scenarios/demo/demo_audio_interruption.json)) | two spoken utterances ([`find_delhi.aiff`](media/find_delhi.aiff), [`wait_mumbai.aiff`](media/wait_mumbai.aiff)) | real on-device speech recognition → immediate acknowledgement → slow Delhi search → spoken correction "Wait, Mumbai instead." → the Delhi search is **cancelled in the same step the transcript arrives** → Mumbai search → the Delhi result arrives **late and is rejected** → the final answer is grounded on the Mumbai result only |
| `ticket` ([scenario](../evaluation/scenarios/demo/demo_ticket_image.json)) | spoken request + boarding-pass image ([`ticket.png`](media/ticket.png)) | real OCR reads SATURDAY / BLR / DEL → grounded evidence → attached to the right goal (it arrives *before* the goal exists and is applied when the goal is created) → search for Saturday → answer grounded on that result; the planner never invents the date |

## Setup (once)

```sh
uv venv --python 3.12 .venv && uv pip install -e ".[dev]"   # Python deps
./scripts/build_asr.sh          # macOS: builds .build/prism_asr (on-device speech recognition; asks for permission once)
brew install tesseract          # OCR (already installed on the demo machine)
```

## Run

```sh
.venv/bin/python demo/run_demo.py                     # both demos: timeline + evaluator verdict
.venv/bin/python demo/run_demo.py interruption --speak   # replay aloud: plays the user audio, speaks the agent (macOS `say`)
.venv/bin/python demo/run_demo.py --planner scripted --perception scripted   # fully deterministic fallback (any OS)
./demo/make_media.sh                                  # regenerate the audio/image (macOS `say` + AppKit)
```

Output: a timeline on stdout; traces, agent journals and results in `demo/output/`. A reference run is in [`SAMPLE_OUTPUT.txt`](SAMPLE_OUTPUT.txt).

## What is real, simulated or fallback in the demo

| Part | Status |
|---|---|
| speech recognition | **real**: Apple Speech framework, on-device (`requiresOnDeviceRecognition`), on the demo audio files. Fallback: scripted transcripts where the helper is unavailable (Linux, Docker) |
| image understanding | **real**: tesseract OCR + schema-light value extraction (weekday, FROM/TO airport codes, flight numbers). Fallback: scripted claims |
| user audio | synthesised with macOS `say` (real audio waveforms, a real recogniser; not a live microphone) |
| speech output | macOS `say` in `--speak` mode (no custom TTS) |
| planner | `auto`: the model named by `PRISM_PLANNER` if its server is reachable, else the **deterministic scripted planner** (used for the reference run: no local model is reliable and fast enough on this machine, see docs/PHASE5_MODEL_EVALUATION.md) |
| tools | the evaluator's mock tool world (scripted latency; honours cancel or not); no real airline API |
| clock | virtual time (lockstep); media latencies are the measured wall-clock recognition times |

## Expected behaviour (checked by the evaluator)

- `interruption`: exactly one Delhi search and one Mumbai search; no Delhi search after the correction; the FINAL snapshot shows destination BOM; the FINAL is not grounded on the Delhi call; both turns get a response.
- `ticket`: exactly one search, with date Sat; FINAL snapshot date Sat, origin BLR, destination DEL; the turn gets a response.

The interruption → cancel latency is **the speech recognition time** (the cancel is emitted in the same kernel step as the transcript; about 0.15-0.9 s for these clips). It is not a streaming recogniser, so interruption is detected at the end of the correction utterance. See docs/SUBMISSION_READINESS.md §9.
