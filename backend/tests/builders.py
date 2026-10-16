"""Tiny builders for in-memory ledgers used by unit tests."""
from datetime import datetime, timedelta

from app.services.graph_store import AccountRec, AuthRec, CaseLink, DeviceRec, InMemoryGraphStore, TxnRec

T0 = datetime(2026, 10, 1, 10, 0, 0)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def rupees(x: float) -> int:
    return int(round(x * 100))


def acct(id: str, balance: float | None = 0, external: bool = False, opened_days_ago: float | None = 400,
         kind: str = "savings") -> AccountRec:
    return AccountRec(
        id=id,
        customer_id=None if external else f"CUST-{id}",
        institution_id="EXT" if external else "SELF",
        institution_name="Other Bank" if external else "FundTrace Demo Bank",
        external=external,
        kind="external" if external else kind,
        holder_label=f"Holder {id}",
        masked_number=f"XXXX{id[-4:]}",
        opened_at=None if opened_days_ago is None else T0 - timedelta(days=opened_days_ago),
        opening_balance_minor=None if (external or balance is None) else rupees(balance),
        currency="INR",
    )


_seq = {"n": 0}


def txn(id: str, src: str, dst: str, amount: float, minutes: float, status: str = "posted", ref: str | None = "auto",
        reversal_of: str | None = None, device: str | None = None, channel: str = "UPI") -> TxnRec:
    _seq["n"] += 1
    return TxnRec(
        id=id,
        debit_account_id=src,
        credit_account_id=dst,
        amount_minor=rupees(amount),
        currency="INR",
        status=status,
        channel=channel,
        reference=(f"UTR{id}" if ref == "auto" else ref),
        occurred_at=at(minutes),
        posted_at=at(minutes),
        reversal_of_id=reversal_of,
        device_id=device,
        source_system="core",
        source_record_id=f"core-{id}",
    )


def store(accounts, txns, auth=None, devices=None, links=None) -> InMemoryGraphStore:
    return InMemoryGraphStore(accounts, txns, auth or [], devices or [], links or [])


def auth(id, account, outcome, minutes, device=None) -> AuthRec:
    return AuthRec(id=id, account_id=account, device_id=device, event_type="login", outcome=outcome,
                   occurred_at=at(minutes), source_system="auth", source_record_id=f"auth-{id}")


def device(id, first_seen_minutes) -> DeviceRec:
    return DeviceRec(id=id, label=f"Device {id}", first_seen_at=at(first_seen_minutes))


def link(case_id, txn_id, beneficiary, status="investigating") -> CaseLink:
    return CaseLink(case_id=case_id, disputed_txn_id=txn_id, beneficiary_account_id=beneficiary, status=status)


def s1_store(**kw):
    """Headline scenario: A → B ₹50,000; B → C ₹30,000; B → D (external) ₹20,000."""
    accounts = [acct("ACC-A", 200000), acct("ACC-B", 1200, opened_days_ago=9), acct("ACC-C", 500), acct("ACC-D", external=True)]
    txns = [
        txn("TXN-1", "ACC-A", "ACC-B", 50000, 2),
        txn("TXN-2", "ACC-B", "ACC-C", 30000, 9),
        txn("TXN-3", "ACC-B", "ACC-D", 20000, 15),
    ]
    return store(accounts, txns, **kw)
