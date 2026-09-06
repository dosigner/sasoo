# 대시보드 홈 화면 컴포넌트 패턴 리서치 (2024–2026)

조사일: 2026-07-13
대상: "논문 사수" AI 논문 분석 웹앱 홈 화면(업로드 패널 + 최근 논문 리스트 + 월간 AI 비용 USD) 리디자인을 위한 컴포넌트 레벨 레퍼런스.

---

## 1. Stat tile / KPI 카드 해부 (2025–2026)

### 공통 아나토미
라벨(뮤트 텍스트, 12–13px) → 큰 숫자(24–36px, tabular-nums, semibold) → 델타 배지(증감률 + 화살표 아이콘, 녹/적 색상) → (옵션) 스파크라인/미니차트 → (옵션) 풋터 설명 텍스트. 이 5요소 조합이 2025–2026 대부분의 SaaS 대시보드에서 반복되는 표준 골격이다.

### 근거 1 — shadcn/ui `dashboard-01` 블록 (공식 shadcn/ui, GitHub 소스 직접 확인)
`section-cards.tsx` 실제 소스를 읽은 결과, 4장의 카드가 반응형 그리드(모바일 1열 → xl 2열 → 5xl 4열, `@container/card` 컨테이너 쿼리 사용)로 배치된다.
- 카드 1: "Total Revenue" / "$1,250.00" / 배지 "+12.5%"(상승 아이콘) / 풋터 "Trending up this month" + "Visitors for the last 6 months"
- 카드 2: "New Customers" / "1,234" / 배지 "-20%"(하락 아이콘, 적색) / 풋터 "Down 20% this period" + "Acquisition needs attention"
- 카드 3: "Active Accounts" / "45,678" / 배지 "+12.5%" / 풋터 "Strong user retention"
- 카드 4: "Growth Rate" / "4.5%" / 배지 "+4.5%" / 풋터 "Steady performance increase"

특징: 카드마다 그라디언트 배경 + Tabler 아이콘 델타 배지 + 2줄 풋터(1줄 요약 + 1줄 보조설명)로, 스파크라인 없이 배지+텍스트만으로 트렌드를 전달한다. 이 4장 구성은 `npx shadcn add dashboard-01`로 그대로 설치 가능한 사실상의 업계 기본값이다.
출처: https://ui.shadcn.com/blocks , https://raw.githubusercontent.com/shadcn-ui/ui/main/apps/v4/registry/new-york-v4/blocks/dashboard-01/components/section-cards.tsx (등급 A — 1차 소스코드)

### 근거 2 — Tailwind Plus(공식 Tailwind CSS 팀) "Stats" 컴포넌트
공식 카탈로그에 6개 변형이 있다: With Trending / Simple / Simple in Cards / With Brand Icon / With Shared Borders 등. "Shared Borders" 변형은 카드 배경 없이 구분선만으로 3–4개 스탯을 한 행에 붙여 배치하는 저비용 패턴으로, 대시보드 상단 요약줄에 흔히 쓰인다. 각 스탯은 라벨 + 값 + 증감 배지의 3요소가 기본, 아이콘·카드는 옵션.
출처: https://tailwindcss.com/plus/ui-blocks/application-ui/data-display/stats (등급 A — 공식 1차 소스, 단 상세 코드는 유료라 목록·구조만 확인)

### 근거 3 — Stripe 대시보드
Revenue/Charges/Payouts/Disputes 4장 카드에 숫자 + 증감 화살표/퍼센트 + 스파크라인이 함께 들어간다. 라벨은 "Total Revenue for the Current Period" 같은 장문이 아니라 "Revenue" 한 단어로 압축 — 라벨은 짧게, 숫자가 주인공이라는 스트라이프식 원칙이 재확인된다.
출처: https://support.stripe.com/questions/dashboard-home-page-charts-for-business-insights (등급 B — 공식 지원문서, 검색엔진 요약 경유라 세부 여백/타이포는 미확인) / https://uibakery.io/templates/stripe-dashboard (등급 D — 템플릿 마케팅 사이트, 참고용)

### 그룹핑 패턴: "3–4개 행" vs "벤토"
- **행(row) 배치**: Stripe, shadcn dashboard-01, Vercel 신규 대시보드 모두 상단 80–120px 영역에 3–4개 카드를 균등폭으로 배치하고, 그 아래 큰 차트/테이블이 이어지는 "요약줄 → 상세뷰" 2단 구조가 지배적이다.
- **벤토(bento) 배치**: 카드 크기를 섞어(2×1, 1×1) 시각적 위계를 주는 방식은 마케팅성 랜딩/제품 소개 페이지에 더 흔하고, 실사용 운영 대시보드에서는 스캔 속도를 해치므로 상대적으로 적다. Vercel의 경우 "KPI + 차트 + 테이블을 CSS Grid로 섞어 5개 기능에서 50개 기능까지 재구조화 없이 확장"하는 근거로 그리드형을 명시적으로 채택했다.
출처: https://vercel.com/changelog/dashboard-navigation-redesign-rollout (등급 B — 공식 체인지로그)

### 언제 쓰나 / 피할 때
- 3–4개 카드 행은 "지금 한눈에 알아야 할 숫자"가 명확할 때 적합. 논문 사수 홈처럼 지표가 1–2개(이번 달 비용, 처리된 논문 수)뿐이면 4칸을 억지로 채우지 말고 2–3칸 + 우측 여백 또는 텍스트형 보조지표로 대체할 것.
- 스파크라인은 "일별 변화가 의미 있는 지표"에만 넣는다. 월 1회 갱신되는 카운터에는 불필요.

---

## 2. AI 사용량/비용 위젯 특화 패턴

### OpenAI Platform (platform.openai.com/usage)
Cost 뷰와 Activity 뷰 2탭 구조. Cost 뷰는 상단에 비용 차트(일별 바/라인 전환 가능) + 최근 청구 요약, 날짜 선택기로 Today/Last 7 days/Current billing cycle/Custom range를 고른다. 신규 Costs API(`/v1/organization/costs`)가 일별 지출 breakdown을 제공해 대시보드가 이 데이터로 바/라인차트를 그린다. Usage 뷰는 프로젝트 셀렉터가 상단 전역 프로젝트 선택기와 별도로 존재.
출처: https://help.openai.com/en/articles/10478918-api-usage-dashboard (등급 B — 공식 헬프센터, WebFetch가 403이라 검색 스니펫 경유) / https://developers.openai.com/cookbook/examples/completions_usage_api (등급 A — 공식 쿡북)

### Anthropic Claude Console (Cost & Usage 페이지, WebFetch로 직접 확인)
**Usage 페이지**: 인풋/아웃풋 토큰 카운트 바차트(시/분 단위까지 드릴다운 가능), Workspace 셀렉터("All Workspaces"), Model 셀렉터("All Models"), API 키 셀렉터, 레이트리밋 시각화(시간당 최대 ITPM/OTPM 대비 캐시율), CSV 내보내기.
**Cost 페이지**: 일별 비용 차트, 토큰 비용/툴 사용 비용(웹서치·코드실행) breakdown, Workspace/Model 필터, 월 단위 기간 선택, CSV 내보내기. 단 "개별 사용자별 breakdown은 불가능"하다고 공식 문서에 명시.
출처: https://support.claude.com/en/articles/9534590-cost-and-usage-reporting-in-console (등급 A — 공식 지원문서, WebFetch 원문 확인)

### Vercel AI Gateway (Observability & Spend, WebFetch로 직접 확인)
페이지 상단에 "AI Gateway Credits 잔액 + 최근 지출"이 헤드라인으로 먼저 오고, 그 아래 **Generations** 뷰에서 개별 요청별 cost/latency/token usage를 로그처럼 나열한다. Custom Reporting API로 model/user/tag/provider 기준 집계가 가능. 즉 "잔액(선불 크레딧형) → 최근 지출 → 요청 로그" 3단 구조로, 예산 소진형(빌링사이클) 앱들과는 달리 **선불 잔액 소모 관점**을 헤더에 배치하는 점이 OpenAI/Anthropic과 다르다.
출처: https://vercel.com/docs/ai-gateway/observability-and-spend/usage (등급 A — 공식 문서 원문, last_updated 2026-06-20)

### Langfuse / Helicone (LLM 옵저버빌리티 특화)
Helicone은 비용 breakdown, 지연시간 백분위, 세션 분석, 사용자별 추적을 오버뷰에서 제공하며 모델/사용자/대화 단위로 지출을 필터링한다. Langfuse는 generation/embedding 단위 오브젝트에 usage·cost를 태깅해 모델별 breakdown을 만든다. 두 툴 다 "요청(트레이스) 단위 원가 태깅 → 집계축(모델/사용자/태그) 선택 → 시계열 차트" 순서로 구성되어 개발자 대상 관측 툴의 공통 골격을 보여준다.
출처: https://langfuse.com/docs/observability/features/token-and-cost-tracking (등급 A — 공식 문서) / https://www.buildmvpfast.com/blog/llm-observability-stack-langfuse-helicone-portkey-2026 (등급 C — 3rd party 비교 블로그, 교차검증용)

### Cursor 사용량 대시보드
2026년 6월 개편 이후 "Auto + Composer" 풀과 "서드파티 API 모델" 풀을 분리해 각각 한도 대비 소진율을 보여주는 방식으로 바뀌었다. 아웃풋 토큰이 인풋 대비 2–5배 비싸다는 점을 강조하는 등, 순수 사용량뿐 아니라 "무엇이 비용을 유발했는지" 모델별 단가 컨텍스트를 함께 노출하는 추세.
출처: https://cursor.com/docs/models-and-pricing (등급 A — 공식 문서) / https://www.vantage.sh/blog/cursor-pricing-explained (등급 B — 3rd party FinOps 벤더, 신뢰도 있음)

### 논문 사수 적용 시사점
현재 요구사항인 "월간 AI 비용(USD) 단일 숫자"는 위 사례들의 **최소 단위 패턴**과 일치한다. 확장한다면: (1) Anthropic/OpenAI식 "일별 바차트 + Month-to-date 숫자" 조합, (2) Vercel식 "잔액/예산 대비 진행바(progress bar)" 중 하나를 고르면 된다. 논문 사수는 선불 크레딧이 아니라 실비용 청구형이므로 (1)이 더 적합하며, 예산 상한을 사용자가 설정하는 기능이 생기면 그때 (2)의 progress bar를 추가하는 것이 자연스럽다.

### 언제 쓰나 / 피할 때
- 일별 바차트는 트래픽이 매일 발생하는 서비스(API 과금형)에 적합. 논문 사수처럼 세션이 간헐적(주 1–2회 업로드)이면 일별 바가 대부분 0으로 비어 보여 시각적으로 허전할 수 있음 — 이 경우 "월 누적선 + 최근 활동 로그" 조합이 더 안전.

---

## 3. Recent items: 행 리스트 vs 썸네일 카드 그리드

### 행 리스트(row list)를 쓰는 제품 — Linear
Linear는 이슈 리스트 뷰에서 그룹핑 기준(상태/담당자/프로젝트/우선순위/사이클/라벨/부모이슈/팀/고객/릴리스/SLA)과 표시할 속성(ID, 상태, 담당자, 우선순위, SLA, 프로젝트, 마감일, 마일스톤, 사이클, 릴리스, 추정치, 라벨, 링크, PR/커밋, Sentry 이슈 등)을 모두 사용자가 토글할 수 있는 매우 밀도 높은 행 기반 UI를 채택한다. 텍스트/코드 중심 데이터(이슈 제목, 상태뱃지, 담당자 아바타, 마감일)일수록 행 리스트가 스캔에 유리하다는 것을 보여주는 사례.
출처: https://linear.app/docs/display-options (등급 A — 공식 문서)

### 썸네일 카드 그리드를 쓰는 제품 — Gamma
Gamma는 문서를 "카드" 단위로 다루며, 각 카드가 슬라이드/섹션처럼 동작한다. 홈/라이브러리에서 최근 작업물은 시각적 미리보기(썸네일)가 핵심 정보이므로 그리드 배치가 자연스럽다 — 프레젠테이션·디자인처럼 **콘텐츠 자체가 시각물**인 제품군의 공통점.
출처: https://help.gamma.app/en/articles/11016396-what-are-cards-in-gamma-and-how-to-do-they-work (등급 B — 공식 헬프센터)

### Figma 홈
파일 썸네일은 16:9(1920×1080) 표준 비율로 통일되며, 파일의 첫 페이지 콘텐츠를 자동 썸네일로 사용(커스텀 지정 가능)한다. Recent files 그리드가 홈 화면 기본 진입점.
출처: https://help.figma.com/hc/en-us/articles/23510169950871-Design-a-file-thumbnail (등급 A — 공식 헬프센터)

### 선택 기준 정리
- **행 리스트**: 콘텐츠가 텍스트/메타데이터 중심이고, 상태(진행중/완료/실패)·타임스탬프·담당자 등 필터링 가능한 속성이 여러 개 있을 때 (Linear, 이슈 트래커류, 문서 관리 도구). 논문 사수의 "논문"은 제목+저자+분석상태+업로드일 등 메타데이터가 핵심이므로 **행 리스트가 기본적으로 더 적합**.
- **썸네일 카드 그리드**: 콘텐츠 자체가 시각적 결과물(슬라이드, 디자인, 이미지)이고 한눈에 "무엇인지" 알아보는 게 목적일 때 (Gamma, Canva, Figma). 논문 PDF는 커버 이미지만으로 식별이 어려워 그리드의 이점이 제한적.
- **하이브리드**: 각 행에 작은 아이콘/파일타입 배지 + 진행률(분석 중 %) + 상태 배지(완료/처리중/실패) + 상대시간("3시간 전")을 붙이는 것이 최근 트렌드 — Linear의 다중 메타데이터 배지 패턴을 행 리스트에 이식하는 방식.

### 언제 쓰나 / 피할 때
- 항목 수가 적고(< 10) 각 항목의 "상태"가 사용자의 다음 행동(재분석, 다운로드, 삭제)을 결정한다면 행 리스트 + 우측 액션 아이콘이 낫다.
- 항목이 많고 시각적 브라우징이 목적이면 그리드가 낫지만, PDF 논문처럼 미리보기 이미지가 무의미한 콘텐츠에는 그리드 전환의 이득이 적다.

---

## 4. Empty state / 첫 실행 경험

### 공통 원칙 (2025–2026 트렌드 종합)
"2026년 최고의 제품들은 empty state를 온보딩의 주 무대로 취급한다 — 헤드라인, 보조설명, 주 CTA가 핵심이고 일러스트는 선택사항"이라는 서술이 다수 소스에서 반복 확인된다. 즉 화려한 일러스트보다 **명확한 카피 + 단일 CTA**가 2026년 기준선이다.
출처: https://www.eleken.co/blog-posts/empty-state-ux (등급 C — 디자인 에이전시 블로그, 다수 실제 제품 사례 인용이라 참고가치 있음)

### 구체 패턴 — 일러스트 최소화형: Linear, Notion
"단색(monochrome) 일러스트로 인터페이스에 녹아드는" 스타일 — 인터페이스 톤을 깨지 않는 라인아트 수준의 미니멀 일러스트.

### 구체 패턴 — 카드형 액션 제시: Google Gemini
빈 화면에서 "각기 다른 CTA를 제시하는 카드 여러 장"을 배열해 무엇을 할 수 있는지 예시로 보여주는 방식. 논문 사수 홈이 완전히 비어있을 때 "논문 업로드", "샘플 논문으로 체험" 등 카드 2–3장을 놓는 데 참고할 수 있음.

### 구체 패턴 — 샘플 데이터 프리로드: 신흥 트렌드
"empty state 자체를 피하기 위해 샘플 데이터를 미리 채우거나 스타터 콘텐츠를 자동 생성"하는 흐름이 늘고 있다고 언급됨. Supabase는 새 프로젝트 생성 시 "샘플 데이터가 있는 테이블 만들기" 옵션을 quickstart에 명시하여 이 패턴을 따른다.
출처: https://supabase.com/docs/guides/getting-started (등급 A — 공식 문서, "when your project is up and running, you can create a table with some sample data" 서술 확인)

### 구체 패턴 — 진행형 배너: PostHog
이벤트가 없는 프로젝트에서는 "This project has no events yet. Go to the onboarding wizard or grab your project API key/HTML snippet from Project Settings to get things moving"라는 배너형 empty state를 상단에 노출한다 — 일러스트 없이 텍스트 배너 + 2개 행동 링크(마법사로 가기 / API 키 복사)로만 구성된 실용적 사례.
출처: 검색 스니펫 경유 (등급 C — 원문 페이지 직접 미확인, GitHub 이슈 스레드 인용)

### 논문 사수 적용
현재 "업로드 패널 + 최근 논문 리스트 + 월간 비용" 구조에서 논문이 0건일 때: (1) 리스트 영역에 미니멀 일러스트 또는 아이콘 + "첫 논문을 업로드해보세요" 헤드라인 + 업로드 버튼(이미 있는 업로드 패널로 스크롤/포커스), (2) 비용 위젯은 "$0.00" 그대로 두되 "논문을 분석하면 여기에 비용이 표시됩니다" 같은 보조텍스트로 무의미한 빈 차트를 대체하는 것이 PostHog식 텍스트 배너 패턴과 부합.

### 언제 쓰나 / 피할 때
- 신규 유저가 많고 활성화율이 중요한 제품(과금 연결 SaaS)일수록 empty state 투자가 ROI가 높음. 논문 사수처럼 사용자가 이미 목적(논문 업로드)을 갖고 들어오는 도구형 제품은 과도한 온보딩 체크리스트보다 **업로드 CTA 자체를 크게 키우는 것**이 우선.

---

## 5. shadcn/ui 시대 대시보드 키트가 정의하는 기본 아나토미

### shadcn/ui `dashboard-01` (공식, 소스 확인)
`AppSidebar`(variant="inset") + `SiteHeader` + `SectionCards`(스탯 4장) + `ChartAreaInteractive`(인터랙티브 영역차트) + `DataTable`. 즉 **사이드바 → 헤더 → 스탯 카드 행 → 차트 → 테이블**의 5블록 세로 스택이 2025–2026 "기본값"으로 굳어졌다. 설치 명령 `npx shadcn add dashboard-01`로 바로 재현 가능.
출처: https://ui.shadcn.com/blocks , GitHub 소스(위 인용) (등급 A)

### Tremor (Vercel 인수, 2025년 1월 이후 활발히 유지보수)
Card는 "KPI 카드/폼/섹션의 기본 빌딩블록"으로 정의된 범용 div 래퍼(모서리·보더·섀도우·다크모드 내장)이며, 그 위에 라인/바/에어리어/도넛차트, 스파크라인, KPI 카드, 데이터테이블을 조합해 쓰는 카피-페이스트 방식(shadcn과 동일 철학). Tremor Raw가 현재 활발히 개발되는 버전.
출처: https://www.tremor.so/docs/ui/card (등급 A — 공식 문서 원문 확인)

### Tailwind Plus Catalyst / Stats 블록
Tailwind CSS 팀 공식 카탈로그의 "Stats" 컴포넌트는 With Trending / Simple / Simple in Cards / With Brand Icon / With Shared Borders 등 6변형을 제공하며, 각 스탯은 라벨+값+증감배지 3요소가 최소 구성. Catalyst는 이보다 상위의 애플리케이션 UI 키트(버튼/폼/다이얼로그/테이블 포함)로, Stats는 그 안의 한 블록.
출처: https://tailwindcss.com/plus/ui-blocks/application-ui/data-display/stats , https://catalyst.tailwindui.com/docs (등급 A)

### 결론 — 업계 표준 아나토미
2025–2026 shadcn/Tremor/Tailwind 3대 키트가 수렴하는 공통 골격은 다음과 같다.
1. 페이지 상단: 스탯 카드 3–4장 행 (라벨 + tabular-nums 큰 숫자 + 증감 배지, 카드 또는 shared-border 두 스타일 중 택1)
2. 그 아래: 시계열 차트 1개(면적/바 인터랙티브)
3. 최하단: 상세 데이터 테이블 또는 리스트
이 3단 구조를 논문 사수 홈에 적용하면: (업로드 패널은 별도 상단 히어로로 유지) → 스탯 요약(논문 수, 이번 달 비용, 진행중 분석 등 2–3개) → 최근 논문 리스트(테이블/행 리스트) 순으로 재배치하는 안이 업계 표준과 정합적이다.

### 언제 쓰나 / 피할 때
- 이 3단 구조는 "관리형 SaaS 백오피스" 톤에 최적화되어 있다. 논문 사수처럼 "업로드가 주행동"인 도구형 제품은 스탯 카드 행을 업로드 패널보다 시각적으로 낮은 위계에 둬야 하며, 업로드 CTA를 스탯 카드 4장과 동일한 그리드 행에 욱여넣지 않도록 주의.

---

## 종합 권고 (논문 사수 홈 리디자인 관점)

1. **비용 위젯**: Anthropic Console/OpenAI 패턴을 따라 "이번 달 누적 비용(큰 숫자, tabular-nums) + 보조로 최근 N일 미니 바/스파크라인" 구성. 예산 상한 기능이 없다면 progress bar는 생략(Vercel 크레딧형과 달리 논문 사수는 후불 실비용이므로).
2. **최근 논문**: 행 리스트 채택(Linear식) — 제목, 상태 배지(분석중/완료/실패), 상대시간, 우측 액션 아이콘. 썸네일 그리드(Gamma/Canva)는 PDF 콘텐츠 특성상 이득이 적어 비권장.
3. **빈 상태**: PostHog식 텍스트 배너 + 단일 CTA를 최우선 적용하고, 일러스트는 미니멀(Linear/Notion 톤)로 제한. 화려한 온보딩 체크리스트는 과설계.
4. **스탯 카드 행**: shadcn `dashboard-01`을 구조적 출발점으로 삼되, 4칸을 억지로 채우지 말고 실제 있는 지표(비용, 논문 수, 진행중 건수)만큼만 2–3칸으로 구성.

---

## 출처 및 등급 목록 (A=1차 공식 소스 직접 확인, B=공식 소스/검색 경유, C=신뢰할만한 3rd party 분석, D=마케팅/템플릿 판매 사이트, E=불확실/미검증)

| 등급 | 출처 | 비고 |
|---|---|---|
| A | https://ui.shadcn.com/blocks | shadcn/ui 공식, 블록 목록 |
| A | https://raw.githubusercontent.com/shadcn-ui/ui/main/apps/v4/registry/new-york-v4/blocks/dashboard-01/components/section-cards.tsx | dashboard-01 스탯카드 실제 소스코드 |
| A | https://tailwindcss.com/plus/ui-blocks/application-ui/data-display/stats | Tailwind 공식 Stats 컴포넌트 카탈로그 |
| A | https://catalyst.tailwindui.com/docs | Catalyst 공식 문서 |
| A | https://www.tremor.so/docs/ui/card | Tremor 공식 Card 문서 |
| A | https://support.claude.com/en/articles/9534590-cost-and-usage-reporting-in-console | Anthropic 공식 지원문서, WebFetch 원문 확인 |
| A | https://vercel.com/docs/ai-gateway/observability-and-spend/usage | Vercel 공식 문서, WebFetch 원문 확인 (last_updated 2026-06-20) |
| A | https://developers.openai.com/cookbook/examples/completions_usage_api | OpenAI 공식 쿡북 |
| A | https://langfuse.com/docs/observability/features/token-and-cost-tracking | Langfuse 공식 문서 |
| A | https://linear.app/docs/display-options | Linear 공식 문서 |
| A | https://help.figma.com/hc/en-us/articles/23510169950871-Design-a-file-thumbnail | Figma 공식 헬프센터 |
| A | https://cursor.com/docs/models-and-pricing | Cursor 공식 문서 |
| A | https://supabase.com/docs/guides/getting-started | Supabase 공식 문서 |
| B | https://help.openai.com/en/articles/10478918-api-usage-dashboard | 공식 헬프센터, WebFetch 403으로 검색 스니펫 경유 |
| B | https://help.gamma.app/en/articles/11016396-what-are-cards-in-gamma-and-how-to-do-they-work | Gamma 공식 헬프센터 |
| B | https://support.stripe.com/questions/dashboard-home-page-charts-for-business-insights | Stripe 공식 지원문서, 검색 경유 |
| B | https://vercel.com/changelog/dashboard-navigation-redesign-rollout | Vercel 공식 체인지로그 |
| C | https://www.eleken.co/blog-posts/empty-state-ux | 디자인 에이전시 블로그, 다수 실제 제품 인용 |
| C | https://www.vantage.sh/blog/cursor-pricing-explained | FinOps 벤더 블로그, 신뢰도 있으나 3rd party |
| C | https://www.buildmvpfast.com/blog/llm-observability-stack-langfuse-helicone-portkey-2026 | 비교 블로그, 교차검증용 |
| C | https://www.fintechbrainfood.com/p/the-cfo-dashboard | Ramp/Brex/Mercury 비교 뉴스레터 |
| D | https://uibakery.io/templates/stripe-dashboard | 템플릿 판매 사이트 |
| D | https://www.saasframe.io/examples/supabase-empty-project-dashboard | 스크린샷 카탈로그, 본문 상세는 유료(Pro) — 구조만 확인, 세부 미검증 |
| D | https://www.saasui.design/pattern/onboarding/resend | 스크린샷 카탈로그, 세부 텍스트 미확인 |
| E | PostHog empty-state 배너 문구 ("This project has no events yet...") | GitHub 이슈 스레드 경유 인용, 원문 페이지 직접 미확인 |
| E | artofstyleframe.com 등 SEO형 "2026 dashboard trends" 블로그 다수 | 일반론 위주로 본 보고서에서 직접 인용하지 않음 |
