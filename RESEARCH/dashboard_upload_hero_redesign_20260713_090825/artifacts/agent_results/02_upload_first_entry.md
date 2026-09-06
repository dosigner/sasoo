# 업로드-퍼스트(Upload-First) 진입점 UX 리서치 — 2024~2026 실사례

조사일: 2026-07-13
목적: "논문 사수"(AI 논문 편집/분석 웹앱)의 홈 화면에서 "PDF 업로드"를 대시보드형 빈 드롭존이 아니라 자연스러운 히어로로 만들기 위한 참조 사례 수집.
조사 방법: WebSearch + WebFetch (직접 fetch 시도, 다수 사이트는 403/봇 차단으로 검색 스니펫·서드파티 UI 아카이브 스니펫에 의존). 각 사례 신뢰도(A~E)는 하단 출처 목록 참고.

---

## 1. ChatPDF (chatpdf.com) — 등급 A (홈페이지 직접 fetch 성공)

**진입점 위치/비중**: 메인 헤드라인("Chat with any file, video or website") 바로 아래, 페이지 최상단(fold 안)에 업로드 존이 유일한 1차 CTA로 배치. 페이지에서 반복적으로 여러 번 등장(스크롤 중간에도 재노출).

**인터랙션 디테일**:
- 드롭존 안에 파일 아이콘 + 링크 아이콘이 함께 표시되어 "파일이든 링크든 다 받는다"는 인상을 즉시 전달.
- 카피: "Drop a file or upload" + 보조 카피 "CTRL+V to paste text or links" — 드래그, 클릭 업로드, 붙여넣기(단축키) 세 가지 진입 방식을 한 화면에서 동시에 제시.
- 지원 포맷 아이콘(.pdf, .doc, .docx, .ppt, .pptx, .md, .txt)을 드롭존 하단에 나열해 "뭘 넣어도 되는지" 사전에 불안을 해소.
- 업로드 존 밑에 "Ask to start a chat"류 텍스트 입력 프롬프트가 이어져, 업로드→질문이 하나의 연속된 플로우로 보이게 설계.

**대시보드 공존 방식**: 별도 "최근 항목" 대시보드는 홈에 노출하지 않음. 대신 업로드 CTA 위/아래에 신뢰 신호(하버드·케임브리지·옥스퍼드·스탠퍼드 로고, "10M+ Researchers" 등 소셜 프루프)를 배치해 "첫 방문자가 업로드를 망설이지 않게" 설계. 즉 대시보드 대신 **신뢰 확보용 콘텐츠**로 빈 화면의 허전함을 채움.

**왜 잘 작동하는가**: 진입 방법이 3중(드래그/클릭/붙여넣기)이라 어떤 사용자 습관에도 대응. 포맷 아이콘 나열이 "이거 넣어도 되나?"라는 인지 부하를 없앰. 재방문자를 위한 최근 문서 목록이 없는 대신 소셜 프루프로 신뢰를 대체—단일 목적 툴이라 가능한 단순화.

**시각 묘사**: 드롭존은 카드형(둥근 모서리, 옅은 배경색), 점선 테두리보다는 아이콘 중심 구성. 카피 톤은 명령형 짧은 문장("Drop a file or upload").

---

## 2. SciSpace — Chat with PDF (scispace.com/chat-pdf) — 등급 B

**진입점 위치/비중**: 로그인 후 "Upload" 버튼 또는 DOI/URL 붙여넣기가 홈의 핵심 액션. 학술 논문 특화 서비스답게 업로드 CTA 옆에 "DOI나 URL도 가능"이라는 대체 경로를 병기.

**인터랙션 디테일**: 파일을 채팅 인터페이스 자체에 바로 드롭하면 즉시 백그라운드에서 처리 시작(별도 "업로드 페이지"로 이동하지 않음). OCR이 필요한 스캔 문서를 위한 "Enable OCR" 토글을 업로드 단계에 노출. 업로드 완료 후에는 논문 요약과 함께 "이 연구의 목적은?", "데이터 수집 방법은?" 같은 **자동 생성 추천 질문 칩**이 등장해 첫 질문의 진입장벽을 낮춤.

**대시보드 공존 방식**: 업로드 직후 화면이 좌(논문 원문 뷰)·우(AI 채팅) 2단 분할로 전환. 즉 "대시보드"가 별도로 있다기보다, 업로드 자체가 작업 공간으로 즉시 전이되는 구조 — 업로드 화면과 작업 화면의 경계가 거의 없음.

**왜 잘 작동하는가**: 논문 사수와 가장 유사한 도메인(학술 PDF)이라 참조 가치가 높음. 추천 질문 칩은 "빈 채팅창 공포"를 없애는 핵심 장치 — 논문 사수에도 업로드 직후 "이 논문의 기여점은?", "선행연구 대비 차별점은?" 같은 칩을 적용할 수 있음.

**시각 묘사**: 미니멀한 2단 레이아웃, 업로드 버튼은 단색 채움형 버튼(점선 드롭존보다 확실한 클릭 대상 우선).

---

## 3. Humata (humata.ai) — 등급 B

**진입점 위치/비중**: 홈 헤드라인 "AI meets your knowledge base" 아래 "Try for free" 대형 CTA. 업로드 자체는 로그인 후 화면에서 드래그앤드롭 존 또는 업로드 버튼으로 제공.

**인터랙션 디테일**: 파일이나 폴더 단위 드래그앤드롭 지원. 업로드 후에는 **회색 펄싱 원(processing indicator)**이 나타났다가 카운트다운 타이머로 바뀌는 프로그레스 연출 — 대부분 20초 이내 처리 완료. 좌(채팅)·우(문서) 2단 레이아웃은 SciSpace와 동일한 패턴.

**대시보드 공존 방식**: "지식 베이스"라는 콘셉트 자체가 여러 문서의 누적 라이브러리이므로, 업로드 존과 기존 문서 목록이 같은 화면에 공존 — 신규 업로드는 상단 고정 액션, 기존 문서는 그 아래 리스트/그리드로 이어짐.

**왜 잘 작동하는가**: 처리 중임을 보여주는 펄싱→카운트다운 애니메이션이 "지금 뭔가 일어나고 있다"는 신뢰를 줌 — 논문 사수의 분석 대기시간(파싱·구조화)에도 적용 가치 높음.

**시각 묘사**: 클린하고 여백이 넉넉한 레이아웃, 브랜드 컬러 강조 없이 기능 자체(펄싱 인디케이터)로 상태를 전달.

---

## 4. Gamma (gamma.app) — 등급 B

**진입점 위치/비중**: 홈의 중앙 텍스트 입력창이 최우선 진입점. "설명을 입력"/"아웃라인 붙여넣기"/"Word·PDF·Google Doc 업로드" 세 가지가 하나의 입력창에서 탭 전환 또는 병기 형태로 제공됨.

**인터랙션 디테일**: 프롬프트, 붙여넣기, 파일 업로드가 사실상 동급 진입 방식으로 취급됨 — "무엇을 넣든 우리가 구조화한다"는 메시지. 업로드 시 Gamma가 문서 내용을 읽어 슬라이드 구조를 자동 생성, 초안이 1분 이내 도출. 2025년 9월 Gamma Agent(v3.0) 도입 이후에는 자연어로 "톤 바꿔줘", "전체 재구성해줘" 같은 대규모 수정도 같은 입력창에서 처리.

**대시보드 공존 방식**: 신규 생성 입력창이 최상단 고정, 그 아래로 최근 프로젝트/템플릿 갤러리가 이어지는 전형적인 "생성 입력 위 + 갤러리 아래" 구조.

**왜 잘 작동하는가**: 업로드를 "여러 시작 방법 중 하나"로 격하시키지 않고 프롬프트와 동급으로 배치함으로써, 파일이 없는 사용자도 진입장벽 없이 시작 가능 — 논문 사수에도 "파일 업로드" 외에 "붙여넣기"나 "제목만으로 시작" 같은 보조 경로 참고 가능.

**시각 묘사**: 카드형 대형 입력창, 미니멀 아이콘(첨부 클립, 문서 아이콘), 파스텔톤 배경.

---

## 5. Elicit (elicit.com) — 등급 B

**진입점 위치/비중**: 홈에 단일 드롭존 대신 **5개 워크플로 카드**(Find Papers / Research Report / Systematic Review / Upload and Extract / Summarize Concepts)를 병렬 배치 — 업로드는 이 중 하나의 명시적 옵션으로 존재.

**인터랙션 디테일**: "Upload and Extract" 카드를 선택하면 PDF를 업로드해 데이터를 추출하는 플로우로 진입. 여러 파일을 한 번에 드롭 가능하고 Zotero·EndNote·Mendeley 레퍼런스 매니저에서 가져오기도 지원 — 연구자의 기존 워크플로(레퍼런스 매니저)를 존중하는 보조 진입점.

**대시보드 공존 방식**: 업로드된 PDF는 사용자 전용 "Library"에 누적되며, 결과는 **논문(행) × 추출 항목(열)의 그리드** 형태로 표시 — 단일 문서 챗이 아니라 다수 문서를 표 형태로 비교하는 리서치 워크벤치 개념.

**왜 잘 작동하는가**: 업로드를 유일한 시작점으로 강요하지 않고 "논문 찾기부터 시작할지, 이미 가진 논문을 업로드할지"를 사용자가 선택하게 함 — 논문 사수 사용자 중 "이미 원고가 있는 사람"과 "아직 없는 사람"을 분기하는 참조 모델.

**시각 묘사**: 무채색 기반에 틸(teal) 포인트 컬러 하나만 사용하는 절제된 팔레트 — "신뢰할 수 있는 연구 도구"라는 톤을 시각적으로 강화.

---

## 6. Consensus (consensus.app) — 등급 C (직접 fetch 실패, 검색 스니펫 기반)

**진입점 위치/비중**: 홈 정중앙에 검색창 하나만 배치 — 로그인 전에도 바로 질문 입력 가능. 업로드가 아니라 "연구 질문 검색"이 히어로라는 점에서 논문 사수와는 결이 다르지만, "빈 화면에 입력창 하나만 남기고 나머지를 걷어낸" 미니멀리즘의 참조가 됨.

**인터랙션 디테일**: 검색창에 자연어 질문을 입력하면 관련 논문의 합의 수준을 요약. 도움말 문서에서 "명확한 연구 질문을 입력하라"는 가이드를 전면에 노출해 빈 입력창의 막막함을 줄임.

**대시보드 공존 방식**: 홈 자체는 대시보드 없이 검색창 단일 포커스 — 검색 이후 결과 페이지에서 필터·저장 등 도구가 등장하는 점진적 노출(progressive disclosure) 구조.

**왜 잘 작동하는가**: "무엇을 입력해야 할지 모르겠다"는 두려움을 줄이기 위해 입력창 자체보다 주변 가이드 카피에 힘을 실음.

**시각 묘사**: 화이트 기반, 검색창은 둥근 필(pill) 형태로 넓게 배치.

---

## 7. Perplexity (perplexity.ai) — 등급 C (직접 fetch 실패, 검색+통념 기반)

**진입점 위치/비중**: 홈은 중앙 정렬된 단일 검색/질문창이 전부에 가까움 — "Ask questions. Get answers." 톤으로, 대시보드적 요소(최근 검색 등)는 로그인 후 사이드바로 격리하고 메인 캔버스는 항상 입력창 중심 유지.

**인터랙션 디테일**: 입력창 내부에 파일 첨부 아이콘이 함께 있어 "텍스트 질문"과 "파일 업로드 후 질문"이 동일한 입력창에서 분기 없이 처리됨. Focus 모드(Academic/Social/Video 등) 칩으로 검색 범위를 조정 가능.

**대시보드 공존 방식**: 재방문자의 "최근 스레드"는 좌측 사이드바에 격리, 메인 히어로 영역은 신규/재방문 상관없이 항상 입력창이 우선 — 즉 **대시보드를 메인 캔버스에서 완전히 분리**하는 패턴.

**왜 잘 작동하는가**: 재방문자도 매번 "새로 시작하는 느낌"을 주는 것이 오히려 핵심 가치(검색 도구는 매번 새 질문이 자연스러움) — 논문 사수처럼 "각 세션이 새 논문"인 경우에도 유효한 패턴.

**시각 묘사**: 다크/라이트 모두 지원, 입력창은 그림자 없는 플랫 카드, 첨부 아이콘은 클립이 아닌 "+" 아이콘.

---

## 8. Adobe Acrobat AI Assistant (adobe.com/acrobat) — 등급 C

**진입점 위치/비중**: "Select files" 버튼 + 드래그앤드롭이 나란히 제공되는 전통적 업로드 UI. 다만 다중 문서 워크스페이스(PDF Spaces)로 최대 10개 문서를 동시에 다룰 수 있어, 업로드가 "1회성 이벤트"가 아니라 지속되는 작업 공간의 시작점으로 설계됨.

**인터랙션 디테일**: 업로드 직후 AI Assistant가 문서 전체를 훑어 "핵심 요약(key takeaways)"과 "시작할 수 있는 질문 목록"을 자동 제시 — SciSpace의 추천 질문 칩과 유사한 패턴이 대기업 제품에도 채택됨.

**대시보드 공존 방식**: 업로드 전 화면은 단순 업로드 존, 업로드 후에는 채팅박스가 포함된 문서 뷰로 전환 — 업로드와 작업공간의 전환이 명확히 분리된(모달·페이지 전환형) 구조로, SciSpace/Humata의 "즉시 전이형"과 대비되는 참조점.

**왜 잘 작동하는가**: 대형 문서(최대 600페이지)를 다루는 전문가 사용자를 위해 처리 가능 용량과 포맷을 명시적으로 고지 — 사용자의 "이 문서도 될까?" 불안을 사전에 해소.

**시각 묘사**: Adobe 특유의 레드 포인트 컬러, 업로드 아이콘은 클라우드 업로드 형태.

---

## 9. Dropbox Dash (dash.dropbox.com) — 등급 B

**진입점 위치/비중**: 홈은 파일 업로드보다 **통합 검색창**이 히어로 — "여러 앱·파일·도구를 한 검색창에서" 컨셉. 업로드는 검색창 주변의 부차적 액션.

**대시보드 공존 방식**: 논문 사수 설계에 가장 참고할 만한 패턴 — 검색창(신규 액션) 바로 아래에 "최근 파일", "자주 쓰는 앱" 등 대시보드 요소가 항상 함께 노출됨. 업로드/검색이 접히지 않고(collapse 없이) 대시보드와 동시에 상시 노출되는 구조.

**왜 잘 작동하는가**: 재방문자에게는 최근 항목이, 신규 액션이 필요한 사용자에게는 검색/업로드가 동시에 보여 "이 화면이 비어 보이지 않게" 함 — 사용량이 쌓일수록 화면이 더 풍부해지는 구조.

**시각 묘사**: 카드 기반 그리드, 앱별 아이콘 뱃지로 소스 구분.

---

## 3대 핵심 패턴 요약 (논문 사수 적용 관점)

1. **업로드=작업공간 즉시 전이형** (SciSpace, Humata): 별도 "업로드 페이지"를 만들지 않고 드롭 즉시 좌(문서)·우(채팅/분석) 2단 작업 화면으로 전환. 대기 시간에는 펄싱→카운트다운 같은 상태 인디케이터로 신뢰 유지.
2. **업로드 직후 추천 질문/액션 칩 자동 생성** (SciSpace, Adobe Acrobat AI): 빈 채팅창의 막막함을 없애는 핵심 장치. 논문 사수라면 업로드 직후 "이 논문의 기여점 요약", "선행연구 갭 분석" 등 도메인 특화 칩 제공 가능.
3. **입력창/업로드존은 상단 고정, 대시보드(최근 항목)는 접지 않고 상시 병존** (Dropbox Dash, Gamma, Elicit): 신규 사용자용 액션과 재방문자용 이력을 같은 화면에서 계층만 분리해 동시 노출 — "비어 보이는 화면"과 "복잡한 화면" 사이의 균형점.

부가 인사이트: ChatPDF·Perplexity처럼 **단일 목적 툴**은 대시보드 없이 신뢰 신호(소셜 프루프, 톤)로 빈 화면을 채우는 것도 유효한 전략이지만, 논문 사수처럼 "재방문·누적 라이브러리"가 핵심 가치인 제품에는 Dropbox Dash/Elicit형(업로드+대시보드 상시 공존)이 더 적합.

---

## 출처 및 신뢰도

| 등급 | 의미 |
|---|---|
| A | 대상 페이지 직접 fetch 성공, 실제 카피/구조 확인 |
| B | 공식 문서·헬프센터·서드파티 UI 아카이브(Mobbin 등) 기반, 구조적으로 신뢰 가능 |
| C | 검색 스니펫 종합 + 일반 통념(직접 fetch 실패, 403 등) |

- [ChatPDF (chatpdf.com)](https://www.chatpdf.com/) — A (직접 fetch)
- [SciSpace Chat with PDF](https://scispace.com/chat-pdf) — B (fetch 403, 보조 문서 다수 확인: [How does Chat with PDF work](https://scispace.com/help/en/articles/10660595-how-does-chat-with-pdf-work-chat-with-pdf-interacting-with-research-papers-using-ai), [Chat with PDF Tutorial](https://scispace.com/resources/how-to-chat-with-pdf/))
- [Humata AI](https://www.humata.ai/) — B (직접 fetch 부분 성공 + [How to upload docs](https://docs.humata.ai/guides/readme/how-to-upload), [Eleken file upload UI tips](https://www.eleken.co/blog-posts/file-upload-ui))
- [Gamma.app](https://gamma.app/) — B (fetch 403, [Gamma text-prompt guide](https://gamma.app/explore/content/guides/gamma-turn-text-prompt-into-presentation), [Gamma AI deck generator](https://gamma.app/explore/content/guides/gamma-ai-deck-generator-speed-and-structure))
- [Elicit.com](https://elicit.com/) — B (직접 fetch 부분 성공 + [Paper Search](https://elicit.com/solutions/search), [Living Documents UX pattern](https://elicit.com/blog/living-documents-ai-ux/))
- [Consensus.app](https://consensus.app/) — C (fetch 403, [How to Search & Best Practices](https://help.consensus.app/en/articles/9922660-how-to-search-best-practices))
- [Perplexity.ai](https://www.perplexity.ai/) — C (fetch 미시도, 검색 스니펫 + [SaaSUI Perplexity UI breakdown](https://www.saasui.design/application/perplexity-ai))
- [Adobe Acrobat AI Assistant](https://www.adobe.com/acrobat/generative-ai-pdf.html) — C (검색 스니펫 기반)
- [Dropbox Dash](https://dash.dropbox.com/) — B ([공식 Universal Search 페이지](https://dash.dropbox.com/features/universal-search), [Fall 2025 release 블로그](https://blog.dropbox.com/topics/news/fall-2025-release-dropbox-dash-context-aware-ai-teammate))
- [Krea AI](https://www.krea.ai/) — C (검색 스니펫 + [Mobbin Krea 홈페이지 스크린](https://mobbin.com/explore/screens/c20380e3-3511-422a-aa2b-11ab0d892855))
- [v0.dev](https://v0.dev/) — D (검색 스니펫 위주, 홈 화면 구조 상세 확인 실패)
- 일반 참고: [SaaS File Upload & Drag-and-Drop UX Patterns (2026)](https://www.saasui.design/blog/saas-file-upload-ux-patterns), [Drag and drop UI examples — Eleken](https://www.eleken.co/blog-posts/drag-and-drop-ui), [Nicelydone Upload documents 패턴 모음](https://nicelydone.club/tags/upload-documents)

**미검증/제한 사항**: ChatGPT·Claude.ai·Napkin·v0.dev는 직접 fetch가 403으로 차단되어 검색 스니펫과 일반 지식 수준의 서술에 그침(등급 C~D). 실제 스크린샷 대조 검증이 필요하면 별도 브라우저 자동화(Playwright/claude-in-chrome) 세션으로 재수집 권장.
