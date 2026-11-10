# Sasoo 전체 모듈 리팩토링 통합 계획

**목표:** 제품 동작, 사용자 데이터, 비용 기록을 보존하면서 6개 영역의 책임 경계를 단계별로 정리합니다. 이 문서는 계획과 검증 전략입니다. 이번 작업에서 제품 코드는 수정하지 않았습니다.

**작성 방법:** 2026-11-09에 6개 subagent(deep-reasoner, 읽기 전용)가 영역별로 정적 조사를 했습니다. 총괄 에이전트가 영역 사이에 걸친 핵심 근거를 실제 코드로 다시 확인했습니다(근거 기록: `docs/validation/2026-11-09-modular-refactor-master-plan-evidence.md`). 테스트, 앱, 빌드, 공급사 호출, migration은 실행하지 않았습니다. 실제 사용자 DB, 라이브러리, `backend/.env` 내용은 열지 않았습니다.

**기준선:** 모든 행 번호는 2026-11-09 현재 **작업 트리** 기준입니다. HEAD(3d0e7d2) 기준이 아닙니다. 아래 1.3을 보세요.

**관련 문서:** `2026-11-09-sasoo-module-refactor-agent-review.md`, `2026-11-09-sasoo-refactor-evidence-review.md`, `2026-11-09-execution-provenance-verification-cost.md`, `docs/validation/2026-11-09-{provenance-cost-partial-investigation, manifest-store-partial-implementation, refactor-approved-abc-validation, es2022-promise-build-verification}.md`.

---

## 1. 조사 결과와 범위

### 1.1 조사한 모듈과 진입점

| 영역 | 조사한 진입점과 모듈 |
|---|---|
| 1 실행과 worker | `run_full_analysis`(analysis_execution.py:3816-4214), worker(`analysis_worker.py:52-90`), supervisor(`analysis_supervisor.py:171-365`), 결과 저장 헬퍼(458-496, 3097-3212), `analysis_completion.py`, `analysis_manifest_store.py`, 테스트와 tools의 patch 전수 |
| 2 API, DB, 설정 | `main.py` lifespan, 토큰 middleware(218-273), route 39개, `/status` 투영(analysis_routes.py:291-418), settings와 credential, `models/database.py` migration(411-561) |
| 3 파서와 증거 | `ensure_text_artifacts`(odl_parser.py:1373), `ensure_visual_artifacts`(1451), artifact task(1970-2074), figure/table sync(1715-1918), `document_context._build_phase_inputs`(363-446), evidence_repo, evidence_verifier |
| 4 프런트엔드 | App 라우팅(App.tsx:103), Workbench 상태 소유권, `useAnalysis` polling, `useWorkbenchAnalysisControls`, PdfViewer 수명, FigureGallery 자동 설명, MermaidRenderer repair, api.ts 요청 공유 |
| 5 Electron과 빌드 | IPC 11채널, PythonManager health와 재시작, stopper, quit handler, updater, scripts의 삭제 경로, PyInstaller spec, CI 2종 |
| 6 공급사와 비용 | `interactions_client` 라우팅, gemini/openai client 재시도와 usage, `model_registry`, `pricing`, 프롬프트 결합 지점, agent profile 우선순위, tools와 backend/scripts |

### 1.2 조사하지 못한 범위

1. 외부 HTTP, Python, TypeScript 소비자와 개인 스크립트의 import.
2. 실제 사용자 DB와 라이브러리의 레거시 데이터 분포(과거 `planned_items` 부재 행 수, sidecar 버전 분포).
3. SDK 내부 재시도의 정확한 의미. google-genai Interactions의 `max_retries=3`이 총 시도인지 재시도 횟수인지 확인하지 못했습니다.
4. 패키징된 앱의 asar 내용, jsonschema metaschema 번들 여부, Windows 실기, Linux 빌드.
5. 실행 중 동작 전부. 모든 결함 후보는 정적 분석이며 재현하지 않았습니다.
6. 영역별로 깊이 읽지 않은 내부: `_run_chain_stage`와 `_run_deep_dive` 분기, `gemini_parser`, `document_manifest`, 후보 휴리스틱, experiment-plan 내부, Electron 테스트 본문.

### 1.3 이전 문서와 현재 코드가 다른 지점

1. **병렬 실행과 완료 계약은 HEAD에 없습니다.** `_run_parallel`, `_completion_checks`, `planned_items`, `_run_visualization_items`는 HEAD에서 0건, 작업 트리에서 각각 3, 4, 3, 2건입니다(총괄 확인). `analysis_execution.py`는 HEAD 4033줄, 작업 트리 4214줄입니다. 이전 문서는 이 구조를 현재 동작으로 서술했습니다.
2. **미추적 모듈에 tracked 파일이 의존합니다.** `analysis_completion`, `chat_context`, `selection_context`를 수정된 tracked 파일이 import합니다(analysis_routes.py:66,69,70, analysis_execution.py:22, document_context.py:226). 일부만 커밋하면 CI와 패키징이 import 단계에서 실패합니다.
3. **`/status`의 의미가 바뀌었습니다.** 미커밋 diff에서 매 poll마다 완료 검사를 실행합니다. `planned_items`가 없는 과거 시각화 행은 `overall=error`, 진행률 99로 판정됩니다(analysis_completion.py:126-128, 테스트 test_analysis_routes.py:4431-4433). `papers.status`는 DB에서 `completed`로 남아 화면마다 상태가 다를 수 있습니다.
4. **Gemini SDK 내부 재시도가 있습니다.** 이전 문서는 "확인하지 못함"이었습니다. 영역 6이 google-genai 2.21.0 Interactions 기본 `max_retries=3`을 확인했습니다. OpenAI는 제품 기본 경로에서 SDK `DEFAULT_MAX_RETRIES=2`가 살아 있습니다(`single_attempt`일 때만 0, openai_client.py:282,346).
5. **늦은 getSettings 우려는 현재 도달할 수 없습니다.** hook 수준에서는 성립하지만 `App.tsx:103`의 `key={location.pathname}`가 논문 전환마다 Workbench를 다시 마운트합니다(총괄 확인).
6. **`requestEfficiency.test.js`는 frontend vitest에서만 실행됩니다.** 루트 include가 `*.test.{ts,tsx}`입니다.
7. **AGENTS.md와 CI는 6곳이 다릅니다.** Node 20과 실제 24, Windows release venv, asset 교체 문구, frozen lockfile, `pnpm start`의 의미, `vite-env.d.ts` 경로(`frontend/vite-env.d.ts`)입니다.
8. **이전 문서에 없던 결함 후보가 있습니다.** 아래 2.3에 모았습니다.

---

## 2. 현재 시스템의 책임과 데이터 흐름

### 2.1 흐름도

실선은 코드에서 확인한 연결입니다. 점선은 추론한 연결입니다.

```mermaid
flowchart TB
  subgraph Renderer
    WB[Workbench + useAnalysis<br/>2s polling] -->|POST /run| RUN
    WB -->|GET /status| ST
    FG[FigureGallery 자동 설명] -->|POST explain/stream 유료| FX
    MR[MermaidRenderer 자동 repair] -->|POST mermaid/repair 유료| MX
  end
  subgraph Electron main
    PM[PythonManager<br/>토큰 2종 생성, HMAC health] -->|spawn env SASOO_API_TOKEN| API
    IPC[IPC 11채널] -->|backend:getAuthToken, getAssetToken| WB
  end
  subgraph FastAPI process
    API[main.py middleware] --> RUN[/run]
    RUN -->|subprocess 모드| SUP[supervisor claim_next generation+1]
    RUN -->|in-process 모드| RFA
    ST[/status 투영] --> CC[analysis_completion 7 checks]
    UP[upload] -->|schedule| ART1[artifact task<br/>프로세스 전역 dict]
  end
  subgraph Worker process
    SUP -->|spawn --analyze-paper| WK[worker heartbeat fence]
    WK -->|generation 전달 안 함| RFA[run_full_analysis]
    RFA -->|조건 없이 schedule| ART2[artifact task<br/>별도 dict]
    RFA --> LLM[interactions_client]
    RFA --> SAVE[_insert_analysis_result<br/>문장별 commit, fence 없음]
  end
  ART1 & ART2 --> FS[(paper_dir 파일<br/>manifest, figures, sidecar)]
  ART1 & ART2 --> DB
  SAVE --> DB[(SQLite analysis_results<br/>cost_usd REAL)]
  LLM -->|gpt- 접두사| OAI[openai_client 서비스 3회 x SDK 2회]
  LLM -->|그 외| GEM[gemini_client 서비스 3회 x SDK 기본]
  DB --> ST
  DB --> COST[settings /cost, supervisor 예산<br/>analysis_results만 읽음]
  ART1 -.->|서로 보지 못함, 중복 추출 추론| ART2
```

### 2.2 흐름별 요약

| 흐름 | 확인한 경로 | 핵심 계약 |
|---|---|---|
| 화면에서 분석 요청 | `useWorkbenchAnalysisControls.ts:51-73` 자동 시작 또는 확인 모달 → `api.runAnalysis` → `POST /run`(analysis_routes.py:146, 202) | 자동 시작은 `pending`이고 실행 중이 아닐 때 1회 |
| API에서 실행까지 | subprocess 모드는 `upsert_queued` → `reconcile_once` → `claim_next` → worker → `run_full_analysis(paper_id)`. in-process 모드는 `background_tasks.add_task`(244) | 프로세스 분리 6계약(fence, 원자 claim, 사이드카, close_db, 플래그 게이팅, phase 무수정) |
| PDF, 캐시, DB | text 단계 → sidecar `.document_context.json` → 단계 입력 9종 → `_phase_cache_key` → 결과 행 INSERT. visual 단계는 별도 task, manifest 기록 후 figures commit, tables commit, visual_parse INSERT | 단계 입력 바이트가 캐시 키. 1바이트 변화는 유료 재호출 |
| 시각화와 공급사 | `_plan_visualizations` → `_gate_viz_items` → 계획 checkpoint → mermaid/html 병렬, paperbanana 순차 2초 간격 → collector CAS checkpoint | 상한 이미지 5, Mermaid 3, HTML 1, Sunburst 1. 캐시 정책 문자열 `images-124-sequence-3-html-5-v2-sunburst` |
| 상태와 비용 표시 | `/status`가 DB 행 8종 + `_completion_checks` + live status + run 행을 합칩니다. 라이브 비용은 `total_cost_usd += cost or 0.0`(14곳). 월별 비용은 `analysis_results`만 읽습니다 | 99% 상한, cancel 우선, unknown은 0으로 바꾸지 않음(복원 경로) |
| Electron과 백엔드 | PythonManager가 기동마다 api와 shutdown 토큰 생성 → health `instance_proof` HMAC → 30초 주기, 1회 실패 시 재시작 → 종료는 `/shutdown`, SIGTERM, SIGKILL 순 | 상수 `sasoo-health-v1`, `sasoo-asset-v1:`, 헤더 이름은 TS와 Python이 공유 |

### 2.3 이번 조사에서 새로 찾은 결함 후보

모두 정적 분석이며 재현하지 않았습니다. 리팩토링 과제가 아니라 별도 동작 수정 과제입니다.

| ID | 영역 | 관찰한 사실 | 영향 | 비용이나 데이터 |
|---|---|---|---|---|
| D1 | 3 | worker가 `schedule_paper_artifacts_refresh`를 조건 없이 호출(analysis_execution.py:3865). 작업 등록부는 프로세스 전역 dict(odl_parser.py:68). 업로드도 호출(papers.py:281). 총괄 확인 | 업로드 직후 분석하면 시각 추출이 두 프로세스에서 실행될 수 있음 | Gemini 비전 중복 결제, 같은 디렉터리 파일 경합 |
| D2 | 3 | manifest `ready` 기록(odl_parser.py:1583)이 DB sync(1986-1987)보다 먼저 | sync 실패 시 재동기화가 다시 일어나지 않음 | figures 행이 예전 상태로 남음 |
| D3 | 3 | visual_parse 사용량이 성공 manifest로만 상위 전달. 엔진 전부 실패, resolver 예외, sync 예외 경로에서 누락. resolver와 naming의 VLM 호출은 사용량을 버림 | 지출 기록 누락 | 비용 과소 집계 |
| D4 | 3 | 재시도 패스가 `seen_figure_nums`를 새로 만듦(figure_resolver.py:545-548) | 같은 번호의 그림 파일 덮어쓰기 | 그림 설명이 다른 행에 붙거나 삭제 |
| D5 | 1, 2 | 결과 쓰기에 generation fence 없음. `execute_insert`는 공유 연결에서 문장별 commit(database.py:624-637) | 절전 복귀 뒤 오래된 worker가 최신 행을 덮을 수 있음 | 결과 출처 혼합 |
| D6 | 2, 6 | 월 키를 `utcnow() - timedelta(days=30*i)`로 계산(settings.py:467). 총괄 확인 | 31일 기준 등에서 한 달이 두 번, 한 달이 빠짐 | 월별 비용 표시 오류 |
| D7 | 6 | Gemini usage 누락을 `or 0`으로 대체(gemini_client.py:203-207). 총괄 확인. 채팅은 이 값을 `complete`, $0으로 저장 | 미확인 비용이 0원으로 기록 | 비용 과소 집계 |
| D8 | 6 | 월별 비용과 예산이 `analysis_results`만 읽음. 채팅, 실험 계획, 그림 설명, resolver, naming 비용 제외 | 예산 가드가 실제보다 적게 계산 | 예산 초과 가능 |
| D9 | 6 | 스크리닝 캐시 키는 `system_instruction=""`(analysis_execution.py:695-697), 실제 호출은 기본 지시문 사용. 미커밋 diff가 지시문을 바꿈 | 지시문을 바꿔도 스크리닝 캐시가 갱신되지 않음 | 예전 지시문 결과 재사용 |
| D10 | 4 | polling 정지 조건이 completed와 error뿐(useAnalysis.ts:341). 총괄 확인 | 취소 뒤 2초 GET 계속 | 무료 요청 증가 |
| D11 | 4 | repair 시도 기록이 컴포넌트 ref(MermaidRenderer.tsx:335). 총괄 확인. 종합 탭은 조건부 마운트 | 탭 재진입마다 유료 repair 재요청 가능 | 유료 호출 반복 |
| D12 | 2 | 미커밋 regenerate 경로의 `load_pdf_part`가 `try` 밖(analysis_routes.py:892-899) | 실패 시 지출 기록을 거치지 않고 500 | 오류 처리 누락 |
| D13 | 2, 1 | `POST /synthesis`에 실행 중 가드와 예산 확인 없음(1003-1061) | worker와 동시 저장 | 예산 우회 |
| D14 | 5 | updater가 첫 창을 고정(updater.ts:8,12). macOS `activate`가 기동 대기 중 창 생성 가능(main.ts:306) | 새 창에 업데이트 배너 없음, 이중 창 | 없음 |
| D15 | 2, 3 | 논문 DELETE가 `analysis_results`와 `discussion_messages`를 지움(papers.py:505-516, discussion.py:106) | 지출 이력이 집계에서 사라짐 | 비용 이력 손실. 원장 설계에서 결정 |
| D16 | 6 | 테스트에 네트워크 차단 없음. `services/conftest.py`만 있고 socket 가드 없음. `backend/.env` 존재, `main.py:77-79`가 로드. 총괄 확인 | 호출 지점을 옮기면 문자열 patch가 빗나가 실제 호출로 나갈 수 있음 | 유료 호출 사고 가능성 |

---

## 3. 모듈별 리팩토링 후보

"동작 변경"은 값, 요청 수, 화면 문구 중 하나라도 바뀌는 작업입니다. 이 표에는 리팩토링 후보만 넣었습니다. 동작 변경은 6절과 4.5에 있습니다.

| ID | 영역 | 현재 근거와 문제 | 변경 단위 | 보존할 계약 | 위험도 | 선행 테스트 |
|---|---|---|---|---|---|---|
| R0 | 공통 | D16. 테스트가 실제 네트워크로 나갈 수 있음 | `backend/conftest.py`에 autouse socket 가드(loopback 허용) 추가. 테스트 지원 코드만 | 기존 테스트 통과 수, 로컬 HTTP 서버를 쓰는 테스트 | 낮음 | 가드가 외부 connect를 실제로 막는지 양성 대조 테스트 1건 |
| R1 | 2 | `get_report`(analysis_routes.py:1083-1154)가 조회와 Markdown 조립을 섞음 | 조립만 `report_service.build_report_markdown`로 이동 | 404 두 종류, 단계 순서, "미확인" 문구, 합계 서식, 응답 바이트 | 낮음 | 합성 행(legacy, partial, None 비용)으로 응답 바이트 스냅샷 |
| R2 | 2 | HTTP 계약 고정 장치가 없음(OpenAPI 스냅샷 0건) | 테스트만 추가: route 목록, `app.openapi()` 스냅샷, 401과 CORS 현재 동작 기록 | 39 route, `/static/library`, `/shutdown` | 낮음 | 없음(이 작업 자체가 고정) |
| R3 | 1 | 시각화 계획 정책이 실행 파일 안에 있음(analysis_execution.py:2567-2681, 2851) | 순수 함수 5종과 상수를 새 모듈로 옮기고 `ae`에서 재노출. 호출자는 `ae`에 유지 | 항목 순서, 상한, 60/70점 경계, 캐시 정책 문자열, `image_model` | 낮음 | legacy, NaN, bool, 문자열 점수, 중복 core의 입출력 스냅샷 |
| R4 | 1 | Mermaid 정리(2462-2565), 인용 선택(804-880), 종합 검증(3246-3356)이 같은 파일 | R3과 같은 방식으로 한 묶음씩 이동. 프롬프트 상수 `_MERMAID_*_RULES`는 제외 | 출력 바이트, `_citation_cache_key` 바이트, `patch.object(ae, "_select_citation_top_refs")` 2곳 | 낮음 | 묶음별 출력 바이트 스냅샷 |
| R5 | 1, 2 | completion이 문자열 `getattr`로 schema를 읽음(analysis_completion.py:86-88), 숫자 인덱스 의존(146-150) | schema 7종을 새 모듈로 옮겨 순환 제거. 인덱스를 stage 이름 조회로 교체. `ae._*_SCHEMA` 재노출 | schema 내용(공급사로 가는 JSON), `/status`, 캐시 hit 경로 | 중간 | schema `json.dumps(sort_keys)` 해시, `test_analysis_completion.py`, `test_deep_dive_schema.py` |
| R6 | 2 | `/status` 투영이 I/O와 계산을 섞음(291-418) | 순수 `project_status(...)` 추출. I/O는 route에 남김 | 응답 필드, 99% 상한, `analyzing` 통과, cancel 우선, poll당 SQL과 키체인 호출 수 | 중간 | `ParallelProgressTests`, finalization 테스트, 호출 수 계측 |
| R7 | 3 | 시각 엔진 시도 루프가 함수 안에 인라인(odl_parser.py:1509-1562) | `_convert_visual_with_fallback`로 추출 | 엔진 순서, 재시도 전 rmtree, 사용량 채널 finally, patch 문자열 `_run_convert` 등 | 낮음 | `test_odl_parser.py`, `test_odl_java_runtime.py`, `test_visual_parse_usage.py` |
| R8 | 3 | 단계 입력 바이트 고정 장치가 없음 | 테스트만 추가: `_build_phase_inputs` 9키 sha256, sidecar 재사용, fake 엔진 파일 목록과 바이트, 설명 보존, 장애 주입 4종의 현재 동작 | 단계 입력 바이트 = 캐시 키 | 낮음 | 없음(이 작업 자체가 고정) |
| R9 | 3 | `odl_parser.py` 2143줄에 task, DB sync, API 변환이 함께 있음 | `visual_db_sync`, `api_dict` 분리. `_refresh_paper_artifacts`는 원 모듈 유지 | patch 문자열 `services.odl_parser.sync_*` 등, `quality_compare.py:264` 속성 대입 | 중간 | R8 완료. 테스트 수정 없이 통과해야 함 |
| R10 | 4 | AnalysisPanel 포맷 함수가 컴포넌트 파일에 비공개로 있음(395-684) | `lib/analysisFormat.ts`로 순수 이동. JSX와 상태 제외 | 화면 텍스트, `[object Object]` 같은 현재 출력도 그대로 | 중간 | 현재 출력 snapshot, `AnalysisPanel.reading.dom.test.tsx` |
| R11 | 4 | api.ts에 타입 48개와 함수 34개가 혼재 | 타입만 이동하고 api.ts에서 재수출 | import 경로, `vi.mock('@/lib/api')` 9개 테스트 | 낮음 | `pnpm tsc --noEmit`, 두 vitest 경로 |
| R12 | 4 | controls hook에 논문 ID 대조와 테스트가 없음(useWorkbenchAnalysisControls.ts:51-79) | `.then`에서 latest paperId ref 대조. 현재 도달 불가 결함의 방어 | 정상 자동 시작 1회, 실패 시 모달 | 낮음 | 4.4의 모의 지연 테스트 |
| R13 | 5 | IPC 핸들러가 main.ts 클로저라 테스트 불가(149-237) | `electron/ipc-handlers.ts`로 의존성 주입 추출. updater IPC 제외 | 채널 11개 문자열, sendSync, 응답 모양, 기존 발신자 검증 3채널 | 낮음 | 채널 목록과 preload 대조, asset path 허용/거부 표, HMAC 벡터 |
| R14 | 6 | `openai_client.py:30`이 `_SYSTEM_INSTRUCTION_KO`를 gemini_client에서 import | 중립 모듈로 이동, 양쪽 재노출 | 지시문 바이트, `test_analysis_routes.py:3809-3810` 동일 객체 검사 | 낮음 | 지시문 sha256 고정 |
| R15 | 2, 5, 6 | TS와 Python이 HMAC 상수를 각자 가짐 | 테스트만 추가: 교차 언어 고정 벡터 | 상수 3종 | 낮음 | 없음 |

### 3.1 지금 분리하지 않을 영역

1. `run_full_analysis` 분해와 단계 함수(`_run_*`) 이동. 테스트가 `ae` 전역 patch로 단계를 바꿔 끼웁니다(test_analysis_routes.py:3328-3730). `quality_compare`도 `setattr(ae, ...)`로 10개를 감쌉니다.
2. 결과 저장 헬퍼(`_insert_analysis_result`, `_store_visualization_progress`, `_claim_visualization_row`)와 시각화 CAS(`_write_visualization_row`). manifest가 같은 트랜잭션으로 묶어야 할 지점과 정확히 겹칩니다. 지금 옮기면 manifest 연결 때 다시 옮겨야 합니다.
3. `_viz_cost_totals`, `_merge_records`. 원장 설계와 같은 파일(`pricing.py`, 미커밋)에 들어갈 후보입니다.
4. settings 저장소 경계. 지연 import 8곳과 `patch.dict(sys.modules, {"api.settings": stub})`(test_analysis_routes.py:66-73)가 걸려 있습니다.
5. 채팅 맥락 조립(analysis_routes.py:1455-1563). 미추적 `chat_context.py`, `selection_context.py`와 같은 작업이고, 플래그 이름 `reading_help`가 의미와 반대입니다(1608).
6. worker, supervisor, launcher, stopper, quit handler, log batcher, EPIPE guard. 이미 단일 책임이고 테스트가 있습니다(python-manager.test.ts 12건, stopper 4건, quit 5건).
7. `prepare-mac-build.js`, `prepare-win-build.js` 통합. 릴리스 삭제 목록이라 합쳐서 얻는 이득이 작습니다.
8. `document_manifest.py`, `gemini_parser.py`, 그림과 표 후보 휴리스틱. 추출 정확도 12/12 회귀가 걸려 있습니다.
9. `tools/`와 `backend/scripts/`. 제품 private 심볼을 patch하고, `quality_compare`는 소스 아카이브로 과거 비교를 재현하며, `Journal`과 `BudgetJournal`은 요청 원장의 실사용 원형입니다.

---

## 4. 우선순위와 실행 순서

우선순위 기준은 위험, 사용자 영향, 결합도, 테스트 가능성, 다른 작업의 선행 조건입니다. 줄 수는 기준이 아닙니다.

### 4.0 0단계: 기준선, 격리, 동작 고정

| 단위 | 범위 | 의존 | 병렬 | 완료 기준 | 중단과 복원 |
|---|---|---|---|---|---|
| 0-A 기준선 결정 | 미커밋 기능 변경(병렬 실행, 완료 계약, 미추적 모듈 3종, `requirements.txt`의 jsonschema)을 한 단위로 확정 | 사용자 결정 | 불가, 모든 작업의 선행 | 사용자가 커밋 단위를 정함. 깨끗한 worktree에서 `pytest services api models` 통과 | 결정 전에는 1단계 이후를 시작하지 않음 |
| 0-B 네트워크 가드 (R0) | `backend/conftest.py` 신규 | 0-A와 독립 | 가능 | 외부 connect 차단 양성 대조 통과, 기존 전체 pytest 통과 수 유지 | 기존 테스트가 실패하면 loopback 허용 범위를 확인. 신규 파일 삭제로 복원 |
| 0-C 계약 고정 테스트 | R2(HTTP), R8(단계 입력 바이트), R15(HMAC), schema 해시, 지시문 sha256, 시각화 계획 입출력, 보고서 바이트 | 0-B | 서로 다른 테스트 파일이면 가능 | 각 고정 테스트가 현재 코드에서 통과 | 실행마다 값이 다르면(비결정성) 해당 고정을 중단 |
| 0-D 격리 하네스 | 임시 HOME, `SASOO_APP_DATA_ROOT`, 합성 SQLite와 PDF, 키 제거, sandbox 외부 네트워크 차단, 원본 dist 보존용 소스 복사 | 없음 | 가능 | 실제 사용자 경로와 다름을 확인 | 경로가 사용자 데이터와 겹치면 중단 |

### 4.1 1단계: 부수효과가 적은 순수 계산과 타입 경계

파일이 겹치지 않는 묶음은 병렬로 구현할 수 있습니다. 병합은 한 묶음씩 하고, 매 병합 뒤 해당 집중 검사를 다시 돌립니다.

| 묶음 | 단위 | 수정 파일 | 병렬 관계 |
|---|---|---|---|
| 1-I | R3 → R4 → R5 | analysis_execution.py, analysis_completion.py, 새 모듈 | 묶음 안은 순차(같은 파일). 다른 묶음과 병렬 |
| 1-II | R1 | analysis_routes.py, report_service.py | 병렬. 단 2-I(R6)보다 먼저 |
| 1-III | R7 | odl_parser.py | 병렬. R9보다 먼저 |
| 1-IV | R10, R11 | frontend 컴포넌트와 lib | R10과 R11은 파일이 달라 병렬 |
| 1-V | R13 | electron/ | 병렬 |
| 1-VI | R14 | services/llm/ | 병렬 |

완료 기준: 각 단위의 고정 테스트와 집중 검사가 테스트 수정 없이 통과합니다. patch 문자열 경로를 바꿔서 통과시키지 않습니다. 단계 마지막 수정 뒤 전체 회귀를 실행합니다.

### 4.2 2단계: API 상태, 프런트 비동기, provider, IPC 경계

| 단위 | 범위 | 의존 | 병렬 |
|---|---|---|---|
| 2-I R6 상태 투영 | analysis_routes.py | 1-II 이후, 0-A의 레거시 상태 결정 이후 | 2-II, 2-III과 병렬 |
| 2-II R12 controls hook | frontend hooks | 없음 | 병렬 |
| 2-III R9 파서 모듈 분할 | odl_parser.py 분할 | 1-III, R8 이후 | 병렬 |
| 2-IV SDK 재시도 관측 테스트 | 테스트만: 설치된 SDK의 HTTP 전송 횟수를 Gemini에도 측정(`test_openai_client.py:888` 방식) | 0-B | 병렬 |
| 2-V Electron 발신자 검증, updater getter | electron/ | R13 이후 | 병렬. 동작 변화가 작아도 6절 승인 대상 |

### 4.3 3단계: DB, 파일, 시각화 저장, 스트리밍, 실행 조율

3단계는 실행 manifest 설계가 확정되기 전에는 시작하지 않습니다. 먼저 아래 동시성과 장애 테스트를 "현재 동작" 특성 테스트로 고정합니다.

1. fence를 잃은 worker의 늦은 비시각화 INSERT(현재 막지 못함을 known gap으로 기록).
2. 같은 `input_hash` 두 실행의 checkpoint INSERT.
3. `created_at`이 같은 행 사이의 캐시 claim과 checkpoint 대상 일치(정렬 기준 불일치: document_context.py:209-217과 analysis_execution.py:3150-3157).
4. regenerate, html-check와 worker checkpoint의 CAS 교차.
5. 실행 중 `POST /synthesis`.
6. in-process 이중 `/run`.
7. aiosqlite execute 진행 중 task 취소 뒤 commit 잔존 여부.
8. figure 성공 후 table 실패, DB 오류, 프로세스 재시작(합성 PDF와 SQLite, 파일 바이트와 행 ID 비교).
9. 구버전 DB 반복 기동, WAL과 FK, DDL 실패(migration의 `except Exception: pass` 11곳).
10. 채팅 SSE: 토큰 전 재시도, 토큰 후 실패, disconnect의 interrupted 저장.

### 4.4 R12 모의 지연 테스트 설계

현재 결함은 도달할 수 없습니다. 이 테스트는 hook 계약을 고정하려는 것입니다.

1. `requestEfficiency.test.js` 하니스를 재사용하는 새 `.test.js` 파일을 만듭니다. api mock에 `getSettings`, `cancelAnalysis`, `status` 필드를 가진 `ApiError`를 추가합니다.
2. `settings = deferred()`로 `getSettings`를 보류합니다. 논문 1(`status: 'pending'`)로 `useAnalysis`와 controls를 함께 마운트합니다.
3. 논문 2(`status: 'completed'`)로 바꿔 다시 렌더한 뒤 `settings.resolve({ auto_analyze: true })`를 실행합니다.
4. `runAnalysis` 호출 0회, `status.paper_id === 2`, `showAnalysisConfirm === false`를 확인합니다. `auto_analyze: false`와 reject 변형도 같은 조건으로 확인합니다.
5. 현재 코드에서는 실패해야 합니다. 수정 뒤에는 통과해야 합니다.
6. 회귀 고정: 언마운트 후 resolve하면 `POST /run` 0건. 정상 경로에서는 `runAnalysis('1')` 정확히 1회.

### 4.5 별도 기능 작업과 동작 수정

이 항목들은 리팩토링과 분리합니다. 각각 사용자 승인이나 별도 설계가 필요합니다.

| 묶음 | 내용 | 선행 |
|---|---|---|
| F1 실행 manifest와 fence | execution과 attempt identity, worker에 `(execution_id, attempt_id, generation)` 전달, 결과 쓰기와 fence를 같은 `BEGIN IMMEDIATE`에. `analysis_manifest_store.py`는 UPDATE만 하고 INSERT가 없으며, in-process 경로에는 `analysis_runs` 행이 없어 항상 `FenceLost`가 납니다. DDL도 migration에 없습니다 | 0-A, 3단계 특성 테스트. 프로세스 분리 계약 "phase 무수정"과 충돌하므로 사용자 결정 |
| F2 요청별 비용 원장 | 전송 전 `request_attempt_id`. 훅 지점은 `gemini_client._sync_call_once`, `_sync_stream`, `openai_client._do_call`, `_produce`, `figure_gen`의 렌더 provider 2종. SDK 재시도를 관측 가능하게(OpenAI 클라이언트 `max_retries=0`, Gemini `retry_options`). 기존 비용 출처 4곳(행 `cost_usd`, 시각화 `requests`, `analysis_cache_events`, visual_parse 행) 투영 | F1의 identity. 2-IV 측정 |
| F3 unknown 의미 통일 | D7 Gemini usage 누락을 None으로. `test_gemini_client.py:336-356`이 0을 잠그고 있어 기대값 변경 필요. `_run_chain_stage`의 `usage_missing` 판정이 Gemini에서 작동하기 시작해 성공 응답이 실패가 될 수 있음 | 사용자 결정. F2와 함께 |
| F4 비용 집계 확장 | D8 채팅, 실험 계획, 그림 설명, resolver, naming 포함. D6 월 키. 라이브 합계에서 캐시 재사용 분리(14곳). 기존 `total_cost_usd` 의미는 유지하고 새 필드 추가 | F2 |
| F5 파서 동시성과 기록 순서 | D1 프로세스 간 단일화(파일 잠금 또는 DB claim), D2 ready 순서, D3 실패 경로 사용량, figures와 tables 단일 트랜잭션 | R8, F2 스키마 합의 |
| F6 개별 결함 수정 | D4 재시도 번호(재현 후), D10 취소 polling, D11 repair 중복, D12 regenerate try 범위, D13 synthesis 가드, D14 updater와 activate | 각 항목 재현 테스트 |
| F7 레거시 상태 표시 | 1.3의 3번. 과거 완료 논문을 `error`로 보여 줄지, 별도 `legacy` 표시로 할지 | 사용자 결정. R6보다 먼저 |
| F8 캐시 무효화 | D9 스크리닝 키에 실제 지시문 포함. 기존 스크리닝 캐시가 한 번 무효화되어 재호출 비용 발생 | 사용자 결정 |
| F9 문서 정정 | 루트 AGENTS.md 6곳(1.3의 7번) | 사용자 승인 |

---

## 5. 검증 매트릭스

| 검사 | 명령 또는 방법 | 적용 대상 |
|---|---|---|
| Python 집중 | 단위별 테스트 파일. 예: `pytest services/test_synthesis.py services/test_viz_plan_contract.py` | R3-R9, R14, 3단계 전부 |
| Python 전체 | `./.venv/bin/python -m pytest services api models tools/test_*.py`, `py_compile main.py` | 모든 백엔드 단위의 단계 마지막 |
| 프런트 집중 | `pnpm --dir=frontend exec vitest run <파일>` | R10-R12 |
| 프런트 전체 | 루트 `pnpm test`와 `pnpm --dir=frontend test` 두 경로 | 모든 프런트 단위, R13 |
| 타입, lint, 빌드 | `pnpm tsc --noEmit`, `pnpm lint`, 격리 복사본에서 `pnpm build` | R10, R11, R12 |
| Electron 빌드 | `pnpm test:unit`, `pnpm build:electron` | R13, 2-V, F6의 D14 |
| API 계약 | R2 스냅샷 비교. 합성 DB와 TestClient | R1, R5, R6, 3단계 |
| 프롬프트와 캐시 | 단계 입력 9키 sha256, schema 해시, 지시문 sha256 | R4, R5, R8, R9, R14, F8 |
| 취소, 실패, 지연, 동시성 | 4.3 목록, 4.4 모의 지연 | R6, R12, F1, F5, F6 |
| 레거시 데이터 | `planned_items` 없는 행, sidecar v4, `legacy-{id}-{tool}` 합성 ID | R5, R6, F3, F4, F7 |
| 파일 바이트와 DB 행 보존 | 합성 PDF로 파일 목록과 sha256, figures 행 ID와 `detailed_explanation` | R7, R9, F5 |
| 공급사 호출 0회 | R0 가드 활성 상태에서 실행. 실제 connect 시도 0건 기록 | 모든 단위 |
| 격리 Electron | 아래 5.1 | R10, R12(선택), R13, 2-V, F6, F7 |
| 미검증으로 남는 범위 | 외부 API 소비자, 실제 사용자 DB 호환, 패키징 앱, Windows 실기, 실제 공급사 청구 | 모든 단위의 보고서에 명시 |

### 5.1 격리 Electron 검증 계획

화면이나 API 흐름이 바뀌는 작업에 적용합니다.

1. 외부 네트워크를 차단합니다. 유료 생성 API(`/run`, explain, repair, regenerate, synthesis POST, chat)는 기본 차단하고 합성 응답 stub으로 대체합니다.
2. 별도 `HOME`, `SASOO_APP_DATA_ROOT`, Electron `--user-data-dir`을 씁니다. 합성 DB에는 정상 완료, 진행 중, 취소, 실패, 레거시(`planned_items` 없음) 논문을 각 1편 넣습니다.
3. 창 너비 1024px와 1440px에서 확인합니다.
4. 키보드 Tab 순서, 라이트박스 포커스 트랩, PDF 스크롤과 인용 이동을 확인합니다.
5. 로딩, 실패, 취소, 레거시 상태 화면을 각각 캡처합니다.
6. 콘솔 오류 0건을 확인합니다. 하네스가 대상을 종료한 경우와 앱 장애를 로그로 구분합니다.
7. 화면 값 하나 이상(예: 진행률, 비용 합계, 단계 상태)을 `/status` 응답과 DB 행과 대조합니다.

---

## 6. 삭제 및 변경 승인 경계

**새 삭제 제안은 없습니다.** 과거 A, B, C 승인은 이미 처리된 세 대상(`_resolve_pdf_engine`, `_set_setting`, `getMermaid`)에만 적용됩니다.

아래 대상은 참조가 없거나 적지만 삭제하지 않고 유지합니다.

| 대상 | 참조 | 불확실성 | 판정 |
|---|---|---|---|
| `BaseAgent.get_system_prompt`, `_OUTPUT_LANG_INSTRUCTION`(base_agent.py:159-179) | 제품과 테스트 호출 0건(grep) | 사용자 agent 파일과 외부 스크립트 미확인. 미커밋 수정 중 | 유지 |
| preload 허용 목록의 송신자 없는 4채널(`analysis:progress`, `analysis:complete`, `analysis:error`, `backend:status`) | 송신자와 구독자 0건 | 향후 기능 계획 미확인 | 유지. 지운다면 제품 결정 |
| `PythonManager.restart()`(python-manager.ts:360-365) | electron/ 안 호출 0건 | 공개 메서드 | 유지 |
| `ensure_parsed_artifacts`, `paper_artifacts_are_current`, `get_odl_reference_text` | 테스트와 도구만. `odl-reference.md` 파일은 `tools/extraction_audit`가 읽음 | 외부 사용 미확인 | 유지 |
| `analysis_manifest_store.py`와 테스트 | 테스트만(미추적) | 미완료 F1 원형 | 유지 |
| `tables/` 고아 파일, `.text_cache.txt` 내용 | 정리 코드 없음, 내용은 읽지 않지만 currency 판정에 사용 | 구버전 라이브러리 | 유지. 정리는 데이터 삭제 승인 필요 |
| GET `/mermaid`, `/mermaid/repair` | 프런트 wrapper 삭제 뒤에도 공개 API | 외부 소비자 | 유지 |

사용자 승인이 필요한 동작 변경은 4.5의 F1-F9입니다. 특히 값이 바뀌는 항목은 F3(unknown 의미), F4(집계 범위), F7(레거시 상태), F8(캐시 무효화와 재호출 비용)입니다.

---

## 7. 첫 구현 제안: R0 테스트 네트워크 가드

**먼저 하는 이유.** 이후의 모든 리팩토링은 함수를 옮깁니다. 테스트는 `services.analysis_execution.call_interaction`을 51-54회(영역 1과 6의 집계 범위 차이), `gemini_client._get_client`를 27회 문자열로 patch합니다. 호출을 옮기면 patch가 조용히 빗나가고, 실제 호출이 나갈 수 있습니다. 현재 테스트에는 socket 차단이 없고, `backend/.env`가 존재하며 `main.py`가 이를 로드합니다. 가드가 있으면 빗나간 patch가 유료 호출 대신 테스트 실패로 드러납니다. 제품 코드를 건드리지 않고 0-A 결정과도 독립적입니다.

**변경 범위.** 새 파일 `sasoo/backend/conftest.py` 하나입니다. autouse fixture로 `socket.socket.connect`와 `connect_ex`를 감쌉니다. loopback(127.0.0.1, ::1)과 Unix socket만 허용하고 나머지는 예외를 냅니다. 기존 `services/conftest.py`는 수정하지 않습니다.

**바뀌지 않아야 할 동작.** 제품 코드, 기존 테스트의 통과 수와 skip 수는 그대로입니다. `test_openai_client.py:886`의 설치 SDK 전송 횟수 테스트는 `httpx2.MockTransport`를 써서 socket을 열지 않으므로 가드의 영향을 받지 않아야 합니다(총괄 확인). loopback socket을 실제로 여는 테스트가 있는지는 미확인이며, 1번 기준선 실행에서 드러납니다.

**먼저 작성하거나 실행할 테스트.**
1. 가드 적용 전 격리 복사본에서 전체 pytest를 실행해 통과, skip, 실패 수를 기록합니다.
2. 양성 대조 테스트를 추가합니다. 외부 주소(예: 192.0.2.1, TEST-NET-1) connect가 예외를 내는지, 127.0.0.1은 허용되는지 확인합니다.

**격리 환경.** 0-D 하네스를 씁니다. 별도 HOME과 앱 데이터 경로, 공급사 키 제거, sandbox 외부 네트워크 차단, 소스 복사본에서 실행합니다.

**완료 기준.** 양성 대조 통과, 전체 pytest의 통과 수가 기준선과 같음, 가드가 차단한 connect 시도 목록이 0건이거나 그 원인이 모두 설명됨.

**중단 조건과 복원.** 기존 테스트가 가드 때문에 실패하면 중단하고 해당 테스트의 네트워크 의존을 먼저 기록합니다. 허용 목록을 넓혀서 통과시키지 않습니다. 복원은 새 파일 삭제 하나입니다.

**manifest와 원장의 관계.** 직접 관계는 없습니다. F2 원장 훅의 모의 SDK 테스트가 실제 전송 0건을 보장받으려면 이 가드가 선행 조건입니다.

**두 번째 후보.** R1 보고서 조립 분리입니다. 순수 이동이고 응답 바이트 스냅샷 하나로 검증할 수 있습니다.

---

## 8. 종료 조건과 남은 미확인 범위

이 계획은 아래 조건을 모두 만족할 때 완료로 봅니다.

1. 0-A 기준선이 사용자 결정으로 확정되어 있습니다.
2. 1단계와 2단계 단위가 각자의 고정 테스트를 테스트 수정 없이 통과합니다.
3. 마지막 수정 기준으로 5절의 전체 회귀가 통과합니다. 화면이 바뀐 단위는 격리 Electron 검증도 통과합니다.
4. 공급사 호출 0건이 R0 가드 기록으로 확인됩니다.
5. 구현 중 새로 발견한 결함은 D 번호를 이어 붙여 이 문서에 추가하고, 리팩토링 단위에 섞지 않습니다.
6. 아래 미확인 범위는 각 보고서에 "미검증"으로 남깁니다.

남은 미확인 범위:

1. 외부 HTTP와 Python, TypeScript 소비자.
2. 실제 사용자 DB의 레거시 행 분포와 F7 영향 규모.
3. google-genai `max_retries=3`의 정확한 의미와 POST 적용 여부.
4. resolver와 naming VLM 호출의 실제 과금 규모.
5. 패키징 앱의 asar 내용(`docs/`, `graphify-out/` 포함 여부), jsonschema metaschema 번들.
6. Windows `taskkill /T`가 DETACHED worker까지 종료하는지, 서명 없는 macOS의 `autoInstallOnAppQuit`.
7. 401 응답에 CORS 헤더가 빠질 때 renderer가 보는 실제 오류.
8. 로컬 `.venv` Python 3.14와 CI 3.12의 차이가 테스트 결과에 주는 영향.
