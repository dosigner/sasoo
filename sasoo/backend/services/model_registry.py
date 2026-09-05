"""Sasoo - provider x role 모델 레지스트리.

phase가 어떤 모델을 어느 사고량으로 돌릴지 한곳에서 정한다.
services/models.py가 "무엇이 있는가"라면 여기는 "언제 무엇을 쓰는가"다.

effort는 provider 중립 인자다. Gemini 경로는 thinking_level로, OpenAI 경로는
reasoning.effort로 전달된다. Gemini 열은 기존 실동작(각 호출부의 model/
thinking_level 실값)의 이식이므로 바꾸면 동작 변경이다. 실값 확인 결과
(2026-08-05, grep 재확인):
  - naming: naming_service.py의 세 호출부(generate_folder_name,
    generate_figure_names, generate_paperbanana_name) 모두 thinking_level=
    "minimal" — None이 아니다.
  - viz_image_plan: viz/figure_gen.py:_plan_description이 thinking_level=
    "medium" — None이 아니다.
  - mermaid, chat: 실호출부(analysis_routes.py의 get_mermaid/repair_mermaid/
    chat 엔드포인트)가 thinking_level 인자를 아예 넘기지 않으므로 None이 맞다.
    (mermaid는 2026-09-06에 high로 올렸다. 아래 레지스트리 주석 참조.)

OpenAI 열 원칙(스펙 개정 1 R3/R4): 모델은 Luna 하나, effort만 변주.
deep_dive는 high까지(xhigh 금지). screening·리졸버·naming은 최저 사고량 —
Task 0 실측(2026-08-05)에서 minimal 미지원 확정 — OpenAI 최저 effort는 low.
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
    MODEL_VISUAL,
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
        # 페이지 전체 비전 파싱(gemini_parser). 그림 판독 단계인 "visual"과 별개 role이다.
        # FLASH_HQ(3.7/3.8 Flash)는 minimal을 400으로 거부한다 — low가 이 모델의
        # 최저치다(ai.google.dev, 2026-08-16 확인). main #51이 같은 이유로
        # figure/table/subfigure 리졸버와 페이지 파서를 low로 올렸다.
        # minimal이 남아 있는 곳은 flash-lite를 쓰는 screening과 naming뿐이다.
        # 잠금: services/test_model_registry.py
        "pdf_parse": ModelChoice(MODEL_VISUAL, "low"),
        "citation": ModelChoice(MODEL_FLASH_HQ, "low"),
        "recipe": ModelChoice(MODEL_FLASH_HQ, "medium"),
        "deep_dive": ModelChoice(MODEL_FLASH_HQ, "high"),
        "viz_planning": ModelChoice(MODEL_FLASH_HQ, "medium"),
        # mermaid: 2026-09-06 사용자 결정으로 None(기본 medium)에서 high로. 다이어그램
        # 코드는 문법이 틀리면 렌더링이 통째로 실패해 repair 호출이 따라붙는다. 실측 없음,
        # 되돌리기 쉬움. chat은 None 그대로(DEC-021 후속).
        "mermaid": ModelChoice(MODEL_FLASH_HQ, "high"),
        "chat": ModelChoice(MODEL_FLASH_HQ, None),
        "figure_explain": ModelChoice(MODEL_FLASH_HQ, "high"),
        "figure_resolver": ModelChoice(MODEL_FLASH_HQ, "low"),
        "table_resolver": ModelChoice(MODEL_FLASH_HQ, "low"),
        "subfigure": ModelChoice(MODEL_FLASH_HQ, "low"),
        "naming": ModelChoice(MODEL_FLASH_LITE, "minimal"),
        "viz_image_plan": ModelChoice(MODEL_PRO, "medium"),
        "image": ModelChoice(MODEL_IMAGE, None),
    },
    "openai": {
        "screening": ModelChoice(MODEL_LUNA, "low"),
        "visual": ModelChoice(MODEL_LUNA, "low"),
        # OpenAI는 minimal 미지원(플랜 Task 0 실측) — 최저치가 low다.
        # box_2d 규약 준수는 2026-08-21 실측으로 확인(tools/openai_vision_spike.py).
        "pdf_parse": ModelChoice(MODEL_LUNA, "low"),
        "citation": ModelChoice(MODEL_LUNA, "low"),
        "recipe": ModelChoice(MODEL_LUNA, "medium"),
        "deep_dive": ModelChoice(MODEL_LUNA, "high"),
        "viz_planning": ModelChoice(MODEL_LUNA, "medium"),
        "mermaid": ModelChoice(MODEL_LUNA, "high"),  # gemini 열과 같은 의도(2026-09-06)
        "chat": ModelChoice(MODEL_LUNA, "low"),
        "figure_explain": ModelChoice(MODEL_LUNA, "medium"),
        "figure_resolver": ModelChoice(MODEL_LUNA, "low"),
        "table_resolver": ModelChoice(MODEL_LUNA, "low"),
        "subfigure": ModelChoice(MODEL_LUNA, "low"),
        "naming": ModelChoice(MODEL_LUNA, "low"),
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


# deep_dive만 provider를 따로 고른다(DEC-019). Gemini 3.7 Flash는 이 role에서만
# 확률적으로 폭주해 출력 상한에 걸리고, 그때 required가 아닌 부가 필드 6개
# (to_be, novelty_assessment, comparison_to_prior_work, suggested_improvements,
# follow_up_questions, practical_applications)가 오류 없이 사라진다 — 상한은 비용만
# 막고 이 손실은 못 막는다. 프롬프트 정형 문구 제거로는 4/4를 2/4로 낮추는 데
# 그쳤고, Luna는 같은 조건에서 누적 42/42 무폭주였다.
# 근거: RESEARCH/2026-08-29-provider-chain-token-convergence.md 6장.
_ROLE_PROVIDER_OVERRIDE: dict[str, Provider] = {"deep_dive": "openai"}


async def provider_for_role(role: str) -> str:
    """role의 유효 provider. 오버라이드가 있고 그 키가 등록돼 있으면 그쪽을 쓴다.

    키가 없으면 조용히 기본 provider로 돌아간다 — deep_dive를 아예 못 돌리는 것보다
    폭주 위험을 안고 돌리는 편이 낫다. 지연 import 이유는 active_provider와 같다.
    """
    from api.settings import _get_all_settings, _resolve_active_provider

    settings = await _get_all_settings()
    base = _resolve_active_provider(settings, settings.get("ai_provider")) or "gemini"
    override = _ROLE_PROVIDER_OVERRIDE.get(role)
    if override and override != base and str(settings.get(f"{override}_api_key") or "").strip():
        return override
    return base


async def active_provider() -> str:
    """현재 유효 provider. 설정(ai_provider)을 키 가용성으로 보정한 값.

    api.settings의 _resolve_active_provider(기존 함수, 재구현하지 않음)를
    그대로 호출한다. None(둘 다 키 없음)이면 "gemini"를 돌려준다 — 이 경우
    어차피 분석 /run이 키 사전 점검에서 거절하므로 여기서 죽지 않는 것이 낫다.

    함수 내부에서 지연 import하는 이유: api.settings가 임포트 시점에 무거운
    라우터 의존성을 끌고 오고, model_registry는 services 계층이라 api 계층을
    모듈 최상단에서 import하면 순환 import가 된다.
    """
    from api.settings import _get_all_settings, _resolve_active_provider

    settings = await _get_all_settings()
    resolved = _resolve_active_provider(settings, settings.get("ai_provider"))
    return resolved or "gemini"
