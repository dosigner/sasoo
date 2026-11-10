# 용어 사전과 학술 분야 표시 검증 (2026-10-12)

영어 핵심 용어에 한국어 설명을 연결하는 용어 사전 기능과, 저장된 학술 분야를 분석 담당과 구분하는 화면 수정은 합의된 로컬 검증 범위를 통과했다. 용어 사전은 검색, 최대 3개 비교, 원문 검색 연결, hover와 키보드 접근을 제공한다. Workbench, Home 최근 논문, Library 목록과 카드에서는 `openalex_field`를 우선 표시하며 Library 필터는 기존 분석 담당 기준을 유지한다.

이 판정은 로컬 미커밋 기능과 고정 데이터로 검증한 화면 동작에 한정한다. 실제 AI가 영어 표기와 정의를 얼마나 정확히 생성하는지, 실제 사용자 DB의 분류가 정확한지, SCI/Scopus 등재 여부는 검증하지 않았다. 인계 기준으로 이 기능은 v1.2.2 배포에 포함되지 않았으며, 이번 문서 작성에서 원격 릴리스 상태를 다시 조회하거나 배포하지 않았다.

현재 소스 기준은 HEAD `3d0e7d2`, `sasoo/VERSION` 1.2.2다. 이번 변경을 커밋하거나 배포하지 않았다.

## 문제와 원인

한국어 설명을 읽는 동안 영어 전문용어의 뜻을 확인하고 서로 비교할 방법이 필요했다. 기존 읽기 안내에는 기호와 약어 중심의 표기 사전이 있었지만, 영어 개념명과 한국어 정의를 연결하는 별도 용어 목록은 없었다. 이번 기능은 기존 읽기 안내 생성과 캐시를 확장해 논문별 사전을 공유한다. 사람 검수를 거친 분야별 전역 고정 사전을 새로 구축한 것은 아니다.

분류 화면에는 서로 다른 의미의 값이 섞여 있었다. `openalex_field`는 저장된 학술 분야명이고, `domain`과 `agent_used`는 분석 담당을 선택하거나 표시하는 데 쓰인다. 예를 들어 Materials Science 논문을 general 담당이 처리할 수 있다. 화면이 `domain`만 학술 분야처럼 보여 주면 저장된 분야가 있어도 일반으로 보인다. [수정 전 GUI 기록](../../.scratch/terminology-20261012/classification-before.log)은 `light-1440:general:workbench-field`에서 실패했다.

사전 재생성에는 별도 상태 문제가 있었다. 기존 비교 선택 3개가 새 사전에서 사라져도 선택 배열에 남아 새 항목을 선택하지 못했다. 새 사전에 존재하는 선택만 유지하도록 수정했으며, 삭제된 선택을 제거한 뒤 새 용어 2개를 비교하는 회귀 검사가 추가됐다.

## 구현 범위와 동작

| 위치 | 역할과 변경 |
| --- | --- |
| [base_agent.py](../../sasoo/backend/services/agents/base_agent.py) | 핵심 전문용어의 영어 표기를 유지하고 뜻을 한국어로 설명하도록 지시한다. 실제 모델 준수율은 미검증이다. |
| [readingGuide.ts](../../sasoo/frontend/src/lib/readingGuide.ts) | 읽기 안내에 용어 사전 섹션을 함께 생성하고 파싱한다. 저장된 학술 분야는 참고 정보로 전달하며 논문 내용과 정의를 우선하도록 지시한다. |
| [useReadingGuide.ts](../../sasoo/frontend/src/hooks/useReadingGuide.ts), [ReadingGuideProvider.tsx](../../sasoo/frontend/src/components/ReadingGuideProvider.tsx) | 논문별 읽기 안내 상태와 사전을 공유한다. 새 결과 형식을 확인한 뒤 읽기 안내와 사전을 함께 교체한다. 실패와 취소 시 기존 결과를 유지한다. |
| [terminology.ts](../../sasoo/frontend/src/lib/terminology.ts) | 항목을 정리하고 최대 100개를 표시한다. 대소문자 중복은 합치고 논문 정의를 우선한다. 긴 표현을 먼저 매칭하며, 중의적인 약어는 임의의 한 뜻에 연결하지 않는다. 새 사전이 없으면 기존 표기 사전의 영어 항목을 사용한다. |
| [rehypeTerminology.ts](../../sasoo/frontend/src/lib/rehypeTerminology.ts), [Markdown.tsx](../../sasoo/frontend/src/components/Markdown.tsx) | 공통 Markdown의 영어 표현을 원문 그대로 유지하면서 한국어 tooltip을 연결한다. 링크, 버튼, 코드, 수식은 치환하지 않는다. |
| [TerminologyTab.tsx](../../sasoo/frontend/src/components/TerminologyTab.tsx) | 영어/한국어 검색, 최대 3개 비교, 범위와 확인된 페이지 표시, PDF 검색 연결을 제공한다. 검색어나 탭을 바꿔도 비교 선택을 유지하고 재생성 후 사라진 항목은 제거한다. |
| [workbenchSummaries.ts](../../sasoo/frontend/src/lib/workbenchSummaries.ts) | `paperFieldLabel`에서 공백을 제거한 `openalex_field`, 기존 `domain`의 표시명, 원래 `domain`, 빈 값 표시 순으로 선택한다. |
| [Workbench.tsx](../../sasoo/frontend/src/pages/Workbench.tsx), [Library.tsx](../../sasoo/frontend/src/pages/Library.tsx), [RecentPaperRow.tsx](../../sasoo/frontend/src/components/home/RecentPaperRow.tsx) | 공유 함수로 학술 분야를 표시한다. 분석 담당은 별도로 유지하며 Library 목록 열을 학술 분야, 필터를 분석 담당/모든 담당으로 설명한다. 필터 요청의 `domain` 값은 유지한다. |

생성 버튼은 AI 사용 비용과 읽기 안내의 동시 교체를 안내하는 확인 창을 거친다. 저장된 사전 검색, 비교와 hover 자체는 추가 모델 호출을 하지 않는다. 프롬프트는 분야 기본 용어와 논문의 핵심 용어를 합쳐 50~100개 이내로 요청하지만, 근거가 부족하면 적게 생성하고 수를 채우기 위해 용어나 정의를 만들지 말라고 명시한다. 표시 개수 제한 100개는 실제 논문에 확실한 용어가 100개 있다는 보장이 아니다.

## 검증 증거

아래는 이번 작업에서 남긴 로그를 직접 확인한 결과다. 문서 작성 단계에서 테스트와 브라우저를 다시 실행하지 않았다.

| 검사 | 결과 | 증거 |
| --- | --- | --- |
| 집중 프런트엔드 검사 | 2개 파일, 43개 테스트 통과 | [focused-tests.log](../../.scratch/terminology-20261012/focused-tests.log) |
| 전체 프런트엔드 검사 | 44개 파일, 365개 테스트 통과 | [frontend-tests.log](../../.scratch/terminology-20261012/frontend-tests.log) |
| 타입 검사와 프로덕션 빌드 | `tsc -b && vite build` 완료 | [frontend-build.log](../../.scratch/terminology-20261012/frontend-build.log) |
| lint | 경고를 허용하지 않는 ESLint 완료 | [frontend-lint.log](../../.scratch/terminology-20261012/frontend-lint.log) |
| 변경 공백 검사 | 이번 분류 표시 변경 6개 파일의 `git diff --check` 통과 | [diff-check.log](../../.scratch/terminology-20261012/diff-check.log) |
| 용어 GUI | 50개 확인, page/console 오류 0개, 금지된 API 쓰기 0개, 실제 모델 호출 0회, 합성 SSE 생성 1회 | [gui-results.json](../../.scratch/terminology-20261012/gui-results.json), [스크립트](../../.scratch/terminology-20261012/terminology-gui.mjs) |
| 분류 GUI | 79개 확인, page/console 오류 0개, API 쓰기 0개 | [classification-gui-results.json](../../.scratch/terminology-20261012/classification-gui-results.json), [스크립트](../../.scratch/terminology-20261012/classification-gui.mjs) |
| 독립 용어 리뷰 | 재생성 후 비교 선택 문제 resolved, ship | [terminology-review.md](../../.scratch/terminology-20261012/terminology-review.md) |
| 독립 분류 리뷰 | 저장된 학술 분야 표시와 분석 담당 구분 범위 ship | [classification-review.md](../../.scratch/terminology-20261012/classification-review.md) |

용어 GUI는 실제 Workbench와 실제 PDF renderer를 사용하되 API와 IndexedDB에는 고정 fixture를 넣었다. 라이트/다크 각각 1440×900과 1024×680에서 50개 목록, 검색을 바꾼 뒤 비교 유지, 3개 제한, 문서 전체 가로 넘침 없음, PDF 검색 이벤트, 한국어 hover, 키보드 정의 접근, Escape 닫기, 기존 안내 유지, 탭 전환과 새로고침 후 상태를 확인했다. 재생성 후 이전 선택 제거와 새 비교, 생성 비용 확인도 검사했다.

50개 용어 fixture 중 42개는 `Validation sample`이라는 합성 항목이다. 나머지 항목과 페이지도 동작 검사용이며 실제 논문의 정의에 대한 과학적 검수 증거가 아니다. 합성 SSE의 비용 0과 실제 생성의 비용은 구분해야 한다. `writes: []`는 금지된 API 쓰기가 없었다는 뜻이며, 테스트용 IndexedDB seed와 캐시 기록이 없었다는 뜻은 아니다. 실제 사용자 서버 DB에 쓰거나 DB를 재분류하지 않았다.

분류 GUI는 라이트/다크 각각 1440×900과 1024×900에서 다음 데이터와 화면을 대조했다. Home은 DOM 값으로 검사했고 별도 시각 캡처는 이번 필수 목록에 없다.

| fixture | 저장된 학술 분야 | 분석 담당 | 기대 표시와 관찰 |
| --- | --- | --- | --- |
| Materials | Materials Science | `domain=general`, `agent_used=general` | 학술 분야는 Materials Science, 담당은 General. general 필터에 남고 요청은 `domain=general`을 사용한다. |
| Computer | Computer Science | `domain=ai_ml`, `agent_used=neural` | 학술 분야는 Computer Science, 담당은 Neural로 유지된다. |
| Legacy | 없음 | `domain=optics`, `agent_used=photon` | 학술 분야는 기존 표시명 광학으로 대체하고 담당은 Photon으로 유지된다. |

general 담당의 일부 메타데이터는 fixture에서 합성했다. Materials fixture도 공통 Flow Matching PDF와 분석 결과를 재사용하므로 PDF 내용이 Materials Science에 속한다는 검증으로 해석하면 안 된다. 이번 검사는 저장값의 표시와 담당 구분을 확인한다. screening 본문의 분야와 전체 taxonomy 일관성은 별도 문제다.

## 기존 디자인과의 일치

새 시각 세계나 디자인 시스템 변경은 승인 범위에 없었다. PRODUCT.md/DESIGN.md는 없으며, 기존 [design-tokens.md](../../sasoo/docs/04-design/design-tokens.md), 실제 [index.css](../../sasoo/frontend/src/index.css), 공통 [Tooltip.tsx](../../sasoo/frontend/src/components/ui/Tooltip.tsx)와 기존 화면을 권위로 삼았다. 디자인 파일과 공통 CSS/Tooltip에는 이번 범위의 변경을 추가하지 않았다.

관찰한 시스템은 다음 다섯 줄로 요약할 수 있다.

1. 무채색 배경과 표면에 퍼플 accent를 적용하며 상태는 기존 success/error 토큰으로 표시한다.
2. Pretendard Variable과 기존 글자 크기 위계를 사용한다. 본문 13px, 보조 정보 12px, 사전 제목 17px이며 새 글꼴을 추가하지 않는다.
3. 입력과 비교 표는 기존 control 반경 6px, 기존 카드/빈 상태는 surface 반경 12px을 사용한다. 사전 목록은 구분선과 여백으로 묶는다.
4. 검색 입력, 생성/취소 버튼, Modal, ContentState와 Tooltip을 재사용하고 focus와 hover는 공통 accent를 사용한다.
5. Workbench의 PDF/분석 분할과 기존 탭 체계를 유지한다. 좁은 비교 표는 표 내부에서 가로 스크롤하고 Library 필터는 기존 pill과 줄바꿈을 유지한다.

기존 [Workbench 라이트 1440 캡처](assets/ui-refinement-2026-10-07/after/workbench-light-1440.png)와 [Library 다크 1024 캡처](assets/ui-refinement-2026-10-07/after/library-dark-1024.png)를 새 캡처와 직접 비교했다. 같은 계열의 배경, 구분선, 본문 밀도, 탭 강조와 카드 표면을 유지한다. 데이터와 선택 상태가 서로 다르므로 픽셀 단위 동등 비교로 주장하지 않는다. 새로운 CSS, 토큰, 그림 자산이나 모션을 추가하지 않았다.

| 상태 | 직접 확인 가능한 캡처 |
| --- | --- |
| 사전, 라이트 넓은 화면 | [dictionary-light-1440.png](../../.scratch/terminology-20261012/dictionary-light-1440.png) |
| 사전, 다크 좁은 화면 | [dictionary-dark-1024.png](../../.scratch/terminology-20261012/dictionary-dark-1024.png) |
| 한국어 hover, 다크 좁은 화면 | [hover-dark-1024.png](../../.scratch/terminology-20261012/hover-dark-1024.png) |
| 사전 없음, 재생성 후 새 비교 | [dictionary-empty.png](../../.scratch/terminology-20261012/dictionary-empty.png), [dictionary-regenerated.png](../../.scratch/terminology-20261012/dictionary-regenerated.png) |
| 분야/담당 구분, Workbench | [classification-workbench-dark-1024.png](../../.scratch/terminology-20261012/classification-workbench-dark-1024.png) |
| 학술 분야, Library 목록 | [classification-library-list-light-1440.png](../../.scratch/terminology-20261012/classification-library-list-light-1440.png) |
| 학술 분야, Library 카드 | [classification-library-grid-dark-1024.png](../../.scratch/terminology-20261012/classification-library-grid-dark-1024.png) |

나머지 테마/크기 조합의 파일명은 각 GUI 결과 JSON의 `captures`에 기록돼 있다. 분류 독립 reviewer는 필수 12개 캡처를 모두 확인했다. 문서 작성자는 위 대표 캡처와 기존 캡처를 직접 열어 비교했다.

기존 Library의 `ARCHIVE VIEW`와 분류 기준 위쪽의 작은 라벨은 기존 화면이 갖고 있는 요소로 남아 있다. 이들을 새 시스템 규칙으로 승격하지 않았고 별도 디자인 승인이 없어 전면 수정하지 않았다. 새 detector 실행이나 전체 앱 디자인 승인으로 범위를 확대하지 않았다.

## 재현 방법

저장된 GUI 결과와 로그는 위 링크에서 먼저 확인한다. 테스트 환경에는 프로젝트의 pnpm 의존성과 로컬 Chrome이 필요하다. GUI 스크립트는 현재 머신의 Playwright 절대 경로를 import하므로 다른 머신에서는 그 경로를 조정해야 한다.

```bash
# Run from sasoo/frontend.
pnpm exec vitest run src/lib/workbenchSummaries.test.ts src/components/Terminology.dom.test.tsx
pnpm test
pnpm build
pnpm lint
pnpm dev --host 127.0.0.1 --port 5187
```

별도 터미널에서 프로젝트 루트를 작업 디렉터리로 두고 실행한다.

```bash
node .scratch/terminology-20261012/terminology-gui.mjs
node .scratch/terminology-20261012/classification-gui.mjs
```

이 스크립트는 API를 고정 데이터로 응답하고 유료 호출과 서버 쓰기를 차단한다. 결과와 캡처 출력 경로가 고정돼 있으므로 기존 증거를 보존하려면 재실행 전에 별도 복사본에서 출력 경로를 바꿔 사용한다. 이번 문서 작성에서는 재실행하지 않았고 `.scratch/terminology-20261011`의 이전 증거도 유지했다.

## 남은 한계와 실패 조건

- 한국어 hover는 공통 Markdown으로 렌더되는 분석/토의의 영어 표현에 적용된다. PDF 원문 텍스트와 이미지 위 tooltip은 제공하지 않는다. 기존 한국어 문장을 자동으로 영어로 변환하지도 않는다.
- 용어 사전은 논문별 읽기 안내와 함께 AI가 생성하고 저장한다. 실제 모델의 영어 표기 준수율, 정의 정확도, 근거 페이지 정확도와 과학적 의미는 미검증이다. UI의 항목 범위와 페이지는 생성값이며 원문 대조가 필요하다.
- 프런트엔드 정상 캐시 경로와 새로고침은 fixture로 확인했지만 실제 사용자 환경의 저장소 실패, 설치된 Electron 앱, 실제 AI/SSE와의 통합은 이번 GUI 검사의 증거 범위 밖이다.
- 로컬 [openalex_subfields.json](../../sasoo/backend/agents/openalex_subfields.json)은 직접 집계한 결과 15개 field, 131개 subfield를 포함한다. 파일 메타데이터는 Physical Sciences와 Life Sciences 범위를 명시한다. 전체 학문 분류나 SCI/Scopus 등재 판정 시스템으로 취급하지 않는다.
- [analysis_execution.py](../../sasoo/backend/services/analysis_execution.py)의 screening 후 담당 선택 경로는 `screening.domain`을 우선하고 `papers.domain`과 `agent_used`를 갱신한다. 이 담당 덮어쓰기 경로는 이번 작업에서 수정하지 않았다.
- [agents/__init__.py](../../sasoo/backend/services/agents/__init__.py)는 알 수 없는 registry 키에 대해 optics/photon을 우선 대체한다. 이 동작도 아직 수정하지 않았다.
- taxonomy 정보가 없는 구형 논문은 기존 `domain`의 표시명으로 대체할 뿐 자동 재분류하지 않는다. 실제 사용자 DB migration 상태는 확인하지 않았다.
- backend 1162개와 Electron 282개 통과는 이전 단계의 기록이며 이번 단계에서 다시 실행한 결과가 아니다. 이번 증거로 해당 계층의 현재 상태나 배포 앱을 승인하지 않는다.
- 독립 reviewer의 ship은 용어 재생성 비교 상태 수정 한 건과 저장된 분야 표시 확장에만 적용된다. 전체 UI, 실제 분류 정확도, 전체 taxonomy의 일관성은 포함하지 않는다.

## 학습 메모

핵심은 화면의 학술 분야와 분석 담당이 서로 다른 데이터라는 점이다. 하나의 문자열이 여러 의미를 대표하게 두면 정확한 저장값도 오해를 만든다. 재사용 가능한 원칙은 각 표시값의 출처를 명시하고 공통 표시 함수에서 우선순위를 한 번만 정하는 것이다. `openalex_field=Materials Science`, `domain=general`인 사례를 넣고 Workbench/Home/Library 표시와 `domain=general` 필터 요청을 함께 대조하면 재현할 수 있다. 흔한 함정은 고정 fixture의 화면 통과를 AI의 분류 정확도나 실제 DB 재분류 완료로 확대하는 것이다.

이번 범위에서 생략한 것은 새 전역 사전 구축, DB 재분류/migration, 신규 디자인 시스템, 새 의존성, 유료 모델 평가와 배포다. 사용 시 남는 위험은 AI가 만든 정의의 오류와 기존 backend 담당 선택 경로가 저장된 학술 분야와 다르게 동작할 가능성이다.
