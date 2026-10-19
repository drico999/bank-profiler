"""Strip personal identifiers BEFORE any text leaves your machine (e.g. to an AI service).

Regex redaction is a safety net, not a guarantee. The real protection is sending as little as
possible: we never send statement headers (name, address, account number), only transaction lines.

Names are the hard part. Words after 'TO' / 'FROM' are masked as a probable person's name, EXCEPT
generic words the AI needs to see (savings, pocket, mom, dad, own account...).
"""
import re

_SAFE_FIRST_WORDS = {
    "SAVINGS", "SAVING", "POCKET", "TFSA", "OWN", "MOM", "DAD", "MOTHER", "FATHER", "SISTER", "BROTHER", "GRAN",
    "GRANDMA", "WIFE", "HUSBAND", "HOME", "ACCOUNT", "CASH", "ATM", "FNB", "CAPITEC", "RETIREMENT", "INVESTMENT",
}
_NAME_AFTER = re.compile(r"\b(TO|FROM)(\s+)([A-Za-z]+(?:\s[A-Za-z]+){0,2})", re.I)
_PATTERNS = [
    (re.compile(r"\b\d{13}\b"), "[ID]"),                                  # SA ID number
    (re.compile(r"\b(?:\+27|0)[6-8]\d[\s-]?\d{3}[\s-]?\d{4}\b"), "[PHONE]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[EMAIL]"),
    (re.compile(r"(?<![\d.,])\d{6,}(?!\d|[.,]\d)"), "[NUM]"),             # account/card numbers, not amounts like 100000.00
]


def _mask_name(m: re.Match) -> str:
    first = m.group(3).split()[0].upper()
    return m.group(0) if first in _SAFE_FIRST_WORDS else f"{m.group(1)}{m.group(2)}[NAME]"


def redact(text: str) -> str:
    for rx, repl in _PATTERNS:
        text = rx.sub(repl, text)
    return _NAME_AFTER.sub(_mask_name, text)
