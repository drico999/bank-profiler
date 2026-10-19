"""Optional LLM fallback for merchants the rules don't recognise.

Design rules (this is the 'LLM extracts, code does the maths' principle):
  * only the redacted, normalised merchant KEY is sent - never whole statement lines, never amounts
  * answers must be JSON and are validated; invalid categories become 'unknown'
  * results are cached on disk so each merchant is paid for once
  * low-confidence answers are kept but flagged for human review
Works with any object exposing  client.messages.create(...)  (the Anthropic SDK shape),
so tests can inject a fake client and you can swap providers.
"""
import json
import os
import re
from pathlib import Path

from pydantic import BaseModel, ValidationError, field_validator

from ..config import ALL_CATEGORIES
from ..redact import redact

DEFAULT_MODEL = os.environ.get("BANKPROFILER_MODEL", "claude-sonnet-5-5")
SYSTEM = (
    "You categorise South African bank transaction merchants. "
    f"Allowed categories: {', '.join(ALL_CATEGORIES)}. "
    "Informal local businesses are common (spaza shops, tuckshops, hair salons, kasi food). "
    "Reply with ONLY a JSON array, no prose, no markdown. Each item: "
    '{"key": <input key unchanged>, "merchant": <clean name or null>, "category": <allowed category>, "confidence": <0..1>}. '
    "If you cannot tell, use category 'unknown' and a low confidence. Never guess a person's relationship."
)


class LLMItem(BaseModel):
    key: str
    merchant: str | None = None
    category: str = "unknown"
    confidence: float = 0.0

    @field_validator("category")
    @classmethod
    def _valid(cls, v):
        return v if v in ALL_CATEGORIES else "unknown"

    @field_validator("confidence")
    @classmethod
    def _clamp(cls, v):
        return max(0.0, min(1.0, float(v)))


def default_client():
    """Anthropic client if a key is configured, else None (pipeline then skips the LLM)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
        return anthropic.Anthropic()
    except ImportError:
        return None


class LLMCategoriser:
    def __init__(self, client=None, model: str = DEFAULT_MODEL, cache_path: str | Path | None = None):
        self.client, self.model = client, model
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache: dict[str, dict] = {}
        if self.cache_path and self.cache_path.exists():
            self.cache = json.loads(self.cache_path.read_text())
        self.calls = 0

    def categorise(self, keys: list[str], batch_size: int = 40) -> dict[str, LLMItem]:
        out: dict[str, LLMItem] = {}
        todo = []
        for k in dict.fromkeys(keys):
            if k in self.cache:
                out[k] = LLMItem(**self.cache[k])
            else:
                todo.append(k)
        for i in range(0, len(todo), batch_size):
            batch = todo[i:i + batch_size]
            for item in self._ask(batch):
                out[item.key] = item
                self.cache[item.key] = item.model_dump()
        if self.cache_path:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, indent=1))
        return out

    def _ask(self, batch: list[str]) -> list[LLMItem]:
        if self.client is None:
            return []
        safe = [redact(k) for k in batch]
        resp = self.client.messages.create(
            model=self.model, max_tokens=1500, system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(safe)}],
        )
        self.calls += 1
        text = "".join(getattr(b, "text", "") for b in resp.content)
        text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            return []
        items = []
        redacted_to_orig = dict(zip(safe, batch))
        for r in raw if isinstance(raw, list) else []:
            try:
                it = LLMItem(**r)
            except (ValidationError, TypeError):
                continue
            if it.key in redacted_to_orig:           # map back; ignore anything we didn't ask about
                it.key = redacted_to_orig[it.key]
                items.append(it)
        return items
