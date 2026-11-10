# 분석 병렬 실행 적용 및 검증

후속 실제 API, 설치 앱, 프로세스 및 원문 품질 검증은 [실측 검증 보고서](2026-10-11-parallel-analysis-live.md)에 기록했다. 아래 내용은 실측 전 구현 검증 시점의 기록이다.

2026-10-11. 추천한 보수적 병렬 실행 구조를 적용했다. 기존 포인트별 분석과 단계 간 문맥 전달을 유지하면서 독립적인 대기 구간을 겹쳤다. 이 작업에서 모델, effort, 분석 스키마, 생성 프롬프트, 이미지 선택 기준은 변경하지 않았다. 같은 작업 폴더에서 별도로 진행 중인 전문용어/읽기 안내 변경은 보존했다.

## 적용한 실행 구조

| 구간 | 실행 방식 |
|---|---|
| 스크리닝 이후 | 시각 자료가 `ready`이고 갱신 중이 아니면 인용 분석과 시각 분석을 병렬 실행한다. 시각 입력을 먼저 고정한다. |
| 시각 자료가 준비되지 않은 경우 | 기존 인용 분석 → 시각 분석 순서를 유지하고 시각 분석 시점에 입력을 다시 읽는다. 무기한 준비 대기는 추가하지 않았다. |
| 레시피와 심층 분석 | 이전 단계 결과가 필요하므로 기존 순서를 유지한다. |
| 심층 분석 이후 | 같은 이전 결과를 종합 생성과 시각화 계획에 전달하고 두 작업을 병렬 실행한다. |
| 시각화 계획 이후 | Mermaid, HTML, 이미지 작업을 겹친다. 이미지끼리는 순차 실행하고 기존 요청 간 2초 간격을 유지한다. |
| 결과 저장 | 완료된 항목을 하나의 수집기가 차례로 저장한다. 화면에서는 먼저 끝난 결과부터 표시한다. |

주요 구현은 [analysis_execution.py](../../sasoo/backend/services/analysis_execution.py), [figure_gen.py](../../sasoo/backend/services/viz/figure_gen.py), [analysis_routes.py](../../sasoo/backend/api/analysis_routes.py)에 있다. 화면에서는 [AnalysisPanel.tsx](../../sasoo/frontend/src/components/AnalysisPanel.tsx)와 [SynthesisView.tsx](../../sasoo/frontend/src/components/synthesis/SynthesisView.tsx)의 대기 조건을 전체 분석 상태에 맞췄다. 자동 종합 생성 중 수동 생성 버튼이 나타나던 조건도 수정했다.

## 저장, 취소, 완료 조건

- 기존 캐시와 성공한 시각화 항목을 재사용한다. 순서가 달라도 최종 항목 ID 순서와 요청별 사용량 기록을 보존한다.
- 사용자 취소는 시작한 작업 결과를 회수하고 다음 이미지 생성을 막는다. 불명 비용은 불명으로 남긴다.
- 워커가 실행 권한을 잃어 강제 취소되면 자식 작업을 종료하고 늦은 저장을 차단한다. 저장 재시도에서도 `run_token`이 바뀌었으면 새 실행의 결과를 덮어쓰지 않는다.
- 저장이 일시 실패해도 이미 시작된 형제 작업의 결과를 회수해 미완료 상태로 저장한 뒤 원래 오류를 전달한다. 계속되는 DB 장애의 복구를 보장하는 기능은 아니다.
- 이미지 요청이 시간 초과되거나 대기 작업이 취소돼도 실제 공급자 스레드가 끝나기 전에는 이미지 동시 실행 슬롯을 반환하지 않는다.
- 종합 또는 시각화 한쪽이 먼저 끝났다고 전체 분석을 완료하지 않는다. 활성 작업의 API 진행률은 100% 미만으로 제한하며, 기존 선택적 생성 실패 처리 정책은 유지한다. 화면의 5/5는 주요 분석 단계 수이고 전체 완료 여부는 별도 실행 상태가 결정한다.

## 검증 결과

| 검증 | 결과 |
|---|---|
| 전체 백엔드 `pytest services api models` | 1,158 passed, 268 subtests passed, 4 skipped, 102.67초 |
| 백엔드 skip 사유 | 임시 DB에 실제 recipe 결과가 없어 기존 Evidence 회귀 검사 4개를 건너뜀 |
| 백엔드 경고 | 기존 SWIG/genai/datetime 관련 deprecation 44건 |
| 독립 수정 검증 | 실제 함수 본문을 추출한 6개 검사 통과. 강제 취소, 실행 소유권 교체, 일시 저장 실패, 사용자 취소 검증 |
| 관련 프런트엔드 테스트 | 7개 파일, 84개 테스트 통과 |
| 타입 검사 / 린트 / 프로덕션 빌드 | 모두 통과 |
| 브라우저 | 1440×900 / 1024×900, 2개 도착 순서, 8개 상태 캡처 통과 |

백엔드 테스트는 임시 앱 데이터 경로와 빈 API 키를 사용하고 소켓 연결을 차단했다. 신규 회귀 검사는 [test_analysis_parallel.py](../../sasoo/backend/services/test_analysis_parallel.py)에 있다. 시간 차이로 병렬성을 추측하지 않고, 각 작업의 시작/종료 이벤트를 제어해 겹치는 실행과 조기 저장, 전체 합류를 검증한다.

브라우저는 현재 앱을 실행하되 기존 저장 응답을 주입했다. 시각화가 먼저 도착하는 순서와 종합이 먼저 도착하는 순서 모두 후속 결과의 자동 갱신을 확인했다. 진행 중에는 완료 표시가 나오지 않고 마지막에 완료 상태로 전환됐다. 예상 밖 런타임/콘솔 오류, 가로 넘침, 쓰기 요청, 외부 네트워크 요청은 0건이다. 아직 없는 종합 응답의 의도된 HTTP 404는 별도로 기록했다. 그림 파일은 로컬 대체 이미지다.

- [브라우저 재현 코드](assets/parallel-analysis-20261011/run_gui.py), [상태와 요청 기록](assets/parallel-analysis-20261011/gui-evidence.json), [검증 요약과 소스 해시](assets/parallel-analysis-20261011/validation-summary.json)
- [시각화가 먼저 표시된 화면](assets/parallel-analysis-20261011/1440-visual-first-stage0.png)
- [종합 결과가 먼저 표시된 화면](assets/parallel-analysis-20261011/1024-synthesis-first-stage0.png)
- [최종 완료 화면](assets/parallel-analysis-20261011/1024-synthesis-first-stage3.png)

브라우저 재현은 `sasoo/frontend`에서 `pnpm exec vite --host 127.0.0.1 --port 5178 --strictPort`를 실행한 뒤, 저장소 루트에서 `python3 docs/validation/assets/parallel-analysis-20261011/run_gui.py`로 수행한다. Python Playwright/Chromium이 필요하다. 검증용 서버는 작업 후 종료했다.

독립 리뷰가 발견한 두 문제(이전 워커의 늦은 저장, 일시 저장 실패 시 형제 결과 유실)는 수정한 뒤 다시 검증했다. handoff 및 독립 증거는 OS 임시 폴더 `/var/folders/tv/bvyx2h2x1817d915v2jhwhsm0000gn/T/sasoo-parallel-handoff-20261011-6o8f53qd/`의 `IMPLEMENTATION_REVIEW.md`, `VERIFY_FIX.md`에 남겼다.

학습 메모: 병렬화의 단위는 서로의 출력을 기다리지 않는 작업이다. 결과 생성은 동시에 하더라도 저장 주체와 전체 완료 조건은 한곳에서 관리해야 한다. 시작 이벤트와 저장 결과를 함께 검사하면 실제로 겹쳐 실행되는지 재현할 수 있다. 화면의 부분 완료를 전체 완료로 해석하거나 강제 취소를 과금 취소로 해석하는 것이 주요 함정이다.

미검증: 실제 유료 API 속도/비용/답변 품질 비교, 설치된 Electron 앱, 실제 프로세스 교체 실험. 커밋과 배포는 수행하지 않았다.
남은 한계: 이미 발행된 외부 요청은 강제 취소 후에도 실행되거나 과금될 수 있다. 실제 시간 단축률은 공급자 제한과 논문별 작업 비중에 따라 달라진다.
