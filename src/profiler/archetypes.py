"""Archetype rules, score, confidence and evidence. Pure functions - fully explainable."""
from pydantic import BaseModel, Field

from .config import THRESHOLDS, Thresholds
from .metrics import Cycle, Metrics
from .models import ReconciliationResult, Transaction
from .money import format_rand

DESCRIPTIONS = {
    "Saver": "Consistently keeps a healthy share of income and holds a cash cushion.",
    "Balanced": "Lives within their means and puts some money aside, with a modest cushion.",
    "Spender": "Spends close to everything that comes in, mostly on non-essential items, with little set aside.",
    "Stretched": "Fixed costs and debt take most of the income, leaving little room to save.",
    "Volatile": "Income swings enough from one period to the next that spending and saving are hard to predict.",
    "Insufficient data": "Not enough income was found in the statements to profile this client.",
}


class Evidence(BaseModel):
    text: str
    metric: str
    txn_ids: list[int] = Field(default_factory=list)
    tone: str = "neutral"          # positive | negative | neutral | warning


class Verdict(BaseModel):
    archetype: str
    rule: str
    score: int
    confidence: float
    confidence_label: str
    confidence_reasons: list[str]
    evidence: list[Evidence]


def classify(m: Metrics, th: Thresholds = THRESHOLDS) -> tuple[str, str]:
    pct = lambda x: f"{x:.0%}"
    if m.income_total <= 0 or m.savings_rate is None:
        return "Insufficient data", "No income found in complete pay cycles"
    if m.n_cycles >= 3 and m.income_cv >= th.volatile_income_cv:
        return "Volatile", f"Income varied by {pct(m.income_cv)} between periods (limit {pct(th.volatile_income_cv)})"
    if m.savings_rate >= th.saver_savings_rate and m.buffer_months >= th.saver_min_buffer_months \
            and m.month_end_low_share <= th.saver_max_month_end_low_share:
        return "Saver", (f"Savings rate {pct(m.savings_rate)} >= {pct(th.saver_savings_rate)}, "
                         f"buffer {m.buffer_months:.1f} months >= {th.saver_min_buffer_months}")
    if m.savings_rate >= th.balanced_savings_rate:
        return "Balanced", f"Savings rate {pct(m.savings_rate)} is at least {pct(th.balanced_savings_rate)} but below Saver criteria"
    if m.committed_ratio >= th.stretched_committed_ratio or m.debt_ratio >= th.stretched_debt_ratio:
        return "Stretched", (f"Savings rate {pct(m.savings_rate)} and fixed commitments take {pct(m.committed_ratio)} "
                             f"of income (debt {pct(m.debt_ratio)})")
    return "Spender", f"Savings rate {pct(m.savings_rate)} below {pct(th.balanced_savings_rate)} with low fixed commitments"


def resilience_score(m: Metrics, th: Thresholds = THRESHOLDS) -> int:
    """0-100 financial resilience. Weights live in config so the maths is inspectable."""
    if m.savings_rate is None:
        return 0
    clamp = lambda x: max(0.0, min(1.0, x))
    s = (clamp(m.savings_rate / 0.20) * th.w_savings
         + clamp(m.buffer_months / 3) * th.w_buffer
         + (1 - clamp(m.month_end_low_share)) * th.w_month_end
         + (1 - clamp(m.debt_ratio / 0.40)) * th.w_debt
         + (1 - clamp((m.fee_ratio + m.gambling_ratio) / 0.10)) * th.w_fees_gambling)
    return round(s)


def confidence(m: Metrics, recon: ReconciliationResult, th: Thresholds = THRESHOLDS) -> tuple[float, str, list[str]]:
    c, why = 1.0, []
    if m.n_cycles < 3:
        c -= th.pen_few_cycles
        why.append(f"Only {m.n_cycles} complete pay cycle(s) - more history would firm this up")
    if m.n_cycles < 2:
        c -= th.pen_very_few_cycles
    if m.method != "pay_cycle":
        c -= th.pen_calendar_fallback
        why.append("Regular salary not detected, so calendar months were used")
    if m.cash_share > 0.25:
        c -= th.pen_high_cash
        why.append(f"{m.cash_share:.0%} of spending is cash, which can't be traced to what it was spent on")
    if m.unknown_share > 0.15:
        c -= th.pen_unknown
        why.append(f"{m.unknown_share:.0%} of spending is uncategorised")
    if not recon.ok:
        c -= th.pen_reconciliation
        why.append(recon.message or "Statement balances did not reconcile - some rows may be misread")
    c = max(0.1, min(1.0, c))
    label = "High" if c >= 0.8 else "Medium" if c >= 0.55 else "Low"
    return round(c, 2), label, why


def _top_ids(txns: list[Transaction], cats: set[str], k: int = 8, credits=False) -> list[int]:
    pick = [t for t in txns if t.category in cats and (t.amount_cents > 0) == credits]
    pick.sort(key=lambda t: abs(t.amount_cents), reverse=True)
    return [t.id for t in pick[:k]]


def build_evidence(m: Metrics, cycles: list[Cycle], txns: list[Transaction], th: Thresholds = THRESHOLDS) -> list[Evidence]:
    from .config import COMMITTED, INCOME_CATEGORIES
    ev: list[Evidence] = []
    R = format_rand
    if m.savings_rate is None:
        return ev
    ev.append(Evidence(
        text=f"Spent {R(m.spend_total)} of {R(m.income_total)} income over {m.n_cycles} cycle(s): a {m.savings_rate:.0%} savings rate.",
        metric="savings_rate", txn_ids=_top_ids(txns, INCOME_CATEGORIES, credits=True, k=6),
        tone="positive" if m.savings_rate >= th.saver_savings_rate else "negative" if m.savings_rate < th.balanced_savings_rate else "neutral"))
    ev.append(Evidence(
        text=f"Spent {th.overspend_share:.0%} or more of income in {m.overspent_cycles} of {m.n_cycles} cycles.",
        metric="overspent_cycles", tone="negative" if m.overspent_cycles >= m.n_cycles / 2 else "positive"))
    ev.append(Evidence(
        text=f"Cash on hand plus money moved into savings covers about {m.buffer_months:.1f} months of spending.",
        metric="buffer_months", tone="positive" if m.buffer_months >= th.saver_min_buffer_months else "negative"))
    ev.append(Evidence(
        text=f"Balance dropped below {th.near_zero_share_of_income:.0%} of income before payday in {m.month_end_low_cycles} of {m.n_cycles} cycles.",
        metric="month_end_low", tone="negative" if m.month_end_low_share > th.saver_max_month_end_low_share else "positive"))
    ev.append(Evidence(
        text=f"Fixed commitments (rent, utilities, insurance, medical, debt) take {m.committed_ratio:.0%} of income.",
        metric="committed_ratio", txn_ids=_top_ids(txns, COMMITTED), tone="warning" if m.committed_ratio >= th.stretched_committed_ratio else "neutral"))
    if m.debt_ratio >= 0.10:
        ev.append(Evidence(text=f"Debt repayments take {m.debt_ratio:.0%} of income.", metric="debt_ratio",
                           txn_ids=_top_ids(txns, {"debt_repayment"}), tone="warning"))
    if m.gambling_ratio > 0:
        ev.append(Evidence(text=f"Betting and gambling totalled {R(m.category_totals.get('gambling', 0))} ({m.gambling_ratio:.0%} of income).",
                           metric="gambling_ratio", txn_ids=_top_ids(txns, {"gambling"}), tone="warning" if m.gambling_ratio >= 0.03 else "neutral"))
    if m.fee_ratio >= 0.01:
        ev.append(Evidence(text=f"Bank fees and charges cost {R(m.category_totals.get('fees', 0))} ({m.fee_ratio:.1%} of income).",
                           metric="fee_ratio", txn_ids=_top_ids(txns, {"fees"}), tone="warning" if m.fee_ratio >= 0.03 else "neutral"))
    ev.append(Evidence(text=f"Income changed by about {m.income_cv:.0%} between periods.", metric="income_cv",
                       tone="warning" if m.income_cv >= th.volatile_income_cv else "positive"))
    if m.cash_share > 0.15:
        ev.append(Evidence(text=f"{m.cash_share:.0%} of spending was cash withdrawals, so part of the picture is untraceable.",
                           metric="cash_share", txn_ids=_top_ids(txns, {"cash_withdrawal"}), tone="warning"))
    if m.unclassified_credits_cents:
        ev.append(Evidence(text=f"{R(m.unclassified_credits_cents)} of deposits could not be classified and were not counted as income.",
                           metric="unclassified_credits", tone="warning"))
    if m.recurring_per_cycle:
        ev.append(Evidence(text=f"About {R(m.recurring_per_cycle)} per cycle goes to recurring debit orders and subscriptions.",
                           metric="recurring", tone="neutral"))
    return ev
