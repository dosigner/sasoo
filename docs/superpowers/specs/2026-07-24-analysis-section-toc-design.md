# 분석 단계 안 목차(ToC) — 설계

## Context

sasoo 분석 결과는 5단계(Phase 1~5) 아코디언으로 표시되고, 각 단계 안의 Markdown 본문은 길어질 수 있다(특히 심층분석·recipe). 본문 안 특정 섹션으로 바로 가려면 스크롤로 찾아야 해 불편하다.

목차 인프라는 일부 만들어져 있으나 실제 UI에 연결된 곳이 없어 미완 상태다:
- `sasoo/frontend/src/lib/mdOutline.ts` — `extractOutline(md)`, `slugify()` (커밋 cf926d9, 테스트 포함). 현재 사용처 0.
- `sasoo/frontend/src/components/Markdown.tsx` — `headingAnchors` prop + `rehypeHeadingIds` 플러그인(헤딩에 slug id 부여). 아직 커밋 안 됨, 넘기는 곳 0.

이 설계는 그 인프라를 각 단계 본문에 연결해 "단계 안 목차" 기능을 완성한다.

## 목표

- 각 분석 단계를 펼치면 본문 위에 그 단계의 헤딩 목차를 보여준다.
- 목차 항목 클릭 시 해당 헤딩으로 부드럽게 스크롤.
- 헤딩이 **2개 이상**인 단계에서만 목차를 표시(짧은 본문엔 생략).

비목표(YAGNI): scroll spy(현재 섹션 하이라이트), 전역 사이드바 목차, 단계 간 점프.

## 설계

### 데이터 흐름

1. phase content(마크다운 문자열) → `extractOutline(content)` → `OutlineItem[]` (`{depth, text, slug}`)
2. 헤딩 2개 이상이면 `<SectionOutline outline={...} />` 렌더
3. 본문은 `<Markdown headingAnchors>{content}</Markdown>` — 헤딩에 slug id 부여(rehypeHeadingIds). slug 규칙이 `extractOutline`과 동일하므로 목차 링크와 id가 정확히 매칭
4. 목차 항목 클릭 → `document.getElementById(slug)?.scrollIntoView({ behavior: 'smooth', block: 'start' })`

### 컴포넌트

**`SectionOutline.tsx` (신규)**
- props: `{ outline: OutlineItem[] }` (타입은 `mdOutline`에서 import)
- 렌더: depth에 따라 들여쓴 링크 목록. 각 항목 클릭 시 해당 slug id로 스크롤.
- 의존: `mdOutline`의 타입, DOM `scrollIntoView`. 다른 상태 없음 → 독립 렌더/테스트 가능.

**`AnalysisPanel.tsx`의 `PhaseSection` (수정, 현재 `<Markdown>` 사용 지점 ~337행)**
```
const outline = extractOutline(content);
...
{outline.length >= 2 && <SectionOutline outline={outline} />}
<Markdown headingAnchors>{content}</Markdown>
```

**`Markdown.tsx` (커밋만)**
- `headingAnchors`/`rehypeHeadingIds`는 이미 구현됨(uncommitted). 그대로 커밋.

### 스타일

- 본문 위 작은 박스(rounded border, 배경 `surface`). 기존 AnalysisPanel의 border/surface 토큰 재사용.
- 항목: depth 2 = 기본 들여쓰기, depth 3+ = 단계별 추가 들여쓰기(pl-*). 텍스트 작게(text-xs/sm), hover 시 accent 색.

## 테스트

- `mdOutline.test.ts` (기존): `extractOutline`·`slugify` — 유지.
- `SectionOutline.test.tsx` (신규):
  - outline 배열 → 링크 목록 렌더(개수·텍스트 검증).
  - 항목 클릭 시 `getElementById` + `scrollIntoView` 호출(mock).
  - depth에 따른 들여쓰기 클래스 반영.

## 영향 범위

- 신규: `SectionOutline.tsx`, `SectionOutline.test.tsx`
- 수정: `AnalysisPanel.tsx`(PhaseSection에 목차 삽입), `Markdown.tsx`(커밋)
- 재사용: `mdOutline.ts`(있음)

## 검증

- `vitest` — `mdOutline` + `SectionOutline` 테스트 통과
- `tsc` / `vite build` 통과
- 실제 분석 화면에서 단계를 펼쳐 목차 표시·클릭 점프 동작 확인(헤딩 2개 미만 단계는 목차 미표시 확인)
