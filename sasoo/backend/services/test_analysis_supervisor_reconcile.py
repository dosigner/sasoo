import os
import tempfile
import unittest
from unittest.mock import patch

import aiosqlite

from models import analysis_runs as ar


class ReconcileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); self.tmp.close()
        self.conn = await aiosqlite.connect(self.tmp.name); self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript("CREATE TABLE papers (id INTEGER PRIMARY KEY, status TEXT);")
        await self.conn.executescript(ar.ANALYSIS_RUNS_DDL); await self.conn.commit()

    async def asyncTearDown(self):
        await self.conn.close(); os.unlink(self.tmp.name)

    async def test_reconcile_drains_queue_up_to_cap(self):
        from services import analysis_supervisor as sup
        for pid in (1, 2, 3):
            await self.conn.execute("INSERT INTO papers VALUES (?, 'analyzing')", (pid,))
            await ar.upsert_queued(self.conn, pid, ar.utcnow_iso())
        await self.conn.commit()
        spawned = []
        await sup.reconcile_once(self.conn, cap=2, spawn=lambda p, g: spawned.append((p, g)) or 1000 + p)
        # cap=2 → 2편만 running으로 전이, spawn 2회
        self.assertEqual(len(spawned), 2)
        running = [r for r in [await ar.get_run(self.conn, i) for i in (1, 2, 3)] if r["status"] == "running"]
        self.assertEqual(len(running), 2)
        for r in running:
            self.assertEqual(r["generation"], 1)  # claim이 generation +1

    async def test_reconcile_marks_over_attempts_error(self):
        from services import analysis_supervisor as sup
        await self.conn.execute("INSERT INTO papers VALUES (1, 'analyzing')")
        await ar.upsert_queued(self.conn, 1, ar.utcnow_iso())
        await self.conn.execute("UPDATE analysis_runs SET attempts=3 WHERE paper_id=1")
        await self.conn.commit()
        spawned = []
        await sup.reconcile_once(self.conn, cap=2, spawn=lambda p, g: spawned.append(p) or 1)
        self.assertEqual(spawned, [])                 # attempts 초과는 스폰 안 함
        self.assertEqual((await ar.get_run(self.conn, 1))["status"], "error")
        row = await (await self.conn.execute("SELECT status FROM papers WHERE id=1")).fetchone()
        self.assertEqual(row["status"], "error")

    async def test_setpid_failure_does_not_requeue(self):
        # spawn 성공 후 set_pid(DB 쓰기)만 실패 — 워커는 이미 떠 있으므로 requeue하면 이중 스폰.
        # 행은 running 유지(재claim 불가), 예외는 전파되지 않아야 한다. 생존 판정은 heartbeat 리스.
        from services import analysis_supervisor as sup
        await self.conn.execute("INSERT INTO papers VALUES (1, 'analyzing')")
        await ar.upsert_queued(self.conn, 1, ar.utcnow_iso())
        await self.conn.commit()
        spawned = []

        def fake_spawn(pid_, gen_):
            spawned.append((pid_, gen_))
            return 12345

        with patch.object(ar, "set_pid", side_effect=RuntimeError("db locked")):
            await sup.reconcile_once(self.conn, cap=2, spawn=fake_spawn)
        self.assertEqual(len(spawned), 1)
        run = await ar.get_run(self.conn, 1)
        self.assertEqual(run["status"], "running")     # queued로 되돌아가지 않음

    async def test_reconcile_once_finalizes_queued_cancel_zombies(self):
        # C1: cap 초과로 queued에 머문 채 cancel_requested=1만 세워진 행은 claim되지도
        # requeue-error되지도 않아 영구 좀비가 됐다. reconcile_once가 cancelled로 확정해야 한다.
        from services import analysis_supervisor as sup
        await self.conn.execute("INSERT INTO papers VALUES (1, 'analyzing')")
        await ar.upsert_queued(self.conn, 1, ar.utcnow_iso())
        await ar.request_cancel(self.conn, 1)
        await self.conn.commit()
        spawned = []
        await sup.reconcile_once(self.conn, cap=0, spawn=lambda p, g: spawned.append(p) or 1)
        self.assertEqual(spawned, [])
        run = await ar.get_run(self.conn, 1)
        self.assertEqual(run["status"], "cancelled")
        row = await (await self.conn.execute("SELECT status FROM papers WHERE id=1")).fetchone()
        self.assertEqual(row["status"], "cancelled")

    async def test_reconcile_spawns_via_to_thread(self):
        # M1: /run 핸들러가 이벤트 루프에서 번들 exec(spawn)를 동기 실행하지 않도록 스레드로 위임한다.
        from services import analysis_supervisor as sup
        await self.conn.execute("INSERT INTO papers VALUES (1, 'analyzing')")
        await ar.upsert_queued(self.conn, 1, ar.utcnow_iso())
        await self.conn.commit()
        to_thread_calls = []

        async def _fake_to_thread(fn, *args, **kwargs):
            to_thread_calls.append((fn, args, kwargs))
            return fn(*args, **kwargs)

        def spawn(pid_, gen_):
            return 999

        with patch("services.analysis_supervisor.asyncio.to_thread", new=_fake_to_thread):
            await sup.reconcile_once(self.conn, cap=2, spawn=spawn)

        self.assertTrue(to_thread_calls, "spawn 호출이 asyncio.to_thread로 위임되지 않음")
        self.assertEqual(to_thread_calls[0][0], spawn)
        self.assertEqual(to_thread_calls[0][1], (1, 1))

    async def test_spawn_failure_requeues(self):
        # spawn 자체가 실패하면 기존대로 queued 복귀(다음 사이클 재시도 가능)
        from services import analysis_supervisor as sup
        await self.conn.execute("INSERT INTO papers VALUES (1, 'analyzing')")
        await ar.upsert_queued(self.conn, 1, ar.utcnow_iso())
        await self.conn.commit()

        def failing_spawn(pid_, gen_):
            raise RuntimeError("exec fail")

        await sup.reconcile_once(self.conn, cap=2, spawn=failing_spawn)
        run = await ar.get_run(self.conn, 1)
        self.assertEqual(run["status"], "queued")


if __name__ == "__main__":
    unittest.main()
