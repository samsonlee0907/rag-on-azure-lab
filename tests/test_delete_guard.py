from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app import _delete_job_artifacts, _is_repo_managed_path
from backend.core.config import settings
from backend.domain.models import JobRecord


class DeleteGuardTests(unittest.TestCase):
    def test_external_source_path_is_not_managed(self) -> None:
        with TemporaryDirectory() as outside:
            external = Path(outside) / "Deep Excavation.pdf"
            external.write_bytes(b"%PDF-1.4 reference only")
            self.assertFalse(_is_repo_managed_path(external))

    def test_uploads_path_is_managed(self) -> None:
        managed = settings.uploads_dir / "doc_report.pdf"
        self.assertTrue(_is_repo_managed_path(managed))

    def test_delete_job_artifacts_preserves_external_source(self) -> None:
        with TemporaryDirectory() as outside, TemporaryDirectory() as artifacts:
            external_source = Path(outside) / "Deep Excavation.pdf"
            external_source.write_bytes(b"%PDF-1.4 original reference file")

            artifacts_dir = Path(artifacts)
            chunks_path = artifacts_dir / "doc-1_chunks.json"
            chunks_path.write_text("[]", encoding="utf-8")

            job = JobRecord(
                doc_id="doc-1",
                file_name="Deep Excavation.pdf",
                stored_path=str(external_source),
                chunks_path=str(chunks_path),
            )

            with (
                patch.object(settings, "artifacts_dir", artifacts_dir),
                patch.object(settings, "data_dir", artifacts_dir),
                patch.object(settings, "uploads_dir", artifacts_dir),
                patch("backend.app.build_blob_artifact_store", return_value=None),
            ):
                _delete_job_artifacts(job)

            # The external source must survive; managed artifacts may be removed.
            self.assertTrue(external_source.exists())
            self.assertFalse(chunks_path.exists())


if __name__ == "__main__":
    unittest.main()
