# AI 글쓰기·논문분석 도구 홈/대시보드 화면 리서치

조사일: 2026-07-13
조사 범위: 학술 AI(Paperpal, SciSpace, Jenni AI, Elicit, Scholarcy, Consensus 등), AI 글쓰기(Grammarly, Notion AI), 레퍼런스 매니저(Zotero) — 로그인 후 홈/대시보드 화면
목적: "논문 사수"(PDF 업로드 → AI 분석 → 워크벤치)의 홈 화면 설계를 위한 경쟁·인접 제품 벤치마킹

---

## 0. 총평 — 가장 눈에 띄는 산업 트렌드

2024~2025년 사이 학술 AI 도구들은 "최근 문서 그리드형 대시보드"에서 **"프롬프트/에이전트 우선 홈"**으로 급격히 이동했다. SciSpace와 Elicit 둘 다 홈 화면 헤드라인이 "How can I help with your research?" 형태의 대화형 인풋 박스이고, 문서 라이브러리는 별도 탭(사이드바)으로 밀려나 있다. 반면 Grammarly는 정반대로 문서 중심(Coda 인수 기반 블록 에디터)으로 재설계했고, Zotero·Scholarcy는 여전히 전통적인 "라이브러리=폴더/컬렉션" 리스트형이다. 즉 업계가 하나의 정답으로 수렴한 게 아니라 "제품의 핵심 동작(검색/합성 vs 편집/정리)"에 따라 홈 화면 패러다임이 갈린다.

---

## 1. SciSpace (Typeset)

**URL**: https://scispace.com/

**1) 로그인 후 홈 우선순위**: 새 작업 시작이 절대적으로 우선. 홈 화면 헤드라인이 "How can I help with your research?"이며, 그 아래 프롬프트 입력창 + 도구 칩(Search Papers / Literature Review / Draft / Diagrams / Presentation)이 배치된다. 최근 문서나 사용량 통계는 첫 화면에 노출되지 않고 별도 진입.

**2) 레이아웃 구조**: 좌측 접이식 사이드바(로고 토글) + 중앙 프롬프트형 메인 영역. 상단 글로벌 내비게이션에 Agent Gallery, AI Writer, Chat with PDF, Literature Review, Find Topics, Paraphraser, Citation Generator, Extract Data, AI Detector가 개별 메뉴로 나열 — 즉 "도구 모음"이 사이드바가 아니라 상단 메뉴로 노출되는 구조. 빈 상태는 대화형 인풋 하나로 처리(전통적 빈 카드/일러스트 방식이 아님).

**3) 논문분석 도구 특유 요소**: PDF Chat(문서와 대화), Extract Data(표 형태 데이터 추출), 라이선스된 2.8억 편 논문 기반 Literature Review. 신뢰 지표로 "9.6M+ 연구자 사용" 배지와 하버드·예일·스탠퍼드 등 대학 로고 스트립을 홈 하단에 노출(신뢰도 소구가 강함).

**4) 강점/약점**: 강점 — 도구가 많아도 진입점을 프롬프트 하나로 단순화해 첫 화면 인지부하를 낮춤. 약점 — 리뷰에서 "라이브러리/파일 저장 체계가 직관적이지 않다", "고트래픽 시 느려짐", "도구 간 이동이 가끔 헷갈림"이 반복 지적됨(SaaSworthy/Capterra 계열 리뷰).

**5) 시각 묘사**: 브랜드 톤은 오렌지(#FF6A00 계열)+블랙의 고대비 조합, 하프톤(halftone) 사진 처리와 굵은 산세리프 헤드라인, 라벨류는 모노스페이스체 사용(마케팅 배너 기준 — 실제 앱 UI는 화이트 배경에 오렌지 포인트로 절제된 편). "AI Agent for Academic Research"라는 카피에서 보듯 학술적이라기보다 "테크/에이전트" 톤에 가깝다.

---

## 2. Elicit

**URL**: https://elicit.com/

**1) 로그인 후 홈 우선순위**: SciSpace와 동일한 패턴 — 대화형 리서치 질문 입력이 최우선. 다만 워크플로우가 명시적으로 5갈래로 갈린다는 리뷰가 있음: Find Papers / Research Report / Systematic Review / Upload and Extract / Summarize Concepts.

**2) 레이아웃 구조**: 좌측 Library(라이브러리) 진입, 중앙은 검색·리포트 작업 영역. 스크린샷 확인 결과(공식 사이트 임베드 이미지) Library 화면은 좌측 컬렉션 트리(All / Recently deleted / Collections: Top papers, Reading list, Systematic reviews…) + 우측 2열 테이블(Source / Tags) 구조 — 화이트 배경, 톤다운된 그레이 텍스트, 포인트 컬러는 딥틸(deep teal). 상단에 "Search your library…" 검색바, "Connect Zotero" 드롭다운, 우측 상단 "Upload" 버튼(청록색 강조 버튼)이 고정.

**3) 논문분석 도구 특유 요소**: 검색 결과 카드에 저자·저널명·발행연도·인용수가 텍스트로 병기(별도 점수 배지는 없고 텍스트 메타데이터 중심). 라이브러리 항목에는 "Research paper / Clinical trial" 같은 문서 유형 필(pill)과 "Full text / Abstract only" 접근성 배지가 태그 옆에 별도로 붙는다. Alerts 기능은 새 논문 발견 시 "16 sources, High/Medium relevance" 형태로 관련도 등급을 요약.

**4) 강점/약점**: 강점 — 텍스트 밀도가 높지만 계층(제목 → 저자 → 저널/연도/인용수 → 유형 배지)이 명확해 스캔이 빠름. Upload 버튼이 전역 헤더에 고정되어 "새 문서 추가"가 항상 한 클릭. 약점 — 서드파티 연동(레퍼런스 매니저, PM 툴)이 API 없이 수동 임포트/익스포트뿐이라는 지적(2025년 중반 기준), 그룹 협업/멀티플레이어 기능 부재.

**5) 시각 묘사**: 미니멀·학술적 톤. 순백 배경, 그레이스케일 텍스트 위계, 딥틸 단일 포인트 컬러, 세리프가 아닌 깔끔한 산세리프. 장식 요소를 거의 배제하고 "표(table)"를 UI의 기본 단위로 쓰는 것이 특징 — 감성보다 데이터 신뢰성을 우선하는 디자인.

---

## 3. Paperpal

**URL**: https://paperpal.com/

**1) 로그인 후 홈 우선순위**: "문서 업로드 또는 텍스트 붙여넣기"로 즉시 시작하는 것이 최우선으로 설계되어 있다는 것이 다수 리뷰의 공통 서술. 대시보드는 첫 로그인부터 모든 도구에 쉽게 접근 가능하도록 구성.

**2) 레이아웃 구조**: 좌측(또는 우측) 아이콘 사이드바로 기능 전환(문법 검사/포맷팅/표절 검사 등), 중앙은 업로드/작성 패널, 우측 컨트롤 패널에 전체 기능 집약. doc/docx/PDF 업로드를 지원해 긴 문서 리뷰에 적합. 큰 버튼 + 툴팁으로 기능 설명을 곁들이는 온보딩형 구성.

**3) 논문분석 도구 특유 요소**: 저널 제출 전 체크(저널 스타일 준수, 표절/AI 탐지, 학술 문체 교정)가 핵심 기능이며, MS Word/Google Docs/Overleaf 애드인으로도 동일 기능을 제공(웹 대시보드가 유일한 진입점이 아님).

**4) 강점/약점**: 강점 — "패키지 안 봐도 되는" 수준으로 UI가 단순하고 퍼플/블루 하이라이트로 편집 영역이 시각적으로 도드라짐. 약점 — 공개된 리뷰들이 대부분 UI 스크린샷보다 기능 설명에 집중되어 있어(자사 블로그 포함) 대시보드 자체의 독자적 디자인 언어는 약한 편 — Word/Docs 애드인 의존도가 높아 "웹 대시보드"의 존재감이 SciSpace/Jenni보다 옅다.

**5) 시각 묘사**: 퍼플·블루 계열 하이라이트, 클린하고 여백이 넉넉한(overwhelming하지 않은) 편집 중심 UI로 묘사됨. 다만 이 항목은 1차 소스(직접 스크린샷)로 검증하지 못해 신뢰도는 중간(C~D).

---

## 4. Jenni AI

**URL**: https://jenni.ai/

**1) 로그인 후 홈 우선순위**: "My library"(문서/PDF 보관함)와 "Current document"(현재 작성 중 문서)가 나란히 배치되는 하이브리드형. 신규 작성 진입과 기존 자료 재사용이 동등한 비중.

**2) 레이아웃 구조**: 좌측 라이브러리(업로드된 PDF 목록) + 중앙 글쓰기 캔버스 + 우측 사이드바(인용, 아웃라인, AI 컨트롤)의 3분할 레이아웃. 라이브러리 카드에는 제목·저자·저널명·발행연도·Impact Factor(IF) 수치·"Open Access" 배지·"Cite Details / Open PDF" 퀵액션 버튼이 밀도 있게 배열됨.

**3) 논문분석 도구 특유 요소**: Impact Factor 표시, Open Access 배지, 출처 기반 생성(source-based generation: 업로드한 논문을 인용해 문장 생성) — 학술 AI 도구 중 "저널 신뢰도/영향력 지표"를 라이브러리 카드에 직접 노출하는 몇 안 되는 사례. 2026년 1월 문서 레벨 Peer Review 기능 추가, 리뷰 실행 이력(시각+종합 점수)을 카드로 보여줌.

**4) 강점/약점**: 강점 — "읽기(라이브러리) → 쓰기(캔버스) → 인용(사이드바)"의 흐름이 하나의 화면에서 유기적으로 연결됨. 처음 접하는 사용자에게도 친숙한 모던 UI라는 평가. 약점 — 카드 정보 밀도가 높아 학습 곡선이 있고, 세리프 폰트를 논문 제목에 쓰는 등 장식 요소가 늘면서 정보 스캔 속도가 느려질 수 있음.

**5) 시각 묘사**: 학술적 신뢰감을 겨냥한 세리프 타이포(논문 제목), 중립 배경 + 배지류에만 악센트 컬러, 카드 밀도가 높은 "콤팩트" 스타일. 전체적으로 "정보 우선, 장식 최소"의 절충형.

---

## 5. Scholarcy

**URL**: https://www.scholarcy.com/ / https://library.scholarcy.com/

**1) 로그인 후 홈 우선순위**: "Summarize anything"이라는 단일 카피로 새 문서 요약이 최우선. My Libraries가 메인 화면으로, 라이브러리(주제별 상위 폴더) 목록이 그 다음 우선순위.

**2) 레이아웃 구조**: My Libraries(전체 라이브러리 목록) → 개별 라이브러리 내부에 폴더(주제/하위주제) → 플래시카드 리스트. 정렬 기준(제목/저자/추가일/발행일/피인용수) 드롭다운과 "컬럼 버튼"으로 카드에 노출할 메타데이터를 커스터마이즈 가능 — 사용자가 정보 밀도를 직접 조절하는 드문 사례.

**3) 논문분석 도구 특유 요소**: 문서를 "플래시카드"로 변환해 초록/방법/결과/결론을 구조화 요약, 하이라이트·주석을 카드 위에 직접 추가 가능, "Enhance" 슬라이더로 요약 길이를 한 문장~상세 리서치 레벨까지 조절. Word 서지(bibliography) 자동 생성, Excel/Obsidian/Notion 익스포트.

**4) 강점/약점**: 강점 — 플래시카드라는 일관된 포맷 덕분에 1편이든 20편이든 동일한 스캔 패턴으로 읽을 수 있음. 사용자 커스터마이즈(컬럼 선택, 요약 길이 슬라이더)가 풍부. 약점 — 공개 문서에서 시각 디자인(색상/타이포/썸네일) 관련 서술이 거의 없어 "기능은 강하지만 비주얀 아이덴티티는 약하다"는 인상.

**5) 시각 묘사**: 1차 소스에서 색상/서체 정보를 확인하지 못함(D~E, 검증 필요). 다만 "clean, modern dashboard"라는 리뷰 서술과 플래시카드 메타포로 미루어 카드형·화이트 배경 계열로 추정됨.

---

## 6. Consensus

**URL**: https://consensus.app/

**1) 로그인 후 홈 우선순위**: 검색(질문 입력)이 절대적으로 우선 — 전통적 학술 검색엔진에 가까운 "distraction-free" 인터페이스. 사용량 통계는 대시보드에 상시 노출(월간 사용량 추적).

**2) 레이아웃 구조**: 검색창 중심의 단일 컬럼. 질문 입력 → 검색 결과 리스트 + 결과 상단에 "Consensus Meter" 위젯이 얹히는 구조. 필터(발행연도/관련도/저널 평판 정렬)와 자주 쓰는 검색어 고정(pin) 기능.

**3) 논문분석 도구 특유 요소(가장 특징적)**: **Consensus Meter** — Yes/No/Possibly 질문에 대해 상위 20편 논문의 결론을 분석해 "학계 합의 정도"를 시각 게이지로 보여줌. 각 논문에 Yes/No/Possibly/Mixed 태그가 붙고, 좌상단에 근거로 쓰인 논문 수를 표시. 관련 논문이 5편 미만이면 미터가 아예 표시되지 않는 등 "신뢰 임계값" 설계가 명확. Scholar Agent(신규 기능)는 복합 검색을 계획하고 학술 필터를 자동 적용, 하위주제별로 결과를 재구성.

**4) 강점/약점**: 강점 — Consensus Meter는 "여러 논문의 결론을 하나의 신뢰 가능한 시각 신호로 압축"하는 사례로, 논문사수의 "분석 결과 요약/점수화" UI에 직접 참고 가능. 약점 — 깊이 있는 방법론적 정독을 대체하지 못한다는 자체 인정(리뷰에서도 "정독의 대체재는 아니다"라고 명시).

**5) 시각 묘사**: 클래식 검색엔진에 가까운 미니멀 톤, 여백 많은 화이트 배경. Consensus Meter는 원형/막대 게이지 형태의 컬러 인디케이터(Yes=초록 계열, No=적색 계열로 추정 — 1차 스크린샷 미확보, 문서 서술 기반 추정치).

---

## 7. Grammarly (Docs / 홈)

**URL**: https://www.grammarly.com/ (신규 AI-native 문서 표면: Grammarly Docs)

**1) 로그인 후 홈 우선순위**: 2025년 8월 대규모 리디자인(Coda 인수 기반) 이후, "새 문서 작성"이 블록 기반 에디터로 강하게 전면화됨. 기존의 "검사할 문서 업로드/붙여넣기" 중심에서 "AI-native 문서 작성 표면(surface)"으로 전환.

**2) 레이아웃 구조**: 블록 퍼스트(block-first) 에디터 — 표, 컬럼, 구분선, 리스트, 헤더를 문서 안에 직접 삽입. 항상 열려 있는(always-on) 우측 사이드바에 AI 어시스턴트가 상주하며 요약/질의응답/제안을 제공. 실제 스크린샷(TechCrunch 게재, 확인함) 기준: 좌측 상단에 홈 아이콘+문서명("Untitled doc")이 있는 심플한 헤더, 중앙 문서 본문(화이트, 세리프 아님 산세리프 헤딩), 우측 패널에 "AI Chat" 라벨과 채팅 입력창, 우측 최외곽에 세로 아이콘 스트립(에이전트 바로가기: 코멘트, 검색, 사람, 북마크, 인용, 체크, 재생 아이콘 등 8개 내외)이 배치됨.

**3) 논문분석 도구 특유 요소**: Citation Finder 에이전트(출처 탐색+인용 자동 포맷), Grader 에이전트(교수 채점 기준/공개 강의자료 기반 피드백), AI Detector 에이전트(AI 생성 여부 스코어), Plagiarism Checker, Reader Reactions(독자 페르소나별 피드백 시뮬레이션), Paraphraser. 즉 "점수/등급"류 위젯이 세분화된 개별 에이전트로 쪼개져 있고 하나의 대시보드 위젯으로 뭉쳐 있지 않음.

**4) 강점/약점**: 강점 — 문서 작성과 AI 보조가 완전히 통합되어 컨텍스트 전환이 적음. 에이전트별 기능이 명확히 라벨링되어 발견성이 좋음. 약점 — "AI로 쓰기"와 "AI 탐지"를 한 제품 안에 공존시키는 데 대한 포지셔닝 긴장(자체 인정, VP 인터뷰에서 "집행 도구가 아니라 학생에게 창을 보여주는 것"이라고 해명) — 목적이 혼재된 제품처럼 보일 리스크.

**5) 시각 묘사**: 순백 문서 캔버스 + 그레이 아이콘 스트립, 우측 채팅 패널은 라이트 그레이 배경에 초록(Grammarly 브랜드 그린) 포인트가 말풍선/버튼에 사용됨. 전체적으로 Notion/Coda류의 "생산성 문서 툴" 톤에 가깝고, 학술적이라기보다 범용 오피스 문서 감성.

---

## 8. Zotero (Web Library)

**URL**: https://www.zotero.org/ (웹 라이브러리)

**1) 로그인 후 홈 우선순위**: "새 문서 시작"이라는 개념 자체가 없음 — 순수 레퍼런스 매니저이므로 **기존 라이브러리(컬렉션) 열람**이 100% 우선. 논문사수처럼 "업로드→분석"이 아니라 "수집→정리"가 핵심 동작.

**2) 레이아웃 구조**: 데스크톱 앱과 거의 동일한 3-페인 레이아웃 — 좌측 컬렉션/태그 트리(계층적 폴더링, 하위 컬렉션 다단 구성 가능), 중앙 아이템 리스트(테이블형), 우측 상세 패널(메타데이터/노트/첨부파일). 아이템 유형별로 색상 코드 아이콘(논문/책/웹페이지 등)을 구분.

**3) 논문분석 도구 특유 요소**: AI 분석·점수화 요소는 전혀 없음(순수 서지관리) — 이는 논문사수 대비 "선명한 대조군"으로서 의미가 있음. 대신 태그·컬렉션의 다단 계층 구조가 매우 성숙해 있어 "많은 문서를 어떻게 분류하는가"의 참고 사례로는 유효.

**4) 강점/약점**: 강점 — 검색바가 즉각적이고, 컬렉션 계층 구조가 유연해 대량의 문헌을 오래 축적한 사용자에게 익숙함. 약점 — AI 시대 관점에서는 "정적 보관함"에 가까워 분석/인사이트 제공이 전무 — 논문사수가 반드시 피해야 할 "그냥 파일 서랍" 패턴의 레퍼런스.

**5) 시각 묘사**: 실용적·중립적 톤 — 화려한 마케팅 컬러 없이 그레이스케일 기반, 아이템 타입 아이콘에만 색이 들어감. 학술 도구라기보다 파일 매니저에 가까운 사무적 인상.

---

## 9. Notion AI (홈/사이드바)

**URL**: https://www.notion.com/

**1) 로그인 후 홈 우선순위**: Home이 "전체 페이지"에서 "사이드바의 한 섹션"으로 격하된 것이 2025년 리디자인의 핵심 — Recents, Favorites, Teamspaces, Agents 등으로 세분화되어 워크플로우에 맞게 재배열 가능. 즉 "고정된 대시보드"가 아니라 "사용자가 구성하는 진입점".

**2) 레이아웃 구조**: 사이드바 폭 224px로 고정(수직 리듬 확보), 상단 컨트롤 패널에 Workspace 전환기·검색·Home·Meetings·Notion AI·Inbox가 나열. Teamspaces/Shared/Private 섹션은 클릭으로 접고 펼 수 있으며 드래그로 순서 재배치 가능. 대시보드 위젯은 행당 최대 4개, 총 12개까지 배치 가능한 커스텀 그리드.

**3) 논문분석 도구 특유 요소**: 해당 없음(범용 워크스페이스) — 다만 "Chats with Notion AI"가 사이드바 최상단 컨트롤에 검색과 나란히 배치된 점은, AI 어시스턴트 진입점을 내비게이션의 1급 시민으로 취급하는 참고 사례.

**4) 강점/약점**: 강점 — 고정폭 사이드바와 섹션 접기/재배치로 "개인화 가능한 홈"을 구현, 위젯 그리드가 유연함. 약점 — 커스터마이즈 자유도가 높은 만큼 초기 설정 없이는 "무엇부터 봐야 할지" 모호할 수 있음(빈 상태 설계 부담이 사용자에게 전가됨).

**5) 시각 묘사**: 뉴트럴 그레이스케일 사이드바에 최소한의 아이콘, 타이포는 시스템 산세리프 중심 — 브랜드 컬러를 억제하고 콘텐츠(사용자 페이지) 색상이 도드라지도록 설계된 "캔버스형" 미니멀리즘.

---

## 10. 참고(약식) — 추가 조사했으나 1차 소스 부족으로 상세 프로필 제외

- **Trinka AI**: 로그인 후 대시보드에서 문서 관리·환경설정 진입. 문서 리뷰 시 "Language Quality Score" + 카테고리별 수정 테이블(문법/어휘/구두점/학술체/철자)을 제공 — 논문사수의 "점수/등급" UI 참고 가치 있음. 시각 디자인 정보는 미확보(D).
- **QuillBot**: 단일 대시보드에서 패러프레이저/문법체커/표절검사/AI휴머나이저/인용생성기를 탭 전환. "최근 문서" 섹션 유무는 확인 못함(D).
- **Writefull**: 독립 대시보드가 아니라 Word/Overleaf 플러그인 안에 언어 품질 지표(문법/어휘/구두점/학술체/철자 5개 카테고리 도넛 또는 막대)를 표시하는 임베디드형 — "대시보드"라는 개념보다 "인라인 계기판"에 가까움(B, VU Amsterdam 협업 공식 블로그 확인).
- **Wordtune**: 대시보드에서 Rewrite/Summarize 진입, UI는 "sleek/직관적"이라는 서술 확인했으나 레이아웃 상세 미확보(D). 최근 리뷰에서 "페이지가 빈 화면이 되는 버그"가 수개월 지속되었다는 부정적 신호 있음(C).
- **Research Rabbit / Enago Read / R Discovery**: 발견(discovery) 중심 도구로 홈이 "씨앗 논문 입력 → 인용 그래프 시각화"(Research Rabbit) 또는 "추천 피드"(Enago Read, R Discovery) 형태. 대시보드 UI 상세는 리뷰에서 확인 못함(D~E).

---

## 11. 교차 패턴 요약

| 제품 | 홈 우선순위 | 진입 패러다임 | 문서 카드/점수 위젯 |
|---|---|---|---|
| SciSpace | 새 작업 | 프롬프트+도구칩 | 없음(도구 선택형) |
| Elicit | 새 작업 5갈래 | 프롬프트+워크플로우 카드 | 텍스트 메타데이터+유형 필 |
| Paperpal | 업로드/붙여넣기 | 큰 버튼+툴팁 온보딩 | 미확인 |
| Jenni AI | 라이브러리+현재문서 병렬 | 3분할(라이브러리/캔버스/AI) | IF·Open Access 배지 |
| Scholarcy | 요약 시작 | 플래시카드 라이브러리 | 커스터마이즈 가능 컬럼 |
| Consensus | 검색 | 단일 검색창 | Consensus Meter(합의도 게이지) |
| Grammarly | 새 문서(블록 에디터) | 문서+상시 AI 사이드바 | 에이전트별 분리형 점수 |
| Zotero | 기존 라이브러리 열람 | 3페인 파일매니저형 | 없음(순수 서지관리) |
| Notion AI | 사용자 구성 위젯 | 커스텀 사이드바+그리드 | 없음(범용) |

**논문사수에 전이 가능한 패턴 3가지**:

1. **"프롬프트/업로드 우선, 라이브러리는 2급 시민"** — SciSpace·Elicit·Consensus 공통. 첫 화면 인지 부하를 낮추려면 "무엇을 할지" 하나의 입력/업로드 지점으로 수렴시키고, 기존 문서함은 사이드바나 별도 탭으로 분리하는 편이 낫다.
2. **"분석 결과의 시각적 압축 지표"** — Consensus Meter(합의도 게이지), Jenni의 IF/Open Access 배지, Trinka의 Language Quality Score+카테고리 테이블은 모두 "AI가 읽은 내용을 하나의 스캔 가능한 신호로 압축"한다. 논문사수의 분석 결과(품질/리스크/완성도 점수)도 텍스트 나열보다 단일 게이지+카테고리 브레이크다운 조합이 유효할 것.
3. **"업로드 버튼은 전역 헤더에 고정"** — Elicit처럼 어느 화면에 있든 우측 상단에 Upload가 고정되어 있으면, 새 문서 추가가 "탐색"이 아니라 "반사 동작"이 된다. 논문사수도 대시보드뿐 아니라 워크벤치 내부에서도 새 논문 업로드 진입점을 상시 노출하는 것이 좋다.

---

## 12. 소스 목록 및 신뢰도 등급

등급 기준: A=1차 소스(공식 사이트/공식 문서/직접 스크린샷 확인), B=신뢰 매체·공식 블로그(간접 확인), C=리뷰 사이트/서드파티 가이드(다수 일치), D=단일 소스·마케팅 편향 가능, E=추정/미검증

- [SciSpace 공식 홈](https://scispace.com/) — A (홈페이지 텍스트+메타 이미지 직접 확인)
- [Elicit 공식 홈](https://elicit.com/) — A (홈페이지+임베드 스크린샷 3장 직접 열람)
- [Grammarly 디자인 개편 — TechCrunch](https://techcrunch.com/2025/08/18/grammarly-gets-a-design-overhaul-multiple-ai-features/) — A (기사 내 실제 UI 스크린샷 직접 열람)
- [Jenni AI 공식 홈](https://www.jenni.ai/) — B (마케팅 페이지, 실제 로그인 화면 아님)
- [Scholarcy — Organise and customise (공식 가이드)](https://help.scholarcy.com/guide/organise-and-customise) — B
- [Consensus — The Consensus Meter (공식 헬프센터)](https://help.consensus.app/en/articles/10069920-the-consensus-meter) — B
- [Notion — Navigate with the sidebar (공식 헬프센터)](https://www.notion.com/help/navigate-with-the-sidebar) — A
- [Notion — Dashboards view (공식 헬프센터)](https://www.notion.com/help/dashboards) — A
- [Zotero Web — UCL 라이브러리 가이드](https://library-guides.ucl.ac.uk/zotero/web) — C
- [Zotero — Collections and Tags (공식 지원문서)](https://www.zotero.org/support/collections_and_tags) — A
- [Paperpal 공식 리뷰 블로그](https://paperpal.com/blog/news-updates/paperpal-review) — C (자사 블로그, UI 스크린샷 서술 없음)
- [Paperpal 리뷰 — codingem.com](https://www.codingem.com/paperpal-review/) — C
- [SciSpace 리뷰 — aithor.com](https://aithor.com/blog/scispace-review) — D (검색 스니펫만 확인, 원문 접근 실패 410)
- [SciSpace — SaaSworthy](https://www.saasworthy.com/product/typeset) — C
- [Trinka AI 공식](https://www.trinka.ai/) — B
- [Writefull 대시보드 공식 블로그(VU Amsterdam 협업)](https://blog.writefull.com/new-monitor-academic-language-quality-with-the-writefull-dashboard/) — B
- [QuillBot 리뷰 — research.com](https://research.com/software/reviews/quillbot-review) — C
- [Wordtune 리뷰 — Capterra](https://www.capterra.com/p/217137/Wordtune/reviews/) — C
- [ResearchRabbit 공식/2025 릴리스](https://www.researchrabbit.ai/announcement-researchrabbit-release-2025) — B
- [Enago Read 공식](https://www.read.enago.com/) — B
- Mobbin Grammarly Web 스크린 페이지 — 접근 실패(403), 미사용

