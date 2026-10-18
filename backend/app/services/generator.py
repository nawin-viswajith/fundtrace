"""Demo data generator: more synthetic disputes on demand, from the bank's view.

Each generated case is complete and consistent, so every screen works on it: a real payment from an existing
customer's account, a money trail (mule accounts, onward transfers to other banks, money left behind so holds
are suggested), sign-in records for takeover cases, an optional customer receipt, and the chosen status. Rules,
priority, SLA deadlines and hold recommendations are then computed by the normal services.

Customer statements come from templates (free) or, within a spending cap, are written by Gemini. A statement
that mentions a different amount from the payment is rejected and the template is used instead.
Everything generated is marked synthetic and audited.
"""
from __future__ import annotations

import hashlib
import random
import re
import uuid
from datetime import timedelta

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.services.scoring import CATEGORIES
from app.services.trace import fmt_amount

STATUSES = ("new", "triage", "investigating", "awaiting_evidence", "ready_for_review", "resolved")
MIX = [("new", 3), ("triage", 2), ("investigating", 3), ("awaiting_evidence", 2), ("ready_for_review", 1), ("resolved", 1)]
FIRST = ["Aditya", "Bhavna", "Chetan", "Divya", "Gaurav", "Hema", "Irfan", "Jaya", "Karan", "Lata", "Manoj", "Nandini", "Prakash",
         "Ritu", "Suresh", "Tanvi", "Uday", "Vani", "Yash", "Zoya"]
LAST = ["Agarwal", "Bhat", "Chopra", "Desai", "Kulkarni", "Mehta", "Patel", "Saxena", "Tiwari", "Varma"]
STORES = ["ShopNest Online", "GadgetHub Store", "TravelEase Bookings", "StyleCart", "GameZone Credits", "QuickBite Foods"]
FRAUD = {"unauthorised_transfer", "account_takeover", "app_scam"}

TEMPLATES = {
    "unauthorised_transfer": ["I did not make this payment of {amt} to {payee}. I only noticed when I got the SMS and I have not shared my OTP with anyone.",
                              "There is a {amt} debit to {payee} that I never made. My phone was with me the whole time."],
    "account_takeover": ["Someone got into my banking app and sent {amt} to {payee}. I got messages about failed logins before it happened.",
                         "My account was accessed without my permission and {amt} was transferred to {payee}. I have changed my password."],
    "app_scam": ["I was told I had won a prize and had to pay {amt} as a processing fee to {payee}. Now they don't answer my calls.",
                 "A person offering a part-time job asked me to pay {amt} to {payee} as a registration fee. It was a fake job."],
    "card_not_present": ["My card was charged {amt} by {payee} online. I have never shopped there and my card is with me.",
                         "There is an online card payment of {amt} to {payee} that I did not make."],
    "merchant_dispute": ["I paid {amt} to {payee} for an order that was never delivered. The seller has stopped replying.",
                         "I paid {amt} to {payee} but the service was cancelled and no refund was given."],
    "processing_error": ["I was charged twice: {amt} was taken two times by {payee} for one purchase.",
                         "My payment of {amt} to {payee} was debited twice. Please refund the extra charge."],
}


class GenerateIn(BaseModel):
    count: int = Field(5, ge=1, le=50)
    categories: list[str] = Field(default_factory=lambda: list(CATEGORIES), min_length=1)
    amount_min: int = Field(5000, ge=100, le=1_000_000, description="Rupees")
    amount_max: int = Field(100000, ge=100, le=1_000_000, description="Rupees")
    status_mode: str = Field("mixed", description="mixed or one of the case statuses")
    assign: str = Field("spread", description="nobody, spread (across investigators) or a username")
    days_back: int = Field(7, ge=1, le=30, description="Payments happened within this many days")
    with_trail: bool = True
    with_evidence: bool = True
    statements: str = Field("template", pattern="^(template|ai)$")
    ai_budget_usd: float = Field(0.10, ge=0, le=2)


class StatementDraft(BaseModel):
    statement: str = Field(description="1–3 sentences in the customer's own voice")


class _Ids:
    """Next free numeric ids, so generated records look like the seeded ones."""

    def __init__(self, db: Session):
        def top(col, prefix: str, floor: int) -> int:
            nums = [int(x[len(prefix):]) for x in db.scalars(select(col)) if re.fullmatch(prefix + r"\d+", x)]
            return max(nums, default=floor)

        self.acct = top(m.Account.id, "ACC-", 100100)
        self.txn = top(m.Transaction.id, "TXN-", 4000000)
        self.dev = top(m.Device.id, "DEV-", 9000)
        self.auth = top(m.AuthEvent.id, "AUTH-", 700000)
        self.case = top(m.DisputeCase.id, "CASE-", 24000)

    def next(self, kind: str) -> int:
        setattr(self, kind, getattr(self, kind) + 1)
        return getattr(self, kind)


class _World:
    def __init__(self, db: Session, rng: random.Random, now):
        self.db, self.rng, self.now, self.ids = db, rng, now, _Ids(db)
        self._payroll: str | None = None

    def payroll(self) -> str:
        """One external employer account per batch, paying salaries into customers' accounts."""
        if self._payroll is None:
            self._payroll = self.account("Employer payroll", inst="INST-EXT-B")
        return self._payroll

    def account(self, holder: str, inst: str = "INST-SELF", kind: str = "savings", opened_days: float | None = 30,
                balance: int | None = 0) -> str:
        aid = f"ACC-{self.ids.next('acct')}"
        ext = inst != "INST-SELF"
        self.db.add(m.Account(id=aid, customer_id=None, institution_id=inst, kind="external" if ext else kind,
                              holder_label=f"{holder} (synthetic)", masked_number=f"XXXX{self.rng.randint(1000, 9999)}",
                              opened_at=None if ext or opened_days is None else self.now - timedelta(days=opened_days),
                              opening_balance_minor=None if ext else balance, currency="INR", is_synthetic=True))
        self.db.flush()  # plain FK columns (no ORM relationship): write it before rows that point at it
        return aid

    def device(self, label: str, first_seen) -> str:
        did = f"DEV-{self.ids.next('dev')}"
        self.db.add(m.Device(id=did, fingerprint_hash=hashlib.sha256(did.encode()).hexdigest(), label=label, first_seen_at=first_seen))
        self.db.flush()
        return did

    def auth(self, account: str, outcome: str, at, device: str | None, etype: str = "login") -> None:
        n = self.ids.next("auth")
        self.db.add(m.AuthEvent(id=f"AUTH-{n}", account_id=account, device_id=device, ip_hash=hashlib.sha256(f"ip{device}".encode()).hexdigest()[:16],
                                event_type=etype, outcome=outcome, occurred_at=at, source_system="digital_auth", source_record_id=f"gen-{n}"))

    def txn(self, src: str, dst: str, amount_minor: int, at, channel: str = "UPI", device: str | None = None, narrative: str = "") -> str:
        n = self.ids.next("txn")
        tid = f"TXN-{n}"
        ref = str(628900000000 + self.rng.randint(100000, 899999))
        self.db.add(m.Transaction(id=tid, source_system="core", source_record_id=f"gen-{n}", debit_account_id=src, credit_account_id=dst,
                                  amount_minor=amount_minor, currency="INR", status="posted", channel=channel, reference=ref, occurred_at=at,
                                  posted_at=at + timedelta(seconds=4), device_id=device, narrative=narrative, is_synthetic=True,
                                  sources=[{"system": "core", "record_id": f"gen-{n}", "amount_minor": amount_minor, "currency": "INR",
                                            "status": "posted", "occurred_at": at.isoformat() + "Z"}]))
        return tid

    def person(self) -> str:
        return f"{self.rng.choice(FIRST)} {self.rng.choice(LAST)[0]}"


def _customers(db: Session) -> list[tuple[str, str, str]]:
    """(customer id, savings account id, display name) for customers with an account at this bank."""
    rows = db.execute(select(m.Customer.id, m.Account.id, m.Customer.display_name).join(m.Account, m.Account.customer_id == m.Customer.id)
                      .where(m.Account.institution_id == "INST-SELF", m.Account.kind == "savings")).all()
    return [(c, a, n) for c, a, n in rows]


def _money_trail(w: _World, mule: str, amount: int, t0, mule_dev: str) -> None:
    """Onward transfers from the mule: most leaves for other banks quickly, some stays (so a hold is possible)."""
    rng = w.rng
    keep = int(amount * rng.uniform(0.05, 0.3)) // 100 * 100
    out = amount - keep
    hops = rng.choice([1, 2, 2, 3])
    if hops == 1:
        w.txn(mule, w.account("Account at Other Bank A", inst="INST-EXT-A"), out, t0 + timedelta(minutes=rng.randint(5, 40)), "IMPS", mule_dev)
        return
    second = w.account(w.person(), opened_days=rng.randint(10, 60), balance=rng.randint(2, 20) * 10000)
    first_leg = int(out * rng.uniform(0.5, 0.7)) // 100 * 100
    w.txn(mule, second, first_leg, t0 + timedelta(minutes=rng.randint(4, 15)), "IMPS", mule_dev)
    w.txn(mule, w.account("Account at Other Bank B", inst="INST-EXT-B"), out - first_leg, t0 + timedelta(minutes=rng.randint(16, 40)), "IMPS", mule_dev)
    onward = int(first_leg * rng.uniform(0.85, 1.0)) // 100 * 100
    w.txn(second, w.account("Account at Other Bank A", inst="INST-EXT-A"), onward, t0 + timedelta(minutes=rng.randint(45, 120)), "IMPS", mule_dev)
    if hops == 3:
        w.txn(second, w.account("Cash withdrawal (ATM)", inst="INST-CASH", kind="cash"), first_leg - onward, t0 + timedelta(hours=3), "INTERNAL")


def _one(db: Session, w: _World, p: GenerateIn, category: str, customer: tuple[str, str, str], status: str, owner: m.User | None,
         actor: m.User) -> m.DisputeCase:
    rng, now = w.rng, w.now
    cid, payer, cname = customer
    amount = rng.randint(p.amount_min // 100, max(p.amount_min, p.amount_max) // 100) * 10000  # whole hundreds, in paise
    t0 = now - timedelta(minutes=rng.randint(30, p.days_back * 24 * 60))
    own_dev = w.device("Customer phone", t0 - timedelta(days=rng.randint(200, 900)))
    # a salary credit before the payment, so the account can afford it (keeps the money tracing realistic)
    w.txn(w.payroll(), payer, amount + rng.randint(5, 40) * 100000, t0 - timedelta(days=rng.randint(1, 3)), "NEFT", None, "Salary")
    w.auth(payer, "success", t0 - timedelta(minutes=3), own_dev)
    payee_label = ""
    if category in FRAUD:
        mule_name = w.person()
        mule = w.account(mule_name, opened_days=rng.randint(2, 25), balance=rng.randint(0, 3) * 50000)
        mule_dev = w.device("Shared handset", t0 - timedelta(days=rng.randint(5, 30)))
        device = own_dev
        if category in ("unauthorised_transfer", "account_takeover"):
            device = w.device("Unrecognised Android", t0 - timedelta(minutes=rng.randint(10, 600)))
            if category == "account_takeover":
                for i in range(rng.randint(3, 5)):
                    w.auth(payer, "failure", t0 - timedelta(minutes=14 - i * 2), device)
            w.auth(payer, "success", t0 - timedelta(minutes=2), device, "otp")
        disputed = w.txn(payer, mule, amount, t0, "UPI", device, "UPI transfer")
        payee_label = mule_name
        if p.with_trail:
            _money_trail(w, mule, amount, t0, mule_dev)
    elif category == "card_not_present":
        store = rng.choice(STORES)
        disputed = w.txn(payer, w.account(store, inst="INST-EXT-A"), amount, t0, "CARD", None, "Card purchase online")
        payee_label = store
    else:
        merchant = db.scalar(select(m.Account).where(m.Account.kind == "merchant").order_by(m.Account.id).offset(rng.randint(0, 5)).limit(1))
        payee_label = merchant.holder_label.replace(" (synthetic)", "") if merchant else "Merchant"
        mid = merchant.id if merchant else w.account("Merchant", kind="merchant", balance=20_000_000)
        disputed = w.txn(payer, mid, amount, t0, "UPI", own_dev, "Purchase")
        if category == "processing_error":
            disputed = w.txn(payer, mid, amount, t0 + timedelta(minutes=rng.randint(1, 3)), "UPI", own_dev, "Purchase")
    db.flush()

    reported = min(now - timedelta(minutes=1), t0 + timedelta(minutes=rng.randint(15, 2 * 24 * 60)))
    statement = rng.choice(TEMPLATES[category]).format(amt=fmt_amount(amount, "INR"), payee=payee_label)
    case = m.DisputeCase(id=f"CASE-{w.ids.next('case')}", disputed_txn_id=disputed, customer_id=cid, category=category,
                         category_source="intake", allegation=statement, allegation_language="en", status="new", priority="P3",
                         reported_at=reported, is_synthetic=True, scenario="GEN", channel="generated")
    db.add(case)
    db.flush()
    audit.record(db, case.id, actor.username, actor.role, "case_created",
                 {"source": "demo data generator", "disputed_txn_id": disputed, "category": category})
    if p.with_evidence and category in FRAUD | {"card_not_present"}:
        from app.seed import evidence_files
        from app.services.evidence_store import store_evidence

        t = db.get(m.Transaction, disputed)
        png = evidence_files.receipt_png(f"{amount / 100:,.2f}", t.reference, payee_label, t0)
        store_evidence(db, case, png, "payment_screenshot.png", "image/png", kind="customer_upload", checklist_key="customer_evidence",
                       actor="customer (synthetic)", actor_role="customer")
    _apply_status(db, case, status, owner, actor, rng, now)
    return case


def _apply_status(db: Session, case: m.DisputeCase, status: str, owner: m.User | None, actor: m.User, rng, now) -> None:
    if owner is not None and status != "new":
        case.owner_id = owner.id
    if status == "new":
        return
    case.status = "resolved" if status == "resolved" else status
    if status == "awaiting_evidence":
        db.add(m.EvidenceRequest(case_id=case.id, checklist_key="customer_evidence", requested_from="customer",
                                 note="Please send a screenshot of the payment.", requested_by=(owner or actor).id))
    if status == "resolved":
        case.decision = rng.choice(["uphold_claim", "decline_claim", "partial"])
        case.decision_rationale = "Synthetic decision created by the demo data generator."
        case.decided_by = (owner or actor).id
        case.decided_at = min(now, case.reported_at + timedelta(hours=rng.randint(2, 48)))
    audit.record(db, case.id, actor.username, actor.role, "status_changed", {"from": "new", "to": case.status, "reason": "demo data generator"})


def _ai_statement(db: Session, gw, case: m.DisputeCase, payee: str) -> tuple[str | None, float]:
    """Gemini writes the customer's statement; rejected if it states a different amount than the payment."""
    from app.ai import prompts

    t = case.disputed_txn
    amt = fmt_amount(t.amount_minor, t.currency)
    facts = (f"Dispute type: {CATEGORIES[case.category]}. Amount: {amt}. Paid to: {payee}. Channel: {t.channel}. "
             f"Write what this (synthetic) bank customer would tell the bank, in 1–3 plain sentences, first person. Mention the amount "
             f"exactly as {amt}. Do not include OTPs, PINs, card numbers, phone numbers or other people's real names.")
    res = gw.generate(node="generate_statement", prompt_version="gen-statement-v1", contents=[facts], schema=StatementDraft, tier="fast",
                      system=prompts.GROUND_RULES, case_id=case.id, run_id=None, db=db, temperature=0.9)
    if not res.ok:
        return None, res.cost_usd
    text = res.data.statement.strip()
    said = {re.sub(r"[^\d]", "", x) for x in re.findall(r"₹\s?[\d,]+(?:\.\d+)?", text)}
    ok = 20 <= len(text) <= 600 and said <= {re.sub(r"[^\d]", "", amt), re.sub(r"[^\d]", "", amt) + "00"}
    return (text if ok else None), res.cost_usd


def generate(db: Session, actor: m.User, p: GenerateIn, gateway=None) -> dict:
    from app.ai.llm import get_gateway
    from app.seed.loader import refresh_case_assessments

    bad = [c for c in p.categories if c not in CATEGORIES]
    if bad:
        raise HTTPException(422, f"Unknown dispute types: {bad}")
    if p.amount_min > p.amount_max:
        raise HTTPException(422, "The lowest amount must not be above the highest")
    if p.status_mode != "mixed" and p.status_mode not in STATUSES:
        raise HTTPException(422, "Unknown status")
    investigators = list(db.scalars(select(m.User).where(m.User.role == "investigator", m.User.is_active.is_(True)).order_by(m.User.username)))
    named = None
    if p.assign not in ("nobody", "spread"):
        named = db.scalar(select(m.User).where(m.User.username == p.assign, m.User.role.in_(("investigator", "supervisor"))))
        if named is None:
            raise HTTPException(422, "Unknown assignee")
    customers = _customers(db)
    if not customers:
        raise HTTPException(409, "There are no customers to generate disputes for")

    rng = random.Random(uuid.uuid4().int)
    w = _World(db, rng, m.utcnow())
    gw = gateway or get_gateway()
    use_ai = p.statements == "ai" and gw.available() and p.ai_budget_usd > 0
    spent, ai_used, ai_rejected = 0.0, 0, 0
    created = []
    for i in range(p.count):
        status = p.status_mode if p.status_mode != "mixed" else rng.choices([s for s, _ in MIX], [wt for _, wt in MIX])[0]
        owner = named if named else (investigators[i % len(investigators)] if p.assign == "spread" and investigators else None)
        category = rng.choice(p.categories)
        case = _one(db, w, p, category, rng.choice(customers), status, owner, actor)
        if use_ai and spent < p.ai_budget_usd:
            payee_acct = db.get(m.Account, case.disputed_txn.credit_account_id)
            text, cost = _ai_statement(db, gw, case, payee_acct.holder_label.replace(" (synthetic)", "") if payee_acct else "the payee")
            spent += cost
            if text:
                case.allegation = text
                ai_used += 1
            else:
                ai_rejected += 1
        created.append(case)
    db.flush()
    refresh_case_assessments(db, [c.id for c in created])
    summary = {"created": [{"case_id": c.id, "category": CATEGORIES[c.category], "status": c.status, "priority": c.priority,
                            "amount": fmt_amount(c.disputed_txn.amount_minor, "INR")} for c in created],
               "statements": {"ai": ai_used, "ai_rejected": ai_rejected, "template": len(created) - ai_used,
                              "ai_cost_usd": round(spent, 6), "ai_available": gw.available()}}
    audit.record(db, None, actor.username, actor.role, "demo_data_generated",
                 {"count": len(created), "case_ids": [c.id for c in created], "params": p.model_dump(), "ai_cost_usd": round(spent, 6)})
    return summary
