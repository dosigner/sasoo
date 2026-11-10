# AI-Scientist-v3의 단계별 산출물 계약 적용

2026-11-03. Sasoo의 기존 분석 항목, 모델, effort, 프롬프트 깊이, 병렬 실행 구조를 유지하면서 저장 결과의 완료 판정을 보강했다. 논문 비교 UI/API/스키마, 추가 모델 호출, 자동 재분석, 릴리스는 이 작업에 포함하지 않았다.

## 확인한 upstream과 채택한 원칙

대상 저장소는 SakanaAI/AI-Scientist-v3, 고정 commit은 `df8313889a004f8a44a472e19a833cd547bb828a`다. 별도 임시 디렉터리에서 소스를 읽었으며 upstream 프로그램은 실행하지 않았다. 읽은 주요 파일의 SHA-256은 [preservation-check.json](assets/analysis-completion-20261103/preservation-check.json)에 기록했다.

- [src/pipeline/cli.py:1328](https://github.com/SakanaAI/AI-Scientist-v3/blob/df8313889a004f8a44a472e19a833cd547bb828a/src/pipeline/cli.py#L1328): investigation 프로세스가 정상 종료해도 결과 검증을 별도로 수행한다. 검증이 성립할 때 완료 receipt를 기록하며, 잘못된 상태는 후속 단계의 성공으로 넘기지 않는다.
- [src/pipeline/config.py:1489](https://github.com/SakanaAI/AI-Scientist-v3/blob/df8313889a004f8a44a472e19a833cd547bb828a/src/pipeline/config.py#L1489), [같은 파일:1566](https://github.com/SakanaAI/AI-Scientist-v3/blob/df8313889a004f8a44a472e19a833cd547bb828a/src/pipeline/config.py#L1566): 사용 가능한 산출물, 검증 플래그, 유한한 점수를 검사하고 manifest SHA-256과 일치하는 완료 receipt를 확인한다. 탐색 종료와 과학적 성과의 성공도 구분한다.
- [src/investigation/run_checkpoint.py:1](https://github.com/SakanaAI/AI-Scientist-v3/blob/df8313889a004f8a44a472e19a833cd547bb828a/src/investigation/run_checkpoint.py#L1): checkpoint는 실행 보존 수단이며 그 자체가 과학적 완료 증거는 아니다. checkpoint의 열화가 실행의 종료 코드를 바꾸지는 않는다.
- [docs/pipeline.md](https://github.com/SakanaAI/AI-Scientist-v3/blob/df8313889a004f8a44a472e19a833cd547bb828a/docs/pipeline.md), [docs/paper_final_outcomes.md](https://github.com/SakanaAI/AI-Scientist-v3/blob/df8313889a004f8a44a472e19a833cd547bb828a/docs/paper_final_outcomes.md): resume은 같은 run 디렉터리를 기준으로 하며, 일부 보조 단계는 degraded로 남긴다. 완결된 비적격 결과와 누락/실패/미완료 결과를 구분한다.

Sasoo에는 “실행 종료와 검증된 산출물의 준비 상태를 분리한다”, “성공한 산출물을 보존하고 부족한 상태를 설명한다”는 원칙을 적용했다. upstream의 실험 프레임워크, receipt/전체 이력 저장소, 논문 작성 파이프라인을 이식한 것은 아니다. 기존 graphify 지도는 경로를 찾는 용도로만 사용하고 현재 소스로 호출 관계를 재확인했다. REA 스킬의 일반 소스 저장소 분석 지침에 따라 바이너리 분석 엔진은 설치하지 않았다.

## 현재 입력과 의존 관계

`analysis_execution.py`의 `run_full_analysis`가 기존 실행 순서를 유지한다.

1. screening은 전용 텍스트를 소비하고 분야와 적용 여부를 판정한다.
2. citation은 본문/참고문헌/섹션을 소비한다. visual은 PDF 또는 본문과 추출된 그림/표를 소비한다. 시각 자료 준비 상태가 허용하면 두 단계는 기존처럼 병렬 실행된다.
3. recipe는 원문과 앞선 단계 결과를 소비한다. deep_dive는 원문과 앞선 결과를 소비하며, 별도 공급사를 선택한 기존 동작도 유지한다.
4. synthesis와 visualization은 원문과 수집한 분석 결과를 공유하며 기존처럼 병렬 실행된다. 한쪽 실패로 이미 발행된 다른 쪽 작업을 취소하지 않는다.
5. 기존 screening gate가 recipe와 deep_dive를 모두 건너뛰면 synthesis/visualization도 실행 대상에서 제외한다. 시스템이 기록한 skip 사유가 있어야 이 예외를 인정한다.

완료 판정은 실행 순서를 추가하거나 누락 단계를 자동 실행하지 않는다.

## Sasoo의 최소 산출물과 완료 기준

아래 항목은 저장 결과에 적용하는 최소 계약이다. 기존 응답 스키마 전체의 의미, 원문 해석, 과학적 정확성을 검증하는 목록은 아니다. 빈 배열은 원래 스키마와 맞춰 허용하며, 결과를 채우기 위해 논문에 없는 내용을 요구하지 않는다.

| 단계 | 필수 저장 산출물 | 추가 완료 조건 |
|---|---|---|
| screening | `domain`, `summary`, `key_topics` | 비어 있지 않은 분야/요약 문자열과 주제 배열 |
| citation | `total_references`, `top_cited`, `citation_distribution` | 로컬 인용 통계의 정수/배열/객체 형식. LLM 실패 envelope는 실패로 유지 |
| visual | `quality_summary`, `key_findings_from_visuals` | 저장된 기존 visual artifact 상태가 partial/error/running이면 전체 준비로 세지 않음 |
| recipe | `title`, `objective`, `parameters`, `steps` | 필수 문자열/배열이 존재. 시스템의 명시적 적용 제외 사유는 skip으로 분리 |
| deep_dive | `problem_definition`, `method_summary`, `key_results`, `section_answers`, `transfer_checks` | 기존 `validate_summary_extensions`를 재사용해 답변/조건의 구조와 출처 필드를 검사 |
| synthesis | `problem_sentence`, `method_sentence`, `key_metrics`, `equations`, `result_figures`, `key_parameters` | 누락이나 실패 응답을 별도로 표시. JSON 파싱 실패도 원문/사용량과 함께 저장 |
| visualization | `items` | 실행 종료, 모든 항목 성공, 도구별 코드/이미지 존재, 생성 이미지 파일의 실제 제공 경로 확인. 명시된 실행 검사 실패는 차단 |

모든 단계에서 JSON 객체, 오류 envelope, 응답 미완료, 복구한 부분 결과, 필수 값 형식을 검사한다. `_input_coverage.status=partial`이면 준비 완료로 세지 않는다. 과거 저장 결과에 필요한 필드가 없으면 삭제하거나 자동 재생성하지 않고 partial로 표시한다.

시각화에는 추가 예외가 있다.

- 빈 결과는 `planned_empty=true`인 명시적 생성 제외 계획이 있어야 인정한다.
- `complete=false`인 checkpoint, 실패 항목, 누락된 코드/이미지, 계획 수와 저장 수 불일치는 partial이다.
- 새 viz_plan이 실패했는데 이전 visualization만 남은 경우 이전 결과로 이번 시각화가 완료됐다고 판정하지 않는다.
- HTML 실행 검사가 없거나 timeout인 경우 기존 재사용 정책을 유지한다. 산출물 확인을 HTML 실행 검증 성공으로 해석하면 안 된다.

## 구현과 사용자 표시

- `backend/services/analysis_completion.py`: 일곱 단계의 순수 판정 함수. 결과를 수정하거나 모델을 호출하지 않는다. 기존 summary 검증기와 실행기의 시각화 재사용 검사를 재사용한다.
- `backend/services/analysis_execution.py`: 잘린 JSON 복구/손상 필드 제거에 `_partial`을 남긴다. 종합 실패를 저장하고, 마지막 완료 판정을 저장 결과의 공통 검사로 결정한다. 시각화 예외를 무시한 전체 completed를 방지한다.
- `backend/api/analysis_routes.py`: 인메모리 완료 표시로 검사를 우회하지 않고 같은 저장 결과를 검사한다. 실행 중인 단계, 취소 상태, 기존 모델 변경 배지와 실시간 사용량 집계는 유지한다.
- `backend/models/schemas.py`, `frontend/src/lib/api.ts`: 기존 5개 phase enum을 확장하지 않고 별도 `completion_checks`를 추가했다. 각 항목은 상태, 이유, 필수 키, 저장 result ID를 담는다.
- `frontend/src/components/AnalysisPanel.tsx`: 접을 수 있는 “단계별 산출물 확인”을 추가했다. 성공/건너뜀/부분/누락/실패를 설명한다. 목록은 높이를 제한하고 키보드 스크롤을 지원한다.
- `frontend/src/lib/workbenchSummaries.ts`, `hooks/useAnalysis.ts`: 일곱 단계 기준 준비 비율을 표시한다. partial 레시피와 기존 결과를 계속 읽고, result ID 또는 산출물 상태가 바뀌면 결과를 다시 가져온다. 새로운 분석 요청은 보내지 않는다.

진행률은 시간 추정이 아니라 준비된 단계 비율이다. 예를 들어 5개 분석 결과가 있고 종합이 없으며 시각화가 중간 저장 상태라면 `5/7`, 약 `71.43%`다. 전체 미완료/실패/취소를 100%로 표시하지 않는다. API의 기존 `error` 상태를 사용하며 UI는 남은 결과가 있으면 “부분 완료”로 설명한다.

## 검증 결과

- 백엔드 전체: `./.venv/bin/python -m pytest services api models -q --tb=short`에서 **1,226 passed, 269 subtests passed**. 전체 실행 뒤 보강한 회귀 사례와 최종 상태 변경은 관련 파일 재실행으로 확인했다.
- 최종 백엔드 관련 회귀: `services/test_analysis_completion.py`, `api/test_analysis_routes.py`, `services/test_analysis_parallel.py`, `services/test_viz_partial_retry.py`, `services/test_analysis_results.py`에서 **254 passed, 20 subtests passed**.
- 프런트엔드: `pnpm test`에서 **45 files, 377 tests passed**. `pnpm tsc --noEmit`, `pnpm build`, `pnpm lint`, 앱의 `pnpm build:electron` 통과.
- 잘린 응답 복구는 1회 mock 호출만 사용하고 원문/토큰을 유지하면서 partial로 판정함을 검사했다. 실패한 새 계획이 과거 성공 시각화에 가려지지 않는 경우, 시스템 skip, malformed JSON, 누락 이미지, 실패한 HTML 실행 검사, 취소 유지, 인메모리/저장 상태의 일치도 검사했다.
- 실제 개발 Electron + 현재 FastAPI + 격리 SQLite fixture로 완료, 부분 결과, 종합 실패, 취소, 과거 형식을 확인했다. 정상 결과는 100%, 부분 결과는 71.43%, 종합 실패/과거 형식은 85.71%, 취소는 cancelled 상태였다.
- 1,440px와 1,024px에서 확인 목록의 실제 좌우/하단 경계를 검사했다. 목록을 키보드 End/Home으로 스크롤할 수 있었고 문서의 가로 넘침, JavaScript page error, 모델 생성/변경 요청은 없었다.
- `git diff --check` 통과. 기존 Python/라이브러리 deprecation warning은 남아 있다.

GUI는 최신 프런트엔드를 빌드한 뒤 `node docs/validation/assets/analysis-completion-20261103/run.mjs`로 재현한다. 이 스크립트는 새로운 임시 DB/프로필을 만들고 외부 네트워크 및 생성/변경 API를 차단한다. 로컬 Playwright 설치 경로는 스크립트 상단에 명시돼 있다.

증거: [GUI 판정 JSON](assets/analysis-completion-20261103/gui-checks.json), [부분 결과 1,024px](assets/analysis-completion-20261103/electron-partial-1024.png), [완료 화면](assets/analysis-completion-20261103/electron-complete-1440.png), [종합 실패 화면](assets/analysis-completion-20261103/electron-failed-1440.png).

## 보존과 남은 경계

시작 당시 tracked 파일과 ignore되지 않은 untracked 파일 **23,356개**의 SHA-256을 수집했다. 최종 확인에서 기존 파일 **23,345개는 동일**, 이 작업 대상 **11개만 변경**, 삭제된 파일은 **0개**였다. 수정 대상의 시작 사본은 임시 baseline 디렉터리에 보존했다. 확인 범위와 전후 hash는 [보존 기록](assets/analysis-completion-20261103/preservation-check.json)에 있다. reset/stash/clean/일괄 staging을 수행하지 않았다.

현재 계약은 최신 저장 행을 판정한다. 전체 실행의 불변 snapshot, 원문 변경에 따른 모든 downstream 결과의 hash 검증, 모든 과거 결과의 완전한 재검증은 구현하지 않았다. 기존 모델 변경 배지는 유지하지만 모든 입력의 최신성을 보증하지 않는다. 기존 `artifact_status.py`의 추출 준비 계약과 새 분석 산출물 계약은 서로 다른 책임을 가진다.

새 모듈의 완료는 **산출물이 최소 형식과 준비 조건을 충족했다는 뜻**이다. 원문에 대한 독립 과학 검토, 공급사 응답 품질, packaged app/릴리스 검증은 이번 fixture/개발 Electron 결과로 입증되지 않는다. 유료 호출과 배포는 실행하지 않았다.
