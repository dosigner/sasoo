import unittest
from unittest.mock import AsyncMock, patch

from services.analysis_results import (
    get_latest_completed_phase_row,
    get_latest_completed_phase_rows,
)


class LatestCompletedPhaseRowsTests(unittest.IsolatedAsyncioTestCase):
    async def test_multiple_reruns_return_only_newest_row(self):
        rows = [
            {"id": 9, "paper_id": 7, "phase": "recipe", "result": '{"title":"new"}', "created_at": "2026-03-02 10:00:00"},
            {"id": 4, "paper_id": 7, "phase": "recipe", "result": '{"title":"old"}', "created_at": "2026-03-01 10:00:00"},
            {"id": 3, "paper_id": 7, "phase": "visual", "result": '{"figure_count":2}', "created_at": "2026-03-01 09:00:00"},
        ]

        with patch("services.analysis_results.fetch_all", new=AsyncMock(return_value=rows)) as fetch_all_mock:
            latest = await get_latest_completed_phase_rows(7, phases=["recipe", "visual"])

        self.assertEqual(latest["recipe"]["id"], 9)
        self.assertEqual(latest["recipe"]["parsed_result"]["title"], "new")
        self.assertEqual(latest["visual"]["id"], 3)
        query = fetch_all_mock.await_args.args[0]
        self.assertIn("ORDER BY created_at DESC, id DESC", query)

    async def test_identical_timestamps_break_ties_by_newest_id(self):
        row = {
            "id": 12,
            "paper_id": 7,
            "phase": "recipe",
            "result": '{"title":"latest"}',
            "created_at": "2026-03-02 10:00:00",
        }

        with patch("services.analysis_results.fetch_one", new=AsyncMock(return_value=row)) as fetch_one_mock:
            latest = await get_latest_completed_phase_row(7, "recipe")

        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest["id"], 12)
        query = fetch_one_mock.await_args.args[0]
        self.assertIn("ORDER BY created_at DESC, id DESC", query)

    async def test_error_rows_are_excluded(self):
        rows = [
            {"id": 100, "paper_id": 7, "phase": "error", "result": '{"error":"boom"}', "created_at": "2026-03-03 10:00:00"},
            {"id": 9, "paper_id": 7, "phase": "recipe", "result": '{"title":"usable"}', "created_at": "2026-03-02 10:00:00"},
        ]

        with patch("services.analysis_results.fetch_all", new=AsyncMock(return_value=rows)) as fetch_all_mock:
            latest = await get_latest_completed_phase_rows(7)

        self.assertNotIn("error", latest)
        self.assertEqual(latest["recipe"]["parsed_result"]["title"], "usable")
        query = fetch_all_mock.await_args.args[0]
        self.assertIn("phase != 'error'", query)


if __name__ == "__main__":
    unittest.main()
