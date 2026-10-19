"""CSV parsers.

IMPORTANT: the column layouts below are SIMPLIFIED approximations of how these
banks export CSVs. Real exports differ by account type and change over time.
Compare against your own export and adjust the column maps - that is the point
of keeping one small class per bank.
"""
import csv
from pathlib import Path

from ..models import ParsedStatement, Transaction
from ..money import parse_amount, parse_date
from .base import StatementParser


def _read_rows(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    return list(csv.DictReader(text.splitlines()))


class CapitecCsvParser(StatementParser):
    """Columns: Transaction Date, Description, Money In, Money Out, Balance"""
    bank = "capitec"

    def can_parse(self, path, head):
        return path.suffix.lower() == ".csv" and "Money In" in head and "Money Out" in head

    def parse(self, path, password=None):
        txns, warnings = [], []
        for n, row in enumerate(_read_rows(path), start=2):
            try:
                money_in = (row.get("Money In") or "").strip()
                money_out = (row.get("Money Out") or "").strip()
                amount = abs(parse_amount(money_in)) if money_in else -abs(parse_amount(money_out))
                txns.append(Transaction(
                    date=parse_date(row["Transaction Date"]),
                    description=row["Description"].strip(),
                    amount_cents=amount,
                    balance_cents=parse_amount(row["Balance"]) if row.get("Balance") else None,
                    source=f"{path.name}:{n}",
                ))
            except (ValueError, KeyError) as e:
                warnings.append(f"row {n} skipped: {e}")
        return ParsedStatement(bank=self.bank, transactions=txns, source=path.name, warnings=warnings)


class FnbCsvParser(StatementParser):
    """Columns: Date, Description, Amount, Balance. Amount like '-250,00' or '18 500,00';
    Balance like '12 345,67Cr' or '320,10Dr'."""
    bank = "fnb"

    def can_parse(self, path, head):
        h = head.lower()
        return path.suffix.lower() == ".csv" and "amount" in h and "balance" in h and "money in" not in h

    def parse(self, path, password=None):
        txns, warnings = [], []
        for n, row in enumerate(_read_rows(path), start=2):
            try:
                txns.append(Transaction(
                    date=parse_date(row["Date"]),
                    description=row["Description"].strip(),
                    amount_cents=parse_amount(row["Amount"]),
                    balance_cents=parse_amount(row["Balance"]) if row.get("Balance") else None,
                    source=f"{path.name}:{n}",
                ))
            except (ValueError, KeyError) as e:
                warnings.append(f"row {n} skipped: {e}")
        return ParsedStatement(bank=self.bank, transactions=txns, source=path.name, warnings=warnings)
