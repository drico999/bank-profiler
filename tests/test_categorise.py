import json
from datetime import date

from profiler.categorise import categorise, merchant_key, save_correction, load_corrections
from profiler.categorise.llm import LLMCategoriser
from profiler.models import Transaction
from profiler.redact import redact
from profiler.parsers import parse_file
from conftest import FakeClient, truth


def tx(desc, amount=-10000):
    return Transaction(date=date(2026, 1, 1), description=desc, amount_cents=amount)


def cat(desc, amount=-10000):
    t = tx(desc, amount)
    categorise([t], corrections={})
    return t.category


def test_sa_merchants_and_rails():
    assert cat("POS PURCHASE SHOPRITE 0231 SANDTON") == "groceries"
    assert cat("POS PURCHASE UBER EATS 1234") == "dining"          # not transport
    assert cat("Uber Trip") == "transport"
    assert cat("PREPAID ELECTRICITY CITY POWER") == "utilities"
    assert cat("PREPAID AIRTIME VODACOM") == "airtime_data"
    assert cat("CAPITEC PAY: HOLLYWOODBETS") == "gambling"
    assert cat("FEE CASH WITHDRAWAL") == "fees"                    # not cash
    assert cat("CASH WITHDRAWAL ATM 4521") == "cash_withdrawal"
    assert cat("FNB APP PAYMENT TO MOM") == "family_support"
    assert cat("Capitec Pay: Mom") == "family_support"
    assert cat("DEBIT ORDER OLD MUTUAL FUNERAL COVER") == "insurance"
    assert cat("COFFEE SHOP 12") != "fees"                         # 'FEE' inside a word


def test_credits():
    assert cat("ACB CREDIT ACME SALARY", 2000000) == "salary"
    assert cat("SASSA GRANT", 35000) == "grant_income"
    assert cat("LOAN DISBURSEMENT QUICKCASH", 300000) == "loan_proceeds"
    assert cat("TRANSFER FROM SAVINGS POCKET", 500000) == "transfer_in"
    assert cat("SOMETHING ODD 99", 50000) == "unknown"            # never assume unknown deposits are income


def test_merchant_key_strips_noise():
    assert merchant_key("POS PURCHASE SHOPRITE 0231 SANDTON") == merchant_key("POS PURCHASE SHOPRITE 9981 SOWETO")


def test_corrections_override_rules_and_persist(tmp_path):
    p = tmp_path / "c.json"
    save_correction(merchant_key("POS PURCHASE MAMA THANDI SPAZA 1"), "groceries", p)
    t = tx("POS PURCHASE MAMA THANDI SPAZA 9876")
    categorise([t], corrections=load_corrections(p))
    assert (t.category, t.category_source) == ("groceries", "correction")


def test_llm_fallback_validates_and_never_sees_amounts():
    def reply(prompt):
        keys = json.loads(prompt)
        return json.dumps([{"key": k, "merchant": k.title(), "category": "groceries", "confidence": 0.9} for k in keys]
                          + [{"key": "INVENTED KEY", "category": "gambling", "confidence": 1}])
    client = FakeClient(reply)
    t = tx("POS PURCHASE MAMA THANDI SPAZA 9876", -45000)
    categorise([t], llm=LLMCategoriser(client), corrections={})
    assert t.category == "groceries" and t.category_source == "llm"
    sent = client.prompts[0]
    assert "450" not in sent and "9876" not in sent               # no amounts, no reference numbers


def test_llm_invalid_category_becomes_unknown_and_flagged():
    client = FakeClient(lambda p: json.dumps([{"key": k, "category": "crypto_riches", "confidence": 0.99} for k in json.loads(p)]))
    t = tx("MYSTERY SHOP")
    categorise([t], llm=LLMCategoriser(client), corrections={})
    assert t.category == "unknown" and "needs_review" in t.flags


def test_llm_garbage_response_is_safe():
    client = FakeClient(lambda p: "sorry, I can't do that")
    t = tx("MYSTERY SHOP")
    categorise([t], llm=LLMCategoriser(client), corrections={})
    assert t.category == "unknown"


def test_llm_cache_avoids_repeat_calls(tmp_path):
    client = FakeClient(lambda p: json.dumps([{"key": k, "category": "dining", "confidence": 0.9} for k in json.loads(p)]))
    llm = LLMCategoriser(client, cache_path=tmp_path / "cache.json")
    llm.categorise(["KASI GRILL"])
    LLMCategoriser(client, cache_path=tmp_path / "cache.json").categorise(["KASI GRILL"])
    assert len(client.prompts) == 1


def test_redaction():
    s = redact("PAYSHAP TO THABO MOKOENA 0821234567 ID 9001015009087 ACC 1234567890")
    assert "THABO" not in s and "0821234567" not in s and "9001015009087" not in s and "1234567890" not in s


def test_llm_lifts_category_accuracy(samples):
    """Rules alone miss informal merchants; a (fake, perfect-for-informal) LLM closes the gap."""
    informal = {"MAMA THANDI SPAZA": "groceries", "BONGANI TUCKSHOP": "groceries", "FRESH PRODUCE MARKET": "groceries",
                "KASI GRILL": "dining", "AUNTY NOMSA FOOD": "dining", "LERATO HAIR SALON": "shopping", "SIPHO HARDWARE": "shopping"}
    def reply(prompt):
        out = []
        for k in json.loads(prompt):
            base = next((v for n, v in informal.items() if k.startswith(n)), "unknown")
            out.append({"key": k, "category": base, "confidence": 0.9})
        return json.dumps(out)
    st = parse_file(samples / "spender_fnb.csv")
    want = truth(samples, "spender")["categories"]
    base = [Transaction(**t.model_dump()) for t in st.transactions]
    categorise(base, corrections={})
    boosted = [Transaction(**t.model_dump()) for t in st.transactions]
    categorise(boosted, llm=LLMCategoriser(FakeClient(reply)), corrections={})
    acc = lambda ts: sum(t.category == w for t, w in zip(ts, want)) / len(want)
    assert acc(boosted) > acc(base) and acc(boosted) > 0.99
