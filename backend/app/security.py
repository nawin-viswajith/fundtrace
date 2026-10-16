"""Authentication (bcrypt + JWT cookie) and authorisation (roles + case-level access)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app import models as m
from app.config import get_settings
from app.db import get_db

COOKIE = "ft_session"
ROLES = ("investigator", "supervisor", "admin")


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode()[:72], bcrypt.gensalt(rounds=10)).decode()


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode()[:72], hashed.encode())
    except ValueError:
        return False


def create_token(user: m.User) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user.id), "usr": user.username, "role": user.role, "iat": now, "exp": now + timedelta(minutes=s.jwt_ttl_minutes)}
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256")


def _token_from(request: Request) -> str | None:
    tok = request.cookies.get(COOKIE)
    if tok:
        return tok
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return None


def current_user(request: Request, db: Session = Depends(get_db)) -> m.User:
    tok = _token_from(request)
    if not tok:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(tok, get_settings().jwt_secret, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    user = db.get(m.User, int(payload.get("sub", 0)))
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_role(*roles: str):
    def dep(user: m.User = Depends(current_user)) -> m.User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Not permitted for your role")
        return user

    return dep


def can_access_case(user: m.User, case: m.DisputeCase) -> bool:
    if user.role in ("supervisor", "admin"):
        return True
    return case.owner_id is None or case.owner_id == user.id


def load_case_for(user: m.User, db: Session, case_id: str) -> m.DisputeCase:
    case = db.get(m.DisputeCase, case_id)
    # Same response for "missing" and "not yours" so case ids cannot be probed.
    if case is None or not can_access_case(user, case):
        raise HTTPException(status_code=404, detail="Case not found")
    return case
