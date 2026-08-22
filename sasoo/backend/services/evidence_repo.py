"""evidence_repo — 결정론적 검증기(순수 계층)와 evidence_anchors 사이의 얇은 결합 계층.

- 검증기는 DB를 모른다. 이 모듈만 DB를 안다.
- CPU 바운드 문자열 연산은 run_pipeline_blocking으로 이벤트 루프 밖에서 돌린다.
- 앵커 부재 = 미검증이 UI 계약이므로, 여기서 실패해도 recipe 데이터는 그대로 남는다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any, Optional

from models.database import get_db
from models.evidence_anchors import anchor_versions, fetch_anchors, upsert_anchors
from services.concurrency import run_pipeline_blocking
from services.evidence_verifier import (
    EVIDENCE_NORMALIZER_VERSION,
    EVIDENCE_VERIFIER_VERSION,
    count_recipe_parameters,
    verify_recipe_parameters,
)

logger = logging.getLogger(__name__)

_CURRENT_VERSION_TAG = f"{EVIDENCE_VERIFIER_VERSION}/{EVIDENCE_NORMALIZER_VERSION}"

# 프론트에 내려보내는 필드. bbox_json은 파싱해 bbox로 바꿔 내보낸다.
_PUBLIC_ANCHOR_FIELDS = (
    "target_index",
    "target_key",
    "target_label",
    "source_tag",
    "claimed_quote",
    "claimed_page",
    "quote_status",
    "page_status",
    "value_status",
    "display_status",
    "match_method",
    "match_ratio",
    "matched_quote",
    "matched_page",
    "corpus",
    "failure_detail",
    "verifier_version",
    "normalizer_version",
)


def _parse_recipe(recipe_text: str) -> Optional[dict[str, Any]]:
    try:
        payload = json.loads(recipe_text)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if "_parse_error" in payload or payload.get("skipped"):
        return None
    return payload


def _parse_bbox(bbox_json) -> Optional[list[float]]:
    if not bbox_json:
        return None
    try:
        value = json.loads(bbox_json)
    except (TypeError, json.JSONDecodeError):
        return None
    if isinstance(value, list) and len(value) == 4:
        try:
            return [float(item) for item in value]
        except (TypeError, ValueError):
            return None
    return None


async def ensure_recipe_anchors(
    *,
    paper_id: int,
    analysis_result_id: int,
    recipe_text: str,
    pdf_path,
    force: bool = False,
) -> dict[str, Any]:
    """이 recipe 행의 앵커가 현재 검증기 버전으로 존재하도록 보장한다(멱등).

    캐시 히트 경로도 이 함수를 태운다 — 옛 결과 백필과 검증기 버전업 재검증이
    LLM 재호출 없이 이루어지는 유일한 통로다.
    """
    recipe = _parse_recipe(recipe_text)
    if recipe is None:
        return {"status": "skipped_unparsable", "anchors": 0}

    expected = count_recipe_parameters(recipe)
    if expected == 0:
        return {"status": "skipped_no_parameters", "anchors": 0}

    conn = await get_db()
    stored, versions = await anchor_versions(conn, analysis_result_id)
    if not force and stored == expected and versions == {_CURRENT_VERSION_TAG}:
        return {"status": "up_to_date", "anchors": stored}

    drafts = await run_pipeline_blocking(verify_recipe_parameters, recipe, pdf_path)
    written = await upsert_anchors(
        conn,
        paper_id=paper_id,
        analysis_result_id=analysis_result_id,
        phase="recipe",
        anchors=[asdict(draft) for draft in drafts],
    )
    logger.info(
        "evidence anchors written: paper=%s result=%s anchors=%s verified=%s",
        paper_id,
        analysis_result_id,
        written,
        sum(1 for draft in drafts if draft.display_status == "VERIFIED"),
    )
    return {"status": "verified", "anchors": written}


async def build_evidence_payload(analysis_result_id: Optional[int]) -> Optional[dict[str, Any]]:
    """recipe 응답에 붙일 read model.

    None을 돌려주는 것은 "검증 기록이 없다"는 뜻이지 "검증됐다"가 아니다.
    UI는 None을 받으면 전 행을 '검증 미실행'으로 표시해야 한다.
    """
    if not analysis_result_id:
        return None

    conn = await get_db()
    rows = await fetch_anchors(conn, int(analysis_result_id))
    if not rows:
        return None

    anchors: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for row in rows:
        anchor = {field: row.get(field) for field in _PUBLIC_ANCHOR_FIELDS}
        anchor["bbox"] = _parse_bbox(row.get("bbox_json"))
        anchors.append(anchor)
        status = str(row.get("display_status") or "UNVERIFIED_ERROR")
        counts[status] = counts.get(status, 0) + 1

    return {
        "verifier_version": EVIDENCE_VERIFIER_VERSION,
        "normalizer_version": EVIDENCE_NORMALIZER_VERSION,
        "summary": {
            "total": len(anchors),
            "verified": counts.get("VERIFIED", 0),
            "by_display_status": counts,
        },
        "anchors": anchors,
    }
