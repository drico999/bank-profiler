"""Reconciliation: does opening balance + each transaction = the next running balance?

This is the main correctness check on parsing. A break means a row was misread,
missing, or has the wrong sign - so we flag it instead of trusting it.
"""
from .models import ReconciliationResult, Transaction


def reconcile(txns: list[Transaction]) -> ReconciliationResult:
    rows = [t for t in txns if t.balance_cents is not None]
    if len(rows) < 2:
        return ReconciliationResult(ok=False, checked=0, message="Not enough balance data to reconcile")
    opening = rows[0].balance_cents - rows[0].amount_cents
    breaks, prev = [], rows[0].balance_cents
    for t in rows[1:]:
        if prev + t.amount_cents != t.balance_cents:
            breaks.append(t.id)
            t.flags.append("reconciliation_break")
        prev = t.balance_cents
    ok = not breaks
    return ReconciliationResult(
        ok=ok, checked=len(rows) - 1, breaks=breaks,
        opening_balance_cents=opening, closing_balance_cents=rows[-1].balance_cents,
        message="Balances reconcile" if ok else f"{len(breaks)} row(s) break the running balance",
    )


def dedupe(txns: list[Transaction]) -> tuple[list[Transaction], int]:
    """Remove exact duplicates from overlapping statement periods (same date, text, amount, balance)."""
    seen, out, dropped = set(), [], 0
    for t in txns:
        key = (t.date, t.description, t.amount_cents, t.balance_cents)
        if key in seen:
            dropped += 1
            continue
        seen.add(key)
        out.append(t)
    return out, dropped
