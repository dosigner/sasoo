# GPT-6 Luna 심층 분석 xhigh 기본값

작성일: 2026-10-07. 사용자가 GPT-6 Luna의 `xhigh` 사용을 요청해 현재 개발 checkout의 OpenAI `deep_dive` effort를 `high`에서 `xhigh`로 변경했다. Gemini 심층 분석과 다른 OpenAI 역할의 effort는 기존 값을 유지한다. 제품의 심층 분석 프롬프트와 출력 상한 16,000 토큰은 그대로다.

2026-10-07 로컬 effort sweep에서 xhigh는 4편 중 2편에만 답변을 반환했다. Diffusion Policy는 필수 내용 20/46과 중대 오류 2건, Agile Locomotion은 24/40과 중대 오류 0건이었다. Bell은 연결 오류, DESeq2는 시간초과로 답변과 usage가 없었다. 원응답과 원문 판정은 로컬 `docs/validation/assets/effort-sweep-20261004/`에 보존돼 있으며 이 코드 커밋에는 포함하지 않는다. 논문당 단회 결과이므로 xhigh의 일반적 정확성, 안정성 또는 비용 효율이 입증된 것은 아니다. [OpenAI Docs의 배포 지침](https://developers.openai.com/api/docs/guides/deployment-checklist#set-up-reasoningeffort)도 xhigh의 추가 지연과 비용을 대표 과업에서 실측하도록 안내한다.

이번 변경은 `services/model_registry.py`의 OpenAI `deep_dive` 선택에만 적용된다. 제품의 모델 선택 함수가 반환한 `gpt-6-luna`와 `xhigh`를 OpenAI Responses 요청의 `reasoning.effort`로 전달하는 것을 로컬에서 확인했다. 분석 설정 지문과 단계 캐시 키는 effort를 포함하므로 기존 `high` 결과와 새 `xhigh` 결과를 구분한다. 실제 새 API 생성은 이 설정 검증에서 발행하지 않았다.

백엔드 `pytest services api models`와 `py_compile main.py services/model_registry.py`로 코드 변경을 검증했다. 이 기록은 개발 checkout의 기본값 변경이다. 설치 앱과 새 effort의 전체 분석 체인 결과는 별도 검증 대상이다.

학습 메모: effort를 높이면 추론 토큰이 늘 수 있지만 원문 오류가 자동으로 줄지는 않는다. 설정의 효과는 저장된 결과에서 질문별 충족 분자/분모, 중대 오류, 응답 실패와 비용을 함께 대조해야 확인할 수 있다. 특히 출력 상한 16,000은 눈에 보이지 않는 추론 토큰도 포함한다.
