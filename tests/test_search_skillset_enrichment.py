from __future__ import annotations

import unittest
from unittest.mock import patch
from requests import Response

from backend.domain.models import ChunkRecord, IntermediateDocument
from backend.services.search_skillset_enrichment import AzureSearchSkillsetEnrichmentService


class SearchSkillsetEnrichmentTests(unittest.TestCase):
    def test_build_enrichment_index_body_uses_keyword_hints_raw_and_optional_vector_field(self) -> None:
        service = AzureSearchSkillsetEnrichmentService()

        with (
            patch("backend.services.search_skillset_enrichment.settings.workshop_skill_profile", "genai_enrichment"),
            patch("backend.services.search_skillset_enrichment.settings.azure_search_enable_integrated_vectorization", True),
            patch("backend.services.search_skillset_enrichment.settings.azure_openai_embedding_deployment", "text-embedding-3-large"),
            patch("backend.services.search_skillset_enrichment.settings.azure_openai_embedding_model_name", "text-embedding-3-large"),
            patch("backend.services.search_skillset_enrichment.settings.azure_foundry_resource_endpoint", "https://example.cognitiveservices.azure.com/"),
        ):
            body = service._build_enrichment_index_body()

        field_names = [field["name"] for field in body["fields"]]
        field_by_name = {field["name"]: field for field in body["fields"]}
        self.assertEqual(body["name"], "ai-search-lab-enrichment-index-genai")
        self.assertIn("keyword_hints_raw", field_names)
        self.assertIn("split_chunks", field_names)
        self.assertIn("content_vector", field_names)
        self.assertEqual(field_by_name["content_markdown_raw"]["searchable"], False)
        self.assertEqual(field_by_name["prompt_seed_text"]["searchable"], True)
        self.assertIn("vectorSearch", body)
        vectorizer = body["vectorSearch"]["vectorizers"][0]["azureOpenAIParameters"]
        self.assertEqual(vectorizer["deploymentId"], "text-embedding-3-large")
        self.assertEqual(vectorizer["modelName"], "text-embedding-3-large")

    def test_build_indexer_body_maps_doc_key_and_keyword_hints_raw(self) -> None:
        service = AzureSearchSkillsetEnrichmentService()

        with (
            patch("backend.services.search_skillset_enrichment.settings.workshop_skill_profile", "genai_enrichment"),
            patch(
                "backend.services.search_skillset_enrichment.settings.azure_search_enrichment_cache_connection_string",
                "UseDevelopmentStorage=true",
            ),
        ):
            body = service._build_indexer_body()

        self.assertIn(
            {
                "sourceFieldName": "metadata_storage_path",
                "targetFieldName": "doc_key",
                "mappingFunction": {"name": "base64Encode"},
            },
            body["fieldMappings"],
        )
        self.assertIn(
            {"sourceFieldName": "metadata_docid", "targetFieldName": "doc_id"},
            body["fieldMappings"],
        )
        self.assertIn(
            {"sourceFieldName": "/document/keyword_hints_raw", "targetFieldName": "keyword_hints_raw"},
            body["outputFieldMappings"],
        )
        self.assertIn(
            {"sourceFieldName": "/document/split_chunks", "targetFieldName": "split_chunks"},
            body["outputFieldMappings"],
        )
        self.assertIn(
            {"sourceFieldName": "/document/prompt_seed_text", "targetFieldName": "prompt_seed_text"},
            body["outputFieldMappings"],
        )
        self.assertEqual(body["cache"]["enableReprocessing"], True)

    def test_build_skillset_body_uses_visual_nlp_skills_for_visual_profile(self) -> None:
        service = AzureSearchSkillsetEnrichmentService()

        with patch("backend.services.search_skillset_enrichment.settings.workshop_skill_profile", "visual_nlp"):
            body = service._build_skillset_body()

        skill_types = [skill["@odata.type"] for skill in body["skills"]]
        self.assertIn("#Microsoft.Skills.Vision.OcrSkill", skill_types)
        self.assertIn("#Microsoft.Skills.Vision.ImageAnalysisSkill", skill_types)
        self.assertIn("#Microsoft.Skills.Text.LanguageDetectionSkill", skill_types)
        self.assertEqual(body["name"], "ai-search-lab-skillset-visual-nlp")

    def test_baseline_skillset_body_keeps_extractor_only_when_prompt_enrichment_is_disabled(self) -> None:
        service = AzureSearchSkillsetEnrichmentService()

        with patch("backend.services.search_skillset_enrichment.settings.workshop_skill_profile", "baseline_extract"):
            body = service._build_skillset_body(prompt_skill_kind="none")

        skill_names = [skill["name"] for skill in body["skills"]]
        self.assertEqual(skill_names, ["#documentExtraction"])

    @patch("backend.services.search_skillset_enrichment.settings.azure_foundry_resource_endpoint", new="https://example.cognitiveservices.azure.com/")
    @patch("backend.services.search_skillset_enrichment.settings.azure_search_llm_deployment", new="gpt-5-4-mini-search")
    def test_build_summary_prompt_skill_uses_search_llm_deployment(self) -> None:
        service = AzureSearchSkillsetEnrichmentService()

        skill = service._build_summary_prompt_skill(prompt_skill_kind="chat_completion")

        self.assertEqual(skill["@odata.type"], "#Microsoft.Skills.Custom.ChatCompletionSkill")
        self.assertIn("/openai/deployments/gpt-5-4-mini-search/chat/completions", skill["uri"])
        self.assertNotIn("apiKey", skill)
        self.assertNotIn("prompt", skill)
        self.assertEqual([entry["name"] for entry in skill["inputs"]], ["text", "systemMessage", "userMessage"])
        self.assertEqual(skill["inputs"][0]["source"], "/document/content_markdown")
        self.assertEqual(skill["outputs"], [{"name": "response", "targetName": "summary_text"}])

    def test_build_skillset_body_uses_prompt_seed_split_merge_and_summary_chain(self) -> None:
        service = AzureSearchSkillsetEnrichmentService()

        with (
            patch("backend.services.search_skillset_enrichment.settings.workshop_skill_profile", "genai_enrichment"),
            patch("backend.services.search_skillset_enrichment.settings.azure_foundry_resource_endpoint", "https://example.cognitiveservices.azure.com/"),
            patch("backend.services.search_skillset_enrichment.settings.azure_foundry_chat_deployment", "gpt-5-4-mini-chat"),
            patch("backend.services.search_skillset_enrichment.settings.azure_openai_embedding_deployment", "text-embedding-3-large-vector"),
            patch("backend.services.search_skillset_enrichment.settings.azure_openai_embedding_model_name", "text-embedding-3-large"),
        ):
            body = service._build_skillset_body()

        skills_by_name = {skill["name"]: skill for skill in body["skills"]}
        self.assertIn("#splitPromptSeed", skills_by_name)
        self.assertIn("#mergePromptSeed", skills_by_name)
        self.assertEqual(
            skills_by_name["#summaryPrompt"]["inputs"][0]["source"],
            "/document/prompt_seed_text",
        )
        self.assertEqual(
            skills_by_name["#keywordPrompt"]["inputs"][0]["source"],
            "/document/summary_text",
        )

    def test_chunk_vector_skillset_embeds_prompt_seed_when_prompt_enrichment_is_disabled(self) -> None:
        service = AzureSearchSkillsetEnrichmentService()

        with (
            patch("backend.services.search_skillset_enrichment.settings.workshop_skill_profile", "chunk_vector"),
            patch("backend.services.search_skillset_enrichment.settings.azure_foundry_resource_endpoint", "https://example.cognitiveservices.azure.com/"),
            patch("backend.services.search_skillset_enrichment.settings.azure_openai_embedding_deployment", "text-embedding-3-large-vector"),
            patch("backend.services.search_skillset_enrichment.settings.azure_openai_embedding_model_name", "text-embedding-3-large"),
        ):
            body = service._build_skillset_body(prompt_skill_kind="none")

        skills_by_name = {skill["name"]: skill for skill in body["skills"]}
        self.assertIn("#splitPromptSeed", skills_by_name)
        self.assertIn("#mergePromptSeed", skills_by_name)
        self.assertEqual(
            skills_by_name["#contentEmbedding"]["inputs"][0]["source"],
            "/document/prompt_seed_text",
        )

    def test_baseline_indexer_body_omits_prompt_outputs_when_prompt_enrichment_is_disabled(self) -> None:
        service = AzureSearchSkillsetEnrichmentService()

        with patch("backend.services.search_skillset_enrichment.settings.workshop_skill_profile", "baseline_extract"):
            body = service._build_indexer_body(prompt_skill_kind="none")

        output_sources = [entry["sourceFieldName"] for entry in body["outputFieldMappings"]]
        self.assertNotIn("/document/prompt_seed_text", output_sources)
        self.assertNotIn("/document/summary_text", output_sources)
        self.assertNotIn("/document/keyword_hints_raw", output_sources)

    @patch("backend.services.search_skillset_enrichment.settings.azure_foundry_resource_endpoint", new="https://example.cognitiveservices.azure.com/")
    def test_build_skillset_body_attaches_billable_foundry_resource(self) -> None:
        service = AzureSearchSkillsetEnrichmentService()

        body = service._build_skillset_body()

        self.assertEqual(body["cognitiveServices"]["@odata.type"], "#Microsoft.Azure.Search.AIServicesByIdentity")
        self.assertEqual(body["cognitiveServices"]["subdomainUrl"], "https://example.cognitiveservices.azure.com")
        self.assertNotIn("cache", body)

    def test_content_understanding_extractor_requires_configuration_in_workshop_mode(self) -> None:
        service = AzureSearchSkillsetEnrichmentService()

        with patch(
            "backend.services.search_skillset_enrichment.settings.azure_search_skillset_preferred_extractor",
            "content_understanding",
        ), patch(
            "backend.services.search_skillset_enrichment.settings.azure_content_understanding_endpoint",
            "",
        ), patch(
            "backend.services.search_skillset_enrichment.settings.azure_content_understanding_key",
            "",
        ), patch(
            "backend.services.search_skillset_enrichment.settings.azure_content_understanding_analyzer_id",
            "",
        ), patch(
            "backend.services.search_skillset_enrichment.settings.workshop_strict_mode",
            True,
        ):
            with self.assertRaises(RuntimeError):
                service._active_extractor_kind()

    @patch("backend.services.search_skillset_enrichment.settings.azure_search_default_rbac_scope_ids", new=("engineering", "reviewers"))
    def test_apply_enrichment_to_document_propagates_blob_summary_keywords_and_rbac(self) -> None:
        service = AzureSearchSkillsetEnrichmentService()
        intermediate = IntermediateDocument(
            doc_id="doc-1",
            source_name="report.pdf",
            source_path="C:/temp/report.pdf",
            format="pdf",
            complexity="complex",
            parser_path="document_intelligence_layout",
            metadata={},
            sections=[],
        )
        chunks = [
            ChunkRecord(
                chunk_id="chunk-1",
                doc_id="doc-1",
                source_name="report.pdf",
                checksum="abc",
                clean_text="Original chunk text",
                token_estimate=20,
            )
        ]

        service._apply_enrichment_to_document(
            intermediate,
            chunks,
            {
                "summary_text": "Document summary",
                "keyword_hints_raw": '["construction", "diagram"]',
                "image_description_text": "Annotated site-plan diagram",
            },
            {
                "blob_url": "https://storage.example/documents/doc-1/report.pdf",
                "blob_name": "workshop/doc-1/report.pdf",
            },
        )

        self.assertEqual(intermediate.source_uri, "https://storage.example/documents/doc-1/report.pdf")
        self.assertEqual(chunks[0].summary_text, "Document summary")
        self.assertEqual(chunks[0].image_description_text, "Annotated site-plan diagram")
        self.assertEqual(chunks[0].keyword_hints, ["construction", "diagram"])
        self.assertEqual(chunks[0].rbac_scope_ids, ["engineering", "reviewers"])
        self.assertIn("search_skillset_blob", intermediate.metadata)

    def test_retryable_indexer_failure_detects_too_many_requests(self) -> None:
        service = AzureSearchSkillsetEnrichmentService()

        retryable, detail = service._retryable_indexer_failure_detail(
            {
                "lastResult": {
                    "status": "transientFailure",
                    "errors": [
                        {
                            "statusCode": 400,
                            "details": "Web Api response status: 'TooManyRequests', Web Api response details: '{\"error\":{\"message\":\"Too Many Requests\"}}'",
                        }
                    ],
                }
            }
        )

        self.assertTrue(retryable)
        self.assertIn("TooManyRequests", detail)

    def test_conflicting_update_response_is_retryable_for_resource_updates(self) -> None:
        service = AzureSearchSkillsetEnrichmentService()
        response = Response()
        response.status_code = 409
        response._content = (
            b'{"error":{"code":"","message":"There was a conflicting update. '
            b'No change was made to the resource from this request."}}'
        )

        self.assertTrue(service._is_conflicting_update_response(response))


if __name__ == "__main__":
    unittest.main()
