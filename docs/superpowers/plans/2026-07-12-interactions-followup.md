# Interactions API 후속 전환 플랜 (보조 서비스·스트리밍·레거시 정리)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 본 파이프라인 전환(PR #7)에서 의도적으로 남긴 구식 `generate_content` 경로 — 보조 서비스, 추출 리랭커, 채팅 스트리밍 — 를 Interactions API로 마저 전환하고 `gemini_client.py`(1,020줄)를 제거한다.

**Architecture:** 기존 `services/llm/interactions_client.py`의 `call_interaction`을 유일한 LLM 게이트웨이로 확장한다(스트리밍 변형 1개 추가). 소비자별로 얇게 치환하며, 죽은 코드는 확인 후 삭제한다. 프론트 계약(채팅 SSE 이벤트 스키마)은 변경하지 않는다.

**Tech Stack:** FastAPI + `google-genai` ≥2.3.0 (이미 설치), pytest. 프론트 무변경(채팅 이벤트 계약 유지).

**선행 조사:** 이 플랜의 모든 파일:라인은 2026-07-12 워크트리(`worktree-interactions-api-ux-redesign`, HEAD 8fac361) 기준 전수 조사 결과다. 브랜치가 진행됐다면 라인은 어긋날 수 있으나 심볼명은 유효하다.

## Global Constraints

- 모델: 전환하는 모든 호출은 `gemini-3.5-flash`(텍스트·비전) 또는 `gemini-3.1-flash-lite`(경량 텍스트 분류)만 사용. `-preview` 모델 ID 신규 사용 금지.
- `temperature`/`top_p`/`top_k`/`thinking_budget` 금지. `types.*` 래퍼 금지(plain dict).
- `call_interaction` 반환 키 `{"text","model","tokens_in","tokens_out","tokens_thought","interaction_id"}` 불변 — 확장은 키 추가로만.
- 채팅 SSE 이벤트 스키마 불변: `{"type":"token","content"}` / `{"type":"done","tokens_in","tokens_out","cost_usd"}` / `{"type":"error","message"}` — 프론트 `chatWithAgent`(`lib/api.ts` L654-716)는 손대지 않는다.
- 삭제는 참조 0건을 grep으로 확인한 뒤에만. `.superpowers/` 파일은 커밋 금지.
- 테스트: `cd sasoo/backend && .venv 인터프리터(/Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv)로 python3 -m pytest -q` — 시작 기준 **87 passed**, 태스크마다 무회귀.
- 커밋 메시지 끝에 `Co-Authored-By:` 트레일러 (세션 규칙 준수).
- **스트리밍 이벤트 실계약**: Task 2 시작 전 `.agents/skills/gemini-interactions-api/SKILL.md`의 Streaming 절과 https://ai.google.dev/gemini-api/docs/interactions/streaming.md.txt 를 읽고 `step.delta`/`interaction.completed` 필드명을 확인할 것 (`# VERIFY:` 주석 지점).

## 사용자 결정 필요 (실행 세션 시작 시 1회 질문)

1. **VizRouter 삭제 여부** — `services/viz/viz_router.py`는 어디서도 인스턴스화되지 않는 고아 코드(주석 참조만 존재). 권장: 삭제. 유지 결정 시 Task 5에서 전환 대상에 포함.
2. **DomainRouter 시맨틱 폴백** — `domain_router.py:83`이 `DomainRouter()`를 gemini 없이 생성해 시맨틱 분류가 사실상 비활성. 권장: 이번에 `call_interaction` 기반으로 **살려서 배선**(스크리닝 분야 감지의 백업 경로). 대안: 죽은 상태 그대로 코드만 정리.

---

### Task 1: 라이브 API 계약 확인 (게이트)

PR #7이 미검증으로 남긴 실 API 계약을 확인한다. **이후 태스크의 전제.**

**Files:** 수정 없음 (확인만). 결과는 `.superpowers/sdd/live-contract-notes.md`(로컬)에 기록.

- [ ] **Step 1:** 앱(또는 `GEMINI_API_KEY` 환경변수)을 통해 키를 확보한다. 앱 DB 키는 OS 키체인 복호화가 필요하므로, 실행 세션에서는 사용자에게 `! export GEMINI_API_KEY=...` 또는 앱 설정 화면 확인을 요청하는 편이 빠르다.
- [ ] **Step 2:** 논문 1건 업로드→분석 완료까지 실행 (uvicorn 기동 후 실제 파이프라인). 확인 항목:
  - document dict(`{"type":"document","uri":...}`)와 `response_format` 스키마가 라이브에서 수용되는지
  - `analysis_results.interaction_id`가 체인 스테이지에 채워지는지
  - `usage.total_thought_tokens`가 실제로 오는지, `total_output_tokens`에 thinking이 **포함**되는지 (deep_dive의 tokens_out vs tokens_thought 비교)
- [ ] **Step 3:** thinking 포함 여부에 따라 비용 처리 확정:
  - 포함이면: 현행 유지 (`tokens_thought`는 breakdown 기록용).
  - 미포함이면: `calc_cost` 호출부들이 `tokens_out + tokens_thought`로 output 비용을 계산하도록 수정 + 테스트 갱신. (수정 지점: `analysis_routes.py`의 `calc_cost(result["model"], ...)` 호출 전부 — grep `calc_cost(result`)
- [ ] **Step 4:** 결과를 커밋 (비용 수정이 있었으면 코드+테스트, 없었으면 이 플랜 문서에 확인 완료 표기만).

### Task 2: interactions_client에 스트리밍 추가 + 채팅 SSE 전환

**Files:**
- Modify: `sasoo/backend/services/llm/interactions_client.py` (신규 함수 추가)
- Modify: `sasoo/backend/api/analysis_routes.py` L2735-2888 (`_CHAT_MODEL`, `_chat_with_agent_impl`)
- Test: `sasoo/backend/services/llm/test_interactions_client.py`, `sasoo/backend/api/test_analysis_routes.py`

**Interfaces:**
- Produces: `async def stream_interaction(prompt, *, model="gemini-3.5-flash", system_instruction=None, thinking_level=None, previous_interaction_id=None, store=True) -> AsyncIterator[dict]` — yield `{"type":"token","text":str}` 반복 후 마지막에 `{"type":"done","tokens_in":int,"tokens_out":int,"tokens_thought":int,"interaction_id":str|None}`.

- [ ] **Step 1: 실패하는 테스트** — `client.interactions.create(stream=True)`를 목킹(이벤트 리스트를 yield하는 fake)해 (a) `step.delta`의 text delta가 token으로 흘러나오는지, (b) `interaction.completed`에서 usage가 done 이벤트로 변환되는지, (c) sync 제너레이터가 이벤트 루프를 막지 않는지(executor+Queue 패턴 — 기존 `_chat_with_agent_impl`의 asyncio.Queue 관용구 재사용) 검증.
- [ ] **Step 2: 구현** — `# VERIFY:` 스트리밍 이벤트 필드는 skill 문서 기준: `event.event_type == "step.delta"` + `event.delta.type == "text"` + `event.delta.text`, 종료는 `event.event_type == "interaction.completed"` + `event.interaction.usage`. sync SDK 스트림을 스레드에서 돌리고 `asyncio.Queue`로 브릿지(기존 L2836-2869 패턴 그대로 이동).
- [ ] **Step 3: 채팅 전환** — `_chat_with_agent_impl`에서 `_get_gemini_client()`/`generate_content_stream`/`types.Content` 조립을 제거하고 `stream_interaction` 사용. `_CHAT_MODEL = "gemini-3.5-flash"`. 히스토리는 현행처럼 매 요청 텍스트로 조립(stateless, `store=False`)을 유지하되, 후속 개선으로 paper 체인 `interaction_id`를 `previous_interaction_id`로 잇는 stateful 모드를 주석으로 남긴다(이번 범위 아님 — 프론트 히스토리 계약 변경 필요). SSE 이벤트 스키마는 기존 그대로 유지.
- [ ] **Step 4:** pytest 무회귀 + (키 있으면) 실채팅 1회 스모크. 커밋.

### Task 3: 이미지 입력 소비자 전환 — subfigure_detector, figure/table_resolver

**Files:**
- Modify: `sasoo/backend/services/subfigure_detector.py` L83-159
- Modify: `sasoo/backend/services/figure_resolver.py` L277, L337 / `sasoo/backend/services/table_resolver.py` L185
- Modify: `sasoo/backend/api/analysis_helpers.py` (`_call_gemini` 삭제 — 이 태스크 후 소비자 0)
- Test: 각 서비스의 기존 테스트 + 신규 목킹 테스트

**Interfaces:**
- Consumes: `call_interaction`은 이미 content dict 리스트를 받는다(figure_service.py L562의 base64 이미지 패턴 참조: `{"type":"image","data":<base64>,"mime_type":...}`).

- [ ] **Step 1:** `subfigure_detector.detect_subfigures`의 `client.generate_with_image(...)` 호출을 `call_interaction([{"type":"image","data":image_base64,"mime_type":"image/png"},{"type":"text","text":prompt}], model="gemini-3.5-flash", thinking_level="minimal", store=False)`로 치환. 반환 파싱(정규식 JSON)은 유지하되 가능하면 `response_schema`로 대체.
- [ ] **Step 2:** figure_resolver 2곳·table_resolver 1곳의 `_call_gemini(prompt, model="gemini-3-flash-preview", thinking_level="minimal", image_paths=[...])`를 치환: 파일을 읽어 base64 인코딩 후 위 content dict 패턴 + `model="gemini-3.5-flash"`. 각 호출부의 `GEMINI_API_KEY` 부재 시 스킵/heuristic 폴백과 `except Exception` 흡수 동작은 그대로 유지.
- [ ] **Step 3:** `_call_gemini` 참조가 0이 됐는지 grep 확인 후 `analysis_helpers.py`에서 삭제 (`_get_gemini_client`는 Task 2에서 이미 소비자 0이면 함께 삭제 — grep으로 판정).
- [ ] **Step 4:** pytest 무회귀. 커밋.

### Task 4: 텍스트 소비자 전환 — naming_service, domain_router

**Files:**
- Modify: `sasoo/backend/services/naming_service.py` L36-181 (3개 함수)
- Modify: `sasoo/backend/services/domain_router.py` L83, L91, L269-275
- Test: 기존 + 신규 목킹 테스트

- [ ] **Step 1:** naming_service의 `GeminiClient()._call(...)`+`_response_text(...)` 3곳을 `call_interaction(prompt, model="gemini-3.1-flash-lite", thinking_level="minimal", store=False)`로 치환 (`generate_figure_names`는 `response_schema` 사용 — 기존 `response_mime_type="application/json"` 대체).
- [ ] **Step 2:** domain_router — 사용자 결정(위 결정 2)에 따라:
  - 살리는 경우: `classify_domain` 로직을 `call_interaction(..., model="gemini-3.1-flash-lite", response_schema={domain,...}, store=False)` 기반의 로컬 함수로 옮기고 `DomainRouter()` 생성부(L83)에서 활성 배선 + `needs_confirmation` 폴백 유지.
  - 정리만 하는 경우: `_semantic_classify`의 GeminiClient 의존 제거(항상 `needs_confirmation=True` 경로만 유지)하고 생성자 파라미터 삭제.
- [ ] **Step 3:** pytest 무회귀. 커밋.

### Task 5: gemini_client.py 및 고아 코드 제거

**Files:**
- Delete: `sasoo/backend/services/llm/gemini_client.py` (UsageTracker/UsageRecord 포함 — 정의처가 여기뿐임을 grep 재확인)
- Delete(사용자 승인 시): `sasoo/backend/services/viz/viz_router.py`
- Modify: `sasoo/backend/services/pricing.py` — 이 시점에 `gemini-3-flash-preview` 참조가 0이면 해당 가격 항목 제거 (`gemini-3.1-pro-preview`·이미지 모델 항목은 paperbanana_bridge 등 잔존 참조 확인 후 판단)
- Modify: `sasoo/backend/services/agents/base_agent.py` L49 — GeminiClient 언급 docstring 주석 정리

- [ ] **Step 1:** `grep -rn "gemini_client\|GeminiClient\|UsageTracker" sasoo/backend --include="*.py"` → 참조 0건 확인 후 `git rm`. 남아 있으면 해당 소비자를 먼저 처리(Task 3·4 누락분).
- [ ] **Step 2:** `grep -rn "gemini-3-flash-preview" sasoo/backend --include="*.py"` → 0건이면 pricing 항목 제거.
- [ ] **Step 3:** `python3 -c "import main"` + pytest 무회귀. 커밋.

### Task 6: 최종 회귀 + 정리

- [ ] **Step 1:** 전체 pytest + 프론트 `npm run build`.
- [ ] **Step 2:** 잔재 검증: `grep -rn "generate_content" sasoo/backend --include="*.py" | grep -v test_ | grep -v ".venv"` → paperbanana_bridge 주석 외 0건이 목표.
- [ ] **Step 3:** (키 있으면) 논문 1건 재분석 + 채팅 1회 + 피규어 추출 확인 E2E.
- [ ] **Step 4:** 커밋, 푸시, PR 갱신(또는 신규 PR — PR #7 병합 이후라면 새 브랜치).

## Self-Review 결과

- 조사에서 확인된 살아있는 구식 경로 전부가 태스크에 배정됨: 채팅 스트리밍(Task 2), subfigure/figure/table 비전(Task 3), naming/domain 텍스트(Task 4), 본체 삭제(Task 5). 죽은 코드(analyze_* 등)는 Task 5의 파일 삭제로 일괄 소멸.
- 타입 일관성: 모든 치환이 `call_interaction`의 기존 반환 키만 사용. 스트리밍 신규 함수는 별도 이벤트 dict(채팅 SSE 스키마와 1:1 변환 가능)로 분리.
- 미확정 지점 2건(VizRouter 삭제, DomainRouter 활성화)은 사용자 결정 섹션에 명시 — 실행 세션이 시작 시 1회 질문으로 해소.
