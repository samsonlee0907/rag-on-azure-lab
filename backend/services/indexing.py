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

# Lab 04 scoring-profile demonstration. These named profiles are attached to the
# canonical index so the chat UI can switch the BM25-layer relevance behavior at
# query time and show how scoring profiles reorder full-text and hybrid results.
# "default" means "send no scoringProfile", i.e. rely on RRF + the semantic
# ranker exactly as the earlier labs do.
DIRECT_SEARCH_DEFAULT_SCORING_PROFILE = "default"
SCORING_PROFILE_ENRICHMENT_WEIGHTED = "enrichment-weighted"
SCORING_PROFILE_FRESHNESS_BOOSTED = "freshness-boosted"
DIRECT_SEARCH_SCORING_PROFILES = {
    DIRECT_SEARCH_DEFAULT_SCORING_PROFILE,
    SCORING_PROFILE_ENRICHMENT_WEIGHTED,
    SCORING_PROFILE_FRESHNESS_BOOSTED,
}

EMBEDDING_BATCH_SIZE = 12
EMBEDDING_RETRY_ATTEMPTS = 4
EMBEDDING_RETRY_BASE_DELAY_SECONDS = 20
MAX_VECTOR_TEXT_LENGTH = 6000
SEARCH_INDEX_BATCH_MAX_ACTIONS = 100
SEARCH_INDEX_BATCH_MAX_BYTES = 4_000_000

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

DIRECT_SEARCH_SNIPPET_STOPWORDS = ROUTING_STOPWORDS | {
    "are",
    "basic",
    "can",
    "components",
    "groups",
    "placed",
    "three",
    "types",
}

DIRECT_SEARCH_NAVIGATION_TERMS = {
    "chapter",
    "chapters",
    "contents",
    "find",
    "locate",
    "overview",
    "page",
    "pages",
    "section",
    "sections",
    "where",
}

DIRECT_SEARCH_VISUAL_TERMS = {
    "architecture",
    "blueprint",
    "callout",
    "chart",
    "diagram",
    "figure",
    "graph",
    "image",
    "label",
    "labels",
    "layout",
    "map",
    "photo",
    "plan",
    "visual",
}

SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+")


def _question_terms(question: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9'\-]{2,}", question.lower()):
        if token in DIRECT_SEARCH_SNIPPET_STOPWORDS or token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms


def _combine_filters(*clauses: str) -> str:
    filtered = [clause.strip() for clause in clauses if clause and clause.strip()]
    if not filtered:
        return ""
    if len(filtered) == 1:
        return filtered[0]
    return " and ".join(f"({clause})" for clause in filtered)


def _is_navigation_question(question: str) -> bool:
    lowered = question.lower()
    return any(term in lowered for term in DIRECT_SEARCH_NAVIGATION_TERMS)


def _is_visual_question(question: str) -> bool:
    lowered = question.lower()
    return any(term in lowered for term in DIRECT_SEARCH_VISUAL_TERMS)


def _extract_best_snippet(text: str, question: str, *, max_length: int = 420) -> str:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return ""

    list_snippet = _extract_numbered_list_snippet(normalized, question, max_length=max_length)
    if list_snippet:
        return list_snippet
    if len(normalized) <= max_length:
        return normalized

    terms = _question_terms(question)
    lowered = normalized.lower()
    best_window = normalized[:max_length]
    best_score = -1
    candidate_positions: list[int] = []
    for term in terms:
        candidate_positions.extend(match.start() for match in re.finditer(re.escape(term), lowered))
    if candidate_positions:
        for position in candidate_positions:
            start = max(0, position - max_length // 3)
            end = min(len(normalized), start + max_length)
            window = normalized[start:end]
            window_lower = window.lower()
            score = sum(3 for term in terms if term in window_lower)
            if re.search(r"(?:^|[\s:;])[1-9]\.\s+[A-Za-z].*?(?:\s+[1-9]\.\s+[A-Za-z])", window):
                score += 4
            if score > best_score:
                best_score = score
                best_window = window

    sentences = [sentence.strip() for sentence in SENTENCE_BOUNDARY_PATTERN.split(normalized) if sentence.strip()]
    if not sentences:
        return normalized[:max_length].strip()
    best_index = 0
    best_score = -1
    for index, sentence in enumerate(sentences):
        sentence_lower = sentence.lower()
        score = sum(1 for term in terms if term in sentence_lower)
        if re.search(r"(?:^|[\s:;])[1-9]\.\s+[A-Za-z].*?(?:\s+[1-9]\.\s+[A-Za-z])", sentence):
            score += 3
        if score > best_score:
            best_score = score
            best_index = index
    selected = sentences[best_index]
    if best_index + 1 < len(sentences) and len(selected) < max_length * 0.8:
        selected = f"{selected} {sentences[best_index + 1]}".strip()
    return selected[:max_length].strip()


def _extract_numbered_list_snippet(text: str, question: str, *, max_length: int = 420) -> str:
    if not _is_list_seeking_question(question):
        return ""

    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return ""

    matches = [
        {
            "ordinal": int(match.group(1)),
            "text": re.sub(r"\s*-\s*see page\s+\d+\b", "", match.group(2), flags=re.IGNORECASE).strip(" .;:-"),
            "start": match.start(),
        }
        for match in re.finditer(r"(?:^|[\s:;])([1-9])\.\s+(.+?)(?=(?:\s+[1-9]\.\s+)|$)", normalized)
    ]
    if len(matches) < 2:
        return ""

    segments: list[list[dict[str, Any]]] = []
    current_segment: list[dict[str, Any]] = []
    last_ordinal = 0
    for item in matches:
        ordinal = int(item["ordinal"])
        if current_segment and ordinal <= last_ordinal:
            if len(current_segment) >= 2:
                segments.append(current_segment)
            current_segment = []
        current_segment.append(item)
        last_ordinal = ordinal
    if len(current_segment) >= 2:
        segments.append(current_segment)

    terms = _question_terms(question)
    best_candidate = ""
    best_score = -1
    for segment in segments:
        first_start = int(segment[0]["start"])
        prefix = normalized[max(0, first_start - 240) : first_start].strip()
        intro = prefix
        for boundary_pattern in (r"[.?!]\s+", r"\s+-\s+", r"\s+~\s+"):
            parts = re.split(boundary_pattern, intro)
            if parts:
                intro = parts[-1].strip()
        intro = intro.lstrip(":;,- ").strip()
        if len(intro) > 180:
            intro = intro[-180:].lstrip()

        list_text = " ".join(
            f"{index}. {_summarize_list_item(str(entry['text']))}"
            for index, entry in enumerate(segment[:5], start=1)
            if entry.get("text")
        )
        candidate = f"{intro} {list_text}".strip() if intro else list_text
        lowered = candidate.lower()
        score = sum(2 for term in terms if term in lowered)
        score += min(8, len(segment) * 2)
        if intro:
            score += 1
        if "..." in lowered or "see page" in lowered:
            score -= 1
        if score > best_score:
            best_candidate = candidate
            best_score = score

    return best_candidate[:max_length].strip()


def _extract_navigation_snippet(text: str, question: str, *, max_length: int = 220) -> str:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return ""
    terms = _question_terms(question)
    best_entry = ""
    best_score = -1
    for match in re.finditer(
        r"([A-Za-z][A-Za-z'&/\-]*(?:\s+[A-Za-z][A-Za-z'&/\-]*){0,6})\s+(\d{1,4})(?=\s|$)",
        normalized,
    ):
        title = match.group(1).strip(" .;:-")
        page = match.group(2)
        lowered = title.lower()
        score = sum(2 for term in terms if term in lowered)
        if score <= 0:
            continue
        entry = f"{title} {page}"
        if score > best_score:
            best_score = score
            best_entry = entry
    return best_entry[:max_length].strip()


def _normalize_numbered_list(text: str) -> str:
    items = _extract_numbered_list_items(text)
    if not items:
        return " ".join(text.split()).strip()
    return " ".join(f"{index}. {item}" for index, item in enumerate(items, start=1))


def _extract_numbered_list_items(text: str) -> list[str]:
    normalized = " ".join((text or "").split()).strip()
    pattern = re.compile(r"(?:^|[\s:;])([1-9])\.\s+(.+?)(?=(?:\s+[1-9]\.\s+)|$)")
    items: list[str] = []
    for match in pattern.finditer(normalized):
        item_text = re.sub(r"\s*-\s*see page\s+\d+\b", "", match.group(2), flags=re.IGNORECASE)
        item_text = item_text.strip(" .;:-")
        if item_text:
            items.append(item_text)
    return items


def _summarize_list_item(text: str) -> str:
    normalized = " ".join((text or "").split()).strip(" .;:-")
    if not normalized:
        return ""
    separator_positions = [
        normalized.find(separator)
        for separator in (" ~ ", " - ", ": ", "; ", ". ")
        if separator in normalized
    ]
    if separator_positions:
        split_at = min(position for position in separator_positions if position >= 0)
        normalized = normalized[:split_at].strip(" .;:-")
    return normalized[:90].rstrip(" .;:-")


def _is_list_seeking_question(question: str) -> bool:
    lowered = question.lower()
    asks_for_items = bool(re.search(r"\b(what|which|list|name|identify)\b", lowered))
    asks_for_categories = bool(re.search(r"\b(group|groups|component|components|type|types|category|categories)\b", lowered))
    return asks_for_items and asks_for_categories


def _snippet_quality(text: str, question: str) -> tuple[int, int]:
    normalized = " ".join((text or "").split()).strip().lower()
    terms = _question_terms(question)
    score = sum(2 for term in terms if term in normalized)
    list_item_count = len(_extract_numbered_list_items(normalized))
    if list_item_count:
        score += min(8, list_item_count * 2)
    if "basic components" in normalized or "one of three groups" in normalized:
        score += 3
    if "..." in normalized:
        score -= 1
    return score, len(normalized)


def _direct_result_rank(item: dict[str, Any]) -> tuple[float, float]:
    return (
        float(item.get("@search.rerankerScore") or 0),
        float(item.get("@search.score") or 0),
    )


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
        scoring_profile: str | None = None,
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
        scoring_profile: str | None = None,
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
        selected_sources, membership_diagnostics = self._reconcile_with_knowledge_base(selected_sources)
        routing_diagnostics.update(membership_diagnostics)
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
        scoring_profile: str | None = None,
    ) -> dict[str, Any]:
        normalized_mode = retrieval_mode.strip().lower()
        if normalized_mode not in {"full_text", "vector", "hybrid"}:
            raise RuntimeError(f"Unsupported direct retrieval mode: {retrieval_mode}")
        if normalized_mode in {"vector", "hybrid"} and not self._vector_search_available():
            raise RuntimeError(
                "Vector and hybrid retrieval require AZURE_OPENAI_EMBEDDING_DEPLOYMENT and a configured Foundry OpenAI endpoint."
            )
        applied_scoring_profile = self._resolve_scoring_profile(scoring_profile, normalized_mode)

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
            try:
                payload, elapsed_ms = self._run_direct_search(
                    source=source,
                    question=question,
                    retrieval_mode=normalized_mode,
                    doc_ids=scoped_doc_ids,
                    query_vector=query_vector,
                    scoring_profile=applied_scoring_profile,
                )
            except Exception as exc:
                # Auto mode can broadcast across heterogeneous indexes. A single index
                # that rejects the canonical request (e.g. an incompatible schema) must
                # not fail the whole turn — record it and keep the other sources.
                logger.warning(
                    "Direct search skipped knowledge source '%s' (index '%s'): %s",
                    source.knowledge_source_name,
                    source.index_name,
                    exc,
                )
                activity.append(
                    {
                        "type": "searchIndex",
                        "id": step,
                        "knowledgeSourceName": source.knowledge_source_name,
                        "count": 0,
                        "elapsedMs": 0,
                        "searchIndexArguments": {"search": question},
                        "searchMode": normalized_mode,
                        "scoringProfile": applied_scoring_profile or DIRECT_SEARCH_DEFAULT_SCORING_PROFILE,
                        "error": str(exc),
                    }
                )
                continue
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
                    "scoringProfile": applied_scoring_profile or DIRECT_SEARCH_DEFAULT_SCORING_PROFILE,
                }
            )
            for item in values:
                if not isinstance(item, dict):
                    continue
                raw_text = item.get("clean_text") or ""
                snippet = ""
                if _is_navigation_question(question) and item.get("content_type") == "table_of_contents":
                    snippet = _extract_navigation_snippet(raw_text, question)
                if not snippet:
                    snippet = _extract_best_snippet(raw_text, question)
                captions = item.get("@search.captions") or []
                if isinstance(captions, list) and captions:
                    first_caption = captions[0]
                    if isinstance(first_caption, dict) and isinstance(first_caption.get("text"), str):
                        caption_text = first_caption["text"]
                        if _snippet_quality(caption_text, question) >= _snippet_quality(snippet, question):
                            snippet = caption_text
                results.append(
                    {
                        **item,
                        "snippet": snippet,
                        "knowledgeSourceName": source.knowledge_source_name,
                        "index_name": source.index_name,
                        "supporting_query": question,
                    }
                )

        results.sort(key=_direct_result_rank, reverse=True)
        diagnostics = {
            **routing_diagnostics,
            "mode": f"{normalized_mode}_search",
            "search_method": normalized_mode,
            "agentic_retrieval": False,
            "corpus_mode": "custom" if doc_ids else "auto",
            "selected_doc_ids": doc_ids or [],
            "scoring_profile": applied_scoring_profile or DIRECT_SEARCH_DEFAULT_SCORING_PROFILE,
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

    def _build_scoring_profiles(self) -> list[dict[str, Any]]:
        """Lab 04 scoring profiles attached to the canonical index.

        Scoring profiles influence the BM25 (text) score that feeds full-text
        search directly and forms half of the fused hybrid result, so switching
        them at query time is a clean way to show how relevance tuning reorders
        results before RRF and the semantic ranker ever run.
        """
        return [
            {
                # Field weighting: a term that lands in the curated enrichment
                # fields outranks the same term buried in raw body text.
                "name": SCORING_PROFILE_ENRICHMENT_WEIGHTED,
                "text": {
                    "weights": {
                        "summary_text": 5,
                        "keyword_hints": 4,
                        "source_name": 3,
                        "section_path": 2,
                        "clean_text": 1,
                        "image_description_text": 1,
                    }
                },
            },
            {
                # Scoring function: boost more recently updated documents using
                # the indexer-maintained last_updated high-water mark.
                "name": SCORING_PROFILE_FRESHNESS_BOOSTED,
                "functionAggregation": "sum",
                "functions": [
                    {
                        "type": "freshness",
                        "fieldName": "last_updated",
                        "boost": 4,
                        "interpolation": "linear",
                        "freshness": {"boostingDuration": "P365D"},
                    }
                ],
            },
        ]

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
            "scoringProfiles": self._build_scoring_profiles(),
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
        embeddings_by_chunk_id = self._embed_chunks_for_index(chunks) if self._vector_indexing_enabled() else {}
        actions: list[dict[str, Any]] = []
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
        batch: list[dict[str, Any]] = []
        batch_bytes = 0
        for action in actions:
            action_payload = json.dumps(action, separators=(",", ":"))
            action_bytes = len(action_payload.encode("utf-8"))
            if batch and (
                len(batch) >= SEARCH_INDEX_BATCH_MAX_ACTIONS
                or batch_bytes + action_bytes >= SEARCH_INDEX_BATCH_MAX_BYTES
            ):
                self._post_chunk_batch(url, batch)
                batch = []
                batch_bytes = 0
            batch.append(action)
            batch_bytes += action_bytes
        if batch:
            self._post_chunk_batch(url, batch)

    def _post_chunk_batch(self, url: str, actions: list[dict[str, Any]]) -> None:
        response = requests.post(
            url,
            headers=self.headers,
            data=json.dumps({"value": actions}),
            timeout=60,
        )
        self._raise_for_status(response)

    def _vector_search_available(self) -> bool:
        return bool(
            settings.azure_openai_embedding_deployment
            and settings.azure_foundry_openai_base_url
        )

    def _vector_indexing_enabled(self) -> bool:
        return self._vector_search_available() and get_workshop_skill_profile().id in {
            "chunk_vector",
            "genai_enrichment",
            "visual_nlp",
            "content_understanding",
        }

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
            embeddings: list[list[float]] | None = None
            for attempt in range(1, EMBEDDING_RETRY_ATTEMPTS + 1):
                try:
                    embeddings, _ = embed_texts_with_foundry(
                        inputs,
                        deployment_id=settings.azure_openai_embedding_deployment,
                    )
                    break
                except Exception as exc:
                    retry_delay = self._embedding_retry_delay_seconds(exc, attempt)
                    if retry_delay is None or attempt >= EMBEDDING_RETRY_ATTEMPTS:
                        raise
                    sleep(retry_delay)
            if embeddings is None:
                raise RuntimeError("Embedding generation failed before any vectors were returned.")
            for chunk, embedding in zip(batch, embeddings):
                embeddings_by_chunk_id[chunk.chunk_id] = embedding
        return embeddings_by_chunk_id

    def _embedding_retry_delay_seconds(self, exc: Exception, attempt: int) -> int | None:
        detail = str(exc)
        retry_after_match = re.search(r"retry after\s+(\d+)\s+seconds", detail, flags=re.IGNORECASE)
        if retry_after_match:
            return max(1, int(retry_after_match.group(1)))
        normalized = detail.lower()
        if "ratelimitreached" in normalized or "too many requests" in normalized or "429" in normalized:
            return min(120, EMBEDDING_RETRY_BASE_DELAY_SECONDS * attempt)
        return None

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

    def _knowledge_base_source_names(self) -> set[str]:
        kb = self._get_knowledge_base(settings.azure_search_knowledge_base_name)
        sources = kb.get("knowledgeSources") if isinstance(kb, dict) else None
        if not isinstance(sources, list):
            return set()
        names: set[str] = set()
        for source in sources:
            if isinstance(source, dict):
                name = source.get("name")
                if isinstance(name, str) and name:
                    names.add(name)
        return names

    def _reconcile_with_knowledge_base(
        self, sources: list[SearchKnowledgeSourceConfig]
    ) -> tuple[list[SearchKnowledgeSourceConfig], dict[str, Any]]:
        """Drop targeted knowledge sources that are not registered in the live KB.

        The agentic ``/retrieve`` call requires every ``knowledgeSourceParams``
        target to match a knowledge source registered in the knowledge base.
        The enrichment source name is derived from the active workshop profile,
        so it can drift away from whatever profile last provisioned the KB (for
        example after the per-job profile pin is restored to the default). When
        that happens, targeting the phantom enrichment source returns a 400. We
        filter the targets down to the sources the KB actually exposes, always
        keeping the primary application source so retrieval still works.
        """
        kb_names = self._knowledge_base_source_names()
        if not kb_names:
            return sources, {}
        retained = [source for source in sources if source.knowledge_source_name in kb_names]
        dropped = [
            source.knowledge_source_name
            for source in sources
            if source.knowledge_source_name not in kb_names
        ]
        if not retained:
            primary = self._primary_knowledge_source()
            retained = [primary] if primary.knowledge_source_name in kb_names else sources
        diagnostics: dict[str, Any] = {}
        if dropped:
            diagnostics = {
                "knowledge_sources_dropped_not_in_kb": dropped,
                "knowledge_base_membership_filtered": True,
            }
        return retained, diagnostics

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
                "content_type",
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
        scoring_profile: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "top": DIRECT_SEARCH_TOP,
            "count": True,
            "select": self._direct_search_select_fields(),
        }
        if filter_expression:
            body["filter"] = filter_expression

        # Scoring profiles act on the BM25 (text) score, so they only change
        # full-text and hybrid ranking. Pure vector search is scored by HNSW
        # similarity and is unaffected, so we never attach one there.
        applied_scoring_profile = self._resolve_scoring_profile(scoring_profile, retrieval_mode)

        if retrieval_mode == "full_text":
            # Keep the baseline genuinely lexical: BM25 ranking only, with no
            # semantic L2 reranking. This preserves the workshop's lexical
            # control group so later labs can attribute gains to vectors,
            # RRF fusion, and the semantic ranker introduced in hybrid mode.
            body["search"] = question
            if applied_scoring_profile:
                body["scoringProfile"] = applied_scoring_profile
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
        body["queryType"] = "semantic"
        body["semanticConfiguration"] = "default-semantic-config"
        body["captions"] = "extractive|highlight-false"
        if applied_scoring_profile:
            body["scoringProfile"] = applied_scoring_profile
        body["vectorQueries"] = [
            {
                "kind": "vector",
                "vector": query_vector,
                "fields": settings.azure_search_vector_field_name,
                "k": DIRECT_VECTOR_K,
            }
        ]
        return body

    @staticmethod
    def _resolve_scoring_profile(scoring_profile: str | None, retrieval_mode: str) -> str | None:
        """Return a scoring-profile name to attach, or None to omit it."""
        if retrieval_mode not in {"full_text", "hybrid"}:
            return None
        normalized = (scoring_profile or "").strip()
        if not normalized or normalized == DIRECT_SEARCH_DEFAULT_SCORING_PROFILE:
            return None
        if normalized not in DIRECT_SEARCH_SCORING_PROFILES:
            return None
        return normalized

    def _default_content_filter(self, question: str) -> str:
        clauses: list[str] = []
        if not _is_navigation_question(question):
            clauses.append("content_type ne 'table_of_contents'")
        if not _is_visual_question(question):
            clauses.append("content_type ne 'figure_catalog'")
            clauses.append("content_type ne 'diagram_labels'")
        return " and ".join(clauses)

    def _run_direct_search(
        self,
        *,
        source: SearchKnowledgeSourceConfig,
        question: str,
        retrieval_mode: str,
        doc_ids: list[str] | None,
        query_vector: list[float] | None,
        scoring_profile: str | None = None,
    ) -> tuple[dict[str, Any], int]:
        filter_expression = _combine_filters(
            self._build_doc_filter(doc_ids or []),
            self._default_content_filter(question),
        )
        body = self._build_direct_search_body(
            question=question,
            retrieval_mode=retrieval_mode,
            filter_expression=filter_expression,
            query_vector=query_vector,
            scoring_profile=scoring_profile,
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
        # The enrichment (Blob skillset) index uses a different projected schema that
        # lacks the canonical fields direct_search selects (chunk_id, clean_text, ...).
        # Only the agentic /retrieve path (include_enrichment=True) can query it safely
        # via per-source field mappings, so when the caller opts out we must keep the
        # enrichment source out of keyword matching too — otherwise a visual question
        # ("...any diagram...") routes a raw $select at an index without those fields.
        match_candidates = (
            configured_sources
            if include_enrichment
            else [
                source
                for source in configured_sources
                if not enrichment_source
                or source.knowledge_source_name != enrichment_source.knowledge_source_name
            ]
        )
        matched_sources: list[SearchKnowledgeSourceConfig] = []
        match_details: list[dict[str, Any]] = []
        for source in match_candidates:
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
