import json
import os
import re
from collections import defaultdict
from pathlib import Path
from statistics import median

from ..models import Transaction
from .normalise import merchant_key
from .rules import match_rule

DATA_DIR = Path(os.environ.get("PROFILER_DATA_DIR", "data"))


# ---------------------------------------------------------------- corrections (learning)
def load_corrections(path: Path | None = None) -> dict[str, str]:
    p = path or DATA_DIR / "corrections.json"
    return json.loads(p.read_text()) if p.exists() else {}


def save_correction(key: str, category: str, path: Path | None = None) -> None:
    p = path or DATA_DIR / "corrections.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    data = load_corrections(p)
    data[key] = category
    p.write_text(json.dumps(data, indent=1))


# ---------------------------------------------------------------- categorise
def categorise(txns: list[Transaction], llm=None, corrections: dict[str, str] | None = None,
               low_conf: float = 0.7) -> None:
    corrections = corrections if corrections is not None else {}
    unknown_keys: dict[str, list[Transaction]] = defaultdict(list)
    for t in txns:
        key = merchant_key(t.description)
        if key in corrections:
            t.category, t.category_source, t.confidence = corrections[key], "correction", 1.0
            t.merchant = t.merchant or key.title()
            continue
        hit = match_rule(t.description, t.is_credit)
        if hit:
            t.category, t.merchant = hit[0], hit[1] or key.title()
            t.category_source = "rule"
            t.confidence = 0.6 if hit[0] == "other_income" else 0.95
        else:
            t.merchant = key.title()
            unknown_keys[key].append(t)
    if llm and unknown_keys:
        # only DEBIT merchants go to the LLM by default; unknown credits stay for human review
        keys = [k for k, ts in unknown_keys.items() if any(not x.is_credit for x in ts)]
        for k, item in llm.categorise(keys).items():
            for t in unknown_keys.get(k, []):
                if t.is_credit:
                    continue
                t.category, t.category_source, t.confidence = item.category, "llm", item.confidence
                t.merchant = item.merchant or t.merchant
    for t in txns:
        if t.category == "unknown" or (t.category_source == "llm" and t.confidence < low_conf):
            t.flags.append("needs_review")


# ---------------------------------------------------------------- recurring
def detect_recurring(txns: list[Transaction]) -> None:
    groups = defaultdict(list)
    for t in txns:
        if t.amount_cents < 0:
            groups[merchant_key(t.description)].append(t)
    for ts in groups.values():
        months = {(t.date.year, t.date.month) for t in ts}
        if len(months) < 3:
            continue
        per_month = defaultdict(int)
        for t in ts:
            per_month[(t.date.year, t.date.month)] += 1
        # one charge a month (or a fixed monthly pair) with a steady amount => a debit order / subscription
        if max(per_month.values()) <= 2:
            amounts = [abs(t.amount_cents) for t in ts]
            if (max(amounts) - min(amounts)) / max(median(amounts), 1) <= 0.15:
                for t in ts:
                    t.recurring = True
