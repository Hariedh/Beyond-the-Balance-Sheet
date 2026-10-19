"""Headless smoke test of the Streamlit dashboard using Streamlit's AppTest."""
from __future__ import annotations

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from btb import config  # noqa: E402
from btb.pipeline import run_pipeline  # noqa: E402


@pytest.fixture
def app(tmp_path, monkeypatch):
    db = tmp_path / "app.sqlite"
    monkeypatch.setenv("BTB_DB_PATH", str(db))
    monkeypatch.setattr(config, "DB_PATH", db)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    run_pipeline(db_path=db, export_dir=None)
    at = AppTest.from_file(str(config.ROOT / "app.py"), default_timeout=90)
    at.run()
    return at


def test_app_renders_without_exceptions(app):
    assert not app.exception, [e.value for e in app.exception]
    assert any("Beyond the Balance Sheet" in t.value for t in app.title)
    assert len(app.metric) == 6
    # the default company is real data: no illustrative banner
    assert not any("ILLUSTRATIVE" in w.value for w in app.warning)


def test_illustrative_banner_shown_for_demo_company(app):
    app.sidebar.selectbox[0].select("DEMOA").run()
    assert not app.exception, [e.value for e in app.exception]
    assert any("ILLUSTRATIVE" in w.value for w in app.warning)


def test_non_12_month_period_is_called_out(app):
    app.sidebar.selectbox[0].select("AMBUJACEM").run()
    assert not app.exception, [e.value for e in app.exception]
    assert any("15-month" in w.value for w in app.warning)


def test_company_switch_and_threshold_change(app):
    app.sidebar.selectbox[0].select("DEMOB").run()
    assert not app.exception
    app.sidebar.number_input[0].set_value(3.0).run()
    assert not app.exception


def test_rules_only_commentary_flow(app):
    app.sidebar.selectbox[0].select("DEMOB").run()
    next(b for b in app.button if b.label == "Generate commentary").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert any("saved for evaluation" in c.value for c in app.caption)


@pytest.fixture
def no_llm_env(monkeypatch):
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:9")   # nothing listens here


def test_ai_mode_blocked_without_provider(app, no_llm_env):
    app.radio[0].set_value("AI-assisted summary").run()
    assert not app.exception, [e.value for e in app.exception]
    assert any("GEMINI_API_KEY" in w.value for w in app.warning)       # default provider explains what to set
    assert next(b for b in app.button if b.label == "Generate commentary").disabled


def test_ai_mode_with_gemini_key_requires_public_data_confirmation(app, monkeypatch, no_llm_env):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    app.radio[0].set_value("AI-assisted summary").run()
    assert not app.exception, [e.value for e in app.exception]
    gen = next(b for b in app.button if b.label == "Generate commentary")
    assert gen.disabled                                    # hosted service: must confirm data is public
    app.checkbox[0].check().run()
    assert not next(b for b in app.button if b.label == "Generate commentary").disabled


def test_ai_mode_full_flow_with_stubbed_provider(app, monkeypatch, no_llm_env):
    """End to end through the UI with the HTTP layer stubbed (no network)."""
    import json as _json
    from btb import llm

    reply = {"observed_changes": [], "implications": [],
             "alternative_explanations": [], "follow_up_questions": ["What drove EBIT?"],
             "caveats": ["Data are from secondary sources."]}
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(llm, "_post_json", lambda *a, **k: {"candidates": [{"content": {"parts": [{"text": _json.dumps(reply)}]}}]})
    app.radio[0].set_value("AI-assisted summary").run()
    app.checkbox[0].check().run()
    next(b for b in app.button if b.label == "Generate commentary").click().run()
    assert not app.exception, [e.value for e in app.exception]
    assert any("saved for evaluation" in c.value for c in app.caption)
    assert any("What drove EBIT?" in m.value for m in app.markdown)
