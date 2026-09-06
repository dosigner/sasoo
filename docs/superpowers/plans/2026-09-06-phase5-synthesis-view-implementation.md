# Phase 5 종합 뷰 구현 계획

스펙: `docs/superpowers/specs/2026-09-06-phase5-synthesis-view-design.md`(§5.3, §5.4 스키마, §7 상태, §8 게이트). 용어는 루트 `CONTEXT.md`. 렌더러는 티켓 01(2026-09-06)로 현재 `MermaidRenderer` SVG 확정, Excalidraw 도입 없음. 라이트박스는 사용자 추가 결정으로 PDF 뷰어와 분석 패널을 모두 덮는 최상위 모달에 배경 블러. 앵커의 줄 번호는 2026-09-06 작업 트리 기준이다.

## 확인한 접점

백엔드(`sasoo/backend`)
- 레지스트리 `services/model_registry.py`: `_REGISTRY` gemini 열 47-73, openai 열 74-93. `viz_planning` 60/83, `mermaid` 64/84(effort high). `_ROLE_PROVIDER_OVERRIDE` 125는 빈 dict(DEC-022). `services/test_model_registry.py:178 test_both_providers_cover_same_roles`가 두 열의 role 집합 일치를 잠근다.
- 체인 `services/analysis_execution.py`: `_PHASE_TO_ROLE` 1000-1005(phase→role 번역표). `_run_chain_stage` 1348(키워드 인자 `phase, prompt_chain, prompt_fallback, system_instruction, previous_interaction_id, pdf_uri, response_schema, restart_context, provider, doc_text, figure_parts`, Gemini 문서 참조와 OpenAI 본문 폴백 분기 1394-1416). `_plan_visualizations` 2261(프롬프트 2287-2303, 상한 2366, `viz_plan` 저장 2370). `_VIZ_PLAN_SCHEMA` 1209-1228(diagram_type과 category에 enum 없음, 마지막 필드 `category` 문자열). `_MERMAID_STYLE_RULES` 2090-2154(C절 mindmap 2129-2131). `_MERMAID_RENDERABLE_TYPES` 2392, 사용 2406. `_run_visualizations` 2545(`generate_one` 2604-2655, 진행 저장 `_store_visualization_progress` 2541, 호출 3013). 캐시 키 `_phase_cache_key` 224는 `_CHAIN_CACHE_VERSION`(221) + 모델 + effort + system_instruction + 프롬프트 본문이라 프롬프트가 바뀌면 키가 자동으로 바뀐다. 스키마만 바꾸고 프롬프트를 그대로 두는 경우에만 버전 문자열을 올린다.
- Phase 1 `_DEEP_DIVE_SCHEMA` 1104(`as_is` 1108, `to_be` 1109, `solution` 1110). 그림 `FigureInfo` `models/schemas.py:118`, 라우트 `api/analysis_routes.py:433`. 레시피 `RecipeParameter` `schemas.py:199`, phase 이름 `recipe`. `AnalysisPhase` enum 27-32에 viz_plan과 visualization은 없고 deep_dive 상태에 편승한다(2278 주석).
- 값 가드 `services/evidence_verifier.py`: `_numeric_tokens` 256, `check_value_in_quote` 266.
- 라우트: `GET /{paper_id}/visualizations` 584, regenerate 702, mermaid repair 648, paperbanana 862. ZIP은 백엔드 없음(프론트 `lib/vizExport.ts`).
- 테스트: `test_*.py`를 소스 옆에 두고 `backend/`에서 `python -m pytest services api models`. 현재 50개 파일.

프론트(`sasoo/frontend/src`)
- **Phase 5 탭은 없다.** `VisualizationGallery`(`components/VisualizationGallery.tsx:90`)는 `AnalysisPanel.tsx:930-937`에서 요약 탭 deep_dive `PhaseSection`의 children으로 인라인 렌더된다. `activeTab`은 `'summary' | 'guide' | 'figures' | 'tables' | 'recipe'` 5종(718). `CitationFocus`는 `tab: 'figures' | 'tables'`(70-76), 점프는 726-734.
- 상태: `hooks/useAnalysis.ts:78 visualizations`, deep_dive 완료 후 249-265에서 한 번 fetch.
- 라이트박스: `FigureGallery.tsx` 내부 함수 `Lightbox`(182~)가 `fixed inset-0 z-50`(299)과 배경 `bg-black/60 backdrop-blur-md`, `role="dialog"`(312), `hooks/useFocusTrap.ts`(ESC 38-41, Tab 순환, 닫힐 때 포커스 복귀 77-80). 방향키는 부모 705-715. 포털은 쓰지 않는다. `components/ui/Modal.tsx`는 Radix Dialog 포털이고 오버레이가 `bg-black/60 backdrop-blur-sm`. `prefers-reduced-transparency` 폴백은 `index.css` 1701~.
- 문구 `lib/strings.ts`: `S.mermaid` 741-770, `S.figures` 604, `S.recipe` 660. `S.visualization`은 없다.
- 타입 `lib/api.ts`: `MermaidDiagram` 267, `VisualizationItem` 275, `VisualizationPlan` 289, `Figure` 116(백엔드 `FigureInfo`), `Recipe.recipe`는 `Record<string, unknown>`(257), `AnalysisResults.deep_dive`도 비타입(112).
- 컨테이너 쿼리 사용처 없음. Tailwind v4(`@custom-variant` 사용)라 `@container`와 `@[560px]:` 변형을 플러그인 없이 쓸 수 있다. 스켈레톤은 `animate-pulse` 인라인 관례. `Markdown.tsx`는 remark-math와 rehype-katex(4-6행). 재분석 비용 모달은 `pages/Workbench.tsx:327`의 공용 `Modal`과 `lib/workbenchSummaries.ts:614 buildAnalysisConfirmCopy`. `AppIcon`은 `components/icons/AppIcon.tsx`(recipe=FlaskConical 123). vitest, `*.test.ts(x)` 소스 옆, 18개.

## 결정이 필요한 것 1건: 종합 뷰가 놓일 자리

스펙과 CONTEXT.md는 "Phase 5 탭"이라 부르지만 코드에는 그 탭이 없고 다이어그램은 요약 탭 안에 있다.
1. **새 탭 `synthesis`("종합")를 요약 다음에 둔다(권장).** 구획 2(as_is와 to_be)가 요약 탭의 deep_dive 본문과 한 화면에서 겹치지 않고, 그림 탭 점프와 레시피 탭 링크가 "다른 탭으로 간다"는 뜻 그대로 성립하며, 스펙의 "한 화면 반 이내"와 위치 기억이 지켜진다. 요약 탭의 인라인 갤러리는 새 탭으로 옮긴다.
2. 지금 자리(요약 탭 deep_dive 구역 안)에 종합 뷰를 인라인으로 둔다. 탭 하나가 매우 길어지고 구획 2가 바로 위 본문과 중복된다.

아래 계획은 1을 전제로 쓰고, 2가 선택되면 덩어리 D의 탭 배선 항목만 빠진다.

## 덩어리 A: 백엔드 레지스트리, 스키마, 프롬프트 (먼저)

수정
- `services/model_registry.py`: `synthesis` role을 gemini 열(`MODEL_FLASH_HQ`, effort `medium`)과 openai 열(`MODEL_LUNA`, effort `medium`)에 함께 추가. 오버라이드 표는 손대지 않는다.
- `services/analysis_execution.py`
  - `_PHASE_TO_ROLE`에 `"synthesis": "synthesis"`.
  - `_SYNTHESIS_SCHEMA` 신설(스펙 §5.3 그대로): `problem_sentence`, `method_sentence`, `key_metrics[{label, value, unit, evidence}]`, `equations[{latex, meaning, symbols[{symbol, meaning}], paper_number}]`, `result_figures[{figure_num, interpretation}]`, `key_parameters[{name}]`, 마지막 `equation_count` integer. 모든 객체의 required는 전체 필드. `maxItems`는 두되 화면과 검증이 다시 자른다.
  - `_VIZ_PLAN_SCHEMA` 개정(§5.4): `concept_illustration{title, description, category}`, `diagrams[{title, block enum(method|result), diagram_type enum(flowchart|sequence), description, category}]`, 마지막 `diagram_count` integer. 기존 `visualizations` 배열은 제거한다.
  - 기획 프롬프트(2287-2303) 개정: 개념도 1개 필수(이론 논문은 문제 설정 도식), 방법 다이어그램 절차 flowchart와 시간 순서 sequence 최대 3, 결과 다이어그램 비교 flowchart 최대 2, mindmap 삭제, 제목과 설명과 레이블에 이모지 금지.
  - `_MERMAID_RENDERABLE_TYPES = {"flowchart", "sequence"}`. `_MERMAID_STYLE_RULES` C절(2129-2131) 삭제, Mermaid 생성 프롬프트에 이모지 금지 한 줄.
  - 종합 프롬프트 상수 `_SYNTHESIS_INSTRUCTION`: 요약 문장 80자 안팎, 그림 해석과 수식 뜻 60자 안팎, 핵심 수치의 evidence는 논문 원문 한 문장 인용, 수식은 유도 순서, paper_number는 논문 표기 번호 또는 빈 문자열, result_figures는 제공한 그림 목록의 figure_num만, key_parameters는 제공한 이름 목록만, 이모지 금지.

테스트(`services/test_model_registry.py`, `services/test_analysis_execution.py` 또는 새 `services/test_synthesis.py`)
- synthesis role이 양쪽 열에 medium으로 있고 오버라이드 표가 비어 있다 1건.
- 두 스키마의 마지막 속성이 정수다 1건(DEC-014 잠금).
- `_MERMAID_RENDERABLE_TYPES`에 mindmap이 없고 mindmap을 넘기면 flowchart로 강제된다 1건.

## 덩어리 B: 백엔드 종합 스테이지, 기획 후처리, 라우트 (A 뒤)

새 코드(`services/analysis_execution.py`)
- `_run_synthesis(paper_id, previous_results, previous_interaction_id, pdf_uri, doc_text, provider, figures, recipe_result, status)`: `_plan_visualizations`(2261)와 같은 뼈대. 입력에 그림 목록(`figure_num`과 caption)과 레시피 `parameters[].name` 목록을 붙인다. `_run_chain_stage(phase="synthesis", response_schema=_SYNTHESIS_SCHEMA, ...)`. 캐시는 `_phase_cache_key`와 `_get_cached_phase_result(paper_id, "synthesis", ...)`. 결과는 `_validate_synthesis`를 거쳐 phase `synthesis`로 `_insert_analysis_result`. 저장 JSON에 `dropped: {key_metrics, result_figures, key_parameters}` 카운트를 함께 둔다(게이트 지표).
- `_validate_synthesis(data, doc_text, figure_nums, param_names) -> tuple[dict, dict]`: 순수 함수. key_metrics는 unit이 비었거나 `_numeric_tokens(value)`가 evidence의 토큰에 없거나 evidence의 토큰이 본문에 없으면 버린다(`evidence_verifier._numeric_tokens` 재사용). result_figures는 figure_num이 목록에 없으면 버린다. key_parameters는 name이 목록에 없으면 버린다. 상한(3, 5, 4, 5)을 자르고, 모든 문자열에서 이모지를 제거한다. 버린 개수를 `logger.info("synthesis.dropped ...")`로 남긴다.
- 기획 후처리 `_normalize_viz_plan(plan_data) -> list[dict]`: `concept_illustration`을 `tool="paperbanana", block="concept"` 항목으로 맨 앞에, `diagrams`를 `tool="mermaid"`로 이어 붙이되 result에 flowchart가 아닌 것은 버리고 method 3개와 result 2개 초과분을 자른다. 총 6개. `visualization` 항목 필드에 `block`을 더한다(`generate_one` 2606-2613).
- 실행 순서: `_run_visualizations`(2545) 진입 직후 `_run_synthesis`를 먼저 돌려 저장하고, 그 다음 기획과 다이어그램 생성(§7 "종합이 먼저 도착하면 뼈대를 그린다"). 종합 실패는 다이어그램 생성을 막지 않는다(로그 후 계속).
- 라우트(`api/analysis_routes.py`): `GET /{paper_id}/synthesis`(없으면 404), `POST /{paper_id}/synthesis`(종합 스테이지만 재실행, 다이어그램 유지. 컨텍스트 조립은 `regenerate_visualization` 702~의 방식을 따른다). 응답 모델 `SynthesisResponse`를 `models/schemas.py`에 추가하고 `VisualizationItem` 응답에 `block: str | None`.
- 비용: 종합 스테이지 비용은 `status.total_cost_usd`에 합산되고 `analysis_results.cost_usd`에 남는다. 예상 비용 문구는 프론트 덩어리 D에서 기존 체계로 만든다.

테스트(`services/test_synthesis.py`)
- `_validate_synthesis` 5건: 단위 없음 버림, value 수치가 evidence에 없음 버림, evidence 수치가 본문에 없음 버림, figure_num 불일치 버림, 파라미터 이름 불일치 버림. 상한 자르기와 이모지 제거 1건.
- `_normalize_viz_plan` 3건: result에 sequence가 오면 버림, method 4개면 3개, 개념도가 맨 앞.
- 라우트 2건(`api/test_analysis_routes.py`): GET 404와 200, POST가 종합만 다시 쓰고 visualization 행은 그대로.

## 덩어리 C: 프론트 데이터 계층 (B와 병렬 가능, 타입은 B의 응답 모델과 맞춘다)

수정
- `lib/api.ts`: `SynthesisResult`(스펙 §5.3 필드 + `dropped`), `VisualizationItem.block?: 'concept' | 'method' | 'result'`, `getSynthesis(paperId)`(404는 null), `runSynthesis(paperId)`.
- `hooks/useAnalysis.ts`: `synthesis` 상태. visualizations를 가져오는 자리(249-265)에서 같이 가져오고, `runSynthesis` 뒤 다시 가져오는 `refreshSynthesis`를 노출.
- `lib/strings.ts`: `S.synthesis`(구획 제목 5개, 헤더 동작 3개, 빈 상태와 실패 문구, "레시피 탭에서 전체 보기", "종합 뷰 만들기", "종합 다시 만들기", 예상 비용 문구).

새 파일
- `lib/synthesisBlocks.ts`: 순수 함수. `assignBlocks(items)`는 `block`이 없는 기존 논문 항목을 category로 배정(comparison은 result, 나머지 method, 첫 paperbanana는 concept)하고 상한(개념도 1, method 3, result 2)을 적용. `formatMetricValue`(값과 단위 한 셀), `pickReproRows(recipe, names)`(이름 일치 행만, 최대 5, notes 열 표시 여부).

테스트(vitest, 소스 옆): `synthesisBlocks.test.ts` 4건(배정, 상한, 이름 불일치 제거, notes 열 여부).

## 덩어리 D: 프론트 종합 뷰 (C 뒤). 스킬 `redesign-existing-projects`

새 파일(`components/synthesis/`)
- `SynthesisView.tsx`: 뷰 헤더(제목, muted 메타, 헤더 동작 3개: 전체 다운로드는 기존 `vizExport`, 설명 모두 펼치기 토글은 세션 상태, 종합 다시 만들기), 고정 순서 구획 5개. 종합 결과가 없으면 기존 `VisualizationGallery`를 그대로 그리고 상단에 "종합 뷰 만들기" 버튼(§7). 종합이 도착했고 다이어그램이 아직이면 구획 뼈대와 스켈레톤(개수는 기획 항목 수, `aria-busy`).
- `SummaryBlock.tsx`: 문제와 방법 문장 15~16px, line-clamp 2와 클릭 전체, 핵심 수치 타일 최대 3(큰 숫자와 단위, 작은 라벨, 배경 없음, 툴팁에 evidence). 칩 클래스는 쓰지 않는다.
- `ProblemBlock.tsx`: as_is와 to_be 2열, solution 한 줄, line-clamp 3. 루트에 `@container`, 열은 `grid-cols-1 @[560px]:grid-cols-2`. as_is와 to_be가 모두 비면 구획 자체를 숨긴다.
- `MethodBlock.tsx`: 개념도(`object-contain`, 호버 다운로드, 클릭 라이트박스) → `EquationChain` → `DiagramCard` 최대 3.
- `EquationChain.tsx`: 항목마다 display math 중앙, 우측 `(Eq. N)` muted, 아래 뜻 line-clamp 2, 기호표 접기(설명 모두 펼치기 토글을 따름). 렌더는 `katex.renderToString(latex, {displayMode: true, throwOnError: true})`를 try로 감싸고 실패 시 모노스페이스 원문. `aria-label`은 뜻. 긴 수식은 `overflow-x: auto`.
- `ResultBlock.tsx`: `FigureStrip`(높이 140px 고정, 너비 비율대로, 가로 스크롤, `Fig. N`과 해석 line-clamp 2, alt는 캡션, 클릭은 `onCitationFocus({tab: 'figures', anchor})` 재사용) → `DiagramCard` 최대 2.
- `ReproductionBlock.tsx`: 이름, 값+단위, 비고(하나라도 있을 때만) 표 최대 5행, "레시피 탭에서 전체 보기" 링크(`setActiveTab('recipe')`).
- `DiagramCard.tsx`: 다이어그램 위, 설명 아래 접기(2줄 초과분), 높이 상한 `max-h-[60vh]`에 맞춰 축소, 호버 시 우상단 아이콘 툴바(다운로드, 다시 생성), 클릭 라이트박스. 렌더는 `MermaidRenderer`의 `renderMermaidSvg` export를 쓰고 실패 시 자리 유지(제목, 오류 한 줄, 다시 생성 = 기존 `handleRegenerate`와 `makeRepairHandler`).
- `DiagramLightbox.tsx`: `createPortal(document.body)`로 워크벤치 전체 위, `fixed inset-0 z-50`, 배경 `bg-black/60 backdrop-blur-md`(FigureGallery와 같은 어휘, reduced-transparency 폴백은 기존 규칙이 받는다), `role="dialog"`와 `aria-modal`, `useFocusTrap`, 마우스 휠 줌과 드래그 팬(transform), 방향키로 같은 구획의 이전과 다음, 상단 제목과 툴바(코드 보기와 복사, 다운로드 SVG와 PNG, 다시 생성). 코드 탭은 여기서만. FigureGallery의 `Lightbox`는 이번에 옮기지 않는다(같은 규약만 공유).

수정
- `components/AnalysisPanel.tsx`: `activeTab`에 `'synthesis'` 추가, 탭 순서 요약, 종합, 읽기 안내, 그림, 표, 레시피. 930-937의 인라인 `VisualizationGallery`를 종합 탭의 `SynthesisView`로 옮긴다. `CitationFocus.tab`은 그대로.
- `pages/Workbench.tsx`: `synthesis`와 `refreshSynthesis` 전달, 종합 다시 만들기 확인 모달은 327의 `Modal`과 같은 방식으로 `buildSynthesisConfirmCopy`(`lib/workbenchSummaries.ts`) 문구.
- `components/MermaidRenderer.tsx`: 카드용으로 툴바를 숨기는 prop 하나(`compact`). 렌더 사다리는 손대지 않는다.

테스트(vitest): `EquationChain.test.tsx` 2건(정상 렌더, 실패 시 모노스페이스 폴백), `DiagramLightbox.test.tsx` 2건(ESC 닫힘과 포커스 복귀, 방향키 이동), `SummaryBlock.test.tsx` 1건(타일 3개 초과 없음, 칩 클래스 없음).

## 덩어리 E: 3편 실측 게이트 (D 뒤, 스펙 §8)

- 논문 3편: 시스템(π0, paper_id 11), 이론(Flow Matching, paper_id 13), 실험 1편(라이브러리에서 고른다). 각 편에 종합 뷰 만들기 1회를 medium으로, 같은 3편을 high로 한 번 더(비용은 실행 전 사용자에게 알린다).
- 측정: 5구획 충족 여부(개념도 포함), 핵심 수치 버림 비율(`dropped.key_metrics / 원래 개수`, 30% 이하), 수식 KaTeX 실패 편당 1개 이하, 다이어그램 첫 렌더 성공 5/6 이상. 기록은 `RESEARCH/2026-09-0X-synthesis-gate.md`(편별 표, effort 비교, 비용).
- effort 확정 후 레지스트리의 synthesis effort를 고정하고, 프롬프트 문구(길이, 인용 형식)를 다듬는다.
- 사용자 시각 검토: 복습 스캔과 타인 설명 두 상황, 다크와 라이트, CDP 캡처(reload는 ignoreCache).

## 검증

덩어리마다: 백엔드 `cd sasoo/backend && python -m pytest services api models`, 프론트 `npx tsc --noEmit -p tsconfig.json`, `pnpm test`, `pnpm lint`. D 끝에 `pnpm build`. 실기는 E에서만.

## 역할 분담과 모델

| 덩어리 | 담당 | 모델 |
|---|---|---|
| A 레지스트리와 상수 | fast-worker | sonnet |
| A 스키마와 프롬프트 문구, B 검증 함수와 후처리와 스테이지 | deep-reasoner | opus |
| C 타입과 훅과 문구 | fast-worker | sonnet |
| D 구획 컴포넌트 골격 | fast-worker(기계적 부분) + 오케스트레이터(라이트박스, 수식 체인, 배치) | sonnet |
| E 게이트 실측과 판단 | 오케스트레이터 | n/a |

커밋과 푸시는 하지 않는다. 작업 트리의 기존 미커밋 변경(인용 분석 수정, 디자인 9단계 등)은 건드리지 않는다.

## 결과 (2026-09-06, 전부 미커밋)

- A, B, C, D, E 모두 완료. 백엔드 `python -m pytest services api models` 874 통과, 프론트 tsc와 lint와 vitest 198 통과, `pnpm build` 통과.
- 계획과 달라진 것:
  - `_run_synthesis`는 검증용 본문을 `body_text`로 따로 받는다. Gemini 체인에서는 `doc_text`가 비어 있어 evidence 본문 검증이 무력화되기 때문이다. POST 경로는 캐시를 쓰지 않는다(다시 만들기가 같은 결과를 돌려주지 않게).
  - POST 경로에 `doc_text=body_text`를 추가했다. 본문 없이 돌린 첫 실측에서 핵심 수치 0개와 수식 번호 0/5가 나왔고, 본문을 넣자 3개와 5/5가 됐다.
  - `useAnalysis`의 종합 조회를 시각화 조회 앞으로 옮겼다. 시각화 블록이 항목을 받으면 `return`으로 빠져나가 저장된 종합이 영영 읽히지 않았다.
  - 컴포넌트 DOM 테스트(라이트박스 ESC와 포커스 복귀, 요약 타일)는 jsdom이 없어 넣지 않았고, 순수 함수(`renderEquation`, `problemFields`)만 테스트했다. 실기 확인은 CDP로 대신했다.
  - FigureGallery의 Lightbox는 옮기지 않고 `DiagramLightbox`를 body 포털로 새로 만들었다(같은 배경 어휘와 `useFocusTrap` 공유).
  - `MermaidRenderer`에 `compact` prop, `VisualizationGallery`에서 `useVisualizationActions` 훅과 `PaperBananaViewer` export.
- 게이트 기록: `RESEARCH/2026-09-06-synthesis-gate.md`. effort는 medium 확정.
- 남은 후속: 개념도(paperbanana) 재생성 버튼(regenerate 엔드포인트가 mermaid 전용), 종합 다시 만들기 모달의 비용 수치(응답에 cost 없음), 옛 deep_dive 스키마 논문의 구획 2(재분석으로 해결), 새 분석 파이프라인 경로의 게이트 실측, `_STAGE_SCHEMAS` 죽은 표 정리, Vite 개발 서버에서 새 의존성(katex 직접 import) 뒤 캐시 무시 새로고침 필요.

### 후속 세션 (2026-09-06 오후, 미커밋)

- 개념도 재생성 완료. 별도 `/paperbanana` 엔드포인트(분석 요약 이미지, 다른 기능)에 붙이지 않고 `regenerate_visualization`이 `tool=paperbanana`도 받게 했다. 파이프라인과 같은 `_generate_single_paperbanana`를 부르고 실패는 502로 돌려주며 저장 행은 건드리지 않는다(mermaid 경로와 대칭). 프론트는 `DiagramCard`의 `!isConcept` 가드 두 곳만 풀었고 `useVisualizationActions`의 기존 `handleRegenerate`가 그대로 쓰인다. 테스트 `MermaidRepairAndRegenerateTests` 3건(개념도 성공과 저장, 실패 502와 미저장, 알 수 없는 tool 400).
- 종합 다시 만들기 모달 비용 완료. `SynthesisResponse.cost_usd`(analysis_results 행 값)를 더하고, 모달에 분석 확인 모달과 같은 강조색 한 줄로 "지난 실행에는 $x.xxxx 들었어요. 이번에도 비슷하게 들어요."를 보인다. 값이 없거나 0이면 medium 실측 범위($0.005 ~ $0.013)로 말한다. 숫자 뒤 조사는 끝소리에 따라 갈려서 조사 없이 잇는다.
- 검증: 백엔드 876 통과, tsc와 eslint와 vitest 198 통과. 실기(999006, CDP): 카드 5개 모두 헤더 재생성 버튼, 모달 문구 "$0.0113"(DB 0.0113278), 취소로 닫힘, 콘솔 오류 0. 개념도 재생성 자체는 유료 호출이라 실기로 누르지 않았다.
- 커밋 완료(로컬 main, 미푸시, 2026-09-06 오후): 리팩터 `0bdd12b`(효율성 세션 10개 항목, 종합 뷰와 인용 수정을 뺀 상태로 검증 820 통과) → 종합 뷰 `1a2b94a`(백엔드 843, vitest 198) → DOM 테스트와 jsdom `7e3dddd`(vitest 201) → `_STAGE_SCHEMAS` 삭제 `60973ce`. 층 분리는 현재 파일에서 다른 흐름의 코드를 걷어낸 내용을 `git hash-object`로 인덱스에 올려 만들었고, 커밋마다 임시 워크트리에서 백엔드 pytest와 tsc, vitest, eslint를 돌렸다. `VisualizationGallery.tsx`의 `useVisualizationActions` 훅 추출은 리팩터 커밋에 넣었다(종합 세션이 한 일이지만 갤러리 추출의 일부로 읽힌다).
- 이어서 따로 커밋한 흐름(사용자 요청, 표 `675123a` → 인용 `964ebf1`, 각각 백엔드 846과 876 통과): 인용 정확도 수정(09-05, `citation_analyzer.py`, `test_citation_analyzer.py`, `analysis_execution.py`의 `_select_citation_top_refs`와 `_norm_ref_id`, `test_analysis_routes.py`의 `CitationTopRefFilterTests`, `provider_compare.py`의 상위 N 문구)과 표 격자 수정(09-01, `table_resolver.py`, `test_resolver_pipeline.py`, `measure.py`). 작업 트리의 추적 변경은 0이다.
- DEC-023(synthesis medium 확정)을 `docs/product-decisions.md`에 기록했다(로컬).
- 파이프라인 경로 게이트 완료(999004 재분석, $0.09, 340초): 버림 0, KaTeX 실패 0, 렌더 6/6, 구획 5/5(as_is와 to_be 채워짐). `RESEARCH/2026-09-06-synthesis-gate.md` 추가 절. 남은 후속: 렌더러 유지 결정의 DEC 기록 여부(사용자가 이번에는 제외), `/status` total_cost_usd가 종합과 시각화 비용을 빼는 문제의 처리 여부.

