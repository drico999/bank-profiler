"""Statement profiler dashboard, designed to be easy to read at a glance.   Run:  python -m streamlit run app.py

Design rules: plain words, big type, colour is ALWAYS paired with an icon and a word,
and everything technical lives in the 'For analysts' tab.
"""
import hashlib
import html
import json
import os
import sys
import tempfile
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))

from profiler.categorise import merchant_key, save_correction  # noqa: E402
from profiler.ai import DEFAULT_MODEL, MODELS, AIError, GroqClient  # noqa: E402
from profiler.ai.ask import ask  # noqa: E402
from profiler.config import ALL_CATEGORIES  # noqa: E402
from profiler.insights import LEVEL_ICON, LEVEL_WORD, STATUS, build_insights, spend_groups  # noqa: E402
from profiler.metrics import daily_balances  # noqa: E402
from profiler.money import format_rand as R  # noqa: E402
from profiler.pipeline import analyse  # noqa: E402
from profiler.pipeline_ai import analyse_with_ai  # noqa: E402
from profiler.synthetic import PERSONAS, generate_all  # noqa: E402

st.set_page_config(page_title="Client money profile", page_icon="R", layout="wide")

INK, MUTED = "#12304A", "#46586B"
LEVELS = {  # text, background, accent
    "good": ("#14692F", "#E4F4E9", "#1E8E3E"),
    "ok": ("#0F4C8A", "#E6F0FA", "#1A5FB4"),
    "watch": ("#7A4B00", "#FFF3D6", "#E08A00"),
    "alert": ("#9E1C14", "#FDE7E5", "#C62828"),
}
GROUP_COLOUR = {"fixed": "#1A5FB4", "loans": "#C62828", "essentials": "#2F8F6B", "fun": "#8E5BB5", "betting": "#7A1F1F",
                "family": "#E08A00", "cash": "#6B7B8C", "fees": "#A67C00", "other": "#9AA5B1", "left": "#1E8E3E"}
SIZES = {"Normal": 18, "Large": 21, "Extra large": 24}
data_dir = Path(os.environ.get("PROFILER_DATA_DIR", "data"))


# ---------------------------------------------------------------- styling
def inject_css(px: int) -> None:
    lv = "".join(f".lvl-{k}{{--fg:{a};--bg:{b};--ac:{c};}}" for k, (a, b, c) in LEVELS.items())
    st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&display=swap');
html {{ font-size: {px}px !important; }}
html, body, .stApp, [class*="css"] {{ font-family: 'Atkinson Hyperlegible', 'Segoe UI', Verdana, sans-serif; color: {INK}; }}
.block-container {{ max-width: 1180px; padding-top: 2rem; }}
{lv}
h1, h2, h3 {{ color: {INK}; letter-spacing: -0.01em; }}
.sec {{ font-size: 1.5rem; font-weight: 700; margin: 2.2rem 0 0.2rem 0; }}
.sec-sub {{ color: {MUTED}; margin: 0 0 0.9rem 0; font-size: 1rem; }}
.hero {{ display: flex; flex-wrap: wrap; gap: 1.5rem; align-items: center; justify-content: space-between;
  background: var(--bg); border: 3px solid var(--ac); border-radius: 18px; padding: 1.6rem 2rem; }}
.pill {{ display: inline-block; background: var(--ac); color: #fff; font-weight: 700; font-size: 1.1rem; padding: 0.3rem 1rem; border-radius: 999px; }}
.hero-title {{ font-size: 3.4rem; font-weight: 700; line-height: 1.05; margin: 0.6rem 0 0.2rem 0; color: var(--fg); }}
.hero-plain {{ font-size: 1.5rem; margin: 0 0 0.6rem 0; max-width: 28ch; line-height: 1.3; }}
.hero-sub {{ color: {MUTED}; margin: 0; font-size: 0.95rem; }}
.ring {{ text-align: center; }}
.ring-label {{ font-weight: 700; font-size: 1.05rem; margin-top: 0.2rem; }}
.note {{ border-radius: 12px; padding: 0.9rem 1.2rem; margin: 1rem 0 0 0; border-left: 8px solid var(--ac); background: var(--bg); color: {INK}; line-height: 1.45; }}
.note b {{ color: var(--fg); }}
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 1rem; margin-top: 1.2rem; }}
.kpi {{ background: #fff; border: 2px solid #D5DEE7; border-radius: 14px; padding: 1rem 1.2rem; }}
.kpi-l {{ color: {MUTED}; font-size: 1rem; }}
.kpi-v {{ font-size: 2rem; font-weight: 700; line-height: 1.15; margin-top: 0.15rem; }}
.kpi-s {{ font-size: 0.9rem; color: {MUTED}; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 1rem; }}
.card {{ background: #fff; border: 2px solid #D5DEE7; border-left: 10px solid var(--ac); border-radius: 12px; padding: 1rem 1.2rem; }}
.card-top {{ display: flex; flex-wrap: wrap; gap: 0.5rem; align-items: center; justify-content: space-between; }}
.card-title {{ font-weight: 700; font-size: 1.1rem; }}
.badge {{ background: var(--bg); color: var(--fg); border: 1.5px solid var(--ac); font-weight: 700; font-size: 0.85rem; padding: 0.1rem 0.6rem; border-radius: 999px; white-space: nowrap; }}
.card-head {{ font-size: 1.45rem; font-weight: 700; margin: 0.5rem 0 0.1rem 0; color: var(--fg); line-height: 1.2; }}
.card-detail {{ line-height: 1.45; }}
.empty {{ color: {MUTED}; font-style: italic; padding: 0.6rem 0; }}
.stack {{ display: flex; height: 46px; border-radius: 10px; overflow: hidden; border: 2px solid #D5DEE7; background: #fff; }}
.legend {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
.legend td {{ padding: 0.6rem 0.5rem; border-bottom: 1px solid #D5DEE7; vertical-align: middle; }}
.legend .sw {{ width: 1.6rem; }} .legend .sw i {{ display: block; width: 1.2rem; height: 1.2rem; border-radius: 4px; }}
.legend .num {{ text-align: right; white-space: nowrap; font-weight: 700; }}
.legend .h {{ color: {MUTED}; font-size: 0.9rem; }}
.mt {{ width: 100%; border-collapse: collapse; background: #fff; border: 2px solid #D5DEE7; border-radius: 12px; overflow: hidden; }}
.mt th {{ background: {INK}; color: #fff; text-align: left; padding: 0.7rem 0.8rem; font-size: 1rem; }}
.mt td {{ padding: 0.7rem 0.8rem; border-top: 1px solid #D5DEE7; }}
.mt tr:nth-child(even) td {{ background: #F4F7FA; }}
.mt .r {{ text-align: right; white-space: nowrap; }}
.foot {{ color: {MUTED}; font-size: 0.9rem; margin-top: 2.5rem; border-top: 1px solid #D5DEE7; padding-top: 0.8rem; }}
.chkbox {{ background: #EEF3FB; border: 2px solid #1A5FB4; border-radius: 14px; padding: 1rem 1.3rem; margin: 1rem 0 0 0; }}
.chkbox-h {{ font-weight: 700; font-size: 1.15rem; margin-bottom: 0.5rem; color: #0F4C8A; }}
.chips {{ display: flex; flex-wrap: wrap; gap: 0.5rem; }}
.chip {{ background: #fff; border: 1.5px solid #9DB8DD; border-radius: 999px; padding: 0.15rem 0.8rem; font-size: 0.95rem; }}
.chip.bad {{ border-color: #E08A00; background: #FFF3D6; }}
.says {{ font-size: 1.2rem; line-height: 1.55; max-width: 68ch; margin: 0.9rem 0 0 0; }}
.says small {{ display: block; color: {MUTED}; font-size: 0.85rem; margin-top: 0.3rem; }}
button[data-baseweb="tab"] p {{ font-size: 1.15rem; font-weight: 700; }}
:focus-visible {{ outline: 3px solid #1A5FB4; outline-offset: 2px; }}
</style>""", unsafe_allow_html=True)


def esc(s) -> str:
    return html.escape(str(s))


def ring_svg(score: int, level: str) -> str:
    c, ac = 2 * 3.14159 * 56, LEVELS[level][2]
    dash = c * score / 100
    return (f'<svg width="150" height="150" viewBox="0 0 150 150" role="img" aria-label="Money health score {score} out of 100">'
            f'<circle cx="75" cy="75" r="56" fill="none" stroke="#D5DEE7" stroke-width="16"/>'
            f'<circle cx="75" cy="75" r="56" fill="none" stroke="{ac}" stroke-width="16" stroke-linecap="round" '
            f'stroke-dasharray="{dash:.1f} {c:.1f}" transform="rotate(-90 75 75)"/>'
            f'<text x="75" y="82" text-anchor="middle" font-size="40" font-weight="700" fill="{INK}">{score}</text>'
            f'<text x="75" y="104" text-anchor="middle" font-size="14" fill="{MUTED}">out of 100</text></svg>')


def insight_card(i) -> str:
    return (f'<div class="card lvl-{i.level}"><div class="card-top"><span class="card-title">{esc(i.title)}</span>'
            f'<span class="badge">{LEVEL_ICON[i.level]} {LEVEL_WORD[i.level]}</span></div>'
            f'<div class="card-head">{esc(i.headline)}</div><div class="card-detail">{esc(i.detail)}</div></div>')


def section(title: str, sub: str = "") -> None:
    st.markdown(f'<div class="sec">{esc(title)}</div>' + (f'<div class="sec-sub">{esc(sub)}</div>' if sub else ""),
                unsafe_allow_html=True)


@st.cache_resource
def sample_dir() -> Path:
    d = Path(tempfile.mkdtemp(prefix="profiler_samples_"))
    generate_all(d)
    return d


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    size_name = st.radio("Text size", list(SIZES), horizontal=True, help="Makes everything on the page bigger or smaller.")
    st.divider()
    st.header("Client statements")
    source = st.radio("Where from?", ["Sample client", "Upload files"], horizontal=True)
    files, passwords = [], {}
    if source == "Sample client":
        persona = st.selectbox("Sample client", list(PERSONAS), format_func=str.title)
        fmt = st.selectbox("Statement format", ["Capitec CSV", "FNB CSV", "FNB PDF"] if persona in ("saver", "volatile")
                           else ["Capitec CSV", "FNB CSV"])
        suffix = {"Capitec CSV": "capitec.csv", "FNB CSV": "fnb.csv", "FNB PDF": "fnb.pdf"}[fmt]
        files = [sample_dir() / f"{persona}_{suffix}"]
        st.caption("Made-up data. No real person is shown.")
    else:
        ups = st.file_uploader("CSV or text-based PDF (one client, one or more statements)", type=["csv", "pdf"],
                               accept_multiple_files=True)
        pw = st.text_input("PDF password, if it has one", type="password")
        tmp = Path(tempfile.mkdtemp(prefix="profiler_up_"))
        for u in ups or []:
            p = tmp / u.name
            p.write_bytes(u.getbuffer())
            files.append(p)
            if pw:
                passwords[u.name] = pw
        st.caption("Statements are read on this computer. When the detailed analysis is on, transaction text is sent to an outside "
                   "analysis service, with names, phone numbers and account numbers masked first.")

# ---------------------------------------------------------------- analysis engine settings (kept out of sight, see For analysts)
def configured_key() -> str:
    for k in (st.session_state.get("cfg_key", ""), os.environ.get("GROQ_API_KEY", "")):
        if str(k).strip():
            return str(k).strip()
    try:                                                  # .streamlit/secrets.toml (git-ignored)
        return str(st.secrets.get("GROQ_API_KEY", "")).strip()
    except Exception:
        return ""


model = st.session_state.get("cfg_model", DEFAULT_MODEL)
ai_reads = st.session_state.get("cfg_reads", True)
_key = configured_key()
client = st.session_state.get("_ai_client_override") or (
    GroqClient(_key, model=model, cache_path=data_dir / "ai_cache.json")
    if (_key and st.session_state.get("cfg_on", True)) else None)

inject_css(SIZES[size_name])

if not files:
    st.markdown('<div class="sec">Client money profile</div>', unsafe_allow_html=True)
    st.write("Choose a sample client or upload statements in the panel on the left.")
    st.stop()

# ---------------------------------------------------------------- analysis
sig = hashlib.sha256(json.dumps([[f.name, f.stat().st_size, hashlib.md5(f.read_bytes()).hexdigest()] for f in files]
                                + [model, ai_reads]).encode()).hexdigest()
saved = st.session_state.get("ai_result")
ai_full = saved["result"] if saved and saved["sig"] == sig else None
if client and ai_full is None and st.session_state.get("ai_attempted") != sig:
    st.session_state["ai_attempted"] = sig                  # one automatic attempt per client; no repeat spending on reruns
    st.session_state["engine_error"] = ""
    box = st.status("Analysing this client...", expanded=True)
    try:
        result = analyse_with_ai(files, client, passwords=passwords, ai_reads_statement=ai_reads, progress=lambda msg: box.write(msg))
        st.session_state["ai_result"] = {"sig": sig, "result": result}
        ai_full = result
        box.update(label="Analysis finished", state="complete", expanded=False)
    except (AIError, ValueError) as e:
        st.session_state["engine_error"] = str(e)
        box.update(label="Showing the quick analysis instead", state="complete", expanded=False)
if ai_full:
    prof, air = ai_full.profile, ai_full.ai
else:
    air = None
    try:
        prof = analyse(files, passwords=passwords)           # quick formula-only result, no outside service
    except ValueError as e:
        st.error(f"We could not read these statements: {e}")
        st.stop()

v, m = prof.verdict, prof.metrics
status, level, plain = STATUS[v.archetype]
unit = "pay months" if m.method == "pay_cycle" else "months"
dates = [t.date for t in prof.transactions]
span = f"{min(dates):%d %b %Y} to {max(dates):%d %b %Y}" if dates else ""
banks = " and ".join(b.title() for b in prof.banks if b != "ai-read") or "bank"
insights = air.insights if (air and air.insights) else build_insights(m)

tab_over, tab_month, tab_ask, tab_an = st.tabs(["Overview", "Month by month", "Ask a question", "For analysts"])

# ================================================================ OVERVIEW
with tab_over:
    st.markdown(
        f'<div class="hero lvl-{level}"><div><span class="pill">{LEVEL_ICON[level]} {status}</span>'
        f'<h1 class="hero-title">{esc(v.archetype)}</h1><p class="hero-plain">{esc(plain)}</p>'
        f'<p class="hero-sub">Based on {m.n_cycles} {unit} of {esc(banks)} statements, {span}.</p></div>'
        f'<div class="ring">{ring_svg(v.score, level)}<div class="ring-label">Money health score</div></div></div>',
        unsafe_allow_html=True)

    if air:
        ex = air.extraction
        chips = [f'<span class="chip">✔ {len(prof.transactions)} transactions read</span>',
                 '<span class="chip">✔ Balances add up</span>' if prof.reconciliation.ok else '<span class="chip bad">▲ Some balances do not add up</span>']
        if ex.get("crosscheck_pct") is not None:
            chips.append(f'<span class="chip{"" if ex["crosscheck_pct"] >= 98 else " bad"}">{ex["crosscheck_pct"]}% match with a second reader</span>')
        if air.agrees_with_formula is not None:
            chips.append('<span class="chip">✔ Two methods agree</span>' if air.agrees_with_formula
                         else '<span class="chip bad">▲ Two methods disagree</span>')
        says = (f'<div class="says"><b>In short.</b> {esc(prof.narrative)}</div>' if prof.narrative_source.startswith("AI") else "")
        st.markdown(f'<div class="chkbox"><div class="chkbox-h">Quality checks</div><div class="chips">{"".join(chips)}</div>{says}</div>',
                    unsafe_allow_html=True)
        if air.agrees_with_formula is False:
            st.markdown(f'<div class="note lvl-watch"><b>▲ Two ways of checking disagree.</b> The detailed analysis rates this client '
                        f'<b>{esc(v.archetype)}</b>; the quick formula says <b>{esc(air.formula_archetype)}</b>. Please review before relying on either.</div>',
                        unsafe_allow_html=True)
        rej = len(air.judgement.rejected) if air.judgement else 0
        if rej:
            st.markdown(f'<div class="note lvl-watch"><b>▲ {rej} statement(s) were left out</b> because their figures did not match '
                        f'the bank statements. Details are in the For analysts tab.</div>', unsafe_allow_html=True)
        if air.warnings or ex.get("fallback_files"):
            st.markdown('<div class="note lvl-watch"><b>▲ Some steps used a simpler method.</b> Details are in the For analysts tab.</div>',
                        unsafe_allow_html=True)
    elif client:
        st.markdown('<div class="note lvl-ok"><b>● Showing the quick analysis.</b> The detailed analysis could not be completed this time. '
                    'Details are in the For analysts tab.</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="note lvl-ok"><b>● Showing the quick analysis.</b> The detailed analysis is not set up on this computer yet '
                    '(see For analysts, then Settings).</div>', unsafe_allow_html=True)

    if prof.reconciliation.ok and v.confidence_label == "High":
        st.markdown('<div class="note lvl-good"><b>✔ We are confident in this picture.</b> Every line on the statements adds up '
                    'and there is enough history to judge.</div>', unsafe_allow_html=True)
    else:
        why = "".join(f"<li>{esc(r)}</li>" for r in v.confidence_reasons) or "<li>Some details were hard to read.</li>"
        st.markdown(f'<div class="note lvl-watch"><b>▲ Treat this picture with some care ({v.confidence_label.lower()} confidence).</b>'
                    f'<ul style="margin:0.3rem 0 0 1.2rem">{why}</ul></div>', unsafe_allow_html=True)
    for w in prof.warnings:
        st.markdown(f'<div class="note lvl-watch"><b>▲</b> {esc(w)}</div>', unsafe_allow_html=True)

    kept = m.avg_income - m.avg_spend
    klevel = "good" if kept > 0.05 * m.avg_income else "watch" if kept >= 0 else "alert"
    weeks = m.buffer_months * 52 / 12
    st.markdown(
        '<div class="kpis">'
        f'<div class="kpi"><div class="kpi-l">Money in, each month</div><div class="kpi-v">{R(m.avg_income)}</div><div class="kpi-s">on average</div></div>'
        f'<div class="kpi"><div class="kpi-l">Money spent, each month</div><div class="kpi-v">{R(m.avg_spend)}</div><div class="kpi-s">on average</div></div>'
        f'<div class="kpi lvl-{klevel}"><div class="kpi-l">Left over, each month</div><div class="kpi-v" style="color:var(--fg)">'
        f'{LEVEL_ICON[klevel]} {R(kept)}</div><div class="kpi-s">{"kept" if kept >= 0 else "more spent than earned"}</div></div>'
        f'<div class="kpi"><div class="kpi-l">Safety net</div><div class="kpi-v">{weeks:.0f} weeks</div><div class="kpi-s">of spending covered</div></div>'
        '</div>', unsafe_allow_html=True)

    good = [i for i in insights if i.is_positive]
    concern = sorted((i for i in insights if not i.is_positive), key=lambda i: 0 if i.level == "alert" else 1)
    section("Worth a closer look", "Things that may need a conversation. The most serious come first.")
    st.markdown('<div class="cards">' + "".join(insight_card(i) for i in concern) + "</div>" if concern
                else '<div class="empty">Nothing here stands out as a concern.</div>', unsafe_allow_html=True)
    section("Going well", "Healthy habits seen in the statements.")
    st.markdown('<div class="cards">' + "".join(insight_card(i) for i in good) + "</div>" if good
                else '<div class="empty">Nothing here stands out as a strength yet.</div>', unsafe_allow_html=True)

    # ---- where the money goes
    g = spend_groups(m)
    base = max(g["income"], g["spent"]) or 1
    section("Where each month's money goes", f"Average per month, from {m.n_cycles} {unit}.")
    segs = [(r["key"], r["label"], r["helper"], r["cents"]) for r in g["rows"]]
    if g["left"] > 0:
        segs.append(("left", "Left over", "kept or saved", g["left"]))
    bar = "".join(f'<div title="{esc(l)}: {R(c)}" style="width:{100 * c / base:.2f}%;background:{GROUP_COLOUR[k]}"></div>' for k, l, _, c in segs)
    st.markdown(f'<div class="stack" role="img" aria-label="Breakdown of monthly spending">{bar}</div>', unsafe_allow_html=True)
    if g["left"] < 0:
        st.markdown(f'<div class="note lvl-alert"><b>✖ More went out than came in.</b> Spending was {R(-g["left"])} a month '
                    f'higher than the money coming in.</div>', unsafe_allow_html=True)
    rows = "".join(
        f'<tr><td class="sw"><i style="background:{GROUP_COLOUR[k]}"></i></td><td><b>{esc(l)}</b>'
        f'{f"<div class=h>{esc(h)}</div>" if h else ""}</td><td class="num">{R(c)} a month</td>'
        f'<td class="num">R{round(100 * c / g["income"]) if g["income"] else 0} of every R100 earned</td></tr>' for k, l, h, c in segs)
    st.markdown(f'<table class="legend">{rows}</table>', unsafe_allow_html=True)

# ================================================================ MONTH BY MONTH
with tab_month:
    done = [c for c in prof.cycles if c.complete and c.income_cents]
    section("Money in and money spent", "Blue is money coming in. Orange is money going out.")

    def label(c):
        return f"{c.start:%d %b} to {c.end:%d %b}" if m.method == "pay_cycle" else f"{c.start:%B %Y}"

    fs = 16 if SIZES[size_name] <= 18 else 18
    long = pd.DataFrame([{"Month": label(c), "Type": t, "Rand": val / 100}
                         for c in done for t, val in (("Money in", c.income_cents), ("Money spent", c.spend_cents))])
    if not long.empty:
        order = [label(c) for c in done]
        chart = alt.Chart(long).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4).encode(
            x=alt.X("Month:N", sort=order, axis=alt.Axis(labelAngle=0, labelFontSize=fs - 2, title=None, labelLimit=140)),
            xOffset=alt.XOffset("Type:N"),
            y=alt.Y("Rand:Q", axis=alt.Axis(labelFontSize=fs, title=None, labelExpr="'R' + format(datum.value, ',.0f')")),
            color=alt.Color("Type:N", scale=alt.Scale(domain=["Money in", "Money spent"], range=["#1A5FB4", "#E08A00"]),
                            legend=alt.Legend(labelFontSize=fs + 1, title=None, orient="top", symbolSize=260)),
            tooltip=["Month", "Type", alt.Tooltip("Rand:Q", format=",.0f")]).properties(height=340)
        st.altair_chart(chart, width="stretch")

    section("How each month went")

    def how(c):
        left = c.income_cents - c.spend_cents
        if left < 0:
            return "alert", "Spent more than earned"
        if c.spend_cents >= 0.95 * c.income_cents:
            return "watch", "Almost nothing left"
        return "good", "Money left over"

    body = ""
    for c in done:
        lv, words = how(c)
        left = c.income_cents - c.spend_cents
        body += (f'<tr><td><b>{esc(label(c))}</b></td><td class="r">{R(c.income_cents)}</td><td class="r">{R(c.spend_cents)}</td>'
                 f'<td class="r"><b>{R(left)}</b></td><td><span class="badge lvl-{lv}">{LEVEL_ICON[lv]} {words}</span></td></tr>')
    st.markdown('<table class="mt"><thead><tr><th>Month</th><th class="r">Money in</th><th class="r">Money spent</th>'
                f'<th class="r">Left over</th><th>How it went</th></tr></thead><tbody>{body}</tbody></table>', unsafe_allow_html=True)

    section("Money in the account", "The dashed red line is zero. Below it, the account is overdrawn." +
            (" Grey dotted lines mark payday." if m.method == "pay_cycle" else ""))
    bal = daily_balances(prof.transactions)
    bdf = pd.DataFrame({"Date": list(bal.keys()), "Rand": [b / 100 for b in bal.values()]})
    line = alt.Chart(bdf).mark_area(line={"color": "#1A5FB4", "strokeWidth": 3}, color="#1A5FB4", opacity=0.12).encode(
        x=alt.X("Date:T", axis=alt.Axis(labelFontSize=fs - 2, title=None, format="%d %b")),
        y=alt.Y("Rand:Q", axis=alt.Axis(labelFontSize=fs, title=None, labelExpr="'R' + format(datum.value, ',.0f')")),
        tooltip=[alt.Tooltip("Date:T", format="%d %b %Y"), alt.Tooltip("Rand:Q", format=",.0f")])
    layers = [line, alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#C62828", strokeDash=[6, 4], strokeWidth=2).encode(y="y:Q")]
    if m.method == "pay_cycle":
        layers.append(alt.Chart(pd.DataFrame({"d": [c.start for c in prof.cycles]})).mark_rule(
            color="#9AA5B1", strokeDash=[2, 4]).encode(x="d:T"))
    st.altair_chart(alt.layer(*layers).properties(height=300), width="stretch")

# ================================================================ ASK THE AI
with tab_ask:
    section("Ask a question about this client", "For example: How much was spent on takeaways each month?")
    if client is None:
        st.info("Questions need the detailed analysis, which is not set up on this computer yet (see For analysts, then Settings).")
    else:
        hist = st.session_state.setdefault("chat", [])
        with st.form("ask_form", clear_on_submit=True):
            q = st.text_input("Your question")
            asked = st.form_submit_button("Ask")
        if asked and q.strip():
            with st.spinner("Working it out..."):
                hist.insert(0, {"q": q.strip(), **ask(client, q.strip(), prof.transactions)})
        st.caption("The program works out what to look for, adds up the real transactions itself, and checks every figure in the answer.")
        for h in hist[:8]:
            st.markdown(f'<div class="note lvl-ok"><b>You asked:</b> {esc(h["q"])}</div>', unsafe_allow_html=True)
            lv = "good" if h["checked"] else "watch"
            mark = "✔ Figures checked against the transactions." if h["checked"] else "▲ Figures could not be double-checked, so only a plain count is shown."
            st.markdown(f'<div class="note lvl-{lv}"><b>Answer:</b> {esc(h["answer"])}<div class="small">{mark}</div></div>', unsafe_allow_html=True)
            if h.get("result"):
                with st.expander("How this was worked out"):
                    spec = h["spec"]
                    st.write({"looked at": spec["direction"], "categories": spec["categories"] or "all", "shop contains": spec["merchant_contains"],
                              "from": str(spec["date_from"]) if spec["date_from"] else None, "to": str(spec["date_to"]) if spec["date_to"] else None,
                              "grouped by": spec["group_by"]})
                    if h["result"]["groups"]:
                        st.dataframe(pd.DataFrame(h["result"]["groups"]).rename(columns={"total_R": "Total (R)"}), hide_index=True, width="stretch")
                    st.dataframe(pd.DataFrame(h["result"]["biggest_examples"]), hide_index=True, width="stretch")

# ================================================================ ANALYSTS
with tab_an:
    st.caption("Technical detail. All figures are calculated by the program from the transactions. When the AI is on, it chooses categories, "
               "decides the profile and writes the words, and the program checks its figures.")
    st.markdown(f"**Rule applied:** {v.rule}")
    st.markdown(f"**Summary text written by:** {prof.narrative_source}")
    st.write(prof.narrative)
    st.markdown(f"**Statement check:** {prof.reconciliation.message} ({prof.reconciliation.checked} rows). "
                f"**Pay pattern:** {m.payday_note}.")
    section("How this analysis works")
    st.markdown("The statements are read, every payment is sorted, and the client is assessed by a language model (an AI service) "
                "when detailed analysis is on. Transaction text is sent to that service with names, phone numbers and account numbers "
                "masked. The program calculates all figures itself and checks every number the model writes against the statements. "
                "With detailed analysis off, a built-in reader and fixed rules do everything on this computer.")
    with st.expander("Settings (advanced)"):
        st.text_input("Groq API key", type="password", key="cfg_key",
                      help="Kept in memory for this session only. For a permanent setup use the GROQ_API_KEY environment variable or .streamlit/secrets.toml.")
        st.selectbox("Model", MODELS, index=MODELS.index(DEFAULT_MODEL) if DEFAULT_MODEL in MODELS else 0, key="cfg_model")
        st.toggle("Use detailed analysis", value=True, key="cfg_on")
        st.toggle("Let the model read the statements (otherwise the built-in reader does)", value=True, key="cfg_reads")
        st.caption("Key found: " + ("yes" if _key else "no"))
        if client is not None and hasattr(client, "list_models") and st.button("Test connection"):
            try:
                names = client.list_models()
                st.success(f"Connected. {len(names)} models available.")
            except AIError as e:
                st.error(str(e))
        if st.button("Run the analysis again"):
            st.session_state["ai_attempted"] = None
            st.session_state.pop("ai_result", None)
            st.rerun()
        if st.session_state.get("engine_error"):
            st.warning(f"The last detailed analysis did not finish: {st.session_state['engine_error']}")
    if air:
        section("Analysis details")
        for stp in air.steps:
            st.markdown(f'{"✔" if stp["ok"] else "✖"} **{stp["name"]}.** {stp["detail"]}')
        for w_ in air.warnings:
            st.markdown(f"▲ {w_}")
        st.markdown(f"**Model:** {air.model}. **Formula check says:** {air.formula_archetype} ({air.formula_rule}). "
                    f"**Requests:** {air.usage.get('calls', 0)} sent, {air.usage.get('cached', 0)} reused from cache, "
                    f"{air.usage.get('prompt_tokens', 0):,} tokens in, {air.usage.get('completion_tokens', 0):,} out, "
                    f"{air.usage.get('retries', 0)} retries after rate limits.")
        c = air.categorisation
        if c:
            st.markdown(f"**Sorting:** {c.get('ai_rows', 0)} rows by AI, {c.get('correction_rows', 0)} by your corrections, {c.get('fallback_rows', 0)} by rule book; "
                        f"AI and rule book agree on {c.get('agree_pct')}% of {c.get('compared', 0)} comparable rows. Disagreements are flagged in the table below.")
        if air.judgement and air.judgement.rejected:
            with st.expander(f"{len(air.judgement.rejected)} AI statement(s) set aside (figures not found in the data)"):
                for r_ in air.judgement.rejected:
                    st.markdown(f"- {r_}")
        with st.expander("What the plain formula found (second opinion)"):
            for e in air.formula_evidence:
                st.markdown(f"- {e.text}")
    by_id = {t.id: t for t in prof.transactions}
    section("Evidence")
    for e in v.evidence:
        lv = {"positive": "good", "negative": "alert", "warning": "watch", "neutral": "ok"}[e.tone]
        st.markdown(f'<div class="note lvl-{lv}" style="margin:0.3rem 0">{LEVEL_ICON[lv]} {esc(e.text)}</div>', unsafe_allow_html=True)
        if e.txn_ids:
            with st.expander(f"See the {len(e.txn_ids)} biggest transactions behind this"):
                st.dataframe(pd.DataFrame([{"Date": by_id[i].date, "Description": by_id[i].description,
                                            "Amount (R)": by_id[i].amount_cents / 100} for i in e.txn_ids]),
                             hide_index=True, width="stretch")

    section("Transactions and corrections")
    review = sum(any(f in t.flags for f in ("needs_review", "ai_rule_disagree")) for t in prof.transactions)
    st.caption(f"{len(prof.transactions)} transactions, {review} need review. Change a category and save: "
               "the app remembers it for that shop from now on.")
    df = pd.DataFrame([{"id": t.id, "date": t.date, "description": t.description, "amount (R)": t.amount_cents / 100,
                        "category": t.category, "how": t.category_source, "recurring": t.recurring,
                        "flags": ", ".join(t.flags)} for t in prof.transactions])
    only_review = st.checkbox("Only show rows needing review", value=review > 0)
    view = df[df["flags"].str.contains("needs_review|reconciliation_break|ai_rule_disagree")] if only_review else df
    edited = st.data_editor(
        view, hide_index=True, width="stretch", key=f"editor_{only_review}",
        disabled=[c for c in df.columns if c != "category"],
        column_config={"category": st.column_config.SelectboxColumn("category", options=ALL_CATEGORIES, required=True)})
    if st.button("Save corrections and re-run", type="primary"):
        changed = edited[edited["category"].values != view["category"].values]
        for _, row in changed.iterrows():
            save_correction(merchant_key(row["description"]), row["category"])
        if len(changed):
            st.success(f"Saved {len(changed)} correction(s).")
            st.rerun()
        else:
            st.info("Nothing changed.")
    st.download_button("Download full profile (JSON)", prof.model_dump_json(indent=2), file_name="profile.json", mime="application/json")

st.markdown('<div class="foot">Decision support only. This is not financial advice and not a credit decision.</div>', unsafe_allow_html=True)
