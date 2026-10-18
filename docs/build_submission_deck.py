"""Fills Hack2Skill's official "Submission Template _ AI Builder Cup.pptx" with FundTrace's content.

This is a SEPARATE file from docs/FundTrace-deck.pdf (the pitch deck built from docs/deck/*.html) —
per instruction, that one is untouched. This script only adds content inside the template's own
slides; it does not change the template's background images, header/footer bars, fonts or layout.

Usage:
    python docs/build_submission_deck.py "<path to the downloaded template .pptx>" [--leader "Name"]

Output: docs/FundTrace-submission.pptx
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.oxml.ns import qn

NAVY = RGBColor(0x14, 0x18, 0x3A)
AMBER = RGBColor(0xA8, 0x65, 0x0B)
GREY = RGBColor(0x4A, 0x50, 0x68)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT = "Google Sans Flex"

SHOTS = Path(__file__).resolve().parent / "screenshots"
REPO = "https://github.com/nawin-viswajith/fundtrace"
LIVE = "https://fundtrace-541805214490.asia-south1.run.app"

# Body content area, below each slide's header/title and above the footer line (slide is 10in x 5.625in).
LEFT, TOP, WIDTH = Inches(0.29), Inches(1.35), Inches(9.42)


def delete_slide(prs: Presentation, index: int) -> None:
    """python-pptx has no built-in slide delete; drop it from the slide-id list and the part relationship."""
    xml_slides = prs.slides._sldIdLst
    slides = list(xml_slides)
    rId = slides[index].rId
    prs.part.drop_rel(rId)
    xml_slides.remove(slides[index])


def add_textbox(slide, left, top, width, height) -> "pptx.shapes.autoshape.Shape":
    tb = slide.shapes.add_textbox(left, top, width, height)
    tb.text_frame.word_wrap = True
    return tb


def para(tf, text, *, size=14, bold=False, color=GREY, bullet=False, space_after=6, first=False):
    p = tf.paragraphs[0] if first and not tf.paragraphs[0].runs else tf.add_paragraph()
    run = p.add_run()
    run.text = ("•  " + text) if bullet else text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    run.font.name = FONT
    p.space_after = Pt(space_after)
    return p


def body_text(slide, lines: list[tuple[str, dict]], *, left=LEFT, top=TOP, width=WIDTH, height=Inches(4.1)):
    tb = add_textbox(slide, left, top, width, height)
    first = True
    for text, kw in lines:
        para(tb.text_frame, text, first=first, **kw)
        first = False
    return tb


def flow_box(slide, left, top, width, height, title, sub, *, fill=NAVY, title_color=WHITE, sub_color=None):
    shp = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    shp.line.color.rgb = fill
    shp.shadow.inherit = False
    tf = shp.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Pt(6)
    tf.margin_top = tf.margin_bottom = Pt(4)
    p0 = tf.paragraphs[0]
    p0.alignment = PP_ALIGN.CENTER
    r0 = p0.add_run()
    r0.text = title
    r0.font.size = Pt(11)
    r0.font.bold = True
    r0.font.color.rgb = title_color
    r0.font.name = FONT
    if sub:
        p1 = tf.add_paragraph()
        p1.alignment = PP_ALIGN.CENTER
        r1 = p1.add_run()
        r1.text = sub
        r1.font.size = Pt(8.5)
        r1.font.color.rgb = sub_color or title_color
        r1.font.name = FONT
    return shp


def arrow(slide, x1, y1, x2, y2, color=NAVY):
    conn = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, x1, y1, x2, y2)
    conn.line.color.rgb = color
    conn.line.width = Pt(1.75)
    ln = conn.line._get_or_add_ln()
    tail = ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"})
    ln.append(tail)
    return conn


def add_picture_fit(slide, path: Path, left, top, max_w, max_h):
    from PIL import Image

    with Image.open(path) as im:
        iw, ih = im.size
    scale = min(max_w / iw, max_h / ih)
    w, h = int(iw * scale), int(ih * scale)
    x = left + (max_w - w) // 2
    y = top + (max_h - h) // 2
    slide.shapes.add_picture(str(path), x, y, width=w, height=h)


def caption(slide, left, top, width, text):
    tb = add_textbox(slide, left, top, width, Inches(0.3))
    p = tb.text_frame.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    r = p.add_run()
    r.text = text
    r.font.size = Pt(9)
    r.font.color.rgb = GREY
    r.font.name = FONT


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("template", help="path to the downloaded Hack2Skill template .pptx")
    ap.add_argument("--leader", default="[team leader name]")
    ap.add_argument("--problem-statement", default="BFSI track — Intelligent Risk, Fraud & Financial Experiences")
    ap.add_argument("--video-link", default="[add after recording — see docs/record_demo.py]")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "FundTrace-submission.pptx"))
    args = ap.parse_args()

    prs = Presentation(args.template)
    slides = prs.slides

    # ---- Slide 1: Team details ----
    tb = slides[0].shapes[0].text_frame
    tb.paragraphs[2].add_run().text = "Aura Bros"
    tb.paragraphs[3].add_run().text = args.leader
    tb.paragraphs[4].add_run().text = (
        f"{args.problem_statement}: FundTrace, an AI-assisted investigation workspace for bank payment disputes."
    )
    for p in (tb.paragraphs[2], tb.paragraphs[3], tb.paragraphs[4]):
        for r in p.runs[1:]:
            r.font.name = FONT

    # ---- delete the "download this template first" instruction slide (index 1) ----
    delete_slide(prs, 1)
    # everything below now shifts up by one: original slide 3 ("Brief about the idea") is index 1, etc.

    # ---- "Brief about the idea" ----
    s = slides[1]
    body_text(s, [
        ("When a customer says “I didn’t make this ₹50,000 payment,” an investigator has hours, "
         "not days, before the money moves again. FundTrace reconstructs the observable downstream trail from "
         "ledger records, works out how much of each onward transfer could or must be the disputed money, shows "
         "the evidence behind every fraud signal, and has Gemini write a cited investigation report — with "
         "every claim fact-checked and the hallucination rate measured.", dict(size=13)),
        ("A customer portal lets the account holder raise the dispute themselves — by guided chat, form, or "
         "free text that Gemini reads — and it lands as a ready case in the bank’s queue, with no "
         "re-keying. The investigator always decides; the AI never calculates money or liability.", dict(size=13)),
    ], height=Inches(3.6))

    # ---- "Opportunities" (differentiation / solves the problem / USP) ----
    s = slides[2]
    tb = s.shapes[-1].text_frame  # the existing prompt textbox (title + 3 guiding lines)
    # Replace the 3 guiding sub-bullets with real answers, keep "Opportunities" as the heading.
    answers = [
        "How different is it from other ideas? Most tools stop at “the amounts match.” FundTrace computes "
        "four tracing conventions (clean-first, FIFO, pro-rata, tainted-first) for a derived lower bound and an "
        "inferred upper bound on every onward transfer — and Gemini proposes hypotheses about the trail that "
        "deterministic code checks, and can reject outright as “invented.”",
        "How will it solve the problem? It turns hours of manual statement-reading into a cited AI report in "
        "about 3 minutes, flags accounts that may still hold disputed money within the golden hour, and lets the "
        "customer raise a dispute that maps straight into the bank’s workflow — no re-keying.",
        "USP: a rules + AI + ML system that never lets AI calculate money or decide liability. Every number is "
        "deterministic code, every AI claim is fact-checked and measured, and the one ML model is evaluated on a "
        "genuine synthetic hold-out — not scenarios the team wrote itself.",
    ]
    # paragraphs: 0=heading "Opportunities", 1..3 = guiding questions, blanks after
    for i, p in enumerate(tb.paragraphs[1:4]):
        for r in p.runs:
            r.text = ""
        if p.runs:
            p.runs[0].text = answers[i]
            p.runs[0].font.size = Pt(13)
        else:
            r = p.add_run()
            r.text = answers[i]
            r.font.size = Pt(13)
            r.font.name = FONT

    # ---- "List of features offered by the solution" ----
    s = slides[3]
    cols = [
        ("Investigation", "Time-ordered money trail · 4 attribution methods with ranges · 15 rule-based "
         "warning signs (R1–R15) · evidence checklist & strength scores · hold recommendations · "
         "calculation record with replay"),
        ("Generative AI", "LangGraph investigation agent · cited report with validator + judge · AI "
         "hypotheses checked by code · multimodal evidence reading · Ask Demo Bank customer assistant · "
         "copilot & translation"),
        ("Machine learning", "Unsupervised Isolation Forest behaviour model, no labels, evaluated on a synthetic "
         "hold-out (ROC-AUC ≈ 0.78) — a separate signal, never a 16th rule"),
        ("Customer side", "Portal: dispute by guided chat, form, or free text · plain-language status "
         "tracking and uploads · safety-check insights · disputes mapped straight into the bank’s queue"),
        ("Workflow & security", "Case queue with SLA clocks · roles & case-level access · shared-account "
         "recovery split · hash-chained audit · field encryption (Cloud KMS) · DLP masking · MFA"),
        ("Operations", "Ledger ingest via Pub/Sub (ISO 20022 camt.053, CSV, JSON) · AI cost/latency/error "
         "tracking · deterministic + hold-out evaluation · demo-data generator"),
    ]
    col_w = Inches(3.0)
    gap = Inches(0.21)
    for i, (title, text) in enumerate(cols):
        col, row = i % 3, i // 3
        x = LEFT + col * (col_w + gap)
        y = TOP + row * Inches(1.95)
        tb = add_textbox(s, x, y, col_w, Inches(1.85))
        para(tb.text_frame, title, size=12.5, bold=True, color=NAVY, first=True, space_after=2)
        para(tb.text_frame, text, size=9.5, color=GREY, space_after=0)

    # ---- "Process flow diagram or Use-case diagram" ----
    s = slides[4]
    steps = [
        ("1. Customer", "Raises a dispute: chat, form or free text"),
        ("2. Case created", "Lands in the bank’s queue, SLA set"),
        ("3. Gather + trail", "Ledger records → hashed snapshot"),
        ("4. Gemini explores", "5 fixed tools; reads evidence"),
        ("5. Gemini drafts", "Cited report · Pro model"),
        ("6. Validate + judge", "Code checks claims; Gemini fact-checks"),
        ("7. Investigator", "Reviews, approves holds, decides"),
    ]
    bw, bh, gap = Inches(1.3), Inches(0.95), Inches(0.1)
    y = TOP + Inches(0.3)
    x = LEFT
    boxes = []
    for i, (title, sub) in enumerate(steps):
        fill = AMBER if i == 6 else NAVY
        tcol = NAVY if i == 6 else WHITE
        b = flow_box(s, x, y, bw, bh, title, sub, fill=fill, title_color=tcol, sub_color=GREY if i == 6 else RGBColor(0xC9, 0xCC, 0xE6))
        boxes.append(b)
        x += bw + gap
    for i in range(len(boxes) - 1):
        b1, b2 = boxes[i], boxes[i + 1]
        arrow(s, b1.left + b1.width, b1.top + b1.height // 2, b2.left, b2.top + b2.height // 2)
    caption(s, LEFT, y + bh + Inches(0.35), WIDTH,
            "Gemini never calculates money, balances or rules — those stay deterministic code throughout.")

    # ---- "Wireframes/Mock diagrams (optional)" ----
    s = slides[5]
    shots = [("portal.png", "Customer portal: raise a dispute, track progress"),
             ("queue.png", "Bank view: case queue with SLA and priority")]
    panel_w, panel_h = Inches(4.6), Inches(3.5)
    x = LEFT
    for name, cap in shots:
        f = SHOTS / name
        if f.exists():
            add_picture_fit(s, f, x, TOP, panel_w, panel_h)
            caption(s, x, TOP + panel_h + Inches(0.05), panel_w, cap)
        x += panel_w + Inches(0.2)

    # ---- "Architecture diagram of the proposed solution" ----
    s = slides[6]
    ui = flow_box(s, LEFT, TOP + Inches(0.4), Inches(2.0), Inches(0.9), "Investigator UI\n& Customer portal", "React, TypeScript, React Flow", fill=RGBColor(0x22, 0x28, 0x50))
    run_box = flow_box(s, LEFT + Inches(2.3), TOP + Inches(0.4), Inches(2.6), Inches(0.9), "Cloud Run", "FastAPI · LangGraph agent · rules R1–R15 · ML model · validator", fill=RGBColor(0x3A, 0x3F, 0xB3))
    arrow(s, ui.left + ui.width, ui.top + ui.height // 2, run_box.left, run_box.top + run_box.height // 2)
    services = [
        ("Vertex AI", "Gemini Pro · Flash · Flash-Lite"),
        ("Cloud SQL", "MySQL 8 · source of truth"),
        ("Cloud Storage", "write-once evidence"),
        ("KMS · Secret Mgr · DLP", "encryption, secrets, masking"),
        ("Pub/Sub", "ledger ingest, dead-letter"),
    ]
    svc_x = LEFT + Inches(5.3)
    svc_y = TOP + Inches(0.1)
    for i, (title, sub) in enumerate(services):
        b = flow_box(s, svc_x, svc_y + i * Inches(0.44), Inches(4.1), Inches(0.38), title, sub, fill=RGBColor(0x22, 0x28, 0x50))
        if i == 0:
            arrow(s, run_box.left + run_box.width, run_box.top + run_box.height // 2, svc_x, b.top + b.height // 2)
    caption(s, LEFT, TOP + Inches(2.6), WIDTH,
            "Observability: OpenTelemetry → Cloud Trace; redacted logs → Cloud Logging/Monitoring.  "
            "Path to bank scale: Dataflow on the same Pub/Sub feed, BigQuery history, Spanner Graph behind the "
            "same graph interface — one container, deployed by a single script (infra/deploy.sh).")

    # ---- "Technologies to be used in the solution" ----
    s = slides[7]
    tech = [
        ("Frontend", "React, TypeScript, React Query, React Flow, Vitest/RTL, axe-core"),
        ("Backend", "FastAPI, SQLAlchemy 2, Alembic, LangGraph, scikit-learn, pytest"),
        ("Generative AI", "Gemini (Pro / Flash / Flash-Lite) on Vertex AI"),
        ("Data", "Cloud SQL (MySQL 8), Cloud Storage, SQLite (local dev)"),
        ("Security", "Cloud KMS, Secret Manager, Cloud DLP, bcrypt + JWT, TOTP MFA"),
        ("Infra & ops", "Cloud Run, Pub/Sub, OpenTelemetry, Cloud Trace/Logging/Monitoring"),
    ]
    for i, (title, text) in enumerate(tech):
        y = TOP + i * Inches(0.62)
        tb = add_textbox(s, LEFT, y, WIDTH, Inches(0.58))
        p = tb.text_frame.paragraphs[0]
        r1 = p.add_run(); r1.text = title + ":  "; r1.font.bold = True; r1.font.size = Pt(13); r1.font.color.rgb = NAVY; r1.font.name = FONT
        r2 = p.add_run(); r2.text = text; r2.font.size = Pt(13); r2.font.color.rgb = GREY; r2.font.name = FONT

    # ---- "Estimated implementation cost (optional)" ----
    s = slides[8]
    body_text(s, [
        ("Cloud Run scales to zero between requests, so a pilot costs little when idle. Rough monthly figures for "
         "a single-branch / low-volume pilot (not full bank scale):", dict(size=13)),
        ("Cloud SQL (db-f1-micro, always on): roughly $10–$15/month", dict(size=13, bullet=True)),
        ("Cloud Run, Cloud Storage, Pub/Sub, KMS, Secret Manager at pilot traffic: a few dollars/month combined", dict(size=13, bullet=True)),
        ("Gemini (Vertex AI): measured at about $0.20 per full AI investigation; routine chat/FAQ answers now use "
         "Flash-Lite, a fraction of a cent each", dict(size=13, bullet=True)),
        ("A pilot handling a few hundred disputes a month is estimated at roughly $50–$150/month, dominated by "
         "Cloud SQL and Gemini usage — scaling close to linearly with investigation volume after that. Full "
         "bank scale would add Spanner Graph, BigQuery and Dataflow (see the architecture slide).", dict(size=13)),
    ], height=Inches(3.6))

    # ---- "Snapshots of the prototype" ----
    s = slides[9]
    shots = [("overview.png", "Case overview — six separate checks"),
             ("graph_cropped.png", "Money trail with attribution ranges"),
             ("recovery.png", "Shared-account recovery split"),
             ("risk.png", "Warning signs with record-level evidence")]
    cw, ch = Inches(4.6), Inches(1.75)
    for i, (name, cap) in enumerate(shots):
        f = SHOTS / name
        if not f.exists():
            continue
        col, row = i % 2, i // 2
        x = LEFT + col * (cw + Inches(0.2))
        y = TOP + row * (ch + Inches(0.3))
        add_picture_fit(s, f, x, y, cw, ch)
        caption(s, x, y + ch + Inches(0.02), cw, cap)

    # ---- "Prototype Performance report/Benchmarking" ----
    s = slides[10]
    body_text(s, [
        ("104/104 deterministic ground-truth checks pass; rule precision and recall 1.0 on labelled scenarios", dict(size=13, bullet=True)),
        ("251 backend tests, 113 frontend tests, all passing; TypeScript, lint and build all clean", dict(size=13, bullet=True)),
        ("Behaviour model (ML): synthetic hold-out on fresh random seeds, never the hand-written scenarios — "
         "mean ROC-AUC ≈ 0.78, precision@k ≈ 0.41, labelled honestly as a synthetic result", dict(size=13, bullet=True)),
        ("Live Gemini report: 35/35 claims confirmed by the fact-check on the first live run; cost ≈ $0.20 per "
         "full investigation, measured per call", dict(size=13, bullet=True)),
        ("Chat latency: a greeting now answers in about 0.2s (code, no AI call); a real question answers in a "
         "few seconds on a Flash-Lite model instead of up to ≈ 60s on the general-purpose chain", dict(size=13, bullet=True)),
    ], height=Inches(3.6))

    # ---- "Additional Details/Future Development" ----
    s = slides[11]
    body_text(s, [
        ("Live bank feeds on the existing Pub/Sub ingest, and Spanner Graph for production trail volumes", dict(size=13, bullet=True)),
        ("Cross-bank trail and hold requests through national cyber-fraud reporting channels", dict(size=13, bullet=True)),
        ("Supervised models trained on investigator-labelled outcomes, with the rules kept as explanations", dict(size=13, bullet=True)),
        ("An investigator feedback loop on claim reviews, to tune prompts and the judge", dict(size=13, bullet=True)),
        ("Scheduled evidence-retention runs and live bank connections on the ingest path", dict(size=13, bullet=True)),
    ], height=Inches(3.6))

    # ---- "Provide links to your:" ----
    s = slides[12]
    tb = s.shapes[-1].text_frame
    links = [REPO, args.video_link, LIVE]
    for p, link in zip(tb.paragraphs[2:5], links):
        for r in p.runs:
            r.text = r.text  # keep label
        r = p.add_run()
        r.text = "  " + link
        r.font.size = Pt(13)
        r.font.color.rgb = AMBER
        r.font.name = FONT

    prs.save(args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
