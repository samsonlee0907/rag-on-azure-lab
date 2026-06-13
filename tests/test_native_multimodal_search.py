from __future__ import annotations

import unittest
from unittest.mock import MagicMock, PropertyMock, patch

from backend.services.native_multimodal_search import NativeMultimodalSearchService


class NativeMultimodalSearchTests(unittest.TestCase):
    def test_should_use_native_mode_honors_explicit_and_auto_terms(self) -> None:
        service = NativeMultimodalSearchService()

        self.assertTrue(service.should_use_native_mode("anything", "native_multimodal"))
        self.assertFalse(service.should_use_native_mode("show me a diagram", "standard"))
        self.assertTrue(service.should_use_native_mode("Show me the diagram and blueprint evidence.", "auto"))
        self.assertFalse(service.should_use_native_mode("Compare the indexed chunks only.", "auto"))

    @patch("backend.services.native_multimodal_search.settings.azure_search_enable_image_serving", new=True)
    @patch("backend.services.native_multimodal_search.settings.azure_search_blob_connection_string", new="UseDevelopmentStorage=true")
    @patch("backend.services.native_multimodal_search.settings.azure_search_asset_store_connection_string", new="")
    @patch("backend.services.native_multimodal_search.settings.azure_search_blob_source_container", new="documents")
    @patch("backend.services.native_multimodal_search.settings.azure_search_asset_store_container", new="search-image-assets")
    @patch("backend.services.native_multimodal_search.settings.azure_foundry_resource_endpoint", new="https://example.cognitiveservices.azure.com/")
    @patch("backend.services.native_multimodal_search.settings.azure_search_native_chat_completion_deployment", new="gpt-5-4-mini-native")
    @patch("backend.services.native_multimodal_search.settings.azure_search_native_chat_completion_model_name", new="gpt-5.4-mini")
    @patch("backend.services.native_multimodal_search.settings.azure_openai_embedding_deployment", new="text-embedding-3-large")
    @patch("backend.services.native_multimodal_search.settings.azure_openai_embedding_model_name", new="text-embedding-3-large")
    @patch("backend.services.native_multimodal_search.settings.azure_search_native_content_extraction_mode", new="standard")
    def test_build_blob_knowledge_source_body_includes_asset_store(self) -> None:
        service = NativeMultimodalSearchService()

        body = service._build_blob_knowledge_source_body(
            knowledge_source_name="native-doc-source",
            blob_folder_path="workshop/doc-123",
            source_name="diagram-report.pdf",
        )

        self.assertEqual(body["kind"], "azureBlob")
        self.assertEqual(body["azureBlobParameters"]["folderPath"], "workshop/doc-123")
        self.assertEqual(
            body["azureBlobParameters"]["ingestionParameters"]["assetStore"]["containerName"],
            "search-image-assets",
        )
        self.assertEqual(
            body["azureBlobParameters"]["ingestionParameters"]["chatCompletionModel"]["azureOpenAIParameters"][
                "deploymentId"
            ],
            "gpt-5-4-mini-native",
        )
        self.assertEqual(
            body["azureBlobParameters"]["ingestionParameters"]["chatCompletionModel"]["azureOpenAIParameters"][
                "resourceUri"
            ],
            "https://example.services.ai.azure.com",
        )
        self.assertEqual(
            body["azureBlobParameters"]["ingestionParameters"]["embeddingModel"]["azureOpenAIParameters"][
                "resourceUri"
            ],
            "https://example.openai.azure.com",
        )
        self.assertEqual(
            body["azureBlobParameters"]["ingestionParameters"]["embeddingModel"]["azureOpenAIParameters"][
                "modelName"
            ],
            "text-embedding-3-large",
        )
        self.assertEqual(
            body["azureBlobParameters"]["ingestionParameters"]["aiServices"]["uri"],
            "https://example.services.ai.azure.com",
        )

    @patch("backend.services.native_multimodal_search.settings.azure_search_enable_image_serving", new=True)
    @patch("backend.services.native_multimodal_search.settings.azure_search_llm_deployment", new="gpt-5-4-mini-search")
    @patch("backend.services.native_multimodal_search.settings.azure_search_llm_model_name", new="gpt-5.4-mini")
    @patch("backend.services.native_multimodal_search.settings.azure_search_native_chat_completion_deployment", new="gpt-5-4-mini-native")
    @patch("backend.services.native_multimodal_search.settings.azure_search_native_chat_completion_model_name", new="gpt-5.4-mini")
    @patch("backend.services.native_multimodal_search.settings.azure_foundry_resource_endpoint", new="https://example.cognitiveservices.azure.com/")
    @patch("backend.services.native_multimodal_search.settings.azure_search_llm_use_managed_identity", new=False)
    @patch("backend.services.native_multimodal_search.settings.azure_foundry_api_key", new="test-key")
    def test_build_native_knowledge_base_body_prefers_native_answer_model(self) -> None:
        service = NativeMultimodalSearchService()

        body = service._build_native_knowledge_base_body(["native-doc-source"])

        self.assertEqual(body["knowledgeSources"][0]["name"], "native-doc-source")
        self.assertTrue(body["knowledgeSources"][0]["enableImageServing"])
        self.assertEqual(body["outputMode"], "answerSynthesis")
        self.assertEqual(body["models"][0]["azureOpenAIParameters"]["deploymentId"], "gpt-5-4-mini-native")
        self.assertEqual(body["models"][0]["azureOpenAIParameters"]["resourceUri"], "https://example.openai.azure.com")

    @patch("backend.services.native_multimodal_search.settings.azure_search_enable_image_serving", new=True)
    def test_build_blob_knowledge_source_params_enable_image_serving(self) -> None:
        service = NativeMultimodalSearchService()

        params = service._build_blob_knowledge_source_params(
            knowledge_source_name="native-doc-source",
            force_query=True,
        )

        self.assertEqual(params["kind"], "azureBlob")
        self.assertTrue(params["enableImageServing"])
        self.assertTrue(params["alwaysQuerySource"])

    @patch.object(NativeMultimodalSearchService, "enabled", new_callable=PropertyMock, return_value=True)
    @patch("backend.services.native_multimodal_search.requests.put")
    def test_sync_knowledge_base_can_use_exact_source_names(self, mock_put, _mock_enabled) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_put.return_value = mock_response
        service = NativeMultimodalSearchService()

        body = service.sync_knowledge_base(exact_source_names=["source-b", "source-a", "source-a"])

        self.assertEqual([item["name"] for item in body["knowledgeSources"]], ["source-a", "source-b"])

    @patch.object(NativeMultimodalSearchService, "enabled", new_callable=PropertyMock, return_value=True)
    @patch.object(NativeMultimodalSearchService, "sync_knowledge_base")
    @patch.object(NativeMultimodalSearchService, "_build_retrieve_payload", return_value={"messages": []})
    @patch("backend.services.native_multimodal_search.requests.post")
    def test_chat_forces_selected_native_source_to_query(
        self,
        mock_post,
        _mock_payload,
        _mock_sync,
        _mock_enabled,
    ) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"answer": "ok"}
        mock_post.return_value = mock_response
        service = NativeMultimodalSearchService()

        with patch.object(
            service,
            "_build_blob_knowledge_source_params",
            wraps=service._build_blob_knowledge_source_params,
        ) as wrapped_params:
            service.chat("Show me the architecture diagram.", knowledge_source_names=["native-doc-source"])

        wrapped_params.assert_called_once_with(
            knowledge_source_name="native-doc-source",
            force_query=True,
        )

    @patch("backend.services.native_multimodal_search.settings.azure_search_native_retrieve_retry_attempts", new=2)
    @patch("backend.services.native_multimodal_search.settings.azure_search_native_retrieve_retry_base_delay_seconds", new=0)
    def test_post_retrieve_with_retry_retries_on_model_throttle(self) -> None:
        service = NativeMultimodalSearchService()
        throttled = MagicMock()
        throttled.status_code = 429
        throttled.text = '{"error":{"message":"Could not complete model action. Too Many Requests"}}'
        success = MagicMock()
        success.status_code = 200
        success.text = '{"answer":"ok"}'

        with patch("backend.services.native_multimodal_search.requests.post", side_effect=[throttled, success]) as mock_post:
            response = service._post_retrieve_with_retry(url="https://example/retrieve", payload={"messages": []})

        self.assertIs(response, success)
        self.assertEqual(mock_post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
