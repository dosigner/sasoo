"""evidence_anchors — Recipe 파라미터 근거 앵커의 스키마와 conn-first 접근자.

models/analysis_runs.py와 같은 관례를 따른다: DDL 상수를 이 모듈이 소유하고,
init_db()가 executescript로 idempotent하게 적용한다. 워커 프로세스는 마이그레이션을
실행하지 않으므로(models/database.py의 connect_worker_db) 신규 DDL은 반드시 init_db()에
등록해야 한다.

설계 근거: docs/superpowers/specs/2026-08-06-evidence-anchoring-design.md
- LLM 원본 JSON(analysis_results.result)은 무수정 보존하고 검증 결과만 여기 저장한다.
- analysis_result_id에 결속한다. (paper_id, phase)에만 묶으면 재분석으로 파라미터 목록이
  바뀐 뒤 옛 앵커가 새 파라미터에 붙는다 — 정확히 "조용한 오승격"이다.
- UNIQUE(analysis_result_id, target_kind, target_key) + ON CONFLICT DO UPDATE로
  검증기 버전업·백필 재실행을 멱등하게 만든다.
"""

from __future__ import annotations

from typing import Any, Sequence

EVIDENCE_ANCHORS_DDL = """
CREATE TABLE IF NOT EXISTS evidence_anchors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    analysis_result_id INTEGER REFERENCES analysis_results(id) ON DELETE CASCADE,
    phase TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target_key TEXT NOT NULL,
    target_index INTEGER,
    target_label TEXT,
    source_tag TEXT,
    claimed_quote TEXT,
    claimed_page INTEGER,
    quote_status TEXT NOT NULL,
    page_status TEXT NOT NULL,
    value_status TEXT NOT NULL,
    display_status TEXT NOT NULL,
    match_method TEXT,
    match_ratio REAL,
    matched_quote TEXT,
    matched_page INTEGER,
    bbox_json TEXT,
    corpus TEXT NOT NULL,
    failure_detail TEXT,
    verifier_version TEXT NOT NULL,
    normalizer_version TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_target
    ON evidence_anchors(analysis_result_id, target_kind, target_key);
CREATE INDEX IF NOT EXISTS idx_evidence_paper ON evidence_anchors(paper_id, phase);
CREATE INDEX IF NOT EXISTS idx_evidence_display ON evidence_anchors(paper_id, display_status);
"""

# upsert가 각 anchor dict에서 이 순서로 읽는다. 누락 키는 None으로 채운다.
ANCHOR_FIELDS: tuple[str, ...] = (
    "target_kind",
    "target_key",
    "target_index",
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
    "bbox_json",
    "corpus",
    "failure_detail",
    "verifier_version",
    "normalizer_version",
)

_UPSERT_SQL = """
INSERT INTO evidence_anchors
    (paper_id, analysis_result_id, phase,
     target_kind, target_key, target_index, target_label, source_tag,
     claimed_quote, claimed_page, quote_status, page_status, value_status,
     display_status, match_method, match_ratio, matched_quote, matched_page,
     bbox_json, corpus, failure_detail, verifier_version, normalizer_version)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(analysis_result_id, target_kind, target_key) DO UPDATE SET
    paper_id = excluded.paper_id,
    phase = excluded.phase,
    target_index = excluded.target_index,
    target_label = excluded.target_label,
    source_tag = excluded.source_tag,
    claimed_quote = excluded.claimed_quote,
    claimed_page = excluded.claimed_page,
    quote_status = excluded.quote_status,
    page_status = excluded.page_status,
    value_status = excluded.value_status,
    display_status = excluded.display_status,
    match_method = excluded.match_method,
    match_ratio = excluded.match_ratio,
    matched_quote = excluded.matched_quote,
    matched_page = excluded.matched_page,
    bbox_json = excluded.bbox_json,
    corpus = excluded.corpus,
    failure_detail = excluded.failure_detail,
    verifier_version = excluded.verifier_version,
    normalizer_version = excluded.normalizer_version,
    created_at = CURRENT_TIMESTAMP
"""


async def upsert_anchors(
    conn,
    *,
    paper_id: int,
    analysis_result_id: int,
    phase: str,
    anchors: Sequence[dict[str, Any]],
) -> int:
    """앵커를 멱등하게 저장한다. 같은 target_key는 새 행이 아니라 갱신이다."""
    rows = [
        (paper_id, analysis_result_id, phase, *(anchor.get(field) for field in ANCHOR_FIELDS))
        for anchor in anchors
    ]
    if not rows:
        return 0
    await conn.executemany(_UPSERT_SQL, rows)
    await conn.commit()
    return len(rows)


async def fetch_anchors(conn, analysis_result_id: int) -> list[dict[str, Any]]:
    """한 분석 결과에 붙은 앵커 전부를 파라미터 순서로 반환한다."""
    cursor = await conn.execute(
        """
        SELECT * FROM evidence_anchors
        WHERE analysis_result_id = ?
        ORDER BY target_index ASC, id ASC
        """,
        (analysis_result_id,),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def anchor_versions(conn, analysis_result_id: int) -> tuple[int, set[str]]:
    """(앵커 수, {verifier/normalizer 버전 조합}) — 재검증 필요 여부 판단용."""
    cursor = await conn.execute(
        """
        SELECT verifier_version, normalizer_version FROM evidence_anchors
        WHERE analysis_result_id = ?
        """,
        (analysis_result_id,),
    )
    rows = await cursor.fetchall()
    return len(rows), {f"{row[0]}/{row[1]}" for row in rows}
