"""LLM provider layer: tested against a real local HTTP server (no external network)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from btb import ai_commentary as ai
from btb import llm
from btb.db import connect
from btb.evidence import build_packet

SECRET = "SECRET-KEY-123"
GOOD = {"observed_changes": [{"statement": "Interest coverage was 5.17x in FY2024-25.",
                              "evidence_ids": ["R.interest_coverage.FY2024-25"]}],
        "implications": [], "alternative_explanations": [], "follow_up_questions": ["Why did debt rise?"],
        "caveats": ["Secondary-source data."]}


class Stub:
    """A tiny HTTP server that records requests and replies with a configurable response."""

    def __init__(self):
        self.requests: list[dict] = []
        self.status = 200
        self.reply: dict | str = {}
        self.queue: list = []          # if non-empty, replies are consumed in order
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):  # silence
                pass

            def _send(self):
                reply = stub.queue.pop(0) if stub.queue else stub.reply
                body = reply if isinstance(reply, str) else json.dumps(reply)
                self.send_response(stub.status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body.encode())

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                stub.requests.append({"path": self.path, "headers": self._headers(),
                                      "body": json.loads(self.rfile.read(n) or b"{}")})
                self._send()

            def _headers(self):
                # HTTP header names are case-insensitive and urllib re-capitalises them
                return {k.lower(): v for k, v in self.headers.items()}

            def do_GET(self):
                stub.requests.append({"path": self.path, "headers": self._headers(), "body": None})
                self._send()

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GEMINI_MODEL", "ANTHROPIC_API_KEY", "LLM_BASE_URL",
                 "LLM_API_KEY", "LLM_MODEL", "OLLAMA_HOST", "OLLAMA_MODEL", "BTB_AI_MODEL"):
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------
def test_gemini_request_shape_and_key_in_header_only(stub, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.setattr(llm, "GEMINI_URL", stub.url + "/v1beta/models/{model}:generateContent")
    stub.reply = {"candidates": [{"content": {"parts": [{"text": json.dumps(GOOD)}]}}]}
    text = llm.complete("gemini", "SYS", "USER", "gemini-test")
    req = stub.requests[0]
    assert json.loads(text) == GOOD
    assert req["path"] == "/v1beta/models/gemini-test:generateContent"
    assert SECRET not in req["path"]                                   # never in the URL
    assert req["headers"]["x-goog-api-key"] == SECRET
    assert req["body"]["systemInstruction"]["parts"][0]["text"] == "SYS"
    assert req["body"]["contents"][0]["parts"][0]["text"] == "USER"
    assert req["body"]["generationConfig"]["temperature"] == 0
    assert req["body"]["generationConfig"]["responseMimeType"] == "application/json"


def test_gemini_skips_thought_parts_and_reports_blocks(stub, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.setattr(llm, "GEMINI_URL", stub.url + "/{model}")
    stub.reply = {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": "{}"}]}}]}
    assert llm.complete("gemini", "s", "u", "m") == "{}"
    stub.reply = {"promptFeedback": {"blockReason": "SAFETY"}}
    with pytest.raises(llm.LLMError, match="blocked"):
        llm.complete("gemini", "s", "u", "m")
    stub.reply = {"candidates": []}
    with pytest.raises(llm.LLMError, match="no candidates"):
        llm.complete("gemini", "s", "u", "m")


def test_gemini_without_key_is_a_clear_error():
    with pytest.raises(llm.LLMError, match="GEMINI_API_KEY"):
        llm.complete("gemini", "s", "u")


def test_http_errors_are_mapped_and_never_leak_the_key(stub, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.setattr(llm, "GEMINI_URL", stub.url + "/{model}")
    for code, hint in [(429, "rate limit"), (401, "API key"), (404, "model name")]:
        stub.status, stub.reply = code, {"error": {"message": "nope"}}
        with pytest.raises(llm.LLMError) as exc:
            llm.complete("gemini", "s", "u", "m")
        assert hint in str(exc.value) and SECRET not in str(exc.value)


def test_unreachable_host_is_a_clear_error(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:9")                  # bare host:port accepted
    assert llm.ollama_host() == "http://127.0.0.1:9"
    with pytest.raises(llm.LLMError, match="Cannot reach"):
        llm.complete("ollama", "s", "u", "m")


def test_ollama_request_shape_models_and_status(stub, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", stub.url)
    stub.reply = {"message": {"role": "assistant", "content": json.dumps(GOOD)}, "done": True}
    text = llm.complete("ollama", "SYS", "USER", "llama-test")
    body = stub.requests[0]["body"]
    assert stub.requests[0]["path"] == "/api/chat" and json.loads(text) == GOOD
    assert body["model"] == "llama-test" and body["stream"] is False and body["format"] == "json"
    assert body["options"]["temperature"] == 0
    assert [m["role"] for m in body["messages"]] == ["system", "user"]

    stub.reply = {"models": [{"name": "qwen2.5:7b"}, {"name": "llama3.1:8b"}]}
    assert llm.ollama_models() == ["llama3.1:8b", "qwen2.5:7b"]
    st = llm.status("ollama")
    assert st.available and st.is_local


def test_ollama_status_when_not_running(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")
    st = llm.status("ollama")
    assert not st.available and "ollama pull" in st.reason and st.is_local


def test_openai_compatible_request_shape(stub, monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", stub.url + "/openai/v1/")
    monkeypatch.setenv("LLM_API_KEY", SECRET)
    monkeypatch.setenv("LLM_MODEL", "some-model")
    stub.reply = {"choices": [{"message": {"content": json.dumps(GOOD)}}]}
    text = llm.complete("openai_compatible", "SYS", "USER")
    req = stub.requests[0]
    assert json.loads(text) == GOOD
    assert req["path"] == "/openai/v1/chat/completions"
    assert req["headers"]["authorization"] == f"Bearer {SECRET}"
    assert req["body"]["model"] == "some-model" and req["body"]["temperature"] == 0
    stub.reply = {"unexpected": True}
    with pytest.raises(llm.LLMError, match="Unexpected response"):
        llm.complete("openai_compatible", "s", "u")


def test_openai_compatible_config_errors():
    with pytest.raises(llm.LLMError, match="LLM_BASE_URL"):
        llm.complete("openai_compatible", "s", "u")
    assert not llm.status("openai_compatible").available


def test_unknown_provider():
    with pytest.raises(llm.LLMError, match="Unknown provider"):
        llm.complete("nope", "s", "u")


def test_status_and_defaults(monkeypatch):
    assert not llm.status("gemini").available and "GEMINI_API_KEY" in llm.status("gemini").reason
    assert not llm.status("gemini").is_local
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    assert llm.status("gemini").available
    monkeypatch.setenv("GEMINI_MODEL", "my-model")
    assert llm.default_model("gemini") == "my-model"
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:1234/v1")
    assert llm.is_local("openai_compatible")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    assert not llm.is_local("openai_compatible")
    assert [s.key for s in llm.all_statuses()] == list(llm.PROVIDERS)


# --------------------------------------------------------------------------
# generate_ai_commentary with real providers (through the stub server)
# --------------------------------------------------------------------------
@pytest.fixture(scope="module")
def packet(tmp_path_factory):
    from btb.pipeline import run_pipeline
    db = tmp_path_factory.mktemp("llm") / "t.sqlite"
    run_pipeline(db_path=db, export_dir=None)
    return build_packet(connect(db), "ULTRACEMCO", "consolidated")


def test_end_to_end_gemini_commentary_is_verified(stub, monkeypatch, packet):
    monkeypatch.setenv("GEMINI_API_KEY", SECRET)
    monkeypatch.setattr(llm, "GEMINI_URL", stub.url + "/{model}")
    stub.reply = {"candidates": [{"content": {"parts": [{"text": json.dumps(GOOD)}]}}]}
    com = ai.generate_ai_commentary(packet, provider="gemini", model="m")
    ver = ai.verify_commentary(com, packet)
    assert ver["problem_count"] == 0, ver
    # the packet (and nothing else) is what was sent
    sent = stub.requests[0]["body"]["contents"][0]["parts"][0]["text"]
    assert "R.interest_coverage.FY2024-25" in sent and SECRET not in sent


def test_hallucinated_number_from_a_model_is_caught(stub, monkeypatch, packet):
    monkeypatch.setenv("OLLAMA_HOST", stub.url)
    bad = {**GOOD, "observed_changes": [{"statement": "Interest coverage was 12.34x in FY2024-25.",
                                         "evidence_ids": ["R.interest_coverage.FY2024-25"]}]}
    stub.reply = {"message": {"content": json.dumps(bad)}}
    ver = ai.verify_commentary(ai.generate_ai_commentary(packet, provider="ollama", model="m"), packet)
    assert ver["problem_count"] == 1 and "not found in the cited evidence" in ver["items"][0]["problems"][0]


def test_invalid_json_triggers_one_retry_then_succeeds(stub, monkeypatch, packet):
    monkeypatch.setenv("OLLAMA_HOST", stub.url)
    stub.queue = [{"message": {"content": "Sure! Here is my analysis..."}},
                  {"message": {"content": "```json\n" + json.dumps(GOOD) + "\n```"}}]
    com = ai.generate_ai_commentary(packet, provider="ollama", model="m")
    assert com["follow_up_questions"] == ["Why did debt rise?"]
    assert len(stub.requests) == 2
    assert "could not be parsed" in stub.requests[1]["body"]["messages"][1]["content"]


def test_invalid_json_twice_raises(stub, monkeypatch, packet):
    monkeypatch.setenv("OLLAMA_HOST", stub.url)
    stub.reply = {"message": {"content": "I cannot do that."}}
    with pytest.raises(ValueError, match="valid JSON"):
        ai.generate_ai_commentary(packet, provider="ollama", model="m")
    assert len(stub.requests) == 2


def test_small_model_quirks_are_normalised():
    messy = {"observed_changes": [{"statement": "A.", "evidence_ids": "R.a.FY2024-25, R.b.FY2024-25"}, "Plain string"],
             "implications": {"statement": "B.", "evidence_ids": ["F.x"], "label": " Hypothesis "},
             "alternative_explanations": ["C."], "follow_up_questions": "One question?", "caveats": None}
    n = ai.normalise_commentary(messy)
    assert n["observed_changes"][0]["evidence_ids"] == ["R.a.FY2024-25", "R.b.FY2024-25"]
    assert n["observed_changes"][1]["statement"] == "Plain string"
    assert n["implications"][0]["label"] == "hypothesis"
    assert n["follow_up_questions"] == ["One question?"] and n["caveats"] == []


def test_run_is_saved_with_provider_and_model(tmp_path, packet):
    from btb.db import init_db, query_df
    conn = connect(tmp_path / "r.sqlite")
    init_db(conn)
    ver = ai.verify_commentary(GOOD, packet)
    rid = ai.save_run(conn, packet, GOOD, ver, "ai", "ollama:llama3.1:8b")
    assert query_df(conn, "SELECT model FROM ai_runs WHERE run_id = ?", (rid,)).loc[0, "model"] == "ollama:llama3.1:8b"
