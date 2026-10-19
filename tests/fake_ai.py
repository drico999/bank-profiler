"""A scripted stand-in for the model. It reads input the way a competent model would and can be told to
make the mistakes real models make, so we can prove the safety checks catch them. It does NOT prove
real-model quality; that needs a live key."""
import csv
import json
import re

from profiler.ai.client import AIError, CallRecord
from profiler.categorise.normalise import merchant_key
from profiler.categorise.rules import match_rule

INFORMAL = {"MAMA THANDI SPAZA": "groceries", "BONGANI TUCKSHOP": "groceries", "FRESH PRODUCE MARKET": "groceries",
            "KASI GRILL": "dining", "AUNTY NOMSA FOOD": "dining", "LERATO HAIR SALON": "shopping", "SIPHO HARDWARE": "shopping"}
PDF_LINE = re.compile(r"^(\d{1,2} \w{3} \d{4})\s+(.+?)\s+([\d,]+\.\d{2})(Cr)?\s+([\d,]+\.\d{2})(Cr|Dr)?$")


class FakeAI:
    model = "fake-model"
    name = "Fake / scripted"

    def __init__(self, flip_once=False, drop_once=False, always_flip=False, hallucinate=False, bad_archetype=False,
                 fail_tasks=(), bad_answer=False, injected_category=None):
        self.flip_once, self.drop_once, self.always_flip = flip_once, drop_once, always_flip
        self.hallucinate, self.bad_archetype, self.fail_tasks, self.bad_answer = hallucinate, bad_archetype, set(fail_tasks), bad_answer
        self.injected_category = injected_category
        self.calls, self.log, self._flipped, self._dropped = [], [], False, False

    def chat_json(self, task, system, user, model=None, max_tokens=0):
        self.calls.append((task, system, user))
        self.log.append(CallRecord(task, self.model, prompt_tokens=len(user) // 4, completion_tokens=50, seconds=0.1))
        if task in self.fail_tasks:
            raise AIError(f"scripted failure in {task}")
        return getattr(self, f"_{task}")(user)

    # ---------------------------------------------------------------- extract
    def _extract(self, user):
        p = json.loads(user)
        header, feedback = p["column_header"], "correction_needed" in p
        out = []
        for n, text in p["lines"]:
            m = PDF_LINE.match(text.strip())
            if m:
                date, desc, amt, cr, bal, balcr = m.groups()
                row = {"date": date, "description": desc, "amount": amt + (cr or ""), "direction": "credit" if cr else "debit",
                       "balance": bal + (balcr or "Cr")}
            else:
                f = next(csv.reader([text]))
                if "Money In" in header:
                    inn, outt = f[2], f[3]
                    row = {"date": f[0], "description": f[1], "amount": inn or outt, "direction": "credit" if inn else "debit", "balance": f[4]}
                else:
                    row = {"date": f[0], "description": f[1], "amount": f[2], "direction": "debit" if f[2].startswith("-") else "credit", "balance": f[3]}
            out.append({"line": n, **row})
        if self.always_flip or (self.flip_once and not feedback and not self._flipped and len(out) > 3):
            out[2]["direction"] = "credit" if out[2]["direction"] == "debit" else "debit"
            self._flipped = True
        if self.drop_once and not feedback and not self._dropped and len(out) > 5:
            out.pop(4)
            self._dropped = True
        return {"transactions": out}

    # ---------------------------------------------------------------- categorise
    def _categorise(self, user):
        items = []
        for it in json.loads(user)["items"]:
            key, credit = it["merchant"], it["direction"] == "credit"
            cat = next((v for n, v in INFORMAL.items() if key.startswith(n)), None)
            if self.injected_category and "IGNORE" in key:
                cat = self.injected_category
            if cat is None:
                hit = match_rule(it["example"], credit)
                cat = hit[0] if hit else ("other_income" if credit else "unknown")
            items.append({"id": it["id"], "merchant": key.title(), "category": cat, "confidence": 0.9})
        return {"items": items}

    # ---------------------------------------------------------------- judge
    def _judge(self, user):
        d = json.loads(user.split("\nPrevious reply")[0])
        f, lines = d["FACTS"], d["TRANSACTIONS"]
        p100, weeks, cv = f["per_R100_earned"], f["safety_net_weeks"], f["income_changes_by_percent_between_months"]
        kept = p100["kept"]
        if cv >= 30:
            arche = "Volatile"
        elif kept >= 15 and weeks >= 4.3:
            arche = "Saver"
        elif kept >= 5:
            arche = "Balanced"
        elif p100["fixed_bills"] + p100["loan_repayments"] >= 55 or p100["loan_repayments"] >= 25:
            arche = "Stretched"
        else:
            arche = "Spender"
        sal = next((l.split("|")[0] for l in lines if "|salary|" in l), None)
        insights = [
            {"key": "kept", "level": "good" if kept >= 15 else "watch", "title": "Money kept", "headline": f"R{kept} of every R100 earned", "detail": "is kept after all spending."},
            {"key": "net", "level": "ok", "title": "Safety net", "headline": f"About {weeks:.0f} weeks", "detail": "of spending could be covered."},
            {"key": "fixed", "level": "ok", "title": "Fixed bills", "headline": f"R{p100['fixed_bills']} of every R100 earned", "detail": "is already spoken for."},
        ]
        summary = f"This client keeps R{kept} of every R100 earned. Fixed bills take R{p100['fixed_bills']} of every R100."
        if self.hallucinate:
            insights.append({"key": "bad", "level": "alert", "title": "Invented", "headline": "R987 654 of every R100 earned", "detail": "made up."})
            summary += " They also saved R555 555 last month."
        return {"archetype": "Wizard" if self.bad_archetype else arche, "confidence": 0.85, "confidence_reasons": ["Clear pattern across months"],
                "summary": summary, "evidence": [{"text": f"Kept R{kept} of every R100 earned.", "tone": "positive", "txn_ids": [int(sal)] if sal else [99999]}],
                "insights": insights}

    # ---------------------------------------------------------------- ask
    def _plan_query(self, user):
        q = json.loads(user)["question"].lower()
        if "should" in q or "lend" in q:
            return {"unanswerable_reason": "that is advice, not something the transactions can show"}
        spec = {"direction": "debit", "categories": [], "group_by": "month" if "month" in q else "none"}
        if any(w in q for w in ("takeaway", "eating out", "restaurant")):
            spec["categories"] = ["dining"]
        if "betting" in q:
            spec["categories"] = ["gambling"]
        return spec

    def _answer(self, user):
        r = json.loads(user)["RESULT"]
        t = f"{r['matching_transactions']} transactions came to R{r['total_R']}."
        return {"answer": t + (" That is R123 456 more than last year." if self.bad_answer else "")}
