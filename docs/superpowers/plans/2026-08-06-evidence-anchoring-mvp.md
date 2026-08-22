# Evidence Anchoring MVP Implementation Plan

> **에이전트 실행 안내 (agentic worker)**
>
> 이 계획은 `superpowers:subagent-driven-development` 스킬로 실행한다. 오케스트레이터는
> 태스크를 하나씩 서브에이전트에 위임하고, 서브에이전트는 **자기 태스크의 Files /
> Interfaces / Steps 블록만 읽고** 작업한다. 이전 태스크가 만든 이름(함수 시그니처,
> 타입, 컬럼명)은 그 태스크의 **Interfaces → Produces** 블록에만 적혀 있다 — 코드를
> 다시 뒤져 추측하지 말고 그 블록을 진실로 삼아라.
>
> 규칙:
> - 각 스텝은 2~5분 단위다. 스텝 순서를 바꾸지 마라.
> - TDD 엄수: 실패하는 테스트 작성 → **실제로 실행해 실패 확인** → 최소 구현 → 통과 확인 → 커밋.
>   "실패할 것이다"라고 쓰고 넘어가지 마라. 명령을 실행하고 출력을 확인한다.
> - 계획에 적힌 코드 블록은 그대로 쓴다. 다르게 쓰려면 그 이유를 태스크 보고서에 남긴다.
> - 파일을 수정하기 전에 반드시 그 파일을 읽는다. 라인 번호는 참고값이므로 **내용으로 매칭**한다.
> - 태스크가 끝나면 커밋하고, 다음 태스크로 넘어가기 전 보고서(변경 파일, 실행한 명령,
>   미검증 항목)를 남긴다.

## Goal

Recipe 파라미터마다 (evidence_quote, page, 검증 상태, bbox)를 결정론적 코드로 검증해
`evidence_anchors` 테이블에 저장하고, UI에서 상태를 정직하게 표시하며 클릭 시 PDF 해당
페이지로 이동한다.

## Architecture

LLM은 후보 생성까지만 한다 — `_RECIPE_SCHEMA`에 `evidence_quote`/`evidence_page`를 추가하고,
검증 상태·bbox는 절대 LLM 출력 필드로 두지 않는다. 검증은 `services/evidence_verifier.py`의
순수 함수 계층(PDF 텍스트층 대조 + normalizer-v1 + 값 가드)이 수행하고, `_run_recipe`가
recipe row 저장 직후(캐시 히트 경로 포함) 동기 실행해 `evidence_anchors`에 upsert한다.
API는 저장 blob을 무수정 유지한 채 응답에 `evidence`를 형제 필드로 붙이고, 프론트는
`target_index`+`target_label`로 결합하되 label이 다르면 앵커를 숨긴다(fail closed).

## Tech Stack

- 백엔드: Python 3.12/3.14, FastAPI, aiosqlite(SQLite), PyMuPDF(`fitz`) 1.25+, pytest(unittest 스타일)
- 프론트: React 19 + TypeScript, Vite, Tailwind, pdf.js 5.x, vitest(`environment: 'node'` — DOM 테스트 불가, 순수 로직만)
- 저장소: `/Users/dongj/dev/논문_사수_개발중` (앱 워크스페이스는 `sasoo/`)

## Global Constraints

**지배 문서 순서** — 충돌 시 위가 이긴다.

1. `docs/superpowers/specs/2026-08-06-evidence-anchoring-design.md` (확정 스펙)
2. 원본 설계 보고서 2건: `.superpowers/sdd/2026-08-06-phase0-truth-restoration/phase1-design-deepreasoner.md`,
   `.../phase1-design-codex.md`
3. 이 계획서

스펙과 이 계획이 어긋나 보이면 **스펙이 이긴다**. 계획을 벗어나야 하면 태스크 보고서에
"스펙 §X 때문에 계획 Y를 바꿨다"로 근거를 남긴다.

**브랜치 (DEC-010)**

구현은 PR #45(Phase 0 진실 회복)가 main에 병합된 뒤 main에서 분기한다.

```bash
cd /Users/dongj/dev/논문_사수_개발중
git fetch origin
git checkout -b feat/phase1-evidence-anchoring origin/main
```

분기 직후 Phase 0 산출물이 실제로 있는지 확인한다(없으면 병합 전 main이므로 중단하고 보고):

```bash
grep -n "_CHAIN_CACHE_VERSION\|def _phase_cache_key" sasoo/backend/api/analysis_routes.py
grep -n "errorMessage" sasoo/frontend/src/components/AnalysisPanel.tsx
```

기대: `_CHAIN_CACHE_VERSION = "2026-08-06"`과 `_phase_cache_key` 정의, AnalysisPanel의
`errorMessage?: string | null` prop이 모두 보인다.

**커밋 관례**

- 메시지: `feat(scope): 한국어 요약` 또는 `fix(scope): 한국어 요약`
- 본문 마지막 줄:
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  ```
- scope 예: `db`, `evidence`, `analysis`, `api`, `workbench`, `export`, `tools`

**테스트 명령**

```bash
# 백엔드 전체
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services api models -q

# 백엔드 단일 파일
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services/test_evidence_verifier.py -q

# 프론트 타입/린트
cd /Users/dongj/dev/논문_사수_개발중/sasoo/frontend && pnpm tsc --noEmit && pnpm lint

# 프론트 유닛 (vitest, 저장소 루트가 아니라 sasoo/ 에서)
cd /Users/dongj/dev/논문_사수_개발중/sasoo && pnpm test:unit
cd /Users/dongj/dev/논문_사수_개발중/sasoo && pnpm exec vitest run frontend/src/lib/evidence.test.ts
```

`backend/.venv`가 없으면 AGENTS.md의 부트스트랩 절차를 먼저 따른다.

**깨면 안 되는 계약**

1. **조용한 승격 금지** — 앵커가 없거나 검증에 실패한 파라미터를 "검증됨"으로 보이게 하는
   코드 경로를 만들지 않는다. 앵커 부재 = `UNVERIFIED_NOT_RUN`.
2. **LLM 출력 무수정 보존** — `analysis_results.result` blob에 검증 결과를 쓰지 않는다.
3. **순환 검증 금지** — Gemini 전사본(`full_text`)으로 quote를 검증하지 않는다. 대조 원본은
   PDF 텍스트층뿐이다.
4. **`_CHAIN_CACHE_VERSION` bump 필수** — 스펙 §"두 설계가 수렴한 결정" 4번. Task 4에서
   `"2026-08-06"` → `"2026-08-06-ev1"`로 올린다. 체인 phase 전체가 1회 재과금되는 것을
   알고 하는 선택이며, PR 본문에 캐시 무효화 고지를 반드시 넣는다.
5. **워커는 마이그레이션을 실행하지 않는다** (`models/database.py`의 `connect_worker_db`
   주석). 신규 DDL은 반드시 `init_db()`에 등록한다.
6. **`partial_match`는 검증이 아니다** — 위조 인용 false-verify = 0 게이트를 pytest로 고정한다.

**유지+추가 원칙**

기존 동작·필드·컬럼·문자열을 삭제하거나 대체하지 않는다. 추가만 한다. 예외는 이 계획이
명시적으로 "이동"이라고 적은 두 건뿐이다(`generateCsvFromRecipe`의 lib 이동, 파라미터 파서의
lib 이동) — 둘 다 호출부에서 동일 동작을 유지한 채 테스트 가능성을 얻기 위한 이동이다.

**PR**

마지막 태스크에서 PR만 만든다. **병합은 사용자만 한다.** 에이전트는 `gh pr merge`를
실행하지 않는다.

---

## Task 1: evidence_anchors 스키마와 conn-first 접근자

`models/analysis_runs.py`와 같은 관례(DDL 상수 + conn을 첫 인자로 받는 async 함수)를 따라
신규 테이블을 추가한다. 순수 추가이므로 alembic은 도입하지 않는다.

**Files**

- Create: `sasoo/backend/models/evidence_anchors.py`
- Create: `sasoo/backend/models/test_evidence_anchors.py`
- Modify: `sasoo/backend/models/database.py` (`init_db()` 끝부분에 DDL 등록)

**Interfaces**

Consumes:
- `models.database.init_db()` — 기존 idempotent 마이그레이션 블록 패턴
- `aiosqlite.Connection` (row_factory = `aiosqlite.Row`)

Produces (이후 태스크가 참조하는 이름):

```python
# sasoo/backend/models/evidence_anchors.py
EVIDENCE_ANCHORS_DDL: str

ANCHOR_FIELDS: tuple[str, ...]  # upsert가 요구하는 dict 키 목록(paper_id/analysis_result_id 제외)

async def upsert_anchors(
    conn,
    *,
    paper_id: int,
    analysis_result_id: int,
    phase: str,
    anchors: Sequence[dict],
) -> int: ...

async def fetch_anchors(conn, analysis_result_id: int) -> list[dict]: ...

async def anchor_versions(conn, analysis_result_id: int) -> tuple[int, set[str]]: ...
#   반환: (앵커 행 수, {"{verifier_version}/{normalizer_version}", ...})
```

테이블 컬럼(전부):
`id, paper_id, analysis_result_id, phase, target_kind, target_key, target_index,
target_label, source_tag, claimed_quote, claimed_page, quote_status, page_status,
value_status, display_status, match_method, match_ratio, matched_quote, matched_page,
bbox_json, corpus, failure_detail, verifier_version, normalizer_version, created_at`

인덱스: `UNIQUE(analysis_result_id, target_kind, target_key)`,
`(paper_id, phase)`, `(paper_id, display_status)`

**Steps**

- [ ] **Step 1: 실패 테스트 작성** — `sasoo/backend/models/test_evidence_anchors.py` 생성.

```python
import os
import tempfile
import unittest

import aiosqlite

from models import evidence_anchors as ea


def _draft(**overrides) -> dict:
    base = {
        "target_kind": "recipe_parameter",
        "target_key": "p000:wavelength",
        "target_index": 0,
        "target_label": "wavelength",
        "source_tag": "explicit",
        "claimed_quote": "a wavelength of 1550 nm",
        "claimed_page": 4,
        "quote_status": "verified_normalized",
        "page_status": "match",
        "value_status": "value_in_quote",
        "display_status": "VERIFIED",
        "match_method": "normalized",
        "match_ratio": 1.0,
        "matched_quote": "a wave-\nlength of 1550 nm",
        "matched_page": 4,
        "bbox_json": "[72.0, 700.1, 300.5, 715.2]",
        "corpus": "pdf_text",
        "failure_detail": None,
        "verifier_version": "ev1",
        "normalizer_version": "norm-v1",
    }
    base.update(overrides)
    return base


class EvidenceAnchorsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.conn = await aiosqlite.connect(self.tmp.name)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA foreign_keys=ON")
        await self.conn.executescript(
            "CREATE TABLE papers (id INTEGER PRIMARY KEY);"
            "CREATE TABLE analysis_results (id INTEGER PRIMARY KEY, paper_id INTEGER);"
        )
        await self.conn.execute("INSERT INTO papers (id) VALUES (7)")
        await self.conn.execute("INSERT INTO analysis_results (id, paper_id) VALUES (41, 7)")
        await self.conn.executescript(ea.EVIDENCE_ANCHORS_DDL)
        await self.conn.commit()

    async def asyncTearDown(self):
        await self.conn.close()
        os.unlink(self.tmp.name)

    async def test_ddl_is_idempotent(self):
        await self.conn.executescript(ea.EVIDENCE_ANCHORS_DDL)
        await self.conn.commit()  # 두 번 실행해도 예외가 없어야 한다

    async def test_upsert_then_reverify_updates_in_place(self):
        written = await ea.upsert_anchors(
            self.conn, paper_id=7, analysis_result_id=41, phase="recipe",
            anchors=[_draft(), _draft(target_key="p001:power", target_index=1, target_label="power")],
        )
        self.assertEqual(written, 2)

        # 검증기 버전업 후 재검증 — 같은 target_key는 새 행이 아니라 갱신이어야 한다
        await ea.upsert_anchors(
            self.conn, paper_id=7, analysis_result_id=41, phase="recipe",
            anchors=[_draft(quote_status="not_found", display_status="UNVERIFIED_NOT_FOUND",
                            verifier_version="ev2")],
        )
        rows = await ea.fetch_anchors(self.conn, 41)
        self.assertEqual(len(rows), 2)
        first = next(r for r in rows if r["target_key"] == "p000:wavelength")
        self.assertEqual(first["display_status"], "UNVERIFIED_NOT_FOUND")
        self.assertEqual(first["verifier_version"], "ev2")

    async def test_fetch_anchors_is_ordered_by_target_index(self):
        await ea.upsert_anchors(
            self.conn, paper_id=7, analysis_result_id=41, phase="recipe",
            anchors=[
                _draft(target_key="p002:c", target_index=2, target_label="c"),
                _draft(target_key="p000:a", target_index=0, target_label="a"),
                _draft(target_key="p001:b", target_index=1, target_label="b"),
            ],
        )
        rows = await ea.fetch_anchors(self.conn, 41)
        self.assertEqual([r["target_index"] for r in rows], [0, 1, 2])

    async def test_anchor_versions_reports_count_and_version_set(self):
        await ea.upsert_anchors(
            self.conn, paper_id=7, analysis_result_id=41, phase="recipe",
            anchors=[_draft(), _draft(target_key="p001:b", target_index=1, target_label="b")],
        )
        count, versions = await ea.anchor_versions(self.conn, 41)
        self.assertEqual(count, 2)
        self.assertEqual(versions, {"ev1/norm-v1"})

    async def test_deleting_analysis_result_cascades(self):
        await ea.upsert_anchors(
            self.conn, paper_id=7, analysis_result_id=41, phase="recipe", anchors=[_draft()],
        )
        await self.conn.execute("DELETE FROM analysis_results WHERE id = 41")
        await self.conn.commit()
        self.assertEqual(await ea.fetch_anchors(self.conn, 41), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest models/test_evidence_anchors.py -q
```

기대 출력: `ModuleNotFoundError: No module named 'models.evidence_anchors'` 또는 수집 오류로 5개 테스트 전부 실패.

- [ ] **Step 3: 모듈 구현** — `sasoo/backend/models/evidence_anchors.py` 생성.

```python
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
```

- [ ] **Step 4: `init_db()`에 DDL 등록** — `sasoo/backend/models/database.py`에서
  `from models.analysis_runs import ANALYSIS_RUNS_DDL`로 시작하는 블록(파일 끝, `init_db()`의
  마지막 블록)을 찾아 그 **뒤에** 다음을 추가한다. 기존 블록은 건드리지 않는다.

```python
    # evidence_anchors: Recipe 파라미터 근거 앵커(Phase 1 Evidence Anchoring).
    # 순수 추가 테이블이라 ALTER 반복이 필요 없다.
    from models.evidence_anchors import EVIDENCE_ANCHORS_DDL
    try:
        await _db_connection.executescript(EVIDENCE_ANCHORS_DDL)
        await _db_connection.commit()
    except Exception:
        pass
```

- [ ] **Step 5: 통과 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest models/test_evidence_anchors.py -q
```

기대 출력: `5 passed`.

- [ ] **Step 6: 전체 백엔드 회귀 + 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services api models -q
cd /Users/dongj/dev/논문_사수_개발중 && git add -A && git commit -m "$(cat <<'EOF'
feat(db): evidence_anchors 테이블과 conn-first 접근자 추가

Recipe 파라미터 근거 앵커를 analysis_results.id에 결속해 저장한다.
UNIQUE(analysis_result_id, target_kind, target_key) + ON CONFLICT DO UPDATE로
검증기 버전업 재검증을 멱등하게 만든다. init_db()에만 DDL을 등록해 워커
프로세스가 마이그레이션을 실행하지 않는 기존 계약을 유지한다.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: normalizer-v1 · target_key · 상태 파생 · 값 가드 (순수 계층)

검증기의 DB·PDF를 모르는 순수 함수부터 만든다. **위조 인용 false-verify = 0 게이트가
이 태스크에서 시작된다.**

**Files**

- Create: `sasoo/backend/services/evidence_verifier.py` (1부 — 순수 함수만)
- Create: `sasoo/backend/services/test_evidence_verifier.py` (1부 — 순수 함수 테스트)

**Interfaces**

Consumes: 없음(표준 라이브러리 `re`, `unicodedata`, `difflib`만)

Produces:

```python
# sasoo/backend/services/evidence_verifier.py
EVIDENCE_VERIFIER_VERSION: str = "ev1"
EVIDENCE_NORMALIZER_VERSION: str = "norm-v1"
EVIDENCE_CORPUS_PDF_TEXT: str = "pdf_text"

QUOTE_STATUSES: frozenset[str]   # verified_exact/verified_normalized/partial_match/not_found/
                                 # no_quote/no_text_layer/ambiguous/stale_source/verifier_error
PAGE_STATUSES: frozenset[str]    # match/mismatch/invalid_page/no_page/derived
VALUE_STATUSES: frozenset[str]   # value_in_quote/value_missing/inferred/not_applicable

def normalize_with_map(text: str) -> tuple[str, list[int]]: ...
    # 반환: (정규화 문자열, 정규화 문자 i가 유래한 원문 인덱스 리스트)

def normalize_text(text: str) -> str: ...

def slugify_target(name: str) -> str: ...
def build_target_key(index: int, name: str) -> str: ...   # "p000:wavelength"

def derive_display_status(quote_status: str, page_status: str, value_status: str) -> str: ...
    # VERIFIED / UNVERIFIED_PAGE_MISMATCH / UNVERIFIED_VALUE_MISMATCH / UNVERIFIED_INFERRED /
    # UNVERIFIED_PARTIAL / UNVERIFIED_AMBIGUOUS / UNVERIFIED_NOT_FOUND / UNVERIFIED_NO_QUOTE /
    # UNVERIFIED_NO_TEXT_LAYER / UNVERIFIED_STALE_SOURCE / UNVERIFIED_ERROR

def check_value_in_quote(
    value: str, source_tag: str | None, matched_quote: str | None
) -> tuple[str, str | None]: ...
    # 반환: (value_status, failure_detail)
```

**Steps**

- [ ] **Step 1: 정규화 실패 테스트 작성** — `sasoo/backend/services/test_evidence_verifier.py` 생성.

```python
"""services.evidence_verifier 테스트.

가장 중요한 것은 "위조 인용 false-verify = 0"이다. 설계 스파이크 실측에서 숫자 한 자리를
바꾼 위조본이 부분일치 임계 0.6에서 81.1%, 0.8에서도 52.0% 통과했고, 정규화 완전일치는
0.0%만 통과했다. 그 0을 회귀 게이트로 고정한다.
"""

import unittest

from services import evidence_verifier as ev


class NormalizerV1Tests(unittest.TestCase):
    def test_collapses_whitespace_and_casefolds(self):
        self.assertEqual(ev.normalize_text("The   SAMPLES\n were\tannealed "), "the samples were annealed")

    def test_joins_line_break_hyphen(self):
        text = "We used a wave-\nlength of 1550 nm"
        self.assertEqual(ev.normalize_text(text), "we used a wavelength of 1550 nm")

    def test_removes_soft_hyphen_and_zero_width(self):
        self.assertEqual(ev.normalize_text("wave­length​ test"), "wavelength test")

    def test_nfkc_expands_ligature_and_fullwidth(self):
        self.assertEqual(ev.normalize_text("ﬁber"), "fiber")
        self.assertEqual(ev.normalize_text("１５５０ ｎｍ"), "1550 nm")

    def test_unifies_dashes_and_smart_quotes(self):
        self.assertEqual(ev.normalize_text("1550–1560"), "1550-1560")
        self.assertEqual(ev.normalize_text("“quoted” ‘x’"), '"quoted" \'x\'')

    def test_does_not_alter_digits_or_scientific_symbols(self):
        # μ와 u, ×와 x를 서로 바꾸지 않는다 — 바꾸면 수치 의미가 사라진다
        normalized = ev.normalize_text("3.2 μm × 10")
        self.assertIn("μm", normalized)
        self.assertIn("×", normalized)
        self.assertNotIn("um", normalized)

    def test_source_map_recovers_original_span(self):
        raw = "We used a wave-\nlength of 1550 nm in the setup."
        normalized, source_map = ev.normalize_with_map(raw)
        needle = ev.normalize_text("a wavelength of 1550 nm")
        start = normalized.find(needle)
        self.assertGreaterEqual(start, 0)
        raw_start = source_map[start]
        raw_end = source_map[start + len(needle) - 1] + 1
        self.assertEqual(raw[raw_start:raw_end], "a wave-\nlength of 1550 nm")

    def test_map_length_matches_normalized_length(self):
        normalized, source_map = ev.normalize_with_map("  A­ B-\ncd  ")
        self.assertEqual(len(normalized), len(source_map))


class ForgedQuoteGateTests(unittest.TestCase):
    """숫자를 변조한 인용은 정규화 완전일치를 통과하지 못한다 (false verify = 0)."""

    CORPUS = (
        "The samples were annealed at 500 °C for 2 h. "
        "A wavelength of 1550 nm was used with 3.2 mW average power. "
        "The beam diameter was 12.5 mm at the aperture."
    )
    HONEST = [
        "The samples were annealed at 500 °C for 2 h.",
        "A wavelength of 1550 nm was used with 3.2 mW average power.",
        "The beam diameter was 12.5 mm at the aperture.",
    ]
    FORGED = [
        "The samples were annealed at 900 °C for 2 h.",
        "A wavelength of 1560 nm was used with 3.2 mW average power.",
        "The beam diameter was 12.8 mm at the aperture.",
    ]

    def test_honest_quotes_all_match_normalized(self):
        corpus = ev.normalize_text(self.CORPUS)
        for quote in self.HONEST:
            self.assertIn(ev.normalize_text(quote), corpus, quote)

    def test_forged_quotes_never_match_normalized(self):
        corpus = ev.normalize_text(self.CORPUS)
        for quote in self.FORGED:
            self.assertNotIn(ev.normalize_text(quote), corpus, quote)


class TargetKeyTests(unittest.TestCase):
    def test_target_key_is_index_prefixed_slug(self):
        self.assertEqual(ev.build_target_key(0, "Annealing Temperature"), "p000:annealing-temperature")
        self.assertEqual(ev.build_target_key(12, "laser_power (mW)"), "p012:laser-power-mw")

    def test_slug_keeps_hangul_and_falls_back_when_empty(self):
        self.assertEqual(ev.slugify_target("파장"), "파장")
        self.assertEqual(ev.slugify_target("  ***  "), "unnamed")

    def test_slug_is_truncated_to_48_chars(self):
        self.assertEqual(len(ev.slugify_target("a" * 200)), 48)


class DisplayStatusTests(unittest.TestCase):
    def test_verified_requires_all_three_fields(self):
        self.assertEqual(ev.derive_display_status("verified_exact", "match", "value_in_quote"), "VERIFIED")
        self.assertEqual(ev.derive_display_status("verified_normalized", "derived", "value_in_quote"), "VERIFIED")

    def test_page_mismatch_is_not_verified(self):
        self.assertEqual(
            ev.derive_display_status("verified_exact", "mismatch", "value_in_quote"),
            "UNVERIFIED_PAGE_MISMATCH",
        )

    def test_value_missing_is_not_verified(self):
        self.assertEqual(
            ev.derive_display_status("verified_exact", "match", "value_missing"),
            "UNVERIFIED_VALUE_MISMATCH",
        )

    def test_inferred_is_never_verified(self):
        self.assertEqual(
            ev.derive_display_status("verified_exact", "match", "inferred"), "UNVERIFIED_INFERRED"
        )

    def test_partial_match_is_never_verified(self):
        self.assertEqual(
            ev.derive_display_status("partial_match", "match", "value_in_quote"), "UNVERIFIED_PARTIAL"
        )

    def test_every_quote_status_maps_to_a_known_display_status(self):
        allowed = {
            "VERIFIED", "UNVERIFIED_PAGE_MISMATCH", "UNVERIFIED_VALUE_MISMATCH",
            "UNVERIFIED_INFERRED", "UNVERIFIED_PARTIAL", "UNVERIFIED_AMBIGUOUS",
            "UNVERIFIED_NOT_FOUND", "UNVERIFIED_NO_QUOTE", "UNVERIFIED_NO_TEXT_LAYER",
            "UNVERIFIED_STALE_SOURCE", "UNVERIFIED_ERROR",
        }
        for quote_status in ev.QUOTE_STATUSES:
            for page_status in ev.PAGE_STATUSES:
                for value_status in ev.VALUE_STATUSES:
                    self.assertIn(
                        ev.derive_display_status(quote_status, page_status, value_status), allowed
                    )

    def test_unknown_quote_status_never_promotes(self):
        self.assertEqual(ev.derive_display_status("who_knows", "match", "value_in_quote"), "UNVERIFIED_ERROR")


class ValueGuardTests(unittest.TestCase):
    def test_numeric_value_must_appear_in_quote(self):
        self.assertEqual(
            ev.check_value_in_quote("500", "explicit", "annealed at 500 °C for 2 h")[0],
            "value_in_quote",
        )
        status, detail = ev.check_value_in_quote("900", "explicit", "annealed at 500 °C for 2 h")
        self.assertEqual(status, "value_missing")
        self.assertIsNotNone(detail)

    def test_non_numeric_value_falls_back_to_literal(self):
        self.assertEqual(
            ev.check_value_in_quote("nitrogen", "explicit", "under a Nitrogen atmosphere")[0],
            "value_in_quote",
        )
        self.assertEqual(
            ev.check_value_in_quote("argon", "explicit", "under a Nitrogen atmosphere")[0],
            "value_missing",
        )

    def test_inferred_is_structurally_unverifiable(self):
        self.assertEqual(ev.check_value_in_quote("500", "inferred", "annealed at 500 °C")[0], "inferred")

    def test_empty_value_is_not_applicable(self):
        self.assertEqual(ev.check_value_in_quote("", "explicit", "any text")[0], "not_applicable")

    def test_missing_match_means_value_missing(self):
        self.assertEqual(ev.check_value_in_quote("500", "explicit", None)[0], "value_missing")

    def test_multi_number_value_requires_every_number(self):
        self.assertEqual(
            ev.check_value_in_quote("1550-1560", "explicit", "from 1550 to 1560 nm")[0], "value_in_quote"
        )
        self.assertEqual(
            ev.check_value_in_quote("1550-1570", "explicit", "from 1550 to 1560 nm")[0], "value_missing"
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services/test_evidence_verifier.py -q
```

기대 출력: `ModuleNotFoundError: No module named 'services.evidence_verifier'`.

- [ ] **Step 3: 순수 계층 구현** — `sasoo/backend/services/evidence_verifier.py` 생성.

```python
"""evidence_verifier — Recipe 파라미터 근거의 결정론적 검증기.

원칙(docs/superpowers/specs/2026-08-06-evidence-anchoring-design.md):
- LLM 후보를 다른 LLM 전사본으로 확인하지 않는다. 대조 원본은 PDF 텍스트층뿐이다.
- 유사도·편집거리·임베딩을 검증에 쓰지 않는다. 실측상 숫자 한 자리를 바꾼 위조 인용이
  임계 0.6에서 81.1%, 0.8에서도 52.0% 통과한다. 정규화 완전일치만 0.0%다.
- partial_match는 탐색 보조일 뿐 검증이 아니다.
- 상태는 직교 3필드(quote/page/value)로 저장하고 표시 상태 1개를 결정론 규칙으로 파생한다.
"""

from __future__ import annotations

import re
import unicodedata

EVIDENCE_VERIFIER_VERSION = "ev1"
EVIDENCE_NORMALIZER_VERSION = "norm-v1"
EVIDENCE_CORPUS_PDF_TEXT = "pdf_text"

QUOTE_STATUSES = frozenset(
    {
        "verified_exact",
        "verified_normalized",
        "partial_match",
        "not_found",
        "no_quote",
        "no_text_layer",
        "ambiguous",
        "stale_source",
        "verifier_error",
    }
)
PAGE_STATUSES = frozenset({"match", "mismatch", "invalid_page", "no_page", "derived"})
VALUE_STATUSES = frozenset({"value_in_quote", "value_missing", "inferred", "not_applicable"})

# ---------------------------------------------------------------------------
# normalizer-v1
# ---------------------------------------------------------------------------
# 스펙의 규칙 순서: NFKC → 소문자 → 대시 통일 → 리거처 해제 → 줄바꿈 하이픈 결합 →
# 공백 축약 → 스마트 따옴표 통일.
# 스펙에 없지만 추가한 0단계: 제로폭/소프트하이픈 제거. 소프트하이픈(U+00AD)은 NFKC가
# 제거하지 않는데, 이걸 남기면 줄바꿈 하이픈 결합이 소프트하이픈 케이스를 놓친다.
# (표기 정규화일 뿐 수치 의미를 바꾸지 않으므로 스펙과 충돌하지 않는다.)

_STRIP_CHARS = frozenset("­​‌‍﻿")
_DASHES = frozenset("‐‑‒–—―−")
_SINGLE_QUOTES = frozenset("‘’‚‛′")
_DOUBLE_QUOTES = frozenset("“”„‟″")
_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"}


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """정규화 문자열과 '정규화 문자 i → 원문 인덱스' 맵을 함께 반환한다.

    맵이 있어야 정규화 매치 구간을 원문 span으로 되돌릴 수 있고, 그 원문 span을
    PyMuPDF page.search_for에 그대로 넘겨 bbox를 얻을 수 있다.
    """
    text = str(text or "")

    # 0~4단계: 문자 단위 치환. 각 출력 문자는 자기가 유래한 원문 인덱스를 들고 다닌다.
    pairs: list[tuple[str, int]] = []
    for index, char in enumerate(text):
        if char in _STRIP_CHARS:
            continue
        if char in _DASHES:
            folded = "-"
        elif char in _SINGLE_QUOTES:
            folded = "'"
        elif char in _DOUBLE_QUOTES:
            folded = '"'
        elif char in _LIGATURES:
            folded = _LIGATURES[char]
        else:
            folded = unicodedata.normalize("NFKC", char).casefold()
        for out_char in folded:
            pairs.append((out_char, index))

    # 5단계: 줄바꿈 하이픈 결합 — '-' + (공백) + '\n' + (공백)을 통째로 제거한다.
    joined: list[tuple[str, int]] = []
    total = len(pairs)
    cursor = 0
    while cursor < total:
        char, source = pairs[cursor]
        if char == "-":
            probe = cursor + 1
            while probe < total and pairs[probe][0] in " \t\r":
                probe += 1
            if probe < total and pairs[probe][0] == "\n":
                probe += 1
                while probe < total and pairs[probe][0].isspace():
                    probe += 1
                cursor = probe
                continue
        joined.append((char, source))
        cursor += 1

    # 6단계: 공백류 연속 → 스페이스 1개, 양끝 strip.
    collapsed: list[tuple[str, int]] = []
    previous_was_space = True  # 선행 공백 제거
    for char, source in joined:
        if char.isspace():
            if previous_was_space:
                continue
            collapsed.append((" ", source))
            previous_was_space = True
        else:
            collapsed.append((char, source))
            previous_was_space = False
    while collapsed and collapsed[-1][0] == " ":
        collapsed.pop()

    return "".join(char for char, _ in collapsed), [source for _, source in collapsed]


def normalize_text(text: str) -> str:
    return normalize_with_map(text)[0]


# ---------------------------------------------------------------------------
# 파라미터 ↔ 앵커 결속 키
# ---------------------------------------------------------------------------

_SLUG_STRIP = re.compile(r"[^0-9a-z가-힣]+")


def slugify_target(name: str) -> str:
    folded = unicodedata.normalize("NFKC", str(name or "")).casefold()
    slug = _SLUG_STRIP.sub("-", folded).strip("-")
    return (slug or "unnamed")[:48]


def build_target_key(index: int, name: str) -> str:
    return f"p{int(index):03d}:{slugify_target(name)}"


# ---------------------------------------------------------------------------
# 표시 상태 파생
# ---------------------------------------------------------------------------

_DISPLAY_BY_QUOTE_STATUS = {
    "verifier_error": "UNVERIFIED_ERROR",
    "no_text_layer": "UNVERIFIED_NO_TEXT_LAYER",
    "stale_source": "UNVERIFIED_STALE_SOURCE",
    "no_quote": "UNVERIFIED_NO_QUOTE",
    "ambiguous": "UNVERIFIED_AMBIGUOUS",
    "not_found": "UNVERIFIED_NOT_FOUND",
    "partial_match": "UNVERIFIED_PARTIAL",
}


def derive_display_status(quote_status: str, page_status: str, value_status: str) -> str:
    """VERIFIED는 세 필드가 전부 통과할 때만 나온다 — 조용한 승격 금지의 마지막 방어선."""
    mapped = _DISPLAY_BY_QUOTE_STATUS.get(quote_status)
    if mapped is not None:
        return mapped
    if quote_status not in {"verified_exact", "verified_normalized"}:
        return "UNVERIFIED_ERROR"  # 알 수 없는 상태는 절대 승격하지 않는다
    if page_status not in {"match", "derived"}:
        return "UNVERIFIED_PAGE_MISMATCH"
    if value_status == "inferred":
        return "UNVERIFIED_INFERRED"
    if value_status != "value_in_quote":
        return "UNVERIFIED_VALUE_MISMATCH"
    return "VERIFIED"


# ---------------------------------------------------------------------------
# 값 가드
# ---------------------------------------------------------------------------

_NUMBER_LITERAL = re.compile(r"\d+(?:\.\d+)?")


def check_value_in_quote(
    value: str, source_tag: str | None, matched_quote: str | None
) -> tuple[str, str | None]:
    """파라미터 값이 확인된 인용 안에 실제로 들어 있는지 본다.

    인용이 원문에 존재한다는 사실만으로는 그 파라미터를 뒷받침하지 못한다. explicit
    파라미터는 값(숫자, 없으면 값 리터럴)이 인용 안에 있어야 VERIFIED가 될 수 있다.
    inferred는 구조적으로 VERIFIED 불가다 — 계산식 검증 기능이 생기기 전까지.
    """
    if str(source_tag or "").strip().casefold() == "inferred":
        return ("inferred", None)

    normalized_value = normalize_text(value)
    if not normalized_value:
        return ("not_applicable", "empty_value")
    if not matched_quote:
        return ("value_missing", "no_matched_quote")

    normalized_quote = normalize_text(matched_quote)
    numbers = _NUMBER_LITERAL.findall(normalized_value)
    needles = numbers or [normalized_value]
    for needle in needles:
        if needle not in normalized_quote:
            return ("value_missing", f"missing:{needle[:24]}")
    return ("value_in_quote", None)
```

- [ ] **Step 4: 통과 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services/test_evidence_verifier.py -q
```

기대 출력: `26 passed` (정규화 8 + 위조 게이트 2 + target_key 3 + 표시상태 7 + 값 가드 6).
숫자가 다르면 테스트가 빠진 것이니 위 코드를 다시 대조한다.

- [ ] **Step 5: 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중 && git add -A && git commit -m "$(cat <<'EOF'
feat(evidence): normalizer-v1과 상태 파생·값 가드 순수 계층 추가

정규화는 표기 차이만 흡수하고 수치·과학기호는 건드리지 않는다(μ↔u, ×↔x 치환 금지).
정규화 문자→원문 인덱스 맵을 함께 반환해 매치 구간을 원문 span으로 되돌릴 수 있게 했다.
VERIFIED는 quote·page·value 세 필드가 모두 통과할 때만 파생된다.
숫자 변조 위조 인용의 false-verify=0을 pytest 게이트로 고정했다.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: PDF 텍스트층 인덱스 · 검색기 · bbox · verify_recipe_parameters

Task 2의 순수 계층 위에 PDF 대조 계층을 얹는다. **대조 원본은 PDF 텍스트층뿐이다** — 매니페스트
`full_text`(Gemini 경로에서는 다른 LLM의 전사본)로는 검증하지 않는다.

**Files**

- Modify: `sasoo/backend/services/evidence_verifier.py` (Task 2 파일에 2부 추가)
- Modify: `sasoo/backend/services/test_evidence_verifier.py` (합성 PDF fixture 테스트 추가)

**Interfaces**

Consumes (Task 2 Produces 전부):
`normalize_with_map`, `normalize_text`, `build_target_key`, `derive_display_status`,
`check_value_in_quote`, `EVIDENCE_VERIFIER_VERSION`, `EVIDENCE_NORMALIZER_VERSION`,
`EVIDENCE_CORPUS_PDF_TEXT`

Produces:

```python
@dataclass(frozen=True, slots=True)
class PageText:
    page_number: int
    raw: str
    normalized: str
    source_map: tuple[int, ...]
    tokens: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class PdfTextIndex:
    pages: tuple[PageText, ...]
    page_count: int
    @property
    def has_text_layer(self) -> bool: ...

@dataclass(frozen=True, slots=True)
class QuoteMatch:
    quote_status: str
    page_status: str
    matched_page: int | None = None
    matched_quote: str | None = None
    match_method: str | None = None
    match_ratio: float | None = None
    failure_detail: str | None = None

@dataclass(frozen=True, slots=True)
class EvidenceAnchorDraft:
    target_kind: str; target_key: str; target_index: int; target_label: str
    source_tag: str | None; claimed_quote: str; claimed_page: int | None
    quote_status: str; page_status: str; value_status: str; display_status: str
    match_method: str | None; match_ratio: float | None
    matched_quote: str | None; matched_page: int | None
    bbox_json: str | None; corpus: str; failure_detail: str | None
    verifier_version: str; normalizer_version: str

def build_pdf_index(pdf_path) -> PdfTextIndex: ...
def find_quote(index: PdfTextIndex, quote: str, claimed_page: int | None) -> QuoteMatch: ...
def locate_bbox(page, matched_quote: str | None) -> list[float] | None: ...
    # [x0, y_bottom, x1, y_top] PDF 포인트, 좌하단 원점 (figures/tables와 동일 규약)
def iter_recipe_parameters(recipe: dict) -> list[tuple[int, dict]]: ...
def count_recipe_parameters(recipe: dict) -> int: ...
def verify_recipe_parameters(recipe: dict, pdf_path=None) -> list[EvidenceAnchorDraft]: ...
```

**Steps**

- [ ] **Step 1: 합성 PDF 실패 테스트 작성** — `sasoo/backend/services/test_evidence_verifier.py` 끝의
  `if __name__ == "__main__":` **앞에** 아래를 추가한다(기존 테스트는 그대로 둔다). 파일 상단
  import 블록도 `import json / import os / import tempfile / import unittest` + `import fitz`로 보강한다.

```python
class _PdfFixture:
    """검증기 테스트용 합성 PDF. 실제 라이브러리 논문 없이 CI에서 돌아야 한다.

    p1: 축자 인용 1건 + 줄바꿈 하이픈으로 끊긴 인용 1건 + 양 페이지 중복 문장
    p2: 긴 문장(부분일치용) + 값 가드용 문장 + 양 페이지 중복 문장
    """

    P1_EXACT = "The samples were annealed at 500 °C for 2 h."
    P1_HYPHEN_RAW = "We used a wave-\nlength of 1550 nm in the setup."
    P1_HYPHEN_QUOTE = "We used a wavelength of 1550 nm in the setup."
    DUPLICATE = "This sentence appears on both pages of the document."
    P2_LONG = (
        "In this experiment the beam diameter was measured as 12.5 mm "
        "at the output aperture of the telescope."
    )
    P2_PARTIAL_QUOTE = (
        "In this experiment the beam diameter was measured as 12.5 mm "
        "at the entrance aperture of the telescope."
    )
    P2_NITROGEN = "The annealing was performed under a nitrogen atmosphere."

    @classmethod
    def write(cls, path: str) -> None:
        doc = fitz.open()
        page1 = doc.new_page()
        page1.insert_text((50, 100), cls.P1_EXACT, fontsize=10, fontname="helv")
        page1.insert_textbox(fitz.Rect(50, 120, 200, 200), cls.P1_HYPHEN_RAW, fontsize=10, fontname="helv")
        page1.insert_text((50, 220), cls.DUPLICATE, fontsize=10, fontname="helv")
        page2 = doc.new_page()
        page2.insert_text((50, 100), cls.P2_LONG, fontsize=8, fontname="helv")
        page2.insert_text((50, 130), cls.P2_NITROGEN, fontsize=10, fontname="helv")
        page2.insert_text((50, 160), cls.DUPLICATE, fontsize=10, fontname="helv")
        doc.save(path)
        doc.close()

    @staticmethod
    def write_blank(path: str) -> None:
        doc = fitz.open()
        doc.new_page()
        doc.save(path)
        doc.close()


class PdfIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        handle.close()
        cls.pdf_path = handle.name
        _PdfFixture.write(cls.pdf_path)
        cls.index = ev.build_pdf_index(cls.pdf_path)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.pdf_path)

    def test_index_has_two_pages_with_text(self):
        self.assertEqual(self.index.page_count, 2)
        self.assertTrue(self.index.has_text_layer)
        self.assertIn("annealed at 500", self.index.pages[0].normalized)

    def test_exact_hit_on_claimed_page(self):
        match = ev.find_quote(self.index, _PdfFixture.P1_EXACT, 1)
        self.assertEqual(match.quote_status, "verified_exact")
        self.assertEqual(match.page_status, "match")
        self.assertEqual(match.matched_page, 1)
        self.assertEqual(match.match_method, "exact")

    def test_line_break_hyphen_needs_normalized_match(self):
        match = ev.find_quote(self.index, _PdfFixture.P1_HYPHEN_QUOTE, 1)
        self.assertEqual(match.quote_status, "verified_normalized")
        self.assertEqual(match.page_status, "match")
        self.assertEqual(match.matched_quote, _PdfFixture.P1_HYPHEN_RAW)

    def test_wrong_claimed_page_is_mismatch_not_silent_fix(self):
        match = ev.find_quote(self.index, _PdfFixture.P2_LONG, 1)
        self.assertEqual(match.quote_status, "verified_exact")
        self.assertEqual(match.page_status, "mismatch")
        self.assertEqual(match.matched_page, 2)

    def test_missing_claimed_page_is_derived(self):
        match = ev.find_quote(self.index, _PdfFixture.P2_LONG, None)
        self.assertEqual(match.page_status, "derived")
        self.assertEqual(match.matched_page, 2)

    def test_out_of_range_claimed_page(self):
        match = ev.find_quote(self.index, _PdfFixture.P2_LONG, 99)
        self.assertEqual(match.quote_status, "verified_exact")
        self.assertEqual(match.page_status, "invalid_page")

    def test_duplicate_quote_is_ambiguous(self):
        match = ev.find_quote(self.index, _PdfFixture.DUPLICATE, None)
        self.assertEqual(match.quote_status, "ambiguous")
        self.assertIsNotNone(match.failure_detail)

    def test_empty_quote_is_no_quote(self):
        self.assertEqual(ev.find_quote(self.index, "", 1).quote_status, "no_quote")
        self.assertEqual(ev.find_quote(self.index, "   ", None).quote_status, "no_quote")

    def test_forged_number_is_not_found_not_partial(self):
        match = ev.find_quote(self.index, "The samples were annealed at 900 °C for 2 h.", 1)
        self.assertEqual(match.quote_status, "not_found")

    def test_partial_match_is_reported_but_never_verified(self):
        match = ev.find_quote(self.index, _PdfFixture.P2_PARTIAL_QUOTE, 2)
        self.assertEqual(match.quote_status, "partial_match")
        self.assertGreaterEqual(match.match_ratio or 0.0, 0.6)
        self.assertNotEqual(
            ev.derive_display_status(match.quote_status, match.page_status, "value_in_quote"),
            "VERIFIED",
        )

    def test_bbox_is_lower_left_origin_and_positive_area(self):
        with fitz.open(self.pdf_path) as doc:
            bbox = ev.locate_bbox(doc[0], _PdfFixture.P1_EXACT)
            height = doc[0].rect.height
        self.assertIsNotNone(bbox)
        assert bbox is not None
        self.assertEqual(len(bbox), 4)
        self.assertLess(bbox[0], bbox[2])
        self.assertLess(bbox[1], bbox[3])
        self.assertGreater(bbox[1], height / 2)  # 페이지 상단 텍스트 → 좌하단 원점에서 y가 크다

    def test_bbox_of_unknown_text_is_none(self):
        with fitz.open(self.pdf_path) as doc:
            self.assertIsNone(ev.locate_bbox(doc[0], "no such text in this document at all"))


class RecipeParameterIterationTests(unittest.TestCase):
    def test_index_alignment_matches_frontend_parser_rules(self):
        recipe = {
            "parameters": [
                {"name": "a", "value": "1"},
                "Temperature: 500 C",
                42,                       # 프론트가 건너뛰는 타입 — 백엔드도 건너뛴다
                {"parameter": "b", "val": "2"},
                None,                     # 프론트의 p !== null 가드와 동일
            ]
        }
        parsed = ev.iter_recipe_parameters(recipe)
        self.assertEqual([index for index, _ in parsed], [0, 1, 2])
        self.assertEqual([param["name"] for _, param in parsed], ["a", "Temperature", "b"])
        self.assertEqual(parsed[1][1]["value"], "500 C")
        self.assertEqual(ev.count_recipe_parameters(recipe), 3)

    def test_no_parameters_returns_empty(self):
        self.assertEqual(ev.iter_recipe_parameters({}), [])
        self.assertEqual(ev.iter_recipe_parameters({"parameters": "nope"}), [])


class VerifyRecipeParametersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        handle.close()
        cls.pdf_path = handle.name
        _PdfFixture.write(cls.pdf_path)

        blank = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        blank.close()
        cls.blank_path = blank.name
        _PdfFixture.write_blank(cls.blank_path)

    @classmethod
    def tearDownClass(cls):
        os.unlink(cls.pdf_path)
        os.unlink(cls.blank_path)

    def _drafts(self, parameters):
        return ev.verify_recipe_parameters({"parameters": parameters}, self.pdf_path)

    def test_happy_path_is_verified_with_bbox(self):
        drafts = self._drafts([
            {"name": "annealing_temperature", "value": "500", "unit": "°C",
             "source_tag": "explicit", "evidence_quote": _PdfFixture.P1_EXACT, "evidence_page": 1},
        ])
        draft = drafts[0]
        self.assertEqual(draft.display_status, "VERIFIED")
        self.assertEqual(draft.quote_status, "verified_exact")
        self.assertEqual(draft.value_status, "value_in_quote")
        self.assertEqual(draft.target_key, "p000:annealing-temperature")
        self.assertEqual(draft.target_label, "annealing_temperature")
        self.assertEqual(draft.corpus, "pdf_text")
        self.assertIsNotNone(draft.bbox_json)
        self.assertEqual(len(json.loads(draft.bbox_json)), 4)

    def test_value_not_in_quote_blocks_verification(self):
        drafts = self._drafts([
            {"name": "annealing_temperature", "value": "900", "unit": "°C",
             "source_tag": "explicit", "evidence_quote": _PdfFixture.P1_EXACT, "evidence_page": 1},
        ])
        self.assertEqual(drafts[0].quote_status, "verified_exact")
        self.assertEqual(drafts[0].value_status, "value_missing")
        self.assertEqual(drafts[0].display_status, "UNVERIFIED_VALUE_MISMATCH")

    def test_inferred_parameter_is_never_verified(self):
        drafts = self._drafts([
            {"name": "power_density", "value": "500", "source_tag": "inferred",
             "evidence_quote": _PdfFixture.P1_EXACT, "evidence_page": 1},
        ])
        self.assertEqual(drafts[0].display_status, "UNVERIFIED_INFERRED")
        self.assertEqual(drafts[0].matched_page, 1)  # 계산 근거 위치는 그래도 제공한다

    def test_missing_quote_is_no_quote(self):
        drafts = self._drafts([{"name": "x", "value": "1", "source_tag": "explicit"}])
        self.assertEqual(drafts[0].display_status, "UNVERIFIED_NO_QUOTE")

    def test_forged_quotes_produce_zero_false_verify(self):
        forged = [
            "The samples were annealed at 900 °C for 2 h.",
            "We used a wavelength of 1560 nm in the setup.",
            "In this experiment the beam diameter was measured as 12.8 mm "
            "at the output aperture of the telescope.",
        ]
        drafts = self._drafts([
            {"name": f"p{i}", "value": "1", "source_tag": "explicit", "evidence_quote": quote,
             "evidence_page": 1}
            for i, quote in enumerate(forged)
        ])
        self.assertEqual([d.display_status for d in drafts if d.display_status == "VERIFIED"], [])

    def test_scanned_pdf_without_text_layer(self):
        drafts = ev.verify_recipe_parameters(
            {"parameters": [{"name": "x", "value": "1", "source_tag": "explicit",
                             "evidence_quote": "anything", "evidence_page": 1}]},
            self.blank_path,
        )
        self.assertEqual(drafts[0].quote_status, "no_text_layer")
        self.assertEqual(drafts[0].display_status, "UNVERIFIED_NO_TEXT_LAYER")

    def test_missing_pdf_still_produces_one_draft_per_parameter(self):
        drafts = ev.verify_recipe_parameters(
            {"parameters": [{"name": "x", "value": "1"}, {"name": "y", "value": "2"}]},
            "/tmp/definitely-not-a-real-file-8f2a.pdf",
        )
        self.assertEqual(len(drafts), 2)
        self.assertEqual({d.failure_detail for d in drafts}, {"pdf_missing"})
        self.assertEqual({d.display_status for d in drafts}, {"UNVERIFIED_NO_TEXT_LAYER"})

    def test_every_parameter_gets_exactly_one_draft(self):
        parameters = [
            {"name": "a", "value": "500", "source_tag": "explicit",
             "evidence_quote": _PdfFixture.P1_EXACT, "evidence_page": 1},
            "Temperature: 500 C",
            {"name": "c", "value": "1", "source_tag": "explicit",
             "evidence_quote": "x", "evidence_page": "not-a-number"},
        ]
        drafts = self._drafts(parameters)
        self.assertEqual(len(drafts), 3)
        self.assertEqual([d.target_index for d in drafts], [0, 1, 2])
        self.assertTrue(all(d.verifier_version == ev.EVIDENCE_VERIFIER_VERSION for d in drafts))
        self.assertTrue(all(d.quote_status in ev.QUOTE_STATUSES for d in drafts))
```

- [ ] **Step 2: 실패 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services/test_evidence_verifier.py -q
```

기대 출력: `AttributeError: module 'services.evidence_verifier' has no attribute 'build_pdf_index'`
(Task 2 테스트 26개는 계속 통과).

- [ ] **Step 3: PDF 대조 계층 구현** — `sasoo/backend/services/evidence_verifier.py`의 import 블록을
  아래로 교체하고(기존 `import re` / `import unicodedata`는 유지), 파일 **끝에** 2부를 추가한다.

import 블록:

```python
from __future__ import annotations

import difflib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import fitz
```

파일 끝에 추가:

```python
# ---------------------------------------------------------------------------
# PDF 텍스트층 인덱스
# ---------------------------------------------------------------------------
# 대조 원본은 PDF 텍스트층 하나뿐이다. 매니페스트 full_text는 Gemini 경로에서 다른 LLM의
# 전사본일 수 있어(순환 검증) 쓰지 않는다. 실측: 축자 인용을 full_text로 대조하면 70.7%만
# 확인되고(ODL 83.0% / Gemini 33.6%), PDF 텍스트층으로 대조하면 91.4%가 확인된다.


@dataclass(frozen=True, slots=True)
class PageText:
    page_number: int
    raw: str
    normalized: str
    source_map: tuple[int, ...]
    tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PdfTextIndex:
    pages: tuple[PageText, ...]
    page_count: int

    @property
    def has_text_layer(self) -> bool:
        return any(page.normalized for page in self.pages)


@dataclass(frozen=True, slots=True)
class QuoteMatch:
    quote_status: str
    page_status: str
    matched_page: int | None = None
    matched_quote: str | None = None
    match_method: str | None = None
    match_ratio: float | None = None
    failure_detail: str | None = None


def _index_from_doc(doc) -> PdfTextIndex:
    pages: list[PageText] = []
    for number in range(1, doc.page_count + 1):
        raw = doc[number - 1].get_text() or ""
        normalized, source_map = normalize_with_map(raw)
        pages.append(
            PageText(
                page_number=number,
                raw=raw,
                normalized=normalized,
                source_map=tuple(source_map),
                tokens=tuple(normalized.split(" ")) if normalized else (),
            )
        )
    return PdfTextIndex(pages=tuple(pages), page_count=doc.page_count)


def build_pdf_index(pdf_path) -> PdfTextIndex:
    with fitz.open(str(pdf_path)) as doc:
        return _index_from_doc(doc)


# ---------------------------------------------------------------------------
# 인용 검색
# ---------------------------------------------------------------------------

_MIN_PARTIAL_TOKENS = 8
_MIN_PARTIAL_RATIO = 0.6
_PARTIAL_PAGE_CANDIDATES = 3


def _claim_is_valid(claimed_page, page_count: int) -> bool:
    return isinstance(claimed_page, int) and not isinstance(claimed_page, bool) and 1 <= claimed_page <= page_count


def _unlocated_page_status(claimed_page, page_count: int) -> str:
    if claimed_page is None or _claim_is_valid(claimed_page, page_count):
        return "no_page"
    return "invalid_page"


def _located_page_status(claimed_page, found_page: int, page_count: int) -> str:
    if claimed_page is None:
        return "derived"
    if not _claim_is_valid(claimed_page, page_count):
        return "invalid_page"
    return "match" if claimed_page == found_page else "mismatch"


def _raw_span(page: PageText, start: int, end_exclusive: int) -> str:
    raw_start = page.source_map[start]
    raw_end = page.source_map[end_exclusive - 1] + 1
    return page.raw[raw_start:raw_end]


def _exact_on_page(page: PageText, raw_needle: str) -> str | None:
    return raw_needle if raw_needle and raw_needle in page.raw else None


def _normalized_on_page(page: PageText, normalized_needle: str) -> str | None:
    start = page.normalized.find(normalized_needle)
    if start < 0:
        return None
    return _raw_span(page, start, start + len(normalized_needle))


def _token_char_span(tokens: tuple[str, ...], start: int, size: int) -> tuple[int, int]:
    """정규화 문자열은 토큰을 스페이스 1개로 이은 것이므로 오프셋이 정확히 계산된다."""
    prefix = sum(len(token) + 1 for token in tokens[:start])
    length = sum(len(token) + 1 for token in tokens[start : start + size]) - 1
    return prefix, prefix + length


def _best_partial(index: PdfTextIndex, normalized_needle: str):
    """부분 일치는 '검증'이 아니라 탐색 보조다. 최장 공통 블록 기준으로만 계산한다."""
    quote_tokens = normalized_needle.split(" ")
    if len(quote_tokens) < _MIN_PARTIAL_TOKENS:
        return None
    quote_set = set(quote_tokens)
    ranked = sorted(
        (page for page in index.pages if page.tokens),
        key=lambda page: (-len(quote_set & set(page.tokens)), page.page_number),
    )[:_PARTIAL_PAGE_CANDIDATES]

    best = None
    for page in ranked:
        matcher = difflib.SequenceMatcher(None, quote_tokens, list(page.tokens), autojunk=False)
        block = matcher.find_longest_match(0, len(quote_tokens), 0, len(page.tokens))
        if block.size < _MIN_PARTIAL_TOKENS:
            continue
        ratio = block.size / len(quote_tokens)
        if ratio < _MIN_PARTIAL_RATIO:
            continue
        if best is None or ratio > best[2]:
            start, end = _token_char_span(page.tokens, block.b, block.size)
            best = (page, _raw_span(page, start, end), ratio)
    return best


def find_quote(index: PdfTextIndex, quote: str, claimed_page: int | None) -> QuoteMatch:
    """검색 순서(스펙): 주장 페이지 exact → 주장 페이지 normalized → 전문 exact → 전문 normalized → 부분.

    주장 페이지가 틀렸을 때 발견 페이지로 조용히 고쳐 VERIFIED를 주지 않는다 —
    page_status='mismatch'로 남기고 발견 페이지는 진단 필드로 보존한다.
    """
    raw_needle = str(quote or "").strip()
    normalized_needle = normalize_text(raw_needle)
    page_count = index.page_count

    if not normalized_needle:
        return QuoteMatch("no_quote", _unlocated_page_status(claimed_page, page_count))
    if not index.has_text_layer:
        return QuoteMatch(
            "no_text_layer",
            _unlocated_page_status(claimed_page, page_count),
            failure_detail="empty_text_layer",
        )

    if _claim_is_valid(claimed_page, page_count):
        page = index.pages[claimed_page - 1]
        hit = _exact_on_page(page, raw_needle)
        if hit is not None:
            return QuoteMatch("verified_exact", "match", page.page_number, hit, "exact", 1.0)
        hit = _normalized_on_page(page, normalized_needle)
        if hit is not None:
            return QuoteMatch("verified_normalized", "match", page.page_number, hit, "normalized", 1.0)

    for status, method, finder, needle in (
        ("verified_exact", "exact", _exact_on_page, raw_needle),
        ("verified_normalized", "normalized", _normalized_on_page, normalized_needle),
    ):
        hits = [(page, finder(page, needle)) for page in index.pages]
        hits = [(page, hit) for page, hit in hits if hit is not None]
        if len(hits) == 1:
            page, hit = hits[0]
            return QuoteMatch(
                status,
                _located_page_status(claimed_page, page.page_number, page_count),
                page.page_number,
                hit,
                method,
                1.0,
            )
        if len(hits) > 1:
            page, hit = hits[0]
            return QuoteMatch(
                "ambiguous",
                _unlocated_page_status(claimed_page, page_count),
                page.page_number,
                hit,
                method,
                1.0,
                failure_detail=f"multi_page:{len(hits)}",
            )

    partial = _best_partial(index, normalized_needle)
    if partial is not None:
        page, matched, ratio = partial
        return QuoteMatch(
            "partial_match",
            _unlocated_page_status(claimed_page, page_count),
            page.page_number,
            matched,
            "partial",
            round(ratio, 3),
        )

    return QuoteMatch("not_found", _unlocated_page_status(claimed_page, page_count))


# ---------------------------------------------------------------------------
# bbox
# ---------------------------------------------------------------------------


def locate_bbox(page, matched_quote: str | None) -> list[float] | None:
    """확인된 원문 span의 bbox를 PDF 포인트·좌하단 원점으로 반환한다.

    첫 매치 rect만 쓴다 — 다단 조판에서 union은 과대 박스가 되어 오히려 오해를 만든다
    (스펙 §알려진 위험 3). 실패하면 None이고, UI는 페이지 점프로 폴백한다.
    """
    needle = str(matched_quote or "").strip()
    if not needle:
        return None
    try:
        rects = page.search_for(needle)
        if not rects and len(needle) > 40:
            rects = page.search_for(needle[:40])
        if not rects:
            return None
        rect = rects[0]
        height = float(page.rect.height)
        bbox = [
            round(float(rect.x0), 2),
            round(height - float(rect.y1), 2),
            round(float(rect.x1), 2),
            round(height - float(rect.y0), 2),
        ]
    except Exception:
        return None
    if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
        return None
    return bbox


# ---------------------------------------------------------------------------
# Recipe 파라미터 순회 (프론트 파서와 규칙이 반드시 같아야 한다)
# ---------------------------------------------------------------------------
# 프론트는 parameters[] 중 object(null 제외)와 string만 화면 행으로 만든다. 백엔드가 다른
# 규칙으로 세면 target_index가 밀려 엉뚱한 파라미터에 근거가 붙는다 — 스펙 §5의 fail-closed
# 조건이 걸리기 전에 애초에 어긋나지 않게 규칙을 맞춘다.

_STRING_PARAM_PATTERN = re.compile(r"^(.+?):\s*(.+)$")


def _first_str(source: dict, *keys: str) -> str:
    """JS의 `a || b || c` 폴백을 그대로 옮긴다(0과 ""는 falsy로 취급)."""
    for key in keys:
        value = source.get(key)
        if value is None or value is False or value == "" or value == 0:
            continue
        return str(value)
    return ""


def _param_from_dict(item: dict) -> dict:
    return {
        "name": _first_str(item, "name", "Name", "parameter", "key"),
        "value": _first_str(item, "value", "Value", "val"),
        "unit": _first_str(item, "unit", "Unit", "units"),
        "notes": _first_str(item, "notes", "Notes", "note", "context"),
        "source_tag": _first_str(item, "source_tag"),
        "evidence_quote": _first_str(item, "evidence_quote"),
        "evidence_page": item.get("evidence_page"),
    }


def _param_from_string(item: str) -> dict:
    match = _STRING_PARAM_PATTERN.match(item)
    if match:
        name, value = match.group(1).strip(), match.group(2).strip()
    else:
        name, value = item, ""
    return {
        "name": name,
        "value": value,
        "unit": "",
        "notes": "",
        "source_tag": "",
        "evidence_quote": "",
        "evidence_page": None,
    }


def iter_recipe_parameters(recipe: dict) -> list[tuple[int, dict]]:
    raw = recipe.get("parameters") if isinstance(recipe, dict) else None
    if not isinstance(raw, list):
        return []
    parsed: list[dict] = []
    for item in raw:
        if isinstance(item, dict):
            parsed.append(_param_from_dict(item))
        elif isinstance(item, list):
            parsed.append(_param_from_dict({}))  # JS의 typeof [] === 'object'와 동형
        elif isinstance(item, str):
            parsed.append(_param_from_string(item))
    return list(enumerate(parsed))


def count_recipe_parameters(recipe: dict) -> int:
    return len(iter_recipe_parameters(recipe))


# ---------------------------------------------------------------------------
# 앵커 초안 생성
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvidenceAnchorDraft:
    target_kind: str
    target_key: str
    target_index: int
    target_label: str
    source_tag: str | None
    claimed_quote: str
    claimed_page: int | None
    quote_status: str
    page_status: str
    value_status: str
    display_status: str
    match_method: str | None
    match_ratio: float | None
    matched_quote: str | None
    matched_page: int | None
    bbox_json: str | None
    corpus: str
    failure_detail: str | None
    verifier_version: str
    normalizer_version: str


def _coerce_page(value) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _draft(
    param_index: int,
    param: dict,
    *,
    quote_status: str,
    page_status: str,
    value_status: str,
    match_method: str | None = None,
    match_ratio: float | None = None,
    matched_quote: str | None = None,
    matched_page: int | None = None,
    bbox: list[float] | None = None,
    failure_detail: str | None = None,
) -> EvidenceAnchorDraft:
    name = param.get("name", "")
    return EvidenceAnchorDraft(
        target_kind="recipe_parameter",
        target_key=build_target_key(param_index, name),
        target_index=param_index,
        target_label=name,
        source_tag=param.get("source_tag") or None,
        claimed_quote=str(param.get("evidence_quote") or ""),
        claimed_page=_coerce_page(param.get("evidence_page")),
        quote_status=quote_status,
        page_status=page_status,
        value_status=value_status,
        display_status=derive_display_status(quote_status, page_status, value_status),
        match_method=match_method,
        match_ratio=match_ratio,
        matched_quote=matched_quote,
        matched_page=matched_page,
        bbox_json=json.dumps(bbox) if bbox else None,
        corpus=EVIDENCE_CORPUS_PDF_TEXT,
        failure_detail=failure_detail,
        verifier_version=EVIDENCE_VERIFIER_VERSION,
        normalizer_version=EVIDENCE_NORMALIZER_VERSION,
    )


def _unverifiable(param_index: int, param: dict, quote_status: str, detail: str) -> EvidenceAnchorDraft:
    value_status, _ = check_value_in_quote(param.get("value", ""), param.get("source_tag"), None)
    return _draft(
        param_index,
        param,
        quote_status=quote_status,
        page_status="no_page",
        value_status=value_status,
        failure_detail=detail,
    )


def _verify_parameter(doc, index: PdfTextIndex, param_index: int, param: dict) -> EvidenceAnchorDraft:
    try:
        match = find_quote(index, param.get("evidence_quote", ""), _coerce_page(param.get("evidence_page")))
        value_status, value_detail = check_value_in_quote(
            param.get("value", ""), param.get("source_tag"), match.matched_quote
        )
        bbox = None
        if match.matched_page is not None and match.matched_quote:
            bbox = locate_bbox(doc[match.matched_page - 1], match.matched_quote)
        return _draft(
            param_index,
            param,
            quote_status=match.quote_status,
            page_status=match.page_status,
            value_status=value_status,
            match_method=match.match_method,
            match_ratio=match.match_ratio,
            matched_quote=match.matched_quote,
            matched_page=match.matched_page,
            bbox=bbox,
            failure_detail=match.failure_detail or value_detail,
        )
    except Exception as exc:  # 파라미터 하나의 실패가 나머지를 죽이지 않는다
        return _unverifiable(param_index, param, "verifier_error", type(exc).__name__)


def verify_recipe_parameters(recipe: dict, pdf_path=None) -> list[EvidenceAnchorDraft]:
    """파라미터마다 앵커 초안을 정확히 1건씩 만든다. 실패도 앵커로 남긴다(침묵 금지)."""
    parameters = iter_recipe_parameters(recipe)
    if not parameters:
        return []

    path = Path(pdf_path) if pdf_path else None
    if path is None or not path.exists():
        return [_unverifiable(i, p, "no_text_layer", "pdf_missing") for i, p in parameters]

    try:
        with fitz.open(str(path)) as doc:
            index = _index_from_doc(doc)
            if not index.has_text_layer:
                return [_unverifiable(i, p, "no_text_layer", "empty_text_layer") for i, p in parameters]
            return [_verify_parameter(doc, index, i, p) for i, p in parameters]
    except Exception as exc:
        return [_unverifiable(i, p, "verifier_error", type(exc).__name__) for i, p in parameters]
```

- [ ] **Step 4: 통과 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services/test_evidence_verifier.py -q
```

기대 출력: `50 passed` (Task 2의 26 + 인덱스/검색 12 + 파라미터 순회 2 + verify 10).
숫자가 다르면 어떤 테스트가 빠졌는지 확인한다.

- [ ] **Step 5: 성능 확인(선택, 실측 기록용)** — 라이브러리 PDF가 있으면 인덱스 비용을 잰다.

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -c "
import glob, time, sys
sys.path.insert(0, '.')
from services.evidence_verifier import build_pdf_index
paths = sorted(glob.glob('library/*/*.pdf'))[:3]
for path in paths:
    started = time.perf_counter()
    index = build_pdf_index(path)
    print(f'{index.page_count:>4}p  {(time.perf_counter()-started)*1000:7.1f} ms  {path}')
"
```

기대: 페이지당 10ms 미만. 논문 1편이 1초를 넘으면 태스크 보고서에 실측값을 남긴다
(동기 실행 유지 판단의 근거다). PDF가 없으면 "미측정"으로 기록하고 넘어간다.

- [ ] **Step 6: 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중 && git add -A && git commit -m "$(cat <<'EOF'
feat(evidence): PDF 텍스트층 대조 검증기와 bbox 산출 추가

검색 순서는 주장 페이지 exact → 주장 페이지 normalized → 전문 exact → 전문 normalized →
부분 일치다. 주장 페이지가 틀리면 조용히 고치지 않고 page_status=mismatch로 남긴다.
bbox는 search_for 첫 매치 rect만 써서 다단 조판 과대 박스를 피하고, 좌하단 원점
PDF 포인트로 figures/tables와 규약을 통일했다. 파라미터 순회 규칙을 프론트 파서와
일치시켜 target_index 밀림을 원천 차단한다.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: _RECIPE_SCHEMA 확장 · 축자 인용 지시문 · 캐시 버전 bump

LLM의 역할은 후보 생성까지다. `verification_status`/`bbox`류는 **절대** LLM 출력 필드로 두지 않는다.

**Files**

- Modify: `sasoo/backend/api/analysis_routes.py` (`_RECIPE_SCHEMA`, `_run_recipe`의 `instruction`, `_CHAIN_CACHE_VERSION`)
- Modify: `sasoo/backend/api/test_analysis_routes.py` (기존 recipe 프롬프트 테스트 확장 + 신규 테스트)

**Interfaces**

Consumes: 없음(라우트 내부 상수)

Produces:
- `_RECIPE_SCHEMA.properties.parameters.items.properties`에 `evidence_quote: {"type": "string"}`,
  `evidence_page: {"type": "integer"}` 추가. `required`는 `["name", "value", "source_tag"]`.
- `_CHAIN_CACHE_VERSION = "2026-08-06-ev1"`
- recipe `instruction`에 규칙 7~11(축자 인용, 가장 짧은 연속 스팬, 1-based PDF 페이지,
  빈 인용 허용, 인용 출처 제한) 추가

**Steps**

- [ ] **Step 1: 실패 테스트 작성** — `sasoo/backend/api/test_analysis_routes.py`에서
  `self.assertIn("score_rationale", captured["response_schema"]["properties"])`가 있는 줄
  (`test_recipe_prompt_removes_count_floor_and_adds_source_tag`의 마지막 줄)을 찾아 그 **뒤에**
  아래 5줄을 추가한다.

```python
        # Evidence Anchoring: LLM은 후보만 낸다(검증 상태·bbox는 LLM 필드가 아니다)
        self.assertEqual(param_props["evidence_quote"]["type"], "string")
        self.assertEqual(param_props["evidence_page"]["type"], "integer")
        self.assertNotIn("verification_status", param_props)
        self.assertNotIn("bbox", param_props)
        self.assertEqual(
            captured["response_schema"]["properties"]["parameters"]["items"]["required"],
            ["name", "value", "source_tag"],
        )
```

  이어서 같은 클래스 안, 그 테스트 메서드 **바로 뒤에** 신규 테스트를 추가한다.

```python
    async def test_recipe_prompt_demands_verbatim_shortest_span_quote(self):
        status = AnalysisStatus(paper_id=7, overall_status="running", phases=[], progress_pct=0.0)
        captured = {}

        async def _fake_call(prompt, **kwargs):
            captured["prompt"] = prompt
            captured.update(kwargs)
            return {
                "text": '{"title":"레시피","objective":"목적","parameters":[],"steps":[]}',
                "model": "gemini", "tokens_in": 10, "tokens_out": 20, "interaction_id": None,
            }

        with (
            patch("api.analysis_routes._get_cached_phase_result", new=AsyncMock(return_value=None)),
            patch("api.analysis_routes.call_interaction", new=_fake_call),
            patch("api.analysis_routes._insert_analysis_result", new=AsyncMock()),
        ):
            await analysis_routes._run_recipe(
                7, "Recipe context body", status, screening_result_text='{"domain":"optics"}',
            )

        prompt = captured["prompt"]
        self.assertIn("evidence_quote", prompt)
        self.assertIn("evidence_page", prompt)
        self.assertIn("축자", prompt)
        self.assertIn("가장 짧은 연속", prompt)
        self.assertIn("1-based", prompt)
        # 빈 근거가 지어낸 근거보다 낫다 — 인용을 강제하지 않는다
        self.assertIn("빈 문자열", prompt)

    def test_chain_cache_version_is_bumped_for_evidence_rollout(self):
        # 스펙 §결정 4: 롤아웃 시 체인 캐시 1회 무효화
        self.assertEqual(analysis_routes._CHAIN_CACHE_VERSION, "2026-08-06-ev1")
        self.assertIn(
            analysis_routes._CHAIN_CACHE_VERSION,
            analysis_routes._phase_cache_key(model="m", thinking="t", system_instruction="s", prompt="p"),
        )
```

- [ ] **Step 2: 실패 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest api/test_analysis_routes.py -q -k "recipe_prompt or chain_cache_version"
```

기대: `KeyError: 'evidence_quote'`와 `AssertionError: '2026-08-06' != '2026-08-06-ev1'`로 3개 실패.

- [ ] **Step 3: 스키마 확장** — `_RECIPE_SCHEMA`의 `parameters.items`에서
  `"source_tag": {"type": "string", "enum": ["explicit", "inferred"]},` 줄을 찾아 그 뒤에 두 필드를
  추가하고 `required`를 바꾼다. 다른 필드는 건드리지 않는다.

```python
                    "source_tag": {"type": "string", "enum": ["explicit", "inferred"]},
                    # Evidence Anchoring(Phase 1): LLM은 후보만 낸다.
                    # verification_status·matched_quote·bbox는 절대 LLM 출력 필드로 두지 않는다.
                    "evidence_quote": {"type": "string"},
                    # 1-based PDF 페이지. Gemini structured output이 minimum을 일관되게
                    # 지원하지 않아 범위 제약은 스키마가 아니라 검증기가 건다(invalid_page).
                    "evidence_page": {"type": "integer"},
                },
                "required": ["name", "value", "source_tag"],
```

- [ ] **Step 4: 지시문 추가** — `_run_recipe` 안의 `instruction = f"""..."""`에서
  `6. reproducibility_score는 ...` 줄을 찾아 그 **뒤, `{domain_hint}` 앞에** 규칙 7~11을 넣는다.

```python
7. 각 파라미터마다 그 값의 근거가 되는 논문 원문을 그대로(축자) evidence_quote에 옮겨.
   번역·요약·재작성·말줄임표·떨어져 있는 문장 결합은 금지야. 원문 언어 그대로 써.
8. evidence_quote는 그 파라미터를 뒷받침하는 가장 짧은 연속 스팬 하나로 해(1~2문장, 최대 300자).
   source_tag="explicit"이면 그 value가 인용 안에 실제로 들어 있어야 해.
9. evidence_page는 PDF 파일 기준 1-based 페이지 번호야(표지 포함). 논문에 인쇄된 페이지 번호가 아니야.
   논문 텍스트만 받은 경우에는 "--- Page N ---" 마커의 N을 써.
10. 축자로 옮길 수 없으면 evidence_quote를 빈 문자열로 두고 페이지도 추측하지 마.
    빈 근거가 지어낸 근거보다 나아 — 근거 없음은 화면에 그대로 표시돼.
11. 인용은 논문 PDF(또는 제공된 논문 텍스트)에서만 가져와. 앞선 단계(스크리닝·시각·인용 분석)
    결과는 인용 출처가 아니야.
```

  같은 문자열의 마지막 "출력 필드:" 문단에서
  `equipment(장비 리스트, 모델번호 포함), parameters(각 항목 name/value/unit/notes/source_tag),`
  줄을 찾아 다음으로 바꾼다(다른 줄은 그대로).

```python
equipment(장비 리스트, 모델번호 포함), parameters(각 항목 name/value/unit/notes/source_tag/evidence_quote/evidence_page),
```

- [ ] **Step 5: 캐시 버전 bump** — `_CHAIN_CACHE_VERSION = "2026-08-06"` 줄과 그 위 주석을 찾아
  아래로 바꾼다(주석은 대체가 아니라 한 문단 추가다).

```python
# Phase 0(2026-08-06): 캐시 키에 프로필·에이전트 지침(system_instruction)·모델·thinking을
# 포함한다. 값을 올리면 모든 체인 phase 캐시가 무효화된다.
# Phase 1(2026-08-06, Evidence Anchoring): 스펙 §결정 4에 따라 롤아웃 시 1회 bump한다.
# recipe 파라미터에 evidence_quote/evidence_page가 생겨 구 스키마 결과를 재사용하면
# 근거 없는 파라미터가 영구히 남는다. 체인 phase 전체가 1회 재과금되는 것을 알고 하는 선택이다.
_CHAIN_CACHE_VERSION = "2026-08-06-ev1"
```

- [ ] **Step 6: 통과 확인 + 전체 회귀**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest api/test_analysis_routes.py -q
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services api models -q
```

기대: 전부 통과. `_run_recipe` 관련 기존 테스트 4건(`test_run_recipe_uses_current_screening_data_without_db_read`,
`test_recipe_prompt_removes_count_floor_and_adds_source_tag`, `test_run_recipe_skips_when_screening_signal_is_weak`,
`test_recipe_stage_forwards_chain_params`)이 계속 통과해야 한다.

- [ ] **Step 7: 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중 && git add -A && git commit -m "$(cat <<'EOF'
feat(analysis): recipe 파라미터에 evidence_quote·evidence_page 후보 필드 추가

LLM 역할은 후보 생성까지다 — 검증 상태와 bbox는 결정론적 코드가 만든다.
source_tag를 required로 올리고, 축자 인용·가장 짧은 연속 스팬·1-based PDF 페이지·
빈 인용 허용을 지시문에 명시했다. 구 스키마 결과 재사용을 막기 위해
_CHAIN_CACHE_VERSION을 1회 bump한다(체인 phase 전체 재과금 1회).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 캐시 result_id 배선과 `_run_recipe` 동기 검증 통합

검증은 recipe row 저장(`lastrowid` 확보) 직후, phase completed 노출 전에 동기 실행한다.
**캐시 히트 경로도 예외가 아니다** — 그 경로가 옛 결과 백필과 검증기 버전업 재검증의
유일한 통로다.

**Files**

- Create: `sasoo/backend/services/evidence_repo.py`
- Create: `sasoo/backend/services/test_evidence_repo.py`
- Modify: `sasoo/backend/services/document_context.py` (`CachedPhaseResult.result_id`, SELECT에 `id`)
- Modify: `sasoo/backend/services/test_document_context.py` (result_id 전달 테스트 추가)
- Modify: `sasoo/backend/api/analysis_routes.py` (`_get_cached_phase_result`, `_insert_analysis_result`,
  `_ensure_recipe_evidence`, `_run_recipe`, `_run_full_analysis` 호출부)
- Modify: `sasoo/backend/api/test_analysis_routes.py` (통합 테스트 3건 + 기존 캐시 테스트 1건 보강)

**Interfaces**

Consumes:
- Task 1: `models.evidence_anchors.{upsert_anchors, fetch_anchors, anchor_versions, EVIDENCE_ANCHORS_DDL}`
- Task 3: `services.evidence_verifier.{verify_recipe_parameters, count_recipe_parameters,
  EVIDENCE_VERIFIER_VERSION, EVIDENCE_NORMALIZER_VERSION, EvidenceAnchorDraft}`
- 기존: `services.concurrency.run_pipeline_blocking`, `models.database.get_db`,
  `api.analysis_routes._find_paper_pdf`, `models.database.get_paper_dir`

Produces:

```python
# sasoo/backend/services/evidence_repo.py
async def ensure_recipe_anchors(
    *, paper_id: int, analysis_result_id: int, recipe_text: str, pdf_path, force: bool = False
) -> dict: ...
#   반환 status: "verified" | "up_to_date" | "skipped_unparsable" | "skipped_no_parameters"

async def build_evidence_payload(analysis_result_id: int | None) -> dict | None: ...
#   {"verifier_version", "normalizer_version",
#    "summary": {"total", "verified", "by_display_status"},
#    "anchors": [{... + "bbox": [x0,y0,x1,y1] | None}]}
#   앵커가 없으면 None

# sasoo/backend/services/document_context.py
@dataclass(slots=True)
class CachedPhaseResult:
    result_text: str; result_data: dict; model_used: str
    tokens_in: int; tokens_out: int; cost_usd: float
    input_hash: Optional[str]
    result_id: int          # 신규 — 캐시 소스 analysis_results.id (없으면 0)

# sasoo/backend/api/analysis_routes.py
async def _insert_analysis_result(...) -> int:   # 반환 타입 None → int (lastrowid)
async def _ensure_recipe_evidence(*, paper_id, analysis_result_id, recipe_text, folder_name) -> None
async def _run_recipe(..., *, ..., folder_name: str = "") -> dict   # 신규 kwarg
# _get_cached_phase_result 반환 dict에 "result_id" 키 추가
```

**Steps**

- [ ] **Step 1: 캐시 result_id 실패 테스트** — `sasoo/backend/services/test_document_context.py`의
  `test_find_cached_phase_result_returns_normal_json_row` 메서드를 찾아 그 **뒤에** 추가한다.

```python
    async def test_find_cached_phase_result_carries_source_row_id(self):
        """캐시 히트 경로에서 근거 백필을 하려면 소스 analysis_results.id가 필요하다."""
        input_text = "recipe input"
        row = {
            "id": 4242,
            "result": '{"title":"레시피"}',
            "model_used": "gemini",
            "tokens_in": 1,
            "tokens_out": 2,
            "cost_usd": 0.1,
            "input_hash": "abc",
        }
        with patch("services.document_context.fetch_one", new=AsyncMock(return_value=row)) as fetch_mock:
            cached = await find_cached_phase_result(7, "recipe", input_text)

        self.assertIsNotNone(cached)
        assert cached is not None
        self.assertEqual(cached.result_id, 4242)
        self.assertIn("id", fetch_mock.await_args.args[0])
```

- [ ] **Step 2: 실패 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services/test_document_context.py -q -k carries_source_row_id
```

기대: `AttributeError: 'CachedPhaseResult' object has no attribute 'result_id'`.

- [ ] **Step 3: CachedPhaseResult 확장** — `sasoo/backend/services/document_context.py`에서
  `class CachedPhaseResult`의 `input_hash: Optional[str]` 줄 뒤에 필드를 추가하고,
  `find_cached_phase_result`의 SELECT와 반환문을 고친다.

```python
@dataclass(slots=True)
class CachedPhaseResult:
    result_text: str
    result_data: dict[str, Any]
    model_used: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    input_hash: Optional[str]
    # 캐시 소스 행의 analysis_results.id. Evidence 백필·재검증이 LLM 재호출 없이
    # 이 id로 이루어진다(스펙 §결정 4). 조회 실패 시 0.
    result_id: int = 0
```

  SELECT 절:

```python
        SELECT id, result, model_used, tokens_in, tokens_out, cost_usd, input_hash
        FROM analysis_results
        WHERE paper_id = ? AND phase = ? AND input_hash = ?
        ORDER BY created_at DESC
        LIMIT 1
```

  반환문의 `input_hash=row.get("input_hash"),` 뒤에 추가:

```python
        result_id=int(row.get("id") or 0),
```

- [ ] **Step 4: 통과 확인 + 커밋 없이 다음 단계로**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services/test_document_context.py -q
```

기대: 전부 통과.

- [ ] **Step 5: evidence_repo 실패 테스트 작성** — `sasoo/backend/services/test_evidence_repo.py` 생성.

```python
"""services.evidence_repo 테스트 — 검증기와 evidence_anchors 사이 배선."""

import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import aiosqlite
import fitz

from models.evidence_anchors import EVIDENCE_ANCHORS_DDL, fetch_anchors
from services import evidence_repo


async def _run_inline(fn, *args):
    """run_pipeline_blocking 대체 — 테스트에서 스레드풀을 쓰지 않는다."""
    return fn(*args)


def _write_pdf(path: str) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), "The samples were annealed at 500 °C for 2 h.", fontsize=10, fontname="helv")
    doc.save(path)
    doc.close()


RECIPE = json.dumps(
    {
        "title": "레시피",
        "parameters": [
            {
                "name": "annealing_temperature",
                "value": "500",
                "unit": "°C",
                "source_tag": "explicit",
                "evidence_quote": "The samples were annealed at 500 °C for 2 h.",
                "evidence_page": 1,
            },
            {"name": "pressure", "value": "1", "source_tag": "explicit"},
        ],
    },
    ensure_ascii=False,
)


class EvidenceRepoTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        handle.close()
        self.db_path = handle.name
        self.conn = await aiosqlite.connect(self.db_path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(
            "CREATE TABLE papers (id INTEGER PRIMARY KEY);"
            "CREATE TABLE analysis_results (id INTEGER PRIMARY KEY, paper_id INTEGER);"
        )
        await self.conn.execute("INSERT INTO papers (id) VALUES (7)")
        await self.conn.execute("INSERT INTO analysis_results (id, paper_id) VALUES (41, 7)")
        await self.conn.executescript(EVIDENCE_ANCHORS_DDL)
        await self.conn.commit()

        pdf_handle = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        pdf_handle.close()
        self.pdf_path = pdf_handle.name
        _write_pdf(self.pdf_path)

        self._patches = [
            patch("services.evidence_repo.get_db", new=AsyncMock(return_value=self.conn)),
            patch("services.evidence_repo.run_pipeline_blocking", new=_run_inline),
        ]
        for item in self._patches:
            item.start()

    async def asyncTearDown(self):
        for item in self._patches:
            item.stop()
        await self.conn.close()
        os.unlink(self.db_path)
        os.unlink(self.pdf_path)

    async def _ensure(self, **overrides):
        kwargs = {
            "paper_id": 7,
            "analysis_result_id": 41,
            "recipe_text": RECIPE,
            "pdf_path": self.pdf_path,
        }
        kwargs.update(overrides)
        return await evidence_repo.ensure_recipe_anchors(**kwargs)

    async def test_writes_one_anchor_per_parameter(self):
        outcome = await self._ensure()
        self.assertEqual(outcome["status"], "verified")
        self.assertEqual(outcome["anchors"], 2)
        rows = await fetch_anchors(self.conn, 41)
        self.assertEqual([row["target_index"] for row in rows], [0, 1])
        self.assertEqual(rows[0]["display_status"], "VERIFIED")
        self.assertEqual(rows[1]["display_status"], "UNVERIFIED_NO_QUOTE")

    async def test_second_run_is_skipped_when_versions_match(self):
        await self._ensure()
        outcome = await self._ensure()
        self.assertEqual(outcome["status"], "up_to_date")

    async def test_force_reverifies(self):
        await self._ensure()
        outcome = await self._ensure(force=True)
        self.assertEqual(outcome["status"], "verified")
        self.assertEqual(len(await fetch_anchors(self.conn, 41)), 2)  # 중복 행이 아니라 갱신

    async def test_unparsable_recipe_is_skipped_without_anchors(self):
        outcome = await self._ensure(recipe_text='{"_raw":"...","_parse_error":"boom"}')
        self.assertEqual(outcome["status"], "skipped_unparsable")
        self.assertEqual(await fetch_anchors(self.conn, 41), [])

    async def test_skipped_phase_result_is_not_anchored(self):
        outcome = await self._ensure(recipe_text='{"skipped": true, "reason": "low_relevance"}')
        self.assertEqual(outcome["status"], "skipped_unparsable")

    async def test_recipe_without_parameters_is_skipped(self):
        outcome = await self._ensure(recipe_text='{"title":"t","parameters":[]}')
        self.assertEqual(outcome["status"], "skipped_no_parameters")

    async def test_missing_pdf_still_records_unverified_anchors(self):
        outcome = await self._ensure(pdf_path=None)
        self.assertEqual(outcome["anchors"], 2)
        rows = await fetch_anchors(self.conn, 41)
        self.assertEqual({row["display_status"] for row in rows}, {"UNVERIFIED_NO_TEXT_LAYER"})

    async def test_build_payload_returns_none_without_anchors(self):
        self.assertIsNone(await evidence_repo.build_evidence_payload(41))
        self.assertIsNone(await evidence_repo.build_evidence_payload(None))

    async def test_build_payload_shapes_read_model(self):
        await self._ensure()
        payload = await evidence_repo.build_evidence_payload(41)
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual(payload["summary"]["verified"], 1)
        self.assertEqual(payload["summary"]["by_display_status"]["UNVERIFIED_NO_QUOTE"], 1)
        first = payload["anchors"][0]
        self.assertEqual(first["target_label"], "annealing_temperature")
        self.assertEqual(len(first["bbox"]), 4)
        self.assertNotIn("bbox_json", first)  # 프론트에는 파싱된 배열만 준다


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 6: 실패 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services/test_evidence_repo.py -q
```

기대: `ModuleNotFoundError: No module named 'services.evidence_repo'`.

- [ ] **Step 7: evidence_repo 구현** — `sasoo/backend/services/evidence_repo.py` 생성.

```python
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
```

- [ ] **Step 8: 통과 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services/test_evidence_repo.py -q
```

기대: `10 passed`.

- [ ] **Step 9: `_run_recipe` 통합 실패 테스트** — `sasoo/backend/api/test_analysis_routes.py`에서
  `test_run_recipe_skips_when_screening_signal_is_weak` 메서드를 찾아 그 **뒤에** 3건을 추가한다.

```python
    async def test_run_recipe_anchors_evidence_with_inserted_row_id(self):
        """검증은 recipe row 저장 직후, phase completed 노출 전에 동기 실행된다."""
        status = AnalysisStatus(paper_id=7, overall_status="running", phases=[], progress_pct=0.0)

        async def _fake_call(prompt, **kwargs):
            return {
                "text": '{"title":"r","objective":"o","parameters":[{"name":"a","value":"1"}],"steps":[]}',
                "model": "gemini", "tokens_in": 1, "tokens_out": 1, "interaction_id": None,
            }

        ensure_mock = AsyncMock(return_value={"status": "verified", "anchors": 1})
        with (
            patch("api.analysis_routes._get_cached_phase_result", new=AsyncMock(return_value=None)),
            patch("api.analysis_routes.call_interaction", new=_fake_call),
            patch("api.analysis_routes._insert_analysis_result", new=AsyncMock(return_value=41)),
            patch("api.analysis_routes.get_paper_dir", return_value=Path("/tmp/sasoo-test-paper")),
            patch("api.analysis_routes._find_paper_pdf", return_value=None),
            patch("api.analysis_routes.ensure_recipe_anchors", new=ensure_mock),
        ):
            await analysis_routes._run_recipe(
                7, "body", status, screening_result_text='{"domain":"optics"}',
                folder_name="2026_Paper_optics",
            )

        ensure_mock.assert_awaited_once()
        self.assertEqual(ensure_mock.await_args.kwargs["analysis_result_id"], 41)
        self.assertEqual(ensure_mock.await_args.kwargs["paper_id"], 7)
        self.assertEqual(status.phases[-1].status, "completed")

    async def test_run_recipe_cache_hit_backfills_evidence(self):
        """캐시 히트도 검증을 태운다 — 옛 결과가 영원히 미검증으로 남지 않게."""
        status = AnalysisStatus(paper_id=7, overall_status="running", phases=[], progress_pct=0.0)
        cached = {
            "text": '{"title":"r","parameters":[{"name":"a","value":"1"}]}',
            "model": "gemini-cache", "tokens_in": 1, "tokens_out": 2, "cost_usd": 0.0,
            "input_hash": "h", "result_id": 77,
        }

        ensure_mock = AsyncMock(return_value={"status": "verified", "anchors": 1})
        with (
            patch("api.analysis_routes._get_cached_phase_result", new=AsyncMock(return_value=cached)),
            patch("api.analysis_routes.call_interaction", new=AsyncMock(side_effect=AssertionError("no LLM on cache hit"))),
            patch("api.analysis_routes.get_paper_dir", return_value=Path("/tmp/sasoo-test-paper")),
            patch("api.analysis_routes._find_paper_pdf", return_value=None),
            patch("api.analysis_routes.ensure_recipe_anchors", new=ensure_mock),
        ):
            await analysis_routes._run_recipe(
                7, "body", status, screening_result_text='{"domain":"optics"}',
                folder_name="2026_Paper_optics",
            )

        ensure_mock.assert_awaited_once()
        self.assertEqual(ensure_mock.await_args.kwargs["analysis_result_id"], 77)

    async def test_evidence_failure_does_not_kill_recipe_phase(self):
        """검증기 예외는 격리한다 — recipe 데이터는 보존되고 phase는 completed다."""
        status = AnalysisStatus(paper_id=7, overall_status="running", phases=[], progress_pct=0.0)

        async def _fake_call(prompt, **kwargs):
            return {
                "text": '{"title":"r","objective":"o","parameters":[{"name":"a","value":"1"}],"steps":[]}',
                "model": "gemini", "tokens_in": 1, "tokens_out": 1, "interaction_id": None,
            }

        with (
            patch("api.analysis_routes._get_cached_phase_result", new=AsyncMock(return_value=None)),
            patch("api.analysis_routes.call_interaction", new=_fake_call),
            patch("api.analysis_routes._insert_analysis_result", new=AsyncMock(return_value=41)),
            patch("api.analysis_routes.get_paper_dir", return_value=Path("/tmp/sasoo-test-paper")),
            patch("api.analysis_routes._find_paper_pdf", return_value=None),
            patch("api.analysis_routes.ensure_recipe_anchors",
                  new=AsyncMock(side_effect=RuntimeError("verifier exploded"))),
        ):
            result = await analysis_routes._run_recipe(
                7, "body", status, screening_result_text='{"domain":"optics"}',
                folder_name="2026_Paper_optics",
            )

        self.assertIn('"title": "r"', result["text"].replace('"title":"r"', '"title": "r"'))
        self.assertEqual(status.phases[-1].status, "completed")
```

  파일 상단 import에 `from pathlib import Path`가 없으면 추가한다.
  같은 파일의 `test_cached_phase_lookup_records_cache_event`에서
  `input_hash="hash1234",` 줄을 찾아 그 뒤에 `result_id=99,`를 추가한다(SimpleNamespace에
  새 필드가 없으면 `_get_cached_phase_result`가 AttributeError를 낸다).

- [ ] **Step 10: 실패 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest api/test_analysis_routes.py -q -k "anchors_evidence or backfills_evidence or evidence_failure"
```

기대: `AttributeError: <module 'api.analysis_routes'> does not have the attribute 'ensure_recipe_anchors'`로 3개 실패.

- [ ] **Step 11: analysis_routes 배선** — 4곳을 고친다.

(a) import 블록에서 `from services.pricing import calc_cost` 줄을 찾아 그 **앞에** 추가:

```python
from services.evidence_repo import build_evidence_payload, ensure_recipe_anchors
```

(b) `_insert_analysis_result`의 시그니처 끝 `) -> None:`을 `) -> int:`로 바꾸고,
    본문의 `await execute_insert(` 를 `return await execute_insert(` 로 바꾼다. 인자는 그대로다.
    docstring이 없으므로 함수 첫 줄에 주석 한 줄을 추가한다.

```python
) -> int:
    """analysis_results에 결과를 저장하고 lastrowid를 반환한다.

    반환값은 Evidence 앵커를 이 행에 결속하는 데 쓴다(스펙 §결정 4). 기존 호출부는
    반환값을 쓰지 않으므로 동작이 바뀌지 않는다.
    """
    return await execute_insert(
```

(c) `_insert_analysis_result` 함수 **뒤에** 헬퍼를 추가한다.

```python
async def _ensure_recipe_evidence(
    *,
    paper_id: int,
    analysis_result_id,
    recipe_text: str,
    folder_name: str,
) -> None:
    """Recipe 파라미터 근거를 결정론적으로 검증해 evidence_anchors에 기록한다.

    예외를 밖으로 내보내지 않는다 — 검증기 실패가 recipe phase를 죽이면 안 된다.
    실패하면 앵커가 남지 않고, 앵커 부재는 UI에서 '검증 미실행'으로 정직하게 보인다
    (부재를 검증됨으로 표시하는 코드 경로는 존재하지 않는다).
    """
    if not analysis_result_id or not folder_name:
        logger.info(
            "evidence anchoring skipped (paper=%s result_id=%r folder=%r)",
            paper_id, analysis_result_id, folder_name,
        )
        return
    try:
        pdf_path = _find_paper_pdf(get_paper_dir(folder_name))
        await ensure_recipe_anchors(
            paper_id=paper_id,
            analysis_result_id=int(analysis_result_id),
            recipe_text=recipe_text,
            pdf_path=pdf_path,
        )
    except Exception as exc:
        logger.warning(
            "evidence anchoring failed (paper=%s result=%s): %s",
            paper_id, analysis_result_id, exc,
        )
```

  `_find_paper_pdf`는 이 헬퍼보다 아래에 정의돼 있지만 호출 시점에는 이미 바인딩되므로
  순서를 옮기지 않는다.

(d) `_get_cached_phase_result`의 반환 dict에서 `"input_hash": ...` 줄 뒤에 추가:

```python
        "result_id": cached.result_id,
```

- [ ] **Step 12: `_run_recipe` 통합** — 3곳을 고친다.

(a) 시그니처의 `pdf_uri: Optional[str] = None,` 뒤에 추가:

```python
    folder_name: str = "",
```

(b) 캐시 히트 블록에서 `status.total_tokens_out += cached["tokens_out"]` 뒤,
    `return cached` **앞에** 추가:

```python
        # 캐시 히트도 검증을 태운다 — 옛 결과 백필과 검증기 버전업 재검증의 유일한 통로다.
        await _ensure_recipe_evidence(
            paper_id=paper_id,
            analysis_result_id=cached.get("result_id"),
            recipe_text=cached["text"],
            folder_name=folder_name,
        )
```

(c) `await _insert_analysis_result(` 로 시작하는 호출을 `result_id = await _insert_analysis_result(`
    로 바꾸고, 그 호출이 끝나는 `)` 뒤 · `if _is_error_result(result["text"]):` **앞에** 추가:

```python
    # recipe row 저장(lastrowid 확보) 직후, phase completed 노출 전 동기 검증(스펙 §결정 3).
    # 41페이지 논문 실측 ~0.4초의 순수 CPU 작업이라 별도 큐·phase를 만들지 않는다.
    if not _is_error_result(result["text"]):
        await _ensure_recipe_evidence(
            paper_id=paper_id,
            analysis_result_id=result_id,
            recipe_text=result["text"],
            folder_name=folder_name,
        )
```

- [ ] **Step 13: `_run_full_analysis` 호출부** — `r3 = await _run_recipe(` 블록에서
  `pdf_uri=pdf_uri,` 줄 뒤에 추가한다(`_run_visual` 호출부는 건드리지 않는다).

```python
            folder_name=folder_name,
```

- [ ] **Step 14: 통과 확인 + 전체 회귀**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest api/test_analysis_routes.py -q
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services api models -q
```

기대: 전부 통과.

- [ ] **Step 15: 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중 && git add -A && git commit -m "$(cat <<'EOF'
feat(analysis): recipe 저장 직후 근거를 동기 검증하고 캐시 히트도 백필

CachedPhaseResult에 result_id를 실어 캐시 히트 경로에서도 앵커를 만든다 —
그 경로가 옛 결과 백필과 검증기 버전업 재검증의 유일한 통로다.
_insert_analysis_result가 lastrowid를 반환해 앵커를 그 행에 결속한다.
검증기 예외는 격리해 recipe 데이터와 phase 완료를 보존한다.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: recipe API hydration

저장 blob은 그대로 두고 응답에 `evidence`를 형제 필드로 붙인다. 새 엔드포인트를 만들지
않는 이유: 두 번의 fetch가 경합하면 "레시피는 왔는데 근거는 아직"인 중간 상태가 생기고,
사용자가 그 순간을 "근거 없음"으로 오해한다.

**Files**

- Modify: `sasoo/backend/api/analysis_routes.py` (`get_recipe`)
- Modify: `sasoo/backend/api/test_analysis_routes.py` (엔드포인트 테스트 2건)

**Interfaces**

Consumes: Task 5의 `services.evidence_repo.build_evidence_payload`

Produces: `GET /api/analysis/{paper_id}/recipe` 응답

```jsonc
{
  "paper_id": 12,
  "recipe": { /* LLM 원본 JSON — 무수정 */ },
  "model_used": "...",
  "created_at": "...",
  "evidence": {                      // 앵커가 없으면 null
    "verifier_version": "ev1",
    "normalizer_version": "norm-v1",
    "summary": {"total": 18, "verified": 11,
                "by_display_status": {"VERIFIED": 11, "UNVERIFIED_NOT_FOUND": 4, "UNVERIFIED_NO_QUOTE": 3}},
    "anchors": [{
      "target_index": 0, "target_key": "p000:wavelength", "target_label": "wavelength",
      "source_tag": "explicit",
      "claimed_quote": "...", "claimed_page": 4,
      "quote_status": "verified_normalized", "page_status": "match", "value_status": "value_in_quote",
      "display_status": "VERIFIED", "match_method": "normalized", "match_ratio": 1.0,
      "matched_quote": "...", "matched_page": 4,
      "bbox": [72.1, 388.4, 523.9, 401.2],
      "corpus": "pdf_text", "failure_detail": null,
      "verifier_version": "ev1", "normalizer_version": "norm-v1"
    }]
  }
}
```

**Steps**

- [ ] **Step 1: 실패 테스트 작성** — `sasoo/backend/api/test_analysis_routes.py` 끝의
  `if __name__ == "__main__":` 앞에 새 클래스를 추가한다.

```python
class GetRecipeEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_recipe_response_carries_evidence_payload(self):
        row = {
            "id": 41,
            "parsed_result": {"title": "레시피", "parameters": []},
            "model_used": "gemini",
            "created_at": "2026-08-06 10:00:00",
        }
        payload = {
            "verifier_version": "ev1",
            "normalizer_version": "norm-v1",
            "summary": {"total": 1, "verified": 1, "by_display_status": {"VERIFIED": 1}},
            "anchors": [{"target_index": 0, "display_status": "VERIFIED"}],
        }
        build_mock = AsyncMock(return_value=payload)
        with (
            patch("api.analysis_routes.get_latest_completed_phase_row", new=AsyncMock(return_value=row)),
            patch("api.analysis_routes.build_evidence_payload", new=build_mock),
        ):
            response = await analysis_routes.get_recipe(12)

        self.assertEqual(response["evidence"], payload)
        self.assertEqual(response["recipe"], row["parsed_result"])  # 원본 blob 무수정
        self.assertEqual(build_mock.await_args.args[0], 41)

    async def test_evidence_is_null_when_no_anchor_exists(self):
        row = {"id": 41, "parsed_result": {"title": "레시피"}, "model_used": "m", "created_at": "t"}
        with (
            patch("api.analysis_routes.get_latest_completed_phase_row", new=AsyncMock(return_value=row)),
            patch("api.analysis_routes.build_evidence_payload", new=AsyncMock(return_value=None)),
        ):
            response = await analysis_routes.get_recipe(12)

        self.assertIsNone(response["evidence"])

    async def test_evidence_lookup_failure_does_not_break_recipe(self):
        row = {"id": 41, "parsed_result": {"title": "레시피"}, "model_used": "m", "created_at": "t"}
        with (
            patch("api.analysis_routes.get_latest_completed_phase_row", new=AsyncMock(return_value=row)),
            patch("api.analysis_routes.build_evidence_payload",
                  new=AsyncMock(side_effect=RuntimeError("db gone"))),
        ):
            response = await analysis_routes.get_recipe(12)

        self.assertIsNone(response["evidence"])
        self.assertEqual(response["recipe"], row["parsed_result"])
```

- [ ] **Step 2: 실패 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest api/test_analysis_routes.py -q -k GetRecipeEvidence
```

기대: `KeyError: 'evidence'`로 3개 실패.

- [ ] **Step 3: `get_recipe` 확장** — `@router.get("/{paper_id}/recipe")` 아래 함수의
  `return {` 블록을 찾아 아래로 바꾼다(404 분기는 그대로).

```python
    # LLM 원본 blob은 무수정 유지하고 검증 결과를 형제 필드로 붙인다.
    # evidence=None은 "검증 기록 없음"이지 "검증됨"이 아니다 — UI는 전 행을 미검증으로 표시한다.
    try:
        evidence = await build_evidence_payload(result.get("id"))
    except Exception as exc:
        logger.warning("evidence payload build failed for paper %s: %s", paper_id, exc)
        evidence = None

    return {
        "paper_id": paper_id,
        "recipe": result.get("parsed_result"),
        "model_used": result.get("model_used"),
        "created_at": result.get("created_at"),
        "evidence": evidence,
    }
```

- [ ] **Step 4: 통과 확인 + 전체 회귀**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services api models -q
```

기대: 전부 통과.

- [ ] **Step 5: 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중 && git add -A && git commit -m "$(cat <<'EOF'
feat(api): recipe 응답에 evidence read model 병합

저장 blob은 무수정으로 두고 앵커를 형제 필드로 붙인다. 앵커가 없으면 evidence=null이고,
이건 "검증 기록 없음"이지 "검증됨"이 아니다. 조회 실패도 null로 격리해 레시피 자체는
항상 내려간다.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: 프론트 타입 · 근거 열 · 페이지 점프 (acceptance 본체)

DEC-009: acceptance는 **페이지 점프 + quote 표시**까지다. 색만으로 상태를 전달하지 않고
아이콘+텍스트+툴팁을 함께 쓴다. 클릭으로 UNVERIFIED를 VERIFIED로 바꾸는 UI는 금지다.

**Files**

- Modify: `sasoo/frontend/src/lib/api.ts` (Evidence 타입, `Recipe.evidence`)
- Create: `sasoo/frontend/src/lib/evidence.ts`
- Create: `sasoo/frontend/src/lib/evidence.test.ts`
- Modify: `sasoo/frontend/src/lib/strings.ts` (`S.recipe.evidence`)
- Modify: `sasoo/frontend/src/components/RecipeCard.tsx`
- Modify: `sasoo/frontend/src/components/AnalysisPanel.tsx`
- Modify: `sasoo/frontend/src/pages/Workbench.tsx`

**Interfaces**

Consumes: Task 6의 `/recipe` 응답 형태

Produces:

```ts
// sasoo/frontend/src/lib/api.ts
export type EvidenceDisplayStatus =
  | 'VERIFIED' | 'UNVERIFIED_PAGE_MISMATCH' | 'UNVERIFIED_VALUE_MISMATCH'
  | 'UNVERIFIED_INFERRED' | 'UNVERIFIED_PARTIAL' | 'UNVERIFIED_AMBIGUOUS'
  | 'UNVERIFIED_NOT_FOUND' | 'UNVERIFIED_NO_QUOTE' | 'UNVERIFIED_NO_TEXT_LAYER'
  | 'UNVERIFIED_STALE_SOURCE' | 'UNVERIFIED_ERROR' | 'UNVERIFIED_NOT_RUN';

export interface EvidenceAnchor { /* 아래 Step 3 참조 */ }
export interface RecipeEvidence { /* 아래 Step 3 참조 */ }
export interface Recipe { /* 기존 필드 + */ evidence?: RecipeEvidence | null }

// sasoo/frontend/src/lib/evidence.ts
export interface RecipeParameterRow { index: number; name: string; value: string; unit: string; notes: string }
export interface AnchoredParameter { row: RecipeParameterRow; anchor: EvidenceAnchor | null }
export interface EvidenceBadge {
  label: string;
  tone: 'neutral' | 'accent' | 'danger' | 'warning' | 'success';
  icon: 'success' | 'warning' | 'error' | 'info';
  verified: boolean;
}
export function parseRecipeParameters(raw: unknown): RecipeParameterRow[];
export function attachEvidence(rows: RecipeParameterRow[], evidence: RecipeEvidence | null | undefined): AnchoredParameter[];
export function resolveDisplayStatus(anchor: EvidenceAnchor | null): EvidenceDisplayStatus;
export function evidenceBadge(status: EvidenceDisplayStatus): EvidenceBadge;
export function evidenceTarget(anchor: EvidenceAnchor | null): { page: number; confirmed: boolean } | null;
export function evidenceTooltip(anchor: EvidenceAnchor | null): string;

// RecipeCard / AnalysisPanel props
onJumpToEvidence?: (anchor: EvidenceAnchor) => void
```

**Steps**

- [ ] **Step 1: 실패 테스트 작성** — `sasoo/frontend/src/lib/evidence.test.ts` 생성.

```ts
import { describe, expect, it } from 'vitest';
import type { EvidenceAnchor, EvidenceDisplayStatus, RecipeEvidence } from '@/lib/api';
import {
  attachEvidence,
  evidenceBadge,
  evidenceTarget,
  evidenceTooltip,
  parseRecipeParameters,
  resolveDisplayStatus,
} from '@/lib/evidence';

function anchor(overrides: Partial<EvidenceAnchor> = {}): EvidenceAnchor {
  return {
    target_index: 0,
    target_key: 'p000:wavelength',
    target_label: 'wavelength',
    source_tag: 'explicit',
    claimed_quote: 'a wavelength of 1550 nm',
    claimed_page: 4,
    quote_status: 'verified_normalized',
    page_status: 'match',
    value_status: 'value_in_quote',
    display_status: 'VERIFIED',
    match_method: 'normalized',
    match_ratio: 1,
    matched_quote: 'a wave-\nlength of 1550 nm',
    matched_page: 4,
    bbox: [72, 700, 300, 715],
    corpus: 'pdf_text',
    failure_detail: null,
    verifier_version: 'ev1',
    normalizer_version: 'norm-v1',
    ...overrides,
  };
}

function evidence(anchors: EvidenceAnchor[]): RecipeEvidence {
  return {
    verifier_version: 'ev1',
    normalizer_version: 'norm-v1',
    summary: { total: anchors.length, verified: 0, by_display_status: {} },
    anchors,
  };
}

describe('parseRecipeParameters — 백엔드 검증기와 같은 규칙으로 센다', () => {
  it('object와 string만 행이 되고 index가 연속으로 붙는다', () => {
    const rows = parseRecipeParameters([
      { name: 'a', value: '1', unit: 'nm', notes: 'n' },
      'Temperature: 500 C',
      42,
      null,
      { parameter: 'b', val: '2' },
    ]);
    expect(rows.map((row) => row.index)).toEqual([0, 1, 2]);
    expect(rows.map((row) => row.name)).toEqual(['a', 'Temperature', 'b']);
    expect(rows[1].value).toBe('500 C');
    expect(rows[2].value).toBe('2');
  });

  it('배열이 아니면 빈 목록이다', () => {
    expect(parseRecipeParameters(undefined)).toEqual([]);
    expect(parseRecipeParameters('nope')).toEqual([]);
  });
});

describe('attachEvidence — label 불일치는 fail closed', () => {
  it('index로 결합한다', () => {
    const rows = parseRecipeParameters([{ name: 'wavelength', value: '1550' }]);
    const [first] = attachEvidence(rows, evidence([anchor()]));
    expect(first.anchor?.target_key).toBe('p000:wavelength');
  });

  it('label이 다르면 앵커를 숨긴다 (엉뚱한 근거보다 근거 없음이 정직하다)', () => {
    const rows = parseRecipeParameters([{ name: 'laser_power', value: '3.2' }]);
    const [first] = attachEvidence(rows, evidence([anchor()]));
    expect(first.anchor).toBeNull();
    expect(resolveDisplayStatus(first.anchor)).toBe('UNVERIFIED_NOT_RUN');
  });

  it('evidence가 null이면 전 행이 검증 미실행이다', () => {
    const rows = parseRecipeParameters([{ name: 'a', value: '1' }, { name: 'b', value: '2' }]);
    const attached = attachEvidence(rows, null);
    expect(attached.every((item) => item.anchor === null)).toBe(true);
    expect(attached.map((item) => resolveDisplayStatus(item.anchor))).toEqual([
      'UNVERIFIED_NOT_RUN',
      'UNVERIFIED_NOT_RUN',
    ]);
  });

  it('앵커가 파라미터보다 적어도 남는 행은 미실행으로 남는다', () => {
    const rows = parseRecipeParameters([{ name: 'wavelength', value: '1' }, { name: 'power', value: '2' }]);
    const attached = attachEvidence(rows, evidence([anchor()]));
    expect(attached[0].anchor).not.toBeNull();
    expect(attached[1].anchor).toBeNull();
  });
});

describe('evidenceBadge — VERIFIED만 검증 표시', () => {
  const ALL: EvidenceDisplayStatus[] = [
    'VERIFIED', 'UNVERIFIED_PAGE_MISMATCH', 'UNVERIFIED_VALUE_MISMATCH', 'UNVERIFIED_INFERRED',
    'UNVERIFIED_PARTIAL', 'UNVERIFIED_AMBIGUOUS', 'UNVERIFIED_NOT_FOUND', 'UNVERIFIED_NO_QUOTE',
    'UNVERIFIED_NO_TEXT_LAYER', 'UNVERIFIED_STALE_SOURCE', 'UNVERIFIED_ERROR', 'UNVERIFIED_NOT_RUN',
  ];

  it('모든 상태가 비어 있지 않은 라벨을 가진다 (색만으로 구분하지 않는다)', () => {
    for (const status of ALL) {
      expect(evidenceBadge(status).label.length).toBeGreaterThan(0);
    }
  });

  it('VERIFIED 외에는 verified=false다', () => {
    expect(evidenceBadge('VERIFIED').verified).toBe(true);
    for (const status of ALL.filter((s) => s !== 'VERIFIED')) {
      expect(evidenceBadge(status).verified).toBe(false);
    }
  });

  it('부분 일치는 성공 톤을 쓰지 않는다', () => {
    expect(evidenceBadge('UNVERIFIED_PARTIAL').tone).not.toBe('success');
  });
});

describe('evidenceTarget — 확인 페이지와 후보 페이지를 구분한다', () => {
  it('확인된 페이지를 우선한다', () => {
    expect(evidenceTarget(anchor())).toEqual({ page: 4, confirmed: true });
  });

  it('page_mismatch는 이동은 가능하지만 confirmed가 아니다', () => {
    const target = evidenceTarget(anchor({ display_status: 'UNVERIFIED_PAGE_MISMATCH', matched_page: 7 }));
    expect(target).toEqual({ page: 7, confirmed: false });
  });

  it('확인 페이지가 없으면 LLM 주장 페이지를 후보로 준다', () => {
    const target = evidenceTarget(anchor({ display_status: 'UNVERIFIED_NOT_FOUND', matched_page: null }));
    expect(target).toEqual({ page: 4, confirmed: false });
  });

  it('페이지가 전혀 없으면 null이다', () => {
    expect(evidenceTarget(anchor({ matched_page: null, claimed_page: null }))).toBeNull();
    expect(evidenceTarget(null)).toBeNull();
  });
});

describe('evidenceTooltip — 확인된 인용과 주장된 인용을 라벨로 구분한다', () => {
  it('VERIFIED는 확인된 원문을 보여준다', () => {
    const text = evidenceTooltip(anchor());
    expect(text).toContain('확인된 원문');
    expect(text).toContain('wave-\nlength of 1550 nm');
  });

  it('미확인은 "LLM이 주장한 인용"으로 명시한다', () => {
    const text = evidenceTooltip(anchor({ display_status: 'UNVERIFIED_NOT_FOUND', matched_quote: null }));
    expect(text).toContain('LLM이 주장한 인용');
    expect(text).not.toContain('확인된 원문');
  });

  it('앵커가 없으면 검증 미실행을 알린다', () => {
    expect(evidenceTooltip(null)).toContain('검증 미실행');
  });
});
```

- [ ] **Step 2: 실패 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo && pnpm exec vitest run frontend/src/lib/evidence.test.ts
```

기대: `Failed to resolve import "@/lib/evidence"`.

- [ ] **Step 3: api.ts 타입 추가** — `sasoo/frontend/src/lib/api.ts`에서
  `// Recipe types` 주석과 `export interface Recipe {` 블록을 찾아 아래로 바꾼다
  (기존 4개 필드는 그대로 두고 `evidence`만 추가).

```ts
// Recipe types
export type EvidenceDisplayStatus =
  | 'VERIFIED'
  | 'UNVERIFIED_PAGE_MISMATCH'
  | 'UNVERIFIED_VALUE_MISMATCH'
  | 'UNVERIFIED_INFERRED'
  | 'UNVERIFIED_PARTIAL'
  | 'UNVERIFIED_AMBIGUOUS'
  | 'UNVERIFIED_NOT_FOUND'
  | 'UNVERIFIED_NO_QUOTE'
  | 'UNVERIFIED_NO_TEXT_LAYER'
  | 'UNVERIFIED_STALE_SOURCE'
  | 'UNVERIFIED_ERROR'
  /** 앵커 자체가 없는 경우. 백엔드는 이 값을 저장하지 않고 프론트가 합성한다. */
  | 'UNVERIFIED_NOT_RUN';

/** 결정론적 검증기(evidence-verifier)가 만든 파라미터별 근거 앵커. LLM 출력이 아니다. */
export interface EvidenceAnchor {
  target_index: number;
  target_key: string;
  target_label: string;
  source_tag: string | null;
  /** LLM이 주장한 인용 — 확인되지 않았을 수 있다. */
  claimed_quote: string | null;
  claimed_page: number | null;
  quote_status: string;
  page_status: string;
  value_status: string;
  display_status: EvidenceDisplayStatus;
  match_method: string | null;
  match_ratio: number | null;
  /** 원문에서 실제로 확인된 span. 확인 실패 시 null. */
  matched_quote: string | null;
  matched_page: number | null;
  /** [x0, y_bottom, x1, y_top] PDF 포인트, 좌하단 원점. */
  bbox: [number, number, number, number] | null;
  corpus: string;
  failure_detail: string | null;
  verifier_version: string;
  normalizer_version: string;
}

export interface RecipeEvidence {
  verifier_version: string;
  normalizer_version: string;
  summary: {
    total: number;
    verified: number;
    by_display_status: Record<string, number>;
  };
  anchors: EvidenceAnchor[];
}

export interface Recipe {
  paper_id: number;
  recipe: Record<string, unknown>;
  model_used: string | null;
  created_at: string | null;
  /** null이면 "검증 기록 없음"이지 "검증됨"이 아니다. */
  evidence?: RecipeEvidence | null;
}
```

- [ ] **Step 4: strings.ts에 근거 문자열 추가** — `S.recipe` 객체에서
  `safetyNotes: '안전 주의사항',` 줄을 찾아 그 뒤에 추가한다(기존 키는 그대로).

```ts
    evidence: {
      column: '근거',
      summaryBadge: (verified: number, total: number) => `근거 확인 ${verified}/${total}`,
      notRunNotice: '이 분석 결과에는 근거 검증 기록이 없어요. 다시 분석하면 근거를 모아요.',
      verifiedQuote: '확인된 원문',
      claimedQuote: 'LLM이 주장한 인용 (원문에서 확인되지 않음)',
      confirmedPage: (page: number) => `p.${page}에서 확인`,
      candidatePage: (page: number) => `후보 위치 p.${page}`,
      claimedPageNote: (page: number) => `LLM 주장 p.${page}`,
      jump: '이 페이지로 이동',
      method: {
        exact: '축자 일치',
        normalized: '표기 정규화 일치',
        partial: '부분 일치',
      },
      status: {
        VERIFIED: '원문 확인',
        UNVERIFIED_PAGE_MISMATCH: '다른 페이지에서 확인',
        UNVERIFIED_VALUE_MISMATCH: '인용에 값이 없음',
        UNVERIFIED_INFERRED: '추론값',
        UNVERIFIED_PARTIAL: '부분 일치 — 미검증',
        UNVERIFIED_AMBIGUOUS: '위치가 모호함',
        UNVERIFIED_NOT_FOUND: '원문에서 찾지 못함',
        UNVERIFIED_NO_QUOTE: '근거 없음',
        UNVERIFIED_NO_TEXT_LAYER: '검증 불가 (텍스트 없는 PDF)',
        UNVERIFIED_STALE_SOURCE: '원문이 바뀜 — 재검증 필요',
        UNVERIFIED_ERROR: '검증 실패',
        UNVERIFIED_NOT_RUN: '검증 미실행',
      },
      disclaimer: '인용이 논문 원문에 있는지 확인한 결과예요. 값의 과학적 타당성 검증은 아니에요.',
    },
```

- [ ] **Step 5: lib/evidence.ts 구현** — `sasoo/frontend/src/lib/evidence.ts` 생성.

```ts
import type { EvidenceAnchor, EvidenceDisplayStatus, RecipeEvidence } from '@/lib/api';
import { S } from '@/lib/strings';

// ---------------------------------------------------------------------------
// 파라미터 파싱
// ---------------------------------------------------------------------------
// RecipeCard 안에 있던 파서를 그대로 옮겼다. 백엔드 검증기(services/evidence_verifier.py의
// iter_recipe_parameters)가 이 규칙과 1:1로 같아야 target_index가 밀리지 않는다.
// 규칙을 바꾸면 반드시 양쪽을 함께 바꾼다.

export interface RecipeParameterRow {
  index: number;
  name: string;
  value: string;
  unit: string;
  notes: string;
}

export function parseRecipeParameters(raw: unknown): RecipeParameterRow[] {
  const rows: RecipeParameterRow[] = [];
  if (!Array.isArray(raw)) return rows;

  raw.forEach((p: unknown) => {
    if (typeof p === 'object' && p !== null) {
      const obj = p as Record<string, unknown>;
      rows.push({
        index: rows.length,
        name: String(obj.name || obj.Name || obj.parameter || obj.key || ''),
        value: String(obj.value || obj.Value || obj.val || ''),
        unit: String(obj.unit || obj.Unit || obj.units || ''),
        notes: String(obj.notes || obj.Notes || obj.note || obj.context || ''),
      });
    } else if (typeof p === 'string') {
      // "Temperature: 500 C" 형식
      const match = p.match(/^(.+?):\s*(.+)$/);
      if (match) {
        rows.push({ index: rows.length, name: match[1].trim(), value: match[2].trim(), unit: '', notes: '' });
      } else {
        rows.push({ index: rows.length, name: p, value: '', unit: '', notes: '' });
      }
    }
  });

  return rows;
}

// ---------------------------------------------------------------------------
// 앵커 결합 (fail closed)
// ---------------------------------------------------------------------------

export interface AnchoredParameter {
  row: RecipeParameterRow;
  anchor: EvidenceAnchor | null;
}

export function attachEvidence(
  rows: RecipeParameterRow[],
  evidence: RecipeEvidence | null | undefined,
): AnchoredParameter[] {
  const byIndex = new Map<number, EvidenceAnchor>();
  for (const anchor of evidence?.anchors ?? []) {
    byIndex.set(anchor.target_index, anchor);
  }

  return rows.map((row) => {
    const anchor = byIndex.get(row.index) ?? null;
    // 인덱스가 밀려 엉뚱한 파라미터에 근거가 붙는 것보다 "근거 없음"이 정직하다.
    if (anchor && (anchor.target_label ?? '').trim() !== row.name.trim()) {
      return { row, anchor: null };
    }
    return { row, anchor };
  });
}

export function resolveDisplayStatus(anchor: EvidenceAnchor | null): EvidenceDisplayStatus {
  return anchor?.display_status ?? 'UNVERIFIED_NOT_RUN';
}

// ---------------------------------------------------------------------------
// 배지 / 툴팁 / 이동 대상
// ---------------------------------------------------------------------------

export interface EvidenceBadge {
  label: string;
  tone: 'neutral' | 'accent' | 'danger' | 'warning' | 'success';
  icon: 'success' | 'warning' | 'error' | 'info';
  verified: boolean;
}

const BADGE_STYLE: Record<EvidenceDisplayStatus, { tone: EvidenceBadge['tone']; icon: EvidenceBadge['icon'] }> = {
  VERIFIED: { tone: 'success', icon: 'success' },
  UNVERIFIED_PAGE_MISMATCH: { tone: 'warning', icon: 'warning' },
  UNVERIFIED_VALUE_MISMATCH: { tone: 'danger', icon: 'warning' },
  UNVERIFIED_INFERRED: { tone: 'warning', icon: 'info' },
  UNVERIFIED_PARTIAL: { tone: 'warning', icon: 'warning' },
  UNVERIFIED_AMBIGUOUS: { tone: 'warning', icon: 'warning' },
  UNVERIFIED_NOT_FOUND: { tone: 'danger', icon: 'error' },
  UNVERIFIED_NO_QUOTE: { tone: 'neutral', icon: 'info' },
  UNVERIFIED_NO_TEXT_LAYER: { tone: 'neutral', icon: 'info' },
  UNVERIFIED_STALE_SOURCE: { tone: 'neutral', icon: 'warning' },
  UNVERIFIED_ERROR: { tone: 'danger', icon: 'error' },
  UNVERIFIED_NOT_RUN: { tone: 'neutral', icon: 'info' },
};

export function evidenceBadge(status: EvidenceDisplayStatus): EvidenceBadge {
  const style = BADGE_STYLE[status] ?? BADGE_STYLE.UNVERIFIED_ERROR;
  return {
    label: S.recipe.evidence.status[status] ?? S.recipe.evidence.status.UNVERIFIED_ERROR,
    tone: style.tone,
    icon: style.icon,
    verified: status === 'VERIFIED',
  };
}

/** 이동 가능한 페이지와 그 페이지가 확인된 위치인지 여부. 확인되지 않은 페이지는 "후보"다. */
export function evidenceTarget(anchor: EvidenceAnchor | null): { page: number; confirmed: boolean } | null {
  if (!anchor) return null;
  if (typeof anchor.matched_page === 'number' && anchor.matched_page > 0) {
    return { page: anchor.matched_page, confirmed: anchor.display_status === 'VERIFIED' };
  }
  if (typeof anchor.claimed_page === 'number' && anchor.claimed_page > 0) {
    return { page: anchor.claimed_page, confirmed: false };
  }
  return null;
}

const METHOD_LABEL: Record<string, string> = {
  exact: S.recipe.evidence.method.exact,
  normalized: S.recipe.evidence.method.normalized,
  partial: S.recipe.evidence.method.partial,
};

export function evidenceTooltip(anchor: EvidenceAnchor | null): string {
  const status = resolveDisplayStatus(anchor);
  const label = evidenceBadge(status).label;
  if (!anchor) {
    return `${label}\n${S.recipe.evidence.notRunNotice}`;
  }

  const lines: string[] = [label];

  if (anchor.display_status === 'VERIFIED' && anchor.matched_quote) {
    lines.push(`${S.recipe.evidence.verifiedQuote}: "${anchor.matched_quote}"`);
  } else if (anchor.claimed_quote) {
    // 확인되지 않은 인용을 확인된 근거처럼 보이게 하지 않는다.
    lines.push(`${S.recipe.evidence.claimedQuote}: "${anchor.claimed_quote}"`);
  }

  if (typeof anchor.matched_page === 'number') {
    lines.push(
      anchor.display_status === 'VERIFIED'
        ? S.recipe.evidence.confirmedPage(anchor.matched_page)
        : S.recipe.evidence.candidatePage(anchor.matched_page),
    );
  }
  if (typeof anchor.claimed_page === 'number' && anchor.claimed_page !== anchor.matched_page) {
    lines.push(S.recipe.evidence.claimedPageNote(anchor.claimed_page));
  }
  if (anchor.match_method && METHOD_LABEL[anchor.match_method]) {
    lines.push(METHOD_LABEL[anchor.match_method]);
  }

  lines.push(S.recipe.evidence.disclaimer);
  return lines.join('\n');
}
```

- [ ] **Step 6: 유닛 테스트 통과 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo && pnpm exec vitest run frontend/src/lib/evidence.test.ts
```

기대: `18 passed`.

- [ ] **Step 7: RecipeCard에 근거 열 추가** — `sasoo/frontend/src/components/RecipeCard.tsx`를 4곳 고친다.

(a) import 블록:

```tsx
import { useState, useCallback } from 'react';
import type { EvidenceAnchor, Recipe } from '@/lib/api';
import { S } from '@/lib/strings';
import { AppIcon } from '@/components/icons';
import CascadeIn from '@/components/amicro/CascadeIn';
import { Badge, Tooltip } from '@/components/ui';
import {
  attachEvidence,
  evidenceBadge,
  evidenceTarget,
  evidenceTooltip,
  parseRecipeParameters,
  resolveDisplayStatus,
} from '@/lib/evidence';
```

(b) props 인터페이스:

```tsx
interface RecipeCardProps {
  recipe: Recipe | null;
  loading?: boolean;
  onJumpToEvidence?: (anchor: EvidenceAnchor) => void;
}
```

  구조분해도 함께 바꾼다.

```tsx
export default function RecipeCard({
  recipe,
  loading = false,
  onJumpToEvidence,
}: RecipeCardProps) {
```

(c) `// Robustly parse parameters — handle both array of objects and other formats` 주석부터
    그 아래 `if (Array.isArray(rawParams)) { ... }` 블록 끝까지를 통째로 아래로 교체한다.

```tsx
  // 파라미터 파싱은 lib/evidence.ts로 옮겼다 — 백엔드 검증기와 규칙을 맞추고 단위 테스트를 붙이기 위해.
  const parameters = parseRecipeParameters(data.parameters);
  const anchored = attachEvidence(parameters, recipe.evidence ?? null);
  const evidenceSummary = recipe.evidence?.summary ?? null;
```

(d) 파라미터 표를 근거 열이 있는 형태로 바꾼다. `{/* Parameters Table */}` 블록 안에서
    헤더 `<h4>` 옆에 요약 배지를 넣고, `<thead>`에 열을 추가하고, `<tbody>`를 `anchored` 기준으로 바꾼다.

```tsx
          <div className="px-3 py-2 border-b border-border bg-surface/70 flex items-center justify-between gap-2">
            <h4 className="text-2xs font-medium uppercase tracking-wide text-fg-muted">
              {S.recipe.parameters} ({parameters.length})
            </h4>
            {evidenceSummary && (
              <Badge variant={evidenceSummary.verified > 0 ? 'success' : 'neutral'}>
                {S.recipe.evidence.summaryBadge(evidenceSummary.verified, evidenceSummary.total)}
              </Badge>
            )}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border bg-surface/30">
                  <th className="text-left font-semibold text-fg-muted px-3 py-2 w-8">#</th>
                  <th className="text-left font-semibold text-fg-secondary px-3 py-2">Parameter</th>
                  <th className="text-left font-semibold text-fg-secondary px-3 py-2">Value</th>
                  <th className="text-left font-semibold text-fg-secondary px-3 py-2">Unit</th>
                  <th className="text-left font-semibold text-fg-secondary px-3 py-2">Notes</th>
                  <th className="text-left font-semibold text-fg-secondary px-3 py-2">{S.recipe.evidence.column}</th>
                </tr>
              </thead>
              <tbody>
                {anchored.map(({ row, anchor }) => {
                  const status = resolveDisplayStatus(anchor);
                  const badge = evidenceBadge(status);
                  const target = evidenceTarget(anchor);
                  return (
                    <tr key={row.index} className="border-b border-border/50 last:border-b-0 hover:bg-surface-hover/30 transition-colors">
                      <td className="px-3 py-2 font-mono tabular-nums text-fg-muted">{row.index + 1}</td>
                      <td className="px-3 py-2 text-sm text-fg-secondary">{row.name || '-'}</td>
                      <td className="px-3 py-2 font-mono text-sm tabular-nums text-accent">{row.value || '-'}</td>
                      <td className="px-3 py-2 font-mono text-sm tabular-nums text-fg-muted">{row.unit || '-'}</td>
                      <td className="px-3 py-2 text-xs text-fg-muted">{row.notes || '-'}</td>
                      <td className="px-3 py-2">
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Tooltip
                            content={<span className="block max-w-xs whitespace-pre-wrap">{evidenceTooltip(anchor)}</span>}
                          >
                            <span aria-label={badge.label}>
                              <Badge variant={badge.tone}>
                                <AppIcon name={badge.icon} className="w-3 h-3 mr-1" />
                                {badge.label}
                              </Badge>
                            </span>
                          </Tooltip>
                          {anchor && target && onJumpToEvidence && (
                            <button
                              type="button"
                              onClick={() => onJumpToEvidence(anchor)}
                              className="btn-ghost text-2xs px-1.5 py-0.5"
                              title={S.recipe.evidence.jump}
                            >
                              {target.confirmed
                                ? S.recipe.evidence.confirmedPage(target.page)
                                : S.recipe.evidence.candidatePage(target.page)}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
```

- [ ] **Step 8: AnalysisPanel 배선** — `sasoo/frontend/src/components/AnalysisPanel.tsx` 3곳.

(a) `import type` 목록에 `EvidenceAnchor`를 추가한다(이미 `Recipe` 등을 `@/lib/api`에서 가져오고 있다).

(b) `AnalysisPanelProps`의 `onJumpToTablePage?: (table: Table) => void;` 줄 뒤에 추가:

```tsx
  onJumpToEvidence?: (anchor: EvidenceAnchor) => void;
```

(c) 구조분해에서 `onJumpToTablePage,` 뒤에 `onJumpToEvidence,`를 추가하고, `<RecipeCard`
    호출에 prop을 넘긴다.

```tsx
            <RecipeCard
              recipe={recipe}
              loading={getPhaseStatus('recipe') === 'running'}
              onJumpToEvidence={onJumpToEvidence}
            />
```

- [ ] **Step 9: Workbench 배선** — `sasoo/frontend/src/pages/Workbench.tsx`에서
  `onJumpToTablePage={(table) => { ... }}` 블록을 찾아 그 **뒤에** 추가한다. import에
  `evidenceTarget`(`@/lib/evidence`)과 타입 `EvidenceAnchor`(`@/lib/api`)를 더한다.

```tsx
                onJumpToEvidence={(anchor: EvidenceAnchor) => {
                  const target = evidenceTarget(anchor);
                  if (!target) return;
                  setNavigationRequest({
                    page: target.page,
                    requestId: `evidence-${anchor.target_key}-${Date.now()}`,
                    source: 'recipe',
                  });
                }}
```

  `PdfNavigationRequest.source`에는 `'recipe'`가 이미 정의돼 있으므로 타입 변경이 없다.

- [ ] **Step 10: 타입·린트·빌드 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/frontend && pnpm tsc --noEmit
cd /Users/dongj/dev/논문_사수_개발중/sasoo/frontend && pnpm lint
cd /Users/dongj/dev/논문_사수_개발중/sasoo && pnpm test:unit
```

기대: 오류 0, 기존 vitest 테스트 + 신규 18건 통과.

- [ ] **Step 11: 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중 && git add -A && git commit -m "$(cat <<'EOF'
feat(workbench): 레시피 파라미터에 근거 상태 배지와 페이지 점프 추가

색만으로 상태를 전달하지 않는다 — 아이콘·라벨·툴팁을 함께 쓰고 VERIFIED만 검증으로
표시한다. 툴팁은 확인된 원문과 LLM이 주장한 인용을 라벨로 구분한다.
앵커는 target_index로 결합하되 target_label이 다르면 숨긴다(fail closed).
파라미터 파서를 lib/evidence.ts로 옮겨 백엔드 검증기와 규칙을 맞추고 테스트를 붙였다.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: CSV export에 근거 열 보존

verified와 unverified를 **모두** 내보낸다. verified만 뽑으면 품질을 실제보다 좋게 보이게 한다.
확인된 인용과 주장된 인용은 서로 다른 열에 넣는다 — 미확인 인용이 "검증된 근거표"로
유통되면 안 된다.

**Files**

- Create: `sasoo/frontend/src/lib/recipeCsv.ts` (RecipeCard의 `generateCsvFromRecipe` 이동 + 열 추가)
- Create: `sasoo/frontend/src/lib/recipeCsv.test.ts`
- Modify: `sasoo/frontend/src/components/RecipeCard.tsx` (로컬 함수 삭제 → lib import)

**Interfaces**

Consumes: Task 7의 `parseRecipeParameters`, `attachEvidence`, `resolveDisplayStatus`,
`evidenceBadge`, `@/lib/api`의 `Recipe`

Produces:

```ts
// sasoo/frontend/src/lib/recipeCsv.ts
export const RECIPE_CSV_HEADER: readonly string[];
export function generateCsvFromRecipe(recipe: Recipe): string;
```

CSV 열(9개, 기존 3열의 의미는 그대로):

```
Section,Key,Value,Evidence Status,Evidence Method,Evidence Page,Evidence Quote (verified),Claimed Quote (unverified),Claimed Page
```

**Steps**

- [ ] **Step 1: 실패 테스트 작성** — `sasoo/frontend/src/lib/recipeCsv.test.ts` 생성.

```ts
import { describe, expect, it } from 'vitest';
import type { EvidenceAnchor, Recipe } from '@/lib/api';
import { RECIPE_CSV_HEADER, generateCsvFromRecipe } from '@/lib/recipeCsv';

function anchor(overrides: Partial<EvidenceAnchor>): EvidenceAnchor {
  return {
    target_index: 0,
    target_key: 'p000:temp',
    target_label: 'temp',
    source_tag: 'explicit',
    claimed_quote: 'annealed at 500 C',
    claimed_page: 3,
    quote_status: 'verified_exact',
    page_status: 'match',
    value_status: 'value_in_quote',
    display_status: 'VERIFIED',
    match_method: 'exact',
    match_ratio: 1,
    matched_quote: 'annealed at 500 C',
    matched_page: 3,
    bbox: null,
    corpus: 'pdf_text',
    failure_detail: null,
    verifier_version: 'ev1',
    normalizer_version: 'norm-v1',
    ...overrides,
  };
}

function recipeWith(anchors: EvidenceAnchor[] | null): Recipe {
  return {
    paper_id: 1,
    model_used: 'gemini',
    created_at: '2026-08-06',
    recipe: {
      title: '레시피',
      objective: '목적',
      materials: ['재료 A'],
      parameters: [
        { name: 'temp', value: '500', unit: 'C', notes: 'Methods' },
        { name: 'power', value: '3.2', unit: 'mW', notes: '' },
      ],
      steps: ['1단계'],
    },
    evidence: anchors
      ? {
          verifier_version: 'ev1',
          normalizer_version: 'norm-v1',
          summary: { total: anchors.length, verified: 1, by_display_status: {} },
          anchors,
        }
      : null,
  };
}

function rows(csv: string): string[][] {
  return csv.split('\n').map((line) => line.split(','));
}

describe('generateCsvFromRecipe', () => {
  it('헤더는 기존 3열 뒤에 근거 6열을 붙인다', () => {
    const [header] = rows(generateCsvFromRecipe(recipeWith(null)));
    expect(header.slice(0, 3)).toEqual(['Section', 'Key', 'Value']);
    expect(header).toEqual([...RECIPE_CSV_HEADER]);
    expect(header).toHaveLength(9);
  });

  it('모든 행의 열 수가 헤더와 같다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({})]));
    for (const row of rows(csv)) {
      expect(row.length).toBeGreaterThanOrEqual(9);
    }
  });

  it('검증 메타 행을 상단에 남긴다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({})]));
    expect(csv).toContain('Meta,Verifier,ev1/norm-v1');
    expect(csv).toContain('Meta,Evidence Verified,1/1');
  });

  it('VERIFIED 행만 확인된 인용 열을 채운다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({})]));
    const paramRow = rows(csv).find((row) => row[0] === 'Parameter' && row[1] === 'temp');
    expect(paramRow).toBeDefined();
    expect(paramRow![3]).toBe('VERIFIED');
    expect(paramRow![6]).toBe('annealed at 500 C');   // Evidence Quote (verified)
    expect(paramRow![7]).toBe('');                     // Claimed Quote (unverified)
  });

  it('미검증 행은 주장 인용을 별도 열에 넣고 확인 열은 비운다', () => {
    const csv = generateCsvFromRecipe(
      recipeWith([anchor({ display_status: 'UNVERIFIED_NOT_FOUND', matched_quote: null, matched_page: null })]),
    );
    const paramRow = rows(csv).find((row) => row[0] === 'Parameter' && row[1] === 'temp');
    expect(paramRow![3]).toBe('UNVERIFIED_NOT_FOUND');
    expect(paramRow![6]).toBe('');
    expect(paramRow![7]).toBe('annealed at 500 C');
  });

  it('앵커가 없는 파라미터는 UNVERIFIED_NOT_RUN으로 나간다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({})]));
    const paramRow = rows(csv).find((row) => row[0] === 'Parameter' && row[1] === 'power');
    expect(paramRow![3]).toBe('UNVERIFIED_NOT_RUN');
  });

  it('Info·Material·Step 행의 근거 열은 비어 있다', () => {
    const csv = generateCsvFromRecipe(recipeWith([anchor({})]));
    for (const row of rows(csv)) {
      if (['Info', 'Material', 'Equipment', 'Step', 'Critical Note', 'Meta'].includes(row[0])) {
        expect(row.slice(3).every((cell) => cell === '')).toBe(true);
      }
    }
  });

  it('인용의 쉼표·따옴표·개행을 이스케이프한다', () => {
    const csv = generateCsvFromRecipe(
      recipeWith([anchor({ matched_quote: 'a "quoted", multi\nline span' })]),
    );
    expect(csv).toContain('"a ""quoted"", multi\nline span"');
  });
});
```

  마지막 테스트의 `Meta` 행은 `row.slice(3)`이 비어야 하므로 메타 행도 9열로 채운다.

- [ ] **Step 2: 실패 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo && pnpm exec vitest run frontend/src/lib/recipeCsv.test.ts
```

기대: `Failed to resolve import "@/lib/recipeCsv"`.

- [ ] **Step 3: recipeCsv.ts 구현** — `sasoo/frontend/src/lib/recipeCsv.ts` 생성.

```ts
import type { Recipe } from '@/lib/api';
import { attachEvidence, parseRecipeParameters, resolveDisplayStatus } from '@/lib/evidence';

// 기존 3열(Section/Key/Value)의 의미는 그대로 두고 근거 6열을 뒤에 붙인다.
// 상태 코드는 번역 라벨이 아니라 코드값 그대로 넣는다 — 기계 처리와 재현을 위해서다.
export const RECIPE_CSV_HEADER = [
  'Section',
  'Key',
  'Value',
  'Evidence Status',
  'Evidence Method',
  'Evidence Page',
  'Evidence Quote (verified)',
  'Claimed Quote (unverified)',
  'Claimed Page',
] as const;

const COLUMN_COUNT = RECIPE_CSV_HEADER.length;

function plainRow(section: string, key: string, value: string): string[] {
  return [section, key, value, ...Array(COLUMN_COUNT - 3).fill('')];
}

function escapeCell(cell: string): string {
  const value = String(cell).replace(/"/g, '""');
  return value.includes(',') || value.includes('"') || value.includes('\n') ? `"${value}"` : value;
}

export function generateCsvFromRecipe(recipe: Recipe): string {
  const data = recipe.recipe as Record<string, unknown>;
  const rows: string[][] = [];

  rows.push([...RECIPE_CSV_HEADER]);

  // 표가 도구 밖으로 나가도 검증 맥락이 따라가게 메타 행을 남긴다.
  const evidence = recipe.evidence ?? null;
  if (evidence) {
    rows.push(plainRow('Meta', 'Verifier', `${evidence.verifier_version}/${evidence.normalizer_version}`));
    rows.push(plainRow('Meta', 'Evidence Verified', `${evidence.summary.verified}/${evidence.summary.total}`));
  } else {
    rows.push(plainRow('Meta', 'Verifier', 'not_run'));
  }

  rows.push(plainRow('Info', 'Title', String(data.title || '')));
  rows.push(plainRow('Info', 'Objective', String(data.objective || '')));
  rows.push(plainRow('Info', 'Confidence', data.confidence != null ? `${(Number(data.confidence) * 100).toFixed(0)}%` : ''));
  rows.push(plainRow('Info', 'Reproducibility', data.reproducibility_score != null ? `${(Number(data.reproducibility_score) * 100).toFixed(0)}%` : ''));

  const materials = (data.materials as string[]) || [];
  materials.forEach((m, i) => rows.push(plainRow('Material', `#${i + 1}`, m)));

  const equipment = (data.equipment as string[]) || [];
  equipment.forEach((e, i) => rows.push(plainRow('Equipment', `#${i + 1}`, e)));

  // 파라미터는 화면과 같은 파서를 쓴다 — CSV와 화면의 행이 어긋나면 근거가 다른 줄에 붙는다.
  const anchored = attachEvidence(parseRecipeParameters(data.parameters), evidence);
  anchored.forEach(({ row, anchor }) => {
    const status = resolveDisplayStatus(anchor);
    const verified = status === 'VERIFIED';
    rows.push([
      'Parameter',
      row.name,
      `${row.value || ''}${row.unit ? ' ' + row.unit : ''}${row.notes ? ' (' + row.notes + ')' : ''}`,
      status,
      anchor?.match_method ?? '',
      anchor?.matched_page != null ? String(anchor.matched_page) : '',
      // 확인된 인용만 이 열에 넣는다. 미확인 인용을 여기 넣으면 CSV가 "검증된 근거표"로
      // 유통되며 거짓을 퍼뜨린다.
      verified ? anchor?.matched_quote ?? '' : '',
      verified ? '' : anchor?.claimed_quote ?? '',
      anchor?.claimed_page != null ? String(anchor.claimed_page) : '',
    ]);
  });

  const steps = (data.steps as string[]) || [];
  steps.forEach((s, i) => rows.push(plainRow('Step', `#${i + 1}`, s)));

  const notes = (data.critical_notes as string[]) || [];
  notes.forEach((n, i) => rows.push(plainRow('Critical Note', `#${i + 1}`, n)));

  if (data.expected_results) rows.push(plainRow('Info', 'Expected Results', String(data.expected_results)));
  if (data.safety_notes) rows.push(plainRow('Info', 'Safety Notes', String(data.safety_notes)));

  return rows.map((row) => row.map(escapeCell).join(',')).join('\n');
}
```

- [ ] **Step 4: RecipeCard에서 로컬 CSV 함수 제거** — `sasoo/frontend/src/components/RecipeCard.tsx`에서
  `function generateCsvFromRecipe(recipe: Recipe): string { ... }` 전체를 삭제하고
  import에 추가한다. `downloadCsv`와 `exportCsv` 콜백은 그대로 둔다.

```tsx
import { generateCsvFromRecipe } from '@/lib/recipeCsv';
```

  삭제 후 `Recipe` 타입이 여전히 쓰이는지 확인한다(props에서 쓰므로 import는 유지).

- [ ] **Step 5: 통과 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo && pnpm exec vitest run frontend/src/lib/recipeCsv.test.ts
cd /Users/dongj/dev/논문_사수_개발중/sasoo/frontend && pnpm tsc --noEmit && pnpm lint
cd /Users/dongj/dev/논문_사수_개발중/sasoo && pnpm test:unit
```

기대: `8 passed` + 타입/린트 오류 0 + 전체 vitest 통과.

- [ ] **Step 6: 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중 && git add -A && git commit -m "$(cat <<'EOF'
feat(export): CSV에 근거 상태·방법·페이지·인용 열 추가

verified와 unverified를 모두 내보낸다 — verified만 뽑으면 품질을 실제보다 좋게 보이게 한다.
확인된 인용과 LLM이 주장한 인용을 별도 열로 분리해 미확인 인용이 검증된 근거표로
유통되는 것을 막는다. 검증기 버전과 확인 비율을 메타 행으로 남긴다.
CSV가 화면과 같은 파라미터 파서를 쓰도록 lib/recipeCsv.ts로 옮겼다.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: 회귀 지표 하네스

`tools/extraction_audit/`의 관례를 따르되 **lane은 하나뿐**이다 — 검증기는 완전 결정론이라
LLM을 부르지 않는다(이미 저장된 recipe 행 + PDF만 읽는다). 실제 논문이 필요한 항목은
로컬 전용이고 CI에서는 자동 skip된다.

**Files**

- Create: `sasoo/backend/tools/evidence_audit/__init__.py`
- Create: `sasoo/backend/tools/evidence_audit/measure.py`
- Create: `sasoo/backend/services/test_evidence_regression.py`

**Interfaces**

Consumes: Task 3의 `verify_recipe_parameters`, `iter_recipe_parameters`,
`EVIDENCE_VERIFIER_VERSION`; 기존 `models.database.{DB_PATH, get_paper_dir}`;
`api.analysis_routes._find_paper_pdf`는 쓰지 않고 tool 안에서 같은 glob 규칙을 재현한다
(라우트 import는 FastAPI 전체를 끌고 온다).

Produces:

```python
# sasoo/backend/tools/evidence_audit/measure.py
def latest_recipe_rows(db_path, limit: int | None = None) -> list[dict]: ...
    #   [{"paper_id", "folder_name", "result_id", "recipe"(dict), "engine"}]
def measure_paper(row: dict) -> dict: ...
    #   {"paper_id","folder_name","engine","parameters","offered","by_display_status",
    #    "verified","exact","normalized","partial","not_found","value_present",
    #    "page_confirmed","bbox","forged_false_verify","elapsed_ms"}
def aggregate(results: list[dict]) -> dict: ...
def main(argv=None) -> int: ...
```

**Steps**

- [ ] **Step 1: 하네스 스켈레톤 + 실패 테스트** — `sasoo/backend/services/test_evidence_regression.py` 생성.

```python
"""Evidence 검증기 회귀 게이트 — 실제 라이브러리가 있을 때만 돈다.

CI에는 논문 데이터도 앱 DB도 없으므로 자동 skip된다(services/test_extraction_accuracy_regression.py와
같은 관례). CI에서 항상 도는 결정론 게이트는 services/test_evidence_verifier.py의 합성 PDF
테스트다 — 위조 인용 false-verify=0은 거기서 고정된다.

여기서 보는 것은 "실제 데이터에서도 불변식이 깨지지 않는가"다.
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from models.database import DB_PATH  # noqa: E402


def _has_local_corpus() -> bool:
    if not Path(DB_PATH).exists():
        return False
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM analysis_results WHERE phase = 'recipe'"
            ).fetchone()[0]
        finally:
            conn.close()
    except sqlite3.Error:
        return False
    return count > 0


@unittest.skipUnless(_has_local_corpus(), "로컬 DB에 recipe 결과가 없어 Evidence 회귀 게이트를 건너뛴다")
class EvidenceRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools.evidence_audit.measure import latest_recipe_rows, measure_paper

        cls.results = [measure_paper(row) for row in latest_recipe_rows(DB_PATH, limit=3)]

    def test_corpus_is_not_empty(self):
        self.assertGreater(len(self.results), 0)

    def test_every_parameter_gets_exactly_one_anchor(self):
        for result in self.results:
            self.assertEqual(
                sum(result["by_display_status"].values()),
                result["parameters"],
                result["folder_name"],
            )

    def test_forged_quotes_never_verify_on_real_papers(self):
        total = sum(result["forged_false_verify"] for result in self.results)
        self.assertEqual(total, 0)

    def test_verifier_stays_within_synchronous_budget(self):
        # 동기 실행을 유지할 수 있는지 보는 지표. 넘으면 별도 phase 분리를 검토한다.
        for result in self.results:
            self.assertLess(result["elapsed_ms"], 5000, result["folder_name"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services/test_evidence_regression.py -q
```

기대: 로컬 DB에 recipe가 있으면 `ModuleNotFoundError: No module named 'tools.evidence_audit'`,
없으면 `1 skipped`(그 경우 Step 3 구현 후 skip 사유를 보고서에 적는다).

- [ ] **Step 3: 하네스 구현** — `sasoo/backend/tools/evidence_audit/__init__.py`는 빈 파일로 만들고
  `sasoo/backend/tools/evidence_audit/measure.py`를 생성한다.

```python
"""Evidence Anchoring 회귀 지표 하네스 (단일 lane).

검증기는 완전 결정론이라 LLM을 부르지 않는다 — 이미 저장된 recipe 결과와 PDF만 읽는다.
그래서 lane이 하나다(tools/extraction_audit는 VLM 비결정성 때문에 2-lane이다).

실행:
    cd sasoo/backend
    .venv/bin/python -m tools.evidence_audit.measure
    .venv/bin/python -m tools.evidence_audit.measure --limit 5 --json _out/metrics.json

측정 지표:
    quote_offer_rate     인용을 준 파라미터 / 전체 파라미터   (프롬프트 준수도)
    verified_rate        VERIFIED / 인용을 준 파라미터        (핵심 KPI)
    parameter_verified_rate  VERIFIED / 전체 파라미터         (사용자 체감)
    exact/normalized/partial/not_found_rate                   (정규화 규칙 효과)
    value_present_rate   값 가드 통과 / 인용이 확인된 파라미터
    page_confirm_rate    page_status=match / 인용이 확인된 파라미터  (LLM 페이지 신뢰도)
    bbox_rate            bbox 있는 앵커 / 인용이 확인된 파라미터     (하이라이트 커버리지)
    forged_false_verify  숫자 1자리 변조 인용이 VERIFIED가 된 건수  (0이어야 한다)
    elapsed_ms           논문당 검증 소요                            (동기 실행 유지 판단)

퍼센트만 쓰지 않고 항상 n/N을 함께 낸다. engine(ODL/Gemini)별로도 분해한다 —
엔진 비대칭이 재발하는지 상시 감시해야 한다.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from models.database import DB_PATH, get_paper_dir  # noqa: E402
from services.evidence_verifier import (  # noqa: E402
    EVIDENCE_NORMALIZER_VERSION,
    EVIDENCE_VERIFIER_VERSION,
    iter_recipe_parameters,
    verify_recipe_parameters,
)

OUT_DIR = Path(__file__).resolve().parent / "_out"
_DIGIT = re.compile(r"\d")


def _find_pdf(paper_dir: Path) -> Optional[Path]:
    """api.analysis_routes._find_paper_pdf와 같은 규칙(라우트 import는 FastAPI를 끌고 온다)."""
    try:
        pdfs = sorted(paper_dir.glob("*.pdf"))
    except OSError:
        return None
    return pdfs[0] if pdfs else None


def _manifest_engine(paper_dir: Path) -> str:
    manifest = paper_dir / ".odl_manifest.json"
    if not manifest.exists():
        return "unknown"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "unknown"
    return str(payload.get("engine") or "unknown")


def latest_recipe_rows(db_path, limit: Optional[int] = None) -> list[dict[str, Any]]:
    """논문별 최신 recipe 행을 읽는다(읽기 전용 연결 — 앱 DB를 건드리지 않는다)."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT p.id AS paper_id, p.folder_name AS folder_name,
                   ar.id AS result_id, ar.result AS result
            FROM papers p
            JOIN analysis_results ar ON ar.id = (
                SELECT id FROM analysis_results
                WHERE paper_id = p.id AND phase = 'recipe'
                ORDER BY created_at DESC, id DESC LIMIT 1
            )
            ORDER BY p.id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    collected: list[dict[str, Any]] = []
    for row in rows:
        try:
            recipe = json.loads(row["result"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(recipe, dict) or "_parse_error" in recipe or recipe.get("skipped"):
            continue
        paper_dir = get_paper_dir(row["folder_name"])
        collected.append(
            {
                "paper_id": row["paper_id"],
                "folder_name": row["folder_name"],
                "result_id": row["result_id"],
                "recipe": recipe,
                "paper_dir": paper_dir,
                "engine": _manifest_engine(paper_dir),
            }
        )
        if limit is not None and len(collected) >= limit:
            break
    return collected


def _forge(quote: str) -> Optional[str]:
    """인용의 마지막 숫자 한 자리를 바꾼 위조본. 숫자가 없으면 None."""
    matches = list(_DIGIT.finditer(quote))
    if not matches:
        return None
    at = matches[-1].start()
    original = quote[at]
    replacement = "9" if original != "9" else "1"
    return quote[:at] + replacement + quote[at + 1 :]


def measure_paper(row: dict[str, Any]) -> dict[str, Any]:
    pdf_path = _find_pdf(row["paper_dir"])
    started = time.perf_counter()
    drafts = verify_recipe_parameters(row["recipe"], pdf_path)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    parameters = iter_recipe_parameters(row["recipe"])
    offered = sum(1 for _, param in parameters if str(param.get("evidence_quote") or "").strip())
    by_display = Counter(draft.display_status for draft in drafts)
    by_quote = Counter(draft.quote_status for draft in drafts)
    located = [d for d in drafts if d.quote_status in {"verified_exact", "verified_normalized"}]

    # 위조 인용 게이트: 확인된 인용의 숫자를 한 자리 바꿔 다시 검증한다.
    forged_params = []
    for draft in located:
        forged = _forge(draft.claimed_quote or "")
        if forged is None:
            continue
        forged_params.append(
            {
                "name": draft.target_label,
                "value": "0",
                "source_tag": "explicit",
                "evidence_quote": forged,
                "evidence_page": draft.matched_page,
            }
        )
    forged_drafts = (
        verify_recipe_parameters({"parameters": forged_params}, pdf_path) if forged_params else []
    )

    return {
        "paper_id": row["paper_id"],
        "folder_name": row["folder_name"],
        "engine": row["engine"],
        "pdf": str(pdf_path) if pdf_path else None,
        "parameters": len(drafts),
        "offered": offered,
        "by_display_status": dict(by_display),
        "by_quote_status": dict(by_quote),
        "verified": by_display.get("VERIFIED", 0),
        "exact": by_quote.get("verified_exact", 0),
        "normalized": by_quote.get("verified_normalized", 0),
        "partial": by_quote.get("partial_match", 0),
        "not_found": by_quote.get("not_found", 0),
        "value_present": sum(1 for d in located if d.value_status == "value_in_quote"),
        "page_confirmed": sum(1 for d in located if d.page_status == "match"),
        "bbox": sum(1 for d in located if d.bbox_json),
        "forged_attempts": len(forged_params),
        "forged_false_verify": sum(1 for d in forged_drafts if d.display_status == "VERIFIED"),
        "elapsed_ms": round(elapsed_ms, 1),
    }


def _ratio(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "n/a (0/0)"
    return f"{numerator / denominator:.3f} ({numerator}/{denominator})"


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    totals: Counter = Counter()
    for result in results:
        for key in (
            "parameters", "offered", "verified", "exact", "normalized", "partial",
            "not_found", "value_present", "page_confirmed", "bbox",
            "forged_attempts", "forged_false_verify",
        ):
            totals[key] += result[key]

    located = totals["exact"] + totals["normalized"]
    by_engine: dict[str, Counter] = defaultdict(Counter)
    for result in results:
        by_engine[result["engine"]]["parameters"] += result["parameters"]
        by_engine[result["engine"]]["verified"] += result["verified"]
        by_engine[result["engine"]]["offered"] += result["offered"]

    return {
        "verifier_version": EVIDENCE_VERIFIER_VERSION,
        "normalizer_version": EVIDENCE_NORMALIZER_VERSION,
        "papers": len(results),
        "quote_offer_rate": _ratio(totals["offered"], totals["parameters"]),
        "verified_rate": _ratio(totals["verified"], totals["offered"]),
        "parameter_verified_rate": _ratio(totals["verified"], totals["parameters"]),
        "exact_rate": _ratio(totals["exact"], totals["parameters"]),
        "normalized_rate": _ratio(totals["normalized"], totals["parameters"]),
        "partial_rate": _ratio(totals["partial"], totals["parameters"]),
        "not_found_rate": _ratio(totals["not_found"], totals["parameters"]),
        "value_present_rate": _ratio(totals["value_present"], located),
        "page_confirm_rate": _ratio(totals["page_confirmed"], located),
        "bbox_rate": _ratio(totals["bbox"], located),
        "forged_false_verify": f"{totals['forged_false_verify']}/{totals['forged_attempts']}",
        "elapsed_ms_max": max((r["elapsed_ms"] for r in results), default=0.0),
        "by_engine": {
            engine: {
                "parameters": counter["parameters"],
                "offered": counter["offered"],
                "verified": counter["verified"],
                "parameter_verified_rate": _ratio(counter["verified"], counter["parameters"]),
            }
            for engine, counter in sorted(by_engine.items())
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Evidence Anchoring 회귀 지표 측정")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json", default=None, help="지표 JSON 저장 경로")
    args = parser.parse_args(argv)

    rows = latest_recipe_rows(args.db, limit=args.limit)
    if not rows:
        print("recipe 결과가 없습니다. 분석을 먼저 실행하세요.")
        return 1

    results = [measure_paper(row) for row in rows]
    summary = aggregate(results)

    print(f"papers={summary['papers']}  verifier={summary['verifier_version']}/{summary['normalizer_version']}")
    for key in (
        "quote_offer_rate", "verified_rate", "parameter_verified_rate",
        "exact_rate", "normalized_rate", "partial_rate", "not_found_rate",
        "value_present_rate", "page_confirm_rate", "bbox_rate", "forged_false_verify",
    ):
        print(f"  {key:<24} {summary[key]}")
    print(f"  {'elapsed_ms_max':<24} {summary['elapsed_ms_max']}")
    for engine, stats in summary["by_engine"].items():
        print(f"  engine[{engine}] {stats['parameter_verified_rate']}")

    out_path = Path(args.json) if args.json else OUT_DIR / f"metrics-{int(time.time())}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({"summary": summary, "papers": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: `.gitignore` 확인** — `tools/extraction_audit/_out`가 이미 무시되고 있는지 본다.
  없으면 `sasoo/backend/tools/evidence_audit/_out/`를 저장소 루트 `.gitignore`에 추가한다
  (측정 산출물은 커밋하지 않는다).

```bash
cd /Users/dongj/dev/논문_사수_개발중 && grep -n "_out" .gitignore sasoo/.gitignore 2>/dev/null
```

- [ ] **Step 5: 실행(로컬에 데이터가 있을 때) + 회귀 테스트**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m tools.evidence_audit.measure --limit 5
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services/test_evidence_regression.py -q
```

  출력의 `quote_offer_rate`·`verified_rate`·`forged_false_verify`를 태스크 보고서에 **실측값 그대로**
  적는다. 이 값이 스펙 §알려진 위험 1(LLM의 실제 축자 인용률 미실측)의 1차 측정 결과다.
  데이터가 없으면 "미측정(로컬 recipe 결과 없음)"으로 정직하게 적는다. **여기서 목표 수치를
  지어내지 않는다.**

- [ ] **Step 6: 전체 회귀 + 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services api models -q
cd /Users/dongj/dev/논문_사수_개발중 && git add -A && git commit -m "$(cat <<'EOF'
feat(tools): Evidence 검증 회귀 지표 하네스 추가

검증기는 결정론이라 LLM을 부르지 않는다 — 저장된 recipe 결과와 PDF만 읽는 단일 lane이다.
인용 제시율·검증률·값 가드·페이지 신뢰도·bbox 커버리지를 n/N과 함께 내고 engine별로
분해해 엔진 비대칭 재발을 감시한다. 확인된 인용의 숫자를 변조해 재검증하는
false-verify 게이트를 실데이터에도 건다. 라이브러리가 없으면 자동 skip된다.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: [Stretch — acceptance 아님] pdf.js bbox 하이라이트 스파이크

**이 태스크는 실패해도 성공으로 기록한다.** DEC-009에 따라 acceptance는 페이지 점프까지이고,
bbox는 이미 백엔드에 저장돼 있다. 여기서 확인하려는 것은 스펙 §알려진 위험 2
(`convertToViewportRectangle` 실환경 정합 미검증)뿐이다.

**중단 규칙**: 60분 안에 화면에서 하이라이트가 올바른 문장 위에 뜨지 않으면 **중단하고**
`PdfViewer.tsx`·`Workbench.tsx` 변경만 되돌린다(`lib/pdfHighlight.ts`와 테스트는 남긴다).
그 상태로 태스크를 성공으로 기록하고 보고서에 실패 원인을 적는다.

**Files**

- Create: `sasoo/frontend/src/lib/pdfHighlight.ts`
- Create: `sasoo/frontend/src/lib/pdfHighlight.test.ts`
- Modify: `sasoo/frontend/src/lib/api.ts` (`PdfNavigationRequest.highlight`)
- Modify: `sasoo/frontend/src/components/PdfViewer.tsx` (오버레이 — 되돌릴 수 있음)
- Modify: `sasoo/frontend/src/pages/Workbench.tsx` (highlight 전달 — 되돌릴 수 있음)

**Interfaces**

Produces:

```ts
// sasoo/frontend/src/lib/api.ts
export interface PdfNavigationRequest {
  page: number;
  requestId: string;
  source: 'figure' | 'table' | 'citation' | 'recipe';
  /** 선택 — bbox는 PDF 포인트·좌하단 원점. 없으면 페이지 이동만 한다. */
  highlight?: { bbox: [number, number, number, number] } | null;
}

// sasoo/frontend/src/lib/pdfHighlight.ts
export interface ViewportLike {
  width: number;
  height: number;
  convertToViewportRectangle(rect: number[]): number[];
}
export interface PercentRect { leftPct: number; topPct: number; widthPct: number; heightPct: number }
export function bboxToPercentRect(bbox: readonly number[], viewport: ViewportLike): PercentRect | null;
```

**Steps**

- [ ] **Step 1: 기하 순수함수 실패 테스트** — `sasoo/frontend/src/lib/pdfHighlight.test.ts` 생성.

```ts
import { describe, expect, it } from 'vitest';
import { bboxToPercentRect, type ViewportLike } from '@/lib/pdfHighlight';

/** 회전 없음·scale 1인 pdf.js viewport의 변환을 흉내낸다: y축만 뒤집는다. */
function viewport(width = 595, height = 842, scale = 1): ViewportLike {
  return {
    width: width * scale,
    height: height * scale,
    convertToViewportRectangle(rect: number[]): number[] {
      const [x0, y0, x1, y1] = rect;
      return [x0 * scale, (height - y1) * scale, x1 * scale, (height - y0) * scale];
    },
  };
}

describe('bboxToPercentRect', () => {
  it('좌하단 원점 bbox를 퍼센트 사각형으로 바꾼다', () => {
    const rect = bboxToPercentRect([59.5, 421, 297.5, 505.2], viewport());
    expect(rect).not.toBeNull();
    expect(rect!.leftPct).toBeCloseTo(10, 1);
    expect(rect!.widthPct).toBeCloseTo(40, 1);
    expect(rect!.topPct).toBeCloseTo(40, 1);
    expect(rect!.heightPct).toBeCloseTo(10, 1);
  });

  it('확대해도 퍼센트가 같다 (줌마다 재계산할 필요가 없다)', () => {
    const at100 = bboxToPercentRect([59.5, 421, 297.5, 505.2], viewport(595, 842, 1));
    const at200 = bboxToPercentRect([59.5, 421, 297.5, 505.2], viewport(595, 842, 2));
    expect(at200!.leftPct).toBeCloseTo(at100!.leftPct, 5);
    expect(at200!.heightPct).toBeCloseTo(at100!.heightPct, 5);
  });

  it('좌표가 뒤집혀 들어와도 정규화한다', () => {
    const rect = bboxToPercentRect([297.5, 505.2, 59.5, 421], viewport());
    expect(rect!.widthPct).toBeGreaterThan(0);
    expect(rect!.heightPct).toBeGreaterThan(0);
  });

  it('면적 0·비정상 값은 null이다', () => {
    expect(bboxToPercentRect([10, 10, 10, 10], viewport())).toBeNull();
    expect(bboxToPercentRect([Number.NaN, 1, 2, 3], viewport())).toBeNull();
    expect(bboxToPercentRect([1, 2, 3], viewport())).toBeNull();
  });
});
```

- [ ] **Step 2: 실패 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo && pnpm exec vitest run frontend/src/lib/pdfHighlight.test.ts
```

기대: `Failed to resolve import "@/lib/pdfHighlight"`.

- [ ] **Step 3: 순수함수 구현** — `sasoo/frontend/src/lib/pdfHighlight.ts` 생성.

```ts
/**
 * 백엔드 bbox(PDF 포인트, 좌하단 원점)를 페이지 div 안의 퍼센트 사각형으로 바꾼다.
 *
 * 직접 `pageHeight - y`를 계산하지 않고 pdf.js의 convertToViewportRectangle을 쓴다 —
 * 회전과 CropBox 오프셋을 pdf.js가 흡수한다. 결과를 퍼센트로 두면 줌이 바뀌어도
 * 다시 계산할 필요가 없다.
 */

export interface ViewportLike {
  width: number;
  height: number;
  convertToViewportRectangle(rect: number[]): number[];
}

export interface PercentRect {
  leftPct: number;
  topPct: number;
  widthPct: number;
  heightPct: number;
}

export function bboxToPercentRect(
  bbox: readonly number[],
  viewport: ViewportLike,
): PercentRect | null {
  if (!Array.isArray(bbox) || bbox.length !== 4 || bbox.some((n) => !Number.isFinite(n))) {
    return null;
  }
  const converted = viewport.convertToViewportRectangle([bbox[0], bbox[1], bbox[2], bbox[3]]);
  if (!converted || converted.length !== 4 || converted.some((n) => !Number.isFinite(n))) {
    return null;
  }

  const left = Math.min(converted[0], converted[2]);
  const right = Math.max(converted[0], converted[2]);
  const top = Math.min(converted[1], converted[3]);
  const bottom = Math.max(converted[1], converted[3]);
  const width = right - left;
  const height = bottom - top;
  if (width <= 0 || height <= 0 || viewport.width <= 0 || viewport.height <= 0) {
    return null;
  }

  return {
    leftPct: (left / viewport.width) * 100,
    topPct: (top / viewport.height) * 100,
    widthPct: (width / viewport.width) * 100,
    heightPct: (height / viewport.height) * 100,
  };
}
```

- [ ] **Step 4: 통과 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo && pnpm exec vitest run frontend/src/lib/pdfHighlight.test.ts
```

기대: `4 passed`.

- [ ] **Step 5: 오버레이 배선 시도** — `api.ts`의 `PdfNavigationRequest`에 `highlight`를 추가하고
  (위 Interfaces 참조), `Workbench.tsx`의 `onJumpToEvidence`에서 bbox를 실어 보낸다.

```tsx
                  setNavigationRequest({
                    page: target.page,
                    requestId: `evidence-${anchor.target_key}-${Date.now()}`,
                    source: 'recipe',
                    highlight: anchor.bbox ? { bbox: anchor.bbox } : null,
                  });
```

  `PdfViewer.tsx`의 `navigationRequest` 이펙트(내용: `if (!navigationRequest) return;`로 시작하고
  `instances.pdfViewer.currentPageNumber = nextPage;`로 끝나는 useEffect)를 아래로 바꾼다.

```tsx
  useEffect(() => {
    if (!navigationRequest) return;
    pendingPageRef.current = navigationRequest.page;

    const instances = instancesRef.current;
    if (!instances || !documentRef.current) return;

    const nextPage = clampPage(navigationRequest.page, instances.pdfViewer.pagesCount);
    instances.pdfViewer.currentPageNumber = nextPage;

    // Evidence 하이라이트(스트레치). bbox가 없으면 페이지 이동만 한다.
    const bbox = navigationRequest.highlight?.bbox ?? null;
    document.querySelectorAll('.sasoo-evidence-highlight').forEach((node) => node.remove());
    if (!bbox) return;

    const draw = () => {
      const pageView = instances.pdfViewer.getPageView?.(nextPage - 1);
      const pageDiv: HTMLElement | undefined = pageView?.div;
      if (!pageView?.viewport || !pageDiv) return;
      const rect = bboxToPercentRect(bbox, pageView.viewport);
      if (!rect) return;
      const overlay = document.createElement('div');
      overlay.className = 'sasoo-evidence-highlight';
      overlay.style.position = 'absolute';
      overlay.style.left = `${rect.leftPct}%`;
      overlay.style.top = `${rect.topPct}%`;
      overlay.style.width = `${rect.widthPct}%`;
      overlay.style.height = `${rect.heightPct}%`;
      overlay.style.background = 'rgba(250, 204, 21, 0.32)';
      overlay.style.outline = '1px solid rgba(250, 204, 21, 0.85)';
      overlay.style.pointerEvents = 'none';
      overlay.style.zIndex = '3';
      if (getComputedStyle(pageDiv).position === 'static') {
        pageDiv.style.position = 'relative';
      }
      pageDiv.appendChild(overlay);
    };

    // 페이지가 아직 렌더되지 않았을 수 있어 pagerendered를 한 번 기다린다.
    draw();
    const onRendered = () => draw();
    instances.eventBus.on('pagerendered', onRendered);
    return () => {
      instances.eventBus.off('pagerendered', onRendered);
      document.querySelectorAll('.sasoo-evidence-highlight').forEach((node) => node.remove());
    };
  }, [navigationRequest]);
```

  `import { bboxToPercentRect } from '@/lib/pdfHighlight';`를 추가한다.

- [ ] **Step 6: 실환경 육안 검증(30분 상한)**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo && pnpm dev
```

  분석이 끝난 논문의 워크벤치 → 레시피 탭 → VERIFIED 파라미터의 페이지 버튼 클릭.
  확인 항목 4가지:
  1. 하이라이트가 **그 문장 위에** 뜨는가(다른 문단이 아니라)
  2. 100% / 200% 줌에서 위치가 유지되는가
  3. 페이지를 넘겼다 돌아와도 잔상이 없는가
  4. 다른 논문으로 전환할 때 stale 오버레이가 남지 않는가

  4개 중 하나라도 실패하고 30분 안에 원인을 못 잡으면 Step 7로 간다.

- [ ] **Step 7: 판정과 정리**

  - 성공: 그대로 커밋한다.
  - 실패: `PdfViewer.tsx`와 `Workbench.tsx`의 highlight 변경만 되돌린다
    (`git checkout -- sasoo/frontend/src/components/PdfViewer.tsx sasoo/frontend/src/pages/Workbench.tsx`
    후 Task 7의 `onJumpToEvidence` 배선을 다시 넣는다 — 되돌리기 전에 `git diff`로 확인할 것).
    `lib/pdfHighlight.ts`·테스트·`api.ts`의 optional 필드는 남긴다.
  - 어느 쪽이든 보고서에 실측 결과를 적는다: 화면에서 확인한 항목, 실패 시 증상과 추정 원인.
    **"동작할 것으로 보인다" 같은 표현을 쓰지 않는다.**

- [ ] **Step 8: 검증 + 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/frontend && pnpm tsc --noEmit && pnpm lint
cd /Users/dongj/dev/논문_사수_개발중/sasoo && pnpm test:unit
cd /Users/dongj/dev/논문_사수_개발중 && git add -A && git commit -m "$(cat <<'EOF'
feat(workbench): bbox→뷰포트 퍼센트 변환 순수함수와 하이라이트 스파이크

좌표 변환은 pdf.js convertToViewportRectangle에 맡기고 결과를 퍼센트로 저장해
줌마다 재계산하지 않는다. 회전·CropBox는 pdf.js가 흡수한다.
하이라이트 오버레이 자체는 스트레치 범위이며 acceptance는 페이지 점프까지다.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: 전체 검증과 PR

**Files**

- Modify: 없음(검증과 PR 생성만)

**Interfaces**

Consumes: Task 1~10 전부

Produces: `feat/phase1-evidence-anchoring` → `main` PR

**Steps**

- [ ] **Step 1: 전체 백엔드 테스트**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m py_compile main.py
cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && ./.venv/bin/python -m pytest services api models -q
```

- [ ] **Step 2: 전체 프론트 검증**

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo/frontend && pnpm tsc --noEmit
cd /Users/dongj/dev/논문_사수_개발중/sasoo/frontend && pnpm lint
cd /Users/dongj/dev/논문_사수_개발중/sasoo/frontend && pnpm build
cd /Users/dongj/dev/논문_사수_개발중/sasoo && pnpm test:unit
```

- [ ] **Step 3: 실행 화면 확인(증거 기반 완료)** — 서버·GUI를 재시작하고 실제 화면을 본다.

```bash
cd /Users/dongj/dev/논문_사수_개발중/sasoo && pnpm dev
```

  확인 목록(스크린샷 또는 관찰 기록을 보고서에 남긴다):
  1. 기존 분석 논문(앵커 없음)의 레시피 탭 → 전 파라미터가 "검증 미실행"으로 표시된다.
     빈칸이나 성공 아이콘이 뜨면 계약 위반이다.
  2. 새로 분석한 논문 → 파라미터마다 상태 배지가 뜨고 요약 배지 "근거 확인 n/m"이 보인다.
  3. VERIFIED 파라미터의 페이지 버튼 클릭 → PDF가 해당 페이지로 이동한다.
  4. 툴팁에 "확인된 원문" 또는 "LLM이 주장한 인용(원문에서 확인되지 않음)" 라벨이 보인다.
  5. CSV 내보내기 → 9개 열, `Meta,Verifier` 행, 미검증 행도 포함돼 있다.

  실행하지 못한 항목은 **미검증으로 명시**한다.

- [ ] **Step 4: 커밋 정리 확인**

```bash
cd /Users/dongj/dev/논문_사수_개발중 && git log --oneline origin/main..HEAD
cd /Users/dongj/dev/논문_사수_개발중 && git status --short
```

  기대: Task별 커밋 9~10개, 미추적 변경 없음. `docs/superpowers/plans/`와
  `.superpowers/` 로컬 문서가 실수로 커밋되지 않았는지 확인한다.

- [ ] **Step 5: PR 생성** — 병합은 하지 않는다.

```bash
cd /Users/dongj/dev/논문_사수_개발중 && git push -u origin feat/phase1-evidence-anchoring
cd /Users/dongj/dev/논문_사수_개발중 && gh pr create --base main --title "feat: Phase 1 Evidence Anchoring MVP — 레시피 파라미터 근거 앵커링" --body "$(cat <<'EOF'
## 무엇을 했나

Recipe 파라미터마다 (evidence_quote, page, 검증 상태, bbox)를 붙이고, LLM이 아닌
결정론적 코드로 검증한 뒤 UI에서 정직하게 표시한다. 검증 실패는 UNVERIFIED 계열로 남는다.

- `evidence_anchors` 테이블 신설(analysis_results.id 결속, UNIQUE 멱등 upsert)
- `services/evidence_verifier.py` — normalizer-v1, PDF 텍스트층 대조, 값 가드, bbox
- `_run_recipe`에서 row 저장 직후 동기 검증. **캐시 히트 경로도 검증한다**(백필)
- `_RECIPE_SCHEMA`에 evidence_quote/evidence_page 추가, source_tag required 승격
- RecipeCard 근거 열(배지+툴팁+페이지 점프), CSV 근거 6열, 회귀 지표 하네스

## ⚠ 캐시 무효화 고지

`_CHAIN_CACHE_VERSION`을 `2026-08-06` → `2026-08-06-ev1`로 올렸다.
**기존 논문을 재분석하면 screening·visual·recipe·deep_dive 체인 phase가 1회 전부
재과금된다.** 구 스키마 recipe 결과를 재사용하면 근거 없는 파라미터가 영구히 남기 때문에
스펙 §결정 4에 따라 의도적으로 선택했다. 이미 저장된 결과는 재분석 전까지 그대로 쓰이고,
그 결과들은 UI에서 "검증 미실행"으로 표시된다.

## 계약 (깨지 말 것)

1. 앵커 부재 = `UNVERIFIED_NOT_RUN`. 부재를 검증됨으로 표시하는 코드 경로가 없어야 한다.
2. `analysis_results.result` blob에 검증 결과를 쓰지 않는다.
3. 대조 원본은 PDF 텍스트층뿐이다(Gemini 전사본 순환 검증 금지).
4. `partial_match`는 검증이 아니다. 위조 인용 false-verify=0 게이트를 유지한다.
5. 프론트 `parseRecipeParameters`와 백엔드 `iter_recipe_parameters`는 같은 규칙이어야 한다.
6. 신규 DDL은 `init_db()`에만 등록한다(워커는 마이그레이션을 실행하지 않는다).

## 테스트

- `pytest services api models` 통과
- 합성 PDF 기반 검증기 테스트(CI에서 항상 실행) — 위조 인용 false-verify = 0
- `pnpm tsc --noEmit`, `pnpm lint`, `pnpm build`, `pnpm test:unit` 통과

## 실측값

<!-- Task 9 하네스 출력을 그대로 붙인다. 데이터가 없으면 "미측정"이라고 쓴다. -->

## 미검증 항목

<!-- 실행하지 못한 검증을 여기 남긴다. 예:
- 실PDF 대규모 pass rate: 라이브러리 N편에서만 측정(표본 편향 있음)
- pdf.js convertToViewportRectangle의 회전 페이지·CropBox≠MediaBox 정합
- 다단 조판에서 bbox 첫-rect 전략의 오배치 비율
- 한글 파일명·저사양 환경에서의 검증 지연
-->

## Stretch 결과 (Task 10)

<!-- 하이라이트 스파이크 결과를 성공/실패와 함께 사실대로 적는다. -->

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: 사용자에게 보고** — PR URL, 태스크별 결과, 실측값, 미검증 항목, stretch 결과를
  한국어로 요약해 전달한다. **병합은 사용자가 한다** — 에이전트는 `gh pr merge`를 실행하지 않는다.

---

## Self-Review

### 스펙 커버리지 (스펙의 각 결정 ↔ 태스크)

| 스펙 항목 | 요구 | 대응 태스크 | 확인 방법 |
|---|---|---|---|
| 수렴 1 — 신규 `evidence_anchors` 테이블, LLM blob 무수정, alembic 불필요 | 순수 추가 DDL + `init_db()` 패턴 | Task 1 | `models/test_evidence_anchors.py::test_ddl_is_idempotent` |
| 수렴 2 — LLM은 후보만, `source_tag` required 승격 | `evidence_quote`/`evidence_page`만 추가, 상태·bbox는 LLM 필드 아님 | Task 4 | `test_recipe_prompt...`의 `assertNotIn("verification_status")`, `required == ["name","value","source_tag"]` |
| 수렴 3 — `_run_recipe` 내 동기 실행, 별도 큐·phase 금지 | row 저장 직후, phase completed 전 | Task 5 | `test_run_recipe_anchors_evidence_with_inserted_row_id` |
| 수렴 4 — 캐시 히트도 검증, `CachedPhaseResult.result_id`, `_CHAIN_CACHE_VERSION` bump | 백필 경로 + 버전 bump | Task 5(+4) | `test_run_recipe_cache_hit_backfills_evidence`, `test_chain_cache_version_is_bumped_for_evidence_rollout` |
| 수렴 5 — 사후 `target_key`(index+slug), label 불일치 시 fail closed | 백엔드 키 생성 + 프론트 숨김 | Task 2, Task 7 | `TargetKeyTests`, `attachEvidence` label 불일치 테스트 |
| 수렴 6 — MVP는 Recipe 파라미터만, 스키마는 범용 | `target_kind`/`target_key` 범용 컬럼, claim 미구현 | Task 1 | DDL에 `target_kind` 존재, claim 코드 없음 |
| 수렴 7 — 사용자 확인/수정 UI 제외 | read-only 표시만 | Task 7 | RecipeCard에 상태를 바꾸는 핸들러가 없다(점프 콜백뿐) |
| 수렴 8 — 값 가드, inferred는 구조적으로 VERIFIED 불가 | `check_value_in_quote` | Task 2 | `ValueGuardTests`, `test_inferred_parameter_is_never_verified` |
| 갈림 A — PDF 텍스트층 일원화, Gemini 전사본 금지, `NO_TEXT_LAYER` | 대조 원본 단일화 | Task 3 | `EVIDENCE_CORPUS_PDF_TEXT` 고정, `test_scanned_pdf_without_text_layer` |
| 갈림 B — 직교 3필드 + `display_status` 파생, VERIFIED 조건 | 3필드 저장 + 결정론 파생 | Task 1(컬럼), Task 2(파생) | `DisplayStatusTests`(전 조합 순회) |
| 갈림 C — `partial_match`는 검증 아님, 위조 false-verify=0 게이트 | 상태 분리 + pytest 게이트 | Task 2, Task 3, Task 9 | `ForgedQuoteGateTests`, `test_forged_quotes_produce_zero_false_verify`, 하네스 `forged_false_verify` |
| 갈림 D / DEC-009 — acceptance는 페이지 점프+quote, bbox 저장은 완비, 하이라이트는 stretch | 점프=Task 7, bbox 저장=Task 3, 하이라이트=Task 10 | Task 3/7/10 | Task 10 헤더에 "acceptance 아님" 명시 |
| normalizer-v1 규칙·버전 태그 | 규칙 순서 + `normalizer_version` 컬럼 | Task 2, Task 1 | `NormalizerV1Tests`, `anchor_versions` |
| 회귀 지표(candidate/pass/page/value/forged, engine별 분모) | 하네스 | Task 9 | `measure.py`의 `aggregate`·`by_engine` |
| 위험 1 — 축자 인용률 미실측 | 프롬프트 강제 + 하네스 1차 측정 | Task 4, Task 9 | `quote_offer_rate` 실측 기록 지시 |
| 위험 2 — pdf.js 좌표 변환 미검증 | 스파이크 선행 | Task 10 | 육안 검증 4항목 |
| 위험 3 — 다단 union bbox 과대 | 첫 매치 rect만 사용 | Task 3 | `locate_bbox`의 `rects[0]` |
| 위험 4 — 검증기 예외 격리 | 파라미터별 + 호출부 2중 격리 | Task 3, Task 5 | `_verify_parameter`의 try/except, `test_evidence_failure_does_not_kill_recipe_phase` |
| DoD — 상태 표시가 색만이 아님 | 아이콘+라벨+툴팁 | Task 7 | `evidenceBadge` 라벨 비어있지 않음 테스트 |
| DoD — CSV에 quote/page/status/method 보존(verified·unverified 모두) | 6열 추가 | Task 8 | `recipeCsv.test.ts` 7건 |
| DEC-010 — PR #45 병합 후 main 분기 | Global Constraints의 분기 절차 + Phase 0 마커 확인 | Global Constraints | `grep _CHAIN_CACHE_VERSION` 사전 점검 |

미대응 항목: 없음. 단 스펙 §갈림 B의 `stale_source`는 어휘와 컬럼만 확보하고
**MVP에서 실제로 판정하지 않는다**(source hash 비교는 Phase 2). 이는 의도된 축소이며
Task 11 PR 본문의 "미검증 항목"에 적는다.

### Placeholder 스캔

계획서 안에서 다음 패턴을 검색한 결과: `TBD` 0건, `적절히` 0건, `위와 유사` 0건,
`...(생략)` 0건, `TODO` 0건. 모든 코드 스텝에 실행 가능한 코드 블록이 있고, 모든 테스트
스텝에 실제 테스트 코드가 있다. 다음 두 곳만 의도적으로 비어 있으며, 그 이유가 함께 적혀 있다.

1. Task 11 PR 본문의 `실측값` / `미검증 항목` / `Stretch 결과` — 실행 전에는 지어낼 수 없는
   값이다. 각각 "출력을 그대로 붙인다", "데이터가 없으면 미측정이라고 쓴다"로 채우는 방법을 지정했다.
2. Task 9 Step 5의 목표 수치 — 스펙이 "코드 감사만으로 임의 목표를 제시하면 parser mix를
   숨기게 된다"고 못박았으므로 baseline 측정 후에 정한다.

### 타입 일관성 확인

- **상태 어휘**: 백엔드 `QUOTE_STATUSES`(9) / `PAGE_STATUSES`(5) / `VALUE_STATUSES`(4)와
  프론트 `EvidenceDisplayStatus`(12)가 각각 Task 2·Task 7에 명시돼 있다.
  `derive_display_status`가 전 조합을 12개 중 하나로 매핑하는 것을
  `test_every_quote_status_maps_to_a_known_display_status`가 순회 검증한다.
  프론트 `BADGE_STYLE`과 `S.recipe.evidence.status`도 같은 12개 키를 갖고,
  `evidenceBadge` 테스트가 12개를 모두 순회한다. `UNVERIFIED_NOT_RUN`은 DB에 저장되지 않고
  프론트가 합성하는 값이며, 그 사실이 api.ts 주석에 적혀 있다.
- **컬럼 ↔ dataclass ↔ 응답 필드**: `ANCHOR_FIELDS`(Task 1, 20개)와
  `EvidenceAnchorDraft` 필드(Task 3, 20개)가 이름·순서까지 같다 —
  `upsert_anchors`가 `asdict(draft)`를 그대로 받으므로 어긋나면 `None`이 들어가고
  `NOT NULL` 제약(`quote_status`/`page_status`/`value_status`/`display_status`/`corpus`/
  `verifier_version`/`normalizer_version`)에서 즉시 터진다.
  `_PUBLIC_ANCHOR_FIELDS`(Task 5, 18개)는 여기서 `bbox_json`을 빼고 `bbox`(파싱된 배열)를
  더한 18+1개이며, 프론트 `EvidenceAnchor`(Task 7)가 정확히 같은 19개 키를 갖는다
  (`test_build_payload_shapes_read_model`이 `bbox_json` 부재를 확인한다).
- **bbox 좌표계**: 백엔드 `locate_bbox`가 `[x0, y_bottom, x1, y_top]` 좌하단 원점으로
  통일하고(기존 `figures`/`tables`와 동일), 프론트 `bboxToPercentRect`가 같은 규약을 전제로
  `convertToViewportRectangle`에 넘긴다. 주석이 양쪽에 있다.
- **파라미터 파서 이중 구현**: 백엔드 `iter_recipe_parameters`와 프론트
  `parseRecipeParameters`가 같은 규칙(dict/list→행, str→"name: value" 파싱, 그 외 skip)을
  갖는다. 양쪽 테스트가 동일한 혼합 입력(`[{...}, "Temperature: 500 C", 42, null, {...}]`)에
  대해 index `[0,1,2]`와 이름 `["a","Temperature","b"]`를 기대한다. 규칙이 어긋나도
  `attachEvidence`의 label fail-closed가 2차 방어선이다.
- **`CachedPhaseResult.result_id`**: 기본값 `0`을 주어 다른 phase의 기존 생성자 호출이
  깨지지 않게 했고, `_ensure_recipe_evidence`가 `if not analysis_result_id`로 0을 걸러낸다.
- **`_insert_analysis_result` 반환 타입 변경(None→int)**: 기존 호출부 6곳은 반환값을 쓰지
  않으므로 동작이 바뀌지 않는다. 테스트가 이 함수를 `AsyncMock()`으로 대체하는 경우
  `folder_name` 기본값 `""`이 검증 경로를 막아 기존 테스트가 그대로 통과한다.

