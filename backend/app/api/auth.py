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
from app.security import COOKIE, create_token, current_user, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
_failures: dict[str, list[float]] = defaultdict(list)
MAX_FAILURES, WINDOW_S = 5, 300


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def user_out(u: m.User) -> dict:
    return {"id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role}


@router.post("/login")
def login(body: LoginIn, response: Response, request: Request, db: Session = Depends(get_db)):
    key = body.username.lower()
    now = time.time()
    _failures[key] = [t for t in _failures[key] if now - t < WINDOW_S]
    if len(_failures[key]) >= MAX_FAILURES:
        raise HTTPException(status_code=429, detail="Too many failed attempts. Try again in a few minutes.")
    user = db.scalar(select(m.User).where(m.User.username == body.username))
    if not user or not user.is_active or not verify_password(body.password, user.password_hash):
        _failures[key].append(now)
        raise HTTPException(status_code=401, detail="Invalid username or password")
    _failures.pop(key, None)
    token = create_token(user)
    s = get_settings()
    response.set_cookie(COOKIE, token, httponly=True, secure=s.cookie_secure, samesite="strict", max_age=s.jwt_ttl_minutes * 60, path="/")
    audit.record(db, None, user.username, user.role, "login", {})
    db.commit()
    return {"user": user_out(user)}


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
    return {
        "demo": True,
        "demo_users": [{"username": "inv.asha", "role": "investigator"}, {"username": "inv.ravi", "role": "investigator"},
                       {"username": "sup.meera", "role": "supervisor"}, {"username": "admin", "role": "admin"}],
        "demo_password": s.demo_password if s.show_demo_credentials else None,
        "firebase_enabled": bool(s.firebase_project_id),
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
    response.set_cookie(COOKIE, create_token(user), httponly=True, secure=s.cookie_secure, samesite="strict",
                        max_age=s.jwt_ttl_minutes * 60, path="/")
    audit.record(db, None, user.username, user.role, "login", {"provider": "firebase"})
    db.commit()
    return {"user": user_out(user)}
