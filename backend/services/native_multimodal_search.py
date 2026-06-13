from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from time import sleep
from typing import Any

import requests

from backend.core.config import settings
from backend.services.job_store import job_store

logger = logging.getLogger(__name__)


def _normalize_foundry_model_name(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return candidate
    match = re.fullmatch(r"(gpt-\d+)-(\d+)(-.+)?", candidate)
    if not match:
        return candidate
    prefix, minor, suffix = match.groups()
    return f"{prefix}.{minor}{suffix or ''}"


@dataclass(slots=True)
class NativeMultimodalSnapshot:
    status: str
    message: str
    knowledge_source_name: str | None = None
    knowledge_base_name: str | None = None
    blob_folder_path: str | None = None
    diagnostics: dict[str, Any] | None = None


class NativeMultimodalSearchService:
    def __init__(self) -> None:
        self.endpoint = settings.azure_search_endpoint.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
            "api-key": settings.azure_search_key,
            "Prefer": "return=representation",
        }
        self.api_version = settings.azure_search_native_api_version

    @property
    def enabled(self) -> bool:
        return settings.azure_search_native_multimodal_enabled

    def ensure_document_source(
        self,
        *,
        doc_id: str,
        source_name: str,
        blob_upload: dict[str, Any] | None,
    ) -> NativeMultimodalSnapshot:
        if not self.enabled:
            return NativeMultimodalSnapshot(
                status="not_configured",
                message="Native Blob multimodal retrieval is not configured.",
                knowledge_base_name=settings.azure_search_native_knowledge_base_name,
                diagnostics={},
            )
        if not blob_upload or not blob_upload.get("blob_name"):
            return NativeMultimodalSnapshot(
                status="not_configured",
                message="No Blob upload metadata is available for the native multimodal lane.",
                knowledge_base_name=settings.azure_search_native_knowledge_base_name,
                diagnostics={},
            )

        knowledge_source_name = self.document_source_name(doc_id)
        blob_folder_path = self._blob_folder_path(blob_upload)
        body = self._build_blob_knowledge_source_body(
            knowledge_source_name=knowledge_source_name,
            blob_folder_path=blob_folder_path,
            source_name=source_name,
        )

        try:
            self._put_knowledge_source(knowledge_source_name, body)
            source_status = self._poll_knowledge_source_status(knowledge_source_name)
            kb_payload = self.sync_knowledge_base(extra_source_names=[knowledge_source_name])
            return NativeMultimodalSnapshot(
                status="completed",
                message="Native Blob multimodal knowledge source and knowledge base are configured.",
                knowledge_source_name=knowledge_source_name,
                knowledge_base_name=settings.azure_search_native_knowledge_base_name,
                blob_folder_path=blob_folder_path,
                diagnostics={
                    "knowledge_source_status": source_status,
                    "knowledge_base": kb_payload,
                    "request_body_preview": body,
                },
            )
        except Exception as exc:
            logger.warning(
                "native multimodal provisioning failed",
                extra={"context": {"doc_id": doc_id, "knowledge_source_name": knowledge_source_name, "error": str(exc)}},
            )
            return NativeMultimodalSnapshot(
                status="failed",
                message=f"Native Blob multimodal provisioning failed: {exc}",
                knowledge_source_name=knowledge_source_name,
                knowledge_base_name=settings.azure_search_native_knowledge_base_name,
                blob_folder_path=blob_folder_path,
                diagnostics={"request_body_preview": body, "error": str(exc)},
            )

    def sync_knowledge_base(
        self,
        *,
        exact_source_names: list[str] | None = None,
        extra_source_names: list[str] | None = None,
        excluded_source_names: list[str] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return {}
        if exact_source_names is not None:
            source_names = sorted({name for name in exact_source_names if name})
        else:
            source_names = self._collect_native_source_names(extra_source_names or [], excluded_source_names or [])
        body = self._build_native_knowledge_base_body(source_names)
        url = (
            f"{self.endpoint}/knowledgebases('{settings.azure_search_native_knowledge_base_name}')"
            f"?api-version={self.api_version}"
        )
        response = requests.put(url, headers=self.headers, data=json.dumps(body), timeout=60)
        self._raise_for_status(response)
        return body

    def delete_document_source(self, knowledge_source_name: str | None) -> None:
        if not self.enabled or not knowledge_source_name:
            return
        url = f"{self.endpoint}/knowledgesources('{knowledge_source_name}')?api-version={self.api_version}"
        response = requests.delete(url, headers=self.headers, timeout=60)
        if response.status_code not in {200, 204, 404}:
            self._raise_for_status(response)
        self.sync_knowledge_base(excluded_source_names=[knowledge_source_name])

    def chat(self, question: str, *, knowledge_source_names: list[str]) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Native Blob multimodal retrieval is not configured.")
        selected_names = [name for name in knowledge_source_names if name]
        if not selected_names:
            raise RuntimeError("No native Blob knowledge sources are available for the selected query.")

        self.sync_knowledge_base(exact_source_names=selected_names)
        knowledge_source_params = [
            self._build_blob_knowledge_source_params(
                knowledge_source_name=name,
                # When the user explicitly selects native multimodal mode for one or more Blob
                # sources, force those sources to be queried so answer synthesis stays grounded.
                force_query=True,
            )
            for name in selected_names
        ]
        payload = self._build_retrieve_payload(question, knowledge_source_params)
        url = (
            f"{self.endpoint}/knowledgebases('{settings.azure_search_native_knowledge_base_name}')/retrieve"
            f"?api-version={self.api_version}"
        )
        response = self._post_retrieve_with_retry(url=url, payload=payload)
        self._raise_for_status(response)
        result = response.json()
        diagnostics = result.setdefault("diagnostics", {})
        diagnostics.update(
            {
                "mode": "search_answer_synthesis_native_multimodal",
                "force_search_answer_synthesis": True,
                "selected_native_knowledge_sources": selected_names,
                "native_multimodal": True,
                "native_answer_synthesis_deployment": (
                    settings.azure_search_native_chat_completion_deployment or settings.azure_search_llm_deployment
                ),
            }
        )
        return result

    def document_source_name(self, doc_id: str) -> str:
        prefix = settings.azure_search_native_knowledge_source_prefix
        suffix = re.sub(r"[^a-z0-9]", "", doc_id.lower())[:24]
        return f"{prefix}{suffix}"

    def should_use_native_mode(self, question: str, explicit_mode: str) -> bool:
        if explicit_mode == "native_multimodal":
            return True
        if explicit_mode == "standard":
            return False
        lowered = question.lower()
        terms = [term.strip().lower() for term in settings.azure_search_native_auto_query_terms if term.strip()]
        return any(term in lowered for term in terms)

    def _collect_native_source_names(
        self, extra_source_names: list[str], excluded_source_names: list[str]
    ) -> list[str]:
        excluded = {name for name in excluded_source_names if name}
        names = {name for name in extra_source_names if name and name not in excluded}
        for job in job_store.list_jobs():
            native_status = (job.enrichment_status or {}).get("native_multimodal") or {}
            if not isinstance(native_status, dict):
                continue
            source_name = native_status.get("knowledge_source_name")
            if source_name and source_name not in excluded:
                names.add(str(source_name))
        return sorted(names)

    def _blob_folder_path(self, blob_upload: dict[str, Any]) -> str:
        blob_name = str(blob_upload.get("blob_name") or "").strip().strip("/")
        if "/" not in blob_name:
            return blob_name
        return blob_name.rsplit("/", 1)[0]

    def _build_blob_knowledge_source_body(
        self,
        *,
        knowledge_source_name: str,
        blob_folder_path: str,
        source_name: str,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": knowledge_source_name,
            "kind": "azureBlob",
            "description": f"Native Blob multimodal knowledge source for {source_name}",
            "azureBlobParameters": {
                "connectionString": settings.azure_search_blob_connection_string_resolved,
                "containerName": settings.azure_search_blob_source_container,
                "folderPath": blob_folder_path,
            },
        }
        ingestion_parameters: dict[str, Any] = {
            "contentExtractionMode": settings.azure_search_native_content_extraction_mode,
        }
        asset_connection_string = (
            settings.azure_search_asset_store_connection_string
            or settings.azure_search_blob_connection_string_resolved
        )
        native_chat_model = self._build_native_chat_completion_model()
        if native_chat_model:
            ingestion_parameters["chatCompletionModel"] = native_chat_model
            ingestion_parameters["disableImageVerbalization"] = False
        if settings.azure_openai_embedding_deployment:
            embedding_model = self._build_native_embedding_model()
            if embedding_model:
                ingestion_parameters["embeddingModel"] = embedding_model
        if (
            settings.azure_search_native_content_extraction_mode == "standard"
            and settings.azure_foundry_services_base_url
        ):
            ingestion_parameters["aiServices"] = {"uri": settings.azure_foundry_services_base_url}
        if settings.azure_search_enable_image_serving and asset_connection_string:
            ingestion_parameters["assetStore"] = {
                "connectionString": asset_connection_string,
                "containerName": settings.azure_search_asset_store_container,
            }
        if ingestion_parameters:
            body["azureBlobParameters"]["ingestionParameters"] = ingestion_parameters
        return body

    def _build_native_knowledge_base_body(self, source_names: list[str]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": settings.azure_search_native_knowledge_base_name,
            "knowledgeSources": [
                {
                    "name": source_name,
                    **({"enableImageServing": True} if settings.azure_search_enable_image_serving else {}),
                }
                for source_name in source_names
            ],
        }
        native_answer_model = self._build_native_answer_synthesis_model()
        if native_answer_model:
            body["models"] = [
                native_answer_model
            ]
            body["retrievalReasoningEffort"] = {"kind": settings.azure_search_llm_reasoning_effort}
        body["outputMode"] = "answerSynthesis"
        if settings.azure_search_answer_instructions:
            body["answerInstructions"] = settings.azure_search_answer_instructions
        return body

    def _build_knowledge_agent_model(
        self,
        *,
        deployment_id: str,
        model_name: str,
        use_managed_identity: bool,
        resource_uri: str | None = None,
    ) -> dict[str, Any]:
        azure_openai_parameters: dict[str, Any] = {
            "resourceUri": (resource_uri or settings.azure_foundry_openai_base_url),
            "deploymentId": deployment_id,
            "modelName": model_name,
        }
        if not use_managed_identity and settings.azure_foundry_api_key:
            azure_openai_parameters["apiKey"] = settings.azure_foundry_api_key
        return {
            "kind": "azureOpenAI",
            "azureOpenAIParameters": azure_openai_parameters,
        }

    def _build_native_chat_completion_model(self) -> dict[str, Any] | None:
        if settings.azure_search_native_chat_completion_deployment and settings.azure_foundry_services_base_url:
            return self._build_knowledge_agent_model(
                deployment_id=settings.azure_search_native_chat_completion_deployment,
                model_name=(
                    settings.azure_search_native_chat_completion_model_name
                    or _normalize_foundry_model_name(settings.azure_search_native_chat_completion_deployment)
                ),
                use_managed_identity=True,
                resource_uri=settings.azure_foundry_services_base_url,
            )
        if settings.azure_search_llm_enabled:
            return self._build_knowledge_agent_model(
                deployment_id=settings.azure_search_llm_deployment,
                model_name=settings.azure_search_llm_model_name or settings.azure_search_llm_deployment,
                use_managed_identity=settings.azure_search_llm_use_managed_identity,
            )
        return None

    def _build_native_answer_synthesis_model(self) -> dict[str, Any] | None:
        if settings.azure_search_native_chat_completion_deployment and settings.azure_foundry_openai_base_url:
            return self._build_knowledge_agent_model(
                deployment_id=settings.azure_search_native_chat_completion_deployment,
                model_name=(
                    settings.azure_search_native_chat_completion_model_name
                    or _normalize_foundry_model_name(settings.azure_search_native_chat_completion_deployment)
                ),
                use_managed_identity=True,
                resource_uri=settings.azure_foundry_openai_base_url,
            )
        if settings.azure_search_llm_enabled:
            return self._build_knowledge_agent_model(
                deployment_id=settings.azure_search_llm_deployment,
                model_name=settings.azure_search_llm_model_name or settings.azure_search_llm_deployment,
                use_managed_identity=settings.azure_search_llm_use_managed_identity,
            )
        return None

    def _build_native_embedding_model(self) -> dict[str, Any] | None:
        if not (settings.azure_openai_embedding_deployment and settings.azure_foundry_openai_base_url):
            return None
        return self._build_knowledge_agent_model(
            deployment_id=settings.azure_openai_embedding_deployment,
            model_name=settings.azure_openai_embedding_model_name,
            use_managed_identity=True,
            resource_uri=settings.azure_foundry_openai_base_url,
        )

    def _build_blob_knowledge_source_params(
        self,
        *,
        knowledge_source_name: str,
        force_query: bool,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "knowledgeSourceName": knowledge_source_name,
            "kind": "azureBlob",
            "includeReferences": True,
            "includeReferenceSourceData": True,
        }
        if settings.azure_search_enable_image_serving:
            params["enableImageServing"] = True
        if force_query:
            params["alwaysQuerySource"] = True
        return params

    def _build_retrieve_payload(
        self, question: str, knowledge_source_params: list[dict[str, Any]]
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": question,
                        }
                    ],
                }
            ],
            "maxRuntimeInSeconds": 45,
            "maxOutputSize": 120000,
            "includeActivity": True,
            "outputMode": "answerSynthesis",
            "knowledgeSourceParams": knowledge_source_params,
            "retrievalReasoningEffort": {"kind": settings.azure_search_llm_reasoning_effort},
        }
        return payload

    def _post_retrieve_with_retry(self, *, url: str, payload: dict[str, Any]) -> requests.Response:
        attempts = max(1, settings.azure_search_native_retrieve_retry_attempts)
        response: requests.Response | None = None
        for attempt in range(1, attempts + 1):
            response = requests.post(url, headers=self.headers, data=json.dumps(payload), timeout=90)
            if not self._is_native_model_throttle_response(response) or attempt >= attempts:
                return response
            sleep(
                min(
                    45,
                    max(1, settings.azure_search_native_retrieve_retry_base_delay_seconds) * (2 ** (attempt - 1)),
                )
            )
        assert response is not None
        return response

    def _is_native_model_throttle_response(self, response: requests.Response) -> bool:
        if response.status_code != 429:
            return False
        detail = response.text.strip().lower()
        return "too many requests" in detail or "could not complete model action" in detail

    def _put_knowledge_source(self, knowledge_source_name: str, body: dict[str, Any]) -> None:
        url = f"{self.endpoint}/knowledgesources('{knowledge_source_name}')?api-version={self.api_version}"
        response = requests.put(url, headers=self.headers, data=json.dumps(body), timeout=60)
        self._raise_for_status(response)

    def _poll_knowledge_source_status(self, knowledge_source_name: str, *, max_attempts: int = 45) -> dict[str, Any]:
        url = f"{self.endpoint}/knowledgesources('{knowledge_source_name}')/status?api-version={self.api_version}"
        last_payload: dict[str, Any] = {}
        for _ in range(max_attempts):
            response = requests.get(url, headers=self.headers, timeout=60)
            self._raise_for_status(response)
            payload = response.json()
            last_payload = payload
            status = str(
                payload.get("status")
                or payload.get("state")
                or (payload.get("lastResult") or {}).get("status")
                or ""
            ).lower()
            if status in {"success", "succeeded", "ready"}:
                return payload
            if status in {"error", "failed", "transientfailure"}:
                return payload
            sleep(4)
        return last_payload

    def _raise_for_status(self, response: requests.Response) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = response.text.strip()
            if detail:
                raise RuntimeError(
                    f"{response.status_code} {response.reason} from Azure AI Search native multimodal lane: {detail}"
                ) from exc
            raise


native_multimodal_search = NativeMultimodalSearchService()
