"""Offline contracts for parallel analysis scheduling and result persistence."""

import asyncio
import json
import os
import threading
from unittest.mock import AsyncMock, patch

from models import database
from models.schemas import AnalysisStatus
from services import analysis_execution as ae
from services.test_viz_partial_retry import PipelineCase
from services.viz import figure_gen


class ParallelVisualizationTests(PipelineCase):
    async def test_failed_checkpoint_still_preserves_completed_sibling_and_usage(self):
        first_save_failed, release_html = asyncio.Event(), asyncio.Event()
        attempts = 0
        real_store = ae._store_visualization_progress
        plan = [{"tool": "mermaid", "title": "diagram", "diagram_type": "sequence"},
                {"tool": "html", "title": "interactive"}]

        async def mermaid(*args, **kwargs):
            return {"mermaid_code": "graph TD; A-->B", "requests": [{"id": "m", "cost_usd": 0.1}]}

        async def html(*args, **kwargs):
            await release_html.wait()
            return {"html_code": "<input><script></script>", "requests": [{"id": "h", "cost_usd": 0.2}]}

        async def store(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                first_save_failed.set()
                raise RuntimeError("temporary checkpoint failure")
            return await real_store(*args, **kwargs)

        with (
            patch.object(ae, "_plan_visualizations", new=AsyncMock(return_value=plan)),
            patch.object(ae, "_generate_single_mermaid", new=mermaid),
            patch.object(ae, "_generate_single_html", new=html),
            patch.object(ae, "_store_visualization_progress", new=store),
        ):
            task = asyncio.create_task(self.run_pipeline())
            try:
                await asyncio.wait_for(first_save_failed.wait(), 2)
            finally:
                release_html.set()
                with self.assertRaisesRegex(RuntimeError, "temporary checkpoint failure"):
                    await asyncio.wait_for(task, 2)
        rows = await database.fetch_all("SELECT result, cost_usd FROM analysis_results WHERE phase = 'visualization'")
        self.assertEqual(len(rows), 1)
        payload = json.loads(rows[0]["result"])
        self.assertEqual([item["id"] for item in payload["items"]], [1, 2])
        self.assertFalse(payload["complete"])
        self.assertAlmostEqual(rows[0]["cost_usd"], 0.3)

    async def test_revoked_run_cannot_overwrite_replacement_checkpoint(self):
        row_id = await self.insert_viz(
            [{"id": 1, "tool": "mermaid", "status": "completed", "mermaid_code": "NEW"}],
            input_hash=ae.compute_input_hash("shared-cache"), run_token="new-run",
        )
        with self.assertRaisesRegex(RuntimeError, "replaced"):
            await ae._store_visualization_progress(
                7, [{"id": 1, "tool": "mermaid", "status": "completed", "mermaid_code": "OLD"}],
                "shared-cache", done=False, run_token="old-run",
            )
        self.assertEqual((await self.stored_items(row_id))[1]["mermaid_code"], "NEW")

    async def test_types_overlap_and_each_completion_is_saved_before_synthesis_finishes(self):
        names = ("synthesis", "mermaid", "image", "html")
        started = {name: asyncio.Event() for name in names}
        release = {name: asyncio.Event() for name in names}
        saved = asyncio.Queue()
        status = AnalysisStatus(paper_id=7, overall_status="running")
        writers = 0
        real_store = ae._store_visualization_progress

        async def synthesize(*args, **kwargs):
            started["synthesis"].set()
            await release["synthesis"].wait()

        def generate(name, payload):
            async def call(*args, **kwargs):
                started[name].set()
                await release[name].wait()
                return {**payload, "requests": [{"id": name, "cost_usd": 0.1}]}
            return call

        async def store(*args, **kwargs):
            nonlocal writers
            writers += 1
            self.assertEqual(writers, 1)
            try:
                await asyncio.sleep(0)
                result = await real_store(*args, **kwargs)
                saved.put_nowait(([item["id"] for item in result], kwargs["done"]))
                return result
            finally:
                writers -= 1

        with (
            patch.object(ae, "_run_synthesis", new=synthesize),
            patch.object(ae, "_generate_single_mermaid", new=generate("mermaid", {"mermaid_code": "graph TD; A-->B"})),
            patch.object(ae, "_generate_single_paperbanana", new=generate("image", {"image_path": "/mock/1.png"})),
            patch.object(ae, "_generate_single_html", new=generate("html", {"html_code": "<input><script></script>"})),
            patch.object(ae, "_store_visualization_progress", new=store),
        ):
            task = asyncio.create_task(ae._run_visualizations(
                7, "source", "folder", ["previous"], "recipe", "deep", status, provider="openai",
            ))
            try:
                await asyncio.wait_for(asyncio.gather(*(event.wait() for event in started.values())), 2)
                self.assertEqual(await asyncio.wait_for(saved.get(), 2), ([], False))
                release["html"].set()
                self.assertEqual(await asyncio.wait_for(saved.get(), 2), ([3], False))
                self.assertFalse(task.done())
                release["mermaid"].set()
                release["image"].set()
                while True:
                    ids, done = await asyncio.wait_for(saved.get(), 2)
                    if done:
                        break
                self.assertEqual(ids, [1, 2, 3])
                self.assertLess(status.progress_pct, 100)
                self.assertFalse(task.done(), "the synthesis sibling is still running")
            finally:
                for event in release.values():
                    event.set()
                result = await asyncio.wait_for(task, 2)
        self.assertEqual([item["id"] for item in result], [1, 2, 3])
        rows = await self.viz_rows()
        self.assertEqual(len(rows), 1)
        payload = json.loads(rows[0]["result"])
        self.assertAlmostEqual(payload["items"][0]["requests"][0]["cost_usd"], 0.1)
        self.assertEqual({record["id"] for item in payload["items"] for record in item["requests"]}, {"image", "mermaid", "html"})
        self.assertEqual(payload["cost_unknown_count"], 0)

    async def _cancel_after_first_image(self, *, force):
        cancel = asyncio.Event()
        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        plan = [
            {"tool": "paperbanana", "title": purpose, "diagram_type": purpose,
             "importance": 80, "difficulty": 40}
            for purpose in ("structure", "process")
        ]

        async def generate(_paper_id, item, *args, **kwargs):
            calls.append(item["id"])
            started.set()
            await release.wait()
            return {"image_path": "/mock/first.png", "requests": [{"id": "issued", "cost_usd": None}]}

        before_cancel = None
        with (
            patch.dict(ae._cancel_events, {7: cancel}),
            patch.object(ae, "_plan_visualizations", new=AsyncMock(return_value=plan)),
            patch.object(ae, "_generate_single_paperbanana", new=generate),
        ):
            task = asyncio.create_task(self.run_pipeline())
            try:
                await asyncio.wait_for(started.wait(), 2)
                if force:
                    before_cancel = await self.viz_rows()
                    task.cancel()
                    await asyncio.wait_for(cancel.wait(), 2)
                    with self.assertRaises(asyncio.CancelledError):
                        await asyncio.wait_for(task, 2)
                else:
                    cancel.set()
                    self.assertFalse(task.done(), "issued work must finish and be recorded")
            finally:
                release.set()
                if force:
                    with self.assertRaises(asyncio.CancelledError):
                        await asyncio.wait_for(task, 2)
                else:
                    await asyncio.wait_for(task, 2)
        self.assertEqual(calls, [1])
        if force:
            self.assertEqual(await self.viz_rows(), before_cancel, "a revoked worker must not write a late result")
            return
        payload = json.loads((await self.viz_rows())[0]["result"])
        self.assertFalse(payload["complete"])
        self.assertEqual([item["id"] for item in payload["items"]], [1])
        self.assertTrue(payload["cost_incomplete"])
        self.assertEqual(payload["cost_unknown_count"], 1)

    async def test_user_cancel_stops_next_image_and_keeps_issued_usage(self):
        await self._cancel_after_first_image(force=False)

    async def test_task_cancel_stops_revoked_worker_without_late_writes(self):
        await self._cancel_after_first_image(force=True)

    async def test_cancel_during_planning_does_not_start_generation(self):
        cancel = asyncio.Event()

        async def plan(*args, **kwargs):
            cancel.set()
            return [{"tool": "mermaid", "title": "diagram", "diagram_type": "sequence"}]

        with (
            patch.dict(ae._cancel_events, {7: cancel}),
            patch.object(ae, "_plan_visualizations", new=plan),
            patch.object(ae, "_generate_single_mermaid", new=AsyncMock()) as generate,
        ):
            self.assertEqual(await self.run_pipeline(), [])
        generate.assert_not_awaited()

    async def test_synthesis_failure_does_not_cancel_visualizations(self):
        self.html_fails = False
        with patch.object(ae, "_run_synthesis", new=AsyncMock(side_effect=ValueError("bad synthesis"))):
            items = await self.run_pipeline()
        self.assertEqual({item["tool"] for item in items if item["status"] == "completed"}, {"mermaid", "html"})

    async def test_complete_cache_is_reused_while_synthesis_is_still_running(self):
        os.environ["OPENAI_API_KEY"] = "test"
        self.html_fails = False
        await self.run_pipeline()
        before = dict(self.calls)
        entered, release = asyncio.Event(), asyncio.Event()
        status = AnalysisStatus(paper_id=7, overall_status="running")

        async def synthesis(*args, **kwargs):
            entered.set()
            await release.wait()

        with patch.object(ae, "_run_synthesis", new=synthesis):
            task = asyncio.create_task(ae._run_visualizations(
                7, "source", "folder", ["previous"], "recipe", "deep", status, provider="openai",
            ))
            try:
                await asyncio.wait_for(entered.wait(), 2)
                self.assertFalse(task.done())
                self.assertLess(status.progress_pct, 100)
            finally:
                release.set()
                items = await asyncio.wait_for(task, 2)
        self.assertEqual(len(items), 3)
        self.assertEqual(self.calls, before)


class RenderSlotTests(PipelineCase):
    async def _check_slot(self, *, timeout):
        semaphore = asyncio.Semaphore(1)
        started, release, ended = threading.Event(), threading.Event(), threading.Event()

        class Provider:
            name = "openai"
            cost_key = "gpt-image-2.5-flare:high"

            def available(self):
                return True

            def generate(self, description):
                started.set()
                release.wait(3)
                ended.set()
                return b"png"

        with (
            patch.object(figure_gen, "RENDER_SEM", semaphore),
            patch.object(figure_gen, "RENDER_TIMEOUT_S", 0.03 if timeout else 2),
            patch.object(figure_gen, "_plan_description", new=AsyncMock(return_value=("description", {"id": "description", "cost_usd": 0.1}))),
            patch.object(figure_gen, "build_providers", return_value=[Provider()]),
        ):
            task = asyncio.create_task(figure_gen.generate_illustration(
                {"title": "one"}, str(database.get_paper_dir("folder")),
            ))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                if timeout:
                    result = await asyncio.wait_for(task, 2)
                    self.assertIn("timeout", result.error)
                    self.assertIsNone(result.requests[-1]["cost_usd"])
                else:
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertTrue(semaphore.locked())
                self.assertFalse(ended.is_set())
            finally:
                release.set()
                jobs = [job for job in figure_gen._render_jobs if job.get_loop() is asyncio.get_running_loop()]
                await asyncio.wait_for(asyncio.gather(*jobs), 2)
        self.assertFalse(semaphore.locked())

    async def test_cancel_keeps_slot_until_provider_thread_finishes(self):
        await self._check_slot(timeout=False)

    async def test_timeout_keeps_slot_and_records_unknown_render_cost(self):
        await self._check_slot(timeout=True)
