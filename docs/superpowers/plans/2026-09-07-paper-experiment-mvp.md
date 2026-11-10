# 논문 실험 MVP Implementation Plan

> **For agentic workers:** When implementation is requested and required approvals are satisfied, execute task-by-task using an available workflow. Prefer superpowers:subagent-driven-development or superpowers:executing-plans when available; otherwise use an equivalent workflow with the same approval gates. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sasoo의 실험 탭에서 논문 속 로봇의 작은 실험을 실행하고 자연어 변형, 예상과 비교, 논문별 학습 메모로 핵심 이해를 돕는다.

**Architecture:** 기존 분석, 프로필, API 인증과 SQLite를 재사용한다. 논문당 실험 세션 한 행과 자료 폴더를 추가하고, FastAPI가 자료 확보와 생성 작업을 맡는다. 로봇 계산은 우선 공식 MuJoCo WebAssembly와 브라우저 격리 실행을 검증해 단일 실행 경로로 구성한다.

**Tech Stack:** 기존 Electron, React/Vite, TypeScript, FastAPI/Pydantic v2, SQLite, Gemini/OpenAI 선택과 pnpm. 실행 후보는 `@mujoco/mujoco` 단일 스레드 빌드와 Three.js이며, Task 1의 검증 후 버전을 고정한다.

**Spec:** [확정 명세](../specs/2026-09-07-paper-experiment-mvp.md)

## Global Constraints

- 사용자가 시작할 때 준비하며, 논문 업로드나 탭 조회만으로 생성하지 않는다.
- 첫 실행 실험 준비 목표는 5분 이내다. 준비되는 설명은 먼저 보여준다.
- 예상 질문은 항상 건너뛸 수 있다.
- 논문별 짧은 학습 메모 하나를 저장하고 다음 턴에 반영한다.
- 논문 간 개념 이해 공유나 전역 학습 상태는 만들지 않는다.
- 시간 초과 또는 준비 실패 시 준비된 설명과 막힌 이유를 보존하고 자동 재시도를 멈춘다.
- 기존 종합 뷰와 레시피의 실험 계획 문서를 유지한다. 새 실행 탭은 별도 기능이다.
- 사용자 설명은 한국어, 코드 주석은 간단한 영어. 기존 디자인 토큰과 컴포넌트를 재사용한다.
- 저장소 전체 리팩터링, 새로운 큐 서버, 다중 실행 엔진과 전역 학습 그래프를 추가하지 않는다.
- 이 문서의 기술 선택은 구현 제안이다. 아래 체크박스는 아직 실행하지 않았으며, 런타임 작동과 성능은 검증 전이다.

---

## 현재 코드에서 확인한 연결 지점

| 현재 파일 / 심볼 | 확인한 사실과 사용 방법 |
|---|---|
| `sasoo/frontend/src/components/AnalysisPanel.tsx`, `activeTab`, `tabs` | 요약, 종합, 읽기 안내, 그림, 표, 레시피 탭을 소유한다. 여기에 `experiment`를 추가한다. |
| `sasoo/frontend/src/pages/Workbench.tsx` | `paperId`, 설명 수준, 분석 결과, 원문 이동과 채팅을 연결한다. 새 페이지나 라우트가 필요하지 않다. |
| `sasoo/frontend/src/components/ExperimentPlanTab.tsx` | 레시피 안의 생성형 실험 계획 문서다. 실제 로봇 실행기로 간주하지 않는다. |
| `sasoo/frontend/src/lib/api.ts`, `request` | 런타임 인증과 네트워크 재시도가 있다. 새 변경 요청에는 재시도 없는 옵션과 중복 방지가 필요하다. |
| `sasoo/backend/api/analysis_routes.py`, `_generate_experiment_plan_impl` | 기존 분석 결과와 논문 텍스트를 조합해 생성하고 비용을 기록하는 참고 경로다. |
| `sasoo/backend/api/analysis_routes.py`, `_chat_with_agent_impl` | 최근 대화와 원문을 채팅에 넣는다. 같은 논문의 실험 메모를 붙일 위치다. |
| `sasoo/backend/api/analysis_context.py`, `build_reader_profile_block` | 연구자 설정을 설명 문맥으로 바꾼다. 조사 보고서의 `build_researcher_context`라는 이름은 실제 코드에 없으므로 사용하지 않는다. |
| `sasoo/backend/services/document_context.py`, `load_or_build_document_context` | `.document_context.json`과 추출 텍스트를 재사용한다. 실험마다 PDF를 다시 파싱하지 않는다. |
| `sasoo/backend/models/database.py`, `get_paper_dir`, `init_db` | 논문 자료 경로와 DB 초기화. `experiment_plans`는 과거 생성 문서의 이력이므로 실행 상태를 덮어쓰지 않는다. |
| `sasoo/backend/services/llm/interactions_client.py` | 모델명에 따른 공용 provider 진입점이다. 신규 실험도 사용자의 provider를 유지한다. |
| `sasoo/backend/services/llm/gemini_client.py`, `openai_client.py` | 동기 SDK/스레드 경로와 재시도가 있다. 단순 coroutine 취소만으로 실제 요청 중단을 보장하지 못한다. |
| `sasoo/backend/models/analysis_runs.py`, `analysis_supervisor.py` | 분석 전용 재시작/재시도 정책이다. 실험에 붙이면 자동 재시도 중단 요구와 충돌하므로 변경하지 않는다. |
| `sasoo/backend/main.py`, `lifespan` | 실험 준비 task의 종료 처리를 연결한다. |
| `sasoo/electron/main.ts`, `webPreferences` | context isolation, sandbox, web security가 활성화되어 있다. 생성 코드를 위해 이를 낮추지 않는다. |
| `sasoo/docs/04-design/design-tokens.md` | 실험 탭도 기존 색, 타이포그래피, 포커스, 상태색을 따른다. |

현재 자료 탐색, 로봇 모델 import, 실제 시뮬레이션, 생성 코드 격리 실행은 새로 구현해야 한다. 이를 설명 생성으로 대체한 상태를 MVP 완료로 판정하지 않는다.

## 기술 선택과 검증 경계

공식 [MuJoCo JavaScript bindings](https://github.com/google-deepmind/mujoco/blob/main/wasm/README.md)는 npm 패키지와 단일 스레드 WebAssembly 빌드를 제공한다. 이 경로를 우선 검증하면 네이티브 Python 시뮬레이터 배포를 추가하지 않고 HTML 실험을 만들 수 있다. 해당 문서는 진행 중인 구현과 플랫폼 차이도 명시하므로 Electron에서의 실측이 선행 조건이다.

[MuJoCo 모델링 문서](https://mujoco.readthedocs.io/en/stable/modeling.html)는 MJCF와 제한적인 URDF import를 설명한다. 형식이 읽힌다는 사실을 원문 로봇의 동역학과 제어기까지 재현했다는 뜻으로 쓰지 않는다.

준비는 저자 자료를 읽고 필요한 모델과 소규모 제어 코드를 구성하는 과정이다. 내려받은 저장소의 설치 스크립트나 임의 Python을 앱 권한으로 실행하지 않는다. 원문 코드의 교육용 포팅과 축소는 명세 R8의 확인 대상이다.

실행은 trusted HTML shell, 물리 계산, 생성 제어 코드의 경계를 둔다. [Electron 보안 문서](https://www.electronjs.org/docs/latest/tutorial/security)와 [iframe sandbox 문서](https://developer.mozilla.org/en-US/docs/Web/HTML/Reference/Elements/iframe)에 따라 원문/생성 코드에 Node, preload, API 인증 토큰과 일반 네트워크 권한을 주지 않는다. Task 1에서 번들 로딩과 격리 조합을 확인한 뒤 재사용한다.

## 데이터와 API 계약

### 최소 저장

새 `experiment_sessions` 한 테이블만 추가한다. 논문별 메모는 이 행의 JSON 안에 둔다. 큰 모델, mesh와 실행 배열은 `get_paper_dir(folder_name) / "experiments"` 아래에 저장한다. 기준 실행과 현재 실행을 보존하고, 실패한 수정이 마지막 검증 결과를 덮어쓰지 않게 한다.

```sql
CREATE TABLE IF NOT EXISTS experiment_sessions (
    paper_id INTEGER PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 0,
    attempt_id TEXT,
    state TEXT NOT NULL,
    content TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

`content`는 Pydantic으로 입출력 시 검증한다. 포함할 필드는 아래와 같고 별도 메모 테이블이나 이벤트 저장 시스템은 만들지 않는다.

| 필드 | 내용 |
|---|---|
| `schema_version`, `paper_fingerprint` | 데이터 버전과 원문/분석 근거의 해시 |
| `explanation`, `course`, `current_step` | 짧은 설명, 근거가 연결된 학습 순서, 진행 위치 |
| `sources` | 실제 확보 URL, 저자 연관 근거, 저장소 commit, 파일 해시와 라이선스 정보 |
| `assumptions` | 식별자, 이유, 영향, 확인 상태와 확인한 번들 해시 |
| `baseline`, `current`, `previous` | 검증된 번들의 상대 경로와 해시. 기준/현재/직전 상태 |
| `memo` | 개념, `unverified`/`confusion`/`supported`, 근거 종류와 짧은 설명의 소규모 배열 |
| `last_run` | 설정, 시드, 물리 시간 간격, 결과 파일, 정상 종료 여부 |
| `error` | 실패 단계, 원인 코드, 한국어 설명 |
| `timing` | 요청 시작, 준비 계산 시간, 사용자 확인 대기 시간, 실제 총 경과 시간 |
| `usage` | provider, model, 호출별 실제 token/cost 합계 |

실험 번들은 `robot_model_path`, `assets`, `controller_source`, `parameters`, `initial_conditions`, `solver`, `observables`, `source_refs`, `assumptions`를 가진다. 모든 변수는 이름, 단위, 범위와 기본값을 가진다. 모델과 자산의 상대 경로는 논문 폴더 밖을 가리킬 수 없다.

### 상태

```text
idle -> preparing -> awaiting_confirmation -> validating -> ready
                    preparing -------------> validating -> ready
preparing / validating -> failed | cancelled
ready -> preparing (사용자의 변경 요청, 검증된 기존 번들 보존)
failed / cancelled -> preparing (사용자의 명시적 재시도)
```

가정 확인이 필요하면 관련 실행 전에 `awaiting_confirmation`에서 멈춘다. 확인 대기 중에는 준비 작업을 돌리지 않는다. 확인 재개 시 준비 계산 예산의 남은 시간만 사용하고, 확인 대기를 포함한 실제 경과 시간도 표시한다. 이 시간 구분은 구현 기본값이며 5분 벽시계 달성으로 바꿔 보고하지 않는다.

한 시도의 자동 준비 작업 예산은 300초다. 검색, 다운로드, 생성, 실행 검증을 모두 포함한다. 실패 시 자동 repair/retry loop가 없다. 재시작 시 진행 중이던 시도는 `failed`와 중단 사유로 정리하고 자동 재개하지 않는다.

### HTTP

모든 경로는 기존 런타임 인증을 유지한다. `paper_id`의 존재, 요청 길이, 유한 수치, 범위와 revision을 입구에서 검증한다.

| 경로 | 요청 / 응답 |
|---|---|
| `GET /api/experiments/{paper_id}` | 저장된 세션. 기록이 없으면 `idle`. 생성 부작용 없음 |
| `POST /api/experiments/{paper_id}/prepare` | `{request_id, expected_revision}`. 빠르게 202와 세션 반환 |
| `POST /api/experiments/{paper_id}/confirm` | `{expected_revision, bundle_hash, assumption_ids}`. 해당 번들만 확인 |
| `POST /api/experiments/{paper_id}/cancel` | `{attempt_id}`. task 종료 후 세션 반환 |
| `POST /api/experiments/{paper_id}/turn` | `{request_id, expected_revision, message, prediction_action}`. 다음 설명, 메모 또는 수정 준비 상태 |
| `POST /api/experiments/{paper_id}/run-result` | `{attempt_id, bundle_hash, settings, result}`. 현재 번들에 대한 검증 결과/실행 기록 |
| `POST /api/experiments/{paper_id}/restore` | `{expected_revision}`. 직전 검증된 번들로 복귀 |
| `GET /api/experiments/{paper_id}/assets/{asset_id}` | 등록된 파일만 인증 후 반환. 임의 URL/경로 fetch 아님 |

`prediction_action`은 `answer`, `skip`, `none`이다. skip은 LLM을 거치기 전에 현재 개념을 `unverified`로 기록한다. 중복 `request_id`는 같은 처리 결과를 돌려주고 비용 발생 작업을 다시 시작하지 않는다. 오래된 revision은 409, 없는 논문은 404, 유효하지 않은 입력은 422다.

## Task 1: 실제 로봇을 이용한 실행 경로 검증

**Files:** Create `sasoo/frontend/src/lib/experiment/runtime.ts`, `sasoo/frontend/src/lib/experiment/physics.worker.ts`, `sasoo/frontend/src/lib/experiment/controller.worker.ts`, `sasoo/frontend/src/components/ExperimentFrame.tsx`; update frontend package/lock and Vite asset handling only as needed. Evidence: `output/paper-experiment-mvp/runtime-check.md`.

**Interfaces:** trusted runtime accepts a validated experiment bundle and produces joint/body states, time series, completion/failure and a bundle hash. Generated controller receives numeric observations and parameters, returns bounded actuator commands, and cannot issue host filesystem/API calls. Predictive rollouts, if needed by the method, go through a bounded trusted physics operation.

- [ ] Start with [Predictive Sampling](https://arxiv.org/abs/2212.00541) and the [author repository](https://github.com/google-deepmind/mujoco_mpc) as a candidate validation case. Choose a robot actually used in the paper, verify its connection to source assets, pin the commit and record model files. A pendulum smoke test can check the engine but cannot satisfy this robot gate.
- [ ] Install exact tested releases of `@mujoco/mujoco` and `three` only in the frontend. Bundle the wasm and meshes locally, lazy-load them on experiment use, and verify packaged `file://` asset resolution. Do not pull a native compiler or full MJPC build into the user startup path.
- [ ] Use a sandboxed frame with no same-origin privilege and no preload bridge. Transfer authenticated asset bytes from trusted parent code. Run generated code in a terminable worker; keep rendering, result assembly and resource limits outside that worker. Validate `event.source`, attempt identity and every message payload.
- [ ] Implement the runtime's command/response protocol with bounded messages:

```text
load(bundle, assets) -> loaded(bundle_hash, joint_names, dimensions)
run(settings, seed, time_step, duration) -> progress | result | error
stop() -> stopped
dispose() -> release workers, wasm objects, GPU resources and object URLs
```

- [ ] Check real torque/control changes produce corresponding joint-state changes. Check reset/replay, invalid dimensions, nonfinite output, infinite-loop cancellation, blocked network/Node access and parent responsiveness. Cross-check one displayed position against physics output; compare time step h versus h/2 for the chosen observable and report the measured difference.
- [ ] Record OS, Electron/Chromium, package versions, asset bytes, load time, simulation rate and frame timing. Verify both dev and packaged loading. Stop dependent implementation if the engine cannot run under the required isolation; revise this same plan using evidence before adding another engine.

**Gate:** real source robot loaded and actuated, killable controller, correct displayed value, reset and resource cleanup. This is not a claim of paper performance reproduction.

## Task 2: 논문별 세션과 학습 메모 저장

**Files:** Create `sasoo/backend/models/experiment.py`, `sasoo/backend/services/experiment_store.py`, `sasoo/backend/services/test_experiment_store.py`; modify `sasoo/backend/models/database.py`.

**Interfaces:** `ExperimentSession` and `ExperimentBundle` implement the contract above. `load_session(paper_id)` returns the typed session or None. `save_session(session, expected_revision)` performs an atomic revision check and returns the new typed session. A conflicting save raises a typed conflict mapped to 409.

- [ ] Add one SQLite round-trip test for a memo and bundle metadata, then implement the DDL and models. Use `get_paper_dir` for binary artifacts.
- [ ] Verify stale attempt and revision updates cannot replace current state. Use one conditional SQL update, not a read followed by an unconditional write:

```sql
UPDATE experiment_sessions
SET content = ?, state = ?, attempt_id = ?, revision = revision + 1,
    updated_at = CURRENT_TIMESTAMP
WHERE paper_id = ? AND revision = ?;
```

- [ ] Write assets to a temporary file in the target directory, rename atomically, and publish the new bundle reference only after all referenced files exist and hashes match. Keep previous/current/baseline references intact on failure.
- [ ] Add tests for paper isolation, restart persistence, invalid relative paths, duplicate request identity and stale saves. Match existing DB setup in backend tests; do not add another DB framework.

```bash
cd sasoo/backend
./.venv/bin/python -m pytest services/test_experiment_store.py -q
```

**Gate:** reload produces the same memo for paper A and no memo for paper B; a stale update cannot overwrite a newer session.

## Task 3: 자료 확보와 300초 준비 작업

**Files:** Create `sasoo/backend/services/experiment_sources.py`, `sasoo/backend/services/experiment_service.py`, `sasoo/backend/services/test_experiment_sources.py`, `sasoo/backend/services/test_experiment_service.py`, `sasoo/backend/api/experiments.py`, `sasoo/backend/api/test_experiments.py`; modify `sasoo/backend/main.py`, provider clients and their existing tests.

**Interfaces:** `prepare_experiment(paper_id, request_id, expected_revision)` returns the new session identity and starts one owned preparation task. `cancel_experiment(paper_id, attempt_id)` closes that task. `collect_experiment_sources(paper_context, remaining_seconds)` returns validated source records and downloaded file metadata. Generation returns `ExperimentBundle`, never raw JSON accepted without schema validation.

- [ ] Add tests for duplicate prepare requests, cancellation, deadline expiration, preserved partial explanation and a delayed result after cancellation. Use a controllable clock/test event rather than waiting 300 seconds.
- [ ] Build the prompt from existing document context, latest analysis results, `build_reader_profile_block` and paper explanation level. Generate a short course first, with one initial executable experiment and source anchors; prepare further experiments only when reached.
- [ ] Extract real URLs from paper text/links and follow author project/repository links. When missing, use public GitHub repository search with title/author terms, then confirm paper title/DOI/author association in retrieved material. Search hits are candidates, not verified provenance. Record failed searches and absent assets explicitly.
- [ ] Use the installed HTTP client and bounded requests. Start with 3 candidate repositories, 2 project-link hops, 100 MiB total assets and 30 seconds per HTTP operation, always clipped to the remaining total budget. These are implementation limits to measure in Task 6, not scientific constants. Validate HTTPS, redirects, DNS/public address, byte count, file type and relative paths. Download selected files at immutable commits; avoid archive extraction and arbitrary install scripts. Respect authentication/rate-limit failures without bypassing them.
- [ ] Keep provider selection through `interactions_client`. Add opt-in per-call `timeout_s` and `max_attempts=1` to both provider implementations. For experiment calls use cancellable async SDK transport with SDK retries disabled and remaining time applied; inspect installed SDK signatures before coding. Do not claim a thread future cancelled the underlying HTTP call. Existing non-experiment behavior retains its current defaults.
- [ ] Parse generated bundle, compare robot identity and source references, and present required assumptions before simulation. After confirmation, Task 1's trusted runtime validates the bundle. Only a matching, current validation result can publish `ready`.
- [ ] Own preparation tasks inside FastAPI lifespan. On shutdown cancel and join them before closing DB. On restart mark interrupted sessions failed with an explanation; never enqueue them again automatically. Reject a second active attempt for the same paper.

```bash
cd sasoo/backend
./.venv/bin/python -m pytest services/test_experiment_sources.py services/test_experiment_service.py api/test_experiments.py services/llm/test_gemini_client.py services/llm/test_openai_client.py -q
```

**Gate:** an actual candidate paper reaches a source-backed bundle; missing sources and timeout take the honest stopped path. A request failing once causes no hidden outer/SDK repair loop.

## Task 4: 실험 탭과 준비/확인/실행 상태 연결

**Files:** Create `sasoo/frontend/src/components/ExperimentTab.tsx`, `sasoo/frontend/src/hooks/useExperiment.ts`, `sasoo/frontend/src/lib/experiment/types.ts`, `sasoo/frontend/src/lib/experiment/experiment.test.ts`; modify `AnalysisPanel.tsx`, `lib/api.ts`, `lib/strings.ts`, and Task 1 runtime files.

**Interfaces:** `useExperiment(paperId)` exposes session, prepare, confirm, cancel, sendTurn, restore and submitRunResult. It loads existing state on mount, not a new experiment. Types mirror backend state and bundle fields. Only preparation states trigger bounded polling; failures stop polling/retries.

- [ ] Add a focused test: loading the tab fetches state but never posts prepare; changing paper aborts observation and rejects late responses for the old paper.
- [ ] Add `experiment` after the existing tabs and render the new component. Keep the existing recipe document where it is. Use existing Button/ContentState/Markdown/icon tokens and standard `<details>` for the learning memo.
- [ ] Give API mutation requests an explicit no-network-retry option while retaining existing callers' defaults. Use request IDs for mutations so an uncertain response cannot double-start preparation. Parse response/message data at the boundary before passing it into the simulation.
- [ ] Render the states directly, without fake progress percentages:

```text
idle: experiment objective + start action
preparing: available explanation + named current operation + elapsed time + stop
awaiting_confirmation: assumptions + impact + confirmation action
validating: available explanation + execution check in progress
ready: simulation + short explanation + natural-language input + optional prediction
failed/cancelled: preserved explanation + precise reason + manual retry
```

- [ ] Default display uses one robot view and a baseline/current toggle, with comparable numeric results. Quantities include units and coordinate convention. Pause animation on tab exit; dispose the worker on paper change/unmount. A view pause does not silently repeat or cancel a persisted experiment request.
- [ ] Keep simulation bundle validation tied to attempt and hash. Source/raw script cannot send a generic `ready` message to bypass trusted checks. Nonfinite result, engine error, invalid control shape or watchdog expiration fails the run and preserves the last valid bundle.

```bash
cd sasoo/frontend
pnpm test -- src/lib/experiment/experiment.test.ts
pnpm tsc --noEmit
pnpm build
pnpm lint
```

**Gate:** the visible tab traverses actual prepare, confirmation, validation, ready and stopped states. Existing summary/synthesis/recipe navigation still works.

## Task 5: 자연어 변형과 다음 턴의 학습 메모

**Files:** Modify `experiment_service.py`, `api/experiments.py`, their tests, `api/analysis_routes.py`, `api/test_analysis_routes.py`, `ExperimentTab.tsx`, `useExperiment.ts`, and frontend experiment tests. No new global memory service.

**Interfaces:** `POST /turn` classifies `explain`, `change`, `predict`, `skip`, `correct_memo` within the experiment context. Explanation and memo updates share one structured AI response when needed. A change creates a candidate bundle through the same preparation/validation path, using current revision as its base.

- [ ] Add a test showing skip updates the current concept to unverified without calling an evaluator or blocking run. Add one showing explicit misconception evidence is available in the next turn prompt.
- [ ] Assemble current paper context, current step, bounded recent experiment conversation, bundle assumptions, actual run summary and memo. Distinguish user statements from observed results. Reject model-proposed `supported` status for a skipped answer or an answer without evidence; correct/unsupported claims remain a note rather than a mastery score.
- [ ] For ordinary explanation, return concise Markdown and an updated memo. For code/parameter changes, return a full candidate bundle with source links and exact change explanation. Compare under the same starting state, seed and observation definitions. Changed assumptions require confirmation tied to the candidate hash.
- [ ] Add the same paper's memo and last verified run summary to `_chat_with_agent_impl` before its prompt is sent, so the next normal chat turn also benefits. No memo means no extra text. Do not insert other papers' notes or store the experiment memo in global Settings.
- [ ] Natural-language correction is stored immediately as user-reported evidence. Keep the memo concise, initially at most 12 relevant entries of 300 characters each; these are implementation caps, not proficiency categories. Do not remove the current unresolved concept when compacting.
- [ ] Test a malformed controller update preserves baseline/current, restore returns previous validated state, new assumptions invalidate only the relevant approval, and paper B chat cannot contain paper A memo.

```bash
cd sasoo/backend
./.venv/bin/python -m pytest services/test_experiment_service.py api/test_experiments.py api/test_analysis_routes.py -q
```

**Gate:** a real natural-language change modifies a controller component, not just copy or labels; skip, observed misunderstanding and user correction affect the next explanation as specified.

## Task 6: 실제 앱과 학습 목표 검증

**Files:** Create `output/paper-experiment-mvp/validation.md` and evidence artifacts during implementation. Update `README.md` only after observed behavior matches the shipped feature.

- [ ] Run the repository's frontend type/build/lint and relevant tests, plus backend compile and affected suites. Do not run paid model calls merely to test static wiring.
- [ ] In the actual app test one source-backed robot paper from start through natural-language component change. Use another paper ID to test isolation and a controlled missing-assets case to test failure. No paper-title allowlist or hardcoded successful robot is an implementation shortcut.
- [ ] Capture 1024×680 (Electron minimum), 1280×800 and a wide viewport in both themes. Check keyboard access, tab overflow, memo disclosure, input focus, interrupted preparation, stale responses and console errors. Cross-check a plotted value against the saved runtime series.
- [ ] Measure cold/warm source acquisition, generation, validation, user wait and total elapsed times separately. Report every attempt; an exceeded budget must show failure, not be dropped from timing results. Bundle simulation settings and compared numerical errors with the evidence.
- [ ] Run source-model structural checks and an independent physics check appropriate to the chosen task: joint limits/units, deterministic replay and time-step refinement at minimum. A stable run does not establish robot hardware fidelity; record physical assumptions separately.
- [ ] Check actual learning with a researcher: ask for an unseen-condition prediction and explanation before/after the short course, record elapsed active learning time and the answer evidence. A developer smoke test cannot prove the 20-minute learning target. If no participant is available, mark this outcome unmeasured rather than passing it by inference.

```bash
cd sasoo/frontend
pnpm tsc --noEmit
pnpm test
pnpm build
pnpm lint
```

```bash
cd sasoo/backend
./.venv/bin/python -m py_compile main.py
./.venv/bin/python -m pytest services api models
```

Use the documented macOS packaged smoke flow for final distribution evidence. Windows packaging follows the existing Windows CI path; macOS observations do not prove Windows support.

## Coverage and delivery

| Spec | Tasks |
|---|---|
| R1, R6, R7, R15 | 1, 3, 4, 6 |
| R2, R3, R5 | 3, 5 |
| R4, R8, R16 | 1, 2, 3, 6 |
| R9, R10, R11 | 4, 5, 6 |
| R12, R13, R14 | 2, 5, 6 |

Execution order is 1 → 2 → 3 → 4 → 5 → 6. Each task should be reviewed with its observed outcome before progressing. Commits, when requested, should follow these task boundaries and the repository's existing message style.

The plan is ready for its first executable validation task. It does not assert the chosen engine is already proven in Sasoo or that arbitrary papers can be prepared in five minutes. If Task 1 fails, revise the runtime decision while preserving the confirmed product requirements.
