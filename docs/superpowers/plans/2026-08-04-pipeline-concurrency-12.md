# 파이프라인 동시성 8→12 상향 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 파이프라인 LLM 동시성 기본값을 8→12로 올려 페이지 비전 파싱 구간(전체의 82%)의 웨이브 수를 줄인다.

**Architecture:** 코드 기본값 2곳(`PIPELINE_LLM_CONCURRENCY`, `PAGE_CONCURRENCY`)과 근거 주석만 변경한다. 세마포어 구조·재시도 정책·resolver 순차 계약은 무수정. 스펙: `docs/superpowers/specs/2026-08-04-pipeline-concurrency-12-design.md`.

**Tech Stack:** Python(FastAPI backend), pytest. 작업 디렉터리는 `sasoo/backend`, 파이썬은 `.venv/bin/python`.

## Global Constraints

- 실효 동시성 = min(PAGE_CONCURRENCY, PIPELINE_LLM_CONCURRENCY) — 반드시 두 값을 함께 12로 올린다.
- env 오버라이드 경로(`SASOO_PIPELINE_LLM_CONCURRENCY`, `SASOO_GEMINI_PARSER_PAGE_CONCURRENCY`)는 그대로 살아 있어야 한다(롤백 계약).
- 이 두 상수를 하드코딩 숫자(8)로 참조하는 테스트는 없다(전부 심볼 참조) — 테스트 파일 수정 금지.
- resolver 2단계 순차 계약, 루프별 세마포어 레지스트리, 비전 호출 출력 구조(DPI·thinking·media_resolution)는 범위 밖 — 건드리면 안 된다.

---

### Task 1: 동시성 기본값 상향 + 근거 주석

**Files:**
- Modify: `sasoo/backend/services/concurrency.py:49` (기본값)와 그 위 주석 블록(41~48행 부근)
- Modify: `sasoo/backend/services/gemini_parser.py:64` (기본값)와 그 위 주석(62~63행 부근)

**Interfaces:**
- Consumes: 없음 (기존 상수 정의 변경)
- Produces: `PIPELINE_LLM_CONCURRENCY == 12`, `PAGE_CONCURRENCY == 12` (env 미설정 시). Task 2가 이 값으로 실측 검증한다.

- [ ] **Step 1: concurrency.py 기본값 상향**

`services/concurrency.py`의

```python
PIPELINE_LLM_CONCURRENCY = _env_int("SASOO_PIPELINE_LLM_CONCURRENCY", 8)
```

를 다음으로 교체:

```python
# 8 -> 12: 2026-08-04 실측 — 동시성 12·실호출 254건에서 429 0건, max_inflight 12 도달.
# 이득은 페이지 비전 파싱 구간(12페이지 논문 2웨이브→1웨이브)에서 나며, resolver 구간은
# 대기열이 8을 거의 안 넘어 무영향(8 vs 12 비교 실측 294.7s vs 301.0s). 문제 시 env 롤백.
PIPELINE_LLM_CONCURRENCY = _env_int("SASOO_PIPELINE_LLM_CONCURRENCY", 12)
```

기존 "4 -> 8" 주석 블록은 그대로 둔다(이력 보존, 유지+추가 원칙).

- [ ] **Step 2: gemini_parser.py 기본값 상향**

`services/gemini_parser.py`의

```python
PAGE_CONCURRENCY = _env_int("SASOO_GEMINI_PARSER_PAGE_CONCURRENCY", 8)
```

를 다음으로 교체:

```python
# 8 -> 12: 2026-08-04 실측(스펙 2026-08-04-pipeline-concurrency-12-design.md 참조).
PAGE_CONCURRENCY = _env_int("SASOO_GEMINI_PARSER_PAGE_CONCURRENCY", 12)
```

바로 위의 "실효 동시성은 … 둘을 같이 올려야 의미가 있다" 주석은 그대로 둔다.

- [ ] **Step 3: 기본값이 12로 읽히는지 즉석 확인**

Run: `cd sasoo/backend && .venv/bin/python -c "from services.concurrency import PIPELINE_LLM_CONCURRENCY as a; from services.gemini_parser import PAGE_CONCURRENCY as b; print(a, b); assert (a, b) == (12, 12)"`
Expected: `12 12` 출력, assert 통과

- [ ] **Step 4: env 롤백 계약 확인**

Run: `cd sasoo/backend && SASOO_PIPELINE_LLM_CONCURRENCY=8 SASOO_GEMINI_PARSER_PAGE_CONCURRENCY=8 .venv/bin/python -c "from services.concurrency import PIPELINE_LLM_CONCURRENCY as a; from services.gemini_parser import PAGE_CONCURRENCY as b; assert (a, b) == (8, 8), (a, b)"`
Expected: 예외 없이 종료 (env가 기본값을 이긴다)

- [ ] **Step 5: 관련 테스트 스위트 실행**

Run: `cd sasoo/backend && .venv/bin/python -m pytest services/test_gemini_parser.py services/llm/test_interactions_client.py services/test_resolver_pipeline.py -q`
Expected: 전부 PASS (이 테스트들은 상수를 심볼로 참조하므로 수정 없이 통과해야 한다. 실패하면 하드코딩 발견이므로 멈추고 보고)

- [ ] **Step 6: 전체 백엔드 테스트**

Run: `cd sasoo/backend && .venv/bin/python -m pytest -q`
Expected: 전부 PASS (2026-07-27 기준 410개+)

- [ ] **Step 7: Commit**

```bash
cd /Users/dongj/dev/논문_사수_개발중
git add sasoo/backend/services/concurrency.py sasoo/backend/services/gemini_parser.py
git commit -m "perf(pipeline): LLM 동시성 기본값 8→12 — 429 무발생 실측 근거"
```

---

### Task 2: 실측 검증 (실제 API + 무료 lane)

**Files:**
- 실행만: `tools/extraction_audit/measure.py` (deterministic lane)
- 실행만: 세션 스크래치의 `occupancy_probe.py` (없으면 Step 2 코드로 재생성)
- 결과 기록: `docs/superpowers/plans/2026-08-04-pipeline-concurrency-12.md` 하단에 실측 수치 추기

**Interfaces:**
- Consumes: Task 1의 기본값 12 (env 미설정 상태로 실행해야 새 기본값을 검증한다)
- Produces: 검증 수치 3종 — deterministic lane 무회귀, 비전 파싱 벽시계 감소, 429 카운트 0

- [ ] **Step 1: deterministic lane 무회귀 확인 (무료, API 안 씀)**

Run: `cd sasoo/backend && .venv/bin/python -m tools.extraction_audit.measure --lane deterministic --tag _conc12default`
Expected: 기존 deterministic 원장(`tools/extraction_audit/_out/measure_deterministic*.json`)과 후보 수·재현율 동일. 동시성은 정확도 경로와 독립이므로 값이 달라지면 멈추고 보고.

- [ ] **Step 2: occupancy probe 재실행 (실제 API, 논문 1편)**

세션 스크래치 `/Users/dongj/.claude/jobs/17a184c0/tmp/occupancy_probe.py`가 있으면 그대로, 없으면 대화 기록의 동일 스크립트를 재생성해 실행:

Run: `cd sasoo/backend && .venv/bin/python /Users/dongj/.claude/jobs/17a184c0/tmp/occupancy_probe.py 2022_SciRep_CoherentFsoLeo_optics`
Expected:
- `gemini_parser`의 `wall_union_sec`이 기준선 95.1초에서 **약 55~70초로 감소** (12페이지 1웨이브)
- probe의 429/오류 카운트 0
- 총 벽시계 116.5초 → 약 80~95초

감소가 없으면(±10% 이내) env 미설정 여부와 실효 동시성(min 규칙)을 먼저 의심하고 보고.

- [ ] **Step 3: 결과를 플랜 문서에 추기하고 커밋**

이 플랜 파일 하단 "실측 결과" 절에 Step 1·2 수치를 기록:

```bash
cd /Users/dongj/dev/논문_사수_개발중
git add docs/superpowers/plans/2026-08-04-pipeline-concurrency-12.md
git commit -m "docs(plan): 동시성 12 상향 실측 검증 수치 기록"
```

---

## 실측 결과 (Task 2에서 기록)

(작성 전)
