"""Synthetic South African statement generator.

Why: lets you build and TEST the pipeline without touching anyone's real data, and
gives you ground truth (true category per row, expected archetype) to measure
accuracy against. Formats are simplified approximations of Capitec/FNB exports.

Run:  python -m profiler.synthetic          (writes ./sample_data)
"""
import csv
import json
import random
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

START_YEAR, START_MONTH, MONTHS = 2026, 1, 6

MERCHANTS = {
    "groceries": ["SHOPRITE", "CHECKERS", "PICK N PAY", "WOOLWORTHS FOOD", "SPAR"],
    "fuel": ["ENGEN", "SHELL", "BP", "SASOL"],
    "dining": ["KFC", "NANDOS", "STEERS", "MUGG AND BEAN", "UBER EATS", "DEBONAIRS"],
    "shopping": ["TAKEALOT", "MR PRICE", "PEP", "CLICKS", "GAME"],
    "airtime_data": ["VODACOM", "MTN", "TELKOM"],
    "betting": ["HOLLYWOODBETS", "BETWAY", "SPORTINGBET"],
    "transport": ["UBER", "BOLT"],
}
# Informal merchants the rules do NOT know - these are what the LLM fallback is for.
INFORMAL = {
    "groceries": ["MAMA THANDI SPAZA", "BONGANI TUCKSHOP", "FRESH PRODUCE MARKET"],
    "dining": ["KASI GRILL", "AUNTY NOMSA FOOD"],
    "shopping": ["LERATO HAIR SALON", "SIPHO HARDWARE"],
}

PERSONAS = {
    "saver": dict(
        archetype="Saver", pay="salary", salary=32000, opening=3000, rent=8500, electricity=800,
        insurance=900, medical=2200, subs=[("NETFLIX", 199), ("SHOWMAX", 99)], groceries=4000,
        fuel=1800, airtime_data=300, dining=800, shopping=600, cash=500, savings=6000,
        fee_monthly=6.90),
    "balanced": dict(
        archetype="Balanced", pay="salary", salary=22000, opening=3000, rent=6500, electricity=700,
        insurance=600, subs=[("NETFLIX", 199), ("DSTV", 449)], groceries=4200, fuel=1800,
        airtime_data=350, dining=2200, shopping=2000, cash=900, savings=800, fee_monthly=6.90),
    "spender": dict(
        archetype="Spender", pay="salary", salary=18000, opening=300, rent=5000, electricity=600,
        insurance=400, subs=[("NETFLIX", 199), ("DSTV", 449), ("SHOWMAX", 99)], groceries=2800,
        fuel=1200, airtime_data=400, dining=2500, shopping=2200, betting=800, cash=1000,
        fee_monthly=6.90),
    "stretched": dict(
        archetype="Stretched", pay="salary", salary=14500, opening=-2500, rent=5500, electricity=700,
        insurance=500, loans=[("QUICKCASH LOANS", 1800), ("EASYLOAN CREDIT", 600)], groceries=2200,
        transport=800, airtime_data=350, dining=300, cash=600, family=500, fee_monthly=6.90,
        loan_proceeds_month=2),
    "volatile": dict(
        archetype="Volatile", pay="freelance", freelance=[9000, 24000, 12000, 28000, 8000, 21000],
        opening=6000, rent=5500, electricity=600, insurance=400, subs=[("NETFLIX", 199)],
        groceries=2800, fuel=1200, airtime_data=400, dining=1500, shopping=800, cash=400,
        fee_monthly=6.90),
}


@dataclass
class Event:
    day: date
    category: str
    merchant: str
    amount_cents: int      # signed
    kind: str              # key used by description templates
    order: int = 0


def _split(total_cents: int, n: int, rng: random.Random) -> list[int]:
    w = [rng.uniform(0.5, 1.5) for _ in range(n)]
    parts = [int(total_cents * x / sum(w)) for x in w]
    parts[-1] += total_cents - sum(parts)
    return parts


def _payday(y: int, m: int) -> date:
    d = date(y, m, 25)
    while d.weekday() >= 5:      # paid on the Friday before when 25th is a weekend
        d -= timedelta(days=1)
    return d


def _months():
    y, m = START_YEAR, START_MONTH
    for _ in range(MONTHS):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


def generate_events(name: str, seed: int = 7) -> list[Event]:
    spec, rng = PERSONAS[name], random.Random(f"{name}-{seed}")
    ev: list[Event] = []

    def add(d, cat, merchant, rand, kind):
        ev.append(Event(d, cat, merchant, int(round(rand * 100)), kind, len(ev)))

    for i, (y, m) in enumerate(_months()):
        last = monthrange(y, m)[1]
        D = lambda day: date(y, m, min(day, last))
        rnd_day = lambda: D(rng.randint(1, 28))

        # income
        if spec["pay"] == "salary":
            add(_payday(y, m), "salary", "ACME PTY LTD", spec["salary"], "salary")
        else:
            total = spec["freelance"][i]
            for part in _split(int(total * 100), rng.randint(2, 3), rng):
                add(rnd_day(), "other_income", rng.choice(["DESIGN CLIENT", "WEB PROJECT", "CONSULTING INV"]),
                    part / 100, "client_in")
        if spec.get("loan_proceeds_month") == i + 1:
            add(D(10), "loan_proceeds", "QUICKCASH LOANS", 3000, "loan_in")

        # committed
        add(D(1), "rent", "LANDLORD", -spec["rent"], "rent")
        if spec.get("medical"):
            add(D(1), "medical", "DISCOVERY HEALTH", -spec["medical"], "debit_order")
        if spec.get("insurance"):
            add(D(3), "insurance", "OLD MUTUAL FUNERAL COVER", -spec["insurance"], "debit_order")
        for k, amt in enumerate(_split(int(spec["electricity"] * 100), 2, rng)):
            add(D(5 + 14 * k), "utilities", "CITY POWER", -amt / 100, "electricity")
        for name_, amt in spec.get("loans", []):
            add(D(28), "debt_repayment", name_, -amt, "debit_order")
        for j, (name_, amt) in enumerate(spec.get("subs", [])):
            add(D(7 + 4 * j), "entertainment", name_, -amt, "debit_order")

        # variable spend
        def visits(cat, total, lo, hi, pool_key=None, informal_p=0.12):
            if not total:
                return
            n = rng.randint(lo, hi)
            for amt in _split(int(total * rng.uniform(0.9, 1.1) * 100), n, rng):
                pool = pool_key or cat
                if pool in INFORMAL and rng.random() < informal_p:
                    merch = rng.choice(INFORMAL[pool])
                else:
                    merch = rng.choice(MERCHANTS[pool])
                add(rnd_day(), cat, merch, -amt / 100, pool)

        visits("groceries", spec.get("groceries"), 6, 8)
        visits("transport", spec.get("fuel"), 3, 4, pool_key="fuel")
        visits("transport", spec.get("transport"), 6, 10, pool_key="transport")
        visits("airtime_data", spec.get("airtime_data"), 2, 3)
        visits("dining", spec.get("dining"), 4, 7)
        visits("shopping", spec.get("shopping"), 2, 4)
        visits("gambling", spec.get("betting"), 4, 8, pool_key="betting")

        if spec.get("cash"):
            n = rng.randint(2, 4)
            for amt in _split(int(spec["cash"] * rng.uniform(0.9, 1.1) * 100), n, rng):
                amt = max(5000, round(amt / 5000) * 5000)       # ATMs pay out in R50 notes
                d = rnd_day()
                add(d, "cash_withdrawal", "ATM", -amt / 100, "atm")
                add(d, "fees", "BANK", -12.00, "atm_fee")
        if spec.get("family"):
            add(D(26), "family_support", "MOM", -spec["family"], "family")

        # savings
        if spec.get("savings"):
            add(D(27), "savings", "SAVINGS POCKET", -spec["savings"], "savings")

        # fees
        add(D(1), "fees", "BANK", -spec["fee_monthly"], "fee_monthly")
        for _ in range(rng.randint(2, 5)):
            add(rnd_day(), "fees", "BANK", -0.35, "sms_fee")

    ev.sort(key=lambda e: (e.day, e.order))
    return ev


def with_balances(name: str, events: list[Event]):
    """Run the balance and add overdraft interest if a month ends overdrawn."""
    spec = PERSONAS[name]
    bal = int(spec["opening"] * 100)
    if spec["pay"] == "salary":
        # 'opening' means the balance on the first payday, so back-solve the true opening balance
        first_pay = _payday(START_YEAR, START_MONTH)
        bal -= sum(e.amount_cents for e in events if e.day < first_pay)
    rows, i = [], 0
    out_events: list[Event] = []
    by_month_end = {}
    for e in events:
        out_events.append(e)
        by_month_end[(e.day.year, e.day.month)] = e.day
    result = []
    running = bal
    last_key = None
    for e in out_events:
        key = (e.day.year, e.day.month)
        if last_key and key != last_key and running < 0:
            # interest charged on previous month's overdrawn closing balance, dated 1st of this month
            interest = max(100, int(-running * 0.0175))
            running -= interest
            result.append((Event(date(key[0], key[1], 1), "fees", "BANK", -interest, "od_interest"), running))
        running += e.amount_cents
        result.append((e, running))
        last_key = key
    return result


# ------------------------------------------------------------------ descriptions
def describe(e: Event, bank: str, rng: random.Random) -> str:
    m, k = e.merchant, e.kind
    ref = f"{rng.randint(100, 9999):04d}"
    town = rng.choice(["SANDTON", "SOWETO", "PRETORIA", "CAPE TOWN", "DURBAN", "JHB"])
    fnb = bank == "fnb"
    table = {
        "groceries": f"POS PURCHASE {m} {ref} {town}" if fnb else f"{m.title()} {town.title()}",
        "fuel": f"POS PURCHASE {m} {ref} {town}" if fnb else f"{m.title()} Fuel {town.title()}",
        "dining": f"POS PURCHASE {m} {ref}" if fnb else f"{m.title()}",
        "shopping": f"POS PURCHASE {m} {ref}" if fnb else f"{m.title()} Online",
        "transport": f"POS PURCHASE {m} *TRIP {ref}" if fnb else f"{m.title()} Trip",
        "airtime_data": f"PREPAID AIRTIME {m}" if fnb else f"Prepaid {m.title()} Airtime",
        "betting": f"POS PURCHASE {m} {ref}" if fnb else f"{m.title()} Deposit",
        "salary": f"ACB CREDIT {m} SALARY" if fnb else f"Salary {m.title()}",
        "client_in": f"PAYSHAP FROM {m} {ref}" if fnb else f"PayShap Payment {m.title()} {ref}",
        "loan_in": f"LOAN DISBURSEMENT {m}" if fnb else f"Loan Payout {m.title()}",
        "rent": "DEBIT ORDER RENT LANDLORD" if fnb else "Debit Order: Rent Payment",
        "debit_order": f"DEBIT ORDER {m}" if fnb else f"Debit Order: {m.title()}",
        "electricity": "PREPAID ELECTRICITY CITY POWER" if fnb else "City Power Prepaid Electricity",
        "atm": f"CASH WITHDRAWAL ATM {ref}" if fnb else f"ATM Cash Withdrawal {ref}",
        "atm_fee": "FEE CASH WITHDRAWAL" if fnb else "Cash Withdrawal Fee",
        "family": "FNB APP PAYMENT TO MOM" if fnb else "Capitec Pay: Mom",
        "savings": "TRANSFER TO SAVINGS POCKET" if fnb else "Transfer to Savings Pocket",
        "fee_monthly": "MONTHLY ACCOUNT FEE" if fnb else "Monthly Account Fee",
        "sms_fee": "SMS NOTIFICATION FEE" if fnb else "SMS Notification Fee",
        "od_interest": "OVERDRAFT INTEREST" if fnb else "Overdraft Interest",
    }
    return table[k]


def _fmt_fnb_amount(c: int) -> str:
    s = f"{abs(c) // 100:,}".replace(",", " ") + f",{abs(c) % 100:02d}"
    return f"-{s}" if c < 0 else s


def _fmt_fnb_balance(c: int) -> str:
    s = f"{abs(c) // 100:,}".replace(",", " ") + f",{abs(c) % 100:02d}"
    return s + ("Dr" if c < 0 else "Cr")


def write_capitec_csv(rows, path: Path, rng):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Transaction Date", "Description", "Money In", "Money Out", "Balance"])
        for e, bal in rows:
            amt = f"{abs(e.amount_cents) // 100}.{abs(e.amount_cents) % 100:02d}"
            w.writerow([e.day.isoformat(), describe(e, "capitec", rng),
                        amt if e.amount_cents > 0 else "", amt if e.amount_cents < 0 else "",
                        f"{bal // 100}.{abs(bal) % 100:02d}" if bal >= 0 else f"-{abs(bal) // 100}.{abs(bal) % 100:02d}"])


def write_fnb_csv(rows, path: Path, rng):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "Description", "Amount", "Balance"])
        for e, bal in rows:
            w.writerow([e.day.strftime("%d/%m/%Y"), describe(e, "fnb", rng),
                        _fmt_fnb_amount(e.amount_cents), _fmt_fnb_balance(bal)])


def write_fnb_pdf(rows, path: Path, rng, password: str | None = None):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib import pdfencrypt
    enc = pdfencrypt.StandardEncryption(password, canPrint=1) if password else None
    c = canvas.Canvas(str(path), pagesize=A4, encrypt=enc)
    W, H = A4

    def header():
        c.setFont("Courier-Bold", 9)
        c.drawString(40, H - 40, "FIRST NATIONAL BANK - SYNTHETIC SAMPLE STATEMENT (NOT REAL)")
        c.setFont("Courier", 8)
        c.drawString(40, H - 54, "Account: **** 0000 (fake)   Currency: ZAR")
        c.drawString(40, H - 74, "Date")
        c.drawString(120, H - 74, "Description")
        c.drawRightString(430, H - 74, "Amount")
        c.drawRightString(550, H - 74, "Balance")
        return H - 90

    y = header()
    c.setFont("Courier", 8)
    for e, bal in rows:
        if y < 50:
            c.showPage()
            y = header()
            c.setFont("Courier", 8)
        amt = f"{abs(e.amount_cents) // 100:,}.{abs(e.amount_cents) % 100:02d}" + ("Cr" if e.amount_cents > 0 else "")
        b = f"{abs(bal) // 100:,}.{abs(bal) % 100:02d}" + ("Cr" if bal >= 0 else "Dr")
        c.drawString(40, y, e.day.strftime("%d %b %Y"))
        c.drawString(120, y, describe(e, "fnb", rng)[:42])
        c.drawRightString(430, y, amt)
        c.drawRightString(550, y, b)
        y -= 12
    c.save()


def generate_all(out_dir: str | Path = "sample_data", seed: int = 7) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, spec in PERSONAS.items():
        rows = with_balances(name, generate_events(name, seed))
        truth = {"persona": name, "expected_archetype": spec["archetype"],
                 "categories": [e.category for e, _ in rows]}
        files = []
        for bank, writer, ext in (("capitec", write_capitec_csv, "csv"), ("fnb", write_fnb_csv, "csv")):
            p = out / f"{name}_{bank}.{ext}"
            writer(rows, p, random.Random(f"{name}-{bank}-{seed}"))
            files.append(p.name)
        if name in ("saver", "volatile"):
            p = out / f"{name}_fnb.pdf"
            write_fnb_pdf(rows, p, random.Random(f"{name}-fnb-{seed}"))
            files.append(p.name)
        (out / f"{name}.truth.json").write_text(json.dumps(truth))
        manifest[name] = files
    return manifest


if __name__ == "__main__":
    import sys
    print(json.dumps(generate_all(sys.argv[1] if len(sys.argv) > 1 else "sample_data"), indent=2))
