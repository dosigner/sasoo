import asyncio
import os
import sys
import tempfile
import types
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

    async def test_reporter_flushes_heartbeat_even_without_shared_status(self):
        """I5: 공유 status(_running_analyses)가 없으면 heartbeat/fence 검사 자체를 건너뛰던 문제.

        지금은 _run_full_analysis가 첫 await 전에 등록해 무해하지만, 그 함수(무수정 대상)의
        내부 순서에 암묵 의존한다. 등록이 뒤로 밀리면 heartbeat 없이 45초 후 false-stale
        재스폰(이중 워커)이 일어난다 — st가 None이어도 폴백 값으로 heartbeat를 계속 찍어야 한다.
        """
        from services import analysis_worker
        from api import analysis_state
        pid, gen = self.claimed
        analysis_state._running_analyses.pop(1, None)   # 공유 status 미등록 상태를 재현

        calls: list = []
        orig_fenced_heartbeat = ar.fenced_heartbeat

        async def _tracking_heartbeat(*args, **kwargs):
            calls.append(args)
            return await orig_fenced_heartbeat(*args, **kwargs)

        async def _fake_main():
            await asyncio.sleep(0.05)

        main_task = asyncio.create_task(_fake_main())
        with patch("services.analysis_worker.ar.fenced_heartbeat", new=_tracking_heartbeat):
            side = asyncio.create_task(
                analysis_worker._reporter_and_cancel_bridge(1, gen, main_task, self.conn, interval=0.01)
            )
            await main_task
            side.cancel()

        self.assertTrue(
            calls, "st가 None이어도 fenced_heartbeat가 호출돼야 한다(heartbeat 갱신·fence 감지 지속)"
        )
        run = await ar.get_run(self.conn, 1)
        self.assertEqual(run["status"], "running")

    async def test_bridge_self_aborts_on_fence_loss_without_shared_status(self):
        """I5: 공유 status가 없어도 fence 실패(generation 밀림)를 감지해 self-abort해야 한다."""
        from services import analysis_worker
        from api import analysis_state
        pid, gen = self.claimed
        analysis_state._running_analyses.pop(1, None)   # 공유 status 미등록
        await self.conn.execute("UPDATE analysis_runs SET generation=generation+1 WHERE paper_id=1")
        await self.conn.commit()

        async def _fake_main():
            await asyncio.sleep(1.0)

        main_task = asyncio.create_task(_fake_main())
        side = asyncio.create_task(
            analysis_worker._reporter_and_cancel_bridge(1, gen, main_task, self.conn, interval=0.01)
        )
        try:
            await asyncio.wait_for(main_task, timeout=1.0)
        except asyncio.CancelledError:
            pass
        self.assertTrue(main_task.cancelled())
        side.cancel()

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


class WorkerShutdownTests(unittest.IsolatedAsyncioTestCase):
    """워커 프로세스가 실제로 종료되는지(=DB 연결을 모두 닫는지)를 고정한다."""

    async def asyncSetUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); self.tmp.close()
        self.conn = await aiosqlite.connect(self.tmp.name); self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript("CREATE TABLE papers (id INTEGER PRIMARY KEY, status TEXT);")
        await self.conn.executescript(ar.ANALYSIS_RUNS_DDL); await self.conn.commit()
        await self.conn.execute("INSERT INTO papers VALUES (1,'completed')")
        await ar.upsert_queued(self.conn, 1, ar.utcnow_iso())
        self.claimed = await ar.claim_next(self.conn, 3, ar.utcnow_iso(),
                                           "2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", 3)

    async def asyncTearDown(self):
        await self.conn.close(); os.unlink(self.tmp.name)

    async def _run_worker(self, generation: int, closed: list, main_impl) -> int:
        """run_analysis_worker를 실 DB 연결 없이 구동(bootstrap/_run_full_analysis/연결을 mock)."""
        from services import analysis_worker

        side_conn = await aiosqlite.connect(self.tmp.name)
        side_conn.row_factory = aiosqlite.Row

        async def _fake_close_db():
            closed.append(True)

        # run_analysis_worker는 호출 시점에 `from main import bootstrap_runtime`을 한다.
        # 실제 main 모듈을 import하면 FastAPI 앱이 조립되는데, 다른 테스트가 sys.modules에
        # 라우터 스텁을 심어둔 세션에서는 그게 깨진다(import 순서 의존). 스텁 main을 sys.modules에
        # 끼워 넣어 실제 main을 건드리지 않는다.
        #
        # patch.dict(sys.modules, ...)를 쓰지 않는다: 해제 시 sys.modules 전체를 clear 후
        # 복원하는데, 살아 있는 aiosqlite 백그라운드 스레드가 그 순간 모듈을 참조하면
        # 인터프리터가 segfault한다(실측: python 3.14 + aiosqlite _connection_worker_thread).
        # 단일 키만 교체/복원하면 dict clear가 없어 안전하다.
        stub_main = types.ModuleType("main")
        stub_main.bootstrap_runtime = AsyncMock()
        had_main = "main" in sys.modules
        prev_main = sys.modules.get("main")
        sys.modules["main"] = stub_main

        try:
            with (
                patch("models.database.open_side_connection", new=AsyncMock(return_value=side_conn)),
                patch("models.database.get_db", new=AsyncMock(return_value=self.conn)),
                patch("api.analysis_routes._run_full_analysis", new=main_impl),
                patch("services.analysis_worker.close_db", new=_fake_close_db),
            ):
                return await analysis_worker.run_analysis_worker(1, generation)
        finally:
            if had_main:
                sys.modules["main"] = prev_main
            else:
                sys.modules.pop("main", None)

    async def test_worker_closes_main_db_connection_before_exit(self):
        # aiosqlite Connection은 non-daemon 스레드다. 닫지 않으면 asyncio.run()이 끝나고
        # sys.exit()가 불려도 인터프리터가 그 스레드를 join하느라 프로세스가 죽지 못한다.
        from services import analysis_worker
        _pid, gen = self.claimed
        closed: list = []

        async def _fake_main(paper_id):
            return None

        code = await self._run_worker(gen, closed, _fake_main)

        self.assertEqual(code, analysis_worker.EXIT_OK)
        self.assertTrue(closed, "close_db()가 호출되지 않음 — 워커 프로세스가 종료되지 못한다")

    async def test_worker_closes_main_db_connection_on_self_abort(self):
        # fence 불일치(self-abort) 경로에서도 연결이 닫혀야 한다 — 안 닫히면 좀비가 누적된다.
        from services import analysis_worker
        from api import analysis_state
        closed: list = []

        # 사이드카가 fence를 검사하려면 공유 status가 있어야 한다(_run_full_analysis가 등록하는 것).
        analysis_state._running_analyses[1] = type("S", (), {
            "overall_status": "running", "current_phase": None, "progress_pct": 1.0})()

        async def _fake_main(paper_id):
            await asyncio.sleep(2.0)  # 사이드카가 fence 불일치로 취소하기 전엔 안 끝남

        try:
            code = await self._run_worker(999, closed, _fake_main)  # generation 불일치 → self-abort
        finally:
            analysis_state._running_analyses.pop(1, None)

        self.assertEqual(code, analysis_worker.EXIT_SELF_ABORT)
        self.assertTrue(closed, "self-abort 경로에서 close_db()가 호출되지 않음")

    async def test_worker_awaits_sidecar_after_cancel(self):
        """M5: side.cancel() 뒤 asyncio.gather로 실제 종료를 기다려야 한다.

        기다리지 않으면 side task가 완전히 멈추기 전에 side_conn.close()/close_db()가
        불려 레이스가 생기고, 잡히지 않은 예외가 있으면 'Task exception was never
        retrieved' 경고로 이어진다(종료 비결정론).
        """
        from services import analysis_worker
        _pid, gen = self.claimed
        closed: list = []

        async def _fake_main(paper_id):
            return None

        gather_calls: list = []
        orig_gather = asyncio.gather

        async def _tracking_gather(*args, **kwargs):
            gather_calls.append((args, kwargs))
            return await orig_gather(*args, **kwargs)

        with patch("services.analysis_worker.asyncio.gather", new=_tracking_gather):
            await self._run_worker(gen, closed, _fake_main)

        self.assertTrue(gather_calls, "side.cancel() 후 asyncio.gather로 종료를 기다리지 않음")
        self.assertEqual(gather_calls[0][1].get("return_exceptions"), True)


if __name__ == "__main__":
    unittest.main()
