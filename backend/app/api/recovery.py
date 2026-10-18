"""Recovery pools: how money in an account shared by several open disputes would be split between them.

Reading is open to bank staff; investigators see the ids of only the cases they can open (others
show as "restricted", as on the linked-case rings). Recording a split is a supervisor/admin action,
needs a written reason, is audited, and moves no money.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.db import get_db
from app.security import can_access_case, current_user, load_case_for, require_role
from app.services import dlp, recovery

router = APIRouter(prefix="/api/recovery", tags=["recovery"])

Basis = Literal["traced", "disputed"]


def _visible(user: m.User, db: Session, case_ids: set[str]) -> set[str]:
    if user.role in ("supervisor", "admin"):
        return set(case_ids)
    if not case_ids:
        return set()
    cases = db.scalars(select(m.DisputeCase).where(m.DisputeCase.id.in_(case_ids))).unique().all()
    return {c.id for c in cases if can_access_case(user, c)}


def _pool_ids(pool: dict) -> set[str]:
    ids = {c["case_id"] for c in pool["claims"]}
    if pool.get("available_source"):
        ids.add(pool["available_source"]["case_id"])
    if pool.get("last_recorded"):
        ids |= {a["case_id"] for a in pool["last_recorded"]["allocations"]}
    return ids


@router.get("/pools")
def pools(basis: Basis = "traced", user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    out = recovery.list_pools(db, basis)
    if user.role not in ("supervisor", "admin"):
        for p in out["pools"]:
            recovery.redact(p, _visible(user, db, _pool_ids(p)))
    return out


@router.get("/pools/{account_id}")
def pool(account_id: str, basis: Basis = "traced", user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    p = recovery.get_pool(db, account_id, basis)
    if p is None:
        raise HTTPException(404, "This account is not shared by two or more open cases")
    if user.role not in ("supervisor", "admin"):
        recovery.redact(p, _visible(user, db, _pool_ids(p)))
    return p


class RecordIn(BaseModel):
    basis: Basis = "traced"
    note: str = Field(min_length=10, max_length=2000)


@router.post("/pools/{account_id}/record")
def record(account_id: str, body: RecordIn, user: m.User = Depends(require_role("supervisor", "admin")), db: Session = Depends(get_db)):
    note = body.note.strip()
    if len(note) < 10:
        raise HTTPException(422, "Write a reason of at least 10 characters")
    note, _ = dlp.mask(note)  # card / Aadhaar numbers and OTPs never reach the database
    p = recovery.get_pool(db, account_id, body.basis)  # always recomputed here: the client's numbers are never trusted
    if p is None:
        raise HTTPException(404, "This account is not shared by two or more open cases")
    if p["available_minor"] is None:
        raise HTTPException(409, "The balance of this account is not known from the records, so no split can be recorded")
    rec = recovery.record_allocation(db, p, note, user)
    db.commit()
    out = recovery.record_to_dict(rec)
    p["last_recorded"] = out
    return {"record": out, "pool": p}


@router.get("/pools/{account_id}/history")
def pool_history(account_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    rows = recovery.history(db, account_id)
    if user.role not in ("supervisor", "admin"):
        visible = _visible(user, db, {a["case_id"] for r in rows for a in r["allocations"]})
        rows = [recovery.redact_record(r, visible) for r in rows]
    return {"account_id": account_id, "records": rows, "effect": recovery.NOT_A_TRANSFER}


@router.get("/cases/{case_id}/shared")
def shared_for_case(case_id: str, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    """For the case screen: which of this case's hold suggestions sit on accounts other open cases also claim."""
    case = load_case_for(user, db, case_id)
    rows = recovery.shared_for_case(db, case)
    visible = _visible(user, db, {c for r in rows for c in r["other_cases"]})
    for r in rows:
        r["other_cases"] = [c if c in visible else "restricted" for c in r["other_cases"]]
    return {"case_id": case.id, "accounts": rows}
