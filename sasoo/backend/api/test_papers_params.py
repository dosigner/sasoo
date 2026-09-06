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
            patch("api.papers.get_visual_row_counts", new=AsyncMock(return_value=(0, 0))),
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
            patch("api.papers.get_visual_row_counts", new=AsyncMock(return_value=(0, 0))),
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
        updated_row["domain"] = "ai_ml"
        updated_row["agent_used"] = "neural"

        update = PaperUpdate(domain="ai_ml")

        fake_agent = type("FakeAgent", (), {"name": "neural"})()

        with (
            patch("api.papers.fetch_one", new=AsyncMock(side_effect=[existing_row, updated_row])),
            patch("api.papers.execute_update", new=AsyncMock()) as execute_update_mock,
            patch("api.papers.get_visual_row_counts", new=AsyncMock(return_value=(0, 0))),
            patch("api.papers.resolve_artifact_status_contract", new=AsyncMock(return_value=_FAKE_ARTIFACT_STATUS)),
            patch("api.papers.get_paper_dir", return_value=Path("/tmp/sasoo-test-nonexistent-paper-dir")),
            patch("services.agents.get_agent_for_domain", return_value=fake_agent) as get_agent_mock,
        ):
            response = await papers.update_paper(paper_id, update)

        # agent_used must be derived from the new domain, not left stale.
        get_agent_mock.assert_called_once_with("ai_ml")
        sql, params = execute_update_mock.await_args.args
        self.assertIn("domain = ?", sql)
        self.assertIn("agent_used = ?", sql)
        self.assertIn("neural", params)
        self.assertEqual(response.agent_used, "neural")
        self.assertEqual(response.domain, "ai_ml")

    async def test_patch_explicit_agent_used_not_overridden(self) -> None:
        """If the caller explicitly sets agent_used, domain-based recompute must not clobber it."""
        paper_id = 4
        existing_row = _base_paper_row(paper_id)

        updated_row = dict(existing_row)
        updated_row["domain"] = "ai_ml"
        updated_row["agent_used"] = "circuit"

        update = PaperUpdate(domain="ai_ml", agent_used="circuit")

        with (
            patch("api.papers.fetch_one", new=AsyncMock(side_effect=[existing_row, updated_row])),
            patch("api.papers.execute_update", new=AsyncMock()) as execute_update_mock,
            patch("api.papers.get_visual_row_counts", new=AsyncMock(return_value=(0, 0))),
            patch("api.papers.resolve_artifact_status_contract", new=AsyncMock(return_value=_FAKE_ARTIFACT_STATUS)),
            patch("api.papers.get_paper_dir", return_value=Path("/tmp/sasoo-test-nonexistent-paper-dir")),
            patch("services.agents.get_agent_for_domain") as get_agent_mock,
        ):
            response = await papers.update_paper(paper_id, update)

        get_agent_mock.assert_not_called()
        sql, params = execute_update_mock.await_args.args
        self.assertIn("circuit", params)
        self.assertEqual(response.agent_used, "circuit")


class _FakeCursor:
    def __init__(self, rowcount: int = 1):
        self.rowcount = rowcount


class _FakeDb:
    """analysis_runs 함수(request_cancel 등)가 기대하는 conn.execute/.commit만 지원하는 더블."""

    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []

    async def execute(self, sql, params=()):
        self.executed.append((sql, params))
        return _FakeCursor()

    async def commit(self):
        return None


class DeletePaperCleansAnalysisRunsTests(unittest.IsolatedAsyncioTestCase):
    """I4: 논문 삭제가 analysis_runs를 정리하지 않으면 reconcile_stale ①에서 papers 조회가
    NULL(terminal 아님)로 보여 ④ requeue가 삭제된 논문에 워커를 재스폰한다(FK 위반·파일 오류)."""

    async def test_delete_paper_requests_cancel_and_deletes_run_rows(self) -> None:
        paper_id = 1
        existing_row = _base_paper_row(paper_id)
        fake_db = _FakeDb()

        with (
            patch("api.papers.fetch_one", new=AsyncMock(return_value=existing_row)),
            patch("api.papers.get_db", new=AsyncMock(return_value=fake_db)),
            patch("api.papers.get_paper_dir", return_value=Path("/tmp/sasoo-test-nonexistent-paper-dir")),
        ):
            await papers.delete_paper(paper_id)

        sqls = [sql for sql, _ in fake_db.executed]
        self.assertTrue(
            any("cancel_requested" in sql for sql in sqls),
            "delete_paper이 실행 중 워커에 취소를 요청하지 않음(request_cancel 누락)",
        )
        self.assertTrue(
            any("DELETE FROM analysis_runs" in sql for sql in sqls),
            "delete_paper이 analysis_runs 잔여 행을 정리하지 않음 — 삭제된 논문에 리컨실러가 재spawn할 수 있음",
        )
        delete_papers_idx = next(i for i, sql in enumerate(sqls) if "DELETE FROM papers" in sql)
        delete_runs_idx = next(i for i, sql in enumerate(sqls) if "DELETE FROM analysis_runs" in sql)
        self.assertLess(delete_runs_idx, delete_papers_idx)


if __name__ == "__main__":
    unittest.main()
