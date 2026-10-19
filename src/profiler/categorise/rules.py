"""Rules-first categorisation with South African merchants and payment rails.

Order matters: the first matching rule wins, so specific rules sit above general ones
(e.g. UBER EATS before UBER, fees before cash withdrawals).
Each rule: (regex, category, direction, brand?)  - brand=True means the match is the merchant name.
"""
import re

R = []


def rule(pattern, category, direction="debit", brand=False):
    R.append((re.compile(pattern, re.I), category, direction, brand))


# ---- credits (money in)
rule(r"SALARY|PAYROLL|WAGES", "salary", "credit")
rule(r"SASSA|\bSRD\b|SOCIAL GRANT|CHILD SUPPORT GRANT", "grant_income", "credit")
rule(r"LOAN (DISBURSEMENT|PAYOUT|ADVANCE)|CREDIT LIMIT INCREASE|CASH ADVANCE", "loan_proceeds", "credit")
rule(r"TRANSFER FROM (SAVINGS|POCKET|OWN)|OWN ACCOUNT TRANSFER|TFSA WITHDRAW", "transfer_in", "credit")
rule(r"REFUND|REVERSAL|CHARGEBACK", "refund", "credit")
rule(r"(PAYSHAP|CAPITEC PAY|PAYMENT|EFT|APP PAYMENT)\s*(FROM)?\s*(MOM|DAD|MOTHER|FATHER|SISTER|BROTHER|GRAN)", "family_in", "credit")
rule(r"PAYSHAP|PAYMENT FROM|EFT CREDIT|INSTANT MONEY|\bCLIENT\b|\bINV\b", "other_income", "credit")

# ---- debits: money moved, not spent
rule(r"TRANSFER TO (SAVINGS|POCKET|TFSA)|\bTFSA\b|RETIREMENT ANNUITY|\bRA CONTRIB|SAVINGS DEPOSIT|SAVINGS POCKET", "savings", "debit")
# fees BEFORE cash/ATM so 'CASH WITHDRAWAL FEE' is a fee
rule(r"\bFEES?\b|SERVICE CHARGE|OVERDRAFT INTEREST|INTEREST DEBIT|SMS NOTIFICATION|ADMIN CHARGE", "fees", "debit")
# ---- gambling
rule(r"HOLLYWOODBETS|BETWAY|SPORTINGBET|SUPABETS|YESPLAY|SPORTSBET|LOTTO|POWERBALL|LOTTERY", "gambling", "debit", True)
# ---- groceries (Woolworths Food before generic Woolworths)
rule(r"SHOPRITE|CHECKERS|PICK N PAY|\bPNP\b|WOOLWORTHS FOOD|\bSPAR\b|FOOD LOVER|\bBOXER\b|USAVE|OK FOODS", "groceries", "debit", True)
# ---- dining (Uber Eats before Uber)
rule(r"UBER EATS|MR D FOOD|KFC|NANDOS|STEERS|MUGG|DEBONAIRS|WIMPY|ROMANS PIZZA|SPUR\b|OCEAN BASKET|MCDONALD|CHICKEN LICKEN|KAUAI", "dining", "debit", True)
# ---- transport
rule(r"\bUBER\b|\bBOLT\b|SANRAL|E-?TOLL|GAUTRAIN|TAXI|ENGEN|\bSHELL\b|\bBP\b|SASOL|CALTEX|TOTAL ENERGIES|\bFUEL\b", "transport", "debit", True)
# ---- airtime & data
rule(r"AIRTIME|PREPAID DATA|DATA BUNDLE|VODACOM|\bMTN\b|TELKOM|CELL C|\bRAIN\b|AFRIHOST", "airtime_data", "debit", True)
# ---- committed costs
rule(r"ELECTRICITY|CITY POWER|ESKOM|MUNICIPAL|CITY OF (JOHANNESBURG|CAPE TOWN|TSHWANE|EKURHULENI)|WATER ACCOUNT|WATER & RATES", "utilities", "debit", True)
rule(r"\bRENT\b|RENTAL|BODY CORPORATE|\bLEVY\b", "rent", "debit")
rule(r"MEDICAL AID|DISCOVERY HEALTH|BONITAS|MOMENTUM HEALTH|MEDSCHEME|\bGEMS\b|PHARMACY|DIS-?CHEM|DOCTOR|DENTIST", "medical", "debit", True)
rule(r"FUNERAL|OLD MUTUAL|SANLAM|OUTSURANCE|DISCOVERY INSURE|HOLLARD|MOMENTUM LIFE|LIFE COVER|INSURANCE|ASSURANCE|BURIAL SOCIETY|STOKVEL", "insurance", "debit", True)
rule(r"LOAN|INSTALMENT|CREDIT CARD|VEHICLE FINANCE|WESBANK|\bMFC\b|HOME LOAN|MICROFINANCE|MICRO ?LEND|PERSONAL LOAN", "debt_repayment", "debit")
# ---- entertainment & subscriptions
rule(r"NETFLIX|SHOWMAX|DSTV|MULTICHOICE|SPOTIFY|YOUTUBE|DISNEY|AMAZON PRIME|APPLE\.COM|GOOGLE ONE|CINEMA|NU METRO|VIRGIN ACTIVE|PLANET FITNESS|\bGYM\b", "entertainment", "debit", True)
# ---- family support
rule(r"(PAYMENT|PAY|PAYSHAP|EFT|APP PAYMENT) TO (MOM|DAD|MOTHER|FATHER|SISTER|BROTHER|GRAN)|CAPITEC PAY:?\s*(MOM|DAD|MOTHER|FATHER|SISTER|BROTHER|GRAN)|REMITTANCE", "family_support", "debit")
# ---- cash (after fees)
rule(r"CASH WITHDRAWAL|\bATM\b|CASH ?SEND|EWALLET|CASH@TILL|CASH BACK", "cash_withdrawal", "debit")
# ---- shopping
rule(r"TAKEALOT|MR PRICE|\bPEP\b|CLICKS|\bGAME\b|WOOLWORTHS|SHEIN|TEMU|AMAZON|BUILDERS|MAKRO|TOTAL SPORTS|TRUWORTHS|FOSCHINI", "shopping", "debit", True)


def match_rule(description: str, is_credit: bool):
    """Return (category, merchant_or_None) or None."""
    direction = "credit" if is_credit else "debit"
    for rx, cat, d, brand in R:
        if d != direction:
            continue
        m = rx.search(description)
        if m:
            return cat, (m.group(0).title().strip() if brand else None)
    return None
