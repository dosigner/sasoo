"""
figure_gen 테스트.

지키는 것: (1) 폴백 순서, (2) 타임아웃이 실제로 발화하고 그동안 이벤트 루프가
살아있음 — PaperBanana가 루프를 블로킹해 서버 전체가 죽던 2026-07-11 사고의 회귀 방지,
(3) 프로바이더 전무 시 에러 결과, (4) 파일명 안전성.
"""

import asyncio
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

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

    async def _fake_plan(self, viz_target):
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

    async def test_fallback_when_first_provider_fails(self):
        bad = _FakeProvider("openai", ok=False)
        good = _FakeProvider("gemini")
        with patch.object(figure_gen, "build_providers", return_value=[bad, good]):
            r = await generate_illustration(_target(), self.paper_dir)
        self.assertEqual(r.provider, "gemini")
        self.assertEqual(bad.calls, 1)

    async def test_unavailable_provider_is_skipped_without_calling(self):
        nokey = _FakeProvider("openai", unavailable=True)
        good = _FakeProvider("gemini")
        with patch.object(figure_gen, "build_providers", return_value=[nokey, good]):
            r = await generate_illustration(_target(), self.paper_dir)
        self.assertEqual(r.provider, "gemini")
        self.assertEqual(nokey.calls, 0)

    async def test_all_providers_fail_returns_error_result(self):
        with patch.object(
            figure_gen, "build_providers",
            return_value=[_FakeProvider("openai", ok=False), _FakeProvider("gemini", ok=False)],
        ):
            r = await generate_illustration(_target(), self.paper_dir)
        self.assertIsNone(r.path)
        self.assertIsNone(r.provider)
        self.assertIn("boom", r.error)

    async def test_timeout_fires_and_loop_stays_alive(self):
        """느린 렌더 중에도 루프가 굴러가고, 타임아웃이 실제로 잘라야 한다."""
        slow = _FakeProvider("openai", delay=3.0)
        good = _FakeProvider("gemini")
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            for _ in range(20):
                await asyncio.sleep(0.05)
                ticks += 1

        with (
            patch.object(figure_gen, "build_providers", return_value=[slow, good]),
            patch.object(figure_gen, "RENDER_TIMEOUT_S", 0.5),
        ):
            hb = asyncio.create_task(heartbeat())
            r = await generate_illustration(_target(), self.paper_dir)
            await hb

        self.assertEqual(r.provider, "gemini")   # 타임아웃 후 폴백
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


class ProviderOrderTests(unittest.TestCase):
    def test_preferred_first(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "x", "GEMINI_API_KEY": "y"}):
            names = [p.name for p in figure_gen.build_providers("gemini", "high")]
        self.assertEqual(names, ["gemini", "openai"])

    def test_default_openai_first(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "x", "GEMINI_API_KEY": "y"}):
            names = [p.name for p in figure_gen.build_providers("openai", "high")]
        self.assertEqual(names, ["openai", "gemini"])


if __name__ == "__main__":
    unittest.main()
