"""Visualization run identity: regeneration writes only into the run it started from."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api import analysis_routes, settings
from models import database


def _payload(items, **extra):
    return json.dumps({"items": items, "total_count": len(items), "complete": True, **extra}, ensure_ascii=False)


class IsolatedDbCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        directory = tempfile.TemporaryDirectory(prefix="sasoo-viz-runs-")
        self.addCleanup(directory.cleanup)
        root = Path(directory.name).resolve()
        for target, value in (("APP_DATA_ROOT", root), ("DB_PATH", root / "sasoo.db"), ("_db_connection", None)):
            patcher = patch.object(database, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {"SASOO_ENV": "production", "SASOO_APP_DATA_ROOT": str(root)})
        env.start()
        self.addCleanup(env.stop)
        defaults = patch.dict(settings.DEFAULT_SETTINGS, {"library_path": str(root / "library")})
        defaults.start()
        self.addCleanup(defaults.stop)
        database.invalidate_library_root_cache()
        await database.init_db()
        self.addAsyncCleanup(database.close_db)
        self.conn = await database.get_db()
        await self.conn.execute("INSERT INTO papers (id, title, folder_name) VALUES (7, 'Paper', 'folder')")
        await self.conn.commit()
        for target, value in (
            ("api.analysis_routes.active_provider", AsyncMock(return_value="openai")),
            ("api.analysis_routes.load_or_build_document_context", lambda *_: {"phase_inputs": {"visualization": "src"}}),
        ):
            patcher = patch(target, new=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def insert_viz(self, items, input_hash="run-a", **extra) -> int:
        cursor = await self.conn.execute(
            "INSERT INTO analysis_results (paper_id, phase, result, model_used, cost_usd, input_hash)"
            " VALUES (7, 'visualization', ?, 'planner', 0.1, ?)",
            (_payload(items, **extra), input_hash),
        )
        await self.conn.commit()
        return cursor.lastrowid

    async def stored_items(self, row_id: int) -> dict:
        row = await database.fetch_one("SELECT result FROM analysis_results WHERE id = ?", (row_id,))
        return {it["id"]: it for it in json.loads(row["result"])["items"]}


HTML_ITEM = {"id": 1, "tool": "html", "title": "old html", "status": "completed", "html_code": "old"}
MERMAID_ITEM = {"id": 2, "tool": "mermaid", "title": "old seq", "diagram_type": "sequence",
                "status": "completed", "mermaid_code": "sequenceDiagram\nA->>B: old"}


class RegenerationRunIdentityTests(IsolatedDbCase):
    async def test_reanalysis_during_regeneration_keeps_new_run_untouched(self):
        old_row = await self.insert_viz([HTML_ITEM])
        started, release = asyncio.Event(), asyncio.Event()

        async def slow_html(*_args, **_kwargs):
            started.set()
            await release.wait()
            return {"html_code": "<input><script>stale()</script>", "cost_usd": 0.02, "model_used": "m"}

        with patch("api.analysis_routes._generate_single_html", new=slow_html):
            task = asyncio.create_task(analysis_routes.regenerate_visualization(7, 1, run_id=old_row))
            await started.wait()
            new_row = await self.insert_viz([{**HTML_ITEM, "title": "new html", "html_code": "new"}], input_hash="run-b")
            release.set()
            with self.assertRaises(HTTPException) as ctx:
                await task

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual((await self.stored_items(new_row))[1]["html_code"], "new")
        self.assertEqual((await self.stored_items(old_row))[1]["html_code"], "old")

    async def test_stale_run_id_is_rejected_before_paid_generation(self):
        old_row = await self.insert_viz([HTML_ITEM])
        await self.insert_viz([HTML_ITEM], input_hash="run-b")
        generate = AsyncMock()
        with patch("api.analysis_routes._generate_single_html", new=generate):
            with self.assertRaises(HTTPException) as ctx:
                await analysis_routes.regenerate_visualization(7, 1, run_id=old_row)
        self.assertEqual(ctx.exception.status_code, 409)
        generate.assert_not_awaited()

    async def test_concurrent_regenerations_of_two_items_both_persist(self):
        row = await self.insert_viz([HTML_ITEM, MERMAID_ITEM])
        both_started = asyncio.Barrier(2)

        async def html(*_args, **_kwargs):
            await both_started.wait()
            return {"html_code": "<input><script>new()</script>", "cost_usd": 0.02, "model_used": "m"}

        async def mermaid(*_args, **_kwargs):
            await both_started.wait()
            return {"mermaid_code": "sequenceDiagram\nA->>B: new", "cost_usd": 0.001, "model_used": "m",
                    "requests": [{"kind": "mermaid", "model": "m", "cost_usd": 0.001}]}

        with patch("api.analysis_routes._generate_single_html", new=html), patch(
            "api.analysis_routes._generate_single_mermaid", new=mermaid
        ):
            await asyncio.gather(
                analysis_routes.regenerate_visualization(7, 1, run_id=row),
                analysis_routes.regenerate_visualization(7, 2, run_id=row),
            )

        stored = await self.stored_items(row)
        self.assertEqual(stored[1]["html_code"], "<input><script>new()</script>")
        self.assertEqual(stored[2]["mermaid_code"], "sequenceDiagram\nA->>B: new")

    async def test_plan_response_exposes_run_id(self):
        row = await self.insert_viz([HTML_ITEM])
        response = await analysis_routes.get_visualizations(7)
        self.assertEqual(response.run_id, row)


if __name__ == "__main__":
    unittest.main()


class HtmlCheckReportTests(IsolatedDbCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.row = await self.insert_viz([HTML_ITEM, MERMAID_ITEM])
        import hashlib
        self.sha = hashlib.sha256(HTML_ITEM["html_code"].encode()).hexdigest()

    def report(self, **overrides):
        from models.schemas import HtmlCheckReport
        body = {"run_id": self.row, "status": "failed", "issues": ["assertion failed: y=2x"], "html_sha256": self.sha}
        return HtmlCheckReport(**{**body, **overrides})

    async def test_failed_check_is_stored_and_makes_the_item_not_reusable(self):
        from services import analysis_execution as ae
        response = await analysis_routes.report_html_check(7, 1, self.report())
        self.assertEqual(response.execution_check["status"], "failed")
        stored = (await self.stored_items(self.row))[1]
        self.assertEqual(stored["execution_check"]["issues"], ["assertion failed: y=2x"])
        self.assertEqual(stored["status"], "completed")  # generated, but not executable
        self.assertFalse(ae._viz_item_reusable(stored, "folder"))
        self.assertTrue(ae._viz_item_reusable({**stored, "execution_check": {"status": "passed"}}, "folder"))

    async def test_check_of_other_code_or_run_or_item_is_refused(self):
        await self.insert_viz([HTML_ITEM], input_hash="run-b")
        for kwargs, viz_id, code in (({"html_sha256": "0" * 64}, 1, 409), ({}, 1, 409), ({}, 2, 404)):
            with self.subTest(kwargs=kwargs, viz_id=viz_id):
                newest = await database.fetch_one("SELECT MAX(id) AS id FROM analysis_results")
                run = self.row if code == 409 and not kwargs else newest["id"]
                with self.assertRaises(HTTPException) as ctx:
                    await analysis_routes.report_html_check(7, viz_id, self.report(run_id=run, **kwargs))
                self.assertEqual(ctx.exception.status_code, code)

    def test_report_schema_rejects_unknown_status_and_long_lists(self):
        from pydantic import ValidationError
        for overrides in ({"status": "verified"}, {"issues": ["x"] * 6}, {"html_sha256": "abc"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self.report(**overrides)
