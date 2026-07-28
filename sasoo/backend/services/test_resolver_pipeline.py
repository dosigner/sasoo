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
            self.assertEqual(kwargs["thinking_level"], "minimal")
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
