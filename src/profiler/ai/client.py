"""Groq client (OpenAI-compatible API), standard library only.

Never hard-code a key. It is read from the GROQ_API_KEY environment variable or typed
into the app's sidebar (kept in memory for the session only).

Safety features worth learning from:
  * retries with back-off on rate limits (429) and server errors
  * every call is logged (task, model, tokens, seconds) so the UI can show what the AI did
  * identical calls are cached on disk, which saves tokens and avoids rate limits
  * the transport is injectable, so tests never touch the network
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile", "llama-3.1-8b-instant"]


class AIError(Exception):
    """Raised with a message that is safe and clear enough to show to the user."""


@dataclass
class CallRecord:
    task: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    retries: int = 0
    cached: bool = False


def parse_json(text: str) -> dict:
    """Pull a JSON object out of model text (handles code fences and stray prose)."""
    text = re.sub(r"^```(?:json)?|```$", "", (text or "").strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise AIError("The AI did not return JSON")
    try:
        out = json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        raise AIError(f"The AI returned broken JSON: {e}") from e
    if not isinstance(out, dict):
        raise AIError("The AI returned JSON that is not an object")
    return out


def _urllib_transport(url, headers, body, timeout):
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read()
    except (urllib.error.URLError, TimeoutError) as e:
        raise AIError(f"Could not reach Groq: {getattr(e, 'reason', e)}") from e


@dataclass
class GroqClient:
    api_key: str
    model: str = DEFAULT_MODEL
    cache_path: str | Path | None = None
    transport: object = None
    sleep: object = time.sleep
    max_retries: int = 4
    log: list = field(default_factory=list)

    def __post_init__(self):
        self.transport = self.transport or _urllib_transport
        self._cache = {}
        if self.cache_path and Path(self.cache_path).exists():
            try:
                self._cache = json.loads(Path(self.cache_path).read_text())
            except (OSError, json.JSONDecodeError):
                self._cache = {}

    @property
    def name(self) -> str:
        return f"Groq / {self.model}"

    def _headers(self):
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                "User-Agent": "bank-profiler/0.2"}

    def list_models(self) -> list[str]:
        status, _, body = self.transport(f"{BASE_URL}/models", self._headers(), None, 30)
        self._raise_for(status, body)
        return sorted(m["id"] for m in json.loads(body).get("data", []))

    @staticmethod
    def _raise_for(status, body):
        if status == 401:
            raise AIError("Groq rejected the API key (401). Check it was copied in full, or create a new one.")
        if status == 403:
            raise AIError("Groq refused access (403). The key may be restricted or the network may block it.")
        if status >= 400:
            try:
                msg = json.loads(body).get("error", {}).get("message", "")
            except Exception:
                msg = ""
            raise AIError(f"Groq error {status}: {msg[:200]}")

    def chat_json(self, task: str, system: str, user: str, model: str | None = None, max_tokens: int = 6000) -> dict:
        model = model or self.model
        key = hashlib.sha256(f"{model}|{max_tokens}|{system}|{user}".encode()).hexdigest()
        if key in self._cache:
            self.log.append(CallRecord(task, model, cached=True))
            return self._cache[key]

        base = {"model": model, "temperature": 0, "max_completion_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        optional = {"response_format": {"type": "json_object"}}
        if model.startswith("openai/gpt-oss"):
            optional["reasoning_effort"] = "low" if task in ("extract", "categorise") else "medium"
        rec = CallRecord(task, model)
        t0, attempt, use_optional = time.time(), 0, True
        while True:
            body = json.dumps({**base, **(optional if use_optional else {})}).encode()
            status, headers, raw = self.transport(f"{BASE_URL}/chat/completions", self._headers(), body, 90)
            if status == 400 and use_optional:           # model may not accept optional parameters
                use_optional = False
                continue
            if status in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                wait = float({k.lower(): v for k, v in headers.items()}.get("retry-after", 2 ** attempt))
                self.sleep(min(wait, 30))
                attempt += 1
                continue
            self._raise_for(status, raw)
            break
        rec.retries, rec.seconds = attempt, round(time.time() - t0, 2)
        data = json.loads(raw)
        usage = data.get("usage", {})
        rec.prompt_tokens, rec.completion_tokens = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        if not text.strip():
            raise AIError("The AI used all its tokens thinking and returned nothing. Try again or choose a larger model.")
        out = parse_json(text)
        self.log.append(rec)
        self._cache[key] = out
        if self.cache_path:
            try:
                Path(self.cache_path).parent.mkdir(parents=True, exist_ok=True)
                Path(self.cache_path).write_text(json.dumps(self._cache))
            except OSError:
                pass
        return out


def summarise_log(log: list) -> dict:
    return {"calls": sum(1 for r in log if not r.cached), "cached": sum(1 for r in log if r.cached),
            "prompt_tokens": sum(r.prompt_tokens for r in log), "completion_tokens": sum(r.completion_tokens for r in log),
            "seconds": round(sum(r.seconds for r in log), 1), "retries": sum(r.retries for r in log)}
