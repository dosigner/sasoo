# AI 공급사 선택 — 백엔드 LLM 프로바이더 중립화 구현 플랜 (개정 1 반영)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** OpenAI 키 단독 사용자도 sasoo의 전체 LLM 기능(분석 5단계·채팅 스트리밍·그림 설명·Mermaid·리졸버·네이밍)이 동작하게 한다.

**Architecture:** `services/llm/`을 gateway 구조(base + gemini_client + openai_client)로 재편하되, 기존 모듈명 `interactions_client`를 프로바이더 라우팅 셔션(façade)으로 유지해 호출부 12곳의 import를 한 줄도 바꾸지 않는다. 모델 선택은 `model_registry.resolve(role, provider)`로 일원화하고, OpenAI 체인은 PDF 업로드 없이 로컬 추출 텍스트 1회 주입 + `previous_response_id`로 잇는다.

**Tech Stack:** FastAPI, google-genai(Interactions API), openai SDK(Responses API), pytest(unittest 스타일)

**전제:**
- 스펙: `docs/superpowers/specs/2026-07-31-ai-provider-selection-design.md` — **하단 "개정 1"(R1~R10)이 원안·구플랜과 충돌 시 우선한다.**
- 구플랜(`2026-08-01-ai-provider-selection.md`)의 Task 4(ai_provider 설정)·Task 10(키 상태 머신)·Task 10b의 설정 미러·Task 11~13(UI)은 **이미 main에 병합 완료** — 이 플랜에서 재실행하지 않는다.
- 이 플랜의 실행 순서는 스펙 R10을 따른다: 스파이크 → 게이트웨이 → 레지스트리 → 가격 → 캐시 키 → OpenAI 클라이언트 → 스트리밍 → stateless 배선 → 체인 → 배지 → 측정 도구.

## Global Constraints

- lane을 명시하지 않는 LLM 호출을 만들지 않는다. 기본값을 두면 2026-07-11 채팅 SSE 무한 대기 사고가 재발한다.
- `store=False`인데 체인 ID(`previous_interaction_id`/`previous_response_id`)를 넘기면 `ValueError`를 올리는 방어를 양쪽 클라이언트 모두 유지한다.
- 파이프라인 세마포어는 루프별로 생성한다(크로스루프 바인딩 방지). `services/concurrency.py`의 구조를 바꾸지 않는다.
- 재시도 루프의 예외 포획은 `except Exception`으로 한다. `BaseException`은 `asyncio.CancelledError`까지 잡아 취소된 태스크를 재시도하는 버그가 된다(스펙 R5-3).
- OpenAI `usage.output_tokens`는 reasoning 토큰을 **이미 포함**한다 — `reasoning_tokens`를 다시 더하지 않는다(스펙 R7-2). Gemini는 반대로 `output + thought` 합산이 맞다(현행 유지).
- deep_dive의 OpenAI effort는 `high`다. `xhigh`를 쓰지 않는다(스펙 R3).
- OpenAI 경로는 Files API에 PDF를 업로드하지 않는다(스펙 R1). `papers.pdf_file_uri`는 Gemini 전용이다.
- 기존 Gemini 동작은 Task 9 이전까지 바이트 단위로 동일해야 한다(순수 리팩터). 각 태스크 완료 시 백엔드 전체 테스트(`.venv/bin/python -m pytest -q`, sasoo/backend에서)가 통과해야 한다.
- 커밋 메시지는 한국어, 본문에 왜를 적는다. 작업 브랜치: `feat/provider-neutral-llm` (origin/main에서 분기).

## File Structure

```
backend/services/llm/
  base.py                  신규 — Lane, LLMResponse, LLMClient 프로토콜
  gemini_client.py         기존 interactions_client.py 개명 (구현 무수정)
  openai_client.py         신규 — Responses API (파트 번역기·스트리밍 포함)
  interactions_client.py   셔션으로 재작성 — 모델 접두사로 라우팅. 호출부 12곳 무수정
backend/services/model_registry.py   신규 — provider × role → (model, effort)
backend/services/models.py           수정 — MODEL_LUNA 상수 추가
backend/services/pricing.py          수정 — Luna 단가, provider별 폴백
backend/services/document_context.py 수정 — compute_input_hash에 provider/model/effort
backend/api/analysis_routes.py       수정 — 레지스트리 조회, 캐시 키, OpenAI 텍스트 체인
backend/tools/openai_spike.py        신규 — 구현 전 검증 스파이크 (R8)
backend/tools/provider_compare.py    수정 — 5단계 전체 + 결함율·토큰 상세 기록 (R9)
```

---

## Task 0: OpenAI 실측 검증 스파이크 (R8)

설계 가정 7건을 소형 스크립트로 실측한다. **이 태스크의 산출물은 코드가 아니라 "확정된 사실"이다** — 결과를 이 플랜의 체크박스에 기록하고, 어긋난 가정은 해당 태스크를 수정한 뒤 진행한다.

**Files:**
- Create: `backend/tools/openai_spike.py`

**Interfaces:**
- Consumes: `OPENAI_API_KEY` 환경변수
- Produces: 실측 결과 JSON(stdout) + 아래 체크박스 기록

- [ ] **Step 1: 스파이크 스크립트 작성**

`backend/tools/openai_spike.py`:

```python
"""OpenAI Responses API 실측 스파이크 — 스펙 개정 1 R8.

프로덕션 코드를 건드리지 않는 일회용 도구(extraction_audit 관례).
실행: OPENAI_API_KEY=... .venv/bin/python tools/openai_spike.py
각 검사는 독립적으로 실패할 수 있다 — 전부 돌고 결과를 JSON으로 출력한다.
"""

import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MODEL = os.environ.get("SPIKE_MODEL", "gpt-5.6-luna")

# 프로덕션 스키마를 그대로 가져와 strict:false 준수율을 본다 (R8-3)
from api.analysis_routes import _SCREENING_SCHEMA  # noqa: E402

RESULTS: dict = {"model": MODEL}


def check(name):
    def deco(fn):
        def run():
            try:
                RESULTS[name] = {"ok": True, "detail": fn()}
            except Exception as exc:  # noqa: BLE001 - 스파이크는 전 결과 수집이 목적
                RESULTS[name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                                 "trace": traceback.format_exc(limit=3)}
        return run
    return deco


def _client():
    from openai import OpenAI
    return OpenAI()


@check("1_chain_previous_response_id")
def spike_chain():
    """store=True 체인: 첫 턴 텍스트가 후속 턴에 유지되는가 (R8-1)."""
    c = _client()
    r1 = c.responses.create(
        model=MODEL, store=True,
        input="비밀 코드는 SASOO-7291 이다. 기억해라. '확인'이라고만 답해라.",
    )
    r2 = c.responses.create(
        model=MODEL, store=True, previous_response_id=r1.id,
        input="아까 말한 비밀 코드가 뭐였지? 코드만 답해라.",
    )
    recalled = "SASOO-7291" in (r2.output_text or "")
    return {"r1_id": r1.id, "recalled_first_turn": recalled}


@check("2_reasoning_effort_values")
def spike_effort():
    """effort 지원 값 집합 — 특히 minimal (R8-2, R4 확정 조건)."""
    c = _client()
    out = {}
    for effort in ("minimal", "low", "medium", "high", "xhigh"):
        try:
            c.responses.create(model=MODEL, input="1+1은? 숫자만.",
                               reasoning={"effort": effort})
            out[effort] = "supported"
        except Exception as exc:  # noqa: BLE001
            out[effort] = f"rejected: {type(exc).__name__}"
    return out


@check("3_strict_false_schema")
def spike_schema():
    """프로덕션 스키마 그대로 strict:false 전송 → 파싱·준수 확인 (R8-3)."""
    c = _client()
    r = c.responses.create(
        model=MODEL,
        input="광섬유 브래그 격자 센서 논문이라고 가정하고 스크리닝 결과를 채워라.",
        text={"format": {"type": "json_schema", "name": "screening",
                         "schema": _SCREENING_SCHEMA, "strict": False}},
    )
    data = json.loads(r.output_text)
    missing = [k for k in _SCREENING_SCHEMA["required"] if k not in data]
    return {"parsed": True, "missing_required": missing}


@check("4_streaming_events")
def spike_stream():
    """스트리밍 이벤트명과 usage 수신 (R8-4)."""
    c = _client()
    events = set()
    usage = None
    with c.responses.stream(model=MODEL, input="하늘이 파란 이유를 두 문장으로.") as s:
        for ev in s:
            events.add(ev.type)
            if ev.type == "response.completed":
                usage = getattr(ev.response, "usage", None)
    return {"event_types": sorted(events),
            "usage_present": usage is not None,
            "output_tokens": getattr(usage, "output_tokens", None),
            "reasoning_tokens": getattr(
                getattr(usage, "output_tokens_details", None), "reasoning_tokens", None)}


@check("5_image_part")
def spike_image():
    """이미지 파트(base64 data URL) 입력 — 리졸버 경로 등가 (R8-7)."""
    import base64
    # 1x1 PNG
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQAB"
        "h6FO1AAAAABJRU5ErkJggg==")
    c = _client()
    r = c.responses.create(model=MODEL, input=[{
        "role": "user",
        "content": [
            {"type": "input_image",
             "image_url": f"data:image/png;base64,{base64.b64encode(png).decode()}"},
            {"type": "input_text", "text": "이 이미지의 크기를 추정해라. 한 문장."},
        ]}])
    return {"answered": bool(r.output_text)}


@check("6_refusal_and_incomplete_shape")
def spike_incomplete():
    """max_output_tokens 도달 시 응답 형태 (R8-6)."""
    c = _client()
    r = c.responses.create(model=MODEL, input="1부터 500까지 세라.", max_output_tokens=32)
    return {"status": getattr(r, "status", None),
            "incomplete_reason": getattr(getattr(r, "incomplete_details", None), "reason", None)}


if __name__ == "__main__":
    for fn_name in sorted(k for k in dir() if k.startswith("spike_")):
        pass  # check 데코레이터가 등록 시 즉시 실행하지 않으므로 아래에서 명시 호출
    for runner in (spike_chain, spike_effort, spike_schema, spike_stream,
                   spike_image, spike_incomplete):
        runner()
    print(json.dumps(RESULTS, ensure_ascii=False, indent=2))
```

- [ ] **Step 2: 실행**

```bash
cd sasoo/backend && OPENAI_API_KEY=$OPENAI_API_KEY .venv/bin/python tools/openai_spike.py
```

Expected: 6개 검사 결과 JSON. 실패한 검사는 error에 원인이 남는다.

- [ ] **Step 3: 결과를 기록하고 후속 태스크를 보정**

아래 체크박스에 실측값을 기입한다(플랜 파일을 직접 수정).

- [ ] 체인 유지: (기록: __________) — 실패 시 Task 10을 stateless 폴백 전용으로 강등
- [ ] effort 값 집합: (기록: __________) — `minimal` 미지원이면 Task 3의 OpenAI 열에서 `minimal` → `low`
- [ ] strict:false 준수: missing_required=(기록: __________)
- [ ] 스트리밍 이벤트명: (기록: __________) — `response.output_text.delta`가 아니면 Task 8 수정
- [ ] reasoning_tokens 위치: (기록: __________)
- [ ] 이미지 파트: (기록: __________)

- [ ] **Step 4: Luna 공식 단가 확인 (R7-5 게이트)**

스펙 원안($0.20/$1.20)과 자문 제시값($1/$6)이 5배 어긋난다. 공식 가격 페이지
(https://platform.openai.com/docs/pricing)에서 `gpt-5.6-luna`의 input/output/cached
단가를 확인해 기록한다: (기록: input $______ / output $______ / cached $______)
→ 이 값이 Task 5의 `PRICING` 항목에 들어간다.

- [ ] **Step 5: Commit**

```bash
git checkout -b feat/provider-neutral-llm origin/main
git add backend/tools/openai_spike.py
git commit -m "tools: OpenAI Responses API 실측 스파이크

스펙 개정 1 R8 — 체인·effort·strict:false·스트리밍·이미지 파트·단가를
구현 전에 실측해 설계 가정을 확정한다. 프로덕션 코드 무수정."
```

---

## Task 1: provider 중립 공통 타입 (`base.py`)

**Files:**
- Create: `backend/services/llm/base.py`
- Test: `backend/services/llm/test_base.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `Lane = Literal["chat", "pipeline"]`
  - `@dataclass(slots=True) class LLMResponse` — 필드 `text: str`, `interaction_id: str | None`, `tokens_in: int`, `tokens_out: int`, `model: str`
  - `class LLMClient(Protocol)` — `available() -> bool`, `async call(**kwargs) -> LLMResponse`, `async stream(**kwargs)`
  - **주의:** `upload_pdf`는 공통 계약에 넣지 않는다 — R1로 OpenAI는 업로드가 없다. Gemini 전용 함수로 남긴다.

- [ ] **Step 1: Write the failing test**

`backend/services/llm/test_base.py`:

```python
import unittest

from services.llm.base import LLMResponse, LLMClient


class TestLLMResponse(unittest.TestCase):
    def test_holds_call_result_fields(self):
        resp = LLMResponse(
            text='{"ok": true}',
            interaction_id="resp_abc",
            tokens_in=100,
            tokens_out=20,
            model="gemini-3.6-flash",
        )
        self.assertEqual(resp.text, '{"ok": true}')
        self.assertEqual(resp.interaction_id, "resp_abc")
        self.assertEqual(resp.tokens_in, 100)
        self.assertEqual(resp.tokens_out, 20)
        self.assertEqual(resp.model, "gemini-3.6-flash")

    def test_interaction_id_is_optional(self):
        resp = LLMResponse(text="hi", interaction_id=None, tokens_in=1, tokens_out=1, model="m")
        self.assertIsNone(resp.interaction_id)


class TestLLMClientProtocol(unittest.TestCase):
    def test_conforming_stub_passes_isinstance(self):
        class Stub:
            def available(self) -> bool:
                return True

            async def call(self, **kwargs) -> LLMResponse:
                return LLMResponse(text="", interaction_id=None, tokens_in=0, tokens_out=0, model="m")

            async def stream(self, **kwargs):
                yield ""

        self.assertIsInstance(Stub(), LLMClient)

    def test_missing_method_fails_isinstance(self):
        class Incomplete:
            def available(self) -> bool:
                return True

        self.assertNotIsInstance(Incomplete(), LLMClient)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd sasoo/backend && .venv/bin/python -m pytest services/llm/test_base.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'services.llm.base'`

- [ ] **Step 3: Write minimal implementation**

`backend/services/llm/base.py`:

```python
"""Sasoo - provider 중립 LLM 인터페이스.

Gemini(Interactions API)와 OpenAI(Responses API)를 같은 모양으로 다루기 위한
공통 타입. 두 provider의 개념은 1:1로 대응된다:

    서버측 체인   previous_interaction_id  <-> previous_response_id
    사고량 조절   thinking_level           <-> reasoning.effort

PDF 업로드는 공통 계약이 아니다 — OpenAI 경로는 파일을 업로드하지 않고
로컬 추출 텍스트를 첫 호출에 주입한다(스펙 개정 1 R1). upload_pdf_for_paper는
gemini_client 전용 함수로 남는다.

lane 분리와 세마포어는 provider와 무관하므로 각 구현이 services.concurrency의
공용 풀을 쓴다.
"""

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

# 모든 호출은 lane을 명시해야 한다 — 기본값을 두지 않는 것이 핵심이다.
#   "chat"     : 사용자가 실시간으로 기다리는 대화형 경로.
#   "pipeline" : 분석 파이프라인. 전용 풀 + 루프별 세마포어.
Lane = Literal["chat", "pipeline"]


@dataclass(slots=True)
class LLMResponse:
    """한 번의 LLM 호출 결과. provider가 무엇이든 이 모양으로 돌려준다."""

    text: str
    interaction_id: str | None
    tokens_in: int
    tokens_out: int
    model: str


@runtime_checkable
class LLMClient(Protocol):
    """provider 구현이 만족해야 하는 계약."""

    def available(self) -> bool:
        """API 키가 있어 호출 가능한 상태인지."""
        ...

    async def call(self, **kwargs) -> LLMResponse:
        ...

    async def stream(self, **kwargs):
        ...
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd sasoo/backend && .venv/bin/python -m pytest services/llm/test_base.py -v
```

Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/services/llm/base.py backend/services/llm/test_base.py
git commit -m "feat(llm): provider 중립 공통 타입

LLMResponse·LLMClient 프로토콜. upload_pdf는 공통 계약에서 제외 —
OpenAI 경로는 파일 업로드 없이 텍스트 주입 체인을 쓴다(스펙 R1)."
```

---

## Task 2: `interactions_client` → `gemini_client` 개명 + 셔션 유지

핵심 트릭: 호출부 12곳이 전부 `services.llm.interactions_client`를 import하므로,
**모듈명을 셔션으로 유지**하면 import를 한 줄도 안 바꾼다. 이번 태스크의 셔션은
gemini_client 재노출뿐이다(동작 무변경). Task 9에서 라우팅이 들어간다.

**Files:**
- Rename: `backend/services/llm/interactions_client.py` → `backend/services/llm/gemini_client.py`
- Create: `backend/services/llm/interactions_client.py` (셔션으로 재작성)
- Rename: `backend/services/llm/test_interactions_client.py` → `backend/services/llm/test_gemini_client.py`

**Interfaces:**
- Consumes: 기존 `interactions_client`의 공개 이름 전부
- Produces: `interactions_client` 모듈이 같은 이름을 계속 노출 — `call_interaction`, `stream_interaction`, `upload_pdf_for_paper`, `_SYSTEM_INSTRUCTION_KO`, `Lane`

- [ ] **Step 1: git mv로 개명**

```bash
cd sasoo/backend
git mv services/llm/interactions_client.py services/llm/gemini_client.py
git mv services/llm/test_interactions_client.py services/llm/test_gemini_client.py
```

- [ ] **Step 2: test_gemini_client.py 내부의 모듈 참조 치환**

```bash
# patch("services.llm.interactions_client....") 형태를 gemini_client로 바꾼다
grep -n "interactions_client" services/llm/test_gemini_client.py
```

나온 모든 줄에서 `interactions_client` → `gemini_client`로 치환한다(Edit).

- [ ] **Step 3: 셔션 작성**

`backend/services/llm/interactions_client.py` (신규):

```python
"""Sasoo - LLM 호출 셔션(façade).

역사적 이름을 유지한다 — 호출부 12곳(analysis_routes, figure_service,
리졸버 3종, subfigure_detector, naming_service, figure_gen, gemini_parser,
analysis_helpers, analysis_context, vlm_probe)이 이 모듈 경로를 import한다.

지금은 gemini_client 재노출뿐이다. provider 라우팅(모델 접두사 기반)은
openai_client가 준비된 뒤 이 파일에 들어온다 — 그 전까지 동작은 바이트
단위로 동일해야 한다.
"""

from services.llm.gemini_client import (  # noqa: F401
    Lane,
    _SYSTEM_INSTRUCTION_KO,
    call_interaction,
    stream_interaction,
    upload_pdf_for_paper,
)
```

주의: `gemini_client.py` 안에서 위 5개 이름이 실제로 정의돼 있는지 먼저 확인한다
(`grep -n "^def \|^async def \|^_SYSTEM_INSTRUCTION_KO\|^Lane" services/llm/gemini_client.py`).
정의 목록이 다르면 셔션의 import 목록을 실제 공개 이름에 맞춘다.

- [ ] **Step 4: 전체 테스트로 회귀 확인**

```bash
cd sasoo/backend && .venv/bin/python -m pytest -q
```

Expected: 기존 전체 통과(현재 516개 + 서브테스트). 실패하면 대부분
`patch("services.llm.interactions_client.X")` 경로 문제다 — 테스트가 셔션이 아니라
gemini_client 내부를 patch해야 하는 경우 경로를 `services.llm.gemini_client.X`로 바꾼다.
단, **호출부 모듈이 `from ... import call_interaction`으로 이름을 복사해 갔으므로
`patch("api.analysis_routes.call_interaction")` 같은 사용처-기준 patch는 그대로 동작한다.**

- [ ] **Step 5: Commit**

```bash
git add -A backend/services/llm/
git commit -m "refactor(llm): interactions_client를 gemini_client로 개명, 셔션 유지

모듈명을 셔션으로 남겨 호출부 12곳의 import 무수정. provider 라우팅은
openai_client 완성 후 셔션에 들어온다. 동작 무변경."
```

---

## Task 3: provider × role 모델 레지스트리 (R4 — role 전체 커버)

phase마다 (모델, effort)를 돌려주는 단일 소스. 구플랜 Task 3에서 **누락됐던
role 5종(figure_resolver, table_resolver, subfigure, naming, viz_image_plan)을
추가**하고, Gemini 열을 실동작과 정확히 일치시킨다(구플랜은 screening effort를
None으로 적었지만 실코드는 `thinking_level="minimal"`이다 — analysis_routes.py:456).

**Files:**
- Create: `backend/services/model_registry.py`
- Modify: `backend/services/models.py` (MODEL_LUNA 상수 추가)
- Test: `backend/services/test_model_registry.py`

**Interfaces:**
- Consumes: `services.models`의 기존 상수
- Produces:
  - `Provider = Literal["openai", "gemini"]`
  - `@dataclass(frozen=True, slots=True) class ModelChoice` — 필드 `model: str`, `effort: str | None`
  - `resolve(role: str, provider: str) -> ModelChoice` — 알 수 없는 role/provider면 `KeyError`
  - `ROLES: tuple[str, ...]`
  - 유효 role: `screening`, `visual`, `citation`, `recipe`, `deep_dive`, `viz_planning`, `mermaid`, `chat`, `figure_explain`, `figure_resolver`, `table_resolver`, `subfigure`, `naming`, `viz_image_plan`, `image`

- [ ] **Step 1: models.py에 상수 추가**

`backend/services/models.py`의 `# Text models` 블록에 추가:

```python
# OpenAI 텍스트 모델 — provider 중립화(스펙 2026-07-31 + 개정 1)
MODEL_LUNA = "gpt-5.6-luna"
```

- [ ] **Step 2: Write the failing test**

`backend/services/test_model_registry.py`:

```python
import unittest

from services.model_registry import ModelChoice, ROLES, resolve


class TestGeminiColumnMatchesProduction(unittest.TestCase):
    """Gemini 열은 기존 실동작의 이식이다 — 값이 다르면 동작 변경이므로 버그다."""

    def test_screening_flash_lite_minimal(self):
        choice = resolve("screening", "gemini")
        self.assertEqual(choice.model, "gemini-3.5-flash-lite")
        self.assertEqual(choice.effort, "minimal")  # analysis_routes.py:456 실값

    def test_citation_low(self):
        self.assertEqual(resolve("citation", "gemini").effort, "low")

    def test_chain_stages(self):
        self.assertEqual(resolve("visual", "gemini").effort, "low")
        self.assertEqual(resolve("recipe", "gemini").effort, "medium")
        self.assertEqual(resolve("deep_dive", "gemini").effort, "high")
        self.assertEqual(resolve("viz_planning", "gemini").effort, "medium")

    def test_resolvers_minimal(self):
        for role in ("figure_resolver", "table_resolver", "subfigure"):
            with self.subTest(role=role):
                choice = resolve(role, "gemini")
                self.assertEqual(choice.model, "gemini-3.6-flash")
                self.assertEqual(choice.effort, "minimal")

    def test_naming_flash_lite(self):
        self.assertEqual(resolve("naming", "gemini").model, "gemini-3.5-flash-lite")

    def test_figure_explain_high(self):
        self.assertEqual(resolve("figure_explain", "gemini").effort, "high")

    def test_viz_image_plan_uses_pro(self):
        self.assertEqual(resolve("viz_image_plan", "gemini").model, "gemini-3.1-pro-preview")


class TestOpenAIColumn(unittest.TestCase):
    def test_deep_dive_is_high_not_xhigh(self):
        """스펙 개정 R3 — xhigh 금지."""
        self.assertEqual(resolve("deep_dive", "openai").effort, "high")

    def test_all_openai_text_roles_use_luna(self):
        for role in ROLES:
            if role == "image":
                continue
            with self.subTest(role=role):
                self.assertEqual(resolve(role, "openai").model, "gpt-5.6-luna")

    def test_no_role_uses_xhigh(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.assertNotEqual(resolve(role, "openai").effort, "xhigh")


class TestRegistryShape(unittest.TestCase):
    def test_unknown_role_raises(self):
        with self.assertRaises(KeyError):
            resolve("no_such_role", "gemini")

    def test_unknown_provider_raises(self):
        with self.assertRaises(KeyError):
            resolve("deep_dive", "anthropic")

    def test_both_providers_cover_same_roles(self):
        from services.model_registry import _REGISTRY
        self.assertEqual(set(_REGISTRY["gemini"]), set(_REGISTRY["openai"]))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd sasoo/backend && .venv/bin/python -m pytest services/test_model_registry.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'services.model_registry'`

- [ ] **Step 4: Write implementation**

`backend/services/model_registry.py`:

```python
"""Sasoo - provider x role 모델 레지스트리.

phase가 어떤 모델을 어느 사고량으로 돌릴지 한곳에서 정한다.
services/models.py가 "무엇이 있는가"라면 여기는 "언제 무엇을 쓰는가"다.

effort는 provider 중립 인자다. Gemini 경로는 thinking_level로, OpenAI 경로는
reasoning.effort로 전달된다. Gemini 열은 기존 실동작(각 호출부의 model/
thinking_level 실값)의 이식이므로 바꾸면 동작 변경이다.

OpenAI 열 원칙(스펙 개정 1 R3/R4): 모델은 Luna 하나, effort만 변주.
deep_dive는 high까지(xhigh 금지). screening·리졸버·naming은 최저 사고량 —
스파이크(Task 0)에서 minimal 미지원이 확인되면 low로 바꾼다.
"""

from dataclasses import dataclass
from typing import Literal

from services.models import (
    MODEL_FLASH_HQ,
    MODEL_FLASH_LITE,
    MODEL_IMAGE,
    MODEL_IMAGE_OPENAI,
    MODEL_LUNA,
    MODEL_PRO,
)

Provider = Literal["openai", "gemini"]


@dataclass(frozen=True, slots=True)
class ModelChoice:
    model: str
    effort: str | None


_REGISTRY: dict[str, dict[str, ModelChoice]] = {
    "gemini": {
        "screening": ModelChoice(MODEL_FLASH_LITE, "minimal"),
        "visual": ModelChoice(MODEL_FLASH_HQ, "low"),
        "citation": ModelChoice(MODEL_FLASH_HQ, "low"),
        "recipe": ModelChoice(MODEL_FLASH_HQ, "medium"),
        "deep_dive": ModelChoice(MODEL_FLASH_HQ, "high"),
        "viz_planning": ModelChoice(MODEL_FLASH_HQ, "medium"),
        "mermaid": ModelChoice(MODEL_FLASH_HQ, None),
        "chat": ModelChoice(MODEL_FLASH_HQ, None),
        "figure_explain": ModelChoice(MODEL_FLASH_HQ, "high"),
        "figure_resolver": ModelChoice(MODEL_FLASH_HQ, "minimal"),
        "table_resolver": ModelChoice(MODEL_FLASH_HQ, "minimal"),
        "subfigure": ModelChoice(MODEL_FLASH_HQ, "minimal"),
        "naming": ModelChoice(MODEL_FLASH_LITE, None),
        "viz_image_plan": ModelChoice(MODEL_PRO, None),
        "image": ModelChoice(MODEL_IMAGE, None),
    },
    "openai": {
        "screening": ModelChoice(MODEL_LUNA, "minimal"),
        "visual": ModelChoice(MODEL_LUNA, "low"),
        "citation": ModelChoice(MODEL_LUNA, "low"),
        "recipe": ModelChoice(MODEL_LUNA, "medium"),
        "deep_dive": ModelChoice(MODEL_LUNA, "high"),
        "viz_planning": ModelChoice(MODEL_LUNA, "medium"),
        "mermaid": ModelChoice(MODEL_LUNA, "medium"),
        "chat": ModelChoice(MODEL_LUNA, "low"),
        "figure_explain": ModelChoice(MODEL_LUNA, "medium"),
        "figure_resolver": ModelChoice(MODEL_LUNA, "minimal"),
        "table_resolver": ModelChoice(MODEL_LUNA, "minimal"),
        "subfigure": ModelChoice(MODEL_LUNA, "minimal"),
        "naming": ModelChoice(MODEL_LUNA, "minimal"),
        "viz_image_plan": ModelChoice(MODEL_LUNA, "medium"),
        "image": ModelChoice(MODEL_IMAGE_OPENAI, None),
    },
}

ROLES: tuple[str, ...] = tuple(_REGISTRY["gemini"])


def resolve(role: str, provider: str) -> ModelChoice:
    """role과 provider로 (모델, effort)를 정한다.

    Raises:
        KeyError: 등록되지 않은 provider 또는 role.
    """
    try:
        by_role = _REGISTRY[provider]
    except KeyError:
        raise KeyError(f"unknown provider: {provider!r}") from None
    try:
        return by_role[role]
    except KeyError:
        raise KeyError(f"unknown role: {role!r}") from None
```

주의: Gemini 열의 `mermaid`·`naming`·`viz_image_plan`·`chat` effort는 현재 호출부가
thinking_level을 넘기지 않으므로 `None`이다. 이식 전 실값을 재확인한다:

```bash
grep -n -B2 -A6 "call_interaction(" api/analysis_routes.py services/naming_service.py services/viz/figure_gen.py | grep -E "model=|thinking_level="
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd sasoo/backend && .venv/bin/python -m pytest services/test_model_registry.py -v
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/model_registry.py backend/services/test_model_registry.py backend/services/models.py
git commit -m "feat(models): provider x role 모델 레지스트리 — role 전체 커버

구플랜에서 누락된 리졸버·subfigure·naming·viz_image_plan role 추가(스펙 R4).
Gemini 열은 실동작 이식(screening=minimal 등), OpenAI 열은 Luna 단일 모델 +
effort 변주, deep_dive는 high까지(R3)."
```

---

## Task 4: 호출부를 레지스트리 조회로 전환 (동작 무변경)

파이프라인(`_STAGE_MODELS`/`_STAGE_THINKING`)과 개별 서비스(리졸버·네이밍·
figure_explain 등)가 모델 상수를 직접 쓰던 것을 `resolve(role, provider)` 조회로
바꾼다. **이 태스크에서 provider는 항상 `"gemini"` 리터럴**이다 — 값 주입은
Task 9. 레지스트리 Gemini 열이 실동작과 같으므로 출력이 바뀌면 안 된다.

**Files:**
- Modify: `backend/api/analysis_routes.py` (`_STAGE_MODELS`·`_STAGE_THINKING` 정의부 :767-775, screening :452-460, citation :650-658)
- Modify: `backend/services/figure_resolver.py:345-355, :415-425`
- Modify: `backend/services/table_resolver.py:214-224`
- Modify: `backend/services/subfigure_detector.py:172-182`
- Modify: `backend/services/naming_service.py:76-82, :137-143, :191-197`
- Modify: `backend/api/figure_service.py:558-566`
- Modify: `backend/services/viz/figure_gen.py:66-84`
- Test: 기존 테스트 전부 (신규 없음 — 순수 리팩터)

**Interfaces:**
- Consumes: Task 3의 `resolve`, `ModelChoice`
- Produces: `analysis_routes._stage_choice(phase: str, provider: str) -> ModelChoice` — 체인 스테이지 phase명(`visualization` 포함)을 레지스트리 role로 번역

- [ ] **Step 1: 파이프라인 스테이지 매핑 교체**

`backend/api/analysis_routes.py:767-775`의 `_STAGE_THINKING`/`_STAGE_MODELS`를 삭제하고:

```python
from services.model_registry import ModelChoice, resolve as resolve_model

# 체인 스테이지 이름과 레지스트리 role의 번역표.
# "visualization"(파이프라인 내부 명)만 레지스트리 role "viz_planning"과 다르다.
_PHASE_TO_ROLE = {
    "visual": "visual",
    "recipe": "recipe",
    "deep_dive": "deep_dive",
    "visualization": "viz_planning",
}


def _stage_choice(phase: str, provider: str) -> ModelChoice:
    return resolve_model(_PHASE_TO_ROLE[phase], provider)
```

기존 사용처 치환:
- `_STAGE_MODELS[phase]` → `_stage_choice(phase, "gemini").model`
- `_STAGE_THINKING[phase]` 또는 `_STAGE_THINKING.get(phase)` → `_stage_choice(phase, "gemini").effort`

```bash
grep -n "_STAGE_MODELS\|_STAGE_THINKING" api/analysis_routes.py
```

나온 모든 사용처를 바꾼다. `_run_chain_stage` 내부(:1004-1020 부근)가 주 사용처다.

- [ ] **Step 2: screening·citation 교체**

screening(:456 부근): `model=MODEL_SCREENING, thinking_level="minimal"` →

```python
choice = resolve_model("screening", "gemini")
# call_interaction(... model=choice.model, thinking_level=choice.effort, ...)
```

citation(:654 부근)도 같은 방식으로 `resolve_model("citation", "gemini")`.

- [ ] **Step 3: 개별 서비스 교체**

각 파일에서 `model=MODEL_FLASH_HQ, thinking_level="minimal"` 패턴을:

```python
from services.model_registry import resolve as resolve_model

_choice = resolve_model("figure_resolver", "gemini")  # 파일별 role 사용
# call_interaction(..., model=_choice.model, thinking_level=_choice.effort, ...)
```

파일별 role: `figure_resolver.py`→`figure_resolver`, `table_resolver.py`→`table_resolver`,
`subfigure_detector.py`→`subfigure`, `naming_service.py`→`naming`,
`figure_service.py`(그림 설명)→`figure_explain`, `figure_gen.py`(플래너)→`viz_image_plan`.

`thinking_level=None`이 되는 role(naming 등)은 기존과 같이 인자를 아예 넘기지
않아야 한다 — `call_interaction`은 `thinking_level=None`이면 generation_config를
만들지 않으므로 `thinking_level=_choice.effort`로 넘겨도 동작은 같다. 이 사실을
근거로 일괄 `thinking_level=_choice.effort`로 통일한다.

- [ ] **Step 4: 전체 테스트**

```bash
cd sasoo/backend && .venv/bin/python -m pytest -q
```

Expected: 전부 통과. 테스트가 `MODEL_FLASH_HQ` 상수 문자열을 assert하는 곳은
레지스트리가 같은 상수를 돌려주므로 깨지지 않는다. `_STAGE_MODELS`를 patch하던
테스트가 있으면 `_stage_choice`를 patch하도록 바꾼다:

```bash
grep -rn "_STAGE_MODELS\|_STAGE_THINKING" api/test_analysis_routes.py
```

- [ ] **Step 5: Commit**

```bash
git add -A backend/
git commit -m "refactor(pipeline): 모델 선택을 레지스트리 조회로 일원화

_STAGE_MODELS/_STAGE_THINKING과 개별 서비스의 상수 직접 참조를
resolve(role, provider)로 교체. provider는 아직 gemini 고정 — 값 주입은
라우팅 태스크에서. 레지스트리 Gemini 열이 실동작 이식이므로 동작 무변경."
```

---

## Task 5: 가격표 — Luna 단가 + provider별 폴백 (R7)

**Files:**
- Modify: `backend/services/pricing.py`
- Test: `backend/services/test_pricing.py` (기존 파일 있으면 케이스 추가, 없으면 생성)

**Interfaces:**
- Consumes: Task 0 Step 4에서 확정한 Luna 공식 단가
- Produces: `PRICING["gpt-5.6-luna"]`, provider별 `_FALLBACK` 분기

- [ ] **Step 1: Write the failing test**

`backend/services/test_pricing.py`에 추가(파일이 없으면 unittest 보일러플레이트와 함께 생성):

```python
import unittest

from services.pricing import PRICING, calc_cost


class TestOpenAIPricing(unittest.TestCase):
    def test_luna_is_registered(self):
        self.assertIn("gpt-5.6-luna", PRICING)
        entry = PRICING["gpt-5.6-luna"]
        self.assertGreater(entry["input"], 0)
        self.assertGreater(entry["output"], 0)

    def test_unknown_openai_model_does_not_use_gemini_fallback(self):
        """미지의 gpt-* 모델을 Gemini 단가로 조용히 계산하면 비용이 오산된다(스펙 R7-1)."""
        cost_unknown_gpt = calc_cost("gpt-99-future", 1_000_000, 1_000_000)
        cost_luna = calc_cost("gpt-5.6-luna", 1_000_000, 1_000_000)
        self.assertEqual(cost_unknown_gpt, cost_luna)  # OpenAI 폴백은 Luna 단가

    def test_unknown_gemini_model_keeps_existing_fallback(self):
        from services.pricing import _FALLBACK
        cost = calc_cost("gemini-99-future", 1_000_000, 0)
        self.assertEqual(cost, calc_cost(_FALLBACK, 1_000_000, 0))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd sasoo/backend && .venv/bin/python -m pytest services/test_pricing.py -v
```

Expected: FAIL — `KeyError`/`AssertionError` (luna 미등록)

- [ ] **Step 3: 구현**

`backend/services/pricing.py`:

1. `PRICING` dict에 추가 — **단가는 Task 0 Step 4의 확정값을 쓴다. 아래 수치는
   자리 표시가 아니라 스펙 원안 값이며, 실측이 다르면 교체한다:**

```python
    # OpenAI 텍스트 (provider 중립화 — 단가는 2026-08-03 공식 페이지 확인값)
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20},
```

2. 폴백 분기 — 기존 `_FALLBACK = "gemini-3-flash-preview"` 아래에:

```python
_FALLBACK_OPENAI = "gpt-5.6-luna"


def _fallback_for(model: str) -> str:
    """미등록 모델의 폴백 단가 — provider를 넘어가는 오산 금지(스펙 R7-1)."""
    return _FALLBACK_OPENAI if model.startswith("gpt-") else _FALLBACK
```

`calc_cost` 내부의 `PRICING.get(model, PRICING[_FALLBACK])` 패턴을
`PRICING.get(model) or PRICING[_fallback_for(model)]`로 바꾼다. (`calc_cost`의
실제 폴백 코드 위치는 `grep -n "_FALLBACK" services/pricing.py`로 확인.)

- [ ] **Step 4: 재시도 비용을 attempt별 계산으로 교체 (R7-3)**

`api/analysis_routes.py`의 재시도 게이트 2곳(screening :470 부근, `_run_chain_stage`
:1032 부근)은 현재 두 attempt의 토큰을 **합산한 뒤** 마지막 모델 단가로 한 번
계산한다. 같은 모델·같은 effort의 재시도라 평면 단가에서는 등가지만, 단가표에
장문 임계값이 생기면 합산 토큰이 임계값을 잘못 넘는다. attempt별로 계산해 USD를
합산하도록 바꾼다:

```python
        retry = await _invoke()
        # 재시도 사용량은 attempt별로 비용을 계산해 합산한다(R7-3) —
        # 토큰을 합쳐 한 번에 계산하면 장문 임계값이 잘못 적용될 수 있다.
        retry["cost_usd_prior_attempts"] = calc_cost(
            result["model"], result.get("tokens_in") or 0, result.get("tokens_out") or 0,
        )
        retry["tokens_in"] = (result.get("tokens_in") or 0) + (retry.get("tokens_in") or 0)
        retry["tokens_out"] = (result.get("tokens_out") or 0) + (retry.get("tokens_out") or 0)
        result = retry
```

그리고 이 결과의 비용을 합산하는 지점(`calc_cost(result["model"], ...)` 호출부)에서
`result.get("cost_usd_prior_attempts", 0.0)`을 더한다. 합산 지점은
`grep -n "calc_cost(" api/analysis_routes.py`로 찾는다(스테이지별 6곳 내외).
토큰 합산 자체는 유지한다 — 사용량 표시(tokens_in/out)는 실사용 총량이 맞다.

- [ ] **Step 5: Run test to verify it passes + 전체 테스트**

```bash
cd sasoo/backend && .venv/bin/python -m pytest services/test_pricing.py -v && .venv/bin/python -m pytest -q
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/pricing.py backend/services/test_pricing.py backend/api/analysis_routes.py
git commit -m "feat(pricing): Luna 단가 등록 + provider별 폴백 + attempt별 재시도 비용

미지의 gpt-* 모델이 Gemini 폴백 단가로 조용히 계산되던 것을 차단(R7-1).
재시도 비용은 attempt별 계산 후 합산(R7-3). 단가는 공식 페이지 실측값."
```

---

## Task 6: 캐시 키에 provider/model/effort 포함 (R6)

`compute_input_hash`를 확장하고, analysis_routes의 캐시 읽기/쓰기가 **같은 키를
쓰도록 스테이지 진입 시 한 번 확정**한다. 기본 인자를 두어 `odl_parser.py:1907`
등 provider 무관 호출부는 무수정으로 동작한다.

**Files:**
- Modify: `backend/services/document_context.py:49` (`compute_input_hash`)
- Modify: `backend/api/analysis_routes.py` — 캐시 관련 호출부 (`grep -n "compute_input_hash" api/analysis_routes.py`: :149, :162, :318, :1928, :2423 부근)
- Test: `backend/services/test_document_context.py`

**Interfaces:**
- Consumes: Task 3의 `ModelChoice`
- Produces: `compute_input_hash(input_text: str, *, provider: str | None = None, model: str | None = None, effort: str | None = None) -> str`

- [ ] **Step 1: Write the failing test**

`backend/services/test_document_context.py`에 추가:

```python
class TestInputHashProviderAware(unittest.TestCase):
    def test_legacy_call_without_kwargs_is_unchanged(self):
        """odl_parser 등 provider 무관 호출부의 해시가 변하면 기존 캐시가 전멸한다."""
        from services.document_context import compute_input_hash
        legacy = compute_input_hash("본문 텍스트")
        self.assertEqual(len(legacy), 16)  # 기존 길이 계약 유지
        self.assertEqual(legacy, compute_input_hash("본문 텍스트"))

    def test_model_and_effort_change_the_hash(self):
        from services.document_context import compute_input_hash
        base = compute_input_hash("t", provider="gemini", model="gemini-3.6-flash", effort="high")
        self.assertNotEqual(base, compute_input_hash("t", provider="openai", model="gpt-5.6-luna", effort="high"))
        self.assertNotEqual(base, compute_input_hash("t", provider="gemini", model="gemini-3.6-flash", effort="low"))

    def test_kwargs_hash_differs_from_legacy(self):
        from services.document_context import compute_input_hash
        self.assertNotEqual(
            compute_input_hash("t"),
            compute_input_hash("t", provider="gemini", model="gemini-3.6-flash", effort=None),
        )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd sasoo/backend && .venv/bin/python -m pytest services/test_document_context.py -v
```

Expected: FAIL — `TypeError: compute_input_hash() got an unexpected keyword argument`

- [ ] **Step 3: 구현**

`backend/services/document_context.py:49`의 `compute_input_hash`를:

```python
def compute_input_hash(
    input_text: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
) -> str:
    """분석 입력의 캐시 키.

    provider/model/effort가 주어지면 키에 포함한다 — 같은 논문이라도 다른
    모델·사고량의 결과는 다른 캐시 행이다(스펙 결정 3 + 개정 R6). 셋 다
    None인 레거시 호출(odl_parser의 파서 사용량 기록 등)은 기존 해시를
    바이트 단위로 유지해 데이터 마이그레이션을 피한다.
    """
    if provider is None and model is None and effort is None:
        payload = input_text
    else:
        payload = f"{provider}\x1f{model}\x1f{effort}\x1f{input_text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
```

(기존 함수 본문이 위와 다른 해시 구성을 쓰면 — 예: 다른 절단 길이 — 기존
구성을 유지한 채 payload 조립만 추가한다. 먼저 기존 본문을 읽어라.)

- [ ] **Step 4: analysis_routes에 스테이지 컨텍스트 도입**

캐시를 쓰는 각 phase에서 **읽기와 쓰기가 같은 (provider, model, effort)를 쓰도록**
phase 진입 시 한 번 확정한다. 패턴:

```python
# phase 진입부 (예: _run_screening 시작)
choice = resolve_model("screening", provider)  # Task 9 전까지 provider="gemini" 리터럴
input_hash = compute_input_hash(
    prompt, provider=provider, model=choice.model, effort=choice.effort,
)
```

그리고 그 phase의 `_get_cached_phase_result(...)` / `_insert_analysis_result(...)` /
`_update_visualization_checkpoint(...)` 호출이 **이 `input_hash` 변수 하나**를 쓰게
한다. 호출부별 위치는:

```bash
grep -n "compute_input_hash\|_get_cached_phase_result\|input_hash" api/analysis_routes.py | head -30
```

주의(스펙 R6): `_update_visualization_checkpoint`(:1928 부근)는 input_hash로 자기
행을 찾아 UPDATE한다 — 읽기/쓰기 키가 어긋나면 중복 INSERT가 난다. 같은 변수를
전달하는지 반드시 확인한다.

- [ ] **Step 5: 전체 테스트 + 캐시 무효화 확인**

```bash
cd sasoo/backend && .venv/bin/python -m pytest -q
```

Expected: 통과. **의도된 부수 효과**: 이 변경으로 기존 분석 캐시는 전부 미스가
된다(키 구성 변경). 스펙 §D의 "옛 행은 배지 경로로" 동작은 Task 11에서 붙는다.

- [ ] **Step 6: Commit**

```bash
git add backend/services/document_context.py backend/services/test_document_context.py backend/api/analysis_routes.py
git commit -m "feat(cache): 캐시 키에 provider/model/effort 포함

provider 전환 시 Gemini 캐시를 OpenAI 실행이 히트하는 조용한 오염을 차단
(스펙 R6). 스테이지 진입 시 키를 한 번 확정해 읽기/쓰기/체크포인트가 같은
키를 쓴다. 레거시 무인자 호출은 해시 불변."
```

---

## Task 7: OpenAI 클라이언트 — 비스트리밍 (R5)

구플랜 Task 9 스케치를 기반으로 하되 **4가지를 고친다**: ①`prompt: str | list[dict]`
파트 번역기 ②`except Exception`(BaseException 금지) ③클라이언트 캐싱(키별 dict+락)
④PDF 업로드 함수 없음(R1 — 텍스트 체인).

**Files:**
- Create: `backend/services/llm/openai_client.py`
- Test: `backend/services/llm/test_openai_client.py`

**Interfaces:**
- Consumes: Task 1의 `Lane`, `LLMResponse`; `services.concurrency`의 `CHAT_EXECUTOR`, `PIPELINE_EXECUTOR`, `pipeline_llm_sem`; `services.models.MODEL_LUNA`
- Produces:
  - `available() -> bool`
  - `async call_interaction(prompt, *, lane, model=MODEL_LUNA, system_instruction=None, thinking_level=None, previous_interaction_id=None, response_schema=None, store=True, media_resolution=None) -> dict`
    — **gemini_client.call_interaction과 같은 시그니처·같은 dict 반환 형태**(셔션이 무분기 위임할 수 있도록). `thinking_level`은 내부에서 `reasoning.effort`로, `previous_interaction_id`는 `previous_response_id`로 번역. `media_resolution`은 무시(Gemini 전용).
  - `_translate_parts(prompt) -> list | str` (모듈 내부, 테스트 대상)
  - `_is_retryable(exc) -> bool`

- [ ] **Step 1: gemini_client의 반환 dict 형태 확인**

```bash
grep -n "return {" -A8 services/llm/gemini_client.py | head -20
```

`call_interaction`이 돌려주는 dict의 키 집합(`text`, `model`, `tokens_in`,
`tokens_out`, `interaction_id` + 그 외)을 기록한다. openai_client는 **같은 키
집합**을 돌려줘야 호출부가 분기를 모른다.

- [ ] **Step 2: Write the failing test**

`backend/services/llm/test_openai_client.py`:

```python
import asyncio
import os
import unittest
from unittest.mock import patch


class _FakeStatusError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class TestAvailability(unittest.TestCase):
    def test_available_true_when_key_present(self):
        from services.llm import openai_client
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            self.assertTrue(openai_client.available())

    def test_available_false_when_key_absent(self):
        from services.llm import openai_client
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(openai_client.available())


class TestChainGuard(unittest.TestCase):
    def test_chain_without_store_raises(self):
        from services.llm import openai_client
        with self.assertRaises(ValueError):
            asyncio.run(openai_client.call_interaction(
                "prompt", lane="pipeline", store=False,
                previous_interaction_id="resp_abc",
            ))


class TestRetryPolicy(unittest.TestCase):
    def test_408_429_5xx_retryable_4xx_not(self):
        from services.llm.openai_client import _is_retryable
        for status, expected in ((408, True), (429, True), (503, True),
                                 (400, False), (401, False), (403, False), (404, False)):
            with self.subTest(status=status):
                self.assertEqual(_is_retryable(_FakeStatusError(status)), expected)

    def test_exception_without_status_is_retryable(self):
        from services.llm.openai_client import _is_retryable
        self.assertTrue(_is_retryable(RuntimeError("connection reset")))


class TestPartTranslator(unittest.TestCase):
    """Gemini 파트 dict를 Responses API input으로 번역 — 이미지 파트를 넘기는
    호출부가 7곳이다(리졸버 3종·subfigure·figure_service 등)."""

    def test_plain_string_passes_through(self):
        from services.llm.openai_client import _translate_parts
        self.assertEqual(_translate_parts("질문"), "질문")

    def test_image_part_becomes_input_image_data_url(self):
        from services.llm.openai_client import _translate_parts
        out = _translate_parts([
            {"type": "image", "data": "QUJD", "mime_type": "image/png"},
            {"type": "text", "text": "이 그림은?"},
        ])
        content = out[0]["content"]
        self.assertEqual(content[0]["type"], "input_image")
        self.assertEqual(content[0]["image_url"], "data:image/png;base64,QUJD")
        self.assertEqual(content[1], {"type": "input_text", "text": "이 그림은?"})

    def test_document_part_raises(self):
        """OpenAI 경로는 문서 파트를 지원하지 않는다(스펙 R1) — 조용히 떨어뜨리면
        체인 첫 호출이 빈 컨텍스트로 나가므로 시끄럽게 실패한다."""
        from services.llm.openai_client import _translate_parts
        with self.assertRaises(ValueError):
            _translate_parts([{"type": "document", "uri": "files/abc",
                               "mime_type": "application/pdf"}])


class TestClientCaching(unittest.TestCase):
    def test_same_key_reuses_client(self):
        from services.llm import openai_client
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-cache-test"}, clear=False):
            openai_client._clients.clear()
            c1 = openai_client._get_client()
            c2 = openai_client._get_client()
            self.assertIs(c1, c2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd sasoo/backend && .venv/bin/python -m pytest services/llm/test_openai_client.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'services.llm.openai_client'`

- [ ] **Step 4: Write implementation**

`backend/services/llm/openai_client.py`:

```python
"""Sasoo - OpenAI Responses API 클라이언트.

gemini_client.call_interaction과 같은 시그니처·같은 반환 dict를 유지한다 —
셔션(interactions_client)이 분기 없이 위임하기 위해서다. 개념 번역:

    previous_interaction_id  ->  previous_response_id
    thinking_level           ->  reasoning.effort
    media_resolution         ->  (무시 - Gemini 전용)

PDF 업로드는 없다(스펙 개정 1 R1) — 체인 첫 호출에 로컬 추출 텍스트를
주입한다. usage.output_tokens는 reasoning 토큰을 이미 포함하므로(R7-2)
Gemini처럼 thought를 더하지 않는다.
"""

import asyncio
import logging
import os
import threading
from typing import Any

from services.concurrency import CHAT_EXECUTOR, PIPELINE_EXECUTOR, pipeline_llm_sem
from services.llm.base import Lane
from services.llm.gemini_client import _SYSTEM_INSTRUCTION_KO
from services.models import MODEL_LUNA

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [2, 8]  # 3회 시도 — gemini_client와 동일 정책
_RETRYABLE_CLIENT_STATUS = frozenset({408, 429})

# 키가 런타임에 바뀔 수 있으므로(설정 화면) api_key를 캐시 키로 둔다.
# gemini_client와 같은 이유·같은 구조 — TLS 핸드셰이크 누적 방지.
_clients: dict[str, Any] = {}
_clients_lock = threading.Lock()


def available() -> bool:
    """OPENAI_API_KEY가 있어 호출 가능한 상태인지."""
    return bool(os.environ.get("OPENAI_API_KEY"))


def _get_client():
    from openai import OpenAI

    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY not set")
    client = _clients.get(key)
    if client is None:
        with _clients_lock:
            client = _clients.get(key)
            if client is None:
                client = OpenAI(api_key=key)
                _clients[key] = client
    return client


def _is_retryable(exc: BaseException) -> bool:
    """재시도로 풀릴 수 있는 오류인지. openai SDK는 APIStatusError.status_code를 준다.

    408/429와 5xx만 재시도. 상태 코드가 없는 예외(네트워크 끊김)는 판단 근거가
    없으니 보수적으로 재시도한다 — gemini_client와 같은 정책.
    """
    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        return True
    if status in _RETRYABLE_CLIENT_STATUS:
        return True
    return status >= 500


def _translate_parts(prompt) -> Any:
    """Gemini 파트 dict 리스트를 Responses API input으로 번역한다.

    str은 그대로(SDK가 user 메시지로 감싼다). 문서 파트는 지원하지 않는다 —
    OpenAI 체인은 파일이 아니라 텍스트 주입을 쓴다(스펙 R1). 조용히
    떨어뜨리면 빈 컨텍스트로 호출이 나가므로 ValueError로 시끄럽게 막는다.
    """
    if isinstance(prompt, str):
        return prompt
    content: list[dict[str, Any]] = []
    for part in prompt:
        kind = part.get("type")
        if kind == "text":
            content.append({"type": "input_text", "text": part["text"]})
        elif kind == "image":
            content.append({
                "type": "input_image",
                "image_url": f"data:{part['mime_type']};base64,{part['data']}",
            })
        else:
            raise ValueError(f"OpenAI 경로가 지원하지 않는 파트: {kind!r}")
    return [{"role": "user", "content": content}]


def _executor_for(lane: Lane):
    if lane == "chat":
        return CHAT_EXECUTOR
    if lane == "pipeline":
        return PIPELINE_EXECUTOR
    raise ValueError(f"unknown lane: {lane!r}")


async def call_interaction(
    prompt,
    *,
    lane: Lane,
    model: str = MODEL_LUNA,
    system_instruction: str | None = None,
    thinking_level: str | None = None,
    previous_interaction_id: str | None = None,
    response_schema: dict | None = None,
    store: bool = True,
    media_resolution: str | None = None,  # noqa: ARG001 - Gemini 전용, 시그니처 호환용
) -> dict:
    """한 번의 Responses API 호출. gemini_client.call_interaction과 동형.

    Raises:
        ValueError: store=False인데 previous_interaction_id를 넘긴 경우.
    """
    if not store and previous_interaction_id:
        raise ValueError("previous_interaction_id requires store=True")

    kwargs: dict[str, Any] = {
        "model": model,
        "input": _translate_parts(prompt),
        "instructions": system_instruction or _SYSTEM_INSTRUCTION_KO,
        "store": store,
    }
    if thinking_level:
        kwargs["reasoning"] = {"effort": thinking_level}
    if previous_interaction_id:
        kwargs["previous_response_id"] = previous_interaction_id
    if response_schema:
        kwargs["text"] = {
            "format": {
                "type": "json_schema",
                "name": "sasoo_result",
                "schema": response_schema,
                "strict": False,  # 현행 스키마는 strict 제약(전 필드 required 등) 미충족
            }
        }

    def _do_call():
        resp = _get_client().responses.create(**kwargs)
        usage = getattr(resp, "usage", None)
        details = getattr(usage, "output_tokens_details", None)
        return {
            "text": getattr(resp, "output_text", "") or "",
            "model": model,
            # output_tokens는 reasoning 포함(R7-2) — 재합산 금지
            "tokens_in": getattr(usage, "input_tokens", 0) or 0,
            "tokens_out": getattr(usage, "output_tokens", 0) or 0,
            "tokens_thought": getattr(details, "reasoning_tokens", 0) or 0,  # 정보용
            "interaction_id": getattr(resp, "id", None),
        }

    loop = asyncio.get_running_loop()
    last_exc: Exception | None = None
    for attempt in range(len(_RETRY_DELAYS) + 1):
        try:
            if lane == "pipeline":
                async with pipeline_llm_sem():
                    return await loop.run_in_executor(PIPELINE_EXECUTOR, _do_call)
            return await loop.run_in_executor(_executor_for(lane), _do_call)
        except Exception as exc:  # noqa: BLE001 - CancelledError는 BaseException이라 통과
            last_exc = exc
            if attempt >= len(_RETRY_DELAYS) or not _is_retryable(exc):
                raise
            delay = _RETRY_DELAYS[attempt]
            logger.warning("openai call failed (%s), retrying in %ss", exc, delay)
            await asyncio.sleep(delay)

    raise last_exc  # 도달 불가 — 루프가 반드시 return 또는 raise 한다
```

주의: 반환 dict의 키 집합을 Step 1에서 확인한 gemini_client와 대조한다.
gemini_client에 있는데 위에 없는 키(예: `cost_usd`)가 있으면 같은 이름으로
채운다. `_do_call` 안에서 세마포어 획득 중 백오프하지 않도록 sleep은 세마포어
밖(except 블록)에 있다 — gemini_client의 슬롯 반납 정책과 동일.

- [ ] **Step 5: Run test to verify it passes + SDK 선언**

```bash
cd sasoo/backend && .venv/bin/python -m pytest services/llm/test_openai_client.py -v
grep -n "openai" requirements.txt || (echo "openai>=1.60" >> requirements.txt && .venv/bin/pip install "openai>=1.60")
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/services/llm/openai_client.py backend/services/llm/test_openai_client.py backend/requirements.txt
git commit -m "feat(llm): OpenAI Responses API 클라이언트 (비스트리밍)

gemini_client와 동형 시그니처·반환 dict. 파트 번역기(이미지 base64 data URL,
문서 파트는 ValueError), 키별 클라이언트 캐싱, except Exception 재시도,
reasoning 토큰 재합산 금지(R7-2). PDF 업로드 없음(R1)."
```

---

## Task 8: OpenAI 스트리밍 (`stream_interaction` 등가) (R5-2)

채팅 SSE가 쓰는 `stream_interaction`의 `{"type":"token"}` / `{"type":"done"}` 이벤트
계약을 OpenAI로 구현한다.

**Files:**
- Modify: `backend/services/llm/openai_client.py`
- Test: `backend/services/llm/test_openai_client.py`

**Interfaces:**
- Consumes: gemini_client의 `stream_interaction` 이벤트 계약 (`grep -n "yield" services/llm/gemini_client.py`로 정확한 이벤트 dict 형태 확인)
- Produces: `async stream_interaction(prompt, *, lane, model=MODEL_LUNA, system_instruction=None, thinking_level=None, store=False) -> AsyncIterator[dict]` — gemini_client와 같은 이벤트 형태

- [ ] **Step 1: gemini_client의 이벤트 계약 확인**

```bash
grep -n -B3 -A8 "yield" services/llm/gemini_client.py | head -50
```

`token` 이벤트의 키(`type`, `text` 등)와 `done` 이벤트의 키(`tokens_in`,
`tokens_out`, `model`, `interaction_id` 등)를 기록한다. 아래 구현의 yield 형태를
이것과 정확히 맞춘다.

- [ ] **Step 2: Write the failing test**

`test_openai_client.py`에 추가:

```python
class TestStreamContract(unittest.TestCase):
    def test_stream_yields_tokens_then_done(self):
        from services.llm import openai_client

        class _FakeEvent:
            def __init__(self, type_, delta=None, response=None):
                self.type = type_
                self.delta = delta
                self.response = response

        class _FakeUsage:
            input_tokens = 7
            output_tokens = 3

        class _FakeResponse:
            id = "resp_x"
            usage = _FakeUsage()

        class _FakeStream:
            def __enter__(self):
                return iter([
                    _FakeEvent("response.output_text.delta", delta="안"),
                    _FakeEvent("response.output_text.delta", delta="녕"),
                    _FakeEvent("response.completed", response=_FakeResponse()),
                ])

            def __exit__(self, *a):
                return False

        class _FakeResponses:
            def stream(self, **kwargs):
                return _FakeStream()

        class _FakeClient:
            responses = _FakeResponses()

        async def collect():
            events = []
            with patch.object(openai_client, "_get_client", return_value=_FakeClient()):
                async for ev in openai_client.stream_interaction(
                    "질문", lane="chat", store=False,
                ):
                    events.append(ev)
            return events

        events = asyncio.run(collect())
        token_events = [e for e in events if e["type"] == "token"]
        self.assertEqual([e["text"] for e in token_events], ["안", "녕"])
        done = events[-1]
        self.assertEqual(done["type"], "done")
        self.assertEqual(done["tokens_in"], 7)
        self.assertEqual(done["tokens_out"], 3)
```

(gemini_client의 실제 이벤트 키가 다르면 — Step 1 확인 결과 — 이 테스트의
assert 키를 실계약에 맞춘 뒤 진행한다.)

- [ ] **Step 3: Run test to verify it fails**

```bash
cd sasoo/backend && .venv/bin/python -m pytest services/llm/test_openai_client.py::TestStreamContract -v
```

Expected: FAIL — `AttributeError: module ... has no attribute 'stream_interaction'`

- [ ] **Step 4: 구현**

`openai_client.py`에 추가:

```python
async def stream_interaction(
    prompt,
    *,
    lane: Lane,
    model: str = MODEL_LUNA,
    system_instruction: str | None = None,
    thinking_level: str | None = None,
    store: bool = False,
):
    """토큰 단위 스트리밍 — gemini_client.stream_interaction과 같은 이벤트 계약.

    스레드 풀에서 동기 SDK 스트림을 돌리고 큐로 이벤트를 건넨다. 채팅은
    stateless(store=False, 히스토리를 텍스트로 조립)라 체인 인자가 없다.
    """
    kwargs: dict[str, Any] = {
        "model": model,
        "input": _translate_parts(prompt),
        "instructions": system_instruction or _SYSTEM_INSTRUCTION_KO,
        "store": store,
    }
    if thinking_level:
        kwargs["reasoning"] = {"effort": thinking_level}

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _SENTINEL = object()

    def _produce():
        try:
            with _get_client().responses.stream(**kwargs) as stream:
                for event in stream:
                    if event.type == "response.output_text.delta":
                        loop.call_soon_threadsafe(
                            queue.put_nowait, {"type": "token", "text": event.delta})
                    elif event.type == "response.completed":
                        usage = getattr(event.response, "usage", None)
                        loop.call_soon_threadsafe(queue.put_nowait, {
                            "type": "done",
                            "model": model,
                            "tokens_in": getattr(usage, "input_tokens", 0) or 0,
                            "tokens_out": getattr(usage, "output_tokens", 0) or 0,
                            "interaction_id": getattr(event.response, "id", None),
                        })
        except Exception as exc:  # noqa: BLE001 - 소비자에게 전달해 SSE error로 변환
            loop.call_soon_threadsafe(queue.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _SENTINEL)

    future = loop.run_in_executor(_executor_for(lane), _produce)
    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        await future
```

(gemini_client의 `stream_interaction`이 큐가 아닌 다른 브릿지 구조를 쓰면 — Step 1
에서 확인 — 그 구조를 그대로 복제한다. 이벤트 dict 키가 계약이고 내부 구조는
자유다. 단 `done` 이전에 발생한 예외는 반드시 소비자에게 재던져져야 한다 —
채팅 라우트의 "첫 토큰 전 실패만 재시도" 정책이 이 예외에 의존한다.)

- [ ] **Step 5: Run tests + Commit**

```bash
cd sasoo/backend && .venv/bin/python -m pytest services/llm/test_openai_client.py -v && .venv/bin/python -m pytest -q
git add backend/services/llm/
git commit -m "feat(llm): OpenAI 스트리밍 — token/done 이벤트 계약 등가

채팅 SSE의 stream_interaction을 Responses API 스트림으로 구현. done 이전
예외는 재던져 첫 토큰 전 재시도 정책을 유지한다(스펙 R5-2)."
```

---

## Task 9: 셔션에 provider 라우팅 배선 + stateless 경로 개통

`interactions_client` 셔션이 **모델 접두사**(`gpt-*` → openai, 그 외 → gemini)로
클라이언트를 고르게 하고, 호출부의 role 조회에 실제 provider 값을 주입한다.
이 태스크가 끝나면 stateless 경로 전부(screening·citation·리졸버·네이밍·
그림설명·Mermaid·채팅)가 OpenAI로 동작한다.

**Files:**
- Modify: `backend/services/llm/interactions_client.py` (셔션)
- Modify: `backend/api/analysis_routes.py` — `"gemini"` 리터럴을 `_active_provider()` 호출로 교체
- Modify: Task 4에서 고친 개별 서비스 6곳 — 동일 교체
- Test: `backend/services/llm/test_interactions_client_routing.py` (신규)

**Interfaces:**
- Consumes: Task 7·8의 openai_client, 기존 `services.provider_state.effective_provider`, `api.settings._get_all_settings`
- Produces:
  - 셔션의 `call_interaction`/`stream_interaction` — 모델 접두사로 라우팅
  - `services/model_registry.py`에 `async active_provider() -> str` — 설정과 키 가용성으로 현재 provider 확정(기본 `"gemini"`)

- [ ] **Step 1: active_provider 구현 위치 확인**

키 상태 머신은 이미 병합돼 있다(`services/provider_state.py`의
`effective_provider(stored, *, has_openai, has_gemini)`). 설정 읽기 경로를 확인한다:

```bash
grep -n "effective_provider" api/settings.py services/provider_state.py
```

`api/settings.py`가 settings dict에서 stored 값을 읽어 `effective_provider`를 부르는
기존 함수(`_resolve_active_provider` 부근)가 있다 — **재구현하지 말고 재사용**한다.

- [ ] **Step 2: Write the failing test**

`backend/services/llm/test_interactions_client_routing.py`:

```python
import asyncio
import unittest
from unittest.mock import AsyncMock, patch


class TestModelPrefixRouting(unittest.TestCase):
    """셔션은 모델 접두사로 클라이언트를 고른다 — 호출부는 분기를 모른다."""

    def test_gpt_model_routes_to_openai(self):
        from services.llm import interactions_client
        openai_mock = AsyncMock(return_value={"text": "ok"})
        with (
            patch("services.llm.openai_client.call_interaction", new=openai_mock),
            patch("services.llm.gemini_client.call_interaction", new=AsyncMock()) as gem,
        ):
            asyncio.run(interactions_client.call_interaction(
                "p", lane="pipeline", model="gpt-5.6-luna", store=False))
        openai_mock.assert_awaited_once()
        gem.assert_not_awaited()

    def test_gemini_model_routes_to_gemini(self):
        from services.llm import interactions_client
        gem = AsyncMock(return_value={"text": "ok"})
        with (
            patch("services.llm.gemini_client.call_interaction", new=gem),
            patch("services.llm.openai_client.call_interaction", new=AsyncMock()) as oai,
        ):
            asyncio.run(interactions_client.call_interaction(
                "p", lane="pipeline", model="gemini-3.6-flash", store=False))
        gem.assert_awaited_once()
        oai.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 셔션 재작성**

`backend/services/llm/interactions_client.py`:

```python
"""Sasoo - LLM 호출 셔션(façade) — provider 라우팅.

역사적 이름을 유지한다(호출부 12곳이 이 경로를 import). 라우팅 규칙은
모델 접두사 하나다: gpt-* 는 openai_client, 그 외는 gemini_client.
provider 결정은 여기가 아니라 모델 선택 지점(model_registry.resolve 호출부)
에서 일어난다 — 셔션은 골라진 모델을 맞는 클라이언트로 나를 뿐이다.
"""

from services.llm import gemini_client, openai_client
from services.llm.gemini_client import (  # noqa: F401 - 하위호환 재노출
    Lane,
    _SYSTEM_INSTRUCTION_KO,
    upload_pdf_for_paper,
)


def _client_for(model: str):
    return openai_client if model.startswith("gpt-") else gemini_client


async def call_interaction(prompt, *, model, **kwargs) -> dict:
    return await _client_for(model).call_interaction(prompt, model=model, **kwargs)


async def stream_interaction(prompt, *, model, **kwargs):
    async for event in _client_for(model).stream_interaction(prompt, model=model, **kwargs):
        yield event
```

주의: 기존 호출부 중 `model`을 안 넘기는 곳이 있는지 확인한다
(`grep -rn "call_interaction(" --include="*.py" | grep -v "model="`). 있다면 그
호출부는 gemini_client의 기본값(MODEL_FLASH_HQ)에 의존하던 곳이다 — 셔션 시그니처의
`model`을 `model=gemini_client.MODEL_FLASH_HQ` 기본값으로 두든지, 호출부에
레지스트리 조회를 넣는다(후자 권장 — Task 4에서 대부분 처리됐어야 한다).

- [ ] **Step 4: active_provider 헬퍼 추가 + 리터럴 교체**

`backend/services/model_registry.py`에 추가:

```python
async def active_provider() -> str:
    """현재 유효 provider. 설정(ai_provider)을 키 가용성으로 보정한 값.

    None(둘 다 키 없음)이면 "gemini"를 돌려준다 — 이 경우 어차피 분석
    /run이 키 사전 점검에서 거절하므로 여기서 죽지 않는 것이 낫다.
    """
    from api.settings import _get_all_settings, _resolve_active_provider

    settings = await _get_all_settings()
    resolved = _resolve_active_provider(settings, settings.get("ai_provider"))
    return resolved or "gemini"
```

(`_resolve_active_provider`의 실제 시그니처를 :81 부근에서 확인해 맞춘다.)

그리고 Task 4에서 넣은 `resolve_model(..., "gemini")` 리터럴을 전부:

```python
provider = await active_provider()
choice = resolve_model("screening", provider)
```

로 바꾼다. 대상: analysis_routes(screening·citation·`_stage_choice` 호출부·Mermaid·
채팅·실험계획), figure_resolver, table_resolver, subfigure_detector, naming_service,
figure_service, figure_gen. 동기 컨텍스트라 await가 불가능한 곳이 있으면 provider를
인자로 끌어올린다(호출자는 전부 async다).

- [ ] **Step 5: /run 사전 점검을 provider-aware로 수정**

`api/analysis_routes.py`의 `/run` 키 사전 점검(GEMINI_API_KEY 확인, :2483 부근 —
PR #41로 들어간 코드)을 provider 기준으로 바꾼다:

```python
    provider = await active_provider()
    key_env = "OPENAI_API_KEY" if provider == "openai" else "GEMINI_API_KEY"
    if not os.getenv(key_env):
        raise HTTPException(
            status_code=400,
            detail=f"논문 분석에 {provider} API 키가 필요해요. 설정에서 키를 등록해 주세요.",
        )
```

(PR #41이 아직 미병합이면 이 스텝은 rebase 후 적용한다. 관련 테스트
`test_run_rejects_clearly_without_gemini_key`도 provider 시나리오 2개로 확장:
gemini 선택+키 없음 → 400, openai 선택+OpenAI 키 있음 → 통과.)

- [ ] **Step 6: 전체 테스트 + Gemini 회귀 확인**

```bash
cd sasoo/backend && .venv/bin/python -m pytest -q
```

Expected: 전부 통과. Gemini 키만 있는 환경에서 논문 1편 실분석(수동)으로 기존
경로 무손상 확인 — 이것이 이 태스크의 게이트다.

- [ ] **Step 7: Commit**

```bash
git add -A backend/
git commit -m "feat(llm): 셔션 provider 라우팅 + stateless 경로 개통

모델 접두사(gpt-*)로 클라이언트를 고르고, 호출부의 레지스트리 조회에
active_provider()를 주입. screening·citation·리졸버·네이밍·그림설명·
Mermaid·채팅이 OpenAI 키 단독으로 동작한다. /run 사전 점검도 provider 기준."
```

---

## Task 10: OpenAI 텍스트 주입 체인 — 4스테이지 (R1)

`_run_chain_stage`(visual → recipe → deep_dive → visualization)가 OpenAI에서
PDF 대신 **로컬 추출 텍스트를 첫 호출에 1회 주입**하고 `previous_interaction_id`
(=previous_response_id)로 잇게 한다.

**Files:**
- Modify: `backend/api/analysis_routes.py` — `_run_chain_stage`(:964-1040 부근)와 그 호출부 4곳(:1174, :1340, :1466, :1758 부근), `_run_full_analysis`의 체인 준비부(:2181 부근 `upload_pdf_for_paper` 호출)
- Test: `backend/api/test_analysis_routes.py`

**Interfaces:**
- Consumes: Task 7의 openai_client(셔션 경유), Task 9의 `active_provider`
- Produces: `_run_chain_stage(..., doc_text: str = "")` — 새 keyword 인자. `pdf_uri`(Gemini 체인)와 `doc_text`(OpenAI 체인)는 상호 배타

- [ ] **Step 1: Write the failing test**

`backend/api/test_analysis_routes.py`에 추가:

```python
    async def test_chain_stage_openai_injects_doc_text_on_first_call_only(self):
        """OpenAI 체인: 첫 스테이지에만 추출 텍스트를 싣고, 이후는 체인 id로 잇는다(스펙 R1)."""
        calls = []

        async def _fake_call(prompt, **kwargs):
            calls.append({"prompt": prompt, **kwargs})
            return {"text": '{"ok": true}', "model": "gpt-5.6-luna",
                    "tokens_in": 10, "tokens_out": 5, "interaction_id": f"resp_{len(calls)}"}

        with patch("api.analysis_routes.call_interaction", new=_fake_call):
            # 첫 스테이지: previous_interaction_id 없음 -> doc_text 포함
            r1 = await analysis_routes._run_chain_stage(
                phase="visual", prompt_chain="지시1", prompt_fallback="폴백",
                system_instruction="si", previous_interaction_id=None,
                pdf_uri=None, doc_text="논문 전문 텍스트",
                response_schema={"type": "object"},
            )
            # 후속 스테이지: 체인 id 있음 -> 지시문만
            await analysis_routes._run_chain_stage(
                phase="recipe", prompt_chain="지시2", prompt_fallback="폴백",
                system_instruction="si",
                previous_interaction_id=r1["interaction_id"],
                pdf_uri=None, doc_text="논문 전문 텍스트",
                response_schema={"type": "object"},
            )

        first, second = calls[0], calls[1]
        self.assertIn("논문 전문 텍스트", str(first["prompt"]))
        self.assertTrue(first["store"])                       # 체인이므로 store=True
        self.assertNotIn("논문 전문 텍스트", str(second["prompt"]))  # 재주입 금지
        self.assertEqual(second["previous_interaction_id"], "resp_1")

    async def test_chain_stage_rejects_both_pdf_and_doc_text(self):
        with self.assertRaises(ValueError):
            await analysis_routes._run_chain_stage(
                phase="visual", prompt_chain="지시", prompt_fallback="폴백",
                system_instruction="si", previous_interaction_id=None,
                pdf_uri="files/abc", doc_text="텍스트",
                response_schema={"type": "object"},
            )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd sasoo/backend && .venv/bin/python -m pytest api/test_analysis_routes.py -k "doc_text" -v
```

Expected: FAIL — `TypeError: _run_chain_stage() got an unexpected keyword argument 'doc_text'`

- [ ] **Step 3: `_run_chain_stage` 확장**

시그니처에 `doc_text: str = ""` 추가, 함수 첫머리에 배타 방어:

```python
    if pdf_uri and doc_text:
        raise ValueError("pdf_uri(Gemini 체인)와 doc_text(OpenAI 체인)는 동시 사용 불가")
```

`_invoke` 내부의 체인 분기(`if pdf_uri:` :990 부근)를 확장한다:

```python
        if pdf_uri or doc_text:
            # 체인 모드 — 첫 호출만 문서를 싣는다. Gemini는 PDF 파트(비전 포함),
            # OpenAI는 로컬 추출 텍스트(스펙 R1 — PDF 업로드 없음).
            if previous_interaction_id is None:
                chain_text = prompt_chain
                if restart_context:
                    chain_text = (
                        f"{prompt_chain}\n\n"
                        f"이전 분석 단계 결과(체인 재시작으로 복원):\n{restart_context}"
                    )
                if pdf_uri:
                    contents = [
                        {"type": "document", "uri": pdf_uri, "mime_type": "application/pdf"},
                        {"type": "text", "text": chain_text},
                    ]
                else:
                    contents = f"[논문 전문]\n{doc_text}\n\n{chain_text}"
            else:
                contents = prompt_chain
            return await call_interaction(
                contents,
                lane="pipeline",
                ...  # 기존 인자 유지 (store=True, previous_interaction_id, ...)
            )
```

기존 stateless 폴백 분기(`store=False`)는 그대로 둔다 — OpenAI에서도 체인 재시작
불가 시의 최후 폴백으로 동작한다.

- [ ] **Step 4: 호출부 배선 — provider에 따라 pdf_uri/doc_text 선택**

`_run_full_analysis`의 체인 준비부(:2181 부근):

```python
    provider = await active_provider()
    pdf_uri = ""
    doc_text = ""
    if provider == "openai":
        # 스크리닝이 이미 읽은 논문 텍스트를 재사용 — 새 파일 IO 없음.
        doc_text = paper_text
    else:
        from services.llm.interactions_client import upload_pdf_for_paper
        pdf_uri = await upload_pdf_for_paper(paper_id, pdf_path)  # 기존 코드 유지
```

체인 스테이지 호출 4곳에 `doc_text=doc_text`를 추가로 넘긴다. `paper_text`의 실제
변수명은 `_run_full_analysis` 안에서 screening에 넘기는 것과 같은 것을 쓴다
(`grep -n "_run_screening(" api/analysis_routes.py`로 확인).

주의: `doc_text`는 첫 스테이지에만 실리므로 토큰 예산은 Gemini 체인과 동형이다.
길이 제한은 기존 fallback 경로가 쓰는 절단 정책이 있으면 그대로 재사용한다
(`grep -n "phase_inputs\|\[:1" api/analysis_routes.py`로 확인).

- [ ] **Step 5: 전체 테스트 + Commit**

```bash
cd sasoo/backend && .venv/bin/python -m pytest -q
git add backend/api/
git commit -m "feat(pipeline): OpenAI 텍스트 주입 체인

4스테이지 체인이 OpenAI에서 PDF 업로드 없이 로컬 추출 텍스트 1회 주입 +
previous_response_id로 잇는다(스펙 R1). pdf_uri와 doc_text는 상호 배타.
pdf_file_uri는 Gemini 전용으로 남는다."
```

---

## Task 11: 다른 모델로 분석된 결과 배지 + 재분석 (스펙 §D 2단계 조회)

캐시 키 변경(Task 6) 후 옛 결과는 캐시 미스가 된다. 미스 시 해당 phase의 최신
행을 "다른 모델로 분석됨" 표시와 함께 보여주고 재분석을 안내한다.

**Files:**
- Modify: `backend/api/analysis_routes.py` — 분석 결과 조회 라우트(`grep -n "def get_analysis\|analysis_results" api/analysis_routes.py | head`로 조회 API 확인)
- Modify: `backend/models/database.py` 또는 조회 쿼리 — `analysis_results`에 `model_used` 저장 여부 확인
- Modify: `sasoo/frontend/src/lib/strings.ts`, 분석 결과 표시 컴포넌트
- Test: `backend/api/test_analysis_routes.py`

**Interfaces:**
- Consumes: Task 6의 캐시 키
- Produces: 결과 조회 응답에 `stale_model: str | null` 필드 — 현재 (provider, model, effort)와 다른 키로 만들어진 결과면 그 모델명

- [ ] **Step 1: 저장 스키마 확인**

```bash
grep -n "model_used\|model TEXT\|INSERT INTO analysis_results" backend/models/database.py backend/api/analysis_routes.py | head
```

`analysis_results`에 모델명이 저장되는 컬럼이 이미 있으면 재사용, 없으면
`ALTER TABLE` 마이그레이션(기존 `models/database.py`의 마이그레이션 관례를 따라
`_MIGRATIONS` 목록 확인)을 추가한다.

- [ ] **Step 2: Write the failing test**

```python
    async def test_result_lookup_marks_stale_model(self):
        """현재 키로 미스, 옛 행 존재 -> stale_model에 옛 모델명이 실린다(스펙 §D)."""
        old_row = {"result": '{"ok": true}', "model_used": "gemini-3.6-flash",
                   "input_hash": "옛키"}
        with (
            patch("api.analysis_routes.fetch_one",
                  new=AsyncMock(side_effect=[None, old_row])),  # 1차: 현재 키 미스, 2차: 최신 행
        ):
            payload = await analysis_routes._lookup_phase_result_with_staleness(
                paper_id=7, phase="recipe", current_hash="새키")
        self.assertEqual(payload["stale_model"], "gemini-3.6-flash")
```

(함수명 `_lookup_phase_result_with_staleness`는 신규다. 기존 조회 라우트의 실제
구조를 보고 — Step 1 — 조회 지점에 이 헬퍼를 끼워 넣는다. 기존 응답 스키마에
필드 추가는 하위호환이다.)

- [ ] **Step 3: 구현 + 프론트 배지**

백엔드: 2단계 조회 헬퍼를 구현하고 결과 조회 응답에 `stale_model`을 싣는다.

프론트: `strings.ts`에 추가 —

```typescript
    staleModelBadge: (model: string) => `${model}로 분석됨`,
    staleModelHint: '현재 설정과 다른 모델의 결과예요. 재분석하면 갱신돼요.',
```

분석 결과 헤더 컴포넌트(`grep -rn "reAnalyze\|재분석" frontend/src/pages/Workbench.tsx
frontend/src/components/ | head`로 재분석 버튼 위치 확인)에서 `stale_model`이 오면
기존 재분석 버튼 옆에 배지를 표시한다. 기존 `reAnalyze` 버튼을 재사용하고 새
버튼을 만들지 않는다.

- [ ] **Step 4: 테스트 + Commit**

```bash
cd sasoo/backend && .venv/bin/python -m pytest -q
cd ../.. && cd sasoo && pnpm test:unit && cd frontend && npx tsc --noEmit
git add -A
git commit -m "feat(analysis): 다른 모델로 분석된 결과에 배지 + 재분석 안내

캐시 키 변경 후 옛 결과는 미스가 되므로, 최신 행을 stale_model 표시와 함께
보여준다(스펙 §D 2단계 조회). 데이터 마이그레이션 없이 배지 경로로 흡수."
```

---

## Task 12: 측정 도구 확장 (R9)

`tools/provider_compare.py`를 5단계 전체 + 품질·비용 신호 기록으로 확장한다.
프로덕션 코드 무수정(extraction_audit 관례).

**Files:**
- Modify: `backend/tools/provider_compare.py`

**Interfaces:**
- Consumes: Task 3의 레지스트리, Task 7의 openai_client
- Produces: 실행 산출 JSON에 스테이지별 `{provider, model, effort, tokens_in, tokens_out, reasoning_tokens, cached_tokens, defect_retries, latency_s, cost_usd}` 기록

- [ ] **Step 1: 기존 도구 구조 확인**

```bash
grep -n "def \|argparse\|json.dump" backend/tools/provider_compare.py | head -20
```

- [ ] **Step 2: 확장 구현**

기존 3개 스테이지 비교를 5단계 전체(screening·citation·visual·recipe·deep_dive)로
늘리고, 스테이지 결과마다 다음을 기록한다:

```python
record = {
    "provider": provider,
    "model": choice.model,
    "effort": choice.effort,
    "tokens_in": result["tokens_in"],
    "tokens_out": result["tokens_out"],
    "reasoning_tokens": result.get("tokens_thought", 0),
    # cached_tokens: openai_client가 usage.input_tokens_details.cached_tokens를
    # dict에 싣도록 Task 7 반환부에 "tokens_cached" 키를 추가(정보용)한 뒤 기록
    "tokens_cached": result.get("tokens_cached", 0),
    "defect": _stage_result_defect(result.get("text") or ""),  # 재시도 발화 신호
    "latency_s": elapsed,
    "cost_usd": calc_cost(result["model"], result["tokens_in"], result["tokens_out"]),
}
```

effort 비교 모드(예: deep_dive를 high vs xhigh로 같은 논문에 실행)를 CLI 인자로
추가한다: `--role deep_dive --efforts high,xhigh`.

- [ ] **Step 3: 실행 확인 + Commit**

```bash
cd sasoo/backend && OPENAI_API_KEY=... GEMINI_API_KEY=... .venv/bin/python tools/provider_compare.py --paper <검증용 PDF 경로> 2>&1 | tail -5
git add backend/tools/provider_compare.py
git commit -m "tools: provider 비교를 5단계 전체 + 품질·비용 신호로 확장

reasoning/cached 토큰, 결함 재시도 발화, effort 비교 모드(R9). 승격 판단은
이 도구의 기록으로만 한다 — 앱 내 A/B 없음."
```

---

## 최종 검증

- [ ] **백엔드 전체 테스트**: `cd sasoo/backend && .venv/bin/python -m pytest -q` — 전부 통과
- [ ] **프론트**: `cd sasoo && pnpm test:unit && cd frontend && npx tsc --noEmit` — 통과
- [ ] **Gemini 회귀**: Gemini 키만 있는 환경에서 논문 1편 전체 분석 완주. 스테이지별 모델·비용이 기존과 동일한지 확인
- [ ] **OpenAI 완주**: OpenAI 키만 있는 환경(GEMINI_API_KEY 제거)에서 ①업로드→분석 5단계 완주 ②채팅 스트리밍 ③그림 설명 ④Mermaid — 전부 동작. `pdf_visual_engine`은 `odl`이어야 한다(LLM 비전 파싱은 범위 외)
- [ ] **키 상태 4시나리오**: OpenAI만/Gemini만/둘 다/없음 — 설정 화면 표시와 /run 거절 메시지 확인
- [ ] **12편 정답셋 기록**: `tools/` 추출 정확도 lane을 OpenAI 경로로 실행해 결과를 **기록**(게이트 아님 — 스펙 결정 1). 결과를 `docs/superpowers/plans/`에 남긴다
- [ ] **설정 문구 갱신**: PR #41의 "분석은 항상 Gemini" 문구(`strings.ts` aiProviderDesc)를 실동작에 맞게 되돌린다 — "분석·그림 판독·도해 생성에 적용돼요" + 카드 모델명을 `GPT-5.6 Luna`/`Gemini 3.6 Flash`로 복원. **이 시점부터 그 문구가 다시 참이 된다.**
- [ ] **버전·릴리스**: 버전 bump는 `scripts/sync-version.js` 경유(관례). PR 병합·publish는 사용자가 수행

## 이 플랜이 다루지 않는 것 (스펙 범위 외 + 완료분)

- PDF 전체 비전 파싱의 OpenAI 대체(`pdf_visual_engine` — 범위 외, R2)
- Terra·Sol 티어 노출, phase별 모델 선택 UI, effort 슬라이더 (스펙 범위 밖)
- 설정 UI·키 상태 머신·ai_provider 마이그레이션 (구플랜 Task 4·10·11·12·13 — 병합 완료)
- 캐시 히트 비용 재합산 버그(R7-6) — 이 플랜과 독립적인 선행 수정 후보로 남긴다
