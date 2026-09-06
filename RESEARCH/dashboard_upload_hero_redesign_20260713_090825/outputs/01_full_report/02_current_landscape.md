# 2. 사례 컬렉션 — 대시보드 겸 업로드 메인의 실제 제품 레퍼런스

> 각 사례: 무엇을 보여주나 → 레이아웃 → 논문사수가 가져갈 것. 등급은 부록 bibliography 참조.

---

## A. 종합 SaaS 홈/대시보드 — "위계를 어떻게 잡는가"

### A1. Stripe Dashboard 홈 — 스탯 카드 행의 교과서
- https://dashboard.stripe.com (문서: src_004, src_005)
- Stripe 대시보드 홈은 상단에 3~4개 KPI 카드(짧은 라벨+큰 숫자+증감+스파크라인)를 가로 행으로 배치하고, 그 아래 순매출 차트가 이어진다. 라벨은 "Revenue"처럼 한 단어로 압축 — 숫자가 주인공이다.
- 색은 성공/실패에만 기능적으로 사용, 브랜드 퍼플은 CTA에만.
- **가져갈 것**: 논문사수의 "이번 달 비용" 카드를 이 문법(라벨 위, tabular-nums 큰 숫자, 보조 스파크)으로 재작성.

### A2. Vercel Dashboard — 상태를 그림으로 답하는 카드
- https://vercel.com/blog/dashboard-redesign (src_002)
- Vercel 대시보드는 프로젝트 카드에 실제 배포 스크린샷 썸네일과 배포 상태 배지를 표시한다 — "빌드가 성공했는가"라는 단일 질문에 스캔 한 번으로 답한다(src_002, src_040).
- **가져갈 것**: 논문 카드에도 "분석 완료/진행중/실패" 상태 배지를 1급 정보로. (PDF 썸네일 자체는 식별력이 낮아 비권장 — §D3 참조)

### A3. Notion Home — 인사말 + 섹션형 최근 항목의 원형
- https://www.notion.com/help/navigate-with-the-sidebar (src_003, src_049)
- Notion Home은 개인화 인사말, 섹션형 최근 항목, 빠른 생성 버튼으로 구성되며 사이드바 중심으로 재편됐다. 섹션별 표시 개수·순서를 사용자가 조절.
- **가져갈 것**: 현재 논문사수의 그리팅+최근 논문 구조와 가장 가까운 사례. "인사 한 줄은 유지하되 그 아래 요약 라인을 붙이는" 확장 방향의 근거.

### A4. Linear — 액션 우선, 분석은 뒤로
- https://linear.app/docs/display-options (src_001)
- 홈은 "지금 처리할 활성 이슈" 리스트가 메인, 차트·통계는 별도 Insights 탭 뒤로. 행 리스트는 상태/담당자/마감일 등 표시 속성을 토글할 수 있는 고밀도 구성.
- **가져갈 것**: "일하는 화면과 분석하는 화면의 분리" 원칙. 논문사수 홈에서 비용 통계는 작게, 업로드·최근 논문(액션)은 크게.

### A5. Mercury — 단일 히어로 지표의 극단
- https://mercury.com/blog/october-2025-product-updates (src_006)
- 로그인 직후 합산 잔액을 히어로급으로 크게, 나머지는 전부 후순위. 지표를 1~2개로 극단적으로 제한해 인지 부하 최소화.
- **가져갈 것**: "다 보여주기"의 반대 증명. 논문사수 홈의 히어로는 지표가 아니라 업로드지만, "하나만 크게"의 원칙은 동일하게 적용된다.

### A6. Ramp — 무채색 + 포인트 컬러 1개의 벤토
- https://bakkenbaeck.com/case/ramp (src_008)
- 웜 오프화이트 캔버스 + 화이트 카드 + 헤어라인 보더에 형광 옐로우그린 하나만 CTA·활성 상태에 사용. 브랜드 차원의 "Bento box" 그리드 시스템으로 저밀도·고밀도 화면을 같은 문법으로 수용.
- **가져갈 것**: 타일 크기 = 중요도. 색을 절제할수록 "돈이 움직이는 곳"(논문사수라면 업로드와 상태 변화)에 시선이 집중된다.

### A7. Attio — 커스터마이즈형 대시보드 (대조군)
- https://attio.com/help/reference/managing-your-data/dashboard-and-reports/dashboards (src_007)
- 위젯을 사용자가 직접 배치·리사이즈. 범용 CRM에는 맞지만, 논문사수처럼 단일 목적 홈에는 고정 위계가 낫다는 대조 사례.

---

## B. 업로드/시작-퍼스트 진입점 — "드롭존을 어떻게 히어로로 만드는가"

### B1. ChatPDF — 3중 진입 + 포맷 불안 제거 (직접 확인)
- https://www.chatpdf.com/ (src_009)
- 드롭존 하나에 "Drop a file or upload" + "CTRL+V to paste" — 드래그/클릭/붙여넣기 3방식 병기. 지원 포맷(.pdf .docx .pptx .md .txt) 아이콘을 드롭존 하단에 나열해 "이거 넣어도 되나?" 불안을 사전에 해소. 대시보드 대신 대학 로고 등 신뢰 신호로 빈 화면을 채움.
- **가져갈 것**: 포맷 아이콘 나열, 붙여넣기 진입. 단 "대시보드 없음"은 단일 목적 툴이라 가능한 단순화 — 논문사수는 라이브러리가 핵심 가치이므로 그대로 복사하면 안 됨.

### B2. SciSpace Chat with PDF — 업로드 즉시 작업공간 전이 (도메인 최유사)
- https://scispace.com/chat-pdf (src_010)
- 별도 업로드 페이지 없이 드롭 즉시 좌(원문)·우(채팅) 2단 작업 화면으로 전환. SciSpace와 Adobe Acrobat AI Assistant는 문서 업로드 직후 자동 요약과 추천 질문을 제시한다(src_010, src_020) — "이 연구의 목적은?" 같은 칩이 빈 채팅창 공포를 없앤다. DOI/URL 붙여넣기, OCR 토글 등 학술 특화 보조 경로.
- **가져갈 것**: 업로드 → 워크벤치 전이를 즉시(전환 애니메이션 포함)로. 분석 완료 직후 "기여점 요약", "선행연구 갭" 같은 도메인 칩 제시.

### B3. Humata — 처리 상태의 신뢰 연출
- https://www.humata.ai/ (src_011, src_012)
- Humata는 업로드 처리 상태를 펄싱 인디케이터와 카운트다운으로 시각화하고, 신규 업로드와 기존 문서 리스트를 한 화면에 공존시킨다. "지식 베이스" 콘셉트라 업로드는 상단 고정 액션, 기존 문서는 그 아래 리스트.
- **가져갈 것**: 논문 분석 대기시간(파싱·구조화)에 펄싱 → 진행 단계 표시. 업로드+라이브러리 공존 골격.

### B4. Gamma — 프롬프트·붙여넣기·업로드의 동급 통합
- https://gamma.app (src_013, src_014)
- 하나의 대형 입력창에서 "설명 입력 / 아웃라인 붙여넣기 / Word·PDF 업로드"가 동급 진입. 입력창 최상단 고정, 그 아래 최근 프로젝트 갤러리.
- **가져갈 것**: "파일이 없어도 시작할 수 있는" 보조 경로 발상. 논문사수도 장기적으로 "제목/초록만으로 시작" 같은 칩 추가 가능.

### B5. Elicit — 워크플로 카드 분기 + 전역 Upload 고정
- https://elicit.com/ (src_015)
- 홈은 단일 드롭존 대신 워크플로 카드(Find Papers / Upload and Extract / …) 분기. 라이브러리는 좌측 컬렉션 트리 + 우측 테이블, 우상단에 Upload 버튼이 전역 고정 — 새 문서 추가가 "탐색"이 아니라 반사동작이 된다.
- **가져갈 것**: 전역 헤더/사이드바에 업로드 버튼 상시 노출(홈 밖에서도).

### B6. Dropbox Dash — 신규 액션과 대시보드의 상시 병존
- https://dash.dropbox.com/features/universal-search (src_018, src_019)
- 검색창 히어로 바로 아래 최근 파일·자주 쓰는 앱이 접히지 않고 상시 노출. Elicit, Dropbox Dash, Gamma는 신규 시작 진입점을 상단에 고정하고 최근 항목을 같은 화면에 상시 병존시킨다(src_015, src_018, src_013) — 사용량이 쌓일수록 화면이 풍부해지는 구조.
- **가져갈 것**: 논문사수 홈 골격의 1순위 참조. "빈 화면"과 "복잡한 화면" 사이의 균형점.

### B7. Adobe Acrobat AI Assistant — 용량 고지와 요약 선제시
- https://www.adobe.com/acrobat/generative-ai-pdf.html (src_020)
- 업로드 직후 핵심 요약(key takeaways)과 시작 질문 목록을 자동 제시. 최대 처리 용량(600페이지)을 사전 고지해 "이 문서도 될까?" 불안을 제거.
- **가져갈 것**: 업로드 존에 지원 한도(페이지 수·용량) 마이크로카피.

### B8. Perplexity — 이력은 사이드바, 캔버스는 항상 입력창 (보조 참고, 등급 낮음)
- https://www.perplexity.ai/ — 재방문자의 최근 스레드를 좌측 사이드바로 격리, 메인은 신규/재방문 무관하게 입력창 우선. 직접 확인 실패로 2차 서술 기반이라는 점 유의.

---

## C. 학술·문서 AI 직접 경쟁군 — "같은 도메인은 어떻게 푸는가"

### C1. SciSpace 홈 — 프롬프트 + 도구 칩
- https://scispace.com/ (src_010)
- 홈 헤드라인이 "How can I help with your research?" — 프롬프트 입력창 + 도구 칩(Search / Literature Review / Draft…). SciSpace와 Elicit의 로그인 후 홈은 프롬프트/워크플로 선택이 최우선이고 문서 라이브러리는 별도 탭으로 분리된다(src_010, src_015). 오렌지+블랙 고대비 톤.

### C2. Jenni AI — 라이브러리 카드에 학술 신뢰 지표
- https://www.jenni.ai/ (src_031)
- 좌(라이브러리)·중(캔버스)·우(AI 사이드바) 3분할. 논문 카드에 Impact Factor 수치와 Open Access 배지를 직접 노출 — 학술 신뢰 지표를 카드에 박은 드문 사례. 세리프 제목 타이포로 학술 감성.
- **가져갈 것**: 논문사수 RecentPaperRow에 저널/연도 같은 메타데이터 계층 추가 여지.

### C3. Scholarcy — 플래시카드 요약 + 밀도 커스터마이즈
- https://help.scholarcy.com/guide/organise-and-customise (src_032)
- 초록/방법/결과/결론을 플래시카드로 구조화, 노출 컬럼과 요약 길이를 사용자가 조절. 1편이든 20편이든 동일한 스캔 패턴.

### C4. Consensus — 분석 결과를 게이지 하나로 압축
- https://consensus.app/ (src_016, src_017)
- Consensus는 검색 결과를 Consensus Meter 게이지로 압축하며 근거 논문이 5편 미만이면 미터를 표시하지 않는다 — 신뢰 임계값 설계가 명확하다.
- **가져갈 것**: 논문사수 분석 결과(완성도/리스크)를 "단일 게이지 + 카테고리 브레이크다운"으로 압축하는 발상. "데이터 부족 시 숨김" 원칙까지.

### C5. Grammarly Docs — 블록 에디터 + 상시 AI 사이드바 (2025.8 개편)
- TechCrunch 보도 스크린샷 기준(src_048): 중앙 문서 캔버스 + 우측 상시 AI 채팅 패널 + 최외곽 에이전트 아이콘 스트립(Citation Finder, Grader, AI Detector…). 점수형 기능이 개별 에이전트로 분리된 구조.

### C6. Paperpal / Trinka / Writefull — 점수·카테고리 계기판 (보조)
- Paperpal은 업로드/붙여넣기 즉시 시작형 온보딩 대시보드(src_034). Trinka는 Language Quality Score + 카테고리별 수정 테이블(src_035), Writefull은 Word/Overleaf 안에 언어 품질 5개 카테고리 계기판을 임베드(src_036). "문서 품질을 숫자+카테고리로 보여주는" 공통 문법.

### C7. Zotero — 반면교사: "그냥 파일 서랍"
- https://www.zotero.org/support/collections_and_tags (src_033)
- 3페인 파일매니저형, 분석·인사이트 전무. 논문사수 홈이 리스트만 남으면 이렇게 보인다 — 피해야 할 기준선.

---

## D. 컴포넌트 표준 — "요즘 문법"의 구체 스펙

### D1. 스탯 카드 행 (shadcn/Tremor/Tailwind가 굳힌 기본값)
- 2025-2026 대시보드 키트(shadcn dashboard-01, Tremor, Tailwind Stats)는 스탯 카드 행 → 시계열 차트 → 데이터 테이블의 세로 스택 골격으로 수렴했다(src_021, src_022, src_023, src_024).
- 카드 아나토미: 뮤트 라벨(12~13px) → 큰 숫자(24~36px, tabular-nums) → 증감 배지 → (옵션) 풋터/스파크라인. `npx shadcn add dashboard-01`로 재현 가능한 사실상의 업계 기본값.
- 주의: 4칸 강박 금지 — 실제 지표 수만큼(논문사수는 2~3개)만.

### D2. AI 비용 위젯
- Anthropic Console과 OpenAI Platform의 비용 화면은 일별 비용 차트, 기간·필터 선택, 내보내기 중심으로 구성된다(src_025, src_026, src_027). Cursor는 풀별 소진율과 모델 단가 컨텍스트를 함께 노출(src_028), Langfuse는 트레이스 단위 원가 태깅 → 집계축 → 시계열 구조(src_054).
- 논문사수는 후불 실비용형 + 간헐 사용(주 1~2회)이므로: 일별 바는 대부분 0으로 비어 보일 위험 — "월 누적 큰 숫자 + 최근 활동 로그" 조합이 안전. 예산 상한 기능이 생기면 그때 진행바 추가.

### D3. 최근 항목: 행 리스트 vs 썸네일 그리드
- 텍스트·메타데이터 중심 콘텐츠에는 행 리스트(Linear), 시각 콘텐츠에는 썸네일 카드 그리드(Gamma, Figma)가 관례다(src_001, src_014, src_030).
- 논문 PDF는 썸네일 식별력이 낮으므로 행 리스트 + 상태 배지 + 상대시간 + 우측 액션이 적합. Figma의 16:9 썸네일 그리드(src_030)는 시각물 제품용.

### D4. Empty state
- 2026년 empty state 기준선은 일러스트보다 명확한 헤드라인과 단일 CTA이며, 샘플 데이터 프리로드로 빈 상태를 회피하기도 한다(src_043, src_029). Supabase는 샘플 데이터 옵션으로 빈 화면 자체를 없앤다.
- 논문 0건일 때: 리스트 영역에 "첫 논문을 업로드해보세요" 헤드라인 + 업로드 포커스 버튼. 비용 위젯은 "$0.00" + "분석하면 여기에 비용이 표시됩니다" 보조문구.

### D5. 드롭존 인터랙션
- 드래그앤드롭 업로드의 표준 패턴은 점선 보더 드롭존, 드래그오버 시각 변화, 파일별 독립 진행 표시다(src_044, src_045, src_046). 가짜 스피너 금지 — 실제 진행률을 보여줄 것.

### D6. 모션
- 홈 화면 모션 가이드는 스태거 진입 40~80ms 간격에 전체 700ms 이내, 개별 인터랙션 150~250ms, transform과 opacity만 애니메이션하는 것이다(src_050, src_051).

---

## E. 갤러리 — 직접 눈으로 볼 곳

| 갤러리 | URL | 비고 |
|---|---|---|
| Nicelydone | https://nicelydone.club/pages/dashboard | 실제 SaaS 대시보드 스크린샷 823+, 이번 조사에서 열람 가능했던 최고 신뢰 갤러리(src_041). Linear 905장·Mercury 367장·Ramp 114장 보유 |
| Mobbin | https://mobbin.com/explore/web/screens | 최대 규모, 로그인 필요 — 리디자인 착수 시 "dashboard", "file upload" 필터로 직접 열람 권장(src_042) |
| SaaSFrame | https://www.saasframe.io | 35개 제품 분석 아티클 2건이 이번 조사의 체계적 2차 자료(src_037, src_038) |
| 925studios | https://www.925studios.co | ChatGPT UI 연대기·35개 대시보드 분석(src_039, src_040) |

미열람: Godly, dark.design, Land-book, PageFlows, Refero — 로그인/JS 장벽. 시각 디테일(여백감, 그림자 깊이)은 텍스트 조사의 한계이므로, 구현 전 Mobbin/Nicelydone에서 SciSpace·Elicit·Gamma·Dropbox Dash 스크린을 직접 대조할 것.
