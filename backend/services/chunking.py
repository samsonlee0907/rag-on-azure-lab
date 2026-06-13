from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from backend.core.config import settings
from backend.domain.models import ChunkRecord, IntermediateDocument, ParagraphSpan, SectionNode

SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
TABLE_OF_CONTENTS_HEADING_PATTERN = re.compile(r"^(contents|table of contents)\b", re.IGNORECASE)
PROSE_HINT_TERMS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "these",
    "this",
    "to",
    "with",
}


def _token_estimate(text: str) -> int:
    return max(1, len(text) // 4)


def _word_count(text: str) -> int:
    return len(text.split())


def _page_numbers_from_span(span: ParagraphSpan | None) -> list[int]:
    if span is None or span.page_start is None:
        return []
    if span.page_end is None or span.page_end <= span.page_start:
        return [span.page_start]
    return list(range(span.page_start, span.page_end + 1))


def _union_page_numbers(blocks: list["_ChunkBlock"]) -> list[int]:
    pages: set[int] = set()
    for block in blocks:
        for page in block.page_numbers:
            if isinstance(page, int) and page > 0:
                pages.add(page)
    return sorted(pages)


def _looks_like_table_of_contents_text(text: str) -> bool:
    normalized = text.replace("\r", "\n")
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    if not lines:
        return False
    heading_region = " ".join(lines[:6]).lower()
    if TABLE_OF_CONTENTS_HEADING_PATTERN.search(heading_region):
        return True
    toc_like_lines = 0
    for line in lines[:40]:
        if len(line) > 120:
            continue
        if re.search(r"\b\d{1,4}\b", line) and len(re.findall(r"[A-Za-z][A-Za-z'&/\-]*", line)) >= 2:
            toc_like_lines += 1
    if toc_like_lines >= 6:
        return True

    flattened = " ".join(lines)
    toc_pairs = re.findall(
        r"(?:^|\s)([A-Za-z][A-Za-z'&/\-]*(?:\s+[A-Za-z][A-Za-z'&/\-]*){0,5})\s+\d{1,4}(?=\s|$)",
        flattened,
    )
    if len(toc_pairs) >= 8 and flattened.count(".") <= 2:
        return True
    return False


def _looks_like_diagram_labels_text(text: str) -> bool:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return False
    if any(punctuation in normalized for punctuation in ".!?"):
        return False

    tokens = re.findall(r"[A-Za-z0-9%℃/+\-]+", normalized.lower())
    if len(tokens) < 5 or len(tokens) > 80:
        return False

    alpha_tokens = [token for token in tokens if any(character.isalpha() for character in token)]
    if len(alpha_tokens) < 4:
        return False

    prose_hits = sum(1 for token in alpha_tokens if token in PROSE_HINT_TERMS)
    numeric_or_symbolic = sum(
        1
        for token in tokens
        if token.isdigit() or any(symbol in token for symbol in ("%","℃","/","+","-"))
    )
    prose_ratio = prose_hits / max(1, len(alpha_tokens))
    symbol_ratio = numeric_or_symbolic / max(1, len(tokens))

    return prose_ratio < 0.2 and symbol_ratio < 0.45


def _infer_chunk_content_type(section_path: list[str], text: str) -> str:
    joined_path = " > ".join(section_path).lower()
    if "extracted figures" in joined_path:
        return "figure_catalog"
    if TABLE_OF_CONTENTS_HEADING_PATTERN.search(joined_path) or _looks_like_table_of_contents_text(text):
        return "table_of_contents"
    if _looks_like_diagram_labels_text(text):
        return "diagram_labels"
    return "text"


@dataclass(slots=True)
class ChunkPolicy:
    name: str = "structure_recursive"
    chunk_size_tokens: int = settings.chunk_size_tokens
    overlap_tokens: int = settings.chunk_overlap_tokens
    semantic_mode: bool = settings.use_semantic_chunking


@dataclass(slots=True)
class _ChunkBlock:
    text: str
    page_numbers: list[int]


class StructureAwareChunker:
    def __init__(self, policy: ChunkPolicy | None = None) -> None:
        self.policy = policy or ChunkPolicy()

    def chunk(self, document: IntermediateDocument) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        counter = 0
        for section in document.sections:
            counter = self._walk(
                document=document,
                section=section,
                heading_path=[],
                chunks=chunks,
                counter=counter,
            )
        if not chunks:
            chunks.append(
                self._build_chunk(
                    document=document,
                    counter=0,
                    section_path=["Document"],
                    text=f"{document.source_name}\n\nNo extractable content was produced.",
                    page_numbers=[],
                )
            )
        return chunks

    def _walk(
        self,
        document: IntermediateDocument,
        section: SectionNode,
        heading_path: list[str],
        chunks: list[ChunkRecord],
        counter: int,
    ) -> int:
        path = [*heading_path, section.heading]
        blocks = self._build_blocks(section)
        if blocks:
            counter = self._emit_blocks(document, chunks, counter, path, blocks)

        for child in section.children:
            counter = self._walk(document, child, path, chunks, counter)
        return counter

    def _build_blocks(self, section: SectionNode) -> list[_ChunkBlock]:
        blocks: list[_ChunkBlock] = []
        fallback_span = ParagraphSpan(page_start=section.page_start, page_end=section.page_end)
        for index, paragraph in enumerate(section.paragraphs):
            text = paragraph.strip()
            if not text:
                continue
            span = section.paragraph_spans[index] if index < len(section.paragraph_spans) else fallback_span
            blocks.append(_ChunkBlock(text=text, page_numbers=_page_numbers_from_span(span)))
        for table in section.tables:
            table_lines = [" | ".join(row) for row in table if row]
            if table_lines:
                blocks.append(
                    _ChunkBlock(
                        text="\n".join(table_lines),
                        page_numbers=_page_numbers_from_span(fallback_span),
                    )
                )
        return blocks

    def _emit_blocks(
        self,
        document: IntermediateDocument,
        chunks: list[ChunkRecord],
        counter: int,
        section_path: list[str],
        blocks: list[_ChunkBlock],
    ) -> int:
        target_words = max(60, self.policy.chunk_size_tokens)
        overlap_words = min(self.policy.overlap_tokens, max(0, target_words // 3))
        current_blocks: list[_ChunkBlock] = []
        current_words = 0
        index = 0

        while index < len(blocks):
            block = blocks[index]
            block_words = _word_count(block.text)
            if block_words > target_words:
                if current_blocks:
                    counter = self._append_chunk(document, chunks, counter, section_path, current_blocks)
                    current_blocks, current_words = self._build_overlap_blocks(
                        current_blocks,
                        overlap_words,
                        incoming_words=block_words,
                        target_words=target_words,
                    )
                    continue
                for segment in self._split_oversized_block(block, target_words, overlap_words):
                    counter = self._append_chunk(document, chunks, counter, section_path, [segment])
                index += 1
                current_blocks = []
                current_words = 0
                continue

            if current_blocks and current_words + block_words > target_words:
                counter = self._append_chunk(document, chunks, counter, section_path, current_blocks)
                current_blocks, current_words = self._build_overlap_blocks(
                    current_blocks,
                    overlap_words,
                    incoming_words=block_words,
                    target_words=target_words,
                )
                continue

            current_blocks.append(block)
            current_words += block_words
            index += 1

        if current_blocks:
            counter = self._append_chunk(document, chunks, counter, section_path, current_blocks)
        return counter

    def _append_chunk(
        self,
        document: IntermediateDocument,
        chunks: list[ChunkRecord],
        counter: int,
        section_path: list[str],
        blocks: list[_ChunkBlock],
    ) -> int:
        text = "\n\n".join(block.text.strip() for block in blocks if block.text.strip()).strip()
        if not text:
            return counter
        counter += 1
        chunks.append(
            self._build_chunk(
                document=document,
                counter=counter,
                section_path=section_path,
                text=text,
                page_numbers=_union_page_numbers(blocks),
            )
        )
        return counter

    def _build_overlap_blocks(
        self,
        blocks: list[_ChunkBlock],
        overlap_words: int,
        *,
        incoming_words: int,
        target_words: int,
    ) -> tuple[list[_ChunkBlock], int]:
        if overlap_words <= 0:
            return [], 0
        overlap_blocks: list[_ChunkBlock] = []
        overlap_total = 0
        for block in reversed(blocks):
            block_words = _word_count(block.text)
            if overlap_blocks and overlap_total + block_words > overlap_words:
                break
            overlap_blocks.insert(0, block)
            overlap_total += block_words
            if overlap_total >= overlap_words:
                break
        while overlap_blocks and overlap_total + incoming_words > target_words:
            removed = overlap_blocks.pop(0)
            overlap_total -= _word_count(removed.text)
        return overlap_blocks, overlap_total

    def _split_oversized_block(
        self,
        block: _ChunkBlock,
        target_words: int,
        overlap_words: int,
    ) -> list[_ChunkBlock]:
        sentence_units = [segment.strip() for segment in SENTENCE_SPLIT_PATTERN.split(block.text) if segment.strip()]
        if len(sentence_units) > 1:
            sentence_blocks = [
                _ChunkBlock(text=sentence, page_numbers=list(block.page_numbers))
                for sentence in sentence_units
            ]
            return self._split_units(sentence_blocks, target_words, overlap_words)
        return self._split_words(block, target_words, overlap_words)

    def _split_units(
        self,
        units: list[_ChunkBlock],
        target_words: int,
        overlap_words: int,
    ) -> list[_ChunkBlock]:
        segments: list[_ChunkBlock] = []
        current_units: list[_ChunkBlock] = []
        current_words = 0
        index = 0
        while index < len(units):
            unit = units[index]
            unit_words = _word_count(unit.text)
            if current_units and current_words + unit_words > target_words:
                text = " ".join(part.text for part in current_units if part.text).strip()
                if text:
                    segments.append(
                        _ChunkBlock(
                            text=text,
                            page_numbers=_union_page_numbers(current_units),
                        )
                    )
                current_units, current_words = self._build_overlap_blocks(
                    current_units,
                    overlap_words,
                    incoming_words=unit_words,
                    target_words=target_words,
                )
                continue
            current_units.append(unit)
            current_words += unit_words
            index += 1
        if current_units:
            text = " ".join(part.text for part in current_units if part.text).strip()
            if text:
                segments.append(
                    _ChunkBlock(
                        text=text,
                        page_numbers=_union_page_numbers(current_units),
                    )
                )
        return segments or [units[0]]

    def _split_words(
        self,
        block: _ChunkBlock,
        target_words: int,
        overlap_words: int,
    ) -> list[_ChunkBlock]:
        words = block.text.split()
        segments: list[_ChunkBlock] = []
        start = 0
        while start < len(words):
            end = min(len(words), start + target_words)
            segment = " ".join(words[start:end]).strip()
            if segment:
                segments.append(_ChunkBlock(text=segment, page_numbers=list(block.page_numbers)))
            if end >= len(words):
                break
            start = max(start + 1, end - overlap_words)
        return segments or [block]

    def _build_chunk(
        self,
        document: IntermediateDocument,
        counter: int,
        section_path: list[str],
        text: str,
        page_numbers: list[int],
    ) -> ChunkRecord:
        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        content_type = _infer_chunk_content_type(section_path, text)
        tags = [document.format, document.complexity, self.policy.name]
        if content_type != "text":
            tags.append(content_type)
        return ChunkRecord(
            chunk_id=f"{document.doc_id}-chunk-{counter:04d}",
            doc_id=document.doc_id,
            source_name=document.source_name,
            source_uri=document.source_uri,
            page_numbers=page_numbers,
            section_path=section_path,
            content_type=content_type,
            checksum=checksum,
            clean_text=text,
            token_estimate=_token_estimate(text),
            tags=tags,
        )
