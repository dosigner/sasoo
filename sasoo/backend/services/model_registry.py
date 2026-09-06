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
        # Phase 5 종합 스테이지, effort는 3편 게이트에서 high와 비교 후 확정(스펙 §5.2)
        "synthesis": ModelChoice(MODEL_FLASH_HQ, "medium"),
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
        # Phase 5 종합 스테이지, effort는 3편 게이트에서 high와 비교 후 확정(스펙 §5.2)
        "synthesis": ModelChoice(MODEL_LUNA, "medium"),
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


# role별 provider 오버라이드. 지금은 비어 있다(DEC-022, 2026-09-06).
# 이력: DEC-019(2026-08-29)가 deep_dive를 OpenAI Luna로 보냈다. Gemini 3.7 Flash가 이 role에서만
# 확률적으로 폭주해 출력 상한에 걸리고, 그때 required가 아닌 부가 필드가 오류 없이 사라졌기
# 때문이다(프롬프트 정형 문구 제거로는 4/4→2/4, Luna는 42/42 무폭주.
# RESEARCH/2026-08-29-provider-chain-token-convergence.md 6장). 대가는 deep_dive 지연 약 90초였다.
# 해제 근거: FLASH_HQ가 3.8 Flash로 올라간 뒤 같은 VLA 6편을 같은 체인·상한으로 재실행해 폭주 0/6,
# 14/14 필드, 출력 2,805~3,444(상한 16k의 18~22%), 16~23초(RESEARCH/2026-09-06-vla6-gemini-3-8.md).
# 기제(provider_for_role, analysis_routes의 체인 갈림 배선)는 남긴다 — 폭주가 재발하면 항목 하나로
# 되돌릴 수 있다. 상한 16k와 salvage_truncated_json은 그대로라 재발 시 손해는 유한하다.
# 잠금: services/test_model_registry.py::TestProviderForRole
_ROLE_PROVIDER_OVERRIDE: dict[str, Provider] = {}


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
