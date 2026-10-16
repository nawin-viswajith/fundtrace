"""Live end-to-end check of the AI pipeline against real Gemini (uses the configured DATABASE_URL).

    cd backend
    set GCP_PROJECT=... & set GEMINI_FAST_MODELS=... & set GEMINI_PRO_MODELS=...
    python -m scripts.live_e2e [--cases CASE-24051,CASE-24049,CASE-24044]

For each case: runs classification, the full investigation (explore → evidence → draft → validate → judge)
and one copilot question, then prints status, claims, flags, hallucination rate, confidence, cost and latency.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default="CASE-24051,CASE-24049,CASE-24044")
    a = ap.parse_args()
    from sqlalchemy import select

    from app import models as m
    from app.ai.copilot import ask, classify
    from app.ai.investigator import run_investigation
    from app.ai.llm import get_gateway
    from app.config import get_settings
    from app.main import bootstrap
    from app.db import session_scope

    s = get_settings()
    print(f"project={s.gcp_project} location={s.gemini_location} fast={s.fast_models} pro={s.pro_models}")
    if not get_gateway().available():
        print("Gemini is not configured (GCP_PROJECT / LLM_ENABLED). Aborting.")
        return
    bootstrap()
    for cid in [c.strip() for c in a.cases.split(",") if c.strip()]:
        with session_scope() as db:
            case = db.get(m.DisputeCase, cid)
            user = db.scalar(select(m.User).where(m.User.username == "sup.meera"))
            print(f"\n=== {cid} ({case.scenario}, {case.category}) ===")
            c = classify(db, case, user)
            print("classify:", c.get("status"), c.get("suggested_category"), "token_conf=", c.get("token_confidence"),
                  "| translation:", (c.get("translation") or "")[:80])
            t0 = time.perf_counter()
            rep = run_investigation(db, case, actor="sup.meera")
            run = db.get(m.AIRun, rep.run_id)
            print(f"report: {rep.status} by {rep.generator} in {int(time.perf_counter() - t0)} s | claims={rep.claims_total} "
                  f"flagged={rep.claims_flagged} hallucination={rep.hallucination_rate} confidence={rep.confidence} "
                  f"cost=${rep.metrics.get('cost_usd')} tokens_in={run.input_tokens} tokens_out={run.output_tokens}")
            print("steps:", json.dumps([{k: v for k, v in st.items() if k in ('node', 'status', 'ms')} for st in run.steps]))
            print("tools:", json.dumps([{k: t.get(k) for k in ('tool', 'target_id', 'status', 'new_records')} for t in run.tool_log]))
            for sec in rep.sections:
                for cl in sec["claims"]:
                    if cl["flagged"]:
                        print(f"  FLAGGED {cl['id']} [{sec['key']}] {cl['text'][:110]} -> {[i['code'] for i in cl['issues']]} {cl['verdict']}")
            for e in db.scalars(select(m.EvidenceItem).where(m.EvidenceItem.case_id == cid)).all():
                print(f"evidence {e.id}: {e.analysis_status} | {(e.reconciliation or {}).get('summary')}")
            q = ask(db, case, "Which accounts may still hold the disputed funds, and how much?", user)
            print("copilot:", q.get("status"), "flagged=", q.get("flagged"), "|", " ".join(cl["text"] for cl in q.get("claims", []))[:300])


if __name__ == "__main__":
    main()
