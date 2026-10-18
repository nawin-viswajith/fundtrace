"""Multi-factor authentication: time-based one-time passwords (RFC 6238) and recovery codes.

- 160-bit secrets, HMAC-SHA1, 6 digits, 30-second steps (what authenticator apps expect); ±1 step for clock drift
- a code's time step can be used once (replay guard: `mfa_last_step`)
- 10 single-use recovery codes, stored only as SHA-256 hashes (they are high-entropy random values)
- the secret is stored encrypted (users.mfa_secret is an encrypted column)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

from app import models as m
from app.config import get_settings

STEP_SECONDS, DIGITS, DRIFT_STEPS = 30, 6, 1
RECOVERY_CODES = 10


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8))
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** DIGITS)
    return str(code).zfill(DIGITS)


def totp(secret_b32: str, at: float | None = None) -> str:
    return _hotp(secret_b32, int((at if at is not None else time.time()) // STEP_SECONDS))


def match_step(secret_b32: str, code: str, at: float | None = None) -> int | None:
    """The time step the code belongs to (within the drift window), or None."""
    code = "".join(ch for ch in code if ch.isdigit())
    if len(code) != DIGITS:
        return None
    now = int((at if at is not None else time.time()) // STEP_SECONDS)
    for step in range(now - DRIFT_STEPS, now + DRIFT_STEPS + 1):
        if hmac.compare_digest(_hotp(secret_b32, step), code):
            return step
    return None


def provisioning_uri(user: m.User, secret_b32: str) -> str:
    issuer = get_settings().mfa_issuer
    label = quote(f"{issuer}:{user.username}")
    return f"otpauth://totp/{label}?" + urlencode({"secret": secret_b32, "issuer": issuer, "algorithm": "SHA1",
                                                   "digits": DIGITS, "period": STEP_SECONDS})


def qr_svg_data_uri(uri: str) -> str | None:
    try:
        import segno
    except ImportError:  # optional: the setup key is always shown as text too
        return None
    return segno.make(uri, error="m").svg_data_uri(scale=5, border=2)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").strip().lower().encode()).hexdigest()


def new_recovery_codes() -> tuple[list[str], list[str]]:
    """(codes to show once, hashes to store)."""
    codes = []
    for _ in range(RECOVERY_CODES):
        raw = secrets.token_hex(5)  # 40 bits each
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes, [_hash_code(c) for c in codes]


def verify(user: m.User, code: str, allow_recovery: bool = True) -> str | None:
    """Check a TOTP or recovery code. Returns "totp" / "recovery" and consumes it, or None."""
    if not user.mfa_secret:
        return None
    step = match_step(user.mfa_secret, code)
    if step is not None:
        if user.mfa_last_step is not None and step <= user.mfa_last_step:
            return None  # this code (or an older one) was already used
        user.mfa_last_step = step
        return "totp"
    if allow_recovery and user.mfa_recovery:
        h = _hash_code(code)
        remaining = [x for x in user.mfa_recovery if not hmac.compare_digest(x, h)]
        if len(remaining) < len(user.mfa_recovery):
            user.mfa_recovery = remaining
            return "recovery"
    return None


def required_for(user: m.User) -> bool:
    return user.role in get_settings().mfa_roles


def reset(user: m.User) -> None:
    user.mfa_enabled, user.mfa_secret, user.mfa_last_step, user.mfa_recovery = False, None, None, None
