from __future__ import annotations

import json

import pytest

from btb import ai_commentary as ai
from btb.db import connect, query_df
from btb.evidence import build_packet, packet_ids


@pytest.fixture
def packet(demo_db):
    conn = connect(demo_db)
    return build_packet(conn, "DEMOB", "consolidated")


def test_packet_structure(packet):
    ids = packet_ids(packet)
    assert "R.interest_coverage.FY2023-24" in ids
    assert "F.ebit_cr.FY2024-25" in ids
    assert "FLAG.LOW_INTEREST_COVERAGE.FY2023-24" in ids
    assert packet["is_illustrative"] is True
    assert "INR crore" in packet["units_note"]
    json.dumps(packet)   # must be serialisable


def test_packet_range_filter(demo_db):
    conn = connect(demo_db)
    p = build_packet(conn, "DEMOB", "consolidated", "FY2022-23", "FY2023-24")
    assert p["years"] == ["FY2022-23", "FY2023-24"]
    assert all(f["financial_year"] in p["years"] for f in p["figures"])
    with pytest.raises(ValueError):
        build_packet(conn, "NOPE", "consolidated")


def test_rules_only_summary_passes_verification(packet):
    com = ai.rules_only_summary(packet)
    ver = ai.verify_commentary(com, packet)
    assert com["observed_changes"] and com["follow_up_questions"]
    assert com["implications"] == []
    assert ver["problem_count"] == 0, ver
    assert any("ILLUSTRATIVE" in c for c in com["caveats"])


def test_commentary_numbers_match_dashboard_formatting(demo_db):
    """Regression: packet rounding must not change how a value is displayed (520/6300 = 8.254% -> 8.3%)."""
    from btb.fmt import fmt_pct
    conn = connect(demo_db)
    p = build_packet(conn, "DEMOB", "consolidated", "FY2022-23", "FY2023-24")
    text = " ".join(o["statement"] for o in ai.rules_only_summary(p)["observed_changes"])
    assert fmt_pct(520 / 6300) == "8.3%"
    assert "8.3%" in text and "8.2%" not in text


def test_rules_only_numbers_come_from_packet(packet):
    com = ai.rules_only_summary(packet)
    text = " ".join(o["statement"] for o in com["observed_changes"])
    assert "0.83x" in text or "1.33x" in text      # DEMOB coverage values from the demo data


def good_commentary():
    return {
        "observed_changes": [{"statement": "Interest coverage fell from 2.69x in FY2022-23 to 1.33x in FY2023-24.",
                              "evidence_ids": ["R.interest_coverage.FY2022-23", "R.interest_coverage.FY2023-24"]}],
        "implications": [{"statement": "Higher borrowing costs after debt-funded expansion may be consistent with the lower coverage.",
                          "evidence_ids": ["F.total_debt_cr.FY2023-24"], "label": "hypothesis"}],
        "alternative_explanations": [{"statement": "Margin pressure from input costs could also have reduced EBIT."}],
        "follow_up_questions": ["What share of debt is floating-rate?"],
        "caveats": ["Illustrative data only."],
    }


def test_verification_accepts_good_commentary(packet):
    assert ai.verify_commentary(good_commentary(), packet)["problem_count"] == 0


def test_verification_catches_each_problem_type(packet):
    bad = good_commentary()
    bad["observed_changes"] += [
        {"statement": "Coverage fell to 0.5x.", "evidence_ids": ["R.interest_coverage.FY2023-24"]},       # wrong number
        {"statement": "Debt rose.", "evidence_ids": ["R.nonexistent.FY2023-24"]},                          # unknown id
        {"statement": "Margins dropped.", "evidence_ids": []},                                              # no evidence
        {"statement": "EBIT fell because of rising fuel costs.", "evidence_ids": ["F.ebit_cr.FY2023-24"]},  # causal in observation
    ]
    bad["implications"] += [
        {"statement": "Fuel costs caused the decline.", "evidence_ids": ["F.ebit_cr.FY2023-24"], "label": "hypothesis"},   # unhedged
        {"statement": "Capex raised debt.", "evidence_ids": ["F.total_debt_cr.FY2023-24"], "label": "documented"},          # no DISC/EXT
        {"statement": "Something might follow.", "evidence_ids": ["F.ebit_cr.FY2023-24"], "label": ""},                    # no label
        {"statement": "The company will default next year.", "evidence_ids": ["F.ebit_cr.FY2023-24"], "label": "hypothesis"},
    ]
    bad["caveats"] = []   # packet is illustrative
    ver = ai.verify_commentary(bad, packet)
    text = " | ".join(p for r in ver["items"] for p in r["problems"])
    for expected in ["not found in the cited evidence", "Unknown evidence ID", "No evidence IDs cited",
                     "Causal language in an observation", "not hedged", "documented", "Missing or invalid label",
                     "Predictive or advisory", "illustrative"]:
        assert expected.lower() in text.lower(), expected


def test_percent_numbers_match_fractions(packet):
    com = {"observed_changes": [{"statement": "EBIT margin was 8.3% in FY2023-24.",
                                 "evidence_ids": ["R.ebit_margin.FY2023-24"]}],
           "implications": [], "alternative_explanations": [], "follow_up_questions": [], "caveats": ["illustrative"]}
    assert ai.verify_commentary(com, packet)["problem_count"] == 0


def test_fy_tokens_are_not_treated_as_numbers():
    assert ai._numbers_in("From FY2022-23 to FY2023-24, 2024 and 1.33x") == [1.33]


def test_ai_generation_with_injected_model(packet):
    seen = {}

    def fake(system, user, model):
        seen.update(system=system, user=user, model=model)
        return "```json\n" + json.dumps(good_commentary()) + "\n```"

    com = ai.generate_ai_commentary(packet, model="test-model", call_model=fake)
    assert seen["model"] == "test-model"
    assert "Do NOT calculate new numbers" in seen["system"]
    assert "R.interest_coverage.FY2023-24" in seen["user"]
    assert com["implications"][0]["label"] == "hypothesis"
    assert ai.verify_commentary(com, packet)["problem_count"] == 0


def test_malformed_model_output_raises(packet):
    with pytest.raises(Exception):
        ai.generate_ai_commentary(packet, call_model=lambda s, u, m: "I cannot comply.")


def test_ai_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ai.anthropic_available() is False


def test_save_run_records_for_manual_review(demo_db, packet):
    conn = connect(demo_db)
    com = ai.rules_only_summary(packet)
    ver = ai.verify_commentary(com, packet)
    run_id = ai.save_run(conn, packet, com, ver, "rules_only", None)
    row = query_df(conn, "SELECT * FROM ai_runs WHERE run_id = ?", (run_id,)).iloc[0]
    assert row["mode"] == "rules_only" and row["ticker"] == "DEMOB"
    assert row["manual_factual_errors"] is None or row["manual_factual_errors"] != row["manual_factual_errors"]


def test_ai_runs_survive_pipeline_rerun(tmp_path):
    from btb.pipeline import run_pipeline
    db = tmp_path / "r.sqlite"
    run_pipeline(db_path=db, export_dir=None)
    conn = connect(db)
    conn.execute("INSERT INTO ai_runs (run_at, ticker, basis, mode, evidence_json, output_json) "
                 "VALUES ('now','X','consolidated','rules_only','{}','{}')")
    conn.commit()
    conn.close()
    run_pipeline(db_path=db, export_dir=None)
    assert query_df(connect(db), "SELECT COUNT(*) AS n FROM ai_runs").loc[0, "n"] == 1
