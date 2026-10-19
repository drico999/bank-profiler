"""Narrative = the ONLY place free text is written. It is grounded two ways:
  1. a deterministic template (default, always available, zero hallucination risk)
  2. optional LLM rewrite that sees ONLY the computed facts, and is rejected if it
     contains any number that isn't in those facts (then we fall back to the template).
"""
import json
import re

from .archetypes import DESCRIPTIONS, Verdict
from .metrics import Metrics
from .money import format_rand


def facts_for(v: Verdict, m: Metrics) -> dict[str, str]:
    R = format_rand
    f = {
        "archetype": v.archetype, "score": str(v.score), "max_score": "100", "overspend_threshold": "95%", "confidence": v.confidence_label,
        "cycles": str(m.n_cycles),
        "avg_income": R(m.avg_income), "avg_spend": R(m.avg_spend),
        "savings_rate": f"{(m.savings_rate or 0):.0%}",
        "overspent": f"{m.overspent_cycles} of {m.n_cycles}",
        "buffer_months": f"{m.buffer_months:.1f}",
        "month_end_low": f"{m.month_end_low_cycles} of {m.n_cycles}",
        "committed": f"{m.committed_ratio:.0%}", "debt": f"{m.debt_ratio:.0%}",
        "discretionary": f"{m.discretionary_ratio:.0%}",
        "gambling": f"{m.gambling_ratio:.0%}", "fees": f"{m.fee_ratio:.1%}",
        "cash_share": f"{m.cash_share:.0%}", "income_variation": f"{m.income_cv:.0%}",
    }
    return f


def template_narrative(v: Verdict, m: Metrics) -> str:
    f = facts_for(v, m)
    parts = [f"This client profiles as {v.archetype}: {DESCRIPTIONS[v.archetype].lower()}"]
    if v.archetype == "Insufficient data":
        return parts[0]
    parts.append(
        f"Across {f['cycles']} cycle(s) they averaged {f['avg_income']} in and {f['avg_spend']} out, "
        f"a savings rate of {f['savings_rate']}. They spent 95% or more of their income in {f['overspent']} cycles.")
    parts.append(
        f"Their balance covers about {f['buffer_months']} months of spending and dipped near zero before payday in "
        f"{f['month_end_low']} cycles.")
    parts.append(f"Fixed commitments take {f['committed']} of income (debt {f['debt']}); discretionary spending is {f['discretionary']}.")
    if m.gambling_ratio > 0:
        parts.append(f"Betting and gambling is {f['gambling']} of income.")
    if m.cash_share > 0.25:
        parts.append(f"Cash is {f['cash_share']} of spending, so this profile is less certain.")
    parts.append(f"Resilience score {f['score']} out of 100, confidence {f['confidence'].lower()}.")
    return " ".join(parts)


_NUM = re.compile(r"\d+(?:\.\d+)?")
_THOUSANDS = re.compile(r"(?<=\d) (?=\d{3}\b)")


def numbers_in(text: str) -> set[str]:
    """All numbers in a string, with SA thousands spaces joined ('R12 000' -> '12000')."""
    return set(_NUM.findall(_THOUSANDS.sub("", text)))


def grounded(text: str, facts: dict[str, str]) -> bool:
    allowed = numbers_in(" | ".join(facts.values()))
    return numbers_in(text) <= allowed


def llm_narrative(v: Verdict, m: Metrics, client, model: str) -> str | None:
    """Ask the model to rewrite the facts in friendlier prose. Returns None if it fails the number check."""
    facts = facts_for(v, m)
    prompt = ("Write 3 short sentences for a financial analyst summarising this client. Use ONLY the facts below; "
              "do not add, round or compute any number. Neutral tone, no advice, no assumptions about why.\n"
              + json.dumps(facts))
    try:
        r = client.messages.create(model=model, max_tokens=400, messages=[{"role": "user", "content": prompt}])
        text = "".join(getattr(b, "text", "") for b in r.content).strip()
    except Exception:
        return None
    return text if text and grounded(text, facts) else None


def write_narrative(v: Verdict, m: Metrics, client=None, model: str = "") -> tuple[str, str]:
    if client is not None:
        t = llm_narrative(v, m, client, model)
        if t:
            return t, "llm (number-checked)"
    return template_narrative(v, m), "template"
