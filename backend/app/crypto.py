"""Field-level encryption for personal data and case narratives (envelope pattern).

Values are encrypted with AES-256-GCM before they reach the database and decrypted on read, through
SQLAlchemy column types, so services and the API never handle ciphertext. Stored format:

    enc:v1:<key id>:<base64(nonce || ciphertext || tag)>

The column's name is bound as associated data, so a ciphertext copied into another column does not decrypt.

Keys:
- FIELD_ENCRYPTION_KEYS="k2:<base64 32 bytes>,k1:<base64>" — the first key encrypts, every key decrypts (rotation).
- On GCP the data key is kept wrapped by Cloud KMS (FIELD_KEY_KMS_NAME + FIELD_KEY_WRAPPED) and unwrapped once
  at start-up, so the plaintext key never sits in configuration.
- Locally (not in the cloud) a development key derived from JWT_SECRET is used when neither is set.

Rows written before encryption was enabled stay readable (plaintext passes through) and `backfill` encrypts them.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.types import TypeDecorator

from app.config import get_settings

log = logging.getLogger("fundtrace.crypto")
PREFIX = "enc:v1:"


class EncryptionConfigError(RuntimeError):
    pass


@dataclass
class Keyring:
    active: str
    keys: dict[str, bytes]
    source: str


_ring: Keyring | None = None


def _parse_keys(spec: str) -> dict[str, bytes]:
    keys: dict[str, bytes] = {}
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        kid, _, b64 = part.partition(":")
        key = base64.b64decode(b64)
        if not kid or len(key) != 32:
            raise EncryptionConfigError("FIELD_ENCRYPTION_KEYS entries must be 'kid:<base64 of 32 bytes>'")
        keys[kid] = key
    return keys


def _unwrap_with_kms(name: str, wrapped_b64: str) -> bytes:
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloudkms"])
    r = AuthorizedSession(creds).post(f"https://cloudkms.googleapis.com/v1/{name}:decrypt", json={"ciphertext": wrapped_b64}, timeout=15)
    if r.status_code != 200:
        raise EncryptionConfigError(f"Cloud KMS could not unwrap the field key (HTTP {r.status_code})")
    key = base64.b64decode(r.json()["plaintext"])
    if len(key) != 32:
        raise EncryptionConfigError("The unwrapped field key is not 32 bytes")
    return key


def keyring() -> Keyring:
    global _ring
    if _ring is not None:
        return _ring
    s = get_settings()
    if s.field_encryption_keys:
        keys = _parse_keys(s.field_encryption_keys)
        _ring = Keyring(active=next(iter(keys)), keys=keys, source="config")
    elif s.field_key_kms_name and s.field_key_wrapped:
        kid = "kms-" + hashlib.sha256(s.field_key_wrapped.encode()).hexdigest()[:8]
        _ring = Keyring(active=kid, keys={kid: _unwrap_with_kms(s.field_key_kms_name, s.field_key_wrapped)}, source="cloud-kms")
    elif s.environment == "cloud":
        raise EncryptionConfigError("Field encryption is required in the cloud: set FIELD_KEY_KMS_NAME and FIELD_KEY_WRAPPED")
    else:
        key = hashlib.sha256(b"fundtrace-dev-field-key:" + s.jwt_secret.encode()).digest()
        _ring = Keyring(active="dev", keys={"dev": key}, source="development key (derived from JWT_SECRET)")
    return _ring


def reset_keyring() -> None:
    global _ring
    _ring = None


def encrypt(value: str, context: str) -> str:
    ring = keyring()
    nonce = os.urandom(12)
    ct = AESGCM(ring.keys[ring.active]).encrypt(nonce, value.encode("utf-8"), context.encode())
    return f"{PREFIX}{ring.active}:{base64.b64encode(nonce + ct).decode()}"


def decrypt(stored: str, context: str) -> str:
    if not stored.startswith(PREFIX):
        return stored  # written before encryption was enabled; `backfill` re-writes it encrypted
    kid, _, b64 = stored[len(PREFIX):].partition(":")
    key = keyring().keys.get(kid)
    if key is None:
        raise EncryptionConfigError(f"No field key with id {kid!r} is configured")
    raw = base64.b64decode(b64)
    return AESGCM(key).decrypt(raw[:12], raw[12:], context.encode()).decode("utf-8")


def is_encrypted(stored: str | None) -> bool:
    return bool(stored) and stored.startswith(PREFIX)


class EncryptedText(TypeDecorator):
    """A text column stored encrypted. `context` (table.column) is bound as associated data."""

    impl = Text
    cache_ok = True

    def __init__(self, context: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.context = context

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt(str(value), self.context)

    def process_result_value(self, value, dialect):
        return None if value is None else decrypt(value, self.context)


class EncryptedJSON(TypeDecorator):
    """A JSON value stored as encrypted text."""

    impl = Text
    cache_ok = True

    def __init__(self, context: str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.context = context

    def process_bind_param(self, value, dialect):
        return None if value is None else encrypt(json.dumps(value, ensure_ascii=False), self.context)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        plain = decrypt(value, self.context)
        return json.loads(plain) if isinstance(plain, str) else plain


def encrypted_columns() -> list[tuple[type, str]]:
    """(model, attribute) for every encrypted column, discovered from the mapped tables."""
    from app.db import Base

    out = []
    for mapper in Base.registry.mappers:
        for col in mapper.columns:
            if isinstance(col.type, (EncryptedText, EncryptedJSON)):
                out.append((mapper.class_, col.key))
    return out


def backfill(db: Session, batch: int = 500) -> int:
    """Encrypt values written before encryption was enabled. Idempotent; returns the number of values encrypted."""
    done = 0
    for model, attr in encrypted_columns():
        table = model.__table__
        col = table.c[attr].name
        pk = list(table.primary_key.columns)[0].name
        # Table and column names come from the ORM metadata, never from input.
        ids = [r[0] for r in db.execute(text(f"SELECT {pk} FROM {table.name} WHERE {col} IS NOT NULL AND {col} NOT LIKE 'enc:v1:%'"))]
        for i in range(0, len(ids), batch):
            for obj in db.query(model).filter(getattr(model, pk).in_(ids[i:i + batch])):
                flag_modified(obj, attr)
                done += 1
            db.flush()
    if done:
        log.info("field encryption backfill: %s values encrypted", done)
    return done


def status() -> dict:
    ring = keyring()
    return {"algorithm": "AES-256-GCM", "active_key": ring.active, "keys": len(ring.keys), "key_source": ring.source,
            "fields": [f"{m.__tablename__}.{a}" for m, a in encrypted_columns()]}
