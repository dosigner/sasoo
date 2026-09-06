# 인수인계: deep_dive 스키마 분해, 양사 체인 실측, 폭주 대응 (PR #59 병합 완료)

작성: 2026-08-29. 갱신: 2026-08-30. 대상: 다음 세션과 사용자.

**현재 상태**: **PR #59 병합 완료**(2026-08-29, squash, origin/main `269d46a`). DEC-017/018/019/020 네 결정이 전부 main에 들어갔다. 이 문서의 남은 내용은 배경 기록이다.

**정리 대상 3건** (에이전트가 임의로 지우지 않았다):
1. `stash@{0}` "wip: deep_dive/report 진행중" — DEC-017/018의 **옛 사본** 7파일. 같은 내용이 main에 있으므로 불필요하다. `git stash drop 'stash@{0}'`.
2. worktree `.claude/worktrees/deep-dive-luna`와 로컬 브랜치 `feat/deep-dive-luna` — 역할이 끝났다.
3. 원격 브랜치 `origin/feat/deep-dive-luna` — 병합됐으므로 삭제 가능하다.

`chore/major-upgrades` 작업 트리의 현재 미커밋 변경분은 **DEC-017/018과 무관한 별개 작업**(v1 design 관련)이므로 위 정리 대상에 포함되지 않는다.

## 한 줄 요약

deep_dive 스키마를 구조화 필드로 분해했고(DEC-017), 양사(gemini-3.7-flash vs gpt-5.6-luna) 체인을 실논문 11편 규모로 실측해 수렴 조건과 effort 사다리를 확정했으며, Gemini deep_dive 폭주에 처방 3종을 적용하고 재실행으로 검증했다(DEC-018, 부분 효과). 그 뒤 사용자가 B(deep_dive만 Luna)를 골라 DEC-019로 구현했고, 그 과정에서 폭주와 무관한 필드 생략을 발견해 DEC-020(required 7→12)까지 반영했다. 네 결정 전부가 PR #59로 병합됐다.

## 먼저 읽을 것 (순서대로)

1. `docs/product-decisions.md`의 DEC-017 ~ DEC-020 — 결정과 근거, 깨면 안 되는 계약.
2. `RESEARCH/2026-08-29-provider-chain-token-convergence.md` — 실측 3회의 전체 분석(토큰표, 수렴 처방 5개, effort 사다리, 폭주 규명). 증거 JSON과 하네스는 `RESEARCH/2026-08-29-chain-compare/` 아래(vla/, vla-fixed/, harness/).
3. PR #59 본문(병합 완료) — 리뷰어 관점으로 정리된 변경 4건과 미검증 항목.

## 미커밋 변경 (2026-08-30 기준 폐기 대상, 아래는 당시 기록)

수정 7파일: `sasoo/backend/api/analysis_routes.py`(스키마·지시문·상한), `api/report_service.py`, `api/test_recipe_output_bounds.py`, `frontend/src/components/AnalysisPanel.tsx`, `frontend/src/lib/strings.ts`, `frontend/src/lib/workbenchSummaries.ts`, `workbenchSummaries.test.ts`.
신규 2파일: `sasoo/backend/api/test_deep_dive_schema.py`, `api/test_report_service.py`.
검증 상태: 백엔드 pytest 692 passed(+138 subtests), vitest 147 passed, `tsc --noEmit` 초록 (2026-08-29 확인).

이 절차는 실행 완료됐다. 9파일은 `feat/deep-dive-luna`로 옮겨 담겼고, RESEARCH/와 docs/product-decisions.md는 로컬 유지 관례(DEC-007)에 따라 커밋하지 않았다.

## 완료된 것

- **DEC-017**: `detailed_analysis` 자유서술을 6필드(problem_definition, as_is, to_be, solution, method_summary, key_results)로 분해. as_is·to_be는 required 제외(지어내기 방지). 렌더러 3곳 신구 폴백. 잠금: `api/test_deep_dive_schema.py`.
- **실측 3회(총 $1.83)**: paper 45 양사 체인 + effort 프로브($0.385), VLA 인용 500+ 6편 양사 체인($0.98), 폭주 4편 재검증($0.46). 핵심 수치는 RESEARCH 문서 1~6장.
- **DEC-018 처방 3종 적용**: deep_dive 출력 상한 16,000(`_STAGE_MAX_OUTPUT_TOKENS`), comparison_scope enum(정형 문구의 스키마 이전, "명시해" 부활 금지 잠금), recipe 명명 규약(규칙 12).
- **재검증 결과(부분 효과)**: 옛 필러는 4/4 소멸, 폭주 해소 2/4(PaLM-E, Octo), 잔존 2/4(π0는 근거 위치 표기 반복, OpenVLA는 점 반복 + recipe 신규 폭주). 결론: 폭주는 3.7 Flash의 확률적 실패 모드. 상한만 3/3 작동.

## 결정 완료 (2026-08-29, B 채택 → DEC-019)

사용자가 **B(deep_dive만 Luna)**를 골랐고 구현·실측까지 끝났다. 결정을 가른 근거는
폭주 산출물에 프로덕션 구제 함수를 적용해 확인한 손해의 성격이다: 14필드 중 8개만
살아남고 나머지 6개가 **오류 없이** 사라진다(required가 아니라 구제가 성공으로
판정된다). 상한은 비용만 막고 이 손실은 못 막는다. 혼합 체인 실측 2편에서 폭주가
사라지고 14/14 필드가 복구됐다. 자세한 내용은 DEC-019와 RESEARCH 문서 7장.

작업 위치는 별도 worktree `.claude/worktrees/deep-dive-luna`(브랜치
`feat/deep-dive-luna`, 커밋 58c8cdd)이고, DEC-017/018 이식분을 함께 담았다.
아래는 결정 당시의 선택지 기록이다.

- **A. 구조 분해 2탄**: strengths/weaknesses 항목을 `{text, location}` 객체로 바꿔 "근거 위치(섹션/그림/표)를 함께 적어" 지시를 자유서술 밖으로 이전. 발생률을 더 낮추지만 0 보장은 아님. 렌더러 3곳 + 잠금 테스트 수정 동반.
- **B. deep_dive만 Luna로**: Luna는 누적 42/42 무폭주, 비용 절반, 단 단계당 약 1분 느림. `feat/provider-neutral-llm` 브랜치의 model_registry와 정합 필요(그 브랜치 인수인계: `docs/superpowers/plans/2026-08-23-provider-neutral-main-integration-handoff.md`).

## 깨면 안 되는 계약

1. `_DEEP_DIVE_SCHEMA` 마지막 속성은 자유서술 문자열 금지(DEC-014 원칙 공유). 잠금 테스트가 막는다.
2. deep_dive 지시문에 "평가임을 명시해"류의 정형 문구 반복 요구를 되살리지 말 것(`test_instruction_does_not_demand_phrase_echo`).
3. comparison_scope는 값 하나짜리 required enum이 의도다. "무정보성"이 목적(문법이 종료를 강제하는 자리).
4. 상한 16,000의 근거: 정상 최대 8,734의 1.8배, 폭주 손해 $0.06 상한. 낮추려면 RT-1의 14.5k completed 경계 사례를 먼저 설명할 것.
5. 구 캐시(detailed_analysis) 렌더러 폴백을 지우지 말 것 — DB에 구 형식 행이 남아 있다.
6. 지시문 변경은 곧 캐시 키 변경 = 재과금. PR 본문에 고지 필요(DEC-011 관례).

## 유예·미검증 항목

- as-is 구도가 없는 논문에서 as_is/to_be가 빈 문자열로 나오는지 미검증(실측 논문들이 전부 공학 프레이밍 보유).
- 수렴 처방 중 미적용 2건: 목록 필드 개수 대역 명시, 분량 지시의 자수 전환(RESEARCH 문서 3장 2·4번).
- ~~`tools/provider_compare.py`의 deep_dive openai_effort "xhigh" 매핑~~ — 2026-08-30 확인 결과 해소돼 있다. `model_registry`의 deep_dive는 gemini·openai 양쪽 다 `high`이고, 그 파일에 남은 `--efforts high,xhigh`는 effort **비교 모드**의 CLI 사용 예시라 정정 대상이 아니다.
- Semantic Scholar 조회 시 시스템 python3는 SSL 인증서 오류가 나므로 curl을 쓸 것.

## 실측 재현 방법

하네스는 `RESEARCH/2026-08-29-chain-compare/harness/`에 보존돼 있다(원본은 잡 임시 디렉토리라 소멸 예정). `chain_compare_multi.py`가 다논문 러너이고, 경로 상수(BACKEND, PDF_DIR, OUT)를 맞춘 뒤 `sasoo/backend/.venv/bin/python`으로 실행한다. 키는 sasoo 설정 DB에서 자동 복호화된다. VLA PDF 7편은 잡 디렉토리(`~/.claude/jobs/63a3bb36/tmp/vla_pdfs/`)에 있으므로 필요하면 arXiv에서 재다운로드(ID는 harness 주석과 RESEARCH 문서 참조).
