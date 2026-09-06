"""SQL and startup regressions using an isolated database and library."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from api import settings
from models import database
from services import analysis_results, analysis_supervisor


class EfficiencyStorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="sasoo-efficiency-storage-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        for target, value in (
            ("APP_DATA_ROOT", self.root),
            ("DB_PATH", self.root / "sasoo.db"),
            ("_db_connection", None),
        ):
            patcher = patch.object(database, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        environment = patch.dict(os.environ, {
            "SASOO_ENV": "production", "SASOO_APP_DATA_ROOT": str(self.root),
        })
        environment.start()
        self.addCleanup(environment.stop)
        defaults = patch.dict(settings.DEFAULT_SETTINGS, {"library_path": str(self.root / "library")})
        defaults.start()
        self.addCleanup(defaults.stop)
        database.invalidate_library_root_cache()
        await database.init_db()
        self.addAsyncCleanup(database.close_db)
        self.conn = await database.get_db()
        self.assertTrue(database.get_library_root().is_relative_to(self.root))
        await self.conn.executemany(
            "INSERT INTO papers (id, title, folder_name) VALUES (?, ?, ?)",
            [(1, "First", "first"), (2, "Second", "second")],
        )
        await self.conn.commit()

    async def test_initialization_then_repeated_reads_do_not_write(self) -> None:
        await self.conn.executemany("INSERT INTO settings (key, value) VALUES (?, ?)", [
            ("pdf_parser_mode", "legacy"),
            ("extraction_pipeline_version", "legacy"),
            ("paperbanana_profile", "retired"),
            ("theme", "dark"),
        ])
        await self.conn.commit()
        await settings._ensure_defaults()
        raw = await settings._get_all_settings()
        self.assertEqual(raw["theme"], "dark")
        self.assertEqual(raw["pdf_parser_mode"], "java")
        self.assertEqual(raw["extraction_pipeline_version"], "resolver_v1")
        self.assertNotIn("paperbanana_profile", raw)
        self.assertTrue(Path(raw["library_path"]).is_relative_to(self.root))
        statements: list[str] = []
        await self.conn.set_trace_callback(statements.append)
        for _ in range(3):
            await settings.get_settings()
        self.assertEqual(len(statements), 6)
        self.assertTrue(all(sql.lstrip().upper().startswith("SELECT") for sql in statements))
        await settings._set_settings({"theme": "light"})
        self.assertEqual((await settings._get_all_settings())["theme"], "light")

    async def test_plaintext_and_unreadable_keys_do_not_migrate_during_reads(self) -> None:
        await settings._ensure_defaults()
        await settings._set_settings({"openai_api_key": "test-plaintext", "gemini_api_key": "enc:v1:broken"})
        with (
            patch.object(settings, "decrypt_value", side_effect=lambda value: "" if value.startswith("enc:") else value),
            patch.object(settings, "encrypt_value") as encrypt,
        ):
            statements: list[str] = []
            await self.conn.set_trace_callback(statements.append)
            raw = await settings._get_all_settings()
        self.assertEqual(raw["openai_api_key"], "test-plaintext")
        self.assertEqual(raw["gemini_api_key"], "")
        encrypt.assert_not_called()
        self.assertEqual(len(statements), 1)
        self.assertTrue(statements[0].startswith("SELECT"))

    async def test_server_initializes_and_worker_reuses_settings(self) -> None:
        import main

        await database.close_db()
        with (
            patch("services.log_setup.setup_logging"),
            patch("services.agents.load_all_agents"),
            patch("services.api_key_runtime.load_api_keys_from_settings", new=AsyncMock()),
            patch.object(settings, "_ensure_defaults", wraps=settings._ensure_defaults) as initialize,
        ):
            await main.bootstrap_runtime(worker=False)
            self.assertEqual((await settings._get_all_settings())["max_concurrent_analyses"], "3")
            await database.close_db()
            await main.bootstrap_runtime(worker=True)
            self.assertEqual((await settings._get_all_settings())["max_concurrent_analyses"], "3")
        initialize.assert_awaited_once()

    async def test_latest_sql_matches_legacy_for_filters_nulls_and_ties(self) -> None:
        rows = [
            (1, "recipe", json.dumps({"revision": index}), "2026-09-01 00:00:00")
            for index in range(100)
        ] + [
            (1, "visual", "broken-json", None),
            (1, "visual", "latest-broken-json", None),
            (1, "screening", "{}", "2026-09-02"),
            (1, "screening", "null-time-is-older", None),
            (1, "error", "{}", "2026-09-03"),
            (1, "", "{}", "2026-09-03"),
            (2, "recipe", "other-paper", "2026-09-04"),
        ]
        await self.conn.executemany(
            "INSERT INTO analysis_results (paper_id, phase, result, created_at) VALUES (?, ?, ?, ?)", rows,
        )
        await self.conn.commit()
        for phases in (None, [], ["recipe"], ["visual", "missing"], ["error"], ["missing"]):
            with self.subTest(phases=phases):
                legacy_rows = await database.fetch_all(
                    "SELECT * FROM analysis_results WHERE paper_id = 1 AND phase != 'error' "
                    "ORDER BY created_at DESC, id DESC",
                )
                expected = {}
                for row in legacy_rows:
                    phase = row["phase"]
                    if phase and (not phases or phase in phases):
                        expected.setdefault(phase, analysis_results.parse_phase_row(row))
                with patch.object(analysis_results, "fetch_all", wraps=database.fetch_all) as fetch:
                    actual = await analysis_results.get_latest_completed_phase_rows(1, phases)
                self.assertEqual(actual, expected)
                self.assertEqual(list(actual), list(expected))
                sql, params = fetch.await_args.args
                returned = await database.fetch_all(sql, params)
                self.assertLessEqual(len(returned), 4)
        latest = await analysis_results.get_latest_completed_phase_rows(1)
        self.assertEqual(latest["recipe"]["parsed_result"], {"revision": 99})
        self.assertEqual(latest["visual"]["parsed_result"], {"raw_text": "latest-broken-json"})

    async def test_budget_sum_preserves_december_bounds_nulls_and_limit(self) -> None:
        await settings._ensure_defaults()
        await settings._set_settings({"monthly_budget_limit": "5.25"})
        with patch.object(analysis_supervisor, "datetime") as clock:
            clock.now.return_value = datetime(2026, 12, 15, tzinfo=timezone.utc)
            self.assertEqual(await analysis_supervisor.read_budget_state(), (0.0, 5.25))
            await self.conn.executemany(
                "INSERT INTO analysis_results (paper_id, phase, result, created_at, cost_usd) VALUES (1, ?, '{}', ?, ?)",
                [("recipe", "2026-12-01", 3.0), ("recipe", "2026-12-31T23:59:59", 2.25),
                 ("visual", "2026-12-03", None), ("error", "2026-12-04", 100.0),
                 ("recipe", "2027-01-01", 50.0), ("recipe", "2026-11-30", 20.0)],
            )
            await self.conn.commit()
            current, limit = await analysis_supervisor.read_budget_state()
            legacy = await database.fetch_all(
                "SELECT cost_usd FROM analysis_results WHERE created_at >= ? AND created_at < ? AND phase != 'error'",
                ("2026-12-01", "2027-01-01"),
            )
            self.assertEqual(current, sum(row["cost_usd"] or 0.0 for row in legacy))
            self.assertTrue(current >= limit)
            await settings._set_settings({"monthly_budget_limit": "5.2500000001"})
            current, limit = await analysis_supervisor.read_budget_state()
            self.assertFalse(current >= limit)

    async def test_reconciler_reuses_one_settings_snapshot(self) -> None:
        await settings._ensure_defaults()
        with patch.object(settings, "_get_all_settings", wraps=settings._get_all_settings) as read:
            await analysis_supervisor.reconcile_once(self.conn)
        read.assert_awaited_once()
