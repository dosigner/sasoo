"""
Explicit text/visual artifact status contract helpers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from services.odl_parser import (
    OdlParserError,
    OdlRuntimeError,
    explain_odl_failure,
    get_artifact_refresh_error,
    is_artifact_refresh_running,
    paper_artifact_readiness,
    schedule_paper_artifacts_refresh,
)

from models.database import fetch_one
from services.concurrency import run_pipeline_blocking

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ArtifactStatusContract:
    text_ready: bool
    visual_ready: bool
    visual_state: str
    visual_error: Optional[str]

    @property
    def artifacts_ready(self) -> bool:
        return self.text_ready and self.visual_ready

    @property
    def artifacts_error(self) -> Optional[str]:
        return self.visual_error


async def resolve_artifact_status_contract(
    *,
    paper_id: int,
    paper_dir: Path,
    row_count: int,
    schedule_if_needed: bool = False,
    schedule_error_message: Optional[str] = None,
) -> ArtifactStatusContract:
    """
    Resolve explicit text/visual readiness for paper and figure/table responses.
    """
    visual_error: Optional[str] = None
    try:
        text_ready, visual_ready = await run_pipeline_blocking(paper_artifact_readiness, paper_dir)
    except (OdlParserError, OdlRuntimeError) as exc:
        text_ready = visual_ready = False
        _, visual_error = explain_odl_failure(exc)
        logger.warning("Artifact readiness check failed for paper %s: %s", paper_id, visual_error)

    refresh_error = get_artifact_refresh_error(paper_id)
    if visual_error is None and refresh_error is not None:
        _, visual_error = refresh_error

    refresh_running = is_artifact_refresh_running(paper_id)
    if (
        not visual_ready
        and not refresh_running
        and visual_error is None
        and schedule_if_needed
    ):
        try:
            await schedule_paper_artifacts_refresh(paper_id, paper_dir)
            refresh_running = is_artifact_refresh_running(paper_id)
        except (OdlParserError, OdlRuntimeError) as exc:
            _, visual_error = explain_odl_failure(exc)
        except Exception:
            logger.exception("Failed to schedule visual artifact refresh for paper %s", paper_id)
            visual_error = schedule_error_message or "시각 artifact 동기화를 시작하지 못했습니다."

    if visual_ready:
        visual_state = "ready"
    elif refresh_running:
        visual_state = "running"
    elif visual_error:
        visual_state = "error"
    elif row_count > 0:
        visual_state = "partial"
    else:
        visual_state = "running" if schedule_if_needed else "partial"

    return ArtifactStatusContract(
        text_ready=text_ready,
        visual_ready=visual_ready,
        visual_state=visual_state,
        visual_error=visual_error,
    )


async def get_visual_row_counts(paper_id: int) -> tuple[int, int]:
    row = await fetch_one(
        """
        SELECT
            (
                SELECT COUNT(*)
                FROM figures
                WHERE paper_id = ?
                  AND COALESCE(extraction_status, 'resolved') != 'rejected'
            ) AS figure_count,
            (
                SELECT COUNT(*)
                FROM tables
                WHERE paper_id = ?
                  AND COALESCE(extraction_status, 'resolved') != 'rejected'
            ) AS table_count
        """,
        (paper_id, paper_id),
    )
    return int(row["figure_count"] or 0), int(row["table_count"] or 0)
