import unittest

from backend.domain.models import IntermediateDocument, ParagraphSpan, SectionNode
from backend.services.chunking import ChunkPolicy, StructureAwareChunker


class ChunkingTests(unittest.TestCase):
    def test_structure_aware_chunker_preserves_section_path_and_paragraph_boundaries(self) -> None:
        document = IntermediateDocument(
            doc_id="doc-1",
            source_name="sample.txt",
            source_path="sample.txt",
            format="txt",
            complexity="simple",
            parser_path="local_simple_parser",
            sections=[
                SectionNode(
                    heading="Policy",
                    paragraphs=[
                        " ".join(["travel"] * 45) + ".",
                        " ".join(["expense"] * 45) + ".",
                        " ".join(["approval"] * 45) + ".",
                    ],
                    paragraph_spans=[
                        ParagraphSpan(page_start=4, page_end=4),
                        ParagraphSpan(page_start=5, page_end=5),
                        ParagraphSpan(page_start=6, page_end=6),
                    ],
                )
            ],
        )
        chunker = StructureAwareChunker(ChunkPolicy(chunk_size_tokens=80, overlap_tokens=20))

        chunks = chunker.chunk(document)

        self.assertGreaterEqual(len(chunks), 2)
        self.assertEqual(chunks[0].section_path, ["Policy"])
        self.assertTrue(all(chunk.clean_text for chunk in chunks))
        self.assertTrue(chunks[0].clean_text.endswith("."))
        self.assertEqual(chunks[0].page_numbers, [4])
        self.assertEqual(chunks[1].page_numbers, [5])

    def test_structure_aware_chunker_uses_narrow_page_spans_for_multi_paragraph_chunks(self) -> None:
        document = IntermediateDocument(
            doc_id="doc-2",
            source_name="sample.pdf",
            source_path="sample.pdf",
            format="pdf",
            complexity="complex",
            parser_path="azure_document_intelligence",
            sections=[
                SectionNode(
                    heading="Section 1. Overview",
                    page_start=1,
                    page_end=200,
                    paragraphs=[
                        "Grid planning starts earlier in the lifecycle.",
                        "Utility coordination shapes the schedule.",
                    ],
                    paragraph_spans=[
                        ParagraphSpan(page_start=18, page_end=18),
                        ParagraphSpan(page_start=19, page_end=19),
                    ],
                )
            ],
        )

        chunker = StructureAwareChunker(ChunkPolicy(chunk_size_tokens=80, overlap_tokens=10))
        chunks = chunker.chunk(document)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].page_numbers, [18, 19])

    def test_chunker_marks_table_of_contents_chunks_for_filtering(self) -> None:
        document = IntermediateDocument(
            doc_id="doc-3",
            source_name="handbook.pdf",
            source_path="handbook.pdf",
            format="pdf",
            complexity="complex",
            parser_path="azure_document_intelligence",
            sections=[
                SectionNode(
                    heading="Contents",
                    paragraphs=[
                        "Suspended Ceilings 629\nPaints and Painting 633\nConcrete Claddings 512\nThermal insulation 517"
                    ],
                    paragraph_spans=[ParagraphSpan(page_start=2, page_end=2)],
                )
            ],
        )

        chunker = StructureAwareChunker(ChunkPolicy(chunk_size_tokens=120, overlap_tokens=20))
        chunks = chunker.chunk(document)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].content_type, "table_of_contents")
        self.assertIn("table_of_contents", chunks[0].tags)

    def test_chunker_marks_flattened_toc_continuation_as_table_of_contents(self) -> None:
        document = IntermediateDocument(
            doc_id="doc-3b",
            source_name="handbook.pdf",
            source_path="handbook.pdf",
            format="pdf",
            complexity="complex",
            parser_path="azure_document_intelligence",
            sections=[
                SectionNode(
                    heading="Part Three Builders Plant",
                    paragraphs=[
                        "Bulldozers 147 Scrapers 148 Graders 149 Tractor shovels 150 Excavators 151 "
                        "Transport vehicles 156 Hoists 159 Rubble chutes and skips 161 Cranes 162 Concreting plant 174"
                    ],
                    paragraph_spans=[ParagraphSpan(page_start=5, page_end=5)],
                )
            ],
        )

        chunker = StructureAwareChunker(ChunkPolicy(chunk_size_tokens=120, overlap_tokens=20))
        chunks = chunker.chunk(document)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].content_type, "table_of_contents")
        self.assertIn("table_of_contents", chunks[0].tags)

    def test_chunker_marks_diagram_label_chunks_for_filtering(self) -> None:
        document = IntermediateDocument(
            doc_id="doc-4",
            source_name="handbook.pdf",
            source_path="handbook.pdf",
            format="pdf",
            complexity="complex",
            parser_path="azure_document_intelligence",
            sections=[
                SectionNode(
                    heading="Typical Plan",
                    paragraphs=[
                        "trees and shrubs retaining walls paved areas rockeries planted areas pools and ponds artificial light"
                    ],
                    paragraph_spans=[ParagraphSpan(page_start=11, page_end=11)],
                )
            ],
        )

        chunker = StructureAwareChunker(ChunkPolicy(chunk_size_tokens=120, overlap_tokens=20))
        chunks = chunker.chunk(document)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].content_type, "diagram_labels")
        self.assertIn("diagram_labels", chunks[0].tags)


if __name__ == "__main__":
    unittest.main()
