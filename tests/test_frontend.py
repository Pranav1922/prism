"""Frontend backend (frontend/server.py, frontend/live.py): the live driver reproduces the evaluator's results for
every guided demo, and the HTTP/SSE API delivers real agent events and refuses bad input."""

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from evaluation.scenario import load
from frontend import server
from frontend.live import LiveSession


@pytest.mark.parametrize("key", [g[0] for g in server.GUIDED])
def test_every_guided_demo_passes_the_unchanged_evaluator_when_run_live(key):
    scenario = load(server.ROOT / "evaluation" / "scenarios" / f"{key}.json")
    events: list[dict] = []
    s = LiveSession(events.append, server.agent_cmd(), scenario["manifest"], scenario.get("world", {}), scenario, speed=8.0)
    s.start()
    s.join(90)
    assert not s.is_alive() and s.result is not None, [e for e in events if e["type"] == "session"]
    assert s.result["passed"], [c["check"] for c in s.result["checks"] if not c["passed"]]
    kinds = {e["type"] for e in events}
    assert {"wire", "journal", "session", "verdict"} <= kinds
    steps = [e["rec"] for e in events if e["type"] == "journal" and e["rec"]["type"] == "step"]
    assert steps and all("changes" in r and "rules" in r for r in steps)  # the kernel's own records, streamed live


@pytest.fixture(scope="module")
def base_url():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    if server.HUB.session is not None:
        server.HUB.session.stop()


def post(url, body=None, raw=None):
    data = raw if raw is not None else json.dumps(body or {}).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_meta_describes_real_capabilities_and_demos(base_url):
    with urllib.request.urlopen(f"{base_url}/api/meta", timeout=10) as r:
        meta = json.loads(r.read())
    assert {"asr", "ocr", "planner", "tools", "clock"} <= set(meta["capabilities"])
    assert meta["capabilities"]["tools"]["real"] is False  # the tool world is simulated, and says so
    assert len(meta["guided"]) == len(server.GUIDED) and meta["prompts"] and meta["clips"]
    with urllib.request.urlopen(f"{base_url}/", timeout=10) as r:
        assert b"Interruptible Agent" in r.read()


def test_live_session_input_reaches_the_agent_and_streams_back(base_url):
    assert post(f"{base_url}/api/session", {"mode": "live", "preset": "fast"})[0] == 200
    assert post(f"{base_url}/api/input", {"kind": "text", "text": "find flights from Bangalore to Delhi on Friday"})[0] == 200
    deadline, seen = time.time() + 15, []
    with urllib.request.urlopen(f"{base_url}/api/events", timeout=20) as stream:
        while time.time() < deadline:
            line = stream.readline().decode()
            if line.startswith("data:"):
                seen.append(json.loads(line[5:]))
                if any(e["type"] == "wire" and e["dir"] == "out" and (e["msg"] or {}).get("type") == "response.final" for e in seen):
                    break
    assert seen[0]["type"] == "reset"  # a (re)connecting browser gets the whole session
    calls = [e["msg"]["data"] for e in seen if e["type"] == "wire" and e["dir"] == "out" and (e["msg"] or {}).get("type") == "tool.call"]
    assert calls and calls[0]["args"]["destination"] == "DEL"


def test_bad_input_is_refused(base_url):
    post(f"{base_url}/api/session", {"mode": "live"})
    assert post(f"{base_url}/api/input", {"kind": "audio", "ref": "../../etc/passwd"})[0] == 400
    assert post(f"{base_url}/api/input", {"kind": "text", "text": "  "})[0] == 400
    assert post(f"{base_url}/api/input", {"kind": "shell"})[0] == 400
    assert post(f"{base_url}/api/upload?ext=exe", raw=b"x")[0] == 400
    assert post(f"{base_url}/api/session", {"mode": "guided", "scenario": "nope"})[0] == 400
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(f"{base_url}/media/../pyproject.toml", timeout=10)
    post(f"{base_url}/api/session", {"mode": "guided", "scenario": server.GUIDED[0][0]})
    assert post(f"{base_url}/api/input", {"kind": "text", "text": "hi"})[0] == 409  # a guided run takes no live input


def test_streaming_voice_endpoints_refuse_what_they_should(base_url):
    post(f"{base_url}/api/session", {"mode": "guided", "scenario": server.GUIDED[0][0]})
    status = post(f"{base_url}/api/voice/start", {})[0]
    assert status in (409, 503)  # a guided demo takes no live voice (503: no streaming recogniser on this machine)
    assert post(f"{base_url}/api/voice/chunk?id=999", raw=b"\0\0")[0] == 404
    assert post(f"{base_url}/api/voice/end?id=999", {})[0] == 404
    if not server.capabilities()["asr"].get("stream"):
        return
    post(f"{base_url}/api/session", {"mode": "live", "preset": "fast"})
    code, started = post(f"{base_url}/api/voice/start", {})
    assert code == 200
    assert post(f"{base_url}/api/voice/chunk?id={started['id']}", raw=b"\0")[0] == 400  # odd length: not 16-bit PCM
    code, ended = post(f"{base_url}/api/voice/end?id={started['id']}", {})
    assert code == 200 and ended["streamed"] is False  # nothing heard: the browser falls back to the file path
