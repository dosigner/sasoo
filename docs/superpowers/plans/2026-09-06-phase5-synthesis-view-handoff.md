# 핸드오프: sasoo Phase 5 종합 뷰, 구현 완료 후 후속 4건과 커밋 분리

## 지금까지의 상태
2026-09-06 세션에서 종합 뷰(Synthesis View)를 스펙대로 구현하고 3편 게이트까지 통과시켰다. 코드는 **전부 미커밋**이다. git 최상위는 `/Users/dongj/dev/논문_사수_개발중`, 앱은 그 아래 `sasoo/`(백엔드 FastAPI, 프론트 React 19 + Vite 8 + Electron). 렌더러는 티켓 01로 현재 `MermaidRenderer` SVG 유지(Excalidraw 도입 안 함), 종합 뷰는 새 탭 "종합"(요약 다음), 종합 스테이지 role `synthesis`는 양쪽 열 effort medium 확정.

**작업 트리 주의.** 같은 날 07:44에 시작된 별도 "효율성 개선" 세션(`docs/superpowers/plans/2026-09-06-efficiency-implementation.md`, `.omo/evidence`)이 `sasoo/backend/api/analysis_routes.py`의 약 3,200줄을 새 미추적 파일 `sasoo/backend/services/analysis_execution.py`로 옮기고 `services/paper_library.py`를 지우는 등 미커밋 리팩터를 남겼다. 종합 스테이지 백엔드 코드는 그 새 파일 안에 있고, `frontend/src/components/VisualizationGallery.tsx`도 그 세션이 만든 미추적 파일이다. 어느 쪽도 되돌리지 말 것. 줄 번호 앵커는 리팩터로 이동했으니 함수 이름으로 grep 한다.

읽을 문서(내용은 여기서 반복하지 않는다):
- 스펙: `docs/superpowers/specs/2026-09-06-phase5-synthesis-view-design.md` (§4 라이트박스에 사용자 추가 결정, §7 자리 결정, §8 실측 요약)
- 구현 계획과 결과: `docs/superpowers/plans/2026-09-06-phase5-synthesis-view-implementation.md` (마지막 "결과" 절에 계획과 달라진 점과 후속 목록)
- 게이트 기록: `RESEARCH/2026-09-06-synthesis-gate.md`
- 용어집: `CONTEXT.md`(루트). wayfinder 지도와 티켓: `.scratch/phase5-synthesis-view/map.md`, `issues/01`, `issues/02`(둘 다 resolved)
- 프로젝트 메모리: `/Users/dongj/.claude/projects/-Users-dongj-dev----------/memory/sasoo-phase5-synthesis-view.md`
- 실기 확인 도구: `.scratch/phase5-synthesis-view/tools/`(`gate.py <effort> <paper_ids>`, `drive4.py <paper_id> <tag> [dark]`, `scrollshots.py <tag> [dark]`, 실측 결과 `gate-medium.json`과 `gate-high.json`). 출력 경로는 환경변수 `SYN_OUT`(기본 `/tmp`)

코드 위치(함수 이름으로 찾을 것):
- 백엔드: `services/analysis_execution.py`의 `_SYNTHESIS_SCHEMA`, `_SYNTHESIS_INSTRUCTION`, `_run_synthesis`, `_validate_synthesis`, `_normalize_viz_plan`, `_VIZ_PLAN_SCHEMA`; `api/analysis_routes.py`의 `get_synthesis`, `run_synthesis`(POST, `doc_text=body_text`, `use_cache=False`), `_synthesis_response`; `models/schemas.py`의 `SynthesisResponse`; `services/model_registry.py`의 `synthesis` role; 테스트 `services/test_synthesis.py`, `api/test_analysis_routes.py::SynthesisRouteTests`, `services/test_model_registry.py::TestSynthesisRole`
- 프론트: `src/components/synthesis/`(SynthesisView, blocks, DiagramCard, DiagramLightbox, EquationChain, FigureStrip), `src/lib/synthesisBlocks.ts`, `src/lib/api.ts`의 `getSynthesis`와 `runSynthesis`, `src/hooks/useAnalysis.ts`의 `synthesis`와 `refreshSynthesis`(시각화 조회보다 앞에 있어야 한다), `src/lib/strings.ts`의 `S.synthesis`, `AnalysisPanel.tsx`의 `synthesis` 탭과 `scrollToCitationAnchor`, `MermaidRenderer.tsx`의 `compact` prop, `VisualizationGallery.tsx`의 `useVisualizationActions` 훅과 `PaperBananaViewer` export

실기 환경(2026-09-06 기준):
- Electron 개발 앱이 `--remote-debugging-port=9222`로 떠 있으면 Playwright `connect_over_cdp('http://127.0.0.1:9222')`로 렌더러(`http://127.0.0.1:5173/#/workbench/<id>`)를 조작한다. 해시 이동 뒤 CDP `Page.reload {ignoreCache: true}`가 필요하다(Vite 캐시 때문에 React 사본이 이중 로드되는 증상).
- 백엔드(포트 8000)는 Electron의 자식이고 자동 리로드가 없다. 새 코드를 올리려면 `pgrep -f "main.py --host 127.0.0.1 --port 8000"`으로 찾아 SIGTERM을 보내면 Electron이 1초 뒤 같은 토큰으로 되살린다(진행 중 분석이 없을 때만). API 토큰은 그 프로세스 환경변수 `SASOO_API_TOKEN`에서 읽는다(`ps -wwE`). 출력에 다른 비밀 키가 섞이니 화면에 그대로 찍지 말 것.
- 개발 앱의 활성 DB는 `sasoo/backend/library/sasoo.db`다(App Support의 DB가 아니다). 게이트 3편은 999006(Flow Matching), 999005(GR00T N1), 999004(지상-위성 업링크).

## 이번 세션이 할 일 (순서대로)
1. **커밋 분리 방식 결정을 사용자에게 묻는다.** 종합 뷰 변경이 효율성 리팩터의 미추적 파일 안에 있으므로 (a) 리팩터와 함께 한 브랜치로 커밋, (b) 종합 뷰만 떼어 리팩터 없이 커밋(analysis_execution.py의 종합 부분을 analysis_routes.py로 되돌려 옮기는 작업 필요), (c) 리팩터를 먼저 커밋한 뒤 종합 뷰를 그 위에 커밋 중 하나. 권장은 (c). 커밋은 사용자가 명시적으로 요청할 때만 하고, `git log origin/main..main`으로 로컬 미푸시 커밋(d6cac62, 649120a, 16f176f, 68d712a 등)을 먼저 확인한다.
2. **개념도 재생성 버튼.** `DiagramCard`는 paperbanana 항목에 재생성 버튼을 숨긴다(`regenerate_visualization`이 mermaid 전용으로 거부). `generate_paperbanana`(POST `/{paper_id}/paperbanana`)의 입력 형식을 확인해 개념도 실패 자리의 "다시 생성"을 그 엔드포인트로 연결하고, `useVisualizationActions`에 핸들러 하나를 더한다. 스펙 §7의 "실패 자리는 제목, 오류 한 줄, 다시 생성"을 개념도에도 성립시키는 것이 목표.
3. **종합 다시 만들기 모달의 예상 비용.** `SynthesisResponse`에 `cost_usd`(analysis_results 행의 값)를 더하고, 모달 본문에 "지난 실행 $x.xxxx"를 기존 `buildAnalysisConfirmCopy` 문구 체계와 같은 어조로 보인다. 실측 단가는 medium 기준 편당 $0.005~0.013(본문 길이 비례).
4. **새 분석 파이프라인 경로의 게이트 실측.** 이번 게이트는 기존 논문용 POST 경로(체인 밖, 본문 텍스트 폴백)만 측정했다. 새 분석 1편(비용은 전체 분석 1회분이므로 실행 전 사용자에게 알린다)을 돌려 `_run_visualizations` 진입 직후 도는 종합 스테이지가 PDF 참조 경로에서도 버림 30% 이하와 수식 번호를 채우는지 `gate.py`의 지표로 확인하고 `RESEARCH/2026-09-06-synthesis-gate.md`에 절을 추가한다. 같은 실행으로 옛 deep_dive 스키마 논문(999005, 999004)의 구획 2(as_is와 to_be)가 채워지는지도 본다.
5. **라이트박스 DOM 테스트(선택).** jsdom이 없어 ESC 닫힘과 포커스 복귀, 방향키 이동 테스트를 못 넣었다. `jsdom`(또는 happy-dom) dev 의존성 추가는 사용자 승인 후에만 하고, 승인되면 `DiagramLightbox.test.tsx` 2건과 `SummaryBlock.test.tsx` 1건(타일 3개 초과 없음, 칩 클래스 없음)을 넣는다.
6. (선택) 렌더러 유지와 synthesis role medium 결정을 `docs/product-decisions.md`에 DEC 항목으로 남길지 사용자에게 묻는다. `_STAGE_SCHEMAS`는 참조가 없는 죽은 표라 정리 후보다.

## 지켜야 할 것
- 사용자 CLAUDE.md 규칙(한국어 설명, 엠대시와 중간점 금지, 커밋은 요청 시에만, 파괴적 명령 금지). 저장소 최상위는 sasoo가 아니라 논문_사수_개발중.
- 깨면 안 되는 계약: LLM 출력은 Mermaid 텍스트 고정이고 렌더러는 현재 SVG로 확정(Excalidraw 도입과 Excalidraw JSON 직접 생성 모두 금지), 핵심 수치는 칩이 아닌 타일, DEC-022(role별 프로바이더 오버라이드 없음), 스키마 마지막 속성은 숫자, 이모지 금지, 라이트박스는 워크벤치 전체 위 최상위 모달에 배경 블러.
- 스펙과 CONTEXT.md는 확장만 하고 덮어쓰지 않는다. 결정을 뒤집어야 하면 사용자에게 먼저 묻는다.
- 유료 모델 호출(새 분석, 종합 다시 만들기)은 비용을 먼저 알린다. 실기 확인은 사용자 데이터 논문으로 최소 횟수만.
- `useAnalysis`의 종합 조회를 시각화 블록 뒤로 옮기지 말 것(시각화 블록이 return으로 빠져나가 저장된 종합을 못 읽는다).

## 제안 스킬 (Skill 도구로 호출)
- `mattpocock-skills:diagnosing-bugs`: 게이트 실측에서 값이 이상하거나 렌더가 깨질 때 pass/fail 신호부터.
- `redesign-existing-projects`: 개념도 실패 자리와 모달 문구를 손볼 때.
- `mattpocock-skills:grilling`과 `mattpocock-skills:domain-modeling`: 커밋 분리 방식과 DEC 항목처럼 사용자 결정이 필요할 때.
- `code-review`: 커밋 전 종합 뷰 변경분 리뷰.

## 진행 상태 (2026-09-06 오후 세션)

- 2 개념도 재생성 완료, 3 모달 비용 완료. 상세는 구현 계획 문서의 "후속 세션" 절. 계획과 달리 `/paperbanana` 엔드포인트에 붙이지 않고 `regenerate_visualization`을 두 tool 공용으로 넓혔다(파이프라인과 같은 생성기, 프론트 핸들러 추가 없음).
- 사용자 결정(2026-09-06 오후): 1은 (c) 리팩터 먼저, 4는 새 분석 1편 승인, 5는 jsdom 추가, 6은 synthesis medium DEC 기록과 `_STAGE_SCHEMAS` 삭제(렌더러 유지 DEC는 제외).
- 1 완료: `0bdd12b` 리팩터 → `1a2b94a` 종합 뷰 → `7e3dddd` DOM 테스트(jsdom) → `60973ce` `_STAGE_SCHEMAS` 삭제. 전부 로컬 main, 미푸시. origin/main은 Renovate 3건이 앞서 있어 PR 전 rebase가 필요하다. 인용 정확도와 표 격자 흐름도 사용자 요청으로 이어서 커밋했다(표 `675123a`, 인용 `964ebf1`). 작업 트리의 추적 변경은 0이고 로컬 main은 origin/main보다 12커밋 앞선다.
- 5 완료: `DiagramLightbox.test.tsx` 2건, `SummaryBlock.test.tsx` 1건. 파일 상단 `@vitest-environment jsdom` 주석으로만 DOM 환경을 켠다.
- 6 완료: DEC-023 기록, `_STAGE_SCHEMAS` 삭제.
- 4: 999004(지상-위성 업링크)를 파이프라인 경로로 재분석했다. 결과는 `RESEARCH/2026-09-06-synthesis-gate.md`의 추가 절.
- 실기 확인 스크립트는 `~/.claude/jobs/277f3a92/tmp/verify.py`(잡 삭제 시 함께 사라진다). 필요하면 `.scratch/phase5-synthesis-view/tools/drive4.py`를 바탕으로 다시 쓴다.

