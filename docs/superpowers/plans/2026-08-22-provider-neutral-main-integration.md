# feat/provider-neutral-llm → origin/main 통합 패스 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `feat/provider-neutral-llm`(43커밋 앞섬)을 `origin/main`(10커밋 앞섬)에 통합해, 텍스트 충돌 20개 hunk와 의미 충돌 4건을 해소하고 백엔드 테스트를 초록으로 되돌린다.

**Architecture:** 통합은 두 단계다. 먼저 병합 전에 결정 1(FLASH_HQ + minimal)을 브랜치 안에서 독립 커밋으로 해소해 병합 시점에 양쪽 의미가 같아지게 만든다. 그다음 `git merge origin/main`을 돌려 20개 hunk를 파일 그룹별로 해소한다. 해소 원칙은 "브랜치의 구조(레지스트리 경유, provider 디스패처)를 채택하고, main이 새로 얻은 기능(도입가 단가, `max_output_tokens`, `_CHAIN_CACHE_VERSION`, `salvage_truncated_json`)을 그 구조 안으로 이식한다"이다.

**Tech Stack:** Python 3.12 / pytest + subtests, TypeScript / vitest, google-genai SDK(Interactions API), OpenAI Responses API

**Spec:** `docs/superpowers/specs/2026-07-31-ai-provider-selection-design.md` (R2에 superseded 주석 있음), 인수인계 `docs/superpowers/plans/2026-08-21-provider-neutral-vision-handoff.md`

## Global Constraints

- 작업 경로는 worktree `/Users/dongj/dev/논문_사수_개발중/.claude/worktrees/provider-neutral-llm` 안으로 한정한다. 메인 체크아웃 `/Users/dongj/dev/논문_사수_개발중`은 읽기만 한다.
- Python은 절대 경로로 호출한다: `/Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python` (이 worktree에는 venv가 없다).
- pytest와 git은 샌드박스를 해제해서 실행한다(`dangerouslyDisableSandbox: true`). 해제하지 않으면 OpenDataLoader의 Java 런타임 때문에 `test_end_to_end_java_mode_writes_manifest_and_cache`가 실패하고, git은 `.gitconfig` 접근 거부로 실패한다. 코드 결함이 아니다.
- 착수 기준선(직접 확인함, 2026-08-22): `cd sasoo/backend && pytest -q` → `641 passed, 3 skipped, 6 warnings, 119 subtests passed`.
- push, `main` 병합, PR 생성, 릴리스 게시는 하지 않는다. 사용자가 직접 한다.
- 실제 API를 호출하는 측정은 시작 전에 예상 호출 수와 비용을 보고하고 승인받는다.
- **깨면 안 되는 계약 3개**
  1. 매니페스트에 저장되는 엔진 문자열 `"gemini"`의 값 공간을 바꾸지 않는다. 공급사 이름이 아니라 "LLM 비전으로 파싱됨"을 뜻하는 레거시 이름이고, 바꾸면 승격과 멱등 판정이 전부 깨진다.
  2. 페이지 파서 role은 `pdf_parse`다. 기존 role `visual`(그림 판독 단계, effort `low`)과 섞지 않는다. 이를 막는 테스트가 있다.
  3. `SASOO_GEMINI_PARSER_THINKING`의 빈 문자열은 "미지정"이 아니라 "오버라이드 없음"(레지스트리 값 사용)을 뜻한다. 같은 파일의 `MEDIA_RESOLUTION`은 여전히 옛 관용구다.

## 확정된 사용자 결정

| 번호 | 결정 |
|---|---|
| 1 | 레지스트리 gemini 4곳(`pdf_parse`, `figure_resolver`, `table_resolver`, `subfigure`)을 `low`로 맞추고, FLASH_HQ role에 `minimal`이 다시 들어오는 것을 막는 테스트를 추가한다. |
| 2 | main 통합 패스를 별도 작업으로 먼저 돌린다. 브랜치 분할은 하지 않는다. |
| 3 | 재측정은 최소 범위(통합 후 12편 × 1회 × 2공급사). 실행 전 비용 재보고와 승인 필요. |
| 4 | 표 1편 차이(OpenAI 9/12 대 Gemini 10/12)를 수용한다. |
| 5·6 | `measure.py`가 실패한 표 번호를 남기게 한다. 릴리스 노트 문구를 초안으로 작성한다. 나머지 후속(`_run_convert` provider 배선, `requested_mode` 정규화)은 별도 이슈로 남긴다. |

## 결정 1의 근거 (재조사 결과)

인수인계 문서는 리졸버 3곳의 `minimal`을 이 브랜치의 산물로 적었으나, 실제 이력은 다르다.

| 시점 | figure_resolver | table_resolver | subfigure | gemini_parser 기본값 |
|---|---|---|---|---|
| merge-base `1ba9fef` (2026-08-05) | minimal | minimal | minimal | minimal |
| origin/main 현재 (#51 `159c5f2`) | **low** | **low** | **low** | **low** |
| 이 브랜치 (레지스트리로 이동) | minimal | minimal | minimal | minimal (`pdf_parse`) |

`minimal`은 merge-base 유산이고, main #51이 네 곳 전부를 `# 3.7 Flash는 minimal을 거부한다(400). low가 이 모델의 최저치다.`라는 주석과 함께 `low`로 올렸다. 따라서 `low`로 맞추는 것은 정확도 회귀가 아니라 main과의 동치 회복이고, `minimal`을 유지하는 쪽이 main 대비 회귀(400 검증 에러)다. `screening`과 `naming`은 모델이 flash-lite이므로 `minimal`을 유지한다. OpenAI 레지스트리는 전 role이 이미 `low` 이상이라 영향이 없다.

## File Structure

병합 전 수정 (Task 1):

- Modify: `sasoo/backend/services/model_registry.py` — gemini 표의 4개 role effort를 `low`로. 400 거부 근거 주석을 여기로 옮긴다.
- Create/Modify: `sasoo/backend/services/test_model_registry.py` — FLASH_HQ role에 `minimal`이 없음을 잠그는 테스트.

병합 충돌 해소 (Task 2). 20개 hunk, 11파일:

| 파일 | hunk | 해소 방향 |
|---|---|---|
| `sasoo/vitest.config.ts` | 1 | HEAD의 `@` 별칭 주석 유지 |
| `sasoo/backend/services/figure_resolver.py` | 2 | HEAD(레지스트리 경유) |
| `sasoo/backend/services/table_resolver.py` | 1 | HEAD(레지스트리 경유) |
| `sasoo/backend/services/subfigure_detector.py` | 1 | HEAD(레지스트리 경유) |
| `sasoo/backend/services/gemini_parser.py` | 1 | HEAD(오버라이드 관용구) |
| `sasoo/backend/services/models.py` | 1 | 합집합 — `MODEL_LUNA` + `MODEL_FLASH_PREV` |
| `sasoo/backend/services/pricing.py` | 1 | 합성 — main의 `_rate` + HEAD의 `_fallback_for` |
| `sasoo/backend/services/test_pricing.py` | 1 | 합집합 |
| `sasoo/backend/tools/provider_compare.py` | 3 | HEAD 채택 + main의 `cost_of` 단가 단일 출처 이식 |
| `sasoo/backend/services/llm/interactions_client.py` | 1 | HEAD(디스패처) + `max_output_tokens`를 두 클라이언트로 이식 |
| `sasoo/backend/api/analysis_routes.py` | 7 | 합집합. 캐시 키 합성이 핵심 |

병합 후 추가 작업:

- Modify: `sasoo/backend/services/llm/gemini_client.py`, `sasoo/backend/services/llm/openai_client.py` — `max_output_tokens` 파라미터 이식 (Task 2 안에서 수행).
- Modify: `sasoo/backend/tools/extraction_audit/measure.py` — 실패한 표 번호 기록 (Task 3).
- Create: `docs/superpowers/plans/2026-08-22-release-note-provider-switch.md` — 릴리스 노트 문구 초안 (Task 4).

## 의미 충돌 4건 (기계적으로 풀면 조용히 깨지는 자리)

1. **결정 1** — 레지스트리의 `minimal`이 병합 후 `gemini-3.7-flash`에 실려 400을 받는다. Task 1에서 선제 해소.
2. **`max_output_tokens`** — main #53(`2e08766`)이 `interactions_client.call_interaction`에 이 파라미터를 추가했는데, 브랜치는 그 구현을 `gemini_client.py`로 옮기고 `interactions_client.py`를 30줄 디스패처로 만들었다. HEAD를 그냥 채택하면 파라미터가 사라진다. `test_gemini_client.py`가 auto-merge로 main의 테스트 3건(`test_call_interaction_passes_max_output_tokens` 등)을 이미 받았으므로 실패로 드러나기는 한다. 반면 **`openai_client.py`는 테스트가 없으므로 조용히 깨진다**: `analysis_routes`가 `_STAGE_MAX_OUTPUT_TOKENS.get(phase)`를 넘기고 디스패처가 `**kwargs`로 통과시키므로, provider가 openai이고 phase가 `recipe`일 때 `TypeError`가 난다.
3. **캐시 키** — main은 `_phase_cache_key(model=, thinking=, system_instruction=, prompt=)`로 `_CHAIN_CACHE_VERSION`을 키에 담고, 브랜치는 `compute_input_hash(input_text, provider=, model=, effort=)`로 provider를 담는다. 두 방식은 겹치지 않고 상보적이다. 한쪽만 고르면 체인 버전 무효화 또는 공급사 격리가 사라진다.
4. **단가 폴백** — main의 `_rate()`는 폴백이 `PRICING[_FALLBACK]`(Gemini)이고, 브랜치는 `_fallback_for(model)`로 `gpt-*`를 Luna 단가로 보낸다. main 쪽만 채택하면 미지의 `gpt-*` 모델이 Gemini 단가로 계산되어 `test_unknown_openai_model_does_not_use_gemini_fallback`이 실패한다. HEAD 쪽만 채택하면 도입가 절반 반영이 사라져 비용이 2배로 과대계상된다.

---

### Task 1: 결정 1 — 레지스트리 effort를 low로 올리고 회귀를 잠근다

**Files:**
- Modify: `sasoo/backend/services/model_registry.py` (gemini 표의 `pdf_parse`, `figure_resolver`, `table_resolver`, `subfigure`)
- Test: `sasoo/backend/services/test_model_registry.py`

**Interfaces:**
- Consumes: `services.model_registry.resolve(role: str, provider: str) -> ModelChoice` (`analysis_routes`는 `resolve as resolve_model` 별칭으로 import한다), `ModelChoice(model: str, effort: str | None)`, `_REGISTRY: dict[str, dict[str, ModelChoice]]` (기존)
- Produces: gemini 표의 네 role이 `effort == "low"`. 다른 role과 OpenAI 표는 불변.

- [ ] **Step 1: 현재 값과 테스트 파일 이름을 확인한다**

```bash
cd /Users/dongj/dev/논문_사수_개발중/.claude/worktrees/provider-neutral-llm
grep -n 'minimal' sasoo/backend/services/model_registry.py
ls sasoo/backend/services/ | grep -i registry
```

기대: `model_registry.py`의 gemini 표에서 `screening`(47행 부근), `pdf_parse`(51행 부근), `figure_resolver`(59행 부근), `table_resolver`(60행 부근), `subfigure`(61행 부근), `naming`(62행 부근) 여섯 자리가 `"minimal"`이다. 테스트 파일이 없으면 다음 단계에서 만든다.

- [ ] **Step 2: 실패하는 테스트를 쓴다**

`sasoo/backend/services/test_model_registry.py`에 추가한다(파일이 없으면 이 내용으로 새로 만들고, 있으면 끝에 붙인다).

```python
def test_flash_hq_roles_never_use_minimal_effort():
    """FLASH_HQ(=3.7 Flash)는 minimal을 400으로 거부한다.

    근거: services/models.py 모듈 docstring, ai.google.dev 2026-08-16 확인.
    main #51(159c5f2)이 figure_resolver/table_resolver/subfigure/gemini_parser
    네 곳을 이 이유로 low로 올렸다. 레지스트리로 값을 옮기면서 minimal이 다시
    들어오면 그 네 경로가 런타임에 400을 받는다 — 테스트 없이는 실호출에서만 드러난다.

    minimal이 안전한 곳은 flash-lite를 쓰는 role뿐이다(screening, naming).
    """
    from services.model_registry import _REGISTRY
    from services.models import MODEL_FLASH_HQ, MODEL_FLASH_LITE

    offenders = [
        role
        for role, choice in _REGISTRY["gemini"].items()
        if choice.effort == "minimal" and choice.model != MODEL_FLASH_LITE
    ]
    assert offenders == [], (
        f"minimal은 flash-lite에서만 쓸 수 있다. FLASH_HQ({MODEL_FLASH_HQ})를 "
        f"쓰면서 minimal인 role: {offenders}"
    )
```

`_REGISTRY`는 `dict[str, dict[str, ModelChoice]]`이고 `model_registry.py:45`에 있다(확인함). 공개 API는 `resolve(role, provider)`와 `ROLES`다.

- [ ] **Step 3: 테스트가 실패하는 것을 확인한다**

```bash
cd sasoo/backend && /Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python -m pytest services/test_model_registry.py::test_flash_hq_roles_never_use_minimal_effort -v
```

기대: FAIL. 메시지에 `['pdf_parse', 'figure_resolver', 'table_resolver', 'subfigure']`가 나온다(순서는 dict 삽입 순서).

- [ ] **Step 4: 네 곳을 low로 올린다**

`sasoo/backend/services/model_registry.py`의 gemini 표를 이렇게 만든다. `screening`과 `naming`은 그대로 둔다.

```python
        # FLASH_HQ(3.7 Flash)는 minimal을 400으로 거부한다 — low가 이 모델의
        # 최저치다(ai.google.dev, 2026-08-16 확인). main #51이 같은 이유로
        # figure/table/subfigure 리졸버와 페이지 파서를 low로 올렸다.
        # minimal이 남아 있는 곳은 flash-lite를 쓰는 screening과 naming뿐이다.
        # 잠금: services/test_model_registry.py
        "pdf_parse": ModelChoice(MODEL_VISUAL, "low"),
        ...
        "figure_resolver": ModelChoice(MODEL_FLASH_HQ, "low"),
        "table_resolver": ModelChoice(MODEL_FLASH_HQ, "low"),
        "subfigure": ModelChoice(MODEL_FLASH_HQ, "low"),
```

`pdf_parse` 위에 있던 기존 주석(`# 페이지 파서는 thinking을 최소로 쓰는 축자 전사 작업이라 effort가 minimal이다.`)은 사실이 아니게 되므로 위 주석으로 교체한다.

- [ ] **Step 5: 테스트가 통과하고 기존 테스트가 깨지지 않았는지 확인한다**

```bash
cd sasoo/backend && /Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python -m pytest -q
```

기대: `test_flash_hq_roles_never_use_minimal_effort` 통과. 총계는 642 passed(신규 1건 추가), 3 skipped.

`minimal`을 값으로 단정한 기존 테스트가 있으면 여기서 실패한다. 그 경우 테스트를 지우지 말고, 왜 그 값을 기대했는지 확인한 뒤 `low`로 갱신하면서 근거 주석을 남긴다.

- [ ] **Step 6: 커밋한다**

```bash
git add sasoo/backend/services/model_registry.py sasoo/backend/services/test_model_registry.py
git commit -m "$(cat <<'EOF'
fix(registry): FLASH_HQ role의 effort를 minimal에서 low로 — 3.7 Flash 400 회피

main #51(159c5f2)이 figure_resolver/table_resolver/subfigure/gemini_parser 네
곳을 minimal에서 low로 올렸다. 근거는 3.7 Flash가 minimal을 검증 에러(400)로
거부한다는 것이다(ai.google.dev, 2026-08-16 확인). 이 브랜치는 그 값들을
model_registry로 옮겨 담았는데, 옮긴 값이 merge-base 시점의 minimal이라 병합하면
FLASH_HQ = gemini-3.7-flash에 minimal이 실려 네 경로가 런타임에 400을 받는다.

pdf_parse도 같은 처지다. main의 gemini_parser._THINKING_LEVEL 기본값이 이미
low이므로, pdf_parse를 low로 두면 main과 값이 동치가 된다.

minimal이 안전한 곳은 flash-lite를 쓰는 screening과 naming뿐이다. 이 규약을
테스트로 잠갔다 — 값만 고치면 다음에 같은 자리로 되돌아온다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: origin/main 병합과 충돌 20 hunk 해소

**Files:**
- Modify (충돌 11파일): 위 File Structure 표 참조
- Modify (이식): `sasoo/backend/services/llm/gemini_client.py`, `sasoo/backend/services/llm/openai_client.py`

**Interfaces:**
- Consumes: Task 1이 만든 레지스트리 값(`effort == "low"`)
- Produces: 병합 커밋 하나. `call_interaction(..., max_output_tokens: int | None = None)`이 두 클라이언트 모두에 존재. `_phase_cache_key`와 `compute_input_hash`가 함께 살아 있는 캐시 키 경로.

병합 중에는 중간 커밋을 만들 수 없다(만들면 병합 커밋이 된다). 그래서 이 Task는 단계마다 부분 검증만 하고 커밋은 마지막에 한 번 한다. 도중에 방향이 잘못되면 `git merge --abort`로 전부 되돌리고 처음부터 다시 한다.

- [ ] **Step 1: 병합을 시작하고 충돌 목록을 고정한다**

```bash
cd /Users/dongj/dev/논문_사수_개발중/.claude/worktrees/provider-neutral-llm
git fetch origin
git merge origin/main --no-commit --no-ff
git diff --name-only --diff-filter=U | while read f; do echo "$(grep -c '^<<<<<<<' "$f") $f"; done
```

기대: 11파일, hunk 합계 20개. Task 1 때문에 리졸버 3종과 `gemini_parser`의 hunk 수는 변하지 않는다(HEAD 쪽이 `_choice.effort`, main 쪽이 `"low"` 리터럴이라 텍스트는 여전히 다르다). 파일 수나 hunk 수가 이와 다르면 멈추고 원인을 확인한다.

- [ ] **Step 2: 리졸버 3종과 gemini_parser, vitest.config.ts를 해소한다**

`figure_resolver.py`(2곳), `table_resolver.py`(1곳), `subfigure_detector.py`(1곳)는 HEAD 쪽을 채택하고, main의 400 근거 주석을 옮겨 적는다. 예를 들어 `table_resolver.py`는 이렇게 된다.

```python
            model=_choice.model,
            # effort는 model_registry가 정한다. FLASH_HQ는 minimal을 400으로
            # 거부하므로 gemini 표의 값이 low다(services/test_model_registry.py).
            thinking_level=_choice.effort,
```

`gemini_parser.py`는 HEAD 쪽을 채택한다. main의 값(`low`)은 이미 레지스트리에 들어갔으므로 오버라이드 기본값은 빈 문자열을 유지한다.

```python
# thinking 토큰은 출력 단가로 과금됨. 빈 문자열이면 model_registry의 pdf_parse role 값을
# 쓴다(Gemini=low, OpenAI=low). 명시하면 provider 무관하게 이 값이 이긴다 —
# 베이스라인 재현 절차(위 주석)가 이 레버에 의존한다.
_THINKING_OVERRIDE = _env_str("SASOO_GEMINI_PARSER_THINKING", "")
```

HEAD 쪽 주석의 `(Gemini=minimal, OpenAI=low)`를 `(Gemini=low, OpenAI=low)`로 고치는 것을 잊지 않는다. Task 1이 값을 바꿨으므로 그 주석은 이제 틀렸다.

`sasoo/vitest.config.ts`는 HEAD의 주석 3줄을 유지하고 마커만 지운다. main 쪽은 그 주석이 없을 뿐 코드가 같다.

검증:

```bash
grep -rn '<<<<<<<\|>>>>>>>' sasoo/backend/services/figure_resolver.py sasoo/backend/services/table_resolver.py sasoo/backend/services/subfigure_detector.py sasoo/backend/services/gemini_parser.py sasoo/vitest.config.ts
```

기대: 출력 없음.

- [ ] **Step 3: models.py를 합집합으로 해소한다**

두 상수를 모두 남긴다. 순서는 Gemini 상수 다음에 OpenAI 상수가 오도록 한다.

```python
# 이전 세대 flash. 현재 어느 단계도 쓰지 않는다. DB에 이 모델이 만든 행이 남아 있어
# 단가 계산을 위해 상수와 PRICING 항목을 유지한다(services/test_model_pins.py가 잠근다).
MODEL_FLASH_PREV = "gemini-3.6-flash"

# OpenAI 텍스트 모델 — provider 중립화(스펙 2026-07-31 + 개정 1)
MODEL_LUNA = "gpt-5.6-luna"
```

모듈 docstring도 확인한다. main 쪽 docstring(3.7 Flash 근거, `thinking_level은 low|medium|high만 쓴다`)이 auto-merge로 살아 있어야 한다. 살아 있다면 그 문단에 OpenAI 쪽 한 줄을 덧붙인다.

```
  LUNA        - gpt-5.6-luna. OpenAI 키 단독 사용자의 전 단계 기본 모델.
                minimal을 지원하지 않아 최저 effort가 low다(플랜 Task 0 실측).
```

검증:

```bash
cd sasoo/backend && /Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python -c "
import services.models as m
print(m.MODEL_FLASH_HQ, m.MODEL_FLASH_PREV, m.MODEL_LUNA)
assert m.MODEL_FLASH_HQ == 'gemini-3.7-flash'
assert m.MODEL_FLASH_PREV == 'gemini-3.6-flash'
assert m.MODEL_LUNA == 'gpt-5.6-luna'
print('ok')
"
```

기대: `gemini-3.7-flash gemini-3.6-flash gpt-5.6-luna` 다음에 `ok`.

- [ ] **Step 4: pricing.py를 합성해 해소한다 (의미 충돌 4)**

`calc_cost` 안의 충돌은 main 쪽(`_rate`)을 채택한다.

```python
        pricing = _rate(model, as_of or datetime.now(timezone.utc).date())
```

그리고 `_rate`의 폴백을 브랜치의 `_fallback_for`로 바꾼다. 이 한 줄이 빠지면 미지의 `gpt-*` 모델이 Gemini 단가로 계산된다.

```python
def _rate(model: str, as_of: date) -> dict[str, float]:
    """기준일에 유효한 (input, output) 단가.

    폴백은 공급사별로 갈린다 — gpt-* 를 Gemini 단가로 계산하면 비용이 조용히
    오산된다(스펙 R7-1, services/test_pricing.py가 잠근다).
    """
    intro = INTRO_PRICING.get(model)
    if intro is not None and as_of <= intro.through:
        return {"input": intro.input, "output": intro.output}
    return PRICING.get(model) or PRICING[_fallback_for(model)]
```

`_fallback_for`가 `_rate`보다 아래에 정의돼 있어도 함수 본문 안의 참조라 문제가 없다. 다만 `_fallback_for`가 auto-merge 결과 남아 있는지 `grep -n '_fallback_for' sasoo/backend/services/pricing.py`로 확인한다. 없으면 브랜치 버전에서 되살린다.

```python
_FALLBACK_OPENAI = "gpt-5.6-luna"


def _fallback_for(model: str) -> str:
    return _FALLBACK_OPENAI if model.startswith("gpt-") else _FALLBACK
```

- [ ] **Step 5: test_pricing.py를 합집합으로 해소하고 단가 테스트를 돌린다**

양쪽 테스트를 모두 남긴다. main 쪽 6건(`test_gemini_37_flash_uses_intro_price_through_2026`, `test_gemini_37_flash_uses_standard_price_from_2027`, `test_gemini_36_flash_shares_the_same_intro_schedule`, `test_intro_price_does_not_leak_into_models_without_a_schedule`, `test_long_context_override_still_wins_for_pro`, `test_every_model_constant_is_priced`)과 HEAD 쪽 3건(`test_luna_is_registered`, `test_unknown_openai_model_does_not_use_gemini_fallback`, `test_unknown_gemini_model_keeps_existing_fallback`)이 전부 남아야 한다. import 줄에 `date`와 `pytest`가 모두 있는지 확인한다.

```bash
cd sasoo/backend && /Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python -m pytest services/test_pricing.py -v
```

기대: 전건 통과. `test_every_model_constant_is_priced`가 `gpt-5.6-luna`와 `gpt-image-2`를 요구하는데 브랜치가 이미 `PRICING`과 `IMAGE_PRICING`에 넣어 뒀으므로 통과한다. 실패하면 빠진 모델 ID가 메시지에 찍힌다.

- [ ] **Step 6: interactions_client 디스패처를 채택하고 max_output_tokens를 이식한다 (의미 충돌 2)**

`interactions_client.py`는 HEAD(30줄 디스패처)를 채택한다. main 쪽 구현 전체(약 300줄)를 버린다 — 그 구현은 이미 `gemini_client.py`에 있다.

```bash
git checkout --ours sasoo/backend/services/llm/interactions_client.py
grep -c '' sasoo/backend/services/llm/interactions_client.py
```

기대: 30줄 부근. `<<<<<<<` 마커가 남아 있지 않은지 확인한다.

그다음 main #53이 추가한 `max_output_tokens`를 두 클라이언트에 이식한다. `gemini_client.py`의 `call_interaction`(127행 부근):

```python
async def call_interaction(
    prompt,
    *,
    lane: Lane,
    model: str = MODEL_FLASH_HQ,
    system_instruction: str | None = None,
    thinking_level: str | None = None,
    previous_interaction_id: str | None = None,
    response_schema: dict | None = None,
    store: bool = True,
    media_resolution: str | None = None,
    max_output_tokens: int | None = None,
) -> dict:
```

그리고 `_sync_call_once` 안에서 `generation_config`를 조립한다. 현재 브랜치 코드는 `thinking_level`만 담고 있으므로 main #53의 형태로 바꾼다.

```python
        generation_config: dict = {}
        if thinking_level:
            generation_config["thinking_level"] = thinking_level
        # VERIFY(확인됨, static/api/interactions.md.txt 2026-08-17): GenerationConfig의
        # max_output_tokens. 상한에 걸리면 status가 "incomplete"로 온다. 기본값은
        # 문서에 없으므로 우리가 임의로 정하지 않는다 — 안 주면 키를 안 보낸다.
        if max_output_tokens is not None:
            generation_config["max_output_tokens"] = max_output_tokens
        if generation_config:
            kwargs["generation_config"] = generation_config
```

`openai_client.py`의 `call_interaction`(104행 부근)에도 같은 파라미터를 받게 한다. 여기가 조용히 깨지는 자리다 — `analysis_routes`가 `recipe` phase에서 `max_output_tokens=24000`을 넘기고 디스패처가 `**kwargs`로 통과시키므로, 파라미터가 없으면 provider가 openai일 때 `TypeError`가 난다. Responses API의 대응 필드는 `max_output_tokens`다.

```python
    media_resolution: str | None = None,  # noqa: ARG001 - Gemini 전용, 시그니처 호환용
    max_output_tokens: int | None = None,
) -> dict:
```

호출 조립부에서 값이 있을 때만 키를 넣는다(Gemini 쪽과 같은 원칙 — 기본값을 우리가 정하지 않는다).

```python
        if max_output_tokens is not None:
            kwargs["max_output_tokens"] = max_output_tokens
```

`openai_client.py`가 실제로 쓰는 SDK 호출 형태(`client.responses.create(**kwargs)` 인지 다른 래퍼인지)를 먼저 읽고 그 관용구에 맞춘다.

- [ ] **Step 7: openai_client의 max_output_tokens에 회귀 테스트를 붙인다**

main이 `test_gemini_client.py`에 남긴 테스트 3건은 auto-merge로 이미 들어와 있다. OpenAI 쪽은 테스트가 없어서 조용히 깨지므로 `sasoo/backend/services/llm/test_openai_client.py`에 추가한다. 기존 테스트의 mock 관용구를 그대로 따른다(파일 앞부분을 읽어 `patch` 대상과 반환 객체 조립 방식을 확인한다).

```python
def test_call_interaction_passes_max_output_tokens():
    """analysis_routes가 recipe phase에서 이 값을 넘긴다.

    파라미터가 없으면 디스패처의 **kwargs가 그대로 전달돼 TypeError가 난다.
    Gemini 쪽만 고치고 여기를 빼면 OpenAI 사용자에게서만 터진다.
    """
    with _patched_client() as captured:
        asyncio.run(call_interaction(
            "안녕", lane="pipeline", thinking_level="low", max_output_tokens=24000,
        ))
    assert captured["kwargs"]["max_output_tokens"] == 24000


def test_call_interaction_omits_max_output_tokens_when_not_given():
    """안 주면 키를 안 보낸다 — 기본값을 우리가 정하지 않는다."""
    with _patched_client() as captured:
        asyncio.run(call_interaction("안녕", lane="pipeline"))
    assert "max_output_tokens" not in captured["kwargs"]
```

`_patched_client()`는 기존 파일의 관용구로 대체한다. 헬퍼가 없으면 파일에 이미 있는 다른 테스트와 같은 방식으로 인라인 patch를 쓴다.

검증:

```bash
cd sasoo/backend && /Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python -m pytest services/llm/ -q
```

기대: 전건 통과. `test_gemini_client.py`의 `max_output_tokens` 테스트 3건과 새 OpenAI 테스트 2건이 모두 초록이어야 한다.

- [ ] **Step 8: provider_compare.py를 해소한다**

세 hunk 모두 HEAD를 채택한다. HEAD는 레지스트리 경유, provider 인자, effort 비교 모드까지 갖춘 발전형이고 main 쪽은 자체 상수를 든 이전 형태다. 다만 main의 개선 한 가지를 살린다: 도구가 자체 `OPENAI_RATES` 상수로 단가를 계산하면 `pricing.py`와 이중 출처가 된다. HEAD가 이미 `calc_cost`를 쓰는지 확인하고(`grep -n 'calc_cost\|OPENAI_RATES' sasoo/backend/tools/provider_compare.py`), `OPENAI_RATES`가 남아 있으면 지우고 `calc_cost`로 통일한다. `gpt-5.6-luna`는 이제 `PRICING`에 있으므로 `calc_cost`가 바로 처리한다.

docstring의 `Gemini 3.6 Flash`는 `프로덕션 Gemini(MODEL_FLASH_HQ)`로 고친다. 3.6은 이제 어느 단계도 쓰지 않는다.

검증:

```bash
cd sasoo/backend && /Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python -c "
import ast, pathlib
ast.parse(pathlib.Path('tools/provider_compare.py').read_text())
print('parse ok')
"
```

- [ ] **Step 9: analysis_routes.py의 7 hunk를 해소한다 (의미 충돌 3 포함)**

hunk 1 (`_get_cached_phase_result` 안의 insert). 양쪽을 합친다. HEAD의 `fallback_hash`(provider/model/effort를 담은 해시)를 쓰고, main이 추가한 `result_id`를 반환 dict에 남긴다. `result_id`는 hunk 안이 아니라 그 아래 반환 dict에 속하므로, 반환 dict 쪽에 `"result_id": cached.result_id,`가 살아 있는지 확인한다(Evidence 앵커가 이 값을 쓴다).

```python
            cached.input_hash or fallback_hash,
```

hunk 2 (결과 저장 함수 시그니처). 합집합이다. HEAD의 키워드 세 개와 main의 반환형·docstring을 모두 남긴다.

```python
async def _insert_analysis_result(
    ...,
    *,
    provider: str | None = None,
    model: str | None = None,
    effort: str | None = None,
) -> int:
    """analysis_results에 결과를 저장하고 lastrowid를 반환한다.

    반환값은 Evidence 앵커를 이 행에 결속하는 데 쓴다(스펙 §결정 4). 기존 호출부는
    반환값을 쓰지 않으므로 동작이 바뀌지 않는다.
    """
    return await execute_insert(
```

함수 이름은 `_insert_analysis_result`다(`sasoo/backend/api/analysis_routes.py:393`). `execute_insert`가 `await`로 감싸져 반환되도록 `return`을 빠뜨리지 않는다 — 빠지면 Evidence 앵커가 조용히 `None`을 받는다.

hunk 3 (screening 캐시 조회). 여기가 의미 충돌 3이다. main의 `_phase_cache_key`(체인 버전 무효화)와 HEAD의 provider 격리를 함께 살린다.

```python
    choice = resolve_model("screening", provider)
    cache_key = _phase_cache_key(
        model=choice.model, thinking=choice.effort or "", system_instruction="", prompt=prompt,
    )
    cached = await _get_cached_phase_result(
        paper_id, "screening", cache_key,
        provider=provider, model=choice.model, effort=choice.effort,
    )
```

`_phase_cache_key`가 `model`과 `thinking`을 이미 담고 `compute_input_hash`도 `model`/`effort`를 담아 중복되지만 무해하다. 둘 중 하나를 빼면 안 된다: `_phase_cache_key`를 빼면 `_CHAIN_CACHE_VERSION` 무효화가 사라지고, `compute_input_hash` 인자를 빼면 공급사 격리가 사라진다.

같은 패턴이 screening 외 다른 phase에도 있으면(`grep -n '_get_cached_phase_result' sasoo/backend/api/analysis_routes.py`) 전부 같은 형태로 맞춘다. `_phase_cache_key`가 `thinking`에 `None`을 받으면 문자열 join에서 터지므로 `choice.effort or ""`로 감싼다.

hunk 4 (screening 재시도). 합집합이다. main의 `salvage_truncated_json`을 먼저 시도하고, 살릴 수 없을 때만 재시도하면서 HEAD의 attempt별 비용 계산(R7-3)을 적용한다.

```python
        salvaged = salvage_truncated_json(result.get("text") or "", _SCREENING_SCHEMA)
        if salvaged is not None:
            logger.warning(
                "screening %s (tokens_out=%s); 잘린 앞부분을 살려 재시도를 건너뛴다",
                defect, result.get("tokens_out"),
            )
            result["text"] = salvaged
        else:
            logger.warning(
                "screening %s (tokens_out=%s); retrying once",
                defect, result.get("tokens_out"),
            )
            retry = await _invoke()
            # 재시도 사용량은 attempt별로 비용을 계산해 합산한다(R7-3) — 토큰을
            # 합쳐 한 번에 계산하면 장문 임계값이 잘못 적용되거나(단가 구간 있는
            # 모델) 이후 tokens_in/out 합산과 겹쳐 비용이 이중 계산된다.
            retry["cost_usd_prior_attempts"] = calc_cost(
                result["model"], result.get("tokens_in") or 0, result.get("tokens_out") or 0,
            ) + calc_cost(
                retry["model"], retry.get("tokens_in") or 0, retry.get("tokens_out") or 0,
            )
            # 사용량 표시(tokens_in/out)는 실사용 총량이 맞으므로 토큰 합산은 유지한다.
            retry["tokens_in"] = (result.get("tokens_in") or 0) + (retry.get("tokens_in") or 0)
            retry["tokens_out"] = (result.get("tokens_out") or 0) + (retry.get("tokens_out") or 0)
            result = retry
```

hunk 5 (`_PHASE_TO_ROLE` 대 `_STAGE_*`). HEAD의 `_PHASE_TO_ROLE`을 채택하되 **main의 `_STAGE_MAX_OUTPUT_TOKENS`를 반드시 남긴다.** 이건 recipe 폭주의 2차 방어선이고 `services/test_model_pins.py::test_recipe_keeps_an_output_cap`이 잠근다. `_STAGE_THINKING`과 `_STAGE_MODELS`는 레지스트리가 대체했으므로 버린다. 버리기 전에 `grep -n '_STAGE_THINKING\|_STAGE_MODELS' sasoo/backend/`로 남은 참조가 없는지 확인한다.

```python
# 체인 스테이지 이름과 레지스트리 role의 번역표.
# "visualization"(파이프라인 내부 명)만 레지스트리 role "viz_planning"과 다르다.
_PHASE_TO_ROLE = {
    "visual": "visual",
    "recipe": "recipe",
    "deep_dive": "deep_dive",
    "visualization": "viz_planning",
}

# 폭주 반복이 뚫렸을 때의 손해 상한. 스키마 쪽 조치(마지막 속성을 숫자로)가 1차
# 방어고, 이건 그게 뚫려도 비용이 유한하게 끝나도록 하는 2차 방어다.
# 값 근거: 실측 최대 정상 recipe 본문이 12,416자(파라미터 26개 완성)였고, 폭주는
# 모델 상한 65,536까지 갔다. 이 상한은 **thinking 토큰을 포함해서 센다**(문서에 없어
# 실호출로 확인. 상한 2,000 -> tokens_out 1,986, 그중 thinking 1,213). recipe의
# medium thinking이 실측 600~4,000이라 24,000이면 본문에 최소 20,000이 남는다.
# 상한에 걸리면 status가 incomplete로 오고 꼬리가 잘리는데, 그건 이미
# salvage_truncated_json이 값 경계에서 되살린다.
# 잠금: api/test_recipe_output_bounds.py
_STAGE_MAX_OUTPUT_TOKENS = {"recipe": 24_000}
```

hunk 6, 7 (파라미터와 인자 전달). 합집합이다. 양쪽 파라미터를 모두 남기고, 호출부에도 둘 다 넘긴다.

```python
    doc_text: str = "",
    provider: str = "gemini",
    folder_name: str = "",
```

```python
            doc_text=doc_text,
            provider=provider,
            folder_name=folder_name,
```

검증:

```bash
grep -rn '<<<<<<<\|=======\|>>>>>>>' sasoo/backend/ sasoo/frontend/ sasoo/electron/ sasoo/vitest.config.ts 2>/dev/null | grep -v '\.pyc'
cd sasoo/backend && /Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python -c "import api.analysis_routes; print('import ok')"
```

기대: 마커 없음(`=======`는 마크다운 구분선으로 오검출될 수 있으니 대상 경로를 코드로 한정한다), import 성공.

- [ ] **Step 10: 전체 테스트를 돌린다**

```bash
cd sasoo/backend && /Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python -m pytest -q 2>&1 | tail -20
```

기대: 실패 0건. 총계는 641(기준선) + Task 1의 1건 + Task 2 Step 7의 2건 + main이 가져온 신규 테스트만큼 늘어난다. 정확한 숫자를 미리 단정하지 않고, **실패가 0건인지**와 **skipped가 3건인지**로 판정한다. skipped가 늘었으면 어떤 테스트가 왜 건너뛰어졌는지 확인한다.

실패가 나오면 systematic-debugging으로 하나씩 처리한다. 실패를 테스트 수정으로 덮지 않는다 — 특히 main이 가져온 테스트가 실패하면 그것은 이식이 덜 된 신호다.

프론트엔드도 돌린다.

```bash
cd /Users/dongj/dev/논문_사수_개발중/.claude/worktrees/provider-neutral-llm/sasoo && npx vitest run 2>&1 | tail -20
```

`node_modules`가 없으면 이 worktree에서는 건너뛰고, 건너뛴 사실을 완료 보고에 명시한다.

- [ ] **Step 11: 병합을 커밋한다**

```bash
git add -A
git commit -m "$(cat <<'EOF'
merge: origin/main (v0.9.0, 3.7 Flash, 도입가 단가, Evidence Anchoring)

텍스트 충돌 11파일 20 hunk와 의미 충돌 4건을 해소했다. 해소 원칙은 브랜치의
구조(model_registry 경유, provider 디스패처)를 채택하고 main이 새로 얻은 기능을
그 구조 안으로 이식하는 것이다.

의미 충돌 4건:

1. FLASH_HQ + minimal. 앞선 커밋에서 레지스트리 값을 low로 올려 선제 해소했다.

2. max_output_tokens. main #53이 interactions_client.call_interaction에 추가한
   파라미터를 이 브랜치는 gemini_client로 옮긴 뒤였다. 디스패처를 채택하면서
   두 클라이언트 모두에 이식했다. openai_client 쪽은 테스트가 없어 조용히
   깨지는 자리였다 — analysis_routes가 recipe phase에서 24,000을 넘기므로
   provider=openai일 때 TypeError가 났을 것이다. 회귀 테스트를 붙였다.

3. 캐시 키. main의 _phase_cache_key(_CHAIN_CACHE_VERSION 무효화)와 이 브랜치의
   compute_input_hash(provider/model/effort 격리)는 상보적이다. 둘 다 살렸다.
   한쪽만 고르면 체인 버전 무효화나 공급사 격리가 사라진다.

4. 단가 폴백. main의 _rate에 도입가 스케줄이 있고 폴백은 Gemini였다. 폴백을
   _fallback_for로 바꿔 gpt-* 가 Luna 단가를 받게 했다. main 쪽만 채택하면
   미지의 gpt-* 가 Gemini 단가로 조용히 오산된다.

analysis_routes에서 main의 _STAGE_MAX_OUTPUT_TOKENS를 살렸다(recipe 폭주 2차
방어선, test_model_pins가 잠근다). _STAGE_THINKING과 _STAGE_MODELS는 레지스트리가
대체하므로 버렸다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: measure.py가 실패한 표 번호를 남기게 한다

**Files:**
- Modify: `sasoo/backend/tools/extraction_audit/measure.py`

**Interfaces:**
- Consumes: 없음 (독립적인 도구 변경)
- Produces: 측정 결과 JSON에 놓친 표·그림의 식별자 목록이 들어간다.

인수인계 문서가 최우선으로 분류한 항목이다. 결정 5의 미해결 2건(표 격자 복원 실패율 약 53%, `OptFor_RefractiveMCAO_optics`의 공급사 공통 누락 1건)이 전부 "실패한 표 번호가 기록되지 않고 스크래치가 삭제된다"는 이유로 진단이 막혀 있다.

- [ ] **Step 1: 현재 결과 조립부와 스크래치 삭제 지점을 읽는다**

```bash
cd /Users/dongj/dev/논문_사수_개발중/.claude/worktrees/provider-neutral-llm
grep -n 'matched\|missed\|exact\|shutil.rmtree\|TemporaryDirectory\|json.dump' sasoo/backend/tools/extraction_audit/measure.py
```

정확일치 판정이 어디서 나는지, 결과 dict의 스키마가 무엇인지, 스크래치를 어디서 지우는지 세 자리를 찾는다.

- [ ] **Step 2: 실패 항목 목록을 결과에 담는다**

정확일치 비교가 집합 연산이면 차집합을 그대로 기록한다. 참조 쪽에만 있는 것(놓침)과 산출 쪽에만 있는 것(허위)을 구분해 남긴다 — 둘을 합치면 어느 방향의 실패인지 알 수 없다.

```python
        "missed": sorted(expected - produced),   # 참조에 있는데 못 뽑은 것
        "spurious": sorted(produced - expected), # 참조에 없는데 뽑은 것
```

변수 이름은 그 파일의 기존 관용구에 맞춘다. 비교가 집합이 아니라 캡션 문자열 정규화 후 매칭이면, 매칭 루프에서 실패한 항목의 식별자(표 번호, 그림 번호)를 리스트에 모아 같은 두 키로 남긴다.

- [ ] **Step 3: 자기 점검을 붙인다**

`measure.py`는 pytest 대상이 아닌 도구이므로 프레임워크 없는 자기 점검 하나만 둔다. 이미 `__main__` 블록이 있으면 그 위에, 없으면 파일 끝에 붙인다.

```python
def _selfcheck_missed_reporting():
    """놓침과 허위가 뒤섞이지 않는지. 이 두 키가 결정 5의 진단 근거다."""
    expected, produced = {"Table 1", "Table 2", "Table 3"}, {"Table 1", "Table 4"}
    missed, spurious = sorted(expected - produced), sorted(produced - expected)
    assert missed == ["Table 2", "Table 3"], missed
    assert spurious == ["Table 4"], spurious
```

`--selfcheck` 플래그나 `__main__`에서 호출하도록 배선한다. 실제 비교 로직을 이 함수가 호출하도록 만들 수 있으면 그렇게 한다(중복 구현이면 점검 가치가 떨어진다).

- [ ] **Step 4: 자기 점검을 돌리고 파싱을 확인한다**

```bash
cd sasoo/backend && /Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
from tools.extraction_audit.measure import _selfcheck_missed_reporting
_selfcheck_missed_reporting(); print('selfcheck ok')
"
/Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python -m pytest -q 2>&1 | tail -5
```

기대: `selfcheck ok`, 그리고 전체 테스트에 회귀 없음.

- [ ] **Step 5: 커밋한다**

```bash
git add sasoo/backend/tools/extraction_audit/measure.py
git commit -m "$(cat <<'EOF'
feat(audit): measure.py가 놓친 항목과 허위 항목을 결과에 남긴다

결정 5의 미해결 2건(표 격자 복원 실패율 약 53%, OptFor_RefractiveMCAO_optics의
공급사 공통 누락 1건)이 전부 이것 때문에 진단이 막혀 있었다. 정확일치 개수만
남기고 어느 표를 놓쳤는지는 기록하지 않은 채 스크래치를 지웠다.

놓침(missed)과 허위(spurious)를 나눠 남긴다. 합치면 실패의 방향을 알 수 없다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: 릴리스 노트 문구 초안

**Files:**
- Create: `docs/superpowers/plans/2026-08-22-release-note-provider-switch.md`

**Interfaces:**
- Consumes: Task 2의 병합 결과(어떤 동작이 실제로 바뀌었는지)
- Produces: 릴리스 노트에 붙일 한국어 문구. 사용자가 게시 시점에 편집해 쓴다.

`ai_provider=openai`이고 Gemini와 OpenAI 키를 모두 가진 기존 사용자는 페이지 파싱이 Gemini에서 Luna로 **바뀐다.** 닫힌 경로를 여는 것이 아니라 동작하던 경로를 교체하는 것이므로 안내가 필요하다.

- [ ] **Step 1: 실제 전환 조건을 코드에서 확인한다**

```bash
cd /Users/dongj/dev/논문_사수_개발중/.claude/worktrees/provider-neutral-llm
grep -n 'key_env_for\|ensure_visual_artifacts\|ai_provider' sasoo/backend/services/odl_parser.py | head -20
```

"두 키를 모두 가진 경우"와 "OpenAI 키만 가진 경우"에 각각 어떤 경로가 선택되는지 확인해 문구에 정확히 반영한다. 추측으로 쓰지 않는다.

- [ ] **Step 2: 문구를 작성한다**

세 부류의 사용자에게 각각 무엇이 달라지는지 쓴다. 확인한 코드 동작만 쓰고, 측정하지 않은 정확도·비용 비교는 넣지 않는다(결정 3의 측정이 아직 없다).

```markdown
# 릴리스 노트 문구 초안 — 페이지 비전 파싱의 공급사 중립화

## 바뀐 것

PDF 페이지의 "AI 판독"이 이제 설정의 AI 공급사(`ai_provider`)를 따릅니다.
이전에는 공급사 설정과 무관하게 Gemini만 썼습니다.

| 사용자 | 이전 | 이후 |
|---|---|---|
| Gemini 키만 있음 | Gemini로 판독 | 그대로 |
| OpenAI 키만 있음 | AI 판독을 쓸 수 없어 로컬 파싱으로 떨어짐 | OpenAI로 판독 |
| 두 키 모두 있고 공급사를 OpenAI로 설정 | Gemini로 판독 | **OpenAI로 판독** |

## 확인해 주실 것

세 번째 줄에 해당하시면 판독 경로가 실제로 바뀝니다. Gemini 판독을 계속 쓰시려면
설정에서 AI 공급사를 Gemini로 돌려 주세요. 기존에 저장된 판독 결과는 그대로
유지되며 다시 판독하지 않습니다.
```

문구는 확인한 동작에 맞춰 고친다. 특히 "기존에 저장된 판독 결과는 그대로 유지"는 매니페스트 엔진 문자열 `"gemini"`의 값 공간을 바꾸지 않았다는 계약에서 나오는 결론이므로, 승격·멱등 판정 코드를 확인해 사실인지 검증한 뒤 남긴다.

- [ ] **Step 3: 커밋한다**

```bash
git add docs/superpowers/plans/2026-08-22-release-note-provider-switch.md
git commit -m "$(cat <<'EOF'
docs: 릴리스 노트 문구 초안 — 페이지 판독 공급사 전환 안내

ai_provider=openai이고 두 키를 모두 가진 사용자는 페이지 판독이 Gemini에서
Luna로 바뀐다. 닫힌 경로를 여는 것이 아니라 동작하던 경로를 교체하는 것이라
안내가 필요하다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: 통합 후 재측정 (사용자 승인 게이트)

**Files:**
- Modify: `docs/superpowers/plans/2026-08-21-openai-vision-audit-record.md` (통합 후 수치 추가)

**Interfaces:**
- Consumes: Task 2의 병합 결과와 Task 3의 실패 항목 기록
- Produces: 3.7 Flash + 도입가 단가 기준의 12편 정확일치와 비용. 이전 실측(3.6 + 표준가)과 대조표.

**이 Task는 실제 API를 호출해 비용이 발생한다. 실행 전에 반드시 멈추고, 예상 호출 수와 비용을 계산해 사용자 승인을 받는다.** 결정 3에서 사용자가 고른 범위는 최소(12편 × 1회 × 2공급사)이고 `--repeat`는 쓰지 않는다.

- [ ] **Step 1: 예상 호출 수와 비용을 계산해 보고한다**

이전 실측(`docs/superpowers/plans/2026-08-21-openai-vision-audit-record.md`)의 논문별 페이지 수와 토큰 사용량을 근거로 계산한다. 세 가지가 이전과 달라졌으므로 그대로 쓰면 틀린다.

1. Gemini 쪽 모델이 3.6에서 3.7로 바뀌었다(고시 단가는 동일).
2. flash 계열에 도입가가 적용되어 단가가 절반이다(`INTRO_PRICING`, 2026-12-31까지).
3. Task 1이 `pdf_parse`의 effort를 `minimal`에서 `low`로 올렸으므로 **Gemini 쪽 thinking 토큰이 늘어난다.** 이전 실측의 thinking 토큰 수로는 하한만 알 수 있다.

보고 형식: 논문 수, 총 페이지 수, 공급사별 예상 호출 수, 공급사별 예상 비용과 그 근거(어느 실측치를 어떻게 환산했는지), 합계. 3번 때문에 Gemini 쪽은 범위로 제시한다.

- [ ] **Step 2: 승인을 받은 뒤에만 측정을 실행한다**

승인 없이 실행하지 않는다. 승인 후:

```bash
cd sasoo/backend
/Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python -m tools.extraction_audit.measure --reparse gemini
/Users/dongj/dev/논문_사수_개발중/sasoo/backend/.venv/bin/python -m tools.extraction_audit.measure --reparse openai
```

정확한 호출 형태는 `measure.py`의 인자 파서를 읽어 확인한다. `--reparse`와 `--lane deterministic`은 상호 배타이므로 함께 주지 않는다.

- [ ] **Step 3: 결과를 실측 기록에 추가한다**

이전 수치를 지우지 않고, 통합 후 수치를 새 절로 덧붙인다. 대조표에 모델과 단가 기준일을 명시한다 — 기준이 바뀐 두 측정을 나란히 두면서 그 사실을 적지 않으면 나중에 잘못 비교된다.

`--repeat`를 쓰지 않았으므로 노이즈 바닥이 없다는 사실을 한계로 명시한다. 표 1편 차이(결정 4)를 수용한 근거도 함께 적는다: 영향받는 사용자의 변경 전 상태는 Gemini 판독이 아니라 로컬 ODL 파싱이므로, 판단 기준은 "OpenAI가 ODL보다 나은가"다.

- [ ] **Step 4: 커밋한다**

```bash
git add docs/superpowers/plans/2026-08-21-openai-vision-audit-record.md
git commit -m "docs(audit): 3.7 Flash + 도입가 단가 기준 통합 후 재측정 기록"
```

---

## 남기는 항목 (이번 패스 범위 밖)

별도 이슈로 세운다. 이번 패스에서 손대지 않는다.

1. `_run_convert` 폴백에서 `provider=resolved`로 배선. 현재 로그와 사용자 메시지의 provider가 어긋날 수 있다(env 레버 없이는 도달 불가).
2. `measure.py`의 `requested_mode="fast"`를 프로덕션 정규화값 `"java"`로.
3. 표 격자 복원 실패율 약 53%(선재 문제). Task 3의 실패 항목 기록이 진단 입구를 연다.
4. `OptFor_RefractiveMCAO_optics`의 표 1건 공급사 공통 누락. 원인 미확인.
5. Terra 승격 검토. 이번 측정은 Luna(effort low)만 한다. Terra는 Luna 입력 단가의 10배다.
6. `explain_odl_failure` 두 호출부에 provider 전달(async 라우트라 가능).
7. `--reparse`와 `--lane deterministic` 상호 배타 처리.
8. OpenAI 키만으로 앱을 띄워 업로드부터 완주까지 하는 수동 확인. 아직 한 적이 없다.
9. `--repeat` 노이즈 바닥, box_2d IoU 12편 재확인, Luna 격자 복원 비용, PyInstaller 번들 확인.
