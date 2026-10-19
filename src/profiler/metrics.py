"""Deterministic metrics. No LLM anywhere in this file: same input => same numbers."""
from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean, median, pstdev

from pydantic import BaseModel, Field

from .config import (COMMITTED, DISCRETIONARY, ESSENTIAL_VARIABLE, INCOME_CATEGORIES, NOT_SPEND,
                     THRESHOLDS, Thresholds)
from .models import Transaction


class Cycle(BaseModel):
    label: str
    start: date
    end: date
    complete: bool = True
    income_cents: int = 0
    spend_cents: int = 0
    saved_cents: int = 0
    closing_balance_cents: int | None = None
    avg_balance_cents: int | None = None
    avg_cushion_cents: int | None = None   # avg balance + cumulative money moved into savings

    @property
    def spend_share(self) -> float | None:
        return self.spend_cents / self.income_cents if self.income_cents else None


class Metrics(BaseModel):
    method: str = "none"                  # pay_cycle | calendar_month | whole_statement
    payday_note: str = ""
    n_cycles: int = 0
    income_total: int = 0
    spend_total: int = 0
    saved_total: int = 0
    avg_income: float = 0
    avg_spend: float = 0
    savings_rate: float | None = None
    overspent_cycles: int = 0
    committed_ratio: float = 0
    essential_ratio: float = 0
    discretionary_ratio: float = 0
    debt_ratio: float = 0
    fee_ratio: float = 0
    gambling_ratio: float = 0
    income_cv: float = 0
    buffer_months: float = 0
    month_end_low_cycles: int = 0
    month_end_low_share: float = 0
    cash_share: float = 0
    unknown_share: float = 0
    unclassified_credits_cents: int = 0
    recurring_per_cycle: float = 0
    category_totals: dict[str, int] = Field(default_factory=dict)


def daily_balances(txns: list[Transaction]) -> dict[date, int]:
    rows = [t for t in txns if t.balance_cents is not None]
    if not rows:
        return {}
    by_day = {}
    for t in rows:
        by_day[t.date] = t.balance_cents          # last balance of the day wins (txns are date-ordered)
    out, d, cur = {}, rows[0].date, rows[0].balance_cents - rows[0].amount_cents
    while d <= rows[-1].date:
        cur = by_day.get(d, cur)
        out[d] = cur
        d += timedelta(days=1)
    return out


def _pay_cycles(txns, first, last):
    """Payday-to-payday cycles from salary credits. Returns (cycles, note) or None."""
    firsts = {}
    for t in txns:
        if t.category == "salary" and t.amount_cents > 0:
            firsts.setdefault((t.date.year, t.date.month), t.date)
    paydays = sorted(firsts.values())
    if len(paydays) < 3:
        return None
    cycles = []
    for i, p in enumerate(paydays):
        if i < len(paydays) - 1:
            end, complete = paydays[i + 1] - timedelta(days=1), True
        else:
            end = last
            typical = median([(paydays[j + 1] - paydays[j]).days for j in range(len(paydays) - 1)])
            complete = (last - p).days + 1 >= typical - 3
        cycles.append(Cycle(label=f"{p:%d %b}", start=p, end=end, complete=complete))
    days = [p.day for p in paydays]
    note = f"Salary usually lands around the {int(median(days))}th (paid {len(paydays)} times)"
    return cycles, note


def _calendar_cycles(first, last):
    cycles, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        s, e = date(y, m, 1), date(y, m, monthrange(y, m)[1])
        complete = first <= s + timedelta(days=3) and last >= e - timedelta(days=3)
        cycles.append(Cycle(label=f"{s:%b %Y}", start=s, end=e, complete=complete))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return cycles


def compute_metrics(txns: list[Transaction], th: Thresholds = THRESHOLDS) -> tuple[Metrics, list[Cycle]]:
    txns = sorted(txns, key=lambda t: (t.date, t.id))
    if not txns:
        return Metrics(), []
    first, last = txns[0].date, txns[-1].date
    pc = _pay_cycles(txns, first, last)
    if pc:
        cycles, note = pc
        method = "pay_cycle"
    else:
        cycles, note, method = _calendar_cycles(first, last), "No regular salary found - using calendar months", "calendar_month"
    used = [c for c in cycles if c.complete]
    if not used:
        used = [Cycle(label="Whole statement", start=first, end=last)]
        method, note = "whole_statement", "Statement too short for full cycles - using everything provided"
    bals = daily_balances(txns)

    cat_totals: dict[str, int] = defaultdict(int)
    recurring_total = 0
    unclassified_credits = 0
    cum_saved = 0
    for c in used:
        inside = [t for t in txns if c.start <= t.date <= c.end]
        for t in inside:
            cat = t.category
            if t.amount_cents > 0:
                if cat in INCOME_CATEGORIES:
                    c.income_cents += t.amount_cents
                elif cat == "refund":
                    c.spend_cents -= t.amount_cents
                elif cat == "unknown":
                    unclassified_credits += t.amount_cents
            else:
                amt = -t.amount_cents
                if cat in NOT_SPEND:
                    c.saved_cents += amt if cat == "savings" else 0
                else:
                    c.spend_cents += amt
                    cat_totals[cat] += amt
                    if t.recurring:
                        recurring_total += amt
        days = [bals[d] for d in (c.start + timedelta(days=i) for i in range((c.end - c.start).days + 1)) if d in bals]
        cum_saved += c.saved_cents
        if days:
            c.closing_balance_cents, c.avg_balance_cents = days[-1], int(mean(days))
            c.avg_cushion_cents = c.avg_balance_cents + cum_saved

    n = len(used)
    income, spend = sum(c.income_cents for c in used), sum(c.spend_cents for c in used)
    m = Metrics(method=method, payday_note=note, n_cycles=n, income_total=income, spend_total=spend,
                saved_total=sum(c.saved_cents for c in used), category_totals=dict(cat_totals),
                unclassified_credits_cents=unclassified_credits)
    m.avg_income, m.avg_spend = income / n, spend / n
    if income <= 0:
        return m, cycles
    m.savings_rate = (income - spend) / income
    m.overspent_cycles = sum(1 for c in used if c.income_cents and c.spend_cents >= th.overspend_share * c.income_cents)
    grp = lambda cats: sum(v for k, v in cat_totals.items() if k in cats)
    m.committed_ratio = grp(COMMITTED) / income
    m.essential_ratio = grp(ESSENTIAL_VARIABLE) / income
    m.discretionary_ratio = grp(DISCRETIONARY) / income
    m.debt_ratio = cat_totals.get("debt_repayment", 0) / income
    m.fee_ratio = cat_totals.get("fees", 0) / income
    m.gambling_ratio = cat_totals.get("gambling", 0) / income
    incomes = [c.income_cents for c in used]
    m.income_cv = pstdev(incomes) / mean(incomes) if n > 1 and mean(incomes) else 0
    avgs = [c.avg_cushion_cents for c in used if c.avg_cushion_cents is not None]
    if avgs and m.avg_spend:
        m.buffer_months = max(0, mean(avgs)) / m.avg_spend
    low = 0
    for c in used:
        if c.closing_balance_cents is not None and c.income_cents:
            if c.closing_balance_cents < th.near_zero_share_of_income * c.income_cents:
                low += 1
    m.month_end_low_cycles, m.month_end_low_share = low, low / n
    if spend:
        m.cash_share = cat_totals.get("cash_withdrawal", 0) / spend
        m.unknown_share = cat_totals.get("unknown", 0) / spend
    m.recurring_per_cycle = recurring_total / n
    return m, cycles
