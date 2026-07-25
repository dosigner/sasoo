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

1. phase content(마크다운 문자열) → `extractOutline(content)` → `OutlineItem[]` (`{ level, text, slug }`)
2. 헤딩 2개 이상이면 `<SectionOutline outline={...} />` 렌더
3. 본문은 `<Markdown headingAnchors>{content}</Markdown>` — 헤딩에 slug id 부여(rehypeHeadingIds). slug 규칙이 `extractOutline`과 동일하므로 목차 링크와 id가 정확히 매칭
4. 목차 항목 클릭 → `document.getElementById(slug)?.scrollIntoView({ behavior: 'smooth', block: 'start' })`

### 컴포넌트

**`SectionOutline.tsx` (신규)**
- props: `{ outline: OutlineItem[] }` (타입은 `mdOutline`에서 import)
- 렌더: 헤딩 레벨(`level`)에 따라 들여쓴 링크 목록. 각 항목 클릭 시 해당 slug id로 스크롤.
- 의존: `mdOutline`의 타입, DOM `scrollIntoView`. 다른 상태 없음 → 독립 렌더 가능.
- 표시 여부는 이 컴포넌트가 아니라 호출부가 판단한다(한 가지 일만 하도록).

**`AnalysisPanel.tsx`의 `PhaseSection` (수정, 현재 `<Markdown>` 사용 지점 335–339행)**
```
const outline = useMemo(() => (content ? extractOutline(content) : []), [content]);
...
{outline.length >= 2 && <SectionOutline outline={outline} />}
<Markdown headingAnchors>{content}</Markdown>
```

**`Markdown.tsx` (수정)**
- `headingAnchors`/`rehypeHeadingIds`는 이미 구현됨(uncommitted). 단, 테스트를 위해 `rehypeHeadingIds`를 `lib/rehypeHeadingIds.ts`로 분리하고 Markdown.tsx는 import해서 쓴다.

### 스타일

- 본문 위 작은 박스(rounded border, 배경 `surface`). 기존 AnalysisPanel의 border/surface 토큰 재사용.
- 항목: `level` 2를 기준으로 한 단계당 12px 들여쓰기. 텍스트 작게(text-xs), hover 시 accent 색.

## 테스트

컴포넌트 렌더 테스트 인프라가 없다(`@testing-library/*`·jsdom 미설치, `*.test.tsx` 0개). 기존 관례대로 **순수 함수만 vitest로 테스트하고 컴포넌트는 수동 검증**한다.

- `mdOutline.test.ts` (기존): `extractOutline`·`slugify` — 유지.
- `rehypeHeadingIds.test.ts` (신규): 헤딩 id 부여, 중복 시 `-2` 접미사, 기존 id 보존, 비헤딩 무시, 그리고 **`extractOutline`과 slug가 일치하는지**(목차 링크 계약) 검증.
- `SectionOutline`: 렌더·클릭은 자동 테스트 대신 빌드(`tsc -b && vite build`)와 실제 화면 수동 검증으로 확인.

## 영향 범위

- 신규: `lib/rehypeHeadingIds.ts`(+ `rehypeHeadingIds.test.ts`), `components/SectionOutline.tsx`
- 수정: `AnalysisPanel.tsx`(PhaseSection에 목차 삽입), `Markdown.tsx`(플러그인을 lib으로 분리, 기존 uncommitted 구현 포함 커밋)
- 재사용: `mdOutline.ts`(변경 없음)

## 검증

- `pnpm test` — `mdOutline` + `rehypeHeadingIds` 테스트 통과
- `pnpm build`(tsc + vite) / `pnpm lint` 통과
- 실제 분석 화면에서 단계를 펼쳐 목차 표시·클릭 점프 동작 확인(헤딩 2개 미만 단계는 목차 미표시, 한글 헤딩·중복 헤딩 점프 포함)
