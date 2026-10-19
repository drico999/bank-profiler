"""Command line:  python -m profiler.cli analyse sample_data/saver_capitec.csv [--json]"""
import argparse
import json
import os
import sys

from .categorise.llm import LLMCategoriser, default_client
from .money import format_rand
from .pipeline import analyse


def main(argv=None):
    ap = argparse.ArgumentParser(prog="profiler")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyse", help="analyse one or more statements for ONE client")
    a.add_argument("files", nargs="+")
    a.add_argument("--password", help="PDF password (applied to all PDFs)")
    a.add_argument("--json", action="store_true", help="print full profile as JSON")
    a.add_argument("--llm", action="store_true", help="old optional Anthropic fallback (needs ANTHROPIC_API_KEY)")
    a.add_argument("--ai", action="store_true", help="let the AI read, sort and judge (needs GROQ_API_KEY)")
    sub.add_parser("generate", help="write synthetic sample statements to ./sample_data")
    args = ap.parse_args(argv)

    if args.cmd == "generate":
        from .synthetic import generate_all
        print(json.dumps(generate_all("sample_data"), indent=2))
        return 0

    if args.ai:
        from .ai import GroqClient
        from .pipeline_ai import analyse_with_ai
        key = os.environ.get("GROQ_API_KEY", "").strip()
        if not key:
            print("Set GROQ_API_KEY first (see README).", file=sys.stderr)
            return 2
        ai = GroqClient(key, cache_path=os.path.join(os.environ.get("PROFILER_DATA_DIR", "data"), "ai_cache.json"))
        res = analyse_with_ai(args.files, ai, passwords={os.path.basename(f): args.password for f in args.files} if args.password else None,
                              progress=lambda m: print("  ..", m, file=sys.stderr))
        p = res.profile
        if args.json:
            print(res.model_dump_json(indent=2))
            return 0
        for s_ in res.ai.steps:
            print(f"  {'OK ' if s_['ok'] else 'BAD'} {s_['name']}: {s_['detail']}")
        client = None
    else:
        client = default_client() if args.llm else None
    if args.llm and client is None:
        print("No ANTHROPIC_API_KEY set - continuing with rules only.", file=sys.stderr)
    llm = LLMCategoriser(client, cache_path=os.path.join(os.environ.get("PROFILER_DATA_DIR", "data"), "llm_cache.json")) if client else None
    passwords = {os.path.basename(f): args.password for f in args.files} if args.password else None
    if not args.ai:
        p = analyse(args.files, passwords=passwords, llm=llm, narrative_client=client)
    if args.json:
        print(p.model_dump_json(indent=2))
        return 0
    v, m = p.verdict, p.metrics
    print(f"\n  {v.archetype.upper()}   score {v.score}/100   confidence {v.confidence_label} ({v.confidence})")
    print(f"  rule: {v.rule}\n")
    print("  " + p.narrative + "\n")
    for e in v.evidence:
        print(f"   - {e.text}")
    for r in v.confidence_reasons:
        print(f"   ! {r}")
    print(f"\n  {m.payday_note}. Reconciliation: {p.reconciliation.message}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
