import pytest
from profiler.insights import build_insights, spend_groups, STATUS
from profiler.pipeline import analyse
from profiler.synthetic import PERSONAS


def by_key(ins):
    return {i.key: i for i in ins}


def test_saver_insights_are_positive(samples):
    p = analyse([samples / "saver_capitec.csv"], corrections={})
    k = by_key(build_insights(p.metrics))
    assert k["savings"].level == "good" and k["buffer"].level == "good" and k["debt"].level == "good"
    assert "of every R100" in k["savings"].headline


def test_stretched_flags_the_right_things(samples):
    p = analyse([samples / "stretched_capitec.csv"], corrections={})
    k = by_key(build_insights(p.metrics))
    assert k["fixed"].level == "alert" and k["debt"].level in ("watch", "alert")
    assert k["savings"].level in ("watch", "alert")


def test_betting_only_shown_when_present(samples):
    assert "betting" in by_key(build_insights(analyse([samples / "spender_capitec.csv"], corrections={}).metrics))
    assert "betting" not in by_key(build_insights(analyse([samples / "saver_capitec.csv"], corrections={}).metrics))


def test_freelancer_pay_is_not_steady(samples):
    k = by_key(build_insights(analyse([samples / "volatile_capitec.csv"], corrections={}).metrics))
    assert k["income"].level in ("watch", "alert")


@pytest.mark.parametrize("persona", list(PERSONAS))
def test_spend_groups_add_up(samples, persona):
    m = analyse([samples / f"{persona}_capitec.csv"], corrections={}).metrics
    g = spend_groups(m)
    assert abs(g["spent"] + g["left"] - g["income"]) < 1e-6
    assert abs(g["spent"] - m.avg_spend) < 1        # nothing lost between groups and total spend (cents)


def test_every_archetype_has_a_status():
    for name in list(PERSONAS.values()):
        assert name["archetype"] in STATUS
    assert "Insufficient data" in STATUS
