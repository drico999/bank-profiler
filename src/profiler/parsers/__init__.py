from pathlib import Path

from ..models import ParsedStatement
from .csv_parsers import CapitecCsvParser, FnbCsvParser
from .pdf_parser import PdfStatementParser

PARSERS = [CapitecCsvParser(), FnbCsvParser(), PdfStatementParser()]


def parse_file(path: str | Path, password: str | None = None) -> ParsedStatement:
    path = Path(path)
    head = ""
    if path.suffix.lower() == ".csv":
        head = path.read_text(encoding="utf-8-sig").splitlines()[0]
    for p in PARSERS:
        if p.can_parse(path, head):
            return p.parse(path, password)
    raise ValueError(f"No parser for {path.name}. Supported: Capitec CSV, FNB CSV, text-based PDF.")
