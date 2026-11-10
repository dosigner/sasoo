"""Freeze report output and missing-data errors before extracting assembly."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from api import analysis_routes


PAPER = {"title": "합성 논문", "authors": "A, B", "year": 2026}
ROWS = {
    "deep_dive": {
        "phase": "deep_dive", "model_used": "fixture-model", "tokens_in": None,
        "tokens_out": None, "cost_usd": None, "result": "partial",
        "parsed_result": {"_parse_error": "fixture failure", "_raw": "partial"},
    },
    "screening": {
        "phase": "screening", "model_used": "fixture-model", "tokens_in": 1200,
        "tokens_out": 30, "cost_usd": 0.3, "result": "legacy result",
        "parsed_result": {"domain": "physics", "summary": "A synthetic summary."},
    },
}
SNAPSHOT = Path(__file__).parent / "fixtures" / "report_snapshot.md"


async def _report(paper, rows):
    with patch.object(analysis_routes, "fetch_one", new=AsyncMock(return_value=paper)), patch.object(
        analysis_routes, "get_latest_completed_phase_rows", new=AsyncMock(return_value=rows)
    ):
        return await analysis_routes.get_report(7)


def test_report_markdown_bytes():
    response = asyncio.run(_report(PAPER, ROWS))
    assert response.markdown.encode("utf-8") == SNAPSHOT.read_bytes()


def test_report_missing_paper_error():
    with pytest.raises(HTTPException) as error:
        asyncio.run(_report(None, {}))
    assert error.value.status_code == 404
    assert error.value.detail == "Paper 7 not found."


def test_report_missing_results_error():
    with pytest.raises(HTTPException) as error:
        asyncio.run(_report(PAPER, {}))
    assert error.value.status_code == 404
    assert error.value.detail == "No analysis results found for paper 7. Run analysis first."
