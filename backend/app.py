from __future__ import annotations

import json
import logging
from pathlib import Path
import shutil

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.core.config import settings
from backend.core.logging import configure_logging
from backend.domain.models import ChatTurnRequest, ChatTurnResponse, JobRecord, PublishStatus
from backend.services.blob_storage import build_blob_artifact_store, build_blob_search_asset_store
from backend.services.chat import (
    build_query_rescue,
    local_preview_chat,
    response_needs_query_rescue,
    synthesize_grounded_chat,
)
from backend.services.indexing import LocalPreviewAdapter, build_foundry_adapter
from backend.services.job_store import job_store
from backend.services.native_multimodal_search import native_multimodal_search
from backend.services.pipeline import pipeline
from backend.services.sample_documents import (
    create_construction_industry_report,
    create_generative_ai_futures_report,
    create_random_research_corpus,
)
from backend.services.workshop_profiles import build_workshop_profile_summary, build_workshop_skill_profiles

configure_logging(settings.log_level)

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = Path.cwd() / "frontend" / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")

_WORKSHOP_PROFILE_TITLES = {profile.id: profile.title for profile in build_workshop_skill_profiles()}


def _job_or_404(doc_id: str) -> JobRecord:
    try:
        return job_store.get(doc_id)
    except KeyError as exc:  # pragma: no cover - API handling
        raise HTTPException(status_code=404, detail="Document not found.") from exc


def _load_chunk_records(job: JobRecord) -> list:
    if not job.chunks_path or not Path(job.chunks_path).exists():
        return []
    from backend.domain.models import ChunkRecord

    payload = json.loads(Path(job.chunks_path).read_text(encoding="utf-8"))
    return [ChunkRecord.model_validate(item) for item in payload]


def _job_route_text(job: JobRecord) -> str:
    if not job.intermediate_path or not Path(job.intermediate_path).exists():
        return ""
    try:
        intermediate = json.loads(Path(job.intermediate_path).read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    headings = []
    for section in intermediate.get("sections") or []:
        if not isinstance(section, dict):
            continue
        heading = section.get("heading")
        if isinstance(heading, str) and heading.strip():
            headings.append(heading.strip())
        if len(headings) >= 12:
            break
    return " ".join(headings)


def _job_workshop_profile_id(job: JobRecord) -> str:
    blob_skillset = (job.enrichment_status or {}).get("blob_skillset") or {}
    search_objects = blob_skillset.get("search_objects") or {}
    diagnostics = blob_skillset.get("diagnostics") or {}
    workshop_profile = diagnostics.get("workshop_profile") if isinstance(diagnostics, dict) else None
    extracted_fields = blob_skillset.get("extracted_fields") or {}
    return (
        search_objects.get("workshop_profile_id")
        or (workshop_profile.get("id") if isinstance(workshop_profile, dict) else None)
        or extracted_fields.get("skill_profile_id")
        or job.skill_profile_id
        or "untracked"
    )


def _job_workshop_profile_title(job: JobRecord) -> str:
    profile_id = _job_workshop_profile_id(job)
    return _WORKSHOP_PROFILE_TITLES.get(profile_id, profile_id.replace("_", " ").title())


def _job_corpus_label(job: JobRecord) -> str:
    return f"{job.file_name} · {_job_workshop_profile_title(job)} · {job.doc_id[:8]}"


def _available_retrieval_modes() -> list[str]:
    # Profiles are now chosen per document at upload time, so the chat surface
    # offers the full union of retrieval modes recommended by any profile.
    ordered: list[str] = []
    for profile in build_workshop_skill_profiles():
        for mode in profile.recommended_retrieval_modes:
            if mode not in ordered:
                ordered.append(mode)
    for fallback in ("full_text", "vector", "hybrid", "agentic"):
        if fallback not in ordered:
            ordered.append(fallback)
    if settings.azure_search_native_multimodal_enabled and "native_multimodal" not in ordered:
        ordered.append("native_multimodal")
    return ordered


def _is_repo_managed_path(path: Path) -> bool:
    """True only when ``path`` lives inside a directory this app owns.

    Notebook-driven ingestion records the *original* source path (e.g. a file in
    the user's Downloads folder) as ``stored_path`` instead of copying it into
    the repo. Deleting a job must never remove source files that live outside the
    application's managed directories, so artifact cleanup is restricted to these
    roots.
    """
    try:
        resolved = path.resolve()
    except Exception:
        return False
    managed_roots = [
        settings.uploads_dir,
        settings.artifacts_dir,
        settings.data_dir,
    ]
    for root in managed_roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _delete_job_artifacts(job: JobRecord) -> None:
    intermediate_payload = None
    if job.intermediate_path and Path(job.intermediate_path).exists():
        intermediate_payload = json.loads(Path(job.intermediate_path).read_text(encoding="utf-8"))

    directory_candidates = []
    stored_path = Path(job.stored_path)
    directory_candidates.append(settings.artifacts_dir / f"{job.doc_id}_figures")
    directory_candidates.append(settings.artifacts_dir / f"{stored_path.stem}_segments")
    directory_candidates.append(settings.artifacts_dir / f"{stored_path.stem}_diagrams")
    for directory in directory_candidates:
        if directory.exists() and directory.is_dir():
            shutil.rmtree(directory, ignore_errors=True)

    if intermediate_payload:
        figures = (intermediate_payload.get("metadata") or {}).get("figure_artifacts") or []
        blob_store = build_blob_artifact_store()
        if blob_store is not None:
            for figure in figures:
                if not isinstance(figure, dict):
                    continue
                blob_name = figure.get("blob_name")
                if not blob_name:
                    continue
                try:
                    blob_store.delete_blob(blob_name)
                except Exception:
                    continue

    paths_to_unlink = [
        job.stored_path,
        job.intermediate_path,
        job.chunks_path,
    ]
    for raw_path in paths_to_unlink:
        if not raw_path:
            continue
        path = Path(raw_path)
        # Never delete source files outside the repo's managed directories. The
        # notebook ingestion path stores the original (e.g. Downloads) location
        # as stored_path, and that file must be treated as read-only reference.
        if not _is_repo_managed_path(path):
            continue
        if path.exists() and path.is_file():
            path.unlink()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def config_summary() -> dict[str, object]:
    available_retrieval_modes = _available_retrieval_modes()
    return {
        "app_name": settings.app_name,
        "default_ingestion_mode": settings.default_ingestion_mode,
        "search_pipeline_mode": settings.search_pipeline_mode,
        "azure_document_intelligence_enabled": settings.azure_docint_enabled,
        "azure_content_understanding_enabled": settings.azure_content_understanding_enabled,
        "azure_search_enabled": settings.azure_search_enabled,
        "azure_agentic_retrieval_enabled": settings.azure_search_enabled,
        "azure_agentic_planning_model_enabled": settings.azure_search_llm_enabled,
        "azure_agentic_planning_model": settings.azure_search_llm_deployment,
        "azure_search_multi_index_enabled": settings.azure_search_multi_index_enabled,
        "azure_search_extra_indexes": [source.index_name for source in settings.azure_search_extra_sources],
        "azure_blob_storage_enabled": settings.azure_blob_storage_enabled,
        "azure_search_blob_ingestion_enabled": settings.azure_search_blob_ingestion_enabled,
        "azure_search_native_multimodal_enabled": settings.azure_search_native_multimodal_enabled,
        "azure_search_native_knowledge_base_name": settings.azure_search_native_knowledge_base_name,
        "azure_search_skillset_name": settings.azure_search_skillset_name,
        "azure_search_blob_data_source_name": settings.azure_search_blob_data_source_name,
        "azure_search_blob_indexer_name": settings.azure_search_blob_indexer_name,
        "azure_search_enrichment_index_name": settings.azure_search_enrichment_index_name,
        "azure_search_enable_answer_synthesis": settings.azure_search_enable_answer_synthesis,
        "azure_search_enable_enrichment_cache": settings.azure_search_enable_enrichment_cache,
        "azure_search_enable_genai_prompt_skill": settings.azure_search_enable_genai_prompt_skill,
        "azure_search_enable_integrated_vectorization": settings.azure_search_enable_integrated_vectorization,
        "azure_search_enable_image_serving": settings.azure_search_enable_image_serving,
        "available_retrieval_modes": available_retrieval_modes,
        "default_retrieval_mode": available_retrieval_modes[0],
        "available_scoring_profiles": ["default", "enrichment-weighted", "freshness-boosted"],
        "default_scoring_profile": "default",
        "azure_search_native_content_extraction_mode": settings.azure_search_native_content_extraction_mode,
        "azure_search_native_chat_completion_deployment": settings.azure_search_native_chat_completion_deployment,
        "azure_search_skillset_preferred_extractor": settings.azure_search_skillset_preferred_extractor,
        "workshop_strict_mode": settings.workshop_strict_mode,
        "workshop_skill_profile": settings.workshop_skill_profile,
        "azure_search_require_blob_skillset_success": settings.azure_search_require_blob_skillset_success,
        "azure_search_require_native_multimodal_success": settings.azure_search_require_native_multimodal_success,
        "foundry_chat_mode": settings.foundry_chat_mode,
        "knowledge_base_name": settings.azure_search_knowledge_base_name,
        "search_index_name": settings.azure_search_index_name,
        "request_timeout_seconds": settings.request_timeout_seconds,
        "workshop_profiles_endpoint": "/api/workshop/profiles",
    }


@app.get("/api/workshop/profiles")
def workshop_profiles() -> dict[str, object]:
    return build_workshop_profile_summary()


@app.get("/api/dashboard")
def dashboard() -> dict[str, object]:
    jobs = job_store.list_jobs()
    return {
        "total_documents": len(jobs),
        "processing_queue": len([job for job in jobs if job.status == "processing"]),
        "ready_for_chat": len([job for job in jobs if job.status == "ready"]),
        "failed_jobs": len([job for job in jobs if job.status == "failed"]),
        "recent_activity": [
            {"doc_id": job.doc_id, "file_name": job.file_name, "stage": job.stage, "updated_at": job.updated_at}
            for job in sorted(jobs, key=lambda item: item.updated_at, reverse=True)[:8]
        ],
    }


@app.get("/api/documents")
def list_documents() -> list[dict[str, object]]:
    return [job.model_dump(mode="json") for job in sorted(job_store.list_jobs(), key=lambda item: item.created_at, reverse=True)]


@app.post("/api/documents/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    ingestion_mode: str = Form(settings.default_ingestion_mode),
    skill_profile: str | None = Form(None),
) -> dict[str, object]:
    job = await pipeline.create_job(
        file,
        background_tasks,
        ingestion_mode=ingestion_mode,
        skill_profile=skill_profile,
    )
    return job.model_dump(mode="json")


@app.post("/api/samples/random-research-corpus")
def create_random_research_sample(
    background_tasks: BackgroundTasks,
    page_count: int = settings.hard_page_split_threshold + 5,
    topic: str | None = None,
    ingestion_mode: str = settings.default_ingestion_mode,
    skill_profile: str | None = None,
) -> dict[str, object]:
    if page_count <= settings.hard_page_split_threshold:
        raise HTTPException(
            status_code=400,
            detail=(
                f"page_count must be greater than the hard split threshold of "
                f"{settings.hard_page_split_threshold}."
            ),
        )
    sample = create_random_research_corpus(page_count=page_count, topic=topic)
    job = pipeline.create_job_from_path(
        sample.path,
        background_tasks,
        file_name=sample.file_name,
        activity_message=(
            f"Generated {sample.page_count}-page research corpus on {sample.report_title or 'a random topic'} and queued it for segmented ingestion."
        ),
        ingestion_mode=ingestion_mode,
        skill_profile=skill_profile,
        source_kind="generated_sample",
    )
    return {
        "job": job.model_dump(mode="json"),
        "sample": {
            "file_name": sample.file_name,
            "page_count": sample.page_count,
            "path": str(sample.path),
            "section_interval": sample.section_interval,
            "topic_key": sample.topic_key,
            "report_title": sample.report_title,
        },
    }


@app.post("/api/samples/generative-ai-futures-report")
def create_generative_ai_futures_sample(
    background_tasks: BackgroundTasks,
    page_count: int = 520,
    ingestion_mode: str = settings.default_ingestion_mode,
    skill_profile: str | None = None,
) -> dict[str, object]:
    if page_count <= 500:
        raise HTTPException(status_code=400, detail="page_count must be greater than 500.")
    sample = create_generative_ai_futures_report(page_count=page_count)
    job = pipeline.create_job_from_path(
        sample.path,
        background_tasks,
        file_name=sample.file_name,
        activity_message=(
            f"Generated {sample.page_count}-page futures report with diagrams and queued it for ingestion."
        ),
        ingestion_mode=ingestion_mode,
        skill_profile=skill_profile,
        source_kind="generated_sample",
    )
    return {
        "job": job.model_dump(mode="json"),
        "sample": {
            "file_name": sample.file_name,
            "page_count": sample.page_count,
            "path": str(sample.path),
            "section_interval": sample.section_interval,
        },
    }


@app.post("/api/samples/construction-industry-report")
def create_construction_industry_sample(
    background_tasks: BackgroundTasks,
    page_count: int = 540,
    ingestion_mode: str = settings.default_ingestion_mode,
    skill_profile: str | None = None,
) -> dict[str, object]:
    if page_count <= 500:
        raise HTTPException(status_code=400, detail="page_count must be greater than 500.")
    sample = create_construction_industry_report(page_count=page_count)
    job = pipeline.create_job_from_path(
        sample.path,
        background_tasks,
        file_name=sample.file_name,
        activity_message=(
            f"Generated {sample.page_count}-page construction report with architecture diagrams and queued it for ingestion."
        ),
        ingestion_mode=ingestion_mode,
        skill_profile=skill_profile,
        source_kind="generated_sample",
    )
    return {
        "job": job.model_dump(mode="json"),
        "sample": {
            "file_name": sample.file_name,
            "page_count": sample.page_count,
            "path": str(sample.path),
            "section_interval": sample.section_interval,
        },
    }


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str) -> dict[str, object]:
    job = _job_or_404(doc_id)
    payload = job.model_dump(mode="json")
    if job.intermediate_path and Path(job.intermediate_path).exists():
        payload["intermediate"] = json.loads(Path(job.intermediate_path).read_text(encoding="utf-8"))
    if job.chunks_path and Path(job.chunks_path).exists():
        payload["chunks"] = json.loads(Path(job.chunks_path).read_text(encoding="utf-8"))
    return payload


@app.get("/api/documents/{doc_id}/figures/{artifact_id}")
def get_document_figure(doc_id: str, artifact_id: str) -> Response:
    job = _job_or_404(doc_id)
    if not job.intermediate_path or not Path(job.intermediate_path).exists():
        raise HTTPException(status_code=404, detail="No intermediate artifact is available for this document.")
    intermediate = json.loads(Path(job.intermediate_path).read_text(encoding="utf-8"))
    metadata = intermediate.get("metadata") or {}
    figures = metadata.get("figure_artifacts") or []
    figure = next(
        (
            item
            for item in figures
            if isinstance(item, dict) and item.get("artifact_id") == artifact_id
        ),
        None,
    )
    if not figure:
        raise HTTPException(status_code=404, detail="Figure artifact not found.")

    blob_name = figure.get("blob_name")
    if blob_name and settings.azure_blob_storage_enabled:
        blob_store = build_blob_artifact_store()
        if blob_store is not None:
            try:
                content, content_type = blob_store.download_bytes(blob_name)
                return Response(content=content, media_type=content_type)
            except Exception as exc:
                # Blob storage can be unreachable (e.g. the storage account
                # firewall is locked down). Fall back to the locally cached
                # artifact instead of returning a broken image to the portal.
                logger.warning(
                    "figure blob download failed; falling back to local artifact",
                    extra={"context": {"blob_name": blob_name, "error": str(exc)}},
                )

    artifact_path = figure.get("artifact_path")
    if artifact_path and Path(artifact_path).exists():
        return FileResponse(artifact_path)
    raise HTTPException(status_code=404, detail="Figure artifact is not available.")


@app.get("/api/native-images")
def get_native_image(path: str) -> Response:
    normalized = path.strip().strip("/")
    if not normalized:
        raise HTTPException(status_code=400, detail="path is required.")
    store = build_blob_search_asset_store()
    if store is None:
        raise HTTPException(status_code=503, detail="Azure AI Search native image serving is not configured.")
    try:
        content, content_type = store.download_bytes(normalized)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=f"Native image asset not found: {exc}") from exc
    return Response(content=content, media_type=content_type)


@app.post("/api/documents/{doc_id}/retry")
def retry_document(doc_id: str, background_tasks: BackgroundTasks) -> dict[str, object]:
    _job_or_404(doc_id)
    job = pipeline.retry(doc_id, background_tasks)
    return job.model_dump(mode="json")


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str) -> dict[str, object]:
    job = _job_or_404(doc_id)
    if job.status.value in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="This document is still processing and cannot be deleted yet.")

    adapter = build_foundry_adapter()
    chunks = _load_chunk_records(job)
    try:
        adapter.delete_chunks(
            chunks,
            index_name=(job.publish_status.diagnostics or {}).get("index_name"),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to remove corpus content from Azure AI Search: {exc}") from exc
    native_status = (job.enrichment_status or {}).get("native_multimodal") or {}
    native_source_name = native_status.get("knowledge_source_name") if isinstance(native_status, dict) else None
    try:
        native_multimodal_search.delete_document_source(native_source_name)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to remove native Blob multimodal knowledge source from Azure AI Search: {exc}",
        ) from exc

    _delete_job_artifacts(job)
    job_store.delete(doc_id)
    return {
        "deleted": True,
        "doc_id": doc_id,
        "file_name": job.file_name,
        "removed_chunk_count": len(chunks),
    }


@app.get("/api/knowledge/status")
def knowledge_status() -> dict[str, object]:
    status = build_foundry_adapter().get_status()
    jobs = job_store.list_jobs()
    ready_docs = [job for job in jobs if job.status == "ready"]
    return {
        "selected_knowledge_base": settings.azure_search_knowledge_base_name,
        "native_multimodal_knowledge_base": settings.azure_search_native_knowledge_base_name,
        "status": status.model_dump(mode="json"),
        "native_multimodal_enabled": settings.azure_search_native_multimodal_enabled,
        "documents": [
            {
                "doc_id": job.doc_id,
                "file_name": job.file_name,
                "corpus_label": _job_corpus_label(job),
                "workshop_skill_profile": _job_workshop_profile_id(job),
                "workshop_profile_title": _job_workshop_profile_title(job),
                "source_kind": job.source_kind,
                "created_at": job.created_at,
                "chunk_count": job.chunk_count,
                "section_count": job.section_count,
                "last_sync_time": job.publish_status.last_sync_time,
                "index_name": (job.publish_status.diagnostics or {}).get("index_name"),
                "knowledge_source_name": (job.publish_status.diagnostics or {}).get("knowledge_source_name"),
                "native_multimodal_status": ((job.enrichment_status or {}).get("native_multimodal") or {}).get("status"),
            }
            for job in ready_docs
        ],
    }


@app.post("/api/knowledge/sync")
def resync_knowledge() -> dict[str, object]:
    ready_jobs = [job for job in job_store.list_jobs() if job.chunks_path and Path(job.chunks_path).exists()]
    if not ready_jobs:
        raise HTTPException(status_code=400, detail="No processed documents are available to sync.")
    adapter = build_foundry_adapter()
    per_document = []
    latest_status = None
    for job in ready_jobs:
        chunks = _load_chunk_records(job)
        previous_index = (job.publish_status.diagnostics or {}).get("index_name")
        status = adapter.publish(
            chunks,
            source_name=job.file_name,
            route_text=_job_route_text(job),
        )
        latest_status = status
        job_store.update_publish_status(job.doc_id, status)
        new_index = (status.diagnostics or {}).get("index_name")
        if previous_index and new_index and previous_index != new_index:
            adapter.delete_chunks(chunks, index_name=previous_index)
        per_document.append(
            {
                "doc_id": job.doc_id,
                "file_name": job.file_name,
                "index_name": new_index,
                "knowledge_source_name": (status.diagnostics or {}).get("knowledge_source_name"),
            }
        )
    native_payload = native_multimodal_search.sync_knowledge_base()
    return {
        "status": latest_status.model_dump(mode="json") if latest_status else {},
        "documents": per_document,
        "native_multimodal": native_payload,
    }


@app.post("/api/chat", response_model=ChatTurnResponse)
def chat(request: ChatTurnRequest) -> ChatTurnResponse:
    jobs = [job for job in job_store.list_jobs() if job.status == "ready" and job.chunks_path]
    if not jobs:
        raise HTTPException(status_code=400, detail="No ready corpus is available for chat.")

    selected_doc_ids: list[str] = []
    if request.corpus_mode == "custom":
        selected_doc_ids = [doc_id for doc_id in request.corpus_doc_ids if doc_id]
        if not selected_doc_ids:
            raise HTTPException(status_code=400, detail="Select at least one corpus when using custom mode.")
        ready_ids = {job.doc_id for job in jobs}
        invalid = [doc_id for doc_id in selected_doc_ids if doc_id not in ready_ids]
        if invalid:
            raise HTTPException(status_code=400, detail=f"Some selected corpora are not ready: {', '.join(invalid)}")

    adapter = build_foundry_adapter()
    doc_source_assignments = {
        job.doc_id: (job.publish_status.diagnostics or {}).get("knowledge_source_name", settings.azure_search_knowledge_source_name)
        for job in jobs
    }
    native_source_assignments = {
        job.doc_id: ((job.enrichment_status or {}).get("native_multimodal") or {}).get("knowledge_source_name")
        for job in jobs
    }
    active_jobs = [job for job in jobs if not selected_doc_ids or job.doc_id in selected_doc_ids]
    requested_retrieval_mode = (request.retrieval_mode or "agentic").strip().lower()
    if requested_retrieval_mode == "auto":
        requested_retrieval_mode = "agentic"
    allowed_modes = set(_available_retrieval_modes())
    if requested_retrieval_mode not in allowed_modes:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Retrieval mode '{requested_retrieval_mode}' is not available. "
                f"Allowed modes: {', '.join(sorted(allowed_modes))}."
            ),
        )
    use_native_multimodal = requested_retrieval_mode == "native_multimodal"
    selected_native_sources = [
        source_name
        for job in active_jobs
        for source_name in [native_source_assignments.get(job.doc_id)]
        if source_name
    ]

    def _run_grounded_chat(question_text: str) -> ChatTurnResponse:
        if use_native_multimodal and selected_native_sources:
            payload = native_multimodal_search.chat(
                question_text,
                knowledge_source_names=selected_native_sources,
            )
        elif requested_retrieval_mode in {"full_text", "vector", "hybrid"}:
            payload = adapter.direct_search(
                question_text,
                retrieval_mode=requested_retrieval_mode,
                doc_ids=selected_doc_ids or None,
                doc_source_assignments=doc_source_assignments,
                scoring_profile=(request.scoring_profile or "default"),
            )
        else:
            if requested_retrieval_mode == "native_multimodal" and not selected_native_sources:
                raise HTTPException(
                    status_code=400,
                    detail="Native Blob multimodal retrieval was requested, but no selected corpus is provisioned for that mode yet.",
                )
            payload = adapter.chat(
                question_text,
                doc_ids=selected_doc_ids or None,
                doc_source_assignments=doc_source_assignments,
            )
        return synthesize_grounded_chat(question_text, payload)

    if isinstance(adapter, LocalPreviewAdapter):
        chunks = []
        from backend.domain.models import ChunkRecord

        for job in jobs:
            payload = json.loads(Path(job.chunks_path).read_text(encoding="utf-8"))
            chunks.extend(ChunkRecord.model_validate(item) for item in payload)
        response = local_preview_chat(request.question, chunks, doc_ids=selected_doc_ids or None)
        response.diagnostics["corpus_mode"] = request.corpus_mode
        response.diagnostics["selected_doc_ids"] = selected_doc_ids
        response.diagnostics["selected_corpora"] = [
            {"doc_id": job.doc_id, "file_name": job.file_name}
            for job in jobs
            if not selected_doc_ids or job.doc_id in selected_doc_ids
        ]
        return response

    try:
        proactive_rescue = None
        if request.corpus_mode == "custom" or len(active_jobs) == 1:
            proactive_rescue = build_query_rescue(
                request.question,
                [job.doc_id for job in active_jobs],
                jobs=active_jobs,
            )

        effective_question = (
            proactive_rescue["effective_question"] if proactive_rescue else request.question
        )
        response = _run_grounded_chat(effective_question)
        if proactive_rescue:
            response.diagnostics.update(
                {
                    "query_rescue_applied": True,
                    "original_question": proactive_rescue["original_question"],
                    "effective_question": proactive_rescue["effective_question"],
                    "query_corrections": proactive_rescue["corrections"],
                }
            )

        rescue_plan = None
        if not proactive_rescue and response_needs_query_rescue(response):
            rescue_plan = build_query_rescue(
                request.question,
                [job.doc_id for job in active_jobs],
                jobs=active_jobs,
            )
            if rescue_plan:
                rescued_response = _run_grounded_chat(rescue_plan["effective_question"])
                if rescued_response.citations or not response_needs_query_rescue(rescued_response):
                    response = rescued_response
                    response.diagnostics.update(
                        {
                            "query_rescue_applied": True,
                            "original_question": rescue_plan["original_question"],
                            "effective_question": rescue_plan["effective_question"],
                            "query_corrections": rescue_plan["corrections"],
                        }
                    )
                else:
                    response.diagnostics.update(
                        {
                            "query_rescue_attempted": True,
                            "original_question": rescue_plan["original_question"],
                            "effective_question": rescue_plan["effective_question"],
                            "query_corrections": rescue_plan["corrections"],
                        }
                    )
        response.diagnostics["corpus_mode"] = request.corpus_mode
        response.diagnostics["selected_doc_ids"] = selected_doc_ids
        response.diagnostics["retrieval_mode"] = (
            "native_multimodal"
            if use_native_multimodal and selected_native_sources
            else requested_retrieval_mode
        )
        response.diagnostics["selected_native_knowledge_sources"] = selected_native_sources
        response.diagnostics["selected_corpora"] = [
            {"doc_id": job.doc_id, "file_name": job.file_name}
            for job in jobs
            if not selected_doc_ids or job.doc_id in selected_doc_ids
        ]
        return response
    except Exception as exc:  # pragma: no cover - API safety
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/")
def root() -> FileResponse:
    return FileResponse(static_dir / "index.html")
