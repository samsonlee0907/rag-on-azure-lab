from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any

import requests

from backend.core.config import settings
from backend.domain.models import ChunkRecord, IntermediateDocument
from backend.services.blob_storage import build_blob_document_store
from backend.services.foundry_openai import call_foundry_text
from backend.services.workshop_profiles import WorkshopSkillProfile, get_workshop_skill_profile

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SearchSkillsetEnrichmentSnapshot:
    status: str
    message: str
    blob_upload: dict[str, Any]
    search_objects: dict[str, Any]
    extracted_fields: dict[str, Any]
    diagnostics: dict[str, Any]


class AzureSearchSkillsetEnrichmentService:
    def __init__(self) -> None:
        self.endpoint = settings.azure_search_endpoint.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
            "api-key": settings.azure_search_key,
        }
        self._last_skillset_selection: dict[str, str] = {
            "api_version": settings.azure_search_indexer_api_version,
            "prompt_skill_kind": "chat_completion",
            "cache_mode": "indexer_cache",
        }

    def _search_timeout(self) -> int:
        return max(60, settings.azure_search_request_timeout_seconds)

    def _request_with_conflict_retry(
        self,
        method: str,
        url: str,
        *,
        body: dict[str, Any] | None = None,
        max_attempts: int = 4,
        timeout: int | None = None,
    ) -> requests.Response:
        response: requests.Response | None = None
        effective_timeout = timeout or self._search_timeout()
        for attempt in range(1, max_attempts + 1):
            response = requests.request(
                method,
                url,
                headers=self.headers,
                data=json.dumps(body) if body is not None else None,
                timeout=effective_timeout,
            )
            if not self._is_conflicting_update_response(response) or attempt >= max_attempts:
                return response
            sleep(min(8, 2 * attempt))
        assert response is not None
        return response

    def enrich_document(
        self,
        *,
        path: Path,
        doc_id: str,
        source_name: str,
        intermediate: IntermediateDocument,
        chunks: list[ChunkRecord],
        profile: WorkshopSkillProfile | None = None,
    ) -> SearchSkillsetEnrichmentSnapshot:
        if not settings.azure_search_enabled:
            return SearchSkillsetEnrichmentSnapshot(
                status="not_configured",
                message="Azure AI Search is not configured, so Search-managed Blob enrichment is disabled.",
                blob_upload={},
                search_objects={},
                extracted_fields={},
                diagnostics={},
            )
        if not settings.azure_search_blob_ingestion_enabled:
            return SearchSkillsetEnrichmentSnapshot(
                status="not_configured",
                message="Blob-backed Search enrichment is not configured.",
                blob_upload={},
                search_objects={},
                extracted_fields={},
                diagnostics={},
            )

        profile = profile or self._active_profile()
        blob_upload = self._upload_source_document(path, doc_id, source_name, profile=profile)
        data_source_name = self._data_source_name(doc_id, profile=profile)
        indexer_name = self._indexer_name(doc_id, profile=profile)
        request_bodies = {
            "index": self._build_enrichment_index_body(profile=profile),
            "data_source": self._build_data_source_body(
                doc_id=doc_id,
                data_source_name=data_source_name,
            ),
            "skillset": self._build_skillset_body(profile=profile),
            "indexer": self._build_indexer_body(
                data_source_name=data_source_name,
                indexer_name=indexer_name,
                profile=profile,
            ),
        }

        try:
            logger.info(
                "ensuring search enrichment index",
                extra={"context": {"doc_id": doc_id, "index_name": self._target_index_name(profile)}},
            )
            self._ensure_enrichment_index(profile=profile)
            logger.info(
                "ensuring search enrichment data source",
                extra={"context": {"doc_id": doc_id, "data_source_name": data_source_name}},
            )
            self._ensure_data_source(
                data_source_name=data_source_name,
                body=request_bodies["data_source"],
            )
            logger.info(
                "ensuring search enrichment skillset",
                extra={"context": {"doc_id": doc_id, "skillset_name": self._target_skillset_name(profile)}},
            )
            self._ensure_skillset(profile=profile)
            logger.info(
                "ensuring search enrichment indexer",
                extra={"context": {"doc_id": doc_id, "indexer_name": indexer_name}},
            )
            self._ensure_indexer(
                indexer_name=indexer_name,
                body=request_bodies["indexer"],
                profile=profile,
            )
            logger.info(
                "running search enrichment indexer",
                extra={"context": {"doc_id": doc_id, "indexer_name": indexer_name}},
            )
            indexer_status, indexer_retry_history = self._run_indexer_with_retry(indexer_name=indexer_name)
            self._raise_if_indexer_failed(indexer_status)
            logger.info(
                "fetching search enrichment document",
                extra={"context": {"doc_id": doc_id, "index_name": self._target_index_name(profile)}},
            )
            extracted_fields = self._fetch_document_enrichment(
                doc_id,
                blob_upload.get("blob_url"),
                profile=profile,
            )
            if not extracted_fields:
                raise RuntimeError(
                    "Blob-backed Search enrichment completed but no enrichment document was found "
                    "for the uploaded blob."
                )
            self._apply_enrichment_to_document(intermediate, chunks, extracted_fields, blob_upload)
            return SearchSkillsetEnrichmentSnapshot(
                status="completed",
                message="Blob-backed Search enrichment completed.",
                blob_upload=blob_upload,
                search_objects={
                    "index_name": self._target_index_name(profile),
                    "data_source_name": data_source_name,
                    "skillset_name": self._target_skillset_name(profile),
                    "indexer_name": indexer_name,
                    "workshop_profile_id": profile.id,
                    "workshop_profile_title": profile.title,
                },
                extracted_fields=extracted_fields,
                diagnostics={
                    "indexer_status": indexer_status,
                    "indexer_retry_history": indexer_retry_history,
                    "request_body_preview": request_bodies,
                    "workshop_profile": profile.to_payload(),
                },
            )
        except Exception as exc:
            logger.warning(
                "search-managed blob enrichment failed",
                extra={"context": {"doc_id": doc_id, "source_name": source_name, "error": str(exc)}},
            )
            return SearchSkillsetEnrichmentSnapshot(
                status="failed",
                message=f"Blob-backed Search enrichment failed: {exc}",
                blob_upload=blob_upload,
                search_objects={
                    "index_name": self._target_index_name(profile),
                    "data_source_name": data_source_name,
                    "skillset_name": self._target_skillset_name(profile),
                    "indexer_name": indexer_name,
                    "workshop_profile_id": profile.id,
                    "workshop_profile_title": profile.title,
                },
                extracted_fields={},
                diagnostics={
                    "request_body_preview": request_bodies,
                    "error": str(exc),
                    "workshop_profile": profile.to_payload(),
                },
            )

    def _upload_source_document(
        self,
        path: Path,
        doc_id: str,
        source_name: str,
        *,
        profile: WorkshopSkillProfile | None = None,
    ) -> dict[str, Any]:
        store = build_blob_document_store()
        if store is None:
            raise RuntimeError("Azure Blob document store is not configured.")
        active_profile = profile or self._active_profile()
        blob_name = self._blob_name_for_document(doc_id, source_name)
        upload = store.upload_file(
            path,
            blob_name=blob_name,
            metadata={
                "docid": doc_id,
                "skillprofile": active_profile.id,
                "sourcename": self._safe_metadata_value(source_name),
                "ingestionmode": self._safe_metadata_value(settings.search_pipeline_mode),
                "uploadedat": _utc_now(),
                **(
                    {"rbacscopeids": ",".join(settings.azure_search_default_rbac_scope_ids)}
                    if settings.azure_search_enable_blob_rbac and settings.azure_search_default_rbac_scope_ids
                    else {}
                ),
            },
        )
        upload["container_name"] = store.container_name
        upload["blob_name"] = blob_name
        upload["blob_prefix"] = self._blob_prefix()
        return upload

    def _blob_prefix(self) -> str:
        return settings.azure_search_blob_source_prefix.strip("/").strip()

    def _blob_name_for_document(self, doc_id: str, source_name: str) -> str:
        prefix = self._blob_prefix()
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", source_name).strip("-") or "document.bin"
        return "/".join(part for part in [prefix, doc_id, safe_name] if part)

    def _blob_query_for_document(self, doc_id: str) -> str:
        return "/".join(part for part in [self._blob_prefix(), doc_id] if part)

    def _active_profile(self) -> WorkshopSkillProfile:
        return get_workshop_skill_profile()

    def _target_index_name(self, profile: WorkshopSkillProfile | None = None) -> str:
        active_profile = profile or self._active_profile()
        return active_profile.target_index_name

    def _target_skillset_name(self, profile: WorkshopSkillProfile | None = None) -> str:
        active_profile = profile or self._active_profile()
        return active_profile.target_skillset_name

    def _data_source_name(self, doc_id: str, *, profile: WorkshopSkillProfile | None = None) -> str:
        active_profile = profile or self._active_profile()
        return f"{settings.azure_search_blob_data_source_name}-{active_profile.id.replace('_', '-')}-{doc_id[:8]}".lower()

    def _indexer_name(self, doc_id: str, *, profile: WorkshopSkillProfile | None = None) -> str:
        active_profile = profile or self._active_profile()
        return f"{active_profile.target_indexer_name}-{doc_id[:12]}".lower()

    def _profile_uses_split(self, profile: WorkshopSkillProfile) -> bool:
        return profile.id in {"chunk_vector", "genai_enrichment", "visual_nlp"}

    def _profile_uses_prompt_enrichment(self, profile: WorkshopSkillProfile) -> bool:
        return profile.id in {"genai_enrichment", "visual_nlp", "content_understanding"}

    def _profile_uses_embedding(self, profile: WorkshopSkillProfile) -> bool:
        return profile.id in {"chunk_vector", "genai_enrichment", "visual_nlp", "content_understanding"}

    def _profile_uses_visual_nlp(self, profile: WorkshopSkillProfile) -> bool:
        return profile.id == "visual_nlp"

    def _safe_metadata_value(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9 _.-]+", "-", value)[:512]

    def _build_enrichment_index_body(self, *, profile: WorkshopSkillProfile | None = None) -> dict[str, Any]:
        active_profile = profile or self._active_profile()
        body: dict[str, Any] = {
            "name": self._target_index_name(active_profile),
            "fields": [
                {"name": "doc_key", "type": "Edm.String", "key": True, "searchable": False, "filterable": True},
                {"name": "doc_id", "type": "Edm.String", "searchable": False, "filterable": True, "retrievable": True},
                {"name": "skill_profile_id", "type": "Edm.String", "searchable": False, "filterable": True, "retrievable": True},
                {"name": "source_name", "type": "Edm.String", "searchable": True, "filterable": True, "retrievable": True},
                {"name": "source_uri", "type": "Edm.String", "searchable": False, "filterable": True, "retrievable": True},
                {"name": "blob_path", "type": "Edm.String", "searchable": False, "filterable": True, "retrievable": True},
                {"name": "content_markdown", "type": "Edm.String", "searchable": True, "retrievable": True},
                {"name": "content_markdown_raw", "type": "Edm.String", "searchable": False, "retrievable": True},
                {"name": "split_chunks", "type": "Collection(Edm.String)", "searchable": True, "retrievable": True},
                {"name": "prompt_seed_text", "type": "Edm.String", "searchable": True, "retrievable": True},
                {"name": "summary_text", "type": "Edm.String", "searchable": True, "retrievable": True},
                {"name": "keyword_hints_raw", "type": "Edm.String", "searchable": True, "retrievable": True},
                {"name": "image_description_text", "type": "Edm.String", "searchable": True, "retrievable": True},
                {"name": "image_description_chunks", "type": "Collection(Edm.String)", "searchable": True, "retrievable": True},
                {"name": "ocr_text_chunks", "type": "Collection(Edm.String)", "searchable": True, "retrievable": True},
                {"name": "table_description_text", "type": "Edm.String", "searchable": True, "retrievable": True},
                {"name": "detected_language", "type": "Edm.String", "filterable": True, "retrievable": True},
                {"name": "figure_locations_json", "type": "Edm.String", "searchable": False, "retrievable": True},
                {"name": "rbac_scope_ids", "type": "Collection(Edm.String)", "searchable": False, "filterable": True, "retrievable": True},
                {"name": "last_updated", "type": "Edm.DateTimeOffset", "filterable": True, "sortable": True, "retrievable": True},
            ],
            "semantic": {
                "defaultConfiguration": "default-semantic-config",
                "configurations": [
                    {
                        "name": "default-semantic-config",
                        "prioritizedFields": {
                            "titleField": {"fieldName": "source_name"},
                            "prioritizedContentFields": [
                                {"fieldName": "summary_text"},
                                {"fieldName": "content_markdown"},
                                {"fieldName": "image_description_text"},
                            ],
                            "prioritizedKeywordsFields": [{"fieldName": "keyword_hints_raw"}],
                        },
                    }
                ],
            },
        }
        if settings.azure_search_enable_integrated_vectorization and settings.azure_openai_embedding_deployment:
            body["fields"].append(
                {
                    "name": settings.azure_search_vector_field_name,
                    "type": "Collection(Edm.Single)",
                    "searchable": True,
                    "retrievable": True,
                    "dimensions": settings.azure_search_vector_dimensions,
                    "vectorSearchProfile": "content-vector-profile",
                }
            )
            body["vectorSearch"] = {
                "algorithms": [
                    {
                        "name": "content-vector-hnsw",
                        "kind": "hnsw",
                        "hnswParameters": {
                            "metric": "cosine",
                            "m": 4,
                            "efConstruction": 400,
                            "efSearch": 500,
                        },
                    }
                ],
                "profiles": [
                    {
                        "name": "content-vector-profile",
                        "algorithm": "content-vector-hnsw",
                        "vectorizer": "content-vectorizer",
                    }
                ],
                "vectorizers": [
                    {
                        "name": "content-vectorizer",
                        "kind": "azureOpenAI",
                        "azureOpenAIParameters": {
                            "resourceUri": settings.azure_foundry_openai_base_url,
                            "deploymentId": settings.azure_openai_embedding_deployment,
                            "modelName": settings.azure_openai_embedding_model_name,
                        },
                    }
                ],
            }
        return body

    def _build_data_source_body(self, *, doc_id: str, data_source_name: str) -> dict[str, Any]:
        container = {
            "name": settings.azure_search_blob_source_container,
        }
        blob_query = self._blob_query_for_document(doc_id)
        if blob_query:
            container["query"] = blob_query
        return {
            "name": data_source_name,
            "type": "azureblob",
            "credentials": {
                "connectionString": settings.azure_search_blob_connection_string_resolved,
            },
            "container": container,
        }

    def _build_skillset_body(
        self,
        *,
        profile: WorkshopSkillProfile | None = None,
        prompt_skill_kind: str = "chat_completion",
        include_cache: bool = True,
    ) -> dict[str, Any]:
        active_profile = profile or self._active_profile()
        include_prompt_skills = prompt_skill_kind != "none"
        extractor_kind = self._active_extractor_kind(profile=active_profile)
        skills: list[dict[str, Any]] = [self._build_extractor_skill(extractor_kind=extractor_kind)]
        if extractor_kind == "content_understanding":
            # The Content Understanding skill emits chunked `text_sections` rather than a
            # single content string, so merge them into /document/content_markdown to feed
            # the same downstream graph (prompt seed, summary, keywords, embeddings).
            skills.append(self._build_content_understanding_merge_skill())
        if self._profile_uses_split(active_profile):
            skills.append(self._build_split_skill())
        if self._profile_uses_visual_nlp(active_profile):
            skills.extend(
                [
                    self._build_ocr_skill(),
                    self._build_image_analysis_skill(),
                    self._build_language_detection_skill(),
                ]
            )
        if self._profile_uses_embedding(active_profile):
            skills.extend(
                [
                    self._build_prompt_seed_split_skill(),
                    self._build_prompt_seed_merge_skill(),
                ]
            )
        if include_prompt_skills and settings.azure_foundry_chat_enabled:
            skills.extend(
                [
                    self._build_summary_prompt_skill(
                        prompt_skill_kind=prompt_skill_kind,
                        text_source="/document/prompt_seed_text",
                    ),
                    self._build_keywords_prompt_skill(
                        prompt_skill_kind=prompt_skill_kind,
                        text_source="/document/summary_text",
                    ),
                ]
            )
        if (
            self._profile_uses_embedding(active_profile)
            and settings.azure_search_enable_integrated_vectorization
            and settings.azure_openai_embedding_deployment
        ):
            skills.append(
                self._build_embedding_skill(
                    text_source="/document/summary_text"
                    if include_prompt_skills
                    else "/document/prompt_seed_text"
                )
            )

        skillset: dict[str, Any] = {
            "name": self._target_skillset_name(active_profile),
            "description": (
                f"Workshop profile '{active_profile.id}' for Blob-backed enrichment, "
                "progressively adding built-in Azure AI Search skills."
            ),
            "skills": skills,
        }
        if settings.azure_foundry_resource_endpoint:
            skillset["cognitiveServices"] = {
                "@odata.type": "#Microsoft.Azure.Search.AIServicesByIdentity",
                "description": "Billable Foundry resource attached to the skillset for built-in skill execution.",
                "subdomainUrl": settings.azure_foundry_resource_endpoint.rstrip("/"),
            }
        elif settings.azure_foundry_api_key:
            skillset["cognitiveServices"] = {
                "@odata.type": "#Microsoft.Azure.Search.CognitiveServicesByKey",
                "description": "Billable Foundry resource attached to the skillset for built-in skill execution.",
                "key": settings.azure_foundry_api_key,
            }
        return skillset

    def _active_extractor_kind(self, *, profile: WorkshopSkillProfile | None = None) -> str:
        active_profile = profile or self._active_profile()
        wants_content_understanding = (
            active_profile.id == "content_understanding"
            or settings.azure_search_skillset_preferred_extractor == "content_understanding"
        )
        if wants_content_understanding:
            if settings.azure_content_understanding_skill_available:
                return "content_understanding"
            if settings.workshop_strict_mode:
                raise RuntimeError(
                    "The workshop profile requires the Azure Content Understanding skill, "
                    "but no billable Foundry resource is attached to the Search skillset. "
                    "Set AZURE_FOUNDRY_RESOURCE_ENDPOINT (preferred, managed identity) "
                    "or AZURE_FOUNDRY_API_KEY so the resource-attached skill can run."
                )
        return "document_extraction"

    def _build_extractor_skill(self, *, extractor_kind: str | None = None) -> dict[str, Any]:
        active_extractor = extractor_kind or self._active_extractor_kind()
        if active_extractor == "content_understanding":
            # GA `#Microsoft.Skills.Util.ContentUnderstandingSkill` is resource-attached:
            # it binds to the billable Foundry resource declared in the skillset's
            # `cognitiveServices` block (AIServicesByIdentity / managed identity) and
            # therefore takes no resourceUri/apiKey/analyzerName. It performs semantic,
            # layout-aware chunking internally and returns `text_sections`, which we merge
            # into /document/content_markdown for the downstream enrichment graph.
            return {
                "@odata.type": "#Microsoft.Skills.Util.ContentUnderstandingSkill",
                "name": "#contentUnderstanding",
                "context": "/document",
                "description": "Resource-attached Azure Content Understanding extractor with semantic, layout-aware chunking for multimodal Blob enrichment.",
                "extractionOptions": ["locationMetadata"],
                "chunkingProperties": {
                    "method": "semantic",
                    "unit": "tokens",
                    "maximumLength": 500,
                },
                "inputs": [{"name": "file_data", "source": "/document/file_data"}],
                "outputs": [
                    {"name": "text_sections", "targetName": "cu_text_sections"},
                ],
            }
        return {
            "@odata.type": "#Microsoft.Skills.Util.DocumentExtractionSkill",
            "name": "#documentExtraction",
            "context": "/document",
            "description": "Workshop-default Search-managed extraction for Blob enrichment.",
            "dataToExtract": "contentAndMetadata",
            "configuration": {
                "imageAction": "generateNormalizedImages",
            },
            "inputs": [{"name": "file_data", "source": "/document/file_data"}],
            "outputs": [
                {"name": "content", "targetName": "content_markdown"},
            ],
        }

    def _build_split_skill(self) -> dict[str, Any]:
        return {
            "@odata.type": "#Microsoft.Skills.Text.SplitSkill",
            "name": "#splitContent",
            "context": "/document",
            "textSplitMode": "pages",
            "maximumPageLength": 1500,
            "pageOverlapLength": 150,
            "inputs": [{"name": "text", "source": "/document/content_markdown"}],
            "outputs": [{"name": "textItems", "targetName": "split_chunks"}],
        }

    def _build_content_understanding_merge_skill(self) -> dict[str, Any]:
        return {
            "@odata.type": "#Microsoft.Skills.Text.MergeSkill",
            "name": "#mergeContentUnderstanding",
            "context": "/document",
            "insertPreTag": "",
            "insertPostTag": "\n\n",
            "inputs": [
                {"name": "itemsToInsert", "source": "/document/cu_text_sections/*/content"}
            ],
            "outputs": [{"name": "mergedText", "targetName": "content_markdown"}],
        }

    def _build_prompt_seed_split_skill(self) -> dict[str, Any]:
        return {
            "@odata.type": "#Microsoft.Skills.Text.SplitSkill",
            "name": "#splitPromptSeed",
            "context": "/document",
            "textSplitMode": "pages",
            "maximumPageLength": max(400, settings.azure_search_prompt_seed_page_length),
            "pageOverlapLength": max(0, settings.azure_search_prompt_seed_page_overlap),
            "maximumPagesToTake": max(1, settings.azure_search_prompt_seed_pages_to_take),
            "inputs": [{"name": "text", "source": "/document/content_markdown"}],
            "outputs": [{"name": "textItems", "targetName": "prompt_seed_chunks"}],
        }

    def _build_prompt_seed_merge_skill(self) -> dict[str, Any]:
        return {
            "@odata.type": "#Microsoft.Skills.Text.MergeSkill",
            "name": "#mergePromptSeed",
            "context": "/document",
            "insertPreTag": "",
            "insertPostTag": "\n\n",
            "inputs": [{"name": "itemsToInsert", "source": "/document/prompt_seed_chunks/*"}],
            "outputs": [{"name": "mergedText", "targetName": "prompt_seed_text"}],
        }

    def _build_ocr_skill(self) -> dict[str, Any]:
        return {
            "@odata.type": "#Microsoft.Skills.Vision.OcrSkill",
            "name": "#ocrImages",
            "context": "/document/normalized_images/*",
            "defaultLanguageCode": "en",
            "detectOrientation": True,
            "inputs": [{"name": "image", "source": "/document/normalized_images/*"}],
            "outputs": [{"name": "text", "targetName": "ocr_text_chunks"}],
        }

    def _build_image_analysis_skill(self) -> dict[str, Any]:
        return {
            "@odata.type": "#Microsoft.Skills.Vision.ImageAnalysisSkill",
            "name": "#imageAnalysis",
            "context": "/document/normalized_images/*",
            "defaultLanguageCode": "en",
            "visualFeatures": ["tags", "description"],
            "inputs": [{"name": "image", "source": "/document/normalized_images/*"}],
            "outputs": [{"name": "description", "targetName": "image_description_chunks"}],
        }

    def _build_language_detection_skill(self) -> dict[str, Any]:
        return {
            "@odata.type": "#Microsoft.Skills.Text.LanguageDetectionSkill",
            "name": "#languageDetection",
            "context": "/document",
            "inputs": [{"name": "text", "source": "/document/content_markdown"}],
            "outputs": [{"name": "languageCode", "targetName": "detected_language"}],
        }

    def _chat_completion_skill_uri(self, deployment_id: str) -> str:
        base_url = settings.azure_foundry_openai_base_url.rstrip("/")
        return f"{base_url}/openai/deployments/{deployment_id}/chat/completions?api-version=2024-10-21"

    def _prompt_skill_deployment(self) -> str:
        return settings.azure_search_llm_deployment or settings.azure_foundry_chat_deployment

    def _literal_source(self, value: str) -> str:
        escaped = " ".join(value.split()).replace("'", "''")
        return f"='{escaped}'"

    def _is_gpt5_deployment(self, deployment_id: str) -> bool:
        return deployment_id.strip().lower().startswith("gpt-5")

    def _build_prompt_skill(
        self,
        *,
        name: str,
        target_name: str,
        system_message: str,
        user_message: str,
        prompt_skill_kind: str,
        text_source: str,
    ) -> dict[str, Any]:
        if prompt_skill_kind != "chat_completion":
            raise RuntimeError("This workshop requires ChatCompletionSkill for Search-managed enrichment prompts.")
        deployment_id = self._prompt_skill_deployment()
        if not deployment_id:
            raise RuntimeError("AZURE_SEARCH_LLM_DEPLOYMENT or AZURE_FOUNDRY_CHAT_DEPLOYMENT must be configured.")
        skill: dict[str, Any] = {
            "@odata.type": "#Microsoft.Skills.Custom.ChatCompletionSkill",
            "name": name,
            "context": "/document",
            "uri": self._chat_completion_skill_uri(deployment_id),
            "inputs": [
                {"name": "text", "source": text_source},
                {"name": "systemMessage", "source": self._literal_source(system_message)},
                {"name": "userMessage", "source": self._literal_source(user_message)},
            ],
            "outputs": [{"name": "response", "targetName": target_name}],
            "responseFormat": {"type": "text"},
        }
        if not self._is_gpt5_deployment(deployment_id):
            skill["commonModelParameters"] = {
                "temperature": 0.1,
                "maxTokens": 256 if target_name == "summary_text" else 180,
            }
        return skill

    def _build_summary_prompt_skill(
        self,
        *,
        prompt_skill_kind: str = "chat_completion",
        text_source: str = "/document/content_markdown",
    ) -> dict[str, Any]:
        return self._build_prompt_skill(
            name="#summaryPrompt",
            target_name="summary_text",
            system_message=(
                "You create concise retrieval summaries for Azure AI Search enrichment pipelines. "
                "Stay factual, preserve important document sections, and retain figure or table signals when present."
            ),
            user_message=(
                "Summarize the provided document content in 120 words or fewer for enterprise retrieval. "
                "Do not invent facts."
            ),
            prompt_skill_kind=prompt_skill_kind,
            text_source=text_source,
        )

    def _build_keywords_prompt_skill(
        self,
        *,
        prompt_skill_kind: str = "chat_completion",
        text_source: str = "/document/content_markdown",
    ) -> dict[str, Any]:
        return self._build_prompt_skill(
            name="#keywordPrompt",
            target_name="keyword_hints_raw",
            system_message=(
                "You create retrieval tags for Azure AI Search enrichment. "
                "Return strict JSON arrays only, with short domain tags useful for retrieval."
            ),
            user_message=(
                "Return up to 12 retrieval tags as a JSON array of strings only. "
                "Focus on domain nouns, document type, diagrams, and operational themes."
            ),
            prompt_skill_kind=prompt_skill_kind,
            text_source=text_source,
        )

    def _build_embedding_skill(self, *, text_source: str = "/document/summary_text") -> dict[str, Any]:
        skill = {
            "@odata.type": "#Microsoft.Skills.Text.AzureOpenAIEmbeddingSkill",
            "name": "#contentEmbedding",
            "context": "/document",
            "resourceUri": settings.azure_foundry_openai_base_url,
            "deploymentId": settings.azure_openai_embedding_deployment,
            "modelName": settings.azure_openai_embedding_model_name,
            "dimensions": settings.azure_search_vector_dimensions,
            "inputs": [{"name": "text", "source": text_source}],
            "outputs": [{"name": "embedding", "targetName": settings.azure_search_vector_field_name}],
        }
        if settings.azure_foundry_api_key and not settings.azure_search_llm_use_managed_identity:
            skill["apiKey"] = settings.azure_foundry_api_key
        return skill

    def _build_indexer_body(
        self,
        *,
        data_source_name: str | None = None,
        indexer_name: str | None = None,
        profile: WorkshopSkillProfile | None = None,
        prompt_skill_kind: str = "chat_completion",
    ) -> dict[str, Any]:
        active_profile = profile or self._active_profile()
        include_prompt_skills = prompt_skill_kind != "none"
        extractor_kind = self._active_extractor_kind(profile=active_profile)
        body: dict[str, Any] = {
            "name": indexer_name or settings.azure_search_blob_indexer_name,
            "dataSourceName": data_source_name or settings.azure_search_blob_data_source_name,
            "targetIndexName": self._target_index_name(active_profile),
            "skillsetName": self._target_skillset_name(active_profile),
            "fieldMappings": [
                {
                    "sourceFieldName": "metadata_storage_path",
                    "targetFieldName": "doc_key",
                    "mappingFunction": {"name": "base64Encode"},
                },
                {"sourceFieldName": "metadata_docid", "targetFieldName": "doc_id"},
                {"sourceFieldName": "metadata_skillprofile", "targetFieldName": "skill_profile_id"},
                {"sourceFieldName": "metadata_storage_name", "targetFieldName": "source_name"},
                {"sourceFieldName": "metadata_storage_path", "targetFieldName": "source_uri"},
                {"sourceFieldName": "metadata_storage_path", "targetFieldName": "blob_path"},
                {"sourceFieldName": "metadata_storage_last_modified", "targetFieldName": "last_updated"},
            ],
            "outputFieldMappings": [],
            "parameters": {
                "configuration": {
                    "dataToExtract": "contentAndMetadata",
                    "allowSkillsetToReadFileData": True,
                    "imageAction": "generateNormalizedImages",
                    "parsingMode": "default",
                    "failOnUnsupportedContentType": False,
                    "indexedFileNameExtensions": ".pdf,.docx,.pptx,.txt,.md,.html",
                }
            },
        }
        if settings.azure_search_enable_enrichment_cache and settings.azure_search_enrichment_cache_connection_string:
            body["cache"] = {
                "storageConnectionString": settings.azure_search_enrichment_cache_connection_string,
                "enableReprocessing": True,
            }
        if extractor_kind == "content_understanding":
            # Content Understanding already returns semantically chunked `text_sections`.
            # Project each chunk's content as a Collection (one small term per chunk) rather
            # than the merged full-document string, which would exceed the 32,766-byte
            # single-term limit when indexed. The merged /document/content_markdown still
            # feeds the prompt-seed/summary/keyword/embedding skills as an enrichment node.
            body["outputFieldMappings"].append(
                {"sourceFieldName": "/document/cu_text_sections/*/content", "targetFieldName": "split_chunks"}
            )
        if self._profile_uses_split(active_profile):
            body["outputFieldMappings"].append(
                {"sourceFieldName": "/document/split_chunks", "targetFieldName": "split_chunks"}
            )
        if include_prompt_skills:
            body["outputFieldMappings"].extend(
                [
                    {"sourceFieldName": "/document/prompt_seed_text", "targetFieldName": "prompt_seed_text"},
                    {"sourceFieldName": "/document/summary_text", "targetFieldName": "summary_text"},
                    {"sourceFieldName": "/document/keyword_hints_raw", "targetFieldName": "keyword_hints_raw"},
                ]
            )
        if self._profile_uses_visual_nlp(active_profile):
            body["outputFieldMappings"].extend(
                [
                    {"sourceFieldName": "/document/ocr_text_chunks", "targetFieldName": "ocr_text_chunks"},
                    {
                        "sourceFieldName": "/document/image_description_chunks",
                        "targetFieldName": "image_description_chunks",
                    },
                    {"sourceFieldName": "/document/detected_language", "targetFieldName": "detected_language"},
                ]
            )
        if (
            self._profile_uses_embedding(active_profile)
            and settings.azure_search_enable_integrated_vectorization
            and settings.azure_openai_embedding_deployment
        ):
            body["outputFieldMappings"].append(
                {
                    "sourceFieldName": f"/document/{settings.azure_search_vector_field_name}",
                    "targetFieldName": settings.azure_search_vector_field_name,
                }
            )
        if settings.azure_search_enable_blob_rbac:
            body["fieldMappings"].append(
                {
                    "sourceFieldName": "metadata_rbacscopeids",
                    "targetFieldName": settings.azure_search_blob_rbac_metadata_field,
                }
            )
        return body

    def _ensure_enrichment_index(self, *, profile: WorkshopSkillProfile | None = None) -> None:
        active_profile = profile or self._active_profile()
        url = f"{self.endpoint}/indexes/{self._target_index_name(active_profile)}?api-version=2025-09-01"
        body = self._build_enrichment_index_body(profile=active_profile)
        response = self._request_with_conflict_retry("PUT", url, body=body)
        if response.status_code >= 400 and "CannotChangeExistingField" in response.text:
            self._delete_enrichment_index(profile=active_profile)
            response = self._request_with_conflict_retry("PUT", url, body=body)
        self._raise_for_status(response)

    def _delete_enrichment_index(self, *, profile: WorkshopSkillProfile | None = None) -> None:
        active_profile = profile or self._active_profile()
        url = f"{self.endpoint}/indexes/{self._target_index_name(active_profile)}?api-version=2025-09-01"
        response = requests.delete(url, headers=self.headers, timeout=self._search_timeout())
        if response.status_code == 404:
            return
        self._raise_for_status(response)

    def _ensure_data_source(self, *, data_source_name: str, body: dict[str, Any]) -> None:
        url = f"{self.endpoint}/datasources/{data_source_name}?api-version={settings.azure_search_indexer_api_version}"
        response = self._request_with_conflict_retry("PUT", url, body=body)
        self._raise_for_status(response)

    def _put_skillset(
        self,
        body: dict[str, Any],
        *,
        profile: WorkshopSkillProfile | None = None,
        api_version: str,
    ) -> None:
        active_profile = profile or self._active_profile()
        url = f"{self.endpoint}/skillsets/{self._target_skillset_name(active_profile)}?api-version={api_version}"
        response = self._request_with_conflict_retry("PUT", url, body=body)
        self._raise_for_status(response)

    def _ensure_skillset(self, *, profile: WorkshopSkillProfile | None = None) -> None:
        active_profile = profile or self._active_profile()
        api_version = settings.azure_search_indexer_api_version
        prompt_skill_kind = (
            "chat_completion"
            if self._profile_uses_prompt_enrichment(active_profile) and settings.azure_foundry_chat_enabled
            else "none"
        )
        self._put_skillset(
            self._build_skillset_body(
                profile=active_profile,
                prompt_skill_kind=prompt_skill_kind,
                include_cache=True,
            ),
            profile=active_profile,
            api_version=api_version,
        )
        self._last_skillset_selection = {
            "api_version": api_version,
            "prompt_skill_kind": prompt_skill_kind,
            "cache_mode": "indexer_cache",
            "workshop_profile_id": active_profile.id,
        }

    def _ensure_indexer(
        self,
        *,
        indexer_name: str,
        body: dict[str, Any],
        profile: WorkshopSkillProfile | None = None,
    ) -> None:
        active_profile = profile or self._active_profile()
        url = f"{self.endpoint}/indexers/{indexer_name}?api-version={settings.azure_search_indexer_api_version}"
        prompt_skill_kind = self._last_skillset_selection.get("prompt_skill_kind") or "chat_completion"
        indexer_body = self._build_indexer_body(
            data_source_name=body["dataSourceName"],
            indexer_name=indexer_name,
            profile=active_profile,
            prompt_skill_kind=prompt_skill_kind,
        )
        response = self._request_with_conflict_retry("PUT", url, body=indexer_body)
        self._raise_for_status(response)

    def _run_indexer(self, *, indexer_name: str, max_attempts: int = 24) -> None:
        url = f"{self.endpoint}/indexers/{indexer_name}/search.run?api-version={settings.azure_search_indexer_api_version}"
        for attempt in range(max_attempts):
            response = requests.post(
                url,
                headers=self.headers,
                data=json.dumps({}),
                timeout=self._search_timeout(),
            )
            if response.status_code < 400:
                return
            detail = response.text.strip().lower()
            if response.status_code == 409 and "currently in progress" in detail:
                sleep(min(5 + attempt, 15))
                continue
            self._raise_for_status(response)
        raise RuntimeError(
            "Azure AI Search Blob indexer could not start because another indexer invocation "
            "kept the service busy."
        )

    def _run_indexer_with_retry(self, *, indexer_name: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        attempts = max(1, settings.azure_search_indexer_transient_retry_attempts)
        retry_history: list[dict[str, Any]] = []
        last_payload: dict[str, Any] = {}
        for attempt in range(1, attempts + 1):
            self._reset_indexer(indexer_name=indexer_name)
            self._run_indexer(indexer_name=indexer_name)
            payload = self._poll_indexer(indexer_name=indexer_name)
            last_payload = payload
            retryable, retry_detail = self._retryable_indexer_failure_detail(payload)
            retry_history.append(
                {
                    "attempt": attempt,
                    "retryable": retryable,
                    "detail": retry_detail,
                    "status": str(((payload.get("lastResult") or {}).get("status") or "")).lower(),
                }
            )
            if not retryable or attempt >= attempts:
                return payload, retry_history
            sleep(
                min(
                    120,
                    max(1, settings.azure_search_indexer_transient_retry_base_delay_seconds) * (2 ** (attempt - 1)),
                )
            )
        return last_payload, retry_history

    def _reset_indexer(self, *, indexer_name: str) -> None:
        url = f"{self.endpoint}/indexers/{indexer_name}/search.reset?api-version={settings.azure_search_indexer_api_version}"
        response = requests.post(
            url,
            headers=self.headers,
            data=json.dumps({}),
            timeout=self._search_timeout(),
        )
        self._raise_for_status(response)

    def _poll_indexer(self, *, indexer_name: str, max_attempts: int = 90) -> dict[str, Any]:
        url = f"{self.endpoint}/indexers/{indexer_name}/status?api-version={settings.azure_search_indexer_api_version}"
        last_payload: dict[str, Any] = {}
        for _ in range(max_attempts):
            response = requests.get(url, headers=self.headers, timeout=self._search_timeout())
            self._raise_for_status(response)
            payload = response.json()
            last_payload = payload
            status = str((payload.get("lastResult") or {}).get("status") or "").lower()
            if status in {"success", "transientfailure", "error"}:
                return payload
            sleep(2)
        return last_payload

    def _raise_if_indexer_failed(self, payload: dict[str, Any]) -> None:
        last_result = payload.get("lastResult") or {}
        status = str(last_result.get("status") or "").lower()
        if status == "success":
            return
        errors = last_result.get("errors") or []
        if errors:
            first_error = errors[0]
            skill_name = str(first_error.get("name") or "").strip()
            detail = str(
                first_error.get("details")
                or first_error.get("errorMessage")
                or last_result.get("errorMessage")
                or status
            ).strip()
            if skill_name:
                message = f"{skill_name}: {detail}"
            else:
                message = detail
        else:
            message = str(last_result.get("errorMessage") or status or "unknown indexer failure")
        raise RuntimeError(f"Azure AI Search Blob indexer ended with status '{status}': {message}")

    def _retryable_indexer_failure_detail(self, payload: dict[str, Any]) -> tuple[bool, str]:
        last_result = payload.get("lastResult") or {}
        status = str(last_result.get("status") or "").lower()
        if status != "transientfailure":
            return False, ""
        # Azure AI Search has already classified this run as `transientFailure`, which by
        # definition means a retry may succeed. Skill-execution flakes from the attached
        # model service surface here as a transientFailure whose wrapper statusCode is 400
        # ("Web Api skill response is invalid") while the underlying detail carries the real
        # transient signal (e.g. InternalServerError / server_error). The original allow-list
        # only matched 429/503 throttling, so a single transient 5xx failed the whole
        # document under strict mode and forced a full manual re-upload. Broaden the match.
        transient_status_codes = {408, 429, 500, 502, 503, 504}
        transient_signatures = (
            "too many requests",
            "toomanyrequests",
            "internalservererror",
            "internal server error",
            "server_error",
            "server had an error",
            "web api skill response is invalid",
            "service unavailable",
            "serviceunavailable",
            "bad gateway",
            "gateway timeout",
            "timed out",
            "timeout",
        )
        errors = last_result.get("errors") or []
        for error in errors:
            detail = str(error.get("details") or error.get("errorMessage") or "").strip()
            combined = " ".join(
                str(value or "")
                for value in (error.get("errorMessage"), error.get("details"), error.get("message"))
            ).lower()
            status_code = int(error.get("statusCode") or 0)
            if status_code in transient_status_codes or any(sig in combined for sig in transient_signatures):
                return True, detail or combined.strip()
        # A transientFailure with no per-error detail is, by the service's own
        # classification, safe to retry.
        if not errors:
            return True, "transientFailure reported with no error detail"
        return False, ""

    def _is_conflicting_update_response(self, response: requests.Response) -> bool:
        if response.status_code != 409:
            return False
        detail = response.text.strip().lower()
        return "conflicting update" in detail and "no change was made to the resource" in detail

    def _fetch_document_enrichment(
        self,
        doc_id: str,
        blob_url: str | None,
        *,
        profile: WorkshopSkillProfile | None = None,
    ) -> dict[str, Any]:
        active_profile = profile or self._active_profile()
        url = f"{self.endpoint}/indexes/{self._target_index_name(active_profile)}/docs/search?api-version=2025-09-01"
        escaped_doc_id = doc_id.replace("'", "''")
        filter_clauses = [f"doc_id eq '{escaped_doc_id}'"]
        if blob_url:
            escaped_blob_url = blob_url.replace("'", "''")
            filter_clauses.append(f"source_uri eq '{escaped_blob_url}'")
        payload = {
            "search": "*",
            "top": 1,
            "select": (
                "doc_id,skill_profile_id,source_name,source_uri,content_markdown,content_markdown_raw,split_chunks,prompt_seed_text,summary_text,"
                "keyword_hints_raw,image_description_text,image_description_chunks,ocr_text_chunks,"
                "table_description_text,detected_language,figure_locations_json,rbac_scope_ids"
            ),
            "filter": " or ".join(filter_clauses),
        }
        for attempt in range(1, 9):
            response = self._request_with_conflict_retry(
                "POST",
                url,
                body=payload,
                max_attempts=6,
                timeout=self._search_timeout(),
            )
            self._raise_for_status(response)
            value = response.json().get("value") or []
            for item in value:
                if isinstance(item, dict):
                    return item
            sleep(min(20, 2 * attempt))
        return {}

    def _apply_enrichment_to_document(
        self,
        intermediate: IntermediateDocument,
        chunks: list[ChunkRecord],
        extracted_fields: dict[str, Any],
        blob_upload: dict[str, Any],
    ) -> None:
        if not extracted_fields:
            intermediate.metadata["search_skillset_blob"] = {
                "status": "no_results",
                "blob_upload": blob_upload,
            }
            return
        extracted_fields = self._supplement_enrichment_with_foundry(extracted_fields)
        if not extracted_fields.get("doc_id"):
            extracted_fields["doc_id"] = intermediate.doc_id
        if not extracted_fields.get("source_name"):
            extracted_fields["source_name"] = intermediate.source_name
        blob_url = str(blob_upload.get("blob_url") or "").strip() or None
        summary_text = str(extracted_fields.get("summary_text") or "").strip() or None
        prompt_seed_text = str(extracted_fields.get("prompt_seed_text") or "").strip() or None
        image_description_chunks = self._normalize_string_list(extracted_fields.get("image_description_chunks"))
        if image_description_chunks and not extracted_fields.get("image_description_text"):
            extracted_fields["image_description_text"] = " ".join(image_description_chunks[:6])
        image_description_text = str(extracted_fields.get("image_description_text") or "").strip() or None
        split_chunks = self._normalize_string_list(extracted_fields.get("split_chunks"))
        ocr_text_chunks = self._normalize_string_list(extracted_fields.get("ocr_text_chunks"))
        detected_language = str(extracted_fields.get("detected_language") or "").strip() or None
        keyword_hints = self._normalize_string_list(
            extracted_fields.get("keyword_hints_raw") or extracted_fields.get("keyword_hints")
        )
        rbac_scope_ids = self._normalize_string_list(extracted_fields.get("rbac_scope_ids"))
        if not rbac_scope_ids and settings.azure_search_default_rbac_scope_ids:
            rbac_scope_ids = list(settings.azure_search_default_rbac_scope_ids)
        if blob_url:
            intermediate.source_uri = blob_url
        intermediate.metadata["search_skillset_blob"] = {
            "status": "completed",
            "blob_upload": blob_upload,
            "skill_profile_id": extracted_fields.get("skill_profile_id") or settings.workshop_skill_profile,
            "prompt_seed_text": prompt_seed_text,
            "summary_text": summary_text,
            "split_chunk_count": len(split_chunks),
            "keyword_hints": keyword_hints,
            "image_description_text": image_description_text,
            "image_description_chunks": image_description_chunks,
            "ocr_text_chunks": ocr_text_chunks,
            "detected_language": detected_language,
            "table_description_text": extracted_fields.get("table_description_text"),
            "figure_locations_json": extracted_fields.get("figure_locations_json"),
            "rbac_scope_ids": rbac_scope_ids,
        }
        if summary_text and summary_text not in intermediate.warnings:
            intermediate.metadata["enrichment_summary_available"] = True
        for chunk in chunks:
            chunk.source_uri = chunk.source_uri or blob_url
            chunk.summary_text = summary_text
            chunk.image_description_text = image_description_text
            if keyword_hints:
                chunk.keyword_hints = sorted(set([*chunk.keyword_hints, *keyword_hints]))
                chunk.tags = sorted(set([*chunk.tags, *keyword_hints]))
            if detected_language:
                chunk.tags = sorted(set([*chunk.tags, detected_language]))
            if rbac_scope_ids:
                chunk.rbac_scope_ids = rbac_scope_ids

    def _supplement_enrichment_with_foundry(self, extracted_fields: dict[str, Any]) -> dict[str, Any]:
        if not settings.azure_search_allow_foundry_enrichment_supplement:
            return extracted_fields
        content_markdown = str(
            extracted_fields.get("content_markdown_raw") or extracted_fields.get("content_markdown") or ""
        ).strip()
        if not content_markdown or not settings.azure_foundry_chat_enabled:
            return extracted_fields
        summary_text = str(extracted_fields.get("summary_text") or "").strip()
        keyword_hints = self._normalize_string_list(
            extracted_fields.get("keyword_hints_raw") or extracted_fields.get("keyword_hints")
        )
        if summary_text and keyword_hints:
            return extracted_fields

        try:
            answer, _ = call_foundry_text(
                [
                    {
                        "role": "system",
                        "content": (
                            "You enrich enterprise retrieval records. Return strict JSON only with keys "
                            "summary_text and keyword_hints. summary_text must be under 120 words. "
                            "keyword_hints must be a JSON array with up to 12 short retrieval tags."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "Summarize this extracted document content for enterprise retrieval and generate "
                            "retrieval tags.\n\n"
                            f"{content_markdown[:12000]}"
                        ),
                    },
                ],
                max_completion_tokens=300,
            )
            normalized = answer.strip()
            match = re.search(r"\{.*\}", normalized, flags=re.DOTALL)
            if match:
                normalized = match.group(0)
            payload = json.loads(normalized)
        except Exception:
            return extracted_fields
        if not isinstance(payload, dict):
            return extracted_fields

        supplemented = dict(extracted_fields)
        fallback_summary = payload.get("summary_text")
        fallback_keywords = payload.get("keyword_hints")
        if isinstance(fallback_summary, str) and fallback_summary.strip():
            supplemented["summary_text"] = fallback_summary.strip()
        if isinstance(fallback_keywords, list):
            normalized_keywords = self._normalize_string_list(fallback_keywords)
            if normalized_keywords:
                supplemented["keyword_hints_raw"] = json.dumps(normalized_keywords)
        return supplemented

    def _normalize_string_list(self, value: Any) -> list[str]:
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                parsed = [part.strip() for part in value.split(",")]
            value = parsed
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                continue
            entry = item.strip()
            if not entry or entry in seen:
                continue
            seen.add(entry)
            normalized.append(entry)
        return normalized

    def _raise_for_status(self, response: requests.Response) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = response.text.strip()
            if detail:
                raise RuntimeError(
                    f"{response.status_code} {response.reason} from Azure AI Search enrichment lane: {detail}"
                ) from exc
            raise


blob_skillset_enrichment = AzureSearchSkillsetEnrichmentService()
