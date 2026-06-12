from __future__ import annotations

import difflib
import json
import re
from pathlib import PurePosixPath
from pathlib import Path
from typing import Any

import requests

from backend.core.config import settings
from backend.domain.models import ChatCitation, ChatTurnResponse, ChunkRecord
from backend.services.foundry_openai import call_foundry_text
from backend.services.job_store import job_store

MAX_CHAT_CITATIONS = 8
MAX_QUERY_RESCUE_CHUNKS = 48
MAX_QUERY_RESCUE_TEXT_LENGTH = 1800
MAX_QUERY_RESCUE_TERMS = 4000
MAX_IMAGE_EVIDENCE_PER_CITATION = 2
MAX_NARROW_IMAGE_PAGE_SPAN = 12
MAX_FIGURE_SELECTION_TERMS = 8

SEARCH_DIRECTIVE_PATTERN = re.compile(r"\b(?:site|source|filetype):[^\s]+\b", re.IGNORECASE)
VISUAL_INTENT_PATTERN = re.compile(
    r"\b(diagram|figure|image|photo|picture|map|blueprint|chart|graph|illustration|visual|workflow|architecture)\b",
    re.IGNORECASE,
)

QUERY_RESCUE_STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "any",
    "are",
    "around",
    "because",
    "been",
    "before",
    "between",
    "both",
    "can",
    "does",
    "earth",
    "from",
    "have",
    "into",
    "mention",
    "mentions",
    "more",
    "night",
    "page",
    "pages",
    "query",
    "relevant",
    "report",
    "says",
    "show",
    "some",
    "that",
    "the",
    "their",
    "them",
    "there",
    "these",
    "this",
    "what",
    "where",
    "which",
    "with",
}

NO_RESULT_PATTERNS = (
    "can't find any mention of",
    "can’t find any mention of",
    "could not find any mention of",
    "couldn't find any mention of",
    "no relevant content was found",
    "no relevant content found",
    "no relevant information was found",
    "no answer returned",
    "i could not find relevant content",
    "i couldn't find relevant content",
    "isn’t identifiable from the provided evidence",
    "isn't identifiable from the provided evidence",
    "is not identifiable from the provided evidence",
    "the provided sources do not contain enough information",
)

SUBQUERY_DISPLAY_STOPWORDS = (QUERY_RESCUE_STOPWORDS - {"earth", "night"}) | {
    "academic",
    "define",
    "defined",
    "definition",
    "definitions",
    "explain",
    "explained",
    "explains",
    "explanation",
    "how",
    "is",
    "me",
    "of",
    "or",
    "press",
    "release",
    "released",
    "say",
    "saying",
    "says",
    "search",
    "searches",
    "searching",
    "find",
    "look",
    "lookup",
    "tell",
    "when",
    "who",
    "why",
    "site",
}

FIGURE_SELECTION_STOPWORDS = QUERY_RESCUE_STOPWORDS | {
    "article",
    "brand",
    "caption",
    "chapter",
    "corpus",
    "document",
    "documents",
    "excerpt",
    "file",
    "image",
    "images",
    "question",
    "reader",
    "reference",
    "references",
    "section",
    "sections",
    "source",
    "sources",
}


def _extract_answer_text(payload: dict[str, Any]) -> str:
    answer = payload.get("answer")
    if isinstance(answer, str):
        return answer
    if isinstance(answer, dict):
        text = answer.get("text")
        if isinstance(text, str) and text.strip():
            return text
        content = answer.get("content")
        if isinstance(content, list):
            texts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
                    texts.append(item["text"].strip())
            if texts:
                return "\n\n".join(texts)

    response_items = payload.get("response")
    if isinstance(response_items, list):
        texts: list[str] = []
        for item in response_items:
            if not isinstance(item, dict):
                continue
            for content in item.get("content", []):
                if isinstance(content, dict):
                    text = content.get("text")
                    if isinstance(text, str) and text.strip():
                        texts.append(text.strip())
        if texts:
            return "\n\n".join(texts)

    if isinstance(response_items, str):
        return response_items

    return "No answer returned."


def _normalize_query_term(value: str) -> str:
    normalized = re.sub(r"(^[^A-Za-z0-9]+|[^A-Za-z0-9]+$)", "", value).strip().lower()
    return normalized


def _collect_display_terms(
    text: str,
    *,
    stopwords: set[str],
    min_length: int = 3,
    max_terms: int = 6,
) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9'\-]{1,}", text):
        normalized = _normalize_query_term(token)
        if len(normalized) < min_length or normalized in stopwords or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(token.strip("\"'"))
        if len(terms) >= max_terms:
            break
    return terms


def _join_display_terms(terms: list[str]) -> str:
    if not terms:
        return ""
    if len(terms) == 1:
        return terms[0]
    if len(terms) == 2:
        return f"{terms[0]} and {terms[1]}"
    return ", ".join(terms[:-1]) + f", and {terms[-1]}"


def _humanize_search_text(raw_search: str) -> str:
    cleaned = SEARCH_DIRECTIVE_PATTERN.sub("", raw_search or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;")
    if not cleaned:
        return ""

    subject_terms = _collect_display_terms(
        cleaned,
        stopwords=SUBQUERY_DISPLAY_STOPWORDS,
        min_length=2,
        max_terms=5,
    )
    subject = _join_display_terms(subject_terms)
    lowered = cleaned.lower()
    if not subject:
        return cleaned
    if VISUAL_INTENT_PATTERN.search(cleaned):
        return f"Look for visual evidence about {subject}"
    if any(term in lowered for term in ("define", "definition", "definitions", "meaning", "what is")):
        return f"Find definitions or explanations about {subject}"
    if any(term in lowered for term in ("compare", "comparison", "versus", " vs ", "between")):
        return f"Compare evidence about {subject}"
    if any(term in lowered for term in ("summary", "summarize")):
        return f"Summarize evidence about {subject}"
    if any(term in lowered for term in ("how", "why", "explain")):
        return f"Investigate {subject}"
    return f"Search for {subject}"


def _iter_query_rescue_terms(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9'\-]{2,}", text):
        normalized = _normalize_query_term(token)
        if len(normalized) < 3 or normalized in QUERY_RESCUE_STOPWORDS:
            continue
        pairs.append((normalized, token.strip()))
    return pairs


def _prefer_query_rescue_display(current: str, candidate: str) -> str:
    if current.islower() and not candidate.islower():
        return candidate
    if candidate.isupper() and not current.isupper():
        return candidate
    return current


def _is_acronym_candidate(value: str) -> bool:
    return value.isupper() and value.isalpha() and 2 <= len(value) <= 8


def _select_query_rescue_candidate(normalized: str, known_terms: dict[str, str]) -> str | None:
    best_match: str | None = None
    best_score = 0.0
    for candidate_normalized, display in known_terms.items():
        if candidate_normalized == normalized:
            continue
        if not candidate_normalized or candidate_normalized[0] != normalized[0]:
            continue
        if abs(len(candidate_normalized) - len(normalized)) > 2:
            continue
        ratio = difflib.SequenceMatcher(None, normalized, candidate_normalized).ratio()
        if ratio < 0.55:
            continue
        score = ratio
        if _is_acronym_candidate(display):
            score += 0.18
        if candidate_normalized[:2] == normalized[:2]:
            score += 0.08
        if candidate_normalized[:3] == normalized[:3]:
            score += 0.06
        if len(candidate_normalized) <= 6:
            score += 0.03
        if display != display.lower():
            score += 0.02
        if score > best_score:
            best_score = score
            best_match = candidate_normalized
    return best_match


def _status_value(status: Any) -> str:
    if hasattr(status, "value"):
        return str(status.value)
    return str(status or "")


def _collect_query_rescue_terms(doc_ids: list[str] | None = None, *, jobs: list[Any] | None = None) -> dict[str, str]:
    selected_ids = set(doc_ids or [])
    known_terms: dict[str, str] = {}
    source_jobs = jobs if jobs is not None else job_store.list_jobs()
    for job in source_jobs:
        if _status_value(getattr(job, "status", "")) != "ready":
            continue
        doc_id = str(getattr(job, "doc_id", "") or "")
        if selected_ids and doc_id not in selected_ids:
            continue

        file_name = str(getattr(job, "file_name", "") or "")
        for normalized, token in _iter_query_rescue_terms(file_name):
            current = known_terms.get(normalized)
            known_terms[normalized] = token if current is None else _prefer_query_rescue_display(current, token)

        chunks_path = getattr(job, "chunks_path", None)
        if not chunks_path or not Path(chunks_path).exists():
            continue
        try:
            payload = json.loads(Path(chunks_path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        for item in payload[:MAX_QUERY_RESCUE_CHUNKS]:
            if not isinstance(item, dict):
                continue
            keyword_hints = item.get("keyword_hints") or []
            if isinstance(keyword_hints, list):
                for keyword in keyword_hints:
                    if not isinstance(keyword, str):
                        continue
                    for normalized, token in _iter_query_rescue_terms(keyword):
                        current = known_terms.get(normalized)
                        known_terms[normalized] = (
                            token if current is None else _prefer_query_rescue_display(current, token)
                        )

            for field_name in ("summary_text", "image_description_text", "clean_text"):
                value = item.get(field_name)
                if not isinstance(value, str) or not value.strip():
                    continue
                for normalized, token in _iter_query_rescue_terms(value[:MAX_QUERY_RESCUE_TEXT_LENGTH]):
                    current = known_terms.get(normalized)
                    known_terms[normalized] = (
                        token if current is None else _prefer_query_rescue_display(current, token)
                    )
                    if len(known_terms) >= MAX_QUERY_RESCUE_TERMS:
                        return known_terms
    return known_terms


def build_query_rescue(
    question: str,
    doc_ids: list[str] | None = None,
    *,
    jobs: list[Any] | None = None,
) -> dict[str, Any] | None:
    known_terms = _collect_query_rescue_terms(doc_ids, jobs=jobs)
    if not known_terms:
        return None

    corrected_question = question
    corrections: list[dict[str, str]] = []
    seen_replacements: set[tuple[str, str]] = set()
    query_terms = re.findall(r"[A-Za-z][A-Za-z0-9'\-]{2,}", question)
    for token in query_terms:
        normalized = _normalize_query_term(token)
        if (
            len(normalized) < 4
            or normalized in QUERY_RESCUE_STOPWORDS
            or normalized in known_terms
        ):
            continue
        matched_normalized = _select_query_rescue_candidate(normalized, known_terms)
        if not matched_normalized:
            continue
        if matched_normalized == normalized:
            continue
        replacement = known_terms[matched_normalized]
        replacement_key = (normalized, matched_normalized)
        if replacement_key in seen_replacements:
            continue
        rewritten, replacement_count = re.subn(
            rf"\b{re.escape(token)}\b",
            replacement,
            corrected_question,
            count=1,
            flags=re.IGNORECASE,
        )
        if replacement_count <= 0:
            continue
        corrected_question = rewritten
        seen_replacements.add(replacement_key)
        corrections.append({"from": token, "to": replacement})

    if not corrections or corrected_question == question:
        return None
    return {
        "original_question": question,
        "effective_question": corrected_question,
        "corrections": corrections,
    }


def response_needs_query_rescue(response: ChatTurnResponse) -> bool:
    answer = (response.answer or "").strip().lower()
    if not answer:
        return True
    if any(pattern in answer for pattern in NO_RESULT_PATTERNS):
        return True
    if response.citations:
        return False
    return False


def _parse_image_evidence(raw_value: Any) -> list[dict[str, Any]]:
    if isinstance(raw_value, list):
        return [item for item in raw_value if isinstance(item, dict)]
    if isinstance(raw_value, str) and raw_value.strip():
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


def _parse_asset_image_paths(raw_value: Any) -> list[str]:
    if isinstance(raw_value, list):
        return [str(item).strip() for item in raw_value if str(item).strip()]
    if not isinstance(raw_value, str):
        return []
    entries = [item.strip() for item in raw_value.split(";")]
    return [entry for entry in entries if entry]


def _derive_title_from_uri(uri: str | None) -> str | None:
    if not uri:
        return None
    candidate = uri.split("?", 1)[0].rstrip("/")
    if not candidate:
        return None
    name = PurePosixPath(candidate).name
    return name or None


def _normalize_citation(
    item: dict[str, Any],
    *,
    evidence_kind: str = "retrieval_reference",
    knowledge_source: str | None = None,
    index_name: str | None = None,
    supporting_query: str | None = None,
    retrieval_step: int | None = None,
) -> ChatCitation | None:
    uri = (
        item.get("url")
        or item.get("uri")
        or item.get("sourceUri")
        or item.get("source_uri")
        or item.get("blob_url")
        or item.get("blobUrl")
    )
    title = (
        item.get("title")
        or item.get("source_name")
        or item.get("knowledgeSourceName")
        or _derive_title_from_uri(uri)
        or "Source"
    )
    chunk_id = item.get("chunk_id") or item.get("chunkId") or item.get("id")
    doc_id = item.get("doc_id")
    page_numbers = item.get("page_numbers") or []
    if not isinstance(page_numbers, list):
        page_numbers = []
    image_evidence = _parse_image_evidence(item.get("image_evidence_json"))
    asset_image_paths = _parse_asset_image_paths(item.get("image_path") or item.get("imagePath"))
    snippet = (
        item.get("snippet")
        or item.get("content")
        or item.get("text")
        or item.get("clean_text")
        or item.get("answer")
        or ""
    )
    if not isinstance(snippet, str):
        snippet = json.dumps(snippet, ensure_ascii=True)
    snippet = " ".join(snippet.split())[:360]
    return ChatCitation(
        title=title,
        uri=uri,
        chunk_id=chunk_id,
        doc_id=doc_id,
        page_numbers=page_numbers,
        snippet=snippet,
        image_evidence=image_evidence,
        asset_image_paths=asset_image_paths,
        raw_reference_id=str(item.get("id")) if item.get("id") is not None else None,
        knowledge_source=knowledge_source or item.get("knowledgeSourceName") or item.get("knowledge_source"),
        index_name=index_name or item.get("index_name"),
        evidence_kind=evidence_kind,
        supporting_query=supporting_query or item.get("supporting_query"),
        retrieval_step=retrieval_step or item.get("retrieval_step"),
    )


def _extract_text_embedded_references(payload: dict[str, Any]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    response_items = payload.get("response")
    if not isinstance(response_items, list):
        return references
    for item in response_items:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, list):
                references.extend(entry for entry in parsed if isinstance(entry, dict))
            elif isinstance(parsed, dict):
                references.append(parsed)
    return references


def _collect_raw_citation_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    activity_by_id: dict[str, dict[str, Any]] = {}
    for activity_item in payload.get("activity", []):
        if not isinstance(activity_item, dict):
            continue
        identifier = activity_item.get("id")
        if identifier is not None:
            activity_by_id[str(identifier)] = activity_item

    for item in payload.get("results") or payload.get("citations") or []:
        if isinstance(item, dict):
            items.append(item)

    for item in payload.get("activity", []):
        if not isinstance(item, dict):
            continue
        for reference in item.get("references", []):
            if not isinstance(reference, dict):
                continue
            items.append(
                {
                    **reference,
                    "knowledgeSourceName": reference.get("knowledgeSourceName") or item.get("knowledgeSourceName"),
                }
            )

    for reference in payload.get("references") or []:
        if not isinstance(reference, dict):
            continue
        source_data = reference.get("sourceData")
        if not isinstance(source_data, dict):
            source_data = {}
        activity_item = activity_by_id.get(str(reference.get("activitySource") or ""))
        items.append(
            {
                **source_data,
                **reference,
                "knowledgeSourceName": (
                    reference.get("knowledgeSourceName")
                    or source_data.get("knowledgeSourceName")
                    or (activity_item.get("knowledgeSourceName") if isinstance(activity_item, dict) else None)
                ),
            }
        )

    for item in _extract_text_embedded_references(payload):
        if isinstance(item, dict):
            items.append(item)

    return items


def _infer_page_numbers(snippet: str) -> list[int]:
    matches = re.findall(r"\b[Pp]age\s+(\d+)\b", snippet)
    return [int(match) for match in matches[:4]]


def _normalize_page_numbers(page_numbers: list[int] | None) -> list[int]:
    normalized: list[int] = []
    seen: set[int] = set()
    for value in page_numbers or []:
        if not isinstance(value, int) or value <= 0 or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return sorted(normalized)


def _page_span(page_numbers: list[int]) -> int:
    if not page_numbers:
        return 0
    return max(page_numbers) - min(page_numbers) + 1


def _figure_text(figure: dict[str, Any]) -> str:
    parts = [
        figure.get("description"),
        figure.get("image_name"),
        figure.get("original_image_name"),
        figure.get("label"),
    ]
    return " ".join(str(part).strip() for part in parts if isinstance(part, str) and part.strip()).lower()


def _has_visual_intent(*texts: str | None) -> bool:
    return any(isinstance(text, str) and VISUAL_INTENT_PATTERN.search(text) for text in texts)


def _select_relevant_figures(citation: ChatCitation, figures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    page_numbers = _normalize_page_numbers(citation.page_numbers)
    narrow_page_scope = bool(page_numbers) and _page_span(page_numbers) <= MAX_NARROW_IMAGE_PAGE_SPAN
    if not narrow_page_scope and not _has_visual_intent(citation.supporting_query, citation.snippet, citation.title):
        return []

    query_terms = _collect_display_terms(
        citation.supporting_query or "",
        stopwords=FIGURE_SELECTION_STOPWORDS,
        max_terms=MAX_FIGURE_SELECTION_TERMS,
    )
    snippet_terms = _collect_display_terms(
        citation.snippet or "",
        stopwords=FIGURE_SELECTION_STOPWORDS,
        max_terms=MAX_FIGURE_SELECTION_TERMS,
    )
    title_terms = _collect_display_terms(
        citation.title or "",
        stopwords=FIGURE_SELECTION_STOPWORDS,
        max_terms=3,
    )

    scored: list[tuple[int, int, int, dict[str, Any]]] = []
    target_page = page_numbers[0] if page_numbers else 0
    for index, figure in enumerate(figures):
        if not isinstance(figure, dict):
            continue
        page_number = figure.get("page_number")
        if narrow_page_scope and page_number not in page_numbers:
            continue
        figure_text = _figure_text(figure)
        score = 0
        if narrow_page_scope and page_number in page_numbers:
            score += 6
        score += 3 * sum(1 for term in query_terms if term.lower() in figure_text)
        score += 2 * sum(1 for term in snippet_terms if term.lower() in figure_text)
        score += sum(1 for term in title_terms if term.lower() in figure_text)
        if _has_visual_intent(citation.supporting_query) and any(
            marker in figure_text
            for marker in ("diagram", "figure", "image", "map", "blueprint", "chart", "graph", "illustration", "visual")
        ):
            score += 2
        if score <= 0 and not narrow_page_scope:
            continue
        distance = abs(int(page_number or 0) - target_page)
        scored.append((score, distance, index, figure))

    if not scored:
        if not narrow_page_scope:
            return []
        return [
            figure
            for figure in figures
            if isinstance(figure, dict) and figure.get("page_number") in page_numbers
        ][:MAX_IMAGE_EVIDENCE_PER_CITATION]

    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    selected: list[dict[str, Any]] = []
    seen_artifacts: set[str] = set()
    for _, _, _, figure in scored:
        artifact_id = str(figure.get("artifact_id") or "")
        if artifact_id and artifact_id in seen_artifacts:
            continue
        if artifact_id:
            seen_artifacts.add(artifact_id)
        selected.append(figure)
        if len(selected) >= MAX_IMAGE_EVIDENCE_PER_CITATION:
            break
    return selected


def _job_lookup() -> tuple[list[Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    jobs = [job for job in job_store.list_jobs() if job.intermediate_path and Path(job.intermediate_path).exists()]
    jobs_by_doc_id = {job.doc_id: job for job in jobs}
    jobs_by_title = {}
    jobs_by_uri = {}
    for job in jobs:
        jobs_by_title[job.file_name] = job
        jobs_by_title[Path(job.stored_path).name] = job
        if job.external_source_uri:
            jobs_by_uri[job.external_source_uri] = job
    return jobs, jobs_by_doc_id, jobs_by_title, jobs_by_uri


def _citation_richness(citation: ChatCitation) -> int:
    score = 0
    if citation.knowledge_source:
        score += 5
    if citation.index_name:
        score += 3
    if citation.doc_id:
        score += 4
    if citation.chunk_id:
        score += 3
    if citation.page_numbers:
        score += 1
    if citation.uri:
        score += 1
    if citation.image_evidence:
        score += 1
    if citation.evidence_kind == "activity_support":
        score += 1
    return score


def _snippet_fingerprint(snippet: str) -> str:
    return re.sub(r"\s+", " ", snippet.strip().lower())[:220]


def _hydrate_citations(citations: list[ChatCitation]) -> list[ChatCitation]:
    jobs, jobs_by_doc_id, jobs_by_title, jobs_by_uri = _job_lookup()
    figures_by_doc_id: dict[str, list[dict[str, Any]]] = {}
    for citation in citations:
        matched_job = jobs_by_doc_id.get(citation.doc_id) if citation.doc_id else None
        if not matched_job:
            matched_job = jobs_by_title.get(citation.title)
        if not matched_job and citation.uri:
            matched_job = jobs_by_uri.get(citation.uri)
        if not matched_job:
            continue
        citation.doc_id = citation.doc_id or matched_job.doc_id
        publish_diagnostics = matched_job.publish_status.diagnostics or {}
        citation.knowledge_source = citation.knowledge_source or publish_diagnostics.get("knowledge_source_name")
        citation.index_name = citation.index_name or publish_diagnostics.get("index_name")
        if not citation.page_numbers:
            citation.page_numbers = _infer_page_numbers(citation.snippet)
        citation.page_numbers = _normalize_page_numbers(citation.page_numbers)
        figures = figures_by_doc_id.get(citation.doc_id)
        if figures is None:
            intermediate = json.loads(Path(matched_job.intermediate_path).read_text(encoding="utf-8"))
            figures = (intermediate.get("metadata") or {}).get("figure_artifacts") or []
            figures_by_doc_id[citation.doc_id] = [figure for figure in figures if isinstance(figure, dict)]

        if citation.image_evidence and _page_span(citation.page_numbers) and _page_span(citation.page_numbers) <= MAX_NARROW_IMAGE_PAGE_SPAN:
            citation.image_evidence = citation.image_evidence[:MAX_IMAGE_EVIDENCE_PER_CITATION]
            continue

        selected_images = _select_relevant_figures(citation, figures)
        if selected_images or _page_span(citation.page_numbers) > MAX_NARROW_IMAGE_PAGE_SPAN:
            citation.image_evidence = selected_images
    return citations


def _dedupe_citations(citations: list[ChatCitation]) -> list[ChatCitation]:
    ranked = sorted(
        enumerate(citations),
        key=lambda item: (-_citation_richness(item[1]), item[0]),
    )
    deduped: list[ChatCitation] = []
    seen_primary: set[tuple[str, str]] = set()
    seen_snippets: set[str] = set()
    for _, citation in ranked:
        primary = citation.chunk_id or citation.doc_id or citation.title
        secondary = citation.snippet[:160]
        primary_key = (str(primary), secondary)
        snippet_key = _snippet_fingerprint(citation.snippet)
        if primary_key in seen_primary:
            continue
        if snippet_key and snippet_key in seen_snippets:
            continue
        seen_primary.add(primary_key)
        if snippet_key:
            seen_snippets.add(snippet_key)
        deduped.append(citation)
    return deduped


def _source_key(citation: ChatCitation) -> str:
    return (
        citation.knowledge_source
        or citation.index_name
        or citation.doc_id
        or citation.title
    )


def _extract_subqueries(activity: list[dict[str, Any]]) -> list[dict[str, Any]]:
    subqueries: list[dict[str, Any]] = []
    for index, item in enumerate(activity, start=1):
        if not isinstance(item, dict):
            continue
        activity_type = item.get("type")
        if activity_type == "searchIndex":
            args = item.get("searchIndexArguments") or {}
        elif activity_type == "azureBlob":
            args = item.get("azureBlobArguments") or {}
        else:
            continue
        subqueries.append(
            {
                "step": len(subqueries) + 1,
                "search": args.get("search") or "",
                "raw_search": args.get("search") or "",
                "display_search": _humanize_search_text(args.get("search") or ""),
                "knowledge_source": item.get("knowledgeSourceName"),
                "result_count": item.get("count"),
                "elapsed_ms": item.get("elapsedMs"),
                "raw_activity_id": item.get("id", index),
                "activity_type": activity_type,
            }
        )
    return subqueries


def _effective_diagnostics(payload: dict[str, Any]) -> dict[str, Any]:
    diagnostics = dict(payload.get("diagnostics") or {})
    activity = payload.get("activity")
    if isinstance(activity, list):
        diagnostics["activity"] = activity
        diagnostics.setdefault("subqueries", _extract_subqueries(activity))
    return diagnostics


def _extract_source_maps(diagnostics: dict[str, Any]) -> dict[str, str]:
    if isinstance(diagnostics.get("knowledge_source_index_map"), dict):
        return {
            str(key): str(value)
            for key, value in diagnostics["knowledge_source_index_map"].items()
            if key and value
        }
    knowledge_sources = diagnostics.get("available_knowledge_sources") or diagnostics.get("selected_knowledge_sources") or []
    indexes = diagnostics.get("available_search_indexes") or diagnostics.get("selected_search_indexes") or []
    mapping: dict[str, str] = {}
    for source_name, index_name in zip(knowledge_sources, indexes):
        if source_name and index_name:
            mapping[str(source_name)] = str(index_name)
    return mapping


def _positive_sources_from_diagnostics(diagnostics: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_source: dict[str, dict[str, Any]] = {}
    for subquery in diagnostics.get("subqueries") or []:
        if not isinstance(subquery, dict):
            continue
        source_name = subquery.get("knowledge_source")
        result_count = int(subquery.get("result_count") or 0)
        if not source_name or result_count <= 0:
            continue
        best = by_source.get(source_name)
        if not best or result_count > int(best.get("result_count") or 0):
            by_source[source_name] = subquery
    return by_source


def _build_doc_filter(doc_ids: list[str]) -> str:
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


def _search_supporting_chunks(
    *,
    index_name: str,
    query: str,
    knowledge_source: str,
    retrieval_step: int | None,
    doc_ids: list[str] | None = None,
    top: int = 2,
) -> list[ChatCitation]:
    endpoint = settings.azure_search_endpoint.rstrip("/")
    headers = {
        "Content-Type": "application/json",
        "api-key": settings.azure_search_key,
    }
    url = f"{endpoint}/indexes/{index_name}/docs/search?api-version=2025-09-01"
    select_fields = ",".join(
        [
            "chunk_id",
            "doc_id",
            "source_name",
            "source_uri",
            "section_path",
            "page_numbers",
            "clean_text",
            "image_evidence_json",
        ]
    )
    filter_expression = _build_doc_filter(doc_ids or [])
    request_variants = [
        {
            "search": query,
            "top": top,
            "queryType": "semantic",
            "semanticConfiguration": "default-semantic-config",
            "select": select_fields,
            **({"filter": filter_expression} if filter_expression else {}),
        },
        {
            "search": query,
            "top": top,
            "select": select_fields,
            **({"filter": filter_expression} if filter_expression else {}),
        },
    ]

    last_error: Exception | None = None
    for body in request_variants:
        try:
            response = requests.post(url, headers=headers, data=json.dumps(body), timeout=20)
            response.raise_for_status()
            payload = response.json()
            citations: list[ChatCitation] = []
            for item in payload.get("value") or []:
                if not isinstance(item, dict):
                    continue
                snippet = item.get("clean_text") or ""
                captions = item.get("@search.captions") or []
                if isinstance(captions, list) and captions:
                    first_caption = captions[0]
                    if isinstance(first_caption, dict) and isinstance(first_caption.get("text"), str):
                        snippet = first_caption["text"]
                citation = _normalize_citation(
                    {
                        **item,
                        "snippet": snippet,
                    },
                    evidence_kind="activity_support",
                    knowledge_source=knowledge_source,
                    index_name=index_name,
                    supporting_query=query,
                    retrieval_step=retrieval_step,
                )
                if citation:
                    citations.append(citation)
            return citations
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        return []
    return []


def _supplement_missing_sources(
    citations: list[ChatCitation],
    diagnostics: dict[str, Any],
) -> list[ChatCitation]:
    source_map = _extract_source_maps(diagnostics)
    positive_sources = _positive_sources_from_diagnostics(diagnostics)
    represented_sources = {_source_key(citation) for citation in citations if _source_key(citation)}
    custom_scope_groups = diagnostics.get("custom_scope_groups") or {}

    supplemental: list[ChatCitation] = []
    for source_name, subquery in positive_sources.items():
        if source_name in represented_sources:
            continue
        index_name = source_map.get(source_name)
        if not index_name:
            continue
        query = str(subquery.get("search") or "").strip()
        if not query:
            continue
        doc_ids = custom_scope_groups.get(source_name) if isinstance(custom_scope_groups, dict) else None
        supplemental.extend(
            _search_supporting_chunks(
                index_name=index_name,
                query=query,
                knowledge_source=source_name,
                retrieval_step=subquery.get("step"),
                doc_ids=doc_ids,
                top=2,
            )
        )
    return supplemental


def _balance_citations(citations: list[ChatCitation], diagnostics: dict[str, Any]) -> list[ChatCitation]:
    positive_sources = list(_positive_sources_from_diagnostics(diagnostics).keys())
    ordered: list[ChatCitation] = []
    used: set[int] = set()

    for source_name in positive_sources:
        for index, citation in enumerate(citations):
            if index in used:
                continue
            if citation.knowledge_source == source_name:
                ordered.append(citation)
                used.add(index)
                break

    for index, citation in enumerate(citations):
        if index in used:
            continue
        ordered.append(citation)
        used.add(index)

    return ordered[:MAX_CHAT_CITATIONS]


def _assign_reference_ids(citations: list[ChatCitation]) -> list[ChatCitation]:
    for index, citation in enumerate(citations, start=1):
        citation.reference_id = index
    return citations


def _rewrite_reference_markers(answer: str, citations: list[ChatCitation]) -> str:
    raw_to_assigned = {
        citation.raw_reference_id: citation.reference_id
        for citation in citations
        if citation.raw_reference_id is not None and citation.reference_id is not None
    }
    if not raw_to_assigned:
        return answer

    def replace(match: re.Match[str]) -> str:
        raw_reference = match.group(1)
        reference_id = raw_to_assigned.get(raw_reference)
        if reference_id is None:
            return match.group(0)
        return f"[{reference_id}]"

    return re.sub(r"\[ref_id:(\d+)\]", replace, answer)


def _summarize_evidence(citations: list[ChatCitation], diagnostics: dict[str, Any]) -> dict[str, Any]:
    source_counts: dict[str, int] = {}
    for citation in citations:
        source_name = citation.knowledge_source or "unknown"
        source_counts[source_name] = source_counts.get(source_name, 0) + 1
    positive_sources = _positive_sources_from_diagnostics(diagnostics)
    return {
        "positive_retrieval_sources": sorted(positive_sources.keys()),
        "evidence_source_counts": source_counts,
        "represented_knowledge_sources": sorted(source_counts.keys()),
        "missing_positive_sources": sorted(set(positive_sources.keys()) - set(source_counts.keys())),
    }


def _extract_citations(payload: dict[str, Any]) -> list[ChatCitation]:
    diagnostics = _effective_diagnostics(payload)
    citations: list[ChatCitation] = []
    for item in _collect_raw_citation_items(payload):
        citation = _normalize_citation(item)
        if citation:
            citations.append(citation)

    citations = _hydrate_citations(citations)
    citations = _dedupe_citations(citations)

    supplemental = _supplement_missing_sources(citations, diagnostics)
    if supplemental:
        citations.extend(_hydrate_citations(supplemental))
        citations = _dedupe_citations(citations)

    citations = _balance_citations(citations, diagnostics)
    return _assign_reference_ids(citations)


def build_chat_response(payload: dict[str, Any]) -> ChatTurnResponse:
    citations = _extract_citations(payload)
    answer = _rewrite_reference_markers(_extract_answer_text(payload), citations)
    diagnostics = _effective_diagnostics(payload)
    diagnostics.update(_summarize_evidence(citations, diagnostics))
    diagnostics.setdefault("mode", "search_raw")
    return ChatTurnResponse(answer=answer, citations=citations, diagnostics=diagnostics)


def _format_sources_for_prompt(citations: list[ChatCitation]) -> str:
    blocks: list[str] = []
    for citation in citations:
        reference_id = citation.reference_id or len(blocks) + 1
        source_lines = [f"[{reference_id}] {citation.title}"]
        if citation.chunk_id:
            source_lines.append(f"chunk_id: {citation.chunk_id}")
        if citation.doc_id:
            source_lines.append(f"doc_id: {citation.doc_id}")
        if citation.knowledge_source:
            source_lines.append(f"knowledge_source: {citation.knowledge_source}")
        if citation.index_name:
            source_lines.append(f"index_name: {citation.index_name}")
        if citation.page_numbers:
            source_lines.append(f"pages: {', '.join(str(page) for page in citation.page_numbers)}")
        if citation.uri:
            source_lines.append(f"uri: {citation.uri}")
        if citation.supporting_query:
            source_lines.append(f"supporting_query: {citation.supporting_query}")
        source_lines.append(f"content: {citation.snippet or 'No snippet available.'}")
        for image in citation.image_evidence[:2]:
            description = image.get("description")
            if description:
                source_lines.append(f"image: {description}")
        blocks.append("\n".join(source_lines))
    return "\n\n".join(blocks)


def synthesize_grounded_chat(question: str, retrieval_payload: dict[str, Any]) -> ChatTurnResponse:
    retrieval_diagnostics = retrieval_payload.get("diagnostics") or {}
    use_search_answer_synthesis = bool(retrieval_diagnostics.get("force_search_answer_synthesis")) or (
        bool(retrieval_diagnostics.get("agentic_retrieval")) and settings.azure_search_enable_answer_synthesis
    )
    if use_search_answer_synthesis:
        response = build_chat_response(retrieval_payload)
        synthesis_model = settings.azure_search_llm_deployment
        if retrieval_diagnostics.get("native_multimodal"):
            synthesis_model = (
                retrieval_diagnostics.get("native_answer_synthesis_deployment")
                or settings.azure_search_native_chat_completion_deployment
                or synthesis_model
            )
        response.diagnostics.update(
            {
                "mode": retrieval_diagnostics.get("mode") or "search_answer_synthesis",
                "model": synthesis_model,
                "answer_synthesis_enabled": True,
                "image_serving_enabled": settings.azure_search_enable_image_serving,
            }
        )
        return response

    citations = _extract_citations(retrieval_payload)
    if not citations:
        return build_chat_response(retrieval_payload)

    if not settings.azure_foundry_chat_enabled:
        response = build_chat_response(retrieval_payload)
        response.diagnostics["mode"] = "search_raw"
        return response

    prompt_sources = _format_sources_for_prompt(citations)
    system_message = (
        "You answer enterprise knowledge questions using only the grounded sources provided. "
        "Do not invent facts. If the evidence is insufficient, say so clearly. "
        "Cite claims inline using square brackets like [1] or [2][3]. "
        "If figure descriptions are provided, use them only as supporting evidence."
    )
    user_message = (
        f"Question:\n{question}\n\n"
        f"Grounded sources:\n{prompt_sources}\n\n"
        "Write a direct answer grounded only in these sources."
    )
    answer, endpoint = call_foundry_text(
        [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]
    )
    diagnostics = _effective_diagnostics(retrieval_payload)
    diagnostics.update(_summarize_evidence(citations, diagnostics))
    diagnostics.update(
        {
            "mode": retrieval_diagnostics.get("mode") or "search_plus_gpt54",
            "model": settings.azure_foundry_chat_deployment,
            "model_endpoint": endpoint,
            "grounding_source_count": len(citations),
        }
    )
    return ChatTurnResponse(answer=answer, citations=citations, diagnostics=diagnostics)


def local_preview_chat(question: str, chunks: list[ChunkRecord], *, doc_ids: list[str] | None = None) -> ChatTurnResponse:
    if doc_ids:
        allowed = set(doc_ids)
        chunks = [chunk for chunk in chunks if chunk.doc_id in allowed]
    scored = []
    query_terms = {term.lower() for term in question.split() if len(term) > 2}
    for chunk in chunks:
        text = chunk.clean_text.lower()
        score = sum(1 for term in query_terms if term in text)
        if score:
            scored.append((score, chunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    top_chunks = [item[1] for item in scored[:3]]
    if not top_chunks:
        return ChatTurnResponse(
            answer="No relevant chunk was found in local preview mode. Configure Azure Search for true agentic retrieval.",
            diagnostics={"mode": "local_preview", "subqueries": [], "selected_doc_ids": doc_ids or []},
        )
    answer = "\n\n".join(chunk.clean_text[:360] for chunk in top_chunks)
    citations = [
        ChatCitation(
            title=chunk.source_name,
            uri=chunk.source_uri,
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            page_numbers=chunk.page_numbers,
            snippet=chunk.clean_text[:200],
            image_evidence=chunk.image_evidence[:2],
        )
        for chunk in top_chunks
    ]
    citations = _assign_reference_ids(citations)
    return ChatTurnResponse(
        answer=answer,
        citations=citations,
        diagnostics={
            "mode": "local_preview",
            "subqueries": [],
            "selected_doc_ids": doc_ids or [],
            **_summarize_evidence(citations, {"subqueries": []}),
        },
    )
