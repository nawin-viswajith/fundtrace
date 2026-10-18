import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app import models as m
from app.config import get_settings
from app.db import get_db
from app.security import COOKIE, create_pending_token, create_token, current_user, read_pending_token, verify_password
from app.seed.loader import CUSTOMER_USERS
from app.services import mfa

router = APIRouter(prefix="/api/auth", tags=["auth"])
_failures: dict[str, list[float]] = defaultdict(list)
MAX_FAILURES, WINDOW_S = 5, 300


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def user_out(u: m.User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role,
            "mfa_enabled": bool(u.mfa_enabled), "mfa_required": mfa.required_for(u)}


def _check_lockout(username: str) -> None:
    key, now = username.lower(), time.time()
    _failures[key] = [t for t in _failures[key] if now - t < WINDOW_S]
    if len(_failures[key]) >= MAX_FAILURES:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in a few minutes.")


def _fail(username: str) -> None:
    _failures[username.lower()].append(time.time())


def _set_session(response: Response, user: m.User, mfa_done: bool) -> None:
    s = get_settings()
    response.set_cookie(COOKIE, create_token(user, mfa_done), httponly=True, secure=s.cookie_secure, samesite="strict",
                        max_age=s.jwt_ttl_minutes * 60, path="/")


def _start_session(db: Session, response: Response, user: m.User, provider: str) -> dict:
    """After the first factor: open a session, or ask for the second factor / MFA enrolment first."""
    if user.mfa_enabled:
        return {"mfa_required": True, "mfa_token": create_pending_token(user, "mfa_verify", provider)}
    if mfa.required_for(user):
        return {"mfa_enrollment_required": True, "mfa_token": create_pending_token(user, "mfa_enroll", provider)}
    _set_session(response, user, mfa_done=False)
    audit.record(db, None, user.username, user.role, "login", {"provider": provider, "mfa": None})
    db.commit()
    return {"user": user_out(user)}


@router.post("/login")
def login(body: LoginIn, response: Response, request: Request, db: Session = Depends(get_db)):
    _check_lockout(body.username)
    user = db.scalar(select(m.User).where(m.User.username == body.username))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        _fail(body.username)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    _failures.pop(body.username.lower(), None)
    return _start_session(db, response, user, "password")


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: m.User = Depends(current_user)):
    return {"user": user_out(user)}


@router.get("/config")
def auth_config():
    s = get_settings()
    firebase = None
    if s.firebase_project_id and s.firebase_api_key:
        firebase = {"apiKey": s.firebase_api_key, "authDomain": s.firebase_auth_domain or f"{s.firebase_project_id}.firebaseapp.com",
                    "projectId": s.firebase_project_id}
    return {
        "demo": True,
        "demo_users": [{"username": "inv.asha", "role": "investigator"}, {"username": "inv.ravi", "role": "investigator"},
                       {"username": "sup.meera", "role": "supervisor"}, {"username": "admin", "role": "admin"}],
        "demo_password": s.demo_password if s.show_demo_credentials else None,
        "demo_customers": [{"username": u, "customer_id": c} for u, c in CUSTOMER_USERS],
        "firebase_enabled": firebase is not None,
        "firebase": firebase,
        "mfa_required_roles": sorted(s.mfa_roles),
        "synthetic_data": True,
    }


class FirebaseIn(BaseModel):
    id_token: str = Field(min_length=20, max_length=4096)


@router.post("/firebase")
def firebase_login(body: FirebaseIn, response: Response, db: Session = Depends(get_db)):
    """Optional Firebase Auth / Identity Platform sign-in. A verified identity only maps to an existing
    FundTrace user (username == verified email); roles are never granted automatically."""
    s = get_settings()
    if not s.firebase_project_id:
        raise HTTPException(status_code=404, detail="Firebase sign-in is not enabled")
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token

    try:
        claims = id_token.verify_firebase_token(body.id_token, g_requests.Request(), audience=s.firebase_project_id)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid sign-in token")
    email = (claims or {}).get("email")
    if not email or not claims.get("email_verified"):
        raise HTTPException(status_code=401, detail="A verified email is required")
    user = db.scalar(select(m.User).where(m.User.username == email.lower()))
    if not user or not user.is_active:
        raise HTTPException(status_code=403, detail="No FundTrace role is assigned to this account")
    return _start_session(db, response, user, "firebase")


# ---------------------------------------------------------------------------- MFA

class MfaVerifyIn(BaseModel):
    mfa_token: str = Field(min_length=20, max_length=2048)
    code: str = Field(min_length=6, max_length=16)


@router.post("/mfa/verify")
def mfa_verify(body: MfaVerifyIn, response: Response, db: Session = Depends(get_db)):
    """Second sign-in step: a code from the authenticator app, or one recovery code."""
    user, provider = read_pending_token(db, body.mfa_token, "mfa_verify")
    _check_lockout(user.username)
    method = mfa.verify(user, body.code)
    if method is None:
        _fail(user.username)
        audit.record(db, None, user.username, user.role, "mfa_failed", {"provider": provider})
        db.commit()
        raise HTTPException(status_code=401, detail="That code is not valid. Check the time on your phone and try again.")
    _failures.pop(user.username.lower(), None)
    _set_session(response, user, mfa_done=True)
    audit.record(db, None, user.username, user.role, "login", {"provider": provider, "mfa": method,
                                                                "recovery_codes_left": len(user.mfa_recovery or [])})
    db.commit()
    return {"user": user_out(user), "recovery_codes_left": len(user.mfa_recovery or []) if method == "recovery" else None}


class MfaSetupIn(BaseModel):
    mfa_token: str | None = Field(default=None, max_length=2048)


def _enrolling_user(request: Request, db: Session, mfa_token: str | None) -> tuple[m.User, bool]:
    """The user enrolling: from a pending enrolment token (forced at sign-in) or the current session."""
    if mfa_token:
        user, _ = read_pending_token(db, mfa_token, "mfa_enroll")
        return user, True
    return current_user(request, db), False


@router.post("/mfa/setup")
def mfa_setup(body: MfaSetupIn, request: Request, db: Session = Depends(get_db)):
    user, _ = _enrolling_user(request, db, body.mfa_token)
    if user.mfa_enabled:
        raise HTTPException(status_code=409, detail="MFA is already on. Turn it off first to enrol a new device.")
    secret = mfa.new_secret()
    user.mfa_secret, user.mfa_last_step = secret, None
    audit.record(db, None, user.username, user.role, "mfa_setup_started", {})
    db.commit()
    uri = mfa.provisioning_uri(user, secret)
    return {"secret": secret, "otpauth_uri": uri, "qr_svg": mfa.qr_svg_data_uri(uri)}


class MfaEnableIn(BaseModel):
    code: str = Field(min_length=6, max_length=16)
    mfa_token: str | None = Field(default=None, max_length=2048)


@router.post("/mfa/enable")
def mfa_enable(body: MfaEnableIn, request: Request, response: Response, db: Session = Depends(get_db)):
    user, via_token = _enrolling_user(request, db, body.mfa_token)
    if user.mfa_enabled:
        raise HTTPException(status_code=409, detail="MFA is already on")
    if not user.mfa_secret:
        raise HTTPException(status_code=409, detail="Start the setup first")
    _check_lockout(user.username)
    if mfa.verify(user, body.code, allow_recovery=False) is None:
        _fail(user.username)
        raise HTTPException(status_code=422, detail="That code is not valid. Enter the current 6-digit code from the app.")
    codes, hashes = mfa.new_recovery_codes()
    user.mfa_enabled, user.mfa_recovery = True, hashes
    _set_session(response, user, mfa_done=True)  # the session now carries the second factor
    audit.record(db, None, user.username, user.role, "mfa_enabled", {"forced_at_sign_in": via_token})
    if via_token:
        audit.record(db, None, user.username, user.role, "login", {"provider": "password", "mfa": "totp"})
    db.commit()
    return {"user": user_out(user), "recovery_codes": codes}


class MfaDisableIn(BaseModel):
    password: str = Field(min_length=1, max_length=128)
    code: str = Field(min_length=6, max_length=16)


@router.post("/mfa/disable")
def mfa_disable(body: MfaDisableIn, response: Response, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    if mfa.required_for(user):
        raise HTTPException(status_code=403, detail="MFA is required for your role and cannot be turned off")
    if not user.mfa_enabled:
        raise HTTPException(status_code=409, detail="MFA is not on")
    _check_lockout(user.username)
    if not verify_password(body.password, user.password_hash) or mfa.verify(user, body.code) is None:
        _fail(user.username)
        raise HTTPException(status_code=401, detail="Password or code is not valid")
    mfa.reset(user)
    _set_session(response, user, mfa_done=False)
    audit.record(db, None, user.username, user.role, "mfa_disabled", {})
    db.commit()
    return {"user": user_out(user)}


class MfaCodeIn(BaseModel):
    code: str = Field(min_length=6, max_length=16)


@router.post("/mfa/recovery-codes")
def mfa_new_recovery_codes(body: MfaCodeIn, user: m.User = Depends(current_user), db: Session = Depends(get_db)):
    """Replace all recovery codes (the old ones stop working). Needs a current authenticator code."""
    if not user.mfa_enabled:
        raise HTTPException(status_code=409, detail="MFA is not on")
    _check_lockout(user.username)
    if mfa.verify(user, body.code, allow_recovery=False) is None:
        _fail(user.username)
        raise HTTPException(status_code=401, detail="That code is not valid")
    codes, hashes = mfa.new_recovery_codes()
    user.mfa_recovery = hashes
    audit.record(db, None, user.username, user.role, "mfa_recovery_codes_replaced", {})
    db.commit()
    return {"recovery_codes": codes}
