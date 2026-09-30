"""Streaming voice input for the console (D17): while the mic button is held, the browser sends 16 kHz PCM every
~250 ms; the on-device recogniser (`prism_asr --stream`, Apple Speech with partial results) turns it into growing
hypotheses, and the words two consecutive hypotheses agree on are sent to the agent as `user.text` chunks of the
still-open turn. On release, the rest of the final transcript and `user.turn_end` follow.

Honest limits: a hypothesis can still change; only words that stayed the same across two hypotheses (never the last,
possibly half-heard word, unless the hypothesis has not changed for `settle_s`: the speaker paused) are sent, and a sent
word cannot be taken back. If the final transcript revised a sent
word, that is reported (`revised`), not hidden. If nothing was recognised, the caller falls back to the file path
(upload the WAV -> `user.audio` -> the agent's own recogniser), which reports "not heard" as before."""

from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from typing import Any

MAX_STREAM_BYTES = 16000 * 2 * 20  # 20 s of 16 kHz 16-bit audio (push-to-talk stops at 15 s)


def _norm(word: str) -> str:
    return re.sub(r"[^\w]", "", word.lower())


class StableWords:
    """Stable prefix of a growing hypothesis: words two consecutive hypotheses agree on, never the last one."""

    def __init__(self) -> None:
        self.prev: list[str] = []
        self.sent: list[str] = []

    def update(self, text: str) -> str | None:
        cur = text.split()
        k = 0
        while k < min(len(cur), len(self.prev)) and _norm(cur[k]) == _norm(self.prev[k]):
            k += 1
        self.prev = cur
        stable = min(k, len(cur) - 1)
        if stable <= len(self.sent) or [_norm(w) for w in cur[:len(self.sent)]] != [_norm(w) for w in self.sent]:
            return None  # nothing new, or the recogniser is revising words already sent (settled at the end)
        new = cur[len(self.sent):stable]
        self.sent += new
        return " ".join(new)

    def settle(self) -> str | None:
        """The speaker paused: the unchanged hypothesis, last word included, is as good as it will get before release."""
        if [_norm(w) for w in self.prev[:len(self.sent)]] != [_norm(w) for w in self.sent]:
            return None
        new = self.prev[len(self.sent):]
        self.sent += new
        return " ".join(new) or None

    def finish(self, final: str) -> tuple[str | None, bool]:
        """(the words of the final transcript not sent yet, whether it revised a sent word)."""
        cur = final.split()
        n = len(self.sent)
        revised = [_norm(w) for w in cur[:n]] != [_norm(w) for w in self.sent]
        rest = cur[n:]
        self.sent += rest
        return (" ".join(rest) or None), revised


class VoiceStream:
    def __init__(self, inject: Any, asr_bin: str, min_gap_s: float = 0.4, settle_s: float = 0.6):
        self.inject = inject  # LiveSession.inject
        self.words = StableWords()
        self.final: str | None = None
        self.chunks: list[dict] = []  # what was sent while the user was still speaking, with wall-clock offsets
        self.bytes = 0
        self.min_gap_s, self.settle_s = min_gap_s, settle_s
        self._last_hyp = time.perf_counter()
        self._done = threading.Event()
        self.t0 = time.perf_counter()
        self._last_sent = 0.0
        self._held = ""  # stable words waiting for the next send (chunks of a few words, not one per word)
        self.lock = threading.Lock()
        self.proc = subprocess.Popen([asr_bin, "--stream"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        threading.Thread(target=self._settle, daemon=True).start()

    def feed(self, pcm: bytes) -> None:
        if len(pcm) % 2 or self.bytes + len(pcm) > MAX_STREAM_BYTES:
            raise ValueError("bad or too much audio")
        self.bytes += len(pcm)
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write(pcm)
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass  # the recogniser stopped (e.g. no speech); end() reports what it heard

    def _send(self, text: str, final: bool) -> None:
        self.inject("user.text", {"text": text, "source": "asr_stream"})
        self.chunks.append({"text": text, "at_s": round(time.perf_counter() - self.t0, 3), "after_release": final})
        self._last_sent = time.perf_counter()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            with self.lock:
                if msg.get("final"):
                    self.final = str(msg.get("text", ""))
                    continue
                self._last_hyp = time.perf_counter()
                new = self.words.update(str(msg.get("text", "")))
                if new:
                    self._held = f"{self._held} {new}".strip()
                if self._held and time.perf_counter() - self._last_sent >= self.min_gap_s:
                    self._send(self._held, False)
                    self._held = ""

    def _settle(self) -> None:
        while not self._done.wait(0.1):
            with self.lock:
                if time.perf_counter() - self._last_hyp < self.settle_s:
                    continue
                new = self.words.settle()
                if new:
                    self._held = f"{self._held} {new}".strip()
                if self._held:
                    self._send(self._held, False)
                    self._held = ""

    def end(self, cancel: bool = False, timeout_s: float = 5.0) -> dict:
        self._done.set()
        try:
            assert self.proc.stdin is not None
            self.proc.stdin.close()
        except OSError:
            pass
        if cancel:
            self.proc.kill()
        self.reader.join(timeout_s)
        if self.proc.poll() is None:
            self.proc.kill()
        with self.lock:
            final = self.final if self.final is not None else " ".join(self.words.prev)
            rest, revised = self.words.finish(final) if not cancel else (None, False)
            tail = " ".join(x for x in (self._held, rest) if x)
            if tail:
                self._send(tail, True)
            streamed = bool(self.chunks)
            if streamed:
                self.inject("user.turn_end")
        return {"streamed": streamed, "text": final, "chunks": self.chunks, "revised": revised,
                "audio_s": round(self.bytes / 32000, 2)}
