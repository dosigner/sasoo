# 통합 리팩토링 계획의 근거 기록

대상 계획: `docs/superpowers/plans/2026-11-09-sasoo-modular-refactor-master-plan.md`.

이 문서는 총괄 에이전트가 subagent 보고를 실제 코드로 다시 확인한 기록입니다. 모든 확인은 읽기 전용입니다. 테스트, 앱, 빌드, 공급사 호출, migration은 실행하지 않았습니다. 사용자 DB, 라이브러리, `backend/.env` 내용은 열지 않았습니다. 민감 정보와 공급사 응답은 복사하지 않았습니다.

## 환경

- 저장소 HEAD: 3d0e7d2. 작업 트리에 추적 파일 수정과 미추적 파일이 함께 있습니다(`git status --short` 381줄, 미추적 327줄, 2026-11-09 측정).
- sandbox에서 git이 `~/.gitconfig`를 읽지 못해 `GIT_CONFIG_GLOBAL=/dev/null`로 실행했습니다.
- graphify-out의 `build-summary.json`은 2026-09-25 생성입니다. 근거로 쓰지 않았습니다.

## 총괄 재확인 항목

| 주장 | 출처 영역 | 확인 방법 | 결과 |
|---|---|---|---|
| 병렬 실행과 완료 계약이 HEAD에 없음 | 1 | `git show HEAD:.../analysis_execution.py`와 작업 트리에서 `_run_parallel`, `_completion_checks`, `planned_items`, `_run_visualization_items` 개수 비교 | HEAD 0/0/0/0, 작업 트리 3/4/3/2. 줄 수 4033과 4214 |
| 라이브 비용이 unknown을 0으로 더함 | 1, 6 | `grep 'total_cost_usd += '` | 14곳 |
| `analysis_completion.py`, `analysis_manifest_store.py`가 미추적 | 1, 5 | `git status --short` | `??` 확인 |
| worker가 artifact refresh를 조건 없이 schedule | 3 | analysis_execution.py:3864-3867 읽기 | `await schedule_paper_artifacts_refresh(...)`를 try로만 감쌈 |
| artifact task 등록부가 프로세스 전역 | 3 | odl_parser.py:68-70 읽기 | 모듈 전역 dict와 `asyncio.Lock` |
| 업로드도 artifact refresh를 schedule | 3 | api/papers.py grep | 281행 |
| 월 키 계산 | 2, 6 | api/settings.py:465-469 읽기 | `datetime.utcnow() - timedelta(days=30 * i)` |
| Gemini usage 누락을 0으로 대체 | 6 | gemini_client.py:201-208 읽기 | `getattr(..., 0) or 0` |
| 취소 뒤 polling 정지 조건 | 4 | useAnalysis.ts:339-345 읽기 | completed와 error만 |
| Mermaid repair 시도 기록이 컴포넌트 ref | 4 | MermaidRenderer.tsx grep | 335, 375, 377행 `useRef` |
| 논문 전환 시 Workbench 재마운트 | 4 | App.tsx:100-105 읽기 | `key={location.pathname}` |
| OpenAI SDK 재시도를 끄는 곳 | 6 | openai_client.py grep | 282, 346행 `with_options(max_retries=0)`, `single_attempt` 분기 |
| 테스트 네트워크 차단 없음 | 6 | backend 아래 conftest 목록과 `socket`, `pytest-socket` grep | `services/conftest.py` 하나, 차단 코드 없음 |
| `backend/.env` 존재 | 6 | `test -f` | 존재. 내용은 읽지 않음 |
| SDK 전송 횟수 테스트의 전송 방식 | 계획 7절 | test_openai_client.py:885-915 읽기 | `httpx2.MockTransport`, socket 미사용 |

## subagent 주장 중 총괄이 재확인하지 않은 항목

아래는 subagent의 정적 읽기 결과이며 총괄은 행을 다시 열지 않았습니다. 계획 문서에서 영역 번호와 함께 인용했습니다.

1. route 39개 목록과 미들웨어 순서(영역 2).
2. `/status`의 레거시 `error` 판정과 이를 고정하는 테스트 행(영역 2).
3. migration `except Exception: pass` 11곳(영역 2).
4. figure/table sync의 commit 단위와 설명 보존 방식, 재시도 번호 충돌(영역 3).
5. IPC 11채널과 발신자 검증 3채널, updater 창 고정, activate 경합(영역 5).
6. AGENTS.md와 CI의 차이 6건(영역 5).
7. google-genai Interactions 기본 `max_retries=3`(영역 6, `.venv` 안 SDK 소스).
8. 월별 집계와 예산이 `analysis_results`만 읽는다는 점(영역 6).
9. 테스트 patch 문자열 개수(영역 1, 6). 영역 1과 영역 6의 `call_interaction` 개수가 51과 54로 다릅니다. 집계 범위(services만, 전체 backend)의 차이로 추정하며 확인하지 않았습니다.

## 실행하지 않은 것

pytest, vitest, tsc, lint, 빌드, Electron, 패키징, 공급사 호출, migration, 실제 사용자 데이터 열람. 따라서 이 문서의 어떤 항목도 실행 결과가 아닙니다.
