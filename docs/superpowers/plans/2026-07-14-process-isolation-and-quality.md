# 분석 프로세스 분리 + 자동 재개 & 품질 미세 보정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (Part 1) 5단계 분석 파이프라인의 인용 병합·게이트·캐시 키를 미세 보정한다(ref_id 정규화, section 라벨 주입, confidence 방어, PROMPT_VERSION). (Part 2) 분석 실행을 서버 프로세스 밖 **디태치드 서브프로세스**로 분리하고, 서버/앱 재기동 시 고아 분석을 **자동 재개**한다(세대 fencing + `analysis_runs` 리스 테이블 + 주기적 리컨실러).

**Architecture:**
- Part 1: 기존 `_run_citation`/`_screening_gate_decision`에 표적 편집만. 파이프라인 골격 불변.
- Part 2: 서버(FastAPI)가 유일한 스포너다. `/run`과 리컨실러가 신규 `analysis_runs` 테이블에 대해 **단일 `UPDATE...RETURNING` claim** 으로 원자적으로 슬롯을 잡고, 같은 번들(`sasoo-backend`)을 `--analyze-paper N --run-generation G` argv로 디태치 스폰한다. 워커는 `_run_full_analysis`(무수정)를 그대로 실행하고, **전용 DB 연결**을 쓰는 사이드카 리포터/취소-브리지가 공유 `status` 객체를 `analysis_runs`로 흘려보낸다. 모든 워커 쓰기는 `WHERE paper_id=? AND generation=?`로 fence되어 재스폰 후 되살아난 구 워커의 split-brain을 차단한다. `/status`는 기존 `analysis_results` builder를 유지하고 runs의 overall/current_phase/progress만 overlay하며, `queued`는 `running`으로 매핑해 프론트 무수정.
- 확정 스파이크(2026-07-14, backend venv, sqlite 3.53.3): aiosqlite에서 cap predicate를 포함한 단일 `UPDATE...RETURNING`이 동작하고 generation을 반환한다. `BEGIN IMMEDIATE` 없이 이 단일 조건부 UPDATE로 claim을 확정한다.

**Tech Stack:** Python 3 / FastAPI / aiosqlite(SQLite WAL) / subprocess(디태치) / PyInstaller(onedir 번들, entry=`main.py`) / Electron(python-manager.ts) / unittest(IsolatedAsyncioTestCase) + pytest 러너

## 설계 근거

- Part 1 소스: `~/.claude/jobs/2a04705e/tmp/options-3-quality.md`(옵션 A + C 최소 계측 하이브리드).
- Part 2 소스: `~/.claude/jobs/2a04705e/tmp/design-process-isolation-v2.md`(Codex 독립 검토 반영: 세대 fencing / papers-runs terminal 우선순위 / claim 원자성 / cancel-wins / 전용 연결 / PYINSTALLER_RESET_ENVIRONMENT / status overlay / queued→running).

## Global Constraints

- **기존 테스트 전부 그린 유지.** Part 2는 `SASOO_ANALYSIS_SUBPROCESS` 환경변수 플래그로 게이트한다. 플래그 미설정(테스트·직접 실행 기본) 시 `/run`은 기존 `background_tasks.add_task(_run_full_analysis, ...)` 경로를 **그대로** 탄다(유지+추가). python-manager.ts가 실런타임에서만 플래그를 켠다.
- **병렬 세션 작업 중**: `git add -A`, `git add -u`, `git commit -a` 금지. 각 Task 커밋은 해당 Task가 실제로 수정한 파일만 명시적으로 `git add` 한다.
- **uvicorn --reload 서버가 가동 중**이라 백엔드 파일 편집 시 리로드가 발생한다(무해). 단 구현 중 **실제 분석 실행(`/run` 호출)은 금지** — 과금/체인 상태를 오염시킨다. 검증은 pytest와 T9 수동 체크리스트로 한다.
- **무수정 원칙**: `_run_full_analysis`, 5개 phase 함수(`_run_screening`/`_run_citation`은 Part 1에서만 표적 편집, 그 외 `_run_visual`/`_run_recipe`/`_run_deep_dive`/`_run_visualizations` 본문 로직), `services/concurrency.py`는 Part 2에서 손대지 않는다(실행 위치만 이동).
- **불변 계약**: temperature 미설정, 모델 문자열 실효값(스크리닝 `gemini-3.1-flash-lite`, 나머지 `gemini-3.5-flash`), 결과 JSON 기존 key는 추가만 허용.
- **동시 편수 진실원**: 기존 설정 `max_concurrent_analyses`(기본 3, `api/settings.py:44,250`). 하드코딩 금지.
- 커밋 메시지는 저장소 관례 + 트레일러 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- 테스트 실행: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest <파일> -q`. Part 1 테스트는 `api/test_analysis_routes.py`의 `AnalysisRouteSemanticTests`(:242)에 추가. Part 2 신규 파일 테스트는 실제 aiosqlite + tempfile DB를 쓴다(스텁 아님).

---
---

# PART 1 — 품질 미세 보정

---

### Task 1: 인용 병합 ref_id 정규화 + 매치 실패 warning (계측 겸용)

현행 병합 루프(`_run_citation`, `analysis_routes.py:602-610`)는 `tc.get("ref_id") == ref_id`로 **정확 문자열 비교**한다. LLM이 `"[1]"`을 `"1"`이나 `" [1] "`로 돌려주면 무음 드랍되어 citation_role/why_cited/evidence_context가 top_cited에 반영되지 않는다. 대괄호·공백을 제거한 정규화 비교로 바꾸고, 매치 실패 시 warning을 남겨 드랍 빈도를 계측한다.

**Files:**
- Modify: `sasoo/backend/api/analysis_routes.py` (`_run_citation` 병합 루프 602-610, 근처에 `_norm_ref_id` 헬퍼 추가)
- Test: `sasoo/backend/api/test_analysis_routes.py` (`AnalysisRouteSemanticTests`에 추가)

**Interfaces:**
- Consumes: 없음
- Produces: `analysis_routes._norm_ref_id(raw: object) -> str` (대괄호·공백·선행 'ref'/'#' 제거 후 소문자). 병합 루프가 이를 통해 비교. LLM 출력/결과 JSON key는 불변.

- [ ] **Step 1: 실패하는 테스트 작성** — `AnalysisRouteSemanticTests` 클래스 안에 추가:

```python
    def test_norm_ref_id_normalizes_bracket_and_space(self):
        self.assertEqual(analysis_routes._norm_ref_id("[1]"), analysis_routes._norm_ref_id(" 1 "))
        self.assertEqual(analysis_routes._norm_ref_id("[12]"), analysis_routes._norm_ref_id("12"))
        self.assertNotEqual(analysis_routes._norm_ref_id("1"), analysis_routes._norm_ref_id("2"))

    async def test_citation_merge_tolerates_ref_id_format_drift(self):
        status = AnalysisStatus(paper_id=7, overall_status="running", phases=[], progress_pct=0.0)

        async def _fake_call(prompt, **kwargs):
            # LLM이 대괄호 없는 "1"로 돌려줘도 top_cited("[1]")에 병합돼야 한다
            return {
                "text": '{"ref_analyses":[{"ref_id":"1","citation_role":"foundational",'
                        '"why_cited":"기반 이론.","evidence_context":"이 방법은 [1]을 따른다"}],'
                        '"summary":"요약","citation_balance":"balanced","key_influences":["[1]"],'
                        '"limitations":"상위 10개 기반"}',
                "model": "gemini-3.5-flash", "tokens_in": 10, "tokens_out": 10, "interaction_id": None,
            }

        local_result = {
            "total_references": 5, "citation_style": "numbered",
            "self_citation_count": 0, "self_citation_ratio": 0.0,
            "top_cited": [{"ref_id": "[1]", "authors": "Kim", "year": 2024, "title": "T",
                           "journal": "J", "cite_count": 3,
                           "cite_contexts": [{"sentence": "이 방법은 [1]을 따른다", "section": "Methods"}]}],
        }
        fake_analysis = types.SimpleNamespace(to_dict=lambda: local_result)

        with (
            patch("services.citation_analyzer.analyze_citations", return_value=fake_analysis),
            patch("api.analysis_routes._get_cached_phase_result", new=AsyncMock(return_value=None)),
            patch("api.analysis_routes.call_interaction", new=_fake_call),
            patch("api.analysis_routes._insert_analysis_result", new=AsyncMock()),
        ):
            result = await analysis_routes._run_citation(
                7, sections={}, citation_body="본문", citation_references="[1] Kim 2024",
                paper_authors="Kim", status=status,
            )

        merged = json.loads(result["text"])
        self.assertEqual(merged["top_cited"][0]["citation_role"], "foundational")
        self.assertEqual(merged["top_cited"][0]["evidence_context"], "이 방법은 [1]을 따른다")
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest api/test_analysis_routes.py -q -k "norm_ref_id or ref_id_format_drift"`
Expected: FAIL (`_norm_ref_id` AttributeError; drift 테스트는 "1" != "[1]"로 role 미병합)

- [ ] **Step 3: 구현**

`analysis_routes.py`의 `_run_citation` 정의 바로 위(503행 직전)에 헬퍼 추가:

```python
def _norm_ref_id(raw: object) -> str:
    """ref_id를 병합 비교용으로 정규화한다(대괄호·공백·'ref'/'#' 선행 표기 제거, 소문자)."""
    s = str(raw or "").strip().lower()
    for ch in ("[", "]", "(", ")", "#"):
        s = s.replace(ch, "")
    if s.startswith("ref"):
        s = s[3:]
    return s.strip()
```

`analysis_routes.py:602-610`의 병합 루프를 교체:

```python
            # Merge LLM analysis into local_result (ref_id 포맷 드리프트 허용)
            ref_analyses = llm_data.get("ref_analyses", [])
            top_cited = local_result.get("top_cited", [])
            top_by_norm = {_norm_ref_id(tc.get("ref_id")): tc for tc in top_cited}
            for ra in ref_analyses:
                norm = _norm_ref_id(ra.get("ref_id", ""))
                tc = top_by_norm.get(norm)
                if tc is None:
                    logger.warning(
                        "citation merge drop: ref_id=%r (norm=%r) not in top_cited for paper %s",
                        ra.get("ref_id"), norm, paper_id,
                    )
                    continue
                tc["citation_role"] = ra.get("citation_role", "")
                tc["why_cited"] = ra.get("why_cited", "")
                tc["evidence_context"] = ra.get("evidence_context", "")
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest api/test_analysis_routes.py -q`
Expected: PASS (63건 + 신규 2건)

- [ ] **Step 5: 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중
git add sasoo/backend/api/analysis_routes.py sasoo/backend/api/test_analysis_routes.py
git commit -m "fix(analysis): 인용 병합 ref_id 정규화 — 대괄호·공백 드리프트 허용, 매치 실패 warning 계측

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: cite_contexts에 section 라벨 주입 + 문맥 문장 3→5개

현행 top_refs_text 조립(`analysis_routes.py:535-544`)은 `c.get("sentence")`만 쓰고 파서가 이미 채운 `section` 라벨을 버린다. 또 `contexts[:3]`으로 문맥을 3개만 본다. `citation_analyzer`의 `to_dict`는 `cite_contexts`를 `{"sentence","section"}`로 최대 5개까지 내보낸다(`services/citation_analyzer.py:85-87`). 섹션 라벨을 프롬프트에 실어 role 분류 근거를 강화하고, 문맥을 5개로 늘린다.

**Files:**
- Modify: `sasoo/backend/api/analysis_routes.py:535-544` (top_refs_text 조립)
- Test: `sasoo/backend/api/test_analysis_routes.py`

**Interfaces:**
- Consumes: `analyze_citations(...).to_dict()["top_cited"][].cite_contexts[] = {"sentence": str, "section": str}` (기존 계약, `citation_analyzer.py:85-87`)
- Produces: 없음(프롬프트 텍스트만 변경). 결과 key 불변.

- [ ] **Step 1: 실패하는 테스트 작성** — `AnalysisRouteSemanticTests` 클래스 안에 추가:

```python
    async def test_citation_prompt_includes_section_labels_and_five_contexts(self):
        status = AnalysisStatus(paper_id=7, overall_status="running", phases=[], progress_pct=0.0)
        captured = {}

        async def _fake_call(prompt, **kwargs):
            captured["prompt"] = prompt
            return {
                "text": '{"ref_analyses":[],"summary":"s","citation_balance":"balanced",'
                        '"key_influences":[],"limitations":"l"}',
                "model": "gemini-3.5-flash", "tokens_in": 1, "tokens_out": 1, "interaction_id": None,
            }

        local_result = {
            "total_references": 5, "citation_style": "numbered",
            "self_citation_count": 0, "self_citation_ratio": 0.0,
            "top_cited": [{
                "ref_id": "[1]", "authors": "Kim", "year": 2024, "title": "T", "journal": "J",
                "cite_count": 6,
                "cite_contexts": [
                    {"sentence": "문장1", "section": "Introduction"},
                    {"sentence": "문장2", "section": "Methods"},
                    {"sentence": "문장3", "section": "Results"},
                    {"sentence": "문장4", "section": "Discussion"},
                    {"sentence": "문장5", "section": "Conclusion"},
                ],
            }],
        }
        fake_analysis = types.SimpleNamespace(to_dict=lambda: local_result)

        with (
            patch("services.citation_analyzer.analyze_citations", return_value=fake_analysis),
            patch("api.analysis_routes._get_cached_phase_result", new=AsyncMock(return_value=None)),
            patch("api.analysis_routes.call_interaction", new=_fake_call),
            patch("api.analysis_routes._insert_analysis_result", new=AsyncMock()),
        ):
            await analysis_routes._run_citation(
                7, sections={}, citation_body="본문", citation_references="[1] Kim 2024",
                paper_authors="Kim", status=status,
            )

        prompt = captured["prompt"]
        self.assertIn("Introduction", prompt)   # section 라벨 주입
        self.assertIn("Conclusion", prompt)      # 5번째 문맥까지 포함
        self.assertIn("문장5", prompt)
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest api/test_analysis_routes.py -q -k section_labels_and_five`
Expected: FAIL (`문장5`/`Conclusion`이 프롬프트에 없음 — `[:3]` + section 미주입)

- [ ] **Step 3: 구현**

`analysis_routes.py:535-544`의 top_refs_text 조립 루프를 교체:

```python
        top_refs_text = ""
        for i, ref in enumerate(top_refs, 1):
            contexts = ref.get("cite_contexts", [])
            ctx_parts = []
            for c in contexts[:5]:
                sentence = (c.get("sentence") or "")[:300]
                sec = (c.get("section") or "").strip()
                ctx_parts.append(f"[{sec or '위치미상'}] {sentence}" if sentence else "")
            ctx_str = "; ".join(p for p in ctx_parts if p)
            top_refs_text += (
                f"{i}. {ref.get('ref_id', '')} {ref.get('authors', '')} "
                f"({ref.get('year', '?')}): \"{ref.get('title', '')}\" "
                f"[{ref.get('journal', '')}] — 인용 {ref.get('cite_count', 0)}회\n"
                f"   인용 맥락: {ctx_str}\n\n"
            )
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest api/test_analysis_routes.py -q`
Expected: PASS

- [ ] **Step 5: 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중
git add sasoo/backend/api/analysis_routes.py sasoo/backend/api/test_analysis_routes.py
git commit -m "feat(analysis): 인용 프롬프트에 section 라벨 주입 + 문맥 문장 3→5개 — role 분류 근거 강화

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: 게이트 confidence 방어 + PROMPT_VERSION 도입(citation input_hash부터)

현행 `_screening_gate_decision`(`analysis_routes.py:138-206`)은 `applicable=False`면 confidence를 보지 않고 바로 스킵한다 — 확신이 낮은 오판정도 그대로 phase를 차단한다. `applicable=False`여도 `confidence < _GATE_CONFIDENCE_FLOOR`(0.6, 잠정)면 스킵하지 않도록 방어한다. 또 현재 citation 캐시 키(`input_hash_source`, `analysis_routes.py:636-648`)는 top_refs가 있을 때 `llm_prompt` **전문**을 해시한다 — 프롬프트 문구를 1자만 고쳐도 전면 재과금이다. `PROMPT_VERSION` 상수 + 안정 콘텐츠(프롬프트 문구 제외)로 캐시 키를 재구성해, 문구 변경이 재과금을 유발하지 않게 한다. 기존 캐시 1회 무효화는 허용된 동작이다.

**Files:**
- Modify: `sasoo/backend/api/analysis_routes.py` (`_GATE_CONFIDENCE_FLOOR`·`PROMPT_VERSION` 상수 추가, `_screening_gate_decision` 194-198 방어, `_run_citation` input_hash_source 636-648 재구성)
- Test: `sasoo/backend/api/test_analysis_routes.py`

**Interfaces:**
- Consumes: 없음
- Produces: `analysis_routes._GATE_CONFIDENCE_FLOOR: float = 0.6`, `analysis_routes.PROMPT_VERSION: str = "2026-07-14"`, `analysis_routes._citation_cache_key(local_result, citation_body) -> str`(안정 콘텐츠+버전). `_screening_gate_decision` 시그니처 불변, 반환 사유 문자열에 변화 없음.

- [ ] **Step 1: 실패하는 테스트 작성** — `AnalysisRouteSemanticTests` 클래스 안에 추가:

```python
    def test_gate_low_confidence_overrides_applicable_false(self):
        # deep_dive_applicable=false 이지만 confidence가 floor 미만이면 스킵하지 않는다
        payload = ('{"relevance_score":0.8,"domain":"optics","key_topics":["광학"],'
                   '"is_experimental":true,"recipe_applicable":true,"deep_dive_applicable":false,'
                   '"confidence":0.4}')
        skip_deep, reason = analysis_routes._screening_gate_decision(payload, phase="deep_dive")
        self.assertFalse(skip_deep)

    def test_gate_high_confidence_applicable_false_still_skips(self):
        payload = ('{"relevance_score":0.8,"domain":"optics","key_topics":["광학"],'
                   '"is_experimental":true,"recipe_applicable":false,"deep_dive_applicable":true,'
                   '"confidence":0.9}')
        skip_recipe, reason = analysis_routes._screening_gate_decision(payload, phase="recipe")
        self.assertTrue(skip_recipe)
        self.assertEqual(reason, "not_applicable_recipe")

    def test_citation_cache_key_ignores_prompt_wording_but_tracks_version(self):
        local_result = {"total_references": 12, "citation_style": "numbered",
                        "self_citation_count": 1, "self_citation_ratio": 0.08,
                        "top_cited": [{"ref_id": "[1]", "cite_count": 3,
                                       "cite_contexts": [{"sentence": "s", "section": "Methods"}]}]}
        key = analysis_routes._citation_cache_key(local_result, "본문 발췌")
        self.assertIn(analysis_routes.PROMPT_VERSION, key)
        # 본문/통계가 같으면 동일 키(프롬프트 문구는 키에 안 들어감)
        self.assertEqual(key, analysis_routes._citation_cache_key(local_result, "본문 발췌"))
        # 버전이 바뀌면 키가 달라진다(재과금 1회 허용 지점)
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest api/test_analysis_routes.py -q -k "low_confidence_overrides or high_confidence_applicable or citation_cache_key"`
Expected: FAIL (`applicable=False`가 confidence 무시하고 스킵; `_citation_cache_key` AttributeError)

- [ ] **Step 3: 구현**

`analysis_routes.py`의 `_screening_gate_decision` 정의 위(약 137행, 헬퍼 영역)에 모듈 상수 추가:

```python
# 게이트가 applicable=False로 스킵하기 전 요구하는 최소 확신도(잠정값 0.6 — e2e 분포로 재조정).
_GATE_CONFIDENCE_FLOOR = 0.6

# 프롬프트 문구가 아닌 "안정 콘텐츠 + 이 버전"으로 캐시 키를 구성한다.
# 문구를 바꿔도 재과금이 없고, 계약이 실제로 바뀔 때만 이 값을 올려 1회 무효화한다.
PROMPT_VERSION = "2026-07-14"
```

`analysis_routes.py:194-198`의 applicable 분기를 confidence 방어로 교체 (기존):

```python
    applicable = payload.get(f"{phase}_applicable")
    if applicable is False:
        return (True, f"not_applicable_{phase}")
    if applicable is True:
        return (False, "")
```

교체 후:

```python
    applicable = payload.get(f"{phase}_applicable")
    if applicable is False:
        # 확신이 낮은 오판정으로 phase를 차단하지 않는다: confidence가 floor 미만이면 실행.
        try:
            confidence = float(payload.get("confidence"))
        except (TypeError, ValueError):
            confidence = 1.0  # confidence 미제공(레거시)은 플래그를 신뢰
        if confidence < _GATE_CONFIDENCE_FLOOR:
            return (False, "")
        return (True, f"not_applicable_{phase}")
    if applicable is True:
        return (False, "")
```

`analysis_routes.py`의 `_run_citation` 정의 위(`_norm_ref_id` 근처)에 캐시 키 헬퍼 추가:

```python
def _citation_cache_key(local_result: dict, citation_body: str) -> str:
    """인용 phase 캐시 키: 프롬프트 문구가 아닌 안정 콘텐츠 + PROMPT_VERSION.

    문구를 고쳐도 재과금이 없고, 계약이 실제로 바뀔 때 PROMPT_VERSION을 올려 1회 무효화한다."""
    top = [
        {
            "ref_id": r.get("ref_id"),
            "cite_count": r.get("cite_count"),
            "contexts": [
                {"s": (c.get("sentence") or "")[:300], "sec": c.get("section") or ""}
                for c in (r.get("cite_contexts") or [])[:5]
            ],
        }
        for r in local_result.get("top_cited", [])[:10]
    ]
    payload = {
        "v": PROMPT_VERSION,
        "phase": "citation",
        "total_references": local_result.get("total_references", 0),
        "citation_style": local_result.get("citation_style", ""),
        "self_citation_count": local_result.get("self_citation_count", 0),
        "top": top,
        "body": citation_body[:3000],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
```

`analysis_routes.py`의 `_run_citation` 안에서 캐시/저장 키를 이 헬퍼로 통일한다. 두 지점을 교체:

(a) top_refs 있을 때의 캐시 조회(571행) 앞에 키를 계산하고, `llm_prompt` 대신 이 키를 캐시·저장에 쓴다. 구체적으로 `cached = await _get_cached_phase_result(paper_id, "citation", llm_prompt)`(571행)를 다음으로:

```python
        cache_key = _citation_cache_key(local_result, citation_body)
        cached = await _get_cached_phase_result(paper_id, "citation", cache_key)
```

(b) `input_hash_source`(636-648행)를 교체:

```python
    input_hash_source = (
        _citation_cache_key(local_result, citation_body)
        if top_refs
        else json.dumps(
            {
                "v": PROMPT_VERSION,
                "phase": "citation",
                "citation_body": citation_body,
                "citation_references": citation_references,
                "paper_authors": paper_authors,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
```

> 주의: top_refs 경로에서 `cache_key`와 `input_hash_source`가 동일 문자열이어야 캐시 조회/저장 키가 일치한다. 둘 다 `_citation_cache_key(local_result, citation_body)`를 쓰므로 일치한다. `citation_body` 지역변수가 (a) 지점에서 접근 가능한지 확인한다(함수 인자이므로 가능).

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest api/test_analysis_routes.py -q`
Expected: PASS — 기존 게이트 테스트(`test_screening_gate_uses_phase_applicable_flags` 등)는 confidence 미제공/floor 이상이라 스킵 동작 유지.

- [ ] **Step 5: 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중
git add sasoo/backend/api/analysis_routes.py sasoo/backend/api/test_analysis_routes.py
git commit -m "feat(analysis): 게이트 confidence 방어(<0.6 시 스킵 보류) + PROMPT_VERSION 캐시 키 — citation 재과금 무효화

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---
---

# PART 2 — 프로세스 분리 + 자동 재개

> 이하 Task는 신규 파일 중심이라 `old_string` 충돌이 없다. 편집 대상(`database.py`/`main.py`/`analysis_routes.py`/`python-manager.ts`)만 정확한 앵커를 사용한다.

---

### Task 4 (T1): DB 계층 — `analysis_runs` 테이블 + `claim_next`(RETURNING) + busy_timeout

`analysis_runs`(paper_id PK + generation fence + heartbeat 리스)를 신설하고, 프로세스 간 조율 primitive를 모두 순수 함수(연결 주입)로 만든다. cap predicate를 포함한 단일 `UPDATE...RETURNING`으로 claim을 원자화한다(스파이크 확정).

**Files:**
- Create: `sasoo/backend/models/analysis_runs.py`
- Modify: `sasoo/backend/models/database.py` (init_db에 busy_timeout + DDL, `connect_worker_db`/`open_side_connection` 추가)
- Create: `sasoo/backend/models/test_analysis_runs.py`

**Interfaces:**
- Produces (모두 첫 인자 `conn: aiosqlite.Connection`, 시간은 iso 문자열 인자로 주입 — 테스트 결정론):
  - `ANALYSIS_RUNS_DDL: str`
  - `utcnow_iso() -> str`
  - `upsert_queued(conn, paper_id: int, now: str) -> None` — 신규 /run: 큐 삽입(있으면 status='queued', attempts=0, cancel=0으로 리셋, generation 유지)
  - `claim_next(conn, cap: int, now: str, fresh_cut: str, backoff_cut: str, max_attempts: int) -> Optional[tuple[int,int]]` — (paper_id, new_generation) 또는 None
  - `set_pid(conn, paper_id: int, generation: int, pid: int) -> None`
  - `fenced_heartbeat(conn, paper_id: int, generation: int, status: str, current_phase: Optional[str], progress_pct: float, now: str) -> int` — rowcount(0이면 fence 실패)
  - `finalize_run(conn, paper_id: int, generation: int, terminal_status: str, now: str, error_message: Optional[str]=None) -> int`
  - `request_cancel(conn, paper_id: int) -> int`
  - `get_run(conn, paper_id: int) -> Optional[dict]`
  - `reconcile_stale(conn, stale_cut: str, max_attempts: int, now: str) -> None`
  - `seed_legacy(conn, now: str) -> int`
  - `mark_over_attempts_error(conn, max_attempts: int) -> list[int]` — attempts 초과 queued를 error로, 대상 paper_id 목록
  - `database.connect_worker_db() -> aiosqlite.Connection`(전역 `_db_connection` 세팅, 마이그레이션 없음), `database.open_side_connection() -> aiosqlite.Connection`(독립 연결)

- [ ] **Step 1: 실패하는 테스트 작성** — `sasoo/backend/models/test_analysis_runs.py` 신규:

```python
import asyncio
import os
import tempfile
import unittest

import aiosqlite

from models import analysis_runs as ar


class AnalysisRunsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.conn = await aiosqlite.connect(self.tmp.name)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.execute("PRAGMA busy_timeout=5000")
        await self.conn.executescript(
            "CREATE TABLE papers (id INTEGER PRIMARY KEY, status TEXT);"
        )
        await self.conn.executescript(ar.ANALYSIS_RUNS_DDL)
        await self.conn.commit()

    async def asyncTearDown(self):
        await self.conn.close()
        os.unlink(self.tmp.name)

    async def _paper(self, pid, status="analyzing"):
        await self.conn.execute("INSERT INTO papers (id, status) VALUES (?, ?)", (pid, status))
        await self.conn.commit()

    async def test_claim_next_returns_generation_and_is_atomic(self):
        now = "2026-07-14T00:00:00+00:00"
        await self._paper(1)
        await ar.upsert_queued(self.conn, 1, now)
        claimed = await ar.claim_next(self.conn, cap=3, now=now, fresh_cut="2026-07-13T23:59:00+00:00",
                                      backoff_cut="2026-07-13T23:59:00+00:00", max_attempts=3)
        self.assertEqual(claimed, (1, 1))                      # generation 0 -> 1
        run = await ar.get_run(self.conn, 1)
        self.assertEqual(run["status"], "running")
        self.assertEqual(run["heartbeat_at"], now)             # claim 시 즉시 기록(영구 running 방지)
        # 두 번째 claim은 같은 논문을 다시 잡지 않는다(더 이상 queued 아님)
        self.assertIsNone(await ar.claim_next(self.conn, 3, now, "2026-07-13T23:59:00+00:00",
                                              "2026-07-13T23:59:00+00:00", 3))

    async def test_claim_next_respects_cap(self):
        now = "2026-07-14T00:00:00+00:00"; fresh = "2026-07-13T23:59:00+00:00"
        for pid in (1, 2):
            await self._paper(pid); await ar.upsert_queued(self.conn, pid, now)
        first = await ar.claim_next(self.conn, cap=1, now=now, fresh_cut=fresh, backoff_cut=fresh, max_attempts=3)
        self.assertEqual(first[0], 1)
        # cap=1이고 이미 running 1개 → 더 못 잡음
        self.assertIsNone(await ar.claim_next(self.conn, 1, now, fresh, fresh, 3))

    async def test_fenced_heartbeat_rejects_stale_generation(self):
        now = "2026-07-14T00:00:00+00:00"; fresh = "2026-07-13T23:59:00+00:00"
        await self._paper(1); await ar.upsert_queued(self.conn, 1, now)
        pid, gen = await ar.claim_next(self.conn, 3, now, fresh, fresh, 3)   # gen=1
        self.assertEqual(await ar.fenced_heartbeat(self.conn, 1, gen, "running", "screening", 16.0, now), 1)
        # 구 워커(gen-1)는 fence 실패
        self.assertEqual(await ar.fenced_heartbeat(self.conn, 1, gen - 1, "running", "x", 50.0, now), 0)

    async def test_reconcile_prefers_papers_terminal_over_requeue(self):
        now = "2026-07-14T00:10:00+00:00"; stale = "2026-07-14T00:09:00+00:00"
        old = "2026-07-14T00:00:00+00:00"; fresh0 = "2026-07-13T23:59:00+00:00"
        await self._paper(1, status="completed")               # papers는 이미 완료
        await ar.upsert_queued(self.conn, 1, old)
        await ar.claim_next(self.conn, 3, old, fresh0, fresh0, 3)  # running, heartbeat=old(→stale)
        await ar.reconcile_stale(self.conn, stale_cut=stale, max_attempts=3, now=now)
        run = await ar.get_run(self.conn, 1)
        self.assertEqual(run["status"], "completed")           # requeue 아님(papers-terminal 우선)

    async def test_reconcile_cancel_wins_over_requeue(self):
        now = "2026-07-14T00:10:00+00:00"; stale = "2026-07-14T00:09:00+00:00"
        old = "2026-07-14T00:00:00+00:00"; fresh0 = "2026-07-13T23:59:00+00:00"
        await self._paper(1, status="analyzing")
        await ar.upsert_queued(self.conn, 1, old)
        await ar.claim_next(self.conn, 3, old, fresh0, fresh0, 3)
        await ar.request_cancel(self.conn, 1)
        await ar.reconcile_stale(self.conn, stale_cut=stale, max_attempts=3, now=now)
        self.assertEqual((await ar.get_run(self.conn, 1))["status"], "cancelled")

    async def test_seed_legacy_creates_queued_for_orphan_analyzing(self):
        now = "2026-07-14T00:00:00+00:00"
        await self._paper(1, status="analyzing")               # runs 행 없음(레거시)
        n = await ar.seed_legacy(self.conn, now)
        self.assertEqual(n, 1)
        self.assertEqual((await ar.get_run(self.conn, 1))["status"], "queued")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest models/test_analysis_runs.py -q`
Expected: FAIL (`models.analysis_runs` ModuleNotFoundError)

- [ ] **Step 3: 구현**

`sasoo/backend/models/analysis_runs.py` 신규:

```python
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
```

`sasoo/backend/models/database.py` 편집 — (a) `init_db`의 WAL 설정 직후(374행 `PRAGMA journal_mode=WAL` 아래)에 busy_timeout 추가:

```python
    # Enable WAL mode for better concurrent read performance
    await _db_connection.execute("PRAGMA journal_mode=WAL")
    # 다중 프로세스(서버 + 디태치 워커) 쓰기 경합을 즉시 실패 대신 대기로 흡수
    await _db_connection.execute("PRAGMA busy_timeout=5000")
    # Enable foreign key enforcement
    await _db_connection.execute("PRAGMA foreign_keys=ON")
```

(b) `init_db`의 마이그레이션 블록 끝(495행 `pass  # column already exists` 뒤)에 analysis_runs DDL 추가:

```python
    # analysis_runs: 디태치 워커 조율 테이블(프로세스 분리 + 자동 재개)
    from models.analysis_runs import ANALYSIS_RUNS_DDL
    try:
        await _db_connection.executescript(ANALYSIS_RUNS_DDL)
        await _db_connection.commit()
    except Exception:
        pass
```

(c) `database.py`의 `close_db` 아래에 워커용 연결 헬퍼 추가:

```python
async def connect_worker_db() -> aiosqlite.Connection:
    """워커 프로세스의 전역 연결을 연다(마이그레이션 미실행 — 서버 startup이 스키마 선행 보장)."""
    global _db_connection
    conn = await aiosqlite.connect(str(DB_PATH))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA busy_timeout=5000")
    await conn.execute("PRAGMA foreign_keys=ON")
    _db_connection = conn
    return conn


async def open_side_connection() -> aiosqlite.Connection:
    """워커 사이드카(리포터/취소-브리지) 전용 독립 연결. 전역 연결의 트랜잭션과 격리."""
    conn = await aiosqlite.connect(str(DB_PATH))
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA busy_timeout=5000")
    return conn
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest models/test_analysis_runs.py api/test_analysis_routes.py -q`
Expected: PASS (신규 6건 + 기존 전체)

- [ ] **Step 5: 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중
git add sasoo/backend/models/analysis_runs.py sasoo/backend/models/database.py sasoo/backend/models/test_analysis_runs.py
git commit -m "feat(analysis): analysis_runs 테이블 + claim_next(RETURNING) + busy_timeout — 프로세스 분리 조율 기반

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5 (T2): 워커 엔트리 + 전용연결 사이드카 + bootstrap 추출

같은 번들을 `--analyze-paper N --run-generation G`로 재실행하면 `_run_full_analysis`(무수정)를 실행하는 워커가 된다. 공유 `status`(`_running_analyses[paper_id]`)를 전용 연결로 `analysis_runs`에 flush하고, cancel_requested를 폴링해 `_cancel_events`를 set하는 사이드카를 붙인다. fence 실패(재스폰) 시 self-abort.

**Files:**
- Create: `sasoo/backend/services/analysis_worker.py`
- Modify: `sasoo/backend/main.py` (lifespan startup을 `bootstrap_runtime(worker=False)`로 추출, `__main__`에 argparse 분기)
- Create: `sasoo/backend/services/test_analysis_worker.py`

**Interfaces:**
- Consumes: T1의 `analysis_runs.*`, `database.connect_worker_db`/`open_side_connection`, 기존 `api.analysis_state._running_analyses`/`_cancel_events`, `api.analysis_routes._run_full_analysis`(무수정)
- Produces:
  - `main.bootstrap_runtime(worker: bool = False) -> None` — init_db(서버)/connect_worker_db(워커) + API키 로드 + pdf engine + agents. worker=True면 setup_logging(공유 파일 핸들)·stuck recovery·리컨실러 미실행.
  - `analysis_worker.run_analysis_worker(paper_id: int, generation: int) -> int` — exit code(0 정상, 75 self-abort)
  - `analysis_worker.REPORT_INTERVAL_S = 1.5`, `analysis_worker.SIDE_FAIL_ABORT_S = 20.0`

- [ ] **Step 1: 실패하는 테스트 작성** — `sasoo/backend/services/test_analysis_worker.py` 신규:

```python
import asyncio
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import aiosqlite

from models import analysis_runs as ar


class ReporterBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); self.tmp.close()
        self.conn = await aiosqlite.connect(self.tmp.name); self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript("CREATE TABLE papers (id INTEGER PRIMARY KEY, status TEXT);")
        await self.conn.executescript(ar.ANALYSIS_RUNS_DDL); await self.conn.commit()
        await self.conn.execute("INSERT INTO papers VALUES (1,'analyzing')")
        await ar.upsert_queued(self.conn, 1, ar.utcnow_iso())
        self.claimed = await ar.claim_next(self.conn, 3, ar.utcnow_iso(),
                                           "2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00", 3)

    async def asyncTearDown(self):
        await self.conn.close(); os.unlink(self.tmp.name)

    async def test_reporter_flushes_shared_status(self):
        from services import analysis_worker
        from api import analysis_state
        pid, gen = self.claimed

        class _St:  # AnalysisStatus 스텁(공유 객체)
            overall_status = "running"
            class current_phase:  # enum 스텁
                value = "screening"
            progress_pct = 42.0

        analysis_state._running_analyses[1] = _St()
        done = asyncio.Event()

        async def _fake_main():
            await asyncio.sleep(0.05)  # 리포터가 최소 1회 flush할 시간
            done.set()

        main_task = asyncio.create_task(_fake_main())
        side = asyncio.create_task(
            analysis_worker._reporter_and_cancel_bridge(1, gen, main_task, self.conn, interval=0.01)
        )
        await main_task; side.cancel()
        analysis_state._running_analyses.pop(1, None)

        run = await ar.get_run(self.conn, 1)
        self.assertEqual(run["current_phase"], "screening")
        self.assertEqual(run["progress_pct"], 42.0)

    async def test_bridge_sets_cancel_event_on_flag(self):
        from services import analysis_worker
        from api import analysis_state
        pid, gen = self.claimed
        ev = asyncio.Event(); analysis_state._cancel_events[1] = ev
        await ar.request_cancel(self.conn, 1)

        async def _fake_main():
            await asyncio.sleep(0.05)

        main_task = asyncio.create_task(_fake_main())
        side = asyncio.create_task(
            analysis_worker._reporter_and_cancel_bridge(1, gen, main_task, self.conn, interval=0.01)
        )
        await main_task; side.cancel()
        analysis_state._cancel_events.pop(1, None)
        self.assertTrue(ev.is_set())

    async def test_bridge_self_aborts_on_generation_fence(self):
        from services import analysis_worker
        from api import analysis_state
        pid, gen = self.claimed
        analysis_state._running_analyses[1] = type("S", (), {
            "overall_status": "running", "current_phase": None, "progress_pct": 1.0})()
        # 다른 프로세스가 재스폰한 것처럼 generation을 밀어버림
        await self.conn.execute("UPDATE analysis_runs SET generation=generation+1 WHERE paper_id=1")
        await self.conn.commit()

        async def _fake_main():
            await asyncio.sleep(1.0)  # 리포터가 fence 실패로 cancel하기 전엔 안 끝남

        main_task = asyncio.create_task(_fake_main())
        side = asyncio.create_task(
            analysis_worker._reporter_and_cancel_bridge(1, gen, main_task, self.conn, interval=0.01)
        )
        try:
            await asyncio.wait_for(main_task, timeout=1.0)
        except asyncio.CancelledError:
            pass
        analysis_state._running_analyses.pop(1, None)
        self.assertTrue(main_task.cancelled())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest services/test_analysis_worker.py -q`
Expected: FAIL (`services.analysis_worker` ModuleNotFoundError)

- [ ] **Step 3: 구현**

`sasoo/backend/services/analysis_worker.py` 신규:

```python
"""Sasoo - 디태치 분석 워커. 같은 번들을 --analyze-paper N --run-generation G로 재실행한 프로세스.

_run_full_analysis(무수정)를 실행하고, 전용 연결 사이드카가 공유 status를 analysis_runs로 fence하며
flush한다. cancel_requested를 폴링해 _cancel_events를 set하고, generation fence 실패 시 self-abort한다.
"""

from __future__ import annotations

import asyncio
import logging

import aiosqlite

from models import analysis_runs as ar

logger = logging.getLogger(__name__)

REPORT_INTERVAL_S = 1.5
SIDE_FAIL_ABORT_S = 20.0
EXIT_OK = 0
EXIT_SELF_ABORT = 75


async def _reporter_and_cancel_bridge(
    paper_id: int, generation: int, main_task: "asyncio.Task",
    conn: aiosqlite.Connection, interval: float = REPORT_INTERVAL_S,
) -> None:
    """공유 status → analysis_runs flush(fence) + cancel_requested → _cancel_events 브리지.

    - fence 실패(rowcount 0 = 재스폰으로 generation 밀림): main_task.cancel() 후 반환(split-brain 방지).
    - transient locked 재시도, 누적 실패가 SIDE_FAIL_ABORT_S 초과 시 리포터 사망=워커 사망(main_task.cancel()).
    """
    from api.analysis_state import _running_analyses, _cancel_events

    fail_streak = 0.0
    while not main_task.done():
        try:
            st = _running_analyses.get(paper_id)
            if st is not None:
                cur_phase = getattr(getattr(st, "current_phase", None), "value", None)
                n = await ar.fenced_heartbeat(
                    conn, paper_id, generation,
                    getattr(st, "overall_status", "running"), cur_phase,
                    float(getattr(st, "progress_pct", 0.0)), ar.utcnow_iso(),
                )
                if n == 0:
                    logger.warning("worker fence lost (paper=%s gen=%s) → self-abort", paper_id, generation)
                    main_task.cancel()
                    return
            run = await ar.get_run(conn, paper_id)
            if run and run.get("cancel_requested"):
                ev = _cancel_events.get(paper_id)
                if ev is not None:
                    ev.set()
            fail_streak = 0.0
        except sqlite3.OperationalError:  # aiosqlite는 sqlite3 예외를 그대로 raise(locked/busy 등 transient)
            fail_streak += interval
            if fail_streak >= SIDE_FAIL_ABORT_S:
                logger.error("worker reporter DB failure > %ss → self-abort (paper=%s)", SIDE_FAIL_ABORT_S, paper_id)
                main_task.cancel()
                return
        await asyncio.sleep(interval)


async def run_analysis_worker(paper_id: int, generation: int) -> int:
    from main import bootstrap_runtime
    from models.database import get_db, open_side_connection
    from api.analysis_routes import _run_full_analysis

    await bootstrap_runtime(worker=True)
    side_conn = await open_side_connection()
    main_task = asyncio.create_task(_run_full_analysis(paper_id))
    side = asyncio.create_task(_reporter_and_cancel_bridge(paper_id, generation, main_task, side_conn))
    exit_code = EXIT_OK
    try:
        await main_task
    except asyncio.CancelledError:
        exit_code = EXIT_SELF_ABORT  # fence 밀림/리포터 사망: terminal write 하지 않는다
        return exit_code
    finally:
        side.cancel()
        if exit_code == EXIT_OK:
            # papers.status(진실원)를 읽어 analysis_runs.status를 fence하에 확정
            try:
                row = await (await get_db()).execute("SELECT status FROM papers WHERE id=?", (paper_id,))
                paper = await row.fetchone()
                terminal = (paper["status"] if paper else "error")
                await ar.finalize_run(side_conn, paper_id, generation, terminal, ar.utcnow_iso())
            except Exception as exc:  # noqa: BLE001
                logger.warning("worker finalize failed (paper=%s): %s", paper_id, exc)
        await side_conn.close()
    return exit_code
```

> `analysis_worker.py` 상단 import에 `import sqlite3`를 추가한다(위 except 절이 참조).

`sasoo/backend/main.py` 편집 — lifespan의 startup 본문(88-154행)을 `bootstrap_runtime`으로 추출하고 lifespan은 이를 호출 + 재개 기동만 한다. lifespan 함수 위에 추가:

```python
async def bootstrap_runtime(worker: bool = False) -> None:
    """서버/워커 공통 런타임 초기화. worker=True면 공유 로그 핸들·stuck recovery·리컨실러 제외."""
    import logging
    if worker:
        from models.database import connect_worker_db
        await connect_worker_db()
    else:
        await init_db()
        from services.log_setup import setup_logging
        log_level = logging.DEBUG if os.environ.get("SASOO_ENV") != "production" else logging.INFO
        setup_logging(level=log_level)
    if worker:
        # 워커는 공유 RotatingFileHandler를 열지 않는다(다중 프로세스 rollover 충돌). stdout만.
        logging.basicConfig(level=logging.INFO)

    print(f"[Sasoo] App data root: {APP_DATA_ROOT}")

    from models.database import fetch_all
    from services.crypto import decrypt_value
    settings_map: dict = {}
    try:
        rows = await fetch_all(
            "SELECT key, value FROM settings "
            "WHERE key IN ('gemini_api_key', 'openai_api_key', 'pdf_visual_engine')"
        )
        settings_map = {row["key"]: row["value"] for row in rows}
    except Exception as exc:
        print(f"[Sasoo] Warning: Could not load settings from DB: {exc}")
    try:
        env_names = {"gemini_api_key": "GEMINI_API_KEY", "openai_api_key": "OPENAI_API_KEY"}
        for setting_key, env_name in env_names.items():
            value = settings_map.get(setting_key)
            if value:
                decrypted = decrypt_value(value)
                if decrypted:
                    os.environ[env_name] = decrypted
    except Exception as exc:
        print(f"[Sasoo] Warning: Could not load API keys from DB: {exc}")
    try:
        engine = str(settings_map.get("pdf_visual_engine") or "").strip().lower()
        if engine in {"gemini", "odl"}:
            os.environ["SASOO_PDF_VISUAL_ENGINE"] = engine
    except Exception as exc:
        print(f"[Sasoo] Warning: Could not load PDF visual engine preference: {exc}")

    from services.agents import load_all_agents
    load_all_agents()
```

lifespan의 startup 부분을 다음으로 교체(기존 88-154행 대체, 단 stuck recovery는 리컨실러 시드로 대체):

```python
    # --- Startup ---
    await bootstrap_runtime(worker=False)

    # 프로세스 분리: 기동 시 고아('analyzing'인데 runs 행 없음)를 큐로 시드하고 리컨실러를 띄운다.
    from services.analysis_supervisor import start_reconciler
    await start_reconciler(app)
```

lifespan shutdown 부분에 리컨실러 정지 추가(159행 `await close_db()` 앞):

```python
    from services.analysis_supervisor import stop_reconciler
    await stop_reconciler(app)
```

`main.py`의 `__main__` argparse(363-368행)에 인자 추가 + 분기(파일 최하단 `if __name__ == "__main__":` 블록 안, `args = parser.parse_args()` 직후):

```python
    parser.add_argument("--analyze-paper", type=int, default=None, help="Run detached analysis worker for paper id")
    parser.add_argument("--run-generation", type=int, default=0, help="Fence token for the analysis worker")

    args = parser.parse_args()

    if args.analyze_paper is not None:
        import asyncio
        from services.analysis_worker import run_analysis_worker
        sys.exit(asyncio.run(run_analysis_worker(args.analyze_paper, args.run_generation)))
```

> 주의: `start_reconciler`/`stop_reconciler`는 Task 7(T4)에서 구현한다. Task 5 완료 시점에는 `services/analysis_supervisor.py`에 이 두 함수의 **no-op 스텁**만 먼저 둔다(아래). Task 7이 본체를 채운다.

Task 5에서 `sasoo/backend/services/analysis_supervisor.py`를 스텁으로 생성(Task 6/7이 확장):

```python
"""Sasoo - 분석 서브프로세스 슈퍼바이저(스폰 + 리컨실러). Task 6/7에서 확장."""

from __future__ import annotations


async def start_reconciler(app) -> None:  # Task 7에서 본체 구현
    return None


async def stop_reconciler(app) -> None:  # Task 7에서 본체 구현
    return None
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest services/test_analysis_worker.py api/test_analysis_routes.py -q`
Expected: PASS (신규 3건 + 기존 전체 — lifespan 편집이 import 시점 회귀를 내지 않는지 함께 확인)

- [ ] **Step 5: 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중
git add sasoo/backend/services/analysis_worker.py sasoo/backend/services/analysis_supervisor.py sasoo/backend/main.py sasoo/backend/services/test_analysis_worker.py
git commit -m "feat(analysis): 디태치 워커 엔트리 + 전용연결 사이드카(fence·self-abort) + bootstrap 추출

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6 (T3): 슈퍼바이저 스폰 — argv 빌더 + env sanitize + 디태치 Popen

frozen/dev를 분기해 워커 커맨드를 만들고, PYINSTALLER_RESET_ENVIRONMENT + CA env pop + 디태치 플래그로 Popen한다. 부모 logfile 핸들은 즉시 close한다.

**Files:**
- Modify: `sasoo/backend/services/analysis_supervisor.py` (스폰 함수 추가)
- Create: `sasoo/backend/services/test_analysis_supervisor.py`

**Interfaces:**
- Produces:
  - `analysis_supervisor.build_worker_argv(paper_id: int, generation: int) -> list[str]`
  - `analysis_supervisor.build_spawn_env(base_env: dict | None = None) -> dict`
  - `analysis_supervisor.spawn_worker(paper_id: int, generation: int) -> int` — 반환: 자식 pid
  - `analysis_supervisor.BACKEND_DIR: pathlib.Path`

- [ ] **Step 1: 실패하는 테스트 작성** — `sasoo/backend/services/test_analysis_supervisor.py` 신규:

```python
import sys
import types
import unittest
from unittest.mock import MagicMock, patch


class SpawnBuilderTests(unittest.TestCase):
    def test_argv_frozen_uses_executable_directly(self):
        from services import analysis_supervisor as sup
        with patch.object(sys, "frozen", True, create=True), \
             patch.object(sys, "executable", "/opt/sasoo/sasoo-backend"):
            argv = sup.build_worker_argv(7, 3)
        self.assertEqual(argv, ["/opt/sasoo/sasoo-backend", "--analyze-paper", "7", "--run-generation", "3"])

    def test_argv_dev_prepends_main_py(self):
        from services import analysis_supervisor as sup
        if hasattr(sys, "frozen"):
            self.skipTest("frozen attr present")
        with patch.object(sys, "executable", "/venv/bin/python"):
            argv = sup.build_worker_argv(7, 3)
        self.assertEqual(argv[0], "/venv/bin/python")
        self.assertTrue(argv[1].endswith("main.py"))
        self.assertEqual(argv[2:], ["--analyze-paper", "7", "--run-generation", "3"])

    def test_env_sets_pyinstaller_reset_and_pops_ca(self):
        from services import analysis_supervisor as sup
        env = sup.build_spawn_env({"SSL_CERT_FILE": "/tmp/x.pem", "REQUESTS_CA_BUNDLE": "/tmp/x.pem",
                                    "GEMINI_API_KEY": "k"})
        self.assertEqual(env["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertEqual(env["SASOO_ANALYSIS_WORKER"], "1")
        self.assertNotIn("SSL_CERT_FILE", env)          # 서버 atexit 삭제 대상이라 상속 금지
        self.assertNotIn("REQUESTS_CA_BUNDLE", env)
        self.assertEqual(env["GEMINI_API_KEY"], "k")     # API 키는 상속

    def test_spawn_worker_uses_detach_flags(self):
        from services import analysis_supervisor as sup
        fake_proc = types.SimpleNamespace(pid=4242)
        with patch("services.analysis_supervisor.subprocess.Popen", return_value=fake_proc) as popen, \
             patch("services.analysis_supervisor.open", create=True):
            pid = sup.spawn_worker(7, 3)
        self.assertEqual(pid, 4242)
        _, kwargs = popen.call_args
        self.assertTrue(kwargs.get("close_fds"))
        if sys.platform == "win32":
            self.assertIn("creationflags", kwargs)
        else:
            self.assertTrue(kwargs.get("start_new_session"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest services/test_analysis_supervisor.py -q`
Expected: FAIL (`build_worker_argv` AttributeError)

- [ ] **Step 3: 구현**

`sasoo/backend/services/analysis_supervisor.py`의 스텁 위(파일 상단)에 스폰 로직 추가:

```python
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from models.database import APP_DATA_ROOT

BACKEND_DIR = Path(__file__).resolve().parent.parent  # sasoo/backend
_LOG_DIR = APP_DATA_ROOT / "logs"


def build_worker_argv(paper_id: int, generation: int) -> list[str]:
    """frozen(번들)=exe 직접 재실행, dev=python main.py. 둘 다 main.py argparse로 라우팅된다."""
    tail = ["--analyze-paper", str(paper_id), "--run-generation", str(generation)]
    if getattr(sys, "frozen", False):
        return [sys.executable, *tail]
    return [sys.executable, str(BACKEND_DIR / "main.py"), *tail]


def build_spawn_env(base_env: dict | None = None) -> dict:
    """워커 env: 서버 env 상속 + 워커 플래그. PyInstaller 독립 재실행 + CA 파일 수명 독립."""
    env = dict(os.environ if base_env is None else base_env)
    env["SASOO_ANALYSIS_WORKER"] = "1"
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # PyInstaller 6.9+: 자식이 부모 _MEIPASS 환경 리셋
    # 서버가 만든 임시 CA PEM은 서버 atexit이 삭제한다 → 상속하면 서버 종료 시 워커 HTTPS가 깨진다.
    # 워커는 main.py 로드 시 _export_os_certs()로 자기 PEM을 만들어 자기 atexit로 관리한다.
    env.pop("SSL_CERT_FILE", None)
    env.pop("REQUESTS_CA_BUNDLE", None)
    return env


def spawn_worker(paper_id: int, generation: int) -> int:
    """디태치 워커를 스폰하고 자식 pid를 반환한다. stdout/stderr는 per-run 로그로 리다이렉트."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    logpath = _LOG_DIR / f"analysis_paper{paper_id}_g{generation}_{ts}.log"
    argv = build_worker_argv(paper_id, generation)
    env = build_spawn_env()
    kwargs: dict = dict(
        stdin=subprocess.DEVNULL, close_fds=True, cwd=str(BACKEND_DIR), env=env,
    )
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    # with 블록으로 부모 핸들 수명 관리(자식은 자기 fd 복사본 유지)
    with open(logpath, "ab") as f:
        proc = subprocess.Popen(argv, stdout=f, stderr=f, **kwargs)
    return proc.pid
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest services/test_analysis_supervisor.py -q`
Expected: PASS (4건)

- [ ] **Step 5: 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중
git add sasoo/backend/services/analysis_supervisor.py sasoo/backend/services/test_analysis_supervisor.py
git commit -m "feat(analysis): 워커 스폰 빌더 — frozen/dev argv 분기, PYINSTALLER_RESET_ENVIRONMENT·CA env 분리, 디태치 Popen

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7 (T4): 리컨실러 — 고아 재개 + 큐 드레인 + startup 시드

주기적 리컨실러가 stale 조정(T1 우선순위) → attempts 정리 → cap까지 claim+spawn을 돈다. lifespan이 startup에서 시드 후 루프를 띄운다.

**Files:**
- Modify: `sasoo/backend/services/analysis_supervisor.py` (`reconcile_once`/`start_reconciler`/`stop_reconciler` 본체, 상수)
- Create: `sasoo/backend/services/test_analysis_supervisor_reconcile.py`

**Interfaces:**
- Consumes: T1 `analysis_runs.*`, T6 `spawn_worker`/`set_pid`, `api.settings`(max_concurrent_analyses)
- Produces:
  - `analysis_supervisor.LEASE_S = 45`, `MAX_ATTEMPTS = 3`, `BACKOFF_S = 60`, `RECONCILE_INTERVAL_S = 15`
  - `analysis_supervisor.read_max_concurrent() -> int`
  - `analysis_supervisor.reconcile_once(conn, spawn=spawn_worker) -> None` (spawn 주입 가능 — 테스트)
  - `start_reconciler(app)`/`stop_reconciler(app)` 본체(스텁 대체)

- [ ] **Step 1: 실패하는 테스트 작성** — `sasoo/backend/services/test_analysis_supervisor_reconcile.py` 신규:

```python
import os
import tempfile
import unittest

import aiosqlite

from models import analysis_runs as ar


class ReconcileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); self.tmp.close()
        self.conn = await aiosqlite.connect(self.tmp.name); self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript("CREATE TABLE papers (id INTEGER PRIMARY KEY, status TEXT);")
        await self.conn.executescript(ar.ANALYSIS_RUNS_DDL); await self.conn.commit()

    async def asyncTearDown(self):
        await self.conn.close(); os.unlink(self.tmp.name)

    async def test_reconcile_drains_queue_up_to_cap(self):
        from services import analysis_supervisor as sup
        for pid in (1, 2, 3):
            await self.conn.execute("INSERT INTO papers VALUES (?, 'analyzing')", (pid,))
            await ar.upsert_queued(self.conn, pid, ar.utcnow_iso())
        await self.conn.commit()
        spawned = []
        await sup.reconcile_once(self.conn, cap=2, spawn=lambda p, g: spawned.append((p, g)) or 1000 + p)
        # cap=2 → 2편만 running으로 전이, spawn 2회
        self.assertEqual(len(spawned), 2)
        running = [r for r in [await ar.get_run(self.conn, i) for i in (1, 2, 3)] if r["status"] == "running"]
        self.assertEqual(len(running), 2)
        for r in running:
            self.assertEqual(r["generation"], 1)  # claim이 generation +1

    async def test_reconcile_marks_over_attempts_error(self):
        from services import analysis_supervisor as sup
        await self.conn.execute("INSERT INTO papers VALUES (1, 'analyzing')")
        await ar.upsert_queued(self.conn, 1, ar.utcnow_iso())
        await self.conn.execute("UPDATE analysis_runs SET attempts=3 WHERE paper_id=1")
        await self.conn.commit()
        spawned = []
        await sup.reconcile_once(self.conn, cap=2, spawn=lambda p, g: spawned.append(p) or 1)
        self.assertEqual(spawned, [])                 # attempts 초과는 스폰 안 함
        self.assertEqual((await ar.get_run(self.conn, 1))["status"], "error")
        row = await (await self.conn.execute("SELECT status FROM papers WHERE id=1")).fetchone()
        self.assertEqual(row["status"], "error")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest services/test_analysis_supervisor_reconcile.py -q`
Expected: FAIL (`reconcile_once` TypeError/AttributeError — 스텁이라 cap/spawn 미지원)

- [ ] **Step 3: 구현**

`sasoo/backend/services/analysis_supervisor.py`에 상수·리컨실러 본체 추가하고 스텁 두 함수를 교체:

```python
import asyncio
import logging

logger = logging.getLogger(__name__)

LEASE_S = 45
MAX_ATTEMPTS = 3
BACKOFF_S = 60
RECONCILE_INTERVAL_S = 15


def _iso_shift(now: "datetime", seconds: int) -> str:
    from datetime import timedelta
    return (now - timedelta(seconds=seconds)).isoformat()


async def read_max_concurrent() -> int:
    try:
        from api.settings import _get_all_settings
        settings = await _get_all_settings()
        return max(1, int(settings.get("max_concurrent_analyses", "3")))
    except Exception:
        return 3


async def reconcile_once(conn, cap: int, spawn=spawn_worker) -> None:
    """stale 조정 → attempts 정리 → cap까지 claim+spawn."""
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    stale_cut = _iso_shift(now_dt, LEASE_S)
    fresh_cut = stale_cut
    backoff_cut = _iso_shift(now_dt, BACKOFF_S)

    await ar.reconcile_stale(conn, stale_cut=stale_cut, max_attempts=MAX_ATTEMPTS, now=now)
    await ar.mark_over_attempts_error(conn, MAX_ATTEMPTS)

    while True:
        claimed = await ar.claim_next(conn, cap=cap, now=now, fresh_cut=fresh_cut,
                                      backoff_cut=backoff_cut, max_attempts=MAX_ATTEMPTS)
        if claimed is None:
            break
        paper_id, generation = claimed
        try:
            pid = spawn(paper_id, generation)
            await ar.set_pid(conn, paper_id, generation, pid)
        except Exception as exc:  # noqa: BLE001
            logger.error("spawn failed (paper=%s gen=%s): %s → requeue", paper_id, generation, exc)
            await ar.finalize_run(conn, paper_id, generation, "queued", now)


async def _reconciler_loop(app) -> None:
    from models.database import get_db, execute_update
    try:
        conn = await get_db()
        # startup: 레거시 고아 시드(구 'analyzing→error' 한 줄 대체)
        await ar.seed_legacy(conn, datetime.now(timezone.utc).isoformat())
    except Exception as exc:  # noqa: BLE001
        logger.warning("reconciler seed failed: %s", exc)
    while True:
        try:
            conn = await get_db()
            cap = await read_max_concurrent()
            await reconcile_once(conn, cap=cap)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("reconcile_once error: %s", exc)
        await asyncio.sleep(RECONCILE_INTERVAL_S)


async def start_reconciler(app) -> None:
    app.state.reconciler_task = asyncio.create_task(_reconciler_loop(app))


async def stop_reconciler(app) -> None:
    task = getattr(app.state, "reconciler_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
```

> 파일 상단에 `from datetime import datetime, timezone`가 Task 6에서 이미 import됨을 확인(중복 import 금지). `spawn=spawn_worker` 기본값은 `spawn_worker`가 위에 정의된 뒤에 와야 한다(함수 정의 순서 유지).

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest services/ models/ api/test_analysis_routes.py -q`
Expected: PASS (리컨실러 2건 + 전체)

- [ ] **Step 5: 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중
git add sasoo/backend/services/analysis_supervisor.py sasoo/backend/services/test_analysis_supervisor_reconcile.py
git commit -m "feat(analysis): 리컨실러 — 고아 재개(우선순위 조정)·큐 드레인(cap)·startup 시드, attempts 상한·백오프

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8 (T5): 엔드포인트 재배선 — `/run` 분기 + `/cancel` DB flag + `/status` overlay + Electron 플래그

`SASOO_ANALYSIS_SUBPROCESS` 플래그로 `/run`을 분기(subprocess=claim+spawn, off=기존 background_tasks). `/cancel`은 DB flag를 세운다. `/status`는 기존 builder에 runs를 overlay하고 queued→running 매핑. python-manager.ts가 실런타임에서 플래그를 켠다.

**Files:**
- Modify: `sasoo/backend/api/analysis_routes.py` (`run_analysis` 2348-2418, `cancel_analysis` 2421-2439, `get_analysis_status` 2442-2505)
- Modify: `sasoo/electron/python-manager.ts` (두 spawn env 블록)
- Modify: `sasoo/backend/api/test_analysis_routes.py`

**Interfaces:**
- Consumes: T1 `analysis_runs.{upsert_queued,request_cancel,get_run}`, T6 `spawn_worker`, T7 `reconcile_once`/`read_max_concurrent`
- Produces: 없음(엔드포인트 계약 불변, 응답 스키마 동일). 플래그 판정 헬퍼 `analysis_routes._subprocess_mode() -> bool`.

- [ ] **Step 1: 실패하는 테스트 작성** — `AnalysisRouteSemanticTests`에 추가:

```python
    def test_subprocess_mode_flag(self):
        with patch.dict("os.environ", {"SASOO_ANALYSIS_SUBPROCESS": "1"}):
            self.assertTrue(analysis_routes._subprocess_mode())
        with patch.dict("os.environ", {}, clear=False):
            os.environ.pop("SASOO_ANALYSIS_SUBPROCESS", None)
            self.assertFalse(analysis_routes._subprocess_mode())

    def test_status_overlay_maps_queued_to_running(self):
        # analysis_runs가 queued면 overall_status를 running으로 매핑(프론트 active 인식)
        merged = analysis_routes._overlay_run_status(
            base={"overall_status": "analyzing", "progress_pct": 0.0, "current_phase": None},
            run={"status": "queued", "current_phase": None, "progress_pct": 0.0},
        )
        self.assertEqual(merged["overall_status"], "running")

    def test_status_overlay_uses_run_progress_and_phase(self):
        merged = analysis_routes._overlay_run_status(
            base={"overall_status": "analyzing", "progress_pct": 0.0, "current_phase": None},
            run={"status": "running", "current_phase": "recipe", "progress_pct": 55.0},
        )
        self.assertEqual(merged["overall_status"], "running")
        self.assertEqual(merged["current_phase"], "recipe")
        self.assertEqual(merged["progress_pct"], 55.0)
```

> 참고: `os`가 테스트 파일에 import되어 있지 않으면 파일 상단 import에 `import os`를 추가한다.

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest api/test_analysis_routes.py -q -k "subprocess_mode or status_overlay"`
Expected: FAIL (`_subprocess_mode`/`_overlay_run_status` AttributeError)

- [ ] **Step 3: 구현**

`analysis_routes.py`의 `run_analysis` 정의 위에 헬퍼 추가:

```python
def _subprocess_mode() -> bool:
    """실런타임(Electron/서버)에서만 켜지는 디태치 워커 모드 플래그. 테스트/직접 실행 기본 off."""
    return os.environ.get("SASOO_ANALYSIS_SUBPROCESS", "") == "1"


def _overlay_run_status(base: dict, run: Optional[dict]) -> dict:
    """analysis_runs 라이브 값을 기존 status builder 결과에 overlay. queued→running 매핑."""
    if not run:
        return base
    st = run.get("status")
    if st in ("queued", "running"):
        merged = dict(base)
        merged["overall_status"] = "running"          # 프론트 isRunning union + 폴링 지속
        if run.get("current_phase"):
            merged["current_phase"] = run["current_phase"]
        pct = run.get("progress_pct")
        if pct is not None and pct > merged.get("progress_pct", 0.0):
            merged["progress_pct"] = pct
        return merged
    return base
```

`run_analysis`(2411-2412행, `background_tasks.add_task` 지점)를 분기로 교체:

```python
    # Launch analysis: subprocess mode(실런타임)면 디태치 워커, 아니면 기존 in-process 경로 유지
    if _subprocess_mode():
        from models.database import get_db
        from models.analysis_runs import upsert_queued, utcnow_iso
        from services.analysis_supervisor import reconcile_once, read_max_concurrent
        conn = await get_db()
        await upsert_queued(conn, paper_id, utcnow_iso())
        # 즉시 드레인 시도(cap 내면 이번 요청이 스폰, 초과면 queued로 남아 리컨실러가 픽업)
        await reconcile_once(conn, cap=await read_max_concurrent())
    else:
        background_tasks.add_task(_run_full_analysis, paper_id)

    return {
        "paper_id": paper_id,
        "status": "started",
        "message": "Analysis pipeline started. Poll /status for progress.",
    }
```

`cancel_analysis`(2421-2439행)를 DB flag 우선으로 보강 (기존 인메모리 경로 유지 + subprocess 경로 추가):

```python
@router.post("/{paper_id}/cancel", status_code=200)
async def cancel_analysis(paper_id: int):
    """Cancel a running analysis for a paper."""
    # subprocess mode: DB flag를 세우면 워커 사이드카가 phase 경계에서 취소를 존중한다
    if _subprocess_mode():
        from models.database import get_db
        from models.analysis_runs import request_cancel, get_run
        conn = await get_db()
        run = await get_run(conn, paper_id)
        if run and run.get("status") in ("queued", "running"):
            await request_cancel(conn, paper_id)
            return {"paper_id": paper_id, "status": "cancelling"}

    # in-process(레거시/테스트) 경로 — 기존 동작 보존
    if paper_id in _cancel_events:
        _cancel_events[paper_id].set()
        return {"paper_id": paper_id, "status": "cancelling"}
    if paper_id in _running_analyses:
        running = _running_analyses[paper_id]
        if running.overall_status == "running":
            running.overall_status = "cancelled"
            await execute_update("UPDATE papers SET status = ? WHERE id = ?", ("cancelled", paper_id))
            return {"paper_id": paper_id, "status": "cancelled"}

    raise HTTPException(status_code=404, detail=f"No running analysis for paper {paper_id}")
```

`get_analysis_status`의 DB 폴백 반환(2497-2505행, `return AnalysisStatus(...)`) 직전에 overlay를 삽입한다. 구체적으로 기존 폴백이 만든 값(overall/progress/phases)을 dict로 모은 뒤 overlay를 적용:

```python
    base = {"overall_status": paper["status"], "progress_pct": progress, "current_phase": None}
    if _subprocess_mode():
        try:
            from models.database import get_db
            from models.analysis_runs import get_run
            run = await get_run(await get_db(), paper_id)
            base = _overlay_run_status(base, run)
        except Exception:
            pass

    return AnalysisStatus(
        paper_id=paper_id,
        overall_status=base["overall_status"],
        phases=phases,
        progress_pct=base["progress_pct"],
        total_cost_usd=total_cost,
        total_tokens_in=total_in,
        total_tokens_out=total_out,
    )
```

> 주의: 기존 `get_analysis_status`는 in-memory `_running_analyses` 체크를 맨 앞에 유지한다(테스트·레거시). overlay는 DB 폴백 경로에만 얹는다. `AnalysisStatus`에 `current_phase` 필드가 있으면 `base["current_phase"]`도 전달, 없으면 생략(schemas.py 확인 후 결정 — 없으면 progress/overall만 overlay).

`sasoo/electron/python-manager.ts` 편집 — 두 spawn env 블록(번들 152행 부근, dev 187행 부근)에 각각 추가:

```typescript
          SASOO_ANALYSIS_SUBPROCESS: '1',
```

(각 `env: { ...process.env, ... SASOO_SHUTDOWN_TOKEN: this.shutdownToken, }` 블록 안, 기존 키들과 나란히)

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `cd /Users/dongj/dev/논문_사수_개발중/sasoo/backend && python3 -m pytest api/test_analysis_routes.py -q`
Expected: PASS — 특히 `get_analysis_status` DB 폴백 테스트(test:322 부근, `get_latest_completed_phase_rows` mock)가 그린인지 확인. 이 테스트는 `SASOO_ANALYSIS_SUBPROCESS` 미설정이라 overlay 분기를 타지 않는다. 만약 이 테스트가 subprocess 플래그를 켠 환경에서 돈다면 `get_run`이 None을 반환하도록 `fetch_one`/`get_db` mock을 추가한다(테스트 조정 1줄).

- [ ] **Step 5: 커밋**

```bash
cd /Users/dongj/dev/논문_사수_개발중
git add sasoo/backend/api/analysis_routes.py sasoo/electron/python-manager.ts sasoo/backend/api/test_analysis_routes.py
git commit -m "feat(analysis): 엔드포인트 재배선 — /run 서브프로세스 분기(플래그), /cancel DB flag, /status overlay·queued→running

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9 (T6): 통합 수동 검증 (자동화 불가 — 체크리스트)

디태치·재개·fence·플랫폼 동작은 실제 프로세스 생명주기와 OS 시그널이 필요해 pytest로 재현이 어렵다. 아래를 수동으로 확인한다. **구현 중 실제 과금 분석을 피하고, 가능한 검증은 짧은 논문 1편으로 최소화한다.**

**Files:** 없음(검증 전용). 필요 시 발견된 결함은 해당 Task로 되돌아가 수정.

- [ ] **Step 1: 플래그 off 회귀** — `SASOO_ANALYSIS_SUBPROCESS` 미설정으로 백엔드 기동, `python3 -m pytest -q`(backend 전체) 그린. 기존 in-process 경로 불변 확인.

- [ ] **Step 2: dev 스폰 경로** — `SASOO_ANALYSIS_SUBPROCESS=1`로 서버 기동 후, 짧은 논문 1편 `/run`. 확인:
  - `models/database.py`의 로그 디렉터리에 `analysis_paperN_gG_*.log` 생성.
  - `analysis_runs` 행: status가 queued→running, heartbeat_at이 ~1.5s마다 갱신, pid 기록.
  - 프론트 진행률 바가 phase 경계에서 갱신되고 현재 phase가 "running"으로 표시.
  - 완료 후 papers.status='completed', analysis_runs.status='completed', CostDashboard에 비용 반영(analysis_results 원장).

- [ ] **Step 3: 서버 크래시/리로드 생존 + 재개** — 분석 진행 중 서버 프로세스를 강제 종료(dev: 소스 저장으로 uvicorn reload 유발, 또는 서버 pid에 SIGKILL). 확인:
  - 워커 프로세스가 살아남아 로그가 계속 쌓임(디태치).
  - 서버 재기동 후 리컨실러가 fresh-heartbeat running을 **재스폰하지 않고** `/status`로 진행률을 이어 읽음.
  - 워커까지 죽인 경우(워커 pid에 SIGKILL): heartbeat 정지 → 45s 후 리컨실러가 requeue → 재스폰(generation +1), 완료 phase는 캐시 스킵(무과금).

- [ ] **Step 4: 세대 fence(split-brain 방지)** — 워커 실행 중 `analysis_runs.generation`을 수동 +1(다른 워커 재스폰 모사) 후, 원래 워커 로그에 "fence lost → self-abort" 출력 + 워커가 terminal write 없이 종료(exit 75) 확인. `analysis_runs`가 한 세대로만 갱신됨.

- [ ] **Step 5: 취소 + 앱 종료 정책** — 진행 중 취소 버튼 → `analysis_runs.cancel_requested=1` → 다음 phase 경계에서 papers/runs='cancelled'. 앱 종료(Electron) 후 재기동 → 미완료 논문이 재개(Windows taskkill reap→재개, macOS 워커 생존→완료 후 관측)되는지 확인. **자동화 불가 항목**: Windows `taskkill /T`의 detached 자식 reap 여부, `PYINSTALLER_RESET_ENVIRONMENT`의 번들 재실행 독립성은 실제 패키징 빌드에서만 검증 가능 — 프로덕션 번들 QA 시 별도 확인.

- [ ] **Step 6: 최종 커밋(문서/체크리스트 결과 기록이 있을 경우에만)** — 코드 변경이 없으면 커밋 없음. 결함 수정이 있었다면 해당 Task 규칙으로 커밋.

---

## 부록: Task 간 시그니처 일치표 (셀프 리뷰용)

| 심볼 | 정의(Task) | 소비(Task) |
|---|---|---|
| `analysis_runs.claim_next(conn,cap,now,fresh_cut,backoff_cut,max_attempts)->Optional[tuple]` | T4 | T7 reconcile_once |
| `analysis_runs.fenced_heartbeat(conn,pid,gen,status,phase,pct,now)->int` | T4 | T5 사이드카 |
| `analysis_runs.finalize_run(conn,pid,gen,terminal,now,err=None)->int` | T4 | T5 워커 finalize, T7 spawn 실패 requeue |
| `analysis_runs.upsert_queued/request_cancel/get_run/reconcile_stale/seed_legacy/mark_over_attempts_error` | T4 | T5·T7·T8 |
| `database.connect_worker_db/open_side_connection` | T4 | T5 |
| `main.bootstrap_runtime(worker)` | T5 | T5 워커, lifespan |
| `analysis_worker.run_analysis_worker(pid,gen)->int` | T5 | main `__main__` |
| `analysis_supervisor.spawn_worker(pid,gen)->int` | T6 | T7 reconcile_once, T8 /run(간접) |
| `analysis_supervisor.reconcile_once(conn,cap,spawn)`/`read_max_concurrent()` | T7 | T8 /run |
| `analysis_supervisor.start_reconciler/stop_reconciler(app)` | T5 스텁→T7 본체 | main lifespan |
| `analysis_routes._subprocess_mode()`/`_overlay_run_status(base,run)` | T8 | T8 엔드포인트 |
