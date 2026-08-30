# 프로바이더 중립화 인수인계 — 사용자 결정 대기 항목

작성: 2026-08-21. 대상: 새 세션.
브랜치: `feat/provider-neutral-llm` (worktree `/Users/dongj/dev/논문_사수_개발중/.claude/worktrees/provider-neutral-llm`)
상태: 작업 완료, push·병합 안 함. 작업 트리 깨끗. `origin/feat/provider-neutral-llm` 대비 12커밋 앞섬, `origin/main` 대비 42앞·10뒤.

## 한 줄 요약

PDF 페이지 비전 파싱을 `ai_provider`에 종속시켜 OpenAI 키 단독 사용자도 "AI 판독"을 쓸 수 있게 했다. 백엔드 641 passed. 최종 리뷰는 이 플랜 구간에 대해 병합 가능으로 판정했으나, **그 리뷰 범위에 `origin/main`의 이동이 빠져 있었고 그 결과 아래 결정 1번이 드러나지 않았다.**

---

# 사용자가 결정해야 할 것

## 결정 1 (필수, 병합 차단) — FLASH_HQ + minimal 4곳을 어떻게 할 것인가

**사실**: `origin/main`의 `sasoo/backend/services/models.py:24-25`가 이렇게 못 박았다.

> thinking_level은 low|medium|high만 쓴다. 3.7 Flash는 minimal을 지원하지 않고, 명시하면 API가 검증 에러를 낸다(ai.google.dev, 2026-08-16 확인).

그리고 `MODEL_FLASH_HQ = "gemini-3.7-flash"`로 바뀌었다(우리 브랜치는 `gemini-3.6-flash`).

**영향 범위**: 우리 브랜치의 `services/model_registry.py`에서 gemini 쪽 `minimal` 사용은 6곳이고, 그중 **4곳이 FLASH_HQ라서 병합 후 API 에러가 난다.**

| role | 모델 | effort | 병합 후 | 출처 |
|---|---|---|---|---|
| `screening` | flash-lite | minimal | 안전 | 브랜치 앞부분 |
| `naming` | flash-lite | minimal | 안전 | 브랜치 앞부분 |
| `pdf_parse` | **FLASH_HQ** | minimal | **깨짐** | 이번 작업 |
| `figure_resolver` | **FLASH_HQ** | minimal | **깨짐** | 브랜치 앞부분 |
| `table_resolver` | **FLASH_HQ** | minimal | **깨짐** | 브랜치 앞부분 |
| `subfigure` | **FLASH_HQ** | minimal | **깨짐** | 브랜치 앞부분 |

main 쪽 실제 사용처를 보면 규칙이 일관된다. `analysis_routes.py:534,555`와 `naming_service.py:81,142,196`의 minimal은 모두 모델이 flash-lite다. 즉 main의 규약은 "minimal은 flash-lite에서만"이다.

**텍스트 충돌을 기계적으로 풀면 이 문제는 드러나지 않는다.** 이것이 PR #44를 닫게 만든 것과 같은 종류의 의미 충돌이다.

**선택지**
1. **4곳 모두 `low`로 올린다.** 가장 단순하고 main 규약에 맞다. 대가: 4개 경로의 thinking 토큰이 늘어 비용이 오르고, 그림·표 리졸버는 기존에 minimal로 12/12를 낸 경로라 정확도 재측정 없이는 동등성을 주장할 수 없다.
2. **4곳을 flash-lite로 내린다.** minimal을 유지할 수 있으나 모델 급이 내려가 정확도 위험이 더 크다.
3. **role별로 다르게 정한다.** 예를 들어 `pdf_parse`만 `low`로, 리졸버 3개는 별도 측정 후 결정. 가장 정확하지만 작업이 늘어난다.

**내 추천**: 1번으로 통합해 먼저 초록을 만들고, 그 상태에서 정답셋 12편을 다시 재서 `low` 상승이 정확도와 비용에 무엇을 하는지 기록한다. 리졸버 3개는 이번 작업의 산물이 아니므로 이 브랜치의 책임 범위를 넘지만, 병합하면 같이 깨지므로 미룰 수 없다.

## 결정 2 — main 통합을 언제, 어떤 단위로 할 것인가

`origin/main`이 10커밋 앞서 있다. 신규 내용은 v0.9.0 릴리스, Gemini 3.7 Flash 반영(#51), flash 단가 2배 과대계상 수정(#51), recipe 핀 해제(#53), Evidence Anchoring(#46), Phase 0 진실 회복(#45) 등이다. 텍스트 충돌은 11파일에서 발생한다.

```
sasoo/backend/api/analysis_routes.py
sasoo/backend/services/figure_resolver.py
sasoo/backend/services/gemini_parser.py
sasoo/backend/services/llm/interactions_client.py
sasoo/backend/services/models.py
sasoo/backend/services/pricing.py
sasoo/backend/services/subfigure_detector.py
sasoo/backend/services/table_resolver.py
sasoo/backend/services/test_pricing.py
sasoo/backend/tools/provider_compare.py
sasoo/vitest.config.ts
```

**선택지**
1. **통합 패스를 별도 작업으로 먼저 돌리고 그 뒤 PR.** 결정 1을 그 안에서 해결한다.
2. **지금 상태로 PR을 올리고 리뷰 중에 통합.** PR이 CONFLICTING으로 뜨고, 리뷰어가 의미 충돌을 놓칠 위험이 있다.
3. **브랜치를 쪼갠다.** 42커밋이 한 PR로는 크다. 예를 들어 텍스트 분석 중립화(앞부분)와 비전 파싱 중립화(이번 작업)를 나눈다.

**내 추천**: 1번. 통합 패스는 텍스트 충돌 해소 + 결정 1 반영 + 재측정으로 구성되며, 그 자체로 플랜과 리뷰가 필요한 규모다.

## 결정 3 — 재측정을 어디까지 할 것인가

main 통합 후에는 모델(3.6→3.7)과 단가(절반)가 모두 바뀌므로 이번 실측치가 그대로 통하지 않는다.

이번 측정의 한계 두 가지도 남아 있다.
- `--repeat`를 생략해 노이즈 바닥을 재지 않았다. 표 1편 차이(Gemini 10/12 대 OpenAI 9/12)가 노이즈인지 실차인지 모른다.
- `measure.py`가 `resolve_table_candidates`에 provider를 넘기지 않아 **표 격자 복원이 양쪽 실행 모두 Gemini로 돌았다.** 따라서 기록된 비용은 페이지 파싱 전용이고 파이프라인 총비용이 아니다. OpenAI 단독 키 사용자가 실제로 쓰게 될 Luna 격자 복원 경로는 미측정이다.

**선택지**: 최소(통합 후 1회씩), 표준(`--repeat 3`으로 노이즈 바닥 포함), 완전(`measure.py`에 provider를 배선해 파이프라인 총비용까지). 비용은 1회 왕복이 약 $2에서 $4 수준이다(단가 절반 반영 후).

**내 추천**: 표준. 결정 1이 4개 경로의 effort를 올리므로 노이즈 바닥 없이는 회귀를 판정할 수 없다.

## 결정 4 — 표 1편 차이를 수용할 것인가

OpenAI 9/12 대 Gemini 10/12다. 방향이 일정하지 않다. `2025_TurboQuant_general`에서는 OpenAI가 2/2로 Gemini(1/2)보다 나았고, `OptFor_RefractiveMCAO_optics`는 양쪽이 동일하게 1개를 놓쳤다(원인 미확인).

최종 리뷰의 논거는 이렇다. 이 변경의 영향을 받는 사용자(OpenAI 키 단독)의 변경 전 상태는 Gemini 10/12가 아니라 **로컬 ODL 파싱**이므로, 판단 기준은 "OpenAI 9/12가 ODL보다 나은가"이고 여유 있게 넘는다. 9/12 대 10/12의 의미는 Gemini 사용자를 OpenAI로 옮기는 결정에서 비로소 필요해지는데 이 변경은 기본 공급사를 바꾸지 않는다.

**결정할 것**: 이 논거를 수용하고 넘어갈지, 아니면 노이즈 확인 후에만 병합할지.

## 결정 5 — 별도 이슈로 세울 것들

1. **표 격자 복원 실패율 약 53%** (Gemini 39/84, OpenAI 43/89). 이 작업이 만든 것이 아니라 선재 문제이고, 새 `--reparse` 모드가 그 경로를 처음 대량 노출했다. 캡션 단위 정확도에는 안 드러나지만 표 셀 품질에 영향을 준다.
2. **`OptFor_RefractiveMCAO_optics`의 표 1건 공급사 공통 누락.** 원인 미확인. 진단이 막힌 이유는 `measure.py`가 실패한 표 번호를 남기지 않고 스크래치를 삭제하기 때문이다.
3. **Terra 승격 검토.** 이번 측정은 Luna(effort low)만 했다. Terra는 Luna 입력 단가의 10배다.

## 결정 6 — 릴리스 노트 문구

`ai_provider=openai`이고 두 키를 모두 가진 기존 사용자는 페이지 파싱이 Gemini에서 Luna로 **바뀐다.** 닫힌 경로를 여는 것이 아니라 동작하던 경로를 교체하는 것이므로 안내가 필요하다.

---

# 새 세션이 알아야 할 사실

## 이번 작업이 한 것 (커밋 12개, `cbbdd13`..`d09e166`)

설정 값 도메인 `pdf_visual_engine ∈ {gemini, odl}`과 매니페스트 엔진 문자열 `"gemini"`를 **바꾸지 않았다.** `"gemini"`는 공급사 이름이 아니라 "LLM 비전으로 파싱됨"을 뜻하는 레거시 이름이고, `strings.ts`의 UI 문구도 이미 공급사 중립("그림 판독 방식", "AI 판독")이었다. 덕분에 마이그레이션과 프론트엔드 변경이 없다. 엔진은 "LLM 비전을 쓸지 말지"만 정하고 어떤 LLM이냐는 `ai_provider`가 정한다.

- 신규 role `pdf_parse` (`services/model_registry.py`). 기존 role `visual`은 effort `low`라서 재사용 금지 — 이를 막는 테스트가 있다.
- `services/gemini_parser.py`가 모델·effort를 하드코딩에서 레지스트리 조회로. `run_convert_gemini(..., provider=)` 추가.
- `services/odl_parser.py`의 비전 엔진 가용성 판정이 `GEMINI_API_KEY` 직접 조회에서 `key_env_for(provider)`로. provider는 `ensure_visual_artifacts` 진입 시 한 번 확정해 내린다.
- Java 미탐지 안내 문구가 provider-aware로.
- `tools/extraction_audit/measure.py`에 `--reparse {gemini,openai}` 모드 추가. 저장된 매니페스트를 쓰지 않고 페이지 비전 파싱부터 다시 돌린다.
- `tools/openai_vision_spike.py` 신규(box_2d IoU 비교 도구).

## 깨면 안 되는 계약 3개

1. 매니페스트에 저장되는 엔진 문자열 `"gemini"`의 값 공간을 바꾸지 말 것. 바꾸면 승격·멱등 판정이 전부 깨진다.
2. 페이지 파서 role은 `pdf_parse`다. `visual`(그림 판독 단계, effort `low`)과 섞지 말 것.
3. `SASOO_GEMINI_PARSER_THINKING`의 **빈 문자열이 더는 "미지정"이 아니다.** 이제 "오버라이드 없음"(레지스트리 값 사용)을 뜻한다. 같은 파일의 `MEDIA_RESOLUTION`은 여전히 옛 관용구다.

## 검증된 것과 미검증

**검증**: 백엔드 641 passed / 3 skipped / 119 subtests(두 번 관찰). 태스크별 리뷰 7회 전부 통과, Task 3만 수정 라운드 1회. 최종 opus 리뷰 병합 가능(단, 범위에 main 이동 제외). 실측 기록의 모든 수치는 별도 리뷰어가 원장 raw JSON에서 독립 재계산해 불일치 0건.

**미검증**: 실제 앱을 띄워 OpenAI 키만으로 업로드부터 완주까지 해 보지 않았다. `--repeat` 노이즈 바닥, box_2d IoU의 12편 재확인, Terra, Luna 격자 복원 비용, PyInstaller 번들 확인 모두 미측정.

## 병합 후 처리 항목 (최종 리뷰 분류)

유예 13건 중 병합 전 수정 0건, 병합 후 3건, 수정 불필요 10건.

1. `_run_convert` 폴백에서 `provider=resolved`로 배선. 현재 로그와 사용자 메시지의 provider가 어긋날 수 있다(env 레버 없이는 도달 불가).
2. `measure.py`의 `requested_mode="fast"`를 프로덕션 정규화값 `"java"`로.
3. **`measure.py`가 실패한 표 번호를 남기게 할 것 — 최우선.** 위 결정 5의 미해결 2건 진단이 전부 이것 때문에 막혀 있다.

그 외: `explain_odl_failure` 두 호출부에 provider 전달(async 라우트라 가능), `--reparse`와 `--lane deterministic` 상호 배타.

## 환경 함정 두 가지

1. 이 저장소의 pytest와 git은 **샌드박스를 해제하고** 실행해야 한다. OpenDataLoader의 Java 런타임과 `.gitconfig` 접근 때문이다. 해제하지 않으면 `test_end_to_end_java_mode_writes_manifest_and_cache`가 실패한다.
2. 이 worktree에는 Python venv가 없다. `/Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python`을 절대 경로로 쓴다. 그리고 worktree의 `library/`에는 정답셋 12편의 PDF와 참조 markdown만 복사되어 있다(사용자 원본은 읽기만 했다).

## 관련 문서

- 구현 플랜: `docs/superpowers/plans/2026-08-21-pdf-visual-engine-provider-neutral.md`
- 실측 기록: `docs/superpowers/plans/2026-08-21-openai-vision-audit-record.md`
- 앞선 작업 플랜: `docs/superpowers/plans/2026-08-03-ai-provider-neutral-llm.md` (2,079줄, 이 브랜치에만 있음)
- 스펙: `docs/superpowers/specs/2026-07-31-ai-provider-selection-design.md` (R2에 superseded 주석 있음)
