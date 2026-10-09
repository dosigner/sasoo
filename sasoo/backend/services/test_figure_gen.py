"""
figure_gen 테스트.

지키는 것: (1) 선택한 공급사, (2) 타임아웃이 실제로 발화하고 그동안 이벤트 루프가
살아있음 — PaperBanana가 루프를 블로킹해 서버 전체가 죽던 2026-07-11 사고의 회귀 방지,
(3) 프로바이더 전무 시 에러 결과, (4) 파일명 안전성.
"""

import asyncio
import base64
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, Mock, patch

from services.viz import figure_gen
from services.viz.figure_gen import FigureGenResult, generate_illustration

PNG_1PX = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _FakeProvider:
    def __init__(self, name, *, ok=True, delay=0.0, unavailable=False):
        self.name = name
        self._ok = ok
        self._delay = delay
        self._unavailable = unavailable
        self.calls = 0
        self.cost_key = "gpt-image-2:high"

    def available(self):
        return not self._unavailable

    def generate(self, description):
        self.calls += 1
        if self._delay:
            time.sleep(self._delay)
        if not self._ok:
            raise RuntimeError(f"{self.name} boom")
        return PNG_1PX


def _target(title="개념도 테스트"):
    return {"title": title, "description": "레이저가 거울에 반사되는 개념도"}


class FigureGenTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.paper_dir = self._tmp.name
        # Planner는 전 테스트에서 스텁: 실제 Gemini 호출 금지
        self._plan = patch.object(
            figure_gen, "_plan_description",
            new=self._fake_plan,
        )
        self._plan.start()

    async def _fake_plan(self, viz_target, **kwargs):
        return "A minimal schematic: laser, mirror, labeled arrows."

    def tearDown(self):
        self._plan.stop()
        self._tmp.cleanup()

    async def test_success_saves_png_and_reports_provider(self):
        p = _FakeProvider("openai")
        with patch.object(figure_gen, "build_providers", return_value=[p]):
            r = await generate_illustration(_target(), self.paper_dir)
        self.assertIsNone(r.error)
        self.assertEqual(r.provider, "openai")
        self.assertTrue(Path(r.path).exists())
        self.assertTrue(Path(r.path).name.endswith(".png"))
        self.assertIn("paperbanana", Path(r.path).parts)

    async def test_selected_gemini_failure_does_not_call_openai(self):
        with (
            patch.dict("os.environ", {"GEMINI_API_KEY": "test", "OPENAI_API_KEY": "test"}),
            patch.object(figure_gen.GeminiImageProvider, "generate", side_effect=RuntimeError("gemini failed")),
            patch.object(figure_gen.OpenAIImageProvider, "generate") as openai_generate,
        ):
            result = await generate_illustration(_target(), self.paper_dir, preferred_provider="gemini")
        self.assertIsNone(result.path)
        self.assertIn("gemini failed", result.error)
        openai_generate.assert_not_called()

    async def test_unavailable_provider_is_skipped_without_calling(self):
        nokey = _FakeProvider("openai", unavailable=True)
        with patch.object(figure_gen, "build_providers", return_value=[nokey]):
            r = await generate_illustration(_target(), self.paper_dir)
        self.assertIsNone(r.provider)
        self.assertIn("no image provider configured", r.error)
        self.assertEqual(nokey.calls, 0)

    async def test_selected_provider_failure_returns_error_result(self):
        with patch.object(
            figure_gen, "build_providers",
            return_value=[_FakeProvider("openai", ok=False)],
        ):
            r = await generate_illustration(_target(), self.paper_dir)
        self.assertIsNone(r.path)
        self.assertIsNone(r.provider)
        self.assertIn("boom", r.error)

    async def test_timeout_fires_and_loop_stays_alive(self):
        """느린 렌더 중에도 루프가 굴러가고, 타임아웃이 실제로 잘라야 한다."""
        slow = _FakeProvider("openai", delay=3.0)
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            for _ in range(20):
                await asyncio.sleep(0.05)
                ticks += 1

        with (
            patch.object(figure_gen, "build_providers", return_value=[slow]),
            patch.object(figure_gen, "RENDER_TIMEOUT_S", 0.5),
        ):
            hb = asyncio.create_task(heartbeat())
            r = await generate_illustration(_target(), self.paper_dir)
            await hb

        self.assertIsNone(r.provider)
        self.assertIn("timeout", r.error)
        self.assertGreater(ticks, 5, "렌더 중 이벤트 루프가 멈춰 있었다")

    async def test_filename_is_sanitized(self):
        p = _FakeProvider("openai")
        with patch.object(figure_gen, "build_providers", return_value=[p]):
            r = await generate_illustration(
                _target(title='광학 테이블 <셋업>: "실험"/구성?'), self.paper_dir
            )
        name = Path(r.path).name
        for ch in '<>:"/\\?*':
            self.assertNotIn(ch, name)

    async def test_distinct_ids_do_not_overwrite_images_with_the_same_title(self):
        with patch.object(figure_gen, "build_providers", return_value=[_FakeProvider("openai")]):
            first = await generate_illustration({**_target(), "id": 1}, self.paper_dir)
            second = await generate_illustration({**_target(), "id": 2}, self.paper_dir)
        self.assertNotEqual(first.path, second.path)
        self.assertTrue(Path(first.path).exists())
        self.assertTrue(Path(second.path).exists())

    async def test_model_switch_keeps_both_assets_and_changes_the_url(self):
        target = {**_target(), "id": 1}
        with patch.object(figure_gen, "build_providers", return_value=[_FakeProvider("openai")]):
            flare = await generate_illustration(target, self.paper_dir, image_model="gpt-image-2.5-flare")
            sunburst = await generate_illustration(target, self.paper_dir, image_model="gpt-image-2.5-sunburst")
        self.assertNotEqual(flare.path, sunburst.path)
        self.assertTrue(Path(flare.path).exists())
        self.assertTrue(Path(sunburst.path).exists())

    async def test_model_prefix_leaves_room_for_long_korean_titles(self):
        with patch.object(figure_gen, "build_providers", return_value=[_FakeProvider("openai")]):
            result = await generate_illustration({**_target("긴제목" * 100), "id": 1}, self.paper_dir,
                                                image_model="gpt-image-2.5-sunburst")
        self.assertTrue(Path(result.path).exists())
        self.assertLessEqual(len(Path(result.path).name.encode("utf-8")), 255)


class ProviderOrderTests(unittest.TestCase):
    def test_gemini_selection_stays_on_gemini(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "x", "GEMINI_API_KEY": "y"}):
            names = [p.name for p in figure_gen.build_providers("gemini", "high")]
        self.assertEqual(names, ["gemini"])

    def test_openai_selection_stays_on_openai(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "x", "GEMINI_API_KEY": "y"}):
            names = [p.name for p in figure_gen.build_providers("openai", "high")]
        self.assertEqual(names, ["openai"])


class FlareRenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_sunburst_request_and_cost_keep_the_selected_model(self):
        usage = {"input_tokens": 200, "input_tokens_details": {"text_tokens": 200, "image_tokens": 0}, "output_tokens": 1000}
        response = Mock()
        response.json.return_value = {"data": [{"b64_json": base64.b64encode(PNG_1PX).decode()}], "usage": usage}
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), patch.object(
            figure_gen, "_plan_description", new=AsyncMock(return_value="A scientific diagram")
        ), patch("httpx.post", return_value=response) as post:
            result = await generate_illustration(_target(), directory, image_model="gpt-image-2.5-sunburst")
        request = post.call_args.kwargs["json"]
        self.assertEqual(request["model"], "gpt-image-2.5-sunburst")
        self.assertEqual(request["quality"], "high")
        self.assertEqual(request["size"], "1536x1024")
        self.assertAlmostEqual(result.cost_usd, 0.031)

    async def test_sunburst_failure_does_not_retry_flare(self):
        with TemporaryDirectory() as directory, patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), patch.object(
            figure_gen, "_plan_description", new=AsyncMock(return_value="A scientific diagram")
        ), patch("httpx.post", side_effect=RuntimeError("render failed")) as post:
            result = await generate_illustration(_target(), directory, image_model="gpt-image-2.5-sunburst")
        self.assertIsNone(result.path)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.kwargs["json"]["model"], "gpt-image-2.5-sunburst")

    async def test_planner_and_renderer_keep_readable_labels_and_usage(self):
        description = "Three panels labeled 'Wavefront measurement and reconstruction'."
        usage = {"input_tokens": 200, "input_tokens_details": {"text_tokens": 200, "image_tokens": 0},
                 "output_tokens": 1000}
        response = Mock()
        response.json.return_value = {"data": [{"b64_json": base64.b64encode(PNG_1PX).decode()}],
                                      "usage": usage}
        planner = AsyncMock(return_value={"text": description})
        provider = figure_gen.OpenAIImageProvider()
        with (
            TemporaryDirectory() as directory,
            patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}),
            patch("services.llm.interactions_client.call_interaction", planner),
            patch("httpx.post", return_value=response) as post,
            patch.object(figure_gen, "build_providers", return_value=[provider]),
        ):
            result = await generate_illustration(_target(), directory, llm_provider="openai")
            self.assertEqual(Path(result.path).read_bytes(), PNG_1PX)
        request = post.call_args.kwargs["json"]
        self.assertEqual(request["model"], "gpt-image-2.5-flare")
        self.assertEqual(request["size"], "1536x1024")
        self.assertEqual(request["quality"], "high")
        self.assertEqual(request["output_format"], "png")
        for prompt in (request["prompt"], planner.call_args.kwargs["system_instruction"]):
            self.assertIn("normal-width sans-serif", prompt)
            self.assertIn("Wrap long labels at word boundaries", prompt)
            self.assertIn("Never squeeze or shrink text to fit", prompt)
        self.assertTrue(request["prompt"].endswith(figure_gen._TYPOGRAPHY_INSTRUCTION))
        self.assertIn(description, request["prompt"])
        self.assertAlmostEqual(result.cost_usd, 0.031)
        self.assertIsNone(result.error)

    async def test_missing_usage_keeps_image_without_inventing_cost(self):
        provider = _FakeProvider("openai")
        provider.cost_key = "gpt-image-2.5-flare:high"
        with (
            TemporaryDirectory() as directory,
            patch.object(figure_gen, "_plan_description", AsyncMock(return_value="A laser.")),
            patch.object(figure_gen, "build_providers", return_value=[provider]),
        ):
            result = await generate_illustration(_target(), directory)
            self.assertEqual(Path(result.path).read_bytes(), PNG_1PX)
        self.assertIsNone(result.error)
        self.assertIsNone(result.cost_usd)


class NanoBananaRenderTests(unittest.IsolatedAsyncioTestCase):
    def test_gemini_21_uses_low_cost_image_request_and_decodes_png(self):
        usage = {
            "total_input_tokens": 100,
            "total_output_tokens": 1120,
            "total_thought_tokens": 0,
            "output_tokens_by_modality": [{"modality": "image", "tokens": 1120}],
        }
        interaction = Mock(status="completed")
        interaction.output_image.data = base64.b64encode(PNG_1PX).decode()
        interaction.usage.model_dump.return_value = usage
        client = Mock()
        client.interactions.create.return_value = interaction
        with (
            patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}),
            patch("google.genai.Client", return_value=client),
        ):
            provider = figure_gen.GeminiImageProvider()
            self.assertEqual(provider.generate("A labeled diagram."), PNG_1PX)
        request = client.interactions.create.call_args.kwargs
        self.assertEqual(request["model"], "gemini-nano-banana-2.1")
        self.assertEqual(request["response_format"], {
            "type": "image", "mime_type": "image/png", "aspect_ratio": "3:2", "image_size": "1K",
        })
        self.assertEqual(request["generation_config"], {"thinking_level": "minimal"})
        self.assertIs(request["store"], False)
        self.assertNotIn("tools", request)
        self.assertIn("At 1K 3:2 resolution", request["input"])
        self.assertEqual(provider.usage, usage)

    async def test_gemini_21_result_records_reported_cost(self):
        interaction = Mock(status="completed")
        interaction.output_image.data = base64.b64encode(PNG_1PX).decode()
        interaction.usage.model_dump.return_value = {
            "total_input_tokens": 100,
            "total_output_tokens": 1120,
            "total_thought_tokens": 0,
            "output_tokens_by_modality": [{"modality": "image", "tokens": 1120}],
        }
        client = Mock()
        client.interactions.create.return_value = interaction
        with (
            TemporaryDirectory() as directory,
            patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}),
            patch("google.genai.Client", return_value=client),
            patch.object(figure_gen, "_plan_description", AsyncMock(return_value="A laser diagram.")),
        ):
            result = await generate_illustration(_target(), directory, preferred_provider="gemini")
            self.assertEqual(Path(result.path).read_bytes(), PNG_1PX)
        self.assertEqual(result.provider, "gemini")
        self.assertEqual(result.cost_usd, 0.03375)
        self.assertIsNone(result.error)


if __name__ == "__main__":
    unittest.main()
