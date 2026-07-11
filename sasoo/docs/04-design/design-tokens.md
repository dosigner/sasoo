# Sasoo 디자인 토큰 명세 v1.0

Linear식 모노크롬: 무채색 베이스 + 단일 액센트(인디고) + 시맨틱 상태색 3종.
JSX는 시맨틱 클래스를 선언하고, 값은 `:root`(다크)/`.light` CSS 변수가 단일 소스로 결정한다.
`[.light_&]` variant, `.light [class*=...]` 속성 셀렉터, 테마별 이중 정의는 전면 금지.

## 1. 색상 토큰 (RGB 채널 방식 — alpha 지원)

CSS 변수는 `--name: R G B;` 형식. Tailwind에서 `rgb(var(--name) / <alpha-value>)`로 참조.

| 토큰 | 다크 (`:root`) | 라이트 (`.light`) | 용도 |
|---|---|---|---|
| `--bg` | `10 10 11` (#0a0a0b) | `250 250 250` (#fafafa) | 앱 배경 |
| `--surface` | `23 23 26` (#17171a) | `255 255 255` (#ffffff) | 카드·패널·입력 배경 |
| `--surface-hover` | `32 32 36` (#202024) | `240 240 242` (#f0f0f2) | hover·active 배경 |
| `--border` | `42 42 48` (#2a2a30) | `228 228 231` (#e4e4e7) | 테두리·구분선 |
| `--fg` | `244 244 245` (#f4f4f5) | `24 24 27` (#18181b) | 본문·제목 텍스트 |
| `--fg-secondary` | `161 161 170` (#a1a1aa) | `82 82 91` (#52525b) | 보조 텍스트 |
| `--fg-muted` | `112 112 122` (#70707a) | `142 142 150` (#8e8e96) | 비활성·플레이스홀더 |
| `--accent` | `94 106 210` (#5e6ad2) | `94 106 210` (#5e6ad2) | 버튼·링크·포커스·선택 |
| `--accent-hover` | `110 121 221` (#6e79dd) | `79 90 191` (#4f5abf) | 액센트 hover |
| `--accent-fg` | `255 255 255` | `255 255 255` | 액센트 배경 위 텍스트 |
| `--danger` | `239 90 90` (#ef5a5a) | `220 38 38` (#dc2626) | 오류·Red Flag |
| `--warning` | `245 158 11` (#f59e0b) | `217 119 6` (#d97706) | 경고 |
| `--success` | `52 199 123` (#34c77b) | `22 163 74` (#16a34a) | 성공·완료 |

총 13개. 추가 금지 — 새 색이 필요하면 이 13개의 alpha 변형으로 해결한다.

### Tailwind config 매핑 (신규 시맨틱 유틸)

```js
colors: {
  bg: 'rgb(var(--bg) / <alpha-value>)',
  surface: {
    // 레거시 50~950 스케일은 마이그레이션 기간 병존 (P4 완료 후 삭제)
    DEFAULT: 'rgb(var(--surface) / <alpha-value>)',
    hover: 'rgb(var(--surface-hover) / <alpha-value>)',
  },
  border: 'rgb(var(--border) / <alpha-value>)',
  fg: {
    DEFAULT: 'rgb(var(--fg) / <alpha-value>)',
    secondary: 'rgb(var(--fg-secondary) / <alpha-value>)',
    muted: 'rgb(var(--fg-muted) / <alpha-value>)',
  },
  accent: {
    DEFAULT: 'rgb(var(--accent) / <alpha-value>)',
    hover: 'rgb(var(--accent-hover) / <alpha-value>)',
    fg: 'rgb(var(--accent-fg) / <alpha-value>)',
  },
  danger: 'rgb(var(--danger) / <alpha-value>)',
  warning: 'rgb(var(--warning) / <alpha-value>)',
  success: 'rgb(var(--success) / <alpha-value>)',
}
```

주의: 시맨틱 텍스트는 `text-fg`/`text-fg-secondary`/`text-fg-muted`로 명명한다
(`text-primary`는 레거시 `primary` 블루 팔레트와 충돌하므로 금지).

## 2. Radius — 3종만

| 토큰 | 값 | 용도 |
|---|---|---|
| `--radius-control` | `6px` | 버튼·입력·셀렉트·배지 |
| `--radius-surface` | `12px` | 카드·패널·모달·팝오버 |
| `--radius-pill` | `9999px` | pill·아바타·토글 |

기존 `--radius-control`(12px)/`--radius-surface`(16px)의 **값만 재정의**한다(사용처 32곳 자동 반영).
`rounded-[18px]`~`rounded-[28px]` 등 arbitrary radius는 전부 위 3종으로 수렴.
Tailwind: `borderRadius: { control: 'var(--radius-control)', surface: 'var(--radius-surface)' }` → `rounded-control`, `rounded-surface`.

## 3. 타이포그래피

- 폰트: **Pretendard Variable** 단독 번들(한글+라틴), mono는 기존 유지.
- `fontSize` 스케일 재정의 (arbitrary `text-[NNpx]` 치환 기준):

| 클래스 | 크기/행간 | 치환 대상 |
|---|---|---|
| `text-2xs` | 11px / 16px | `text-[10px]`, `text-[11px]` |
| `text-xs` | 12px / 16px | (기존 12px 유지) |
| `text-sm` | 13px / 20px | `text-[13px]`, `text-[14px]` |
| `text-base` | 15px / 22px | `text-[15px]`, `text-[16px]` |
| `text-lg` | 17px / 26px | — |

- weight: 400(본문) / 500(강조·버튼) / 600(제목). 700 이상 금지.

## 4. 팔레트→시맨틱 매핑 표 (P4 코드모드 명세)

| 레거시 클래스 | → 시맨틱 클래스 |
|---|---|
| `bg-surface-950`, `bg-surface-900` | `bg-bg` |
| `bg-surface-800` | `bg-surface` |
| `bg-surface-700`, `bg-surface-600` (정적) | `bg-surface` |
| `hover:bg-surface-700/600/800` | `hover:bg-surface-hover` |
| `bg-white`, `bg-surface-50/100` (라이트 전용 짝) | 삭제 (시맨틱이 자동 처리) |
| `text-surface-50/100/200`, `text-white` | `text-fg` |
| `text-surface-300` | `text-fg-secondary` |
| `text-surface-400/500` | `text-fg-muted` |
| `border-surface-600/700/800` | `border-border` |
| `text-primary-400/500`, `text-blue-*` (액센트 용도) | `text-accent` |
| `bg-primary-500/600`, `bg-blue-*` (액센트 용도) | `bg-accent` (+텍스트 `text-accent-fg`) |
| `text-red-*`/`bg-red-*` (오류 의미) | `text-danger`/`bg-danger` (alpha 변형 가능: `bg-danger/10`) |
| `text-amber-*`, `text-yellow-*` (경고 의미) | `text-warning` |
| `text-green-*`, `text-emerald-*` (성공 의미) | `text-success` |
| 위 매핑을 적용한 뒤 짝을 이루던 `[.light_&]:*` | **삭제** |

규칙:
- **§1 용도 열 우선**: 입력 필드·세그먼트/토글 트랙·드롭다운 패널처럼 §1이 surface로 규정한 요소는 레거시 팔레트 값이 900/950이었더라도 bg-surface로 매핑한다. §4 표의 bg-bg 매핑은 페이지/섹션 배경에만 적용.
- hover/포커스 상태 배경은 무조건 `surface-hover`.
- 의미(성공/경고/위험)가 있는 색은 시맨틱 상태 토큰, 장식 색은 accent로 수렴 — 판단이 애매하면 무채색.
- `lib/agents.ts`의 동적 에이전트 hex는 데이터이므로 인라인 style 유지.
- 매핑에 없는 케이스는 "이 요소의 의미가 무엇인가"로 판단해 13개 토큰 중 선택.

## 5. 모션·상호작용 원칙

- 키보드로 트리거되는 액션(단축키·Enter 제출)에는 애니메이션 금지.
- 모든 트랜지션 ≤ 200ms (`--transition-speed: 150ms` 재정의), `prefers-reduced-motion` 유지.
- 포커스 링: `focus-visible` 시 `--accent` 2px ring — 전 인터랙티브 요소 공통. 예외: 파괴적 액션 버튼(`.btn-danger`)은 `--danger` ring.
- spacing 8px 배수 원칙 (4px는 아이콘-라벨 간격 등 미세 조정에만).
