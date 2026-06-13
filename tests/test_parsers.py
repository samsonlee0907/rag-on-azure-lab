from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from backend.services.parsers import AzureDocumentIntelligenceParser, parser_registry


class ParserTests(unittest.TestCase):
    def test_markdown_parser_creates_sections(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "guide.md"
            path.write_text("# Heading\n\nFirst paragraph.\n\n## Details\n\nSecond paragraph.", encoding="utf-8")

            profile = parser_registry.detect(path)
            document = parser_registry.parse(path, "doc-123", profile)

            self.assertEqual(profile.parser_path, "local_simple_parser")
            self.assertEqual(len(document.sections), 2)
            self.assertEqual(document.sections[0].heading, "Heading")
            self.assertIn("Second paragraph.", document.sections[1].paragraphs)

    def test_workshop_strict_mode_blocks_pdf_fallback_path(self) -> None:
        with TemporaryDirectory() as directory, patch(
            "backend.services.parsers.settings.workshop_strict_mode",
            True,
        ), patch(
            "backend.services.parsers.settings.azure_document_intelligence_endpoint",
            "",
        ), patch(
            "backend.services.parsers.settings.azure_document_intelligence_key",
            "",
        ):
            path = Path(directory) / "sample.pdf"
            path.write_bytes(b"%PDF-1.4\n% workshop test\n")

            profile = parser_registry.detect(path)

            self.assertEqual(profile.parser_path, "strict_configuration_error")
            with self.assertRaises(RuntimeError):
                parser_registry.parse(path, "doc-123", profile)

    def test_workshop_strict_mode_blocks_unsupported_format(self) -> None:
        with TemporaryDirectory() as directory, patch(
            "backend.services.parsers.settings.workshop_strict_mode",
            True,
        ):
            path = Path(directory) / "archive.zip"
            path.write_bytes(b"PK\x03\x04")

            profile = parser_registry.detect(path)

            self.assertEqual(profile.parser_path, "strict_configuration_error")
            with self.assertRaises(RuntimeError):
                parser_registry.parse(path, "doc-zip", profile)

    def test_document_intelligence_parser_uses_roles_to_build_sections_and_drops_page_artifacts(self) -> None:
        parser = AzureDocumentIntelligenceParser()
        result = {
            "paragraphs": [
                {"content": "1", "role": "pageNumber", "boundingRegions": [{"pageNumber": 1}]},
                {"content": "CONTENTS", "role": "title", "boundingRegions": [{"pageNumber": 1}]},
                {"content": "Suspended Ceilings 629", "boundingRegions": [{"pageNumber": 1}]},
                {"content": "Paints and Painting", "role": "sectionHeading", "boundingRegions": [{"pageNumber": 633}]},
                {
                    "content": "Composition ~ the basic components are binder, pigment, and solvents.",
                    "boundingRegions": [{"pageNumber": 633}],
                },
            ]
        }

        blocks = parser._extract_paragraph_blocks(result)
        sections = parser._build_structured_sections(blocks, "Layout Extraction")

        self.assertEqual([section.heading for section in sections], ["CONTENTS", "Paints and Painting"])
        self.assertEqual(sections[0].paragraphs, ["Suspended Ceilings 629"])
        self.assertEqual(sections[1].paragraphs[0], "Composition ~ the basic components are binder, pigment, and solvents.")


if __name__ == "__main__":
    unittest.main()
