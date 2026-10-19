"""Headless smoke test of the Streamlit dashboard (no browser needed)."""
import os
from pathlib import Path
import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")


def run_app(tmp_path, persona=None):
    os.environ["PROFILER_DATA_DIR"] = str(tmp_path)
    at = st_testing.AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=60)
    at.run()
    if persona:
        at.sidebar.selectbox[0].select(persona)
        at.run()
    return at


@pytest.mark.parametrize("persona", ["saver", "spender", "stretched", "volatile", "balanced"])
def test_dashboard_renders_each_persona(tmp_path, persona):
    at = run_app(tmp_path, persona)
    assert not at.exception, at.exception
    html = " ".join(m.value for m in at.markdown)
    assert PERSONA_LABEL[persona] in html


PERSONA_LABEL = {"saver": "Saver", "spender": "Spender", "stretched": "Stretched",
                 "volatile": "Volatile", "balanced": "Balanced"}


@pytest.mark.parametrize("size", ["Normal", "Large", "Extra large"])
def test_text_size_options_all_render(tmp_path, size):
    os.environ["PROFILER_DATA_DIR"] = str(tmp_path)
    at = st_testing.AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=60)
    at.run()
    at.sidebar.radio[0].set_value(size)
    at.run()
    assert not at.exception, at.exception
    css = " ".join(m.value for m in at.markdown if "<style>" in m.value)
    assert {"Normal": "18px", "Large": "21px", "Extra large": "24px"}[size] in css


def test_screen_uses_plain_language_and_icons_with_colour(tmp_path):
    at = run_app(tmp_path, "stretched")
    # Overview and Month-by-month are for everyone; the 'For analysts' tab may be technical.
    html = " ".join(m.value for tab in at.tabs[:2] for m in tab.markdown)
    for phrase in ("Money health score", "Worth a closer look", "Going well", "of every R100 earned", "Under pressure"):
        assert phrase in html, phrase
    for jargon in ("Resilience", "reconciliation", "cycle(s)", "archetype", "savings rate", "Confidence"):
        assert jargon not in html, jargon
    assert "✖" in html and "✔" in html          # status is never colour alone


# ------------------------------------------------------------------ detailed analysis (scripted stand-in model)
import re  # noqa: E402
from fake_ai import FakeAI  # noqa: E402

FORBIDDEN = re.compile(r"\bAI\b|Groq|\bLLM\b|language model|artificial|gpt|llama|Claude|Anthropic", re.I)


def ai_app(tmp_path, persona="spender", fake=None):
    os.environ["PROFILER_DATA_DIR"] = str(tmp_path)
    os.environ.pop("GROQ_API_KEY", None)
    at = st_testing.AppTest.from_file(str(Path(__file__).parent.parent / "app.py"), default_timeout=90)
    at.session_state["_ai_client_override"] = fake or FakeAI()
    at.run()
    at.sidebar.selectbox[0].select(persona)
    at.run()
    return at


def click(at, label):
    next(b for b in at.button if b.label == label).click()
    at.run()


def tab_html(at, i):
    return " ".join(m.value for m in at.tabs[i].markdown)


def public_text(at):
    """Everything a viewer can read outside the For analysts tab: tabs 0-2, the sidebar, widget labels and status boxes."""
    parts = [tab_html(at, i) for i in range(3)]
    sb = at.sidebar
    for group in (sb.markdown, sb.caption, sb.header, sb.subheader):
        parts += [e.value for e in group]
    for group in (sb.radio, sb.selectbox, sb.toggle, sb.button, sb.text_input):
        parts += [e.label for e in group]
        parts += [getattr(e, "help", "") or "" for e in group]
    parts += [t.label for t in at.tabs] + [x.label for x in at.status] + [i.value for i in at.info] + [e.value for e in at.error]
    return " ".join(str(p) for p in parts)


def test_public_screens_never_mention_ai_but_analysts_tab_discloses_it(tmp_path):
    at = ai_app(tmp_path, "stretched")
    assert not at.exception, at.exception
    assert not FORBIDDEN.search(public_text(at)), FORBIDDEN.search(public_text(at))
    assert "language model" in tab_html(at, 3) and "sent to that service" in tab_html(at, 3)       # honest disclosure stays


def test_public_screens_neutral_without_a_key_too(tmp_path):
    os.environ.pop("GROQ_API_KEY", None)
    at = run_app(tmp_path, "saver")
    assert not FORBIDDEN.search(public_text(at))
    assert "quick analysis" in tab_html(at, 0)


def test_there_is_no_key_box_or_run_button_on_the_main_screens(tmp_path):
    at = ai_app(tmp_path)
    assert not [b for b in at.sidebar.button] and not [t for t in at.sidebar.text_input]


def test_analysis_runs_by_itself_exactly_once_per_client(tmp_path):
    fake = FakeAI()
    at = ai_app(tmp_path, "spender", fake)
    assert fake.calls and "Quality checks" in tab_html(at, 0) and "match with a second reader" in tab_html(at, 0)
    n = len(fake.calls)
    at.sidebar.radio[0].set_value("Large")                       # any click reruns the whole script
    at.run()
    assert len(fake.calls) == n and "Quality checks" in tab_html(at, 0)


def test_new_client_triggers_a_fresh_analysis(tmp_path):
    fake = FakeAI()
    at = ai_app(tmp_path, "saver", fake)
    n = len(fake.calls)
    at.sidebar.selectbox[0].select("stretched")
    at.run()
    assert len(fake.calls) > n and "Stretched" in tab_html(at, 0) and "Quality checks" in tab_html(at, 0)


def test_failures_fall_back_quietly_and_never_loop(tmp_path):
    fake = FakeAI(fail_tasks=["extract", "categorise", "judge"])
    at = ai_app(tmp_path, "stretched", fake)
    assert not at.exception, at.exception
    html = tab_html(at, 0)
    assert "Stretched" in html and "simpler method" in html
    assert not FORBIDDEN.search(public_text(at))
    n = len(fake.calls)
    at.sidebar.radio[0].set_value("Large")
    at.run()
    assert len(fake.calls) == n                           # no retry storm


def test_total_outage_shows_the_quick_analysis_not_an_error_page(tmp_path):
    class Down(FakeAI):
        def chat_json(self, *a, **k):
            from profiler.ai.client import AIError
            raise AIError("Groq rejected the API key (401).")
    at = ai_app(tmp_path, "saver", Down())
    assert not at.exception, at.exception
    assert "Saver" in tab_html(at, 0) and not FORBIDDEN.search(public_text(at))
    assert "Groq rejected" in " ".join(w.value for w in at.warning) or "Groq rejected" in tab_html(at, 3)


def test_ask_a_question_tab_answers_and_shows_its_working(tmp_path):
    at = ai_app(tmp_path, "spender")
    next(t for t in at.text_input if t.label == "Your question").set_value("How much on betting each month?")
    click(at, "Ask")
    assert not at.exception, at.exception
    html = tab_html(at, 2)
    assert "You asked" in html and "Figures checked" in html
    assert not FORBIDDEN.search(public_text(at))
