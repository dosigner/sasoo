# GPT-6 Luna 기본 모델 최종 점검

2026-10-07 현재 작업 트리의 OpenAI 텍스트 기본 모델은 이미 `gpt-6-luna`다. 이번 점검에서 기본 모델 값을 새로 수정하지 않았다. 기존 미커밋 변경을 보존했다.

## 확인한 경로

- `sasoo/backend/services/models.py`: `MODEL_LUNA = MODEL_GPT6_LUNA = "gpt-6-luna"`.
- `sasoo/backend/services/model_registry.py`: 모든 OpenAI 텍스트 역할은 `MODEL_LUNA`를 사용한다. `deep_dive`의 effort는 `high`다.
- `sasoo/backend/services/llm/openai_client.py`: 실제 요청 구성에 모델 `gpt-6-luna`와 `reasoning.effort=high`가 들어가는 것을 네트워크 호출 없이 확인했다.
- `sasoo/backend/services/pricing.py`: GPT-6 Luna 요율 항목이 있다. 미등록 GPT 모델의 요율 대체값으로 남은 GPT-5.6 Luna는 활성 분석 모델 선택과 무관하다.
- `sasoo/frontend/src/lib/strings.ts`: OpenAI 공급사 설명이 `GPT-6 Luna`다.
- 이미지 모델은 분리되어 있다. Gemini `gemini-3.1-flash-image`, OpenAI `gpt-image-2.5-flare`가 현재 코드값이다.

## 검증 결과

- 백엔드 `pytest services api models -q`: 1065 passed, 228 subtests passed.
- `py_compile main.py`: 통과.
- 프런트엔드 `pnpm tsc --noEmit`, `pnpm build`, `pnpm lint`: 통과.
- 로컬 설치 데이터베이스(`~/Library/Application Support/Sasoo/sasoo.db`)와 실행 중인 Sasoo 프로세스가 없었다. 따라서 실제 설치 앱의 저장된 공급사 선택이나 패키지 실행은 확인하지 못했다. 새 설치의 설정 기본 공급사는 OpenAI지만, 기존 설치의 저장된 공급사 선택은 별도다.

이번 검증은 작업 트리의 소스, 요청 구성, 빌드와 테스트까지다. macOS 릴리스 패키지 생성과 설치 앱 실행은 이 점검에 포함되지 않았다.
