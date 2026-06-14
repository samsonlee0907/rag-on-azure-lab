"""Pre-ingest every workshop skill profile so the lab notebooks can reuse them.

Run once (it is idempotent thanks to reuse=True). Each profile re-indexes the
same source PDF into a progressively richer Azure AI Search index.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lab_runtime as lab

info = lab.bootstrap()
print("BOOTSTRAP:", info["search_endpoint"], "configured=", info["search_configured"])

PROFILES = [
    "baseline_extract",
    "chunk_vector",
    "genai_enrichment",
    "visual_nlp",
    "content_understanding",
]

for profile in PROFILES:
    print(f"\n=== {profile} ===")
    try:
        job = lab.ingest(skill_profile=profile, reuse=True)
        print("OVERVIEW:", lab.chunk_overview(job))
    except Exception as exc:  # keep going so one failure doesn't block the rest
        print(f"!! {profile} failed: {exc}")

print("\nPRE_INGEST_DONE")
