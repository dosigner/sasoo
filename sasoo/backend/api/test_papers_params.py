"""
Tests for Task 3: papers DB expansion — analysis params + chain checkpoint columns.

Follows the mock-based unittest.IsolatedAsyncioTestCase style used in
api/test_settings.py: the route function is awaited directly with its DB/IO
dependencies patched, rather than going through an HTTP test client (this
project has no FastAPI TestClient fixture wired up in api/).
"""

import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from api import papers
from models.schemas import PaperUpdate
from services.artifact_status import ArtifactStatusContract


def _base_paper_row(paper_id: int = 1) -> dict:
    return {
        "id": paper_id,
        "title": "Sample Paper",
        "authors": "A. Author",
        "year": 2024,
        "journal": "Journal of Testing",
        "doi": "10.1234/test",
        "domain": "optics",
        "agent_used": "photon",
        "folder_name": "sample-paper-folder",
        "tags": None,
        "status": "pending",
        "analyzed_at": None,
        "notes": None,
        "created_at": "2024-01-01T00:00:00",
        "explanation_level": None,
        "analysis_focus": None,
        "pdf_file_uri": None,
        "pdf_file_expires_at": None,
    }


_FAKE_ARTIFACT_STATUS = ArtifactStatusContract(
    text_ready=True,
    visual_ready=True,
    visual_state="ready",
    visual_error=None,
)


class UpdatePaperAnalysisParamsTests(unittest.IsolatedAsyncioTestCase):
    async def test_patch_paper_analysis_params(self) -> None:
        paper_id = 1
        existing_row = _base_paper_row(paper_id)

        updated_row = dict(existing_row)
        updated_row["explanation_level"] = "high"
        updated_row["analysis_focus"] = json.dumps(
            {"chips": ["reproduction", "theory"], "note": "격자 정합 조건이 궁금함"},
            ensure_ascii=False,
        )

        update = PaperUpdate(
            explanation_level="high",
            analysis_focus={"chips": ["reproduction", "theory"], "note": "격자 정합 조건이 궁금함"},
        )

        with (
            patch("api.papers.fetch_one", new=AsyncMock(side_effect=[existing_row, updated_row])),
            patch("api.papers.execute_update", new=AsyncMock()) as execute_update_mock,
            patch("api.papers._get_visual_row_counts", new=AsyncMock(return_value=(0, 0))),
            patch("api.papers.resolve_artifact_status_contract", new=AsyncMock(return_value=_FAKE_ARTIFACT_STATUS)),
            patch("api.papers.get_paper_dir", return_value=Path("/tmp/sasoo-test-nonexistent-paper-dir")),
        ):
            response = await papers.update_paper(paper_id, update)

        # The UPDATE statement must serialize analysis_focus to a JSON string.
        execute_update_mock.assert_awaited_once()
        sql, params = execute_update_mock.await_args.args
        self.assertIn("explanation_level = ?", sql)
        self.assertIn("analysis_focus = ?", sql)
        analysis_focus_param = params[list(update.model_dump(exclude_none=True).keys()).index("analysis_focus")]
        self.assertIsInstance(analysis_focus_param, str)
        self.assertEqual(
            json.loads(analysis_focus_param),
            {"chips": ["reproduction", "theory"], "note": "격자 정합 조건이 궁금함"},
        )

        data = response.model_dump()
        self.assertEqual(data["explanation_level"], "high")
        parsed_focus = json.loads(data["analysis_focus"]) if isinstance(data["analysis_focus"], str) else data["analysis_focus"]
        self.assertEqual(parsed_focus, {"chips": ["reproduction", "theory"], "note": "격자 정합 조건이 궁금함"})

    async def test_patch_paper_existing_fields_still_work(self) -> None:
        """Regression guard: PATCH of pre-existing fields (e.g. notes) is unaffected."""
        paper_id = 2
        existing_row = _base_paper_row(paper_id)

        updated_row = dict(existing_row)
        updated_row["notes"] = "업데이트된 메모"

        update = PaperUpdate(notes="업데이트된 메모")

        with (
            patch("api.papers.fetch_one", new=AsyncMock(side_effect=[existing_row, updated_row])),
            patch("api.papers.execute_update", new=AsyncMock()) as execute_update_mock,
            patch("api.papers._get_visual_row_counts", new=AsyncMock(return_value=(0, 0))),
            patch("api.papers.resolve_artifact_status_contract", new=AsyncMock(return_value=_FAKE_ARTIFACT_STATUS)),
            patch("api.papers.get_paper_dir", return_value=Path("/tmp/sasoo-test-nonexistent-paper-dir")),
        ):
            response = await papers.update_paper(paper_id, update)

        sql, params = execute_update_mock.await_args.args
        self.assertEqual(sql, "UPDATE papers SET notes = ? WHERE id = ?")
        self.assertEqual(params, ("업데이트된 메모", paper_id))
        self.assertEqual(response.notes, "업데이트된 메모")


class UpdatePaperDomainSyncsAgentUsedTests(unittest.IsolatedAsyncioTestCase):
    async def test_patch_domain_recomputes_agent_used(self) -> None:
        """Task 13: PATCH {domain} must also refresh agent_used to match."""
        paper_id = 3
        existing_row = _base_paper_row(paper_id)  # domain=optics, agent_used=photon

        updated_row = dict(existing_row)
        updated_row["domain"] = "materials"
        updated_row["agent_used"] = "crystal"

        update = PaperUpdate(domain="materials")

        fake_agent = type("FakeAgent", (), {"name": "crystal"})()

        with (
            patch("api.papers.fetch_one", new=AsyncMock(side_effect=[existing_row, updated_row])),
            patch("api.papers.execute_update", new=AsyncMock()) as execute_update_mock,
            patch("api.papers._get_visual_row_counts", new=AsyncMock(return_value=(0, 0))),
            patch("api.papers.resolve_artifact_status_contract", new=AsyncMock(return_value=_FAKE_ARTIFACT_STATUS)),
            patch("api.papers.get_paper_dir", return_value=Path("/tmp/sasoo-test-nonexistent-paper-dir")),
            patch("services.agents.get_agent_for_domain", return_value=fake_agent) as get_agent_mock,
        ):
            response = await papers.update_paper(paper_id, update)

        # agent_used must be derived from the new domain, not left stale.
        get_agent_mock.assert_called_once_with("materials")
        sql, params = execute_update_mock.await_args.args
        self.assertIn("domain = ?", sql)
        self.assertIn("agent_used = ?", sql)
        self.assertIn("crystal", params)
        self.assertEqual(response.agent_used, "crystal")
        self.assertEqual(response.domain, "materials")

    async def test_patch_explicit_agent_used_not_overridden(self) -> None:
        """If the caller explicitly sets agent_used, domain-based recompute must not clobber it."""
        paper_id = 4
        existing_row = _base_paper_row(paper_id)

        updated_row = dict(existing_row)
        updated_row["domain"] = "materials"
        updated_row["agent_used"] = "atlas"

        update = PaperUpdate(domain="materials", agent_used="atlas")

        with (
            patch("api.papers.fetch_one", new=AsyncMock(side_effect=[existing_row, updated_row])),
            patch("api.papers.execute_update", new=AsyncMock()) as execute_update_mock,
            patch("api.papers._get_visual_row_counts", new=AsyncMock(return_value=(0, 0))),
            patch("api.papers.resolve_artifact_status_contract", new=AsyncMock(return_value=_FAKE_ARTIFACT_STATUS)),
            patch("api.papers.get_paper_dir", return_value=Path("/tmp/sasoo-test-nonexistent-paper-dir")),
            patch("services.agents.get_agent_for_domain") as get_agent_mock,
        ):
            response = await papers.update_paper(paper_id, update)

        get_agent_mock.assert_not_called()
        sql, params = execute_update_mock.await_args.args
        self.assertIn("atlas", params)
        self.assertEqual(response.agent_used, "atlas")


if __name__ == "__main__":
    unittest.main()
