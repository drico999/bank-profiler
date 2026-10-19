"""Measure the system against synthetic ground truth. Run:  python -m profiler.evaluate

This is the habit that separates a demo from engineering: every claim has a number.
Caveat to remember: the synthetic data was written by us, so scores here are an UPPER bound
on real-world performance. Re-run on your own anonymised statements for the honest number.
"""
import json
from collections import Counter
from pathlib import Path

from .categorise import categorise, detect_recurring
from .parsers import parse_file
from .pipeline import analyse
from .reconcile import reconcile


def evaluate(sample_dir="sample_data", llm=None) -> dict:
    d = Path(sample_dir)
    files = sorted(list(d.glob("*.csv")) + list(d.glob("*.pdf")))
    cat_ok = cat_total = 0
    recon_ok = arch_ok = arch_total = 0
    misses = Counter()
    for f in files:
        truth = json.loads((d / f"{f.stem.split('_')[0]}.truth.json").read_text())
        st = parse_file(f)
        for i, t in enumerate(st.transactions):
            t.id = i
        recon_ok += reconcile(st.transactions).ok
        categorise(st.transactions, llm=llm, corrections={})
        detect_recurring(st.transactions)
        assert len(st.transactions) == len(truth["categories"]), f"row count mismatch in {f.name}"
        for t, want in zip(st.transactions, truth["categories"]):
            cat_total += 1
            if t.category == want:
                cat_ok += 1
            else:
                misses[(want, t.category)] += 1
        p = analyse([f], llm=llm, corrections={})
        arch_total += 1
        arch_ok += p.verdict.archetype == truth["expected_archetype"]
    return {
        "files": len(files),
        "reconciled": f"{recon_ok}/{len(files)}",
        "category_accuracy": round(cat_ok / cat_total, 4),
        "archetype_accuracy": f"{arch_ok}/{arch_total}",
        "top_category_misses": [(f"{a} -> {b}", n) for (a, b), n in misses.most_common(5)],
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2))
