"""All tunable numbers live here so thresholds are easy to change and explain.

Thresholds are starting points for South African retail clients, NOT validated
against real data. Tune them with your own test statements.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Thresholds:
    # Archetype rules (see archetypes.py for the order they are applied)
    volatile_income_cv: float = 0.30        # coefficient of variation of per-cycle income
    saver_savings_rate: float = 0.15
    saver_min_buffer_months: float = 1.0
    saver_max_month_end_low_share: float = 0.34
    balanced_savings_rate: float = 0.05
    stretched_committed_ratio: float = 0.55  # rent+insurance+medical+debt+utilities / income
    stretched_debt_ratio: float = 0.25

    # Month-end "near zero": closing balance below this share of income
    near_zero_share_of_income: float = 0.10
    overspend_share: float = 0.95            # a cycle is "overspent" if spend >= 95% of income

    # Resilience score weights (sum to 100)
    w_savings: int = 35
    w_buffer: int = 25
    w_month_end: int = 20
    w_debt: int = 10
    w_fees_gambling: int = 10

    # Confidence penalties
    pen_few_cycles: float = 0.25             # fewer than 3 complete cycles
    pen_very_few_cycles: float = 0.20        # fewer than 2 (added on top)
    pen_calendar_fallback: float = 0.10
    pen_high_cash: float = 0.15              # cash > 25% of spend
    pen_unknown: float = 0.10                # uncategorised > 15% of spend
    pen_reconciliation: float = 0.30


THRESHOLDS = Thresholds()

# Category groups used by the metrics
INCOME_CATEGORIES = {"salary", "grant_income", "family_in", "other_income"}
NON_INCOME_CREDITS = {"loan_proceeds", "transfer_in", "refund"}
COMMITTED = {"rent", "insurance", "medical", "debt_repayment", "utilities"}
ESSENTIAL_VARIABLE = {"groceries", "transport", "airtime_data"}
DISCRETIONARY = {"dining", "entertainment", "shopping", "gambling"}
OTHER_SPEND = {"family_support", "cash_withdrawal", "fees", "other", "unknown"}
NOT_SPEND = {"savings", "transfer_out"}      # money moved, not consumed

ALL_CATEGORIES = sorted(
    INCOME_CATEGORIES | NON_INCOME_CREDITS | COMMITTED | ESSENTIAL_VARIABLE
    | DISCRETIONARY | OTHER_SPEND | NOT_SPEND
)
