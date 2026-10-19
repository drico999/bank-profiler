from pathlib import Path
from ..models import ParsedStatement


class StatementParser:
    """Subclass per bank/format. Add a new bank by implementing can_parse + parse."""
    bank = "unknown"

    def can_parse(self, path: Path, head: str) -> bool:
        raise NotImplementedError

    def parse(self, path: Path, password: str | None = None) -> ParsedStatement:
        raise NotImplementedError
