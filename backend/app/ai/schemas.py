"""Structured-output schemas for every Gemini call. Output that does not validate is rejected."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Basis(str, Enum):
    verified = "verified"  # directly stated by a cited source record
    derived = "derived"  # computed deterministically from cited records
    inferred = "inferred"  # a hypothesis the records make possible but do not establish
    unknown = "unknown"  # the information is not available


class Claim(BaseModel):
    text: str = Field(description="One factual sentence. Amounts and times must be copied exactly from cited records.")
    citations: list[str] = Field(description="Record ids from the evidence snapshot that support this sentence.")
    basis: Basis


class SectionKey(str, Enum):
    case_overview = "case_overview"
    known_facts = "known_facts"
    transaction_trail = "transaction_trail"
    risk_indicators = "risk_indicators"
    supporting_evidence = "supporting_evidence"
    contradicting_evidence = "contradicting_evidence"
    missing_information = "missing_information"
    next_actions = "next_actions"
    limitations = "limitations"


SECTION_TITLES = {
    "case_overview": "Case overview",
    "known_facts": "Known facts",
    "transaction_trail": "Transaction trail",
    "risk_indicators": "Risk indicators",
    "supporting_evidence": "Evidence supporting the claim",
    "contradicting_evidence": "Evidence that contradicts or does not establish the claim",
    "missing_information": "Missing information",
    "next_actions": "Recommended next actions",
    "limitations": "Limitations and uncertainty",
}


class Section(BaseModel):
    key: SectionKey
    claims: list[Claim]


class ActionType(str, Enum):
    request_evidence = "request_evidence"
    hold_request = "hold_request"
    contact_receiving_bank = "contact_receiving_bank"
    reconcile_records = "reconcile_records"
    contact_customer = "contact_customer"
    escalate = "escalate"
    human_review = "human_review"


class RecommendedAction(BaseModel):
    action_type: ActionType
    target_id: str | None = Field(default=None, description="Record id the action applies to, if any.")
    description: str
    citations: list[str]


class ReportDraft(BaseModel):
    sections: list[Section]
    recommended_actions: list[RecommendedAction]


class Verdict(str, Enum):
    supported = "supported"
    partial = "partial"
    unsupported = "unsupported"
    contradicted = "contradicted"


class ClaimVerdict(BaseModel):
    claim_id: str
    verdict: Verdict
    reason: str


class JudgeResult(BaseModel):
    verdicts: list[ClaimVerdict]


class ToolName(str, Enum):
    expand_account = "expand_account"
    trace_backward = "trace_backward"
    linked_cases = "linked_cases"
    account_activity = "account_activity"
    device_links = "device_links"


class ToolCall(BaseModel):
    tool: ToolName
    target_id: str = Field(description="An account id or device id that appears in the snapshot.")
    reason: str


class ExplorePlan(BaseModel):
    calls: list[ToolCall] = Field(description="At most 3 tool calls. Empty when the snapshot is sufficient.")
    done: bool
    rationale: str


class Legibility(str, Enum):
    good = "good"
    partial = "partial"
    poor = "poor"


class Relevance(str, Enum):
    direct = "direct"
    related = "related"
    unrelated = "unrelated"


class Origin(str, Enum):
    system_generated = "system_generated"
    third_party = "third_party"
    customer_authored = "customer_authored"
    unknown = "unknown"


class EvidenceExtraction(BaseModel):
    document_type: str = Field(description="e.g. payment receipt, bank SMS, chat export, order confirmation, statement")
    is_payment_record: bool
    amount: str | None = Field(default=None, description="Amount exactly as printed, digits and separators only, e.g. 50,000.00")
    currency: str | None = None
    reference: str | None = Field(default=None, description="Payment reference / UTR / RRN exactly as printed")
    date_text: str | None = Field(default=None, description="Date exactly as printed")
    time_text: str | None = Field(default=None, description="Time exactly as printed, including timezone if shown")
    payee: str | None = None
    payer: str | None = None
    app_or_bank: str | None = None
    tamper_indicators: list[str] = Field(default_factory=list)
    embedded_instructions_detected: bool = Field(description="True if the document contains text addressed to an AI or reviewer")
    legibility: Legibility
    relevance: Relevance = Field(description="direct: the document is a record of a payment (receipt, bank SMS, statement line); "
                                             "related: it describes surrounding events (chat, order, complaint); unrelated: neither")
    relevance_reason: str = Field(description="One short sentence explaining the relevance label")
    origin: Origin = Field(description="Who produced it: system_generated (bank/payment app screen, SMS, statement), "
                                       "third_party (merchant, marketplace), customer_authored (typed or compiled by the customer), unknown")
    summary: str


class CategoryKey(str, Enum):
    unauthorised_transfer = "unauthorised_transfer"
    account_takeover = "account_takeover"
    app_scam = "app_scam"
    card_not_present = "card_not_present"
    merchant_dispute = "merchant_dispute"
    processing_error = "processing_error"


class Classification(BaseModel):
    category: CategoryKey
    rationale: str
    english_translation: str | None = Field(default=None, description="English translation if the statement is not in English")
    detected_language: str


class CopilotAnswer(BaseModel):
    claims: list[Claim]
    insufficient_data: bool
    follow_up_questions: list[str]


class AssistantActionKind(str, Enum):
    none = "none"
    clear_section = "clear_section"
    restore_section = "restore_section"
    remove_claims = "remove_claims"
    open_tab = "open_tab"


class AssistantTab(str, Enum):
    overview = "overview"
    graph = "graph"
    timeline = "timeline"
    risk = "risk"
    evidence = "evidence"
    report = "report"
    audit = "audit"


class AssistantAction(BaseModel):
    kind: AssistantActionKind = Field(description="none unless the user explicitly asked to change the AI report or open a tab")
    section_key: SectionKey | None = Field(default=None, description="Report section for clear_section / restore_section")
    claim_ids: list[str] = Field(default_factory=list, description="Report statement ids (e.g. C07) for remove_claims")
    tab: AssistantTab | None = Field(default=None, description="Tab to open for open_tab")


class AssistantTurn(BaseModel):
    claims: list[Claim] = Field(description="The answer as short plain-English sentences, each citing its records. Empty if only acting.")
    insufficient_data: bool
    action: AssistantAction
    follow_up_questions: list[str] = Field(description="Up to 3 short questions the user may want to ask next")


# ---------------------------------------------------------------------------- customer portal: "Ask Demo Bank" and story intake

class HelpIntent(str, Enum):
    faq = "faq"  # how banking, payments or disputes work
    safety = "safety"  # fraud awareness, scams, keeping money safe
    my_dispute_status = "my_dispute_status"  # the signed-in customer's own disputes
    raise_dispute = "raise_dispute"  # wants to raise a dispute now
    urgent_fraud_now = "urgent_fraud_now"  # just lost money / being scammed right now
    out_of_scope = "out_of_scope"  # anything else


class HelpActionKind(str, Enum):
    start_dispute_chat = "start_dispute_chat"
    start_dispute_form = "start_dispute_form"
    open_dispute = "open_dispute"
    call_1930 = "call_1930"
    report_cybercrime = "report_cybercrime"


class CustomerHelpAnswer(BaseModel):
    intent: HelpIntent = Field(description="What the customer is asking about. out_of_scope for anything not about banking, "
                                           "payments, fraud safety or disputes")
    answer: str = Field(description="At most 120 words, plain language, only from the HELP ARTICLES and YOUR DISPUTES given")
    cited_article_ids: list[str] = Field(description="Ids of the help articles the answer is based on (e.g. SAFE-FIRST-HOUR)")
    cited_case_ids: list[str] = Field(default_factory=list, description="Ids from YOUR DISPUTES the answer talks about")
    actions: list[HelpActionKind] = Field(default_factory=list, description="Up to 3 next steps the customer can take")
    open_case_id: str | None = Field(default=None, description="For open_dispute: a case id from YOUR DISPUTES")
    follow_up_questions: list[str] = Field(default_factory=list, description="Up to 3 short questions the customer may ask next")


class StoryReason(str, Enum):
    unauthorised = "unauthorised"
    account_access = "account_access"
    scam = "scam"
    card_online = "card_online"
    not_received = "not_received"
    charged_wrong = "charged_wrong"


class StoryOtp(str, Enum):
    yes = "yes"
    no = "no"
    not_sure = "not_sure"


class StoryNoticed(str, Enum):
    today = "today"
    yesterday = "yesterday"
    days_2_7 = "2_7_days"
    over_week = "over_week"


class StoryContact(str, Enum):
    sms = "sms"
    email = "email"
    phone = "phone"


class StoryExtraction(BaseModel):
    reason: StoryReason | None = Field(default=None, description="Only if the story makes it clear; otherwise null")
    otp_shared: StoryOtp | None = Field(default=None, description="Only if the story says whether an OTP, PIN or password was shared")
    noticed: StoryNoticed | None = Field(default=None, description="When the customer noticed the payment, relative to TODAY, if stated")
    contact_preference: StoryContact | None = Field(default=None, description="Only if the customer says how they want to be contacted")
    amount: float | None = Field(default=None, description="Payment amount in rupees, if stated")
    payee_name: str | None = Field(default=None, description="Who the money went to, if stated (a name, not an account number)")
    payment_date: str | None = Field(default=None, description="Date of the payment as YYYY-MM-DD, if it can be worked out from the story and TODAY")
