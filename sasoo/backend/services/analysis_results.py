"""
Semantic readers for latest completed analysis_results rows.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Sequence

from models.database import fetch_all, fetch_one


def parse_phase_row(row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """Attach a parsed_result payload to an analysis_results row."""
    if row is None:
        return None

    parsed = dict(row)
    result_text = parsed.get("result")
    try:
        parsed["parsed_result"] = json.loads(result_text)
    except (TypeError, json.JSONDecodeError):
        parsed["parsed_result"] = {"raw_text": result_text}
    return parsed


async def get_latest_completed_phase_row(
    paper_id: int,
    phase: str,
) -> Optional[dict[str, Any]]:
    """
    Return the newest non-error row for a paper/phase.

    Ties are broken by id DESC so reruns with identical timestamps are stable.
    """
    row = await fetch_one(
        """
        SELECT *
        FROM analysis_results
        WHERE paper_id = ? AND phase = ? AND phase != 'error'
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (paper_id, phase),
    )
    return parse_phase_row(row)


async def get_latest_completed_phase_rows(
    paper_id: int,
    phases: Optional[Sequence[str]] = None,
) -> dict[str, dict[str, Any]]:
    """
    Return at most one newest non-error row per phase for a paper.

    Results are keyed by phase name.
    """
    params: list[Any] = [paper_id]
    where = ["paper_id = ?", "phase != 'error'"]
    if phases:
        placeholders = ", ".join("?" for _ in phases)
        where.append(f"phase IN ({placeholders})")
        params.extend(phases)

    rows = await fetch_all(
        f"""
        SELECT *
        FROM analysis_results
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY phase ORDER BY created_at DESC, id DESC
                ) AS phase_rank
                FROM analysis_results
                WHERE {" AND ".join(where)}
            ) WHERE phase_rank = 1
        )
        ORDER BY created_at DESC, id DESC
        """,
        tuple(params),
    )

    latest_by_phase: dict[str, dict[str, Any]] = {}
    for row in rows:
        phase = str(row.get("phase") or "")
        if not phase or phase == "error" or phase in latest_by_phase:
            continue
        parsed = parse_phase_row(row)
        if parsed is not None:
            latest_by_phase[phase] = parsed
    return latest_by_phase
