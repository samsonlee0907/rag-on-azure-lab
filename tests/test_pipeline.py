from __future__ import annotations

import unittest

from backend.domain.models import ChunkRecord, IntermediateDocument, JobRecord
from backend.services.pipeline import IngestionPipeline
from backend.services.search_skillset_enrichment import SearchSkillsetEnrichmentSnapshot


class PipelineMessageCleanupTests(unittest.TestCase):
    def test_completed_search_enrichment_clears_historical_failure_messages(self) -> None:
        pipeline = IngestionPipeline()
        job = JobRecord(
            doc_id="doc-1",
            file_name="report.pdf",
            stored_path="C:/temp/report.pdf",
            warnings=[
                "Blob-backed Search enrichment failed: old failure",
                "keep-this-warning",
            ],
            errors=[
                "Azure AI Search Blob + skillset enrichment did not complete successfully. old failure",
                "keep-this-error",
            ],
        )
        snapshot = SearchSkillsetEnrichmentSnapshot(
            status="completed",
            message="Blob-backed Search enrichment completed.",
            blob_upload={"blob_url": "https://storage.example/doc.pdf", "blob_name": "workshop/doc-1/report.pdf"},
            search_objects={},
            extracted_fields={},
            diagnostics={},
        )

        pipeline._store_search_enrichment_status(job, snapshot)

        self.assertEqual(job.warnings, ["keep-this-warning"])
        self.assertEqual(job.errors, ["keep-this-error"])

    def test_chunk_enrichment_does_not_attach_figures_for_broad_page_ranges(self) -> None:
        pipeline = IngestionPipeline()
        intermediate = IntermediateDocument(
            doc_id="doc-1",
            source_name="report.pdf",
            source_path="C:/temp/report.pdf",
            format="pdf",
            complexity="complex",
            parser_path="azure_document_intelligence",
            page_count=40,
            metadata={
                "figure_artifacts": [
                    {"artifact_id": "fig-1", "page_number": 1, "description": "Cover image."},
                    {"artifact_id": "fig-2", "page_number": 2, "description": "Map diagram."},
                ]
            },
        )
        broad_chunk = ChunkRecord(
            chunk_id="chunk-broad",
            doc_id="doc-1",
            source_name="report.pdf",
            checksum="broad",
            clean_text="General overview of the report.",
            token_estimate=12,
            page_numbers=list(range(1, 30)),
        )
        focused_chunk = ChunkRecord(
            chunk_id="chunk-focused",
            doc_id="doc-1",
            source_name="report.pdf",
            checksum="focused",
            clean_text="Diagram discussion on page 2.",
            token_estimate=12,
            page_numbers=[2],
        )

        chunks = pipeline._enrich_chunks(intermediate, [broad_chunk, focused_chunk])

        self.assertEqual(chunks[0].image_evidence, [])
        self.assertEqual(len(chunks[1].image_evidence), 1)
        self.assertEqual(chunks[1].image_evidence[0]["artifact_id"], "fig-2")


class ActiveSkillProfilePinningTests(unittest.TestCase):
    def test_context_manager_pins_and_restores_global_profile(self) -> None:
        from backend.core.config import settings
        from backend.services.pipeline import _active_skill_profile

        previous = settings.workshop_skill_profile
        try:
            settings.workshop_skill_profile = "baseline_extract"
            with _active_skill_profile("visual_nlp"):
                self.assertEqual(settings.workshop_skill_profile, "visual_nlp")
            self.assertEqual(settings.workshop_skill_profile, "baseline_extract")
        finally:
            settings.workshop_skill_profile = previous

    def test_context_manager_restores_global_on_error(self) -> None:
        from backend.core.config import settings
        from backend.services.pipeline import _active_skill_profile

        previous = settings.workshop_skill_profile
        try:
            settings.workshop_skill_profile = "baseline_extract"
            with self.assertRaises(RuntimeError):
                with _active_skill_profile("chunk_vector"):
                    self.assertEqual(settings.workshop_skill_profile, "chunk_vector")
                    raise RuntimeError("boom")
            self.assertEqual(settings.workshop_skill_profile, "baseline_extract")
        finally:
            settings.workshop_skill_profile = previous

    def test_empty_profile_id_leaves_global_unchanged(self) -> None:
        from backend.core.config import settings
        from backend.services.pipeline import _active_skill_profile

        previous = settings.workshop_skill_profile
        try:
            settings.workshop_skill_profile = "genai_enrichment"
            with _active_skill_profile(None):
                self.assertEqual(settings.workshop_skill_profile, "genai_enrichment")
            self.assertEqual(settings.workshop_skill_profile, "genai_enrichment")
        finally:
            settings.workshop_skill_profile = previous

    def test_run_pins_job_profile_for_duration(self) -> None:
        from backend.core.config import settings
        from backend.services.job_store import job_store

        pipeline = IngestionPipeline()
        job = JobRecord(
            doc_id="doc-pin",
            file_name="report.pdf",
            stored_path="C:/temp/report.pdf",
            skill_profile_id="visual_nlp",
        )

        previous = settings.workshop_skill_profile
        observed: list[str] = []
        original_get = job_store.get
        try:
            settings.workshop_skill_profile = "baseline_extract"
            job_store.get = lambda doc_id: job  # type: ignore[assignment]
            pipeline._run_job = lambda doc_id: observed.append(settings.workshop_skill_profile)  # type: ignore[assignment]

            pipeline.run("doc-pin")

            self.assertEqual(observed, ["visual_nlp"])
            self.assertEqual(settings.workshop_skill_profile, "baseline_extract")
        finally:
            job_store.get = original_get  # type: ignore[assignment]
            settings.workshop_skill_profile = previous


if __name__ == "__main__":
    unittest.main()

