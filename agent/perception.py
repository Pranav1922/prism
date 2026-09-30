"""Local perception worker (behind the kernel's `perceive` effect): real audio and image input, no model downloads.

  audio  -> on-device speech recognition (macOS Speech framework, .build/prism_asr) -> UserText{source: asr}
  image  -> tesseract OCR -> schema-light value extraction -> Evidence{claims: {slot: [value, confidence]}}

A request whose media ref is not a readable file, or whose tool is unavailable (no ASR helper, no tesseract), goes
to the scripted fallback (the fixtures used by the black-box suite), so evaluation behaviour is unchanged. Like the
planner, perception returns events only; it never touches state. Evidence is data: the kernel decides what to do
with it (goal association, last-writer-wins against the user, conflict -> clarification).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from agent.model import Event, Kind
from agent.planner import ScriptedPerception

ROOT = Path(__file__).resolve().parents[1]
WEEKDAYS = {name: day for day, names in {
    "Mon": ("mon", "monday"), "Tue": ("tue", "tues", "tuesday"), "Wed": ("wed", "wednesday"),
    "Thu": ("thu", "thur", "thurs", "thursday"), "Fri": ("fri", "friday"), "Sat": ("sat", "saturday"),
    "Sun": ("sun", "sunday")}.items() for name in names}


def extract_claims(words: list[tuple[str, float]], hints: list[str]) -> dict[str, list]:
    """Values the image shows, for the slots the active goal has (`hints`; all if unknown). words: (text, conf 0-1).
    Deliberately small: weekday -> date, 'FROM XXX' / 'TO XXX' IATA codes, a flight number -> flight_id."""
    want = set(hints) if hints else {"date", "origin", "destination", "flight_id"}
    toks = [(re.sub(r"[^\w-]", "", w), c) for w, c in words if w.strip()]
    claims: dict[str, list] = {}
    for i, (w, c) in enumerate(toks):
        low = w.lower()
        if "date" in want and low in WEEKDAYS:
            claims.setdefault("date", [WEEKDAYS[low], round(c, 2)])
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if nxt and re.fullmatch(r"[A-Z]{3}", nxt[0]):
            role = {"from": "origin", "to": "destination"}.get(low)
            if role in want:
                claims.setdefault(role, [nxt[0], round(min(c, nxt[1]), 2)])
        if "flight_id" in want and re.fullmatch(r"[0-9A-Z]{2}-\d{3,4}", w):
            claims.setdefault("flight_id", [w, round(c, 2)])
    return claims


@dataclass
class LocalPerception:
    fallback: ScriptedPerception
    latency: float | None = None  # None: measured wall time becomes virtual latency; else fixed seconds
    asr_bin: str = field(default_factory=lambda: os.environ.get("PRISM_ASR_BIN", str(ROOT / ".build" / "prism_asr")))
    records: list[dict] = field(default_factory=list)

    def _file(self, ref: str | None) -> Path | None:
        if not ref:
            return None
        p = Path(ref) if Path(ref).is_absolute() else ROOT / ref
        return p if p.is_file() else None

    def available(self) -> dict[str, bool]:
        return {"asr": Path(self.asr_bin).is_file() and os.access(self.asr_bin, os.X_OK),
                "ocr": shutil.which("tesseract") is not None}

    def respond(self, request: dict, now: float) -> tuple[float, Event]:
        path = self._file(request.get("ref"))
        kind = request["kind"]
        tool = "asr" if kind == "asr" else "ocr"
        if path is None or not self.available()[tool]:
            self.records.append({"req_id": request["req_id"], "kind": kind, "backend": "scripted_fallback"})
            return self.fallback.respond(request, now)
        started = time.perf_counter()
        try:
            event_payload = self._asr(path, request) if kind == "asr" else self._ocr(path, request)
        except (subprocess.SubprocessError, OSError, ValueError) as exc:
            event_payload = None
            error = f"{type(exc).__name__}: {exc}"[:200]
        wall = time.perf_counter() - started
        t = now + (wall if self.latency is None else self.latency)
        rec = {"req_id": request["req_id"], "kind": kind, "backend": tool, "wall_s": round(wall, 4)}
        if event_payload is None:
            self.records.append({**rec, "error": locals().get("error", "no result")})
            return t, Event(Kind.PERCEPTION_FAILED, t, {"req_id": request["req_id"]})
        self.records.append({**rec, "output": event_payload})
        if kind == "asr":
            return t, Event(Kind.USER_TEXT, t, {"text": event_payload["text"], "source": "asr",
                                                 "source_eid": request.get("source_eid")})
        return t, Event(Kind.EVIDENCE, t, {"frame_eid": request["source_eid"], "claims": event_payload["claims"]})

    def _asr(self, path: Path, request: dict) -> dict | None:
        out = subprocess.run([self.asr_bin, str(path)], capture_output=True, text=True, timeout=30)
        text = out.stdout.strip()
        return {"text": text} if out.returncode == 0 and text else None

    def _ocr(self, path: Path, request: dict) -> dict | None:
        out = subprocess.run(["tesseract", str(path), "stdout", "tsv"], capture_output=True, text=True, timeout=30)
        words = []
        for line in out.stdout.splitlines()[1:]:
            cols = line.split("\t")
            if len(cols) == 12 and cols[11].strip() and float(cols[10]) >= 0:
                words.append((cols[11], float(cols[10]) / 100))
        claims = extract_claims(words, list(request.get("hints") or []))
        return {"claims": claims, "text": " ".join(w for w, _ in words)[:300]} if claims else None

    def describe(self) -> dict:
        return {"perception": "local", **self.available(), "latency": "measured" if self.latency is None else self.latency}
