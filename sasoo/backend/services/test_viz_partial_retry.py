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

        async def chain(**_kwargs):
            self.calls["plan"] += 1
            return _text(json.dumps(PLAN, ensure_ascii=False))

        async def call(prompt, **_kwargs):
            if "Mermaid" in prompt:
                self.calls["mermaid"] += 1
                return _text("sequenceDiagram\nA->>B: 신호", *self.tokens["mermaid"])
            self.calls["html"] += 1
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


class ReusableItemTests(IsolatedDbCase):
    def test_image_is_found_in_the_paper_folder_after_a_library_move(self):
        folder = database.get_paper_dir("folder") / "paperbanana"
        folder.mkdir(parents=True)
        (folder / "1_structure.png").write_bytes(PNG)
        moved = {"id": 1, "tool": "paperbanana", "status": "completed", "image_path": "/old/library/folder/paperbanana/1_structure.png"}
        self.assertTrue(ae._viz_item_reusable(moved, "folder"))
        self.assertFalse(ae._viz_item_reusable({**moved, "image_path": "/x/2_gone.png"}, "folder"))
        self.assertFalse(ae._viz_item_reusable({**moved, "status": "error"}, "folder"))
        self.assertFalse(ae._viz_item_reusable({"id": 2, "tool": "mermaid", "status": "completed", "mermaid_code": ""}, "folder"))
