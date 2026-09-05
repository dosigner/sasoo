"""MODEL_FLASH_HQ 계열 호출은 그 모델이 받는 thinking_level만 써야 한다.

Gemini 3.7 Flash와 3.8 Flash는 minimal을 거부한다. 실호출로 확인한 응답(3.7은
2026-08-16, 3.8은 2026-09-05, 메시지가 글자까지 같다):

    400 invalid_request: 'minimal' is not a supported thinking level for this
    model. Allowed values are: medium, low, high.

호출부가 대부분 try/except 안에 있어서 이 400은 예외로 튀지 않고 조용한 품질
저하로만 나타난다.

이 파일의 AST 스캔이 잡는 것은 `model=<FLASH_HQ 별칭 리터럴 이름>` 형태
(ast.Name)로 쓴 호출뿐이다. 이 브랜치는 호출부를 거의 전부 model_registry
경유 `model=choice.model`(ast.Name이 아니라 ast.Attribute)로 옮겼기 때문에,
지금 이 스캔이 실제로 걸리는 프로덕션 호출은 0건이다. 걸리는 두 곳
(tools/extraction_audit/vlm_probe.py의 리터럴 model=MODEL_FLASH_HQ 호출
두 건)은 감사 도구이고 이미 low다. 즉 이 스캔은 남아 있는 리터럴 호출부만
지키는 좁은 안전망이고, "모델을 갈 때마다 전 호출부를 훑는다"는 보장은 하지
않는다.

실질 방어는 값의 출처인 레지스트리 자체를 보는 두 테스트가 한다 — provider별로
resolve()가 실제로 내주는 (model, effort)를 확인하므로 호출부가 ast.Name이든
ast.Attribute든 가리지 않는다.

  - services/test_model_registry.py::test_flash_hq_roles_never_use_minimal_effort
  - api/test_analysis_routes.py::StageThinkingLevelTests

minimal 자체는 여전히 유효하다. flash-lite를 쓰는 screening과 파일명 생성은
그대로 minimal을 쓴다. 금지되는 것은 FLASH_HQ와 minimal의 조합뿐이다.
"""

import ast
from pathlib import Path

import services.models as models

FLASH_HQ_SUPPORTED = frozenset({"low", "medium", "high"})

BACKEND = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".venv", "library", "outputs", "__pycache__", ".git", "node_modules"}


def _flash_hq_aliases() -> frozenset[str]:
    """models.py에서 MODEL_FLASH_HQ와 같은 문자열을 가리키는 상수 이름 전부."""
    target = models.MODEL_FLASH_HQ
    return frozenset(
        name
        for name, value in vars(models).items()
        if name.startswith("MODEL_") and isinstance(value, str) and value == target
    )


def _python_files():
    for path in BACKEND.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _violations():
    aliases = _flash_hq_aliases()
    found = []
    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            model, thinking = kw.get("model"), kw.get("thinking_level")
            if not isinstance(model, ast.Name) or model.id not in aliases:
                continue
            if isinstance(thinking, ast.Constant) and isinstance(thinking.value, str):
                if thinking.value not in FLASH_HQ_SUPPORTED:
                    found.append(
                        f"{path.relative_to(BACKEND)}:{node.lineno} "
                        f"model={model.id} thinking_level={thinking.value!r}"
                    )
    return sorted(found)


def test_no_flash_hq_call_uses_an_unsupported_thinking_level():
    bad = _violations()
    assert bad == [], "MODEL_FLASH_HQ가 거부하는 thinking_level:\n  " + "\n  ".join(bad)


def test_gemini_parser_default_thinking_level_is_supported():
    """페이지 파서는 모델과 effort를 변수로 넘긴다(model_registry의 pdf_parse role).

    변수라 위 AST 스캔에 안 걸리므로 실효 기본값을 따로 잠근다. 환경변수
    SASOO_GEMINI_PARSER_THINKING으로 덮을 수 있는 값이라 기본값이 유일한 방어선이다.

    옛 형태는 gemini_parser._THINKING_LEVEL 상수(기본 "low")를 봤다. 이 브랜치는
    값의 출처를 레지스트리로 옮기고 그 상수를 _THINKING_OVERRIDE(기본 ""=오버라이드
    없음)로 바꿨으므로, 여기서도 오버라이드가 없을 때 실제로 쓰이는 값을 본다.
    """
    from services import gemini_parser
    from services.model_registry import resolve

    assert gemini_parser._THINKING_OVERRIDE == "", (
        "테스트 환경에 SASOO_GEMINI_PARSER_THINKING이 설정돼 기본값을 못 본다"
    )
    choice = resolve("pdf_parse", "gemini")
    assert choice.model == models.MODEL_FLASH_HQ
    effective = gemini_parser._THINKING_OVERRIDE or choice.effort
    assert effective in FLASH_HQ_SUPPORTED, (
        f"페이지 파서 실효 effort={effective!r}는 {models.MODEL_FLASH_HQ}가 받지 않는다"
    )


def test_the_scan_actually_looks_at_files():
    # 스캔 대상 파일 수만 확인한다 — 스캔이 실제로 하나 이상의 model= 호출을
    # 매치하는지는 보지 않으므로, 매치 0건(현재 프로덕션 상태)이어도 이 테스트는 통과한다.
    assert len(list(_python_files())) > 20
