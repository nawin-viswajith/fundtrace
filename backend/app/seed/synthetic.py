"""Deterministic SYNTHETIC banking world for the demo, with ground truth for evaluation.

Nothing here is real customer or bank data. All names, accounts, references and devices are
generated. Times are anchored to `anchor` (normally "now") so SLA clocks and the golden-hour story
stay meaningful whenever the demo is (re)seeded.
"""
from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

SELF = "INST-SELF"
EXT_A, EXT_B, CASH = "INST-EXT-A", "INST-EXT-B", "INST-CASH"

FIRST = ["Aarav", "Diya", "Kabir", "Meera", "Rohan", "Ananya", "Vikram", "Isha", "Arjun", "Sara", "Neel", "Tara", "Dev", "Riya",
         "Kiran", "Asha", "Imran", "Leela", "Samir", "Nisha", "Farah", "Joel", "Lakshmi", "Omar", "Pooja", "Ravi", "Sneha", "Tenzin"]
LAST = ["Iyer", "Menon", "Shah", "Rao", "Khan", "Das", "Pillai", "Gupta", "Nair", "Bose", "Reddy", "Singh", "Joshi", "Mathew"]


@dataclass
class Dataset:
    anchor: datetime
    institutions: list[dict] = field(default_factory=list)
    customers: list[dict] = field(default_factory=list)
    accounts: list[dict] = field(default_factory=list)
    devices: list[dict] = field(default_factory=list)
    auth_events: list[dict] = field(default_factory=list)
    raw_transactions: list[dict] = field(default_factory=list)
    cases: list[dict] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    truth: dict = field(default_factory=dict)


class _B:
    def __init__(self, anchor: datetime, seed: int):
        self.d = Dataset(anchor=anchor)
        self.rng = random.Random(seed)
        self.n_acct = 100100
        self.n_txn = 4000000
        self.n_auth = 700000
        self.n_dev = 9000
        self.n_cust = 1000
        self.ref = 628900000000
        self.reserved: set[str] = set()

    # ---- entities ---------------------------------------------------------------------------
    def name(self) -> str:
        return f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)}"

    def customer(self, name: str | None = None, lang: str = "en") -> str:
        self.n_cust += 1
        cid = f"CUST-{self.n_cust}"
        self.d.customers.append({"id": cid, "display_name": (name or self.name()) + " (synthetic)", "segment": "retail",
                                 "preferred_language": lang})
        return cid

    def account(self, holder: str, inst: str = SELF, kind: str = "savings", balance: float | None = 50000,
                opened_days: float | None = 900, customer: str | None = None, reserve: bool = False) -> str:
        self.n_acct += 1
        aid = f"ACC-{self.n_acct}"
        ext = inst != SELF
        self.d.accounts.append({
            "id": aid, "customer_id": customer, "institution_id": inst, "kind": "external" if ext and kind != "cash" else kind,
            "holder_label": holder + ("" if "synthetic" in holder else " (synthetic)"),
            "masked_number": f"XXXX{self.rng.randint(1000, 9999)}",
            "opened_at": None if ext or opened_days is None else self.d.anchor - timedelta(days=opened_days),
            "opening_balance_minor": None if ext or balance is None else int(round(balance * 100)), "currency": "INR"})
        if reserve:
            self.reserved.add(aid)
        return aid

    def device(self, label: str, first_seen: datetime) -> str:
        self.n_dev += 1
        did = f"DEV-{self.n_dev}"
        self.d.devices.append({"id": did, "fingerprint_hash": hashlib.sha256(did.encode()).hexdigest(), "label": label,
                               "first_seen_at": first_seen})
        return did

    def auth(self, account: str, outcome: str, at: datetime, device: str | None, etype: str = "login") -> str:
        self.n_auth += 1
        aid = f"AUTH-{self.n_auth}"
        self.d.auth_events.append({"id": aid, "account_id": account, "device_id": device, "ip_hash": hashlib.sha256(f"ip{device}".encode()).hexdigest()[:16],
                                   "event_type": etype, "outcome": outcome, "occurred_at": at, "source_system": "digital_auth",
                                   "source_record_id": f"da-{self.n_auth}"})
        return aid

    def txn(self, src: str, dst: str, amount: float, at: datetime, channel: str = "UPI", status: str = "posted",
            device: str | None = None, narrative: str = "", reference: str | None | bool = True, reversal_of: str | None = None,
            extra_sources: list[dict] | None = None) -> str:
        self.n_txn += 1
        tid = f"TXN-{self.n_txn}"
        self.ref += self.rng.randint(1, 97)
        ref = str(self.ref) if reference is True else (reference or None)
        rec = {"id": tid, "source_system": "core", "source_record_id": f"cbs-{self.n_txn}", "debit_account_id": src,
               "credit_account_id": dst, "amount": f"{amount:.2f}", "currency": "INR", "status": status, "channel": channel,
               "reference": ref, "occurred_at": at.isoformat() + "Z", "posted_at": (at + timedelta(seconds=4)).isoformat() + "Z",
               "device_id": device, "narrative": narrative, "reversal_of_id": reversal_of}
        self.d.raw_transactions.append(rec)
        for es in extra_sources or []:
            self.d.raw_transactions.append({**rec, "id": tid + "-" + es["source_system"], **es})
        return tid


def build(anchor: datetime, seed: int = 2026) -> Dataset:
    b = _B(anchor.replace(second=0, microsecond=0), seed)
    d = b.d
    A = d.anchor
    d.institutions = [
        {"id": SELF, "name": "FundTrace Demo Bank (synthetic)", "kind": "self"},
        {"id": EXT_A, "name": "Other Bank A (synthetic)", "kind": "external"},
        {"id": EXT_B, "name": "Other Bank B (synthetic)", "kind": "external"},
        {"id": CASH, "name": "Cash withdrawal (ATM)", "kind": "external"},
    ]

    # ---- background world ---------------------------------------------------------------------
    employers = [b.account(f"{n} Pvt Ltd payroll", kind="current", balance=50_000_000, opened_days=3000, reserve=True)
                 for n in ("Nimbus Tech", "Coastal Foods", "Orbit Logistics", "Lotus Health")]
    merchants = {n: b.account(n, kind="merchant", balance=200_000, opened_days=2000, reserve=True)
                 for n in ("FreshKart Grocery", "PowerGrid Electricity", "AirLink Telecom", "StreamPlus", "FuelUp", "MediCare Pharmacy")}
    hub = b.account("QuickMart marketplace settlement", kind="merchant", balance=5_000_000, opened_days=2500, reserve=True)
    merchants["QuickMart"] = hub
    ext_payees = [b.account(f"{b.name()}", inst=b.rng.choice([EXT_A, EXT_B])) for _ in range(25)]
    settle_ext = b.account("Merchant settlement pool", inst=EXT_A)
    atm = b.account("ATM cash", inst=CASH, kind="cash")

    bg: list[tuple[str, str, str]] = []  # (customer, account, device)
    for _ in range(70):
        cid = b.customer()
        bal = b.rng.choice([15_000, 40_000, 90_000, 150_000, 300_000])
        acc = b.account(next(c["display_name"] for c in d.customers if c["id"] == cid), balance=bal,
                        opened_days=b.rng.randint(400, 3000), customer=cid)
        dev = b.device("Phone", A - timedelta(days=b.rng.randint(200, 900)))
        bg.append((cid, acc, dev))

    start = A - timedelta(days=90)
    raw_bg: list[tuple] = []

    def rand_time(lo: datetime, hi: datetime) -> datetime:
        t = lo + timedelta(seconds=b.rng.randint(0, int((hi - lo).total_seconds())))
        return t.replace(hour=b.rng.randint(3, 17), second=0)  # 08:30–23:30 IST in UTC terms

    for month in range(3):
        pay_day = start + timedelta(days=30 * month + 1)
        for cid, acc, dev in bg:
            if b.rng.random() < 0.7:
                raw_bg.append((b.rng.choice(employers), acc, b.rng.choice([28_000, 45_000, 65_000, 85_000, 120_000]), pay_day.replace(hour=4), "NEFT", None, "Salary"))
    for cid, acc, dev in bg:
        for _ in range(b.rng.randint(8, 22)):
            m = b.rng.choice(list(merchants.values()))
            raw_bg.append((acc, m, b.rng.choice([149, 299, 450, 799, 1200, 2300, 3999, 5600]), rand_time(start, A - timedelta(hours=3)), "UPI", dev, "Purchase"))
        for _ in range(b.rng.randint(0, 4)):
            other = b.rng.choice(bg)[1]
            if other != acc:
                raw_bg.append((acc, other, b.rng.choice([500, 1500, 2500, 6000, 12000]), rand_time(start, A - timedelta(hours=3)), "UPI", dev, "Transfer"))
        if b.rng.random() < 0.5:
            raw_bg.append((acc, b.rng.choice(ext_payees), b.rng.choice([8000, 15000, 22000]), rand_time(start, A - timedelta(hours=3)), "IMPS", dev, "Rent"))
        if b.rng.random() < 0.3:
            raw_bg.append((acc, atm, b.rng.choice([2000, 5000, 10000]), rand_time(start, A - timedelta(hours=3)), "ATM", None, "Cash withdrawal"))
    # merchants settle out daily; the marketplace pays many sellers (a hub)
    for day in range(90):
        t = (start + timedelta(days=day)).replace(hour=20)
        for name, macc in merchants.items():
            if name != "QuickMart" and b.rng.random() < 0.5:
                raw_bg.append((macc, settle_ext, b.rng.choice([5000, 12000, 30000]), t, "NEFT", None, "Settlement"))
    for i in range(70):
        t = A - timedelta(hours=70) + timedelta(minutes=i * 59)
        raw_bg.append((hub, b.rng.choice(ext_payees + [x[1] for x in bg]), b.rng.choice([1800, 4200, 9500, 15000]), t, "IMPS", None, "Seller payout"))

    # apply in time order without overdrawing in-bank accounts
    bal = {a["id"]: (a["opening_balance_minor"] or 0) for a in d.accounts if a["institution_id"] == SELF}
    for src, dst, amt, t, ch, dev, narr in sorted(raw_bg, key=lambda x: x[3]):
        minor = int(amt * 100)
        if src in bal and bal[src] < minor:
            continue
        if src in bal:
            bal[src] -= minor
        if dst in bal:
            bal[dst] += minor
        if dev:
            b.auth(src, "success", t - timedelta(minutes=b.rng.randint(1, 4)), dev)
            if b.rng.random() < 0.03:
                b.auth(src, "failure", t - timedelta(minutes=6), dev)
        b.txn(src, dst, amt, t, channel=ch, device=dev, narrative=narr)

    def history(acc: str, dev: str, n: int = 12) -> None:
        """Ordinary prior activity for a scenario customer (baseline for unusual-amount checks)."""
        for i in range(n):
            t = A - timedelta(days=80 - i * 6, hours=b.rng.randint(0, 5))
            m = b.rng.choice(list(merchants.values())[:6])
            b.auth(acc, "success", t - timedelta(minutes=2), dev)
            b.txn(acc, m, b.rng.choice([350, 899, 1450, 2600, 4100]), t, device=dev, narrative="Purchase")

    cases: list[dict] = d.cases
    truth: dict = d.truth

    def case(cid: str, scenario: str, txn: str, customer: str, category: str, allegation: str, reported: datetime, status: str,
             owner: str | None, lang: str = "en") -> None:
        cases.append({"id": cid, "scenario": scenario, "disputed_txn_id": txn, "customer_id": customer, "category": category,
                      "allegation": allegation, "allegation_language": lang, "reported_at": reported, "status": status, "owner": owner})

    # ---- S3 first (it creates the mule history used by S1) -----------------------------------------
    fraud_dev = b.device("Unrecognised Android", A - timedelta(days=6, hours=1))
    mule_b = b.account("Rahul K", balance=1200, opened_days=9, customer=b.customer("Rahul K"), reserve=True)
    mule_c = b.account("Sunil P", balance=500, opened_days=40, customer=b.customer("Sunil P"), reserve=True)
    ext_d = b.account("Account at Other Bank A", inst=EXT_A)
    ext_e = b.account("Account at Other Bank B", inst=EXT_B)
    ext_f = b.account("Account at Other Bank B", inst=EXT_B)
    mule_dev = b.device("Shared handset", A - timedelta(days=9))

    cx = b.customer("Victim X")
    acc_x = b.account("Victim X savings", balance=60_000, opened_days=1500, customer=cx, reserve=True)
    dev_x = b.device("Phone", A - timedelta(days=700))
    history(acc_x, dev_x)
    t3a = A - timedelta(days=6)
    for i in range(3):
        b.auth(acc_x, "failure", t3a - timedelta(minutes=9 - i), fraud_dev)
    b.auth(acc_x, "success", t3a - timedelta(minutes=4), fraud_dev)
    s3a = b.txn(acc_x, mule_b, 15000, t3a, device=fraud_dev, narrative="UPI transfer")
    b.txn(mule_b, ext_f, 15000, t3a + timedelta(minutes=22), channel="IMPS", device=mule_dev)
    case("CASE-24031", "S3a", s3a, cx, "account_takeover",
         "Someone logged into my account and sent ₹15,000. I only noticed when I got the SMS. I have filed a cyber complaint.",
         t3a + timedelta(hours=5), "awaiting_evidence", "inv.ravi")

    cy = b.customer("Victim Y")
    acc_y = b.account("Victim Y savings", balance=80_000, opened_days=2100, customer=cy, reserve=True)
    dev_y = b.device("Phone", A - timedelta(days=500))
    history(acc_y, dev_y)
    t3b = A - timedelta(days=4)
    b.auth(acc_y, "success", t3b - timedelta(minutes=3), dev_y)
    s3b = b.txn(acc_y, mule_b, 22000, t3b, device=dev_y, narrative="UPI transfer")
    b.txn(mule_b, mule_c, 22000, t3b + timedelta(minutes=15), channel="IMPS", device=mule_dev)
    b.txn(mule_c, ext_e, 21500, t3b + timedelta(minutes=50), channel="IMPS", device=mule_dev)
    case("CASE-24038", "S3b", s3b, cy, "app_scam",
         "I paid ₹22,000 for a used bike listed online. The seller stopped answering and the listing was removed.",
         t3b + timedelta(hours=26), "triage", None)

    # ---- S1 headline -----------------------------------------------------------------------------
    c1 = b.customer("Priya N")
    acc_a = b.account("Priya N savings", balance=310_000, opened_days=2200, customer=c1, reserve=True)
    dev_a = b.device("Priya's phone", A - timedelta(days=640))
    history(acc_a, dev_a, 16)
    t1 = A - timedelta(minutes=95)
    for i in range(4):
        b.auth(acc_a, "failure", t1 - timedelta(minutes=14 - i * 1.5), fraud_dev)
    b.auth(acc_a, "success", t1 - timedelta(minutes=8), fraud_dev, "otp")
    s1 = b.txn(acc_a, mule_b, 50000, t1, device=fraud_dev, narrative="UPI transfer",
               extra_sources=[{"source_system": "upi_switch", "source_record_id": "npci-sw-77120"}])
    s1_b_c = b.txn(mule_b, mule_c, 30000, t1 + timedelta(minutes=7), channel="IMPS", device=mule_dev)
    s1_b_d = b.txn(mule_b, ext_d, 20000, t1 + timedelta(minutes=13), device=mule_dev)
    s1_c_e = b.txn(mule_c, ext_e, 12000, t1 + timedelta(minutes=48), channel="IMPS", device=mule_dev)
    case("CASE-24051", "S1", s1, c1, "unauthorised_transfer",
         "I did not make this payment of ₹50,000. I got a call from someone saying they were from the bank and needed to update "
         "my KYC. A few minutes later I got a debit SMS. I did not share any OTP.",
         t1 + timedelta(minutes=35), "new", "inv.asha")
    d.evidence.append({"case_id": "CASE-24051", "kind": "customer_upload", "checklist_key": "customer_evidence",
                       "template": "receipt", "amount": "50,000.00", "utr": None, "txn": s1, "payee": "Rahul K",
                       "time": t1, "filename": "debit_alert_screenshot.png"})

    # ---- S2 mixed funds (APP scam, Hindi allegation) --------------------------------------------------
    c2 = b.customer("Kavya S", lang="hi")
    acc_2 = b.account("Kavya S savings", balance=95_000, opened_days=1300, customer=c2, reserve=True)
    dev_2 = b.device("Phone", A - timedelta(days=300))
    history(acc_2, dev_2)
    b2 = b.account("Mohit R", balance=8_000, opened_days=700, customer=b.customer("Mohit R"), reserve=True)
    c2x = b.account("Account at Other Bank A", inst=EXT_A)
    t2 = A - timedelta(days=2, hours=3)
    b.auth(acc_2, "success", t2 - timedelta(minutes=2), dev_2)
    s2 = b.txn(acc_2, b2, 40000, t2, device=dev_2, narrative="UPI transfer")
    b.txn(employers[1], b2, 60000, t2 + timedelta(minutes=5), channel="NEFT", narrative="Salary")
    s2_out = b.txn(b2, c2x, 70000, t2 + timedelta(minutes=20), channel="IMPS")
    case("CASE-24044", "S2", s2, c2, "app_scam",
         "मुझे व्हाट्सऐप पर पार्ट-टाइम नौकरी का ऑफर मिला और रजिस्ट्रेशन के लिए ₹40,000 भेजने को कहा गया। पैसे भेजने के बाद उस व्यक्ति ने जवाब देना बंद कर दिया।",
         t2 + timedelta(hours=3), "investigating", "inv.asha", lang="hi")
    d.evidence.append({"case_id": "CASE-24044", "kind": "customer_upload", "checklist_key": "scam_communication", "template": "chat",
                       "filename": "whatsapp_chat_export.txt"})

    # ---- S4 hub (merchant dispute) --------------------------------------------------------------------
    c4 = b.customer("Arjun M")
    acc_4 = b.account("Arjun M savings", balance=70_000, opened_days=1800, customer=c4, reserve=True)
    dev_4 = b.device("Phone", A - timedelta(days=420))
    history(acc_4, dev_4)
    t4 = A - timedelta(hours=60)
    b.auth(acc_4, "success", t4 - timedelta(minutes=2), dev_4)
    s4 = b.txn(acc_4, hub, 12500, t4, device=dev_4, narrative="QuickMart order")
    case("CASE-24047", "S4", s4, c4, "merchant_dispute",
         "I ordered a phone on QuickMart for ₹12,500 and paid by UPI. It was never delivered and the seller is not responding.",
         t4 + timedelta(hours=20), "new", None)
    d.evidence.append({"case_id": "CASE-24047", "kind": "customer_upload", "checklist_key": "customer_evidence", "template": "order",
                       "filename": "order_confirmation.txt", "txn": s4})

    # ---- S5 reversal then resend (processing error) ---------------------------------------------------
    c5 = b.customer("Fatima Z")
    acc_5 = b.account("Fatima Z savings", balance=60_000, opened_days=1000, customer=c5, reserve=True)
    dev_5 = b.device("Phone", A - timedelta(days=380))
    history(acc_5, dev_5)
    b5 = b.account("Account at Other Bank B", inst=EXT_B)
    b6 = b.account("Account at Other Bank A", inst=EXT_A)
    t5 = A - timedelta(days=3)
    b.auth(acc_5, "success", t5 - timedelta(minutes=2), dev_5)
    r5 = b.txn(acc_5, b5, 25000, t5, device=dev_5, status="reversed")
    b.txn(b5, acc_5, 25000, t5 + timedelta(minutes=12), channel="UPI", narrative="Reversal", reversal_of=r5)
    s5 = b.txn(acc_5, b6, 25000, t5 + timedelta(minutes=40), device=dev_5)
    case("CASE-24042", "S5", s5, c5, "processing_error",
         "My first payment of ₹25,000 failed and I paid again. Now I am not sure if I was charged twice.",
         t5 + timedelta(days=1), "ready_for_review", "inv.ravi")

    # ---- S6 cycle -------------------------------------------------------------------------------------
    c6 = b.customer("Nikhil T")
    acc_6 = b.account("Nikhil T savings", balance=40_000, opened_days=900, customer=c6, reserve=True)
    dev_6 = b.device("Phone", A - timedelta(days=200))
    history(acc_6, dev_6)
    b6a = b.account("Asha V", balance=2_000, opened_days=600, customer=b.customer("Asha V"), reserve=True)
    b6b = b.account("Joel D", balance=1_000, opened_days=650, customer=b.customer("Joel D"), reserve=True)
    t6 = A - timedelta(days=5)
    b.auth(acc_6, "success", t6 - timedelta(minutes=3), dev_6)
    s6 = b.txn(acc_6, b6a, 8000, t6, device=dev_6)
    b.txn(b6a, b6b, 8000, t6 + timedelta(minutes=30))
    b.txn(b6b, acc_6, 7900, t6 + timedelta(hours=2))
    case("CASE-24039", "S6", s6, c6, "unauthorised_transfer",
         "There is a ₹8,000 transfer I do not recognise, and later a credit of ₹7,900 from someone I do not know.",
         t6 + timedelta(days=1), "investigating", "inv.ravi")

    # ---- S7 evidence contradicts ledger -----------------------------------------------------------------
    c7 = b.customer("Deepa K")
    acc_7 = b.account("Deepa K savings", balance=120_000, opened_days=1600, customer=c7, reserve=True)
    dev_7 = b.device("Phone", A - timedelta(days=350))
    history(acc_7, dev_7)
    b7 = b.account("Account at Other Bank B", inst=EXT_B)
    t7 = A - timedelta(days=1, hours=5)
    b.auth(acc_7, "success", t7 - timedelta(minutes=2), dev_7)
    s7 = b.txn(acc_7, b7, 50000, t7, device=dev_7)
    case("CASE-24049", "S7", s7, c7, "unauthorised_transfer",
         "₹45,000 was taken from my account without my permission. I have attached the screenshot of the payment.",
         t7 + timedelta(hours=4), "triage", "inv.asha")
    d.evidence.append({"case_id": "CASE-24049", "kind": "customer_upload", "checklist_key": "customer_evidence", "template": "receipt",
                       "amount": "45,000.00", "utr": "628977001234", "txn": s7, "payee": "Account at Other Bank B", "time": t7,
                       "filename": "payment_screenshot.png", "injection": True})

    # ---- S8 clean merchant dispute ----------------------------------------------------------------------
    c8 = b.customer("Rakesh B")
    acc_8 = b.account("Rakesh B savings", balance=45_000, opened_days=2400, customer=c8, reserve=True)
    dev_8 = b.device("Phone", A - timedelta(days=800))
    history(acc_8, dev_8)
    t8 = A - timedelta(days=8)
    b.auth(acc_8, "success", t8 - timedelta(minutes=2), dev_8)
    s8 = b.txn(acc_8, merchants["StreamPlus"], 649, t8, device=dev_8, narrative="StreamPlus subscription")
    case("CASE-24033", "S8", s8, c8, "merchant_dispute",
         "I cancelled my StreamPlus subscription last month but was still charged ₹649.",
         t8 + timedelta(days=2), "investigating", "inv.asha")

    # ---- S9 missing data, reported late -----------------------------------------------------------------
    c9 = b.customer("Gopal R")
    acc_9 = b.account("Gopal R current", kind="current", balance=400_000, opened_days=3000, customer=c9, reserve=True)
    b9 = b.account("Account at Other Bank A", inst=EXT_A)
    t9 = A - timedelta(days=16)
    s9 = b.txn(acc_9, b9, 75000, t9, channel="NEFT", narrative="Branch NEFT")
    case("CASE-24027", "S9", s9, c9, "unauthorised_transfer",
         "A NEFT of ₹75,000 went out from my current account. I did not authorise it. I noticed it only on my monthly statement.",
         t9 + timedelta(days=13), "awaiting_evidence", None)

    # ---- S10 two source systems disagree ----------------------------------------------------------------
    c10 = b.customer("Hema L")
    acc_10 = b.account("Hema L savings", balance=50_000, opened_days=1100, customer=c10, reserve=True)
    dev_10 = b.device("Phone", A - timedelta(days=260))
    history(acc_10, dev_10)
    t10 = A - timedelta(days=2)
    b.auth(acc_10, "success", t10 - timedelta(minutes=2), dev_10)
    s10 = b.txn(acc_10, merchants["FreshKart Grocery"], 9999, t10, device=dev_10,
                extra_sources=[{"source_system": "upi_switch", "source_record_id": "npci-sw-80931", "amount": "9990.00"}])
    case("CASE-24045", "S10", s10, c10, "processing_error",
         "I was charged ₹9,999 at FreshKart but the bill was ₹9,990.", t10 + timedelta(hours=6), "new", None)

    truth.update({
        "S1": {"case": "CASE-24051", "triggered": ["R1", "R2", "R3", "R4", "R5", "R6", "R7", "R10", "R11", "R14"], "not_triggered": ["R8", "R9", "R12"],
               "not_evaluable": ["R9"], "endpoints": {ext_d: "visibility_ends", ext_e: "visibility_ends"},
               "attribution": {s1_b_c: {"min": 28800_00, "max": 30000_00}}, "holdable": [mule_c],
               "trail": [s1, s1_b_c, s1_b_d, s1_c_e]},
        "S2": {"case": "CASE-24044", "attribution": {s2_out: {"min": 2000_00, "max": 40000_00}}, "triggered": ["R11"]},
        "S3a": {"case": "CASE-24031", "triggered": ["R1", "R3", "R4", "R5", "R7", "R14"]},
        "S3b": {"case": "CASE-24038", "triggered": ["R1", "R3", "R7", "R14"]},
        "S4": {"case": "CASE-24047", "endpoints": {hub: "merchant"}, "not_evaluable": ["R1", "R2"], "not_triggered": ["R4", "R5", "R11", "R14"]},
        "S5": {"case": "CASE-24042", "triggered": ["R8"]},
        "S6": {"case": "CASE-24039", "endpoints": {acc_6: "cycle"}},
        "S7": {"case": "CASE-24049", "consistency_contradictory": True},
        "S8": {"case": "CASE-24033", "not_evaluable": ["R1", "R2"],
               "not_triggered": ["R3", "R4", "R5", "R6", "R7", "R8", "R10", "R11", "R12", "R13", "R14", "R15"]},
        "S9": {"case": "CASE-24027", "not_evaluable": ["R4", "R5", "R14"], "policy_overall": "needs_information"},
        "S10": {"case": "CASE-24045", "source_discrepancy": True},
    })
    # S1's ledger already has R9 not evaluable (no analysed evidence); keep lists disjoint for evaluation.
    truth["S1"]["not_triggered"] = ["R8", "R12", "R13", "R15"]
    return d
