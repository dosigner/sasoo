from __future__ import annotations

import base64
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
from services.table_resolver import _repair_with_vlm, resolve_table_candidates
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
