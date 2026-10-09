"""토의 기록 저장소(discussion_messages).

논문당 토의는 하나다. 맥락 초기화는 kind='reset' 행으로 남기고, 마지막 reset 이후의
user와 complete sasoo 행만 사수에게 맥락으로 보낸다. 끊긴 답(interrupted)은 기록에는
남기되 맥락에서는 뺀다. 설계: docs/superpowers/specs/2026-10-07-discussion-design.md 6~7장.
"""

from __future__ import annotations

from typing import Optional

from models.database import execute_insert, execute_update, fetch_all, fetch_one

CONTEXT_BUDGET_TOKENS = 260_000
# 이 추정값을 넘을 때만 프로바이더 계산 API로 센다(평소 턴은 왕복을 늘리지 않는다).
PRECOUNT_THRESHOLD_TOKENS = 234_000

RESET_MANUAL = "manual"
RESET_REANALYSIS = "reanalysis"
RESET_BUDGET = "budget"


async def list_messages(paper_id: int) -> list[dict]:
    return await fetch_all(
        "SELECT * FROM discussion_messages WHERE paper_id = ? ORDER BY id", (paper_id,)
    )


async def _last_reset_id(paper_id: int) -> int:
    row = await fetch_one(
        "SELECT MAX(id) AS id FROM discussion_messages WHERE paper_id = ? AND kind = 'reset'",
        (paper_id,),
    )
    return int(row["id"] or 0) if row else 0


async def active_context(paper_id: int) -> list[dict]:
    """마지막 맥락 초기화 이후 사수에게 보낼 메시지(질문과 완료된 답)."""
    return await fetch_all(
        """
        SELECT * FROM discussion_messages
        WHERE paper_id = ? AND id > ?
          AND (kind = 'user' OR (kind = 'sasoo' AND status = 'complete'))
        ORDER BY id
        """,
        (paper_id, await _last_reset_id(paper_id)),
    )


async def last_usage(paper_id: int) -> Optional[dict]:
    """마지막 초기화 이후 마지막 완료된 답의 실제 입력 토큰과 그 답의 길이."""
    return await fetch_one(
        """
        SELECT tokens_in, LENGTH(content) AS answer_chars FROM discussion_messages
        WHERE paper_id = ? AND id > ? AND kind = 'sasoo' AND status = 'complete'
          AND tokens_in IS NOT NULL
        ORDER BY id DESC LIMIT 1
        """,
        (paper_id, await _last_reset_id(paper_id)),
    )


def estimate_next_input(usage: Optional[dict], message: str) -> int:
    """다음 요청 입력 토큰의 보수적 추정. 글자 하나를 토큰 하나로 본다."""
    if not usage:
        return 0
    return int(usage["tokens_in"]) + int(usage["answer_chars"] or 0) + len(message)


async def append_user(paper_id: int, content: str) -> int:
    return await execute_insert(
        "INSERT INTO discussion_messages (paper_id, kind, content) VALUES (?, 'user', ?)",
        (paper_id, content),
    )


async def append_sasoo(
    paper_id: int,
    content: str,
    *,
    status: str,
    model_used: Optional[str] = None,
    tokens_in: Optional[int] = None,
    tokens_out: Optional[int] = None,
    cost_usd: Optional[float] = None,
) -> int:
    return await execute_insert(
        """
        INSERT INTO discussion_messages
            (paper_id, kind, content, status, model_used, tokens_in, tokens_out, cost_usd)
        VALUES (?, 'sasoo', ?, ?, ?, ?, ?, ?)
        """,
        (paper_id, content, status, model_used, tokens_in, tokens_out, cost_usd),
    )


async def append_reset(paper_id: int, reason: str) -> dict:
    row_id = await execute_insert(
        "INSERT INTO discussion_messages (paper_id, kind, status, reset_reason) VALUES (?, 'reset', 'complete', ?)",
        (paper_id, reason),
    )
    return await fetch_one("SELECT * FROM discussion_messages WHERE id = ?", (row_id,))


async def delete_all(paper_id: int) -> int:
    return await execute_update("DELETE FROM discussion_messages WHERE paper_id = ?", (paper_id,))


async def reanalysis_reset_needed(paper_id: int) -> bool:
    """맥락에 있던 분석 결과가 재분석으로 바뀌었는지.

    마지막 초기화 이후 메시지가 있고, 어떤 phase의 최신 결과가 마지막 메시지보다 늦게
    만들어졌는데 같은 phase의 이전 결과가 그 메시지 전에 이미 있었으면 참이다. 분석이
    진행되는 도중에 처음 끝난 단계는 새 맥락을 더할 뿐이라 초기화하지 않는다.
    """
    last = await fetch_one(
        """
        SELECT MAX(created_at) AS at FROM discussion_messages
        WHERE paper_id = ? AND id > ? AND kind IN ('user', 'sasoo')
        """,
        (paper_id, await _last_reset_id(paper_id)),
    )
    if not last or not last["at"]:
        return False
    row = await fetch_one(
        """
        SELECT 1 FROM analysis_results newer
        WHERE newer.paper_id = ? AND newer.phase != 'error' AND newer.created_at > ?
          AND EXISTS (
            SELECT 1 FROM analysis_results older
            WHERE older.paper_id = newer.paper_id AND older.phase = newer.phase
              AND older.created_at <= ?
          )
        LIMIT 1
        """,
        (paper_id, last["at"], last["at"]),
    )
    return row is not None
