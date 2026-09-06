# 2025-2026 대시보드 홈 화면 비주얼·인터랙션 트렌드 리서치

- 조사일: 2026-07-13
- 목적: "논문 사수"(AI 논문분석 웹앱, 한국어 UI, 라이트/다크 테마, Tailwind) 홈 화면을 "대시보드 + 업로드 히어로"로 리디자인하기 위한 2026년 시점 기준선 확보
- 방법: WebSearch(다건) + WebFetch(가능한 소스에 한해 원문 확인). Mobbin·Godly·dark.design·PageFlows·Land-book은 로그인/JS 렌더링 벽으로 이번 세션에서 원문 직접 열람이 불가했고, 애그리게이터 기사의 2차 서술에 의존했음을 명시함(아래 소스 표에서 등급 반영).

---

## 1. 대시보드가 "2026" vs "2020"으로 읽히는 지점

**밀도(density)**: 2020년대 초반은 "차트·테이블을 많이 욱여넣을수록 강력해 보인다"는 전제가 지배적이었다면, 2026년 표준은 화면당 핵심 요소 5~9개로 제한하고 하나의 노스스타 지표를 좌상단에 배치하는 쪽으로 수렴했다. SaaSFrame의 35개 대시보드 분석(Stripe, Vercel, Baremetrics, ChartMogul 등 "단일 지표形", Linear·Notion·Intercom 등 "점진적 노출形")이 이를 잘 보여준다. (SaaSFrame, "The Anatomy of High-Performance SaaS Dashboard Design: 2026 Trends & Patterns", https://www.saasframe.io/blog/the-anatomy-of-high-performance-saas-dashboard-design-2026-trends-patterns — B등급)

**보더 vs 섀도우**: 2026년 뚜렷한 흐름은 "보더리스 카드(borderless card)"다. 다크모드에서 1px 보더는 저채도일 땐 안 보이고 고채도일 땐 무겁게 느껴지는 신뢰할 수 없는 신호이므로, 배경 레이어를 단계적으로 밝게 쌓는 "layered elevation"으로 위계를 만드는 방식이 확산 중이다(모달 > 패널 > 페이지 배경 순으로 명도를 올림). 그림자를 아예 안 쓰는 건 아니지만 "shadow soup"을 피하는 절제가 핵심이다. (UpDivision, "UI Color Trends to Watch in 2026", https://updivision.com/blog/post/ui-color-trends-to-watch-in-2026 — C등급 / SaaSFrame Anatomy 글 상동 — B등급)

**라운드 반경(radius)**: 대부분의 갤러리 자료에서 "soft-edged rounded card"가 표준으로 굳어졌다고 서술하지만, 동시에 925studios의 35개 사례 분석은 "whitespace-heavy layout with minimal chrome"—즉 크롬(장식) 자체를 줄이는 절제된 미니멀리즘—을 2026년의 지배적 원칙으로 꼽는다. 라운드는 있지만 장식이 아니라 배경(bento/muz.li류 마케팅 템플릿 갤러리)일수록 과장되고, 실제 프로덕트(925studios가 다룬 Linear/Notion/Attio 등)일수록 절제되어 있다는 대비가 뚜렷하다. (925studios, "35 SaaS Dashboard Design Examples, Trends and Patterns (2026)", https://www.925studios.co/blog/saas-dashboard-design-examples-2026 — B등급 / Muzli, https://muz.li/blog/best-dashboard-design-examples-inspirations-for-2026/ — D등급, 실제 프로덕트가 아닌 Behance풍 컨셉 목업 다수)

**무채색 팔레트 + 단일 액센트**: 2026년 표준은 순백/순회색이 아니라 틴트된 뉴트럴(zinc·slate 계열)을 베이스로, 액션 하나에만 원색 액센트를 쓰는 절제형 팔레트다. Vercel이 흑백 모노크롬 + 단일 액센트 브랜딩의 대표 사례로 반복 인용된다. SaaSFrame Anatomy 글은 다크 인터페이스에서 "Red means broken, not 'look here'"라는 문구로 색을 의미 전용으로 예약하라고 강조한다. (UpDivision 상동 — C등급 / SaaSFrame Anatomy 상동 — B등급)

**tabular numbers·대문자 마이크로 라벨**: 직접적인 "탭뉼러 넘버" 트렌드 기사는 드물었지만, 인접 근거로 (1) 2026년 다수 디자인 시스템이 폰트 패밀리를 1개(+보조 1개)로 줄이고 웨이트·트래킹으로 위계를 표현하는 흐름, (2) "Uppercase text receives attention to avoid density, while body text usually remains untouched"—즉 라벨류에만 대문자를 절제해서 쓰는 관행이 확인된다. 데이터 대시보드 타이포 기사는 "ledger-style numerals"(장부형 숫자, 즉 고정폭 numeral)로 헤드라인 수치를 신뢰도 있게 보이는 기법을 언급한다. (GraphicDesignJunction/Designity 등 타이포 트렌드 기사 종합 — C등급, 개별 기사 낮은 검증도)

**헤어라인 디바이더에 대한 중요한 반례**: 이번 리서치에서 나온 실제 방향은 "얇은 선(hairline divider)을 더 쓰자"가 아니라 정반대에 가깝다 — UpDivision 기사는 "Audit pages by removing redundant dividers and relying on spacing and type scale to separate sections"라고 명시한다. 즉 2026년 트렌드는 선을 얇게 쓰는 것보다 여백·타입스케일·배경 레이어로 구획을 나누고 선 자체를 줄이는 쪽이다. 논문 사수 홈 리디자인 시 "헤어라인 디바이더"를 기본기로 쓰더라도 남용하지 않는 게 더 현재형이다.

---

## 2. AI 제품 홈 컨벤션 2025-2026 — "프롬프트 박스 히어로"

**ChatGPT의 정석**: 925studios의 ChatGPT 인터페이스 분석에 따르면, OpenAI가 만든 가장 영향력 있는 결정은 "화면 중앙의 빈 텍스트 필드, 지시문도 템플릿도 온보딩 체크리스트도 없이 placeholder 하나"였다. 지금 익숙한 제안 칩("요약해줘", "브레인스토밍", "데이터 분석해줘")은 2023년에 추가된 **부가 기능**이지 처음부터 있던 게 아니었다는 순서가 중요하다 — 빈 입력창이 먼저였고 칩은 나중에 발견성(discoverability)을 보완하려고 얹은 것이다. 핵심 레이아웃(중앙 입력창 + 스트리밍 응답 + 좌측 히스토리 사이드바)은 2022년 이후 거의 변하지 않았다. (925studios, "ChatGPT Design Breakdown: The Interface That Defined AI UX", https://www.925studios.co/blog/chatgpt-interface-design-breakdown — B등급)

**Perplexity**: 팔로우업 칩(contextual follow-up chips)이 답변 아래 계속 이어지며 "빈 입력창 공포"를 없애고 세션 깊이를 늘리는 장치로 쓰인다. (검색 스니펫 기반, 원문 직접 열람은 HTTP 403으로 실패 — https://aiuxplayground.com/teardowns/perplexity/output/ — E등급, 인용은 참고용)

**비-챗 제품으로의 확산**: "프롬프트 박스 히어로" 패턴은 챗 제품을 넘어 확산 중이다. Notion은 AI 프롬프트 박스를 템플릿 마켓플레이스 수준으로 표준화했고, Framer AI는 히어로 섹션 자체를 AI 생성 결과로 채우는 워크플로를 제공한다. 다만 검색 결과에서 확인된 것은 "AI 기능 진입점으로서의 프롬프트 입력창"이 확산되고 있다는 방향성이지, 각 제품의 홈 화면이 챗 UI로 완전히 수렴했다는 근거는 아니다 — 오히려 **2026년 프런티어는 "프롬프트를 입력하면 대화가 시작되는 것"이 아니라 "AI가 먼저 무언가를 발견해서 보여주는 것"**이다. Attio(CRM)·Hex(데이터 워크스페이스)·Cursor(코딩 에이전트)의 대시보드는 사용자가 프롬프트를 치기 전에 AI가 "무엇을 주목해야 하는지" 먼저 순위를 매겨 보여준다 — "대시보드가 읽히기를 기다리지 않고, 알아챈 것을 먼저 말한다"는 표현이 이 흐름을 요약한다. (SaaSFrame Anatomy 글 — B등급)

**논문 사수 시사점**: 순수 챗봇이 아닌 논문 사수(업로드 → 분석 → 대시보드) 맥락에서는 ChatGPT식 "빈 프롬프트창"보다, Attio/Hex식 "AI가 먼저 무언가(최근 분석·추천 논문·미완료 작업)를 제시하고, 그 아래 업로드 CTA를 두는" 하이브리드가 2026년 관례에 더 부합한다. 인사말(greeting) 개인화는 챗 제품 관례이지만, "AI가 먼저 발견한 것을 보여주는 것"이 그보다 한 단계 더 현재형이라는 점을 반영할 필요가 있다.

---

## 3. 벤토 그리드, 아직 유효한가

**결론: 마케팅 페이지에서는 여전히 지배적, 인앱 대시보드에서는 제한적**. "67% of the top 100 SaaS products on ProductHunt now use this modular layout"라는 수치가 여러 마케팅성 블로그(Mockuuups Studio, Senorit)에서 반복 인용되지만 원 소스가 불명확해 신뢰도는 낮게 잡아야 한다(D등급). 다만 방향성 자체는 SaaSFrame의 실무형 가이드와도 일치한다.

SaaSFrame의 벤토 전용 글은 사용처를 명확히 가른다: **마케팅/랜딩 페이지**(Huly의 협업 기능 쇼케이스, Payhawk 랜딩)에서는 벤토가 "사이즈 기반 위계로 여러 가치 제안을 동시에 전달"하는 데 강하다. **대시보드 개요(overview) 화면**에서도 "차트·지표·리스트 등 다른 콘텐츠 타입을 시각적 혼란 없이 섞을 수 있어" 적합하다고 본다. 그러나 동시에 "in-app dashboards"에서 벤토를 **작업 흐름(task-focused workflow)에 억지로 끼워 넣는 것**은 경고 대상으로 명시한다 — 벤토의 경직된 구획화가 선형적 진행이 필요한 작업에는 오히려 방해가 된다는 것. 모바일에서는 단일 컬럼으로 접히는 순간 "벤토 효과" 자체가 사라진다는 한계도 지적한다. (SaaSFrame, "Designing Bento Grids That Actually Work: A 2026 Practical Guide", https://www.saasframe.io/blog/designing-bento-grids-that-actually-work-a-2026-practical-guide — B등급)

실제 프로덕트 사례: Linear의 다크 테크니컬 인터페이스는 벤토형 프로젝트 개요(대형 타일=활성 스프린트, 소형 타일=이슈 카운트)를 잘 쓰는 예로 꼽히고, Notion은 2024년 말 홈 리디자인에서 최근 페이지·팀 활동·데이터베이스 뷰에 벤토를 도입했다고 서술된다. Ramp는 벤토라기보다 "총 지출 옆에 시스템이 감지한 절감액을 나란히 두는" 아웃컴 중심 배치로, 벤토의 정신(이질적 정보를 한 화면에 병치)을 데이터 스토리텔링에 응용한 사례로 볼 수 있다. (검색 스니펫 종합, 원문 직접 확인 못함 — C등급)

**논문 사수 시사점**: 홈 히어로+통계 카드 영역(2~4개 타일)에는 절제된 벤토를 써도 되지만, 논문 목록·분석 결과 테이블 같은 작업 흐름 영역은 벤토가 아니라 일반 리스트/테이블 레이아웃을 유지하는 것이 2026년 실무 컨센서스에 가깝다.

---

## 4. 홈 화면 마이크로 인터랙션 — 세련됨 vs 과함

**스켈레톤 로딩**: 최종 레이아웃을 흉내 낸 회색 블록이 스피너보다 "체감 속도"를 높인다는 것은 여러 소스에서 반복되는 표준 관행이다(체감 40% 개선이라는 수치는 근거가 약한 블로그 수치이므로 방향성만 참고). 2026년 맥락에서 특기할 점은 시머(shimmer) 효과와 결합해 "로딩 중"임을 더 명확히 알리는 방향으로 진화했다는 것. (freefrontend/bricxlabs 류 블로그 종합 — C~D등급, 그러나 스켈레톤 자체는 이미 검증된 업계 표준)

**스태거드 엔트런스**: 카드가 20px 아래에서 페이드+슬라이드업하며 카드마다 약 80ms 지연을 두고, ease-out으로 전체 시퀀스를 700ms 이내에 끝내는 것이 구체적 가이드로 제시된다. 다른 소스는 "스태거 딜레이는 30~60ms, 100ms 이상은 슬라이드쇼처럼 느껴진다"고 더 타이트한 값을 제시한다 — 두 소스가 완전히 일치하진 않으므로 40~80ms 범위에서 화면 요소 개수에 맞춰 조정하는 것이 안전하다. 마이크로 인터랙션(호버, 버튼 프레스, 토글) 자체는 150~250ms가 "즉각적으로 느껴지는" 상한선으로 반복 인용된다. (0xminds/bricxlabs 종합 — C등급)

**호버 리프트**: 카드가 살짝 떠오르며(-translate-y-1 정도, 약 4px) 그림자가 짙어지는 hover:shadow-xl 패턴이 2026년에도 "가장 흔히 쓰이는 절제된 인터랙션"으로 남아 있다. 다만 transform·opacity만 애니메이션하고 width/height/margin/top-left처럼 레이아웃을 리플로우시키는 속성은 피하라는 성능 가이드가 공통적으로 따라붙는다. (Layoutscene/CSS 카드 호버 라운드업 종합 — C등급)

**드래그앤드롭 업로드 (논문 사수 핵심 인터랙션)**: 점선(dashed) 보더가 "드롭 가능"을 나타내는 가장 널리 인식된 시각 패턴이라는 점은 Dropbox·Google Drive가 굳힌 컨벤션으로, Smart Interface Design Patterns(Vitaly Friedman 계열, UX 패턴 자료로 신뢰도 높음)도 이를 확인한다. 드래그 오버 시 보더 색상 변화·배경 톤 변화·미세한 스케일 효과로 "여기 놓으세요"를 확정 신호로 주는 것이 표준이다. 진행률 표시는 (1) 실제 전송 진행률을 보여줄 것(가짜 인디케이터 스피너 금지), (2) 파일이 여러 개면 배치 전체가 아니라 **파일마다 독립적인 행/타일**로 대기·업로드중·완료·실패(사유 포함) 상태를 보여줄 것이 2026년 기준으로 제시된다. (Filestack blog / uxpatterns.dev / smart-interface-design-patterns.com 종합 — B등급, 구체적이고 실무 근거 있음)

**숫자 카운트업**: 이번 검색에서 "탭뉼러 넘버 + 카운트업" 조합을 직접 다루는 2026년 기사는 찾지 못했다(리서치 공백으로 명시). 다만 tabular-nums CSS 속성과 숫자 증가 애니메이션의 조합은 이미 다수 모던 대시보드(Linear, Vercel, Stripe 계열)에서 관찰되는 관행이며, 위 타이포 트렌드(고정폭 숫자)와 일관된 방향이라는 점은 확인된다 — 단, 이 문장은 직접 소스로 검증되지 않은 정황적 추론임을 밝힌다.

**세련됨 vs 과함의 경계**: timgraf.com의 "Mental Load in UX Design" 글은 딜라이트성 마이크로 인터랙션이 누적되면 인지 부하로 돌아온다는 경고를 담고 있어, 2026년의 절제 기조(보더리스, 무채색+단일 액센트)와 같은 맥락으로 읽힌다 — 인터랙션은 상태 변화를 확정해주는 최소 신호로 쓰고, 장식으로 쌓지 않는 것이 "과하지 않은" 기준이다. (timgraf.com, "The Cognitive Cost of Delight" — C등급)

---

## 5. 갤러리 스윕 — 눈에 띄는 사례 (2025-2026)

세션 제약상 Mobbin·Godly·dark.design·Land-book·PageFlows는 로그인/JS 렌더링 벽으로 스크린샷을 직접 열람하지 못했다. 아래는 실제로 원문을 열람할 수 있었던 갤러리(Nicelydone, SaaSFrame, 925studios)에서 확인한 구체적 프로덕트와, 접근 실패한 갤러리는 "직접 탐색 권장" 항목으로 별도 표기했다.

1. **Nicelydone — Dashboard & Stats 카테고리 (823+ 스크린샷)**: https://nicelydone.club/pages/dashboard — Gumloop(워크플로 빌더), Dub(링크 분석), Front(고객 지원), Bitly, Monarch 등 823개 이상의 실제 프로덕트 대시보드 스크린샷을 카테고리별로 열람 가능. 실제 화면 캡처 기반이라는 점에서 이번 조사에서 가장 신뢰도 높은 1차 갤러리. (A등급)

2. **SaaSFrame — Anatomy of High-Performance SaaS Dashboard Design (2026)**: https://www.saasframe.io/blog/the-anatomy-of-high-performance-saas-dashboard-design-2026-trends-patterns — Stripe/Vercel(단일 지표 히어로), Linear/Notion/Attio(점진적 노출), Mercury/Ramp(핀테크 신뢰감), Raycast/Railway/Sentry/Resend/Supabase(다크모드), Attio/Hex/Cursor/Pylon/Default(AI-네이티브)까지 35개 프로덕트를 카테고리별로 분류·분석해 이번 리서치에서 가장 체계적인 2차 자료였다. (B등급)

3. **925studios — ChatGPT Design Breakdown**: https://www.925studios.co/blog/chatgpt-interface-design-breakdown — "AI UX를 정의한 인터페이스"라는 제목대로 중앙 프롬프트창의 등장·진화(제안 칩, GPTs, Projects, 모델 셀렉터)를 연도별로 추적. 프롬프트 박스 히어로 컨벤션의 기원을 이해하는 데 가장 구체적인 자료. (B등급)

4. **SaaSFrame — Designing Bento Grids That Actually Work (2026)**: https://www.saasframe.io/blog/designing-bento-grids-that-actually-work-a-2026-practical-guide — Huly·Payhawk(마케팅 벤토 성공 사례) vs 인앱 대시보드에서의 오남용 경고를 구체적으로 대비시켜, "벤토를 어디에 쓰지 말아야 하는가"까지 다룬 드문 자료. (B등급)

5. **AI UX Playground — Perplexity Output UX 티어다운**: https://aiuxplayground.com/teardowns/perplexity/output/ — ChatGPT/Claude/Perplexity/Gemini를 나란히 놓고 구조화된 답변·팔로우업 UX를 분석하는 전문 티어다운 사이트로 검색 결과에 반복 노출됐으나, 이번 세션에서는 HTTP 403으로 원문 열람에 실패했다. 프롬프트 박스 히어로·인용 UI 등을 더 깊이 볼 필요가 있다면 직접(로그인 없이) 브라우저로 방문해 확인할 것을 권장. (E등급 — 접근 실패, 존재와 스코프만 확인)

6. **Mobbin — Explore Web Screens**: https://mobbin.com/explore/web/screens — 세계 최대 규모의 실제 모바일/웹 프로덕트 스크린샷 라이브러리로, "대시보드", "파일 업로드", "AI tool" 등 플로우 단위 필터링이 가능하다고 알려져 있음. 이번 세션은 로그인 요구로 직접 열람하지 못했으나, 논문 사수 리디자인 시 가장 먼저 확인해야 할 1차 소스로 강력 추천. (C등급 — 존재·성격만 2차 확인)

7. **SaaSUI (saasui.design)**: https://www.saasui.design/best-saas-ui-design-inspiration — 대시보드·온보딩·설정 등 화면 유형별로 실제 SaaS 앱 UI 패턴을 큐레이션하는 갤러리로, Mobbin·Godly·SaaSFrame·PageFlows·Refero 등 경쟁 갤러리 지형을 비교 정리한 메타 자료이기도 해서, 다음 리서치 라운드에서 갤러리를 고를 때 참고할 가치가 있다. (C등급)

8. **muz.li — 50 Best Dashboard Design Examples for 2026**: https://muz.li/blog/best-dashboard-design-examples-inspirations-for-2026/ — WanderWheels, Intelly, ZenWallet 등 다수 프로덕트를 소개하지만, 검색 스니펫 기준으로는 실제 출시된 SaaS라기보다 Behance/Dribbble류 컨셉 목업에 가까워 보인다("글래스모피즘", "네온 하이라이트" 등 마케팅 랜딩용 표현이 두드러짐). 시각적 영감 차원에서는 참고할 수 있으나, "2026년 실제 프로덕트가 어떻게 보이는가"의 근거로는 925studios·Nicelydone·SaaSFrame보다 신뢰도를 낮게 두어야 한다. (D등급)

---

## 소스 등급표 (A=1차/실제 스크린샷 근거, B=전문 분석·구체적 근거, C=일반 트렌드 블로그, D=마케팅성 리스티클/미검증 수치, E=원문 접근 실패·스니펫만 확인)

| URL | 성격 | 등급 |
|---|---|---|
| https://nicelydone.club/pages/dashboard | 실제 SaaS 대시보드 스크린샷 갤러리 (823+) | A |
| https://www.saasframe.io/blog/the-anatomy-of-high-performance-saas-dashboard-design-2026-trends-patterns | 35개 프로덕트 분석, 구체적 근거 | B |
| https://www.saasframe.io/blog/designing-bento-grids-that-actually-work-a-2026-practical-guide | 벤토 사용처 구분, 실무 경고 포함 | B |
| https://www.925studios.co/blog/chatgpt-interface-design-breakdown | ChatGPT UI 연도별 진화 분석 | B |
| https://www.925studios.co/blog/saas-dashboard-design-examples-2026 | 35개 SaaS 대시보드 카테고리 분석 | B |
| https://smart-interface-design-patterns.com/articles/drag-and-drop-ux/ | Vitaly Friedman 계열 UX 패턴 자료 | B |
| https://updivision.com/blog/post/ui-color-trends-to-watch-in-2026 | 디자인 에이전시 컬러 트렌드 기사 | C |
| https://think.design/blog/dashboard-design-in-2026-dos-and-donts/ | 디자인 에이전시 대시보드 원칙 기사 | C |
| https://fuselabcreative.com/top-dashboard-design-trends-2025/ | 디자인 에이전시, 실제/과열 트렌드 구분 | C |
| https://blog.filestack.com/upload-ui-components-drag-drop-progress-preview/ | 업로드 컴포넌트 벤더 블로그 | C |
| https://uxpatterns.dev/patterns/forms/file-input | UX 패턴 레퍼런스 사이트 | B |
| https://timgraf.com/ui/the-cognitive-cost-of-delight-balancing-micro-interactions-and-mental-load-in-ux-design/ | 마이크로 인터랙션 과용 경고 아티클 | C |
| https://0xminds.com/blog/guides/ai-animation-prompts-micro-interactions-tutorial | 애니메이션 타이밍 수치(스태거 등) | C |
| https://bricxlabs.com/blogs/micro-interactions-2025-examples | 마이크로 애니메이션 예시·수치 | C |
| https://mockuuups.studio/blog/post/best-bento-grid-design-examples/ | 벤토 그리드 리스티클, 통계 출처 불명확 | D |
| https://senorit.de/en/blog/bento-grid-design-trend-2025 | 벤토 그리드 리스티클 | D |
| https://muz.li/blog/best-dashboard-design-examples-inspirations-for-2026/ | 대시보드 "예시" 다수가 실제 출시 프로덕트인지 불명확 | D |
| https://mobbin.com/explore/web/screens | 실제 프로덕트 스크린샷 최대 라이브러리(로그인 필요, 직접 열람 실패) | C |
| https://aiuxplayground.com/teardowns/perplexity/output/ | AI 제품 UX 티어다운(HTTP 403으로 원문 열람 실패) | E |
| https://www.saasui.design/best-saas-ui-design-inspiration | 갤러리 지형 비교 메타 자료 | C |

---

## 논문 사수 리디자인에 대한 요약 제언 (본 리서치 기반)

1. 카드 보더 대신 배경 레이어(라이트/다크 각각 별도 elevation 스텝)로 위계를 만들고, 헤어라인 디바이더는 최소화하고 여백으로 대체.
2. 무채색(zinc/slate 톤) 베이스 + 단일 액센트 색만 액션에 사용, 색상은 상태(성공/경고/오류) 전용으로 예약.
3. 홈 히어로는 "빈 프롬프트창"보다 "최근 분석·추천 논문을 먼저 보여주는" Attio/Hex식 발견형 레이아웃 + 업로드 CTA 하이브리드가 2026년 관례에 더 부합.
4. 벤토는 히어로+통계 타일 2~4개 정도로 절제해서 쓰고, 논문 목록/분석 결과는 벤토가 아닌 일반 리스트로 유지.
5. 업로드 드롭존은 점선 보더 + 드래그 오버 시 색상·스케일 변화 + 파일별 독립 진행률 행을 표준 패턴으로 채택.
6. 스태거드 엔트런스는 40~80ms 간격/700ms 이내, 마이크로 인터랙션은 150~250ms, transform·opacity만 애니메이션.
