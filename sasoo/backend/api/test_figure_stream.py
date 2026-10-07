import asyncio
import json
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from api import figure_service
from models.schemas import FigureExplanationResponse


def event(raw):
    return json.loads(raw.removeprefix("data: ").strip())


class FigureStreamTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = Path(self.stack.enter_context(TemporaryDirectory()))
        image = directory / "figure.png"
        image.write_bytes(b"figure-image")
        self.figures = {i: {"id": i, "paper_id": 7, "figure_num": f"Figure {i}",
                            "caption": f"Caption {i}", "file_path": str(image)} for i in (1, 2)}
        paper = {"id": 7, "folder_name": "paper", "title": "Paper", "agent_used": "neural"}

        async def fetch(sql, params):
            return dict(paper) if "FROM papers" in sql else dict(self.figures[params[0]])

        async def save(sql, params):
            self.figures[params[1]]["detailed_explanation"] = params[0]

        self.update = AsyncMock(side_effect=save)
        self.stack.enter_context(patch.multiple(
            figure_service,
            fetch_one=AsyncMock(side_effect=fetch),
            fetch_all=AsyncMock(return_value=list(self.figures.values())),
            get_paper_dir=lambda _: directory,
            ensure_text_artifacts_async=AsyncMock(),
            load_or_build_document_context=lambda _: {"phase_inputs": {"figure_detail": "Methods: 10 ms"}},
            get_latest_completed_phase_rows=AsyncMock(return_value={}),
            active_provider=AsyncMock(return_value="openai"),
            execute_update=self.update,
        ))

    async def test_stream_replays_and_shares_generation_with_rest_after_reader_leaves(self):
        release = asyncio.Event()
        calls = []

        async def stream(parts, **kwargs):
            calls.append(kwargs)
            yield {"type": "token", "text": "## 그림 개요\n"}
            await release.wait()
            yield {"type": "token", "text": "측정 시간 10 ms"}
            yield {"type": "done", "response_status": "completed", "tokens_in": 100,
                   "tokens_out": 50, "tokens_cached": 20, "tokens_cache_write": 0}

        with patch.object(figure_service, "stream_interaction", new=stream):
            first = figure_service.stream_figure_explanation(7, 1)
            self.assertEqual(event(await anext(first))["type"], "token")
            second = figure_service.stream_figure_explanation(7, 1)
            self.assertEqual(event(await anext(second))["content"], "## 그림 개요\n")
            await first.aclose()
            rest = asyncio.create_task(figure_service.explain_figure_handler(7, 1))
            await asyncio.sleep(0)
            release.set()
            events = [event(raw) async for raw in second]
            response = await rest
            cached = await figure_service.explain_figure_handler(7, 1)

        self.assertEqual(len(calls), 1)
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["result"]["explanation"], response.explanation)
        self.assertEqual(response.tokens_cached, 20)
        self.assertEqual(cached.model_used, "cached")
        self.update.assert_awaited_once()
        self.assertFalse(figure_service._figure_jobs)

    async def test_common_prefix_is_stable_and_image_is_after_cache_boundary(self):
        inputs = []

        async def stream(parts, **kwargs):
            inputs.append(parts)
            yield {"type": "token", "text": "상세 설명"}
            yield {"type": "done", "tokens_in": 100, "tokens_out": 50,
                   "tokens_cached": 0, "tokens_cache_write": 0, "response_status": "completed"}

        with patch.object(figure_service, "stream_interaction", new=stream):
            for i in (1, 2):
                await figure_service.explain_figure_handler(7, i)
        self.assertEqual(inputs[0][0], inputs[1][0])
        self.assertEqual(inputs[0][0]["prompt_cache_breakpoint"], {"mode": "explicit"})
        self.assertNotEqual(inputs[0][1], inputs[1][1])
        self.assertEqual(inputs[0][2]["type"], "image")
        self.assertIn("State each fact once", inputs[0][0]["text"])
        self.assertIn("Preserve all relevant numerical values", inputs[0][0]["text"])

    async def test_interrupted_stream_is_not_cached_and_can_be_retried(self):
        calls = []

        async def stream(parts, **kwargs):
            calls.append(kwargs)
            yield {"type": "token", "text": "부분 설명"}
            if len(calls) == 1:
                raise RuntimeError("connection lost")
            yield {"type": "done", "response_status": "completed", "tokens_in": 100,
                   "tokens_out": 50, "tokens_cached": 0, "tokens_cache_write": 0}

        with patch.object(figure_service, "stream_interaction", new=stream):
            failed = [event(raw) async for raw in figure_service.stream_figure_explanation(7, 1)]
            self.assertEqual(failed[-1]["type"], "error")
            self.update.assert_not_awaited()
            retried = [event(raw) async for raw in figure_service.stream_figure_explanation(7, 1)]
        self.assertEqual(retried[-1]["type"], "done")
        self.assertEqual(len(calls), 2)

    async def test_missing_completion_or_usage_never_emits_success(self):
        for terminal in (None, {"type": "done", "response_status": "completed"},
                         {"type": "done", "tokens_in": 100, "tokens_out": 50,
                          "tokens_cached": 0, "tokens_cache_write": 0, "response_status": "incomplete"}):
            async def stream(parts, **kwargs):
                yield {"type": "token", "text": "부분 설명"}
                if terminal:
                    yield terminal

            with patch.object(figure_service, "stream_interaction", new=stream):
                events = [event(raw) async for raw in figure_service.stream_figure_explanation(7, 1)]
            self.assertEqual(events[-1]["type"], "error")
        self.update.assert_not_awaited()

    async def test_gemini_has_no_openai_cache_fields_and_requires_completion_id(self):
        inputs = []

        async def stream(parts, **kwargs):
            inputs.append(parts)
            yield {"type": "token", "text": "상세 설명"}
            yield {"type": "done", "tokens_in": 100, "tokens_out": 50,
                   "interaction_id": "gemini-done" if len(inputs) == 2 else None}

        with patch.object(figure_service, "active_provider", new=AsyncMock(return_value="gemini")), patch.object(
            figure_service, "stream_interaction", new=stream
        ):
            failed = [event(raw) async for raw in figure_service.stream_figure_explanation(7, 1)]
            done = [event(raw) async for raw in figure_service.stream_figure_explanation(7, 1)]
        self.assertEqual(failed[-1]["type"], "error")
        self.assertEqual(done[-1]["type"], "done")
        self.assertNotIn("prompt_cache_breakpoint", inputs[-1][0])

    async def test_http_stream_route_uses_shared_generation(self):
        from api.analysis_routes import explain_figure_stream

        async def generate(paper_id, figure_id, publish):
            publish("설명")
            return FigureExplanationResponse(paper_id=paper_id, figure_id=figure_id,
                                             explanation="설명", model_used="cached")

        with patch.object(figure_service, "_generate_figure_explanation", new=generate):
            response = await explain_figure_stream(7, 1)
            events = [event(raw) async for raw in response.body_iterator]
        self.assertEqual(response.media_type, "text/event-stream")
        self.assertEqual([item["type"] for item in events], ["token", "done"])
