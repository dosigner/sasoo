"""Visualization spend: every paid request once, unknown usage kept as unknown.

Expected USD values are computed here from token counts and the published rates
(gpt-6-luna $0.10 in / $0.50 out per 1M; gpt-image-2.5 text in $5, image out $30
per 1M), not from the pricing helpers under test.
"""

import json
import os
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api import analysis_routes, settings
from models import database
from services.test_viz_partial_retry import PipelineCase

LUNA_IN, LUNA_OUT = 0.10 / 1e6, 0.50 / 1e6
MERMAID = 1000 * LUNA_IN + 200 * LUNA_OUT        # 0.0002
DESCRIBE = 2000 * LUNA_IN + 400 * LUNA_OUT       # 0.0004
HTML = 3000 * LUNA_IN + 1000 * LUNA_OUT          # 0.0008
RENDER = (500 * 5.0 + 4000 * 30.0) / 1e6         # 0.1225
RENDER_USAGE = {"input_tokens": 500, "output_tokens": 4000,
                "input_tokens_details": {"text_tokens": 500, "image_tokens": 0}}


class PipelineCostTests(PipelineCase):
    tokens = {"mermaid": (1000, 200), "html": (3000, 1000), "describe": (2000, 400)}
    render_usage = RENDER_USAGE

    async def asyncSetUp(self):
        await super().asyncSetUp()
        os.environ["OPENAI_API_KEY"] = "sk-dummy"
        self.html_fails = False

    async def row(self):
        row = (await database.fetch_all(
            "SELECT cost_usd, result FROM analysis_results WHERE phase = 'visualization'"))[0]
        return row["cost_usd"], json.loads(row["result"])

    async def test_each_request_is_counted_once_across_checkpoints_and_cache_hits(self):
        items = {it["id"]: it for it in await self.run_pipeline()}

        self.assertAlmostEqual(items[1]["cost_usd"], DESCRIBE + RENDER, places=10)
        self.assertAlmostEqual(items[2]["cost_usd"], MERMAID, places=10)
        self.assertAlmostEqual(items[3]["cost_usd"], HTML, places=10)
        self.assertEqual([r["kind"] for r in items[1]["requests"]], ["describe", "render"])
        self.assertEqual(items[1]["requests"][1]["model"], "gpt-image-2.5-flare")
        cost, payload = await self.row()
        self.assertAlmostEqual(cost, MERMAID + DESCRIBE + RENDER + HTML, places=10)
        self.assertEqual((payload["cost_unknown_count"], payload["cost_incomplete"]), (0, False))

        await self.run_pipeline()  # cache hit: no new spend
        self.assertAlmostEqual((await self.row())[0], MERMAID + DESCRIBE + RENDER + HTML, places=10)

    async def test_unknown_render_usage_keeps_the_known_total(self):
        self.render_usage = None
        items = {it["id"]: it for it in await self.run_pipeline()}

        self.assertIsNone(items[1]["cost_usd"])
        cost, payload = await self.row()
        self.assertAlmostEqual(cost, MERMAID + DESCRIBE + HTML, places=10)
        self.assertEqual((payload["cost_unknown_count"], payload["cost_incomplete"]), (1, True))

    async def test_known_zero_is_not_unknown(self):
        self.tokens = {**self.tokens, "mermaid": (0, 0)}
        items = {it["id"]: it for it in await self.run_pipeline()}
        self.assertEqual(items[2]["cost_usd"], 0.0)
        self.assertEqual((await self.row())[1]["cost_unknown_count"], 0)

    async def test_failed_attempts_stay_in_the_run_total_after_retry(self):
        self.html_fails = True
        os.environ["OPENAI_API_KEY"] = ""
        await self.run_pipeline()
        cost, payload = await self.row()
        self.assertAlmostEqual(cost, MERMAID + DESCRIBE, places=10)  # html failed with unknown spend
        self.assertEqual(payload["cost_unknown_count"], 1)

        self.html_fails = False
        os.environ["OPENAI_API_KEY"] = "sk-dummy"
        await self.run_pipeline()

        cost, payload = await self.row()
        self.assertAlmostEqual(cost, MERMAID + 2 * DESCRIBE + RENDER + HTML, places=10)
        self.assertEqual(payload["cost_unknown_count"], 1)
        self.assertEqual(sorted(r["kind"] for r in payload["prior_requests"]), ["describe", "html"])


class RegenerationCostTests(PipelineCase):
    tokens = {"mermaid": (1000, 200), "html": (3000, 1000), "describe": (2000, 400)}
    render_usage = RENDER_USAGE

    async def asyncSetUp(self):
        await super().asyncSetUp()
        os.environ["OPENAI_API_KEY"] = "sk-dummy"
        self.html_fails = False
        await self.run_pipeline()
        self.row_id = (await database.fetch_one("SELECT id FROM analysis_results WHERE phase = 'visualization'"))["id"]
        self.base = MERMAID + DESCRIBE + RENDER + HTML

    async def row(self, row_id=None):
        row = await database.fetch_one("SELECT cost_usd, result FROM analysis_results WHERE id = ?", (row_id or self.row_id,))
        return row["cost_usd"], json.loads(row["result"])

    async def test_regeneration_adds_its_cost_and_the_item_shows_the_latest(self):
        response = await analysis_routes.regenerate_visualization(7, 3, run_id=self.row_id)
        self.assertAlmostEqual(response.cost_usd, HTML, places=10)
        cost, payload = await self.row()
        self.assertAlmostEqual(cost, self.base + HTML, places=10)
        self.assertFalse(payload["cost_incomplete"])

        await analysis_routes.regenerate_visualization(7, 2, run_id=self.row_id)
        self.assertAlmostEqual((await self.row())[0], self.base + HTML + MERMAID, places=10)

    async def test_unknown_regeneration_cost_replaces_the_old_known_cost(self):
        self.render_usage = None
        response = await analysis_routes.regenerate_visualization(7, 1, run_id=self.row_id)
        self.assertIsNone(response.cost_usd)
        cost, payload = await self.row()
        stored = {it["id"]: it for it in payload["items"]}
        self.assertIsNone(stored[1]["cost_usd"])
        self.assertAlmostEqual(cost, self.base + DESCRIBE, places=10)
        self.assertEqual((payload["cost_unknown_count"], payload["cost_incomplete"]), (1, True))

    async def test_failed_regeneration_still_records_its_spend(self):
        with patch("services.analysis_execution.call_interaction",
                   new=AsyncMock(return_value={"text": "no controls", "model": "gpt-6-luna", "tokens_in": 3000,
                                               "tokens_out": 1000, "tokens_cached": 0, "tokens_cache_write": 0})):
            with self.assertRaises(HTTPException) as ctx:
                await analysis_routes.regenerate_visualization(7, 3, run_id=self.row_id)
        self.assertEqual(ctx.exception.status_code, 502)
        cost, payload = await self.row()
        self.assertAlmostEqual(cost, self.base + HTML, places=10)
        self.assertEqual({it["id"]: it for it in payload["items"]}[3]["status"], "completed")

    async def test_stale_regeneration_cost_goes_to_its_own_run(self):
        real = analysis_routes._generate_single_html
        newer = {}

        async def reanalysis_finishes_meanwhile(*args, **kwargs):
            out = await real(*args, **kwargs)
            cursor = await self.conn.execute(
                "INSERT INTO analysis_results (paper_id, phase, result, model_used, cost_usd, input_hash)"
                " VALUES (7, 'visualization', ?, 'm', 0.5, 'run-b')",
                (json.dumps({"items": [], "complete": True, "planned_empty": True, "cost_unknown_count": 0}),),
            )
            await self.conn.commit()
            newer["id"] = cursor.lastrowid
            return out

        with patch("api.analysis_routes._generate_single_html", new=reanalysis_finishes_meanwhile):
            with self.assertRaises(HTTPException) as ctx:
                await analysis_routes.regenerate_visualization(7, 3, run_id=self.row_id)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertAlmostEqual((await self.row())[0], self.base + HTML, places=10)
        self.assertEqual(await self.row(newer["id"]), (0.5, {"items": [], "complete": True, "planned_empty": True,
                                                            "cost_unknown_count": 0}))


class CostSummaryTests(PipelineCase):
    async def test_summary_keeps_known_totals_and_counts_unknown_requests(self):
        rows = [
            # New visualization row: known total in the column, request records in the payload.
            ("visualization", json.dumps({"items": [
                {"id": 1, "tool": "paperbanana", "status": "completed", "cost_usd": None, "requests": [
                    {"kind": "describe", "model": "gpt-6-luna", "cost_usd": 0.0004},
                    {"kind": "render", "model": "gpt-image-2.5-flare", "cost_usd": None}]},
                {"id": 2, "tool": "mermaid", "status": "completed", "cost_usd": 0.0002, "requests": [
                    {"kind": "mermaid", "model": "gpt-6-luna", "cost_usd": 0.0002}]},
            ], "prior_requests": [{"kind": "render", "model": "gpt-image-2.5-flare", "cost_usd": 0.1225}],
                "cost_unknown_count": 1}), "gpt-6-luna", 0.1231),
            ("viz_plan", json.dumps({"visualizations": []}), "gpt-6-luna", 0.01),
            # v1.2.0 rows: unknown visualization total and an unpriced phase.
            ("visualization", json.dumps({"items": [], "cost_incomplete": True}), "gpt-6-luna", None),
            ("deep_dive", json.dumps({"summary": "x"}), "gpt-6-luna", None),
        ]
        for phase, result, model, cost in rows:
            await self.conn.execute(
                "INSERT INTO analysis_results (paper_id, phase, result, model_used, cost_usd) VALUES (7, ?, ?, ?, ?)",
                (phase, result, model, cost),
            )
        await self.conn.commit()

        summary = await settings.get_cost_summary(month=None)

        self.assertEqual(summary["totals"]["total_cost_usd"], round(0.1231 + 0.01, 4))
        self.assertEqual(summary["totals"]["unknown_cost_count"], 3)
        self.assertEqual(summary["current_month"]["unknown_cost_count"], 3)
        self.assertEqual(summary["monthly_costs"][-1]["unknown_cost_count"], 3)
        paper = summary["per_paper_costs"][0]
        self.assertEqual((paper["total_usd"], paper["unknown_cost_count"]), (round(0.1331, 4), 3))
        models = {m["model"]: m for m in summary["by_model"]}
        self.assertEqual(models["gpt-image-2.5-flare"]["cost_usd"], 0.1225)
        self.assertEqual(models["gpt-image-2.5-flare"]["unknown_cost_count"], 1)
        self.assertEqual(models["gpt-image-2.5-flare"]["calls"], 2)
        self.assertEqual(models["gpt-6-luna"]["cost_usd"], round(0.0004 + 0.0002 + 0.01, 4))
        self.assertEqual(models["gpt-6-luna"]["unknown_cost_count"], 2)
