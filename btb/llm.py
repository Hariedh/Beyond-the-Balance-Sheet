"""LLM providers for the commentary step.

Providers (pick one in the dashboard, or pass provider= in code)
  gemini             Google Gemini API. A free tier exists (Google AI Studio key); limits and
                     which models are free are shown in your AI Studio account.
                     env: GEMINI_API_KEY (or GOOGLE_API_KEY), GEMINI_MODEL
  ollama             Local open-source models via Ollama (http://localhost:11434). Data never
                     leaves your machine. env: OLLAMA_HOST, OLLAMA_MODEL
  openai_compatible  Any OpenAI-style /chat/completions endpoint: Groq, OpenRouter, LM Studio,
                     vLLM, llama.cpp server, ... env: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
  anthropic          Claude via the Anthropic SDK. env: ANTHROPIC_API_KEY, BTB_AI_MODEL

Only the standard library is used for HTTP. API keys come from the environment (never source
code) and are sent in headers, never in URLs, and never included in error messages.

Whatever the provider, the model only ever receives the evidence packet built from the database,
and its output goes through the same verification as every other provider.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_MODELS = {
    "gemini": "gemini-3.5-flash-lite",     # per Google's model list (Oct 2026); override with GEMINI_MODEL
    "ollama": "llama3.1:8b",
    "openai_compatible": "",               # must be provided
    "anthropic": "claude-sonnet-5-5",
}
LABELS = {
    "gemini": "Google Gemini API (free tier available)",
    "ollama": "Ollama (local open-source model)",
    "openai_compatible": "OpenAI-compatible endpoint (Groq, OpenRouter, LM Studio, ...)",
    "anthropic": "Anthropic Claude API",
}
PROVIDERS = tuple(LABELS)
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


class LLMError(RuntimeError):
    """Raised for configuration, network or provider errors (messages never contain API keys)."""


@dataclass(frozen=True)
class ProviderStatus:
    key: str
    label: str
    available: bool
    reason: str            # why unavailable, or a short description when available
    default_model: str
    is_local: bool         # True if prompts never leave the user's machine


# --------------------------------------------------------------------------
# configuration helpers
# --------------------------------------------------------------------------
def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def gemini_key() -> str:
    return _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")


def ollama_host() -> str:
    raw = _env("OLLAMA_HOST") or "http://localhost:11434"
    if "://" not in raw:                # Ollama's own convention allows a bare host:port
        raw = "http://" + raw
    return raw.rstrip("/")


def default_model(provider: str) -> str:
    if provider == "gemini":
        return _env("GEMINI_MODEL") or DEFAULT_MODELS["gemini"]
    if provider == "ollama":
        return _env("OLLAMA_MODEL") or DEFAULT_MODELS["ollama"]
    if provider == "openai_compatible":
        return _env("LLM_MODEL")
    if provider == "anthropic":
        return _env("BTB_AI_MODEL") or DEFAULT_MODELS["anthropic"]
    raise LLMError(f"Unknown provider '{provider}'. Choose one of: {', '.join(PROVIDERS)}.")


def _is_local_url(url: str) -> bool:
    return (urlparse(url).hostname or "") in LOCAL_HOSTS


def is_local(provider: str) -> bool:
    if provider == "ollama":
        return _is_local_url(ollama_host())
    if provider == "openai_compatible":
        return _is_local_url(_env("LLM_BASE_URL"))
    return False


# --------------------------------------------------------------------------
# HTTP (single function so tests can replace it)
# --------------------------------------------------------------------------
def _post_json(url: str, headers: dict, body: dict, timeout: float = 120.0) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    return _open(req, timeout)


def _get_json(url: str, timeout: float = 2.0) -> dict:
    return _open(urllib.request.Request(url, method="GET"), timeout)


def _open(req: urllib.request.Request, timeout: float) -> dict:
    # Never route localhost traffic through an HTTP proxy.
    handlers = [urllib.request.ProxyHandler({})] if _is_local_url(req.full_url) else []
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        hint = {401: " (check the API key)", 403: " (key not allowed for this model/region)",
                404: " (check the model name)", 429: " (rate limit or quota reached; try again later)"}.get(exc.code, "")
        raise LLMError(f"HTTP {exc.code} from {urlparse(req.full_url).netloc}{hint}: {detail}") from None
    except urllib.error.URLError as exc:
        raise LLMError(f"Cannot reach {urlparse(req.full_url).netloc}: {exc.reason}") from None
    except (TimeoutError, OSError) as exc:
        raise LLMError(f"Request to {urlparse(req.full_url).netloc} failed: {exc}") from None
    except json.JSONDecodeError:
        raise LLMError(f"{urlparse(req.full_url).netloc} returned a non-JSON response.") from None


# --------------------------------------------------------------------------
# provider calls: each returns the model's text
# --------------------------------------------------------------------------
def _gemini(system: str, user: str, model: str, timeout: float, api_key: str = "") -> str:
    key = api_key.strip() or gemini_key()
    if not key:
        raise LLMError("No Gemini API key. Paste one in the dashboard, or set GEMINI_API_KEY (free key from Google AI Studio).")
    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "maxOutputTokens": 4096},
    }
    out = _post_json(GEMINI_URL.format(model=model), {"x-goog-api-key": key}, body, timeout)
    block = (out.get("promptFeedback") or {}).get("blockReason")
    if block:
        raise LLMError(f"Gemini blocked the prompt ({block}).")
    cands = out.get("candidates") or []
    if not cands:
        raise LLMError("Gemini returned no candidates.")
    parts = (cands[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        raise LLMError(f"Gemini returned no text (finishReason={cands[0].get('finishReason')}).")
    return text


def _ollama(system: str, user: str, model: str, timeout: float) -> str:
    body = {"model": model, "stream": False, "format": "json",
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    out = _post_json(ollama_host() + "/api/chat", {}, body, timeout)
    text = ((out.get("message") or {}).get("content")) or ""
    if not text.strip():
        raise LLMError("Ollama returned an empty response.")
    return text


def _openai_compatible(system: str, user: str, model: str, timeout: float) -> str:
    base = _env("LLM_BASE_URL").rstrip("/")
    if not base:
        raise LLMError("LLM_BASE_URL is not set (for example https://api.groq.com/openai/v1 or http://localhost:1234/v1).")
    if not model:
        raise LLMError("LLM_MODEL is not set for the OpenAI-compatible provider.")
    headers = {"Authorization": f"Bearer {_env('LLM_API_KEY')}"} if _env("LLM_API_KEY") else {}
    body = {"model": model, "temperature": 0,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    out = _post_json(base + "/chat/completions", headers, body, timeout)
    try:
        text = out["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise LLMError("Unexpected response shape from the OpenAI-compatible endpoint.") from None
    if not text.strip():
        raise LLMError("The endpoint returned an empty response.")
    return text


def _anthropic(system: str, user: str, model: str, timeout: float) -> str:
    try:
        import anthropic
    except ImportError:
        raise LLMError("The 'anthropic' package is not installed (pip install anthropic).") from None
    if not _env("ANTHROPIC_API_KEY"):
        raise LLMError("ANTHROPIC_API_KEY is not set.")
    try:
        client = anthropic.Anthropic(timeout=timeout)
        resp = client.messages.create(model=model, max_tokens=3000, system=system,
                                      messages=[{"role": "user", "content": user}])
    except Exception as exc:  # noqa: BLE001  (SDK raises many types; message never includes the key)
        raise LLMError(f"Anthropic request failed: {type(exc).__name__}: {str(exc)[:200]}") from None
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


_CALLERS = {"gemini": _gemini, "ollama": _ollama, "openai_compatible": _openai_compatible, "anthropic": _anthropic}


def complete(provider: str, system: str, user: str, model: str | None = None, timeout: float = 120.0,
             api_key: str = "") -> str:
    """Send one request to the chosen provider and return the model's text.

    api_key (Gemini only) overrides the environment key, e.g. a key pasted into the dashboard.
    """
    if provider not in _CALLERS:
        raise LLMError(f"Unknown provider '{provider}'. Choose one of: {', '.join(PROVIDERS)}.")
    if provider == "gemini" and api_key:
        return _gemini(system, user, model or default_model(provider), timeout, api_key)
    return _CALLERS[provider](system, user, model or default_model(provider), timeout)


# --------------------------------------------------------------------------
# availability
# --------------------------------------------------------------------------
def ollama_models() -> list[str]:
    """Installed Ollama models, or [] if the server is unreachable."""
    try:
        out = _get_json(ollama_host() + "/api/tags", timeout=1.5)
    except LLMError:
        return []
    return sorted(m.get("name", "") for m in out.get("models", []) if m.get("name"))


def status(provider: str) -> ProviderStatus:
    model = default_model(provider)
    local = is_local(provider)
    if provider == "gemini":
        ok = bool(gemini_key())
        reason = "API key found." if ok else "Set GEMINI_API_KEY (free key from Google AI Studio) in .env."
    elif provider == "ollama":
        installed = ollama_models()
        ok = bool(installed)
        reason = (f"Ollama is running with {len(installed)} model(s)." if ok else
                  f"Ollama not reachable at {ollama_host()} (or no models pulled). Install Ollama, run "
                  f"'ollama pull {model}' and start it.")
    elif provider == "openai_compatible":
        ok = bool(_env("LLM_BASE_URL") and _env("LLM_MODEL"))
        reason = "Endpoint configured." if ok else "Set LLM_BASE_URL and LLM_MODEL (and LLM_API_KEY if required)."
    elif provider == "anthropic":
        try:
            import anthropic  # noqa: F401
            has_sdk = True
        except ImportError:
            has_sdk = False
        ok = has_sdk and bool(_env("ANTHROPIC_API_KEY"))
        reason = "API key found." if ok else ("Install the 'anthropic' package and set ANTHROPIC_API_KEY."
                                              if not has_sdk else "Set ANTHROPIC_API_KEY.")
    else:
        raise LLMError(f"Unknown provider '{provider}'.")
    return ProviderStatus(provider, LABELS[provider], ok, reason, model, local)


def all_statuses() -> list[ProviderStatus]:
    return [status(p) for p in PROVIDERS]
