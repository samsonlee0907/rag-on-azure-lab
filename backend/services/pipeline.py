from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from fastapi import BackgroundTasks, UploadFile

from backend.core.config import settings
from backend.domain.models import ChunkRecord, IntermediateDocument, JobRecord, JobStatus, PipelineMessage, Stage
from backend.services.chunking import ChunkPolicy, StructureAwareChunker
from backend.services.indexing import build_foundry_adapter
from backend.services.job_store import job_store
from backend.services.native_multimodal_search import NativeMultimodalSnapshot, native_multimodal_search
from backend.services.normalization import normalize_document
from backend.services.parsers import parser_registry
from backend.services.search_skillset_enrichment import SearchSkillsetEnrichmentSnapshot, blob_skillset_enrichment

logger = logging.getLogger(__name__)
MAX_DIRECT_CHUNK_IMAGE_PAGE_SPAN = 12


class IngestionPipeline:
    def __init__(self) -> None:
        self.chunker = StructureAwareChunker(
            ChunkPolicy(
                chunk_size_tokens=settings.chunk_size_tokens,
                overlap_tokens=settings.chunk_overlap_tokens,
                semantic_mode=settings.use_semantic_chunking,
            )
        )

    async def create_job(
        self,
        file: UploadFile,
        background_tasks: BackgroundTasks,
        *,
        ingestion_mode: str | None = None,
    ) -> JobRecord:
        file_name = file.filename or "upload.bin"
        temp_record = JobRecord(file_name=file_name, stored_path="")
        stored_path = settings.uploads_dir / f"{temp_record.doc_id}_{file_name}"
        with stored_path.open("wb") as handle:
            shutil.copyfileobj(file.file, handle)

        return self.create_job_from_path(
            stored_path,
            background_tasks,
            doc_id=temp_record.doc_id,
            file_name=file_name,
            activity_message="File uploaded and queued for ingestion.",
            ingestion_mode=ingestion_mode,
            source_kind="upload",
        )

    def create_job_from_path(
        self,
        path: Path,
        background_tasks: BackgroundTasks,
        *,
        doc_id: str | None = None,
        file_name: str | None = None,
        activity_message: str = "Document queued for ingestion.",
        ingestion_mode: str | None = None,
        source_kind: str = "upload",
    ) -> JobRecord:
        resolved_file_name = file_name or path.name
        temp_record = JobRecord(file_name=resolved_file_name, stored_path="")
        resolved_doc_id = doc_id or temp_record.doc_id
        resolved_ingestion_mode = self._normalize_ingestion_mode(ingestion_mode)
        profile = parser_registry.detect(path)
        job = JobRecord(
            doc_id=resolved_doc_id,
            file_name=resolved_file_name,
            stored_path=str(path),
            format=profile.format,
            complexity=profile.complexity,
            page_count=profile.page_count,
            parser_path=profile.parser_path,
            warnings=profile.warnings,
            activity=[],
            status=JobStatus.queued,
            progress=5,
            stage=Stage.uploaded,
            ingestion_mode=resolved_ingestion_mode,
            source_kind=source_kind,
        )
        job.activity.append(
            PipelineMessage(
                timestamp=job.created_at,
                level="info",
                message=f"{activity_message} Ingestion mode: {resolved_ingestion_mode}.",
            )
        )
        job_store.upsert(job)
        background_tasks.add_task(self.run, job.doc_id)
        return job

    def retry(self, doc_id: str, background_tasks: BackgroundTasks) -> JobRecord:
        job = job_store.get(doc_id)

        def mutate(current: JobRecord) -> None:
            current.status = JobStatus.queued
            current.stage = Stage.uploaded
            current.progress = 5
            current.warnings = []
            current.errors = []
            current.activity.append(
                PipelineMessage(timestamp=current.updated_at, level="info", message="Retry requested.")
            )

        updated = job_store.mutate(doc_id, mutate)
        background_tasks.add_task(self.run, job.doc_id)
        return updated

    def run(self, doc_id: str) -> None:
        try:
            job = job_store.get(doc_id)
            path = Path(job.stored_path)

            job_store.mark_stage(doc_id, Stage.parsing, 15, "Selecting parser path and validating document.")
            profile = parser_registry.detect(path)
            intermediate = parser_registry.parse(path, doc_id, profile)
            job_store.mark_stage(
                doc_id,
                Stage.extraction,
                30,
                f"Extraction completed via {intermediate.parser_path}.",
                parser_path=intermediate.parser_path,
            )

            intermediate = normalize_document(intermediate)
            job_store.mark_stage(
                doc_id,
                Stage.cleanup,
                45,
                "Normalized document structure and stitched cross-segment boundaries where needed.",
            )

            chunks = self.chunker.chunk(intermediate)
            job_store.mark_stage(
                doc_id,
                Stage.chunking,
                60,
                f"Generated {len(chunks)} retrieval-friendly chunks.",
            )

            enrichment_snapshot: SearchSkillsetEnrichmentSnapshot | None = None
            native_snapshot: NativeMultimodalSnapshot | None = None
            if job.ingestion_mode == "hybrid_blob_skillset":
                job_store.mark_stage(
                    doc_id,
                    Stage.enrichment,
                    68,
                    "Uploading the source file to Azure Blob and running Azure AI Search skillset enrichment.",
                )
                enrichment_snapshot = blob_skillset_enrichment.enrich_document(
                    path=path,
                    doc_id=doc_id,
                    source_name=intermediate.source_name,
                    intermediate=intermediate,
                    chunks=chunks,
                )
                job_store.mutate(
                    doc_id,
                    lambda current: self._store_search_enrichment_status(current, enrichment_snapshot),
                )
                if (
                    settings.azure_search_require_blob_skillset_success
                    and enrichment_snapshot.status != "completed"
                ):
                    raise RuntimeError(
                        "Azure AI Search Blob + skillset enrichment did not complete successfully. "
                        f"Status: {enrichment_snapshot.status}. {enrichment_snapshot.message}"
                    )
                native_snapshot = native_multimodal_search.ensure_document_source(
                    doc_id=doc_id,
                    source_name=intermediate.source_name,
                    blob_upload=enrichment_snapshot.blob_upload,
                )
                job_store.mutate(
                    doc_id,
                    lambda current: self._store_native_multimodal_status(current, native_snapshot),
                )
                if (
                    settings.azure_search_require_native_multimodal_success
                    and native_snapshot.status != "completed"
                ):
                    raise RuntimeError(
                        "Azure AI Search native Blob multimodal provisioning did not complete successfully. "
                        f"Status: {native_snapshot.status}. {native_snapshot.message}"
                    )

            enriched_chunks = self._enrich_chunks(intermediate, chunks)
            job_store.mark_stage(
                doc_id,
                Stage.enrichment,
                72,
                self._enrichment_stage_message(enrichment_snapshot, native_snapshot),
            )
            job_store.mark_stage(doc_id, Stage.embedding, 82, "Prepared chunks for Azure AI Search publishing.")

            intermediate_path = settings.artifacts_dir / f"{doc_id}_intermediate.json"
            chunks_path = settings.artifacts_dir / f"{doc_id}_chunks.json"
            intermediate_path.write_text(intermediate.model_dump_json(indent=2), encoding="utf-8")
            chunks_path.write_text(
                json.dumps([chunk.model_dump(mode="json") for chunk in enriched_chunks], indent=2),
                encoding="utf-8",
            )
            job_store.mutate(
                doc_id,
                lambda current: self._store_artifact_metadata(
                    current,
                    intermediate,
                    enriched_chunks,
                    intermediate_path,
                    chunks_path,
                ),
            )

            adapter = build_foundry_adapter()
            section_headings = [section.heading for section in intermediate.sections[:12] if section.heading]
            publish_status = adapter.publish(
                enriched_chunks,
                source_name=intermediate.source_name,
                route_text=" ".join(section_headings),
            )
            job_store.update_publish_status(doc_id, publish_status)
            job_store.mark_stage(doc_id, Stage.publishing, 92, publish_status.message)

            job_store.mark_stage(doc_id, Stage.ready, 100, "Document is ready for chat.")
        except Exception as exc:  # pragma: no cover - production behavior
            logger.exception("pipeline failed", extra={"context": {"doc_id": doc_id}})

            def mutate(current: JobRecord) -> None:
                current.status = JobStatus.failed
                current.stage = Stage.failed
                current.errors.append(str(exc))
                current.activity.append(
                    PipelineMessage(timestamp=current.updated_at, level="error", message=str(exc))
                )

            job_store.mutate(doc_id, mutate)

    def _enrich_chunks(self, intermediate: IntermediateDocument, chunks: list[ChunkRecord]) -> list[ChunkRecord]:
        figure_artifacts = intermediate.metadata.get("figure_artifacts") or []
        for chunk in chunks:
            if intermediate.page_count and not chunk.page_numbers:
                chunk.page_numbers = [1]
            if intermediate.metadata:
                chunk.tags.extend(
                    [value for value in [intermediate.metadata.get("model_id"), intermediate.metadata.get("analyzer_id")] if value]
                )
            if figure_artifacts:
                related_figures = []
                scoped_pages = sorted({page for page in chunk.page_numbers if isinstance(page, int) and page > 0})
                if scoped_pages and len(scoped_pages) <= MAX_DIRECT_CHUNK_IMAGE_PAGE_SPAN:
                    for figure in figure_artifacts:
                        if not isinstance(figure, dict):
                            continue
                        page_number = figure.get("page_number")
                        if page_number is None or page_number in scoped_pages:
                            related_figures.append(figure)
                chunk.image_evidence = related_figures[:4]
        return chunks

    def _normalize_ingestion_mode(self, ingestion_mode: str | None) -> str:
        allowed_modes = {"app_managed", "hybrid_blob_skillset"}
        normalized = str(ingestion_mode or settings.default_ingestion_mode).strip().lower()
        if normalized in allowed_modes:
            return normalized
        return settings.default_ingestion_mode

    def _store_search_enrichment_status(
        self,
        job: JobRecord,
        enrichment_snapshot: SearchSkillsetEnrichmentSnapshot,
    ) -> None:
        blob_upload = enrichment_snapshot.blob_upload or {}
        search_objects = enrichment_snapshot.search_objects or {}
        job.enrichment_status = {
            "mode": job.ingestion_mode,
            "blob_skillset": {
                "status": enrichment_snapshot.status,
                "message": enrichment_snapshot.message,
                "blob_upload": blob_upload,
                "search_objects": search_objects,
                "extracted_fields": enrichment_snapshot.extracted_fields,
                "diagnostics": enrichment_snapshot.diagnostics,
            },
        }
        blob_url = blob_upload.get("blob_url")
        blob_name = blob_upload.get("blob_name")
        if blob_url:
            job.external_source_uri = str(blob_url)
        if blob_name:
            job.external_source_path = str(blob_name)
        if enrichment_snapshot.status == "failed":
            if enrichment_snapshot.message not in job.warnings:
                job.warnings.append(enrichment_snapshot.message)
        elif enrichment_snapshot.status == "completed":
            self._clear_historical_enrichment_messages(job)

    def _store_native_multimodal_status(
        self,
        job: JobRecord,
        native_snapshot: NativeMultimodalSnapshot,
    ) -> None:
        current = dict(job.enrichment_status or {})
        current["native_multimodal"] = {
            "status": native_snapshot.status,
            "message": native_snapshot.message,
            "knowledge_source_name": native_snapshot.knowledge_source_name,
            "knowledge_base_name": native_snapshot.knowledge_base_name,
            "blob_folder_path": native_snapshot.blob_folder_path,
            "diagnostics": native_snapshot.diagnostics or {},
        }
        job.enrichment_status = current
        if native_snapshot.status == "failed" and native_snapshot.message not in job.warnings:
            job.warnings.append(native_snapshot.message)
        elif native_snapshot.status == "completed":
            self._clear_historical_enrichment_messages(job)

    def _enrichment_stage_message(
        self,
        enrichment_snapshot: SearchSkillsetEnrichmentSnapshot | None,
        native_snapshot: NativeMultimodalSnapshot | None,
    ) -> str:
        if enrichment_snapshot is None and native_snapshot is None:
            return "Chunk metadata enriched for filtering and citation."
        native_status = native_snapshot.status if native_snapshot else "not_run"
        if enrichment_snapshot.status == "completed":
            if native_status == "completed":
                return (
                    "Chunk metadata enriched with Azure AI Search Blob + skillset outputs, and a native Blob "
                    "multimodal knowledge source was prepared for image-serving retrieval."
                )
            return "Chunk metadata enriched with Azure AI Search Blob + skillset outputs, summaries, and retrieval hints."
        if enrichment_snapshot.status == "not_configured":
            if native_status == "completed":
                return (
                    "Chunk metadata enriched for filtering and citation. The native Blob multimodal knowledge "
                    "source is ready, but the Blob + skillset enrichment lane is not configured."
                )
            return (
                "Chunk metadata enrichment could not complete in Azure AI Search because the Blob + skillset "
                "lane is not configured."
            )
        return (
            "Azure AI Search enrichment reported an error. Review the Blob + skillset and native multimodal "
            "status details for the failing service-side path."
        )

    def _store_artifact_metadata(
        self,
        job: JobRecord,
        intermediate: IntermediateDocument,
        chunks: list[ChunkRecord],
        intermediate_path: Path,
        chunks_path: Path,
    ) -> None:
        job.format = intermediate.format
        job.complexity = intermediate.complexity
        job.page_count = intermediate.page_count
        job.parser_path = intermediate.parser_path
        job.section_count = len(intermediate.sections)
        job.chunk_count = len(chunks)
        job.intermediate_path = str(intermediate_path)
        job.chunks_path = str(chunks_path)
        if intermediate.source_uri:
            job.external_source_uri = intermediate.source_uri
        search_blob_status = intermediate.metadata.get("search_skillset_blob")
        if isinstance(search_blob_status, dict):
            blob_upload = search_blob_status.get("blob_upload") or {}
            if isinstance(blob_upload, dict) and blob_upload.get("blob_name"):
                job.external_source_path = str(blob_upload["blob_name"])
        for warning in intermediate.warnings:
            if warning not in job.warnings:
                job.warnings.append(warning)

    def _clear_historical_enrichment_messages(self, job: JobRecord) -> None:
        transient_prefixes = (
            "Blob-backed Search enrichment failed:",
            "Azure AI Search Blob + skillset enrichment did not complete successfully.",
            "Previous retry was interrupted while applying a search-enrichment hotfix.",
            "Azure AI Search native Blob multimodal provisioning did not complete successfully.",
        )
        job.warnings = [warning for warning in job.warnings if not warning.startswith(transient_prefixes)]
        job.errors = [error for error in job.errors if not error.startswith(transient_prefixes)]


pipeline = IngestionPipeline()
