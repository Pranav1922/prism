"""Microphone path, end to end, minus the physical microphone:
browser encoder (frontend/static/recorder.js, run in Node) -> WAV -> server upload validation -> user.audio ->
on-device recognition (macOS) -> kernel (D16 turn close) -> plan -> tool call; and the failure paths.

Parts that need Node, macOS's speech helper or afconvert are skipped where those are absent; the kernel-level
failure test runs everywhere."""

import json
import shutil
import struct
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from agent.model import ActionKind, Event, Kind
from agent.planner import ScriptedPerception, ScriptedPlanner
from agent.scenario import Sim, eot
from frontend import server
from frontend.live import LiveSession
from tests.invariants import CheckedKernel

ROOT = Path(__file__).resolve().parents[1]
RECORDER = ROOT / "frontend" / "static" / "recorder.js"
ASR = ROOT / ".build" / "prism_asr"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node not installed")
needs_asr = pytest.mark.skipif(not (sys.platform == "darwin" and ASR.is_file() and shutil.which("afconvert")),
                               reason="macOS on-device ASR helper not available")


def run_node(tmp_path: Path, body: str) -> dict:
    """Import the shipped recorder.js as an ES module in Node and run `body`; it must print one JSON line."""
    mod = tmp_path / "recorder.mjs"
    mod.write_text(RECORDER.read_text())
    script = tmp_path / "t.mjs"
    script.write_text(f'import * as R from "{mod.as_uri()}";\nimport fs from "node:fs";\n' + textwrap.dedent(body))
    out = subprocess.run([NODE, str(script)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@needs_node
def test_browser_wav_encoder_writes_16k_mono_pcm(tmp_path):
    r = run_node(tmp_path, """
        const pcm = new Float32Array([0, 0.5, -0.5, 1.5, -1.5]);
        const buf = new Uint8Array(R.encodeWav(pcm, 16000));
        fs.writeFileSync(process.argv[1] ?? "/dev/null", buf);
        const v = new DataView(buf.buffer);
        const s = (o, n) => String.fromCharCode(...buf.slice(o, o + n));
        console.log(JSON.stringify({riff: s(0, 4), wave: s(8, 4), fmt: s(12, 4), data: s(36, 4), size: v.getUint32(4, true),
          format: v.getUint16(20, true), channels: v.getUint16(22, true), rate: v.getUint32(24, true),
          byteRate: v.getUint32(28, true), block: v.getUint16(32, true), bits: v.getUint16(34, true),
          dataLen: v.getUint32(40, true), samples: [0, 1, 2, 3, 4].map((i) => v.getInt16(44 + 2 * i, true)), total: buf.length}));
    """)
    assert (r["riff"], r["wave"], r["fmt"], r["data"]) == ("RIFF", "WAVE", "fmt ", "data")
    assert (r["format"], r["channels"], r["rate"], r["bits"], r["block"], r["byteRate"]) == (1, 1, 16000, 16, 2, 32000)
    assert r["dataLen"] == 10 and r["size"] == 36 + 10 and r["total"] == 54
    assert r["samples"] == [0, 16383, -16384, 32767, -32768]  # out-of-range input is clipped, never wrapped


@needs_node
def test_downsampling_and_the_early_release_guard(tmp_path):
    r = run_node(tmp_path, """
        const x = new Float32Array(48000).map((_, i) => (i % 3 === 0 ? 0.3 : 0));
        const y = R.downsample(x, 48000, 16000);
        let bad = null; try { R.downsample(x, undefined, 16000); } catch (e) { bad = e.name; }
        console.log(JSON.stringify({len: y.length, first: y[0], same: R.downsample(x, 16000, 16000) === x, bad,
          concat: Array.from(R.concat([new Float32Array([1, 2]), new Float32Array([3])]))}));
    """)
    assert r["len"] == 16000 and abs(r["first"] - 0.1) < 1e-6 and r["same"] is True and r["concat"] == [1, 2, 3]
    assert r["bad"] == "RangeError"  # an unknown input rate (stop() before start()) is an error, not NaN audio


@needs_node
def test_microphone_unsupported_reasons_are_explicit(tmp_path):
    r = run_node(tmp_path, """
        const ok = {isSecureContext: true, navigator: {mediaDevices: {getUserMedia() {}}}, AudioContext: function () {}};
        console.log(JSON.stringify({
          insecure: R.unsupportedReason({...ok, isSecureContext: false}),
          nomic: R.unsupportedReason({...ok, navigator: {}}),
          noaudio: R.unsupportedReason({...ok, AudioContext: undefined}),
          ok: R.unsupportedReason(ok), limits: [R.MIN_SECONDS, R.MAX_SECONDS, R.TARGET_RATE]}));
    """)
    assert "secure context" in r["insecure"] and "microphone" in r["nomic"] and "Web Audio" in r["noaudio"]
    assert r["ok"] is None and r["limits"] == [0.4, 15, 16000]


def browser_encoded(tmp_path: Path, clip: str) -> Path:
    """The demo clip as the browser would send it: decoded to 48 kHz float (a typical AudioContext rate), then
    downsampled and encoded by the shipped recorder.js."""
    f32 = tmp_path / "in.wav"
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEF32@48000", "-c", "1", str(ROOT / clip), str(f32)], check=True)
    out = tmp_path / "browser.wav"
    run_node(tmp_path, f"""
        const b = fs.readFileSync("{f32}");
        let p = 12; while (b.toString("latin1", p, p + 4) !== "data") p += 8 + b.readUInt32LE(p + 4);
        const n = b.readUInt32LE(p + 4) / 4, pcm = new Float32Array(n);
        for (let i = 0; i < n; i++) pcm[i] = b.readFloatLE(p + 8 + 4 * i);
        fs.writeFileSync("{out}", new Uint8Array(R.encodeWav(R.downsample(pcm, 48000, R.TARGET_RATE), R.TARGET_RATE)));
        console.log(JSON.stringify({{n}}));
    """)
    return out


@needs_node
@needs_asr
def test_browser_encoded_speech_is_recognised_on_device(tmp_path):
    wav = browser_encoded(tmp_path, "demo/media/wait_mumbai.aiff")
    assert server.check_upload("wav", wav.read_bytes()) is None
    out = subprocess.run([str(ASR), str(wav)], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0 and out.stdout.strip().lower().replace(",", "") == "wait mumbai instead"


def test_upload_content_is_checked_not_just_the_extension():
    def wav(seconds: float, rate: int = 16000, bits: int = 16, fmt: int = 1) -> bytes:
        n = int(seconds * rate)
        data = b"\x00\x00" * n
        return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE" + b"fmt " +
                struct.pack("<IHHIIHH", 16, fmt, 1, rate, rate * 2, 2, bits) + b"data" + struct.pack("<I", len(data)) + data)
    assert server.check_upload("wav", wav(1.0)) is None
    assert "too short" in server.check_upload("wav", wav(0.1))
    assert "too long" in server.check_upload("wav", wav(61))
    assert "PCM" in server.check_upload("wav", wav(1.0, fmt=3))  # float WAV: not what the recorder sends
    assert "PCM" in server.check_upload("wav", b"RIFF1234WAVEjunk" + b"x" * 40)
    assert "PCM" in server.check_upload("wav", (ROOT / "demo/media/ticket.png").read_bytes())  # a PNG named .wav
    assert server.check_upload("png", (ROOT / "demo/media/ticket.png").read_bytes()) is None
    assert server.check_upload("jpg", b"\xff\xd8\xff\xe0" + b"x" * 100) is None
    assert server.check_upload("png", b"GIF89a") is not None and server.check_upload("exe", b"MZ") is not None


def live(events: list, agent_audio_ref: str) -> LiveSession:
    s = LiveSession(events.append, server.agent_cmd(), server.MANIFEST, server.PRESETS["fast"]["world"])
    s.start()
    s.inject("user.audio", {"ref": agent_audio_ref})
    s.inject("user.turn_end")
    return s


def journal(events: list, typ: str) -> list[dict]:
    return [e["rec"] for e in events if e["type"] == "journal" and e["rec"]["type"] == typ]


def wait_for(events: list, pred, seconds: float = 20.0) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


@needs_node
@needs_asr
def test_live_session_turns_a_browser_recording_into_a_tool_call(tmp_path):
    wav = browser_encoded(tmp_path, "demo/media/find_delhi.aiff")
    server.UPLOADS.mkdir(parents=True, exist_ok=True)
    target = server.UPLOADS / f"test-{time.time_ns()}.wav"
    shutil.copy(wav, target)
    events: list = []
    s = live(events, f"demo/uploads/{target.name}")
    try:
        assert wait_for(events, lambda: any(e["type"] == "wire" and (e["msg"] or {}).get("type") == "tool.call" for e in events))
    finally:
        s.stop()
        s.join(10)
        target.unlink()
    perc = journal(events, "perception_io")
    assert perc and perc[0]["backend"] == "asr" and perc[0]["kind"] == "UserText"  # the real recogniser, not a fallback
    heard = [r["event"] for r in journal(events, "in") if r["event"]["kind"] == "UserText"]
    assert heard and heard[0]["payload"]["source"] == "asr" and "bangalore" in heard[0]["payload"]["text"].lower()
    rules = [x for r in journal(events, "step") for x in r["rules"]]
    # whichever arrives last (transcript or the user's end of turn, D16) closes the turn: never the 1 s silence timer
    assert any(x["rule"] == "TURN.close" and x["inferred"] is False for x in rules)
    assert not any(x["rule"] == "TURN.close" and x["inferred"] for x in rules)
    call = next(e["msg"]["data"] for e in events if e["type"] == "wire" and (e["msg"] or {}).get("type") == "tool.call")
    assert call["tool"] == "search_flights" and call["args"]["destination"] == "DEL"


@needs_asr
def test_live_session_says_it_did_not_catch_silence(tmp_path):
    server.UPLOADS.mkdir(parents=True, exist_ok=True)
    target = server.UPLOADS / f"test-silence-{time.time_ns()}.wav"
    n = 16000
    target.write_bytes(b"RIFF" + struct.pack("<I", 36 + 2 * n) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
                       + b"data" + struct.pack("<I", 2 * n) + b"\x00\x00" * n)
    events: list = []
    s = live(events, f"demo/uploads/{target.name}")
    try:
        said = lambda: [e["msg"]["data"]["text"] for e in events if e["type"] == "wire" and (e["msg"] or {}).get("type") == "speech"]  # noqa: E731
        assert wait_for(events, lambda: bool(said()))
    finally:
        s.stop()
        s.join(10)
        target.unlink()
    assert said() == ["Sorry, I didn't catch that. Could you say it again?"]
    assert not any(e["type"] == "wire" and (e["msg"] or {}).get("type") == "tool.call" for e in events)


@pytest.mark.parametrize("recognition_s", [0.4, 0.05])  # failure after, or before, the user's end of turn
def test_unrecognised_speech_is_reported_as_not_heard_not_as_a_planning_failure(recognition_s):
    sim = Sim(json.loads((ROOT / "evaluation/scenarios/manifests/flights.json").read_text()), {}, ScriptedPlanner({}),
              ScriptedPerception(latency=recognition_s), kernel_factory=CheckedKernel)
    sim.run([(0.1, Event(Kind.MEDIA, 0.0, {"kind": "audio", "ref": "unknown-clip"}, "a1")), (0.2, eot())])
    said = [a.payload["text"] for a in sim.of(ActionKind.SPEAK)]
    assert said == ["Sorry, I didn't catch that. Could you say it again?"] and not sim.calls()


def test_a_transcript_before_the_end_of_turn_still_closes_on_the_end_of_turn():
    manifest = json.loads((ROOT / "evaluation/scenarios/manifests/flights.json").read_text())
    text = "find flights from Bangalore to Delhi on Friday"
    plan = {"intent": "search_flights", "slot_writes": {"origin": "BLR", "destination": "DEL", "date": "Fri"},
            "graph": [{"node_id": "n1", "tool": "search_flights", "args": {p: {"$slot": p} for p in ("origin", "destination", "date")}}]}
    sim = Sim(manifest, {}, ScriptedPlanner({text: plan}, 0.25), ScriptedPerception(transcripts={"clip": {"text": text}}, latency=0.05),
              kernel_factory=CheckedKernel)
    sim.run([(0.1, Event(Kind.MEDIA, 0.0, {"kind": "audio", "ref": "clip"}, "a1")), (0.3, eot())])
    closes = [x for rec in sim.journal.of_type("step") for x in rec["rules"] if x["rule"] == "TURN.close"]
    assert closes and closes[0]["inferred"] is False and [c.tool for c in sim.calls().values()] == ["search_flights"]


@needs_node
def test_a_microphone_that_never_starts_or_stays_blocked_fails_cleanly_instead_of_hanging(tmp_path):
    r = run_node(tmp_path, """
        let released = 0;
        const node = {connect() {}, disconnect() {}, onaudioprocess: null};
        const makeCtx = (state) => function () { return {sampleRate: 48000, state, resume: () => new Promise(() => {}),
          close: async () => {}, createMediaStreamSource: () => ({connect() {}}), createScriptProcessor: () => node, destination: {}}; };
        const track = {stop() { released++; }};
        Object.defineProperty(globalThis, "navigator", {value: {mediaDevices: {}}, configurable: true});
        // 1) getUserMedia never settles (e.g. a permission prompt left open): stop() must give up, not hang
        globalThis.AudioContext = makeCtx("suspended");
        navigator.mediaDevices.getUserMedia = () => new Promise(() => {});
        let t0 = Date.now(); let a = new R.Recorder(); a.start(); const hung = await a.stop(); const waited = Date.now() - t0;
        // 2) the stream arrives but the audio context stays suspended (no gesture): report it, never send silence
        navigator.mediaDevices.getUserMedia = async () => ({getTracks: () => [track]});
        let b = new R.Recorder(); b.start(); await new Promise((r) => setTimeout(r, 20)); const blocked = await b.stop();
        console.log(JSON.stringify({hung: hung.error?.name, waited, blocked: blocked.error?.name, released, wav: !!blocked.wav}));
    """)
    assert r["hung"] == "StartTimeout" and 2900 <= r["waited"] < 6000
    assert r["blocked"] == "Suspended" and r["released"] == 1 and r["wav"] is False  # the microphone is released


# ---------------------------------------------------------------- streaming voice (D17)


def test_stable_words_never_send_a_word_that_may_still_change():
    from frontend.voice_stream import StableWords
    w = StableWords()
    assert w.update("Find") is None  # heard once: may still change
    assert w.update("Find a") == "Find"  # agreed by two hypotheses, and not the last word
    assert w.update("Find a flight from Ben") == "a"  # "a" is now agreed; "flight from Ben" was heard only once
    assert w.update("Find a flight from Bangalore") == "flight from"  # "Ben" -> "Bangalore": the half word never went out
    assert w.settle() == "Bangalore"  # the speaker paused: the unchanged hypothesis is sent in full
    assert w.update("Fine a flight") is None  # the recogniser revises a sent word: nothing new is sent meanwhile
    assert w.finish("Find a flight from Bangalore to Delhi") == ("to Delhi", False)
    v = StableWords()
    v.update("Find a"), v.update("Find a flight")
    assert v.finish("Fine a flight to Goa") == ("flight to Goa", True)  # reported as revised, never hidden


@needs_node
def test_streamed_pcm_is_16_bit_little_endian_and_clipped(tmp_path):
    r = run_node(tmp_path, """
        const b = new DataView(R.pcm16(new Float32Array([0, 0.5, -0.5, 1.5, -1.5])));
        console.log(JSON.stringify({n: b.byteLength, s: [0, 1, 2, 3, 4].map((i) => b.getInt16(2 * i, true))}));
    """)
    assert r == {"n": 10, "s": [0, 16383, -16384, 32767, -32768]}


def test_partial_text_never_borrows_the_rest_of_a_known_example():
    from agent.reasoner.rules import DeterministicPlanner, RulePlanner
    fixtures = json.loads((ROOT / "agent" / "fixtures" / "scripted.json").read_text())
    planner = DeterministicPlanner(ScriptedPlanner(fixtures["planner"], 0.25), RulePlanner(0.25))
    view = {"turn_text": "Find a flight from Bangalore to Delhi on", "turn_classes": ["REQUEST"], "turn_attributed": [],
            "utterances": [], "tools": [{"name": t["name"], "description": t.get("description", ""),
                                          "effect": t.get("effect", "read_only"), "parameters": t["parameters"]}
                                         for t in server.MANIFEST],
            "goal": None, "slots": {}, "results": [], "evidence": [], "pending": [], "suspended_goals": []}
    whole = planner.respond({"req_id": "r1", "based_on_seq": 1, "view": view}, 0.0)[1].payload
    assert whole["slot_writes"].get("date") == "Fri"  # a finished turn may match the known example (noise tolerance)
    part = planner.respond({"req_id": "r2", "based_on_seq": 1, "view": {**view, "partial": True}}, 0.0)[1].payload
    assert "date" not in part["slot_writes"]  # half a sentence: only what it says


def pcm_of(tmp_path: Path, clip: str) -> bytes:
    import wave
    out = tmp_path / "clip.wav"
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(ROOT / clip), str(out)], check=True)
    with wave.open(str(out)) as w:
        return w.readframes(w.getnframes())


@needs_asr
def test_streamed_voice_starts_the_search_before_the_button_is_released(tmp_path):
    from frontend.voice_stream import VoiceStream
    events: list = []
    s = LiveSession(events.append, server.agent_cmd(), server.MANIFEST, server.PRESETS["realistic"]["world"])
    s.start()
    try:
        v = VoiceStream(s.inject, str(server.ASR_BIN))
        audio = pcm_of(tmp_path, "demo/media/find_delhi.aiff") + b"\0" * 32000  # the speech, then 1 s held in silence
        for i in range(0, len(audio), 8000):  # 250 ms blocks in real time, as the browser sends them
            v.feed(audio[i:i + 8000])
            time.sleep(0.25)
        before_release = [e["msg"] for e in events if e["type"] == "wire" and (e["msg"] or {}).get("type") == "tool.call"]
        out = v.end()
    finally:
        s.stop()
        s.join(10)
    assert out["streamed"] and "bangalore" in out["text"].lower() and len(out["chunks"]) >= 2
    assert any(not c["after_release"] for c in out["chunks"])  # words reached the agent while the user was speaking
    assert before_release and before_release[0]["data"]["args"] == {"origin": "BLR", "destination": "DEL", "date": "Fri"}
    heard = [r["event"]["payload"] for r in journal(events, "in") if r["event"]["kind"] == "UserText"]
    assert heard and all(h.get("source") == "asr_stream" for h in heard)
