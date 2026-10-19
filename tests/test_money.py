import pytest
from datetime import date
from profiler.money import parse_amount, parse_date, format_rand


@pytest.mark.parametrize("raw,cents", [
    ("1 234,56", 123456), ("1,234.56", 123456), ("R1 234.56", 123456), ("-250,00", -25000),
    ("250.00Dr", -25000), ("18,500.00Cr", 1850000), ("(250.00)", -25000), ("5", 500), ("0,5", 50),
])
def test_parse_amount(raw, cents):
    assert parse_amount(raw) == cents


def test_parse_amount_rejects_garbage():
    with pytest.raises(ValueError):
        parse_amount("abc")


def test_dates():
    assert parse_date("25/01/2026") == date(2026, 1, 25)
    assert parse_date("2026-01-25") == date(2026, 1, 25)
    assert parse_date("25 Jan 2026") == date(2026, 1, 25)
    assert parse_date("25 Jan", ref_year=2026) == date(2026, 1, 25)


def test_format_rand():
    assert format_rand(1234567) == "R12 346" or format_rand(1234567) == "R12 345"  # rounding is whole rands
    assert format_rand(-5000, decimals=True) == "-R50.00"
