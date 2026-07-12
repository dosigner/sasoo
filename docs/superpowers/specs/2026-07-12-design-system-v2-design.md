# 디자인 시스템 v2 — "Minimalist Intelligence" 보정판

- 날짜: 2026-07-12
- 브랜치: feature/gui-redesign
- 원본: `/Users/dongj/Downloads/DESIGN.md` (외부 제안)
- 검토 방식: deep-reasoner(Opus) + Codex 독립 병렬 비평 후 종합. 컴포넌트/영역별 5-whys 근거 수록
- 관계: `2026-07-11-openai-platform-home-redesign-design.md`(홈+사이드바 구조 스펙)의 비주얼 레이어를 정의. 구조 스펙의 "토큰 불변" 원칙은 본 문서로 대체됨

## 0. 결론

DESIGN.md는 **방향만 채택하고 구체값은 기각**한다. frontmatter(M3 제너레이터 덤프)와 본문(수기)이
서로 모순되어 색 원본의 권위가 없다(배경 #f9f9fa vs #FFFFFF, 보더 #cfc4c5 vs #E5E5E5, 퍼플 3종).
현재 앱의 라이트 테마가 이미 DESIGN.md 의도의 ~90%를 구현하고 있으므로, v2는 재설계가 아니라
다음 5개 변경으로 수렴한다:

1. **기본 테마를 라이트로 플립** (다크는 1급 파생으로 유지) — 사용자 확정
2. **액센트 인디고 → 퍼플** 값 교체 (라이트 #683DCC, 다크 #7C5AE8 — 컴포넌트 churn 0)
3. **라이트 `fg-muted` 접근성 버그 수정** (#8e8e96 3.25:1 → #70707A 4.8:1)
4. **JetBrains Mono를 메타데이터·논문 ID·citation에 실사용**
5. **라이트 뉴트럴을 true-gray로 정규화** (warm-tint 기각)

13개 시맨틱 토큰 아키텍처, control/surface 이중 radius, 3종 상태색, 2px 포커스 링, Pretendard는
전부 유지한다.

## 1. 색상 토큰 (13개 유지, 값 재정의)

`:root` = 라이트(신규 기본), `.dark` = 다크. RGB 채널 형식은 현행 유지.

| 토큰 | 라이트 `:root` | 다크 `.dark` | 비고 |
|---|---|---|---|
| `--bg` | #F7F7F8 | #0a0a0b (현행) | 캔버스. 라이트는 회색, 카드가 흰색으로 raised |
| `--surface` | #FFFFFF | #17171a (현행) | 카드·사이드바·입력 |
| `--surface-hover` | #EFEFF1 | #202024 (현행) | hover/선택 배경 |
| `--border` | #E4E4E7 | #2a2a30 (현행) | true-gray. #cfc4c5(warm) 기각 |
| `--fg` | #18181B | #f4f4f5 (현행) | 본문·제목 |
| `--fg-secondary` | #52525B | #a1a1aa (현행) | 7.6:1 |
| `--fg-muted` | **#70707A** | #70707A | **버그 수정**: 라이트 기존 #8e8e96은 3.25:1로 AA 미달 |
| `--accent` | **#683DCC** | **#7C5AE8** | 인디고→퍼플. 흰 텍스트 대비 라이트 6.71:1 / 다크 4.67:1 |
| `--accent-hover` | #5221B6 | #9179F0 | 라이트=어둡게, 다크=밝게 (현행 패턴) |
| `--accent-fg` | #FFFFFF | #FFFFFF | 액센트 위 텍스트. 다크도 흰 텍스트(현행형) — 사용자 확정 |
| `--danger` | #dc2626 (현행) | #ef5a5a (현행) | 변경 없음 |
| `--warning` | #d97706 (현행) | #f59e0b (현행) | 변경 없음 |
| `--success` | #16a34a (현행) | #34c77b (현행) | 변경 없음 |

**왜 이 팔레트인가 (5-whys 종착점):**
- 왜 모노크롬 + 단일 액센트? → 논문 텍스트·차트가 UI보다 먼저 읽혀야 하므로 UI는 물러난다.
- 왜 warm-tint 기각? → frontmatter의 분홍기 뉴트럴은 M3 시드 컬러의 부작용이며 "strictly
  monochromatic" 선언 자체와 모순.
- 왜 #683DCC? → 퍼플 3종 중 흰 텍스트 대비 여유가 가장 큼(6.71:1 vs 5.83/4.65). frontmatter의
  최초 시맨틱 `secondary` 값이기도 함.
- 왜 다크 액센트는 4.5:1 미달(텍스트 용도 4.2:1)을 수용? → 단일 퍼플로 fill(흰 텍스트)과
  dark-bg 텍스트를 동시에 4.5:1 맞추는 해는 존재하지 않음. 버튼 외형 연속성을 위해 fill
  우선(4.67:1 통과), 텍스트 용도는 현행 인디고와 동일한 한계를 문서화하고 수용.
- 왜 상태색 3종 유지? → Library 행이 pending/analyzing/completed/error 4-상태를 실제 소비.
  DESIGN.md가 success만 언급한 것은 범용 템플릿이라 비운 것.

## 2. 타이포그래피

- **sans: Pretendard Variable 단독 유지. Inter 미도입.**
  - 왜? → Inter에는 한글 글리프가 없다. 한국어 UI에서 Inter를 앞에 두면 한글은 시스템 폰트로
    폴백되어 한 문장 안에서 자폭·기준선·굵기가 갈라진다. Pretendard는 애초에 Inter류 라틴
    메트릭과 한글을 한 variable font에 담도록 설계된 폰트라, DESIGN.md가 Inter로 얻으려던
    "정돈된 기술적 인상"을 한글 포함으로 달성한다.
- **mono: JetBrains Mono** (현행 스택) — 메타데이터, 논문 ID/DOI, citation, 기술 스니펫에
  `font-mono` 실사용. DESIGN.md에서 새로 얻는 유일한 타이포 가치이며 이미 번들돼 있어 비용 0.
- 위계는 크기보다 **weight(400/600)**로: DESIGN.md 원칙 채택, 현행 규칙(700+ 금지)과 일치.
- 크기 스케일: 현행 rem 스케일 유지. `label-caps` 패턴(11px/600/0.05em uppercase muted)은
  섹션 헤더·리스트 헤더에 적용 (기존 `archive-kicker` 관례 확장).

## 3. 형태 (radius)

`--radius-control: 6px`(버튼·입력·칩) / `--radius-surface: 12px`(카드·패널·모달) /
`--radius-pill`(배지·토글) — **현행 유지, DESIGN.md의 6px 단일화 기각.**

- 왜? → 이중 radius는 장식이 아니라 "담김(containment)" 신호다. 큰 컨테이너 12px vs 조작부
  6px의 대비가 위계를 형태로 전달한다. 6px 단일화는 이 정보를 소거하며, DESIGN.md 스스로도
  frontmatter(2~12px 스케일)와 본문(6px 단일)이 모순된다. 32+ 사용처가 이미 연결됨.

## 4. 깊이 (elevation)

- **카드·사이드바·리스트: 그림자 없음, 1px `--border` + tonal layer** (bg 회색 < surface 흰색).
  DESIGN.md 원칙 채택 — 다크의 기존 논리(bg < surface, 밝을수록 raised)와 정확히 대칭이라
  신규 토큰 불필요.
- **모달·팝오버·드래그 오버레이: 그림자 유지** (Codex 지적 채택).
  - 왜? → 실제로 다른 평면 위에 뜨는 계층은 1px 보더만으론 분리가 약하다. 무그림자 원칙은
    같은 평면 내 구획에만 적용한다.
- hover: `--surface-hover` 배경 전환만. glow/gradient 장식 금지.

## 5. 인터랙션 상태

- **포커스: `focus-visible` 시 2px `--accent` 링 + 2px offset, 단일 규칙.** 파괴적 컨트롤만
  `--danger` 링. 마우스 클릭에는 미표시.
  - 왜? → DESIGN.md의 "1px black or 2px ring" 양자택일은 키보드 어포던스를 파편화하고,
    보더 있는 입력 위 1px 검정은 시인성이 낮다. WCAG 2.4.7 + 1.4.11(비텍스트 3:1) 충족.
    현행 코드가 이미 이 규칙 — 유지.
- 입력 필드: `--surface` 배경 + 1px `--border`. 라이트에서 #E4E4E7/흰색은 1.3:1로 낮으므로
  라벨·배치로 식별을 보조하고 포커스 링이 고대비 상태를 담당 (구현 후 시각 QA 항목).

## 6. 컴포넌트 규칙

| 컴포넌트 | 규칙 | 왜 (종착 근거) |
|---|---|---|
| 버튼 Primary | `--fg` 배경 + `--bg` 텍스트 (라이트=검정 버튼) | DESIGN.md의 "high-emphasis=검정" 채택. 액센트는 '작업 결과'에 아껴야 하므로 범용 CTA는 무채색 |
| 버튼 Secondary | `--surface` + 1px `--border` | 구조 분리는 전부 1px 보더로 — elevation 원칙과 동일 문법 |
| 버튼 Ghost | 배경 없음, hover 시 `--surface-hover` | 저빈도 액션의 시각 소음 제거 |
| 카드 | `--surface` + 1px `--border`, radius 12px, 무그림자 | §4 |
| 데이터 리스트 | 행 구분 1px `--border`, 헤더는 label-caps + `--fg-muted` | "blueprint" 수평선 문법. 헤더는 콘텐츠가 아니므로 muted |
| Citation Chip | 현행 유지: `--accent`/10 배경 + `--accent` 텍스트 + mono | DESIGN.md는 정적 회색 칩을 가정했으나 실제로는 클릭백 액티브 요소 — "accent=active state"라는 DESIGN.md 자신의 원칙에 현행이 더 부합 |
| Analysis Progress | 4px `--accent` 바 (결정형 진행에 한정) | discrete 상태는 기존 phase-dot(상태색) 담당 — 의미 충돌 없음 |
| 사이드바 | 13rem 펼침 / 4.5rem 접힘, 활성 항목 6px radius `--surface-hover` 하이라이트 | 260px은 범용 디폴트. 한글 라벨 4개엔 208px면 충분하고 PDF 3-패널 앱에서 52px는 콘텐츠 몫. 기존 `--sidebar-width: 16rem`은 13rem으로 정리 |

## 7. 테마 플립 구현 메모

`dark:` Tailwind variant 사용 0건 확인 — 플립 리스크 낮음. 실작업 4곳:

1. `index.css`: `:root`=라이트 값, `.dark`=다크 값으로 블록 스왑 (`.light` 클래스 폐기)
2. `App.tsx:64-68`: 테마 클래스 토글이 `.dark`를 의미 클래스로 다루도록 반전
3. `MermaidRenderer.tsx:184,195`: `!classList.contains('light')` → `classList.contains('dark')`
4. 기본 테마 `light` (localStorage `sasoo-theme` 마이그레이션 고려)

## 8. 검증 기준

- 5개 라우트 × 2테마 × density compact 스크린샷 QA (launch-sim)
- Workbench 회귀: PDF 툴바, resize handle, 채팅 버블, 분석 상태 행 — 동일 13토큰 소비
- 콘트라스트 스팟체크: fg-muted/bg, accent 텍스트, 상태색 배지 (계산값이므로 실화면 재확인)
- 입력 필드가 라이트에서 보더만으로 식별되는지 (미달 시 배경 차이 강화, 토큰 추가는 최후)

## 9. 트레이드오프 (수용한 것)

- 인디고 #5e6ad2 브랜드 연속성 포기 → 퍼플 채택 (DESIGN.md 채택 정신)
- 다크 액센트-as-text 4.2:1 (현행과 동일 프로파일, fill 우선)
- 다크에서 쓰던 gradient/blur/inset 장식 제거 (콘텐츠 우선 원칙)
- "DESIGN.md를 그대로 구현"이라는 설명 가능성 — 실제로는 한국어·다크·접근성 보정판
