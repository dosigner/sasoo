"""New visualization plans are validated, and limits are enforced, before any paid call."""

import json
import unittest
from unittest.mock import AsyncMock, patch

from models.schemas import AnalysisStatus
from services import analysis_execution as ae


def _plan(**overrides):
    plan = {"illustrations": [], "diagrams": [], "interactive_html": {"title": "", "description": "", "applicable": False},
            "diagram_count": 0}
    plan.update(overrides)
    return plan


def _chain_result(text):
    return {"text": text, "model": "planner", "tokens_in": 10, "tokens_out": 5}


class PlanValidationTests(unittest.IsolatedAsyncioTestCase):
    async def _plan_with(self, text):
        insert = AsyncMock()
        with patch.object(ae, "_get_cached_phase_result", new=AsyncMock(return_value=None)), patch.object(
            ae, "_run_chain_stage", new=AsyncMock(return_value=_chain_result(text))
        ), patch.object(ae, "_insert_analysis_result", new=insert), patch.object(ae, "calc_result_cost", return_value=0.01):
            try:
                return await ae._plan_visualizations(7, "src", [], AnalysisStatus(paper_id=7), provider="openai"), insert
            except ValueError as exc:
                return exc, insert

    async def test_failure_envelopes_are_rejected(self):
        for text in (
            json.dumps({"_raw": "{\"illustrations\": [", "_parse_error": "응답이 완료되지 않았습니다"}),
            json.dumps({"error": "rate limited"}),
            "",
        ):
            with self.subTest(text=text[:30]):
                result, insert = await self._plan_with(text)
                self.assertIsInstance(result, ValueError)
                self.assertTrue(ae._is_error_result(insert.await_args.args[2]))

    async def test_missing_or_malformed_required_fields_are_rejected(self):
        legacy = {"diagrams": [{"title": f"m{i}", "diagram_type": "flowchart", "importance": 0} for i in range(5)],
                  "diagram_count": 5}
        cases = {
            "missing illustrations": legacy,
            "missing interactive_html": {k: v for k, v in _plan().items() if k != "interactive_html"},
            "missing diagram_count": {k: v for k, v in _plan().items() if k != "diagram_count"},
            "illustrations not a list": _plan(illustrations={"title": "x"}),
            "applicable not bool": _plan(interactive_html={"title": "t", "description": "d", "applicable": "true"}),
            "diagram_count bool": _plan(diagram_count=True),
            "diagram_count text": _plan(diagram_count="2"),
            "item not an object": _plan(diagrams=["sequenceDiagram"]),
        }
        for name, plan in cases.items():
            with self.subTest(name):
                result, insert = await self._plan_with(json.dumps(plan))
                self.assertIsInstance(result, ValueError)
                self.assertIn("_parse_error", json.loads(insert.await_args.args[2]))

    async def test_valid_empty_plan_is_kept_as_an_empty_success(self):
        result, insert = await self._plan_with(json.dumps(_plan()))
        self.assertEqual(result, [])
        self.assertEqual(json.loads(insert.await_args.args[2]), {"visualizations": []})

    async def test_diagram_count_from_the_model_is_not_trusted(self):
        plan = _plan(diagrams=[{"title": "roles", "block": "method", "diagram_type": "sequence", "description": "d",
                                "category": "timeline", "importance": 10}], diagram_count=9)
        result, _ = await self._plan_with(json.dumps(plan))
        self.assertEqual([it["title"] for it in result], ["roles"])

    async def test_unreadable_plan_cache_is_a_miss_not_an_empty_plan(self):
        chain = AsyncMock(return_value=_chain_result(json.dumps(_plan(
            interactive_html={"title": "관계", "description": "y=2x", "applicable": True}))))
        with patch.object(ae, "_get_cached_phase_result", new=AsyncMock(return_value={"text": "not json"})), patch.object(
            ae, "_run_chain_stage", new=chain
        ), patch.object(ae, "_insert_analysis_result", new=AsyncMock()), patch.object(ae, "calc_result_cost", return_value=0.0):
            result = await ae._plan_visualizations(7, "src", [], AnalysisStatus(paper_id=7), provider="openai")
        chain.assert_awaited_once()
        self.assertEqual([it["tool"] for it in result], ["html"])


class GenerationGateTests(unittest.IsolatedAsyncioTestCase):
    """The gate runs on whatever list reaches generation, including cached plans."""

    async def _run(self, plan_items=None, plan_error=None):
        calls = {"mermaid": 0, "paperbanana": [], "html": 0}

        async def mermaid(*_a, **_k):
            calls["mermaid"] += 1
            return "sequenceDiagram\nA->>B: x"

        async def image(_pid, item, *_a, **_k):
            calls["paperbanana"].append(item.get("image_model"))
            return {"image_path": "/tmp/x.png", "image_url": "/x.png", "cost_usd": 0.03}

        async def html(*_a, **_k):
            calls["html"] += 1
            return {"html_code": "<input><script></script>", "cost_usd": 0.01}

        plan = AsyncMock(side_effect=plan_error) if plan_error else AsyncMock(return_value=plan_items)
        store = AsyncMock()
        with patch.object(ae, "_run_synthesis", new=AsyncMock()), patch.object(
            ae, "_get_all_settings", new=AsyncMock(return_value={})
        ), patch.object(ae, "_get_cached_phase_result", new=AsyncMock(return_value=None)), patch.object(
            ae, "_plan_visualizations", new=plan
        ), patch.object(ae, "_generate_single_mermaid", new=mermaid), patch.object(
            ae, "_generate_single_paperbanana", new=image
        ), patch.object(ae, "_generate_single_html", new=html), patch.object(
            ae, "_store_visualization_progress", new=store
        ), patch.object(ae.asyncio, "sleep", new=AsyncMock()):
            try:
                items = await ae._run_visualizations(7, "src", "folder", [], "", "", AnalysisStatus(paper_id=7))
            except ValueError:
                items = None
        return items, calls, store

    async def test_over_allocated_cached_plan_is_cut_before_generation(self):
        image = lambda purpose, **kw: {"title": purpose, "tool": "paperbanana", "diagram_type": purpose,
                                       "importance": kw.get("importance", 90), "difficulty": kw.get("difficulty", 90),
                                       "image_model": kw.get("model", ae.MODEL_IMAGE_SUNBURST)}
        items = [image("structure"), image("structure"), image("process"), image("comparison"),
                 image("additional"), image("additional"), image("additional"),
                 image("additional", importance=59, model=ae.MODEL_IMAGE_OPENAI),
                 {"title": "legacy concept", "tool": "paperbanana", "block": "concept"}]
        items += [{"title": f"m{i}", "tool": "mermaid", "diagram_type": "flowchart", "importance": 0} for i in range(5)]
        items += [{"title": "seq", "tool": "mermaid", "diagram_type": "sequence", "importance": None},
                  {"title": "seq2", "tool": "mermaid", "diagram_type": "sequence", "importance": 60.0},
                  {"title": "nan", "tool": "mermaid", "diagram_type": "flowchart", "importance": float("nan")}]
        items += [{"title": "h1", "tool": "html"}, {"title": "h2", "tool": "html"}, {"title": "svg", "tool": "svg"}]

        result, calls, _ = await self._run(items)

        self.assertEqual(len(calls["paperbanana"]), 5)
        self.assertEqual(calls["paperbanana"].count(ae.MODEL_IMAGE_SUNBURST), 1)
        self.assertEqual(calls["mermaid"], 2)  # primary sequence + one valid extra
        self.assertEqual(calls["html"], 1)
        self.assertEqual(len(result), 8)
        self.assertEqual([it["id"] for it in result], list(range(1, 9)))

    async def test_sunburst_only_for_an_eligible_core_image(self):
        items = [{"title": "s", "tool": "paperbanana", "diagram_type": "structure", "importance": 59, "difficulty": 99,
                  "image_model": ae.MODEL_IMAGE_SUNBURST},
                 {"title": "p", "tool": "paperbanana", "diagram_type": "process", "importance": 60, "difficulty": 69,
                  "image_model": ae.MODEL_IMAGE_SUNBURST},
                 {"title": "a", "tool": "paperbanana", "diagram_type": "additional", "importance": 99, "difficulty": 99,
                  "image_model": ae.MODEL_IMAGE_SUNBURST},
                 {"title": "c", "tool": "paperbanana", "diagram_type": "comparison", "importance": 60, "difficulty": 70,
                  "image_model": ae.MODEL_IMAGE_SUNBURST}]
        _, calls, _ = await self._run(items)
        self.assertEqual(calls["paperbanana"], [ae.MODEL_IMAGE_OPENAI] * 3 + [ae.MODEL_IMAGE_SUNBURST])

    async def test_planning_failure_makes_no_generation_call_and_no_complete_row(self):
        result, calls, store = await self._run(plan_error=ValueError("Visualization planning returned an invalid plan"))
        self.assertIsNone(result)
        self.assertEqual((calls["mermaid"], calls["paperbanana"], calls["html"]), (0, [], 0))
        store.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
