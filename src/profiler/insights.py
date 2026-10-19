"""Plain-language insights for non-specialists. Pure functions over Metrics - no LLM, fully testable.

Every insight has a level (good / ok / watch / alert), a big headline number phrased as
'R34 of every R100', and one sentence of explanation. The UI always pairs colour with an
icon and a word, so colour is never the only signal.
"""
from dataclasses import dataclass

from .archetypes import Verdict
from .config import ESSENTIAL_VARIABLE, THRESHOLDS
from .metrics import Metrics
from .money import format_rand

LEVEL_WORD = {"good": "Good", "ok": "Fair", "watch": "Keep an eye on", "alert": "Concern"}
LEVEL_ICON = {"good": "✔", "ok": "●", "watch": "▲", "alert": "✖"}

STATUS = {   # archetype -> (short status, level, one plain sentence)
    "Saver": ("Doing well", "good", "Keeps money aside every month."),
    "Balanced": ("Steady", "ok", "Pays their way and saves a little."),
    "Spender": ("Needs attention", "watch", "Spends almost everything they earn."),
    "Stretched": ("Under pressure", "alert", "Bills and debt take most of the pay."),
    "Volatile": ("Up and down", "watch", "Income changes a lot from month to month."),
    "Insufficient data": ("Not enough data", "ok", "We could not find enough income to judge."),
}


@dataclass
class Insight:
    key: str
    level: str
    title: str
    headline: str
    detail: str

    @property
    def is_positive(self) -> bool:
        return self.level in ("good", "ok")


def _per100(x: float) -> int:
    return int(round(x * 100))


def _of_100(x: float, basis: str = "earned") -> str:
    v = _per100(x)
    return f"Less than R1 of every R100 {basis}" if 0 < x and v < 1 else f"R{v} of every R100 {basis}"


def build_insights(m: Metrics) -> list[Insight]:
    out: list[Insight] = []
    if m.savings_rate is None:
        return out
    n = max(m.n_cycles, 1)

    # --- savings
    sr = m.savings_rate
    if sr >= 0.15:
        lvl, d = "good", "is kept after all spending. A healthy habit."
    elif sr >= 0.05:
        lvl, d = "ok", "is kept after all spending. Some room to grow."
    elif sr >= 0:
        lvl, d = "watch", "is kept after all spending. Almost nothing is being put aside."
    else:
        lvl, d = "alert", ""
    if sr >= 0:
        out.append(Insight("savings", lvl, "Money kept", f"R{_per100(sr)} of every R100 earned", d))
    else:
        out.append(Insight("savings", "alert", "Money kept", f"R{100 + _per100(-sr)} spent for every R100 earned",
                           "More goes out than comes in, so savings or borrowing is being used."))

    # --- safety net
    weeks = m.buffer_months * 52 / 12
    lvl = "good" if m.buffer_months >= 2 else "ok" if m.buffer_months >= 1 else "watch" if m.buffer_months >= 0.5 else "alert"
    out.append(Insight("buffer", lvl, "Safety net", f"About {weeks:.0f} weeks" if weeks >= 2 else f"About {weeks:.1f} weeks",
                       "of spending could be covered from cash and savings if the pay stopped."))

    # --- payday squeeze
    share = m.month_end_low_share
    lvl = "good" if m.month_end_low_cycles == 0 else "ok" if share <= 0.34 else "watch" if share <= 0.6 else "alert"
    out.append(Insight("squeeze", lvl, "Running low before payday", f"{m.month_end_low_cycles} of {m.n_cycles} months",
                       "ended with a very low balance, under a tenth of a month's pay, just before payday."))

    # --- fixed bills
    c = m.committed_ratio
    alert_at = THRESHOLDS.stretched_committed_ratio      # same line the Stretched rule uses
    lvl = "good" if c < 0.40 else "ok" if c < 0.50 else "watch" if c < alert_at else "alert"
    out.append(Insight("fixed", lvl, "Fixed bills", _of_100(c),
                       "is already spoken for by rent, electricity, insurance, medical aid and loan repayments."))

    # --- loans
    d = m.debt_ratio
    if d == 0:
        out.append(Insight("debt", "good", "Loan repayments", "None seen", "No loan or credit repayments were found."))
    else:
        lvl = "ok" if d < 0.10 else "watch" if d < THRESHOLDS.stretched_debt_ratio else "alert"
        out.append(Insight("debt", lvl, "Loan repayments", _of_100(d), "goes to paying back loans and credit."))

    # --- betting
    if m.gambling_ratio > 0:
        g = m.gambling_ratio
        out.append(Insight("betting", "alert" if g >= 0.05 else "watch", "Betting and lotto", _of_100(g),
                           f"went on betting and lotto ({format_rand(m.category_totals.get('gambling', 0))} in total)."))

    # --- fees
    f = m.fee_ratio
    lvl = "good" if f < 0.01 else "ok" if f < 0.025 else "watch" if f < 0.05 else "alert"
    out.append(Insight("fees", lvl, "Bank fees", f"{format_rand(m.category_totals.get('fees', 0) / n)} a month",
                       "is paid in account fees, SMS fees and charges. A cheaper account may save some of it."))

    # --- steady pay
    cv = m.income_cv
    if cv < 0.10:
        lvl, head = "good", "Very steady"
    elif cv < 0.30:
        lvl, head = "ok", "Mostly steady"
    elif cv < 0.50:
        lvl, head = "watch", "Up and down"
    else:
        lvl, head = "alert", "Very uneven"
    out.append(Insight("income", lvl, "How steady the pay is", head, f"Money coming in changed by about {cv:.0%} from month to month."))

    # --- cash
    cs = m.cash_share
    if cs >= 0.15:
        out.append(Insight("cash", "watch", "Cash taken out", _of_100(cs, "spent"),
                           "was taken out as cash. We cannot see what cash was spent on, so this picture is less certain."))

    # --- recurring
    if m.recurring_per_cycle > 0:
        out.append(Insight("recurring", "ok", "Debit orders and subscriptions", f"{format_rand(m.recurring_per_cycle)} a month",
                           "goes out automatically. Worth checking that nothing has been forgotten."))
    return out


GROUPS = [   # key, label, helper text, categories
    ("fixed", "Fixed bills", "rent, electricity, insurance, medical aid", {"rent", "utilities", "insurance", "medical"}),
    ("loans", "Loan repayments", "loans and credit", {"debt_repayment"}),
    ("essentials", "Food, transport and airtime", "groceries, fuel, taxis, airtime", ESSENTIAL_VARIABLE),
    ("fun", "Eating out, shopping and fun", "takeaways, clothes, streaming", {"dining", "entertainment", "shopping"}),
    ("betting", "Betting and lotto", "", {"gambling"}),
    ("family", "Family support", "money sent to family", {"family_support"}),
    ("cash", "Cash taken out", "ATM and cash send", {"cash_withdrawal"}),
    ("fees", "Bank fees", "account, SMS and ATM fees", {"fees"}),
    ("other", "Other", "could not be sorted", {"other", "unknown"}),
]


def spend_groups(m: Metrics) -> dict:
    """Where each rand of income goes, as per-cycle averages. 'left' may be negative (overspent)."""
    n = max(m.n_cycles, 1)
    rows = []
    for key, label, helper, cats in GROUPS:
        cents = sum(v for k, v in m.category_totals.items() if k in cats)
        if cents > 0:
            rows.append({"key": key, "label": label, "helper": helper, "cents": cents / n})
    income = m.avg_income
    spent = sum(r["cents"] for r in rows)
    return {"rows": rows, "income": income, "spent": spent, "left": income - spent}
