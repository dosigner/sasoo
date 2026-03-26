from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import fitz
from PIL import Image

subfigure_detector_module = types.ModuleType("services.subfigure_detector")


class _StubSubFigureDetector:
    async def detect_subfigures(self, *args, **kwargs):
        return types.SimpleNamespace(has_subfigures=False, confidence=0.0)

    async def extract_subfigures(self, *args, **kwargs):
        return []


subfigure_detector_module.SubFigureDetector = _StubSubFigureDetector
sys.modules.setdefault("services.subfigure_detector", subfigure_detector_module)

from services.odl_parser import (
    OdlRuntimeError,
    PYMUPDF_TEXT_ENGINE,
    _build_manifest,
    _render_bbox_crop,
    ensure_java_runtime,
    get_artifact_refresh_error,
    get_pdf_signature,
    paper_artifacts_are_current,
    paper_text_is_current,
    paper_visuals_are_current,
    schedule_paper_artifacts_refresh,
    TEXT_CACHE_FILENAME,
    TEXT_CACHE_META_FILENAME,
    MANIFEST_FILENAME,
    ensure_paper_artifacts,
    ensure_parsed_artifacts,
    ensure_text_artifacts,
    figure_row_to_api_dict,
    sync_figures_for_paper,
    sync_tables_for_paper,
    table_row_to_api_dict,
)


class OdlParserUnitTests(unittest.TestCase):
    def test_build_manifest_prefers_caption_targets_and_list_item_captions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            pdf_path = paper_dir / "paper.pdf"
            doc = fitz.open()
            doc.new_page(width=300, height=400)
            doc.new_page(width=300, height=400)
            doc.save(pdf_path)
            doc.close()

            root = {
                "title": "Sample Paper",
                "author": "Jane Doe",
                "number of pages": 2,
                "kids": [
                    {
                        "type": "table",
                        "id": 301,
                        "page number": 1,
                        "bounding box": [10, 80, 140, 240],
                    },
                    {
                        "type": "caption",
                        "id": 201,
                        "page number": 1,
                        "linked content id": 301,
                        "bounding box": [10, 40, 180, 70],
                        "content": "Figure 3. Table-linked caption",
                    },
                    {
                        "type": "image",
                        "id": 102,
                        "page number": 1,
                        "bounding box": [150, 80, 280, 240],
                    },
                    {
                        "type": "caption",
                        "id": 202,
                        "page number": 1,
                        "bounding box": [150, 40, 280, 70],
                        "content": "Figure 4. Nearby caption",
                    },
                    {
                        "type": "image",
                        "id": 103,
                        "page number": 2,
                        "bounding box": [0, 40, 300, 360],
                    },
                    {
                        "type": "image",
                        "id": 104,
                        "page number": 2,
                        "bounding box": [0, 0, 300, 30],
                    },
                    {
                        "type": "list",
                        "page number": 2,
                        "list items": [
                            {
                                "type": "list item",
                                "page number": 2,
                                "content": "Figure 5. List-item caption",
                            }
                        ],
                    },
                ],
            }

            fake_outputs = [
                (str(paper_dir / "figures" / "Fig_3.png"), 600, 400),
                (str(paper_dir / "figures" / "Fig_4.png"), 500, 320),
                (str(paper_dir / "figures" / "Fig_5.png"), 900, 600),
            ]

            with patch("services.odl_parser._copy_or_render_figure", side_effect=fake_outputs):
                manifest = _build_manifest(
                    pdf_path=pdf_path,
                    paper_dir=paper_dir,
                    output_dir=paper_dir,
                    root=root,
                    markdown_text="# Sample Paper",
                    actual_engine="odl-java",
                    requested_mode="java",
                )

            self.assertEqual(manifest["metadata"]["title"], "Sample Paper")
            self.assertEqual(len(manifest["figures"]), 3)
            self.assertEqual(manifest["figures"][0]["figure_num"], "Fig. 3")
            self.assertEqual(manifest["figures"][0]["caption"], "Figure 3. Table-linked caption")
            self.assertEqual(manifest["figures"][0]["bbox"], [10.0, 80.0, 140.0, 240.0])
            self.assertEqual(manifest["figures"][1]["figure_num"], "Fig. 4")
            self.assertEqual(manifest["figures"][1]["caption"], "Figure 4. Nearby caption")
            self.assertEqual(manifest["figures"][1]["bbox"], [150.0, 80.0, 280.0, 240.0])
            self.assertEqual(manifest["figures"][2]["figure_num"], "Fig. 5")
            self.assertEqual(manifest["figures"][2]["caption"], "Figure 5. List-item caption")
            self.assertEqual(manifest["figures"][2]["page_number"], 2)

    def test_render_bbox_crop_uses_odl_pdf_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            pdf_path = tmp_path / "crop.pdf"
            out_path = tmp_path / "figures" / "crop.png"

            doc = fitz.open()
            page = doc.new_page(width=300, height=400)
            page.draw_rect(fitz.Rect(50, 50, 200, 250), color=(1, 0, 0), fill=(1, 0.8, 0.8))
            doc.save(pdf_path)
            doc.close()

            # ODL bbox order is [left, bottom, right, top] in PDF coordinates.
            rendered_path, width, height = _render_bbox_crop(
                pdf_path=pdf_path,
                page_number=1,
                bbox=[50, 150, 200, 350],
                out_path=out_path,
            )

            self.assertTrue(Path(rendered_path).exists())
            self.assertGreater(width, 0)
            self.assertGreater(height, 0)

    def test_figure_row_to_api_dict_deserializes_bbox(self) -> None:
        payload = figure_row_to_api_dict(
            {
                "id": 1,
                "paper_id": 5,
                "figure_num": "Fig. 1",
                "bbox_json": "[1, 2, 3, 4]",
            }
        )
        self.assertEqual(payload["bbox"], [1, 2, 3, 4])

    def test_figure_row_to_api_dict_converts_library_absolute_path_to_static_url(self) -> None:
        with patch("services.odl_parser.get_library_root", return_value=Path("/Users/alice/Papers")):
            payload = figure_row_to_api_dict(
                {
                    "id": 1,
                    "paper_id": 5,
                    "file_path": "/Users/alice/Papers/paper-123/figures/Fig 1.png",
                }
            )

        self.assertEqual(
            payload["file_path"],
            "/static/library/paper-123/figures/Fig%201.png",
        )

    def test_artifact_current_check_uses_pdf_signature_without_hashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            pdf_path = paper_dir / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nsignature test\n")
            signature = get_pdf_signature(pdf_path)

            figures_dir = paper_dir / "figures"
            figures_dir.mkdir(parents=True, exist_ok=True)
            (figures_dir / "Fig_1.png").write_bytes(b"png")
            (paper_dir / "paper.md").write_text("# sample", encoding="utf-8")
            (paper_dir / "paper.json").write_text("{}", encoding="utf-8")
            (paper_dir / TEXT_CACHE_FILENAME).write_text("cached text", encoding="utf-8")
            (paper_dir / TEXT_CACHE_META_FILENAME).write_text(
                json.dumps(
                    {
                        "pdf_hash": "legacy-hash",
                        "pdf_mtime_ns": signature["pdf_mtime_ns"],
                        "pdf_size": signature["pdf_size"],
                        "parser_version": "odl-v2",
                        "requested_mode": "java",
                        "extraction_pipeline_version": "legacy",
                        "resolver_version": "legacy",
                        "engine": "odl-java",
                    }
                ),
                encoding="utf-8",
            )
            (paper_dir / MANIFEST_FILENAME).write_text(
                json.dumps(
                    {
                        "parser_version": "odl-v2",
                        "requested_mode": "java",
                        "extraction_pipeline_version": "legacy",
                        "resolver_version": "legacy",
                        "engine": "odl-java",
                        "pdf_hash": "legacy-hash",
                        "pdf_mtime_ns": signature["pdf_mtime_ns"],
                        "pdf_size": signature["pdf_size"],
                        "markdown_file": "paper.md",
                        "json_file": "paper.json",
                        "full_text": "cached text",
                        "visual_artifacts_ready": True,
                        "pages": [],
                        "figures": [{"file_path": "figures/Fig_1.png"}],
                    }
                ),
                encoding="utf-8",
            )

            with patch("services.odl_parser._pdf_hash", side_effect=AssertionError("hash should not be recomputed")):
                self.assertFalse(paper_artifacts_are_current(paper_dir))
                self.assertTrue(
                    paper_artifacts_are_current(
                        paper_dir,
                        extraction_pipeline_version="legacy",
                    )
                )

    def test_artifact_current_check_rejects_legacy_meta_without_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            pdf_path = paper_dir / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nlegacy meta test\n")

            figures_dir = paper_dir / "figures"
            figures_dir.mkdir(parents=True, exist_ok=True)
            (figures_dir / "Fig_1.png").write_bytes(b"png")
            (paper_dir / TEXT_CACHE_FILENAME).write_text("cached text", encoding="utf-8")
            (paper_dir / TEXT_CACHE_META_FILENAME).write_text(
                json.dumps(
                    {
                        "pdf_hash": "legacy-hash",
                        "parser_version": "odl-v2",
                        "engine": "odl-java",
                    }
                ),
                encoding="utf-8",
            )
            (paper_dir / MANIFEST_FILENAME).write_text(
                json.dumps(
                    {
                        "parser_version": "odl-v2",
                        "requested_mode": "java",
                        "engine": "odl-java",
                        "pdf_hash": "legacy-hash",
                        "figures": [{"file_path": "figures/Fig_1.png"}],
                    }
                ),
                encoding="utf-8",
            )

            self.assertFalse(paper_artifacts_are_current(paper_dir))

    def test_text_and_visual_readiness_are_split_when_figure_asset_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            pdf_path = paper_dir / "paper.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\nsplit readiness test\n")
            signature = get_pdf_signature(pdf_path)

            figures_dir = paper_dir / "figures"
            figures_dir.mkdir(parents=True, exist_ok=True)
            figure_path = figures_dir / "Fig_1.png"
            figure_path.write_bytes(b"png")
            (paper_dir / "paper.md").write_text("# sample", encoding="utf-8")
            (paper_dir / "paper.json").write_text("{}", encoding="utf-8")
            (paper_dir / TEXT_CACHE_FILENAME).write_text("cached text", encoding="utf-8")
            (paper_dir / TEXT_CACHE_META_FILENAME).write_text(
                json.dumps(
                    {
                        "pdf_mtime_ns": signature["pdf_mtime_ns"],
                        "pdf_size": signature["pdf_size"],
                    }
                ),
                encoding="utf-8",
            )
            (paper_dir / MANIFEST_FILENAME).write_text(
                json.dumps(
                    {
                        "parser_version": "odl-v2",
                        "requested_mode": "java",
                        "extraction_pipeline_version": "legacy",
                        "resolver_version": "legacy",
                        "engine": "odl-java",
                        "pdf_mtime_ns": signature["pdf_mtime_ns"],
                        "pdf_size": signature["pdf_size"],
                        "pdf_file": "paper.pdf",
                        "markdown_file": "paper.md",
                        "json_file": "paper.json",
                        "full_text": "cached text",
                        "visual_artifacts_ready": True,
                        "figures": [{"file_path": "figures/Fig_1.png"}],
                        "tables": [],
                        "pages": [],
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(paper_text_is_current(paper_dir, extraction_pipeline_version="legacy"))
            self.assertTrue(paper_visuals_are_current(paper_dir, extraction_pipeline_version="legacy"))
            self.assertTrue(paper_artifacts_are_current(paper_dir, extraction_pipeline_version="legacy"))

            figure_path.unlink()

            self.assertTrue(paper_text_is_current(paper_dir, extraction_pipeline_version="legacy"))
            self.assertFalse(paper_visuals_are_current(paper_dir, extraction_pipeline_version="legacy"))
            self.assertFalse(paper_artifacts_are_current(paper_dir, extraction_pipeline_version="legacy"))

    def test_ensure_text_artifacts_falls_back_to_pymupdf_when_odl_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            pdf_path = paper_dir / "paper.pdf"

            doc = fitz.open()
            page = doc.new_page(width=300, height=400)
            page.insert_text((72, 72), "Fallback text extraction works.", fontsize=12)
            doc.save(pdf_path)
            doc.close()

            with patch(
                "services.odl_parser._run_convert",
                side_effect=OdlRuntimeError("Java runtime was not found."),
            ):
                manifest = ensure_text_artifacts(paper_dir, mode="java", force=True)

            self.assertEqual(manifest["engine"], PYMUPDF_TEXT_ENGINE)
            self.assertFalse(manifest["visual_artifacts_ready"])
            self.assertIn("Fallback text extraction works.", manifest["full_text"])
            self.assertTrue((paper_dir / MANIFEST_FILENAME).exists())
            self.assertTrue((paper_dir / TEXT_CACHE_FILENAME).exists())
            self.assertTrue((paper_dir / TEXT_CACHE_META_FILENAME).exists())
            self.assertTrue((paper_dir / "paper.md").exists())
            self.assertTrue((paper_dir / "paper.json").exists())
            self.assertTrue(paper_text_is_current(paper_dir))
            self.assertFalse(paper_visuals_are_current(paper_dir))

    def test_table_row_to_api_dict_deserializes_bbox(self) -> None:
        payload = table_row_to_api_dict(
            {
                "id": 2,
                "paper_id": 5,
                "table_num": "Table 1",
                "bbox_json": "[5, 6, 7, 8]",
            }
        )
        self.assertEqual(payload["bbox"], [5, 6, 7, 8])

    def test_table_row_to_api_dict_converts_library_absolute_paths_to_static_urls(self) -> None:
        with patch("services.odl_parser.get_library_root", return_value=Path("/Users/alice/Papers")):
            payload = table_row_to_api_dict(
                {
                    "id": 2,
                    "paper_id": 5,
                    "csv_path": "/Users/alice/Papers/paper-123/tables/Table 1.csv",
                    "html_path": "/Users/alice/Papers/paper-123/tables/Table 1.html",
                }
            )

        self.assertEqual(
            payload["csv_path"],
            "/static/library/paper-123/tables/Table%201.csv",
        )
        self.assertEqual(
            payload["html_path"],
            "/static/library/paper-123/tables/Table%201.html",
        )

    def test_table_row_to_api_dict_converts_repair_fields(self) -> None:
        payload = table_row_to_api_dict(
            {
                "id": 2,
                "paper_id": 5,
                "table_num": "Table 1",
                "repair_attempted": 1,
                "repair_reason": "irregular_row_widths",
                "repair_confidence": 0.31,
                "review_required": 0,
            }
        )

        self.assertTrue(payload["repair_attempted"])
        self.assertEqual(payload["repair_reason"], "irregular_row_widths")
        self.assertEqual(payload["repair_confidence"], 0.31)
        self.assertFalse(payload["review_required"])


class SyncFiguresTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_figures_preserves_existing_ai_fields(self) -> None:
        class FakeDb:
            def __init__(self) -> None:
                self.calls: list[tuple[str, tuple]] = []
                self.committed = False

            async def execute(self, query: str, params: tuple = ()) -> None:
                self.calls.append((query, params))

            async def commit(self) -> None:
                self.committed = True

        fake_db = FakeDb()
        manifest = {
            "figures": [
                {
                    "figure_num": "Fig. 1",
                    "caption": "Figure 1. Updated",
                    "file_path": "figures/Fig_1.png",
                    "quality": "high",
                    "page_number": 2,
                    "bbox": [10, 20, 30, 40],
                    "extraction_engine": "odl-java",
                    "confidence": 0.91,
                    "classifier_label": "figure",
                    "classifier_model": "heuristic",
                    "is_composite": True,
                    "resolver_version": "resolver-v1",
                    "extraction_status": "resolved",
                }
            ]
        }

        with (
            patch(
                "services.odl_parser.fetch_all",
                AsyncMock(
                    side_effect=[
                        [
                            {
                                "id": 99,
                                "figure_num": "Fig. 1",
                                "ai_analysis": "keep me",
                                "detailed_explanation": "keep me too",
                            },
                            {
                                "id": 100,
                                "figure_num": "Fig. old",
                                "ai_analysis": None,
                                "detailed_explanation": None,
                            },
                        ],
                        [
                            {
                                "id": 99,
                                "figure_num": "Fig. 1",
                            }
                        ],
                    ],
                ),
            ),
            patch("services.odl_parser.get_db", AsyncMock(return_value=fake_db)),
        ):
            await sync_figures_for_paper(7, Path("/tmp/paper"), manifest=manifest)

        update_query = next(query for query, _ in fake_db.calls if "UPDATE figures" in query)
        update_params = next(params for query, params in fake_db.calls if "UPDATE figures" in query)
        delete_params = next(params for query, params in fake_db.calls if "DELETE FROM figures" in query)

        self.assertIn("bbox_json", update_query)
        self.assertEqual(update_params[0], "Fig. 1")
        self.assertEqual(json.loads(update_params[5]), [10, 20, 30, 40])
        self.assertEqual(update_params[6], "odl-java")
        self.assertEqual(update_params[7], 0.91)
        self.assertEqual(update_params[8], "figure")
        self.assertEqual(update_params[10], 1)
        self.assertEqual(update_params[11], "resolver-v1")
        self.assertEqual(delete_params, (100,))
        self.assertTrue(fake_db.committed)

    async def test_sync_tables_upserts_resolved_tables(self) -> None:
        class FakeDb:
            def __init__(self) -> None:
                self.calls: list[tuple[str, tuple]] = []
                self.committed = False

            async def execute(self, query: str, params: tuple = ()) -> None:
                self.calls.append((query, params))

            async def commit(self) -> None:
                self.committed = True

        fake_db = FakeDb()
        manifest = {
            "tables": [
                {
                    "table_num": "Table 1",
                    "caption": "Table 1. Caption",
                    "page_number": 3,
                    "bbox": [11, 12, 13, 14],
                    "csv_path": "tables/Table_1.csv",
                    "html_path": "tables/Table_1.html",
                    "markdown_text": "| A |\n| --- |\n| 1 |",
                    "confidence": 0.87,
                    "parse_method": "hybrid",
                    "classifier_model": "heuristic",
                    "resolver_version": "resolver-v1",
                    "extraction_status": "resolved",
                }
            ]
        }
        with (
            patch(
                "services.odl_parser.fetch_all",
                AsyncMock(
                    return_value=[
                        {"id": 12, "table_num": "Table 1"},
                        {"id": 13, "table_num": "Table old"},
                    ]
                ),
            ),
            patch("services.odl_parser.get_db", AsyncMock(return_value=fake_db)),
        ):
            await sync_tables_for_paper(7, Path("/tmp/paper"), manifest=manifest)

        update_query = next(query for query, _ in fake_db.calls if "UPDATE tables" in query)
        update_params = next(params for query, params in fake_db.calls if "UPDATE tables" in query)
        delete_params = next(params for query, params in fake_db.calls if "DELETE FROM tables" in query)

        self.assertIn("resolver_version", update_query)
        self.assertEqual(update_params[0], "Table 1")
        self.assertEqual(json.loads(update_params[3]), [11, 12, 13, 14])
        self.assertEqual(update_params[7], 0.87)
        self.assertEqual(update_params[9], "heuristic")
        self.assertEqual(delete_params, (13,))
        self.assertTrue(fake_db.committed)

    async def test_sync_figures_matches_existing_rows_by_page_and_bbox_when_number_changes(self) -> None:
        class FakeDb:
            def __init__(self) -> None:
                self.calls: list[tuple[str, tuple]] = []
                self.committed = False

            async def execute(self, query: str, params: tuple = ()) -> None:
                self.calls.append((query, params))

            async def commit(self) -> None:
                self.committed = True

        fake_db = FakeDb()
        manifest = {
            "figures": [
                {
                    "figure_num": "Fig. 2",
                    "caption": "Figure 2. Renumbered",
                    "file_path": "figures/Fig_2.png",
                    "quality": "high",
                    "page_number": 2,
                    "bbox": [10, 20, 30, 40],
                    "extraction_engine": "odl-java",
                    "confidence": 0.95,
                    "classifier_label": "figure",
                    "classifier_model": "heuristic",
                    "is_composite": False,
                    "resolver_version": "resolver-v1",
                    "extraction_status": "resolved",
                }
            ]
        }

        with (
            patch(
                "services.odl_parser.fetch_all",
                AsyncMock(
                    side_effect=[
                        [
                            {
                                "id": 77,
                                "figure_num": "Fig. old",
                                "page_number": 2,
                                "bbox_json": "[10, 20, 30, 40]",
                                "ai_analysis": "keep",
                                "detailed_explanation": "keep",
                            }
                        ],
                        [
                            {
                                "id": 77,
                                "figure_num": "Fig. 2",
                            }
                        ],
                    ],
                ),
            ),
            patch("services.odl_parser.get_db", AsyncMock(return_value=fake_db)),
        ):
            await sync_figures_for_paper(7, Path("/tmp/paper"), manifest=manifest)

        update_params = next(params for query, params in fake_db.calls if "UPDATE figures" in query)
        self.assertEqual(update_params[-1], 77)
        self.assertFalse(any("DELETE FROM figures" in query for query, _ in fake_db.calls))
        self.assertTrue(fake_db.committed)

    async def test_ensure_paper_artifacts_deduplicates_inflight_requests(self) -> None:
        manifest = {"figures": []}
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        async def fake_ensure(*args, **kwargs):
            first_started.set()
            await release_first.wait()
            return manifest

        with (
            patch(
                "services.odl_parser.ensure_visual_artifacts_async",
                AsyncMock(side_effect=fake_ensure),
            ) as ensure_mock,
            patch(
                "services.odl_parser.sync_figures_for_paper",
                AsyncMock(return_value=[]),
            ) as sync_mock,
            patch(
                "services.odl_parser.sync_tables_for_paper",
                AsyncMock(return_value=[]),
            ) as sync_tables_mock,
        ):
            task_a = asyncio.create_task(ensure_paper_artifacts(7, Path("/tmp/paper")))
            await first_started.wait()
            task_b = asyncio.create_task(ensure_paper_artifacts(7, Path("/tmp/paper")))
            release_first.set()

            result_a, result_b = await asyncio.gather(task_a, task_b)

        self.assertIs(result_a, manifest)
        self.assertIs(result_b, manifest)
        self.assertEqual(ensure_mock.await_count, 1)
        sync_mock.assert_awaited_once_with(7, Path("/tmp/paper"), manifest=manifest)
        sync_tables_mock.assert_awaited_once_with(7, Path("/tmp/paper"), manifest=manifest)

    async def test_schedule_paper_artifacts_refresh_records_background_failures(self) -> None:
        with (
            patch(
                "services.odl_parser.ensure_visual_artifacts_async",
                AsyncMock(side_effect=OdlRuntimeError("Java runtime was not found.")),
            ),
            patch(
                "services.odl_parser.sync_figures_for_paper",
                AsyncMock(return_value=[]),
            ),
            patch(
                "services.odl_parser.sync_tables_for_paper",
                AsyncMock(return_value=[]),
            ),
        ):
            await schedule_paper_artifacts_refresh(9, Path("/tmp/paper"))
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        self.assertEqual(
            get_artifact_refresh_error(9),
            (503, "Java runtime was not found."),
        )


class OdlParserIntegrationTests(unittest.TestCase):
    def test_end_to_end_java_mode_writes_manifest_and_cache(self) -> None:
        try:
            ensure_java_runtime()
            importlib.import_module("opendataloader_pdf")
        except Exception as exc:
            self.skipTest(f"Java/OpenDataLoader runtime unavailable: {exc}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = Path(tmp_dir)
            pdf_path = paper_dir / "integration.pdf"
            image_path = paper_dir / "figure.png"

            Image.new("RGB", (320, 200), color=(64, 128, 220)).save(image_path)

            doc = fitz.open()
            page = doc.new_page(width=595, height=842)
            page.insert_text((72, 72), "OpenDataLoader integration smoke test", fontsize=18)
            page.insert_text((72, 108), "This PDF is generated during the test suite.", fontsize=12)
            page.insert_image(fitz.Rect(72, 160, 392, 360), filename=str(image_path))
            page.insert_text((72, 390), "Figure 1. Synthetic test figure", fontsize=12)
            doc.save(pdf_path)
            doc.close()

            manifest = ensure_parsed_artifacts(paper_dir, mode="java", force=True)

            self.assertEqual(manifest["engine"], "odl-java")
            self.assertEqual(manifest["requested_mode"], "java")
            self.assertTrue((paper_dir / MANIFEST_FILENAME).exists())
            self.assertTrue((paper_dir / TEXT_CACHE_FILENAME).exists())
            self.assertTrue((paper_dir / TEXT_CACHE_META_FILENAME).exists())
            self.assertTrue((paper_dir / f"{pdf_path.stem}.md").exists())
            self.assertTrue((paper_dir / f"{pdf_path.stem}.json").exists())
            self.assertIn("OpenDataLoader integration smoke test", manifest["full_text"])
            self.assertEqual(len(manifest["pdf_hash"]), 16)
            self.assertIn("pdf_mtime_ns", manifest)
            self.assertIn("pdf_size", manifest)
            self.assertGreaterEqual(len(manifest.get("figures", [])), 0)


if __name__ == "__main__":
    unittest.main()
