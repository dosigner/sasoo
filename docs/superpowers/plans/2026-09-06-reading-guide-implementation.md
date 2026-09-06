# 읽기 안내 구현 계획

브리프: `docs/superpowers/specs/2026-09-05-reading-guide-design.md`. 프론트만 수정, 백엔드 0.

## 확인한 접점

- 채팅: `chatWithAgent(paperId, message, history, onToken, onDone, signal)` (lib/api.ts:743). 서버가 논문 전문을 붙이고 `ChatDoneMeta{tokens_in, tokens_out, cost_usd}`를 돌려준다.
- PDF 이동: `PdfNavigationRequest{page, requestId, source, highlight?}` (lib/api.ts:136). Workbench의 `setNavigationRequest`.
- PDF 검색: PdfViewer 내부 `dispatchFind`가 pdf.js `find` 이벤트를 쏜다(components/PdfViewer.tsx:520). 외부에서 검색을 시키는 prop은 없어 추가한다. pdf.js 새 검색은 현재 보이는 페이지부터 시작하므로 "페이지 이동 후 find"로 첫 정의 위치 점프가 된다.
- 채팅 초안 주입: Workbench `chatDraft`/`setChatDraft` → ChatPanel `draft` prop. 이미 있다.
- 설명 수준: `paper.explanation_level`(Workbench:413에서 AnalysisPanel에 `paperLevel`로 전달).
- 탭: AnalysisPanel `activeTab` 5종(summary, figures, tables, recipe, experiment). `citationFocus.tab`은 figures/tables만.
- 로컬 저장: localStorage는 테마 등에만 쓰고 IndexedDB 사용처 없음.
- 인용 파서: `lib/citations.ts` `detectCitations(text)`. 채팅 답변에서 칩으로 렌더.

## 덩어리 A+B: 데이터 계층과 읽기 안내 탭 (먼저)

새 파일
- `lib/readingGuide.ts`: `buildReadingGuidePrompt(level)`, `parseReadingGuide(markdown)`. 고정 헤딩 `## 표기 사전`, `## 선행 지식`, `## 섹션별 직관`. 항목 형식은 프롬프트가 지정하고 파서는 관대하게(형식이 어긋나면 raw 마크다운 폴백).
- `lib/guideCache.ts`: IndexedDB `sasoo-reading-guide`/store `guides`, key paperId, 값 `{markdown, createdAt, level, costUsd}`. IDB 불가 시 메모리 폴백.
- `hooks/useReadingGuide.ts`: idle → cache 조회 → empty | ready. `generate()`는 스트리밍 텍스트 누적, 완료 시 캐시 저장. `regenerate()`는 확인 후 동일. 오류는 상태로.
- `components/ReadingGuideTab.tsx`: 빈 상태(비용 안내 + 생성 버튼 + 확인 모달), 생성 중(스트리밍 마크다운), 준비됨(메타 한 줄 + 표기 사전 목록/필터 + 선행 지식 카드 + 섹션 아코디언), 오류(재시도), 설명 수준 불일치 메타.

수정
- `components/AnalysisPanel.tsx`: 탭 5개 `summary, guide, figures, tables, recipe`. experiment 탭 제거, `ExperimentPlanTab`을 recipe 탭 하단 섹션으로.
- `components/PdfViewer.tsx`: `searchRequest?: {term, page, requestId}` prop. 페이지 이동 후 `dispatchFind`.
- `pages/Workbench.tsx`: `onJumpToPage`, `onSearchInPdf` 배선, `searchRequest` 상태.
- `lib/strings.ts`: `S.readingGuide`.
- `lib/api.ts`: `PdfNavigationRequest.source`에 `'guide'` 추가.

테스트: 파서 4건(정상, 페이지 없음, 헤딩 누락 폴백, 빈 입력), 프롬프트에 설명 수준 포함 1건, 캐시 메모리 폴백 1건.

## 덩어리 C: PDF 선택 팝오버 (A+B 뒤, D와 병렬)

- PdfViewer: `onTextSelected?({text, page, rect})`. mouseup에서 `window.getSelection()`이 텍스트 레이어 안이면 발화. 텍스트 레이어 없음(스캔)은 미발화.
- Workbench: 선택 위 팝오버 버튼 "이 부분 설명" 하나. 클릭 시 `S.readingGuide.explainPrompt(page, text)`로 초안 만들고 채팅 열기. 2,000자 초과 시 안내만.

## 덩어리 D: 요약 탭 인용 칩 (C와 병렬)

- 요약 탭(deep_dive 마크다운)의 "Fig. 3", "Table 2", "p.12"를 `detectCitations`로 칩화. 클릭은 Workbench `handleCitationClick` 재사용. AnalysisPanel과 Markdown.tsx 접점.

## 검증

각 덩어리: `npx tsc --noEmit -p tsconfig.json`, `pnpm test`, `pnpm lint`. 마지막에 `pnpm build`, 실행 중인 앱에서 CDP 캡처(생성은 사용자 데이터 논문 1편으로 1회만, 비용 확인 후).
