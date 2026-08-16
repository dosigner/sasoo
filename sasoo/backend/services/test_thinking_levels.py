"""MODEL_FLASH_HQ 계열 호출은 그 모델이 받는 thinking_level만 써야 한다.

Gemini 3.7 Flash는 minimal을 거부한다. 실호출로 확인한 응답(2026-08-16):

    400 invalid_request: 'minimal' is not a supported thinking level for this
    model. Allowed values are: medium, low, high.

호출부가 대부분 try/except 안에 있어서 이 400은 예외로 튀지 않고 조용한 품질
저하로만 나타난다. 그래서 정적으로 잡는다. 모델을 갈 때마다 사람이 전 호출부를
다시 훑는 대신 이 테스트가 훑는다.

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
    """페이지 파서는 MODEL_VISUAL(=FLASH_HQ)로 부르면서 thinking을 변수로 넘긴다.

    변수라 위 AST 스캔에 안 걸리므로 기본값을 따로 잠근다. 환경변수로 덮을 수
    있는 값이라 기본값이 유일한 방어선이다.
    """
    from services import gemini_parser

    assert gemini_parser.MODEL_VISUAL in (models.MODEL_FLASH_HQ,)
    assert gemini_parser._THINKING_LEVEL in FLASH_HQ_SUPPORTED, (
        f"gemini_parser 기본 thinking_level={gemini_parser._THINKING_LEVEL!r}는 "
        f"{models.MODEL_FLASH_HQ}가 받지 않는다"
    )


def test_the_scan_actually_looks_at_files():
    # 스캔 대상이 비면 위 테스트가 공허하게 통과한다.
    assert len(list(_python_files())) > 20
