# Phase 0: Truth Restoration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 제품이 사용자에게 거짓말하는 지점(P0 거짓 성공 표시 2건, P1 캐시 오염 1건)과 낡은 문서·마케팅 문구를 제거해 "약속 = 구현" 상태를 회복한다.

**Architecture:** 코드 변경은 3건 모두 국소 수정이다 — (1) 프론트 `useAnalysis.startAnalysis`의 에러 삼킴을 boolean 반환 계약으로 교체, (2) 백엔드 phase 상태 결정을 `_is_error_result` 분기로 정직화, (3) 체인 phase 캐시 키에 system_instruction(프로필·에이전트 지침)·모델·버전을 포함. 문서 작업 3건은 유지+추가 원칙(내용 보존, 정정 추가)을 따르되 orphan CI 파일 1건만 승인된 삭제다.

**Tech Stack:** FastAPI + aiosqlite(백엔드, pytest/unittest 스타일), React + TypeScript(프론트, vitest node 환경 — jsdom 없음), Electron.

**근거:** 2026-08-05 Current-State Audit (세션 보고), `docs/product-decisions.md` DEC-005.

## Global Constraints

- 저장소: `/Users/dongj/dev/논문_사수_개발중` (원격 `dosigner/sasoo`), 앱 루트는 `sasoo/`.
- 브랜치: `fix/phase0-truth-restoration`. **PR 생성 전 `git log origin/main..main`으로 로컬 main 오염 확인 필수** (과거 사고 이력).
- 병합·release publish는 에이전트 불가(가드레일) — PR까지만 만들고 사용자에게 넘긴다.
- 버전 bump 없음 (기능 릴리스가 아니라 정합성 수정).
- 커밋 메시지는 기존 관례를 따른다: `fix(scope): 한국어 요약` + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- 문서 수정은 삭제가 아니라 정정·추가(예외: Task 4의 orphan ci.yml 삭제는 사용자 승인 항목).
- 프론트 vitest는 `environment: 'node'`(vitest.config.ts:9) — hook 렌더링 테스트 불가. Task 1은 타입 계약 + 수동 검증으로 보증하고 이 한계를 보고서에 명시한다.
- 백엔드 테스트 실행: `cd sasoo/backend && python -m pytest services api models` (venv 필요 시 기존 관례 따름). 프론트: `pnpm --dir=frontend test`, 타입: `cd sasoo/frontend && npx tsc --noEmit`.

---

### Task 1: 프론트 — 분석 시작 실패 시 성공 toast 제거 (P0)

**문제:** `useAnalysis.startAnalysis`(useAnalysis.ts:359-379)가 catch에서 에러를 삼키고 재throw하지 않아, `Workbench.onConfirmAnalysis`(Workbench.tsx:187-194)의 try가 항상 정상 종료 → 백엔드 500/네트워크 오류에도 `toast.success('분석을 시작했어요')`가 무조건 뜬다.

**설계 선택:** 재throw 대신 `Promise<boolean>` 반환(true=시작 성공). 이유: `useWorkbenchAnalysisControls.ts:79`처럼 fire-and-forget 호출처가 있어 재throw는 unhandled rejection 위험이 있고, boolean은 TypeScript가 소비를 강제한다.

**Files:**
- Modify: `sasoo/frontend/src/hooks/useAnalysis.ts:50` (인터페이스), `:359-379` (구현)
- Modify: `sasoo/frontend/src/hooks/useWorkbenchAnalysisControls.ts:12,39-47,79`
- Modify: `sasoo/frontend/src/pages/Workbench.tsx:187-194`

**Interfaces:**
- Produces: `startAnalysis(request?: AnalysisRunRequest): Promise<boolean>`, `handleStartAnalysis(selection?: AnalysisProfileSelection): Promise<boolean>`

- [ ] **Step 1: useAnalysis.ts 수정**

인터페이스(L50): `startAnalysis: (request?: AnalysisRunRequest) => Promise<void>;` → `Promise<boolean>`.

구현(L359-379)을 다음으로 교체:

```ts
const startAnalysis = useCallback(async (request: AnalysisRunRequest = {}): Promise<boolean> => {
    if (!paperId) return false;
    const sessionId = beginNewSession();
    if (!isSessionActive(sessionId)) return false;
    setIsRunning(true);

    try {
      await apiRunAnalysis(paperId, request);
      if (!isSessionActive(sessionId)) return true;
      // Don't set the /run response as status (it's not an AnalysisStatus).
      // Instead, poll immediately to get the real status.
      await pollStatus(paperId, sessionId);
      if (!isSessionActive(sessionId)) return true;
      startPolling(paperId, sessionId, POLL_INTERVAL_ACTIVE);
      return true;
    } catch (err) {
      if (!isSessionActive(sessionId)) return false;
      setIsRunning(false);
      if (err instanceof Error) console.warn('[analysis] start error:', err.message);
      setError(S.error.startAnalysisFailed);
      return false;
    }
  }, [paperId, beginNewSession, isSessionActive, pollStatus, startPolling]);
```

주의: `apiRunAnalysis` 성공 후 세션이 교체된 경우는 true(시작 자체는 성공). 기존 주석은 보존한다.

- [ ] **Step 2: useWorkbenchAnalysisControls.ts 수정**

L12 타입: `startAnalysis: (request?: AnalysisRunRequest) => Promise<boolean>;`
L39-47 `handleStartAnalysis`: 마지막 줄 `await startAnalysis({...})` → `return startAnalysis({...})`, 반환 타입 `Promise<boolean>` 명시.
L79의 직접 호출은 결과 미사용이므로 `void startAnalysis({...})`로 두고, 이 경로에 성공 toast가 없는지 눈으로 확인(있으면 같은 방식으로 분기).

- [ ] **Step 3: Workbench.tsx 수정 (L187-194)**

```ts
const onConfirmAnalysis = useCallback(async (selection?: AnalysisProfileSelection) => {
    const started = await handleStartAnalysis(selection);
    if (started) {
      toast.success(S.toast.analysisStarted);
    } else {
      toast.error(S.error.startAnalysisFailed);
    }
  }, [handleStartAnalysis, toast]);
```

- [ ] **Step 4: 검증**

Run: `cd sasoo/frontend && npx tsc --noEmit` → PASS (Promise<void> 잔존 소비처가 있으면 여기서 잡힘)
Run: `pnpm --dir=sasoo/frontend test` → 기존 8개 파일 PASS
자동 테스트 한계 명시: vitest가 node 환경이라 hook 동작 테스트는 불가 — 보고서에 "수동 검증 필요"로 기록하고, 수동 검증 절차(백엔드 미기동 상태에서 분석 시작 → 에러 toast 확인)를 남긴다.

- [ ] **Step 5: Commit**

```bash
git add sasoo/frontend/src/hooks/useAnalysis.ts sasoo/frontend/src/hooks/useWorkbenchAnalysisControls.ts sasoo/frontend/src/pages/Workbench.tsx
git commit -m "fix(workbench): 분석 시작 실패 시 성공 토스트가 뜨던 문제 — startAnalysis boolean 계약"
```

---

### Task 2: 백엔드 — 파싱 실패 phase를 completed로 승격하지 않기 (P0)

**문제:** screening/visual/recipe/deep_dive 4개 phase가 JSON 파싱 실패 시 `{"_raw":..., "_parse_error":...}` 스텁으로 저장하면서도(analysis_routes.py:485,1193,1359,1485) 곧바로 `phase_status.status = "completed"`(L503,1209,1375,1501)를 무조건 실행 — SSE·UI에 성공으로 표시된다.

**전제 확인(이미 검증됨):** `find_cached_phase_result`는 `_parse_error`/`error` 키 행을 캐시 미스로 처리(L702 주석)하므로 스텁 저장 자체는 캐시를 오염시키지 않는다. `PhaseStatus.error_message` 필드 존재(models/schemas.py:257). ProgressTracker.tsx:52는 phase `error` 상태 아이콘을 이미 렌더링한다.

**Files:**
- Modify: `sasoo/backend/api/analysis_routes.py:503,1209,1375,1501` (4개 사이트)
- Test: `sasoo/backend/api/test_analysis_routes.py` (신규 테스트 추가)

**Interfaces:**
- Consumes: `_is_error_result(text)` (api/analysis_helpers.py:100-108, analysis_routes에서 이미 사용 중 — import 확인)
- Produces: 파싱 실패 phase는 `status="error"` + `error_message` 세팅. 파이프라인은 기존대로 다음 phase로 계속 진행(전체 중단 아님).

- [ ] **Step 1: 실패 테스트 작성**

`test_analysis_routes.py`에 기존 관례(L430,447-450: `AnalysisStatus(paper_id=7, overall_status="running", phases=[], progress_pct=0.0)` + `patch("api.analysis_routes.call_interaction", ...)`)를 그대로 따라 추가. 기존 `_fake_call` fixture의 반환 dict 형태를 복사해 text만 비JSON으로 바꾼다:

```python
class ParseFailurePhaseStatusTest(unittest.IsolatedAsyncioTestCase):
    """JSON 파싱 실패 phase가 completed로 승격되지 않는다 (Phase 0 P0-2)."""

    async def test_screening_parse_failure_marks_phase_error(self):
        status = AnalysisStatus(paper_id=7, overall_status="running", phases=[], progress_pct=0.0)
        broken = {"text": "이건 JSON이 아니다 {{{", "model": MODEL_FLASH_LITE,
                  "tokens_in": 10, "tokens_out": 10, "interaction_id": None}
        with (
            patch("api.analysis_routes.call_interaction", new=AsyncMock(return_value=broken)),
            patch("api.analysis_routes._get_cached_phase_result", new=AsyncMock(return_value=None)),
            patch("api.analysis_routes._insert_analysis_result", new=AsyncMock()),
        ):
            await analysis_routes._run_screening(7, "본문 내용", status)
        phase = next(p for p in status.phases if p.phase.value == "screening")
        self.assertEqual(phase.status, "error")
        self.assertTrue(phase.error_message)
```

주의: 기존 테스트의 `_fake_call` 반환 키·`_run_screening` 내부의 phase_status 획득 방식을 먼저 읽고(파일 L405-510), 위 코드의 dict 키와 phase 조회를 실제와 일치시킨다. 재시도 1회가 있으므로 call_interaction은 2회 호출된다(AsyncMock이면 자동 처리).

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd sasoo/backend && python -m pytest api/test_analysis_routes.py::ParseFailurePhaseStatusTest -v`
Expected: FAIL — `AssertionError: 'completed' != 'error'`

- [ ] **Step 3: 4개 사이트 수정**

각 사이트(L503, L1209, L1375, L1501)의 `phase_status.status = "completed"` 한 줄을 다음으로 교체(주변 completed_at/model_used 라인은 그대로 둠):

```python
    if _is_error_result(result["text"]):
        phase_status.status = "error"
        phase_status.error_message = "LLM 응답을 구조화하지 못했습니다 (JSON 파싱 실패, 1회 재시도 포함)"
    else:
        phase_status.status = "completed"
```

캐시 히트 분기(L441,1162,1328,1454)의 `completed`는 그대로 둔다 — find_cached가 에러 행을 미스 처리하므로 히트는 항상 정상 결과다.

- [ ] **Step 4: 테스트 통과 확인 + 기존 스위트 회귀 확인**

Run: `cd sasoo/backend && python -m pytest api/test_analysis_routes.py -v`
Expected: 신규 PASS + 기존 전부 PASS (정상 JSON 경로가 completed를 유지하는지는 기존 테스트가 커버)

- [ ] **Step 5: 프론트 표시 경로 확인 (읽기만)**

`AnalysisPanel.tsx`에서 phase status가 error일 때 탭 콘텐츠가 어떻게 보이는지 확인. 스텁 JSON(`_raw`)을 본문처럼 렌더링하는 경로가 있으면 보고서에 유예 항목으로 기록(이번 범위에서 UI 수정은 하지 않음 — ProgressTracker의 error 아이콘 표시가 P0 최소선).

- [ ] **Step 6: Commit**

```bash
git add sasoo/backend/api/analysis_routes.py sasoo/backend/api/test_analysis_routes.py
git commit -m "fix(analysis): JSON 파싱 실패 phase를 completed로 표시하던 문제 — error 상태 정직화"
```

**명시적 설계 결정(보고서에 기록):** phase 하나가 error여도 `overall_status`는 기존대로 "completed"(파이프라인 완주 의미)로 둔다. phase 카드에 error가 보이므로 은폐는 아니며, "partial" 개념 도입은 프론트 enum 전파가 필요해 유예.

---

### Task 3: 캐시 키에 system_instruction·모델·버전 포함 (P1)

**문제:** visual/recipe/deep_dive/viz_plan의 캐시 키가 `prompt_fallback`뿐(L1158,1324,1442,1749)이라 연구자 프로필·설명수준·에이전트 지침(`system_instruction`)·모델을 바꿔도 옛 캐시가 재사용된다. screening 캐시 키(L441 위)는 프롬프트 원문뿐이라 모델·버전 미포함. citation만 `_CITATION_PROMPT_VERSION`(L173) 보유.

**Files:**
- Modify: `sasoo/backend/api/analysis_routes.py` — 헬퍼 추가(1곳) + 캐시 키 사이트 5곳(screening ~L441 위, visual 1158, recipe 1324, deep_dive 1442, viz_plan 1749) + screening 저장 인자(L498 `prompt` → `cache_key`)
- Test: `sasoo/backend/api/test_analysis_routes.py`

**Interfaces:**
- Produces: `_phase_cache_key(*, model: str, thinking: str, system_instruction: str, prompt: str) -> str` — `_CHAIN_CACHE_VERSION` 상수 포함 결정적 문자열.

- [ ] **Step 1: 실패 테스트 작성**

```python
class PhaseCacheKeyTest(unittest.TestCase):
    """캐시 키가 프로필(system_instruction)·모델 변경에 반응한다 (Phase 0 P1)."""

    def test_system_instruction_changes_key(self):
        base = dict(model="m1", thinking="low", prompt="P")
        k1 = analysis_routes._phase_cache_key(system_instruction="박사생 대상", **base)
        k2 = analysis_routes._phase_cache_key(system_instruction="초등학생 대상", **base)
        self.assertNotEqual(k1, k2)

    def test_model_changes_key(self):
        k1 = analysis_routes._phase_cache_key(model="m1", thinking="low", system_instruction="s", prompt="P")
        k2 = analysis_routes._phase_cache_key(model="m2", thinking="low", system_instruction="s", prompt="P")
        self.assertNotEqual(k1, k2)

    def test_deterministic(self):
        args = dict(model="m1", thinking="low", system_instruction="s", prompt="P")
        self.assertEqual(analysis_routes._phase_cache_key(**args), analysis_routes._phase_cache_key(**args))
```

- [ ] **Step 2: 테스트 실패 확인**

Run: `cd sasoo/backend && python -m pytest api/test_analysis_routes.py::PhaseCacheKeyTest -v`
Expected: FAIL — `AttributeError: _phase_cache_key`

- [ ] **Step 3: 헬퍼 구현 + 사이트 교체**

`_CITATION_PROMPT_VERSION`(L173) 근처에 추가:

```python
# Phase 0(2026-08-06): 캐시 키에 프로필·에이전트 지침(system_instruction)·모델·thinking을
# 포함한다. 값을 올리면 모든 체인 phase 캐시가 무효화된다.
_CHAIN_CACHE_VERSION = "2026-08-06"


def _phase_cache_key(*, model: str, thinking: str, system_instruction: str, prompt: str) -> str:
    return "\n\x1f\n".join((_CHAIN_CACHE_VERSION, model, thinking, system_instruction or "", prompt))
```

사이트 교체:
- visual(L1158): `cache_key = _phase_cache_key(model=_STAGE_MODELS["visual"], thinking=_STAGE_THINKING["visual"], system_instruction=system_instruction, prompt=prompt_fallback)`
- recipe(L1324)·deep_dive(L1442): 동일 패턴, 키는 `"recipe"`/`"deep_dive"`.
- viz_plan(L1749): `_STAGE_MODELS["visualization"]`, `_STAGE_THINKING["visualization"]` 사용(스테이지 맵 키가 "visualization"임에 주의, L768-770).
- screening: `_run_screening` 내부에서 call_interaction에 실제로 넘기는 model/thinking 값을 읽어 그대로 인자로 전달하고(`system_instruction`이 없으면 `""`), `cache_key` 변수를 만들어 `_get_cached_phase_result(paper_id, "screening", cache_key)`와 저장 인자(L498의 `prompt`)를 모두 `cache_key`로 통일한다. **조회 재료와 저장 재료가 같아야 다음 실행에서 히트한다** — 5개 phase 모두 `_insert_analysis_result`의 input 인자가 cache_key와 동일한지 눈으로 대조한다(visual은 현재 저장 인자도 확인해서 맞출 것).

- [ ] **Step 4: 테스트 통과 + 전체 회귀 확인**

Run: `cd sasoo/backend && python -m pytest api/test_analysis_routes.py -v` → PASS
기존 캐시 관련 테스트(L559-680 부근)가 새 키 재료로도 히트/미스 시나리오를 유지하는지 확인 — 깨지면 테스트의 키 재료를 새 헬퍼로 갱신(동작 의미는 불변).

- [ ] **Step 5: Commit**

```bash
git add sasoo/backend/api/analysis_routes.py sasoo/backend/api/test_analysis_routes.py
git commit -m "fix(analysis): 캐시 키에 프로필·에이전트 지침·모델 포함 — 프로필 변경 후 옛 캐시 재사용 차단"
```

**비용 영향(보고서에 명시):** 배포 후 기존 사용자의 체인 phase 캐시는 전부 미스가 되어 논문당 1회 재분석 비용이 다시 든다. 정확성이 우선이므로 수용.

---

### Task 4: orphan CI 파일 삭제 + AGENTS.md 현행화 (P2)

**문제:** `sasoo/.github/workflows/ci.yml`은 GitHub Actions가 실행하지 않는 죽은 파일(워크플로는 저장소 루트만 인식)인데, 잡 이름("Backend lint + test")과 달리 py_compile만 수행해 "CI가 부실하다"는 오판을 유발한다. `AGENTS.md`는 존재하지 않는 경로(`/Users/dongj/Documents/논문/sasoo`)와 낡은 테스트 커맨드(unittest discover)를 안내한다.

**Files:**
- Delete: `sasoo/.github/workflows/ci.yml` (사용자 승인 완료 항목 — 승인 없으면 이 태스크 중단)
- Modify: `AGENTS.md` (루트, 미추적 파일)

- [ ] **Step 1: ci.yml 삭제**

```bash
git rm sasoo/.github/workflows/ci.yml
```

- [ ] **Step 2: AGENTS.md 정정**

- 모든 `/Users/dongj/Documents/논문/sasoo` → `/Users/dongj/dev/논문_사수_개발중/sasoo` (L13,24,40,47,59,67,78,89,101,108,137,144 등 전체 치환, 치환 후 `grep -n "Documents/논문" AGENTS.md`로 잔존 0건 확인).
- L69-70 백엔드 테스트 커맨드: `unittest discover -s services` / `-s api` → 실제 CI와 동일한 `python -m pytest services api models`.
- 실제 CI가 루트 `.github/workflows/build-check.yml`·`release.yml` 2개이고 `sasoo/.github/workflows/ci.yml`은 제거됐음을 한 줄 추가.

- [ ] **Step 3: 검증 + Commit**

AGENTS.md는 미추적 파일이므로 add로 스테이징. `git status`로 삭제·수정만 잡혔는지 확인.

```bash
git add AGENTS.md
git commit -m "docs(dev): orphan ci.yml 제거·AGENTS.md 경로/테스트 커맨드 현행화"
```

---

### Task 5: 릴리스 문서 2종 현행화 (P2)

**문제:** `doc/macos-release.md:3-4,29,37`은 "ZIP만 배포, DMG는 범위 밖"이라 하지만 실제로는 DMG도 빌드·배포 중(sasoo/package.json:92-97 `mac.target: ["zip","dmg"]`, README.md:63,148, release.yml 업로드 목록). `sasoo/docs/03-release/release-checklist.md:50,81-88,107-113`은 "v0.7.0 macOS-only, Windows 미배포"라 하지만 v0.8.0에서 Windows 미서명 릴리스가 이미 나갔다(README.md:89).

- [ ] **Step 1: doc/macos-release.md 정정**

해당 문서를 읽고 "ZIP 단독 배포" 서술을 "ZIP + DMG 배포(둘 다 미서명)"로 정정. 미서명·미공증이라는 정직한 고지는 그대로 보존. 문서 상단에 `> 2026-08-06 현행화: v0.8.0 기준 ZIP+DMG 배포를 반영` 한 줄 추가.

- [ ] **Step 2: release-checklist.md 정정**

"macOS-only for v0.7.0" / "does not publish a Windows build" 항목을 v0.8.0 현실(Windows 미서명 배포 중, `WIN_CSC_*` 시크릿 설정 시 서명 빌드 자동 전환)에 맞게 정정. 체크리스트의 나머지 항목(서명 표현 금지 규칙 등)은 보존.

- [ ] **Step 3: Commit**

```bash
git add doc/macos-release.md sasoo/docs/03-release/release-checklist.md
git commit -m "docs(release): macOS DMG·Windows v0.8.0 배포 현실로 릴리스 문서 현행화"
```

---

### Task 6: 마케팅 문구·PRD 정정 (P1/P2)

**문제:** `docs/marketing/sns-drafts.md`의 "서버를 안 거치고 논문이 내 컴퓨터와 Google 사이에서만 오갑니다" / "your PDFs go straight from your machine to Google and nowhere else"는 기본 이미지 생성이 OpenAI로 나가는 구현(README.md:170,173)과 충돌한다(P1 — 신뢰). `PRD_Sasoo_v3.0.md`는 폐기된 옛 비전(Claude 듀얼 LLM, PaperBanana 브랜드, 4단계)을 현행처럼 서술한다(P2).

- [ ] **Step 1: sns-drafts.md 정정**

해당 문구를 사실에 맞게 수정: "논문 PDF는 내 컴퓨터에서 선택한 AI 공급사(Gemini)로만 직접 전송되고, 이미지 생성 기능을 켜면 그 설명 텍스트만 OpenAI로 추가 전송됩니다. Sasoo 자체 서버는 없습니다." (영문도 동일 취지로.) 원문은 삭제하지 않고 `~~취소선~~ → 정정문` 또는 정정 주석 블록으로 남겨 어떤 문구가 왜 바뀌었는지 추적 가능하게 한다. **이미 SNS에 게시된 글이 있다면 파일 정정만으로는 부족** — 보고서에 "게시물 원문 정정은 사용자 조치 필요"로 명시.

- [ ] **Step 2: PRD_Sasoo_v3.0.md 아카이브 고지**

문서 최상단에 다음 블록 추가(본문 무삭제):

```markdown
> **[ARCHIVED 2026-08-06]** 이 문서는 v3.0 시점(2026-02)의 초기 비전이다. 현행 구현과 다른 점:
> 분석은 4단계가 아니라 5단계(Citation Analysis 추가), LLM은 Gemini+OpenAI(Claude 미사용),
> 이미지 생성 기본 공급사는 OpenAI. 현행 제품 방향은 `docs/product-decisions.md`를 본다.
```

- [ ] **Step 3: Commit**

```bash
git add docs/marketing/sns-drafts.md PRD_Sasoo_v3.0.md
git commit -m "docs(marketing): 데이터 전송 범위 문구 정정·PRD v3.0 아카이브 고지"
```

---

### Task 7: 전체 검증 + PR 생성

- [ ] **Step 1: 백엔드 전체 스위트**

Run: `cd sasoo/backend && python -m pytest services api models`
Expected: 전부 PASS (실행 못 한 테스트가 있으면 skip 사유를 보고서에 그대로 기록)

- [ ] **Step 2: 프론트 전체 검증**

Run: `pnpm --dir=sasoo/frontend test && cd sasoo/frontend && npx tsc --noEmit && pnpm lint`
Expected: 전부 PASS

- [ ] **Step 3: PR 생성**

```bash
git log origin/main..main   # 로컬 main 오염 확인 — 커밋이 있으면 중단하고 보고
git push -u origin fix/phase0-truth-restoration
gh pr create --title "fix: Phase 0 진실 회복 — 거짓 성공 표시 2건·캐시 오염·문서 정정" --body "..."
```

PR 본문에 포함: 변경 요약(P0 2건, P1 1건, 문서 3건), 캐시 전면 무효화로 인한 1회 재분석 비용 고지, 수동 검증 절차(분석 시작 실패 toast, 파싱 실패 phase 표시), 미검증 항목 명시. 병합은 사용자가 수행.

---

## Self-Review 체크 결과

- Spec coverage: DEC-005의 Phase 0 범위(P0 2건, P1 캐시, 문서·마케팅 정정) ↔ Task 1-6 대응 확인. 12/12 프로덕션 재측정은 API 비용이 들어 Phase 0 밖(보고서에 후속 권고로만).
- Placeholder: 코드 태스크(1-3)는 실제 코드 포함. 문서 태스크(4-6)는 대상 문구 원문 인용 + 정정문 제시 — 실행자가 파일을 읽고 적용.
- Type consistency: `Promise<boolean>` 계약이 Task 1의 3개 파일에서 일관. `_phase_cache_key` 시그니처가 Step 1 테스트와 Step 3 구현에서 일치.
- 알려진 리스크: (1) Task 3에서 기존 캐시 테스트가 키 재료 변경으로 깨질 수 있음 — Step 4에 갱신 지침 포함. (2) Task 2의 테스트는 기존 fixture 형태에 맞춰 조정 필요함을 명시. (3) 프론트 hook 자동 테스트 불가(node 환경) — 수동 검증으로 대체하고 명시.
