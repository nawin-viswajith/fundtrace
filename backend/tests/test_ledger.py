import pytest

from app.services.ledger import NormalisationError, normalise, to_minor, to_utc_naive


def raw(**kw):
    base = {"id": "TXN-1", "source_system": "core", "source_record_id": "c-1", "debit_account_id": "A", "credit_account_id": "B",
            "amount": "50000.00", "currency": "INR", "status": "posted", "channel": "UPI", "reference": "UTR1",
            "occurred_at": "2026-10-01T10:00:00Z"}
    base.update(kw)
    return base


def test_amounts_are_exact_minor_units():
    assert to_minor("50000.00", "INR") == 5000000
    assert to_minor("0.1", "INR") + to_minor("0.2", "INR") == to_minor("0.3", "INR")  # no float drift
    assert to_minor("10.005", "INR") == 1001  # half-up
    with pytest.raises(NormalisationError):
        to_minor("-5", "INR")
    with pytest.raises(NormalisationError):
        to_minor("12", "XXX")


def test_timezones_become_utc():
    assert to_utc_naive("2026-10-01T15:30:00+05:30").isoformat() == "2026-10-01T10:00:00"


def test_same_payment_from_two_systems_is_merged_with_provenance():
    txns, rep = normalise([raw(), raw(id="TXN-1b", source_system="upi_switch", source_record_id="u-9", occurred_at="2026-10-01T10:01:00Z")])
    assert len(txns) == 1 and len(txns[0]["sources"]) == 2
    assert rep.merged and not rep.merged[0]["discrepancies"]


def test_disagreeing_sources_keep_primary_and_record_discrepancy():
    txns, rep = normalise([raw(), raw(id="X", source_system="upi_switch", source_record_id="u-9", amount="49990.00")])
    assert txns[0]["amount_minor"] == 5000000  # core wins
    assert txns[0]["sources"][0]["discrepancies"][0]["fields"]["amount_minor"]["other"] == 4999000
    assert rep.merged[0]["discrepancies"] == ["amount_minor"]


def test_exact_duplicate_source_records_are_dropped():
    txns, rep = normalise([raw(), raw()])
    assert len(txns) == 1 and rep.dropped_duplicates == ["core:c-1"]


def test_records_without_reference_are_not_merged():
    txns, _ = normalise([raw(reference=None), raw(id="TXN-2", source_system="upi_switch", source_record_id="u-1", reference=None)])
    assert len(txns) == 2


def test_malformed_records_are_rejected_not_crashing():
    txns, rep = normalise([raw(amount="abc"), raw(id="T2", source_record_id="c-2", status="weird"),
                           raw(id="T3", source_record_id="c-3", credit_account_id="A")])
    assert txns == [] and len(rep.rejected) == 3
