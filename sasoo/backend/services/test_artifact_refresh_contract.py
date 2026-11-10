"""Record current refresh failure and figure persistence boundaries."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import aiosqlite
import pytest

from services import odl_parser as odl


@pytest.mark.parametrize("stage", ["extract", "figures", "tables"])
def test_refresh_stops_at_the_failing_stage(stage, tmp_path):
    async def run():
        marker = tmp_path / "engine-output.txt"
        marker.write_bytes(b"synthetic engine output\n")
        manifest = {"figures": [], "_visual_parse_usage": {"model": "fixture", "tokens_in": 1}}
        extract = AsyncMock(return_value=manifest)
        figures = AsyncMock()
        tables = AsyncMock()
        record = AsyncMock()
        {"extract": extract, "figures": figures, "tables": tables}[stage].side_effect = RuntimeError(stage)
        with patch.object(odl, "ensure_visual_artifacts_async", extract), patch.object(
            odl, "sync_figures_for_paper", figures
        ), patch.object(odl, "sync_tables_for_paper", tables), patch.object(
            odl, "_record_visual_parse_usage", record
        ):
            with pytest.raises(RuntimeError, match=stage):
                await odl._refresh_paper_artifacts(7, tmp_path)
        assert extract.await_count == 1
        assert figures.await_count == (0 if stage == "extract" else 1)
        assert tables.await_count == (1 if stage == "tables" else 0)
        record.assert_not_awaited()
        assert marker.read_bytes() == b"synthetic engine output\n"
    asyncio.run(run())


def test_table_failure_keeps_committed_figure_id_description_and_files(tmp_path):
    async def run():
        (tmp_path / "paper.pdf").write_bytes(b"synthetic pdf bytes")
        (tmp_path / "figure.png").write_bytes(b"synthetic image bytes")
        db_path = tmp_path / "test.sqlite"
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("""CREATE TABLE figures (
                id INTEGER PRIMARY KEY, paper_id INTEGER, figure_num TEXT, caption TEXT,
                file_path TEXT, quality TEXT, page_number INTEGER, bbox_json TEXT,
                extraction_engine TEXT, confidence REAL, classifier_label TEXT,
                classifier_model TEXT, is_composite INTEGER, resolver_version TEXT,
                extraction_status TEXT, parent_figure_id INTEGER, ai_analysis TEXT,
                detailed_explanation TEXT)""")
            await db.execute("INSERT INTO figures (id, paper_id, figure_num, caption, ai_analysis, detailed_explanation) VALUES (?, ?, ?, ?, ?, ?)",
                             (41, 7, "Fig. 1", "old", "analysis", "explanation"))
            await db.commit()
            async def fetch_all(query, params):
                async with db.execute(query, params) as cursor:
                    return [dict(row) for row in await cursor.fetchall()]
            manifest = {"figures": [{"figure_num": "Fig. 1", "caption": "new", "file_path": "figure.png"}],
                        "tables": [], "_visual_parse_usage": {"model": "fixture", "tokens_in": 1}}
            record = AsyncMock()
            with patch.object(odl, "ensure_visual_artifacts_async", new=AsyncMock(return_value=manifest)), patch.object(
                odl, "get_db", new=AsyncMock(return_value=db)
            ), patch.object(odl, "fetch_all", new=fetch_all), patch.object(
                odl, "sync_tables_for_paper", new=AsyncMock(side_effect=RuntimeError("table sync failed"))
            ), patch.object(odl, "_record_visual_parse_usage", record):
                with pytest.raises(RuntimeError, match="table sync failed"):
                    await odl._refresh_paper_artifacts(7, tmp_path)
            async with db.execute("SELECT id, caption, ai_analysis, detailed_explanation FROM figures") as cursor:
                rows = [tuple(row) for row in await cursor.fetchall()]
            assert rows == [(41, "new", "analysis", "explanation")]
            record.assert_not_awaited()
        assert (tmp_path / "paper.pdf").read_bytes() == b"synthetic pdf bytes"
        assert (tmp_path / "figure.png").read_bytes() == b"synthetic image bytes"
        assert sorted(path.name for path in tmp_path.iterdir()) == ["figure.png", "paper.pdf", "test.sqlite"]
    asyncio.run(run())


def test_fake_engine_artifact_files_and_text_bytes(tmp_path):
    import hashlib
    import fitz
    from services.test_odl_parser import _parser_env, _stage_convert_side_effect

    pdf = fitz.open()
    page = pdf.new_page(width=300, height=400)
    page.insert_text((72, 72), "seed", fontsize=12)
    pdf.save(tmp_path / "paper.pdf")
    pdf.close()
    with _parser_env(GEMINI_API_KEY="fixture"), patch.object(
        odl, "_java_runtime_available", return_value=True
    ), patch.object(odl, "_run_convert", side_effect=_stage_convert_side_effect()), patch.object(
        odl, "active_provider", new=AsyncMock(return_value="gemini")
    ):
        odl.ensure_visual_artifacts(tmp_path, mode="java", extraction_pipeline_version="legacy", force=True)
    files = sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*") if path.is_file())
    assert files == [
        ".odl_manifest.json", ".page_rasters/page_1.png", ".text_cache.meta.json", ".text_cache.txt",
        "paper.json", "paper.md", "paper.odl-reference.md", "paper.pdf",
    ]
    expected = {
        ".text_cache.txt": "216a3ff3cd287372f69fe429838bf0d1d263b552e563a1badcaaa51eb9f09802",
        "paper.md": "216a3ff3cd287372f69fe429838bf0d1d263b552e563a1badcaaa51eb9f09802",
        "paper.odl-reference.md": "4212e405e326466dc09fcf284465eaaef37bbccc672daf201f1d07cd4ed6e88d",
    }
    assert {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in expected} == expected
    assert (tmp_path / ".page_rasters/page_1.png").stat().st_size > 0
