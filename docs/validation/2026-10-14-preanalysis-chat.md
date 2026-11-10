# 분석 전 대화 assistant 보강

현재 작업 버전 1.2.2 위에 v1.2.3 후보 기능으로 반영했다. 버전 변경, 커밋, 배포는 수행하지 않았다.

## 적용한 기본값

1. 분석 결과가 없으면 읽기 도움 단계로 안내한다. 기본 답변은 짧은 1~3문단이며 사용자가 요청한 깊이와 출력 형식이 우선이다.
2. 원문 context는 초록 2,000자, 서론 2,500자, 결론 1,800자를 각각 확보한다. 이는 초기 구현값이며 실제 모델 품질과 비용으로 최적화한 수치는 아니다. 자동 감지한 절 목록도 포함한다.
3. 절 구분에 실패하면 원문 앞 6,300자를 제공하고 구분 실패와 생략 여부를 밝힌다. 누락된 절이 논문에 없다고 단정하지 않는다.
4. 논문별 설명 수준을 우선하고, 없으면 설정의 기본 수준을 사용한다. 기존 독자 프로필과 관심 분야를 적용한다. API 키 등 나머지 설정은 프롬프트에 넣지 않는다.
5. 논문 주제, 필요한 개념, 읽는 순서의 추천 질문을 표시한다. 클릭은 입력창만 채우고, 보내기는 사용자가 수행한다.
6. 첫 분석 결과가 생기면 기존 분석 context 경로를 사용한다. 첫 결과 추가 시 대화를 유지하는 기존 저장소 정책을 보존한다.
7. 읽기 안내 생성은 같은 API의 persist=false 경로를 사용하므로, 이 경로에는 입문용 원문 축소와 짧은 답변 규칙을 적용하지 않는다.
8. context는 기존 문서의 sections로 요청 시 조합한다. 분석 입력과 캐시 버전은 변경하지 않는다.

## 검증

- 백엔드: `services/test_chat_context.py`, `services/test_document_context.py`, `api/test_chat_reading_context.py`, `api/test_discussion.py`, `api/test_analysis_routes.py`: 245 passed, 16 subtests passed. 기존 SWIG deprecation warning 5건.
- 프론트엔드: `workbenchSummaries.test.ts`, `ChatPanel.reading.dom.test.tsx`, `useDiscussion.dom.test.tsx`: 44 passed.
- `pnpm tsc --noEmit`, `pnpm build`, `pnpm lint`, `git diff --check` 통과.
- 실제 ChatPanel을 로컬 Vite에서 렌더링하고 API 응답만 fixture로 대체했다. 1280x800, 390x844에서 가로 넘침 없음, 추천 질문 선택 시 POST 0회, 전송 후 POST 1회, PDF 텍스트 준비 전 입력창 없음, 콘솔/pageerror 없음.
- GUI 검사 수치: [browser-check.json](assets/chat-reading-20261014/browser-check.json)
- 화면: [데스크톱](assets/chat-reading-20261014/reading-1280.png), [좁은 화면](assets/chat-reading-20261014/reading-390.png), [답변 상태](assets/chat-reading-20261014/answer-390.png), [대기 상태](assets/chat-reading-20261014/waiting-390.png)

브라우저 검증은 컴포넌트 fixture 검사다. 실제 PDF 업로드부터의 전체 Workbench 흐름, 설치된 Electron 앱, 유료 모델의 말투와 과학적 답변 품질은 검증하지 않았다. 원문 파서의 절 감지와 페이지 위치 정확성도 이번 테스트의 입증 범위가 아니다.

## 다음 결정 순서

1. 기본 답변 길이: 현재 1~3문단. 더 짧거나 상세한 기본값을 원하는지 선택할 수 있다.
2. 질문별 근거 확장: 현재 선택 구절은 기존 질문 텍스트로 전달한다. 주변 문단 자동 첨부와 관련 절 검색은 후속 범위다. 우선 주변 문단을 붙이는 순서를 권장한다.
3. 초기 논문 대상: 일반 연구 논문으로 시작할지, 리뷰 논문이나 절 구분이 어려운 PDF도 첫 품질 검증에 포함할지 정한다. 후자에서 fallback 비율과 유용성을 확인해야 한다.
4. 실제 모델 품질 기준: 개요, 용어, 읽는 순서, 근거 없음 질문의 답변을 검토한다. 프롬프트 포함 여부를 검증하는 테스트는 실제 답변 품질을 보장하지 않는다.
5. v1.2.3 출시 범위: 다른 작업 변경사항과 함께 출시할지, 이 기능을 별도 변경으로 정리할지 정한다.

핵심 원칙: 답변 길이와 근거 범위를 별도로 제어한다. 재현 시 긴 서론과 짧은 결론을 가진 입력으로 결론 보존을 확인한다. 문서의 앞부분을 초록으로 오인하거나 자동 감지한 절 이름을 원문의 정확한 위치로 주장하지 않는 것이 중요하다.
