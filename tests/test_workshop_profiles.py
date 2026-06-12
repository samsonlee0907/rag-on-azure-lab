from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.services.workshop_profiles import build_workshop_profile_summary, get_workshop_skill_profile


class WorkshopProfileTests(unittest.TestCase):
    def test_summary_reports_active_profile_and_same_document_strategy(self) -> None:
        with patch("backend.services.workshop_profiles.settings.workshop_skill_profile", "chunk_vector"):
            summary = build_workshop_profile_summary()

        self.assertTrue(summary["same_document_strategy"])
        self.assertEqual(summary["active_profile_id"], "chunk_vector")
        self.assertEqual(summary["profiles"][0]["id"], "baseline_extract")

    def test_unknown_profile_falls_back_to_baseline_extract(self) -> None:
        with patch("backend.services.workshop_profiles.settings.workshop_skill_profile", "does-not-exist"):
            profile = get_workshop_skill_profile()

        self.assertEqual(profile.id, "baseline_extract")

    def test_summary_includes_core_retrieval_tracks(self) -> None:
        summary = build_workshop_profile_summary()

        self.assertEqual(
            [track["id"] for track in summary["retrieval_tracks"]],
            ["full_text", "vector", "hybrid", "agentic"],
        )


if __name__ == "__main__":
    unittest.main()
