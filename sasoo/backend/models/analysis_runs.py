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


async def upsert_queued(conn: aiosqlite.Connection, paper_id: int, now: str) -> None:
    """신규 /run: 큐 삽입 또는 기존 행을 새 실행으로 리셋(generation은 유지 — claim이 +1)."""
    await conn.execute(
        """
        INSERT INTO analysis_runs (paper_id, status, generation, current_phase, progress_pct,
                                   cancel_requested, attempts, pid, error_message,
                                   started_at, last_attempt_at, heartbeat_at, updated_at)
        VALUES (?, 'queued', 0, NULL, 0, 0, 0, NULL, NULL, ?, NULL, NULL, ?)
        ON CONFLICT(paper_id) DO UPDATE SET
            status='queued', current_phase=NULL, progress_pct=0, cancel_requested=0,
            attempts=0, pid=NULL, error_message=NULL, started_at=excluded.started_at,
            last_attempt_at=NULL, heartbeat_at=NULL, updated_at=excluded.updated_at
        """,
        (paper_id, now, now),
    )
    await conn.commit()


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


async def get_run(conn: aiosqlite.Connection, paper_id: int) -> Optional[dict]:
    cur = await conn.execute("SELECT * FROM analysis_runs WHERE paper_id=?", (paper_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def reconcile_stale(
    conn: aiosqlite.Connection, stale_cut: str, max_attempts: int, now: str,
) -> None:
    """stale running을 우선순위로 조정: papers-terminal > cancel > attempts-error > requeue."""
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
