# 모듈 리팩토링 계약 고정 검증

대상: `docs/superpowers/plans/2026-11-09-sasoo-modular-refactor-master-plan.md` 0-C. 기준은 현재 미커밋 작업 트리를 복사한 격리 테스트 환경이며, 0-A의 최종 기준선 결정이나 깨끗한 worktree 검증을 뜻하지 않는다. 제품 코드와 기존 사용자 데이터는 변경하지 않았다.

## 추가 계약

- R2: `api/test_openapi_contract_snapshot.py`와 `api/fixtures/openapi_snapshot.json`에 OpenAPI 전체를 고정한다. `/static/library/{requested_path:path}`와 `/shutdown`은 직접 route 목록에서도 확인한다. 인증 실패 응답은 401, `Missing or invalid local API token`, CORS 허용 헤더 부재로 관찰됐다. OpenAPI는 32 paths, 38 operations다. 설치된 FastAPI 0.141.1, Pydantic 2.13.5에서 생성했으므로 다른 의존성 버전의 출력이나 Python 3.12 CI 호환성은 아직 미검증이다.
- R8: `services/test_phase_input_hash_contract.py`는 합성 텍스트의 단계 입력 9종 UTF-8 SHA-256을 고정한다. `services/test_artifact_refresh_contract.py`는 가짜 변환기의 파일 목록과 안정적인 세 텍스트 파일 바이트를 고정하고, 추출, 그림 동기화, 표 동기화 실패 시 중단 순서를 확인한다. 합성 SQLite에서 표 동기화 실패 뒤 이미 커밋된 그림의 ID와 설명, 파일 바이트가 유지되고 usage 기록은 실행되지 않는 현재 동작을 확인했다. 기존 `test_document_context.py::test_reuses_current_document_context_sidecar`와 `test_visual_parse_usage.py::RefreshRecordsUsageTests::test_db_error_is_swallowed`도 함께 전체 회귀에서 실행했다. 이 테스트는 실패를 고치는 것이 아니라 현재 동작을 기록한다. 래스터 PNG와 PDF의 정확한 바이트는 생성 환경에 종속될 수 있어 고정하지 않았다.
- R15: `contract-fixtures/hmac-vectors.json`을 Python `api/test_hmac_vector_contract.py`와 Electron `electron/hmac-health-contract.test.ts`, `electron/hmac-asset-contract.test.ts`가 함께 사용한다. Python ASGI health와 asset 인증, Electron PythonManager의 health 확인과 실제 등록된 asset IPC handler를 모의 앱 환경에서 확인했다.
- 시각화 계획: `services/test_viz_plan_snapshot_contract.py`와 JSON fixture에 60점, 70점 경계, 중복 core, 문자열, bool, NaN 점수, legacy gate, Sunburst 선정 결과를 고정한다.
- 보고서: `api/test_report_bytes_contract.py`와 Markdown fixture에 partial 결과, 비용 미확인, 알려진 비용 부분 합계가 섞인 합성 행의 보고서 바이트와 404 오류 2종을 고정한다.
- 지시문과 schema 7종은 이전 R0 기록의 `test_instruction_contract.py`, `test_schema_hash_contract.py`에서 고정했다.

## 실행 결과

격리 복사본에서 `python -m pytest services api models tools --disable-warnings -q`: **1,359 passed, 7 skipped, 236 subtests passed**. 네트워크 가드 차단 2건은 가드 양성 대조다. 이전 기준선은 1,332 passed, 7 skipped였다.

같은 격리 영역에서 `vitest run electron`: **8개 파일, 37개 테스트 통과**. Electron은 모의 모듈을 이용한 단위 테스트이며 실제 GUI나 패키징 앱 실행은 아니다. 격리는 R0 검증 기록과 같은 별도 HOME, 앱 데이터, Java 임시 경로, 외부 송신 차단 macOS sandbox를 사용했다. `.env` 및 실제 사용자 라이브러리는 복사하지 않았다.

미검증: Python 3.12 및 Windows, 실제 사용자 데이터와 외부 API 소비자, 실제 Electron GUI, 공급사 및 청구. socket 가드 집계는 Python 테스트 프로세스의 가드된 메서드에 국한되고 OS sandbox의 전체 거부 시도 계측은 아니다. 실행 로그는 `/private/tmp/sasoo-refactor-r0.mmau7fi2/final-backend-turn2.log`와 `final-electron-turn2.log`에 있으며 임시 파일이다.
