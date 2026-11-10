# 분석 전 assistant context와 대화 연결 보강

시작일 2026-10-15, 검증 완료일 2026-10-16. 기존 변경사항과 `2026-10-14-preanalysis-chat.md` 및 그 증거는 유지했다. 버전 변경, 커밋, 배포, 분석 캐시 버전 변경은 수행하지 않았다.

분석 전 대화, 선택 구절의 주변 문맥, 첫 분석 결과 추가와 논문 전환을 보강하고 검증했다. 유료 모델 평가와 설치된 Electron 앱의 전체 흐름은 검증하지 않았다.

## 초기 결정과 확인 결과

사용자가 정한 기본값을 그대로 적용했다. 기본 답변은 1~3문단이며 명시적인 깊이와 출력 형식이 우선이다. 원문 전체 자동 검색, 벡터 DB, 외부 웹 검색은 추가하지 않았다. 구현을 진행하기 위한 추가 사용자 결정은 없었다.

| 이전 보고 항목 | 현재 코드 확인과 이번 처리 |
| --- | --- |
| PDF 텍스트 준비 후 대화 활성화 | `paper.text_ready` 사용 확인. 준비 중에 연 Workbench가 상태를 다시 읽지 않는 결함을 수정해 1.5초 간격으로 준비 완료까지 갱신한다. |
| 분석 전 입문용 원문 context | 유지. 논문 기본 정보, 자동 분류한 절 목록, 원문 발췌, 독자 정보, 선택 구절, 분석 상태를 구분한다. |
| 초록 2,000자 / 서론 2,500자 / 결론 1,800자 | 독립 상한 유지. 긴 서론이 결론을 밀어내지 않는 테스트 통과. 최적화된 수치라는 주장은 하지 않는다. |
| 절 감지 실패 시 앞부분 제공 | 6,300자 fallback 유지. method/results 등은 감지됐지만 개요 절이 없는 경우와 전체 절 구분 실패를 구분하도록 보강했다. 실제로 절이 없는지는 단정하지 않는다. |
| 설명 수준, 프로필, 관심 분야 | 유지. 분석용 프로필이 박사/전문가에게 비판이나 재현 평가를 강요하던 부분을 일반 대화에서는 배경지식 참고로 분리했다. 분석 자체의 기존 프로필 규칙은 유지한다. |
| 짧은 기본 답변 | 일반 대화의 기본 1~3문단과 명시적 요청 우선 규칙을 적용한다. |
| 입문 추천 질문 | 연구 문제, 사전 개념, 읽는 순서 유지. 클릭은 입력만 채운다. |
| 첫 분석 결과 추가 시 대화 유지 | 저장소 정책 유지. 실제 SQLite와 HTTP 대화에서 기존 기록 및 새 분석 근거의 동시 전달 확인. |
| `persist=false` 읽기 안내 | 기존 넓은 `phase_inputs.chat` 범위와 출력 형식 유지. 짧은 답변 제약 및 선택 구절 첨부를 적용하지 않는다. |

## 선택 context 규칙

1. pdf.js의 `data-page-number`는 **1부터 세는 물리 PDF 페이지**다. 인쇄된 쪽수와 구분해 질문에 표시한다. 선택 구절의 원래 문자열, 시작 페이지, 끝 페이지를 질문과 별도 필드로 전달한다. 페이지를 넘는 선택도 허용한다.
2. 서버는 해당 논문의 PDF에서 선택된 페이지를 직접 읽는다. 최대 두 개의 연속 페이지만 추출하며 문서 전체 검색이나 별도의 AI 요약을 하지 않는다. 페이지 텍스트의 블록 경계를 문단 경계 후보로 사용한다.
3. 공백과 줄바꿈을 정규화한 정확한 일치를 찾는다. 줄 끝 영단어의 하이픈 분리도 처리하지만, 일반적인 뺄셈 기호는 합치지 않는다. 정규화된 문자열과 원문 위치의 대응을 보관한다.
4. 지정한 페이지 범위에서 유일하게 일치할 때만 주변 원문을 붙인다. 두 페이지 선택은 실제 일치 범위가 두 페이지에 걸쳐 있어야 한다. 같은 페이지에서 중복되거나 문자열이 다르거나 PDF가 없거나 페이지 범위가 불확실하면 선택 구절만 제공하고 주변 문맥 미확인을 표시한다. 짧은 4자 미만 문자열도 보수적으로 미확인 처리한다.
5. 선택 범위 앞뒤 각각 최대 800자를 포함하고, 그 안에서 가장 가까운 문단 경계로 좁힌다. 선택 문자열은 최대 2,000자, 원문 발췌 전체는 최대 5,000자다. 이는 지연과 입력량을 제한하면서 국소 정의를 함께 제공하기 위한 단순한 상한이며 품질 최적값은 아니다.
6. 근거에는 정규화된 텍스트가 아닌 **PDF에서 추출한 원래 문자열**을 사용한다. 생략 여부와 추출 위치를 함께 전달한다. 문자 수 상한 때문에 문단이나 수식의 일부만 남을 수 있으므로 완전한 유도나 전체 원문을 제공했다고 주장하지 않는다. OCR이나 PDF의 문자 인코딩 자체가 정확하다는 보장도 아니다.

본문과 분석 결과는 JSON 참고 자료로 직렬화하고, 그 안의 지시나 역할 표시는 서비스 규칙으로 실행하지 않도록 명시했다. 논문 저자의 주장, 일반 배경 설명, assistant의 추론을 구분하도록 했다. 이것은 프롬프트 구성 검증이며 실제 모델에 대한 적대적 지시문 저항성 검증은 아니다.

## 대화 상태 보강

- 선택 팝오버, 패널 열기, 추천 질문 선택은 모델을 호출하지 않는다. 선택 정보는 전송 버튼을 누를 때 해당 대기 질문에 묶인다. 인용문을 지우거나 다른 질문으로 바꾸면 첨부 선택 정보도 해제한다.
- 논문 전환 시 draft, 선택 구절, 페이지 이동 요청을 초기화한다. 이전 논문의 응답, reset, 삭제 결과가 늦게 돌아와 새 논문에 적용되지 않도록 요청 세대를 검사한다. 대기 질문도 논문 ID에 묶는다.
- 첫 분석 결과는 기존 대화에 근거를 추가한다. 재분석은 기존의 명시적인 reset 기록 정책을 유지하며 기록 자체를 삭제하지 않는다.

## 검증 결과

- 백엔드: `services/test_selection_context.py`, `services/test_chat_context.py`, `services/test_document_context.py`, `api/test_chat_reading_context.py`, `api/test_analysis_context.py`, `api/test_discussion.py`, `api/test_analysis_routes.py`: **281 passed, 16 subtests passed**. 기존 SWIG deprecation warning 5건.
- 프론트엔드: `useDiscussion.dom.test.tsx`, `ChatPanel.reading.dom.test.tsx`, `workbenchSummaries.test.ts`, `selectionExplain.test.ts`, `readingGuide.test.ts`: **62 passed**.
- `pnpm tsc --noEmit`, `pnpm build`, `pnpm lint`, `git diff --check` 통과.
- 중복 문장, 지정 페이지에만 존재하는 중복, 공백 차이, 하이픈 줄 분리, 수식 기호 보존, 페이지 경계, 불일치 fallback, 긴 문단 상한, 잘못된 선택 payload를 검사했다. 임시 PDF를 실제 생성하고 PyMuPDF로 읽는 테스트도 포함했다.
- 설정의 비밀값 sentinel이 prompt에 포함되지 않는 테스트 통과. GUI에서 캡처한 prompt에도 API 키 설정명은 없었다. 이번 코드는 prompt나 설정값을 로그로 출력하지 않는다.

### 실제 GUI와 검증 환경의 구분

브라우저는 **빌드된 전체 Workbench**를 실행했다. 로컬 라이브러리의 실제 TurboQuant PDF를 임시 라이브러리에 복사하고, 실제 FastAPI 라우트, SQLite, PDF.js, PyMuPDF, 문서 context builder를 사용했다. 기존 사용자 DB와 논문 폴더는 수정하지 않았다.

모델 스트림은 고정 응답으로 대체했다. 텍스트 준비 시점, 첫 분석 결과, 응답 오류는 검증용으로 주입했다. 입력 token 수와 비용 값은 이 대체 응답의 fixture이므로 실제 모델 성능이나 요금 측정에 쓰면 안 된다. 업로드 API와 원래 파서의 자동 선택 경로를 실행한 것이 아니라 **복사한 기존 논문 열기 흐름**을 검증했다. 브라우저 선택은 실제 PDF 텍스트 레이어에 DOM Range를 만들어 UI 이벤트를 통과시켰다. 마우스/터치 장치별 드래그 품질은 별도 검증이다.

- 1440×900, 390×844에서 대기, 빈 대화, 추천 질문, 전송 중, 답변, 선택 draft, 오류, 첫 분석 후 대화, 페이지 경계 선택, 논문 전환 등 **32개 상태**를 캡처했다.
- 추천 질문 클릭과 문장 선택 후 패널 열기까지 추가 POST **0회**. 각 전송은 chat POST **1회**. 화면별 5회, 합계 **10회 대체 모델 호출**, 실제 공급자 호출 **0회**.
- 단일 페이지 선택은 `matched`, 889자 주변 발췌. 1→2페이지 선택도 `matched`, 255자 발췌. 각 화면에서 동일하게 확인했다.
- 첫 결과 추가 후 prompt에 `FIRST_ANALYSIS_EVIDENCE`와 이전 대화가 모두 존재했다. 논문 전환 시 미전송 draft가 제거됐다.
- 브라우저 console error **0**, pageerror **0**, 문서 전체 가로 넘침 **0**. 390px에서 assistant 카드와 입력/전송 동작은 확인했지만 기존 Workbench의 두 패널은 매우 좁아진다. 전체 PDF 읽기 UX를 모바일에 최적화했다는 의미는 아니다.
- 초기 검사 도구의 locator 및 캡처 timeout은 통과로 세지 않았다. 중간 API 전달을 제거하고 같은 FastAPI에서 빌드 산출물을 제공한 최종 실행이 위 결과다.

증거: [GUI 결과](assets/preanalysis-context-20261015/browser-check.json), [context 검사](assets/preanalysis-context-20261015/context-check.json), [백엔드 로그](assets/preanalysis-context-20261015/backend-tests.log), [프론트엔드 로그](assets/preanalysis-context-20261015/frontend-tests.log), [좁은 화면 입력](assets/preanalysis-context-20261015/selection-draft-390.png), [전송 중](assets/preanalysis-context-20261015/sending-2-390.png), [오류 상태](assets/preanalysis-context-20261015/error-390.png).

### 재현

프로젝트의 기존 frontend 의존성과 backend 가상환경이 필요하다. 브라우저 스크립트는 Python Playwright와 Chromium을 사용한다.

```bash
pnpm --dir sasoo/frontend build
sasoo/backend/.venv/bin/python docs/validation/assets/preanalysis-context-20261015/backend_harness.py
# 별도 터미널에서 실행
python3 docs/validation/assets/preanalysis-context-20261015/gui_check.py
python3 docs/validation/assets/preanalysis-context-20261015/context_check.py
```

harness는 매번 새 임시 DB와 라이브러리를 만들고 127.0.0.1:8015에서 실행한다. 반복 실행 시 harness를 재시작해 빈 대화로 시작해야 한다. 10개의 캡처된 prompt/input은 `captured-context.json`에 있고, 내용은 공개 논문과 검증용 대화다.

## 주요 변경 파일

- `backend/services/selection_context.py`: 페이지 한정 선택 위치 확인과 원문 주변 문맥 구성.
- `backend/services/chat_context.py`, `backend/api/analysis_routes.py`, `backend/api/analysis_context.py`: 절 감지 상태 구분, 구조화된 근거, 분석 누락 상태, 일반 대화용 독자 수준 규칙.
- `frontend/src/components/PdfViewer.tsx`, `frontend/src/lib/selectionExplain.ts`: 실제 페이지 범위와 원래 선택 문자열 보존, 페이지 경계 선택.
- `frontend/src/pages/Workbench.tsx`, `frontend/src/components/ChatPanel.tsx`, `frontend/src/hooks/useDiscussion.ts`, `frontend/src/lib/api.ts`: 선택 데이터 전송, 준비 상태 갱신, 대화와 논문 전환 격리.
- 관련 backend/frontend 테스트와 이 검증 자료.

## 남은 결정과 한계

1. 실제 모델 품질 평가: 개요, 배경 개념, 읽는 순서, 선택 구절, 전문가의 상세 요청, 근거 부족의 6개 질문을 우선 대상으로 권장한다. 실행 전에 공급자/모델, 호출 수와 재시도 수, 금액 상한을 확정하고 별도 승인 범위를 확인해야 한다. 이번에는 유료 호출을 하지 않았다.
2. 설치된 Electron 앱 전체 흐름: 패키징, 설치 앱의 preload/IPC, 실제 모델 스트림, 업로드와 텍스트 준비까지의 E2E는 미검증이다. 이번 브라우저 검증을 Electron 검증으로 해석하면 안 된다.
3. 문서 전체 질문별 검색: 국소 선택 fallback으로 해결되지 않는 질문이 실제 평가에서 반복될 때 설계한다. 현재는 추가 검색의 품질/비용/지연 근거가 없어 도입하지 않았다.

학습 원칙: **답변은 짧게 하더라도 필요한 근거는 충분히 제공한다.** 답변 길이, 독자의 지식 수준, 질문의 깊이, 현재 근거 범위를 각각 제어한다. 긴 서론/짧은 결론과 중복 문장을 넣어 독립 발췌와 보수적인 위치 확인을 재현할 수 있다. 가장 흔한 함정은 정규화된 문자열을 원문으로 제공하거나, 우연히 먼저 검색된 중복 문장을 정확한 위치로 간주하거나, fixture 통과를 실제 모델 품질로 확대 해석하는 것이다.
