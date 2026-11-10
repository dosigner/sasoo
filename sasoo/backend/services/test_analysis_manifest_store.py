"""Isolated tests for the unfinished execution-manifest storage boundary."""

import asyncio
import hashlib

import aiosqlite
import pytest

from services.analysis_manifest_store import DDL, FenceLost, save_result_version


def test_versions_capture_consumed_bytes_and_fence_is_atomic(tmp_path):
    asyncio.run(_exercise(tmp_path / "isolated.db"))


async def _exercise(path):
    async with aiosqlite.connect(path) as db:
        await db.executescript("""
            CREATE TABLE analysis_runs (paper_id INTEGER PRIMARY KEY, generation INTEGER, status TEXT);
            CREATE TABLE analysis_results (id INTEGER PRIMARY KEY, paper_id INTEGER, phase TEXT, result TEXT);
            INSERT INTO analysis_runs VALUES (1, 7, 'running');
            INSERT INTO analysis_results VALUES (10, 1, 'visual', 'visual A');
            INSERT INTO analysis_results VALUES (11, 1, 'recipe', 'recipe B');
            INSERT INTO analysis_results VALUES (12, 1, 'deep_dive', 'old');
        """ + DDL)
        await db.execute("INSERT INTO manifest_executions VALUES ('exec', 1)")
        await db.execute("INSERT INTO manifest_attempts VALUES ('attempt', 'exec', 7)")
        await db.commit()
        visual = await save_result_version(db, 'exec', 'attempt', 1, 7, 10, 'visual', 'visual A', [])
        recipe = await save_result_version(db, 'exec', 'attempt', 1, 7, 11, 'recipe', 'recipe B', [])
        deep = await save_result_version(db, 'exec', 'attempt', 1, 7, 12, 'deep_dive', 'answer', [('visual', visual), ('recipe', recipe)])
        await db.execute("UPDATE analysis_results SET result='changed' WHERE id IN (10, 11)")
        await db.commit()
        rows = await (await db.execute("SELECT i.role, v.result_bytes, v.content_sha256 FROM manifest_inputs i JOIN manifest_versions v ON v.version_id=i.version_id WHERE i.event_id=? ORDER BY i.position", (deep,))).fetchall()
        assert [(r[0], r[1]) for r in rows] == [('visual', b'visual A'), ('recipe', b'recipe B')]
        assert all(hashlib.sha256(row[1]).hexdigest() == row[2] for row in rows)
        await db.execute("UPDATE analysis_runs SET generation=8 WHERE paper_id=1")
        await db.commit()
        with pytest.raises(FenceLost):
            await save_result_version(db, 'exec', 'attempt', 1, 7, 12, 'deep_dive', 'stale', [])
        assert (await (await db.execute("SELECT result FROM analysis_results WHERE id=12")).fetchone())[0] == 'answer'
        assert (await (await db.execute("SELECT COUNT(*) FROM manifest_events")).fetchone())[0] == 3


def test_write_failure_rolls_back_and_versions_are_immutable(tmp_path):
    asyncio.run(_failure_and_immutability(tmp_path / 'failure.db'))


async def _failure_and_immutability(path):
    async with aiosqlite.connect(path) as db:
        await db.executescript("""
            CREATE TABLE analysis_runs (paper_id INTEGER PRIMARY KEY, generation INTEGER, status TEXT);
            CREATE TABLE analysis_results (id INTEGER PRIMARY KEY, paper_id INTEGER, phase TEXT, result TEXT);
            INSERT INTO analysis_runs VALUES (1, 1, 'running');
            INSERT INTO analysis_results VALUES (1, 1, 'visual', 'original');
        """ + DDL)
        await db.execute("INSERT INTO manifest_executions VALUES ('e', 1)")
        await db.execute("INSERT INTO manifest_attempts VALUES ('a', 'e', 1)")
        await db.commit()
        version = await save_result_version(db, 'e', 'a', 1, 1, 1, 'visual', 'saved', [])
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute("UPDATE manifest_versions SET result_bytes=x'00' WHERE version_id=?", (version,))
        await db.rollback()
        await db.executescript("""CREATE TRIGGER fail_event BEFORE INSERT ON manifest_events
            BEGIN SELECT RAISE(ABORT, 'injected failure'); END;""")
        with pytest.raises(aiosqlite.IntegrityError):
            await save_result_version(db, 'e', 'a', 1, 1, 1, 'visual', 'not saved', [])
        assert (await (await db.execute("SELECT result FROM analysis_results WHERE id=1")).fetchone())[0] == 'saved'
        assert (await (await db.execute("SELECT COUNT(*) FROM manifest_versions")).fetchone())[0] == 1
