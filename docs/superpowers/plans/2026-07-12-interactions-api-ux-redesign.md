# Interactions API 전환 + 에이전트 편성 UX 재설계 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 백엔드 LLM 호출을 구식 `generate_content`에서 Gemini Interactions API(상태 유지 체인)로 전환하고, 에이전트 편성 UI를 제거해 연구자용 자동화 UX(분야 자동 감지 + 분석 초점 + 설명 수준 6단계)로 교체한다.

**Architecture:** 스크리닝은 독립 stateless 호출(`gemini-3.1-flash-lite`), 본 분석(Visual→Recipe→DeepDive→Viz플래닝)은 PDF를 Files API로 1회 업로드한 뒤 `gemini-3.5-flash` 단일 체인(`previous_interaction_id`)으로 연결한다. 프론트는 Agents 페이지를 제거하고 설정 2개(연구 분야, 기본 설명 수준) + 업로드 시 초점/수준 입력 + 결과 화면 수준 재작성(체인 연장)만 노출한다.

**Tech Stack:** FastAPI + `google-genai` ≥2.3.0 (Python), React+TS (frontend), SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-07-12-interactions-api-ux-redesign-design.md`

## Global Constraints

- SDK: `google-genai>=2.3.0` (requirements.txt 13행 `google-genai>=1.0.0`에서 상향).
- 모델 ID: 본 체인 `gemini-3.5-flash`, 스크리닝 `gemini-3.1-flash-lite` (`-preview` 접미사 금지).
- `temperature`/`top_p`/`top_k` 사용 금지. `thinking_budget` 금지 — `thinking_level`("minimal"|"low"|"medium"|"high")만 사용.
- Interactions API는 `types.*` 래퍼(`GenerateContentConfig`, `Part`, `Content`) 미사용 — 전부 plain dict.
- `tools`/`system_instruction`/`generation_config`는 interaction-scoped — `previous_interaction_id`를 써도 매 호출 재지정.
- 설명 수준 키(저장값): `elementary|middle|high|undergrad|masters|phd`. 기본값 `masters`. 한국어 라벨: 초등학생/중학생/고등학생/학부생/석사생/박사생.
- 분석 초점 칩 키: `reproduction|contribution|limitations|theory|related_work`.
- 모든 사용자 노출 문자열은 한국어, `src/lib/strings.ts` 경유.
- 파괴 금지: `lib/agents.ts`(getAgentMeta/getAllAgents/fetchAllAgents), `AgentAvatar.tsx`, backend `GET /api/agents`·`GET /api/agents/{name}`은 Upload/Workbench가 사용하므로 유지.
- 각 태스크 완료 시 커밋. 백엔드 테스트: `cd sasoo/backend && python3 -m pytest`. 프론트 검증: `cd sasoo/frontend && npm run build`.
- **API 형태 검증**: Interactions API는 학습 데이터보다 최신이다. Task 4 시작 전 반드시
  `https://ai.google.dev/gemini-api/docs/interactions/structured-output.md.txt`와
  `https://ai.google.dev/static/api/interactions.md.txt`를 fetch해 `response_format` 정확한 형태(단일 객체 vs 배열)와
  `interaction.usage` 필드명을 확인하고, 다르면 Task 4 코드의 해당 두 지점만 조정한다(주석 `# VERIFY:`로 표시해둠).

---

### Task 1: pricing.py 모델 가격 갱신

**Files:**
- Modify: `sasoo/backend/services/pricing.py`
- Test: `sasoo/backend/services/test_pricing.py` (신규)

**Interfaces:**
- Consumes: 없음 (독립)
- Produces: `calc_cost(model: str, input_tokens: int, output_tokens: int) -> float`가 `gemini-3.5-flash`, `gemini-3.1-flash-lite`를 지원. 이후 태스크의 비용 계산이 의존.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# sasoo/backend/services/test_pricing.py
from services.pricing import PRICING, calc_cost


def test_gemini_35_flash_pricing():
    # $1.50 in / $9.00 out per 1M tokens
    assert calc_cost("gemini-3.5-flash", 1_000_000, 1_000_000) == 10.50


def test_gemini_31_flash_lite_pricing():
    # $0.25 in / $1.50 out per 1M tokens
    assert calc_cost("gemini-3.1-flash-lite", 1_000_000, 1_000_000) == 1.75


def test_claude_models_removed():
    assert not any(k.startswith("claude") for k in PRICING)
```

- [ ] **Step 2: 실패 확인**

Run: `cd sasoo/backend && python3 -m pytest services/test_pricing.py -v`
Expected: FAIL (KeyError 또는 assert 실패)

- [ ] **Step 3: 구현**

`pricing.py`의 `PRICING` 딕셔너리에서 `claude-*` 2개 항목과 `gemini-2.5-flash-preview-05-20`, `gemini-2.0-flash` 항목을 삭제하고 다음을 추가:

```python
    "gemini-3.5-flash": {"input": 1.50, "output": 9.00},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
```

`calc_cost`의 폴백(`PRICING.get(model, PRICING["gemini-3-flash-preview"])`)은 `PRICING["gemini-3.5-flash"]` 폴백으로 변경.

- [ ] **Step 4: 테스트 통과 확인**

Run: `cd sasoo/backend && python3 -m pytest services/test_pricing.py -v`
Expected: 3 PASS

- [ ] **Step 5: 커밋**

```bash
git add sasoo/backend/services/pricing.py sasoo/backend/services/test_pricing.py
git commit -m "feat(pricing): add gemini-3.5-flash/3.1-flash-lite, drop claude legacy"
```

---

### Task 2: 설정 백엔드 — research_context / default_explanation_level

**Files:**
- Modify: `sasoo/backend/api/settings.py` (`DEFAULT_SETTINGS` L24-38, `get_settings()` L145-166)
- Modify: `sasoo/backend/models/schemas.py` (`SettingsModel` L416-437, `SettingsUpdate` L440-453)
- Test: `sasoo/backend/api/test_settings.py` (기존 파일에 테스트 추가)

**Interfaces:**
- Consumes: 없음
- Produces: `GET /api/settings` 응답과 `PUT /api/settings` 요청에 `research_context: str`(기본 `""`), `default_explanation_level: str`(기본 `"masters"`) 필드. Task 6·10이 의존.

- [ ] **Step 1: 실패하는 테스트 작성** — `test_settings.py`의 기존 테스트 스타일(기존 fixture 재사용)을 따라 추가:

```python
async def test_new_researcher_settings_defaults(client):
    resp = await client.get("/api/settings")
    data = resp.json()
    assert data["research_context"] == ""
    assert data["default_explanation_level"] == "masters"


async def test_update_researcher_settings(client):
    resp = await client.put("/api/settings", json={
        "research_context": "페로브스카이트 태양전지 소자 물리",
        "default_explanation_level": "phd",
    })
    assert resp.status_code == 200
    data = (await client.get("/api/settings")).json()
    assert data["research_context"] == "페로브스카이트 태양전지 소자 물리"
    assert data["default_explanation_level"] == "phd"
```

(기존 파일의 client fixture가 sync TestClient라면 async 제거하고 동일 패턴으로 맞춘다.)

- [ ] **Step 2: 실패 확인** — `python3 -m pytest api/test_settings.py -v` → KeyError FAIL

- [ ] **Step 3: 구현**
  - `DEFAULT_SETTINGS`에 `"research_context": ""`, `"default_explanation_level": "masters"` 추가.
  - `SettingsModel`과 `SettingsUpdate` 양쪽에 필드 추가:

```python
    research_context: str = ""          # SettingsModel
    default_explanation_level: str = "masters"

    research_context: Optional[str] = None   # SettingsUpdate
    default_explanation_level: Optional[str] = None
```

  - `get_settings()`의 반환 매핑에 `research_context=raw.get("research_context", "")`, `default_explanation_level=raw.get("default_explanation_level", "masters")` 추가. `_API_KEY_FIELDS`에는 넣지 않는다(암호화 불필요).

- [ ] **Step 4: 통과 확인** — `python3 -m pytest api/test_settings.py -v` → PASS

- [ ] **Step 5: 커밋** — `git commit -m "feat(settings): research_context and default_explanation_level fields"`

---

### Task 3: papers DB 확장 — 분석 파라미터 + 체인 체크포인트 컬럼

**Files:**
- Modify: `sasoo/backend/models/database.py` (`SCHEMA_SQL` L136-164, `init_db()` ALTER 패턴 L266+)
- Modify: `sasoo/backend/models/schemas.py` (`PaperUpdate` L84)
- Modify: `sasoo/backend/api/papers.py` (`update_paper` L759-760)
- Test: `sasoo/backend/api/test_papers_params.py` (신규)

**Interfaces:**
- Consumes: 없음
- Produces:
  - `papers` 신규 컬럼: `explanation_level TEXT`, `analysis_focus TEXT`(JSON: `{"chips": ["reproduction",...], "note": "..."}`), `pdf_file_uri TEXT`, `pdf_file_expires_at TEXT`(ISO8601).
  - `analysis_results` 신규 컬럼: `interaction_id TEXT`.
  - `PATCH /api/papers/{id}`가 `explanation_level`, `analysis_focus`(dict) 수용.
  - Task 6·7·12가 의존.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# sasoo/backend/api/test_papers_params.py
# 기존 test_analysis_routes.py의 DB fixture/셋업 방식을 그대로 따라 작성
import json


async def test_patch_paper_analysis_params(client, sample_paper_id):
    resp = await client.patch(f"/api/papers/{sample_paper_id}", json={
        "explanation_level": "high",
        "analysis_focus": {"chips": ["reproduction", "theory"], "note": "격자 정합 조건이 궁금함"},
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["explanation_level"] == "high"
    assert json.loads(data["analysis_focus"]) if isinstance(data["analysis_focus"], str) else data["analysis_focus"]
```

- [ ] **Step 2: 실패 확인** — `python3 -m pytest api/test_papers_params.py -v` → FAIL

- [ ] **Step 3: 구현**
  - `SCHEMA_SQL`의 `papers` CREATE에 4개 컬럼, `analysis_results` CREATE에 `interaction_id TEXT` 추가 (신규 DB용).
  - `init_db()`에 기존 패턴(L292-296 스타일) 그대로 ALTER 5개 추가:

```python
    for ddl in (
        "ALTER TABLE papers ADD COLUMN explanation_level TEXT",
        "ALTER TABLE papers ADD COLUMN analysis_focus TEXT",
        "ALTER TABLE papers ADD COLUMN pdf_file_uri TEXT",
        "ALTER TABLE papers ADD COLUMN pdf_file_expires_at TEXT",
        "ALTER TABLE analysis_results ADD COLUMN interaction_id TEXT",
    ):
        try:
            await conn.execute(ddl)
        except Exception:
            pass  # column already exists
```

  - `PaperUpdate`에 `explanation_level: Optional[str] = None`, `analysis_focus: Optional[dict] = None` 추가.
  - `update_paper`에서 `analysis_focus`는 `json.dumps(update.analysis_focus, ensure_ascii=False)`로 저장. 기존 필드 업데이트 로직(동적 SET 구성)에 두 필드를 합류시킨다.

- [ ] **Step 4: 통과 확인** — `python3 -m pytest api/test_papers_params.py -v` → PASS

- [ ] **Step 5: 커밋** — `git commit -m "feat(db): analysis params and interaction checkpoint columns"`

---

### Task 4: interactions_client.py — Interactions API 클라이언트 계층

**Files:**
- Create: `sasoo/backend/services/llm/interactions_client.py`
- Modify: `sasoo/backend/requirements.txt` (13행 → `google-genai>=2.3.0`)
- Test: `sasoo/backend/services/llm/test_interactions_client.py` (신규)

**Interfaces:**
- Consumes: Task 1의 `calc_cost`.
- Produces (이후 모든 백엔드 태스크가 사용):

```python
async def call_interaction(
    prompt: str | list[dict],            # 텍스트 또는 content dict 리스트
    *,
    model: str = "gemini-3.5-flash",
    system_instruction: str | None = None,   # None이면 _SYSTEM_INSTRUCTION_KO
    thinking_level: str | None = None,        # "minimal"|"low"|"medium"|"high"
    previous_interaction_id: str | None = None,
    response_schema: dict | None = None,      # JSON Schema → structured output
    store: bool = True,
) -> dict:
    """returns {"text", "model", "tokens_in", "tokens_out", "interaction_id"}"""

async def upload_pdf_for_paper(paper_id: int, pdf_path: str) -> str:
    """Files API 업로드(48h 유효). papers.pdf_file_uri/expires_at 캐시,
    만료 시 재업로드. returns file_uri"""
```

- [ ] **Step 0: API 형태 검증** — Global Constraints의 두 문서를 WebFetch로 확인하고 `response_format` 형태와 usage 필드명을 메모. 아래 코드의 `# VERIFY:` 두 곳을 필요시 수정.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# sasoo/backend/services/llm/test_interactions_client.py
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.llm.interactions_client import call_interaction


def _fake_interaction(text="결과", interaction_id="int_1"):
    return SimpleNamespace(
        id=interaction_id,
        output_text=text,
        usage=SimpleNamespace(total_input_tokens=100, total_output_tokens=50),
        status="completed",
    )


def test_call_interaction_basic():
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = _fake_interaction()
    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        result = asyncio.run(call_interaction("안녕"))
    assert result["text"] == "결과"
    assert result["interaction_id"] == "int_1"
    assert result["tokens_in"] == 100
    kwargs = fake_client.interactions.create.call_args.kwargs
    assert kwargs["model"] == "gemini-3.5-flash"
    assert "temperature" not in str(kwargs)


def test_call_interaction_chains_previous_id():
    fake_client = MagicMock()
    fake_client.interactions.create.return_value = _fake_interaction(interaction_id="int_2")
    with patch("services.llm.interactions_client._get_client", return_value=fake_client):
        asyncio.run(call_interaction("후속", previous_interaction_id="int_1"))
    assert fake_client.interactions.create.call_args.kwargs["previous_interaction_id"] == "int_1"


def test_call_interaction_retries_on_error():
    fake_client = MagicMock()
    fake_client.interactions.create.side_effect = [
        RuntimeError("503"), RuntimeError("503"), _fake_interaction(),
    ]
    with patch("services.llm.interactions_client._get_client", return_value=fake_client), \
         patch("services.llm.interactions_client._RETRY_DELAYS", [0, 0]):
        result = asyncio.run(call_interaction("재시도"))
    assert result["text"] == "결과"
    assert fake_client.interactions.create.call_count == 3
```

- [ ] **Step 2: 실패 확인** — `python3 -m pytest services/llm/test_interactions_client.py -v` → ImportError FAIL

- [ ] **Step 3: 구현**

```python
# sasoo/backend/services/llm/interactions_client.py
"""Sasoo - Gemini Interactions API client layer.

generate_content을 대체한다. types.* 래퍼 없이 plain dict만 사용.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_SYSTEM_INSTRUCTION_KO = (
    "너는 Sasoo(사수)라는 한국어 AI 연구 보조원이야. "
    "모든 출력 텍스트를 반드시 한국어로 작성해. "
    "JSON key 이름만 영어로 유지하고, 모든 value(문장, 설명, 리스트 항목 등)는 한국어로 써. "
    "영어로 쓰지 마."
)

_RETRY_DELAYS = [2, 8]  # 3회 시도, 지수 백오프
_FILE_TTL = timedelta(hours=47)  # Files API 48h에서 1h 여유


def _get_client():
    from google import genai
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set")
    return genai.Client(api_key=api_key)


async def call_interaction(
    prompt,
    *,
    model: str = "gemini-3.5-flash",
    system_instruction: str | None = None,
    thinking_level: str | None = None,
    previous_interaction_id: str | None = None,
    response_schema: dict | None = None,
    store: bool = True,
) -> dict:
    def _sync_call():
        client = _get_client()
        kwargs: dict = {
            "model": model,
            "input": prompt,
            "system_instruction": system_instruction or _SYSTEM_INSTRUCTION_KO,
            "store": store,
        }
        if thinking_level:
            kwargs["generation_config"] = {"thinking_level": thinking_level}
        if previous_interaction_id:
            kwargs["previous_interaction_id"] = previous_interaction_id
        if response_schema:
            # VERIFY: structured-output.md.txt 기준 단일 객체 vs 배열 확인
            kwargs["response_format"] = {
                "type": "text",
                "mime_type": "application/json",
                "schema": response_schema,
            }

        last_err: Exception | None = None
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                interaction = client.interactions.create(**kwargs)
                usage = getattr(interaction, "usage", None)
                # VERIFY: usage 필드명 (total_input_tokens / total_output_tokens)
                tokens_in = getattr(usage, "total_input_tokens", 0) or 0
                tokens_out = getattr(usage, "total_output_tokens", 0) or 0
                return {
                    "text": interaction.output_text or "",
                    "model": model,
                    "tokens_in": tokens_in,
                    "tokens_out": tokens_out,
                    "interaction_id": getattr(interaction, "id", None),
                }
            except Exception as exc:  # noqa: BLE001 - 재시도 후 재던짐
                last_err = exc
                if attempt < len(_RETRY_DELAYS):
                    import time
                    time.sleep(_RETRY_DELAYS[attempt])
        raise RuntimeError(f"Interactions API call failed after retries: {last_err}")

    return await asyncio.get_event_loop().run_in_executor(None, _sync_call)


async def upload_pdf_for_paper(paper_id: int, pdf_path: str) -> str:
    """PDF를 Files API에 업로드하고 papers 테이블에 uri/만료를 캐시한다."""
    from models.database import fetch_one, execute_update

    row = await fetch_one(
        "SELECT pdf_file_uri, pdf_file_expires_at FROM papers WHERE id = ?", (paper_id,)
    )
    now = datetime.now(timezone.utc)
    if row and row["pdf_file_uri"] and row["pdf_file_expires_at"]:
        try:
            expires = datetime.fromisoformat(row["pdf_file_expires_at"])
            if expires > now:
                return row["pdf_file_uri"]
        except ValueError:
            pass

    def _sync_upload():
        client = _get_client()
        uploaded = client.files.upload(file=pdf_path)
        return uploaded.uri

    uri = await asyncio.get_event_loop().run_in_executor(None, _sync_upload)
    await execute_update(
        "UPDATE papers SET pdf_file_uri = ?, pdf_file_expires_at = ? WHERE id = ?",
        (uri, (now + _FILE_TTL).isoformat(), paper_id),
    )
    return uri
```

requirements.txt 13행을 `google-genai>=2.3.0`으로 변경 후 `pip3 install -U "google-genai>=2.3.0"`.

- [ ] **Step 4: 통과 확인** — `python3 -m pytest services/llm/test_interactions_client.py -v` → 3 PASS

- [ ] **Step 5: 실제 API 스모크 (1회)** — `GEMINI_API_KEY`가 설정된 환경에서:

```bash
cd sasoo/backend && python3 -c "
import asyncio
from services.llm.interactions_client import call_interaction
r = asyncio.run(call_interaction('한 문장으로 인사해줘'))
print(r['interaction_id'], r['text'][:50])
r2 = asyncio.run(call_interaction('방금 뭐라고 했는지 반복해줘', previous_interaction_id=r['interaction_id']))
print(r2['text'][:50])
"
```
Expected: 두 줄 출력, 두 번째 줄이 첫 응답 내용을 기억함. 실패 시 Step 0의 VERIFY 지점 재확인.

- [ ] **Step 6: 커밋** — `git commit -m "feat(llm): interactions API client layer with files upload cache"`

---

### Task 5: 스크리닝 마이그레이션 (stateless + structured output)

**Files:**
- Modify: `sasoo/backend/api/analysis_routes.py` (`_run_screening` L290-369, import L77)
- Test: `sasoo/backend/api/test_analysis_routes.py` (기존 스타일로 테스트 추가)

**Interfaces:**
- Consumes: Task 4 `call_interaction`.
- Produces: `_run_screening` 반환 dict에 기존 키 유지 + `interaction_id`(None 가능). 스크리닝 결과 JSON 스키마는 기존과 동일(`domain`, `agent_recommended`, ...) — 다운스트림/프론트 무변경.

- [ ] **Step 1: 실패하는 테스트 작성** — 기존 test_analysis_routes.py의 목킹 스타일을 따라, `_call_gemini` 대신 `call_interaction`이 `model="gemini-3.1-flash-lite"`와 `response_schema`(dict, `properties.domain` 포함), `store=False`로 호출되는지 검증하는 테스트 추가:

```python
async def test_screening_uses_interactions_stateless(monkeypatch):
    calls = {}
    async def fake_call(prompt, **kwargs):
        calls.update(kwargs)
        return {"text": '{"domain": "optics", "agent_recommended": "photon", '
                        '"relevance_score": 0.9, "key_topics": [], '
                        '"methodology_type": "experimental", "summary": "요약", '
                        '"is_experimental": true, "has_figures": true, '
                        '"estimated_complexity": "low"}',
                "model": "gemini-3.1-flash-lite", "tokens_in": 10, "tokens_out": 10,
                "interaction_id": None}
    monkeypatch.setattr("api.analysis_routes.call_interaction", fake_call)
    # ... 기존 픽스처로 paper 생성 후 _run_screening 직접 호출 ...
    assert calls["model"] == "gemini-3.1-flash-lite"
    assert calls["store"] is False
    assert "domain" in calls["response_schema"]["properties"]
```

- [ ] **Step 2: 실패 확인** — FAIL (call_interaction import 없음)

- [ ] **Step 3: 구현**
  - `analysis_routes.py` 상단 import에 `from services.llm.interactions_client import call_interaction` 추가.
  - `_run_screening`에서 프롬프트의 "Return ONLY valid JSON …" 블록과 JSON 골격을 제거하고, 대신 모듈 상수로 스키마 정의:

```python
_SCREENING_SCHEMA = {
    "type": "object",
    "properties": {
        "domain": {"type": "string", "enum": ["optics", "materials", "bio", "energy", "quantum", "general"]},
        "agent_recommended": {"type": "string"},
        "relevance_score": {"type": "number"},
        "key_topics": {"type": "array", "items": {"type": "string"}},
        "methodology_type": {"type": "string", "enum": ["experimental", "computational", "theoretical", "review"]},
        "summary": {"type": "string"},
        "is_experimental": {"type": "boolean"},
        "has_figures": {"type": "boolean"},
        "estimated_complexity": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["domain", "summary", "relevance_score"],
}
```

  - 호출 교체:

```python
    result = await call_interaction(
        prompt,
        model="gemini-3.1-flash-lite",
        thinking_level="minimal",
        response_schema=_SCREENING_SCHEMA,
        store=False,
    )
```

  - `_clean_llm_json`/JSON 검증 로직은 안전망으로 유지(structured output 실패 대비).

- [ ] **Step 4: 통과 확인** — `python3 -m pytest api/test_analysis_routes.py -v` → 기존+신규 PASS

- [ ] **Step 5: 커밋** — `git commit -m "feat(pipeline): migrate screening to interactions API structured output"`

---

### Task 6: 본 체인 마이그레이션 — Visual→Recipe→DeepDive→Viz플래닝

**Files:**
- Modify: `sasoo/backend/api/analysis_routes.py`
  - `_run_full_analysis` L1485-1664, `_run_visual` L557-739, `_run_recipe` L742+, `_run_deep_dive` L936+, viz 플래닝 호출 L1125·L1206, `_run_citation` 내 호출 L466, `_insert_analysis_result` L235
- Create: `sasoo/backend/api/analysis_context.py` (system_instruction 빌더)
- Test: `sasoo/backend/api/test_analysis_context.py` (신규), 기존 test_analysis_routes.py 갱신

**Interfaces:**
- Consumes: Task 3 컬럼, Task 4 `call_interaction`/`upload_pdf_for_paper`, Task 5 스크리닝 결과.
- Produces:
  - `build_chain_system_instruction(persona_prompt: str, research_context: str, focus: dict | None, level_key: str) -> str`
  - 각 체인 스테이지가 `interaction_id`를 `analysis_results.interaction_id`에 저장 (Task 7이 재작성 기점으로 사용).
  - `EXPLANATION_LEVELS: dict[str, str]` — 수준 키 → 지시문 매핑 (Task 7 재사용).

- [ ] **Step 1: 컨텍스트 빌더 테스트 작성**

```python
# sasoo/backend/api/test_analysis_context.py
from api.analysis_context import build_chain_system_instruction, EXPLANATION_LEVELS


def test_level_keys_complete():
    assert set(EXPLANATION_LEVELS) == {"elementary", "middle", "high", "undergrad", "masters", "phd"}


def test_instruction_composition():
    si = build_chain_system_instruction(
        persona_prompt="광학 전문가 페르소나",
        research_context="페로브스카이트 태양전지",
        focus={"chips": ["reproduction"], "note": "격자 정합"},
        level_key="high",
    )
    assert "광학 전문가 페르소나" in si
    assert "페로브스카이트" in si
    assert "재현 방법" in si
    assert "격자 정합" in si
    assert EXPLANATION_LEVELS["high"][:20] in si
    assert "한국어" in si  # 기본 한국어 지시 포함


def test_instruction_defaults():
    si = build_chain_system_instruction("", "", None, "masters")
    assert EXPLANATION_LEVELS["masters"][:20] in si
```

- [ ] **Step 2: 실패 확인** — ImportError FAIL

- [ ] **Step 3: 빌더 구현**

```python
# sasoo/backend/api/analysis_context.py
"""분석 체인 system_instruction 조립. 페르소나 + 연구자 컨텍스트 + 초점 + 설명 수준."""

from services.llm.interactions_client import _SYSTEM_INSTRUCTION_KO

EXPLANATION_LEVELS: dict[str, str] = {
    "elementary": "설명 수준: 초등학생. 전문용어를 쓰지 말고 일상 비유로 설명해. 수식은 말로 풀어써.",
    "middle": "설명 수준: 중학생. 기초 과학 용어만 사용하고 새 용어는 즉시 한 줄로 정의해.",
    "high": "설명 수준: 고등학생. 고교 물리/화학/생물 수준의 용어와 간단한 수식을 사용해.",
    "undergrad": "설명 수준: 학부생. 전공 기초 용어를 사용하되 대학원 수준 개념은 짧게 배경을 설명해.",
    "masters": "설명 수준: 석사생. 해당 분야 표준 용어와 수식을 자유롭게 사용해.",
    "phd": "설명 수준: 박사생. 최신 문헌 맥락, 방법론의 한계, 미해결 논점까지 전문가 수준으로 다뤄.",
}

_FOCUS_LABELS = {
    "reproduction": "재현 방법",
    "contribution": "핵심 기여",
    "limitations": "한계·후속 연구",
    "theory": "수식·이론",
    "related_work": "선행연구 대비",
}


def build_chain_system_instruction(
    persona_prompt: str,
    research_context: str,
    focus: dict | None,
    level_key: str,
) -> str:
    parts = [_SYSTEM_INSTRUCTION_KO]
    if persona_prompt.strip():
        parts.append(persona_prompt.strip())
    if research_context.strip():
        parts.append(f"사용자의 연구 분야: {research_context.strip()}. 이 분야 관점에서 관련성을 짚어줘.")
    if focus:
        chips = [_FOCUS_LABELS[c] for c in focus.get("chips", []) if c in _FOCUS_LABELS]
        if chips:
            parts.append(f"분석 초점: {', '.join(chips)}에 비중을 둬.")
        note = (focus.get("note") or "").strip()
        if note:
            parts.append(f"사용자가 특별히 궁금한 점: {note}")
    parts.append(EXPLANATION_LEVELS.get(level_key, EXPLANATION_LEVELS["masters"]))
    return "\n\n".join(parts)
```

- [ ] **Step 4: 빌더 테스트 통과 확인** — `python3 -m pytest api/test_analysis_context.py -v` → PASS

- [ ] **Step 5: 파이프라인 체인 전환** — `analysis_routes.py`:

1. `_insert_analysis_result` 시그니처에 `interaction_id: str | None = None` 파라미터를 추가하고 INSERT 컬럼에 포함.
2. `_run_full_analysis`에서 스크리닝 후, 체인 준비 블록 추가 (r1 파싱 → domain → 페르소나 → 설정 로드 → PDF 업로드 → system_instruction):

```python
        # --- 체인 준비 ---
        import json as _json
        from api.analysis_context import build_chain_system_instruction
        from services.llm.interactions_client import upload_pdf_for_paper
        from services.agents import get_agent_for_domain
        from api.settings import get_raw_settings  # 없으면 기존 설정 조회 헬퍼 사용

        try:
            screening_data = _json.loads(r1.get("text") or "{}")
        except _json.JSONDecodeError:
            screening_data = {}
        domain = screening_data.get("domain") or paper.get("domain") or "general"
        agent = get_agent_for_domain(domain)
        await execute_update(
            "UPDATE papers SET domain = ?, agent_used = ? WHERE id = ?",
            (domain, agent.name, paper_id),
        )

        settings_raw = await get_raw_settings()
        focus = _json.loads(paper["analysis_focus"]) if paper.get("analysis_focus") else None
        level_key = paper.get("explanation_level") or settings_raw.get("default_explanation_level", "masters")
        system_instruction = build_chain_system_instruction(
            persona_prompt=agent.get_deep_dive_overlay() if hasattr(agent, "get_deep_dive_overlay") else "",
            research_context=settings_raw.get("research_context", ""),
            focus=focus,
            level_key=level_key,
        )

        pdf_path = str(paper_dir / "paper.pdf")  # 실제 PDF 파일명 규칙은 get_paper_dir 사용처 확인
        chain_prev_id: str | None = None
        pdf_uri: str | None = None
        try:
            pdf_uri = await upload_pdf_for_paper(paper_id, pdf_path)
        except Exception as exc:
            logger.warning("PDF upload failed for paper %s, falling back to text context: %s", paper_id, exc)
```

   (`agent`의 오버레이 접근자 이름은 `services/agents/base_agent.py`의 실제 메서드명을 확인해 사용 — Screening/Visual/Recipe/DeepDive 4개 오버레이 중 파이프라인 전체 페르소나로는 에이전트 `.md`의 frontmatter 설명+DeepDive 오버레이를 합쳐 쓴다. `get_raw_settings`가 없으면 `api/settings.py`에 내부용 `async def get_raw_settings() -> dict` (마스킹 없이 dict 반환)를 추가한다.)

3. `_run_visual`/`_run_recipe`/`_run_deep_dive`와 viz 플래닝 함수의 시그니처에 `system_instruction: str`, `previous_interaction_id: str | None`, `pdf_uri: str | None` 파라미터 추가. 각 함수 내부에서:
   - 첫 체인 호출(visual)만 PDF 문서를 input에 포함:

```python
    if pdf_uri and previous_interaction_id is None:
        contents = [
            {"type": "document", "uri": pdf_uri, "mime_type": "application/pdf"},
            {"type": "text", "text": prompt},
        ]
    else:
        contents = prompt

    result = await call_interaction(
        contents,
        model="gemini-3.5-flash",
        system_instruction=system_instruction,
        thinking_level=_STAGE_THINKING[phase],   # visual=low, recipe=medium, deep_dive=high, visualization=medium
        previous_interaction_id=previous_interaction_id,
        response_schema=_STAGE_SCHEMAS[phase],
    )
```

   - 모듈 상수 추가:

```python
_STAGE_THINKING = {"visual": "low", "recipe": "medium", "deep_dive": "high", "visualization": "medium"}
```

   - `_STAGE_SCHEMAS`: 각 스테이지 프롬프트에 이미 명시된 JSON 골격(예: visual의 `figure_count`, `quality_summary`, `key_findings_from_visuals` 등)을 Task 5와 같은 방식의 JSON Schema dict로 옮긴다. 프롬프트에서 "Return ONLY valid JSON" 블록은 제거하되 한국어 지시는 유지.
   - PDF가 체인에 있으므로 프롬프트의 `{visual_input}` 등 대용량 텍스트 삽입은 첫 체인 호출에서 제거하고, 이후 스테이지는 서버 상태를 신뢰해 지시문만 보낸다. **단, PDF 업로드 실패 시(`pdf_uri is None`) 기존 `phase_inputs` 텍스트 삽입 경로를 유지**(폴백).
   - 각 스테이지 완료 시 `_insert_analysis_result(..., interaction_id=result.get("interaction_id"))`로 저장하고, `_run_full_analysis`에서 `chain_prev_id = result["interaction_id"] or chain_prev_id`로 전달.
4. `_run_full_analysis`의 `previous` 리스트(텍스트 이어붙이기, L1577-1633)는 체인 성공 경로에서는 사용하지 않는다 — 폴백 경로(pdf_uri None)에서만 유지.
5. `_run_citation`(L466)과 기타 `_call_gemini` 사용처(L2044 explain_figure, L2349 chat)는 기계적 치환: `await call_interaction(prompt, model="gemini-3.5-flash", store=False)` (+이미지가 있으면 `{"type":"image","data":...,"mime_type":...}` content dict). 치환 후 `analysis_helpers.py`의 `_call_gemini`/`_call_anthropic`/`_get_anthropic_client`를 삭제하고 import 정리.

- [ ] **Step 6: 기존 테스트 정비 후 전체 통과** — `python3 -m pytest` → PASS (기존 `_call_gemini` 목킹 테스트는 `call_interaction` 목킹으로 이전)

- [ ] **Step 7: 실제 논문 1건 E2E 스모크** — 백엔드 기동 후 실제 PDF 업로드→분석 완료까지:

```bash
cd sasoo/backend && python3 -m uvicorn main:app --port 8765 &
# 별도로: 샘플 PDF 업로드 → POST /api/papers/{id}/analyze → GET 분석 상태 폴링
# 확인: 4개 스테이지 결과 저장, analysis_results.interaction_id 채워짐, 비용 기록
```
Expected: status=completed, `SELECT phase, interaction_id FROM analysis_results` 에서 visual/recipe/deep_dive에 interaction_id 존재.

- [ ] **Step 8: 커밋** — `git commit -m "feat(pipeline): stateful interactions chain with PDF direct input"`

---

### Task 7: 섹션 재작성 엔드포인트 (수준 변경 = 체인 연장)

**Files:**
- Modify: `sasoo/backend/api/analysis_routes.py` (라우터 끝에 엔드포인트 추가)
- Test: `sasoo/backend/api/test_analysis_routes.py`

**Interfaces:**
- Consumes: Task 6의 `analysis_results.interaction_id`, `EXPLANATION_LEVELS`.
- Produces: `POST /api/papers/{paper_id}/rewrite` body `{"phase": "deep_dive", "level": "high"}` → `{"text": str, "level": str, "cached": bool}`. 재작성 결과는 `analysis_results`에 `phase=f"{phase}#level={level}"`로 저장(캐시). Task 13이 호출.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
async def test_rewrite_section_extends_chain(client, analyzed_paper_id, monkeypatch):
    captured = {}
    async def fake_call(prompt, **kwargs):
        captured.update(kwargs)
        return {"text": "쉬운 설명", "model": "gemini-3.5-flash",
                "tokens_in": 10, "tokens_out": 10, "interaction_id": "int_rw"}
    monkeypatch.setattr("api.analysis_routes.call_interaction", fake_call)
    resp = await client.post(f"/api/papers/{analyzed_paper_id}/rewrite",
                             json={"phase": "deep_dive", "level": "high"})
    assert resp.status_code == 200
    assert resp.json()["text"] == "쉬운 설명"
    assert captured["previous_interaction_id"]  # 체인 연장
    # 두 번째 호출은 캐시 히트
    resp2 = await client.post(f"/api/papers/{analyzed_paper_id}/rewrite",
                              json={"phase": "deep_dive", "level": "high"})
    assert resp2.json()["cached"] is True


async def test_rewrite_invalid_level_rejected(client, analyzed_paper_id):
    resp = await client.post(f"/api/papers/{analyzed_paper_id}/rewrite",
                             json={"phase": "deep_dive", "level": "toddler"})
    assert resp.status_code == 422
```

- [ ] **Step 2: 실패 확인** — 404 FAIL

- [ ] **Step 3: 구현**

```python
from pydantic import BaseModel, field_validator
from api.analysis_context import EXPLANATION_LEVELS

_REWRITABLE_PHASES = {"screening", "visual", "recipe", "deep_dive"}


class RewriteRequest(BaseModel):
    phase: str
    level: str

    @field_validator("phase")
    @classmethod
    def _phase_ok(cls, v):
        if v not in _REWRITABLE_PHASES:
            raise ValueError(f"phase must be one of {_REWRITABLE_PHASES}")
        return v

    @field_validator("level")
    @classmethod
    def _level_ok(cls, v):
        if v not in EXPLANATION_LEVELS:
            raise ValueError(f"level must be one of {set(EXPLANATION_LEVELS)}")
        return v


@router.post("/{paper_id}/rewrite")
async def rewrite_section(paper_id: int, req: RewriteRequest):
    cache_phase = f"{req.phase}#level={req.level}"
    cached = await fetch_one(
        "SELECT result FROM analysis_results WHERE paper_id = ? AND phase = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (paper_id, cache_phase),
    )
    if cached:
        return {"text": cached["result"], "level": req.level, "cached": True}

    original = await fetch_one(
        "SELECT result, interaction_id FROM analysis_results "
        "WHERE paper_id = ? AND phase = ? ORDER BY created_at DESC LIMIT 1",
        (paper_id, req.phase),
    )
    if original is None:
        raise HTTPException(404, f"phase {req.phase} not analyzed yet")

    level_instruction = EXPLANATION_LEVELS[req.level]
    chain_id = None
    row = await fetch_one(
        "SELECT interaction_id FROM analysis_results WHERE paper_id = ? "
        "AND interaction_id IS NOT NULL ORDER BY created_at DESC LIMIT 1",
        (paper_id,),
    )
    if row:
        chain_id = row["interaction_id"]

    prompt = (
        f"방금 분석한 논문의 {req.phase} 결과를 아래 수준으로 다시 설명해줘. "
        f"{level_instruction} 마크다운 본문으로만 답해."
    )
    try:
        if chain_id is None:
            raise RuntimeError("no chain id")
        result = await call_interaction(
            prompt, model="gemini-3.5-flash",
            thinking_level="low", previous_interaction_id=chain_id,
        )
    except Exception:
        # 체인 만료(55일)·유실 폴백: 원문 포함 stateless 재작성
        result = await call_interaction(
            f"다음 논문 분석 결과를 읽고 아래 수준으로 다시 설명해줘. {level_instruction}\n\n"
            f"분석 결과:\n{original['result']}",
            model="gemini-3.5-flash", thinking_level="low", store=False,
        )

    cost = calc_cost(result["model"], result["tokens_in"], result["tokens_out"])
    await _insert_analysis_result(
        paper_id, cache_phase, result["text"], result["model"],
        result["tokens_in"], result["tokens_out"], cost,
        prompt, interaction_id=result.get("interaction_id"),
    )
    return {"text": result["text"], "level": req.level, "cached": False}
```

- [ ] **Step 4: 통과 확인** — `python3 -m pytest api/test_analysis_routes.py -v` → PASS

- [ ] **Step 5: 커밋** — `git commit -m "feat(api): section rewrite by explanation level via chain extension"`

---

### Task 8: 에이전트 API 축소 + 레거시 제거

**Files:**
- Modify: `sasoo/backend/api/agents.py` (POST /generate L70, POST "" L121, PUT L163, DELETE L194, POST duplicate L216, PATCH toggle L259, GET export L277, POST import L294 제거 — GET "" L102, GET /{name} L109만 유지)
- Delete: `sasoo/backend/agent_profiles/` 디렉토리 전체
- Modify: `sasoo/backend/services/agents/__init__.py` (`save_agent_file`/`delete_agent_file`/`serialize_agent_md` export 제거 — md_loader에서 함수 자체는 삭제하지 않고 export만 축소)
- Test: 기존 백엔드 테스트 전체

**Interfaces:**
- Consumes: 없음
- Produces: `GET /api/agents`, `GET /api/agents/{name}`만 존재. 프론트 Task 9와 순서 무관(프론트가 먼저 CRUD 호출을 제거해도 무방).

- [ ] **Step 1: 실패하는 테스트 작성** — agents 라우트 테스트 파일에 추가(없으면 `api/test_agents.py` 신규):

```python
async def test_agent_crud_endpoints_removed(client):
    assert (await client.post("/api/agents", json={})).status_code in (404, 405)
    assert (await client.put("/api/agents/photon", json={})).status_code in (404, 405)
    assert (await client.delete("/api/agents/photon")).status_code in (404, 405)
    assert (await client.post("/api/agents/generate", json={})).status_code in (404, 405)


async def test_agent_read_endpoints_kept(client):
    resp = await client.get("/api/agents")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1
```

- [ ] **Step 2: 실패 확인** → FAIL (CRUD가 아직 200/422 반환)

- [ ] **Step 3: 구현** — agents.py에서 위 8개 핸들러 함수와 전용 request 모델, 안 쓰게 된 import 삭제. `agent_profiles/` 디렉토리 삭제 전 `grep -rn "agent_profiles" sasoo/backend`로 참조 0건 확인 후 `git rm -r`. `__init__.py` export 축소.

- [ ] **Step 4: 전체 백엔드 테스트 통과** — `python3 -m pytest` → PASS

- [ ] **Step 5: 커밋** — `git commit -m "refactor(agents): read-only agent API, drop yaml profiles and CRUD"`

---

### Task 9: 프론트 — Agents 페이지 제거

**Files:**
- Modify: `sasoo/frontend/src/App.tsx` (L23 lazy import, L32 NAV_ITEMS 항목, L143 Route 제거)
- Delete: `sasoo/frontend/src/pages/Agents.tsx`
- Modify: `sasoo/frontend/src/lib/api.ts` (L727-811에서 `generateAgent/createAgent/updateAgent/deleteAgent/duplicateAgent/exportAgent/importAgent/toggleAgent`와 `AgentGenerateRequest` 제거 — **`getAgents`/`getAgent`/`AgentDetail`은 유지**, `lib/agents.ts`의 `fetchAllAgents`가 사용)
- Modify: `sasoo/frontend/src/lib/strings.ts` (L12 nav 라벨 `agents` 제거, L282 부근 Agents 페이지 전용 블록 제거 — 단 Upload/Workbench가 참조하는 키는 유지)

**Interfaces:**
- Consumes: Task 8 (백엔드 CRUD 제거와 정합)
- Produces: `/agents` 라우트 부재. `lib/agents.ts`·`AgentAvatar.tsx`는 그대로.

- [ ] **Step 1: 제거 전 참조 확인**

```bash
cd sasoo/frontend && grep -rn "pages/Agents\|createAgent\|updateAgent\|deleteAgent\|generateAgent\|duplicateAgent\|exportAgent\|importAgent\|toggleAgent" src --include="*.tsx" --include="*.ts" | grep -v "src/pages/Agents.tsx"
```
Expected: `src/lib/api.ts` 정의부 외 0건. 다른 사용처가 나오면 해당 파일 먼저 정리.

- [ ] **Step 2: 제거 수행** — App.tsx 3개 지점, Agents.tsx 삭제(`git rm`), api.ts CRUD 함수 삭제, strings.ts 정리. `strings.ts`의 각 키 삭제 전 `grep -rn "S.agents\.\|S\.app\.agents" src`로 사용처 0건 확인.

- [ ] **Step 3: 빌드 검증**

Run: `cd sasoo/frontend && npm run build`
Expected: 타입 에러 0건, 빌드 성공

- [ ] **Step 4: 커밋** — `git commit -m "feat(ui): remove agent authoring page and nav"`

---

### Task 10: 프론트 — 설정 페이지 (연구 분야 + 기본 설명 수준)

**Files:**
- Modify: `sasoo/frontend/src/lib/api.ts` (`Settings` interface L258-272)
- Modify: `sasoo/frontend/src/pages/Settings.tsx` (defaultSettings L48-62, form state L72-78, applySettingsToForm L97-105, handleSave L164-170, handleDiscard L230-238, hasChanges L243-250, 새 SettingPanel 블록)
- Modify: `sasoo/frontend/src/lib/strings.ts` (라벨 추가)

**Interfaces:**
- Consumes: Task 2 백엔드 필드, Task 11 `LevelSlider`(이 태스크에서는 임시로 `<select>` 사용 후 Task 11 완료 시 교체해도 되고, Task 11을 먼저 실행해도 됨 — **권장 순서: Task 11 → Task 10**).
- Produces: 설정 화면에서 두 값 저장/복원.

- [ ] **Step 1: 타입/상태 확장** — `Settings` interface에 `research_context: string; default_explanation_level: string;` 추가. Settings.tsx에 `gemini_api_key` 필드와 동일한 흐름(useState → applySettingsToForm → handleSave payload → hasChanges 비교)으로 두 필드 배선.

- [ ] **Step 2: UI 블록 추가** — 기존 `SettingPanel` 스타일(L453-538 참고)로 "연구자 프로필" 패널 추가:

```tsx
<SettingPanel title={S.settings.researcherProfile} description={S.settings.researcherProfileDesc}>
  <label className="settings-label" htmlFor="research-context">{S.settings.researchContext}</label>
  <input
    id="research-context"
    type="text"
    value={researchContext}
    onChange={(e) => setResearchContext(e.target.value)}
    placeholder={S.settings.researchContextPlaceholder}
  />
  <p className="settings-helper">{S.settings.researchContextHelper}</p>

  <label className="settings-label">{S.settings.defaultLevel}</label>
  <LevelSlider value={defaultLevel} onChange={setDefaultLevel} />
</SettingPanel>
```

strings.ts 추가 문자열:

```ts
  researcherProfile: '연구자 프로필',
  researcherProfileDesc: '분석 결과의 눈높이와 관점을 조정합니다.',
  researchContext: '연구 분야 소개',
  researchContextPlaceholder: '예: 페로브스카이트 태양전지 소자 물리를 연구합니다',
  researchContextHelper: '한 줄이면 충분합니다. 분석 결과가 내 분야 관점으로 연결됩니다.',
  defaultLevel: '기본 설명 수준',
```

- [ ] **Step 3: 검증** — `npm run build` 통과 + 앱 실행해 설정 저장→새로고침→값 유지 확인(스크린샷).

- [ ] **Step 4: 커밋** — `git commit -m "feat(settings-ui): researcher profile fields"`

---

### Task 11: 프론트 — LevelSlider 컴포넌트 (6단계 + 예시 프리뷰)

**Files:**
- Create: `sasoo/frontend/src/components/LevelSlider.tsx`
- Modify: `sasoo/frontend/src/lib/strings.ts`

**Interfaces:**
- Consumes: 없음
- Produces: `<LevelSlider value: string, onChange: (key: string) => void, compact?: boolean>` — value는 `elementary|middle|high|undergrad|masters|phd`. Task 10·12·13이 사용. `LEVEL_ORDER`, `LEVEL_LABELS` named export.

- [ ] **Step 1: 구현**

```tsx
// sasoo/frontend/src/components/LevelSlider.tsx
import { useId } from 'react';

export const LEVEL_ORDER = ['elementary', 'middle', 'high', 'undergrad', 'masters', 'phd'] as const;
export type LevelKey = (typeof LEVEL_ORDER)[number];

export const LEVEL_LABELS: Record<LevelKey, string> = {
  elementary: '초등학생', middle: '중학생', high: '고등학생',
  undergrad: '학부생', masters: '석사생', phd: '박사생',
};

// 같은 개념(빛의 간섭)을 수준별 문체로 — 슬라이더의 의미를 즉시 체감시키는 프리뷰
const LEVEL_PREVIEWS: Record<LevelKey, string> = {
  elementary: '빛 두 줄기가 만나면 물결처럼 겹쳐서 더 밝아지거나 어두워져요.',
  middle: '두 빛의 파동이 겹치면 마루끼리 만나 밝아지고, 마루와 골이 만나 어두워집니다.',
  high: '두 파동의 위상차가 0이면 보강간섭, π이면 상쇄간섭이 일어나 간섭무늬가 생깁니다.',
  undergrad: '두 간섭 광의 세기는 I = I₁ + I₂ + 2√(I₁I₂)cosΔφ로 위상차에 의해 결정됩니다.',
  masters: '가시도(visibility)는 광원의 시간·공간 결맞음에 의해 제한되며 상호결맞음 함수로 기술됩니다.',
  phd: '부분결맞음 조건에서 간섭항은 상호결맞음 함수 γ₁₂(τ)의 크기와 인수로 완전히 결정되며, van Cittert–Zernike 정리로 광원 분포와 연결됩니다.',
};

interface Props {
  value: string;
  onChange: (key: LevelKey) => void;
  compact?: boolean; // true면 프리뷰 문장 숨김 (결과 화면용)
}

export default function LevelSlider({ value, onChange, compact = false }: Props) {
  const id = useId();
  const index = Math.max(0, LEVEL_ORDER.indexOf(value as LevelKey));
  const current = LEVEL_ORDER[index];
  return (
    <div className="level-slider">
      <input
        id={id}
        type="range"
        min={0}
        max={LEVEL_ORDER.length - 1}
        step={1}
        value={index}
        onChange={(e) => onChange(LEVEL_ORDER[Number(e.target.value)])}
        aria-label="설명 수준"
        aria-valuetext={LEVEL_LABELS[current]}
        list={`${id}-ticks`}
      />
      <div className="level-slider-labels">
        {LEVEL_ORDER.map((key) => (
          <button
            key={key}
            type="button"
            className={key === current ? 'level-label active' : 'level-label'}
            onClick={() => onChange(key)}
          >
            {LEVEL_LABELS[key]}
          </button>
        ))}
      </div>
      {!compact && (
        <p className="level-preview" aria-live="polite">{LEVEL_PREVIEWS[current]}</p>
      )}
    </div>
  );
}
```

스타일은 프로젝트의 기존 시맨틱 토큰 방식(eb27f6f 커밋의 semantic tokens 패턴)을 따라 전역 CSS에 추가: 라벨 버튼 최소 터치 높이 44px, `.active`는 `font-weight: 600` + accent 색, 프리뷰는 `min-height`를 고정해 문장이 바뀌어도 레이아웃 시프트가 없게 한다.

- [ ] **Step 2: 검증** — `npm run build` 통과. 앱 실행해 6단계 이동 시 라벨 강조·프리뷰 문장 전환 확인(스크린샷).

- [ ] **Step 3: 커밋** — `git commit -m "feat(ui): 6-step explanation level slider with live preview"`

---

### Task 12: 프론트 — 업로드 흐름에 초점/수준 입력

**Files:**
- Modify: `sasoo/frontend/src/pages/Upload.tsx` (classified 단계 UI L447-515, handleStartAnalysis L241-251)
- Modify: `sasoo/frontend/src/lib/api.ts` (`PaperUpdateData` L54-59에 `explanation_level?: string; analysis_focus?: { chips: string[]; note: string };` 추가)
- Modify: `sasoo/frontend/src/lib/strings.ts`

**Interfaces:**
- Consumes: Task 3 (PATCH 수용), Task 11 `LevelSlider`.
- Produces: 업로드 완료(classified) 화면에서 초점 칩+자유 입력+수준을 설정하면 `handleStartAnalysis`가 `updatePaper()` PATCH에 포함.

- [ ] **Step 1: 상태와 UI 추가** — Upload.tsx classified 블록(도메인 select 아래)에 접힌 "분석 옵션" 섹션(progressive disclosure, 기존 프로젝트의 collapse 패턴 사용):

```tsx
const FOCUS_CHIPS = [
  { key: 'reproduction', label: '재현 방법' },
  { key: 'contribution', label: '핵심 기여' },
  { key: 'limitations', label: '한계·후속 연구' },
  { key: 'theory', label: '수식·이론' },
  { key: 'related_work', label: '선행연구 대비' },
] as const;

const [focusChips, setFocusChips] = useState<string[]>([]);
const [focusNote, setFocusNote] = useState('');
const [levelOverride, setLevelOverride] = useState<string | null>(null); // null = 설정 기본값 사용
```

칩은 `<button type="button" aria-pressed={selected}>` 토글(44px 높이, 선택 시 accent 배경+체크 아이콘 — 색상만으로 구분 금지). 자유 입력은 상시 라벨 "이 논문에서 특별히 궁금한 점" + 헬퍼 "비워두면 균형 있게 분석합니다". 수준은 `<LevelSlider value={levelOverride ?? settingsDefaultLevel} onChange={setLevelOverride} />` — `settingsDefaultLevel`은 `getSettings()`로 로드.

- [ ] **Step 2: 시작 시 PATCH 반영** — `handleStartAnalysis`에서:

```tsx
const updates: PaperUpdateData = {};
if (domainOverride !== uploadResult.domain) updates.domain = domainOverride;
if (levelOverride) updates.explanation_level = levelOverride;
if (focusChips.length > 0 || focusNote.trim()) {
  updates.analysis_focus = { chips: focusChips, note: focusNote.trim() };
}
if (Object.keys(updates).length > 0) await updatePaper(uploadResult.id, updates);
navigate(`/workbench/${uploadResult.id}`);
```

- [ ] **Step 3: 검증** — `npm run build` + 앱 실행: 업로드→옵션 입력→분석 시작→백엔드 로그에서 system_instruction에 초점/수준 반영 확인(스크린샷).

- [ ] **Step 4: 커밋** — `git commit -m "feat(upload): analysis focus chips and level override"`

---

### Task 13: 프론트 — 페르소나 배지 + 결과 화면 수준 재작성

**Files:**
- Modify: `sasoo/frontend/src/components/workbench/WorkbenchHeader.tsx` (페르소나 배지에 변경 드롭다운)
- Modify: `sasoo/frontend/src/components/AnalysisPanel.tsx` (deep_dive `PhaseSection` 상단에 compact LevelSlider)
- Modify: `sasoo/frontend/src/lib/api.ts` (rewrite API 함수 추가)
- Modify: `sasoo/frontend/src/pages/Workbench.tsx` (배지 드롭다운 → `updatePaper` 배선)

**Interfaces:**
- Consumes: Task 7 rewrite 엔드포인트, Task 11 `LevelSlider`, 기존 `lib/agents.ts`의 `getAllAgents`/`getAgentMeta`, `updatePaper`.
- Produces: 결과 화면에서 수준 변경 시 해당 섹션 텍스트가 재작성본으로 교체(수준별 캐시), 페르소나 배지에서 담당 에이전트 변경 가능.

- [ ] **Step 1: rewrite API 클라이언트 추가** — api.ts:

```ts
export interface RewriteResponse { text: string; level: string; cached: boolean }

export function rewriteSection(paperId: number, phase: string, level: string): Promise<RewriteResponse> {
  return request<RewriteResponse>(`/papers/${paperId}/rewrite`, {
    method: 'POST',
    body: JSON.stringify({ phase, level }),
  });
}
```

- [ ] **Step 2: AnalysisPanel 수준 슬라이더** — deep_dive `PhaseSection`(L990 부근) 헤더에 `<LevelSlider compact>` 배치. 상태:

```tsx
const [viewLevel, setViewLevel] = useState<string>(paperLevel ?? 'masters');
const [rewrites, setRewrites] = useState<Record<string, string>>({}); // level → text
const [rewriting, setRewriting] = useState(false);

async function handleLevelChange(level: string) {
  setViewLevel(level);
  if (level === (paperLevel ?? 'masters') || rewrites[level]) return; // 원본/캐시
  setRewriting(true);
  try {
    const r = await rewriteSection(paperId, 'deep_dive', level);
    setRewrites((prev) => ({ ...prev, [level]: r.text }));
  } finally {
    setRewriting(false);
  }
}
```

렌더링: `viewLevel`이 원본 수준이면 기존 결과, 아니면 `rewrites[viewLevel]`(로딩 중엔 스켈레톤 + 슬라이더 disabled). 실패 시 기존 에러 토스트 패턴으로 "재작성에 실패했습니다. 다시 시도해주세요." + 원본 유지.

- [ ] **Step 3: 페르소나 배지 드롭다운** — WorkbenchHeader의 `agentLabel` 표시부를 클릭 가능한 드롭다운으로: `getAllAgents()` 목록(아바타+한국어 이름), 선택 시 `updatePaper(paperId, { domain: agent.domain })` 호출 후 헤더 갱신. 접근성: `aria-haspopup="listbox"`, 키보드 조작 가능해야 함(기존 프로젝트 드롭다운 컴포넌트 재사용 우선).

- [ ] **Step 4: 검증** — `npm run build` + 앱 실행: 분석 완료 논문에서 수준 변경→재작성 텍스트 표시→같은 수준 재선택 시 즉시 표시(캐시)를 확인(스크린샷). 배지 드롭다운으로 페르소나 변경 확인.

- [ ] **Step 5: 커밋** — `git commit -m "feat(workbench): persona badge dropdown and level-based section rewrite"`

---

### Task 14: 최종 회귀 + E2E 검증

**Files:**
- Test: 전체

- [ ] **Step 1: 백엔드 전체 테스트** — `cd sasoo/backend && python3 -m pytest -v` → 전부 PASS

- [ ] **Step 2: 잔재 검증**

```bash
grep -rn "generate_content\|_call_gemini\|_call_anthropic\|anthropic\|claude-" sasoo/backend --include="*.py" | grep -v test_
```
Expected: 0건 (viz `figure_gen.py`의 OpenAI 이미지 경로는 범위 밖 — `openai` 문자열은 허용).

- [ ] **Step 3: 프론트 빌드+실행 E2E** — `npm run build` 후 앱 기동: 논문 업로드→초점/수준 입력→분석 완료→페르소나 배지 표시→수준 변경 재작성까지 전체 흐름 1회. 각 화면 스크린샷 확보.

- [ ] **Step 4: 스펙 대조** — 스펙 문서의 각 섹션(백엔드 1-5, 프론트 1-6, 에러 처리, 테스트)을 열고 구현 여부 체크. 미구현 항목 발견 시 해당 태스크로 복귀.

- [ ] **Step 5: 최종 커밋 및 브랜치 정리** — 잔여 변경 커밋 후 `superpowers:finishing-a-development-branch` 스킬로 마무리.

---

## Self-Review 결과

- **스펙 커버리지**: 백엔드 1(클라이언트 통합)=Task 4, 2(PDF 직접 입력)=Task 6, 3(파이프라인 체인)=Task 5·6, 4(에이전트 강등)=Task 8, 5(잔재 정리)=Task 1·6 / 프론트 1(페이지 제거)=Task 9, 2(설정)=Task 2·10, 3(페르소나)=Task 13, 4(초점)=Task 12, 5(슬라이더)=Task 11, 6(체인 연장 재작성)=Task 7·13 / 에러 처리=Task 4(재시도)·6(폴백)·7(stateless 폴백) / 테스트=각 태스크 + Task 14. 갭 없음.
- **타입 일관성**: `call_interaction` 반환 dict 키(text/model/tokens_in/tokens_out/interaction_id)를 Task 5·6·7이 동일 사용. `LevelKey` 6종과 백엔드 `EXPLANATION_LEVELS` 키 일치. `analysis_focus` JSON 형태(`{chips, note}`)를 Task 3·6·12가 동일 사용.
- **주의**: Task 6은 이 플랜에서 가장 큰 태스크다. 서브에이전트 실행 시 Task 6만은 스펙 문서와 `analysis_routes.py` 전체를 읽게 하고, 실행 후 리뷰를 반드시 거친다.
