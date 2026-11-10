# 모듈 리팩토링 R1 보고서 조립 분리

2026-11-10에 인계 문서의 첫 구현 R1을 완료했다. 조회와 HTTP 응답 처리는 기존 route에 남기고 Markdown 조립만 분리했다. R3 이후와 F1-F9의 동작 변경은 이번 구현에 포함하지 않았다.

## 변경과 보존한 계약

- `sasoo/backend/api/report_service.py`에 `build_report_markdown(paper: dict, latest_results: dict[str, dict]) -> str`을 추가했다. 기존 `get_report`의 메타데이터, 단계별 본문과 사용량, 비용 합계 조립을 그대로 옮겼다.
- `sasoo/backend/api/analysis_routes.py`의 `get_report(paper_id)`는 논문과 최신 결과 조회, 두 종류의 404, `ReportResponse` 생성과 `_utcnow_iso()` 호출을 유지한다. 조회한 두 값을 조립 함수에 전달한다.
- 기존 `_format_phase_data`와 `analysis_routes`에서의 재노출을 유지했다. 단계 순서, 부분 실패, 과거 형식 결과, `None` 사용량의 미확인 표시, 알려진 비용 부분 합계를 바꾸지 않았다.
- 기존 테스트, Markdown/OpenAPI fixture, DB 스키마, 지시문, 캐시 키와 비용 기록은 수정하지 않았다. 실제 커밋과 릴리스는 만들지 않았다.

수정 전 두 제품 파일과 관련 테스트 4종, 보고서/OpenAPI fixture, 네트워크 가드의 바이트는 사용자가 선택한 2026-11-09 스냅샷과 일치했다. 기준 HEAD는 `3d0e7d20abf251341ca4396eeb8dc981e2b0b643`이며, 이번 비교 기준은 HEAD 단독이 아닌 기존 미커밋 작업을 포함한 파일 상태다.

옮긴 조립 코드의 AST(코드를 연산과 분기로 표현한 구조)를 변경 전과 비교했다. 마지막 Markdown 대입을 반환으로 바꾼 부분을 제외하면 구조가 완전히 같다. 새 함수가 DB를 조회하거나 시각을 생성하지 않으므로 같은 입력으로 같은 문자열을 만들 수 있다.

## 검증 결과

Python 3.14.6, FastAPI 0.141.1, Pydantic 2.13.5의 기존 backend 가상환경을 사용했다. 소스와 필요한 고정 자료, Java 런타임은 별도 복사본에서 실행했다.

| 검사 | 변경 전 | 변경 후 |
|---|---|---|
| 보고서 바이트, 보고서 service, analysis routes, OpenAPI 집중 검사 | 245 passed, 20 subtests passed | 245 passed, 20 subtests passed |
| `pytest services api models tools --disable-warnings -q` | 1,359 passed, 7 skipped, 236 subtests passed | 1,359 passed, 7 skipped, 236 subtests passed |
| `py_compile main.py api/analysis_routes.py api/report_service.py` | 별도 실행 안 함 | 통과 |
| Python 가드가 관찰한 외부 연결 시도 | 집중 검사 0건, 전체 검사 2건 | 집중 검사 0건, 전체 검사 2건 |

전체 검사의 가드 차단 2건은 기존 `test_network_guard.py`의 `connect`, `connect_ex` 양성 대조에 해당한다. 가드가 관찰하는 Python 메서드 범위의 집계이며 모든 자식 프로세스의 연결 시도를 전수 계측한 값은 아니다.

변경 전 전체 검사의 첫 실행은 격리 자료 복사에서 `parallel-live-20261011` 폴더를 빠뜨려 3 failed, 1,356 passed였다. 세 실패 모두 기존 고정 JSON 자료의 `FileNotFoundError`였다. 원본의 자료를 변경 없이 두 복사본에 보충하고, 같은 격리 설정에서 변경 전후 전체 검사를 다시 실행해 위 통과 결과를 얻었다. 제품 코드나 테스트 기대값을 바꿔 해결하지 않았다. 초기 실패 로그도 보존했다.

## 격리와 작업 보존

실행마다 별도 HOME, `SASOO_APP_DATA_ROOT`, 임시 폴더와 Java 임시 경로를 사용했고 공급사 키를 전달하지 않았다. 실제 `.env`와 사용자 라이브러리는 복사하지 않았다. macOS sandbox는 외부 네트워크와 작업 임시 루트 바깥의 파일 쓰기를 차단했다. 독립 프로브에서 TEST-NET-1 주소로의 연결과 루트 밖 쓰기가 거부되고, loopback과 Unix socket 연결은 허용되는 것을 확인했다.

작업 시작 시 Git이 인식하는 파일 23,416개의 SHA-256 또는 심볼릭 링크 대상, Git 상태를 기록했다. 마지막에 기존 파일 내용과 목록을 다시 비교한 결과는 아래 `workspace-preservation.json`에 기록했다. 제품 파일 변경은 두 대상에 한정되며 나머지 변경은 이 검증 기록, 로드맵 진행 표시와 새 검증 자료다. reset, stash, clean, stage, 기존 데이터 삭제는 수행하지 않았다.

재현용 임시 루트는 `/private/tmp/sasoo-refactor-r1-okytt635/`다. `run_checks.py`와 `sandbox.sb`, 변경 전후 소스 복사본, 전체 작업 파일의 최초 해시를 남겼다. 임시 루트가 남아 있는 동안 다음 명령으로 같은 검사를 실행할 수 있다.

```bash
python3 /private/tmp/sasoo-refactor-r1-okytt635/run_checks.py before focused
python3 /private/tmp/sasoo-refactor-r1-okytt635/run_checks.py after focused
python3 /private/tmp/sasoo-refactor-r1-okytt635/run_checks.py before full
python3 /private/tmp/sasoo-refactor-r1-okytt635/run_checks.py after full
```

소스 이동 diff와 최종 로그, 격리 프로브 및 보존 비교 결과는 저장소의 [`assets/refactor-r1-20261110/`](assets/refactor-r1-20261110/)에도 보관했다. 임시 실행 폴더의 장기 보존은 보장하지 않는다.

## 한계와 다음 경계

이 결과는 코드 이동 뒤 기존 출력과 오류 계약, 관련 백엔드 회귀가 유지된다는 증거다. 실제 논문의 과학적 정확성, 실행 출처, 공급사 응답이나 실제 청구의 검증은 아니다. Python 3.12 CI, Windows, 외부 API 소비자, 실제 사용자 DB와 라이브러리, Electron GUI와 패키징 앱은 이번에 검증하지 않았다.

다음 순서는 로드맵의 R3 시각화 정책 분리다. 모델 설정을 읽는 캐시 조립과 기존 patch 경로를 순수 선택 계산과 구분해 확인해야 한다. R6 전에 필요한 F7 레거시 표시 결정, manifest와 비용 원장 설계 및 캐시 무효화 승인은 기존 경계를 유지한다.

학습 메모: DB 조회와 문자열 조립을 나누면 보고서 형식의 변경 영향을 독립적으로 확인할 수 있다. 같은 입력의 출력 바이트와 오류 계약을 먼저 고정하고, 옮긴 뒤 같은 테스트로 비교하는 것이 재사용할 원칙이다. 함수가 더 작은 파일로 옮겨졌다는 사실만으로 동작 보존이나 분석의 정확성을 판단하면 안 된다.
