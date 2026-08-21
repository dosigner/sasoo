# PDF 페이지 비전 파싱 provider 중립화 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `pdf_visual_engine`의 "AI 판독" 경로가 OpenAI 키 단독 사용자에게도 동작하게 한다. 엔진 축은 "LLM 비전으로 읽을까 / 로컬 Java 파서로 뽑을까"만 정하고, 어떤 LLM이냐는 `ai_provider`가 정한다.

**Architecture:** 설정 값 도메인(`{gemini, odl}`)과 저장 포맷, 프론트엔드를 전혀 바꾸지 않는다. `gemini`는 이미 "LLM 비전 경로"를 가리키는 레거시 이름으로 문서화되어 있고(`services/provider_state.py:15-18`, `sasoo/frontend/src/lib/strings.ts:355-357`), UI 문구도 이미 공급사 중립("그림 판독 방식" / "AI 판독 (정확, 유료)")이다. 따라서 마이그레이션이 없다. 바뀌는 것은 두 가지다. ① 페이지 파서가 쓰는 모델과 effort를 `MODEL_VISUAL` 하드코딩 대신 `model_registry`의 신규 role `pdf_parse`에서 가져온다. ② 비전 엔진의 가용성 판정과 디스패치가 `GEMINI_API_KEY` 직접 조회 대신 활성 provider의 키(`key_env_for`)를 본다.

**Tech Stack:** FastAPI, PyMuPDF(fitz), google-genai(Interactions API), openai SDK(Responses API), pytest(unittest 스타일)

**Spec:** `docs/superpowers/specs/2026-07-31-ai-provider-selection-design.md`

이 플랜은 그 스펙의 **R2를 의도적으로 뒤집는다**. R2는 "PDF 전체 비전 파싱은 범위 밖, OpenAI 키 단독 사용자는 로컬 ODL 경로를 쓴다"고 정했다. 뒤집는 근거는 2026-08-21 실측이다(아래 실측 기록). R2는 기술적 불가가 아니라 범위 봉쇄를 이유로 제외한 항목이었고, 실측 결과 OpenAI Luna가 `box_2d` 규약을 그대로 지켰다.

## 실측 기록 (2026-08-21, `tools/openai_vision_spike.py`)

대상: `2022_SciRep_CoherentFsoLeo_optics` 7페이지(p2~p8), DPI 150, 정답셋 12편 중 1편.

| 항목 | 측정값 |
|---|---|
| `box_2d` 규약 위반 | 양쪽 모두 0건 (범위·좌표순서·면적 전부 유효) |
| 그림 박스 IoU (Gemini 기준) | 0.811 ~ 1.0, 6페이지 중 5페이지가 0.977 이상 |
| 표 박스 IoU (Gemini 기준) | 0.982, 0.980, 0.990 |
| markdown 분량비 | 0.889 ~ 1.044 |
| 입력 토큰비 | 전 페이지 2.01배 (`media_resolution`이 OpenAI에서 no-op) |
| 지연 | Gemini 7.3~18.8초, OpenAI 8.4~11.4초 |

**비용 단서:** 스파이크는 양쪽 모두 role `visual`(Gemini effort `low`)로 돌렸다. 프로덕션 페이지 파서는 `minimal`이므로 측정된 Gemini 비용($0.0772/7p)은 프로덕션보다 비싸다. 따라서 "OpenAI가 5.4배 저렴"이라는 스파이크 수치를 그대로 인용하지 말 것. 확정 수치는 Task 5의 감사 lane에서 나온다.

**미해결 관찰:** OpenAI가 요소를 더 많이 방출한다(p4 4대5, p5 2대3, p6 4대6). 과분할인지 Gemini 누락 포착인지는 Task 5에서 갈린다.

## Global Constraints

- **Gemini 경로는 바이트 단위로 동일해야 한다.** 페이지 파서의 Gemini effort는 현행 `minimal`을 유지한다. `model_registry`의 기존 role `visual`은 effort가 `low`이므로 **재사용하면 안 된다** — 신규 role `pdf_parse`를 만든다.
- `SASOO_GEMINI_PARSER_*` env 레버(DPI, THINKING, MEDIA_RESOLUTION, ELEMENTS, PAGE_CONCURRENCY)는 전부 그대로 동작해야 한다. 베이스라인 재현 절차(`services/gemini_parser.py:58-60`)가 이 레버에 의존한다.
- 설정 값 도메인 `pdf_visual_engine ∈ {gemini, odl}`을 바꾸지 않는다. `api/settings.py:376-377`의 검증, `models/schemas.py:339,371`, `sasoo/frontend/src/lib/api.ts:286`을 건드리지 않는다.
- 매니페스트에 저장되는 엔진 문자열(`actual_engine`, `manifest["text_engine"]`, `visual_parse_usage["engine"]`)의 값 공간을 바꾸지 않는다. `"gemini"`는 "LLM 비전으로 파싱됨"을 뜻한다. 값을 바꾸면 기존 매니페스트의 승격·멱등 판정(`services/odl_parser.py:618,1290,1453,1540`, `services/document_manifest.py:781`)이 전부 깨진다.
- `media_resolution`은 OpenAI에서 no-op이다(`services/llm/openai_client.py:114`). 입력 토큰이 2배가 되는 것을 알고 넘기며, 이 플랜에서 DPI를 조정하지 않는다.
- 재시도 루프의 예외 포획은 `except Exception`으로 한다. `BaseException`은 `asyncio.CancelledError`까지 잡는다(스펙 R5-3).
- 각 태스크 완료 시 `cd sasoo/backend && .venv/bin/python -m pytest -q` 전체 통과. 착수 시점 기준선은 **630 passed, 3 skipped, 117 subtests**.
- 커밋 메시지는 한국어, 본문에 왜를 적는다. 작업 브랜치: `feat/provider-neutral-llm`.

## File Structure

```
backend/services/model_registry.py    수정 — role "pdf_parse" 추가 (양 provider), ROLES 갱신
backend/services/gemini_parser.py     수정 — provider 인자, 모델·effort를 레지스트리에서
backend/services/odl_parser.py        수정 — 비전 엔진 가용성·디스패치를 provider-aware로
backend/services/provider_state.py    수정 — docstring을 새 설계로 갱신 (코드 무변경)
backend/services/test_model_registry.py   수정 — pdf_parse role 테스트
backend/services/test_gemini_parser.py    수정 — provider별 모델·effort 테스트
backend/services/test_odl_parser.py       수정 — provider별 엔진 계획·폴백 테스트
backend/tools/openai_vision_spike.py  신규 — 위 실측 기록을 만든 스파이크. 아직 미커밋(Task 0)
```

---

## Task 0: 스파이크와 플랜을 커밋

위 실측 기록을 만든 도구가 아직 커밋되지 않았다. Task 5의 감사 결과를 나중에 재현하려면 이 도구가 이력에 있어야 한다.

**Files:**
- Commit: `sasoo/backend/tools/openai_vision_spike.py`, `docs/superpowers/plans/2026-08-21-pdf-visual-engine-provider-neutral.md`

- [ ] **Step 1: 자체 검증이 도는지 확인한다**

Run: `cd sasoo/backend && .venv/bin/python -m tools.openai_vision_spike --selftest`
Expected: `selftest ok`

- [ ] **Step 2: 전체 테스트가 여전히 초록인지 확인한다**

스파이크는 프로덕션 경로를 건드리지 않으므로 기준선이 그대로여야 한다.

Run: `cd sasoo/backend && .venv/bin/python -m pytest -q`
Expected: 630 passed, 3 skipped, 117 subtests

- [ ] **Step 3: 커밋**

```bash
git add sasoo/backend/tools/openai_vision_spike.py \
        docs/superpowers/plans/2026-08-21-pdf-visual-engine-provider-neutral.md
git commit -m "tools: OpenAI 페이지 비전 파싱 실측 스파이크 + 구현 플랜

스펙 R2가 'PDF 전체 비전 파싱은 범위 밖'으로 제외한 근거는 기술적 불가가
아니라 범위 봉쇄였다. 실제로 되는지 재기 위해 gemini_parser의 렌더·프롬프트·
스키마를 그대로 재사용해 같은 페이지를 양쪽 공급사로 파싱하고 box_2d IoU와
비용을 비교하는 도구를 만들었다. 정답셋 12편 중 1편 7페이지 실측 결과
OpenAI Luna가 box_2d 규약을 위반 0건으로 지켰다(플랜에 수치 기록)."
```

---

## Task 1: 레지스트리에 `pdf_parse` role 추가

페이지 파서 전용 role을 만든다. 기존 `visual`(그림 판독 단계)과 섞으면 Gemini effort가 `minimal`에서 `low`로 올라가 Global Constraints를 깬다.

**Files:**
- Modify: `sasoo/backend/services/model_registry.py:42-83` (`_REGISTRY` 양 provider), `ROLES` 상수
- Test: `sasoo/backend/services/test_model_registry.py`

**Interfaces:**
- Consumes: `services.models.MODEL_VISUAL`, `services.models.MODEL_LUNA` (기존)
- Produces: `resolve("pdf_parse", "gemini") -> ModelChoice(MODEL_VISUAL, "minimal")`, `resolve("pdf_parse", "openai") -> ModelChoice(MODEL_LUNA, "low")`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`services/test_model_registry.py`에 추가한다.

```python
class TestPdfParseRole(unittest.TestCase):
    def test_gemini_pdf_parse_matches_current_parser_defaults(self):
        """Gemini 경로는 현행 페이지 파서와 바이트 동일해야 한다 — 모델은 MODEL_VISUAL,
        effort는 minimal. 기존 role "visual"(low)을 재사용하면 이 테스트가 막는다."""
        choice = resolve("pdf_parse", "gemini")
        self.assertEqual(choice.model, MODEL_VISUAL)
        self.assertEqual(choice.effort, "minimal")

    def test_openai_pdf_parse_uses_luna_low(self):
        """OpenAI는 minimal을 BadRequestError로 거부한다(플랜 Task 0 실측). low가 최저치."""
        choice = resolve("pdf_parse", "openai")
        self.assertEqual(choice.model, MODEL_LUNA)
        self.assertEqual(choice.effort, "low")

    def test_pdf_parse_is_declared_in_roles(self):
        self.assertIn("pdf_parse", ROLES)
```

파일 상단 import에 `MODEL_VISUAL`, `ROLES`가 없으면 추가한다.

- [ ] **Step 2: 실패를 확인한다**

Run: `cd sasoo/backend && .venv/bin/python -m pytest services/test_model_registry.py -q`
Expected: FAIL — `KeyError: unknown role: 'pdf_parse'`

- [ ] **Step 3: 레지스트리에 role을 추가한다**

`_REGISTRY["gemini"]`에 추가한다(`visual` 바로 아래에 두어 둘이 다른 role임을 눈에 보이게 한다).

```python
        # 페이지 전체 비전 파싱(gemini_parser). 그림 판독 단계인 "visual"과 별개 role이다 —
        # 페이지 파서는 thinking을 최소로 쓰는 축자 전사 작업이라 effort가 minimal이다.
        "pdf_parse": ModelChoice(MODEL_VISUAL, "minimal"),
```

`_REGISTRY["openai"]`에 추가한다.

```python
        # OpenAI는 minimal 미지원(플랜 Task 0 실측) — 최저치가 low다.
        # box_2d 규약 준수는 2026-08-21 실측으로 확인(tools/openai_vision_spike.py).
        "pdf_parse": ModelChoice(MODEL_LUNA, "low"),
```

`ROLES`는 건드리지 않는다 — `services/model_registry.py:81`이 `tuple(_REGISTRY["gemini"])`로 파생시키므로 gemini 쪽에 키를 넣으면 자동으로 들어간다. `MODEL_VISUAL`이 `services/models.py`에서 import되어 있지 않으면 import에 추가한다.

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `cd sasoo/backend && .venv/bin/python -m pytest services/test_model_registry.py -q`
Expected: PASS

Run: `cd sasoo/backend && .venv/bin/python -m pytest -q`
Expected: 633 passed (기준선 630 + 신규 3), 3 skipped

- [ ] **Step 5: 커밋**

```bash
git add sasoo/backend/services/model_registry.py sasoo/backend/services/test_model_registry.py
git commit -m "feat(models): 페이지 파서 전용 role pdf_parse 추가

기존 role visual은 그림 판독 단계용이고 effort가 low다. 페이지 파서는
minimal을 쓰므로 visual을 재사용하면 Gemini 동작이 바뀐다(비용 상승).
별개 role로 분리해 Gemini는 현행과 바이트 동일하게, OpenAI는 minimal
미지원이므로 low로 매핑한다."
```

---

## Task 2: `gemini_parser`에 provider 배선

**Files:**
- Modify: `sasoo/backend/services/gemini_parser.py` (`_THINKING_LEVEL` 정의부 `:68`, `_call_page:295-322`, `_process_page:325-`, `run_convert_gemini:415-421` 진입부와 `:464,479`의 모델 인자)
- Test: `sasoo/backend/services/test_gemini_parser.py`
- Test: `sasoo/backend/services/test_visual_parse_usage.py:154,232,247` — `run_convert_gemini`를 대체하는 가짜 함수 3개가 `provider` 인자를 못 받아 `TypeError`로 깨진다

**Interfaces:**
- Consumes: `services.model_registry.resolve("pdf_parse", provider) -> ModelChoice` (Task 1)
- Produces: `run_convert_gemini(pdf_path, output_dir, figures_dir, *, usage_out=None, provider="gemini") -> tuple[dict, str, str]` — 3-tuple 계약과 반환하는 엔진 문자열 `GEMINI_ENGINE_NAME`은 불변.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`services/test_gemini_parser.py`에 추가한다. 기존 파일의 mock 패턴(`patch`, `AsyncMock`)을 따른다.

```python
class TestParserProviderRouting(unittest.TestCase):
    """페이지 호출이 provider에 따라 올바른 모델·effort로 나가는지."""

    def _run(self, provider: str) -> dict:
        """1페이지 PDF를 파싱하고 call_interaction에 실제로 넘어간 kwargs를 돌려준다."""
        page_json = json.dumps({
            "markdown": "# T",
            "elements": [{"type": "image", "box_2d": [10, 10, 200, 200], "text": ""}],
        })
        captured: dict = {}

        async def _fake_call(prompt, **kwargs):
            captured.update(kwargs)
            return {"text": page_json, "tokens_in": 1, "tokens_out": 1, "model": kwargs["model"]}

        with TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "one.pdf"
            doc = fitz.open()
            doc.new_page()
            doc.save(str(pdf))
            doc.close()
            with patch.object(gemini_parser, "call_interaction", new=AsyncMock(side_effect=_fake_call)):
                asyncio.run(run_convert_gemini(
                    pdf, Path(tmp), Path(tmp), provider=provider
                ))
        return captured

    def test_gemini_keeps_current_model_and_minimal_effort(self):
        """회귀 방어: Gemini는 현행과 동일해야 한다."""
        kwargs = self._run("gemini")
        self.assertEqual(kwargs["model"], MODEL_VISUAL)
        self.assertEqual(kwargs["thinking_level"], "minimal")

    def test_openai_uses_luna_and_low_effort(self):
        """minimal을 그대로 보내면 openai_client가 reasoning.effort=minimal로 전달해
        BadRequestError가 난다(openai_client.py:130-131). low여야 한다."""
        kwargs = self._run("openai")
        self.assertEqual(kwargs["model"], MODEL_LUNA)
        self.assertEqual(kwargs["thinking_level"], "low")

    def test_env_thinking_override_still_wins(self):
        """SASOO_GEMINI_PARSER_THINKING 레버는 베이스라인 재현 절차가 의존한다."""
        with patch.dict(os.environ, {"SASOO_GEMINI_PARSER_THINKING": "high"}):
            importlib.reload(gemini_parser)
            try:
                kwargs = self._run("openai")
                self.assertEqual(kwargs["thinking_level"], "high")
            finally:
                importlib.reload(gemini_parser)
```

파일 상단 import에 `asyncio`, `importlib`, `MODEL_VISUAL`, `MODEL_LUNA`를 추가한다.

- [ ] **Step 2: 실패를 확인한다**

Run: `cd sasoo/backend && .venv/bin/python -m pytest services/test_gemini_parser.py -q`
Expected: FAIL — `run_convert_gemini() got an unexpected keyword argument 'provider'`

- [ ] **Step 3: provider를 배선한다**

`:68`의 상수를 오버라이드 전용으로 바꾼다. 기본값을 비우는 것이 핵심이다. 그래야 레지스트리 값이 기본이 되고 env 레버는 명시 설정 시에만 이긴다.

```python
# thinking 토큰은 출력 단가로 과금됨. 빈 문자열이면 model_registry의 pdf_parse role 값을
# 쓴다(Gemini=minimal, OpenAI=low). 명시하면 provider 무관하게 이 값이 이긴다 —
# 베이스라인 재현 절차(위 주석)가 이 레버에 의존한다.
_THINKING_OVERRIDE = _env_str("SASOO_GEMINI_PARSER_THINKING", "")
```

`_THINKING_LEVEL`을 참조하는 곳을 전부 찾아 고친다(`grep -n _THINKING_LEVEL services/gemini_parser.py`).

`_call_page`에 effort를 인자로 받는다.

```python
async def _call_page(png_b64: str, model: str, effort: str | None) -> dict[str, Any]:
    """한 페이지에 대한 비전 호출. 파싱된 JSON dict + usage를 담아 반환."""
    result = await call_interaction(
        [
            {"type": "image", "data": png_b64, "mime_type": "image/png"},
            {"type": "text", "text": _PAGE_PROMPT},
        ],
        lane="pipeline",
        model=model,
        system_instruction=_PARSER_SYSTEM_INSTRUCTION,
        thinking_level=effort or None,
        store=False,
        response_schema=_PAGE_RESPONSE_SCHEMA,
        media_resolution=_MEDIA_RESOLUTION or None,
    )
```

`_process_page`의 시그니처에 `effort: str | None`을 추가하고 `_call_page(png_b64, model, effort)`로 넘긴다.

`run_convert_gemini` 진입부에서 한 번 확정해 내린다(스펙 R6의 "스테이지 진입 시 한 번 확정" 원칙).

```python
async def run_convert_gemini(
    pdf_path: Path,
    output_dir: Path,
    figures_dir: Path,
    *,
    usage_out: dict[str, Any] | None = None,
    provider: str = "gemini",
) -> tuple[dict[str, Any], str, str]:
```

본문 앞부분에서 결정한다.

```python
    from services.model_registry import resolve

    choice = resolve("pdf_parse", provider)
    model = choice.model
    effort = _THINKING_OVERRIDE or choice.effort
```

`:464`와 `:479`의 `_process_page(doc_pool, page_index, page_sem, MODEL_VISUAL)`을 `_process_page(doc_pool, page_index, page_sem, model, effort)`로 바꾼다. `MODEL_VISUAL` import는 다른 참조가 남지 않으면 제거한다.

- [ ] **Step 4: 깨지는 기존 가짜 함수를 고친다**

`services/test_visual_parse_usage.py`의 세 곳(`:154` `_fake_run_convert_gemini`, `:232` `_raise_raw`, `:247` `_partial_then_raise`)이 `run_convert_gemini`를 대체한다. Task 3이 `provider=`를 넘기기 시작하면 `TypeError`가 난다. 세 시그니처에 인자를 추가한다.

```python
        async def _fake_run_convert_gemini(
            pdf_path, output_dir, figures_dir, *, usage_out=None, provider="gemini"
        ):
```

나머지 두 개도 같은 방식으로 `provider="gemini"`를 더한다. 본문은 그대로 둔다 — 이 테스트들이 검증하는 것은 usage 채널과 예외 변환이지 provider가 아니다.

- [ ] **Step 5: 테스트 통과를 확인한다**

Run: `cd sasoo/backend && .venv/bin/python -m pytest services/test_gemini_parser.py services/test_visual_parse_usage.py -q`
Expected: PASS

Run: `cd sasoo/backend && .venv/bin/python -m pytest -q`
Expected: 636 passed, 3 skipped

- [ ] **Step 6: 커밋**

```bash
git add sasoo/backend/services/gemini_parser.py sasoo/backend/services/test_gemini_parser.py \
       sasoo/backend/services/test_visual_parse_usage.py
git commit -m "feat(parser): 페이지 비전 파서에 provider 배선

모델과 effort를 MODEL_VISUAL + _THINKING_LEVEL 하드코딩에서
model_registry.resolve(\"pdf_parse\", provider)로 옮겼다. OpenAI는 effort
minimal을 BadRequestError로 거부하므로(openai_client.py:130-131이 값을
reasoning.effort로 그대로 전달) 하드코딩을 남겨두면 OpenAI 경로가 첫
페이지에서 죽는다. SASOO_GEMINI_PARSER_THINKING 레버는 명시 설정 시
계속 이기도록 남겨 베이스라인 재현 절차를 보존했다."
```

---

## Task 3: `odl_parser`의 비전 엔진 가용성과 디스패치를 provider-aware로

**Files:**
- Modify: `sasoo/backend/services/odl_parser.py:864-895` (`_run_convert`), `:897-922` (`_plan_visual_engines`), `:889-895` (`_visual_runtime_unavailable_message`), `:953-976` (`_run_convert_gemini`), `:1409-1500` (`ensure_visual_artifacts`)
- Test: `sasoo/backend/services/test_odl_parser.py`

**Interfaces:**
- Consumes: `services.provider_state.key_env_for(provider) -> str` (기존), `services.model_registry.active_provider() -> str` (기존, async), `run_convert_gemini(..., provider=...)` (Task 2)
- Produces: `_plan_visual_engines(provider: str) -> list[str]`, `_run_convert(..., provider: str | None = None)`, `_visual_runtime_unavailable_message(provider: str) -> str`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

`services/test_odl_parser.py`에 추가한다.

```python
class TestVisualEngineProviderGate(unittest.TestCase):
    """비전 엔진 가용성이 활성 provider의 키를 보는지."""

    def test_openai_key_alone_keeps_vision_engine_in_plan(self):
        """회귀 방어: 이전에는 GEMINI_API_KEY만 봐서 OpenAI 단독 키가 vision 경로에
        전혀 못 들어갔다(로컬 ODL로만 떨어짐)."""
        env = {"OPENAI_API_KEY": "k", "SASOO_PDF_VISUAL_ENGINE": "gemini"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            with patch.object(odl_parser, "_java_runtime_available", return_value=True):
                plan = odl_parser._plan_visual_engines("openai")
        self.assertEqual(plan[0], odl_parser.GEMINI_ENGINE_NAME)

    def test_gemini_provider_without_gemini_key_drops_vision_engine(self):
        env = {"SASOO_PDF_VISUAL_ENGINE": "gemini"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("GEMINI_API_KEY", None)
            with patch.object(odl_parser, "_java_runtime_available", return_value=True):
                plan = odl_parser._plan_visual_engines("gemini")
        self.assertEqual(plan, ["odl"])

    def test_run_convert_downgrades_on_missing_active_provider_key(self):
        """provider 키가 없으면 조용히 ODL로 내려간다(페이지별 재시도 폭주 방지)."""
        with patch.dict(os.environ, {"SASOO_PDF_VISUAL_ENGINE": "gemini"}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            with patch.object(odl_parser, "_run_convert_odl", return_value=({}, "", "odl-java")) as odl_mock:
                with patch.object(odl_parser, "_run_convert_gemini") as gem_mock:
                    odl_parser._run_convert(
                        Path("x.pdf"), Path("."), Path("."), "fast",
                        stage="visual", provider="openai",
                    )
        gem_mock.assert_not_called()
        odl_mock.assert_called_once()

    def test_unavailable_message_names_the_active_provider_key(self):
        msg = odl_parser._visual_runtime_unavailable_message("openai")
        self.assertIn("OPENAI_API_KEY", msg)
        self.assertNotIn("GEMINI_API_KEY", msg)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `cd sasoo/backend && .venv/bin/python -m pytest services/test_odl_parser.py -q`
Expected: FAIL — `_plan_visual_engines() takes 0 positional arguments but 1 was given`

- [ ] **Step 3: provider를 배선한다**

상단 import에 추가한다.

```python
from services.provider_state import key_env_for
```

`_plan_visual_engines`가 provider를 받는다. docstring의 "gemini는 GEMINI_API_KEY가 있을 때만" 문구도 함께 고친다.

```python
def _plan_visual_engines(provider: str) -> list[str]:
    ...
    stage_default = _resolve_stage_engine("visual")
    ordered = [stage_default] + [
        engine for engine in (GEMINI_ENGINE_NAME, "odl") if engine != stage_default
    ]
    # 비전 엔진은 활성 provider의 키가 있을 때만 후보에 넣는다. GEMINI_ENGINE_NAME은
    # 공급사가 아니라 "LLM 비전 경로"를 가리키는 레거시 이름이다(provider_state 참조).
    vision_ok = bool((os.environ.get(key_env_for(provider)) or "").strip())
    java_ok = _java_runtime_available()

    plan: list[str] = []
    for engine in ordered:
        if engine == GEMINI_ENGINE_NAME and not vision_ok:
            continue
        if engine == "odl" and not java_ok:
            continue
        plan.append(engine)
    return plan
```

`_run_convert`에 provider를 추가한다.

```python
def _run_convert(
    pdf_path: Path,
    output_dir: Path,
    figures_dir: Path,
    mode: str,
    engine: str | None = None,
    stage: str = "text",
    provider: str | None = None,
) -> tuple[dict[str, Any], str, str]:
```

키 게이트와 디스패치를 고친다.

```python
    selected = _resolve_stage_engine(stage, engine)
    if selected == GEMINI_ENGINE_NAME:
        resolved = provider or _resolve_visual_provider()
        key_env = key_env_for(resolved)
        if not (os.environ.get(key_env) or "").strip():
            logger.warning(
                "%s not set; %s stage falling back to ODL parser engine.", key_env, stage
            )
        else:
            return _run_convert_gemini(pdf_path, output_dir, figures_dir, resolved)
    return _run_convert_odl(pdf_path, output_dir, figures_dir, mode)
```

동기 경로용 provider 조회 헬퍼를 추가한다(`_run_coroutine_sync` 정의 근처).

```python
def _resolve_visual_provider() -> str:
    """LLM 비전 경로가 쓸 공급사. 호출부가 provider를 안 넘긴 경우의 폴백이다.

    동기 함수에서 async active_provider()를 부르므로 기존 브리지를 재사용한다. 문서당
    한 번만 타는 경로라(페이지별이 아니다) 설정 DB 조회 비용은 무시할 수 있다.
    """
    from services.model_registry import active_provider

    return _run_coroutine_sync(active_provider())
```

`_run_convert_gemini`가 provider를 받아 넘긴다.

```python
def _run_convert_gemini(
    pdf_path: Path, output_dir: Path, figures_dir: Path, provider: str = "gemini"
) -> tuple[dict[str, Any], str, str]:
    ...
        return _run_coroutine_sync(
            run_convert_gemini(
                pdf_path, output_dir, figures_dir, usage_out=usage_out, provider=provider
            )
        )
```

`_visual_runtime_unavailable_message`가 provider를 받는다.

```python
def _visual_runtime_unavailable_message(provider: str) -> str:
    key_env = key_env_for(provider)
    label = "OpenAI" if provider == "openai" else "Gemini"
    return (
        f"표·그림 추출에 Java 실행 환경 또는 {label} API 키가 필요합니다. "
        f"동작하는 Java 런타임(backend/java-runtime)이 없고 {key_env}도 설정돼 있지 않습니다."
    )
```

`ensure_visual_artifacts`(`:1409`)에서 provider를 한 번 확정해 내린다. `:1477`의 `_plan_visual_engines()`, `:1490`의 `_run_convert(...)`, `_visual_runtime_unavailable_message()` 호출부에 전달한다.

```python
    visual_provider = _resolve_visual_provider()
    engine_plan = _plan_visual_engines(visual_provider)
```

`:1376`의 `_run_convert` 호출은 text 스테이지다. provider를 넘기지 않고 기본값(None)에 맡긴다 — text 기본 엔진은 `odl`이라 비전 분기를 타지 않는다.

`grep -n "_visual_runtime_unavailable_message\|_plan_visual_engines\|_run_convert_gemini" services/odl_parser.py`로 남은 호출부가 없는지 확인한다.

- [ ] **Step 4: 테스트 통과를 확인한다**

Run: `cd sasoo/backend && .venv/bin/python -m pytest services/test_odl_parser.py -q`
Expected: PASS

Run: `cd sasoo/backend && .venv/bin/python -m pytest -q`
Expected: 640 passed, 3 skipped

- [ ] **Step 5: 커밋**

```bash
git add sasoo/backend/services/odl_parser.py sasoo/backend/services/test_odl_parser.py
git commit -m "feat(parser): 비전 엔진 가용성 판정을 활성 provider 키로

_plan_visual_engines와 _run_convert가 GEMINI_API_KEY를 직접 조회해,
OpenAI 단독 키 사용자는 pdf_visual_engine=gemini(AI 판독)를 골라도
vision 경로에 전혀 진입하지 못하고 로컬 ODL로만 떨어졌다. 설정 화면이
'AI 판독 (정확, 유료)'라고 약속한 동작이 조용히 무시된 것이다.
key_env_for(provider)로 교체하고 provider를 ensure_visual_artifacts에서
한 번 확정해 내려보낸다(스펙 R6의 스테이지 진입 확정 원칙)."
```

---

## Task 4: 감사 도구에 재파싱 모드 추가

**이 태스크가 왜 필요한가(플랜 개정, 2026-08-21):** 원래 Task 4는 `measure.py`를 OpenAI 경로로 돌려 12편 정확도를 재라고 지시했다. 그런데 이 도구는 **페이지 비전 파싱을 다시 돌리지 않는다.** `measure.py:94`가 저장된 `.odl_manifest.json`을 읽고, 이후 호출하는 것은 `build_figure_candidates`/`resolve_figure_candidates`(`:215-216`)와 `build_table_candidates`/`resolve_table_candidates`(`:222-224`)뿐이다. `ensure_visual_artifacts`나 `run_convert_gemini`를 부르는 곳이 없다. 도구 docstring도 "저장된 매니페스트는 옛 코드 산출물"이라며 리졸버 단계를 격리해 재는 것이 의도임을 밝힌다. 따라서 원안대로 돌리면 이미 완료된 리졸버 단계의 provider 중립성을 재게 되고, Task 1~3이 새로 연 페이지 비전 경로는 측정되지 않는다.

**Files:**
- Modify: `sasoo/backend/tools/extraction_audit/measure.py`
- Setup: `sasoo/backend/library/` (worktree는 비어 있다 — 정답셋 12편 PDF만 복사한다. 46.8 MB)

**Interfaces:**
- Consumes: Task 2의 `run_convert_gemini(pdf_path, output_dir, figures_dir, *, usage_out=None, provider="gemini")`
- Produces: `--reparse {gemini,openai}` 플래그. 주면 저장된 매니페스트 대신 그 provider의 비전 엔진으로 매니페스트를 새로 만든 뒤 리졸버를 돌린다. 플래그가 없으면 현행 동작 그대로(회귀 없음).

- [ ] **Step 1: 정답셋 12편 PDF를 worktree 라이브러리에 복사한다**

`measure.py:61`의 `LIBRARY = BACKEND / "library"`는 백엔드 상대 경로다. worktree의 `library/`는 빈 `sasoo.db`만 있는 껍데기이므로 논문을 놓아야 실행조차 되지 않는다. 재파싱 모드는 저장된 매니페스트가 필요 없으니 **PDF만** 복사한다(옛 산출물을 가져오면 재파싱의 의미가 없다).

```bash
cd "/Users/dongj/dev/논문_사수_개발중"
"/Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python" - <<'PY'
import json, shutil
from pathlib import Path

src_lib = Path("sasoo/backend/library")
dst_lib = Path(".claude/worktrees/provider-neutral-llm/sasoo/backend/library")
gold = json.load(open("docs/table_gold.json"))["papers"]

copied = 0
for key in gold:
    src = src_lib / key
    dst = dst_lib / key
    dst.mkdir(parents=True, exist_ok=True)
    for pdf in src.glob("*.pdf"):
        if not (dst / pdf.name).exists():
            shutil.copy2(pdf, dst / pdf.name)
            copied += 1
print(f"복사한 PDF {copied}개 / 정답셋 {len(gold)}편")
PY
```

Expected: `복사한 PDF 12개 / 정답셋 12편`

사용자의 원본 라이브러리에는 **쓰지 않는다**. 복사는 한 방향(원본 → worktree)뿐이다.

- [ ] **Step 2: 키 로딩을 두 공급사로 확장한다**

`measure.py`의 키 로딩 함수(`:405-432` 부근, 읽기 전용 sqlite 연결로 `DB_PATH`와 `~/Library/Application Support/sasoo/sasoo.db`를 후보로 훑는다)가 지금은 `gemini_api_key`만 읽는다. `openai_api_key`도 함께 읽어야 재파싱 OpenAI 모드가 돈다.

`SELECT` 절을 두 키로 넓히고, 성공 판정도 요청된 provider의 환경변수를 보도록 바꾼다.

```python
            rows = connection.execute(
                "SELECT key, value FROM settings WHERE key IN ('gemini_api_key', 'openai_api_key')"
            ).fetchall()
```

성공 판정은 `services.provider_state.key_env_for(provider)`로 한다 — 하드코딩하지 말 것. `init_db()`를 부르지 않고 `mode=ro`를 유지하는 현행 계약(스키마 마이그레이션이 사용자 DB를 바꿀 위험 회피)을 깨지 말 것.

- [ ] **Step 3: 재파싱 헬퍼를 추가한다**

프로덕션(`services/odl_parser.py:1140-1150`)이 매니페스트를 만드는 방식을 그대로 따른다. 인자를 임의로 바꾸면 측정 대상이 프로덕션과 달라진다.

```python
async def _reparse_manifest(pdf_path: Path, scratch: Path, provider: str) -> dict:
    """비전 엔진으로 매니페스트를 새로 만든다(저장된 산출물을 쓰지 않는다).

    프로덕션 경로(_build_resolver_v1_manifest)와 같은 인자로 build_document_manifest를
    부르는 것이 핵심이다 — 여기서 인자가 어긋나면 "제품이 이렇게 뽑는다"가 아니라
    "감사 도구가 이렇게 뽑는다"를 재게 된다.
    """
    from services.document_manifest import build_document_manifest
    from services.gemini_parser import run_convert_gemini
    from services.odl_parser import (
        RESOLVER_PARSER_VERSION,
        RESOLVER_PIPELINE_VERSION,
    )

    figures_dir = scratch / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    root, markdown_text, actual_engine = await run_convert_gemini(
        pdf_path, scratch, figures_dir, provider=provider
    )
    return build_document_manifest(
        pdf_path=pdf_path,
        paper_dir=scratch,
        root=root,
        markdown_text=markdown_text,
        actual_engine=actual_engine,
        requested_mode="fast",
        extraction_pipeline_version=RESOLVER_PIPELINE_VERSION,
        parser_version=RESOLVER_PARSER_VERSION,
        resolver_version="audit",
    )
```

`resolver_version="audit"`는 `measure.py`가 이미 쓰는 값(`:217, 224, 256, 270`)과 맞춘 것이다. `RESOLVER_PARSER_VERSION`은 `"odl-v3"`, `RESOLVER_PIPELINE_VERSION`은 `"resolver_v1"`이다(`services/odl_parser.py:40-41`).

- [ ] **Step 4: 논문 선별과 매니페스트 획득 지점을 분기한다**

`_paper_dirs()`(`:85` 부근)가 후보 조건으로 `.odl_manifest.json` 존재를 요구한다. 재파싱 모드에서는 저장된 매니페스트가 없어도 되므로 `*.pdf`만 요구하도록 분기한다.

매니페스트를 읽는 지점(`:94`의 `json.loads((paper_dir / ".odl_manifest.json").read_text(...))`)도 분기한다. 재파싱 모드면 스크래치를 먼저 만들고 `_reparse_manifest(...)`의 결과를 쓴다. 비재파싱 모드의 코드 경로는 한 줄도 바꾸지 말 것 — 현행 측정의 회귀를 만들면 안 된다.

재파싱 모드에서는 `_prepare_scratch`가 저장된 `.page_rasters`/`.odl_raw_images`를 symlink할 대상이 없다. `build_document_manifest`의 `generate_page_rasters` 기본값이 `True`이므로 래스터는 스크래치에 새로 만들어진다 — 그것이 의도한 동작이다.

- [ ] **Step 5: 플래그를 추가한다**

```python
    parser.add_argument(
        "--reparse",
        choices=["gemini", "openai"],
        default=None,
        help="저장된 매니페스트 대신 이 공급사의 비전 엔진으로 다시 파싱해 측정한다",
    )
```

`--reparse`를 주면 VLM 키가 필수다. 키가 없으면 측정을 시작하지 말고 명확한 메시지로 즉시 종료하라(부분 결과가 정답처럼 기록되는 것을 막는다).

- [ ] **Step 6: 1편으로 연무 시험(smoke)한다**

전체 12편을 돌리기 전에 한 편으로 경로가 실제로 도는지 확인한다. 이것이 이 태스크의 실행 가능한 검증이다.

```bash
cd "/Users/dongj/dev/논문_사수_개발중/.claude/worktrees/provider-neutral-llm/sasoo/backend"
"/Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python" -m tools.extraction_audit.measure \
    --lane production --reparse gemini --papers 2022_SciRep_CoherentFsoLeo
```

확인할 것: ① 예외 없이 완주하는가 ② 그림·표 후보 수가 0이 아닌가 ③ 로그나 원장에 기록된 엔진이 `gemini`인가 ④ 사용자 원본 라이브러리(`/Users/dongj/dev/논문_사수_개발중/sasoo/backend/library`)의 파일 수정 시각이 변하지 않았는가.

④는 실행 전후로 확인하라:

```bash
ls -la --time-style=full-iso "/Users/dongj/dev/논문_사수_개발중/sasoo/backend/library/2022_SciRep_CoherentFsoLeo_optics/" | head
```

관찰한 출력을 보고서에 그대로 적어라. 하나라도 어긋나면 12편 실행으로 넘어가지 말 것.

- [ ] **Step 7: 백엔드 전체 테스트가 여전히 초록인지 확인한다**

`tools/`는 pytest 스위트에 없지만 import 오류가 없어야 한다.

Run: `cd sasoo/backend && .venv/bin/python -m pytest -q`
Expected: 641 passed, 3 skipped

- [ ] **Step 8: Commit**

`library/`는 gitignore 대상이므로(`sasoo/.gitignore:21`) 복사한 PDF는 커밋되지 않는다. `measure.py`만 커밋한다.

```bash
git add sasoo/backend/tools/extraction_audit/measure.py
git commit -m "tools(audit): 감사 lane에 재파싱 모드 추가

기존 lane은 저장된 .odl_manifest.json을 읽어 리졸버 단계만 격리해 쟀다.
그래서 페이지 비전 파싱을 provider별로 바꿔도 이 도구로는 아무 차이가
측정되지 않는다 — 새로 연 OpenAI 비전 경로가 검증 없이 들어갈 참이었다.
--reparse {gemini,openai}를 주면 프로덕션과 같은 인자로 매니페스트를
새로 만든 뒤 리졸버를 돌린다. 플래그가 없으면 현행 동작 그대로다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: 정확도 실측 — 정답셋 12편, 두 공급사

Task 1~4가 경로를 열고 재는 도구를 만들었을 뿐, 쓸 만한지는 아직 모른다. 스파이크는 1편 7페이지였다.

**Files:**
- Run: `sasoo/backend/tools/extraction_audit/measure.py` (Task 4가 확장한 것)
- Create: `docs/superpowers/plans/2026-08-21-openai-vision-audit-record.md`
- 정답셋: `docs/table_gold.json` (12편, 표 라벨 26개)

**Interfaces:**
- Consumes: Task 4의 `--reparse {gemini,openai}`
- Produces: 기록 문서. 게이트가 아니라 **기록**이다(스펙 결정 1). 승격 판단의 근거가 된다.

- [ ] **Step 1: Gemini 기준선을 재파싱 모드로 잰다**

이것이 회귀 게이트다. Task 1~3이 Gemini 동작을 바꾸지 않았다면 기존 12/12 정확일치가 유지되어야 한다.

```bash
cd "/Users/dongj/dev/논문_사수_개발중/.claude/worktrees/provider-neutral-llm/sasoo/backend"
"/Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python" -m tools.extraction_audit.measure \
    --lane production --reparse gemini --no-cache --tag reparse-gemini
```

**깨지면 Task 1~3에 회귀가 있다는 뜻이므로 다음 단계로 넘어가지 말고 보고하라.**

- [ ] **Step 2: OpenAI 경로를 잰다**

```bash
cd "/Users/dongj/dev/논문_사수_개발중/.claude/worktrees/provider-neutral-llm/sasoo/backend"
"/Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python" -m tools.extraction_audit.measure \
    --lane production --reparse openai --no-cache --tag reparse-openai
```

- [ ] **Step 3: 결과를 기록한다**

`docs/superpowers/plans/2026-08-21-openai-vision-audit-record.md`에 아래를 채운다. **추정치를 쓰지 않는다. 실행하지 않은 항목은 "미측정"으로 적는다.**

```markdown
# OpenAI 페이지 비전 파싱 정확도 기록 (2026-08-21)

정답셋: docs/table_gold.json, 12편. 도구: tools.extraction_audit.measure --lane production --reparse {gemini,openai} --no-cache
측정 대상: 페이지 비전 파싱 + 그림·표 후보 생성 + 리졸버 (프로덕션과 같은 인자로 매니페스트 재생성)

| 지표 | Gemini (기준선) | OpenAI | 비고 |
|---|---|---|---|
| 그림 정확일치 | __/12 | __/12 | |
| 표 정확일치 | __/12 | __/12 | |
| 표 라벨 재현율 | | | 정답 26개 기준 |
| 논문당 평균 비용 | $__ | $__ | Gemini effort minimal, OpenAI low |
| 논문당 평균 소요 | __초 | __초 | |
| 요소 과분할 관찰 | | | 스파이크의 p4/p5/p6 관찰이 12편에서도 보이는가 |

## 스파이크(1편 7페이지) 대비
스파이크에서 본 box_2d IoU 0.98 수준과 비용 우위가 12편에서도 유지되는가. 스파이크는 Gemini를
effort low로 돌려 프로덕션(minimal)보다 비싸게 측정했으므로 비용 배율은 이 기록의 값을 쓴다.

## 판정
- [ ] OpenAI 경로를 기본으로 노출할 수 있는가
- [ ] Terra 승격을 검토해야 하는가 (Luna 입력 단가의 10배)
- [ ] 남은 위험
```

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-08-21-openai-vision-audit-record.md
git commit -m "docs: OpenAI 페이지 비전 파싱 정확도 12편 실측 기록

게이트가 아니라 기록이다(스펙 결정 1). Gemini 기준선 회귀 확인 결과와
OpenAI 경로 정확도·비용을 나란히 남긴다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: `provider_state` 문서 갱신

코드는 그대로다. docstring이 이제 사실과 다르다.

**Files:**
- Modify: `sasoo/backend/services/provider_state.py:15-18`

- [ ] **Step 1: docstring을 고친다**

현재 문구는 "pdf_visual_engine은 미러 대상이 아니다. 값 도메인이 {gemini, odl}이고, 이건 공급사가 아니라 ... 독립된 선택이다"다. 뒤쪽 "독립된 선택"이 더는 참이 아니다. 값 도메인은 그대로지만 어떤 LLM이냐는 이제 `ai_provider`를 따른다.

```python
pdf_visual_engine은 미러 대상이 아니다. 값 도메인은 {gemini, odl} 그대로이고,
이건 "LLM 비전으로 판독할까 / 로컬 Java 파서로 뽑을까"라는 선택이다. gemini는
공급사 이름이 아니라 LLM 비전 경로를 가리키는 레거시 이름이다. 어떤 LLM으로
읽을지는 이 값이 정하지 않고 ai_provider가 정한다(2026-08-21). 공급사 값을
직접 넣으면 api/settings.py의 검증이 400으로 거부한다.
```

- [ ] **Step 2: 전체 테스트**

Run: `cd sasoo/backend && .venv/bin/python -m pytest -q`
Expected: 640 passed, 3 skipped

- [ ] **Step 3: 커밋**

```bash
git add sasoo/backend/services/provider_state.py
git commit -m "docs(provider): pdf_visual_engine 설계 설명을 실동작에 맞춤

'독립된 선택'이라는 서술이 더는 참이 아니다. 값 도메인은 그대로지만
어떤 LLM으로 읽을지는 ai_provider가 정한다."
```

---

## 최종 검증

- [ ] **백엔드 전체**: `cd sasoo/backend && .venv/bin/python -m pytest -q` — 640 passed, 3 skipped 기대
- [ ] **프론트엔드**: 이 플랜은 프론트엔드를 건드리지 않는다. 착수 시점 기준선(14 files, 94 tests, `tsc --noEmit` 종료코드 0)이 유지되는지만 확인한다
- [ ] **Gemini 회귀 완주**: Gemini 키만 있는 환경에서 논문 1편을 `pdf_visual_engine=gemini`로 완주. 페이지별 모델이 `gemini-3.6-flash`, effort가 `minimal`인지 로그로 확인
- [ ] **OpenAI 완주**: `GEMINI_API_KEY`를 제거한 환경에서 `pdf_visual_engine=gemini`로 완주. `actual_engine`이 `gemini`(=LLM 비전 경로)로 기록되고, 페이지 호출 모델이 `gpt-5.6-luna`인지 확인. 그림 크롭이 실제로 그림을 담고 있는지 육안 확인
- [ ] **키 없음 폴백**: 두 키를 모두 제거하고 Java 런타임이 있는 환경에서 `odl`로 조용히 내려가는지 확인. 안내 문구가 활성 provider의 키 이름을 말하는지 확인
- [ ] **Task 5 기록 완료**: 12편 결과가 문서에 실측값으로 채워져 있고 "미측정" 항목이 명시되어 있는지
- [ ] **스펙 R2 정정**: `docs/superpowers/specs/2026-07-31-ai-provider-selection-design.md`의 R2에 "2026-08-21 실측으로 뒤집힘, 플랜 2026-08-21-pdf-visual-engine-provider-neutral.md 참조"를 추가
- [ ] **PR 전**: `origin/main` 머지(문서 1건 add/add 충돌 예상 — `2026-08-03-ai-provider-neutral-llm.md`는 feat 쪽이 실측값까지 채워진 최신본이므로 ours 채택). 버전 bump는 `scripts/sync-version.js` 경유. 병합과 publish는 사용자가 수행

## 이 플랜이 다루지 않는 것

- 설정 값 도메인 확장(`openai`를 제3의 엔진 값으로 노출) — 사용자 결정으로 제외. 엔진은 공급사를 따라간다
- `media_resolution` 대응(OpenAI 입력 토큰 2배) — DPI나 타일 전략 조정은 Task 5 비용 결과를 보고 별건으로 판단
- Terra·Sol 승격 — Task 5가 Luna 정확도 부족을 보이면 그때 별건으로
- 요소 과분할 대응 — Task 5에서 실재가 확인되면 별건으로
- `GEMINI_ENGINE_NAME` 상수의 개명(`odl_parser.py:47`과 `gemini_parser.py:36`에 중복 정의) — 매니페스트에 저장되는 값이라 개명은 마이그레이션을 부른다. 레거시 이름으로 유지
