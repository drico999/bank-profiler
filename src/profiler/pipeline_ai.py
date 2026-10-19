"""AI-first pipeline: the AI reads, sorts and judges; code verifies and does the arithmetic.

  read (AI) -> verify balances (code, AI retries its own mistakes) -> cross-check vs built-in reader
  -> sort every payment (AI, your corrections win) -> metrics (code) -> judge + insights (AI, numbers checked)

If any AI step fails, the pipeline falls back to the code-only path and says so on screen.
"""
from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

from .ai.categorise import ai_categorise
from .ai.client import AIError, summarise_log
from .ai.extract import ai_extract
from .ai.judge import AIInsight, AIJudgement, ai_judge, build_facts
from .archetypes import Evidence, Verdict, build_evidence, classify, confidence, resilience_score
from .categorise import categorise, detect_recurring, load_corrections
from .config import THRESHOLDS, Thresholds
from .metrics import compute_metrics
from .models import ParsedStatement
from .parsers import parse_file
from .pipeline import Profile, _recon_multi
from .reconcile import dedupe, reconcile

TONE_LEVEL = {"positive": "good", "negative": "alert", "warning": "watch", "neutral": "ok"}


class AIRun(BaseModel):
    model: str
    steps: list[dict] = Field(default_factory=list)          # {"name","detail","ok"}
    extraction: dict = Field(default_factory=dict)
    categorisation: dict = Field(default_factory=dict)
    judgement: AIJudgement | None = None
    formula_archetype: str = ""
    formula_rule: str = ""
    formula_evidence: list[Evidence] = Field(default_factory=list)
    agrees_with_formula: bool | None = None
    insights: list[AIInsight] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class AIProfile(BaseModel):
    profile: Profile
    ai: AIRun


def _crosscheck(ai_txns, path, password) -> tuple[int, str] | None:
    """(% of AI-read rows, date + amount, that the independent built-in reader also found, bank name it recognised)."""
    try:
        ref_st = parse_file(path, password)
        ref = ref_st.transactions
    except Exception:
        return None
    a = Counter((t.date, t.amount_cents) for t in ai_txns)
    b = Counter((t.date, t.amount_cents) for t in ref)
    return round(100 * sum((a & b).values()) / max(sum(a.values()), sum(b.values()), 1)), ref_st.bank


def analyse_with_ai(paths, client, passwords: dict | None = None, corrections: dict | None = None,
                    th: Thresholds = THRESHOLDS, ai_reads_statement: bool = True, progress=None) -> AIProfile:
    passwords = passwords or {}
    run = AIRun(model=client.name)
    say = progress or (lambda s: None)
    step = lambda name, detail, ok=True: run.steps.append({"name": name, "detail": detail, "ok": ok})
    warnings, parsed = [], []

    # ---- 1. read
    ext = {"mode": "ai" if ai_reads_statement else "builtin", "files": [], "crosscheck_pct": None, "fallback_files": []}
    for p in map(Path, paths):
        pw = passwords.get(p.name)
        st = None
        if ai_reads_statement:
            try:
                st, stats = ai_extract(client, p, pw, progress=say)
                ext["files"].append(stats)
                cc = _crosscheck(st.transactions, p, pw)
                if cc is not None:
                    pct, bank = cc
                    ext["crosscheck_pct"] = pct if ext["crosscheck_pct"] is None else min(ext["crosscheck_pct"], pct)
                    st.bank = bank                      # the AI does not name the bank; the built-in reader does
                step("AI read the statement", f"{p.name}: {len(st.transactions)} transactions from {stats['lines']} lines"
                     + (f"; it corrected itself on {stats['retried_chunks']} part(s)" if stats["retried_chunks"] else "")
                     + (f"; {stats['unresolved_rows']} row(s) still failed checks" if stats["unresolved_rows"] else ""), not stats["unresolved_rows"])
            except AIError as e:
                run.warnings.append(f"The AI could not read {p.name} ({e}). The built-in reader was used instead.")
                ext["fallback_files"].append(p.name)
                step("AI read the statement", f"{p.name}: AI failed, used built-in reader. {e}", False)
        if st is None:
            st = parse_file(p, pw)                      # raises ValueError for unsupported files, handled by the app
            step("Built-in reader", f"{p.name}: {len(st.transactions)} transactions")
        parsed.append(st)
        warnings += [f"{st.source}: {w}" for w in st.warnings]
    run.extraction = ext

    txns = sorted([t for st in parsed for t in st.transactions], key=lambda t: t.date)
    txns, dropped = dedupe(txns)
    if dropped:
        warnings.append(f"{dropped} duplicate row(s) removed (overlapping statement periods)")
    for i, t in enumerate(txns):
        t.id = i
    recon = reconcile(txns) if len(parsed) == 1 else _recon_multi([ParsedStatement(bank=s.bank, transactions=s.transactions, source=s.source) for s in parsed])
    step("Balance check (code)", recon.message, recon.ok)

    # ---- 2. sort every payment
    corr = corrections if corrections is not None else load_corrections()
    try:
        run.categorisation = ai_categorise(client, txns, corr, progress=say)
        c = run.categorisation
        step("AI sorted the payments", f"{c['ai_rows']} rows by AI, {c['correction_rows']} by your corrections, {c['fallback_rows']} by the rule book"
             + (f". AI and rule book agree on {c['agree_pct']}% of the {c['compared']} rows both could judge" if c["agree_pct"] is not None else ""),
             c["fallback_rows"] < max(1, len(txns)) * 0.5)
    except Exception as e:                              # never lose the whole run for a categorising problem
        categorise(txns, corrections=corr)
        run.warnings.append(f"AI sorting failed ({e}); the rule book was used.")
        step("AI sorted the payments", f"failed, used rule book: {e}", False)
    detect_recurring(txns)

    # ---- 3. numbers (code)
    metrics, cycles = compute_metrics(txns, th)
    f_arche, f_rule = classify(metrics, th)
    conf, label, why = confidence(metrics, recon, th)
    verdict = Verdict(archetype=f_arche, rule=f_rule, score=resilience_score(metrics, th), confidence=conf, confidence_label=label,
                      confidence_reasons=why, evidence=build_evidence(metrics, cycles, txns, th))
    run.formula_archetype, run.formula_rule, run.formula_evidence = f_arche, f_rule, list(verdict.evidence)
    narrative, nsrc = None, "formula template"

    # ---- 4. AI judgement
    if f_arche != "Insufficient data":
        try:
            j = ai_judge(client, build_facts(metrics, cycles, recon), txns, f_arche, progress=say)
            run.judgement, run.insights = j, j.insights
            run.agrees_with_formula = j.archetype == f_arche
            verdict.archetype = j.archetype
            verdict.rule = f"AI judgement. Formula check says {f_arche}: {f_rule}"
            if j.evidence:
                verdict.evidence = [Evidence(text=e.text, metric="ai", txn_ids=e.txn_ids, tone=e.tone) for e in j.evidence]
            verdict.confidence = round(min(conf, j.confidence), 2)
            verdict.confidence_label = "High" if verdict.confidence >= 0.8 else "Medium" if verdict.confidence >= 0.55 else "Low"
            verdict.confidence_reasons = why + j.confidence_reasons
            if j.summary:
                narrative, nsrc = j.summary, f"AI ({client.model}), figures checked against the data"
            run.warnings += j.warnings
            step("AI judged the client", f"{j.archetype}; {len(j.insights)} insights kept, {len(j.rejected)} set aside for unverified figures"
                 + ("" if run.agrees_with_formula else f". Disagrees with the formula check ({f_arche})"), True)
        except AIError as e:
            run.warnings.append(f"The AI judgement failed ({e}). The formula result is shown instead.")
            step("AI judged the client", f"failed: {e}", False)
    if narrative is None:
        from .narrative import template_narrative
        narrative = template_narrative(verdict, metrics)
    run.usage = summarise_log(client.log)
    prof = Profile(banks=sorted({s.bank for s in parsed}), sources=[s.source for s in parsed], transactions=txns, reconciliation=recon,
                   metrics=metrics, cycles=cycles, verdict=verdict, narrative=narrative, narrative_source=nsrc,
                   warnings=warnings, duplicates_removed=dropped)
    return AIProfile(profile=prof, ai=run)
