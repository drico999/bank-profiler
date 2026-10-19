import pytest
from profiler.parsers import parse_file
from profiler.reconcile import reconcile, dedupe
from profiler.synthetic import generate_events, with_balances, write_fnb_pdf
import random
from conftest import truth


@pytest.mark.parametrize("name", ["capitec.csv", "fnb.csv", "fnb.pdf"])
def test_every_sample_parses_and_reconciles(samples, name):
    for f in sorted(samples.glob(f"*_{name}")):
        st = parse_file(f)
        for i, t in enumerate(st.transactions):
            t.id = i
        assert len(st.transactions) == len(truth(samples, f.stem.split("_")[0])["categories"])
        assert reconcile(st.transactions).ok, f.name
        assert not st.warnings


def test_amounts_match_across_formats(samples):
    """Same persona in three formats must yield identical money columns."""
    a = parse_file(samples / "saver_capitec.csv").transactions
    b = parse_file(samples / "saver_fnb.csv").transactions
    c = parse_file(samples / "saver_fnb.pdf").transactions
    key = lambda ts: [(t.date, t.amount_cents, t.balance_cents) for t in ts]
    assert key(a) == key(b) == key(c)


def test_reconciliation_catches_a_misread_row(samples):
    ts = parse_file(samples / "saver_capitec.csv").transactions
    for i, t in enumerate(ts):
        t.id = i
    ts[10].amount_cents += 100          # simulate a misread amount
    r = reconcile(ts)
    assert not r.ok and 10 in r.breaks and "reconciliation_break" in ts[10].flags


def test_dedupe_removes_overlap(samples):
    ts = parse_file(samples / "saver_capitec.csv").transactions
    out, dropped = dedupe(ts + ts[:20])
    assert dropped == 20 and len(out) == len(ts)


def test_password_protected_pdf(tmp_path):
    rows = with_balances("saver", generate_events("saver"))
    p = tmp_path / "locked.pdf"
    write_fnb_pdf(rows, p, random.Random(1), password="secret")
    assert len(parse_file(p, password="secret").transactions) == len(rows)
    with pytest.raises(ValueError):
        parse_file(p, password="wrong")


def test_unsupported_file(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("a,b\n1,2\n")
    with pytest.raises(ValueError):
        parse_file(f)
