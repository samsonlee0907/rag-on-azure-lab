"""Shared runtime helpers for the lab walkthrough notebooks.

These helpers drive the *real* ingestion and retrieval stack in-process (the same
code the FastAPI app and the browser UI call) so each notebook can show the
search ingestion flow, inspect the chunks that were produced, and run grounded
queries against Azure AI Search with captured outputs.

Import order matters: ``backend.core.config.Settings`` reads environment
variables when the module is first imported, so this helper loads the
repository ``.env`` into ``os.environ`` and changes the working directory to the
repository root *before* any backend module is imported.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any


# --------------------------------------------------------------------------- #
# Environment bootstrap (must run before importing backend modules)
# --------------------------------------------------------------------------- #

def _find_repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here.parent, *here.parents):
        if (candidate / "backend" / "app.py").exists():
            return candidate
    # Fallback: assume the notebooks live directly under the repo root.
    return here.parent.parent


REPO_ROOT = _find_repo_root()
RESULTS_DIR = REPO_ROOT / "notebooks" / "results"
RESULTS_FILE = RESULTS_DIR / "lab_runs.jsonl"
DEFAULT_PDF = Path(
    os.environ.get(
        "LAB_SOURCE_PDF",
        str(Path.home() / "Downloads" / "Deep Excavation Design and Construction.pdf"),
    )
)


def _load_dotenv(path: Path) -> int:
    """Load a simple KEY=VALUE .env file into os.environ (no overrides)."""
    if not path.exists():
        return 0
    loaded = 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value
            loaded += 1
    return loaded


def bootstrap() -> dict[str, Any]:
    """Prepare the process so backend services can run from a notebook.

    Returns a small dict describing what was configured so the first notebook
    cell can print a friendly confirmation.
    """
    os.chdir(REPO_ROOT)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    loaded = _load_dotenv(REPO_ROOT / ".env")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Import lazily, after the environment is in place.
    from backend.core.config import settings

    return {
        "repo_root": _redact_path(REPO_ROOT),
        "env_values_loaded": loaded,
        "search_endpoint": _redact_endpoint(settings.azure_search_endpoint),
        "search_configured": bool(settings.azure_search_endpoint and settings.azure_search_key),
        "embedding_deployment": settings.azure_openai_embedding_deployment,
        "chat_deployment": settings.azure_foundry_chat_deployment,
        "agentic_planning_model": settings.azure_search_llm_deployment,
        "canonical_index": settings.azure_search_index_name,
    }


def _redact_path(path: "str | os.PathLike[str] | None") -> str:
    """Mask the user home directory so committed notebook outputs are safe.

    Replaces the current user's home directory prefix (e.g.
    ``C:\\Users\\<name>``) with ``<home>`` so executed notebooks do not leak the
    local username or machine-specific paths when committed.
    """

    if not path:
        return ""
    text = str(path)
    home = str(Path.home())
    if home and text.lower().startswith(home.lower()):
        return "<home>" + text[len(home):]
    return text


def _redact_endpoint(endpoint: str | None) -> str:
    """Mask the resource-specific host so notebook outputs are safe to publish.

    Keeps the Azure service domain (e.g. ``search.windows.net``) for context but
    replaces the unique resource name with a placeholder, so committing executed
    notebooks does not reveal the live resource.
    """

    if not endpoint:
        return ""
    match = re.match(r"^(https?://)([^.]+)(\..+)$", endpoint.strip())
    if not match:
        return "https://your-search-service.search.windows.net"
    return f"{match.group(1)}your-search-service{match.group(3)}"


# --------------------------------------------------------------------------- #
# Ingestion
# --------------------------------------------------------------------------- #

def _backend():
    """Return frequently used backend handles (imported after bootstrap)."""
    from backend.services.pipeline import pipeline
    from backend.services.job_store import job_store
    from backend.services.indexing import build_foundry_adapter

    return pipeline, job_store, build_foundry_adapter


from contextlib import contextmanager


@contextmanager
def active_profile(profile_id: str | None):
    """Pin the *global* workshop profile for the duration of a backend call.

    The application is designed to run with a single ``WORKSHOP_SKILL_PROFILE``
    for the whole process. Several behaviours read that global value via
    ``get_workshop_skill_profile()`` rather than a per-job argument, including:

    * whether ``content_vector`` embeddings are generated at publish time, and
    * which enrichment knowledge source the agentic knowledge base binds to.

    A notebook kernel drives *multiple* profiles in one process, so we must align
    the global profile with the job under test around each ingest/retrieve/chat
    call. Without this, vectors are skipped and agentic retrieval fails with
    "Knowledge Source Params target ... must match a Knowledge Base Knowledge
    Source name" because the knowledge base was last built for another profile.
    """
    from backend.core.config import settings

    if not profile_id:
        yield
        return
    previous = settings.workshop_skill_profile
    settings.workshop_skill_profile = profile_id
    try:
        yield
    finally:
        settings.workshop_skill_profile = previous


def _ensure_knowledge_base_for(profile_id: str | None) -> None:
    """Rebuild the agentic knowledge base so its sources match ``profile_id``.

    The live search adapter only (re)builds the knowledge base at *publish*
    time, so after driving several profiles in one kernel the knowledge base is
    bound to whichever profile published last. Agentic retrieval for any other
    profile then fails with "Knowledge Source Params target ... must match a
    Knowledge Base Knowledge Source name". Re-ensuring the knowledge sources and
    knowledge base under the pinned profile keeps the registered sources aligned
    with the document being queried. The operation is idempotent and cheap.
    """
    if not profile_id:
        return
    _, _, build_foundry_adapter = _backend()
    adapter = build_foundry_adapter()
    with active_profile(profile_id):
        if hasattr(adapter, "_ensure_knowledge_sources"):
            adapter._ensure_knowledge_sources()
        if hasattr(adapter, "_ensure_knowledge_base"):
            adapter._ensure_knowledge_base()


def _run_with_kb_sync_retry(call, profile_id: str | None, *, attempts: int = 4):
    """Call ``call`` and retry the knowledge-base-source mismatch race.

    Switching the active profile rebuilds the agentic knowledge base, but the
    update is eventually consistent: the ``/retrieve`` endpoint can briefly still
    see the previous source set and reject the request with "Knowledge Source
    Params target ... must match a Knowledge Base Knowledge Source name". When
    that happens we re-ensure the knowledge base, wait briefly for propagation,
    and retry a few times before giving up.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - inspect message to scope the retry
            message = str(exc)
            if "must match a Knowledge Base Knowledge Source" not in message:
                raise
            last_exc = exc
            if attempt == attempts:
                break
            _ensure_knowledge_base_for(profile_id)
            time.sleep(2 * attempt)
    raise last_exc


def find_existing_job(*, skill_profile_id: str, file_name: str):
    """Return the most recent ready job for a profile+file, or None."""
    _, job_store, _ = _backend()
    candidates = [
        job
        for job in job_store.list_jobs()
        if job.status == "ready"
        and job.skill_profile_id == skill_profile_id
        and job.file_name == file_name
        and job.chunks_path
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda job: job.updated_at, reverse=True)
    return candidates[0]


def ingest(
    pdf_path: str | Path = DEFAULT_PDF,
    *,
    skill_profile: str,
    reuse: bool = True,
    verbose: bool = True,
):
    """Ingest ``pdf_path`` with the given workshop skill profile.

    Runs the exact same pipeline the FastAPI app runs (parse -> normalize ->
    chunk -> Azure AI Search blob+skillset enrichment -> publish), synchronously
    so the notebook captures the real result.

    When ``reuse`` is True a previously completed run for the same profile and
    file is returned instead of re-ingesting (saves time and Azure cost on
    notebook re-runs). Pass ``reuse=False`` to force a fresh ingestion.
    """
    from fastapi import BackgroundTasks

    pipeline, job_store, _ = _backend()
    pdf_path = Path(pdf_path)

    # Reuse is resolved by profile + file *name*, so a cached run can be replayed
    # offline even when the original source file is no longer on this machine
    # (e.g. re-executing a committed notebook on a fresh clone). Only require the
    # file to exist when we actually have to ingest it.
    if reuse:
        existing = find_existing_job(skill_profile_id=skill_profile, file_name=pdf_path.name)
        if existing is not None:
            if verbose:
                print(
                    f"Reusing existing '{skill_profile}' ingestion "
                    f"(doc_id={existing.doc_id[:8]}, {existing.chunk_count} chunks). "
                    "Pass reuse=False to force a fresh run."
                )
            return existing

    if not pdf_path.exists():
        raise FileNotFoundError(f"Source PDF not found: {pdf_path}")

    job = pipeline.create_job_from_path(
        pdf_path,
        BackgroundTasks(),  # tasks are executed manually below, not by FastAPI
        file_name=pdf_path.name,
        ingestion_mode="hybrid_blob_skillset",
        skill_profile=skill_profile,
        source_kind="notebook",
    )
    if verbose:
        print(f"Ingesting '{pdf_path.name}' with profile '{skill_profile}' (doc_id={job.doc_id[:8]}) ...")

    # Several publish-time behaviours (notably whether content_vector embeddings
    # are generated and uploaded) are gated on the *global* active workshop
    # profile via get_workshop_skill_profile(), mirroring how the deployed app
    # runs with WORKSHOP_SKILL_PROFILE set for the whole process. When driving
    # multiple profiles in a single notebook kernel we must align that global
    # profile with the job's profile for the duration of the run, otherwise the
    # default (baseline_extract) suppresses vectors for every profile.
    started = time.time()
    with active_profile(skill_profile):
        pipeline.run(job.doc_id)  # synchronous full pipeline
    elapsed = time.time() - started

    job = job_store.get(job.doc_id)
    if verbose:
        status = job.status.value if hasattr(job.status, "value") else job.status
        print(f"  -> status={status} stage={job.stage} chunks={job.chunk_count} in {elapsed:0.1f}s")
        for err in job.errors:
            print(f"  !! {err}")
    return job


def load_chunks(job) -> list[dict[str, Any]]:
    """Load the published chunk records for a job as plain dicts."""
    if not job.chunks_path or not Path(job.chunks_path).exists():
        return []
    return json.loads(Path(job.chunks_path).read_text(encoding="utf-8"))


def chunk_overview(job) -> dict[str, Any]:
    """Summarise the chunk set so notebooks can show ingestion characteristics."""
    chunks = load_chunks(job)
    token_counts = [c.get("token_estimate", 0) for c in chunks]
    enriched = [c for c in chunks if c.get("summary_text")]
    with_keywords = [c for c in chunks if c.get("keyword_hints")]
    with_image_desc = [c for c in chunks if c.get("image_description_text")]
    return {
        "doc_id": job.doc_id,
        "skill_profile": job.skill_profile_id,
        "chunk_count": len(chunks),
        "avg_tokens": round(sum(token_counts) / len(token_counts), 1) if token_counts else 0,
        "max_tokens": max(token_counts) if token_counts else 0,
        "chunks_with_summary": len(enriched),
        "chunks_with_keyword_hints": len(with_keywords),
        "chunks_with_image_description": len(with_image_desc),
    }


# --------------------------------------------------------------------------- #
# Retrieval
# --------------------------------------------------------------------------- #

def _doc_source_assignments(job) -> dict[str, str]:
    from backend.core.config import settings

    return {
        job.doc_id: (job.publish_status.diagnostics or {}).get(
            "knowledge_source_name", settings.azure_search_knowledge_source_name
        )
    }


# --------------------------------------------------------------------------- #
# Multi-source knowledge routing (Lab 09)
# --------------------------------------------------------------------------- #

def build_adapter():
    """Return the live Azure AI Search adapter the app uses.

    Lab 09 inspects the adapter's knowledge-source routing directly, so the
    notebook can show *which* index the knowledge base decided to query for a
    given question — and why — before any answer is synthesised.
    """
    _, _, build_foundry_adapter = _backend()
    return build_foundry_adapter()


def route_preview(question: str, *, include_enrichment: bool = False) -> dict[str, Any]:
    """Show how the knowledge base would route ``question`` across indexes.

    This calls the same ``_route_knowledge_sources`` logic the live retrieve
    path uses, but stops *before* issuing any search request, so it is fast and
    free. Returns a compact, notebook-friendly view of the decision: the routing
    mode, the indexes that were selected, and the per-source terms that matched.
    """
    adapter = build_adapter()
    if not hasattr(adapter, "_route_knowledge_sources"):
        return {
            "routing_mode": "local_preview",
            "routing_reason": "Azure AI Search is not configured; multi-source routing is unavailable.",
            "selected_search_indexes": [],
            "matched_terms_by_index": {},
        }
    _, diagnostics = adapter._route_knowledge_sources(
        question, include_enrichment=include_enrichment
    )
    matched_terms_by_index = {
        detail["index_name"]: detail["matched_terms"]
        for detail in diagnostics.get("knowledge_source_match_details", [])
    }
    return {
        "question": question,
        "routing_mode": diagnostics.get("routing_mode"),
        "routing_reason": diagnostics.get("routing_reason"),
        "available_search_indexes": diagnostics.get("available_search_indexes", []),
        "selected_search_indexes": diagnostics.get("selected_search_indexes", []),
        "matched_terms_by_index": matched_terms_by_index,
        "multi_index_routing": diagnostics.get("multi_index_routing", False),
    }


def multi_source_search(
    question: str,
    *,
    retrieval_mode: str = "hybrid",
    top: int = 6,
) -> list[dict[str, Any]]:
    """Run a direct search the router scopes across *all* configured indexes.

    No ``doc_ids`` are passed, so the knowledge-source router (not a manual
    corpus pin) decides which index or indexes answer the question. Each hit
    carries the index it came from, which is the whole point of the lab: you can
    see the AI-trends questions land on the AI-trends index and the excavation
    questions land on the primary index.
    """
    adapter = build_adapter()
    payload = adapter.direct_search(question, retrieval_mode=retrieval_mode)
    hits: list[dict[str, Any]] = []
    for item in payload.get("results", [])[:top]:
        hits.append(
            {
                "index": item.get("index_name"),
                "knowledge_source": item.get("knowledgeSourceName"),
                "score": round(float(item.get("@search.score", 0.0)), 4),
                "source_doc": item.get("source_name"),
                "snippet": (item.get("snippet") or item.get("clean_text") or "")[:200].strip(),
            }
        )
    return hits, payload.get("diagnostics", {})


def ask_corpus(
    question: str,
    *,
    retrieval_mode: str = "agentic",
    active_profile_id: str = "genai_enrichment",
):
    """Answer ``question`` over the whole workshop corpus (router picks sources).

    Unlike :func:`ask`, this does not pin the query to one document. It runs the
    app's chat turn in ``auto`` corpus mode so the knowledge base routes across
    every ready corpus, mirroring a real multi-document assistant. ``active
    profile_id`` aligns the agentic knowledge base with the profile the relevant
    documents were ingested under (see :func:`active_profile`).
    """
    from backend.app import chat
    from backend.domain.models import ChatTurnRequest

    is_agentic = retrieval_mode.strip().lower() == "agentic"
    if is_agentic:
        _ensure_knowledge_base_for(active_profile_id)

    def _do_chat():
        with active_profile(active_profile_id):
            return chat(
                ChatTurnRequest(
                    question=question,
                    corpus_mode="auto",
                    retrieval_mode=retrieval_mode,
                )
            )

    return _run_with_kb_sync_retry(_do_chat, active_profile_id) if is_agentic else _do_chat()


def retrieve(
    question: str,
    *,
    job,
    retrieval_mode: str,
    scoring_profile: str = "default",
    top: int = 5,
) -> list[dict[str, Any]]:
    """Return scored retrieval hits (no answer synthesis) for inspection.

    Uses the same adapter the app uses. For full_text/vector/hybrid this returns
    Azure AI Search ``@search.score`` ordered hits; for agentic it returns the
    knowledge-base references.
    """
    _, _, build_foundry_adapter = _backend()
    adapter = build_foundry_adapter()
    mode = retrieval_mode.strip().lower()
    assignments = _doc_source_assignments(job)

    if mode in {"full_text", "vector", "hybrid"}:
        with active_profile(job.skill_profile_id):
            payload = adapter.direct_search(
                question,
                retrieval_mode=mode,
                doc_ids=[job.doc_id],
                doc_source_assignments=assignments,
                scoring_profile=scoring_profile,
            )
        hits = []
        for item in payload.get("results", [])[:top]:
            hits.append(
                {
                    "score": round(float(item.get("@search.score", 0.0)), 4),
                    "reranker": item.get("@search.rerankerScore"),
                    "section": " > ".join(item.get("section_path") or []) or "(root)",
                    "pages": item.get("page_numbers") or [],
                    "snippet": (item.get("snippet") or item.get("clean_text") or "")[:280].strip(),
                }
            )
        return hits

    # Agentic / knowledge-base retrieval.
    _ensure_knowledge_base_for(job.skill_profile_id)

    def _do_agentic_search():
        with active_profile(job.skill_profile_id):
            return adapter.chat(
                question,
                doc_ids=[job.doc_id],
                doc_source_assignments=assignments,
            )

    payload = _run_with_kb_sync_retry(_do_agentic_search, job.skill_profile_id)
    refs = payload.get("references") or payload.get("results") or []
    hits = []
    for item in refs[:top]:
        if not isinstance(item, dict):
            continue
        source = item.get("sourceData") or item
        hits.append(
            {
                "score": item.get("rerankerScore") or item.get("@search.score"),
                "section": " > ".join(source.get("section_path") or []) or "(root)",
                "pages": source.get("page_numbers") or [],
                "snippet": (source.get("clean_text") or item.get("content") or "")[:280].strip(),
            }
        )
    return hits


def ask(
    question: str,
    *,
    job,
    retrieval_mode: str,
    scoring_profile: str = "default",
    record_as: str | None = None,
):
    """Run a full grounded chat turn (retrieval + synthesis) like the UI does.

    Returns the ChatTurnResponse. When ``record_as`` is provided the run is
    appended to ``notebooks/results/lab_runs.jsonl`` so the final comparison
    notebook can read every lab's captured output.
    """
    from backend.app import chat
    from backend.domain.models import ChatTurnRequest

    is_agentic = retrieval_mode.strip().lower() == "agentic"
    # Agentic retrieval depends on a knowledge base whose registered sources
    # match the document's profile; re-ensure it before querying (see
    # _ensure_knowledge_base_for). Direct modes do not use the knowledge base.
    if is_agentic:
        _ensure_knowledge_base_for(job.skill_profile_id)

    def _do_chat():
        with active_profile(job.skill_profile_id):
            return chat(
                ChatTurnRequest(
                    question=question,
                    corpus_mode="custom",
                    corpus_doc_ids=[job.doc_id],
                    retrieval_mode=retrieval_mode,
                    scoring_profile=scoring_profile,
                )
            )

    started = time.time()
    response = _run_with_kb_sync_retry(_do_chat, job.skill_profile_id) if is_agentic else _do_chat()
    elapsed = round(time.time() - started, 2)

    if record_as:
        record_run(
            label=record_as,
            question=question,
            retrieval_mode=retrieval_mode,
            scoring_profile=scoring_profile,
            job=job,
            response=response,
            elapsed_s=elapsed,
        )
    return response


# --------------------------------------------------------------------------- #
# Display helpers
# --------------------------------------------------------------------------- #

def show_answer(response, *, max_citations: int = 6) -> None:
    """Pretty-print a ChatTurnResponse for a notebook cell."""
    diag = response.diagnostics or {}
    mode = diag.get("retrieval_mode") or diag.get("search_method") or diag.get("mode")
    print(f"[retrieval_mode={mode} | scoring_profile={diag.get('scoring_profile', 'default')} | "
          f"citations={len(response.citations)}]\n")
    print(response.answer.strip())
    if response.citations:
        print("\nCitations:")
        for cite in response.citations[:max_citations]:
            section = " > ".join(cite.section_path) if cite.section_path else cite.title
            pages = f" p.{cite.page_numbers}" if cite.page_numbers else ""
            ref = f"[{cite.reference_id}] " if cite.reference_id else ""
            print(f"  {ref}{section}{pages}")


def hits_table(hits: list[dict[str, Any]]):
    """Return a pandas DataFrame of retrieval hits (falls back to the list)."""
    try:
        import pandas as pd

        return pd.DataFrame(hits)
    except Exception:
        return hits


def keypoint_coverage(answer: str, keypoints: list[Any]) -> dict[str, Any]:
    """Score an answer against a rubric of expected key points.

    ``keypoints`` is a list where each item is either a plain string (used as
    both the label and the single match term) or a ``(label, [terms])`` pair.
    A key point counts as covered when any of its terms appears in the answer
    (case-insensitive substring match). Returns the covered/missing labels and a
    ``"n/total"`` score string so a reader who does not know the domain can see,
    at a glance, how completely each retrieval mode answered the question.
    """

    text = (answer or "").lower()
    covered: list[str] = []
    missing: list[str] = []
    for item in keypoints:
        if isinstance(item, (list, tuple)):
            label, terms = item[0], list(item[1])
        else:
            label, terms = item, [item]
        if any(term.lower() in text for term in terms):
            covered.append(label)
        else:
            missing.append(label)
    total = len(keypoints)
    return {
        "covered": covered,
        "missing": missing,
        "covered_count": len(covered),
        "total": total,
        "score": f"{len(covered)}/{total}",
    }


def citation_summary(response, *, top: int = 3) -> str:
    """Return a compact ``section (pages)`` summary of the top citations."""
    parts: list[str] = []
    for cite in response.citations[:top]:
        section = " > ".join(cite.section_path) if cite.section_path else (cite.title or "—")
        pages = f" p.{cite.page_numbers}" if cite.page_numbers else ""
        parts.append(f"{section}{pages}")
    return "; ".join(parts) if parts else "—"


# --------------------------------------------------------------------------- #
# Results recording (for the final comparison notebook)
# --------------------------------------------------------------------------- #

def record_run(
    *,
    label: str,
    question: str,
    retrieval_mode: str,
    scoring_profile: str,
    job,
    response,
    elapsed_s: float,
) -> None:
    diag = response.diagnostics or {}
    entry = {
        "label": label,
        "skill_profile": job.skill_profile_id,
        "doc_id": job.doc_id,
        "question": question,
        "retrieval_mode": retrieval_mode,
        "scoring_profile": scoring_profile,
        "effective_retrieval_mode": diag.get("retrieval_mode") or diag.get("search_method"),
        "answer_synthesis_enabled": diag.get("answer_synthesis_enabled"),
        "citation_count": len(response.citations),
        "query_rescue_applied": diag.get("query_rescue_applied", False),
        "elapsed_s": elapsed_s,
        "answer": response.answer.strip(),
        "citations": [
            {
                "section": " > ".join(c.section_path) if c.section_path else c.title,
                "pages": c.page_numbers,
                "reference_id": c.reference_id,
            }
            for c in response.citations[:8]
        ],
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with RESULTS_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_runs() -> list[dict[str, Any]]:
    """Load every recorded lab run (for the comparison notebook)."""
    if not RESULTS_FILE.exists():
        return []
    runs = []
    for line in RESULTS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            runs.append(json.loads(line))
    return runs
