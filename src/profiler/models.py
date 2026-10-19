from datetime import date
from pydantic import BaseModel, Field


class Transaction(BaseModel):
    id: int = 0
    date: date
    description: str
    amount_cents: int                      # credits positive, debits negative
    balance_cents: int | None = None
    merchant: str | None = None
    category: str = "unknown"
    category_source: str = "none"          # rule | correction | llm | none
    confidence: float = 0.0
    recurring: bool = False
    flags: list[str] = Field(default_factory=list)
    source: str = ""

    @property
    def is_credit(self) -> bool:
        return self.amount_cents > 0


class ParsedStatement(BaseModel):
    bank: str
    transactions: list[Transaction]
    source: str = ""
    warnings: list[str] = Field(default_factory=list)


class ReconciliationResult(BaseModel):
    ok: bool
    checked: int
    breaks: list[int] = Field(default_factory=list)   # transaction ids where running balance disagrees
    opening_balance_cents: int | None = None
    closing_balance_cents: int | None = None
    message: str = ""
