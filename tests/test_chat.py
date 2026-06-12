from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.core.config import SearchKnowledgeSourceConfig
from backend.domain.models import ChatCitation, ChunkRecord
from backend.services.chat import (
    _extract_citations,
    build_chat_response,
    build_query_rescue,
    local_preview_chat,
    response_needs_query_rescue,
    synthesize_grounded_chat,
)
from backend.services.indexing import AzureSearchKnowledgeBaseAdapter


class ChatServiceTests(unittest.TestCase):
    def test_response_needs_query_rescue_for_empty_negative_answer(self) -> None:
        response = SimpleNamespace(answer="No relevant content was found for your query.", citations=[])

        self.assertTrue(response_needs_query_rescue(response))

    def test_build_query_rescue_corrects_obvious_corpus_term_typo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            chunks_path = Path(temp_dir) / "chunks.json"
            chunks_path.write_text(
                json.dumps(
                    [
                        {
                            "chunk_id": "chunk-1",
                            "doc_id": "doc-earth",
                            "source_name": "earth_at_night_508.pdf",
                            "checksum": "abc",
                            "clean_text": "National Aeronautics and Space Administration NASA Earth at Night. Some nauts appear in OCR noise.",
                            "summary_text": "NASA publication Earth at Night.",
                            "keyword_hints": ["NASA publication", "Earth at Night"],
                            "token_estimate": 10,
                        }
                    ]
                ),
                encoding="utf-8",
            )
            job = SimpleNamespace(
                doc_id="doc-earth",
                status="ready",
                file_name="earth_at_night_508.pdf",
                chunks_path=str(chunks_path),
            )

            rescue = build_query_rescue(
                "What does Nasus mention about Earth?",
                ["doc-earth"],
                jobs=[job],
            )

        self.assertIsNotNone(rescue)
        self.assertEqual(rescue["effective_question"], "What does NASA mention about Earth?")
        self.assertEqual(rescue["corrections"], [{"from": "Nasus", "to": "NASA"}])

    def test_extracts_citations_from_activity_references(self) -> None:
        payload = {
            "activity": [
                {
                    "references": [
                        {
                            "title": "Future of AI",
                            "sourceUri": "https://contoso.example/docs/future",
                            "chunkId": "chunk-001",
                            "doc_id": "doc-123",
                            "page_numbers": [9],
                            "image_evidence_json": '[{"artifact_id":"fig-1","description":"Adoption curve"}]',
                            "content": "Generative AI is becoming a general-purpose capability.",
                        }
                    ]
                }
            ]
        }

        citations = _extract_citations(payload)

        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0].title, "Future of AI")
        self.assertEqual(citations[0].chunk_id, "chunk-001")
        self.assertEqual(citations[0].doc_id, "doc-123")
        self.assertEqual(citations[0].page_numbers, [9])
        self.assertEqual(citations[0].image_evidence[0]["artifact_id"], "fig-1")

    def test_build_chat_response_extracts_subqueries(self) -> None:
        payload = {
            "activity": [
                {
                    "type": "searchIndex",
                    "id": 0,
                    "knowledgeSourceName": "enterprise-knowledge-source",
                    "count": 7,
                    "elapsedMs": 123,
                    "searchIndexArguments": {"search": "future of generative AI energy demand"},
                }
            ],
            "answer": "placeholder",
        }

        response = build_chat_response(payload)

        self.assertEqual(response.diagnostics["subqueries"][0]["search"], "future of generative AI energy demand")

    def test_build_chat_response_adds_humanized_subquery_display(self) -> None:
        payload = {
            "activity": [
                {
                    "type": "searchIndex",
                    "id": 0,
                    "knowledgeSourceName": "enterprise-knowledge-source",
                    "count": 7,
                    "elapsedMs": 123,
                    "searchIndexArguments": {
                        "search": "How does NASA define light academic definition NASA definition of light site:nasa.gov"
                    },
                }
            ],
            "answer": "placeholder",
        }

        response = build_chat_response(payload)

        self.assertEqual(
            response.diagnostics["subqueries"][0]["display_search"],
            "Find definitions or explanations about NASA and light",
        )

    def test_build_chat_response_parses_top_level_native_references_and_rewrites_ref_ids(self) -> None:
        payload = {
            "response": [
                {
                    "content": [
                        {
                            "type": "text",
                            "text": "The architecture diagram shows the Blob to Search flow. [ref_id:0]",
                        }
                    ]
                }
            ],
            "activity": [
                {
                    "type": "azureBlob",
                    "id": 1,
                    "knowledgeSourceName": "native-blob-source",
                    "count": 1,
                    "elapsedMs": 42,
                    "azureBlobArguments": {"search": "diagram architecture"},
                }
            ],
            "references": [
                {
                    "type": "azureBlob",
                    "id": "0",
                    "activitySource": 1,
                    "sourceData": {
                        "blob_url": "https://contoso.blob.core.windows.net/documents/sample.pdf",
                        "snippet": "Source docs -> Blob -> Search skillset -> knowledge base",
                        "image_path": "asset-one.jpg;asset-two.jpg",
                    },
                }
            ],
        }

        response = build_chat_response(payload)

        self.assertEqual(response.answer, "The architecture diagram shows the Blob to Search flow. [1]")
        self.assertEqual(len(response.citations), 1)
        self.assertEqual(response.citations[0].knowledge_source, "native-blob-source")
        self.assertEqual(response.citations[0].asset_image_paths, ["asset-one.jpg", "asset-two.jpg"])
        self.assertEqual(response.citations[0].reference_id, 1)

    def test_build_chat_response_extracts_azure_blob_subqueries(self) -> None:
        payload = {
            "activity": [
                {
                    "type": "azureBlob",
                    "id": 3,
                    "knowledgeSourceName": "native-blob-source",
                    "count": 2,
                    "elapsedMs": 58,
                    "azureBlobArguments": {"search": "show me the blueprint diagram"},
                }
            ],
            "answer": "placeholder",
        }

        response = build_chat_response(payload)

        self.assertEqual(response.diagnostics["subqueries"][0]["activity_type"], "azureBlob")
        self.assertEqual(response.diagnostics["subqueries"][0]["search"], "show me the blueprint diagram")

    def test_extract_citations_clears_broad_irrelevant_image_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            intermediate_path = Path(temp_dir) / "intermediate.json"
            intermediate_path.write_text(
                json.dumps(
                    {
                        "metadata": {
                            "figure_artifacts": [
                                {
                                    "artifact_id": "cover-1",
                                    "page_number": 1,
                                    "description": "Cover image of Earth at night over the Western Hemisphere.",
                                },
                                {
                                    "artifact_id": "cover-2",
                                    "page_number": 2,
                                    "description": "Dark Earth limb image with stars.",
                                },
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            fake_job = SimpleNamespace(
                doc_id="doc-earth",
                file_name="earth_at_night_508.pdf",
                stored_path=str(Path(temp_dir) / "earth_at_night_508.pdf"),
                intermediate_path=str(intermediate_path),
                publish_status=SimpleNamespace(diagnostics={}),
                external_source_uri=None,
            )
            payload = {
                "citations": [
                    {
                        "title": "earth_at_night_508.pdf",
                        "doc_id": "doc-earth",
                        "snippet": "NASA defines light as electromagnetic radiation that can be detected by the human eye.",
                        "page_numbers": list(range(1, 40)),
                        "image_evidence_json": '[{"artifact_id":"cover-1","page_number":1,"description":"Cover image of Earth at night."}]',
                    }
                ]
            }

            with patch(
                "backend.services.chat._job_lookup",
                return_value=([fake_job], {"doc-earth": fake_job}, {"earth_at_night_508.pdf": fake_job}, {}),
            ):
                citations = _extract_citations(payload)

        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0].image_evidence, [])

    @patch("backend.services.chat._search_supporting_chunks")
    def test_extract_citations_supplements_missing_positive_source_from_activity(self, mock_supporting_chunks) -> None:
        mock_supporting_chunks.return_value = [
            ChatCitation(
                title="Energy report",
                doc_id="doc-energy",
                chunk_id="energy-chunk-1",
                snippet="Power availability is now an early project dependency.",
                knowledge_source="energy-knowledge-source",
                index_name="energy-knowledge-index",
                evidence_kind="activity_support",
                supporting_query="energy supply impacts on project delivery",
                retrieval_step=2,
            )
        ]
        payload = {
            "citations": [
                {
                    "title": "Construction report",
                    "doc_id": "doc-construction",
                    "chunk_id": "construction-chunk-1",
                    "snippet": "Construction delivery is becoming more complex.",
                    "knowledgeSourceName": "enterprise-knowledge-source",
                    "index_name": "enterprise-knowledge-index",
                }
            ],
            "diagnostics": {
                "knowledge_source_index_map": {
                    "enterprise-knowledge-source": "enterprise-knowledge-index",
                    "energy-knowledge-source": "energy-knowledge-index",
                }
            },
            "activity": [
                {
                    "type": "searchIndex",
                    "knowledgeSourceName": "enterprise-knowledge-source",
                    "count": 10,
                    "elapsedMs": 100,
                    "searchIndexArguments": {"search": "construction delivery complexity"},
                },
                {
                    "type": "searchIndex",
                    "knowledgeSourceName": "energy-knowledge-source",
                    "count": 7,
                    "elapsedMs": 90,
                    "searchIndexArguments": {"search": "energy supply impacts on project delivery"},
                },
            ],
        }

        citations = _extract_citations(payload)

        self.assertEqual(
            [citation.knowledge_source for citation in citations[:2]],
            ["enterprise-knowledge-source", "energy-knowledge-source"],
        )
        self.assertEqual(citations[1].supporting_query, "energy supply impacts on project delivery")
        self.assertEqual(citations[1].reference_id, 2)

    def test_extract_citations_prefers_richer_duplicate_metadata(self) -> None:
        payload = {
            "citations": [
                {
                    "title": "Construction report",
                    "snippet": "Project teams need stronger document control because permitting packs move faster than manual coordination can absorb.",
                },
                {
                    "title": "Construction report enriched",
                    "doc_id": "doc-construction",
                    "chunk_id": "chunk-42",
                    "snippet": "Project teams need stronger document control because permitting packs move faster than manual coordination can absorb.",
                    "knowledgeSourceName": "enterprise-knowledge-source",
                    "index_name": "enterprise-knowledge-index",
                },
            ]
        }

        citations = _extract_citations(payload)

        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0].chunk_id, "chunk-42")
        self.assertEqual(citations[0].knowledge_source, "enterprise-knowledge-source")

    @patch("backend.services.chat.settings.azure_foundry_chat_deployment", new="gpt-5-4")
    @patch("backend.services.chat.settings.azure_foundry_resource_endpoint", new="https://example.cognitiveservices.azure.com/")
    @patch("backend.services.chat.settings.azure_search_enable_answer_synthesis", new=False)
    @patch("backend.services.chat.call_foundry_text")
    def test_synthesizes_grounded_answer_with_gpt(self, mock_completion) -> None:
        retrieval_payload = {
            "activity": [
                {
                    "references": [
                        {
                            "title": "Future of AI",
                            "sourceUri": "https://contoso.example/docs/future",
                            "chunkId": "chunk-001",
                            "content": "Generative AI is becoming a general-purpose capability.",
                        }
                    ]
                }
            ]
        }

        mock_completion.return_value = (
            "Generative AI is becoming a general-purpose capability across industries. [1]",
            "https://example.openai.azure.com/openai/v1/chat/completions",
        )

        response = synthesize_grounded_chat("What is changing?", retrieval_payload)

        self.assertIn("[1]", response.answer)
        self.assertEqual(response.diagnostics["mode"], "search_plus_gpt54")
        self.assertEqual(response.diagnostics["model"], "gpt-5-4")
        self.assertEqual(len(response.citations), 1)

    @patch("backend.services.chat.settings.azure_search_enable_answer_synthesis", new=True)
    @patch("backend.services.chat.settings.azure_search_llm_deployment", new="gpt-5-mini")
    @patch("backend.services.chat.settings.azure_search_enable_image_serving", new=True)
    def test_synthesizes_grounded_answer_with_search_answer_synthesis_when_enabled(self) -> None:
        retrieval_payload = {
            "answer": {"text": "Search produced a grounded answer. [1]"},
            "diagnostics": {"agentic_retrieval": True},
            "activity": [
                {
                    "references": [
                        {
                            "title": "Blob-enriched report",
                            "chunkId": "chunk-001",
                            "content": "Blob skillset enrichment generated a summary.",
                        }
                    ]
                }
            ],
        }

        response = synthesize_grounded_chat("Summarize the corpus.", retrieval_payload)

        self.assertEqual(response.answer, "Search produced a grounded answer. [1]")
        self.assertEqual(response.diagnostics["mode"], "search_answer_synthesis")
        self.assertEqual(response.diagnostics["model"], "gpt-5-mini")
        self.assertTrue(response.diagnostics["image_serving_enabled"])

    def test_local_preview_chat_respects_selected_corpora(self) -> None:
        chunks = [
            ChunkRecord(
                chunk_id="chunk-1",
                doc_id="doc-a",
                source_name="A.pdf",
                checksum="a",
                clean_text="Labor shortages are a major issue in this report.",
                token_estimate=10,
            ),
            ChunkRecord(
                chunk_id="chunk-2",
                doc_id="doc-b",
                source_name="B.pdf",
                checksum="b",
                clean_text="Safety risk drives schedule pressure in this report.",
                token_estimate=10,
            ),
        ]

        response = local_preview_chat("labor shortages", chunks, doc_ids=["doc-a"])

        self.assertEqual(len(response.citations), 1)
        self.assertEqual(response.citations[0].doc_id, "doc-a")
        self.assertEqual(response.diagnostics["selected_doc_ids"], ["doc-a"])

    def test_build_doc_filter_escapes_values(self) -> None:
        adapter = AzureSearchKnowledgeBaseAdapter()

        result = adapter._build_doc_filter(["doc-a", "doc-b", "doc'a"])

        self.assertEqual(result, "doc_id eq 'doc-a' or doc_id eq 'doc-b' or doc_id eq 'doc''a'")

    @patch("backend.services.indexing.sleep", return_value=None)
    @patch("backend.services.indexing.requests.post")
    def test_standard_retrieve_retries_on_model_throttle(self, mock_post, _mock_sleep) -> None:
        adapter = AzureSearchKnowledgeBaseAdapter()
        throttled = SimpleNamespace(status_code=429, text="Too Many Requests")
        success = SimpleNamespace(status_code=200, text="{}", json=lambda: {})
        mock_post.side_effect = [throttled, success]

        with patch("backend.services.indexing.settings.azure_search_retrieve_retry_attempts", new=2), patch(
            "backend.services.indexing.settings.azure_search_retrieve_retry_base_delay_seconds", new=1
        ):
            response = adapter._post_retrieve_with_retry(url="https://example.test/retrieve", payload={"messages": []})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_post.call_count, 2)

    @patch(
        "backend.services.indexing.settings.azure_search_extra_sources",
        new=(
            SearchKnowledgeSourceConfig(
                knowledge_source_name="construction-source",
                index_name="construction-index",
                description="Construction safety schedules BIM delivery",
                route_keywords=("construction", "bim", "safety"),
            ),
            SearchKnowledgeSourceConfig(
                knowledge_source_name="energy-source",
                index_name="energy-index",
                description="Power demand grid transmission generation data centers",
                route_keywords=("power", "grid", "energy", "data center"),
            ),
        ),
    )
    @patch("backend.services.indexing.AzureSearchKnowledgeBaseAdapter._published_document_terms_for_source", return_value=set())
    def test_route_knowledge_sources_selects_keyword_matched_extra_index(self, _mock_terms) -> None:
        adapter = AzureSearchKnowledgeBaseAdapter()

        selected, diagnostics = adapter._route_knowledge_sources(
            "How does construction safety interact with BIM delivery risk?"
        )

        self.assertEqual(
            [source.knowledge_source_name for source in selected],
            ["construction-source"],
        )
        self.assertFalse(diagnostics["multi_index_routing"])
        self.assertEqual(diagnostics["routing_mode"], "keyword_routed")

    @patch(
        "backend.services.indexing.settings.azure_search_extra_sources",
        new=(
            SearchKnowledgeSourceConfig(
                knowledge_source_name="construction-source",
                index_name="construction-index",
                description="Construction safety schedules BIM delivery",
                route_keywords=("construction", "bim", "safety"),
            ),
            SearchKnowledgeSourceConfig(
                knowledge_source_name="energy-source",
                index_name="energy-index",
                description="Power demand grid transmission generation data centers",
                route_keywords=("power", "grid", "energy", "data center"),
            ),
        ),
    )
    def test_route_knowledge_sources_uses_all_indexes_for_cross_source_queries(self) -> None:
        adapter = AzureSearchKnowledgeBaseAdapter()

        selected, diagnostics = adapter._route_knowledge_sources(
            "Compare construction delivery risk with grid capacity constraints across the indexes."
        )

        self.assertEqual(
            [source.knowledge_source_name for source in selected],
            ["enterprise-knowledge-source", "construction-source", "energy-source"],
        )
        self.assertTrue(diagnostics["multi_index_routing"])
        self.assertEqual(diagnostics["routing_mode"], "cross_source_intent")

    @patch(
        "backend.services.indexing.settings.azure_search_extra_sources",
        new=(
            SearchKnowledgeSourceConfig(
                knowledge_source_name="construction-source",
                index_name="construction-index",
                description="Construction safety schedules BIM delivery",
                route_keywords=("construction",),
            ),
        ),
    )
    def test_custom_doc_scope_keeps_search_on_primary_index(self) -> None:
        adapter = AzureSearchKnowledgeBaseAdapter()

        selected, diagnostics = adapter._route_knowledge_sources(
            "Compare construction delivery risk with the uploaded corpus.",
            doc_ids=["doc-a"],
        )

        self.assertEqual([source.knowledge_source_name for source in selected], ["enterprise-knowledge-source"])
        self.assertFalse(diagnostics["multi_index_routing"])
        self.assertEqual(diagnostics["routing_mode"], "custom_doc_scope")

    @patch(
        "backend.services.indexing.settings.azure_search_extra_sources",
        new=(
            SearchKnowledgeSourceConfig(
                knowledge_source_name="construction-source",
                index_name="construction-index",
                description="Construction safety schedules BIM delivery",
                route_keywords=("construction",),
            ),
            SearchKnowledgeSourceConfig(
                knowledge_source_name="energy-source",
                index_name="energy-index",
                description="Power demand grid transmission generation data centers",
                route_keywords=("power",),
            ),
        ),
    )
    def test_knowledge_base_body_references_multiple_sources(self) -> None:
        adapter = AzureSearchKnowledgeBaseAdapter()

        body = adapter._knowledge_base_body()

        self.assertEqual(
            [item["name"] for item in body["knowledgeSources"]],
            ["enterprise-knowledge-source", "construction-source", "energy-source"],
        )

    @patch(
        "backend.services.indexing.settings.azure_search_extra_sources",
        new=(
            SearchKnowledgeSourceConfig(
                knowledge_source_name="energy-source",
                index_name="energy-index",
                description="Power systems electricity grid transmission interconnection load growth",
                route_keywords=("power", "grid", "energy"),
                assignment_keywords=("power", "electricity", "grid"),
            ),
        ),
    )
    def test_select_target_source_for_document_assigns_energy_index(self) -> None:
        adapter = AzureSearchKnowledgeBaseAdapter()

        target, diagnostics = adapter._select_target_source_for_document(
            source_name="power-system-transformation-report.pdf",
            route_text="Grid modernization load growth interconnection queues",
        )

        self.assertEqual(target.knowledge_source_name, "energy-source")
        self.assertEqual(target.index_name, "energy-index")
        self.assertEqual(diagnostics["assignment_mode"], "keyword_assigned")

    @patch(
        "backend.services.indexing.settings.azure_search_extra_sources",
        new=(
            SearchKnowledgeSourceConfig(
                knowledge_source_name="energy-source",
                index_name="energy-index",
                description="Power systems electricity grid transmission interconnection load growth",
                route_keywords=("power", "grid", "energy"),
                assignment_keywords=("power", "electricity", "grid"),
            ),
            SearchKnowledgeSourceConfig(
                knowledge_source_name="construction-source",
                index_name="construction-index",
                description="Construction BIM safety retrofit project delivery",
                route_keywords=("construction", "bim", "retrofit"),
                assignment_keywords=("construction", "retrofit", "bim"),
            ),
        ),
    )
    def test_custom_doc_scope_groups_selected_docs_by_source(self) -> None:
        adapter = AzureSearchKnowledgeBaseAdapter()

        selected, diagnostics = adapter._route_knowledge_sources(
            "Use the selected corpora only.",
            doc_ids=["doc-energy", "doc-construction"],
            doc_source_assignments={
                "doc-energy": "energy-source",
                "doc-construction": "construction-source",
            },
        )

        self.assertEqual(
            [source.knowledge_source_name for source in selected],
            ["energy-source", "construction-source"],
        )
        self.assertTrue(diagnostics["multi_index_routing"])
        self.assertEqual(
            diagnostics["custom_scope_groups"],
            {
                "energy-source": ["doc-energy"],
                "construction-source": ["doc-construction"],
            },
        )

    def test_build_retrieve_payload_keeps_knowledge_source_params_flat(self) -> None:
        adapter = AzureSearchKnowledgeBaseAdapter()

        payload = adapter._build_retrieve_payload(
            "Use both corpora",
            [
                {"knowledgeSourceName": "enterprise-knowledge-source", "kind": "searchIndex"},
                {"knowledgeSourceName": "energy-source", "kind": "searchIndex"},
            ],
        )

        self.assertIsInstance(payload["knowledgeSourceParams"], list)
        self.assertEqual(len(payload["knowledgeSourceParams"]), 2)
        self.assertEqual(
            payload["knowledgeSourceParams"][0]["knowledgeSourceName"],
            "enterprise-knowledge-source",
        )
        self.assertEqual(payload["knowledgeSourceParams"][1]["knowledgeSourceName"], "energy-source")

    @patch("backend.services.indexing.settings.azure_search_api_version", new="2026-05-01-preview")
    @patch("backend.services.indexing.settings.azure_search_llm_deployment", new="gpt-5-mini")
    @patch("backend.services.indexing.settings.azure_search_llm_model_name", new="gpt-5-mini")
    @patch("backend.services.indexing.settings.azure_foundry_resource_endpoint", new="https://example.cognitiveservices.azure.com/")
    @patch("backend.services.indexing.settings.azure_search_enable_answer_synthesis", new=True)
    @patch("backend.services.indexing.settings.azure_foundry_api_key", new="test-key")
    @patch("backend.services.indexing.settings.azure_search_llm_use_managed_identity", new=False)
    def test_build_retrieve_payload_uses_answer_synthesis_when_enabled(self) -> None:
        adapter = AzureSearchKnowledgeBaseAdapter()

        payload = adapter._build_retrieve_payload(
            "Summarize the visual evidence.",
            [{"knowledgeSourceName": "enterprise-knowledge-source", "kind": "searchIndex"}],
        )

        self.assertEqual(payload["outputMode"], "answerSynthesis")
        self.assertNotIn("answerInstructions", payload)

    @patch.object(
        AzureSearchKnowledgeBaseAdapter,
        "_enrichment_knowledge_source",
        return_value=SearchKnowledgeSourceConfig(
            knowledge_source_name="enterprise-knowledge-enrichment-source-v2",
            index_name="enterprise-knowledge-enrichment-index-v2",
            description="Blob-enriched summaries and image descriptions",
            route_keywords=("diagram", "summary", "image"),
        ),
    )
    def test_route_knowledge_sources_includes_enrichment_source_for_diagram_queries(self, _mock_source) -> None:
        adapter = AzureSearchKnowledgeBaseAdapter()

        selected, diagnostics = adapter._route_knowledge_sources("Show me the diagram summary for this corpus.")

        self.assertEqual(
            [source.knowledge_source_name for source in selected],
            ["enterprise-knowledge-source", "enterprise-knowledge-enrichment-source-v2"],
        )
        self.assertTrue(diagnostics["multi_index_routing"])

    @patch("backend.services.indexing.get_workshop_skill_profile")
    @patch("backend.services.indexing.settings.azure_search_include_enrichment_source_in_chat", new=True)
    @patch("backend.services.indexing.settings.azure_search_blob_source_container", new="documents")
    @patch(
        "backend.services.indexing.settings.azure_search_blob_connection_string",
        new="ResourceId=/subscriptions/test/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/acct;",
    )
    @patch("backend.services.indexing.settings.azure_search_key", new="test-search-key")
    @patch("backend.services.indexing.settings.azure_search_endpoint", new="https://example.search.windows.net")
    def test_enrichment_knowledge_source_uses_active_workshop_profile_index(self, mock_profile) -> None:
        mock_profile.return_value = SimpleNamespace(
            id="genai_enrichment",
            title="Generative Enrichment",
            target_index_name="enterprise-knowledge-enrichment-index-v2-genai",
        )
        adapter = AzureSearchKnowledgeBaseAdapter()

        source = adapter._enrichment_knowledge_source()

        self.assertIsNotNone(source)
        assert source is not None
        self.assertEqual(source.index_name, "enterprise-knowledge-enrichment-index-v2-genai")
        self.assertEqual(
            source.knowledge_source_name,
            "enterprise-knowledge-enrichment-source-v2-genai-enrichment",
        )


if __name__ == "__main__":
    unittest.main()
