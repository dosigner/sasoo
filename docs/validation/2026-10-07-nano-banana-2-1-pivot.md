# Gemini 도해 모델을 Nano Banana 2.1로 전환

상태: 2026-10-07 공급사별 모델 선택 구조를 유지한 코드 전환. 실제 유료 이미지 생성은 별도 검증 상태로 기록한다.

## 공급사 계약

유효 분석 공급사가 OpenAI이면 분석은 GPT-6 Luna, 도해는 GPT Image 2.5 Flare를 사용한다. Gemini이면 분석은 Gemini 역할별 모델, 도해는 Nano Banana 2.1을 사용한다. 저장된 `image_provider`는 호환성 미러로 남고 도해 실행은 유효 분석 공급사를 직접 사용한다. 공급사 선택을 두 개의 독립 설정으로 분리하지 않는다. 선택한 공급사의 키가 없거나 이미지 생성이 실패해도 다른 공급사로 유료 요청을 보내지 않는다.

## 비용을 줄이는 기본 요청

- Gemini 도해 모델 ID는 `gemini-nano-banana-2.1`이다. Google 공식 예시에 맞춰 `client.interactions.create()`를 사용한다.
- 출력은 PNG, 가로세로 비율 3:2, 크기 1K로 고정한다. 이미지 생성 `thinking_level=minimal`을 명시하고 검색 도구를 요청하지 않는다. 도해 한 장에 렌더 요청 한 번을 보낸다.
- `store=False`를 명시한다. 이미지와 실제 응답 사용량을 확인한다. 이미지가 없거나 PNG가 아니면 정상 결과로 저장하지 않는다.
- Gemini를 선택했을 때 화면에는 1K와 최소 사고량을 표시한다. OpenAI 전용 `low/medium/high` 품질 선택은 Gemini에서 숨긴다.
- 시각화 캐시 키에 이미지 모델 ID를 포함해 이전 Nano Banana 2 이미지가 2.1 결과로 재사용되지 않게 한다. 분석 체인 전체의 캐시 버전은 올리지 않는다.

Google의 표준 요율은 입력 US$1.50/백만 토큰, 텍스트와 생각 출력 US$7.50/백만 토큰, 이미지 출력 US$30/백만 토큰이다. 1K 이미지 한 장의 공시 출력 비용은 US$0.0336이다. 여기에 입력과 생각 토큰, 별도 도해 설명 플래너 호출 비용이 더해진다. 따라서 장당 실제 비용은 응답의 `usage`로 계산하고 사용량 누락을 0원으로 간주하지 않는다. 같은 모델의 Batch 요율은 절반이지만 최대 24시간 대기하는 작업 방식이므로 현재 대화형 생성에는 적용하지 않았다.

## 검증 범위와 다음 판정

Google SDK 설치판 2.21.0의 `interactions.create`와 요청 스키마를 네트워크 없이 확인했다. 요청 형식, PNG 디코딩, 사용량 계산, 공급사 고정, 캐시 키를 테스트했다. 백엔드 전체 테스트 1069개와 231개 하위 테스트, 프런트엔드 빌드와 린트가 통과했다. 임시 설정 응답을 붙인 실제 브라우저 화면에서 Gemini 선택 시 Nano Banana 2.1과 1K/최소 사고량 안내가 보이고 OpenAI 전용 품질 선택이 보이지 않는 것을 넓은 화면과 좁은 화면에서 확인했다.

현재 실행 환경에는 Gemini API 키가 없어 실제 2.1 이미지나 제공자 사용량은 확인하지 못했다. 긴 한글 및 영문 라벨, 숫자와 단위, 화살표 방향을 포함한 실제 도해로 출력 품질을 확인하기 전에는 Google의 텍스트 렌더링 개선 주장을 Sasoo의 과학 도해 정확성으로 간주하지 않는다. 기존 Nano Banana 2는 과거 행의 비용 계산을 위해 단가표에 남겼다.

공식 근거: [2.1 모델 설명](https://ai.google.dev/gemini-api/docs/models/gemini-nano-banana-2.1), [이미지 생성 API](https://ai.google.dev/gemini-api/docs/image-generation), [요율](https://ai.google.dev/gemini-api/docs/pricing), [Interactions 사용량 필드](https://ai.google.dev/api/interactions-api-v1), [생각 토큰 비용](https://ai.google.dev/gemini-api/docs/thinking/).
