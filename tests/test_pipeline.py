import pytest
from profiler.pipeline import analyse
from profiler.narrative import grounded, facts_for, write_narrative
from profiler.synthetic import PERSONAS
from conftest import FakeClient


@pytest.mark.parametrize("persona", list(PERSONAS))
@pytest.mark.parametrize("fmt", ["capitec.csv", "fnb.csv"])
def test_archetype_matches_ground_truth(samples, persona, fmt):
    p = analyse([samples / f"{persona}_{fmt}"], corrections={})
    assert p.verdict.archetype == PERSONAS[persona]["archetype"]
    assert p.reconciliation.ok


def test_pdf_and_csv_give_same_verdict(samples):
    a = analyse([samples / "saver_capitec.csv"], corrections={})
    b = analyse([samples / "saver_fnb.pdf"], corrections={})
    assert a.verdict.archetype == b.verdict.archetype == "Saver"
    assert a.metrics.savings_rate == b.metrics.savings_rate


def test_deterministic(samples):
    f = samples / "balanced_fnb.csv"
    a, b = analyse([f], corrections={}), analyse([f], corrections={})
    assert a.metrics == b.metrics and a.verdict.score == b.verdict.score


def test_loan_proceeds_are_not_income(samples):
    p = analyse([samples / "stretched_capitec.csv"], corrections={})
    assert p.metrics.income_total == 14500 * 100 * p.metrics.n_cycles


def test_pay_cycles_follow_payday_not_calendar(samples):
    p = analyse([samples / "saver_capitec.csv"], corrections={})
    assert p.metrics.method == "pay_cycle" and p.metrics.n_cycles == 5
    assert all(c.start.day >= 23 for c in p.cycles)


def test_freelancer_falls_back_to_calendar_months(samples):
    p = analyse([samples / "volatile_capitec.csv"], corrections={})
    assert p.metrics.method == "calendar_month" and p.metrics.income_cv > 0.3
    assert any("calendar" in r.lower() for r in p.verdict.confidence_reasons) or p.verdict.confidence <= 0.9


def test_overlapping_uploads_are_deduplicated(samples):
    one = analyse([samples / "saver_capitec.csv"], corrections={})
    twice = analyse([samples / "saver_capitec.csv", samples / "saver_capitec.csv"], corrections={})
    assert twice.duplicates_removed == len(one.transactions)
    assert twice.metrics.savings_rate == one.metrics.savings_rate


def test_evidence_links_to_real_transactions(samples):
    p = analyse([samples / "spender_capitec.csv"], corrections={})
    ids = {t.id for t in p.transactions}
    linked = [e for e in p.verdict.evidence if e.txn_ids]
    assert linked and all(set(e.txn_ids) <= ids for e in linked)
    assert any(e.metric == "gambling_ratio" for e in p.verdict.evidence)


def test_confidence_drops_when_balances_break(samples):
    good = analyse([samples / "saver_capitec.csv"], corrections={})
    bad_file = samples / "bad.csv"
    lines = (samples / "saver_capitec.csv").read_text().splitlines()
    parts = lines[5].split(",")
    parts[-1] = "99999.00"                       # corrupt one running balance
    lines[5] = ",".join(parts)
    bad_file.write_text("\n".join(lines))
    bad = analyse([bad_file], corrections={})
    assert not bad.reconciliation.ok and bad.verdict.confidence < good.verdict.confidence


def test_narrative_rejects_invented_numbers(samples):
    p = analyse([samples / "saver_capitec.csv"], corrections={})
    facts = facts_for(p.verdict, p.metrics)
    assert grounded(p.narrative, facts)
    assert not grounded("They save 87% of their income.", facts)
    liar = FakeClient(lambda _: "This client saves 87% every month.")
    text, src = write_narrative(p.verdict, p.metrics, liar, "m")
    assert src == "template" and "87%" not in text


def test_narrative_accepts_grounded_llm_text(samples):
    p = analyse([samples / "saver_capitec.csv"], corrections={})
    sr = facts_for(p.verdict, p.metrics)["savings_rate"]
    ok = FakeClient(lambda _: f"A steady saver with a {sr} savings rate.")
    text, src = write_narrative(p.verdict, p.metrics, ok, "m")
    assert src.startswith("llm") and sr in text


def test_user_corrections_flow_through_the_pipeline(samples, tmp_path):
    from profiler.categorise import save_correction, load_corrections, merchant_key
    f = samples / "spender_fnb.csv"
    before = analyse([f], corrections={})
    unknown_before = sum(t.category == "unknown" for t in before.transactions)
    assert unknown_before > 0
    cp = tmp_path / "c.json"
    for name in ("MAMA THANDI SPAZA", "BONGANI TUCKSHOP", "FRESH PRODUCE MARKET"):
        save_correction(merchant_key(name), "groceries", cp)
    after = analyse([f], corrections=load_corrections(cp))
    assert sum(t.category == "unknown" for t in after.transactions) < unknown_before
    assert after.metrics.category_totals["groceries"] > before.metrics.category_totals["groceries"]
