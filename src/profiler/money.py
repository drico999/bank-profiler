"""Rand handling. Amounts are ALWAYS integer cents; never floats."""
import re
from datetime import date, datetime

_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def parse_amount(raw: str) -> int:
    """Parse South African style amounts into signed integer cents.

    Handles: '1 234,56'  '1,234.56'  'R1 234.56'  '-250,00'  '250.00Dr'  '250.00 Cr'  '(250.00)'
    Sign rules: leading '-', trailing 'Dr' or brackets => negative. 'Cr' => positive.
    """
    if raw is None:
        raise ValueError("empty amount")
    s = str(raw).strip().replace("\u00a0", " ")
    if not s:
        raise ValueError("empty amount")
    negative = False
    low = s.lower()
    if low.endswith("dr"):
        negative, s = True, s[:-2]
    elif low.endswith("cr"):
        s = s[:-2]
    s = s.strip()
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    s = s.replace("R", "").replace("r", "").strip()
    if s.startswith("-"):
        negative, s = True, s[1:]
    elif s.startswith("+"):
        s = s[1:]
    s = s.replace(" ", "")
    m = re.fullmatch(r"(\d[\d.,]*?)(?:[.,](\d{1,2}))?", s)
    if not m:
        raise ValueError(f"cannot parse amount: {raw!r}")
    whole = re.sub(r"[.,]", "", m.group(1))
    frac = (m.group(2) or "0").ljust(2, "0")
    cents = int(whole) * 100 + int(frac)
    return -cents if negative else cents


def format_rand(cents: int, decimals: bool = False) -> str:
    """Format cents as 'R12 345' (SA style thousands separator)."""
    neg = cents < 0
    cents = abs(int(round(cents)))
    rands, c = divmod(cents, 100)
    body = f"{rands:,}".replace(",", " ")
    if decimals:
        body += f".{c:02d}"
    return f"-R{body}" if neg else f"R{body}"


def parse_date(raw: str, ref_year: int | None = None) -> date:
    """Parse DD/MM/YYYY, YYYY-MM-DD, YYYY/MM/DD, 'DD Mon YYYY', and 'DD Mon' (needs ref_year)."""
    s = str(raw).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%Y/%m/%d", "%d %b %Y", "%d-%m-%Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*", s)
    if m and ref_year and m.group(2).lower() in _MONTHS:
        return date(ref_year, _MONTHS.index(m.group(2).lower()) + 1, int(m.group(1)))
    raise ValueError(f"cannot parse date: {raw!r}")
