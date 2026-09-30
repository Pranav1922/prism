"""Scripted workers (Phase 1): deterministic stand-ins for the planner and perception.

They sit behind the same request/response shapes as the real backends (PHASE0_PREFLIGHT §8.5–8.6):
a request dict goes in, an Event comes back after a scripted latency. They are NOT models.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agent.model import Event, Kind


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s-]", " ", text.lower()).split())


@dataclass
class ScriptedPlanner:
    """Maps the closing turn's text to a proposal. Unknown text -> ProposalFailed."""

    script: dict[str, dict] = field(default_factory=dict)
    latency: float = 0.3
    min_similarity: float = 0.85  # word-set overlap needed to accept a noisy transcript as a known utterance
    records: list[dict] = field(default_factory=list)

    def match(self, text: str) -> tuple[str | None, float]:
        """Exact key, then case/punctuation-insensitive, then the most similar key (word-set Jaccard) above the
        threshold: speech recognition adds noise ("find flight flights from ..."), not new meaning."""
        if text in self.script:
            return text, 1.0
        norm = {_norm(k): k for k in self.script}
        if _norm(text) in norm:
            return norm[_norm(text)], 1.0
        words = set(_norm(text).split())
        best, score = None, 0.0
        for n, k in norm.items():
            other = set(n.split())
            sim = len(words & other) / len(words | other) if words | other else 0.0
            if sim > score:
                best, score = k, sim
        return (best, round(score, 3)) if score >= self.min_similarity else (None, round(score, 3))

    def respond(self, request: dict, now: float) -> tuple[float, Event]:
        base = {"req_id": request["req_id"], "based_on_seq": request["based_on_seq"]}
        key, similarity = self.match(request["view"]["turn_text"])
        proposal = self.script.get(key) if key is not None else None
        self.records.append({"backend": "scripted", "fixture": key, "similarity": similarity})
        if proposal is None:
            return now + self.latency, Event(Kind.PROPOSAL_FAILED, now + self.latency, {**base, "reason": "no_script"})
        return now + self.latency, Event(Kind.PROPOSAL, now + self.latency, {**base, **proposal})


@dataclass
class ScriptedPerception:
    """Maps a media ref to evidence claims ({key: [value, confidence]}) or a transcript."""

    frames: dict[str, dict] = field(default_factory=dict)
    transcripts: dict[str, dict] = field(default_factory=dict)
    latency: float = 1.5

    def respond(self, request: dict, now: float) -> tuple[float, Event]:
        t = now + self.latency
        ref = request.get("ref")
        if request["kind"] == "vision" and ref in self.frames:
            return t, Event(Kind.EVIDENCE, t, {"frame_eid": request["source_eid"], "claims": self.frames[ref]})
        if request["kind"] == "asr" and ref in self.transcripts:
            return t, Event(Kind.USER_TEXT, t, {"source": "asr", **self.transcripts[ref]})
        return t, Event(Kind.PERCEPTION_FAILED, t, {"req_id": request["req_id"]})
