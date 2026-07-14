import os
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()
