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
            blob_upload={"blob_url": "https://storage.example/doc.pdf", "blob_name": "v2/doc-1/report.pdf"},
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


if __name__ == "__main__":
    unittest.main()
