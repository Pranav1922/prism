"""Model backends: one method, `generate(messages, schema, timeout_s) -> Generation`. Replaceable by configuration;
the kernel never imports this module. Standard library HTTP only (no SDK dependency)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


class BackendError(RuntimeError):
    pass


@dataclass(frozen=True)
class Generation:
    text: str
    wall_s: float
    prompt_tokens: int | None = None
    output_tokens: int | None = None


class Backend(Protocol):
    def generate(self, messages: list[dict], schema: dict, timeout_s: float) -> Generation: ...

    def describe(self) -> dict: ...


def _post(url: str, body: dict, timeout_s: float, headers: dict | None = None) -> dict:
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 (configured local/remote endpoint)
            return json.loads(resp.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise BackendError(f"{type(exc).__name__}: {exc}") from exc


@dataclass
class OllamaBackend:
    """A local model served by Ollama, with grammar-constrained JSON output (`format` = the output schema)."""

    model: str
    host: str = "http://127.0.0.1:11434"
    options: dict = field(default_factory=lambda: {"temperature": 0, "seed": 7, "num_ctx": 8192, "num_predict": 800})
    keep_alive: str = "30m"

    def generate(self, messages: list[dict], schema: dict, timeout_s: float) -> Generation:
        t0 = time.perf_counter()
        out = _post(f"{self.host}/api/chat", {"model": self.model, "messages": messages, "stream": False,
                                               "format": schema, "options": self.options,
                                               "keep_alive": self.keep_alive}, timeout_s)
        return Generation(str(out.get("message", {}).get("content", "")), time.perf_counter() - t0,
                          out.get("prompt_eval_count"), out.get("eval_count"))

    def warm(self, timeout_s: float = 120.0) -> float:
        """Load the model (startup latency), returning wall seconds."""
        t0 = time.perf_counter()
        _post(f"{self.host}/api/generate", {"model": self.model, "prompt": "", "keep_alive": self.keep_alive}, timeout_s)
        return time.perf_counter() - t0

    def describe(self) -> dict:
        return {"backend": "ollama", "model": self.model, "options": self.options}


@dataclass
class OpenAICompatibleBackend:
    """Any hosted /chat/completions endpoint with JSON-schema response format. Used only when configured:
    PRISM_OPENAI_BASE_URL and PRISM_OPENAI_API_KEY (never committed, never logged)."""

    model: str
    base_url: str = ""
    api_key_env: str = "PRISM_OPENAI_API_KEY"

    def generate(self, messages: list[dict], schema: dict, timeout_s: float) -> Generation:
        key = os.environ.get(self.api_key_env)
        base = self.base_url or os.environ.get("PRISM_OPENAI_BASE_URL", "")
        if not key or not base:
            raise BackendError("remote backend not configured")
        t0 = time.perf_counter()
        out = _post(f"{base.rstrip('/')}/chat/completions", {
            "model": self.model, "messages": messages, "temperature": 0, "seed": 7,
            "response_format": {"type": "json_schema", "json_schema": {"name": "proposal", "schema": schema}},
        }, timeout_s, {"Authorization": f"Bearer {key}"})
        usage = out.get("usage") or {}
        return Generation(str(out["choices"][0]["message"]["content"]), time.perf_counter() - t0,
                          usage.get("prompt_tokens"), usage.get("completion_tokens"))

    def describe(self) -> dict:
        return {"backend": "openai_compatible", "model": self.model}


@dataclass
class FakeBackend:
    """Tests: returns scripted raw outputs (or raises), recording what it was asked."""

    outputs: list[str | Exception] | Callable[[list[dict]], str]
    calls: list[list[dict]] = field(default_factory=list)

    def generate(self, messages: list[dict], schema: dict, timeout_s: float) -> Generation:
        self.calls.append(messages)
        if callable(self.outputs):
            return Generation(self.outputs(messages), 0.0)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return Generation(out, 0.0)

    def describe(self) -> dict:
        return {"backend": "fake"}
