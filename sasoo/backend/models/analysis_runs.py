"""Sasoo - analysis_runs: 서버↔디태치 워커 조율 테이블(진행률·취소·generation fence·heartbeat 리스).

모든 저수준 함수는 aiosqlite 연결을 주입받고, 시간은 iso 문자열 인자로 받는다(테스트 결정론).
claim은 cap predicate를 포함한 단일 UPDATE...RETURNING으로 원자화한다(sqlite 3.35+/실측 3.53.3).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import aiosqlite

ANALYSIS_RUNS_DDL = """
CREATE TABLE IF NOT EXISTS analysis_runs (
    paper_id         INTEGER PRIMARY KEY,
    status           TEXT NOT NULL DEFAULT 'queued',
    generation       INTEGER NOT NULL DEFAULT 0,
    current_phase    TEXT,
    progress_pct     REAL NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    attempts         INTEGER NOT NULL DEFAULT 0,
    pid              INTEGER,
    error_message    TEXT,
    started_at       TEXT,
    last_attempt_at  TEXT,
    heartbeat_at     TEXT,
    updated_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_status ON analysis_runs(status, heartbeat_at);
"""


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def upsert_queued(conn: aiosqlite.Connection, paper_id: int, now: str) -> bool:
    """신규 /run: 큐 삽입 또는 기존 행을 새 실행으로 리셋(generation은 유지 — claim이 +1).

    결함2(I3 TOCTOU): 409 가드(get_run 스냅샷)와 이 호출 사이에 DB I/O await가 여럿 끼어
    있어 동시 이중 /run이 둘 다 가드를 통과할 수 있다. DO UPDATE에
    `WHERE status NOT IN ('queued','running')` 원자 가드를 걸어, 이미 진행 중인 run 위에
    리셋이 덮어써지는 것(→ 즉시 재claim → 두 번째 워커 스폰)을 DB 레벨에서 막는다.
    이미 queued/running이면 아무 것도 갱신하지 않고 False를 반환 — 호출부(/run)가 이를
    409로 변환해야 한다. rowcount>0(신규 삽입 또는 terminal→queued 리셋)이면 True.
    """
    cur = await conn.execute(
        """
        INSERT INTO analysis_runs (paper_id, status, generation, current_phase, progress_pct,
                                   cancel_requested, attempts, pid, error_message,
                                   started_at, last_attempt_at, heartbeat_at, updated_at)
        VALUES (?, 'queued', 0, NULL, 0, 0, 0, NULL, NULL, ?, NULL, NULL, ?)
        ON CONFLICT(paper_id) DO UPDATE SET
            status='queued', current_phase=NULL, progress_pct=0, cancel_requested=0,
            attempts=0, pid=NULL, error_message=NULL, started_at=excluded.started_at,
            last_attempt_at=NULL, heartbeat_at=NULL, updated_at=excluded.updated_at
        WHERE analysis_runs.status NOT IN ('queued', 'running')
        """,
        (paper_id, now, now),
    )
    await conn.commit()
    return cur.rowcount > 0


async def claim_next(
    conn: aiosqlite.Connection, cap: int, now: str, fresh_cut: str,
    backoff_cut: str, max_attempts: int,
) -> Optional[tuple[int, int]]:
    """cap 미만이면 다음 queued 후보 1개를 running으로 원자 전이하고 (paper_id, new_generation)."""
    cur = await conn.execute(
        """
        UPDATE analysis_runs
        SET status='running', generation=generation+1, attempts=attempts+1,
            last_attempt_at=?, heartbeat_at=?, pid=NULL, current_phase=NULL, progress_pct=0,
            updated_at=?
        WHERE paper_id = (
            SELECT paper_id FROM analysis_runs
            WHERE status='queued' AND cancel_requested=0 AND attempts < ?
              AND (last_attempt_at IS NULL OR last_attempt_at < ?)
              AND EXISTS (SELECT 1 FROM papers p WHERE p.id = analysis_runs.paper_id)
            ORDER BY started_at LIMIT 1
        )
        AND (SELECT COUNT(*) FROM analysis_runs
             WHERE status='running' AND heartbeat_at IS NOT NULL AND heartbeat_at > ?) < ?
        RETURNING paper_id, generation
        """,
        (now, now, now, max_attempts, backoff_cut, fresh_cut, cap),
    )
    row = await cur.fetchone()
    await conn.commit()
    if row is None:
        return None
    return (row[0], row[1])


async def set_pid(conn: aiosqlite.Connection, paper_id: int, generation: int, pid: int) -> None:
    await conn.execute(
        "UPDATE analysis_runs SET pid=? WHERE paper_id=? AND generation=?",
        (pid, paper_id, generation),
    )
    await conn.commit()


async def fenced_heartbeat(
    conn: aiosqlite.Connection, paper_id: int, generation: int, status: str,
    current_phase: Optional[str], progress_pct: float, now: str,
) -> int:
    cur = await conn.execute(
        "UPDATE analysis_runs SET status=?, current_phase=?, progress_pct=?, heartbeat_at=?, "
        "updated_at=? WHERE paper_id=? AND generation=?",
        (status, current_phase, progress_pct, now, now, paper_id, generation),
    )
    await conn.commit()
    return cur.rowcount


async def finalize_run(
    conn: aiosqlite.Connection, paper_id: int, generation: int, terminal_status: str,
    now: str, error_message: Optional[str] = None,
) -> int:
    cur = await conn.execute(
        "UPDATE analysis_runs SET status=?, error_message=?, heartbeat_at=?, updated_at=? "
        "WHERE paper_id=? AND generation=?",
        (terminal_status, error_message, now, now, paper_id, generation),
    )
    await conn.commit()
    return cur.rowcount


async def request_cancel(conn: aiosqlite.Connection, paper_id: int) -> int:
    cur = await conn.execute(
        "UPDATE analysis_runs SET cancel_requested=1 WHERE paper_id=?", (paper_id,)
    )
    await conn.commit()
    return cur.rowcount


async def cancel_queued_now(conn: aiosqlite.Connection, paper_id: int, now: str) -> int:
    """queued 상태의 run을 원자적으로 즉시 cancelled로 전이한다.

    rowcount>0이면 아직 워커가 뜨지 않은 상태에서 즉시 취소됐다는 뜻이라 /cancel이
    바로 응답할 수 있다. rowcount 0이면 이미 running(또는 없음)이라 호출부가
    request_cancel 폴백으로 넘어가야 한다."""
    cur = await conn.execute(
        "UPDATE analysis_runs SET status='cancelled', cancel_requested=1, updated_at=? "
        "WHERE paper_id=? AND status='queued'",
        (now, paper_id),
    )
    await conn.commit()
    return cur.rowcount


async def sweep_cancelled_queued(conn: aiosqlite.Connection, now: str) -> list[int]:
    """cap 초과로 queued에 머문 채 cancel_requested=1만 세워진 행을 cancelled로 확정한다.

    claim_next(cancel_requested=0 필터)·reconcile_stale(status='running'만 봄)·
    mark_over_attempts_error(attempts만 봄) 중 그 플래그를 소비하는 경로가 없어
    행이 queued로 영구 고착되던 문제(C1)의 리컨실러측 수정. 단일 writer인
    리컨실러 루프에서 주기 호출한다."""
    cur = await conn.execute(
        "SELECT paper_id FROM analysis_runs WHERE status='queued' AND cancel_requested=1"
    )
    ids = [r[0] for r in await cur.fetchall()]
    if ids:
        await conn.execute(
            "UPDATE papers SET status='cancelled' WHERE id IN "
            "(SELECT paper_id FROM analysis_runs WHERE status='queued' AND cancel_requested=1)"
        )
        await conn.execute(
            "UPDATE analysis_runs SET status='cancelled', updated_at=? "
            "WHERE status='queued' AND cancel_requested=1",
            (now,),
        )
        await conn.commit()
    return ids


async def sweep_orphan_analyzing_papers(conn: aiosqlite.Connection) -> list[int]:
    """결함1: run이 terminal(cancelled/error/completed)인데 papers가 'analyzing'에 고착된
    좀비를 역방향으로 동기화한다.

    reconcile_stale ②(cancel-wins)는 analysis_runs만 쓰고 papers를 안 건드린다(③ error는
    papers도 씀 — ②만 빠짐). 그 외에도 (i) /cancel이 cancel_queued_now 성공 직후 papers
    UPDATE 전에 죽는 경합, (ii) /run이 papers='analyzing' 기록 후 upsert_queued 실패로
    이전 terminal run 행이 남는 경합이 같은 증상(run=terminal, papers='analyzing' 영구
    고착 → seed_legacy는 run 행이 있으면 시딩 안 하므로 재기동으로도 자가 치유 불가)을
    낳는다. run이 terminal이면 papers를 그 상태로 강제 동기화해 좀비를 회수한다.
    status='running'인 run은 건드리지 않는다(정상 진행 중 보호)."""
    cur = await conn.execute(
        "SELECT paper_id FROM analysis_runs WHERE status IN ('cancelled','error','completed') "
        "AND paper_id IN (SELECT id FROM papers WHERE status='analyzing')"
    )
    ids = [r[0] for r in await cur.fetchall()]
    if ids:
        for status in ("cancelled", "error", "completed"):
            await conn.execute(
                "UPDATE papers SET status=? WHERE status='analyzing' AND id IN "
                "(SELECT paper_id FROM analysis_runs WHERE status=?)",
                (status, status),
            )
        await conn.commit()
    return ids


async def get_run(conn: aiosqlite.Connection, paper_id: int) -> Optional[dict]:
    cur = await conn.execute("SELECT * FROM analysis_runs WHERE paper_id=?", (paper_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def reconcile_stale(
    conn: aiosqlite.Connection, stale_cut: str, max_attempts: int, now: str,
) -> None:
    """stale running을 우선순위로 조정: papers-terminal > cancel > attempts-error > requeue.

    비-fence 스윕: stale 판정(45s 무heartbeat) 자체가 살아있는 fenced writer 부재를 함의하므로 안전.
    워커 대면 프리미티브(fenced_heartbeat/finalize_run)와 구분된 경로.
    """
    # ① papers가 terminal이면 그 값으로 finalize(requeue 금지)
    await conn.execute(
        "UPDATE analysis_runs SET status=(SELECT status FROM papers WHERE papers.id=analysis_runs.paper_id), "
        "updated_at=? WHERE status='running' AND heartbeat_at < ? "
        "AND (SELECT status FROM papers WHERE papers.id=analysis_runs.paper_id) "
        "IN ('completed','error','cancelled')",
        (now, stale_cut),
    )
    # ② cancel-wins
    await conn.execute(
        "UPDATE analysis_runs SET status='cancelled', updated_at=? "
        "WHERE status='running' AND heartbeat_at < ? AND cancel_requested=1",
        (now, stale_cut),
    )
    # ③ attempts 초과 running-stale → error(+papers error)
    await conn.execute(
        "UPDATE papers SET status='error' WHERE id IN "
        "(SELECT paper_id FROM analysis_runs WHERE status='running' AND heartbeat_at < ? AND attempts >= ?)",
        (stale_cut, max_attempts),
    )
    await conn.execute(
        "UPDATE analysis_runs SET status='error', error_message='max_attempts', updated_at=? "
        "WHERE status='running' AND heartbeat_at < ? AND attempts >= ?",
        (now, stale_cut, max_attempts),
    )
    # ④ 나머지 running-stale → queued
    await conn.execute(
        "UPDATE analysis_runs SET status='queued', updated_at=? WHERE status='running' AND heartbeat_at < ?",
        (now, stale_cut),
    )
    await conn.commit()


async def mark_over_attempts_error(conn: aiosqlite.Connection, max_attempts: int) -> list[int]:
    """attempts 초과 queued를 error로(claim 후보에서 영구 제외). 대상 paper_id 반환."""
    cur = await conn.execute(
        "SELECT paper_id FROM analysis_runs WHERE status='queued' AND attempts >= ?", (max_attempts,)
    )
    ids = [r[0] for r in await cur.fetchall()]
    if ids:
        await conn.execute(
            "UPDATE analysis_runs SET status='error', error_message='max_attempts' "
            "WHERE status='queued' AND attempts >= ?", (max_attempts,)
        )
        await conn.executemany("UPDATE papers SET status='error' WHERE id=?", [(i,) for i in ids])
        await conn.commit()
    return ids


async def seed_legacy(conn: aiosqlite.Connection, now: str) -> int:
    """runs 행이 없는 papers.status='analyzing'(구버전/inprocess 크래시 잔재)에 queued 행 시드."""
    cur = await conn.execute(
        """
        INSERT INTO analysis_runs (paper_id, status, generation, progress_pct, cancel_requested,
                                   attempts, started_at, updated_at)
        SELECT p.id, 'queued', 0, 0, 0, 0, ?, ?
        FROM papers p
        WHERE p.status='analyzing'
          AND NOT EXISTS (SELECT 1 FROM analysis_runs r WHERE r.paper_id = p.id)
        """,
        (now, now),
    )
    await conn.commit()
    return cur.rowcount
