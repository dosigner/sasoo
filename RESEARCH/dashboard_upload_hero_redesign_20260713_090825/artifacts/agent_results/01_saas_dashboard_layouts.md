# SaaS/제품 앱 HOME·대시보드 레이아웃 레퍼런스 조사 (2024–2026)

조사 목적: "논문 사수"(AI 논문 편집·분석 웹앱)의 Home을 현재의 단순 수직 스택(인사말 → 업로드 패널 → 최근 논문 카드 → 이번 달 비용 카드)에서 "대시보드 + 업로드 진입점" 형태의 정돈된 홈 화면으로 리디자인하기 위한 레퍼런스 수집.
조사일: 2026-07-13

---

## 1. Linear — 이슈 트래커 (linear.app)

- **URL**: https://linear.app/now/how-we-redesigned-the-linear-ui , https://linear.app/now/dashboards-best-practices
- **화면이 하는 일**: 로그인 직후 "지금 내가 처리해야 할 작업(활성 이슈)"을 즉시 보여주고, 분석/추이는 별도 탭으로 분리한다.
- **레이아웃 구조**: 좌측 사이드바(약 240–280px, 아이콘 축소 시 얇은 레일로 접힘) + 상단 헤더 없이 바로 리스트/보드가 시작되는 구조. 홈 화면 자체는 "활성 이슈" 리스트가 메인이고, 차트·벨로시티 같은 대시보드성 위젯은 별도 Insights 탭 뒤에 숨겨져 있다. 밀도는 높지만 여백을 적극 활용해 "일하는 화면"과 "분석하는 화면"을 분리한다.
- **눈에 띄는 패턴**: 프로그레시브 디스클로저(할 일과 분석의 분리), 사이드바 상시 노출, 다크/라이트 모드 대비를 강화한 크롬(chrome) 리디자인.
- **왜 잘 작동하는가**: 사용자가 로그인 직후 "무엇을 해야 하는가"에 바로 답하고, "얼마나 잘하고 있는가"(분석)는 원할 때만 보게 해 첫 화면의 인지 부하를 낮춘다. 업로드/작업 시작형 앱에 참고할 만한 "액션 우선, 통계는 2차" 원칙.
- **시각 묘사**: 화이트/다크 배경에 얇은 보더, 낮은 채도의 그레이 톤 위에 상태 컬러(라벨)만 채도를 준다. 타이포는 작고 촘촘하지만 라인 간격으로 답답함을 줄임.
- **등급**: B (제품사 공식 블로그, 스펙 수치는 비공식)

## 2. Vercel Dashboard — 배포 플랫폼 (vercel.com)

- **URL**: https://vercel.com/blog/dashboard-redesign , https://vercel.com/changelog/dashboard-navigation-redesign-rollout
- **화면이 하는 일**: 로그인 후 "내 프로젝트들이 지금 정상 배포됐는가"를 스크린샷 그리드로 즉답한다.
- **레이아웃 구조**: 접을 수 있는 좌측 사이드바(팀/프로젝트 전환) + 프로젝트 카드 그리드. 각 카드에 최신 프로덕션 배포의 실제 스크린샷 썸네일 + git 저장소 연결 상태 + 배포 상태(성공/실패)가 표시됨. 모바일에서는 사이드바 대신 하단 플로팅 바로 전환.
- **눈에 띄는 패턴**: "상태를 텍스트가 아니라 색상 배지 + 실제 화면 캡처"로 보여주는 시각적 상태 표시, 팀/프로젝트를 필터처럼 전환하는 탭 일관성, 브라우저 탭 파비콘에도 배포 상태 반영.
- **왜 잘 작동하는가**: 개발자에게 가장 중요한 단일 질문("빌드가 성공했는가")에 스캔 한 번으로 답을 주는 이진적 명료함. 첫 화면 성능(FMP 1.2초 단축)까지 신경 써서 "빠른 확인"이라는 목적에 맞춤.
- **시각 묘사**: 미니멀한 그레이스케일 카드 위에 실제 배포 스크린샷이 들어가 화면 자체가 데이터가 되는 느낌. 상태 배지만 초록/빨강으로 포인트.
- **등급**: A (제품사 공식 블로그·체인지로그)

## 3. Notion Home — 워크스페이스 허브 (notion.com)

- **URL**: https://www.notion.com/help/navigate-with-the-sidebar , https://thomasjfrank.com/notion-home-everything-you-need-to-know/
- **화면이 하는 일**: "안녕하세요, OO님" 인사말 아래 최근 작업/즐겨찾기/예정 일정을 모아 보여주고 하단에 새 항목 생성 버튼을 배치한다.
- **레이아웃 구조**: 최근에는 Home이 별도 풀페이지가 아니라 사이드바 안의 한 섹션으로 통합됨. 섹션 순서: 인사말 → Upcoming events → Recents → Favorites → Agents → Teamspaces → Shared/Private pages → Notion apps. 각 섹션은 개수를 사용자가 조절 가능(Show N items), 섹션 순서도 재배열 가능. 하단 고정 영역에 새 채팅(AI)/페이지/미팅노트/DB 생성 버튼.
- **눈에 띄는 패턴**: 개인화된 인사 한 줄 + 섹션형 최근 항목 목록 + 하단 고정 "빠른 생성" 버튼 조합. 섹션 표시 개수·순서·숨김을 사용자가 커스터마이즈.
- **왜 잘 작동하는가**: "무엇을 다시 열지"(Recents)와 "무엇을 새로 만들지"(하단 버튼)를 한 화면에서 분리해 제공, 정보 위계가 최근성 순으로 명확함.
- **시각 묘사**: 여백이 넓은 화이트 배경, 텍스트 중심의 미니멀 리스트, 아이콘은 작고 절제됨.
- **등급**: A (제품사 공식 헬프센터)

## 4. Stripe Dashboard 홈 — 결제 플랫폼 (dashboard.stripe.com)

- **URL**: https://support.stripe.com/questions/dashboard-home-page-charts-for-business-insights , https://docs.stripe.com/dashboard/basics
- **화면이 하는 일**: 총 매출/거래/입금/분쟁 등 핵심 지표 카드 + 순매출 차트로 사업 현황을 즉시 요약.
- **레이아웃 구조**: 사이드바 없이(또는 얇게) 상단에 4개 내외 KPI 카드가 가로로 배열되고 각 카드는 큰 숫자 + 전기 대비 증감 + 스파크라인 하나로 구성. 그 아래 순매출 추이 차트. 위젯은 Add/Edit로 커스터마이징 가능.
- **눈에 띄는 패턴**: "숫자 큼직하게 + 증감 화살표 + 미니 스파크라인" 조합의 stat tile row가 최상단을 차지하는 전형적 패턴. 카드당 정보량을 억제(라벨 설명 최소화)해 여백을 지킴.
- **왜 잘 작동하는가**: 사용자가 스크롤 없이 "돈이 잘 들어오고 있는가"를 3~4개 숫자로 파악. 색은 기능적으로만 사용(성공=초록, 실패=빨강)해 시각적 소음을 줄임.
- **시각 묘사**: 화이트 배경, 카드 사이 여백 큼, 보라색(Stripe 브랜드) 포인트는 CTA에만.
- **등급**: A (제품사 공식 지원 문서), 세부 배치는 C(2차 정리 블로그 925studios/artofstyleframe 교차 확인)

## 5. Mercury — 스타트업 뱅킹 (mercury.com)

- **URL**: https://mercury.com/blog/october-2025-product-updates , https://support.mercury.com/hc/en-us/articles/28767842120852
- **화면이 하는 일**: 로그인 직후 전체 계좌 합산 잔액("Mercury balance")과 캐시 런웨이를 최우선으로 보여주고 최근 거래 내역을 바로 아래 배치.
- **레이아웃 구조**: 얕은 내비게이션 구조(깊은 메뉴 트리 없음), 잔액이 페이지 최상단 히어로처럼 크게 표시되고 이후 정보는 모두 "부차적"으로 취급됨. 최근 거래 리스트가 잔액 카드 옆/아래에 배치되어 "얼마 있고, 최근 뭘 썼는지"를 한 화면에서 답한다.
- **눈에 띄는 패턴**: 단일 히어로 지표(잔액) + 보조 지표(런웨이) 나란히 배치, 나머지는 리스트로 후순위. 다크모드 옵션 제공(저자극 뷰).
- **왜 잘 작동하는가**: "은행 지식이 없어도 이해되는" 것을 목표로 지표를 1~2개로 극단적으로 제한, 나머지는 스크롤 아래로 밀어 첫 화면의 인지 부하를 최소화.
- **시각 묘사**: 화이트/오프화이트 배경에 큰 숫자 타이포, 여백 넉넉, 강조색은 거의 없음(신뢰감 있는 절제된 톤).
- **등급**: B (공식 블로그+지원문서), 레이아웃 세부는 C(2차 소스 925studios 교차 확인)

## 6. Ramp — 지출관리 (ramp.com)

- **URL**: https://bakkenbaeck.com/case/ramp , https://styles.refero.design/style/b38702a0-75ab-474c-9106-00b624535825
- **화면이 하는 일**: 지출 현황 + 시스템이 자동으로 찾아낸 절감액을 함께 보여줘 "숫자"가 아니라 "의미 있는 결과"로 번역해 제시.
- **레이아웃 구조**: 브랜드 차원에서 "Bento box"라는 이름의 유연한 그리드 시스템을 만들어, 저밀도(단순 카드)와 고밀도(복수 통화/거래 애니메이션) 화면 모두를 같은 그리드 문법으로 수용. 대시보드 자체는 지출 테이블 + 분석 카드 + 카드 관리 위젯의 조합.
- **눈에 띄는 패턴**: 베이지/화이트 바탕의 거의 무채색 편집형(에디토리얼) 톤에 형광 옐로우그린(#e4f222) 포인트 컬러 하나만 CTA·실시간 카운터·활성 상태에 사용. Bento grid(비대칭 타일 크기)로 중요도를 라벨 없이 크기로 전달.
- **왜 잘 작동하는가**: 컬러를 극도로 제한해 "돈이 움직이는 곳"에만 시선이 가도록 강제. 타일 크기 자체가 위계를 말해줘 설명 텍스트가 줄어듦.
- **시각 묘사**: 웜 오프화이트 캔버스 + 화이트 카드 + 헤어라인 그레이 보더 + 짙은 블랙 텍스트, 옐로우그린 포인트 하나.
- **등급**: B (디자인 에이전시 공식 케이스 스터디, Ramp와 협업 확인됨), 컬러 디테일은 C(refero.design 스타일 아카이브)

## 7. Attio — CRM (attio.com)

- **URL**: https://attio.com/help/reference/managing-your-data/dashboard-and-reports/dashboards
- **화면이 하는 일**: 팀이 리포트(위젯)를 직접 배치해 만드는 커스텀 대시보드로, 팀마다 다른 홈 화면을 구성.
- **레이아웃 구조**: 고정 그리드가 아니라 "줄(row)"마다 리포트 개수가 달라질 수 있는 유연한 구조. 리포트 카드는 드래그로 순서 변경, 카드 사이 경계를 드래그해 폭 조절. 대시보드 상단에 제목 + 설명 텍스트 + 우측 Share 버튼.
- **눈에 띄는 패턴**: 사용자 커스터마이즈형 위젯 그리드(고정 밀도 없음), 대시보드에 "설명(description)"을 달아 용도를 문서화하는 패턴.
- **왜 잘 작동하는가**: 조직마다 중요한 지표가 다른 CRM 특성상 고정 레이아웃을 강요하지 않고 사용자가 위계를 직접 설계하게 함 — 다만 이는 범용 대시보드 툴에 적합한 방식이며, 논문 사수처럼 단일 목적 홈에는 고정 위계가 더 나을 수 있음(참고용 대조 사례).
- **시각 묘사**: 헌터블랙(#1C1D1F) 텍스트 + 틸/그린 계열(#3ABDAF) 포인트, 데이터 밀도가 높은 그리드/칸반 뷰.
- **등급**: A (제품사 공식 헬프센터)

## 8. Bento Grid 패턴 (횡단 트렌드, 다수 제품 공통) — 참고용 디자인 갤러리·블로그 종합

- **URL**: https://www.orbix.studio/blogs/bento-grid-dashboard-design-aesthetics , https://senorit.de/en/blog/bento-grid-design-trend-2025 , https://landdding.com/blog/blog-bento-grid-design-guide
- **화면이 하는 일**: 단일 제품이 아니라 2024~2026년 SaaS 홈/대시보드 전반에 확산된 레이아웃 문법 — 비대칭 크기의 타일들을 한 그리드에 배치.
- **레이아웃 구조**: "Tier 1 히어로 타일"(가장 중요한 1~2개 숫자, 4~6칸×2행)을 크게 배치하고 그 옆에 2×2, 1×2 크기의 보조 타일(최근 활동 리스트, 상태 지표 등)을 채우는 방식. Apple의 iPad 마케팅 페이지에서 출발해 Notion·Linear·Vercel의 마케팅 페이지를 거쳐 2025~2026년 B2B SaaS 홈페이지의 기본값이 됨(ProductHunt 상위 100개 SaaS의 67%가 벤토 스타일 채택, 2026년 기준 추정치).
- **눈에 띄는 패턴**: 타일 크기 = 데이터 중요도(라벨 없이 크기로 위계 전달), 카드 유형을 섞어도(차트+숫자+리스트) 시각적 혼란 없이 공존 가능.
- **왜 잘 작동하는가**: "얼마나 큰가"가 곧 "얼마나 중요한가"를 뜻하므로 텍스트 설명 없이 스캔 순서를 유도함. 논문 사수 홈처럼 업로드(핵심 액션)+최근 논문(리스트)+비용(단일 숫자)을 섞어야 하는 화면에 직접 적용 가능한 문법.
- **시각 묘사**: 카드 간 일관된 라운드 코너·갭, 색은 절제하고 크기로 위계를 표현.
- **등급**: C~D (2차 트렌드 정리 블로그, 수치는 참고용이며 1차 검증 안 됨)

## 9. Mobbin / nicelydone.club — 실제 제품 스크린 갤러리 (메타 소스)

- **URL**: https://mobbin.com/explore/web/screens/dashboard , https://nicelydone.club/apps/linear , https://nicelydone.club/apps/mercury , https://nicelydone.club/apps/ramp
- **화면이 하는 일**: Linear(905개 UI 스크린), Mercury(367개), Ramp(114개) 등 실제 SaaS 제품의 대시보드/홈 스크린을 원본 그대로 캡처해 검색 가능한 라이브러리로 제공.
- **레이아웃 구조/패턴**: 텍스트 설명 대신 스크린샷 위주라 이 조사에서는 세부 수치를 끌어오지 못했지만, 리디자인 착수 시 실제 화면을 눈으로 비교하는 1차 스크리닝 도구로 유용(디자이너가 직접 방문해 스크린 열람 필요).
- **왜 유용한가**: 텍스트 기반 조사로는 놓치는 "실제 여백감·타이포 크기·그림자 깊이" 같은 정성적 디테일을 스크린샷으로 직접 확인 가능.
- **등급**: C (큐레이션된 갤러리, 스크린 자체는 원본이라 신뢰도 높으나 본 조사에서는 텍스트 설명을 얻지 못함 — 방문 열람 권장)

---

## 종합: 논문 사수 홈 리디자인에 적용 가능한 3대 패턴

1. **스탯 타일 로우 + 히어로 업로드 (Stripe/Mercury형)**: 상단에 "이번 달 비용, 분석 완료 논문 수" 같은 큰 숫자 1~2개 + 스파크라인을 카드로 배치하고, 업로드 영역을 그 아래(또는 옆) 히어로급 크기로 배치. 라벨 설명은 최소화하고 숫자 크기로 중요도를 전달.
2. **벤토 그리드 비대칭 배치 (Ramp/Bento 트렌드형)**: 업로드 패널을 가장 큰 타일(4~6칸)로, 최근 논문 리스트를 세로로 긴 타일(1×2)로, 비용 카드를 작은 타일(2×1)로 — 현재의 수직 스택을 하나의 그리드 안에서 크기 위계로 재배치. 색은 포인트 컬러 1개로 제한.
3. **인사말 + 섹션형 최근 항목 + 하단 빠른 생성 버튼 (Notion Home형)**: 개인화된 인사 한 줄 → "최근 논문"을 섹션 리스트로 → 하단(또는 상단 고정)에 "새 논문 업로드" 같은 빠른 액션 버튼을 고정 배치. 개수·순서를 사용자가 조절 가능하게 하면 확장성도 확보.

공통적으로, 잘 작동하는 홈 화면들은 (a) 최상단에서 스크롤 없이 핵심 지표/액션에 답하고, (b) 색과 타이포 크기로 위계를 표현해 설명 텍스트를 줄이며, (c) 통계·분석은 후순위(별도 탭 또는 작은 타일)로 미룬다는 공통점이 있음 — 이는 현재 논문 사수 Home의 "그리팅 → 업로드 → 최근논문 → 비용"의 균등한 수직 스택 구조를 히어로(업로드)+보조 타일(최근/비용) 구조로 바꾸는 근거가 됨.

---

## 소스 목록 및 등급

| URL | 등급 | 비고 |
|---|---|---|
| https://linear.app/now/how-we-redesigned-the-linear-ui | B | 공식 블로그, 리디자인 공지 |
| https://linear.app/now/dashboards-best-practices | B | 공식 블로그, 대시보드 기능 가이드 |
| https://vercel.com/blog/dashboard-redesign | A | 공식 제품 블로그 |
| https://vercel.com/changelog/dashboard-navigation-redesign-rollout | A | 공식 체인지로그 |
| https://www.notion.com/help/navigate-with-the-sidebar | A | 공식 헬프센터 |
| https://thomasjfrank.com/notion-home-everything-you-need-to-know/ | C | 서드파티 파워유저 해설 |
| https://support.stripe.com/questions/dashboard-home-page-charts-for-business-insights | A | 공식 지원 문서 |
| https://docs.stripe.com/dashboard/basics | A | 공식 제품 문서 |
| https://mercury.com/blog/october-2025-product-updates | B | 공식 제품 블로그 |
| https://support.mercury.com/hc/en-us/articles/28767842120852 | A | 공식 지원 문서 |
| https://bakkenbaeck.com/case/ramp | B | 공식 협업 디자인 에이전시 케이스 스터디 |
| https://styles.refero.design/style/b38702a0-75ab-474c-9106-00b624535825 | C | 디자인 시스템 아카이브(서드파티 추출) |
| https://attio.com/help/reference/managing-your-data/dashboard-and-reports/dashboards | A | 공식 헬프센터 |
| https://www.925studios.co/blog/saas-dashboard-design-examples-2026 | C | 디자인 에이전시 정리 블로그, 다수 제품 교차 인용(구체적이나 1차 검증 안 됨) |
| https://artofstyleframe.com/blog/dashboard-design-patterns-web-apps/ | C | 개발자 블로그, 수치(px)는 저자 권장값이지 실측 아님 |
| https://www.orbix.studio/blogs/bento-grid-dashboard-design-aesthetics | D | 트렌드 정리 블로그 |
| https://senorit.de/en/blog/bento-grid-design-trend-2025 | D | 트렌드 정리 블로그 |
| https://landdding.com/blog/blog-bento-grid-design-guide | D | 트렌드 정리 블로그 |
| https://mobbin.com/explore/web/screens/dashboard | C | 큐레이션 갤러리(원본 스크린샷, 텍스트 설명 없음) |
| https://nicelydone.club/apps/linear , /mercury , /ramp | C | 큐레이션 갤러리(원본 스크린샷, 텍스트 설명 없음) |
| https://www.saasui.design/application/linear | D | 갤러리성 페이지, 세부 스펙 없음 |

**주의**: Stripe/Notion/Attio/Vercel은 공식 소스(A등급)로 구조적 사실(섹션명, 커스터마이징 기능 등)은 신뢰도가 높으나, 정확한 픽셀 수치(사이드바 240px 등)는 대부분 C~D등급 2차 블로그의 권장값이며 실측이 아님 — 리디자인 시 참고 수치로만 사용하고 자체 그리드 시스템에 맞게 재조정 필요.
