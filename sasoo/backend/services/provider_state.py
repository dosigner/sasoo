"""Sasoo - AI 공급사 상태.

ai_provider 하나가 분석·PDF파싱·그림생성을 모두 결정한다. 레거시 설정
image_provider는 삭제하지 않고 쓰기 전용 미러로 남긴다 — 이 값을 읽는 기존
코드(api/analysis_routes.py의 preferred_provider)를 한 번에 걷어내면 회귀
위험이 크기 때문이다.

읽기 권위는 항상 ai_provider에 있다. 레거시 키에 직접 write 하지 말고 반드시
mirror_legacy_settings()를 거쳐라.

pdf_visual_engine은 미러 대상이 아니다. 값 도메인이 {gemini, odl}이고, 이건
공급사가 아니라 "LLM 비전으로 판독할까 / 로컬 Java 파서로 뽑을까"라는 독립된
선택이다. gemini는 공급사 이름이 아니라 LLM 비전 경로를 가리키는 레거시
이름이다. 공급사 값을 넣으면 api/settings.py의 검증이 400으로 거부한다.
"""

VALID_PROVIDERS = ("openai", "gemini")

# ai_provider를 따라 함께 갱신할 레거시 설정 키. 값 도메인이 VALID_PROVIDERS와
# 같은 것만 넣을 수 있다.
_MIRRORED_KEYS = ("image_provider",)


def mirror_legacy_settings(provider: str) -> dict[str, str]:
    """ai_provider와 lockstep으로 갱신할 레거시 설정 값을 만든다.

    Raises:
        ValueError: 알 수 없는 provider.
    """
    if provider not in VALID_PROVIDERS:
        raise ValueError(f"unknown provider: {provider!r}")
    return {key: provider for key in _MIRRORED_KEYS}


def effective_provider(
    stored: str | None,
    *,
    has_openai: bool,
    has_gemini: bool,
) -> str | None:
    """저장된 선택을 키 가용성으로 보정한다.

    규칙은 하나뿐이다 — 신규·기존 설치를 구분하지 않는다:
        저장된 선택의 키가 있으면      -> 그대로
        없고 다른 쪽 키가 있으면       -> 그쪽으로 자동 전환
        둘 다 없으면                   -> None (기능 잠김)

    저장값이 없거나 알 수 없는 값이면 미설정으로 보고, 키가 둘 다 있을 때
    openai를 기본으로 한다.
    """
    available = {"openai": has_openai, "gemini": has_gemini}

    if stored in VALID_PROVIDERS and available[stored]:
        return stored

    for candidate in VALID_PROVIDERS:  # 튜플 순서가 곧 우선순위다
        if available[candidate]:
            return candidate
    return None


def provider_switched(stored: str | None, effective: str | None) -> bool:
    """사용자에게 자동 전환을 알려야 하는 상황인지.

    키가 하나도 없어 None이 된 것은 전환이 아니라 잠김이므로 제외한다.
    저장값이 애초에 없었던 경우도 알릴 것이 없다.
    """
    if effective is None or stored not in VALID_PROVIDERS:
        return False
    return stored != effective
