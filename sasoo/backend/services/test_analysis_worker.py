import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import aiosqlite

from models import analysis_runs as ar


class ReporterBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); self.tmp.close()
        self.conn = await aiosqlite.connect(self.tmp.name); self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript("CREATE TABLE papers (id INTEGER PRIMARY KEY, status TEXT);")
        await self.conn.executescript(ar.ANALYSIS_RUNS_DDL); await self.conn.commit()
        await self.conn.execute("INSERT INTO papers VALUES (1,'analyzing')")
        await ar.upsert_queued(self.conn, 1, ar.utcnow_iso())
        self.claimed = await ar.claim_next(self.conn, 3, ar.utcnow_iso(),
                                           "2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", 3)

    async def asyncTearDown(self):
        await self.conn.close(); os.unlink(self.tmp.name)

    async def test_reporter_flushes_shared_status(self):
        from services import analysis_worker
        from api import analysis_state
        pid, gen = self.claimed

        class _St:  # AnalysisStatus 스텁(공유 객체)
            overall_status = "running"
            class current_phase:  # enum 스텁
                value = "screening"
            progress_pct = 42.0

        analysis_state._running_analyses[1] = _St()

        async def _fake_main():
            await asyncio.sleep(0.05)  # 리포터가 최소 1회 flush할 시간

        main_task = asyncio.create_task(_fake_main())
        side = asyncio.create_task(
            analysis_worker._reporter_and_cancel_bridge(1, gen, main_task, self.conn, interval=0.01)
        )
        await main_task; side.cancel()
        analysis_state._running_analyses.pop(1, None)

        run = await ar.get_run(self.conn, 1)
        self.assertEqual(run["current_phase"], "screening")
        self.assertEqual(run["progress_pct"], 42.0)

    async def test_bridge_sets_cancel_event_on_flag(self):
        from services import analysis_worker
        from api import analysis_state
        pid, gen = self.claimed
        ev = asyncio.Event(); analysis_state._cancel_events[1] = ev
        await ar.request_cancel(self.conn, 1)

        async def _fake_main():
            await asyncio.sleep(0.05)

        main_task = asyncio.create_task(_fake_main())
        side = asyncio.create_task(
            analysis_worker._reporter_and_cancel_bridge(1, gen, main_task, self.conn, interval=0.01)
        )
        await main_task; side.cancel()
        analysis_state._cancel_events.pop(1, None)
        self.assertTrue(ev.is_set())

    async def test_bridge_self_aborts_on_generation_fence(self):
        from services import analysis_worker
        from api import analysis_state
        pid, gen = self.claimed
        analysis_state._running_analyses[1] = type("S", (), {
            "overall_status": "running", "current_phase": None, "progress_pct": 1.0})()
        # 다른 프로세스가 재스폰한 것처럼 generation을 밀어버림
        await self.conn.execute("UPDATE analysis_runs SET generation=generation+1 WHERE paper_id=1")
        await self.conn.commit()

        async def _fake_main():
            await asyncio.sleep(1.0)  # 리포터가 fence 실패로 cancel하기 전엔 안 끝남

        main_task = asyncio.create_task(_fake_main())
        side = asyncio.create_task(
            analysis_worker._reporter_and_cancel_bridge(1, gen, main_task, self.conn, interval=0.01)
        )
        try:
            await asyncio.wait_for(main_task, timeout=1.0)
        except asyncio.CancelledError:
            pass
        analysis_state._running_analyses.pop(1, None)
        self.assertTrue(main_task.cancelled())

    async def test_sidecar_unexpected_exception_aborts_main_task(self):
        """사이드카가 OperationalError 아닌 예외로 죽으면 본 분석도 중단돼야 한다.

        죽은 채 방치되면 heartbeat가 멈추고 → 리컨실러가 false-stale로 판정 →
        같은 논문에 두 번째 워커를 스폰한다(이중 실행·중복 과금).
        """
        from services import analysis_worker
        from api import analysis_state
        pid, gen = self.claimed
        analysis_state._running_analyses[1] = type("S", (), {
            "overall_status": "running", "current_phase": None, "progress_pct": 1.0})()

        async def _fake_main():
            await asyncio.sleep(1.0)  # 사이드카가 중단시키기 전엔 안 끝남

        main_task = asyncio.create_task(_fake_main())
        with patch("services.analysis_worker.ar.fenced_heartbeat",
                   new=AsyncMock(side_effect=RuntimeError("unexpected sidecar bug"))):
            side = asyncio.create_task(
                analysis_worker._reporter_and_cancel_bridge(1, gen, main_task, self.conn, interval=0.01)
            )
            try:
                await asyncio.wait_for(main_task, timeout=1.0)
            except asyncio.CancelledError:
                pass
            await side  # 사이드카는 본 태스크를 죽인 뒤 스스로 조용히 종료한다

        analysis_state._running_analyses.pop(1, None)
        self.assertTrue(main_task.cancelled())


if __name__ == "__main__":
    unittest.main()
