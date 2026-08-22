from __future__ import annotations

import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

from services import figure_resolver
from services.models import MODEL_FLASH_HQ


def _make_png(path: Path, size: tuple[int, int] = (40, 20)) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, color="white")
    image.save(path, "PNG")
    return path.read_bytes()


class MaybeSelectCandidateCallInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_call_interaction_with_image_dict_and_model_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            raster_rel = "pages/page_1.png"
            image_bytes = _make_png(paper_dir / raster_rel)

            # 두 후보 모두 캡션이 연결되고 수용 게이트를 통과하는 크기여야 한다 —
            # 캡션 없는 후보는 계약 7상 어차피 버려지므로 선택 계약을 검증할 수 없다.
            group = [
                {"id": "cand:1", "bbox": [40.0, 40.0, 260.0, 300.0], "source_kind": "pymupdf_image",
                 "best_caption_id": "cap:1", "linked_caption_ids": ["cap:1"]},
                {"id": "cand:2", "bbox": [60.0, 10.0, 240.0, 220.0], "source_kind": "pymupdf_image",
                 "best_caption_id": "cap:1", "linked_caption_ids": ["cap:1"]},
            ]
            captions = {"cap:1": {"id": "cap:1", "text": "Figure 1. Example.",
                                  "bbox": [10.0, 60.0, 120.0, 70.0], "linked_content_id": 7}}
            page = {"page_size": {"width": 300.0, "height": 400.0}, "raster_path": raster_rel}

            fake_call = AsyncMock(
                return_value={
                    "text": '{"selected_candidate_id": "cand:2", "confidence": 0.1}',
                    "model": MODEL_FLASH_HQ,
                    "tokens_in": 1,
                    "tokens_out": 1,
                }
            )

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                 patch("services.figure_resolver.call_interaction", new=fake_call):
                chosen, delta, model_used = await figure_resolver._maybe_select_candidate(
                    group, page, captions, figure_resolver._RasterCache(paper_dir), "resolver-v1",
                )

            fake_call.assert_awaited_once()
            args, kwargs = fake_call.call_args
            contents = args[0]
            self.assertEqual(contents[0]["type"], "image")
            self.assertEqual(contents[0]["mime_type"], "image/png")
            self.assertEqual(base64.b64decode(contents[0]["data"]), image_bytes)
            self.assertEqual(contents[1]["type"], "text")
            self.assertEqual(kwargs["model"], MODEL_FLASH_HQ)
            # FLASH_HQ(3.7 Flash)는 minimal을 400으로 거부한다 — low로 상향
            # (model_registry.py의 figure_resolver role, 2026-08-22).
            self.assertEqual(kwargs["thinking_level"], "low")
            self.assertIs(kwargs["store"], False)

            self.assertEqual(chosen["id"], "cand:2")
            self.assertEqual(model_used, MODEL_FLASH_HQ)

    async def test_call_interaction_exception_falls_back_to_heuristic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            raster_rel = "pages/page_1.png"
            _make_png(paper_dir / raster_rel)

            # 두 후보 모두 캡션이 연결되고 수용 게이트를 통과하는 크기여야 한다 —
            # 캡션 없는 후보는 계약 7상 어차피 버려지므로 선택 계약을 검증할 수 없다.
            group = [
                {"id": "cand:1", "bbox": [40.0, 40.0, 260.0, 300.0], "source_kind": "pymupdf_image",
                 "best_caption_id": "cap:1", "linked_caption_ids": ["cap:1"]},
                {"id": "cand:2", "bbox": [60.0, 10.0, 240.0, 220.0], "source_kind": "pymupdf_image",
                 "best_caption_id": "cap:1", "linked_caption_ids": ["cap:1"]},
            ]
            captions = {"cap:1": {"id": "cap:1", "text": "Figure 1. Example.",
                                  "bbox": [10.0, 60.0, 120.0, 70.0], "linked_content_id": 7}}
            page = {"page_size": {"width": 300.0, "height": 400.0}, "raster_path": raster_rel}

            fake_call = AsyncMock(side_effect=RuntimeError("boom"))

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                 patch("services.figure_resolver.call_interaction", new=fake_call):
                chosen, delta, model_used = await figure_resolver._maybe_select_candidate(
                    group, page, captions, figure_resolver._RasterCache(paper_dir), "resolver-v1",
                )

            self.assertEqual(delta, 0.0)
            self.assertEqual(model_used, "heuristic")

    async def test_no_api_key_skips_call_interaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            raster_rel = "pages/page_1.png"
            _make_png(paper_dir / raster_rel)

            # 두 후보 모두 캡션이 연결되고 수용 게이트를 통과하는 크기여야 한다 —
            # 캡션 없는 후보는 계약 7상 어차피 버려지므로 선택 계약을 검증할 수 없다.
            group = [
                {"id": "cand:1", "bbox": [40.0, 40.0, 260.0, 300.0], "source_kind": "pymupdf_image",
                 "best_caption_id": "cap:1", "linked_caption_ids": ["cap:1"]},
                {"id": "cand:2", "bbox": [60.0, 10.0, 240.0, 220.0], "source_kind": "pymupdf_image",
                 "best_caption_id": "cap:1", "linked_caption_ids": ["cap:1"]},
            ]
            captions = {"cap:1": {"id": "cap:1", "text": "Figure 1. Example.",
                                  "bbox": [10.0, 60.0, 120.0, 70.0], "linked_content_id": 7}}
            page = {"page_size": {"width": 300.0, "height": 400.0}, "raster_path": raster_rel}

            fake_call = AsyncMock(side_effect=AssertionError("call_interaction should not run"))

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("GEMINI_API_KEY", None)
                with patch("services.figure_resolver.call_interaction", new=fake_call):
                    chosen, delta, model_used = await figure_resolver._maybe_select_candidate(
                        group, page, captions, figure_resolver._RasterCache(paper_dir), "resolver-v1",
                    )

            fake_call.assert_not_awaited()
            self.assertEqual(model_used, "heuristic")

    async def test_openai_provider_with_only_openai_key_enters_vlm_path(self) -> None:
        """리뷰 Important 1 회귀 고정: provider=openai면 게이트가 GEMINI_API_KEY가
        아니라 OPENAI_API_KEY 존재를 봐야 한다 — 그렇지 않으면 OpenAI 단독 키
        환경에서 이 보강 경로가 한 번도 안 돌고 항상 휴리스틱으로 저하된다."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            raster_rel = "pages/page_1.png"
            _make_png(paper_dir / raster_rel)

            group = [
                {"id": "cand:1", "bbox": [40.0, 40.0, 260.0, 300.0], "source_kind": "pymupdf_image",
                 "best_caption_id": "cap:1", "linked_caption_ids": ["cap:1"]},
                {"id": "cand:2", "bbox": [60.0, 10.0, 240.0, 220.0], "source_kind": "pymupdf_image",
                 "best_caption_id": "cap:1", "linked_caption_ids": ["cap:1"]},
            ]
            captions = {"cap:1": {"id": "cap:1", "text": "Figure 1. Example.",
                                  "bbox": [10.0, 60.0, 120.0, 70.0], "linked_content_id": 7}}
            page = {"page_size": {"width": 300.0, "height": 400.0}, "raster_path": raster_rel}

            fake_call = AsyncMock(
                return_value={
                    "text": '{"selected_candidate_id": "cand:2", "confidence": 0.1}',
                    "model": "gpt-5.6-luna",
                    "tokens_in": 1,
                    "tokens_out": 1,
                }
            )

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("GEMINI_API_KEY", None)
                os.environ["OPENAI_API_KEY"] = "test-key"
                try:
                    with patch("services.figure_resolver.call_interaction", new=fake_call):
                        chosen, delta, model_used = await figure_resolver._maybe_select_candidate(
                            group, page, captions, figure_resolver._RasterCache(paper_dir),
                            "resolver-v1", provider="openai",
                        )
                finally:
                    os.environ.pop("OPENAI_API_KEY", None)

            fake_call.assert_awaited_once()
            self.assertEqual(chosen["id"], "cand:2")
            self.assertNotEqual(model_used, "heuristic")


class MaybeRerankCaptionCallInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_call_interaction_with_image_dict_and_model_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            raster_rel = "pages/page_1.png"
            image_bytes = _make_png(paper_dir / raster_rel)

            candidate = {
                "best_caption_id": "cap:1",
                "bbox": [1.0, 2.0, 3.0, 4.0],
                "linked_caption_ids": ["cap:1", "cap:2"],
                "needs_vlm_rerank": True,
            }
            captions_by_id = {
                "cap:1": {"id": "cap:1", "text": "Figure 1 caption", "bbox": [0.0, 0.0, 10.0, 10.0]},
                "cap:2": {"id": "cap:2", "text": "Figure 1 duplicate caption", "bbox": [0.0, 0.0, 10.0, 10.0]},
            }
            page = {"raster_path": raster_rel}

            fake_call = AsyncMock(
                return_value={
                    "text": '{"selected_caption_id": "cap:2", "confidence": 0.12}',
                    "model": MODEL_FLASH_HQ,
                    "tokens_in": 1,
                    "tokens_out": 1,
                }
            )

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                 patch("services.figure_resolver.call_interaction", new=fake_call):
                selected, delta, model_used = await figure_resolver._maybe_rerank_caption(
                    candidate, page, captions_by_id, figure_resolver._RasterCache(paper_dir), "resolver-v1",
                )

            fake_call.assert_awaited_once()
            args, kwargs = fake_call.call_args
            contents = args[0]
            self.assertEqual(contents[0]["type"], "image")
            self.assertEqual(contents[0]["mime_type"], "image/png")
            self.assertEqual(base64.b64decode(contents[0]["data"]), image_bytes)
            self.assertEqual(contents[1]["type"], "text")
            self.assertEqual(kwargs["model"], MODEL_FLASH_HQ)
            # FLASH_HQ(3.7 Flash)는 minimal을 400으로 거부한다 — low로 상향
            # (model_registry.py의 figure_resolver role, 2026-08-22).
            self.assertEqual(kwargs["thinking_level"], "low")
            self.assertIs(kwargs["store"], False)

            self.assertEqual(selected, "cap:2")
            self.assertAlmostEqual(delta, 0.12)
            self.assertEqual(model_used, MODEL_FLASH_HQ)


if __name__ == "__main__":
    unittest.main()


class ResolveConcurrencyAndOrderingTests(unittest.IsolatedAsyncioTestCase):
    """resolve_figure_candidates 병렬화의 두 계약을 고정한다.

    (1) 그룹별 VLM 판정이 실제로 동시에 나간다(순차 루프였다면 최대 동시 1).
    (2) 그림 번호·파일명·출력 순서는 후보 그룹 원래 순서를 그대로 따른다 —
        병렬화가 순서를 흔들면 같은 논문을 다시 분석할 때 그림 번호가 바뀐다.
    """

    def _manifest(self, paper_dir: Path, pages: int):
        import fitz

        pdf_path = paper_dir / "sample.pdf"
        doc = fitz.open()
        for _ in range(pages):
            doc.new_page(width=300, height=400)
        doc.save(str(pdf_path))
        doc.close()

        manifest_pages = []
        captions = []
        candidates = []
        for page_number in range(1, pages + 1):
            raster_rel = f".page_rasters/page_{page_number}.png"
            _make_png(paper_dir / raster_rel, size=(300, 400))
            manifest_pages.append(
                {
                    "page_number": page_number,
                    "page_size": {"width": 300.0, "height": 400.0},
                    "raster_path": raster_rel,
                }
            )
            caption_id = f"cap:{page_number}"
            captions.append(
                {
                    "id": caption_id,
                    "text": f"Figure {page_number}: sample caption",
                    "bbox": [20.0, 20.0, 280.0, 40.0],
                    "linked_content_id": None,
                }
            )
            # 그룹당 후보 2개 -> _needs_candidate_recheck가 True -> VLM 판정이 걸린다.
            for n in range(2):
                candidates.append(
                    {
                        "id": f"figcand:p{page_number}:n{n}",
                        "page_number": page_number,
                        "bbox": [30.0 + n, 60.0, 270.0, 340.0],
                        "source_kind": "pymupdf_image",
                        "linked_caption_ids": [caption_id],
                        "best_caption_id": caption_id,
                        "needs_vlm_rerank": False,
                    }
                )
        return pdf_path, {
            "engine": "gemini",
            "pages": manifest_pages,
            "captions": captions,
            "figure_candidates": candidates,
        }

    async def test_vlm_decisions_run_concurrently_and_order_is_preserved(self) -> None:
        import asyncio

        pages = 6
        inflight = {"now": 0, "max": 0}

        async def fake_call(contents, **kwargs):
            inflight["now"] += 1
            inflight["max"] = max(inflight["max"], inflight["now"])
            try:
                await asyncio.sleep(0.02)
            finally:
                inflight["now"] -= 1
            return {
                "text": '{"selected_candidate_id": "none", "confidence": 0.05}',
                "model": MODEL_FLASH_HQ,
                "tokens_in": 1,
                "tokens_out": 1,
            }

        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            pdf_path, manifest = self._manifest(paper_dir, pages)

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                 patch("services.figure_resolver.call_interaction", new=fake_call), \
                 patch("services.figure_resolver._maybe_detect_subfigures", new=AsyncMock(return_value=[])):
                result = await figure_resolver.resolve_figure_candidates(
                    manifest,
                    paper_dir=paper_dir,
                    pdf_path=pdf_path,
                    resolver_version="resolver-v1",
                )

            self.assertGreater(inflight["max"], 1, "VLM 판정이 여전히 순차로 나가고 있다")

            figures = result["figures"]
            self.assertEqual(len(figures), pages)
            # 출력 순서 = 후보 그룹 순서(페이지 오름차순)
            self.assertEqual([f["page_number"] for f in figures], list(range(1, pages + 1)))
            # 캡션에서 뽑은 그림 번호가 페이지 순서대로 부여된다
            self.assertEqual(
                [f["figure_num"] for f in figures],
                [f"Fig. {n}" for n in range(1, pages + 1)],
            )
            # 크롭 파일이 실제로 그림 번호대로 쓰였다
            for figure in figures:
                self.assertTrue((paper_dir / figure["file_path"]).exists())

    async def test_page_raster_read_once_per_page(self) -> None:
        """같은 페이지에 VLM 호출이 여러 번 걸려도 래스터는 페이지당 1회만 읽는다."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            raster_rel = "pages/page_1.png"
            _make_png(paper_dir / raster_rel)
            page = {"page_number": 1, "page_size": {"width": 300.0, "height": 400.0},
                    "raster_path": raster_rel}

            cache = figure_resolver._RasterCache(paper_dir)
            first = cache.get(page)
            (paper_dir / raster_rel).unlink()  # 파일을 지워도 캐시가 살아 있어야 한다
            second = cache.get(page)

            self.assertIsNotNone(first)
            self.assertEqual(first, second)


class CaptionlessFigureSuppressionTests(unittest.IsolatedAsyncioTestCase):
    """캡션에 연결되지 않은 후보를 언제 그림으로 인정할지.

    로고·아이콘·수식 이미지 같은 것들이 각각 그림으로 승격돼 목록을 부풀렸다
    (실측: 캡션 8개인 문서에서 그림 16개, 이름이 "p9_fig7" 꼴). 다만 파서가 캡션을
    아예 못 잡은 문서에서는 진짜 그림도 전부 캡션이 없으므로 무조건 버리면 안 된다.
    """

    @staticmethod
    def _manifest(with_caption: bool):
        page = {
            "page_number": 1,
            "page_size": {"width": 612.0, "height": 792.0},
            "raster_path": None,
        }
        captions = []
        candidates = [
            {   # 캡션에 연결되지 않은 후보 — 로고/장식 같은 것
                "id": "figcand:p1:n0",
                "page_number": 1,
                "bbox": [60.0, 400.0, 550.0, 700.0],
                "source_kind": "pymupdf_image",
                "linked_caption_ids": [],
                "best_caption_id": None,
                "needs_vlm_rerank": False,
            }
        ]
        if with_caption:
            captions.append({
                "id": "cap:p1:n0", "page_number": 1, "kind": "figure",
                "bbox": [72.0, 340.0, 540.0, 360.0],
                "text": "Figure 1: A real captioned figure.", "linked_content_id": None, "order": 0,
            })
            candidates.append({
                "id": "figcand:p1:n1",
                "page_number": 1,
                "bbox": [60.0, 60.0, 550.0, 330.0],
                "source_kind": "pymupdf_image",
                "linked_caption_ids": ["cap:p1:n0"],
                "best_caption_id": "cap:p1:n0",
                "needs_vlm_rerank": False,
            })
        return {"engine": "gemini", "pages": [page], "captions": captions,
                "figure_candidates": candidates}

    async def _resolve(self, manifest):
        import fitz
        with tempfile.TemporaryDirectory() as tmp:
            paper_dir = Path(tmp)
            pdf = paper_dir / "s.pdf"
            doc = fitz.open(); doc.new_page(width=612, height=792); doc.save(str(pdf)); doc.close()
            with patch("services.figure_resolver._maybe_detect_subfigures",
                       new=AsyncMock(return_value=[])):
                result = await figure_resolver.resolve_figure_candidates(
                    manifest, paper_dir=paper_dir, pdf_path=pdf, resolver_version="resolver-v1"
                )
        return result["figures"]

    async def test_captionless_candidate_is_dropped(self):
        figures = await self._resolve(self._manifest(with_caption=True))
        nums = [f["figure_num"] for f in figures]
        self.assertEqual(nums, ["Fig. 1"], f"캡션 없는 후보가 그림으로 남았다: {nums}")

    async def test_captionless_candidate_dropped_even_without_any_caption(self):
        """캡션이 하나도 없는 문서에서도 버린다 — 사용자 결정(2026-07-29).

        예전에는 "문서에 캡션이 있을 때만 억제"하는 안전장치가 있었으나, 캡션 서식
        정규화 이후 전 논문이 캡션을 충분히 잡아 그 분기가 한 번도 발동하지 않았다
        (12편 결과가 전부 동일). 대신 전멸 시 경고 로그를 남긴다.
        """
        with self.assertLogs("services.figure_resolver", level="WARNING") as captured:
            figures = await self._resolve(self._manifest(with_caption=False))
        self.assertEqual(figures, [])
        self.assertTrue(any("그림 0개" in line for line in captured.output),
                        "전멸했는데 진단용 경고가 없다")


class SubFigureNumberingTests(unittest.TestCase):
    """숫자 패널 라벨이 부모 번호와 붙어 구분되지 않던 문제.

    `_normalize_sub_label`은 알파벳뿐 아니라 숫자도 패널 라벨로 인정한다.
    그대로 이어붙이면 실측(2013_IEEETIP)처럼 Fig. 12의 패널 7개가
    `Fig. 121`~`Fig. 127`이 되어 존재하지 않는 121번 그림처럼 읽힌다.
    """

    def test_numeric_label_gets_a_separator(self):
        from services.figure_resolver import _subfigure_num

        self.assertEqual(_subfigure_num("Fig. 12", "1"), "Fig. 12-1")
        self.assertEqual(_subfigure_num("Fig. 12", "7"), "Fig. 12-7")
        self.assertEqual(_subfigure_num("Fig. 3", "10"), "Fig. 3-10")

    def test_alphabetic_label_keeps_existing_form(self):
        """알파벳 표기는 바꾸지 않는다 — 기존 산출물·기준선과 어긋나면 안 된다."""
        from services.figure_resolver import _subfigure_num

        self.assertEqual(_subfigure_num("Fig. 11", "C"), "Fig. 11C")
        self.assertEqual(_subfigure_num("Fig. 11", "c"), "Fig. 11C")

    def test_missing_label_falls_back_to_parent(self):
        from services.figure_resolver import _subfigure_num

        self.assertEqual(_subfigure_num("Fig. 4", None), "Fig. 4")
        self.assertEqual(_subfigure_num("Fig. 4", ""), "Fig. 4")

    def test_numeric_subfigure_is_distinguishable_from_a_real_figure(self):
        """이 단언이 회귀의 본질이다 — 라벨만 보고 부모 번호를 되찾을 수 있어야 한다."""
        from services.figure_resolver import _subfigure_num

        self.assertNotEqual(_subfigure_num("Fig. 12", "1"), "Fig. 121")


class VlmSelectionDoesNotDropFiguresTests(unittest.IsolatedAsyncioTestCase):
    """VLM이 고른 크롭이 수용 게이트에 걸려 그림이 통째로 사라지던 문제.

    `_maybe_select_candidate`의 역할은 "여럿 중 최선 고르기"이지 수용 여부를 뒤집는 것이
    아닌데, 고른 결과가 그대로 게이트로 넘어갔다. 실측(2022_SciRep p9): 휴리스틱은
    figcand:p9:n1(figure, 0.60)을 고르는데 VLM이 figcand:p9:n0(reject, 0.43,
    low_visual_signal)을 골라 **Fig. 9가 매번 없어졌다**. 2025_TurboQuant에서는 같은
    경로로 실행마다 다른 그림이 1~3개씩 사라져 그림 정확도가 실행마다 흔들렸다.
    """

    def test_acceptance_check_mirrors_the_emit_conditions(self):
        """게이트 조건이 2단계 루프와 어긋나면 이 보호 장치가 무의미해진다."""
        from services.figure_resolver import _survives_acceptance

        page = {"page_number": 1, "page_size": {"width": 612.0, "height": 792.0}}
        with patch("services.figure_resolver._score_candidate") as scored:
            scored.return_value = ("figure", 0.6, None, False, "cap:1")
            self.assertTrue(_survives_acceptance({}, page, {}, 0.0))

            scored.return_value = ("reject", 0.6, "low_visual_signal", False, "cap:1")
            self.assertFalse(_survives_acceptance({}, page, {}, 0.0), "reject 판정이 통과했다")

            scored.return_value = ("figure", 0.43, None, False, "cap:1")
            self.assertFalse(_survives_acceptance({}, page, {}, 0.0), "0.5 미만이 통과했다")

            # selection_delta가 더해져 0.5를 넘으면 통과해야 한다(실제 계산과 같게).
            self.assertTrue(_survives_acceptance({}, page, {}, 0.16))

            scored.return_value = ("figure", 0.9, None, False, None)
            self.assertFalse(_survives_acceptance({}, page, {}, 0.0), "캡션 없는 후보가 통과했다(계약 7)")
