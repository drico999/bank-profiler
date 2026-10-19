"""End to end: files -> parse -> reconcile -> dedupe -> categorise -> metrics -> verdict."""
from pathlib import Path

from pydantic import BaseModel, Field

from .archetypes import Verdict, build_evidence, classify, confidence, resilience_score
from .categorise import categorise, detect_recurring, load_corrections
from .config import THRESHOLDS, Thresholds
from .metrics import Cycle, Metrics, compute_metrics
from .models import ReconciliationResult, Transaction
from .narrative import write_narrative
from .parsers import parse_file
from .reconcile import dedupe, reconcile


class Profile(BaseModel):
    banks: list[str]
    sources: list[str]
    transactions: list[Transaction]
    reconciliation: ReconciliationResult
    metrics: Metrics
    cycles: list[Cycle]
    verdict: Verdict
    narrative: str
    narrative_source: str
    warnings: list[str] = Field(default_factory=list)
    duplicates_removed: int = 0


def analyse(paths: list[str | Path], passwords: dict[str, str] | None = None, llm=None,
            narrative_client=None, narrative_model: str = "", corrections: dict[str, str] | None = None,
            th: Thresholds = THRESHOLDS) -> Profile:
    passwords = passwords or {}
    parsed, warnings, txns = [], [], []
    for p in paths:
        st = parse_file(p, passwords.get(Path(p).name))
        parsed.append(st)
        warnings += [f"{st.source}: {w}" for w in st.warnings]
        txns += st.transactions
    txns.sort(key=lambda t: t.date)                  # stable: keeps statement order within a day
    txns, dropped = dedupe(txns)
    if dropped:
        warnings.append(f"{dropped} duplicate row(s) removed (overlapping statement periods)")
    for i, t in enumerate(txns):
        t.id = i
    recon = reconcile(txns) if len(parsed) == 1 else _recon_multi(parsed)
    categorise(txns, llm=llm, corrections=corrections if corrections is not None else load_corrections())
    detect_recurring(txns)
    metrics, cycles = compute_metrics(txns, th)
    archetype, rule = classify(metrics, th)
    conf, label, why = confidence(metrics, recon, th)
    verdict = Verdict(archetype=archetype, rule=rule, score=resilience_score(metrics, th), confidence=conf,
                      confidence_label=label, confidence_reasons=why, evidence=build_evidence(metrics, cycles, txns, th))
    narrative, nsrc = write_narrative(verdict, metrics, narrative_client, narrative_model)
    return Profile(banks=sorted({s.bank for s in parsed}), sources=[s.source for s in parsed], transactions=txns,
                   reconciliation=recon, metrics=metrics, cycles=cycles, verdict=verdict, narrative=narrative,
                   narrative_source=nsrc, warnings=warnings, duplicates_removed=dropped)


def _recon_multi(parsed) -> ReconciliationResult:
    """Reconcile each statement separately (balances only chain within one account)."""
    results = [reconcile(list(s.transactions)) for s in parsed]
    bad = sum(len(r.breaks) for r in results)
    return ReconciliationResult(ok=all(r.ok for r in results), checked=sum(r.checked for r in results),
                                breaks=[b for r in results for b in r.breaks],
                                message="Balances reconcile in every statement" if not bad else f"{bad} row(s) break the running balance")
