"""Customer-facing generative AI in the portal: "Ask Demo Bank", the safety check, and reading a dispute story.

"Ask Demo Bank" answers questions about banking and payments, fraud safety and scams, disputes, and the signed-in
customer's own disputes. What keeps it safe and on-topic is code, not the prompt:
- Scope: Gemini classifies the intent in a fixed schema; out_of_scope gets a fixed refusal written here.
- Grounding: code retrieves the best help articles (data/customer_help.yaml, BM25 scoring) and passes only those. The
  answer must cite them; an answer citing nothing valid, mentioning a dispute that isn't the customer's, or asking for
  an OTP/PIN is dropped for the best article's own summary.
- Personal context is minimal: the customer's own disputes (reference, plain status, next deadline). Never other
  customers' data, risk signals or AI reports.
- Customer text is DLP-masked before it reaches Gemini and fenced as untrusted. An OTP/PIN/card number typed by the
  customer gets a code-written warning.
- When AI is unavailable, over budget or fails, the best-matching article answers ("From our help articles").

The safety check on the portal home is deterministic: computed from the customer's own payments and sign-ins.
"""
from __future__ import annotations

import json
import logging
import math
import re
import statistics
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.ai import prompts
from app.ai.llm import Gateway, get_gateway
from app.ai.schemas import CustomerHelpAnswer, HelpIntent, StoryExtraction
from app.services import dlp, intake
from app.services.trace import fmt_amount

log = logging.getLogger("fundtrace.customer_help")

HELP_FILE = Path(__file__).resolve().parent.parent / "data" / "customer_help.yaml"
TOP_K = 4
MAX_WORDS = 120
MAX_HISTORY = 6
DEFAULT_SOURCES = ("DSP-HOW", "SAFE-NEVER-SHARE", "SAFE-FIRST-HOUR")

AI_LABEL = "Answer by AI (Gemini), from Demo Bank's help articles"
ARTICLE_LABEL = "From our help articles"
POLICY_LABEL = "Demo Bank assistant"

SUGGESTIONS = ["Someone asked for my OTP", "How long does a dispute take?", "What proof should I send?",
               "Where is my dispute?", "I think I was scammed just now"]
REFUSAL = ("I'm just Demo Bank's helper, so that one's outside what I know! I can chat about banking and payments, "
           "staying safe from fraud and scams, and disputes with Demo Bank — including where your own disputes have "
           "got to. Here's what I can help with:")
NOT_FOUND = "Hmm, I couldn't find a help article that answers that. Here's what I can help with instead:"

# Small talk never needs Gemini: it's instant, free, and still works when the AI is down. Anything longer than a
# bare greeting/thanks/goodbye (e.g. "hi, did someone call me about my KYC?") still goes to the model as normal.
GREETING_RE = re.compile(r"^(hi+|hello+|hey+|hiya|yo|howdy|good\s*(morning|afternoon|evening|day))[\s!.,]*$", re.I)
HOW_ARE_YOU_RE = re.compile(r"^how\s*(are|'?re)\s*(you|u)([\s!?.,]*(doing|going)?)?[\s!?.,]*$", re.I)
THANKS_RE = re.compile(r"^(thanks?|thank\s*you|thx|ty|cheers|appreciate\s*it|great|awesome|perfect)[\s!.,]*$", re.I)
BYE_RE = re.compile(r"^(bye|goodbye|see\s*ya|see\s*you|take\s*care|that'?s\s*all|ok(ay)?(\s*thanks)?|got\s*it|cool)[\s!.,]*$", re.I)
SECRET_WARNING = ("For your safety I've hidden what looked like an OTP, PIN, password or card number in your message. Never share "
                  "these with anyone, not even Demo Bank. If you've already given them to someone, block your card or UPI in the "
                  "app and call 1930 now.")

ACTION_LABELS = {
    "start_dispute_chat": ("Raise a dispute in chat", "/portal/new/chat"),
    "start_dispute_form": ("Use the dispute form", "/portal/new/form"),
    "call_1930": ("Call 1930 (cyber-crime helpline)", "tel:1930"),
    "report_cybercrime": ("Report at cybercrime.gov.in", "https://cybercrime.gov.in"),
}

# Phrases that mean "this is happening now"; any of them makes the reply lead with the first-hour steps.
URGENT = re.compile(r"\b(just now|right now|scammed|cheated|lost (my )?money|money (is |has )?gone|stolen|hacked|"
                    r"being scammed|someone is (calling|asking)|took (all )?my money|emptied)\b", re.I)
STATUS_Q = re.compile(r"\b(where|status|progress|update|track)\b.{0,40}\b(dispute|complaint|claim|case)s?\b|"
                      r"\bmy (dispute|complaint|claim|case)s?\b|\bCASE-\d+\b", re.I)
CASE_ID = re.compile(r"\bCASE-\d+\b", re.I)
# An answer that asks the customer for a secret (and doesn't say "never") is dropped.
ASKS_SECRET = re.compile(r"\b(share|send|tell|give|enter|type|provide|confirm|read out)\b[^.?!]{0,40}"
                         r"\b(otp|one[- ]time|pin|mpin|cvv|password|card number|aadhaa?r)\b", re.I)
NEGATION = re.compile(r"\b(never|don'?t|do not|not|no one|nobody|won'?t|will not|avoid|isn'?t)\b", re.I)


# ---------------------------------------------------------------------------- knowledge base

SLA_GROUPS = {  # who each SLA policy applies to, in the customer's words
    "IN-UET": "A payment you didn't make, someone getting into your account, or your card used online",
    "IN-APP": "You were tricked into making a payment",
    "DEFAULT": "Other disputes (charged twice or the wrong amount, or paid but didn't get it)",
}


def _duration(ms: dict) -> str:
    if "working_days" in ms:
        return f"{ms['working_days']} working days"
    if "hours" in ms:
        return f"{ms['hours']} hours"
    return f"{ms['days']} days"


def deadline_text() -> str:
    """The SLA configuration in plain words, so the help articles and the case file always agree."""
    from app.services.scoring import SLA_POLICIES

    lines = []
    for key, pol in SLA_POLICIES.items():
        parts = [f"{intake.MILESTONE_PLAIN.get(ms['key'], ms['label']).lower()} within {_duration(ms)}" for ms in pol["milestones"]]
        group = SLA_GROUPS.get(key, key)
        lines.append(f"{group}: {'; '.join(parts)}.")
    return " ".join(lines)


@lru_cache(maxsize=1)
def articles() -> dict[str, dict]:
    raw = yaml.safe_load(HELP_FILE.read_text(encoding="utf-8"))
    deadlines = deadline_text()
    out: dict[str, dict] = {}
    for a in raw:
        a = dict(a)
        for f in ("summary", "body"):
            a[f] = " ".join(str(a.get(f, "")).replace("{deadlines}", deadlines).split())
        a.setdefault("keywords", [])
        a.setdefault("actions", [])
        a.setdefault("signs", [])
        a.setdefault("do", [])
        assert a["id"] not in out, f"duplicate help article {a['id']}"
        out[a["id"]] = a
    _index.cache_clear()
    return out


def article_brief(a: dict) -> dict:
    return {"id": a["id"], "title": a["title"], "summary": a["summary"], "topic": a["topic"]}


# ---------------------------------------------------------------------------- retrieval (BM25 over the articles)

STOP = set("a an and are as at be been but by can could did do does for from had has have how i if in into is it its me my "
           "of on or our so than that the their them then there these they this to too was we were what when where which who "
           "why will with would you your yours about should just get got any".split())
FORMS = {"scammed": "scam", "scammer": "scam", "scammers": "scam", "cheated": "scam", "fraudster": "fraud", "fraudsters": "fraud",
         "fraudulent": "fraud", "shared": "share", "sharing": "share", "blocked": "block", "blocking": "block", "asked": "ask",
         "asking": "ask", "hacked": "hack", "called": "call", "calling": "call", "caller": "call", "otps": "otp", "pins": "pin",
         "disputes": "dispute", "investigated": "investigate", "investigation": "investigate", "deadlines": "deadline",
         "screenshots": "screenshot", "documents": "document", "proofs": "proof", "evidence": "proof", "refunded": "refund",
         "stolen": "steal", "took": "take", "taken": "take", "paid": "pay", "payment": "pay", "payments": "pay",
         "transferred": "transfer", "sent": "send", "lost": "lose", "loss": "lose", "messages": "message", "sms": "message"}


def _tokens(text: str) -> list[str]:
    words = []
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        w = FORMS.get(w, w)
        if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        if w not in STOP:
            words.append(w)
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]


@lru_cache(maxsize=1)
def _index() -> tuple[dict[str, list[str]], dict[str, int], float]:
    docs: dict[str, list[str]] = {}
    for a in articles().values():
        kw = " . ".join(a["keywords"])
        docs[a["id"]] = _tokens(a["title"]) * 2 + _tokens(kw) * 3 + _tokens(a["summary"]) + _tokens(a["body"])
    df: dict[str, int] = {}
    for toks in docs.values():
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    avg = sum(len(t) for t in docs.values()) / max(1, len(docs))
    return docs, df, avg


def retrieve(question: str, k: int = TOP_K) -> list[tuple[str, float]]:
    """The best-matching article ids for a question, best first (only articles that share a word with it)."""
    docs, df, avg = _index()
    n = len(docs)
    q = set(_tokens(question))
    scored = []
    for aid, toks in docs.items():
        tf: dict[str, int] = {}
        for t in toks:
            if t in q:
                tf[t] = tf.get(t, 0) + 1
        s = 0.0
        for t, f in tf.items():
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * len(toks) / avg))
        if s > 0:
            scored.append((aid, round(s, 3)))
    return sorted(scored, key=lambda x: -x[1])[:k]


# ---------------------------------------------------------------------------- the customer's own disputes (minimal)

def own_disputes(db: Session, user: m.User) -> list[dict]:
    """Reference, plain status, what we need and the next deadline. Nothing internal."""
    out = []
    for d in intake.list_disputes(db, user):
        view = intake.dispute_view(db, user, intake.own_case(db, user, d["case_id"]))
        nxt = min(view["deadlines"], key=lambda x: x["due_at"]) if view["deadlines"] else None
        out.append({"case_id": d["case_id"], "payment": f"{d['payment']['amount']} to {d['payment']['paid_to']}",
                    "paid_on": d["payment"]["occurred_at"][:10], "reason": d["reason"], "status": view["status"], "step": view["step"],
                    "explain": view["explain"], "needs_from_you": [r["label"] for r in view["requests"]],
                    "next_deadline": {"label": nxt["label"], "due_at": nxt["due_at"]} if nxt else None, "decision": view["decision"]})
    return out


def _status_text(disputes: list[dict]) -> str:
    if not disputes:
        return ("You haven't raised any disputes with us yet. If something is wrong with a payment, you can raise one in about "
                "two minutes.")
    parts = []
    for d in disputes[:3]:
        s = f"{d['case_id']} ({d['payment']}): {d['status']}."
        if d["needs_from_you"]:
            s += f" We need from you: {d['needs_from_you'][0].lower()}."
        elif d["next_deadline"]:
            s += f" Next: {d['next_deadline']['label'].lower()} by {_day(d['next_deadline']['due_at'])}."
        parts.append(s)
    lead = "Here is where your dispute is:" if len(disputes) == 1 else f"You have {len(disputes)} disputes:"
    return f"{lead} " + " ".join(parts)


def _day(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso.rstrip("Z"))
    except ValueError:
        return iso[:10]
    return f"{d.day} {d.strftime('%b %Y')}"


# ---------------------------------------------------------------------------- answering

def _words(text: str, limit: int = MAX_WORDS) -> str:
    """At most `limit` words, cut at a sentence end where possible."""
    w = text.split()
    if len(w) <= limit:
        return " ".join(w)
    cut = " ".join(w[:limit])
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return cut[:end + 1] if end > len(cut) // 2 else cut.rstrip(",;:") + "…"


def asks_for_secret(text: str) -> bool:
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if ASKS_SECRET.search(sentence) and not NEGATION.search(sentence):
            return True
    return False


def _action(kind: str, case_id: str | None = None) -> dict:
    if kind == "open_dispute":
        return {"kind": kind, "label": f"Open dispute {case_id}", "href": f"/portal/disputes/{case_id}", "case_id": case_id}
    label, href = ACTION_LABELS[kind]
    return {"kind": kind, "label": label, "href": href}


def _actions(kinds: list[str], *, urgent: bool, intent: str, own_ids: list[str], open_case: str | None) -> list[dict]:
    seq: list[str] = []
    if urgent:
        seq += ["call_1930", "report_cybercrime", "start_dispute_chat"]
    if intent == HelpIntent.raise_dispute.value:
        seq += ["start_dispute_chat", "start_dispute_form"]
    seq += kinds
    out, seen = [], set()
    for k in seq:
        if k in seen:
            continue
        if k == "open_dispute":
            case = open_case if open_case in own_ids else None
            if not case:
                continue
            out.append(_action(k, case))
        elif k in ACTION_LABELS:
            out.append(_action(k))
        seen.add(k)
    return out[:3]


def _base(warning: str | None, masked_msg: str | None) -> dict:
    return {"status": "ok", "source": "ai", "source_label": AI_LABEL, "intent": None, "text": "", "warning": warning, "urgent": False,
            "masked_message": masked_msg, "articles": [], "disputes": [], "actions": [], "suggestions": [], "note": None}


def _fallback(out: dict, question: str, hits: list[tuple[str, float]], disputes: list[dict], note: str | None) -> dict:
    """Answer by code from the best-matching article (or the customer's own disputes for a status question)."""
    kb = articles()
    urgent = bool(URGENT.search(question))
    out.update(status="fallback", source="help_articles", source_label=ARTICLE_LABEL, note=note, urgent=urgent,
               suggestions=SUGGESTIONS[:])
    if urgent:
        art = kb["SAFE-FIRST-HOUR"]
    elif STATUS_Q.search(question):
        own = [d["case_id"] for d in disputes]
        out.update(intent=HelpIntent.my_dispute_status.value, text=_status_text(disputes), disputes=disputes,
                   articles=[article_brief(kb["DSP-STATUS"])],
                   actions=[_action("open_dispute", own[0])] if own else [_action("start_dispute_chat")])
        return out
    elif hits:
        art = kb[hits[0][0]]
    else:
        out.update(source="policy", source_label=POLICY_LABEL, intent=HelpIntent.out_of_scope.value, text=NOT_FOUND)
        return out
    out.update(intent=HelpIntent.urgent_fraud_now.value if urgent else ("safety" if art["topic"] in ("safety", "scam") else "faq"),
               text=art["summary"], articles=[article_brief(art)],
               actions=_actions(art["actions"], urgent=urgent, intent="faq", own_ids=[], open_case=None))
    return out


def _sources_block(ids: list[str]) -> str:
    kb = articles()
    parts = []
    for aid in ids:
        a = kb[aid]
        extra = ""
        if a["signs"]:
            extra += "\nWarning signs: " + "; ".join(a["signs"])
        if a["do"]:
            extra += "\nWhat to do: " + "; ".join(a["do"])
        parts.append(f"[{aid}] {a['title']}\n{a['body']}{extra}")
    return "\n\n".join(parts)


def _small_talk_reply(db: Session, user: m.User, msg: str) -> dict | None:
    """A bare greeting, "how are you", thanks or goodbye — answered instantly and warmly, no AI call needed."""
    if GREETING_RE.match(msg):
        name = intake.profile(db, user)["name"].split(" ")[0]
        text = (f"Hi {name}! I'm Ask Demo Bank. I can help with banking and payments, staying safe from fraud, "
                "raising or checking a dispute — what's up?")
    elif HOW_ARE_YOU_RE.match(msg):
        text = "Doing well, thanks for asking! What can I help you with today — a dispute, a safety question, or something else?"
    elif THANKS_RE.match(msg):
        text = "You're welcome! Anything else I can help with?"
    elif BYE_RE.match(msg):
        text = "Take care, and don't forget: we'll never ask for your OTP, PIN or password. Come back anytime!"
    else:
        return None
    out = _base(None, None)
    out.update(intent="greeting", text=text, suggestions=SUGGESTIONS[:3])
    return out


def ask(db: Session, user: m.User, message: str, history: list[dict] | None = None, gateway: Gateway | None = None) -> dict:
    """One question to "Ask Demo Bank". Always returns an answer the customer can act on, with or without AI."""
    intake.customer_of(user)
    msg = " ".join((message or "").split())
    if not 2 <= len(msg) <= 1000:
        return {**_base(None, None), "status": "invalid", "source": "policy", "source_label": POLICY_LABEL,
                "text": "Please write a question of up to 1000 characters.", "suggestions": SUGGESTIONS[:]}
    small_talk = _small_talk_reply(db, user, msg)
    if small_talk is not None:
        return _log(small_talk, msg)
    masked, findings = dlp.mask(msg)
    masked = masked or msg
    warning = SECRET_WARNING if findings else None
    out = _base(warning, masked if masked != msg else None)
    disputes = own_disputes(db, user)
    own_ids = [d["case_id"] for d in disputes]
    hits = retrieve(masked)

    gw = gateway or get_gateway()
    if not gw.available():
        return _log(_fallback(out, masked, hits, disputes, "The AI assistant isn't available right now, so this answer comes "
                                                            "straight from our help articles."), msg)

    source_ids = [h[0] for h in hits] or list(DEFAULT_SOURCES)
    if STATUS_Q.search(masked) and "DSP-STATUS" not in source_ids:
        source_ids.append("DSP-STATUS")
    convo = "\n".join(f"{'customer' if t.get('role') == 'user' else 'assistant'}: {str(t.get('text', ''))[:400]}"
                      for t in (history or [])[-MAX_HISTORY:])
    facts = [{k: d[k] for k in ("case_id", "payment", "paid_on", "reason", "status", "explain", "needs_from_you", "next_deadline",
                                "decision")} for d in disputes]
    contents = [f"{prompts.CUSTOMER_HELP_INSTRUCTIONS}\n\nTODAY: {m.utcnow().date().isoformat()}\n\n"
                f"HELP ARTICLES:\n{_sources_block(source_ids)}\n\n"
                f"YOUR DISPUTES (the signed-in customer's own; nothing else is available):\n{json.dumps(facts, ensure_ascii=False)}\n\n"
                f"CONVERSATION SO FAR:\n{prompts.fence(dlp.redact_for_llm(convo) or '(none)')}\n\n"
                f"CUSTOMER MESSAGE: {prompts.fence(masked)}"]
    res = gw.generate(node="customer_help", prompt_version=prompts.CUSTOMER_HELP_V, contents=contents, schema=CustomerHelpAnswer,
                      tier="chat", system=prompts.CUSTOMER_GROUND_RULES, db=db)
    if not res.ok:
        return _log(_fallback(out, masked, hits, disputes, "The AI assistant couldn't answer just now, so this answer comes "
                                                            "straight from our help articles."), msg)
    a: CustomerHelpAnswer = res.data
    out.update(model=res.model)
    intent = a.intent.value
    if a.intent == HelpIntent.out_of_scope:
        out.update(status="refused", source="policy", source_label=POLICY_LABEL, intent=intent, text=REFUSAL, suggestions=SUGGESTIONS[:])
        return _log(out, msg)

    cited = [x for x in dict.fromkeys(i.strip().upper() for i in a.cited_article_ids) if x in source_ids]
    cases = [x for x in dict.fromkeys(i.strip().upper() for i in a.cited_case_ids) if x in own_ids]
    foreign = {c.upper() for c in CASE_ID.findall(a.answer)} - set(own_ids)
    problem = ("cites no help article" if not cited and not cases else "mentions a dispute that isn't yours" if foreign
               else "asks for a secret" if asks_for_secret(a.answer) else None)
    if problem:
        log.info("customer_help_rejected", extra={"fields": {"event": "customer_help_rejected", "why": problem}})
        return _log(_fallback(out, masked, hits, disputes, None), msg)

    urgent = intent == HelpIntent.urgent_fraud_now.value or bool(URGENT.search(masked))
    status_q = intent == HelpIntent.my_dispute_status.value
    kb = articles()
    out.update(intent=intent, urgent=urgent, text=_words(a.answer), articles=[article_brief(kb[x]) for x in cited],
               disputes=[d for d in disputes if d["case_id"] in cases] or (disputes if status_q else []),
               actions=_actions([k.value for k in a.actions], urgent=urgent, intent=intent, own_ids=own_ids,
                                open_case=(a.open_case_id or "").upper() or (cases[0] if cases else None)),
               suggestions=[q.strip() for q in a.follow_up_questions if 3 <= len(q.strip()) <= 90][:3] or SUGGESTIONS[:3])
    return _log(out, msg)


def _log(out: dict, msg: str) -> dict:
    # Never the customer's text: only what kind of answer it got.
    log.info("customer_help", extra={"fields": {"event": "customer_help", "status": out["status"], "intent": out["intent"],
                                                "source": out["source"], "length": len(msg), "masked": bool(out["warning"]),
                                                "articles": [a["id"] for a in out["articles"]]}})
    return out


def help_index() -> dict:
    kb = articles()
    return {"articles": [article_brief(a) for a in kb.values()], "suggestions": SUGGESTIONS, "label": AI_LABEL}


# ---------------------------------------------------------------------------- safety check (deterministic)

NEW_PAYEE_DAYS = 30
SIGNIN_DAYS = 14
LARGE_MIN_MINOR = 5000_00
LARGE_FACTOR = 3


def _device_kind(label: str | None) -> str:
    lab = (label or "").lower()
    for word, name in (("android", "an Android phone"), ("iphone", "an iPhone"), ("ipad", "an iPad"), ("windows", "a Windows computer"),
                       ("mac", "a Mac")):
        if word in lab:
            return name
    return "a device"


def scam_tips() -> list[dict]:
    return [{"id": a["id"], "title": a["title"], "summary": a["summary"], "signs": a["signs"], "do": a["do"]}
            for a in articles().values() if a["topic"] == "scam"]


def safety_check(db: Session, user: m.User) -> dict:
    """Plain-language checks on the customer's own account, and a scam to watch for."""
    cid = intake.customer_of(user)
    accts = intake.own_account_ids(db, cid)
    now = m.utcnow()
    items: list[dict] = []
    if accts:
        txns = db.scalars(select(m.Transaction).where(m.Transaction.debit_account_id.in_(accts), m.Transaction.status != "failed")
                          .order_by(m.Transaction.occurred_at).limit(3000)).all()
        disputed = dict(db.execute(select(m.DisputeCase.disputed_txn_id, m.DisputeCase.id).where(m.DisputeCase.customer_id == cid)).all())
        names: dict[str, str] = {}

        def payee(acc_id: str) -> str:
            if acc_id not in names:
                acc = db.get(m.Account, acc_id)
                names[acc_id] = intake._name(acc.holder_label) if acc else "Unknown"
            return names[acc_id]

        # New payees: someone paid for the first time in the last 30 days.
        first: dict[str, m.Transaction] = {}
        for t in txns:
            first.setdefault(t.credit_account_id, t)
        new = sorted((t for t in first.values() if now - t.occurred_at <= timedelta(days=NEW_PAYEE_DAYS)), key=lambda t: t.occurred_at,
                     reverse=True)
        if new:
            listed = ", ".join(f"{payee(t.credit_account_id)} ({fmt_amount(t.amount_minor, t.currency)} on {_day(t.occurred_at.isoformat())})"
                               for t in new[:3])
            more = f" and {len(new) - 3} more" if len(new) > 3 else ""
            items.append({"kind": "new_payees", "level": "check",
                          "title": f"{len(new)} new payee{'s' if len(new) > 1 else ''} in the last {NEW_PAYEE_DAYS} days",
                          "text": f"You paid {listed}{more} for the first time. If you don't recognise one, raise a dispute.",
                          "action": _action("start_dispute_chat")})

        # A payment much larger than usual (compared with the customer's other payments in the last 120 days).
        recent = [t for t in txns if now - t.occurred_at <= timedelta(days=intake.LIST_DAYS)]
        big = None
        for t in sorted((t for t in recent if now - t.occurred_at <= timedelta(days=NEW_PAYEE_DAYS)), key=lambda t: -t.amount_minor):
            others = [o.amount_minor for o in recent if o.id != t.id]
            if len(others) >= 3:
                usual = statistics.median(others)
                if t.amount_minor >= max(LARGE_FACTOR * usual, LARGE_MIN_MINOR):
                    big = (t, usual)
            break
        if big:
            t, usual = big
            case = disputed.get(t.id)
            text = (f"{fmt_amount(t.amount_minor, t.currency)} to {payee(t.credit_account_id)} on {_day(t.occurred_at.isoformat())} is much "
                    f"larger than your usual payments (typically about {fmt_amount(int(usual), t.currency)}).")
            text += (f" You've already raised a dispute for it ({case})." if case else " If you didn't make it, raise a dispute now.")
            items.append({"kind": "large_payment", "level": "check", "title": "A payment much larger than usual", "text": text,
                          "action": _action("open_dispute", case) if case else _action("start_dispute_chat")})

        # Failed sign-in or PIN attempts, and new devices.
        events = db.scalars(select(m.AuthEvent).where(m.AuthEvent.account_id.in_(accts),
                                                      m.AuthEvent.occurred_at >= now - timedelta(days=NEW_PAYEE_DAYS))).all()
        fails = [e for e in events if e.outcome == "failure" and now - e.occurred_at <= timedelta(days=SIGNIN_DAYS)]
        if fails:
            items.append({"kind": "failed_signins", "level": "check",
                          "title": f"{len(fails)} failed sign-in attempt{'s' if len(fails) > 1 else ''} in the last {SIGNIN_DAYS} days",
                          "text": "If that wasn't you, change your banking password and MPIN in the app. Never share them or an OTP "
                                  "with anyone."})
        dev_ids = {e.device_id for e in events if e.device_id and e.outcome == "success"}
        new_devs = [d for d in (db.get(m.Device, x) for x in sorted(dev_ids))
                    if d and now - d.first_seen_at <= timedelta(days=NEW_PAYEE_DAYS)]
        for d in new_devs[:2]:
            items.append({"kind": "new_device", "level": "check", "title": "A new device signed in",
                          "text": f"{_device_kind(d.label).capitalize()} we hadn't seen before signed in to your account on "
                                  f"{_day(d.first_seen_at.isoformat())}. If it wasn't you, block your UPI in the app, change your "
                                  f"password and call 1930."})
    tips = scam_tips()
    seed = sum(ord(c) for c in cid)
    return {"checked_at": now.isoformat() + "Z", "window_days": NEW_PAYEE_DAYS, "items": items, "all_clear": not items,
            "all_clear_text": (f"No new payees, unusual payments, failed sign-ins or new devices in the last {NEW_PAYEE_DAYS} days."
                               if not items else None),
            "tips": tips, "tip_index": (now.date().toordinal() + seed) % len(tips) if tips else 0}


# ---------------------------------------------------------------------------- reading a dispute story (guided chat)

SUGGESTABLE = {"reason": intake.REASONS, "otp_shared": intake.OTP_OPTIONS, "noticed": intake.NOTICED_OPTIONS,
               "contact_preference": intake.CONTACT_OPTIONS}


def clean_suggestions(raw) -> dict:
    """Only fixed option keys survive (the state comes back from the client)."""
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if k in SUGGESTABLE and isinstance(v, str) and v in SUGGESTABLE[k]}


def clean_hints(raw) -> dict:
    if not isinstance(raw, dict):
        return {}
    out: dict = {}
    amt = raw.get("amount_minor")
    if isinstance(amt, int) and not isinstance(amt, bool) and 0 < amt < 10**12:
        out["amount_minor"] = amt
    if isinstance(raw.get("payee"), str) and raw["payee"].strip():
        out["payee"] = raw["payee"].strip()[:64]
    if isinstance(raw.get("date"), str):
        try:
            out["date"] = date.fromisoformat(raw["date"][:10]).isoformat()
        except ValueError:
            pass
    return out


def extract_story(db: Session, user: m.User, story: str, gateway: Gateway | None = None) -> dict | None:
    """Fixed answers (to be confirmed by the customer) and payment hints from a DLP-masked story. None if AI can't help."""
    gw = gateway or get_gateway()
    if not gw.available():
        return None
    today = m.utcnow().date()
    contents = [f"{prompts.INTAKE_EXTRACT_INSTRUCTIONS}\n\nTODAY: {today.isoformat()}\n\nSTORY: {prompts.fence(story)}"]
    res = gw.generate(node="intake_extract", prompt_version=prompts.INTAKE_EXTRACT_V, contents=contents, schema=StoryExtraction,
                      tier="chat", system=prompts.CUSTOMER_GROUND_RULES, temperature=0.0, db=db)
    if not res.ok:
        return None
    x: StoryExtraction = res.data
    suggest = clean_suggestions({k: getattr(x, k).value for k in SUGGESTABLE if getattr(x, k) is not None})
    hints: dict = {}
    if x.amount and 0 < x.amount < 10**10:
        hints["amount_minor"] = int(round(x.amount * 100))
    if x.payee_name:
        hints["payee"] = (dlp.redact_for_llm(x.payee_name) or "").strip()[:64]
    if x.payment_date:
        try:
            d = date.fromisoformat(x.payment_date[:10])
            if today - timedelta(days=400) <= d <= today:
                hints["date"] = d.isoformat()
        except ValueError:
            pass
    return {"suggest": suggest, "hints": clean_hints(hints)}


def payment_match(card: dict, hints: dict) -> float:
    """How well one of the customer's payments matches the hints from their story."""
    s = 0.0
    amt = hints.get("amount_minor")
    if amt:
        diff = abs(card["amount_minor"] - amt) / max(amt, 1)
        s += 5 if diff == 0 else 4 if diff <= 0.02 else 2 if diff <= 0.1 else 0
    name = hints.get("payee")
    if name:
        want = {w for w in re.findall(r"[a-z]+", name.lower()) if len(w) >= 3}
        have = set(re.findall(r"[a-z]+", card["paid_to"].lower()))
        if want:
            s += 3 * len(want & have) / len(want)
    when = hints.get("date")
    if when:
        days = abs((date.fromisoformat(card["occurred_at"][:10]) - date.fromisoformat(when)).days)
        s += 2 if days == 0 else 1.5 if days <= 1 else 1 if days <= 3 else 0
    return s


def rank_payments(cards: list[dict], hints: dict) -> tuple[list[dict], list[str]]:
    """Best matches first (stable otherwise), and the ids of the clear matches."""
    if not hints:
        return cards, []
    scored = [(payment_match(c, hints), i, c) for i, c in enumerate(cards)]
    scored.sort(key=lambda x: (-x[0], x[1]))
    matched = [c["id"] for s, _, c in scored if s >= 2][:3]
    return [c for _, _, c in scored], matched
