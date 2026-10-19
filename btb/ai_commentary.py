"""Commentary generation with guardrails.

Two modes produce the SAME output structure so they can be compared:
  * rules_only : deterministic text built from the evidence packet (no AI).
  * ai         : an existing model summarises ONLY the evidence packet.

The AI never calculates ratios. Every statement must cite evidence IDs, and
verify_commentary() checks IDs, numbers, label discipline and causal language
afterwards. Verification catches some problems, not all: a human must still
review the output (see the ai_runs manual-review columns).

Guardrails: public data only (the app asks for confirmation before sending anything to a
hosted service), API keys read from the environment only, causation never asserted without a
documented disclosure or external indicator. Providers (Gemini free tier, local Ollama,
OpenAI-compatible endpoints, Anthropic) live in btb/llm.py.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Callable

from . import llm
from .evidence import packet_ids
from .fmt import fmt_pct, fmt_x

# --------------------------------------------------------------------------
# Output structure
#   {"observed_changes":   [{"statement", "evidence_ids"}],
#    "implications":       [{"statement", "evidence_ids", "label": "hypothesis"|"documented"}],
#    "alternative_explanations": [{"statement"}],
#    "follow_up_questions": [str],
#    "caveats": [str]}
# --------------------------------------------------------------------------
SECTIONS_WITH_EVIDENCE = ("observed_changes", "implications")

SYSTEM_PROMPT = """You are an assistant for a financial-ratio SCREENING tool. You help a human analyst read \
a structured evidence packet about one Indian listed company. You are not a credit-rating agency and you \
do not predict default.

Hard rules:
1. Use ONLY the evidence packet provided. Do not use outside knowledge about the company, its industry or \
the economy. Do not invent facts, figures, events or dates.
2. Do NOT calculate new numbers. Quote numbers exactly as they appear in the packet (percent-type ratios \
are stored as fractions: 0.1234 means 12.3%). Do not state differences, averages or growth rates you \
computed yourself.
3. Every statement in "observed_changes" and "implications" must list the evidence IDs it relies on in \
"evidence_ids", copied exactly from the packet.
4. "observed_changes" are plain descriptions of what the numbers show. They must not contain causal language \
(no "because", "due to", "caused", "led to", "driven by").
5. "implications" must carry a label. Use "hypothesis" unless a disclosure or external indicator in the packet \
(IDs starting DISC. or EXT.) documents the point; only then may you use "documented" and you must cite that ID. \
Hypotheses must be hedged (may, might, could, possibly, consistent with).
6. Never claim that a company will default, is distressed, or is safe. Never give investment advice.
7. If the packet marks data as illustrative, say so in "caveats".
8. If evidence is missing or thin, say so in "caveats" rather than guessing.

Return ONLY a JSON object with exactly these keys:
{
 "observed_changes": [{"statement": str, "evidence_ids": [str]}],
 "implications": [{"statement": str, "evidence_ids": [str], "label": "hypothesis" | "documented"}],
 "alternative_explanations": [{"statement": str}],
 "follow_up_questions": [str],
 "caveats": [str]
}"""

FOLLOW_UP_BY_RULE = {
    "LOW_INTEREST_COVERAGE": "What drove the movement in EBIT and finance costs, and what share of debt is floating-rate or due for refinancing?",
    "NEGATIVE_OPERATING_CASH_FLOW": "Which working-capital items (receivables, inventory, payables) or one-off items explain the cash-flow shortfall?",
    "DEBT_UP_EBIT_DOWN": "What was the new debt used for (capacity expansion, acquisition, working capital), and when is incremental capacity expected to contribute earnings?",
    "LOW_CURRENT_RATIO": "Is the low current ratio structural (e.g. normal for this business model) or a sign of near-term funding pressure? What undrawn facilities exist?",
    "SUSTAINED_EBIT_MARGIN_DECLINE": "Which cost lines (energy, freight, raw materials) or price/mix changes are documented in the annual report for the margin decline?",
    "SUSTAINED_REVENUE_DECLINE": "Is the decline driven by volume, price or a scope change such as a divestment or demerger?",
    "NONPOSITIVE_EQUITY": "What caused equity to turn non-positive (accumulated losses, buybacks, restatement) and how should leverage be assessed instead?",
}

CAUSAL_RE = re.compile(
    r"\b(caused|causes|because of|because|due to|as a result of|led to|leading to|resulted in|"
    r"driven by|owing to|attributable to|thanks to)\b", re.I)
HEDGE_RE = re.compile(r"\b(may|might|could|possibly|potentially|suggests?|consistent with|appears?|"
                      r"would be consistent|can indicate)\b", re.I)
FY_TOKEN_RE = re.compile(r"\bFY\s?\d{4}\s?[-–]\s?\d{2}\b|\b\d{4}\s?[-–]\s?\d{2}\b|\b(?:19|20)\d{2}\b", re.I)
NUMBER_RE = re.compile(r"(?<![\w.])\(?-?\+?\d[\d,]*\.?\d*\)?%?")


# --------------------------------------------------------------------------
# Evidence lookup helpers
# --------------------------------------------------------------------------
def _figure(packet: dict, metric: str, fy: str, prefix: str = "R"):
    wanted = f"{prefix}.{metric}.{fy}"
    return next((f for f in packet["figures"] if f["id"] == wanted), None)


def _numbers_in(text: str) -> list[float]:
    """Numbers in free text, ignoring financial-year / year tokens."""
    cleaned = FY_TOKEN_RE.sub(" ", text or "")
    out = []
    for tok in NUMBER_RE.findall(cleaned):
        t = tok.strip("()%").replace(",", "").lstrip("+")
        try:
            out.append(float(t))
        except ValueError:
            pass
    return out


def _candidate_numbers(packet: dict, evidence_id: str) -> list[float]:
    for f in packet["figures"]:
        if f["id"] == evidence_id:
            return [f["value"]]
    for f in packet["flags"]:
        if f["id"] == evidence_id:
            nums = _numbers_in(f["evidence_text"]) + _numbers_in(f.get("threshold") or "")
            if f["observed_value"] is not None:
                nums.append(f["observed_value"])
            return nums
    for d in packet["disclosures"]:
        if d["id"] == evidence_id:
            return _numbers_in(d["excerpt"])
    for e in packet["external_indicators"]:
        if e["id"] == evidence_id:
            return [e["value"]] if e["value"] is not None else []
    return []


def _number_supported(n: float, candidates: list[float]) -> bool:
    for c in candidates:
        for v in (c, c * 100, abs(c), abs(c) * 100):
            if abs(n - v) <= max(0.051, 0.01 * abs(n)) or abs(abs(n) - abs(v)) <= max(0.051, 0.01 * abs(n)):
                return True
    return False


# --------------------------------------------------------------------------
# Rules-only summary (deterministic baseline)
# --------------------------------------------------------------------------
def rules_only_summary(packet: dict) -> dict:
    years = packet["years"]
    observed: list[dict] = []

    if len(years) >= 2:
        prev, cur = years[-2], years[-1]
        spec = [("interest_coverage", fmt_x), ("debt_to_equity", fmt_x), ("current_ratio", fmt_x),
                ("ocf_to_debt", fmt_x), ("ebit_margin", fmt_pct)]
        for metric, fmt in spec:
            a, b = _figure(packet, metric, prev), _figure(packet, metric, cur)
            if a and b:
                label = a["label"]
                observed.append({
                    "statement": f"{label} moved from {fmt(a['value'])} in {prev} to {fmt(b['value'])} in {cur}.",
                    "evidence_ids": [a["id"], b["id"]],
                })
        g = _figure(packet, "revenue_growth", cur)
        if g:
            observed.append({"statement": f"Revenue growth in {cur} was {fmt_pct(g['value'])}.",
                             "evidence_ids": [g["id"]]})
    elif years:
        observed.append({"statement": f"Only one financial year ({years[0]}) is in range, so no year-on-year "
                                      "changes can be described.", "evidence_ids": []})

    for f in packet["flags"]:
        observed.append({"statement": f"Screening flag {f['rule_id']} in {f['financial_year']}: {f['evidence_text']}",
                         "evidence_ids": [f["id"]]})

    rules_seen = []
    for f in packet["flags"]:
        if f["rule_id"] not in rules_seen:
            rules_seen.append(f["rule_id"])
    follow_ups = [FOLLOW_UP_BY_RULE[r] for r in rules_seen if r in FOLLOW_UP_BY_RULE]
    if not follow_ups:
        follow_ups = ["No screening flags fired at the chosen thresholds. Do peers or the trend in the underlying "
                      "inputs show anything the rules do not capture?"]

    caveats = ["Rules-only summary: no implications are generated. Flags show where simple threshold rules "
               "fired, not why."]
    if packet["is_illustrative"]:
        caveats.insert(0, "ILLUSTRATIVE (synthetic) data: not real company figures.")
    if not packet["disclosures"] and not packet["external_indicators"]:
        caveats.append("No company disclosures or external indicators are loaded, so no cause can be documented.")
    caveats.extend(packet["data_quality_notes"][:5])

    return {"observed_changes": observed, "implications": [],
            "alternative_explanations": [], "follow_up_questions": follow_ups, "caveats": caveats}


# --------------------------------------------------------------------------
# AI mode
# --------------------------------------------------------------------------
def anthropic_available() -> bool:
    """Kept for backwards compatibility; prefer llm.status(provider)."""
    return llm.status("anthropic").available


RETRY_SUFFIX = ("\n\nYour previous reply could not be parsed. Reply again with ONLY the JSON object described in "
                "the instructions: no prose, no markdown fences, keys exactly as specified, evidence_ids as arrays.")


def parse_model_json(text: str) -> dict:
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.I)
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Model response did not contain a JSON object.")
    data = json.loads(s[start:end + 1])
    return normalise_commentary(data)


def normalise_commentary(data: dict) -> dict:
    def as_list(value):
        # small / local models sometimes return a string instead of a list
        if isinstance(value, str):
            return [v.strip() for v in value.split(",") if v.strip()]
        return [str(x).strip() for x in (value or [])]

    def items(key, with_label=False):
        out = []
        raw = data.get(key, []) or []
        if isinstance(raw, (str, dict)):
            raw = [raw]
        for it in raw:
            if isinstance(it, str):
                it = {"statement": it}
            if not isinstance(it, dict):
                continue
            d = {"statement": str(it.get("statement", "")).strip(),
                 "evidence_ids": as_list(it.get("evidence_ids"))}
            if with_label:
                d["label"] = str(it.get("label", "")).strip().lower()
            if key == "alternative_explanations":
                d.pop("evidence_ids", None)
            if d["statement"]:
                out.append(d)
        return out

    return {
        "observed_changes": items("observed_changes"),
        "implications": items("implications", with_label=True),
        "alternative_explanations": items("alternative_explanations"),
        "follow_up_questions": as_list(data.get("follow_up_questions")),
        "caveats": as_list(data.get("caveats")),
    }


def generate_ai_commentary(packet: dict, provider: str = "anthropic", model: str | None = None,
                           call_model: Callable[[str, str, str], str] | None = None, retries: int = 1) -> dict:
    """Ask a model to summarise the packet.

    provider   one of llm.PROVIDERS ('gemini', 'ollama', 'openai_compatible', 'anthropic')
    call_model optional `(system, user, model) -> text` used instead of a real provider (tests)
    retries    extra attempts if the reply is not valid JSON (small local models need this sometimes)
    """
    model = model or llm.default_model(provider)
    call = call_model or (lambda s, u, m: llm.complete(provider, s, u, m))
    user = ("Evidence packet (JSON). Use only this.\n\n" + json.dumps(packet, ensure_ascii=False, indent=1))
    last: Exception | None = None
    for attempt in range(retries + 1):
        text = call(SYSTEM_PROMPT, user if attempt == 0 else user + RETRY_SUFFIX, model)
        try:
            return parse_model_json(text)
        except (ValueError, TypeError, AttributeError) as exc:   # JSONDecodeError is a ValueError
            last = exc
    raise ValueError(f"The model did not return valid JSON after {retries + 1} attempt(s): {last}")


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------
def verify_commentary(commentary: dict, packet: dict) -> dict:
    """Check commentary against the packet. Returns per-item problems and totals."""
    ids = packet_ids(packet)
    results = []

    def check(section: str, index: int, item: dict) -> list[str]:
        problems: list[str] = []
        text = item["statement"]
        cited = item.get("evidence_ids", [])

        if section in SECTIONS_WITH_EVIDENCE and not cited:
            problems.append("No evidence IDs cited.")
        unknown = [c for c in cited if c not in ids]
        if unknown:
            problems.append(f"Unknown evidence ID(s): {', '.join(unknown)}")

        if section in SECTIONS_WITH_EVIDENCE:
            known = [c for c in cited if c in ids]
            candidates = [n for c in known for n in _candidate_numbers(packet, c)]
            for n in _numbers_in(text):
                if float(n).is_integer() and abs(n) <= 10:
                    continue
                if not _number_supported(n, candidates):
                    problems.append(f"Number {n:g} is not found in the cited evidence.")

        causal = bool(CAUSAL_RE.search(text))
        if section == "observed_changes" and causal:
            problems.append("Causal language in an observation.")
        if section == "implications":
            label = item.get("label", "")
            if label not in ("hypothesis", "documented"):
                problems.append("Missing or invalid label (must be 'hypothesis' or 'documented').")
            if label == "documented" and not any(c.startswith(("DISC.", "EXT.")) for c in cited):
                problems.append("Labelled 'documented' but cites no disclosure (DISC.) or external indicator (EXT.).")
            if label == "hypothesis" and causal and not HEDGE_RE.search(text):
                problems.append("Causal hypothesis is not hedged.")
        if re.search(r"\b(will default|is going to default|certain to default|guaranteed|safe investment|buy|sell)\b",
                     text, re.I):
            problems.append("Predictive or advisory language.")
        return problems

    for section in ("observed_changes", "implications", "alternative_explanations"):
        for i, item in enumerate(commentary.get(section, [])):
            results.append({"section": section, "index": i, "statement": item["statement"],
                            "problems": check(section, i, item)})

    if packet["is_illustrative"] and not any("illustrative" in c.lower() for c in commentary.get("caveats", [])):
        results.append({"section": "caveats", "index": -1, "statement": "(missing illustrative-data caveat)",
                        "problems": ["Packet is illustrative but the commentary does not say so."]})

    total = sum(len(r["problems"]) for r in results)
    return {"items": results, "problem_count": total,
            "statements_checked": len(results),
            "statements_without_problems": sum(not r["problems"] for r in results)}


# --------------------------------------------------------------------------
# Persistence for manual evaluation
# --------------------------------------------------------------------------
def save_run(conn, packet: dict, commentary: dict, verification: dict, mode: str, model: str | None) -> int:
    """`model` is stored as given, e.g. 'gemini:gemini-3.5-flash-lite' (None for rules-only)."""
    cur = conn.execute(
        "INSERT INTO ai_runs (run_at, ticker, basis, mode, model, evidence_json, output_json, auto_problem_count) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"), packet["company"]["ticker"], packet["basis"],
         mode, model if mode == "ai" else None, json.dumps(packet, ensure_ascii=False),
         json.dumps({"commentary": commentary, "verification": verification}, ensure_ascii=False),
         verification["problem_count"]),
    )
    conn.commit()
    return cur.lastrowid
