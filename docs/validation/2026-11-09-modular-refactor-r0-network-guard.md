# 모듈 리팩토링 R0 검증 기록

대상: `docs/superpowers/plans/2026-11-09-sasoo-modular-refactor-master-plan.md`의 0-B. 기존 작업 트리를 그대로 보존하고 테스트 코드만 추가했다. 0-A 기준선 확정, 0-C 계약 고정, 이후 리팩토링은 완료하지 않았다.

## 변경과 검증

- `sasoo/backend/conftest.py`: 각 pytest 테스트 중 `socket.socket.connect`와 `connect_ex`에서 loopback과 Unix socket을 허용하고 그 밖의 주소를 차단한다. 차단 횟수는 pytest 종료 요약에 표시한다.
- `sasoo/backend/services/test_network_guard.py`: 두 연결 메서드 각각에 대해 TEST-NET-1 외부 주소 차단, IPv4 loopback 연결, Unix socket 연결을 검증한다.
- 변경 전: 1,332 passed, 7 skipped, 236 subtests passed.
- 변경 후: 1,338 passed, 7 skipped, 236 subtests passed. 추가된 6건 외 통과와 skip 수는 동일하다.
- 가드가 기록한 차단은 2건이며, 두 건 모두 추가된 외부 연결 양성 대조다. 기존 테스트가 가드에 기록한 외부 연결 시도는 없다.

두 실행 모두 복사본에서 `python -m pytest services api models tools --disable-warnings -q`를 실행했다. 사용한 Python은 기존 backend `.venv`의 Python 3.14다. 각 소스 복사본에서 최종 테스트 파일과 원본 파일의 바이트가 일치함을 확인했다.

## 격리

별도 임시 HOME, `SASOO_APP_DATA_ROOT`, `TMPDIR`, Java 임시 디렉터리와 합성 테스트 데이터를 사용했다. `.env`, 실제 사용자 라이브러리, 기존 빌드 및 출력은 복사하지 않았다. 테스트에 필요한 기존 고정 검증 자료와 Java 런타임은 복사했다. 환경 변수를 최소화하고 공급사 키를 전달하지 않았다. macOS sandbox는 외부 네트워크 송신과 임시 폴더 바깥 파일 쓰기를 차단하고 loopback, Unix socket 및 `/dev/null` 쓰기를 허용했다. 외부 TEST-NET-1 연결이 OS에서 거부되고 loopback 및 Unix socket이 연결되는 것을 별도로 확인했다.

중간 실행에서는 Java 런타임 누락, Java 임시 경로, Unix socket 경로 길이, sandbox의 Unix socket 차단이 각각 테스트 환경 실패로 나타났다. 마지막 비교는 같은 수정된 격리 정책과 Java 설정에서 변경 전과 후를 각각 다시 실행한 결과다. 원시 로그와 임시 복사본은 `/private/tmp/sasoo-refactor-r0.mmau7fi2/`에 남아 있으며 임시 파일이므로 지속 보관은 보장하지 않는다.

## 한계

가드는 pytest fixture가 활성화된 테스트 프로세스의 Python socket 메서드를 감싼다. 수집 시점, 자식 프로세스, 다른 네트워크 구현, 테스트가 직접 교체한 메서드까지 계측하는 장치는 아니다. 따라서 차단 횟수 2는 이 가드가 관찰한 횟수이며 모든 프로세스의 연결 시도 총계는 아니다. 별도의 OS sandbox가 외부 송신을 막았지만, sandbox 거부 시도 전수 기록을 수집하지는 않았다. 실제 공급사 호출 성공이나 과금은 발생하지 않았다고 단정할 수 있는 외부 청구 대조는 수행하지 않았다. 실제 사용자 라이브러리 12편 기반 추출 회귀, Python 3.12 CI 환경, Electron과 패키징 앱은 검증하지 않았다.

## 0-C 일부: 지시문과 schema 고정

`services/test_instruction_contract.py`는 Gemini와 OpenAI가 같은 기본 지시문 객체를 재노출하고 UTF-8 바이트 SHA-256이 `ebadc3fd3fd2c3e638c575f603e5d7460c6fcc8cfe8d8b483243eaa1ada3060c`인지 검사한다. `services/test_schema_hash_contract.py`는 screening, citation, visual, recipe, deep dive, visualization plan, synthesis schema 7종을 `json.dumps(..., sort_keys=True)` 기본 설정으로 직렬화한 뒤 SHA-256을 비교한다. 두 값은 현재 작업 트리의 기존 구현에서 측정한 기준선이며 과학적 정확성 검증은 아니다.

두 계약 테스트를 추가한 최종 격리 전체 실행은 1,346 passed, 7 skipped, 236 subtests passed이며, 차단 2건은 앞의 양성 대조다. 기존 1,332건에 가드 6건과 계약 8건이 추가됐다. HTTP 계약, 단계 입력과 파일 바이트, HMAC, 시각화 입출력, 보고서 바이트 고정은 아직 수행하지 않았다.

추가 조사: 현재 설치된 FastAPI에서 `app.routes`에는 `path` 속성이 없는 내부 포함 라우터가 들어 있어 단순 `route.path` 열거는 실패했다. `app.openapi()`는 이 환경에서 32개 path와 38개 operation을 생성했다. OpenAPI 전체 스냅샷과 route 목록을 검증하는 R2는 아직 작성하지 않았고, 프레임워크 버전 차이와 비 OpenAPI mount를 포함하는 안정적인 목록 수집 방법이 필요하다.
