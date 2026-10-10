"""A cached visualization run is reused only for items that really succeeded.

Runs the real pipeline against an isolated DB: plan cache, checkpoint rows and
generate_illustration. Paid APIs are replaced at the HTTP-client boundary.
"""

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

from api.test_visualization_runs import IsolatedDbCase
from models import database
from models.schemas import AnalysisStatus
from services import analysis_execution as ae
from services.viz import figure_gen

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 16
PLAN = {
    "illustrations": [{"title": "구조", "purpose": "structure", "description": "d", "category": "physical_setup",
                       "importance": 80, "difficulty": 40}],
    "diagrams": [{"title": "역할", "block": "method", "diagram_type": "sequence", "description": "d",
                  "category": "timeline", "importance": 70}],
    "interactive_html": {"title": "관계", "description": "y = 2x", "applicable": True},
    "diagram_count": 3,
}


class _WorkerDied(BaseException):
    """Not an Exception, so per-item error handling cannot swallow it."""


def _text(text, tokens_in=100, tokens_out=50):
    return {"text": text, "model": "gpt-6-luna", "tokens_in": tokens_in, "tokens_out": tokens_out,
            "tokens_cached": 0, "tokens_cache_write": 0}


class PipelineCase(IsolatedDbCase):
    """Real pipeline with paid calls replaced; no tests of its own."""

    render_usage = None
    tokens = {"mermaid": (100, 50), "html": (100, 50), "describe": (100, 50)}

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.calls = {"plan": 0, "mermaid": 0, "html": 0, "describe": 0, "render": 0}
        self.html_fails = True
        self.mermaid_fails = False
        self.mermaid_text = "sequenceDiagram\nA->>B: 신호"
        self.html_hold = None  # an asyncio.Event the next HTML call waits for

        async def chain(**_kwargs):
            self.calls["plan"] += 1
            return _text(json.dumps(PLAN, ensure_ascii=False))

        async def call(prompt, **_kwargs):
            if "Mermaid" in prompt:
                self.calls["mermaid"] += 1
                if self.mermaid_fails:
                    raise RuntimeError("temporary upstream error")
                return _text(self.mermaid_text, *self.tokens["mermaid"])
            self.calls["html"] += 1
            hold, self.html_hold = self.html_hold, None
            if hold is not None:
                await hold.wait()
            if self.html_fails:
                raise RuntimeError("temporary upstream error")
            return _text('<input type="range"><script>/* y=2x */</script>', *self.tokens["html"])

        async def describe(*_args, **_kwargs):
            self.calls["describe"] += 1
            return _text("A clean diagram", *self.tokens["describe"])

        def render(provider, _description):
            self.calls["render"] += 1
            provider.usage = self.render_usage
            return PNG

        for target, value in (
            ("services.analysis_execution._run_synthesis", AsyncMock()),
            ("services.analysis_execution._run_chain_stage", chain),
            ("services.analysis_execution.call_interaction", call),
            ("services.llm.interactions_client.call_interaction", describe),
            ("services.viz.figure_gen.OpenAIImageProvider.generate", render),
            ("services.analysis_execution.asyncio.sleep", AsyncMock()),
        ):
            patcher = patch(target, new=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        no_key = patch.dict(os.environ, {"OPENAI_API_KEY": ""})
        no_key.start()
        self.addCleanup(no_key.stop)

    async def run_pipeline(self):
        return await ae._run_visualizations(
            7, "source", "folder", ["previous"], "recipe", "deep", AnalysisStatus(paper_id=7), provider="openai",
        )

    async def viz_rows(self):
        return await database.fetch_all(
            "SELECT id, result FROM analysis_results WHERE phase = 'visualization' ORDER BY id")

    def cache_hash(self):
        cache_input = ae._visualization_cache_input(
            visualization_input="source", previous_results=["previous"], recipe_result="recipe",
            deep_dive_result="deep", image_provider="openai", image_quality="high", analysis_provider="openai",
        )
        return ae.compute_input_hash(cache_input)


class PartialRetryTests(PipelineCase):
    async def test_failed_items_are_retried_and_successes_are_not_replayed(self):
        first = {it["id"]: it for it in await self.run_pipeline()}
        self.assertEqual([first[i]["status"] for i in (1, 2, 3)], ["error", "completed", "error"])
        self.assertIn("no image provider", first[1]["error_message"])
        self.assertEqual(self.calls, {"plan": 1, "mermaid": 1, "html": 1, "describe": 1, "render": 0})

        # A key is added and the upstream recovers; the same inputs are analyzed again.
        os.environ["OPENAI_API_KEY"] = "sk-dummy"
        self.html_fails = False
        second = {it["id"]: it for it in await self.run_pipeline()}

        self.assertEqual([second[i]["status"] for i in (1, 2, 3)], ["completed"] * 3)
        self.assertEqual(second[2]["mermaid_code"], first[2]["mermaid_code"])
        self.assertEqual(self.calls, {"plan": 1, "mermaid": 1, "html": 2, "describe": 2, "render": 1})
        rows = await self.viz_rows()
        self.assertEqual(len(rows), 1, "the retry updates the same run")
        stored = json.loads(rows[0]["result"])
        self.assertTrue(stored["complete"])
        self.assertEqual([it["status"] for it in stored["items"]], ["completed"] * 3)

        # A third analysis is a pure cache hit.
        await self.run_pipeline()
        self.assertEqual(self.calls, {"plan": 1, "mermaid": 1, "html": 2, "describe": 2, "render": 1})

    async def test_missing_image_file_is_regenerated(self):
        os.environ["OPENAI_API_KEY"] = "sk-dummy"
        self.html_fails = False
        first = {it["id"]: it for it in await self.run_pipeline()}
        Path(first[1]["image_path"]).unlink()

        second = {it["id"]: it for it in await self.run_pipeline()}

        self.assertTrue(Path(second[1]["image_path"]).exists())
        self.assertEqual(self.calls["render"], 2)
        self.assertEqual((self.calls["mermaid"], self.calls["html"]), (1, 1))

    async def test_interrupted_checkpoint_resumes_only_unfinished_items(self):
        os.environ["OPENAI_API_KEY"] = "sk-dummy"
        self.html_fails = False
        original = figure_gen.generate_illustration

        async def crash(*_args, **_kwargs):
            raise _WorkerDied  # the worker dies after the Mermaid checkpoint

        with patch("services.viz.figure_gen.generate_illustration", new=crash):
            with self.assertRaises(_WorkerDied):
                await self.run_pipeline()
        checkpoint = json.loads((await self.viz_rows())[0]["result"])
        self.assertFalse(checkpoint["complete"])
        self.assertEqual([it["id"] for it in checkpoint["items"]], [2])

        with patch("services.viz.figure_gen.generate_illustration", new=original):
            items = await self.run_pipeline()

        self.assertEqual([it["status"] for it in items], ["completed"] * 3)
        self.assertEqual(self.calls["mermaid"], 1)
        self.assertEqual(self.calls["plan"], 1)

    async def test_saved_empty_run_without_a_plan_marker_is_planned_again(self):
        # v1.2.0 saved a failed plan as a completed run with no items.
        await self.conn.execute(
            "INSERT INTO analysis_results (paper_id, phase, result, model_used, input_hash) VALUES (7, 'visualization', ?, 'm', ?)",
            (json.dumps({"items": [], "complete": True}), self.cache_hash()),
        )
        await self.conn.commit()
        os.environ["OPENAI_API_KEY"] = "sk-dummy"
        self.html_fails = False

        items = await self.run_pipeline()

        self.assertEqual(len(items), 3)
        self.assertEqual(self.calls["plan"], 1)


class ConcurrentEditTests(PipelineCase):
    """The worker and the routes edit the same row when a reanalysis reuses it."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        os.environ["OPENAI_API_KEY"] = "sk-dummy"
        await self.run_pipeline()  # html fails: the next analysis reuses this row
        self.row_id = (await self.viz_rows())[0]["id"]
        self.html_fails = False

    async def wait_for_html_calls(self, count, task):
        import asyncio
        for _ in range(500):
            if self.calls["html"] >= count:
                return
            if task.done():
                task.result()  # surface the error
                self.fail("task finished before reaching its HTML call")
            await asyncio.wait({task}, timeout=0.01)  # asyncio.sleep is patched in this case
        self.fail(f"HTML call {count} never started: {self.calls}")

    async def stored(self):
        row = await database.fetch_one("SELECT cost_usd, result FROM analysis_results WHERE id = ?", (self.row_id,))
        return row["cost_usd"], json.loads(row["result"])

    async def test_regeneration_during_a_reanalysis_of_the_same_row_is_kept(self):
        import asyncio
        from api import analysis_routes
        hold = self.html_hold = asyncio.Event()
        worker = asyncio.create_task(self.run_pipeline())
        await self.wait_for_html_calls(2, worker)  # the worker is waiting inside its HTML call
        token = (await self.stored())[1]["run_token"]
        self.mermaid_text = "sequenceDiagram\nA->>B: 사용자가 다시 만듦"
        await analysis_routes.regenerate_visualization(7, 2, run_id=self.row_id, run_token=token)
        regenerated = {it["id"]: it for it in (await self.stored())[1]["items"]}[2]["requests"]
        hold.set()
        await worker

        _, payload = await self.stored()
        items = {it["id"]: it for it in payload["items"]}
        self.assertEqual(items[2]["mermaid_code"], "sequenceDiagram\nA->>B: 사용자가 다시 만듦")
        self.assertEqual(items[3]["status"], "completed")
        prior_ids = {r.get("id") for r in payload["prior_requests"]}
        self.assertEqual([r["id"] for r in regenerated], [r["id"] for r in items[2]["requests"]])
        self.assertEqual(len(prior_ids), len(payload["prior_requests"]), "no record twice")
        self.assertEqual(payload["cost_unknown_count"], 2)  # the unpriced render and the first failed html

    async def test_regeneration_from_the_replaced_run_is_refused_after_reanalysis(self):
        import asyncio
        from api import analysis_routes
        from fastapi import HTTPException
        old_token = (await self.stored())[1]["run_token"]
        hold = self.html_hold = asyncio.Event()
        route = asyncio.create_task(analysis_routes.regenerate_visualization(7, 3, run_id=self.row_id, run_token=old_token))
        await self.wait_for_html_calls(2, route)  # the route waits inside its HTML call
        await self.run_pipeline()  # same inputs, same row id, new run_token
        _, after_reanalysis = await self.stored()
        hold.set()
        with self.assertRaises(HTTPException) as ctx:
            await route
        self.assertEqual(ctx.exception.status_code, 409)
        cost, payload = await self.stored()
        self.assertEqual(payload["items"], after_reanalysis["items"])
        self.assertEqual(len(payload["prior_requests"]), len(after_reanalysis["prior_requests"]) + 1)

    async def test_crash_after_the_first_checkpoint_keeps_reused_items(self):
        await self.run_pipeline()  # complete run: image, mermaid, html all succeeded
        self.mermaid_fails = True
        await database.execute_update(
            "UPDATE analysis_results SET result = json_set(result, '$.items[1].status', 'error') WHERE id = ?",
            (self.row_id,),
        )
        cost_before, _ = await self.stored()
        real_store = ae._store_visualization_progress

        async def die_after_one_checkpoint(*args, **kwargs):
            await real_store(*args, **kwargs)
            raise _WorkerDied

        with patch("services.analysis_execution._store_visualization_progress", new=die_after_one_checkpoint):
            with self.assertRaises(_WorkerDied):
                await self.run_pipeline()

        cost, payload = await self.stored()
        self.assertEqual({it["id"] for it in payload["items"]}, {1, 2, 3})
        self.assertEqual({it["id"]: it["status"] for it in payload["items"]}, {1: "completed", 2: "error", 3: "completed"})
        self.assertGreaterEqual(cost, cost_before)


class ReusableItemTests(IsolatedDbCase):
    def test_image_is_found_in_the_paper_folder_after_a_library_move(self):
        folder = database.get_paper_dir("folder") / "paperbanana"
        folder.mkdir(parents=True)
        (folder / "1_structure.png").write_bytes(PNG)
        moved = {"id": 1, "tool": "paperbanana", "status": "completed", "image_path": "/old/library/folder/paperbanana/1_structure.png"}
        self.assertTrue(ae._viz_item_reusable(moved, "folder"))
        self.assertFalse(ae._viz_item_reusable({**moved, "image_path": "/x/2_gone.png"}, "folder"))
        self.assertFalse(ae._viz_item_reusable({**moved, "status": "error"}, "folder"))
        html = {"id": 3, "tool": "html", "status": "completed", "html_code": "<input>"}
        self.assertFalse(ae._viz_item_reusable({**html, "execution_check": {"status": "failed"}}, "folder"))
        self.assertTrue(ae._viz_item_reusable({**html, "execution_check": {"status": "timeout"}}, "folder"))
        self.assertFalse(ae._viz_item_reusable({"id": 2, "tool": "mermaid", "status": "completed", "mermaid_code": ""}, "folder"))
