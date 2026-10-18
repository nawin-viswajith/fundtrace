"""Drives the 3-minute demo in docs/DEMO_VIDEO.md on a real browser, so you can screen-record it
(OBS, Windows Game Bar, etc.) instead of clicking through it live. Optionally speaks the narration
out loud in the background (Windows SAPI) while it drives the UI, so a screen+mic recorder captures
narrated audio automatically; otherwise use --dump-transcript / --dump-srt to get a script to read
from, or to feed to a text-to-speech tool, kept in sync with the recording because both are built
from the same STEPS table below.

Before running:
  1. Start the app against a server that has the demo data (local: `cd backend && uvicorn app.main:app --port 8011`,
     or point --base-url at a deployed Cloud Run URL).
  2. As an admin, run "Reset demo data" on the AI & system health page (restarts SLA clocks and the
     golden hour, and clears any payments dated after today).
  3. Run the AI investigation on CASE-24051 once, and analyse the evidence on CASE-24051 and
     CASE-24049, so the report and evidence match are already there when the recording reaches them
     (a live Gemini call mid-recording is slow and sometimes fails).
  4. Start your screen/audio recorder, THEN run this script.

Usage:
  python docs/record_demo.py --base-url http://localhost:8011                 # drive the browser + record video + speak narration
  python docs/record_demo.py --base-url http://localhost:8011 --no-speak      # drive + record video, silent (you narrate live)
  python docs/record_demo.py --dump-transcript docs/demo_narration.txt        # just write a cue-sheet to read from, no browser
  python docs/record_demo.py --dump-srt docs/demo_narration.srt               # same, as subtitles

Two browser profiles are used (customer, then bank), so this produces two video files in --video-dir:
one for the 0:00-0:35 customer segment and one for 0:35-3:00 bank segment, which is also how
DEMO_VIDEO.md's own timeline is split. Trim/join them in your editor, or just record your screen
continuously across both — they open one after another with no manual step in between.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

CUST_USER, BANK_USER, PASSWORD = "cust.priya", "sup.meera", "Investigate@2026"


@dataclass
class Step:
    start: float  # seconds from the start of its segment ("customer" or "bank")
    end: float
    segment: str  # "customer" | "bank"
    screen: str
    narration: str
    act: Callable[["object"], None] | None = field(default=None, repr=False)  # page -> None; best-effort

    @property
    def duration(self) -> float:
        return self.end - self.start


def _click_text(page, text: str, role: str = "button", timeout: int = 4000) -> bool:
    """Best-effort click: tries an exact-ish role match, then any element containing the text.
    Returns whether it found something, but never raises — a missed click should not abort the
    recording, just leave that one scene a little emptier."""
    for finder in (
        lambda: page.get_by_role(role, name=text),
        lambda: page.locator(f"text={text}").first,
    ):
        try:
            loc = finder()
            loc.wait_for(state="visible", timeout=timeout)
            loc.click(timeout=timeout)
            return True
        except Exception:
            continue
    return False


def _login(page, base_url: str, username: str) -> None:
    page.goto(f"{base_url}/login")
    page.get_by_label("Username").fill(username)
    page.get_by_label("Password").fill(PASSWORD)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_load_state("networkidle")


# ---------------------------------------------------------------------------- customer segment (0:00-0:35)

def _act_home(page) -> None:
    pass  # just sit on the portal home while the narration plays


def _act_raise_dispute(page) -> None:
    page.goto(page.url.split("/portal")[0] + "/portal/new/chat")
    page.wait_for_selector(".pay-card-btn, .pay-card", timeout=8000)
    btn = page.locator(".pay-card-btn:not([disabled])").first
    if btn.count():
        btn.click()
    time.sleep(1.5)
    _click_text(page, "didn't make this payment", role="button") or _click_text(page, "tricked")
    time.sleep(1.2)
    _click_text(page, "No, I didn't share any") or _click_text(page, "No")
    time.sleep(1.0)
    _click_text(page, "Today")
    time.sleep(0.8)
    box = page.locator("textarea#chat-text, textarea.textarea").first
    if box.count():
        box.fill("I did not make this payment. My phone was with me the whole time.")
        _click_text(page, "Send")
    time.sleep(1.2)
    _click_text(page, "SMS") or _click_text(page, "Email")
    time.sleep(1.5)
    png = Path(tempfile.gettempdir()) / "demo_upi_receipt.png"
    if not png.exists():
        png.write_bytes(
            bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108020000009077"
                          "53de0000000a49444154789c6360000002000100ffff03000006000557bf"
                          "a2c00000000049454e44ae426082")
        )
    file_input = page.locator("input[aria-label='Add files'], input[type=file]").first
    if file_input.count():
        try:
            file_input.set_input_files(str(png))
        except Exception:
            pass
    time.sleep(1.0)
    _click_text(page, "Continue with")
    time.sleep(1.0)
    chk = page.locator(".declaration input, input[type=checkbox]").first
    if chk.count():
        chk.check(force=True)
    time.sleep(0.5)
    _click_text(page, "Submit dispute")
    time.sleep(1.5)


CUSTOMER_STEPS = [
    Step(0, 10, "customer", "Portal home", "Priya sees ₹50,000 leave her account that she never sent. With real-time payments, that money can be three accounts away in minutes.", _act_home),
    Step(10, 35, "customer", "Chat with our assistant → submit", "She raises it in the bank's app. The assistant asks one question at a time and she taps answers, so every dispute lands mapped to the right account and payment. It asks for proof — she adds the bank's screenshot — checks the summary card and submits.", _act_raise_dispute),
]

# ---------------------------------------------------------------------------- bank segment (0:35-3:00)
#  Offsets below are seconds into the BANK segment, i.e. (video time - 0:35), matching DEMO_VIDEO.md.

CASE = "CASE-24051"
EVIDENCE_CASE = "CASE-24049"


def _goto_case(page, base_url: str, case_id: str, tab: str | None = None) -> None:
    url = f"{base_url}/cases/{case_id}" + (f"?tab={tab}" if tab else "")
    page.goto(url)
    page.wait_for_load_state("networkidle")


def _act_queue(page) -> None:
    pass  # already on /cases from the caller


def _act_overview(page) -> None:
    pass


def _act_trail(page) -> None:
    page.wait_for_timeout(1500)
    section = page.locator("text=How these figures were calculated").first
    if section.count():
        section.scroll_into_view_if_needed()
        try:
            section.click()
        except Exception:
            pass


def _act_risk(page) -> None:
    row = page.locator("button:has-text('Failed logins')").first
    if row.count():
        row.scroll_into_view_if_needed()
        row.click()


def _act_evidence(page) -> None:
    pass


def _act_report(page) -> None:
    page.wait_for_timeout(1500)


def _act_recovery(page) -> None:
    sec = page.locator("text=Money recovered from shared accounts").first
    if sec.count():
        sec.scroll_into_view_if_needed()


def _act_ops(page) -> None:
    page.wait_for_timeout(1000)


def _act_title(page) -> None:
    pass


BANK_STEPS = [
    Step(0, 10, "bank", "Case queue — the new case at the top", "On the bank side it's already a case: customer, payment, category, SLA clocks and priority set. No re-keying.", _act_queue),
    Step(10, 25, "bank", f"{CASE} Overview — at a glance, six separate checks", "This is the investigation for that kind of dispute. P1, and it says why. Six separate checks — warning signs, evidence, records, tracing, policy, AI — and deliberately no single trust score.", _act_overview),
    Step(25, 50, "bank", "Money trail", "The trail is rebuilt from ledger records in time order: fifty thousand to a nine-day-old account, then split — thirty thousand to Sunil, twenty thousand to another bank, where our visibility ends, and we say so. Rahul already held ₹1,200, so balance arithmetic proves at least ₹28,800 of the transfer to Sunil is the disputed money. That's derived. Where the ledger can't force it, we say inferred.", _act_trail),
    Step(50, 65, "bank", "Warning signs → open \"Failed logins\"", "Fifteen explainable warning signs. Each shows the records behind it: four failed logins, then an OTP from a device first seen fourteen minutes earlier — the same device as another victim's account. Signs prompt review; they are not proof.", _act_risk),
    Step(65, 80, "bank", f"Evidence ({EVIDENCE_CASE})", "Gemini reads the customer's screenshot, but code compares it with the ledger. Here the screenshot says ₹45,000 against a ₹50,000 record — a contradiction. And the hidden note telling the AI to approve the refund? Detected and ignored.", _act_evidence),
    Step(80, 105, "bank", f"AI report ({CASE})", "A LangGraph agent explores the trail with fixed tools and Gemini writes the report. Every sentence cites a record. Code checks every ID, amount and time; a Gemini judge fact-checks each claim. Thirty-five claims, all confirmed, zero not backed by records — measured on every report, with its cost.", _act_report),
    Step(105, 120, "bank", "Linked cases → \"Money recovered from shared accounts\"", "Three disputes traced money into Rahul's account, and together their holds ask for ₹3,600 — but only ₹1,200 is there. FundTrace shows the money once and splits it fairly. Every figure has a calculation record anyone can recompute.", _act_recovery),
    Step(120, 135, "bank", "AI & system health", "And we run the AI responsibly: cost, latency and errors per call, 104 of 104 ground-truth checks, investigator agreement with the AI, and field encryption with Cloud KMS. All on Gemini, LangGraph and Cloud Run.", _act_ops),
    Step(135, 145, "bank", "Title slide", "FundTrace: follow the money, show the proof, mark the guesses. The investigator decides.", _act_title),
]

ALL_STEPS = CUSTOMER_STEPS + BANK_STEPS


# ---------------------------------------------------------------------------- narration (speak / transcript)

def _speak_async(text: str) -> None:
    """Speaks `text` on a background thread via Windows SAPI, so the Playwright actions below keep
    running while the narration plays ("talk in bkgd"). A silent no-op on anything but Windows, or
    if PowerShell/speech isn't available — the recording still proceeds either way."""

    def _run() -> None:
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
                f.write(text)
                path = f.name
            subprocess.run(
                [
                    "powershell", "-NoProfile", "-NonInteractive", "-Command",
                    "Add-Type -AssemblyName System.Speech; "
                    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                    "$s.Rate = 0; "
                    f"$t = Get-Content -Raw -Encoding UTF8 '{path}'; "
                    "$s.Speak($t)",
                ],
                check=False, capture_output=True, timeout=120,
            )
        except Exception as exc:  # pragma: no cover - best effort only
            print(f"  (narration not spoken: {exc})", file=sys.stderr)

    threading.Thread(target=_run, daemon=True).start()


def dump_transcript(path: Path) -> None:
    lines = ["FundTrace demo narration — cue sheet (matches docs/DEMO_VIDEO.md)\n"]
    base = 0.0
    for step in ALL_STEPS:
        if step is CUSTOMER_STEPS[0]:
            base = 0.0
        if step is BANK_STEPS[0]:
            base = CUSTOMER_STEPS[-1].end
        t0, t1 = base + step.start, base + step.end
        lines.append(f"[{t0:5.1f}s - {t1:5.1f}s]  {step.screen}")
        lines.append(f'  "{step.narration}"\n')
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {path}")


def _srt_ts(seconds: float) -> str:
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def dump_srt(path: Path) -> None:
    out, n, base = [], 1, 0.0
    for step in ALL_STEPS:
        if step is CUSTOMER_STEPS[0]:
            base = 0.0
        if step is BANK_STEPS[0]:
            base = CUSTOMER_STEPS[-1].end
        t0, t1 = base + step.start, base + step.end
        out.append(f"{n}\n{_srt_ts(t0)} --> {_srt_ts(t1)}\n{step.narration}\n")
        n += 1
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {path}")


# ---------------------------------------------------------------------------- the drive itself

def run_segment(pw, base_url: str, username: str, steps: list[Step], video_dir: Path, speak: bool) -> None:
    browser = pw.chromium.launch()
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        record_video_dir=str(video_dir),
        record_video_size={"width": 1440, "height": 900},
    )
    page = context.new_page()
    try:
        _login(page, base_url, username)
        for step in steps:
            print(f"[{step.segment} +{step.start:>5.1f}s] {step.screen}")
            if speak:
                _speak_async(step.narration)
            t0 = time.time()
            if step.act is not None:
                try:
                    step.act(page)
                except Exception as exc:  # a missed selector should not kill the recording
                    print(f"  (action skipped: {exc})", file=sys.stderr)
            remaining = step.duration - (time.time() - t0)
            if remaining > 0:
                page.wait_for_timeout(int(remaining * 1000))
    finally:
        context.close()
        browser.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", default="http://localhost:8011")
    p.add_argument("--video-dir", default=str(Path(tempfile.gettempdir()) / "fundtrace_demo_video"))
    p.add_argument("--no-speak", action="store_true", help="drive the browser and record video, but don't speak narration")
    p.add_argument("--dump-transcript", metavar="PATH", help="just write a plain-text cue sheet and exit (no browser)")
    p.add_argument("--dump-srt", metavar="PATH", help="just write subtitles (.srt) and exit (no browser)")
    args = p.parse_args()

    if args.dump_transcript:
        dump_transcript(Path(args.dump_transcript))
        return
    if args.dump_srt:
        dump_srt(Path(args.dump_srt))
        return

    from playwright.sync_api import sync_playwright

    video_dir = Path(args.video_dir)
    video_dir.mkdir(parents=True, exist_ok=True)
    print(f"Recording to: {video_dir}\nStart your screen/audio recorder now. Starting in 3 seconds...")
    time.sleep(3)

    with sync_playwright() as pw:
        print("\n=== Customer segment (0:00-0:35) ===")
        run_segment(pw, args.base_url, CUST_USER, CUSTOMER_STEPS, video_dir, speak=not args.no_speak)
        print("\n=== Bank segment (0:35-3:00) ===")
        run_segment(pw, args.base_url, BANK_USER, _bank_steps_with_nav(args.base_url), video_dir, speak=not args.no_speak)

    print(f"\nDone. Video files are in {video_dir} (one .webm per segment, named by Playwright).")


def _bank_steps_with_nav(base_url: str) -> list[Step]:
    """Wraps each bank step's action with the page navigation it needs, so run_segment stays generic."""
    nav = {
        0: lambda page: page.goto(f"{base_url}/cases"),
        1: lambda page: _goto_case(page, base_url, CASE),
        2: lambda page: _goto_case(page, base_url, CASE, "graph"),
        3: lambda page: _goto_case(page, base_url, CASE, "risk"),
        4: lambda page: _goto_case(page, base_url, EVIDENCE_CASE, "evidence"),
        5: lambda page: _goto_case(page, base_url, CASE, "report"),
        6: lambda page: page.goto(f"{base_url}/network#recovery"),
        7: lambda page: page.goto(f"{base_url}/ops"),
        8: lambda page: None,
    }
    wrapped = []
    for i, step in enumerate(BANK_STEPS):
        original_act = step.act

        def act(page, _nav=nav[i], _orig=original_act) -> None:
            if _nav is not None:
                _nav(page)
                page.wait_for_load_state("networkidle")
            if _orig is not None:
                _orig(page)

        wrapped.append(Step(step.start, step.end, step.segment, step.screen, step.narration, act))
    return wrapped


if __name__ == "__main__":
    main()
