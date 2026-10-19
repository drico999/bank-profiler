"""Code that checks the AI's work. The AI may phrase things; it may not invent numbers."""
import json
import re

_NUM = re.compile(r"\d+(?:\.\d+)?")
_GROUPING = re.compile(r"(?<=\d)[ ,](?=\d{3}(?!\d))")      # 'R12 345' and 'R12,345' -> 12345


def numbers_in_text(text: str) -> list[float]:
    return [float(x) for x in _NUM.findall(_GROUPING.sub("", str(text)))]


def allowed_numbers(*blobs) -> list[float]:
    out: list[float] = []
    for b in blobs:
        out += numbers_in_text(b if isinstance(b, str) else json.dumps(b))
    return out


def unsupported_numbers(text: str, allowed: list[float], tol: float = 0.02) -> list[float]:
    """Numbers in `text` that are not backed by `allowed`.

    Rules: whole numbers up to 12 are always fine (counts of months, etc). Numbers under 100 must
    match a known figure to within rounding; larger ones may differ by up to 2%.
    """
    bad = []
    for n in numbers_in_text(text):
        if n == int(n) and n <= 12:
            continue
        if n < 100:
            ok = any(abs(n - a) <= 0.51 for a in allowed)
        else:
            ok = any(abs(n - a) <= max(1.0, tol * abs(a)) for a in allowed)
        if not ok:
            bad.append(n)
    return bad
