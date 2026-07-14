import asyncio
import os
import tempfile
import unittest

import aiosqlite

from models import analysis_runs as ar


class AnalysisRunsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.conn = await aiosqlite.connect(self.tmp.name)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA busy_timeout=5000")
        await self.conn.executescript(
            "CREATE TABLE papers (id INTEGER PRIMARY KEY, status TEXT);"
        )
        await self.conn.executescript(ar.ANALYSIS_RUNS_DDL)
        await self.conn.commit()

    async def asyncTearDown(self):
        await self.conn.close()
        os.unlink(self.tmp.name)

    async def _paper(self, pid, status="analyzing"):
        await self.conn.execute("INSERT INTO papers (id, status) VALUES (?, ?)", (pid, status))
        await self.conn.commit()

    async def test_claim_next_returns_generation_and_is_atomic(self):
        now = "2026-07-14T00:00:00+00:00"
        await self._paper(1)
        await ar.upsert_queued(self.conn, 1, now)
        claimed = await ar.claim_next(self.conn, cap=3, now=now, fresh_cut="2026-07-13T23:59:00+00:00",
                                      backoff_cut="2026-07-13T23:59:00+00:00", max_attempts=3)
        self.assertEqual(claimed, (1, 1))                      # generation 0 -> 1
        run = await ar.get_run(self.conn, 1)
        self.assertEqual(run["status"], "running")
        self.assertEqual(run["heartbeat_at"], now)             # claim 시 즉시 기록(영구 running 방지)
        # 두 번째 claim은 같은 논문을 다시 잡지 않는다(더 이상 queued 아님)
        self.assertIsNone(await ar.claim_next(self.conn, 3, now, "2026-07-13T23:59:00+00:00",
                                              "2026-07-13T23:59:00+00:00", 3))

    async def test_claim_next_respects_cap(self):
        now = "2026-07-14T00:00:00+00:00"; fresh = "2026-07-13T23:59:00+00:00"
        for pid in (1, 2):
            await self._paper(pid); await ar.upsert_queued(self.conn, pid, now)
        first = await ar.claim_next(self.conn, cap=1, now=now, fresh_cut=fresh, backoff_cut=fresh, max_attempts=3)
        self.assertEqual(first[0], 1)
        # cap=1이고 이미 running 1개 → 더 못 잡음
        self.assertIsNone(await ar.claim_next(self.conn, 1, now, fresh, fresh, 3))

    async def test_claim_next_atomic_under_two_connection_race(self):
        # 같은 파일에 두 연결을 열고 asyncio.gather로 동시에 claim — cap=1이면 정확히 1개만 성공해야 한다.
        # (aiosqlite는 연결마다 전용 스레드라 두 UPDATE가 실제로 경합하고, busy_timeout이 락 대기를 흡수.
        #  claim_next는 내부에서 commit하므로 승자의 running 전이가 패자의 cap predicate에 보인다)
        now = "2026-07-14T00:00:00+00:00"; fresh = "2026-07-13T23:59:00+00:00"
        for pid in (1, 2):
            await self._paper(pid); await ar.upsert_queued(self.conn, pid, now)

        conn_a = await aiosqlite.connect(self.tmp.name)
        conn_b = await aiosqlite.connect(self.tmp.name)
        try:
            for c in (conn_a, conn_b):
                await c.execute("PRAGMA busy_timeout=5000")
            results = await asyncio.gather(
                ar.claim_next(conn_a, cap=1, now=now, fresh_cut=fresh,
                              backoff_cut=fresh, max_attempts=3),
                ar.claim_next(conn_b, cap=1, now=now, fresh_cut=fresh,
                              backoff_cut=fresh, max_attempts=3),
            )
            claimed = [r for r in results if r is not None]
            self.assertEqual(len(claimed), 1)  # cap=1: 두 연결 중 정확히 1개만 claim
        finally:
            await conn_a.close()
            await conn_b.close()

    async def test_fenced_heartbeat_rejects_stale_generation(self):
        now = "2026-07-14T00:00:00+00:00"; fresh = "2026-07-13T23:59:00+00:00"
        await self._paper(1); await ar.upsert_queued(self.conn, 1, now)
        pid, gen = await ar.claim_next(self.conn, 3, now, fresh, fresh, 3)   # gen=1
        self.assertEqual(await ar.fenced_heartbeat(self.conn, 1, gen, "running", "screening", 16.0, now), 1)
        # 구 워커(gen-1)는 fence 실패
        self.assertEqual(await ar.fenced_heartbeat(self.conn, 1, gen - 1, "running", "x", 50.0, now), 0)

    async def test_reconcile_prefers_papers_terminal_over_requeue(self):
        now = "2026-07-14T00:10:00+00:00"; stale = "2026-07-14T00:09:00+00:00"
        old = "2026-07-14T00:00:00+00:00"; fresh0 = "2026-07-13T23:59:00+00:00"
        await self._paper(1, status="completed")               # papers는 이미 완료
        await ar.upsert_queued(self.conn, 1, old)
        await ar.claim_next(self.conn, 3, old, fresh0, fresh0, 3)  # running, heartbeat=old(→stale)
        await ar.reconcile_stale(self.conn, stale_cut=stale, max_attempts=3, now=now)
        run = await ar.get_run(self.conn, 1)
        self.assertEqual(run["status"], "completed")           # requeue 아님(papers-terminal 우선)

    async def test_reconcile_cancel_wins_over_requeue(self):
        now = "2026-07-14T00:10:00+00:00"; stale = "2026-07-14T00:09:00+00:00"
        old = "2026-07-14T00:00:00+00:00"; fresh0 = "2026-07-13T23:59:00+00:00"
        await self._paper(1, status="analyzing")
        await ar.upsert_queued(self.conn, 1, old)
        await ar.claim_next(self.conn, 3, old, fresh0, fresh0, 3)
        await ar.request_cancel(self.conn, 1)
        await ar.reconcile_stale(self.conn, stale_cut=stale, max_attempts=3, now=now)
        self.assertEqual((await ar.get_run(self.conn, 1))["status"], "cancelled")

    async def test_seed_legacy_creates_queued_for_orphan_analyzing(self):
        now = "2026-07-14T00:00:00+00:00"
        await self._paper(1, status="analyzing")               # runs 행 없음(레거시)
        n = await ar.seed_legacy(self.conn, now)
        self.assertEqual(n, 1)
        self.assertEqual((await ar.get_run(self.conn, 1))["status"], "queued")


if __name__ == "__main__":
    unittest.main()
