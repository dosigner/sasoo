"""visual 단계 Gemini 파서 usage → analysis_results 원장 배선 테스트 (오프라인).

검증 항목:
  1. 성공(gemini visual 파싱) 시 원장에 phase="visual_parse"로 1회 기록 + 값 검증.
  2. usage 부재(ODL 폴백/캐시 히트) 시 미기록.
  3. DB 오류(예: 파일럿·미초기화 환경) 시 조용히 스킵, 파이프라인 불변.
  4. thread-local 채널이 _run_convert를 건드리지 않고 gemini usage를 manifest로 끌어올림.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import fitz

import services.odl_parser as odl
from services.pricing import calc_cost

MODEL = "gemini-3.5-flash"


def _usage(pages: int = 3, tin: int = 1000, tout: int = 500, tthought: int = 120) -> dict:
    return {
        "engine": "gemini",
        "model": MODEL,
        "pages": pages,
        "tokens_in": tin,
        "tokens_out": tout,
        "tokens_thought": tthought,
        "cost_usd": 0.123,  # 채널이 준 값 — 기록 헬퍼는 무시하고 calc_cost로 재계산한다.
    }


class RefreshRecordsUsageTests(unittest.IsolatedAsyncioTestCase):
    async def _run_refresh(self, manifest: dict):
        insert_mock = AsyncMock()
        with patch(
            "services.odl_parser.ensure_visual_artifacts_async",
            new=AsyncMock(return_value=manifest),
        ), patch(
            "services.odl_parser.sync_figures_for_paper", new=AsyncMock()
        ) as fig_mock, patch(
            "services.odl_parser.sync_tables_for_paper", new=AsyncMock()
        ) as tbl_mock, patch(
            "services.odl_parser.execute_insert", new=insert_mock
        ):
            returned = await odl._refresh_paper_artifacts(42, Path("/tmp/paper"))
        return returned, insert_mock, fig_mock, tbl_mock

    async def test_success_records_once_with_values(self):
        manifest = {"engine": "gemini", "_visual_parse_usage": _usage()}
        returned, insert_mock, fig_mock, tbl_mock = await self._run_refresh(manifest)

        # 기록 1회
        insert_mock.assert_awaited_once()
        params = insert_mock.await_args.args[1]
        # (paper_id, phase, result, model, tokens_in, tokens_out, cost, input_hash)
        self.assertEqual(params[0], 42)
        self.assertEqual(params[1], "visual_parse")
        self.assertEqual(params[3], MODEL)
        self.assertEqual(params[4], 1000)
        self.assertEqual(params[5], 500)
        self.assertAlmostEqual(params[6], calc_cost(MODEL, 1000, 500))
        self.assertAlmostEqual(params[6], 0.006)  # 1000*1.5/1e6 + 500*9/1e6

        payload = json.loads(params[2])
        self.assertEqual(payload["engine"], "gemini")
        self.assertEqual(payload["pages"], 3)
        self.assertEqual(payload["tokens_thought"], 120)

        # 아티팩트 sync는 그대로 수행되고, transient 키는 걷혀 나간다.
        fig_mock.assert_awaited_once()
        tbl_mock.assert_awaited_once()
        self.assertNotIn("_visual_parse_usage", returned)

    async def test_no_usage_key_records_nothing(self):
        # ODL 폴백/캐시 히트 → manifest에 transient 키 없음.
        manifest = {"engine": "odl-java"}
        returned, insert_mock, fig_mock, tbl_mock = await self._run_refresh(manifest)
        insert_mock.assert_not_awaited()
        fig_mock.assert_awaited_once()
        tbl_mock.assert_awaited_once()

    async def test_zero_tokens_records_nothing(self):
        manifest = {"engine": "gemini", "_visual_parse_usage": _usage(tin=0, tout=0)}
        _, insert_mock, _, _ = await self._run_refresh(manifest)
        insert_mock.assert_not_awaited()

    async def test_db_error_is_swallowed(self):
        # DB 미초기화/오류 환경: 기록 실패해도 refresh는 정상 완료해야 한다.
        manifest = {"engine": "gemini", "_visual_parse_usage": _usage()}
        boom = AsyncMock(side_effect=RuntimeError("Database not initialized"))
        with patch(
            "services.odl_parser.ensure_visual_artifacts_async",
            new=AsyncMock(return_value=manifest),
        ), patch(
            "services.odl_parser.sync_figures_for_paper", new=AsyncMock()
        ), patch(
            "services.odl_parser.sync_tables_for_paper", new=AsyncMock()
        ), patch(
            "services.odl_parser.execute_insert", new=boom
        ):
            # 예외가 전파되지 않아야 한다.
            returned = await odl._refresh_paper_artifacts(7, Path("/tmp/paper"))
        boom.assert_awaited_once()
        self.assertNotIn("_visual_parse_usage", returned)


def _root(content: str) -> dict:
    return {
        "title": "T",
        "author": "A",
        "number of pages": 1,
        "kids": [
            {
                "type": "paragraph",
                "id": 1,
                "page number": 1,
                "bounding box": [10, 10, 120, 40],
                "content": content,
            }
        ],
    }


class ChannelCaptureTests(unittest.TestCase):
    """_run_convert(mock 경계)를 건드리지 않고 gemini usage가 manifest로 올라오는지."""

    def _make_paper(self, tmp_dir: str) -> Path:
        paper_dir = Path(tmp_dir)
        pdf_path = paper_dir / "paper.pdf"
        doc = fitz.open()
        page = doc.new_page(width=300, height=400)
        page.insert_text((72, 72), "seed", fontsize=12)
        doc.save(pdf_path)
        doc.close()
        return paper_dir

    def test_gemini_usage_bubbles_into_manifest_key(self):
        async def _fake_run_convert_gemini(pdf_path, output_dir, figures_dir, *, usage_out=None):
            # 실제 API 대신, 채널이 넘겨준 usage_out을 run_convert_gemini와 동일 계약으로 채운다.
            if usage_out is not None:
                usage_out.update(
                    {
                        "engine": "gemini",
                        "model": MODEL,
                        "pages": 1,
                        "tokens_in": 800,
                        "tokens_out": 300,
                        "tokens_thought": 40,
                        "cost_usd": calc_cost(MODEL, 800, 300),
                    }
                )
            return copy.deepcopy(_root("GEMINI VISUAL TEXT")), "GEMINI VISUAL TEXT", "gemini"

        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = self._make_paper(tmp_dir)
            env = {"GEMINI_API_KEY": "test-key", "SASOO_PDF_VISUAL_ENGINE": "gemini"}
            with patch.dict(os.environ, env), patch(
                "services.odl_parser.ensure_text_artifacts"
            ), patch(
                "services.gemini_parser.run_convert_gemini",
                new=_fake_run_convert_gemini,
            ):
                manifest = odl.ensure_visual_artifacts(
                    paper_dir, mode="java", extraction_pipeline_version="legacy", force=True
                )

        usage = manifest.get("_visual_parse_usage")
        self.assertIsNotNone(usage, "gemini usage가 manifest로 올라오지 않음")
        assert usage is not None
        self.assertEqual(usage["engine"], "gemini")
        self.assertEqual(usage["tokens_in"], 800)
        self.assertEqual(usage["tokens_out"], 300)
        # 채널은 호출 후 비워진다(스레드 재사용 시 stale 방지).
        self.assertIsNone(getattr(odl._visual_parse_usage_channel, "usage", None))

    def test_channel_stays_empty_when_engine_is_odl(self):
        # visual 엔진을 ODL로 강제하면 gemini 파서가 안 돌아 usage 키가 없어야 한다.
        def _all_odl(pdf_path, output_dir, figures_dir, mode, engine=None, stage="text"):
            return copy.deepcopy(_root("ODL TEXT")), "ODL TEXT", "odl-java"

        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = self._make_paper(tmp_dir)
            with patch("services.odl_parser._run_convert", side_effect=_all_odl), patch(
                "services.odl_parser.ensure_text_artifacts"
            ):
                manifest = odl.ensure_visual_artifacts(
                    paper_dir, mode="java", extraction_pipeline_version="legacy", force=True
                )
        self.assertNotIn("_visual_parse_usage", manifest)


if __name__ == "__main__":
    unittest.main()
