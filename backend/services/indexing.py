from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from time import sleep
from typing import Any

import requests

from backend.core.config import SearchKnowledgeSourceConfig, settings
from backend.domain.models import ChunkRecord, PublishStatus
from backend.services.foundry_openai import embed_texts_with_foundry
from backend.services.workshop_profiles import get_workshop_skill_profile

logger = logging.getLogger(__name__)
DIRECT_SEARCH_TOP = 8
DIRECT_VECTOR_K = 8
EMBEDDING_BATCH_SIZE = 12
MAX_VECTOR_TEXT_LENGTH = 6000

ROUTING_STOPWORDS = {
    "about",
    "after",
    "against",
    "answer",
    "asked",
    "corpus",
    "data",
    "document",
    "documents",
    "explain",
    "from",
    "index",
    "indexes",
    "into",
    "knowledge",
    "query",
    "report",
    "reports",
    "search",
    "show",
    "source",
    "sources",
    "tell",
    "that",
    "their",
    "them",
    "these",
    "those",
    "what",
    "which",
    "with",
    "would",
}


class FoundryIQAdapter:
    def publish(
        self,
        chunks: list[ChunkRecord],
        *,
        source_name: str | None = None,
        route_text: str | None = None,
    ) -> PublishStatus:
        raise NotImplementedError

    def get_status(self) -> PublishStatus:
        raise NotImplementedError

    def chat(
        self,
        question: str,
        *,
        doc_ids: list[str] | None = None,
        doc_source_assignments: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def direct_search(
        self,
        question: str,
        *,
        retrieval_mode: str,
        doc_ids: list[str] | None = None,
        doc_source_assignments: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError

    def delete_chunks(self, chunks: list[ChunkRecord], *, index_name: str | None = None) -> None:
        raise NotImplementedError


class LocalPreviewAdapter(FoundryIQAdapter):
    def publish(
        self,
        chunks: list[ChunkRecord],
        *,
        source_name: str | None = None,
        route_text: str | None = None,
    ) -> PublishStatus:
        return PublishStatus(
            mode="local_preview",
            resource="Azure AI Search Knowledge Base",
            ready=True,
            last_sync_time=datetime.now(timezone.utc).isoformat(),
            indexed_document_count=len({chunk.doc_id for chunk in chunks}),
            indexed_chunk_count=len(chunks),
            message="Azure Search is not configured. Using local retrieval preview for chat.",
        )

    def get_status(self) -> PublishStatus:
        return PublishStatus(
            mode="local_preview",
            resource="Azure AI Search Knowledge Base",
            ready=False,
            message="Azure Search is not configured. Configure it to publish a real knowledge base.",
        )

    def chat(
        self,
        question: str,
        *,
        doc_ids: list[str] | None = None,
        doc_source_assignments: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return {
            "answer": "Azure Search is not configured. Local preview mode can only answer over ingested chunks stored in the app.",
            "citations": [],
            "diagnostics": {"mode": "local_preview", "question": question, "selected_doc_ids": doc_ids or []},
        }

    def direct_search(
        self,
        question: str,
        *,
        retrieval_mode: str,
        doc_ids: list[str] | None = None,
        doc_source_assignments: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return self.chat(question, doc_ids=doc_ids, doc_source_assignments=doc_source_assignments)

    def delete_chunks(self, chunks: list[ChunkRecord], *, index_name: str | None = None) -> None:
        return


class AzureSearchKnowledgeBaseAdapter(FoundryIQAdapter):
    def __init__(self) -> None:
        self.endpoint = settings.azure_search_endpoint.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
            "api-key": settings.azure_search_key,
            "Prefer": "return=representation",
        }
        self.api_version = settings.azure_search_api_version

    @property
    def _is_preview_api(self) -> bool:
        return "preview" in self.api_version

    def publish(
        self,
        chunks: list[ChunkRecord],
        *,
        source_name: str | None = None,
        route_text: str | None = None,
    ) -> PublishStatus:
        target_source, assignment_diagnostics = self._select_target_source_for_document(
            source_name=source_name,
            route_text=route_text,
        )
        self._ensure_indexes()
        self._upload_chunks(chunks, target_source.index_name)
        if self.api_version in {"2026-04-01", "2025-11-01-preview", "2026-05-01-preview"}:
            self._ensure_knowledge_sources()
            self._ensure_knowledge_base()
        publishable_sources = self._publishable_knowledge_sources()
        retrieval_sources = self._retrieval_knowledge_sources()
        return PublishStatus(
            mode="search_knowledge_base",
            resource=settings.azure_search_knowledge_base_name,
            ready=True,
            last_sync_time=datetime.now(timezone.utc).isoformat(),
            indexed_document_count=len({chunk.doc_id for chunk in chunks}),
            indexed_chunk_count=len(chunks),
            message="Chunks published to Azure AI Search and associated knowledge base resources ensured.",
            diagnostics={
                "index_name": target_source.index_name,
                "knowledge_source_name": target_source.knowledge_source_name,
                "knowledge_base_name": settings.azure_search_knowledge_base_name,
                "index_names": [source.index_name for source in publishable_sources],
                "knowledge_source_names": [source.knowledge_source_name for source in publishable_sources],
                "retrieval_index_names": [source.index_name for source in retrieval_sources],
                "retrieval_knowledge_source_names": [source.knowledge_source_name for source in retrieval_sources],
                "multi_index_enabled": len(publishable_sources) > 1,
                "answer_synthesis_enabled": settings.azure_search_enable_answer_synthesis,
                "blob_skillset_source_enabled": bool(
                    settings.azure_search_include_enrichment_source_in_chat and self._enrichment_knowledge_source()
                ),
                **assignment_diagnostics,
            },
        )

    def get_status(self) -> PublishStatus:
        if not settings.azure_search_enabled:
            return LocalPreviewAdapter().get_status()
        publishable_sources = self._publishable_knowledge_sources()
        retrieval_sources = self._retrieval_knowledge_sources()
        return PublishStatus(
            mode="search_knowledge_base",
            resource=settings.azure_search_knowledge_base_name,
            ready=True,
            message="Azure Search knowledge base publishing is configured.",
            diagnostics={
                "index_name": settings.azure_search_index_name,
                "knowledge_source_name": settings.azure_search_knowledge_source_name,
                "knowledge_base_name": settings.azure_search_knowledge_base_name,
                "index_names": [source.index_name for source in publishable_sources],
                "knowledge_source_names": [source.knowledge_source_name for source in publishable_sources],
                "retrieval_index_names": [source.index_name for source in retrieval_sources],
                "retrieval_knowledge_source_names": [source.knowledge_source_name for source in retrieval_sources],
                "multi_index_enabled": len(publishable_sources) > 1,
                "answer_synthesis_enabled": settings.azure_search_enable_answer_synthesis,
                "blob_skillset_source_enabled": bool(
                    settings.azure_search_include_enrichment_source_in_chat and self._enrichment_knowledge_source()
                ),
            },
        )

    def chat(
        self,
        question: str,
        *,
        doc_ids: list[str] | None = None,
        doc_source_assignments: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        selected_sources, routing_diagnostics = self._route_knowledge_sources(
            question,
            doc_ids=doc_ids,
            doc_source_assignments=doc_source_assignments,
            include_enrichment=True,
        )
        grouped_doc_ids = self._group_doc_ids_by_source(doc_ids or [], doc_source_assignments or {})
        knowledge_source_params = [
            self._build_knowledge_source_params(
                source,
                doc_ids=grouped_doc_ids.get(source.knowledge_source_name),
                force_query=len(selected_sources) > 1 or bool(doc_ids),
            )
            for source in selected_sources
        ]
        payload = self._build_retrieve_payload(question, knowledge_source_params)
        url = (
            f"{self.endpoint}/knowledgebases('{settings.azure_search_knowledge_base_name}')/retrieve"
            f"?api-version={self.api_version}"
        )
        response = self._post_retrieve_with_retry(url=url, payload=payload)
        self._raise_for_status(response)
        result = response.json()
        diagnostics = result.setdefault("diagnostics", {})
        diagnostics["selected_doc_ids"] = doc_ids or []
        diagnostics["corpus_mode"] = "custom" if doc_ids else "auto"
        diagnostics["agentic_retrieval"] = True
        diagnostics["search_method"] = "agentic"
        diagnostics.update(routing_diagnostics)
        return result

    def direct_search(
        self,
        question: str,
        *,
        retrieval_mode: str,
        doc_ids: list[str] | None = None,
        doc_source_assignments: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        normalized_mode = retrieval_mode.strip().lower()
        if normalized_mode not in {"full_text", "vector", "hybrid"}:
            raise RuntimeError(f"Unsupported direct retrieval mode: {retrieval_mode}")
        if normalized_mode in {"vector", "hybrid"} and not self._vector_search_available():
            raise RuntimeError(
                "Vector and hybrid retrieval require AZURE_OPENAI_EMBEDDING_DEPLOYMENT and a configured Foundry OpenAI endpoint."
            )

        selected_sources, routing_diagnostics = self._route_knowledge_sources(
            question,
            doc_ids=doc_ids,
            doc_source_assignments=doc_source_assignments,
            include_enrichment=False,
        )
        grouped_doc_ids = self._group_doc_ids_by_source(doc_ids or [], doc_source_assignments or {})
        query_vector: list[float] | None = None
        if normalized_mode in {"vector", "hybrid"}:
            embeddings, _ = embed_texts_with_foundry([question], deployment_id=settings.azure_openai_embedding_deployment)
            query_vector = embeddings[0]

        results: list[dict[str, Any]] = []
        activity: list[dict[str, Any]] = []
        for step, source in enumerate(selected_sources, start=1):
            scoped_doc_ids = grouped_doc_ids.get(source.knowledge_source_name) if grouped_doc_ids else None
            payload, elapsed_ms = self._run_direct_search(
                source=source,
                question=question,
                retrieval_mode=normalized_mode,
                doc_ids=scoped_doc_ids,
                query_vector=query_vector,
            )
            values = payload.get("value") or []
            activity.append(
                {
                    "type": "searchIndex",
                    "id": step,
                    "knowledgeSourceName": source.knowledge_source_name,
                    "count": len(values),
                    "elapsedMs": elapsed_ms,
                    "searchIndexArguments": {
                        "search": question,
                    },
                    "searchMode": normalized_mode,
                }
            )
            for item in values:
                if not isinstance(item, dict):
                    continue
                snippet = item.get("clean_text") or ""
                captions = item.get("@search.captions") or []
                if isinstance(captions, list) and captions:
                    first_caption = captions[0]
                    if isinstance(first_caption, dict) and isinstance(first_caption.get("text"), str):
                        snippet = first_caption["text"]
                results.append(
                    {
                        **item,
                        "snippet": snippet,
                        "knowledgeSourceName": source.knowledge_source_name,
                        "index_name": source.index_name,
                        "supporting_query": question,
                    }
                )

        results.sort(key=lambda item: float(item.get("@search.score") or 0), reverse=True)
        diagnostics = {
            **routing_diagnostics,
            "mode": f"{normalized_mode}_search",
            "search_method": normalized_mode,
            "agentic_retrieval": False,
            "corpus_mode": "custom" if doc_ids else "auto",
            "selected_doc_ids": doc_ids or [],
            "activity": activity,
        }
        return {
            "results": results[: max(DIRECT_SEARCH_TOP * max(1, len(selected_sources)), DIRECT_SEARCH_TOP)],
            "diagnostics": diagnostics,
        }

    def delete_chunks(self, chunks: list[ChunkRecord], *, index_name: str | None = None) -> None:
        if not chunks:
            return
        target_index = index_name or settings.azure_search_index_name
        url = f"{self.endpoint}/indexes/{target_index}/docs/index?api-version=2025-09-01"
        actions = [{"@search.action": "delete", "chunk_id": chunk.chunk_id} for chunk in chunks]
        response = requests.post(url, headers=self.headers, data=json.dumps({"value": actions}), timeout=60)
        self._raise_for_status(response)

    def _ensure_indexes(self) -> None:
        for source in self._publishable_knowledge_sources():
            self._ensure_index(source.index_name)

    def _ensure_index(self, index_name: str) -> None:
        url = f"{self.endpoint}/indexes/{index_name}?api-version=2025-09-01"
        fields: list[dict[str, Any]] = [
            {"name": "chunk_id", "type": "Edm.String", "key": True, "searchable": False, "filterable": True},
            {"name": "doc_id", "type": "Edm.String", "searchable": False, "filterable": True},
            {"name": "source_name", "type": "Edm.String", "searchable": True, "filterable": True, "retrievable": True},
            {"name": "source_uri", "type": "Edm.String", "searchable": False, "filterable": True, "retrievable": True},
            {"name": "section_path", "type": "Collection(Edm.String)", "searchable": True, "retrievable": True},
            {"name": "page_numbers", "type": "Collection(Edm.Int32)", "filterable": True, "retrievable": True},
            {"name": "content_type", "type": "Edm.String", "filterable": True, "retrievable": True},
            {"name": "tags", "type": "Collection(Edm.String)", "filterable": True, "retrievable": True},
            {"name": "checksum", "type": "Edm.String", "filterable": True, "retrievable": True},
            {"name": "last_updated", "type": "Edm.DateTimeOffset", "filterable": True, "sortable": True, "retrievable": True},
            {"name": "clean_text", "type": "Edm.String", "searchable": True, "retrievable": True},
            {"name": "summary_text", "type": "Edm.String", "searchable": True, "retrievable": True},
            {"name": "keyword_hints", "type": "Collection(Edm.String)", "searchable": True, "filterable": True, "retrievable": True},
            {"name": "image_description_text", "type": "Edm.String", "searchable": True, "retrievable": True},
            {"name": "rbac_scope_ids", "type": "Collection(Edm.String)", "searchable": False, "filterable": True, "retrievable": True},
            {"name": "image_evidence_json", "type": "Edm.String", "searchable": False, "retrievable": True},
        ]
        if self._vector_search_available():
            fields.append(
                {
                    "name": settings.azure_search_vector_field_name,
                    "type": "Collection(Edm.Single)",
                    "searchable": True,
                    "retrievable": False,
                    "dimensions": settings.azure_search_vector_dimensions,
                    "vectorSearchProfile": "content-vector-profile",
                }
            )

        body: dict[str, Any] = {
            "name": index_name,
            "fields": fields,
            "semantic": {
                "defaultConfiguration": "default-semantic-config",
                "configurations": [
                    {
                        "name": "default-semantic-config",
                        "prioritizedFields": {
                            "titleField": {"fieldName": "source_name"},
                            "prioritizedContentFields": [
                                {"fieldName": "summary_text"},
                                {"fieldName": "clean_text"},
                                {"fieldName": "image_description_text"},
                            ],
                            "prioritizedKeywordsFields": [{"fieldName": "keyword_hints"}, {"fieldName": "tags"}],
                        },
                    }
                ],
            },
        }
        if self._vector_search_available():
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
                    }
                ],
            }
        response = requests.put(url, headers=self.headers, data=json.dumps(body), timeout=60)
        self._raise_for_status(response)

    def _upload_chunks(self, chunks: list[ChunkRecord], index_name: str | None = None) -> None:
        target_index = index_name or settings.azure_search_index_name
        url = f"{self.endpoint}/indexes/{target_index}/docs/index?api-version=2025-09-01"
        embeddings_by_chunk_id = self._embed_chunks_for_index(chunks) if self._vector_search_available() else {}
        actions = []
        for chunk in chunks:
            action = {
                "@search.action": "mergeOrUpload",
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "source_name": chunk.source_name,
                "source_uri": chunk.source_uri,
                "section_path": chunk.section_path,
                "page_numbers": chunk.page_numbers,
                "content_type": chunk.content_type,
                "tags": chunk.tags,
                "checksum": chunk.checksum,
                "last_updated": chunk.last_updated,
                "clean_text": chunk.clean_text,
                "summary_text": chunk.summary_text,
                "keyword_hints": chunk.keyword_hints,
                "image_description_text": chunk.image_description_text,
                "rbac_scope_ids": chunk.rbac_scope_ids,
                "image_evidence_json": json.dumps(chunk.image_evidence),
            }
            if chunk.chunk_id in embeddings_by_chunk_id:
                action[settings.azure_search_vector_field_name] = embeddings_by_chunk_id[chunk.chunk_id]
            actions.append(action)
        response = requests.post(url, headers=self.headers, data=json.dumps({"value": actions}), timeout=60)
        self._raise_for_status(response)

    def _vector_search_available(self) -> bool:
        return bool(
            settings.azure_openai_embedding_deployment
            and settings.azure_foundry_openai_base_url
        )

    def _chunk_embedding_text(self, chunk: ChunkRecord) -> str:
        keyword_text = ", ".join(chunk.keyword_hints[:12])
        parts = [
            f"Source: {chunk.source_name}",
            f"Section: {' > '.join(chunk.section_path)}" if chunk.section_path else "",
            f"Summary: {chunk.summary_text}" if chunk.summary_text else "",
            f"Keywords: {keyword_text}" if keyword_text else "",
            f"Image description: {chunk.image_description_text}" if chunk.image_description_text else "",
            f"Content: {chunk.clean_text}",
        ]
        combined = "\n".join(part for part in parts if part).strip()
        return combined[:MAX_VECTOR_TEXT_LENGTH]

    def _embed_chunks_for_index(self, chunks: list[ChunkRecord]) -> dict[str, list[float]]:
        if not chunks:
            return {}
        embeddings_by_chunk_id: dict[str, list[float]] = {}
        for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
            batch = chunks[start : start + EMBEDDING_BATCH_SIZE]
            inputs = [self._chunk_embedding_text(chunk) for chunk in batch]
            embeddings, _ = embed_texts_with_foundry(inputs, deployment_id=settings.azure_openai_embedding_deployment)
            for chunk, embedding in zip(batch, embeddings):
                embeddings_by_chunk_id[chunk.chunk_id] = embedding
        return embeddings_by_chunk_id

    def _ensure_knowledge_sources(self) -> None:
        for source in self._retrieval_knowledge_sources():
            self._ensure_knowledge_source(source)

    def _ensure_knowledge_source(self, source: SearchKnowledgeSourceConfig) -> None:
        url = (
            f"{self.endpoint}/knowledgesources('{source.knowledge_source_name}')"
            f"?api-version={self.api_version}"
        )
        body = {
            "name": source.knowledge_source_name,
            "kind": "searchIndex",
            "searchIndexParameters": {
                "searchIndexName": source.index_name,
                "semanticConfigurationName": source.semantic_configuration_name,
                "sourceDataFields": [
                    {"name": field_name}
                    for field_name in source.source_data_fields
                ],
                "searchFields": [
                    {"name": field_name}
                    for field_name in source.search_fields
                ],
            },
        }
        response = requests.put(url, headers=self.headers, data=json.dumps(body), timeout=60)
        self._raise_for_status(response)

    def _ensure_knowledge_base(self) -> None:
        url = (
            f"{self.endpoint}/knowledgebases('{settings.azure_search_knowledge_base_name}')"
            f"?api-version={self.api_version}"
        )
        body = self._knowledge_base_body()
        response = requests.put(url, headers=self.headers, data=json.dumps(body), timeout=60)
        self._raise_for_status(response)

        if self._is_preview_api and settings.azure_search_llm_enabled:
            current = self._get_knowledge_base(settings.azure_search_knowledge_base_name)
            models = current.get("models") if isinstance(current, dict) else None
            if not models:
                self._delete_knowledge_base(settings.azure_search_knowledge_base_name)
                recreate = requests.put(url, headers=self.headers, data=json.dumps(body), timeout=60)
                self._raise_for_status(recreate)

    def _knowledge_base_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": settings.azure_search_knowledge_base_name,
            "knowledgeSources": [
                {"name": source.knowledge_source_name}
                for source in self._retrieval_knowledge_sources()
            ],
        }
        if self._is_preview_api and settings.azure_search_llm_enabled:
            azure_openai_parameters: dict[str, Any] = {
                "resourceUri": settings.azure_foundry_openai_base_url,
                "deploymentId": settings.azure_search_llm_deployment,
                "modelName": settings.azure_search_llm_model_name or settings.azure_search_llm_deployment,
            }
            if not settings.azure_search_llm_use_managed_identity:
                azure_openai_parameters["apiKey"] = settings.azure_foundry_api_key
            body["models"] = [
                {
                    "kind": "azureOpenAI",
                    "azureOpenAIParameters": azure_openai_parameters,
                }
            ]
            body["retrievalReasoningEffort"] = {"kind": settings.azure_search_llm_reasoning_effort}
            body["outputMode"] = (
                "answerSynthesis" if settings.azure_search_enable_answer_synthesis else "extractiveData"
            )
            if settings.azure_search_enable_answer_synthesis and settings.azure_search_answer_instructions:
                body["answerInstructions"] = settings.azure_search_answer_instructions
        return body

    def _get_knowledge_base(self, knowledge_base_name: str) -> dict[str, Any]:
        url = f"{self.endpoint}/knowledgebases('{knowledge_base_name}')?api-version={self.api_version}"
        response = requests.get(url, headers=self.headers, timeout=60)
        if response.status_code == 404:
            return {}
        self._raise_for_status(response)
        return response.json()

    def _delete_knowledge_base(self, knowledge_base_name: str) -> None:
        url = f"{self.endpoint}/knowledgebases('{knowledge_base_name}')?api-version={self.api_version}"
        response = requests.delete(url, headers=self.headers, timeout=60)
        if response.status_code not in {200, 204, 404}:
            self._raise_for_status(response)

    def _build_doc_filter(self, doc_ids: list[str]) -> str:
        unique_ids: list[str] = []
        seen = set()
        for doc_id in doc_ids:
            normalized = str(doc_id).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique_ids.append(normalized)
        clauses = []
        for value in unique_ids:
            escaped = value.replace("'", "''")
            clauses.append(f"doc_id eq '{escaped}'")
        return " or ".join(clauses)

    def _direct_search_select_fields(self) -> str:
        return ",".join(
            [
                "chunk_id",
                "doc_id",
                "source_name",
                "source_uri",
                "section_path",
                "page_numbers",
                "clean_text",
                "summary_text",
                "keyword_hints",
                "image_description_text",
                "image_evidence_json",
            ]
        )

    def _build_direct_search_body(
        self,
        *,
        question: str,
        retrieval_mode: str,
        filter_expression: str,
        query_vector: list[float] | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "top": DIRECT_SEARCH_TOP,
            "count": True,
            "select": self._direct_search_select_fields(),
        }
        if filter_expression:
            body["filter"] = filter_expression

        if retrieval_mode == "full_text":
            body["search"] = question
            return body

        if retrieval_mode == "vector":
            body["search"] = "*"
            body["vectorQueries"] = [
                {
                    "kind": "vector",
                    "vector": query_vector,
                    "fields": settings.azure_search_vector_field_name,
                    "k": DIRECT_VECTOR_K,
                }
            ]
            return body

        body["search"] = question
        body["vectorQueries"] = [
            {
                "kind": "vector",
                "vector": query_vector,
                "fields": settings.azure_search_vector_field_name,
                "k": DIRECT_VECTOR_K,
            }
        ]
        return body

    def _run_direct_search(
        self,
        *,
        source: SearchKnowledgeSourceConfig,
        question: str,
        retrieval_mode: str,
        doc_ids: list[str] | None,
        query_vector: list[float] | None,
    ) -> tuple[dict[str, Any], int]:
        filter_expression = self._build_doc_filter(doc_ids or [])
        body = self._build_direct_search_body(
            question=question,
            retrieval_mode=retrieval_mode,
            filter_expression=filter_expression,
            query_vector=query_vector,
        )
        url = f"{self.endpoint}/indexes/{source.index_name}/docs/search?api-version=2025-09-01"
        response = requests.post(url, headers=self.headers, data=json.dumps(body), timeout=60)
        self._raise_for_status(response)
        payload = response.json()
        elapsed_ms = int(response.elapsed.total_seconds() * 1000) if response.elapsed else 0
        return payload, elapsed_ms

    def _primary_knowledge_source(self) -> SearchKnowledgeSourceConfig:
        return SearchKnowledgeSourceConfig(
            knowledge_source_name=settings.azure_search_knowledge_source_name,
            index_name=settings.azure_search_index_name,
            description="Primary application corpus index for uploaded and generated documents.",
        )

    def _publishable_knowledge_sources(self) -> list[SearchKnowledgeSourceConfig]:
        sources: list[SearchKnowledgeSourceConfig] = []
        seen_names: set[str] = set()
        for source in (self._primary_knowledge_source(), *settings.azure_search_extra_sources):
            if source.knowledge_source_name in seen_names:
                continue
            seen_names.add(source.knowledge_source_name)
            sources.append(source)
        return sources

    def _enrichment_knowledge_source(self) -> SearchKnowledgeSourceConfig | None:
        if not (
            settings.azure_search_include_enrichment_source_in_chat
            and settings.azure_search_blob_ingestion_enabled
        ):
            return None
        active_profile = get_workshop_skill_profile()
        profile_suffix = active_profile.id.replace("_", "-")
        knowledge_source_name = settings.azure_search_enrichment_knowledge_source_name
        if not knowledge_source_name.endswith(f"-{profile_suffix}"):
            knowledge_source_name = f"{knowledge_source_name}-{profile_suffix}"
        return SearchKnowledgeSourceConfig(
            knowledge_source_name=knowledge_source_name,
            index_name=active_profile.target_index_name,
            description=(
                f"Blob + skillset enrichment index for the '{active_profile.title}' workshop profile, carrying "
                "document summaries, image descriptions, table descriptions, and other Search-managed "
                "enrichment outputs."
            ),
            route_keywords=(
                "abstract",
                "caption",
                "chart",
                "diagram",
                "figure",
                "image",
                "overview",
                "summary",
                "table",
                "visual",
            ),
            semantic_configuration_name="default-semantic-config",
            source_data_fields=(
                "doc_id",
                "summary_text",
                "content_markdown",
                "source_name",
                "source_uri",
                "keyword_hints_raw",
                "image_description_text",
                "table_description_text",
                "figure_locations_json",
                "rbac_scope_ids",
            ),
            search_fields=("*",),
        )

    def _retrieval_knowledge_sources(self) -> list[SearchKnowledgeSourceConfig]:
        sources = list(self._publishable_knowledge_sources())
        enrichment_source = self._enrichment_knowledge_source()
        if enrichment_source and all(
            source.knowledge_source_name != enrichment_source.knowledge_source_name for source in sources
        ):
            sources.append(enrichment_source)
        return sources

    def _build_knowledge_source_params(
        self,
        source: SearchKnowledgeSourceConfig,
        *,
        doc_ids: list[str] | None,
        force_query: bool,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "knowledgeSourceName": source.knowledge_source_name,
            "kind": "searchIndex",
            "includeReferences": True,
            "includeReferenceSourceData": True,
        }
        if doc_ids:
            params["filterAddOn"] = self._build_doc_filter(doc_ids)
        if self._is_preview_api and force_query:
            params["alwaysQuerySource"] = True
        return params

    def _route_knowledge_sources(
        self,
        question: str,
        *,
        doc_ids: list[str] | None = None,
        doc_source_assignments: dict[str, str] | None = None,
        include_enrichment: bool = True,
    ) -> tuple[list[SearchKnowledgeSourceConfig], dict[str, Any]]:
        configured_sources = self._retrieval_knowledge_sources()
        publishable_sources = self._publishable_knowledge_sources()
        enrichment_source = self._enrichment_knowledge_source()
        source_by_name = {source.knowledge_source_name: source for source in configured_sources}
        diagnostics: dict[str, Any] = {
            "available_knowledge_sources": [source.knowledge_source_name for source in configured_sources],
            "available_search_indexes": [source.index_name for source in configured_sources],
            "knowledge_source_index_map": {
                source.knowledge_source_name: source.index_name
                for source in configured_sources
            },
            "knowledge_source_match_details": [],
        }
        if doc_ids:
            grouped_doc_ids = self._group_doc_ids_by_source(doc_ids, doc_source_assignments or {})
            selected = [
                source_by_name[source_name]
                for source_name in grouped_doc_ids
                if source_name in source_by_name
            ]
            if not selected:
                selected = [self._primary_knowledge_source()]
            question_lower = question.lower()
            tokens = self._tokenize_routing_text(question_lower)
            if include_enrichment and enrichment_source and self._should_include_enrichment_source(question_lower, tokens):
                selected.append(enrichment_source)
            diagnostics.update(
                {
                    "routing_mode": "custom_doc_scope",
                    "routing_reason": "Custom corpus selection is grouped by the assigned knowledge source for each selected document.",
                    "selected_knowledge_sources": [source.knowledge_source_name for source in selected],
                    "selected_search_indexes": [source.index_name for source in selected],
                    "multi_index_routing": len(selected) > 1,
                    "custom_scope_groups": grouped_doc_ids,
                }
            )
            return selected, diagnostics
        if len(publishable_sources) == 1 and not enrichment_source:
            primary = publishable_sources[0]
            diagnostics.update(
                {
                    "routing_mode": "single_index",
                    "routing_reason": "No extra Azure AI Search knowledge sources are configured.",
                    "selected_knowledge_sources": [primary.knowledge_source_name],
                    "selected_search_indexes": [primary.index_name],
                    "multi_index_routing": False,
                }
            )
            return [primary], diagnostics

        question_lower = question.lower()
        tokens = self._tokenize_routing_text(question_lower)
        cross_source_intent = self._has_cross_source_intent(question_lower, tokens)
        matched_sources: list[SearchKnowledgeSourceConfig] = []
        match_details: list[dict[str, Any]] = []
        for source in configured_sources:
            matched_terms = self._matched_routing_terms(question_lower, tokens, source)
            if matched_terms:
                matched_sources.append(source)
            match_details.append(
                {
                    "knowledge_source_name": source.knowledge_source_name,
                    "index_name": source.index_name,
                    "matched_terms": matched_terms,
                }
            )
        diagnostics["knowledge_source_match_details"] = match_details

        if cross_source_intent:
            selected = publishable_sources
            diagnostics.update(
                {
                    "routing_mode": "cross_source_intent",
                    "routing_reason": "The question contains compare or cross-source language, so all configured corpus indexes were included.",
                }
            )
        elif matched_sources:
            selected = matched_sources
            diagnostics.update(
                {
                    "routing_mode": "keyword_routed",
                    "routing_reason": "The question matched source routing hints or published corpus terms, so those indexes were selected.",
                }
            )
        elif len(publishable_sources) <= settings.azure_search_auto_broadcast_limit:
            selected = publishable_sources
            diagnostics.update(
                {
                    "routing_mode": "broad_auto",
                    "routing_reason": (
                        "No source-specific hint matched, so the app broadcast the query across all configured indexes "
                        f"because the source count is within the auto-broadcast limit of {settings.azure_search_auto_broadcast_limit}."
                    ),
                }
            )
        else:
            selected = [self._primary_knowledge_source()]
            diagnostics.update(
                {
                    "routing_mode": "primary_default",
                    "routing_reason": "No source-specific hint matched and the source count exceeds the broadcast limit, so the query stayed on the primary application index.",
                }
            )

        if (
            include_enrichment
            and
            enrichment_source
            and enrichment_source not in selected
            and self._should_include_enrichment_source(question_lower, tokens)
        ):
            selected = [*selected, enrichment_source]
            diagnostics["routing_reason"] = (
                f"{diagnostics['routing_reason']} The Blob skillset enrichment index was also included because the "
                "question appears to ask for summaries, diagrams, images, or other enrichment-heavy signals."
            )
        if include_enrichment and enrichment_source and any(
            source.knowledge_source_name == enrichment_source.knowledge_source_name for source in selected
        ):
            primary = self._primary_knowledge_source()
            has_publishable_source = any(
                source.knowledge_source_name != enrichment_source.knowledge_source_name for source in selected
            )
            if not has_publishable_source:
                selected = [primary, *selected]

        diagnostics["selected_knowledge_sources"] = [source.knowledge_source_name for source in selected]
        diagnostics["selected_search_indexes"] = [source.index_name for source in selected]
        diagnostics["multi_index_routing"] = len(selected) > 1
        return selected, diagnostics

    def _select_target_source_for_document(
        self, *, source_name: str | None = None, route_text: str | None = None
    ) -> tuple[SearchKnowledgeSourceConfig, dict[str, Any]]:
        primary = self._primary_knowledge_source()
        extra_sources = [
            source
            for source in self._publishable_knowledge_sources()
            if source.knowledge_source_name != primary.knowledge_source_name
        ]
        source_name_text = (source_name or "").lower()
        route_text_value = (route_text or "").lower()
        combined_text = " ".join(part for part in [source_name_text, route_text_value] if part).strip()
        if not combined_text or not extra_sources:
            return primary, {
                "assignment_mode": "primary_default",
                "assignment_matches": [],
            }

        tokens = self._tokenize_routing_text(combined_text)
        source_name_tokens = self._tokenize_routing_text(source_name_text)
        best_source = primary
        best_matches: list[str] = []
        best_score = 0
        for source in extra_sources:
            name_matches = self._matched_assignment_terms(source_name_text, source_name_tokens, source)
            context_matches = self._matched_assignment_terms(combined_text, tokens, source)
            score = (len(name_matches) * 3) + len(context_matches)
            eligible = bool(name_matches) or len(context_matches) >= 2
            if eligible and score > best_score:
                best_source = source
                best_matches = name_matches or context_matches
                best_score = score

        if best_source == primary:
            return primary, {
                "assignment_mode": "primary_default",
                "assignment_matches": [],
            }
        return best_source, {
            "assignment_mode": "keyword_assigned",
            "assignment_matches": best_matches,
        }

    def _group_doc_ids_by_source(
        self, doc_ids: list[str], doc_source_assignments: dict[str, str]
    ) -> dict[str, list[str]]:
        primary_source_name = settings.azure_search_knowledge_source_name
        grouped: dict[str, list[str]] = {}
        for doc_id in doc_ids:
            source_name = doc_source_assignments.get(doc_id) or primary_source_name
            grouped.setdefault(source_name, []).append(doc_id)
        return grouped

    def _build_retrieve_payload(
        self, question: str, knowledge_source_params: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if self._is_preview_api and settings.azure_search_llm_enabled:
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
                "maxRuntimeInSeconds": 20,
                "maxOutputSize": 100000,
                "includeActivity": True,
                "outputMode": (
                    "answerSynthesis" if settings.azure_search_enable_answer_synthesis else "extractiveData"
                ),
                "retrievalReasoningEffort": {"kind": settings.azure_search_llm_reasoning_effort},
                "knowledgeSourceParams": knowledge_source_params,
            }
            return payload
        return {
            "intents": [
                {
                    "type": "semantic",
                    "search": question,
                }
            ],
            "maxRuntimeInSeconds": 20,
            "includeActivity": True,
            "knowledgeSourceParams": knowledge_source_params,
        }

    def _post_retrieve_with_retry(self, *, url: str, payload: dict[str, Any]) -> requests.Response:
        attempts = max(1, settings.azure_search_retrieve_retry_attempts)
        response: requests.Response | None = None
        for attempt in range(1, attempts + 1):
            response = requests.post(url, headers=self.headers, data=json.dumps(payload), timeout=90)
            if not self._is_model_throttle_response(response) or attempt >= attempts:
                return response
            sleep(
                min(
                    30,
                    max(1, settings.azure_search_retrieve_retry_base_delay_seconds) * (2 ** (attempt - 1)),
                )
            )
        assert response is not None
        return response

    def _is_model_throttle_response(self, response: requests.Response) -> bool:
        if response.status_code != 429:
            return False
        detail = response.text.strip().lower()
        return "too many requests" in detail or "could not complete model action" in detail

    def _tokenize_routing_text(self, text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]{3,}", text.lower())
            if token not in ROUTING_STOPWORDS
        }

    def _has_cross_source_intent(self, question_lower: str, tokens: set[str]) -> bool:
        compare_tokens = {
            "across",
            "between",
            "both",
            "combine",
            "combined",
            "compare",
            "comparison",
            "contradict",
            "contradiction",
            "cross",
            "different",
            "difference",
            "synthesize",
            "versus",
        }
        compare_phrases = (
            "side by side",
            "compare with",
            "compare across",
            "use both",
            "use all",
            "across the indexes",
            "across indexes",
            "across sources",
        )
        if tokens & compare_tokens:
            return True
        return any(phrase in question_lower for phrase in compare_phrases)

    def _should_include_enrichment_source(self, question_lower: str, tokens: set[str]) -> bool:
        enrichment_terms = {
            "abstract",
            "caption",
            "chart",
            "diagram",
            "figure",
            "image",
            "overview",
            "summary",
            "table",
            "visual",
        }
        if tokens & enrichment_terms:
            return True
        phrases = (
            "show me a diagram",
            "show me the figure",
            "summarize",
            "high level summary",
            "visual evidence",
        )
        return any(phrase in question_lower for phrase in phrases)

    def _matched_routing_terms(
        self, question_lower: str, tokens: set[str], source: SearchKnowledgeSourceConfig
    ) -> list[str]:
        matches: list[str] = []
        for keyword in source.route_keywords:
            if (" " in keyword and keyword in question_lower) or keyword in tokens:
                matches.append(keyword)

        for label in (source.knowledge_source_name, source.index_name):
            normalized = label.lower().replace("_", " ").replace("-", " ").strip()
            if normalized and normalized in question_lower:
                matches.append(normalized)

        descriptor_terms = self._descriptor_terms_for_source(source)
        descriptor_hits = [
            term
            for term in sorted(tokens & descriptor_terms)
            if len(term) >= 5
        ]
        if descriptor_hits:
            matches.extend(descriptor_hits[:4])

        document_hits = [
            term
            for term in sorted(tokens & self._published_document_terms_for_source(source.knowledge_source_name))
            if len(term) >= 5
        ]
        if document_hits:
            matches.extend(document_hits[:4])

        unique_matches: list[str] = []
        seen: set[str] = set()
        for match in matches:
            if match in seen:
                continue
            seen.add(match)
            unique_matches.append(match)
        return unique_matches

    def _descriptor_terms_for_source(self, source: SearchKnowledgeSourceConfig) -> set[str]:
        descriptor = " ".join(
            filter(None, [source.knowledge_source_name, source.index_name, source.description])
        ).lower()
        return {
            term
            for term in re.findall(r"[a-z0-9]{3,}", descriptor)
            if term not in ROUTING_STOPWORDS
        }

    def _matched_assignment_terms(
        self, document_text: str, tokens: set[str], source: SearchKnowledgeSourceConfig
    ) -> list[str]:
        matches: list[str] = []
        assignment_keywords = source.assignment_keywords or source.route_keywords
        for keyword in assignment_keywords:
            if (" " in keyword and keyword in document_text) or keyword in tokens:
                matches.append(keyword)

        unique_matches: list[str] = []
        seen: set[str] = set()
        for match in matches:
            if match in seen:
                continue
            seen.add(match)
            unique_matches.append(match)
        return unique_matches

    def _published_document_terms_for_source(self, knowledge_source_name: str) -> set[str]:
        from backend.services.job_store import job_store

        terms: set[str] = set()
        for job in job_store.list_jobs():
            if job.status.value != "ready":
                continue
            publish_diagnostics = job.publish_status.diagnostics or {}
            source_name = publish_diagnostics.get("knowledge_source_name") or settings.azure_search_knowledge_source_name
            if source_name != knowledge_source_name:
                continue
            terms.update(self._tokenize_routing_text(job.file_name))
        return terms

    def _raise_for_status(self, response: requests.Response) -> None:
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            detail = response.text.strip()
            if detail:
                raise RuntimeError(
                    f"{response.status_code} {response.reason} from Azure AI Search: {detail}"
                ) from exc
            raise


def build_foundry_adapter() -> FoundryIQAdapter:
    if settings.azure_search_enabled:
        return AzureSearchKnowledgeBaseAdapter()
    return LocalPreviewAdapter()
