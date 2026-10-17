"""Find which Gemini model ids answer in this project/location (run first, once credentials exist).

    cd backend
    gcloud auth application-default login        # or run in Cloud Shell
    python -m scripts.probe_gemini --project MY_PROJECT [--location global]

Prints latency, tokens and whether structured JSON output works, then suggests GEMINI_*_MODELS values.
"""
from __future__ import annotations

import argparse
import time

from pydantic import BaseModel

CANDIDATES = ["gemini-3.1-pro", "gemini-3.1-pro-preview", "gemini-3-flash", "gemini-3-flash-preview", "gemini-2.5-pro",
              "gemini-2.5-flash", "gemini-2.5-flash-lite"]


class Probe(BaseModel):
    answer: str
    amount_inr: int


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--location", default="global")
    ap.add_argument("--models", default=",".join(CANDIDATES))
    ap.add_argument("--use-gcloud-token", action="store_true",
                    help="authenticate with `gcloud auth print-access-token` instead of Application Default Credentials")
    a = ap.parse_args()
    from google import genai
    from google.genai import types

    creds = None
    if a.use_gcloud_token:
        import shutil
        import subprocess

        from google.oauth2.credentials import Credentials

        gcloud = shutil.which("gcloud") or shutil.which("gcloud.cmd")
        token = subprocess.run([gcloud, "auth", "print-access-token"], capture_output=True, text=True, check=True).stdout.strip()
        creds = Credentials(token=token)
    client = genai.Client(vertexai=True, project=a.project, location=a.location, credentials=creds)
    try:
        listed = [m.name for m in client.models.list() if "gemini" in (m.name or "")]
        print(f"Models listed by the API ({len(listed)}):", ", ".join(sorted(n.split("/")[-1] for n in listed)[:40]))
    except Exception as exc:  # listing is optional
        print("Model listing unavailable:", type(exc).__name__, str(exc)[:120])
    ok = []
    for model in [x.strip() for x in a.models.split(",") if x.strip()]:
        t0 = time.perf_counter()
        try:
            r = client.models.generate_content(
                model=model,
                contents="A transfer of ₹50,000 was made. Reply with answer='ok' and amount_inr as an integer.",
                config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Probe, temperature=0,
                                                   http_options=types.HttpOptions(timeout=30000)))
            p = r.parsed if isinstance(r.parsed, Probe) else Probe.model_validate_json(r.text)
            um = r.usage_metadata
            print(f"OK   {model:28s} {int((time.perf_counter() - t0) * 1000):6d} ms  in={um.prompt_token_count} "
                  f"out={um.candidates_token_count} amount={p.amount_inr}")
            ok.append(model)
        except Exception as exc:
            print(f"FAIL {model:28s} {type(exc).__name__}: {str(exc)[:140]}")
    pro = [m for m in ok if "pro" in m] + [m for m in ok if "flash" in m and "lite" not in m]
    fast = [m for m in ok if "flash" in m and "lite" not in m] + [m for m in ok if "lite" in m]
    print("\nSuggested settings:")
    print(f"  GEMINI_PRO_MODELS={','.join(pro[:2]) or '<none>'}")
    print(f"  GEMINI_FAST_MODELS={','.join(fast[:2]) or '<none>'}")
    print(f"  GEMINI_LOCATION={a.location}")


if __name__ == "__main__":
    main()
