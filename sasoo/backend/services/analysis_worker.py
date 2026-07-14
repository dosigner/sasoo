"""Sasoo - 디태치 분석 워커. 같은 번들을 --analyze-paper N --run-generation G로 재실행한 프로세스.

_run_full_analysis(무수정)를 실행하고, 전용 연결 사이드카가 공유 status를 analysis_runs로 fence하며
flush한다. cancel_requested를 폴링해 _cancel_events를 set하고, generation fence 실패 시 self-abort한다.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3

import aiosqlite

from models import analysis_runs as ar

logger = logging.getLogger(__name__)

REPORT_INTERVAL_S = 1.5
SIDE_FAIL_ABORT_S = 20.0
EXIT_OK = 0
EXIT_SELF_ABORT = 75


async def _reporter_and_cancel_bridge(
    paper_id: int, generation: int, main_task: "asyncio.Task",
    conn: aiosqlite.Connection, interval: float = REPORT_INTERVAL_S,
) -> None:
    """공유 status → analysis_runs flush(fence) + cancel_requested → _cancel_events 브리지.

    - fence 실패(rowcount 0 = 재스폰으로 generation 밀림): main_task.cancel() 후 반환(split-brain 방지).
    - transient locked 재시도, 누적 실패가 SIDE_FAIL_ABORT_S 초과 시 리포터 사망=워커 사망(main_task.cancel()).
    """
    from api.analysis_state import _running_analyses, _cancel_events

    fail_streak = 0.0
    while not main_task.done():
        try:
            st = _running_analyses.get(paper_id)
            if st is not None:
                cur_phase = getattr(getattr(st, "current_phase", None), "value", None)
                n = await ar.fenced_heartbeat(
                    conn, paper_id, generation,
                    getattr(st, "overall_status", "running"), cur_phase,
                    float(getattr(st, "progress_pct", 0.0)), ar.utcnow_iso(),
                )
                if n == 0:
                    logger.warning("worker fence lost (paper=%s gen=%s) → self-abort", paper_id, generation)
                    main_task.cancel()
                    return
            run = await ar.get_run(conn, paper_id)
            if run and run.get("cancel_requested"):
                ev = _cancel_events.get(paper_id)
                if ev is not None:
                    ev.set()
            fail_streak = 0.0
        except sqlite3.OperationalError:  # aiosqlite는 sqlite3 예외를 그대로 raise(locked/busy 등 transient)
            fail_streak += interval
            if fail_streak >= SIDE_FAIL_ABORT_S:
                logger.error("worker reporter DB failure > %ss → self-abort (paper=%s)", SIDE_FAIL_ABORT_S, paper_id)
                main_task.cancel()
                return
        except asyncio.CancelledError:  # 정상 종료 경로(run_analysis_worker의 side.cancel()) — 삼키지 않는다
            raise
        except Exception:  # noqa: BLE001
            # "리포터 사망 = 워커 사망". 사이드카만 죽고 본 분석이 계속 돌면 heartbeat가 끊겨
            # 리컨실러가 false-stale로 판정하고 같은 논문에 두 번째 워커를 스폰한다(이중 실행·중복 과금).
            logger.exception("worker reporter 예기치 못한 오류 → self-abort (paper=%s)", paper_id)
            main_task.cancel()
            return
        await asyncio.sleep(interval)


async def run_analysis_worker(paper_id: int, generation: int) -> int:
    from main import bootstrap_runtime
    from models.database import get_db, open_side_connection
    from api.analysis_routes import _run_full_analysis

    await bootstrap_runtime(worker=True)
    side_conn = await open_side_connection()
    main_task = asyncio.create_task(_run_full_analysis(paper_id))
    side = asyncio.create_task(_reporter_and_cancel_bridge(paper_id, generation, main_task, side_conn))

    # 안전망: 루프 내 except가 놓친 경로(루프 밖 예외 등)로 사이드카가 죽어도 본 분석을 중단시킨다.
    # heartbeat 없는 채 계속 도는 워커는 리컨실러에 stale로 보여 이중 스폰을 유발한다.
    def _side_died(t: "asyncio.Task") -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None and not main_task.done():
            logger.error("사이드카 비정상 종료 — 본 분석 중단(false-stale 재스폰 방지): %r", exc)
            main_task.cancel()

    side.add_done_callback(_side_died)
    exit_code = EXIT_OK
    try:
        await main_task
    except asyncio.CancelledError:
        exit_code = EXIT_SELF_ABORT  # fence 밀림/리포터 사망: terminal write 하지 않는다
        return exit_code
    finally:
        side.cancel()
        if exit_code == EXIT_OK:
            # papers.status(진실원)를 읽어 analysis_runs.status를 fence하에 확정
            try:
                row = await (await get_db()).execute("SELECT status FROM papers WHERE id=?", (paper_id,))
                paper = await row.fetchone()
                terminal = (paper["status"] if paper else "error")
                await ar.finalize_run(side_conn, paper_id, generation, terminal, ar.utcnow_iso())
            except Exception as exc:  # noqa: BLE001
                logger.warning("worker finalize failed (paper=%s): %s", paper_id, exc)
        await side_conn.close()
    return exit_code
