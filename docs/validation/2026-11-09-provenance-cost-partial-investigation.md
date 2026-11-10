# 실행 이력 및 비용 추적 부분 조사

이 문서는 완료 보고가 아니다. 유료 공급사를 호출하지 않고 현재 소스와 모의 테스트를 확인했다.

## 계획과 현재 코드의 차이

- `analysis_runs`의 generation은 worker heartbeat에서 확인되지만 `run_full_analysis`나 결과 저장 트랜잭션에 전달되지 않는다. heartbeat 확인만으로 오래된 worker의 결과 저장을 막을 수 없다. 별도 execution과 attempt identity, 결과와 fence를 함께 확인하는 트랜잭션이 필요하다.
- 저장된 과거 시각화에 `planned_items`가 없으면 이전 완료 검사는 완료로 표시했다. 구조적 완료 판정은 partial로 변경했으며, 기존 캐시를 재사용하는 경로에서만 과거 정책을 유지한다. 과거 계획을 생성하거나 새로운 요청을 보내지 않는다.
- 현재 HTML 클라이언트 검증 보고의 해시 일치는 격리 증거가 아니다. 별도 격리 검사기를 구현하거나 검증 완료를 새로 인정하지 않았다.

## 요청 경계 조사

| 경로 | 소스에서 확인한 경계와 한계 |
| --- | --- |
| OpenAI 텍스트 | `openai_client.call_interaction`의 `responses.create` 앞에 서비스 재시도 루프가 있다. `single_attempt`인 경우에만 SDK `max_retries=0`을 적용한다. 일반 호출의 SDK 내부 전송 횟수는 앱 원장으로 관측하지 않는다. 응답 ID와 usage는 응답 이후에 얻는다. |
| OpenAI 스트림 | `responses.stream` 앞에 동일한 선택적 SDK 재시도 제한이 있다. 완료 이벤트가 없으면 사용량을 모르는 종료 메타데이터를 반환한다. |
| Gemini 텍스트 | `gemini_client.call_interaction`이 `interactions.create`를 서비스 재시도 루프로 호출한다. SDK 내부 재시도와 각 물리 전송은 이번 조사에서 확인하지 못했다. usage가 없으면 토큰을 0으로 대체하는 코드가 있다. |
| Gemini 스트림 | `interactions.create(stream=True)`를 사용한다. 완료 이벤트 또는 usage가 없을 때 토큰을 0으로 대체하는 경로가 있다. 이 값으로 미청구를 입증할 수 없다. |
| 이미지 | `figure_gen`은 텍스트 설명을 일반 LLM 호출로 만들고 OpenAI HTTP 이미지 요청 또는 Gemini `interactions.create`로 렌더한다. 성공, timeout, 오류 이후 `usage_record`를 만든다. 전송 전에 내구성 있게 기록되는 물리 시도 ID는 아니다. timeout은 미청구 증거가 아니다. |
| Mermaid, HTML, 종합 및 계획 | 생성은 공통 LLM 호출 경로를 사용한다. Mermaid와 HTML의 `usage_record`는 응답 이후 만들어지며, 종합과 계획 등은 동일한 전송별 원장에 연결되어 있지 않다. 단계 수준의 별도 재시도는 사용량을 합산할 수 있다. |

`interaction_id`, `usage_record.id`와 물리 전송 시도 ID는 서로 다른 개념이다. 지금 있는 기록만으로 SDK의 숨은 재시도, 불확실한 전송, 과거 결과의 정확한 생성 맥락을 복원할 수 없다. 과거 데이터는 추정하거나 재발행하지 않는다.

## 남은 작업

불변 manifest와 이미지 바이트 보존, 실제 소비 관계, 원문 및 설정 충돌, 결과 저장 트랜잭션의 fence, 도구별 버전 결속 검사, 요청별 원장 및 동일 시점 집계, 격리 Electron 검사는 구현 또는 검증하지 않았다. 계획의 성공 조건을 충족한 것으로 취급하지 않는다.
