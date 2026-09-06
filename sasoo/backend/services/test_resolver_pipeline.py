from __future__ import annotations

import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import fitz
from PIL import Image

from services.document_audit import find_suspect_pages
from services.document_manifest import build_document_manifest
from services.figure_candidates import build_figure_candidates
from services.table_candidates import build_table_candidates
from services import table_resolver as table_resolver_module
from services.table_resolver import _repair_reasons, _repair_with_vlm, resolve_table_candidates
from services.models import MODEL_FLASH_HQ


def _make_png(path: Path, size: tuple[int, int] = (40, 20)) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", size, color="white")
    image.save(path, "PNG")
    return path.read_bytes()


class ResolverMetadataTests(unittest.TestCase):
    def test_metadata_prefers_first_page_heading_and_front_matter_doi(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            pdf_path = paper_dir / "paper.pdf"
            doc = fitz.open()
            doc.new_page(width=320, height=420)
            doc.new_page(width=320, height=420)
            doc.save(pdf_path)
            doc.close()

            root = {
                "title": "",
                "author": "",
                "number of pages": 2,
                "kids": [
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "bounding box": [24, 376, 296, 404],
                        "content": "arXiv:2603.12345v1 [cs.LG] 26 Mar 2026",
                    },
                    {
                        "type": "heading",
                        "page number": 1,
                        "bounding box": [28, 314, 292, 356],
                        "content": "TurboQuant Stabilizes Caption-Aligned Extraction",
                    },
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "bounding box": [50, 276, 270, 302],
                        "content": "Alice Kim, Bob Park",
                    },
                    {
                        "type": "heading",
                        "page number": 1,
                        "bounding box": [28, 246, 108, 262],
                        "content": "Abstract",
                    },
                    {
                        "type": "paragraph",
                        "page number": 1,
                        "bounding box": [28, 214, 280, 238],
                        "content": "DOI: 10.1234/front.matter",
                    },
                    {
                        "type": "paragraph",
                        "page number": 2,
                        "bounding box": [28, 60, 280, 96],
                        "content": "References\n[1] Prior work doi 10.9999/reference.only",
                    },
                ],
            }

            manifest = build_document_manifest(
                pdf_path=pdf_path,
                paper_dir=paper_dir,
                root=root,
                markdown_text="",
                actual_engine="odl-java",
                requested_mode="java",
                extraction_pipeline_version="resolver_v1",
                parser_version="odl-v3",
                resolver_version="resolver-v1",
                generate_page_rasters=False,
            )

            metadata = manifest["metadata"]
            self.assertEqual(metadata["title"], "TurboQuant Stabilizes Caption-Aligned Extraction")
            self.assertEqual(metadata["authors"], "Alice Kim, Bob Park")
            self.assertEqual(metadata["doi"], "10.1234/front.matter")


class ResolverFigureCandidateTests(unittest.TestCase):
    def test_figure_candidates_reject_tiny_slivers_and_emit_one_caption_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            pdf_path = paper_dir / "figures.pdf"
            doc = fitz.open()
            doc.new_page(width=300, height=400)
            doc.save(pdf_path)
            doc.close()

            manifest = {
                "pages": [
                    {
                        "page_number": 1,
                        "page_size": {"width": 300.0, "height": 400.0},
                        "caption_blocks": [
                            {
                                "id": "cap:1",
                                "page_number": 1,
                                "bbox": [40.0, 40.0, 190.0, 60.0],
                                "text": "Figure 1. Caption-aligned figure",
                                "kind": "figure",
                                "linked_content_id": 101,
                                "order": 3,
                            },
                            {
                                "id": "cap:1-dup",
                                "page_number": 1,
                                "bbox": [40.0, 40.0, 190.0, 60.0],
                                "text": "Figure 1. Caption-aligned figure",
                                "kind": "figure",
                                "linked_content_id": 101,
                                "order": 4,
                            },
                        ],
                        "image_blocks": [
                            {
                                "id": "img:tiny",
                                "page_number": 1,
                                "bbox": [80.0, 80.0, 92.0, 220.0],
                                "source_id": 101,
                                "order": 1,
                            }
                        ],
                        "text_blocks": [],
                    }
                ]
            }

            candidates = build_figure_candidates(manifest, pdf_path=pdf_path)

            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["best_caption_id"], "cap:1")
            self.assertEqual(candidates[0]["source_kind"], "caption_fallback_crop")
            self.assertGreater(candidates[0]["bbox"][2] - candidates[0]["bbox"][0], 200.0)
            self.assertGreater(candidates[0]["bbox"][3] - candidates[0]["bbox"][1], 200.0)


class ResolverTableCandidateTests(unittest.TestCase):
    def test_table_candidates_discard_empty_odl_placeholders(self) -> None:
        manifest = {
            "pages": [
                {
                    "page_number": 1,
                    "page_size": {"width": 300.0, "height": 400.0},
                    "caption_blocks": [
                        {
                            "id": "tblcap:1",
                            "page_number": 1,
                            "bbox": [30.0, 280.0, 160.0, 300.0],
                            "text": "Table 1. Real grid",
                            "kind": "table",
                            "order": 1,
                        }
                    ],
                    "odl_table_nodes": [
                        {
                            "id": "odl:empty",
                            "page_number": 1,
                            "bbox": [10.0, 10.0, 30.0, 24.0],
                            "rows": [{"cells": [{"content": ""}]}],
                            "text": "",
                            "order": 2,
                        }
                    ],
                }
            ]
        }

        with patch(
            "services.table_candidates._pdfplumber_candidates",
            return_value={
                1: [
                    {
                        "id": "pdf:1",
                        "bbox": [30.0, 120.0, 260.0, 250.0],
                        "text_grid": [["A", "B"], ["1", "2"]],
                        "source_kind": "pdfplumber",
                    }
                ]
            },
        ):
            candidates = build_table_candidates(
                manifest,
                pdf_path=Path("/tmp/placeholder.pdf"),
                paper_dir=Path("/tmp"),
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source_kind"], "pdfplumber")
        self.assertTrue(candidates[0]["has_meaningful_grid"])


class ResolverTableResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_rule_based_sparse_header_cleanup_resolves_without_vlm(self) -> None:
        manifest = {
            "captions": [
                {
                    "id": "tblcap:1",
                    "text": "Table 1. Sample summary",
                }
            ],
            "table_candidates": [
                {
                    "id": "tblcand:p1:n0",
                    "page_number": 1,
                    "bbox": [30.0, 110.0, 260.0, 250.0],
                    "source_kind": "pdfplumber",
                    "text_grid": [
                        ["", "Value"],
                        ["Sample", "Mean"],
                        ["A", "1.0"],
                        ["B", "2.0"],
                    ],
                    "best_caption_id": "tblcap:1",
                    "plausible_ruled_bbox": False,
                    "had_irregular_rows": False,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch(
                "services.table_resolver._repair_with_vlm",
                new=AsyncMock(side_effect=AssertionError("VLM repair should not run")),
            ):
                result = await resolve_table_candidates(
                    manifest,
                    paper_dir=Path(tmp_dir),
                    resolver_version="resolver-v1",
                )

        self.assertEqual(len(result["tables"]), 1)
        table = result["tables"][0]
        self.assertEqual(table["extraction_status"], "resolved")
        self.assertFalse(table["review_required"])
        self.assertFalse(table["repair_attempted"])
        self.assertIn("Value / Mean", table["markdown_text"])

    async def test_irregular_rows_stay_uncertain_with_review_metadata(self) -> None:
        manifest = {
            "captions": [
                {
                    "id": "tblcap:2",
                    "text": "Table 2. Needs review",
                }
            ],
            "table_candidates": [
                {
                    "id": "tblcand:p1:n1",
                    "page_number": 1,
                    "bbox": [30.0, 110.0, 260.0, 250.0],
                    "source_kind": "odl",
                    "text_grid": [
                        ["Name", "Value"],
                        ["A", "1.0"],
                        ["B", "2.0"],
                    ],
                    "best_caption_id": "tblcap:2",
                    "plausible_ruled_bbox": True,
                    "had_irregular_rows": True,
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch(
                "services.table_resolver._repair_with_vlm",
                new=AsyncMock(
                    return_value=(
                        [["Name", "Value"], ["A", "1.0"], ["B", "2.0"]],
                        "mock-vlm",
                        0.31,
                    )
                ),
            ):
                result = await resolve_table_candidates(
                    manifest,
                    paper_dir=Path(tmp_dir),
                    resolver_version="resolver-v1",
                )

        self.assertEqual(len(result["tables"]), 1)
        table = result["tables"][0]
        self.assertEqual(table["extraction_status"], "uncertain")
        self.assertTrue(table["review_required"])
        self.assertTrue(table["repair_attempted"])
        self.assertEqual(table["repair_reason"], "irregular_row_widths")
        self.assertEqual(table["repair_confidence"], 0.31)
        self.assertEqual(result["low_confidence_pages"], [1])


class RepairWithVlmCallInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_calls_call_interaction_with_image_dict_and_model_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            raster_rel = "pages/page_1.png"
            image_bytes = _make_png(paper_dir / raster_rel)

            manifest = {"pages": [{"page_number": 1, "raster_path": raster_rel}]}
            candidate = {
                "page_number": 1,
                "bbox": [1.0, 2.0, 3.0, 4.0],
                "text_grid": [["", "Value"], ["A", "1.0"]],
            }

            fake_call = AsyncMock(
                return_value={
                    "text": '{"rows": [["Name", "Value"], ["A", "1.0"]], "confidence": 0.5}',
                    "model": MODEL_FLASH_HQ,
                    "tokens_in": 1,
                    "tokens_out": 1,
                }
            )

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                 patch("services.table_resolver.call_interaction", new=fake_call):
                grid, model_used, confidence = await _repair_with_vlm(candidate, manifest, paper_dir)

            fake_call.assert_awaited_once()
            args, kwargs = fake_call.call_args
            contents = args[0]
            self.assertEqual(contents[0]["type"], "image")
            self.assertEqual(contents[0]["mime_type"], "image/png")
            self.assertEqual(base64.b64decode(contents[0]["data"]), image_bytes)
            self.assertEqual(contents[1]["type"], "text")
            self.assertEqual(kwargs["model"], MODEL_FLASH_HQ)
            # FLASH_HQ(3.7/3.8 Flash)는 minimal을 400으로 거부한다 — low로 상향
            # (model_registry.py의 table_resolver role, 2026-08-22).
            self.assertEqual(kwargs["thinking_level"], "low")
            self.assertIs(kwargs["store"], False)

            self.assertEqual(grid, [["Name", "Value"], ["A", "1.0"]])
            self.assertEqual(model_used, MODEL_FLASH_HQ)
            self.assertAlmostEqual(confidence, 0.5)

    async def test_no_api_key_skips_call_interaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            manifest = {"pages": [{"page_number": 1, "raster_path": "pages/page_1.png"}]}
            candidate = {"page_number": 1, "text_grid": [["A", "B"], ["1", "2"]]}

            fake_call = AsyncMock(side_effect=AssertionError("call_interaction should not run"))

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("GEMINI_API_KEY", None)
                with patch("services.table_resolver.call_interaction", new=fake_call):
                    grid, model_used, confidence = await _repair_with_vlm(candidate, manifest, paper_dir)

            fake_call.assert_not_awaited()
            self.assertEqual(model_used, "heuristic")
            self.assertEqual(confidence, 0.0)

    async def test_openai_provider_with_only_openai_key_enters_vlm_path(self) -> None:
        """리뷰 Important 1 회귀 고정: provider=openai면 게이트가 GEMINI_API_KEY가
        아니라 OPENAI_API_KEY 존재를 봐야 한다. 그렇지 않으면 OpenAI 단독 키
        환경에서 격자 복원이 한 번도 안 돌아 text_grid가 빈 표 후보가 통째로
        탈락한다(최종 필터 _has_meaningful_grid에서 100% 걸러짐)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            raster_rel = "pages/page_1.png"
            _make_png(paper_dir / raster_rel)

            manifest = {"pages": [{"page_number": 1, "raster_path": raster_rel}]}
            candidate = {
                "page_number": 1,
                "bbox": [1.0, 2.0, 3.0, 4.0],
                "text_grid": [],  # caption_fallback_crop 후보처럼 grid가 비어 있음
            }

            fake_call = AsyncMock(
                return_value={
                    "text": '{"rows": [["Name", "Value"], ["A", "1.0"]], "confidence": 0.5}',
                    "model": "gpt-5.6-luna",
                    "tokens_in": 1,
                    "tokens_out": 1,
                }
            )

            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("GEMINI_API_KEY", None)
                os.environ["OPENAI_API_KEY"] = "test-key"
                try:
                    with patch("services.table_resolver.call_interaction", new=fake_call):
                        grid, model_used, confidence = await _repair_with_vlm(
                            candidate, manifest, paper_dir, provider="openai",
                        )
                finally:
                    os.environ.pop("OPENAI_API_KEY", None)

            fake_call.assert_awaited_once()
            self.assertEqual(grid, [["Name", "Value"], ["A", "1.0"]])
            self.assertNotEqual(model_used, "heuristic")

    async def test_call_interaction_exception_falls_back_to_heuristic_grid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            raster_rel = "pages/page_1.png"
            _make_png(paper_dir / raster_rel)

            manifest = {"pages": [{"page_number": 1, "raster_path": raster_rel}]}
            candidate = {
                "page_number": 1,
                "bbox": [1.0, 2.0, 3.0, 4.0],
                "text_grid": [["A", "B"], ["1", "2"]],
            }

            fake_call = AsyncMock(side_effect=RuntimeError("boom"))

            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                 patch("services.table_resolver.call_interaction", new=fake_call):
                grid, model_used, confidence = await _repair_with_vlm(candidate, manifest, paper_dir)

            self.assertEqual(grid, [["A", "B"], ["1", "2"]])
            self.assertEqual(model_used, "heuristic")
            self.assertEqual(confidence, 0.0)


class ResolverAuditTests(unittest.TestCase):
    def test_audit_flags_low_quality_visual_results(self) -> None:
        audit = find_suspect_pages(
            full_text="--- Page 1 ---\nFigure 1 is discussed here. Figure 2 is discussed here.",
            pages=[{"page_number": 1, "page_size": {"width": 300.0, "height": 400.0}}],
            figures=[
                {
                    "page_number": 1,
                    "bbox": [10.0, 20.0, 42.0, 48.0],
                    "confidence": 0.61,
                    "quality": "low",
                }
            ],
            tables=[],
            figure_candidates=[
                {
                    "page_number": 1,
                    "bbox": [10.0, 20.0, 42.0, 48.0],
                    "weak_image_evidence": True,
                }
            ],
            table_candidates=[],
        )

        self.assertTrue(audit["triggered"])
        self.assertEqual(audit["reason"], "low_quality_visual_results")
        self.assertEqual(audit["suspect_pages"], [1])


class RetryPassMergeTests(unittest.IsolatedAsyncioTestCase):
    """_build_resolver_v1_manifest의 재시도 패스 수와 대상 페이지 집합을 고정한다.

    예전 구조는 (1) low_confidence 재시도와 (2) audit suspect 재시도를 그림·표 각각
    따로 돌려 문서당 최대 6번의 resolve 패스가 나갔다. 두 집합을 합쳐 한 번만
    재시도하도록 바꿨으므로, 패스 수와 합집합 의미를 회귀 테스트로 못박는다.
    """

    async def _run(self, *, low_figure_pages, low_table_pages, suspect_pages):
        from services import odl_parser

        figure_calls: list[set[int] | None] = []
        table_calls: list[set[int] | None] = []

        async def fake_resolve_figures(manifest, **kwargs):
            page_numbers = kwargs.get("page_numbers")
            figure_calls.append(page_numbers)
            # 1차 패스에서만 low_confidence를 보고한다(재시도 패스는 빈 목록).
            low = low_figure_pages if page_numbers is None else []
            return {"figures": [], "low_confidence_pages": sorted(low)}

        async def fake_resolve_tables(manifest, **kwargs):
            page_numbers = kwargs.get("page_numbers")
            table_calls.append(page_numbers)
            low = low_table_pages if page_numbers is None else []
            return {"tables": [], "low_confidence_pages": sorted(low)}

        with tempfile.TemporaryDirectory() as tmp:
            paper_dir = Path(tmp)
            pdf_path = paper_dir / "sample.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.save(str(pdf_path))
            doc.close()

            with patch.object(odl_parser, "resolve_figure_candidates", fake_resolve_figures), \
                 patch.object(odl_parser, "resolve_table_candidates", fake_resolve_tables), \
                 patch.object(odl_parser, "build_figure_candidates", lambda *a, **k: []), \
                 patch.object(odl_parser, "build_table_candidates", lambda *a, **k: []), \
                 patch.object(odl_parser, "active_provider", AsyncMock(return_value="gemini")), \
                 patch.object(
                     odl_parser,
                     "find_suspect_pages",
                     lambda **k: {"suspect_pages": sorted(suspect_pages), "triggered": bool(suspect_pages)},
                 ):
                await odl_parser._build_resolver_v1_manifest(
                    paper_dir=paper_dir,
                    pdf_path=pdf_path,
                    root={"kids": []},
                    markdown_text="",
                    actual_engine="gemini",
                    requested_mode="resolver_v1",
                )

        return figure_calls, table_calls

    async def test_no_retry_when_everything_resolves(self):
        figure_calls, table_calls = await self._run(
            low_figure_pages=[], low_table_pages=[], suspect_pages=[]
        )
        self.assertEqual(figure_calls, [None])  # 1차 패스뿐
        self.assertEqual(table_calls, [None])

    async def test_low_confidence_and_suspect_merge_into_one_retry(self):
        # 예전엔 그림 3패스(1차 + low_conf + suspect), 표 3패스가 나갔다.
        figure_calls, table_calls = await self._run(
            low_figure_pages=[2], low_table_pages=[5], suspect_pages=[7, 9]
        )

        self.assertEqual(len(figure_calls), 2, "그림 resolve는 1차 + 병합 재시도 2회여야 한다")
        self.assertEqual(len(table_calls), 2, "표 resolve는 1차 + 병합 재시도 2회여야 한다")
        self.assertIsNone(figure_calls[0])
        self.assertIsNone(table_calls[0])
        # 재시도 대상은 low_confidence ∪ suspect (커버리지가 이전보다 좁아지지 않는다).
        self.assertEqual(figure_calls[1], {2, 7, 9})
        self.assertEqual(table_calls[1], {5, 7, 9})

    async def test_suspect_only_still_retries_both(self):
        figure_calls, table_calls = await self._run(
            low_figure_pages=[], low_table_pages=[], suspect_pages=[3]
        )
        self.assertEqual(figure_calls[1], {3})
        self.assertEqual(table_calls[1], {3})


class OrphanFigureCleanupTests(unittest.TestCase):
    """반복 resolve 패스가 남긴 고아 크롭 PNG를 정리한다(실측: figures 21개에 PNG 41개)."""

    def test_unreferenced_crops_are_removed_and_referenced_kept(self):
        from services.odl_parser import _prune_orphan_figure_files

        with tempfile.TemporaryDirectory() as tmp:
            paper_dir = Path(tmp)
            figures_dir = paper_dir / "figures"
            kept = figures_dir / "Fig_1.png"
            orphan = figures_dir / "Fig_1_oldpass.png"
            _make_png(kept)
            _make_png(orphan)

            _prune_orphan_figure_files(paper_dir, [{"file_path": "figures/Fig_1.png"}])

            self.assertTrue(kept.exists())
            self.assertFalse(orphan.exists())

    def test_missing_figures_dir_is_a_noop(self):
        from services.odl_parser import _prune_orphan_figure_files

        with tempfile.TemporaryDirectory() as tmp:
            _prune_orphan_figure_files(Path(tmp), [])  # 예외 없이 조용히 끝나야 한다


if __name__ == "__main__":
    unittest.main()


class TableCaptionFallbackTests(unittest.IsolatedAsyncioTestCase):
    """표 캡션은 있는데 구조 검출기가 모두 놓친 경우의 폴백.

    그림 쪽에는 caption_fallback_crop이 있었는데 표에만 없어서, ODL/pdfplumber/래스터
    괘선이 전부 표를 놓치면 캡션이 멀쩡히 있어도 table_candidates=0이 되고 표가 영구히
    사라졌다(실측: 표 캡션 1개인 논문의 candidates=0 -> tables=0).
    """

    @staticmethod
    def _page_with_table_caption():
        return {
            "page_number": 1,
            "page_size": {"width": 612.0, "height": 792.0},
            "raster_path": None,
            "text_blocks": [],
            "image_blocks": [],
            "odl_table_nodes": [],          # ODL 미검출
            "caption_blocks": [
                {
                    "id": "cap:p1:n0",
                    "page_number": 1,
                    "kind": "table",
                    # 페이지 위쪽 캡션 -> 표는 그 아래에 있다고 본다.
                    "bbox": [72.0, 600.0, 540.0, 620.0],
                    "text": "Table 1: Measured throughput by configuration.",
                    "order": 0,
                }
            ],
        }

    def _build(self, page, pdf_path, paper_dir):
        # pdfplumber / 래스터 괘선 검출기는 아무것도 못 찾은 상황을 만든다.
        with patch("services.table_candidates._pdfplumber_candidates", return_value={}), \
             patch("services.table_candidates._raster_ruled_table_candidates", return_value=[]):
            return build_table_candidates(
                {"pages": [page]}, pdf_path=pdf_path, paper_dir=paper_dir
            )

    def test_caption_without_detector_hit_still_yields_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            paper_dir = Path(tmp)
            pdf_path = paper_dir / "sample.pdf"
            doc = fitz.open(); doc.new_page(width=612, height=792); doc.save(str(pdf_path)); doc.close()

            candidates = self._build(self._page_with_table_caption(), pdf_path, paper_dir)

            self.assertEqual(len(candidates), 1, "캡션 폴백 후보가 만들어지지 않았다")
            candidate = candidates[0]
            self.assertEqual(candidate["source_kind"], "caption_fallback_crop")
            self.assertEqual(candidate["best_caption_id"], "cap:p1:n0")
            self.assertFalse(candidate["has_meaningful_grid"])
            # 이 후보가 resolver의 VLM 수리 게이트를 열어야 의미가 있다.
            reasons = _repair_reasons(candidate, page_number=1, suspect_pages=set(), grid=[])
            self.assertIn("caption_linked_but_grid_weak", reasons)

    def test_no_duplicate_when_detector_already_covers_caption(self):
        """검출기가 이미 그 캡션의 표를 찾았으면 폴백을 덧붙이지 않는다."""
        page = self._page_with_table_caption()
        page["odl_table_nodes"] = [
            {
                "id": "odltbl:p1:n0",
                "page_number": 1,
                "bbox": [72.0, 380.0, 540.0, 590.0],   # 캡션 바로 아래의 실제 표
                "rows": [["A", "B"], ["1", "2"], ["3", "4"]],
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            paper_dir = Path(tmp)
            pdf_path = paper_dir / "sample.pdf"
            doc = fitz.open(); doc.new_page(width=612, height=792); doc.save(str(pdf_path)); doc.close()

            candidates = self._build(page, pdf_path, paper_dir)

            kinds = [c["source_kind"] for c in candidates]
            self.assertNotIn("caption_fallback_crop", kinds, "검출기가 찾았는데도 폴백이 붙었다")

    async def test_fallback_candidate_reaches_vlm_repair(self):
        """폴백 후보가 조용히 버려지지 않고 실제로 VLM 수리를 태운다."""
        manifest = {
            "pages": [dict(self._page_with_table_caption(), raster_path="p1.png")],
            "captions": [self._page_with_table_caption()["caption_blocks"][0]],
            "table_candidates": [
                {
                    "id": "tblcand:p1:cap0",
                    "page_number": 1,
                    "bbox": [30.0, 300.0, 580.0, 590.0],
                    "source_kind": "caption_fallback_crop",
                    "text_grid": [],
                    "linked_caption_ids": ["cap:p1:n0"],
                    "best_caption_id": "cap:p1:n0",
                    "has_meaningful_grid": False,
                    "plausible_ruled_bbox": True,
                    "had_irregular_rows": False,
                }
            ],
            "audit": {"suspect_pages": []},
        }
        repaired = {"rows": [["cfg", "Gbps"], ["A", "1.2"], ["B", "3.4"]], "confidence": 0.9}
        fake = AsyncMock(return_value={
            "text": json.dumps(repaired), "model": MODEL_FLASH_HQ, "tokens_in": 1, "tokens_out": 1,
        })

        with tempfile.TemporaryDirectory() as tmp:
            paper_dir = Path(tmp)
            _make_png(paper_dir / "p1.png")
            with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}), \
                 patch("services.table_resolver.call_interaction", new=fake):
                result = await resolve_table_candidates(
                    manifest, paper_dir=paper_dir, resolver_version="resolver-v1"
                )

        fake.assert_awaited_once()
        self.assertEqual(len(result["tables"]), 1, "폴백 후보가 표로 복원되지 않았다")
        self.assertEqual(result["tables"][0]["table_num"], "Table 1")


class CaptionFallbackSuppressionTests(unittest.TestCase):
    """캡션 폴백이 엉뚱하게 차단되던 문제.

    폴백 생성 여부를 linked_caption_ids로 판정했는데, 그건 후보 주변 캡션 상위 3개일 뿐
    "이 후보가 그 캡션을 대표한다"는 뜻이 아니다(_best_linked_caption). 그래서:
      - 한 페이지에 그림이 둘이면 Figure 2의 후보가 Figure 1의 캡션까지 달아 Figure 1이 소실
      - 약한 후보가 자기 캡션을 달고 있어 aggressive 재시도의 폴백까지 차단
    실측(41쪽 논문): 원문 13개 중 9개만 추출, Figure 1·3·6이 이 경로로 사라졌다.
    """

    @staticmethod
    def _page(captions, image_blocks=(), text_blocks=()):
        return {
            "page_number": 1,
            "page_size": {"width": 612.0, "height": 792.0},
            "text_blocks": list(text_blocks),
            "image_blocks": list(image_blocks),
            "caption_blocks": list(captions),
            "odl_table_nodes": [],
        }

    @staticmethod
    def _caption(cid, text, bbox, order=0):
        return {"id": cid, "page_number": 1, "kind": "figure", "bbox": bbox,
                "text": text, "linked_content_id": None, "order": order}

    def _build(self, page, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "s.pdf"
            doc = fitz.open(); doc.new_page(width=612, height=792); doc.save(str(pdf)); doc.close()
            with patch("services.figure_candidates._extract_pymupdf_image_blocks", return_value={}):
                return build_figure_candidates({"pages": [page]}, pdf_path=pdf, **kwargs)

    def test_second_figure_on_page_still_gets_a_candidate(self):
        """한 페이지에 그림이 둘일 때, 한쪽 후보가 다른 쪽 캡션을 가로채지 않는다.

        이미지 블록을 두 캡션의 밴드 밖에 두면 blockcandidate 경로가 타면서
        linked_caption_ids에 두 캡션이 모두 담긴다(_best_linked_caption은 근처 상위 3개).
        예전 판정은 이걸 "cap:1도 커버됨"으로 읽어 Figure 1의 폴백을 막았다.
        """
        page = self._page(
            captions=[
                self._caption("cap:1", "Figure 1. Classification.", [72.0, 700.0, 540.0, 720.0], 0),
                self._caption("cap:2", "Figure 2. Space FSO links.", [72.0, 300.0, 540.0, 320.0], 1),
            ],
            image_blocks=[
                {"id": "i1", "bbox": [100.0, 120.0, 300.0, 270.0], "source_kind": "odl_image"},
                {"id": "i2", "bbox": [320.0, 120.0, 520.0, 270.0], "source_kind": "odl_image"},
            ],
        )
        candidates = self._build(page)
        linked_anywhere = {cid for c in candidates for cid in (c.get("linked_caption_ids") or [])}
        self.assertIn("cap:1", linked_anywhere, "픽스처가 실제 조건(다른 후보가 cap:1을 링크)을 재현하지 못한다")

        represented = {c.get("best_caption_id") for c in candidates}
        self.assertIn("cap:2", represented)
        self.assertIn("cap:1", represented, "다른 그림의 후보에 가려 Figure 1이 후보조차 못 얻었다")

    def test_aggressive_retry_adds_fallback_despite_weak_candidate(self):
        """약한 후보가 있어도 aggressive 재시도에선 폴백을 추가한다.

        aggressive는 1차에서 실패한 페이지를 다시 시도하라는 뜻인데, 실패의 원인인 약한
        후보(caption_chart_text, weak_image_evidence)가 폴백을 막으면 재시도가 아무것도
        바꾸지 못한다 — 실측에서 Figure 3·6이 이 경로로 끝내 복구되지 않았다.
        """
        page = self._page(
            captions=[
                self._caption("cap:1", "Figure 1. Classification.", [72.0, 700.0, 540.0, 720.0], 0),
                self._caption("cap:2", "Figure 6. Stare/Scan acquisition.", [72.0, 300.0, 540.0, 320.0], 1),
            ],
            text_blocks=[{"id": "t1", "bbox": [100.0, 400.0, 500.0, 500.0],
                          "text": "0 10 nm 20 nm 30 nm", "type": "paragraph"}],
        )
        weak = [c for c in self._build(page) if c.get("weak_image_evidence") and c["source_kind"] == "caption_chart_text"]
        self.assertTrue(weak, "픽스처가 약한 후보(caption_chart_text)를 만들지 못한다")

        aggressive = self._build(page, page_numbers={1}, aggressive=True)
        fallbacks_for_cap2 = [
            c for c in aggressive
            if c["source_kind"] == "caption_fallback_crop" and c.get("best_caption_id") == "cap:2"
        ]
        self.assertTrue(
            fallbacks_for_cap2,
            "약한 후보에 가려 aggressive 재시도의 폴백이 생성되지 않았다",
        )

    def test_same_label_captions_are_deduped(self):
        """같은 라벨의 캡션이 조각나 여러 개 잡혀도 후보는 하나만 만든다.

        안 그러면 "Fig. 1"과 "Fig. 1 [2]"가 함께 나온다(합자·줄바꿈으로 텍스트가
        미세하게 달라 전체 텍스트 비교로는 안 걸러진다).
        """
        page = self._page(captions=[
            self._caption("cap:1", "Figure 1. Classiﬁcation of the optical links.", [72.0, 700.0, 540.0, 720.0], 0),
            self._caption("cap:2", "Figure 1. Classification of the optical links", [72.0, 698.0, 538.0, 718.0], 1),
        ])
        candidates = self._build(page)
        used = [c.get("best_caption_id") for c in candidates]
        self.assertLessEqual(len(set(used)), 1, f"같은 Figure 1에 후보가 중복 생성됐다: {used}")


class CaptionDecorationTests(unittest.TestCase):
    """캡션 앞 마크다운 서식 때문에 라벨 인식이 통째로 실패하던 문제.

    gemini 파서는 캡션을 마크다운 그대로 내보내므로 "**Fig. 1. ...**"처럼 볼드로 시작한다.
    라벨 패턴은 전부 문두 매칭이라 "**"가 하나만 붙어도 매칭이 깨지고, 그러면
    (1) 캡션 종류 판정이 unknown이 되고 (2) 그림 번호가 "p3_fig1" 꼴로 떨어진다.
    실측: 캡션 6개가 전부 unknown으로 떨어져 그림이 원문 8개 대비 17개까지 부풀었다.
    """

    def test_strips_markdown_and_decoration_prefixes(self):
        from services.document_manifest import strip_caption_decoration

        for raw, expected_start in [
            ("**Fig. 1. Traversing terrains.**", "Fig. 1."),
            ("__Figure 2.__ Training pipeline", "Figure 2."),
            ("### Table 3: Results", "Table 3:"),
            ("• Figure 4. Something", "Figure 4."),
            ("   Fig. 5. Already clean", "Fig. 5."),
        ]:
            with self.subTest(raw=raw):
                self.assertTrue(strip_caption_decoration(raw).startswith(expected_start))

    def test_bold_caption_is_classified_as_figure(self):
        from services.document_manifest import _caption_kind

        self.assertEqual(_caption_kind("**Fig. 1. Traversing challenging terrains.**"), "figure")
        self.assertEqual(_caption_kind("**Table 2.** Ablation results"), "table")
        self.assertIsNone(_caption_kind("**Discussion**"))

    def test_bold_caption_yields_proper_figure_number(self):
        """번호 부여도 같은 문두 매칭이라 함께 깨졌다 — "p3_fig1" 대신 "Fig. 1"이 나와야 한다."""
        from services.figure_resolver import _normalized_figure_num

        seen: set[str] = set()
        self.assertEqual(
            _normalized_figure_num("**Fig. 1. Traversing terrains.**", 3, 1, seen), "Fig. 1"
        )

    def test_bold_caption_yields_proper_table_number(self):
        from services.table_resolver import _table_num

        seen: set[str] = set()
        self.assertEqual(_table_num("**Table 2.** Ablation results", 4, 1, seen), "Table 2")


class InlineMentionCaptionTests(unittest.TestCase):
    """본문 문장이 캡션으로 오인돼 그림이 중복 생성되던 문제.

    "Fig. N"으로 시작하기만 하면 캡션으로 인정했기 때문에, 본문 첫 문장이
    "Figure 9 shows time-series data..."처럼 시작하면 그것이 별도 캡션 블록이 되고
    같은 번호의 그림 후보가 하나 더 생겼다("Fig. 9"와 "Fig. 9 [2]").
    실측 초과분(2013_IEEETIP +1, 2022_SciRep +1, 2022_ApplOpt +3)이 정확히 이 케이스였다.

    가르는 기준은 라벨 바로 뒤다. 구분자(. : ,)나 대문자로 이어지면 캡션,
    소문자 단어(=동사)로 이어지면 본문 문장이다. 아래 문자열은 전부 실제 코퍼스에서 뽑았다.
    """

    # 실제 라이브러리 12편의 캡션 블록에서 뽑은 본문 언급 전량(라벨 뒤 형태별 대표)
    INLINE_MENTIONS = [
        "Fig. 8 shows some visual results of saliency detection on image pairs.",
        "Fig. 12 shows some segmentation results using our co-saliency map.",
        "Figure 3 shows the comparison of atmospheric turbulence prediction results",
        "Figure 9 shows time-series data for the 2022/04/21 high speed flight",
        "Fig. 1 illustrates the co-saliency example, where the single image algorithm",
        "Figure 6 illustrates the comparison of atmospheric turbulence prediction",
        "Fig. 2(e) shows the corresponding cue, where the soccer players in red",
        "Figure 4(a) shows the atmospheric turbulence before the compensation",
    ]

    # 반대로 캡션으로 남아야 하는 것들. 마지막 두 개가 핵심 —
    # 구분자 없는 캡션(TurPy Fig. 2)과 공백 없는 표기(2022_ApplOpt p3)가 실제로 존재한다.
    REAL_CAPTIONS = [
        "Fig. 1. Given a group of images (first row), the state-of-the-art methods",
        "Figure 1: Error distribution of TurboQuantprod for Inner Product Estimation",
        "**Fig. 1. Traversing challenging terrains.**",
        "Figure\xa01. Schematic of the coherent FSO terminal",
        "Fig. 2 Subharmonic Phase Screen Generation. (A) An original screen",
        "Fig.2. Architecture of the prediction network",
    ]

    def test_fixture_strings_start_with_a_figure_label(self):
        """픽스처가 조건을 재현하는지 먼저 단언한다 — 라벨 매칭 자체는 전부 성공해야 한다.

        이 단언이 없으면 "라벨이 아예 안 잡혀서" None이 나온 것을 성공으로 오인할 수 있다.
        """
        from services.document_manifest import FIGURE_LABEL_PATTERN, strip_caption_decoration

        for text in self.INLINE_MENTIONS + self.REAL_CAPTIONS:
            with self.subTest(text=text):
                self.assertIsNotNone(
                    FIGURE_LABEL_PATTERN.match(strip_caption_decoration(text)),
                    "픽스처가 조건을 재현하지 못한다: 라벨 패턴에 애초에 안 걸린다",
                )

    def test_inline_mentions_are_not_captions(self):
        from services.document_manifest import _caption_kind

        for text in self.INLINE_MENTIONS:
            with self.subTest(text=text):
                self.assertIsNone(_caption_kind(text))

    def test_real_captions_survive(self):
        from services.document_manifest import _caption_kind

        for text in self.REAL_CAPTIONS:
            with self.subTest(text=text):
                self.assertEqual(_caption_kind(text), "figure")

    def test_table_inline_mention_is_not_a_caption(self):
        from services.document_manifest import _caption_kind

        self.assertIsNone(_caption_kind("Table 3 summarizes the ablation results."))
        self.assertEqual(_caption_kind("Table 3. Ablation results."), "table")


class CaptionRecoveryTests(unittest.TestCase):
    """파서가 페이지 하나의 캡션 요소를 통째로 빠뜨려 그림이 사라지던 문제.

    실측(2026_SR_AgileMultiskill): 원문 Figure 1~8인데 gemini가 p6·p9에서 caption/image
    요소를 하나도 내지 않아 Fig. 3과 Fig. 5가 없어졌다. markdown에는 두 캡션이 온전히
    들어 있었으므로 프롬프트가 아니라 elements 방출이 확률적으로 누락된 것이다.
    캡션 없는 후보는 버리는 규칙(2026-07-29 결정) 때문에 누락이 곧 그림 소실로 이어진다.

    캡션 텍스트는 PDF 안에 결정적으로 존재하므로, LLM이 빠뜨린 페이지는 PyMuPDF 텍스트
    블록에서 되살린다.
    """

    @staticmethod
    def _build_pdf(path, page_texts):
        import fitz

        doc = fitz.open()
        for lines in page_texts:
            page = doc.new_page(width=595, height=842)
            y = 700
            for line in lines:
                page.insert_text((40, y), line, fontsize=9)
                y += 20
        doc.save(str(path))
        doc.close()

    @staticmethod
    def _page_stub(page_number, caption_blocks=()):
        return {
            "page_number": page_number,
            "page_size": {"width": 595.0, "height": 842.0},
            "text_blocks": [],
            "image_blocks": [],
            "caption_blocks": list(caption_blocks),
            "odl_table_nodes": [],
        }

    def _run(self, page_texts, pages):
        from services.document_manifest import recover_missing_caption_blocks

        with tempfile.TemporaryDirectory() as tmp:
            pdf_path = Path(tmp) / "sample.pdf"
            self._build_pdf(pdf_path, page_texts)
            return recover_missing_caption_blocks(pdf_path=pdf_path, pages=pages)

    def test_fixture_page_really_has_no_caption_block(self):
        """픽스처가 조건을 재현하는지 먼저 단언한다 — 2페이지는 정말로 캡션이 비어 있어야 한다."""
        pages = {1: self._page_stub(1), 2: self._page_stub(2)}
        self.assertEqual(pages[2]["caption_blocks"], [])

    def test_recovers_caption_the_parser_dropped(self):
        pages = {
            1: self._page_stub(
                1,
                [
                    {
                        "id": "cap:p1:n0",
                        "page_number": 1,
                        "bbox": [40.0, 130.0, 500.0, 150.0],
                        "text": "Fig. 1. Traversing challenging terrains.",
                        "kind": "figure",
                        "order": 3,
                    }
                ],
            ),
            2: self._page_stub(2),
        }
        recovered = self._run(
            [
                ["Fig. 1. Traversing challenging terrains."],
                ["Fig. 2. Training pipeline for APT-RL."],
            ],
            pages,
        )

        self.assertEqual(len(recovered), 1, f"복원 결과가 예상과 다르다: {recovered}")
        block = recovered[0]
        self.assertEqual(block["page_number"], 2)
        self.assertEqual(block["kind"], "figure")
        self.assertTrue(block["text"].startswith("Fig. 2."))
        self.assertEqual(pages[2]["caption_blocks"], [block])
        # 1페이지는 이미 캡션이 있으니 건드리면 안 된다 — 중복은 곧 "Fig. 1 [2]"가 된다.
        self.assertEqual(len(pages[1]["caption_blocks"]), 1)

    def test_does_not_duplicate_a_label_the_parser_already_found(self):
        """파서 캡션과 PDF 텍스트가 미세하게 달라도(마크다운 서식·합자) 같은 라벨이면 중복 아님."""
        pages = {
            1: self._page_stub(
                1,
                [
                    {
                        "id": "cap:p1:n0",
                        "page_number": 1,
                        "bbox": [40.0, 130.0, 500.0, 150.0],
                        "text": "**Fig. 1. Traversing challenging terrains.**",
                        "kind": "figure",
                        "order": 3,
                    }
                ],
            )
        }
        self.assertEqual(self._run([["Fig. 1. Traversing challenging terrains."]], pages), [])

    def test_does_not_recover_body_sentences(self):
        """본문 첫 문장이 라벨로 시작해도 복원 대상이 아니다 — 과추출로 되돌아간다."""
        pages = {1: self._page_stub(1)}
        self.assertEqual(
            self._run([["Fig. 3 shows some segmentation results using our map."]], pages), []
        )

    def test_recovers_table_captions_too(self):
        pages = {1: self._page_stub(1)}
        recovered = self._run([["Table 2. Ablation results."]], pages)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]["kind"], "table")

    def test_recovered_bbox_is_bottom_left_origin(self):
        """매니페스트 bbox 규약은 좌하단 원점이다 — PyMuPDF의 좌상단 좌표를 그대로 쓰면
        캡션이 페이지 반대편에 있는 것으로 잡혀 그림 영역 폴백이 위아래로 뒤집힌다."""
        pages = {1: self._page_stub(1)}
        recovered = self._run([["Fig. 1. A caption near the page bottom."]], pages)
        self.assertEqual(len(recovered), 1)
        x0, y_bottom, x1, y_top = recovered[0]["bbox"]
        self.assertLess(y_bottom, y_top)
        self.assertLess(x0, x1)
        # 텍스트를 PyMuPDF y=700(위에서부터)에 넣었으므로 좌하단 기준으로는 842-700 근처다.
        self.assertLess(y_top, 842.0 * 0.35)


class RomanTableLabelTests(unittest.TestCase):
    """IEEE 계열의 로마 숫자 표 라벨(`Table I`)을 라벨 규칙이 통째로 못 보던 문제.

    `TABLE_LABEL_PATTERN`이 digit-only라 `Table I`~`Table VIII`이 캡션으로 인정되지
    않았다. 그 결과 (a) 표 정답 기준이 그 논문에서 0이 되고, (b) 캡션에 기대는 하류
    로직(후보-캡션 연결, 캡션 폴백)이 통째로 무력화됐다.
    실측: 2017_COMST_OpticalComm은 원문 표 8개인데 캡션 인정 0개, 후보 9개 전부 무캡션.

    아래 문자열은 전부 실제 코퍼스에서 뽑았다.
    """

    ROMAN_CAPTIONS = [
        "Table I COMPARISON OF POWER AND MASS FOR GEOSTATIONARY EARTH ORBIT (GEO) AND LOW EARTH ORBIT (LEO)",
        "Table II WAVELENGTHS USED IN PRACTICAL FSO COMMUNICATION SYSTEMS",
        "Table III MOLECULAR ABSORPTION AT TYPICAL WAVELENGTHS [80]",
        "Table V TURBULENCE PROFILE MODELS FOR C2 n",
        "Table VIII EXAMPLE OF HAPS USED IN OPTICAL COMMUNICATION MISSIONS",
        "TABLE I",  # 2013_IEEETIP p10 — 라벨만 있고 캡션 본문이 다음 줄로 넘어간 형태
        "###### Table II WAVELENGTHS USED IN PRACTICAL FSO COMMUNICATION SYSTEMS",
    ]

    # 로마 숫자를 인정하면 새로 생기는 오탐 후보. 전부 표 라벨이 아니다.
    NOT_TABLE_LABELS = [
        "Table cells are merged in the header row.",
        "Table ILL-CONDITIONED CASES ARE EXCLUDED",  # ILL은 로마 숫자 형태가 아니다
        "Tables VI and VII are compared below.",  # "Tables"는 라벨이 아니다
        "Table D SHOWS NOTHING",  # D/L/C/M은 표 번호 범위 밖이다
        "Table iv shows the simulated transmittance.",  # 소문자는 로마로 인정하지 않는다
    ]

    def test_label_parsing_separates_pattern_from_validation(self):
        """라벨 토큰은 정규식이 통째로 잡고, 로마 숫자 여부는 형태 검증이 가른다.

        수정 전에는 `TABLE_LABEL_PATTERN`이 digit-only여서 "Table IV ..."가 아예 매칭되지
        않았다(이 클래스의 나머지 테스트가 구코드에서 전부 실패함을 확인한 뒤 고쳤다).
        정규식만 넓히고 검증을 두지 않으면 "Table ILL-CONDITIONED ..."가 통과한다.
        """
        from services.document_manifest import TABLE_LABEL_PATTERN, parse_table_label

        self.assertIsNotNone(TABLE_LABEL_PATTERN.match("Table ILL-CONDITIONED CASES"))
        self.assertIsNone(parse_table_label("Table ILL-CONDITIONED CASES"))

        self.assertEqual(parse_table_label("Table IV MODTRAN SIMULATED")[:3], ("roman", 4, ""))
        self.assertEqual(parse_table_label("Table 4. Ablation")[:3], ("arabic", 4, ""))
        self.assertEqual(parse_table_label("Table 2a. Ablation")[:3], ("arabic", 2, "a"))

    def test_roman_captions_are_recognized_as_tables(self):
        from services.document_manifest import _caption_kind

        for text in self.ROMAN_CAPTIONS:
            with self.subTest(text=text):
                self.assertEqual(_caption_kind(text), "table")

    def test_non_labels_are_rejected(self):
        from services.document_manifest import _caption_kind

        for text in self.NOT_TABLE_LABELS:
            with self.subTest(text=text):
                self.assertIsNone(_caption_kind(text))

    def test_roman_inline_mention_is_not_a_caption(self):
        """라벨 뒤 소문자 규칙(계약 8)은 로마에도 그대로 적용된다."""
        from services.document_manifest import _caption_kind

        self.assertIsNone(_caption_kind("Table IV shows the simulated transmittance."))
        self.assertIsNone(_caption_kind("Table VI summarizes the mapping."))

    def test_arabic_labels_still_work(self):
        from services.document_manifest import _caption_kind

        self.assertEqual(_caption_kind("**Table 2.** Ablation results"), "table")
        self.assertEqual(_caption_kind("Table 3. Ablation results."), "table")
        self.assertIsNone(_caption_kind("Table 3 summarizes the ablation results."))

    def test_table_number_keeps_roman_notation(self):
        """계약 6: 라벨 규칙만 넓히고 `_table_num`을 놔두면 캡션은 인정하면서 번호를
        못 읽어 `Table {index}`라는 가짜 이름이 붙는다."""
        from services.table_resolver import _table_num

        seen: set[str] = set()
        self.assertEqual(_table_num("Table VIII EXAMPLE OF HAPS USED", 28, 1, seen), "Table VIII")
        self.assertEqual(_table_num("Table I COMPARISON OF POWER", 3, 2, seen), "Table I")
        # 아라비아 표기는 그대로 유지된다.
        self.assertEqual(_table_num("**Table 2.** Ablation results", 4, 3, seen), "Table 2")

    def test_label_key_normalizes_notation(self):
        """캡션 복원 중복 판정은 표기법이 아니라 번호로 해야 한다 — 파서가 `Table 1`로,
        PDF 텍스트가 `Table I`로 같은 표를 가리키면 캡션이 둘이 되어 `Table 1 [2]`가 나온다."""
        from services.document_manifest import _caption_label_key

        self.assertEqual(
            _caption_label_key("Table I COMPARISON OF POWER"),
            _caption_label_key("Table 1. Comparison of power"),
        )
        self.assertNotEqual(
            _caption_label_key("Table II WAVELENGTHS USED"),
            _caption_label_key("Table 1. Comparison of power"),
        )


class TableCaptionGateTests(unittest.IsolatedAsyncioTestCase):
    """캡션 없는 표 후보가 그대로 산출물이 되던 문제.

    그림에는 "캡션 없는 후보는 버린다"(계약 7)가 있는데 표에는 대칭 규칙이 없었다.
    캡션이 없으면 `Table {fallback_index}`라는 가짜 번호가 붙어 그대로 나갔다.
    실측: 산출된 표 38개 중 28개가 무캡션이고, 크롭을 눈으로 보니 정체는 대부분
    **그래프의 범례 박스**였다 — 범례는 격자 구조라 pdfplumber가 표로 보지만
    캡션이 붙지 않는다(2014_Saliency p7의 PR 곡선 범례 9개, 2013_IEEETIP p8).

    라벨 중복제거도 함께 넣는다. 같은 표에 후보가 둘 붙으면 "Table 1"과 "Table 1 [2]"가
    함께 나오는데, 원인이 (a) 한 캡션에 후보 여럿(2022_SciRep 3건), (b) 같은 라벨의 캡션
    자체가 중복(2025_TurboQuant p20)으로 둘이라 라벨 기준이어야 함께 잡힌다.
    """

    GRID = [["cfg", "Gbps"], ["A", "1.2"], ["B", "3.4"]]

    def _candidate(self, index: int, caption_id: str | None, *, page: int = 1) -> dict:
        return {
            "id": f"tblcand:p{page}:n{index}",
            "page_number": page,
            "bbox": [30.0 + index, 300.0, 580.0, 590.0],
            "source_kind": "pdfplumber",
            "text_grid": self.GRID,
            "linked_caption_ids": [caption_id] if caption_id else [],
            "best_caption_id": caption_id,
            "has_meaningful_grid": True,
            "plausible_ruled_bbox": True,
            "had_irregular_rows": False,
        }

    def _manifest(self, candidates: list[dict], captions: list[dict]) -> dict:
        return {
            "pages": [{"page_number": 1, "page_size": {"width": 612.0, "height": 792.0}, "raster_path": None}],
            "captions": captions,
            "table_candidates": candidates,
            "audit": {"suspect_pages": []},
        }

    @staticmethod
    def _caption(caption_id: str, text: str) -> dict:
        return {"id": caption_id, "page_number": 1, "kind": "table", "bbox": [72.0, 600.0, 540.0, 620.0], "text": text}

    async def _resolve(self, manifest: dict) -> list[dict]:
        with tempfile.TemporaryDirectory() as tmp:
            result = await resolve_table_candidates(
                manifest, paper_dir=Path(tmp), resolver_version="resolver-v1"
            )
            return result["tables"]

    async def test_fixture_grid_would_otherwise_be_emitted(self):
        """픽스처가 조건을 재현하는지 먼저 단언한다 — 캡션만 붙이면 이 후보는 표가 된다.

        이 단언이 없으면 격자가 부실해서 안 나온 것을 "게이트가 걸렀다"로 오인할 수 있다.
        """
        tables = await self._resolve(
            self._manifest([self._candidate(0, "cap:p1:n0")], [self._caption("cap:p1:n0", "Table 1. Throughput.")])
        )
        self.assertEqual([table["table_num"] for table in tables], ["Table 1"])

    async def test_candidate_without_caption_is_dropped(self):
        tables = await self._resolve(self._manifest([self._candidate(0, None)], []))
        self.assertEqual(tables, [], "캡션 없는 후보가 표로 나갔다")

    async def test_no_table_files_are_written_for_dropped_candidates(self):
        """게이트는 파일 쓰기 앞에 있어야 한다 — 뒤에 있으면 고아 csv/html이 남는다."""
        manifest = self._manifest([self._candidate(0, None)], [])
        with tempfile.TemporaryDirectory() as tmp:
            paper_dir = Path(tmp)
            await resolve_table_candidates(manifest, paper_dir=paper_dir, resolver_version="resolver-v1")
            self.assertEqual(sorted((paper_dir / "tables").glob("*")), [])

    async def test_captioned_candidate_survives_alongside_uncaptioned(self):
        """무캡션 후보를 버려도 캡션 있는 진짜 표는 남아야 한다."""
        manifest = self._manifest(
            [self._candidate(0, None), self._candidate(1, "cap:p1:n0")],
            [self._caption("cap:p1:n0", "Table 2. Measured throughput.")],
        )
        tables = await self._resolve(manifest)
        self.assertEqual([table["table_num"] for table in tables], ["Table 2"])

    async def test_two_candidates_on_one_caption_yield_one_table(self):
        manifest = self._manifest(
            [self._candidate(0, "cap:p1:n0"), self._candidate(1, "cap:p1:n0")],
            [self._caption("cap:p1:n0", "Table 1. Mount parameters.")],
        )
        tables = await self._resolve(manifest)
        self.assertEqual([table["table_num"] for table in tables], ["Table 1"])

    async def test_duplicate_captions_with_same_label_yield_one_table(self):
        """2025_TurboQuant p20 — 같은 "Table 1" 캡션이 2개라 캡션 id 기준으로는 못 잡는다."""
        manifest = self._manifest(
            [self._candidate(0, "cap:p1:n0"), self._candidate(1, "cap:p1:n1")],
            [
                self._caption("cap:p1:n0", "Table 1: LongBench-V1 results."),
                self._caption("cap:p1:n1", "Table 1: LongBench-V1 results."),
            ],
        )
        tables = await self._resolve(manifest)
        self.assertEqual([table["table_num"] for table in tables], ["Table 1"])

    async def test_roman_and_arabic_labels_are_deduplicated_together(self):
        manifest = self._manifest(
            [self._candidate(0, "cap:p1:n0"), self._candidate(1, "cap:p1:n1")],
            [
                self._caption("cap:p1:n0", "Table I COMPARISON OF POWER"),
                self._caption("cap:p1:n1", "Table 1. Comparison of power"),
            ],
        )
        tables = await self._resolve(manifest)
        self.assertEqual(len(tables), 1)

    async def test_distinct_labels_are_kept(self):
        manifest = self._manifest(
            [self._candidate(0, "cap:p1:n0"), self._candidate(1, "cap:p1:n1")],
            [
                self._caption("cap:p1:n0", "Table 1. Mount parameters."),
                self._caption("cap:p1:n1", "Table 2. Link budget."),
            ],
        )
        tables = await self._resolve(manifest)
        self.assertEqual([table["table_num"] for table in tables], ["Table 1", "Table 2"])

    async def test_wipeout_is_logged(self):
        """전멸 시 경고를 남긴다(figure_resolver의 같은 경고와 동형, 계약 7)."""
        manifest = self._manifest([self._candidate(0, None)], [])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertLogs("services.table_resolver", level="WARNING") as captured:
                await resolve_table_candidates(manifest, paper_dir=Path(tmp), resolver_version="resolver-v1")
        self.assertTrue(any("표 0개" in message for message in captured.output))


class TableRepairCallScopeTests(unittest.IsolatedAsyncioTestCase):
    """폐기가 확정된 후보에 VLM 격자 복원을 호출하던 낭비.

    2단계가 `needs_vlm_repair` 후보 전부를 복원한 뒤, 3단계 캡션 게이트가 캡션 없는
    후보를 전량 버렸다. 즉 결과를 쓰지 않을 호출을 먼저 하고 있었다. 실측(2026-09-01,
    매니페스트 14편): VLM 호출 77건 중 55건(71%)이 이 경우였고, 그 정체는 캡션 게이트가
    걸러내는 바로 그 대상, 곧 그래프의 범례 박스였다.

    정확도 지표에는 드러나지 않는다 — 버려질 결과였으므로 산출물이 같다. 드러나는 곳은
    호출 수와 비용이다(원장 기준 논문 12편에 90회, 그중 약 71%가 낭비).
    """

    EMPTY_GRID: list[list[str]] = []

    def _candidate(self, index: int, caption_id: str | None) -> dict:
        # 격자가 비어 있고 ruled bbox가 있는 후보 = `ruled_bbox_without_grid` 사유가 붙어
        # 복원 대상이 된다. 캡션이 붙으면 `caption_linked_but_grid_weak`도 함께 붙는다.
        return {
            "id": f"tblcand:p1:n{index}",
            "page_number": 1,
            "bbox": [30.0 + index, 300.0, 580.0, 590.0],
            "source_kind": "pdfplumber",
            "text_grid": self.EMPTY_GRID,
            "linked_caption_ids": [caption_id] if caption_id else [],
            "best_caption_id": caption_id,
            "has_meaningful_grid": False,
            "plausible_ruled_bbox": True,
            "had_irregular_rows": False,
        }

    def _manifest(self, candidates: list[dict], captions: list[dict]) -> dict:
        return {
            "pages": [{"page_number": 1, "page_size": {"width": 612.0, "height": 792.0}, "raster_path": None}],
            "captions": captions,
            "table_candidates": candidates,
            "audit": {"suspect_pages": []},
        }

    async def _repair_calls(self, manifest: dict) -> int:
        repaired = AsyncMock(return_value=([["a", "b"], ["1", "2"]], MODEL_FLASH_HQ, 0.9))
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(table_resolver_module, "_repair_with_vlm", repaired):
                await resolve_table_candidates(
                    manifest, paper_dir=Path(tmp), resolver_version="resolver-v1"
                )
        return repaired.await_count

    async def test_uncaptioned_candidate_is_not_sent_to_the_vlm(self):
        calls = await self._repair_calls(self._manifest([self._candidate(0, None)], []))
        self.assertEqual(calls, 0, "캡션 게이트가 버릴 후보에 복원을 호출했다")

    async def test_captioned_candidate_is_still_sent_to_the_vlm(self):
        """낭비만 걷어내야 한다 — 결과를 실제로 쓰는 호출까지 잃으면 격자 품질이 떨어진다."""
        manifest = self._manifest(
            [self._candidate(0, "cap:p1:n0")],
            [{"id": "cap:p1:n0", "page_number": 1, "kind": "table",
              "bbox": [72.0, 600.0, 540.0, 620.0], "text": "Table 1. Throughput."}],
        )
        self.assertEqual(await self._repair_calls(manifest), 1)

    async def test_caption_id_without_caption_text_is_not_sent(self):
        """캡션 id는 있는데 캡션 객체가 없는 경우도 게이트가 버린다 — 기준을 게이트와 맞춘다."""
        calls = await self._repair_calls(self._manifest([self._candidate(0, "cap:missing")], []))
        self.assertEqual(calls, 0)
