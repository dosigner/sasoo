"""HTTP regression checks using an isolated SQLite DB and artifact files."""

import asyncio
import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from api.papers import router
from models import database
from services import artifact_status, odl_parser


class PaperEfficiencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.dict(os.environ, {"SASOO_APP_DATA_ROOT": str(self.root)}))
        self.stack.enter_context(patch.object(database, "APP_DATA_ROOT", self.root))
        self.stack.enter_context(patch.object(database, "DB_PATH", self.root / "test.db"))
        self.stack.enter_context(patch.object(database, "_get_default_library_root", return_value=self.root / "papers"))
        self.stack.enter_context(patch.object(database, "_db_connection", None))
        self.stack.enter_context(patch.object(database, "_library_root_cache", None))
        await database.init_db()
        self.addCleanup(self.stack.close)
        self.addAsyncCleanup(database.close_db)
        self.db = await database.get_db()
        app = FastAPI()
        app.include_router(router)

        from main import health_check

        app.add_api_route("/health", health_check)

        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)

    async def add_papers(self, count):
        for number in range(count):
            folder = f"paper-{number}"
            await self.db.execute(
                "INSERT INTO papers (title, folder_name, status) VALUES (?, ?, ?)",
                (folder, folder, "completed" if number % 2 == 0 else "pending"),
            )
            paper_dir = database.get_paper_dir(folder)
            paper_dir.mkdir(parents=True)
            pdf = paper_dir / "paper.pdf"
            pdf.write_bytes(b"%PDF-1.4\nTest\n")
            signature = odl_parser.get_pdf_signature(pdf)
            manifest = {
                **signature,
                "requested_mode": "java", "parser_version": "odl-v3",
                "extraction_pipeline_version": "resolver_v1", "resolver_version": "resolver-v1",
                "full_text": "Test", "visual_artifacts_ready": True,
                "figures": [{"file_path": "figure.png"}],
                "tables": [{"csv_path": "table.csv", "html_path": "table.html"}],
                "pages": [{"raster_path": "page.png"}],
            }
            (paper_dir / odl_parser.MANIFEST_FILENAME).write_text(json.dumps(manifest))
            (paper_dir / odl_parser.TEXT_CACHE_META_FILENAME).write_text(json.dumps(signature))
            (paper_dir / odl_parser.TEXT_CACHE_FILENAME).write_text("Test")
            for filename in ("figure.png", "table.csv", "table.html", "page.png"):
                (paper_dir / filename).write_bytes(b"test")
        await self.db.commit()

    async def test_page_size_does_not_increase_query_count(self):
        # Given: 100 valid paper artifacts in the real temporary database.
        await self.add_papers(100)
        for page_size in (20, 100):
            statements = []
            await self.db.set_trace_callback(statements.append)
            with (
                patch.object(odl_parser, "_load_manifest", wraps=odl_parser._load_manifest) as manifests,
                patch.object(odl_parser, "get_pdf_signature", wraps=odl_parser.get_pdf_signature) as signatures,
            ):
                # When: the actual list HTTP route serves this page.
                start = time.perf_counter()
                response = await self.client.get(f"/api/papers?page_size={page_size}")
                elapsed_ms = (time.perf_counter() - start) * 1000
            # Then: query count is constant and each artifact is inspected once.
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(len(data["papers"]), page_size)
            self.assertEqual(data["completed_count"], 50)
            self.assertTrue(all(paper["artifacts_ready"] for paper in data["papers"]))
            selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
            self.assertEqual(len(selects), 4, selects)
            self.assertEqual(manifests.call_count, page_size)
            self.assertEqual(signatures.call_count, page_size)
            print(f"papers page={page_size}: SQL={len(selects)}, manifests={manifests.call_count}, elapsed_ms={elapsed_ms:.2f}")
        await self.db.set_trace_callback(None)

    async def test_missing_files_preserve_degraded_states(self):
        # Given: missing PDF, missing figure/table/raster, stale PDF, missing manifest.
        await self.add_papers(6)
        for number, filename in enumerate(("paper.pdf", "figure.png", "table.csv", "page.png")):
            (database.get_paper_dir(f"paper-{number}") / filename).unlink()
        (database.get_paper_dir("paper-4") / "paper.pdf").write_bytes(b"changed PDF")
        (database.get_paper_dir("paper-5") / odl_parser.MANIFEST_FILENAME).unlink()
        # When: listing papers whose artifacts became unavailable.
        response = await self.client.get("/api/papers?sort_by=title&sort_order=asc")
        # Then: missing PDF remains an error; missing visuals do not invalidate text.
        items = response.json()["papers"]
        self.assertEqual((items[0]["text_ready"], items[0]["visual_state"], items[0]["visual_error"]), (False, "error", "PDF not found"))
        self.assertTrue(all(item["text_ready"] for item in items[1:4]))
        self.assertTrue(all(item["visual_state"] == "partial" for item in items[1:]))
        self.assertFalse(items[4]["text_ready"])
        self.assertFalse(items[5]["text_ready"])

    async def test_health_responds_while_file_inspection_is_blocked(self):
        # Given: disk inspection held at a controlled thread boundary.
        await self.add_papers(1)
        started, release = threading.Event(), threading.Event()
        original = artifact_status.paper_artifact_readiness

        def held_inspection(paper_dir):
            started.set()
            if not release.wait(timeout=3):
                raise TimeoutError("File check was never released")
            return original(paper_dir)

        with patch.object(artifact_status, "paper_artifact_readiness", side_effect=held_inspection):
            pending = asyncio.create_task(self.client.get("/api/papers"))
            try:
                self.assertTrue(await asyncio.to_thread(started.wait, 2))
                # When: health is requested while the file check is still held.
                start = time.perf_counter()
                response = await asyncio.wait_for(self.client.get("/health"), timeout=1)
                print(f"health during held artifact check: {(time.perf_counter() - start) * 1000:.2f}ms")
                # Then: health responds before listing can complete.
                self.assertEqual(response.json()["status"], "ok")
                self.assertFalse(pending.done())
            finally:
                release.set()
                await pending

    async def test_filtered_count_and_empty_page_when_no_papers_match(self):
        # Given: two completed papers and one pending paper.
        await self.add_papers(3)
        # When: listing an empty page of the completed filter.
        response = await self.client.get("/api/papers?status=completed&page=2")
        # Then: the full filtered aggregate survives an empty page.
        self.assertEqual(response.json()["papers"], [])
        self.assertEqual(response.json()["total"], 2)
        self.assertEqual(response.json()["completed_count"], 2)

    async def test_visual_counts_ignore_rejected_rows(self):
        # Given: accepted, legacy NULL, and rejected figure/table rows.
        await self.add_papers(1)
        for table, required in (("figures", "figure_num"), ("tables", "table_num")):
            for number, state in enumerate((None, "resolved", "rejected")):
                await self.db.execute(
                    f"INSERT INTO {table} (paper_id, {required}, extraction_status) VALUES (1, ?, ?)",
                    (str(number), state),
                )
        await self.db.commit()
        # When: shared single-paper count helper reads the database.
        counts = await artifact_status.get_visual_row_counts(1)
        # Then: rejected artifacts do not count as usable rows.
        self.assertEqual(counts, (2, 2))
