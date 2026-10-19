import re

_PREFIXES = re.compile(
    r"^(POS PURCHASE|POS|DEBIT ORDER:?|ACB CREDIT|FNB APP PAYMENT TO|FNB APP PAYMENT|PREPAID|"
    r"PAYSHAP FROM|PAYSHAP TO|PAYSHAP PAYMENT|CAPITEC PAY:?|ATM CASH WITHDRAWAL|CASH WITHDRAWAL|"
    r"PURCHASE|EFT)\s+", re.I)


def merchant_key(description: str) -> str:
    """Stable key for 'the same merchant': strip prefixes, digits, reference noise, town names."""
    s = description.upper().strip()
    s = _PREFIXES.sub("", s)
    s = re.sub(r"\*?TRIP", "", s)
    s = re.sub(r"[\d#*]+", " ", s)
    s = re.sub(r"\b(SANDTON|SOWETO|PRETORIA|CAPE TOWN|DURBAN|JHB|JOHANNESBURG|ZA)\b", "", s)
    s = re.sub(r"[^A-Z& ]", " ", s)
    return re.sub(r"\s+", " ", s).strip() or description.upper()[:30]
