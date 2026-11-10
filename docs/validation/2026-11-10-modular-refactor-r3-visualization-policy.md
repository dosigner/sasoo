# 모듈 리팩토링 R3 시각화 선택 규칙 분리

2026-11-10에 R3를 완료했다. 시각화 계획의 점수와 형식 검사, 항목 선택과 생성 전 제한을 별도 모듈로 옮겼다. 선택 결과, 모델, 실행 흐름과 저장 동작을 변경하는 작업은 포함하지 않았다. R1은 보존했고 R4 이후와 F1-F9는 이번 구현에 포함하지 않았다.

## 구현 범위와 이유

- `sasoo/backend/services/visualization_policy.py`에 `_viz_score`, `_viz_plan_shape_error`, `_normalize_viz_plan`, `_gate_viz_items`와 `_VIZ_CORE_PURPOSES`, `_MERMAID_RENDERABLE_TYPES`를 옮겼다. 최상위 함수는 4개이며 `_normalize_viz_plan` 안의 `importance` 보조 함수도 함께 이동했다.
- `sasoo/backend/services/analysis_execution.py`는 네 함수와 두 상수를 import해 기존 이름으로 제공한다. 기존 테스트와 `tools/quality_compare.py`가 사용하는 `ae._gate_viz_items` 등의 경로를 유지했다.
- `_plan_visualizations`, `_run_visualization_items`, 모델 호출, checkpoint와 사용량 저장은 기존 위치에 남겼다. 실행 함수의 전역 이름을 통해 테스트가 대체 함수를 넣는 기존 구조도 유지했다.
- `_visualization_cache_input`은 모델 설정과 기존 `resolve_model`, 모델 상수 patch 검사에 연결돼 있으므로 이동하지 않았다. 본문과 `images-124-sequence-3-html-5-v2-sunburst` 정책 문자열은 그대로다.

이동한 함수 본문의 소스 문자열과 AST(연산과 분기를 표현한 코드 구조), 두 상수의 AST가 변경 전과 일치함을 확인했다. 이동한 정의와 새 import를 제외한 `analysis_execution.py`의 나머지 AST도 전체가 같다. 비교 결과와 소스 이동 diff는 아래 검증 자료에 보관했다.

## 기준선과 검증 결과

기준 HEAD는 `3d0e7d20abf251341ca4396eeb8dc981e2b0b643`이다. 실제 비교는 R1과 기존 미커밋 작업을 포함한 파일 상태에서 수행했다. R3 대상과 관련 시각화 테스트, JSON fixture는 사용자가 선택한 2026-11-09 스냅샷 및 R1 검증본과 바이트가 일치했다. R1의 두 제품 파일은 R1 검증본과 일치했다.

환경은 기존 backend 가상환경의 Python 3.14.6, FastAPI 0.141.1, Pydantic 2.13.5다. 제품 코드를 바꾸기 전에 집중 검사와 전체 검사를 실행했고, 코드 이동 후 같은 기대값으로 다시 실행했다.

| 검사 | 변경 전 | 변경 후 |
|---|---|---|
| 시각화와 API, 캐시 등 집중 검사 | 366 passed, 42 subtests passed | 366 passed, 42 subtests passed |
| `pytest services api models tools --disable-warnings -q` | 1,359 passed, 7 skipped, 236 subtests passed | 1,359 passed, 7 skipped, 236 subtests passed |
| `py_compile main.py services/analysis_execution.py services/visualization_policy.py` | 새 모듈 생성 전에는 실행 안 함 | 통과 |
| 독립 import와 기존 경로의 객체 동일성 | 새 모듈 생성 전에는 실행 불가 | 네 함수와 두 상수 모두 통과 |
| Python 가드가 관찰한 외부 연결 시도 | 집중 0건, 전체 2건 | 집중 0건, 전체 2건 |

집중 검사는 `test_viz_plan_snapshot_contract.py`, `test_viz_plan_contract.py`, `test_synthesis.py`, `test_viz_costs.py`, `test_viz_partial_retry.py`, `test_analysis_completion.py`, `test_schema_hash_contract.py`, `test_instruction_contract.py`, `test_quality_preflight.py`, `api/test_analysis_routes.py`, `api/test_openapi_contract_snapshot.py`, `tools/test_quality_compare.py`다. 기존 테스트와 기대값, Markdown/JSON fixture는 수정하지 않았다. 이번 검사에서 테스트 실패는 없었다.

주요 관측은 다음과 같다.

- 기존 계획 스냅샷에서 항목 순서, 60/70점 경계, 문자열과 bool 및 NaN 점수, 중복 core, 과거 계획 제한과 모델 선택이 유지됐다.
- 과다한 과거 계획을 넣는 기존 모의 생성 검사는 이미지 5회(Sunburst 1회), Mermaid 2회, HTML 1회를 변경 전후 동일하게 확인했다. 다른 기존 검사에서는 이미지 5개, Mermaid 3개, HTML 1개 선택 상한과 중요도 조건을 확인했다.
- 계획 실패 시 모의 생성 호출은 0회이며 완료 결과를 저장하지 않는 기존 검사가 통과했다. 부분 재시도와 성공 항목 재사용, 시각화 비용 및 API 회귀도 통과했다.
- 모델 또는 품질을 바꾸면 캐시 값이 달라지는 기존 검사, schema 7종과 기본 지시문 해시, OpenAPI 스냅샷이 그대로 통과했다.
- 새 모듈만 import한 시점에는 DB, 설정, 파서와 실행 모듈이 로드되지 않았다. 실행 모듈을 이어서 import한 뒤 네 함수와 두 상수가 양쪽 경로에서 동일한 객체임을 확인했다.

전체 검사에서 가드가 차단한 2건은 기존 `test_network_guard.py`의 `connect`, `connect_ex` 양성 대조다. 이 집계는 가드가 감싸는 Python 메서드 범위이며 모든 자식 프로세스의 연결 시도를 전수 계측한 값은 아니다.

## 격리와 작업 보존

실행마다 별도 HOME, `SASOO_APP_DATA_ROOT`, 임시 폴더, Java 임시 경로를 지정했다. 공급사 키, 실제 `.env`, 사용자 라이브러리는 복사하거나 전달하지 않았다. 필요한 기존 고정 자료와 Java 런타임을 복사한 소스에서 실행했다. macOS sandbox는 외부 송신과 작업 임시 루트 밖의 쓰기를 차단했다. 독립 프로브에서 TEST-NET-1 연결과 루트 밖 쓰기가 거부되고, loopback과 Unix socket 연결은 허용되는 것을 확인했다.

시작 시 Git이 인식하는 기존 파일 23,428개의 SHA-256 또는 심볼릭 링크 대상, 파일 모드와 Git 상태를 기록했다. 마지막 비교에서는 기존 제품 파일 변경이 `analysis_execution.py` 하나에 한정되고, R1 파일과 기존 테스트, 고정 자료 및 나머지 작업이 보존됐는지 확인했다. 새 제품 파일은 `visualization_policy.py` 하나이며 문서와 검증 자료를 별도로 추가했다. 최종 목록은 `workspace-preservation.json`에 있다. reset, stash, clean, stage, 기존 데이터 삭제, 커밋과 릴리스는 수행하지 않았다.

임시 실행 루트는 `/private/tmp/sasoo-refactor-r3-kj11szos/`다. 임시 폴더가 남아 있는 동안 다음 명령으로 재현할 수 있다.

```bash
python3 /private/tmp/sasoo-refactor-r3-kj11szos/run_checks.py before focused
python3 /private/tmp/sasoo-refactor-r3-kj11szos/run_checks.py after focused
python3 /private/tmp/sasoo-refactor-r3-kj11szos/run_checks.py before full
python3 /private/tmp/sasoo-refactor-r3-kj11szos/run_checks.py after full
python3 /private/tmp/sasoo-refactor-r3-kj11szos/run_checks.py after boundaries
```

최종 로그, 격리 프로브, import 경계 검사와 실행 스크립트, 소스 비교 결과, 이동 diff와 작업 보존 결과는 [`assets/refactor-r3-20261110/`](assets/refactor-r3-20261110/)에 보관했다. 전체 최초 파일 해시와 변경 전후 소스는 임시 실행 루트에 있으며 임시 폴더의 장기 보존은 보장하지 않는다.

## 한계와 다음 작업

검증한 것은 합성 및 고정 입력에 대한 기존 선택과 호출 계약의 보존이다. 실제 공급사 생성, 청구, 과학적 정확성이나 시각화 품질을 검증한 것은 아니다. Python 3.12 CI, Windows, 외부 스크립트 및 API 소비자, 실제 사용자 DB와 라이브러리, Electron GUI와 패키징 앱은 미검증이다.

다음 작업은 R4다. Mermaid 정리, 인용 선택과 캐시, 종합 결과 검증을 한 묶음씩 처리한다. 각 묶음의 기존 출력과 patch 경로를 먼저 고정하고, 프롬프트와 실제 동작 변경은 분리한다.

학습 메모: 선택 함수는 값을 계산하지만 그 출력이 유료 생성 요청의 개수와 모델을 정한다. 이동할 때는 선택 결과뿐 아니라 모의 호출 횟수와 모델, 캐시 계약을 함께 비교해야 한다. 기존 함수의 import 이름만 남겨도 내부 의존성이 달라질 수 있으므로 호출자와 설정 의존을 함께 확인하는 것이 재사용할 원칙이다.
