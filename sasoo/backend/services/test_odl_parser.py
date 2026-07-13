from __future__ import annotations

import asyncio
import contextlib
import copy
import importlib
import json
import os
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
    GEMINI_ENGINE_NAME,
    OdlParserError,
    OdlRuntimeError,
    PYMUPDF_TEXT_ENGINE,
    _resolve_stage_engine,
    _run_convert,
    ensure_java_runtime,
    ensure_visual_artifacts,
    get_odl_reference_text,
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
                        "pdf_hash": "cached-hash",
                        "pdf_mtime_ns": signature["pdf_mtime_ns"],
                        "pdf_size": signature["pdf_size"],
                        "parser_version": "odl-v3",
                        "requested_mode": "java",
                        "extraction_pipeline_version": "resolver_v1",
                        "resolver_version": "resolver-v1",
                        "engine": "odl-java",
                    }
                ),
                encoding="utf-8",
            )
            (paper_dir / MANIFEST_FILENAME).write_text(
                json.dumps(
                    {
                        "parser_version": "odl-v3",
                        "requested_mode": "java",
                        "extraction_pipeline_version": "resolver_v1",
                        "resolver_version": "resolver-v1",
                        "engine": "odl-java",
                        "pdf_hash": "cached-hash",
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
                self.assertTrue(paper_artifacts_are_current(paper_dir))

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
                        "parser_version": "odl-v3",
                        "requested_mode": "java",
                        "extraction_pipeline_version": "resolver_v1",
                        "resolver_version": "resolver-v1",
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

            self.assertTrue(paper_text_is_current(paper_dir))
            self.assertTrue(paper_visuals_are_current(paper_dir))
            self.assertTrue(paper_artifacts_are_current(paper_dir))

            figure_path.unlink()

            self.assertTrue(paper_text_is_current(paper_dir))
            self.assertFalse(paper_visuals_are_current(paper_dir))
            self.assertFalse(paper_artifacts_are_current(paper_dir))

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


@contextlib.contextmanager
def _parser_env(**overrides):
    """파서 관련 env(SASOO_PDF_*, GEMINI_API_KEY)만 격리한다. 값이 None이면 미설정."""
    keys = [
        "SASOO_PDF_ENGINE",
        "SASOO_PDF_TEXT_ENGINE",
        "SASOO_PDF_VISUAL_ENGINE",
        "GEMINI_API_KEY",
    ]
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ.pop(k, None)
    for k, v in overrides.items():
        if v is not None:
            os.environ[k] = v
    try:
        yield
    finally:
        for k in keys:
            os.environ.pop(k, None)
            if saved[k] is not None:
                os.environ[k] = saved[k]


ODL_TEXT = "ODL VERBATIM alpha beta grant 12345 J. Doe"
GEMINI_TEXT = "GEMINI PROMOTED body with $x^2$ and | a | b | table"


def _stage_convert_side_effect(*, visual_fail: bool = False):
    """스테이지별로 다른 (root, markdown, engine)을 돌려주는 _run_convert 대역.

    - text 스테이지(또는 engine='odl' 폴백 재시도): ODL 텍스트 + engine 'odl-java'
    - visual 스테이지(engine 미지정): gemini 텍스트 + engine 'gemini' (visual_fail이면 예외)
    """

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

    def _side(pdf_path, output_dir, figures_dir, mode, engine=None, stage="text"):
        if stage == "visual" and engine is None:
            if visual_fail:
                raise OdlParserError("simulated gemini visual failure")
            return copy.deepcopy(_root(GEMINI_TEXT)), GEMINI_TEXT, GEMINI_ENGINE_NAME
        return copy.deepcopy(_root(ODL_TEXT)), ODL_TEXT, "odl-java"

    return _side


class StageEngineResolutionTests(unittest.TestCase):
    def test_defaults_text_odl_visual_gemini(self) -> None:
        with _parser_env():
            self.assertEqual(_resolve_stage_engine("text"), "odl")
            self.assertEqual(_resolve_stage_engine("visual"), "gemini")

    def test_stage_env_overrides_defaults(self) -> None:
        with _parser_env(SASOO_PDF_TEXT_ENGINE="gemini", SASOO_PDF_VISUAL_ENGINE="odl"):
            self.assertEqual(_resolve_stage_engine("text"), "gemini")
            self.assertEqual(_resolve_stage_engine("visual"), "odl")

    def test_global_env_overrides_both_stages(self) -> None:
        with _parser_env(SASOO_PDF_ENGINE="gemini", SASOO_PDF_VISUAL_ENGINE="odl"):
            # 전역이 스테이지 env보다 우선 — 하위호환.
            self.assertEqual(_resolve_stage_engine("text"), "gemini")
            self.assertEqual(_resolve_stage_engine("visual"), "gemini")
        with _parser_env(SASOO_PDF_ENGINE="odl", SASOO_PDF_VISUAL_ENGINE="gemini"):
            self.assertEqual(_resolve_stage_engine("visual"), "odl")

    def test_explicit_override_beats_env(self) -> None:
        with _parser_env(SASOO_PDF_ENGINE="gemini"):
            self.assertEqual(_resolve_stage_engine("visual", "odl"), "odl")

    def test_invalid_value_falls_back_to_stage_default(self) -> None:
        with _parser_env(SASOO_PDF_TEXT_ENGINE="bogus", SASOO_PDF_VISUAL_ENGINE="bogus"):
            self.assertEqual(_resolve_stage_engine("text"), "odl")
            self.assertEqual(_resolve_stage_engine("visual"), "gemini")


class RunConvertKeyGuardTests(unittest.TestCase):
    def _dispatch(self, stage: str):
        with patch(
            "services.odl_parser._run_convert_gemini",
            return_value=({}, "md", "gemini"),
        ) as gemini_mock, patch(
            "services.odl_parser._run_convert_odl",
            return_value=({}, "md", "odl-java"),
        ) as odl_mock:
            _, _, engine = _run_convert(Path("x.pdf"), Path("."), Path("."), "java", stage=stage)
        return engine, gemini_mock, odl_mock

    def test_visual_uses_gemini_when_key_present(self) -> None:
        with _parser_env(GEMINI_API_KEY="k"):
            engine, gemini_mock, odl_mock = self._dispatch("visual")
        self.assertEqual(engine, "gemini")
        gemini_mock.assert_called_once()
        odl_mock.assert_not_called()

    def test_visual_downgrades_to_odl_without_key(self) -> None:
        with _parser_env():  # GEMINI_API_KEY 미설정
            engine, gemini_mock, odl_mock = self._dispatch("visual")
        self.assertEqual(engine, "odl-java")
        gemini_mock.assert_not_called()
        odl_mock.assert_called_once()

    def test_text_stage_defaults_to_odl(self) -> None:
        with _parser_env(GEMINI_API_KEY="k"):
            engine, gemini_mock, odl_mock = self._dispatch("text")
        self.assertEqual(engine, "odl-java")
        odl_mock.assert_called_once()
        gemini_mock.assert_not_called()


class VisualPromotionTests(unittest.TestCase):
    def _make_paper(self, tmp_dir: str) -> Path:
        paper_dir = Path(tmp_dir)
        pdf_path = paper_dir / "paper.pdf"
        doc = fitz.open()
        page = doc.new_page(width=300, height=400)
        page.insert_text((72, 72), "seed", fontsize=12)
        doc.save(pdf_path)
        doc.close()
        return paper_dir

    def test_gemini_visual_promotes_text_and_preserves_odl_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = self._make_paper(tmp_dir)
            # 분석이 이미 만들어 둔 stale 사이드카(승격 시 무효화되어야 함).
            sidecar = paper_dir / ".document_context.json"
            sidecar.write_text("{\"stale\": true}", encoding="utf-8")

            with patch(
                "services.odl_parser._run_convert",
                side_effect=_stage_convert_side_effect(),
            ):
                manifest = ensure_visual_artifacts(
                    paper_dir, mode="java", extraction_pipeline_version="legacy", force=True
                )

            md = (paper_dir / "paper.md").read_text(encoding="utf-8")
            ref = (paper_dir / "paper.odl-reference.md").read_text(encoding="utf-8")
            cache = (paper_dir / TEXT_CACHE_FILENAME).read_text(encoding="utf-8")

            self.assertIn("GEMINI PROMOTED", md)
            self.assertNotIn("ODL VERBATIM", md)
            self.assertIn("ODL VERBATIM", ref)
            self.assertIn("GEMINI PROMOTED", cache)
            self.assertIn("GEMINI PROMOTED", manifest["full_text"])
            self.assertEqual(manifest["text_engine"], "gemini")
            self.assertEqual(manifest["visual_engine"], "gemini")
            self.assertEqual(manifest["engine"], "gemini")
            self.assertEqual(get_odl_reference_text(paper_dir), ref)
            self.assertFalse(sidecar.exists(), "stale document_context 사이드카가 무효화되지 않음")

    def test_promotion_is_idempotent_on_force_rerun(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = self._make_paper(tmp_dir)
            side = _stage_convert_side_effect()
            with patch("services.odl_parser._run_convert", side_effect=side):
                ensure_visual_artifacts(
                    paper_dir, mode="java", extraction_pipeline_version="legacy", force=True
                )
                ref_first = (paper_dir / "paper.odl-reference.md").read_text(encoding="utf-8")
                # 재실행(force): 레퍼런스를 gemini 텍스트로 덮어쓰면 안 된다.
                ensure_visual_artifacts(
                    paper_dir, mode="java", extraction_pipeline_version="legacy", force=True
                )

            ref_second = (paper_dir / "paper.odl-reference.md").read_text(encoding="utf-8")
            md = (paper_dir / "paper.md").read_text(encoding="utf-8")
            self.assertEqual(ref_first, ref_second)
            self.assertIn("ODL VERBATIM", ref_second)
            self.assertNotIn("GEMINI PROMOTED", ref_second)
            self.assertIn("GEMINI PROMOTED", md)

    def test_gemini_visual_failure_falls_back_to_odl_without_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = self._make_paper(tmp_dir)
            sidecar = paper_dir / ".document_context.json"
            sidecar.write_text("{\"stale\": true}", encoding="utf-8")

            with patch(
                "services.odl_parser._run_convert",
                side_effect=_stage_convert_side_effect(visual_fail=True),
            ):
                manifest = ensure_visual_artifacts(
                    paper_dir, mode="java", extraction_pipeline_version="legacy", force=True
                )

            md = (paper_dir / "paper.md").read_text(encoding="utf-8")
            self.assertIn("ODL VERBATIM", md)
            self.assertFalse((paper_dir / "paper.odl-reference.md").exists())
            self.assertIsNone(get_odl_reference_text(paper_dir))
            self.assertNotIn("text_engine", manifest)
            self.assertEqual(manifest["engine"], "odl-java")
            # ODL-only 경로: stale 사이드카를 건드리지 않는다(승격 없음).
            self.assertTrue(sidecar.exists())

    def test_odl_only_visual_env_does_not_promote(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            paper_dir = self._make_paper(tmp_dir)
            # SASOO_PDF_VISUAL_ENGINE=odl → 실제 _run_convert 경로가 ODL을 고른다.
            # 여기선 _run_convert를 mock하되 visual/text 모두 ODL을 반환하도록 강제.
            def _all_odl(pdf_path, output_dir, figures_dir, mode, engine=None, stage="text"):
                root = {
                    "title": "T", "author": "A", "number of pages": 1,
                    "kids": [{"type": "paragraph", "id": 1, "page number": 1,
                              "bounding box": [10, 10, 120, 40], "content": ODL_TEXT}],
                }
                return copy.deepcopy(root), ODL_TEXT, "odl-java"

            with patch("services.odl_parser._run_convert", side_effect=_all_odl):
                manifest = ensure_visual_artifacts(
                    paper_dir, mode="java", extraction_pipeline_version="legacy", force=True
                )

            self.assertFalse((paper_dir / "paper.odl-reference.md").exists())
            self.assertNotIn("text_engine", manifest)
            self.assertNotIn("visual_engine", manifest)
            self.assertIn("ODL VERBATIM", (paper_dir / "paper.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
