# 설정 페이지 리디자인 스펙 (L1 + C1)

- 날짜: 2026-07-13
- 상태: 사용자 승인 (브라우저 비주얼 세션에서 L1·C1 선택, "진행" 지시)
- 범위: `Settings.tsx`, `CostDashboard.tsx`, `strings.ts`, `App.tsx`(밀도 부팅 코드), `index.css`. **백엔드 API·Profile 페이지·예산 기능은 범위 외.**
- 선행: 디자인 시스템 v2 (`2026-07-12-design-system-v2-design.md`) — 모든 스타일은 v2 토큰 내에서.

## 1. 네이밍: "시스템 제어" → "설정"

| 위치 | 현재 | 변경 |
|---|---|---|
| `strings.ts:19` `S.app.settings` (사이드바) | 시스템 제어 | 설정 |
| `strings.ts:238` `S.settings.title` (페이지 h1) | 시스템 제어 | 설정 |
| `strings.ts:322` `S.settings.heroKicker` | Control room | Settings |
| `strings.ts:689` `apiKeyMissing` | "시스템 제어에서 API 키를…" | "설정에서 API 키를…" |

## 2. 표시모드 밀도(comfortable/compact) 완전 제거

효과가 체감되지 않는 옵션(패딩 0.25rem 차이)으로 판정, 전면 제거:

1. `Settings.tsx` — 밀도 서브섹션 UI(≈698-728), density state(≈89-91), 토글 로직(≈186-191), 관련 import/문자열 참조 제거
2. `App.tsx` — 부팅 시 `sasoo-density` 적용 코드(≈88-89) 제거
3. `index.css` — `--density-control-py`/`--density-card-p`/`--density-row-py` 변수와 `.density-compact` 오버라이드(≈57-67) 제거, 소비처(≈142-143, 322-323, 359-360)는 comfortable 고정값을 인라인
4. `strings.ts` — `densityComfortable`/`densityCompact`(≈304-305) 등 밀도 전용 문자열 제거
5. localStorage `sasoo-density` 잔존 값은 무해하므로 마이그레이션 불필요 (읽는 코드가 사라짐)
6. "표시 모드" 섹션은 **"테마"**로 개칭, 테마(다크/라이트) 토글만 유지

## 3. 레이아웃 L1 — 좁은 단일 컬럼 + 행 기반

- **컨테이너**: `page-container-compact`(96rem)는 Home·Profile 공유 클래스이므로 변경 금지. `index.css`에 **`.page-container-settings { max-width: 44rem }`** 신설(그 외 속성은 compact와 동일 패턴), `Settings.tsx:321`에서 교체
- **행 구조**: 각 설정 항목을 `SettingRow` 패턴으로 통일 — 좌측 라벨+보조설명(라벨 `text-sm font-medium`, 설명 `text-xs text-fg-muted`), 우측 컨트롤(입력/토글/버튼). 행 간 구분은 `divide-y` 헤어라인, 행 패딩 `py-3`
- **섹션**: 기존 5개 섹션(모델 키 / 이미지 생성 / 보관함 경로 / 테마 / 사용량과 비용)과 순서 유지, 섹션 타이틀은 컬럼 내 좌측 정렬. 연구자 프로필 링크 행 유지
- **히어로 헤더**: 타이틀+상태 배지+저장/되돌리기 버튼 유지하되 44rem 컬럼 폭에 맞춤. 저장 버튼이 스크롤 밖으로 사라지는 문제가 생기면 하단 고정 저장 바가 아닌 **헤더 sticky**로 해결(범위 최소화)
- 넓은 입력(API 키 등)은 행 우측 정렬 대신 라벨 아래 풀폭 배치 허용 (행 패턴의 예외, 일관되게 적용)

## 4. 사용량과 비용 C1 — 답변 우선 + 접기

`CostDashboard.tsx` 재구성. 데이터는 기존 `getCostSummary()` 응답만 사용(백엔드 무변경 — 월별 6개월 데이터에서 전월 대비를 프론트 계산).

위에서 아래 순서:

1. **히어로 라인**: 이번 달 비용(큰 숫자) + 전월 대비 델타 + 우측 6개월 스파크바
   - 큰 숫자: `font-mono tabular-nums text-3xl font-semibold`
   - 델타: 감소 시 `▼ N% 지난달보다 적게`(success 색), 증가 시 `▲ N% 지난달보다 많이`(중립 `text-fg-muted` — 지출 증가는 오류가 아니므로 경고색 금지), 전월 데이터 없으면 생략
   - 부제 한 줄: `이번 달 · 논문 N편 분석 · 편당 평균 $X.XX`
   - 스파크바: 최근 6개월 세로 바, 현재 월만 accent(#683DCC 계열 토큰), 과거는 뉴트럴, hover 시 월+금액 툴팁, 높이 ≤48px
2. **절감·검증 한 줄**: 기존 3개 소카드를 단일 라인으로 — `캐시 절감 $X · Phase 호출 N회 · 표 검증 대기 N건` (뉴트럴 배경 박스 1개)
3. **아코디언 3개** (기본 접힘, 상태 비영속):
   - `모델별 사용량` — 기존 표 그대로 이식 (숫자 열 `font-mono tabular-nums`, 우측 정렬)
   - `논문별 비용 (상위 10)` — 기존 목록 이식
   - `월별 추이` — 기존 바 차트 이식 (스파크바의 확대판, 동일 배색 규칙)
4. 로딩/에러/빈 상태 처리는 기존 유지. `id="cost"` 해시 딥링크 유지 — `#cost` 진입 시 섹션으로 스크롤(기존 동작 보존)
5. 모든 금액·토큰 수치는 `font-mono tabular-nums`

## 5. 성공 기준

- 설정 페이지 콘텐츠 폭이 44rem으로 제한되고 행 기반 스캔이 가능
- 비용 섹션 첫 화면(펼치기 전)에서 세 질문에 답함: 이번 달 얼마 / 지난달 대비 / 편당 평균
- 앱 전체에서 "시스템 제어" 문자열 잔존 0건, `sasoo-density`·`density-compact` 참조 0건
- `npm run lint` + `npm run build` 그린, 실행 화면(스크린샷)으로 라이트/다크 확인

## 6. 범위 외

- Profile·Home 레이아웃, 백엔드 API, 예산(budget) 알림 기능, 앵커 네비(L2 — 추후 필요 시)
