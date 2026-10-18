"""Sensitive-data detection (DLP) for case notes, uploaded evidence and text sent to the LLM.

Two backends behind one interface:
- ``local``: built-in detectors with checksums where the format has one (Luhn for card numbers, Verhoeff for
  Aadhaar), so random digit runs are not reported. Works offline and for every deployment.
- ``gcp``: Cloud DLP `content:inspect` (text, images and PDFs, with OCR). Falls back to ``local`` on any error,
  and the result says which backend ran.

Policy (what happens to a finding) is separate from detection:
- MASK types are replaced in case notes before they are stored, and in customer text before it reaches the LLM:
  card numbers, Aadhaar numbers, and one-time passwords / PINs / passwords a customer wrote down.
- Other types (email, phone, UPI id, PAN, IFSC) are reported only — investigators legitimately need them.
Findings never contain the matched value: only its type, a count and the likelihood.
"""
from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass

from app.config import get_settings

log = logging.getLogger("fundtrace.dlp")

LABELS = {
    "CREDIT_CARD_NUMBER": "Card number",
    "INDIA_AADHAAR_INDIVIDUAL": "Aadhaar number",
    "INDIA_PAN_INDIVIDUAL": "PAN (tax id)",
    "SECRET_CODE": "OTP / PIN / password",
    "EMAIL_ADDRESS": "Email address",
    "PHONE_NUMBER": "Phone number",
    "UPI_ID": "UPI id",
    "IFSC_CODE": "IFSC code",
}
MASK_TYPES = {"CREDIT_CARD_NUMBER", "INDIA_AADHAAR_INDIVIDUAL", "SECRET_CODE"}
CLOUD_INFO_TYPES = ["CREDIT_CARD_NUMBER", "INDIA_AADHAAR_INDIVIDUAL", "INDIA_PAN_INDIVIDUAL", "EMAIL_ADDRESS", "PHONE_NUMBER"]
CLOUD_LIKELY = {"LIKELY", "VERY_LIKELY"}
CLOUD_BYTES_TYPES = {"image/png": "IMAGE_PNG", "image/jpeg": "IMAGE_JPEG", "application/pdf": "PDF", "text/plain": "TEXT_UTF8"}


@dataclass
class Match:
    info_type: str
    start: int
    end: int
    likelihood: str = "LIKELY"


# ---------------------------------------------------------------------------- local detectors

def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


_VD = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
       [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1], [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
       [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VP = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
       [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1], [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def _verhoeff_ok(digits: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _VD[c][_VP[i % 8][int(ch)]]
    return c == 0


_CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
_AADHAAR = re.compile(r"(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)")
_PAN = re.compile(r"\b[A-Z]{3}[PCHFATBLJG][A-Z]\d{4}[A-Z]\b")
_IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_UPI = re.compile(r"\b[\w.-]{2,64}@(?:ok\w+|upi|ybl|paytm|ibl|axl|apl|icici|sbi|hdfcbank|axisbank|kotak)\b", re.I)
_PHONE = re.compile(r"(?<![\d+])(?:\+91[ -]?|91[ -])?[6-9]\d{4}[ -]?\d{5}(?!\d)")  # a bare 91+10 digits is usually a UTR
# A short code next to a word that names it: "OTP is 482913", "my PIN 1234", "password: hunter2"
_SECRET = re.compile(r"\b(?:otp|one[ -]time (?:password|code)|m?pin|cvv|password|passcode)\b\s*(?:is|was|:|=|-)?\s*"
                     r"([A-Za-z0-9@#$%^&*!]{3,12})(?![,.]?\d)", re.I)
_AADHAAR_WORD = re.compile(r"\b(?:aadhaa?r|uidai|uid)\b", re.I)


def _local_scan(text: str) -> list[Match]:
    out: list[Match] = []
    taken: list[tuple[int, int]] = []

    def add(t: str, s: int, e: int, lk: str = "LIKELY") -> None:
        if any(s < b and a < e for a, b in taken):
            return
        taken.append((s, e))
        out.append(Match(t, s, e, lk))

    for mt in _SECRET.finditer(text):
        if any(ch.isdigit() for ch in mt.group(1)):  # "OTP request", "password reset" are not secrets
            add("SECRET_CODE", mt.start(1), mt.end(1), "VERY_LIKELY")
    for mt in _CARD.finditer(text):
        d = re.sub(r"\D", "", mt.group())
        if 13 <= len(d) <= 19 and _luhn_ok(d) and len(set(d)) > 1:
            add("CREDIT_CARD_NUMBER", mt.start(), mt.end(), "VERY_LIKELY")
    for mt in _AADHAAR.finditer(text):
        d = re.sub(r"\D", "", mt.group())
        # 12-digit payment references (UTR/RRN) look the same, so require the 4-4-4 layout or the word nearby.
        grouped = len(mt.group()) == 14
        named = bool(_AADHAAR_WORD.search(text[max(0, mt.start() - 40):mt.start()]))
        if len(d) == 12 and _verhoeff_ok(d) and (grouped or named):
            add("INDIA_AADHAAR_INDIVIDUAL", mt.start(), mt.end())
    for mt in _UPI.finditer(text):
        add("UPI_ID", mt.start(), mt.end())
    for mt in _EMAIL.finditer(text):
        add("EMAIL_ADDRESS", mt.start(), mt.end())
    for mt in _PAN.finditer(text):
        add("INDIA_PAN_INDIVIDUAL", mt.start(), mt.end())
    for mt in _IFSC.finditer(text):
        add("IFSC_CODE", mt.start(), mt.end(), "POSSIBLE")
    for mt in _PHONE.finditer(text):
        add("PHONE_NUMBER", mt.start(), mt.end(), "POSSIBLE")
    return sorted(out, key=lambda x: x.start)


# ---------------------------------------------------------------------------- Cloud DLP

def _cloud_inspect(item: dict) -> list[dict]:
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    s = get_settings()
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    body = {"item": item, "inspectConfig": {"infoTypes": [{"name": n} for n in CLOUD_INFO_TYPES], "minLikelihood": "POSSIBLE",
                                            "includeQuote": False, "limits": {"maxFindingsPerRequest": 200}}}
    r = AuthorizedSession(creds).post(f"https://dlp.googleapis.com/v2/projects/{s.gcp_project}/locations/global/content:inspect",
                                      json=body, timeout=20)
    r.raise_for_status()
    return r.json().get("result", {}).get("findings", [])


def backend() -> str:
    b = get_settings().dlp_backend
    return "gcp" if b == "gcp" and get_settings().gcp_project else ("off" if b == "off" else "local")


# ---------------------------------------------------------------------------- public API

def _summarise(matches: list[tuple[str, str]]) -> list[dict]:
    counts: dict[str, dict] = {}
    rank = {"POSSIBLE": 1, "LIKELY": 2, "VERY_LIKELY": 3}
    for t, lk in matches:
        c = counts.setdefault(t, {"type": t, "label": LABELS.get(t, t.replace("_", " ").title()), "count": 0, "likelihood": lk,
                                  "masked_in_notes": t in MASK_TYPES})
        c["count"] += 1
        if rank.get(lk, 0) > rank.get(c["likelihood"], 0):
            c["likelihood"] = lk
    return sorted(counts.values(), key=lambda c: (not c["masked_in_notes"], c["label"]))


def scan_text(text: str) -> dict:
    """Findings for a piece of text. Uses the local detectors (fast, deterministic) for text."""
    if backend() == "off" or not text:
        return {"backend": backend(), "status": "not_scanned" if backend() == "off" else "scanned", "findings": []}
    return {"backend": "local", "status": "scanned", "findings": _summarise([(m_.info_type, m_.likelihood) for m_ in _local_scan(text)])}


def mask(text: str | None, types: set[str] = MASK_TYPES) -> tuple[str | None, list[dict]]:
    """Replace values of `types` with [REDACTED: label]. Returns (masked text, findings for the masked values)."""
    if not text or backend() == "off":
        return text, []
    found = [m_ for m_ in _local_scan(text) if m_.info_type in types]
    out = text
    for m_ in sorted(found, key=lambda x: x.start, reverse=True):
        out = out[:m_.start] + f"[REDACTED: {LABELS[m_.info_type]}]" + out[m_.end:]
    return out, _summarise([(m_.info_type, m_.likelihood) for m_ in found])


def redact_for_llm(text: str | None) -> str | None:
    """Customer text on its way to the LLM: card numbers, Aadhaar numbers and written-down OTPs/PINs are masked."""
    return mask(text)[0]


def scan_file(data: bytes, mime: str) -> dict:
    """Scan an uploaded file. Text is scanned locally; images and PDFs need Cloud DLP (OCR)."""
    from app.models import utcnow

    which = backend()
    at = utcnow().isoformat() + "Z"
    if which == "off":
        return {"backend": "off", "status": "not_scanned", "findings": [], "note": "DLP scanning is turned off", "scanned_at": at}
    if which == "gcp" and mime in CLOUD_BYTES_TYPES:
        try:
            raw = _cloud_inspect({"byteItem": {"type": CLOUD_BYTES_TYPES[mime], "data": base64.b64encode(data).decode()}})
            pairs = [(f["infoType"]["name"], f.get("likelihood", "POSSIBLE")) for f in raw
                     if f.get("likelihood") in CLOUD_LIKELY or f["infoType"]["name"] in MASK_TYPES]
            if mime == "text/plain":  # the cloud has no detector for written-down OTPs/PINs; add the local one
                pairs += [(m_.info_type, m_.likelihood) for m_ in _local_scan(data.decode("utf-8", "replace")) if m_.info_type == "SECRET_CODE"]
            return {"backend": "gcp", "status": "scanned", "findings": _summarise(pairs), "scanned_at": at}
        except Exception as exc:
            log.warning("Cloud DLP inspect failed, using local detectors: %s", type(exc).__name__)
    if mime == "text/plain":
        res = scan_text(data.decode("utf-8", "replace"))
        return {**res, "backend": "local", "scanned_at": at}
    return {"backend": "local", "status": "not_scanned", "findings": [], "scanned_at": at,
            "note": "Images and PDFs need Cloud DLP (DLP_BACKEND=gcp) to be read for sensitive data"}
