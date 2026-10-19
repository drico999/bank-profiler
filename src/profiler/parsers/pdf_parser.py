"""Text-based PDF parser (FNB-style layout).

Line format it understands:
  25 Jan 2026  SALARY ACME PTY LTD  18,500.00Cr  21,340.12Cr
Credits carry a 'Cr' suffix, debits have none, balance ends in Cr or Dr.
Limits (be honest about these): no OCR, no multi-line descriptions, one layout.
Direction is taken from the markers, then verified by balance reconciliation.
"""
import re
from pathlib import Path

from ..models import ParsedStatement, Transaction
from ..money import parse_amount, parse_date
from .base import StatementParser

LINE = re.compile(
    r"^(?P<date>\d{1,2} [A-Za-z]{3}(?: \d{4})?)\s+(?P<desc>.+?)\s+"
    r"(?P<amt>-?[\d,]+\.\d{2})\s?(?P<amtcr>Cr)?\s+(?P<bal>-?[\d,]+\.\d{2})\s?(?P<balcr>Cr|Dr)?$"
)


class PdfStatementParser(StatementParser):
    bank = "fnb"

    def can_parse(self, path, head):
        return path.suffix.lower() == ".pdf"

    def parse(self, path, password=None):
        import pdfplumber
        warnings, txns = [], []
        try:
            pdf = pdfplumber.open(str(path), password=password)
        except Exception as e:  # wrong/missing password, corrupt file
            raise ValueError(f"cannot open PDF (password protected?): {e}") from e
        with pdf:
            lines = []
            for page in pdf.pages:
                lines += (page.extract_text() or "").splitlines()
        if not any(LINE.match(l.strip()) for l in lines):
            warnings.append("no transaction lines recognised - this may be a scanned PDF or an unsupported layout")
        prev_date, year = None, 2000
        for n, line in enumerate(lines, start=1):
            m = LINE.match(line.strip())
            if not m:
                continue
            try:
                ds = m["date"]
                d = parse_date(ds, ref_year=year if len(ds.split()) == 2 else None)
                if prev_date and (prev_date - d).days > 180:   # yearless dates rolled over
                    d = d.replace(year=d.year + 1)
                prev_date = d
                amt = parse_amount(m["amt"])
                amt = abs(amt) if m["amtcr"] else -abs(amt)
                bal = parse_amount(m["bal"] + (m["balcr"] or "Cr"))
                txns.append(Transaction(date=d, description=m["desc"].strip(),
                                        amount_cents=amt, balance_cents=bal, source=f"{path.name}:line{n}"))
            except ValueError as e:
                warnings.append(f"line {n} skipped: {e}")
        return ParsedStatement(bank=self.bank, transactions=txns, source=path.name, warnings=warnings)
