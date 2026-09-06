# Phase 5 종합 뷰(Synthesis View) 템플릿 스펙

작성: 2026-09-06, `/wayfinder` 지도 작성 인터뷰(13라운드, 결정 48건) 결과. 구현 전 스펙이며 코드는 포함하지 않는다. 용어는 저장소 루트 `CONTEXT.md`를 따른다. 열린 결정은 `.scratch/phase5-synthesis-view/map.md`의 티켓으로 관리한다.

## 배경

Phase 5 탭("시각화 & 종합")은 지금 다이어그램 6~10개를 구획 구분 없이 위에서 아래로 나열한다. 종합 텍스트와 수식은 없고, 그림(Phase 3)과 레시피(Phase 4)와의 연결도 없다. 이 스펙은 Phase 1~4 결과를 한 화면에 엮는 **종합 뷰**를 정의하고, 무엇을 템플릿(코드와 프롬프트)으로 고정하고 무엇을 모델에 맡길지 확정한다.

독자는 두 상황이다: 논문을 한 번 읽은 연구자가 며칠 뒤 방법론을 빠르게 되살리는 **복습**, 그리고 랩 미팅이나 동료에게 설명하는 **타인 설명**. 스캔 속도와 위치 기억이 우선이고, 설명 문장은 필요할 때 펼친다.

확인한 사실(2026-09-06 기준 코드):
- 수식은 어느 Phase도 추출하지 않는다(`schemas.py`, `analysis_routes.py`에 equation, formula, latex 필드 0건). 렌더 쪽은 `Markdown.tsx`가 remark-math와 rehype-katex를 쓰고 있어 LaTeX 표시는 준비돼 있다.
- Phase 1 결과(`_DEEP_DIVE_SCHEMA`)에 `problem_definition`, `as_is`, `to_be`, `solution`, `method_summary`, `key_results`가 있다. 프론트 문구 `기존 접근 (As-Is)`, `목표 상태 (To-Be)`가 이미 있다.
- Phase 3 그림 `FigureInfo`는 `figure_num`, `caption`, `file_path`, `page_number`를 가진다. Phase 4 `RecipeParameter`는 `name`, `value`, `unit`, `notes` 4필드다.
- 기획 프롬프트(`_VIZ_PLAN_SCHEMA`)는 6~10개 항목을 mermaid 또는 paperbanana 도구로 분류하고 diagram_type은 flowchart, sequence, mindmap 3종이다. Mermaid 스타일 규칙(시맨틱 classDef 6종 팔레트, 노드 모양, 화살표 의미, subgraph, linkStyle)은 프롬프트에 이미 있다.
- `MermaidRenderer`는 ELK 레이아웃, `useMaxWidth`, 다크와 라이트 테마 변수, 코드 보기와 복사와 다운로드와 다시 생성 툴바를 가진다. 높이 제한은 없다.
- `FigureGallery`에 `role="dialog"` 라이트박스가 있고, 채팅 인용 칩이 그림과 표 탭의 카드로 점프하는 `citationFocus` 라우팅이 있다.
- UI 계약(PR #43): 칩 어휘는 `chip-tint`, `chip-soft`, 색점 3종만이고 정보성 숫자는 칩 금지, 텍스트로 표시한다. 이모지는 쓰지 않는다.
- `model_registry.py`의 role별 프로바이더 오버라이드 표는 DEC-022(2026-09-06)로 비어 있다. 모든 role은 설정에서 선택한 프로바이더로만 돈다.
- `@excalidraw/mermaid-to-excalidraw`는 flowchart, sequence, class, ER, state를 네이티브 변환하고 mindmap은 SVG 이미지 폴백이다. 프론트는 React 19.2.8, mermaid 11.16, Vite 8이다.

## 1. 목적지와 범위

이 문서가 고정하는 층은 둘이다.
1. **LLM 출력 규칙**: 종합 스테이지 스키마와 프롬프트 지시, 다이어그램 기획 프롬프트의 구획과 개수와 종류 규칙, Mermaid 스타일 규칙.
2. **프론트 렌더링 레이아웃**: 구획 구조와 순서, 각 요소의 위치와 크기와 접기, 실패와 로딩 상태, 라이트박스, 반응형.

범위 밖: 내보내기 산출물(ZIP, HTML 노트, 마크다운)의 레이아웃, 표(Table) 썸네일 참조, 구획 사이 이동 UI, Excalidraw 편집 캔버스. 자세한 목록은 §9.

## 2. 구획 구조

종합 뷰는 고정 순서의 구획 5개다. 어떤 논문을 열어도 같은 자리에 같은 종류가 있다. 구획 헤더는 고정 문구와 lucide 아이콘 하나, 번호 없음, 우측에 muted 메타(다이어그램 개수 등).

| 순서 | 구획 | 내용 | 데이터 출처 |
|---|---|---|---|
| 1 | 요약 | 문제 1문장, 방법 1문장, 핵심 수치 최대 3개 | 종합 스테이지 |
| 2 | 문제와 기여 | as_is와 to_be 2열 대비, solution 1줄 | Phase 1 기존 필드 재사용 |
| 3 | 방법 흐름 | 개념도 1개, 수식 체인 2~5개, Mermaid 다이어그램 최대 3개 | 종합 스테이지(수식), 기획(다이어그램) |
| 4 | 결과 | 그림 참조 2~4개 스트립, 결과 Mermaid 다이어그램 최대 2개 | 종합 스테이지(그림 선택), 기획(다이어그램) |
| 5 | 재현 핵심 | 핵심 파라미터 표 최대 5행, 레시피 탭 링크 | 종합 스테이지(선택), Phase 4 |

구획 내부 순서는 고정한다. 방법 흐름은 개념도, 수식 체인, Mermaid 순서다(물리 설정을 보고, 그것을 기술하는 수식을 보고, 절차를 본다). 결과는 그림 스트립 뒤에 다이어그램이다(원본 증거가 해석보다 앞선다).

데이터가 없는 요소는 자리를 숨긴다(수식 0개면 수식 체인 없음, as_is와 to_be가 비면 구획 2 숨김). 생성이 **실패**한 요소는 다르다: 자리를 유지하고 제목과 오류 한 줄과 "다시 생성" 버튼을 둔다(§7).

## 3. 구획별 표시 규칙

### 3.1 요약 카드
다른 구획과 같은 카드(배경과 테두리 동일). 문제 문장과 방법 문장만 15~16px로 키운다. 그 아래 한 줄에 **핵심 수치 타일** 최대 3개: 큰 숫자(값과 단위), 그 아래 작은 라벨, 배경 없음. 칩이 아니다(UI 계약 준수). 타일 호버에 근거 문장(evidence)을 툴팁으로 보인다. 문장은 line-clamp 2줄, 클릭하면 전체.

### 3.2 문제와 기여
왼쪽 이전(as_is), 오른쪽 이후(to_be) 2열 카드, 아래에 solution 한 줄. 각 열 line-clamp 3줄과 더보기. 패널 폭이 약 560px 미만이면 컨테이너 쿼리로 1열(위아래)로 전환한다. 새 생성 없이 Phase 1 필드를 그대로 쓴다.

### 3.3 방법 흐름
- **개념도**: 항상 1개, 첫 자리. 생성 이미지는 `object-contain`, 카드 배경은 surface. 클릭하면 라이트박스.
- **수식 체인**: 개념도 아래, Mermaid 위에 세로로 2~5개. 항목 하나는 display math 중앙 정렬, 우측에 논문 수식 번호 `(Eq. N)` muted(번호 없으면 생략), 그 아래 한 줄 뜻 왼정렬(line-clamp 1~2), 그 아래 기호표(기호와 뜻 최대 4쌍) 접기. 순서는 모델이 정한 유도 순서다(논문 번호는 표기만 하고 정렬 기준이 아니다). KaTeX 파싱 실패 수식은 그 자리에 LaTeX 원문을 모노스페이스로 두고 뜻은 그대로 보인다. 체인에서 버리지 않는다. 긴 수식은 가로 스크롤.
- **Mermaid 다이어그램**: 최대 3개, 기획 순서. 다이어그램이 위, 설명이 아래 접기(§4).

### 3.4 결과
- **그림 스트립**: 높이 140px 고정, 너비는 그림 비율대로, 가로 스크롤. 썸네일 아래 `Fig. N` 라벨과 해석 한 줄(line-clamp 2). 클릭하면 그림 탭의 해당 그림으로 점프(`citationFocus` 재사용). 종합 뷰 안에서 원본 크기로 그리지 않는다.
- **결과 다이어그램**: 최대 2개, flowchart만(비교 구조). 표는 참조하지 않는다. 표의 값이 필요하면 핵심 수치의 근거 문장에 "Table 2" 식으로 언급되는 것으로 충분하다.

### 3.5 재현 핵심
표 열은 이름, 값+단위(한 셀, 예: `1550 nm`), 비고(notes가 하나라도 있을 때만 열 표시). 최대 5행. 어떤 5개를 고를지는 종합 스테이지가 재현에 가장 민감한 파라미터를 기준으로 정하고, 이름이 Phase 4 `parameters`의 `name`과 일치하지 않는 항목은 버린다. 표 아래 "레시피 탭에서 전체 보기" 링크.

## 4. 다이어그램 공통 규칙

- **배치**: 다이어그램이 위, 설명 문단이 아래. 설명은 기본 접힘(2줄 초과분). 뷰 헤더 우측에 "설명 모두 펼치기" 토글 하나가 있고 세션 동안만 기억한다(저장 없음). 수식 기호표도 이 토글을 따른다.
- **크기**: 너비는 카드 폭, 높이는 뷰포트의 약 60%를 상한으로 맞춰 축소. 클릭하면 라이트박스.
- **라이트박스**: 앱 전체를 덮는 오버레이. PDF 뷰어와 오른쪽 분석 패널을 포함한 워크벤치 전체 위에 가장 높은 z-index로 올리고, 뒤 화면은 블러 처리한다(2026-09-06 사용자 추가 결정, 기존 글래스 블러 토큰 재사용). 원본 크기에서 마우스 휠 줌과 드래그 팬, ESC 닫기, 방향키로 같은 구획의 이전과 다음 다이어그램. 상단에 제목과 툴바(코드 보기와 복사, 다운로드, 다시 생성). `FigureGallery`의 라이트박스를 일반화해 재사용한다. `role="dialog"`, 포커스 트랩, 닫힐 때 원래 요소로 포커스 복귀.
- **툴바**: 구획 안에서는 호버 시 우상단에 아이콘만(개념도 다운로드 버튼과 같은 방식). 코드 탭은 라이트박스 안에서만.
- **아이콘**: 이모지 금지. 구획 아이콘은 lucide 고정 세트(제안: 요약 `FileText`, 문제와 기여 `Target`, 방법 흐름 `GitBranch`, 결과 `BarChart3`, 재현 핵심 AppIcon `recipe`). LLM 출력(제목, 설명, Mermaid 레이블)의 이모지는 프롬프트로 금지하고 후처리로 제거한다.
- **접근성**: 썸네일 alt는 캡션, 수식 컨테이너 aria-label은 뜻, 라이트박스는 위 규칙, 스켈레톤은 `aria-busy`.

## 5. LLM 출력 규칙

### 5.1 호출 구조
Phase 5는 두 스테이지로 나눈다. 스키마를 작게 유지하고 LaTeX 자유서술이 다이어그램 계획을 망치지 않게 하기 위해서다.
1. **종합 스테이지**(새 role `synthesis`): 요약 문장 2개, 핵심 수치, 수식 체인, 결과 그림 선택, 핵심 파라미터 선택.
2. **다이어그램 기획**(기존 role `viz_planning`, 스키마 개정): 개념도 1개와 Mermaid 다이어그램 계획.

둘 다 기존 `_run_chain_stage` 패턴(Gemini는 문서 참조 체인, OpenAI는 Phase 1~4 결과와 본문 텍스트 폴백)과 캐시 키 규칙을 따른다. 종합 스테이지 입력에는 Phase 1~4 결과 외에 그림 목록(번호와 캡션)과 레시피 파라미터 이름 목록을 넣는다.

### 5.2 모델과 effort
DEC-022를 그대로 따른다: role별 프로바이더 오버라이드 없음, 설정에서 선택한 프로바이더로만 돈다. `synthesis` role은 레지스트리 양쪽 열에 등록한다(Gemini 열 `MODEL_FLASH_HQ`, OpenAI 열 `MODEL_LUNA`). effort는 **medium으로 시작**하고 §8 게이트에서 high와 비교해 확정한다.

### 5.3 종합 스테이지 스키마(필드는 전부 required, 마지막 속성은 숫자)
DEC-014 교훈(마지막 자유서술 필드가 폭주의 근원)에 따라 마지막 속성은 숫자로 둔다. Gemini에서 `maxLength`는 무효로 실증되었으므로 길이는 프롬프트 지시로 부탁하고 화면에서 자른다(§6).

```
problem_sentence: string        # 한 문장, 80자 안팎
method_sentence: string         # 한 문장, 80자 안팎
key_metrics: [ {label, value, unit, evidence} ]   # 최대 3. unit 필수(무차원은 "-"), evidence는 논문 원문 인용 한 문장
equations: [ {latex, meaning, symbols: [{symbol, meaning}], paper_number} ]  # 2~5. symbols 최대 4, paper_number는 "3" 또는 ""
result_figures: [ {figure_num, interpretation} ]  # 2~4. figure_num은 Phase 3 목록의 값만
key_parameters: [ {name} ]      # 최대 5. Phase 4 parameters.name과 일치
equation_count: integer         # 마지막 필드
```

백엔드 검증(값 가드 #48의 수치 동치 검사 재사용):
- `key_metrics`: unit이 비었거나 evidence의 수치가 본문 텍스트에 없으면 항목을 버린다. 버린 개수는 로그에 남긴다(게이트 지표).
- `result_figures`: figure_num이 Phase 3 목록에 없으면 버린다.
- `key_parameters`: name이 레시피에 없으면 버린다.
- 배열 상한 초과분은 잘라낸다.

### 5.4 다이어그램 기획 스키마 개정
```
concept_illustration: {title, description, category}   # 항상 1개, PaperBanana
diagrams: [ {title, block, diagram_type, description, category} ]
  # block: enum(method|result), diagram_type: enum(flowchart|sequence)
  # method 최대 3, result 최대 2, result는 flowchart만
diagram_count: integer          # 마지막 필드
```
프롬프트 지시: 개념도는 논문의 물리적 설정 또는 핵심 개념 도식 1개를 반드시 낸다(이론 논문도 문제 설정 도식으로). 방법 다이어그램은 절차(flowchart)와 신호 또는 시간 순서(sequence), 결과 다이어그램은 비교 구조(flowchart). mindmap은 제거한다. 상한 초과분은 백엔드가 자른다. 총 다이어그램은 개념도 1 + Mermaid 최대 5 = 6.

### 5.5 Mermaid 규칙
LLM 출력은 Mermaid 텍스트로 고정한다(자동 레이아웃, 기존 정화와 복구 파이프라인 재사용). 렌더러는 현재 `MermaidRenderer`의 SVG(ELK 레이아웃, 앱 테마 변수, 스타일 제거 폴백 사다리)로 확정한다(2026-09-06 프로토타입 티켓 01, §10). Excalidraw 변환은 도입하지 않는다. 기존 문법 규칙과 스타일 규칙(시맨틱 classDef 팔레트, 모양, 화살표, subgraph, linkStyle)은 유지하고, `_MERMAID_RENDERABLE_TYPES`에서 mindmap을 빼고 mindmap 관련 스타일 지시(C절)를 제거한다.

## 6. 텍스트 길이
프롬프트 지시: 요약 문장 80자 안팎, 그림 해석과 수식 뜻 60자 안팎. 화면: 요약 문장 2줄, as_is와 to_be 3줄, 그림 해석 2줄, 수식 뜻 2줄로 line-clamp하고 클릭하면 전체. 데이터는 자르지 않는다.

## 7. 상태

- **로딩**: 종합 스테이지가 먼저 도착하면 구획 5개 뼈대를 즉시 그리고, 다이어그램 자리는 제목과 회색 스켈레톤(다이어그램 상한 높이)으로 채운다. 스켈레톤 개수는 기획 항목 수.
- **부분 실패**: 다이어그램 렌더 실패나 개념도 생성 실패는 그 자리에 제목, 오류 한 줄, "다시 생성"(기존 regenerate와 repair 경로). 리스트 순서는 변하지 않는다.
- **종합 다시 만들기**: 뷰 헤더에 버튼 하나. 종합 스테이지만 재실행하고 다이어그램은 유지. 예상 비용을 기존 재분석 모달 문구 체계로 보인다. 구획별 재생성은 만들지 않는다.
- **기존 논문**(구획 정보와 종합 결과 없음): 지금 갤러리를 그대로 그리고 상단에 "종합 뷰 만들기" 버튼. 누르면 종합 스테이지만 실행하고, 기존 다이어그램은 프론트가 category로 구획을 배정한다(comparison은 result, 나머지는 method, paperbanana 첫 항목은 개념도 자리). 재분석은 요구하지 않는다.
- **헤더 동작 3개**: 전체 다운로드(기존 ZIP), 설명 모두 펼치기, 종합 다시 만들기.
- **자리**(2026-09-06 구현 계획 승인 시 결정): 코드에는 "Phase 5 탭"이 없고 갤러리가 요약 탭 deep_dive 구역 안에 인라인으로 있었다. 종합 뷰는 새 탭 `synthesis`("종합")로 요약 탭 다음에 두고, 탭 순서는 요약, 종합, 읽기 안내, 그림, 표, 레시피다. 기존 갤러리는 종합 탭으로 옮긴다.

## 8. 완료 게이트
서로 다른 유형의 논문 3편(실험, 이론, 시스템)으로 실측한다. 숫자는 구현 단계에서 측정해 채운다. 통과 조건:
- 5구획이 모두 채워진다(개념도 포함).
- 핵심 수치 버림 비율 30% 이하.
- 수식 KaTeX 실패 편당 1개 이하.
- 다이어그램 첫 렌더 성공 5/6 이상.
- 종합 스테이지 medium과 high를 같은 3편에 돌려 버림 비율과 수식 실패 수를 비교하고 effort를 확정한다.
- 사용자 시각 검토(복습 스캔과 타인 설명 두 상황).

실측(2026-09-06, POST 경로, OpenAI Luna): 3편(Flow Matching, GR00T N1, 지상-위성 업링크)에서 버림 0%, KaTeX 실패 0, 렌더 14/14, 핵심 수치 3/3/3, medium과 high 지표 동일이라 effort는 medium 확정. 옛 deep_dive 스키마 논문 2편은 구획 2가 숨겨져 5구획은 1/3만 충족(재분석으로 해결). 상세는 `RESEARCH/2026-09-06-synthesis-gate.md`.

## 9. 범위 밖
- 내보내기 산출물의 레이아웃(ZIP, HTML 노트, `formatPhaseAsMarkdown`에 종합 포함 여부).
- 표(Table) 썸네일 참조.
- 구획 사이 이동 UI(sticky 탭, 목차). 상한 6과 높이 제한으로 한 화면 반 이내를 목표로 하고, 넘치면 그때 다시 본다.
- Excalidraw 편집 캔버스(사용자가 다이어그램을 직접 고치는 기능).
- LLM이 Excalidraw JSON을 직접 생성하는 경로(자동 레이아웃이 없어 배제).
- 사용자 설정 항목 추가(설명 펼침 기본값 등).

## 10. 열린 결정(티켓)
- **Excalidraw 렌더 스타일 프로토타입**(HITL, 2026-09-06 해결): π0 논문 다이어그램 3개를 현재 Mermaid SVG와 mermaid-to-excalidraw 변환(roughness 0과 1)으로 나란히 그려 비교한 결과 **현재 Mermaid SVG 유지**로 결정. 요지: subgraph가 있으면 변환기가 이미지 폴백(mermaid 11.17 cluster id 접두사, issue #107)이라 dist 패치가 필요하고, linkStyle 색과 굵기가 소실되며, 한국어 레이블 폭 불일치로 단어 중간 줄바꿈이 생기고, 손그림은 글꼴 내장으로 SVG가 3배 커진다. ELK는 변환기에도 적용됨을 확인. 상세는 `.scratch/phase5-synthesis-view/issues/01-excalidraw-render-prototype.md`의 Answer.
- **Excalidraw 번들과 호환 조사**(AFK, 2026-09-06 해결): 결과는 `.scratch/phase5-synthesis-view/issues/02-excalidraw-bundle-compat-research.md`의 Answer. 요지: mermaid-to-excalidraw 2.2.2는 mermaid `^11.12.1`을 일반 dependency로 요구해 11.16과 semver 호환이고 classDef 색과 노드 모양과 subgraph와 sequence 요소는 보존되지만, linkStyle 엣지 색은 보존되지 않고 `<br/>` 줄바꿈 미변환 이슈가 열려 있다. `@excalidraw/utils`는 npm latest가 `0.1.3-test32` 프리릴리스이고 폰트와 dev 번들이 포함되어 압축 해제 95.9MB라 그대로 도입하기 어렵다. `@excalidraw/excalidraw` 0.18.1은 React 19 peer 호환이며 진입점 gzip 약 353KB다. 변환기가 자체 mermaid 인스턴스로 렌더하므로 ELK 레이아웃 적용 여부와 exportToSvg의 다크 모드 반전 여부는 미확인이다. 프로토타입 티켓 01은 이 결과를 전제로 진행한다.

## 관련 문서
- 용어집: `CONTEXT.md`(저장소 루트)
- wayfinder 지도: `.scratch/phase5-synthesis-view/map.md`
- UI 계약: `docs/superpowers/specs/2026-08-05-workbench-chip-unification-design.md`
- 읽기 안내 브리프: `docs/superpowers/specs/2026-09-05-reading-guide-design.md`(citationFocus 재사용 선례)
- 모델 레지스트리와 DEC-022: `sasoo/backend/services/model_registry.py`
