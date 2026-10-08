# Sasoo 기존 UI refinement 검증

결과: **완료**. 처음 고정한 10개 문제의 통과 조건을 첫 통합 검증에서 충족했다. 재수정 라운드는 없었다. 기존 미커밋 변경과 브랜드 요소를 보존했으며 유료 AI 분석/이미지 생성은 실행하지 않았다.

대상은 Home, Library, Workbench의 PDF와 분석 읽기, Settings, Profile 및 연결된 공통 컴포넌트다. 평가 A와 B는 읽기 전용 독립 에이전트로 수행했다. A의 판단을 고정한 다음 detector 결과를 수집했다. PRODUCT.md/DESIGN.md는 없었고 기존 디자인 토큰 문서와 폼 원칙, 현재 구현을 기준으로 삼았다.

고정 기준: 행동 위계, 상태 정확성, 긴 내용 처리, 키보드 접근성, 지원 창 크기, 테마 가독성, 반복 조작의 즉시성. Pretendard와 기존 본문/라벨/메타데이터 역할, 퍼플 선택색, 중립 콘텐츠 표면을 유지했다. UI UX Pro Max의 오류 복구, 긴 토큰 줄바꿈, 포커스 검색 결과만 적용했다. 긴 제목에 대한 React 검색이 목록 가상화를 반환한 것은 적용하지 않았고, 좁힌 UX 검색과 React 포커스 지침을 사용했다. Impeccable은 Operate, harden/typeset/adapt/clarify/polish의 필요한 지침만 적용했다.

## 고정 문제와 결과

| ID | 우선순위 | 화면/상태 | 관찰한 문제와 재현 조건 | 증거 | 사용자 영향 | 수정 위치 | 통과 조건 및 결과 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| R01 | P1 | Home/Library 조회 실패 및 로딩 | GET papers 503 또는 응답 보류. 실패가 빈 보관함으로 표시됨 | before/home-error.png, before/library-error.png, regression-before.log | 기존 논문이 없어진 것으로 오해, 복구 행동 부재 | Home 조회 상태, Library 상태 분기, ContentState | 오류와 빈 상태 분리, 재시도로 29건 복원, 로딩 중 빈 상태 없음. 통과 |
| R02 | P1 | Library 검색 0건 | 검색어만 입력해 결과 0건 | before/library-search-empty.png, A/B 평가 | 첫 업로드 안내가 나와 검색을 복구하기 어려움 | Library hasActiveFilters | 검색 0건 안내와 필터 초기화 노출, 초기화 후 29건 복원. 통과 |
| R03 | P1 | Settings/Profile 초기 조회 실패 | GET settings 503 뒤 기본값 폼 활성 | before/settings-settings-error.png, B load-error 증거 | 받아오지 못한 현재값을 기본값으로 덮어쓸 수 있음 | 두 페이지의 초기 loadFailed 분기 | 초기 실패 시 입력/저장 폼 없음, 재시도 성공 후 편집 가능. 통과 |
| R04 | P1 | Profile/Settings 미저장 이동 | 입력 변경 후 내부 링크 또는 뒤로 가기 | A interaction-observations.json | 입력이 안내 없이 사라짐 | 공유 SaveBar useBlocker, main hash data router | 이동 전 확인, Escape/계속 편집 시 입력 유지, 명시적 이동 허용. 링크와 history 모두 통과 |
| R05 | P1 | 공유 Modal, 긴 논문 제목 | 1024x680에서 매우 긴 제목, Escape 닫기 | B extreme-long-delete 높이1994px/top -657px, before-behavior.json | 닫기/삭제 버튼 화면 밖, 키보드 위치 소실, 이름 불명확 | Modal, 기존 5개 호출의 title | 높이 viewport-32px 이내, 내부 스크롤, 실제 제목으로 명명, opener 포커스 복귀. 브라우저와 실제 Electron 통과 |
| R06 | P1 | Workbench 상태 조회 실패 | GET analysis status 503 | before/workbench-workbench-error.png | 완료 논문을 분석 전/결과 없음으로 오인, 불필요한 재분석 유도 | Workbench 표시, useAnalysis 성공 후 오류 해제, Header 오류 영역 | 상태 확인 실패 표시, PDF 읽기 유지, 상태 재조회 후 완료 5 복원. 통과 |
| R07 | P1 | 프로필/설정 라디오, 보관함 컨트롤 | radio에서 방향키 입력, 목록/그리드 전환 | B 키보드 증거, SaveBar.dom.test.tsx | radio 역할과 실제 키보드 동작 불일치, 선택 상태 미노출 | SettingPrimitives SegmentGroup, Library aria-pressed/연도 label | 방향키 선택 및 포커스 이동, 선택 항목만 Tab 정지점, 보기 상태 노출. 통과 |
| R08 | P2 | UploadPanel 긴 파일명 | 공백 없는 긴 한국어 파일 선택 | before/home-long-file.png | h2가 패널 밖에서 잘려 식별이 어려움 | 제목측 min-w-0, 2줄 줄바꿈, 파일명 title | 제목이 패널 안 2줄로 유지, 원문 title 보존, 선택 해제/추가 버튼 접근. 통과 |
| R09 | P1 | Light 도움말, 에이전트 라벨 | 설정 행 위 작은 보조 텍스트, 밝은 에이전트 이름 | B 대비4.265:1, A 에이전트 약2.7:1 | 낮은 대비로 읽기 어려움 | 공통 light fg-muted, WorkbenchHeader 라벨 | 도움말 6곳 합성 배경 대비 light4.80:1/dark4.75:1, 라벨 중립 전경 사용. 통과 |
| R10 | P2 | 질문 패널 키보드/반복 토글 | Enter 열기, Escape 닫기, 연속 토글 | before-behavior.json chatFocusReturned=false | 포커스 BODY 이동, 반복 조작 지연/되열림 가능 | ChatPanel closeCard/launcher ref, CSS 입력별 전환 | 키보드 즉시 전환, Escape 런처 복귀, 3회 반복 토글 잔류 카드 없음, reduced motion 존중. 브라우저와 실제 Electron 통과 |

## 상호작용 수정 근거

| Before | After | Why | 검증 방법 |
| --- | --- | --- | --- |
| 모달 Escape 후 BODY 포커스, 이름은 대화상자 | 열린 시점 opener 저장, 닫힐 때 복귀, 실제 제목 전달 | 다음 키보드 작업의 위치와 문맥 유지 | 삭제/재분석 확인창의 mouse/Tab/Escape, Modal DOM 회귀 테스트, Electron |
| 미저장 입력을 화면 이동으로 폐기 | 공유 저장바가 router의 이동 차단 기능 사용 | 사용자가 계속 편집하거나 이동을 직접 선택 | 내부 링크, history 뒤로 가기, Escape, 계속 편집, 명시적 이동 |
| radio 방향키 무반응, transition-all과 press scale | 방향키/홈/끝 및 roving Tab, 색상 전환만 사용 | 반복 선택은 즉각적이고 예측 가능해야 함 | SegmentGroup DOM 테스트와 실제 키보드 선택 |
| 키보드도 질문 카드 진입/이탈 애니메이션, 복귀 대상 없음 | 키보드는 즉시, 마우스는 기존 짧은 전환, 런처 복귀 | 자주 반복하는 조작을 기다리게 하지 않음 | Enter/Escape, 계산된 animationName, 3회 빠른 토글 |
| 모든 포인터에서 오브 hover 확대 | hover 가능하고 fine pointer일 때만 확대 | 터치 입력의 잔류 hover 이동 방지 | CSS media 확인, reduced-motion에서 실제 애니메이션 이름 none |

## 대표 Before/After

| 상태 | Before | After |
| --- | --- | --- |
| 보관함 GET 실패 | [빈 보관함과 오류 동시 표시](assets/ui-refinement-2026-10-07/before/library-error.png) | [오류와 다시 시도](assets/ui-refinement-2026-10-07/after/library-error.png) |
| 검색 0건 | [첫 업로드 안내](assets/ui-refinement-2026-10-07/before/library-search-empty.png) | [검색 결과 없음과 초기화](assets/ui-refinement-2026-10-07/after/library-search-empty-light.png) |
| 긴 파일명 | [패널 밖 잘림](assets/ui-refinement-2026-10-07/before/home-long-file.png) | [패널 안 2줄 유지](assets/ui-refinement-2026-10-07/after/home-long-file.png) |
| 긴 삭제 대상 | [식별자 넘침](assets/ui-refinement-2026-10-07/before/library-long-modal.png) | [줄바꿈과 제한된 높이](assets/ui-refinement-2026-10-07/after/library-long-modal.png) |
| 설정 초기 실패 | [기본값 폼 활성](assets/ui-refinement-2026-10-07/before/settings-settings-error.png) | [복구 전 편집 차단](assets/ui-refinement-2026-10-07/after/settings-settings-error.png) |
| 실제 Electron | [기존 화면](assets/ui-refinement-2026-10-07/before/electron-live.png) | [수정 후 화면](assets/ui-refinement-2026-10-07/after/electron-live.png), [어두운 테마](assets/ui-refinement-2026-10-07/after/electron-dark.png) |

## 변경 파일

- 공통 원인: `frontend/src/components/ui/Modal.tsx`, `ContentState.tsx`, `components/settings/SaveBar.tsx`, `SettingPrimitives.tsx`, `src/index.css`, `src/main.tsx`.
- 화면 상태: `src/pages/Home.tsx`, `Library.tsx`, `Profile.tsx`, `Settings.tsx`, `Workbench.tsx`, `src/hooks/useAnalysis.ts`.
- 긴 내용과 포커스: `components/home/UploadPanel.tsx`, `components/workbench/WorkbenchHeader.tsx`, `components/ChatPanel.tsx`.
- Modal 이름 전달: `components/ReadingGuideTab.tsx`, `ExperimentPlanTab.tsx`, `synthesis/SynthesisView.tsx` 및 두 페이지의 확인창.
- 회귀 테스트: `pages/LoadStates.dom.test.tsx`, `components/ui/Modal.dom.test.tsx`, `components/settings/SaveBar.dom.test.tsx`, `hooks/requestEfficiency.test.js`.
- 토큰 값 문서: `sasoo/docs/04-design/design-tokens.md`.
- 검증 자산: `docs/validation/assets/ui-refinement-2026-10-07/`.

위 경로 중 frontend로 시작하지 않는 source 상대 경로는 `sasoo/frontend/` 기준이다. 모델, 프롬프트, 과금 계산, 백엔드 저장, API 계약, package.json을 변경하지 않았다. 기존 AnalysisPanel/RecipeCard/CSV 관련 미커밋 작업은 이번 수정 대상에서 제외했다. ChatPanel과 CSS의 기존 오브 변경은 유지했다. 실행 도중 다른 작업이 바꾼 `.gitignore`/`CONTEXT.md`도 정리하지 않았다.

## 검증과 재현

- `sasoo/frontend`에서 `pnpm tsc --noEmit`, `pnpm lint`, `pnpm build` 모두 성공. 관련 Vitest 9개 파일, 88개 테스트 성공. `git diff --check` 성공.
- Home, Library, Workbench, Settings, Profile을 1440x900과 1024x680, light/dark에서 고정 GET 스냅샷으로 비교했다. 정상/오류/빈 결과/긴 내용 비교 30장, 추가 로딩/확대/탭/포커스 화면을 저장했다.
- 마우스/키보드 체크 81개 중 80개 자동 통과. 남은 확대된 표 경고는 의도한 내부 가로 스크롤이었다. 실제 키보드 focus 시 scrollLeft875로 이동하고 버튼이 보여 오탐으로 해소했다. 문서 자체 가로 넘침은 없었다.
- 추가로 1024x645에서도 다섯 화면을 확인했다. 512x340은 1024x680 창의 200% 확대에 해당하는 CSS 공간을 모사한 검사이며 실제 OS 확대 조작을 대체했다고 주장하지 않는다.
- 실제 개발 Electron 1400x865 viewport에서 밝음/어두움, 재분석 확인창, 에이전트 메뉴, 질문 카드의 포커스 복귀를 확인했다. 변경한 테마는 복원했고 저장된 테마 값도 유지했다.
- 화면의 완료 5는 실제 인증 API의 완료 phase 5와 일치했다. PDF의 28페이지는 PyMuPDF로 독립 확인했다. 실제 백엔드 인증 GET 200도 확인했다.
- 오류/긴 텍스트/응답 보류는 GET 목업이다. 정상 주요 화면은 동결된 실제 응답을 사용했다. 이미지 갤러리의 일부 이미지는 명시적 자리표시자여서 이미지 자산 연동 성공 근거로 사용하지 않았다. 모든 비GET 요청은 격리 context에서 차단됐으며 유료 AI 요청은 0건이었다.
- Impeccable 초기 CLI detector는 `[]`. 수정 후 자동 훅이 검사한 파일은 재검출하지 않았고, 빠진 9개 파일의 검사만 추가해 `[]`를 확인했다. live detector 공식 스크립트 inline 주입은 headless 4개 페이지에서 실행됐지만 사용자 창 overlay로 표시하지 않았다.
- 임시 detector 서버8400은 종료했다. 기존 Vite/backend/Electron은 유지했다. Aside guide는 설치 CLI와 호환되지 않아 기존 Playwright 및 Electron CDP를 사용했다.
- 원시 결과: [acceptance.json](assets/ui-refinement-2026-10-07/acceptance.json), [static checks](assets/ui-refinement-2026-10-07/static-checks.json), [동작 체크](assets/ui-refinement-2026-10-07/after-behavior.json), [합성 대비](assets/ui-refinement-2026-10-07/contrast.json), [history 이동 차단](assets/ui-refinement-2026-10-07/history-block.json).
- GUI 재현: 준비된 개발 서버에서 설치된 Playwright Python으로 `run_gui.py after`, `verify_behavior.py`, `verify_additional.py --loading`, `verify_additional.py --contrast`를 실행한다. 실제 API 쓰기와 유료 호출은 실행하지 않는다. 원본 검사 로그의 harness 초기 오류/잘못된 투명 배경 계산은 보존했으며 최종 해석은 contrast.json 및 acceptance.json을 따른다.

## 유지한 선택과 미검증

카드형 콘텐츠 묶음, 단일 Pretendard, 작업 탭, 기존 브랜드 오브를 결함으로 판정하지 않았다. PDF.js의 투명 selection text layer에 대한 작은 글자/line-height 경고, detector overlay 자체의 가림/광택 경고, 스크롤 가능한 표의 화면 밖 버튼은 실제 사용자 결함과 구분했다. A/B 초기 평가는 독립 기록에 보존했고 점수 상승을 완료 기준으로 사용하지 않았다. 중간 선택 질문은 사용자의 범위 내 수정/검증 승인으로 이미 답변됐다. Questions skipped: user authorized the scoped fixes and verification.

남은 확인된 P0/P1은 없다. 패키징된 배포 앱, 실제 Electron 창의 최소 크기 직접 변경, OS 전역 스크린 리더, 앱 종료/새로고침 시 초안 유지, 유료 분석/생성의 전체 동작은 미검증이다. 이동 차단은 앱 내부 라우터 탐색을 보호한다. 새 라이브러리나 시각 시스템을 도입하지 않았다.

핵심 원칙: **받아오지 못한 데이터는 빈 데이터가 아니다.** 성공한 응답의 빈 값, 로딩, 실패를 나눠야 사용자가 다음 행동을 올바르게 선택한다. API 응답을 보류하거나 실패시킨 뒤 화면의 문구와 복구 버튼을 대조하면 이 원칙을 다시 검증할 수 있다.
