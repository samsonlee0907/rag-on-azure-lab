from __future__ import annotations

import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

from backend.domain.models import ChunkRecord
from backend.services.indexing import (
    AzureSearchKnowledgeBaseAdapter,
    _direct_result_rank,
    _extract_best_snippet,
    _extract_navigation_snippet,
)


class DirectSearchBodyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = AzureSearchKnowledgeBaseAdapter()

    def test_build_full_text_body_uses_search_without_vector_queries(self) -> None:
        body = self.adapter._build_direct_search_body(
            question="find the workflow",
            retrieval_mode="full_text",
            filter_expression="doc_id eq 'abc'",
            query_vector=None,
        )

        self.assertEqual(body["search"], "find the workflow")
        self.assertEqual(body["filter"], "doc_id eq 'abc'")
        self.assertNotIn("vectorQueries", body)
        self.assertNotIn("captions", body)
        self.assertNotIn("queryType", body)

    def test_build_vector_body_uses_star_and_vector_queries(self) -> None:
        body = self.adapter._build_direct_search_body(
            question="find the workflow",
            retrieval_mode="vector",
            filter_expression="",
            query_vector=[0.1, 0.2, 0.3],
        )

        self.assertEqual(body["search"], "*")
        self.assertEqual(body["vectorQueries"][0]["kind"], "vector")
        self.assertEqual(body["vectorQueries"][0]["vector"], [0.1, 0.2, 0.3])
        self.assertNotIn("captions", body)

    def test_build_hybrid_body_uses_search_and_vector_queries(self) -> None:
        body = self.adapter._build_direct_search_body(
            question="find the workflow",
            retrieval_mode="hybrid",
            filter_expression="",
            query_vector=[0.1, 0.2, 0.3],
        )

        self.assertEqual(body["search"], "find the workflow")
        self.assertEqual(body["vectorQueries"][0]["kind"], "vector")
        self.assertEqual(body["vectorQueries"][0]["vector"], [0.1, 0.2, 0.3])
        self.assertEqual(body["captions"], "extractive|highlight-false")
        self.assertEqual(body["queryType"], "semantic")

    def test_full_text_body_attaches_named_scoring_profile(self) -> None:
        body = self.adapter._build_direct_search_body(
            question="find the workflow",
            retrieval_mode="full_text",
            filter_expression="",
            query_vector=None,
            scoring_profile="enrichment-weighted",
        )

        self.assertEqual(body["scoringProfile"], "enrichment-weighted")

    def test_hybrid_body_attaches_named_scoring_profile(self) -> None:
        body = self.adapter._build_direct_search_body(
            question="find the workflow",
            retrieval_mode="hybrid",
            filter_expression="",
            query_vector=[0.1, 0.2, 0.3],
            scoring_profile="freshness-boosted",
        )

        self.assertEqual(body["scoringProfile"], "freshness-boosted")

    def test_default_scoring_profile_is_omitted(self) -> None:
        body = self.adapter._build_direct_search_body(
            question="find the workflow",
            retrieval_mode="hybrid",
            filter_expression="",
            query_vector=[0.1, 0.2, 0.3],
            scoring_profile="default",
        )

        self.assertNotIn("scoringProfile", body)

    def test_vector_mode_ignores_scoring_profile(self) -> None:
        body = self.adapter._build_direct_search_body(
            question="find the workflow",
            retrieval_mode="vector",
            filter_expression="",
            query_vector=[0.1, 0.2, 0.3],
            scoring_profile="enrichment-weighted",
        )

        self.assertNotIn("scoringProfile", body)

    def test_unknown_scoring_profile_is_omitted(self) -> None:
        body = self.adapter._build_direct_search_body(
            question="find the workflow",
            retrieval_mode="full_text",
            filter_expression="",
            query_vector=None,
            scoring_profile="not-a-real-profile",
        )

        self.assertNotIn("scoringProfile", body)

    def test_default_content_filter_excludes_navigation_for_normal_questions(self) -> None:
        filter_expression = self.adapter._default_content_filter("What three groups can suspended ceilings be placed in?")

        self.assertIn("content_type ne 'table_of_contents'", filter_expression)
        self.assertIn("content_type ne 'figure_catalog'", filter_expression)
        self.assertIn("content_type ne 'diagram_labels'", filter_expression)

    def test_default_content_filter_keeps_navigation_for_contents_questions(self) -> None:
        filter_expression = self.adapter._default_content_filter("Which chapter or page covers suspended ceilings?")

        self.assertNotIn("table_of_contents", filter_expression)

    def test_default_content_filter_keeps_visual_chunks_for_diagram_questions(self) -> None:
        filter_expression = self.adapter._default_content_filter("Show me the plan labels for the roof drainage diagram.")

        self.assertNotIn("figure_catalog", filter_expression)
        self.assertNotIn("diagram_labels", filter_expression)

    def test_vector_indexing_disabled_for_baseline_profile(self) -> None:
        with (
            patch("backend.services.indexing.settings.workshop_skill_profile", "baseline_extract"),
            patch("backend.services.indexing.settings.azure_openai_embedding_deployment", "text-embedding-3-large"),
            patch("backend.services.indexing.settings.azure_foundry_resource_endpoint", "https://example.cognitiveservices.azure.com/"),
        ):
            self.assertFalse(self.adapter._vector_indexing_enabled())

    def test_embed_chunks_retries_on_rate_limit(self) -> None:
        chunk = ChunkRecord(
            chunk_id="chunk-1",
            doc_id="doc-1",
            source_name="report.pdf",
            checksum="abc",
            clean_text="Chunk body",
            token_estimate=12,
        )

        with (
            patch(
                "backend.services.indexing.embed_texts_with_foundry",
                side_effect=[
                    RuntimeError("429 Too Many Requests from Embedding model: retry after 2 seconds"),
                    ([[0.1, 0.2, 0.3]], "https://example.openai.azure.com/openai/v1/embeddings"),
                ],
            ) as embed_mock,
            patch("backend.services.indexing.sleep") as sleep_mock,
        ):
            embeddings = self.adapter._embed_chunks_for_index([chunk])

        self.assertEqual(embed_mock.call_count, 2)
        sleep_mock.assert_called_once_with(2)
        self.assertEqual(embeddings["chunk-1"], [0.1, 0.2, 0.3])

    def test_upload_chunks_batches_large_documents(self) -> None:
        adapter = AzureSearchKnowledgeBaseAdapter()
        chunks = [
            ChunkRecord(
                chunk_id=f"chunk-{index}",
                doc_id="doc-1",
                source_name="report.pdf",
                checksum=f"checksum-{index}",
                clean_text=("Chunk body " * 600) + str(index),
                token_estimate=200,
            )
            for index in range(160)
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = ""
        mock_response.elapsed = None

        with patch("backend.services.indexing.requests.post", return_value=mock_response) as post_mock:
            adapter._upload_chunks(chunks, index_name="ai-search-lab-index")

        self.assertGreaterEqual(post_mock.call_count, 2)

    def test_extract_best_snippet_preserves_three_group_list(self) -> None:
        text = (
            "Classification of Suspended Ceiling ~ there is no standard method of classification. "
            "The latter method is simple since most suspended ceiling types can be placed in one of three groups :- "
            "1. Jointless suspended ceilings. 2. Panelled suspended ceilings - see page 632. "
            "3. Decorative and open suspended ceilings - see page 633. "
            "Jointless Suspended Ceilings ~ these forms provide a continuous surface."
        )

        snippet = _extract_best_snippet(text, "What three groups can suspended ceilings be placed in?")

        self.assertIn("Jointless suspended ceilings", snippet)
        self.assertIn("Panelled suspended ceilings", snippet)
        self.assertIn("Decorative and open suspended ceilings", snippet)
        self.assertNotIn("Jointless Suspended Ceilings ~ these forms", snippet)

    def test_extract_best_snippet_chooses_components_list_over_previous_numbered_list(self) -> None:
        text = (
            "Functions ~ the main functions of paint are to provide :- "
            "1. Surface protection. 2. Surface decoration. "
            "Composition ~ the actual composition of any paint can be complex but the basic components are :- "
            "1. Binder ~ liquid vehicle. 2. Pigment ~ body and colour. "
            "3. Solvents and Thinners ~ alter viscosity."
        )

        snippet = _extract_best_snippet(text, "What are the basic components of paint?")

        self.assertIn("basic components", snippet.lower())
        self.assertIn("1. Binder", snippet)
        self.assertIn("2. Pigment", snippet)
        self.assertIn("3. Solvents and Thinners", snippet)
        self.assertNotIn("Surface protection", snippet)

    def test_direct_result_rank_prefers_semantic_reranker_score(self) -> None:
        weaker_text_match = {"@search.score": 14.0, "@search.rerankerScore": 1.8}
        better_semantic_match = {"@search.score": 9.0, "@search.rerankerScore": 3.1}

        ordered = sorted([weaker_text_match, better_semantic_match], key=_direct_result_rank, reverse=True)

        self.assertIs(ordered[0], better_semantic_match)

    def test_extract_navigation_snippet_picks_matching_contents_entry(self) -> None:
        text = (
            "Internal walls 546 Construction joints 551 Partitions 552 Plasters and plastering 557 "
            "Dry lining techniques 559 Wall tiling 563 Domestic floors and finishes 565 "
            "Suspended ceilings 630 Paints and painting 633 Joinery production 647"
        )

        snippet = _extract_navigation_snippet(text, "Which page covers paints and painting?")

        self.assertEqual(snippet, "Paints and painting 633")


if __name__ == "__main__":
    unittest.main()
